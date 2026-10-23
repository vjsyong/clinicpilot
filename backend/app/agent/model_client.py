"""OpenAI-compatible chat-completion providers for ClinicPilot.

The local Gemma endpoint is the primary provider. DeepSeek is an optional
manual backup whose API key is supplied at runtime and kept in memory.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    OpenAIError,
)

from app.contracts import (
    ModelResponse,
    ModelToolCall,
    ModelUsage,
    ProviderError,
    ProviderNotConfiguredError,
)
from app.services.provider_settings import ProviderSettings
from app.settings import Settings

logger = logging.getLogger("clinicpilot.agent.model")

PROVIDER_SAFE_ERROR = "The assistant provider is temporarily unavailable. Please retry."
_LOCAL_PROVIDER = "local"
_DEEPSEEK_PROVIDER = "deepseek"
_INTERNAL_KEY_PREFIX = "_cp_"
_STANDARD_TOOL_CHOICES = frozenset({"auto", "none", "required"})


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    model: str
    base_url: str
    timeout_seconds: float
    temperature: float
    max_tokens: int
    top_p: float | None = None
    top_k: int | None = None
    disable_thinking: bool = False
    requires_key: bool = False
    extra_headers: dict[str, str] = field(default_factory=dict)


class OpenAICompatibleModelClient:
    """Thin, bounded adapter around one OpenAI-compatible chat endpoint."""

    def __init__(
        self,
        config: ProviderConfig,
        *,
        api_key: str = "unused",
        client: AsyncOpenAI | None = None,
    ) -> None:
        self._config = config
        self._owns_client = client is None
        self._client = client or AsyncOpenAI(
            base_url=config.base_url,
            api_key=api_key or "unused",
            timeout=config.timeout_seconds,
            default_headers=dict(config.extra_headers) or None,
        )

    @property
    def provider(self) -> str:
        return self._config.name

    async def complete(
        self,
        *,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
        tool_choice: str | dict[str, Any] = "auto",
        model: str | None = None,
    ) -> ModelResponse:
        sanitized = [_sanitize_message(message) for message in messages]
        definitions = _convert_tools(tools)
        choice = _convert_tool_choice(tool_choice)

        last_error: Exception | None = None
        for attempt in range(2):
            try:
                return await self._complete_once(sanitized, definitions, choice)
            except ProviderError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt == 0 and _is_retryable(exc):
                    logger.warning(
                        "%s request failed (%s); retrying once.",
                        self._config.name,
                        type(exc).__name__,
                    )
                    continue
                raise ProviderError(PROVIDER_SAFE_ERROR) from None
        # The loop either returns, raises, or retries exactly once.
        logger.warning(
            "%s request failed after retry (%s).",
            self._config.name,
            type(last_error).__name__ if last_error is not None else "unknown",
        )
        raise ProviderError(PROVIDER_SAFE_ERROR)

    async def stream_complete(
        self,
        *,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
        tool_choice: str | dict[str, Any] = "auto",
        model: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield content and completed tool calls as they arrive.

        Streaming is intentionally best-effort: once any text has been emitted
        the turn is not retried, because replaying partial prose would duplicate
        it. The application persists only the completed response.
        """
        sanitized = [_sanitize_message(message) for message in messages]
        definitions = _convert_tools(tools)
        choice = _convert_tool_choice(tool_choice)
        request = self._request(sanitized, definitions, choice)
        request["stream"] = True
        request["stream_options"] = {"include_usage": True}

        pending: dict[int, dict[str, str]] = {}
        usage: ModelUsage | None = None
        finish_reason: str | None = None
        response_model: str | None = None
        response_id: str | None = None
        try:
            stream = await self._client.chat.completions.create(**request)
            try:
                async for chunk in stream:
                    response_model = getattr(chunk, "model", None) or response_model
                    response_id = getattr(chunk, "id", None) or response_id
                    if getattr(chunk, "usage", None) is not None:
                        usage = _usage(
                            request["model"],
                            response_id,
                            response_model,
                            chunk.usage,
                            finish_reason,
                        )
                    if not chunk.choices:
                        continue
                    choice_delta = chunk.choices[0]
                    delta = choice_delta.delta
                    if delta.content:
                        yield {"type": "content", "text": delta.content}
                    for call in delta.tool_calls or []:
                        index = call.index if call.index is not None else 0
                        entry = pending.setdefault(index, {"id": "", "name": "", "arguments": ""})
                        if call.id:
                            entry["id"] = call.id
                        function = call.function
                        if function is not None:
                            if function.name:
                                entry["name"] = function.name
                            if function.arguments:
                                entry["arguments"] += function.arguments
                    if choice_delta.finish_reason:
                        finish_reason = choice_delta.finish_reason
                        yield {
                            "type": "done",
                            "finish_reason": choice_delta.finish_reason,
                        }
            finally:
                await stream.close()
        except ProviderError:
            raise
        except Exception as exc:
            logger.warning(
                "%s stream failed (%s).",
                self._config.name,
                type(exc).__name__,
            )
            raise ProviderError(PROVIDER_SAFE_ERROR) from None

        if usage is None:
            usage = ModelUsage(
                model=request["model"],
                response_model=response_model,
                response_id=response_id,
                finish_reason=finish_reason,
            )
        else:
            usage.finish_reason = finish_reason
        yield {"type": "usage", "usage": usage.model_dump(mode="json")}

        if pending:
            yield {
                "type": "tool_calls",
                "calls": [
                    ModelToolCall(
                        id=entry["id"] or f"tool_call_{index}",
                        name=entry["name"] or "unknown",
                        arguments=entry["arguments"] or "{}",
                    )
                    for index, entry in sorted(pending.items())
                ],
            }

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.close()

    def _request(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any],
    ) -> dict[str, Any]:
        extra_body: dict[str, Any] = {}
        if self._config.disable_thinking:
            extra_body["thinking"] = {"type": "disabled"}
        if self._config.top_k is not None:
            extra_body["top_k"] = self._config.top_k

        request: dict[str, Any] = {
            "model": self._config.model,
            "messages": messages,
            "temperature": self._config.temperature,
            "max_tokens": self._config.max_tokens,
        }
        if self._config.top_p is not None:
            request["top_p"] = self._config.top_p
        if extra_body:
            request["extra_body"] = extra_body
        if tools:
            request["tools"] = tools
            request["tool_choice"] = tool_choice
        return request

    async def _complete_once(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any],
    ) -> ModelResponse:
        request = self._request(messages, tools, tool_choice)

        response = await self._client.chat.completions.create(**request)
        if not response.choices:
            raise ProviderError(PROVIDER_SAFE_ERROR)
        message = response.choices[0].message
        calls: list[ModelToolCall] = []
        for index, call in enumerate(message.tool_calls or []):
            calls.append(
                ModelToolCall(
                    id=call.id or f"tool_call_{index}",
                    name=call.function.name,
                    arguments=call.function.arguments or "{}",
                )
            )
        return ModelResponse(
            content=message.content,
            tool_calls=calls,
            usage=_usage(
                request["model"],
                getattr(response, "id", None),
                getattr(response, "model", None),
                getattr(response, "usage", None),
                getattr(response.choices[0], "finish_reason", None),
            ),
        )


class ModelRouter:
    """Dispatch a turn to the selected provider without leaking credentials."""

    def __init__(
        self,
        *,
        local_config: ProviderConfig,
        deepseek_config: ProviderConfig,
        provider_settings: ProviderSettings,
    ) -> None:
        self._local_config = local_config
        self._deepseek_config = deepseek_config
        self._provider_settings = provider_settings
        self._local = OpenAICompatibleModelClient(local_config)
        self._deepseek: OpenAICompatibleModelClient | None = None
        self._deepseek_key = ""
        # A key change while another turn is streaming must not close a client
        # that is still in use. Retired clients are closed at shutdown.
        self._retired: list[OpenAICompatibleModelClient] = []

    async def complete(
        self,
        *,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
        tool_choice: str | dict[str, Any] = "auto",
        model: str = _LOCAL_PROVIDER,
    ) -> ModelResponse:
        client = await self._resolve(model)
        return await client.complete(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
        )

    async def stream_complete(
        self,
        *,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
        tool_choice: str | dict[str, Any] = "auto",
        model: str = _LOCAL_PROVIDER,
    ) -> AsyncIterator[dict[str, Any]]:
        client = await self._resolve(model)
        async for event in client.stream_complete(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
        ):
            yield event

    def available(self, model: str) -> bool:
        if model == _LOCAL_PROVIDER:
            return True
        if model == _DEEPSEEK_PROVIDER:
            return self._provider_settings.configured()
        return False

    async def aclose(self) -> None:
        await self._local.aclose()
        if self._deepseek is not None:
            await self._deepseek.aclose()
            self._deepseek = None
            self._deepseek_key = ""
        for client in self._retired:
            await client.aclose()
        self._retired.clear()

    async def _resolve(self, model: str) -> OpenAICompatibleModelClient:
        if model == _LOCAL_PROVIDER:
            return self._local
        if model != _DEEPSEEK_PROVIDER:
            raise ProviderNotConfiguredError("Unknown model provider.")
        return await self._deepseek_client()

    async def _deepseek_client(self) -> OpenAICompatibleModelClient:
        key = self._provider_settings.get_key()
        if not key:
            raise ProviderNotConfiguredError(
                "DeepSeek is not configured. Add an API key or use the local model."
            )
        if self._deepseek is None or key != self._deepseek_key:
            if self._deepseek is not None:
                self._retired.append(self._deepseek)
            self._deepseek = OpenAICompatibleModelClient(
                self._deepseek_config,
                api_key=key,
            )
            self._deepseek_key = key
        return self._deepseek


def build_model_router(settings: Settings, provider_settings: ProviderSettings) -> ModelRouter:
    return ModelRouter(
        local_config=ProviderConfig(
            name=_LOCAL_PROVIDER,
            model=settings.local_model_id,
            base_url=settings.local_model_base_url,
            timeout_seconds=settings.local_model_timeout_seconds,
            temperature=settings.local_model_temperature,
            top_p=settings.local_model_top_p,
            top_k=settings.local_model_top_k,
            max_tokens=settings.local_model_max_tokens,
        ),
        deepseek_config=ProviderConfig(
            name=_DEEPSEEK_PROVIDER,
            model=settings.deepseek_model,
            base_url=settings.deepseek_base_url,
            timeout_seconds=settings.deepseek_timeout_seconds,
            temperature=0,
            max_tokens=1024,
            disable_thinking=True,
            requires_key=True,
        ),
        provider_settings=provider_settings,
    )


def _sanitize_message(message: Mapping[str, Any]) -> dict[str, Any]:
    sanitized = _strip_internal(message)
    if not isinstance(sanitized, dict):  # pragma: no cover - defensive
        raise ProviderError(PROVIDER_SAFE_ERROR)
    return sanitized


def _strip_internal(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _strip_internal(item)
            for key, item in value.items()
            if not (isinstance(key, str) and key.startswith(_INTERNAL_KEY_PREFIX))
        }
    if isinstance(value, list):
        return [_strip_internal(item) for item in value]
    return value


def _convert_tools(tools: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, Mapping):
            raise ProviderError(PROVIDER_SAFE_ERROR)
        if tool.get("type") == "function" and isinstance(tool.get("function"), Mapping):
            converted.append(dict(tool))
            continue
        if isinstance(tool.get("name"), str) and isinstance(tool.get("parameters"), Mapping):
            converted.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": tool["parameters"],
                    },
                }
            )
            continue
        raise ProviderError(PROVIDER_SAFE_ERROR)
    return converted


def _convert_tool_choice(
    choice: str | dict[str, Any],
) -> str | dict[str, Any]:
    if isinstance(choice, str):
        if choice in _STANDARD_TOOL_CHOICES:
            return choice
        return {"type": "function", "function": {"name": choice}}
    if not isinstance(choice, Mapping):
        return "auto"
    if "type" in choice:
        return dict(choice)
    name = choice.get("name")
    if isinstance(name, str):
        return {"type": "function", "function": dict(choice)}
    return dict(choice)


def _is_retryable(exc: Exception) -> bool:
    if isinstance(
        exc,
        (TimeoutError, APITimeoutError, APIConnectionError, httpx.TimeoutException),
    ):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code >= 500
    if isinstance(exc, httpx.TransportError):
        return True
    return isinstance(exc, OpenAIError) and "timeout" in type(exc).__name__.lower()


def _usage(
    requested_model: str,
    response_id: str | None,
    response_model: str | None,
    usage: Any,
    finish_reason: str | None,
) -> ModelUsage:
    prompt_details = getattr(usage, "prompt_tokens_details", None) if usage else None
    completion_details = getattr(usage, "completion_tokens_details", None) if usage else None
    return ModelUsage(
        model=requested_model,
        response_model=response_model,
        response_id=response_id,
        prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0,
        completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0,
        cached_tokens=int(getattr(prompt_details, "cached_tokens", 0) or 0)
        if prompt_details
        else 0,
        reasoning_tokens=int(getattr(completion_details, "reasoning_tokens", 0) or 0)
        if completion_details
        else 0,
        total_tokens=int(getattr(usage, "total_tokens", 0) or 0) if usage else 0,
        finish_reason=finish_reason,
    )
