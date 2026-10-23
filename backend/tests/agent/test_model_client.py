from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from app.agent.model_client import OpenAICompatibleModelClient, ProviderConfig
from app.contracts import ProviderError
from openai import APIStatusError, APITimeoutError


class _FakeCompletions:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _FakeOpenAI:
    def __init__(self, outcomes: list[Any]) -> None:
        self.completions = _FakeCompletions(outcomes)
        self.chat = SimpleNamespace(completions=self.completions)


def _local_config() -> ProviderConfig:
    return ProviderConfig(
        name="local",
        model="gemma-4-26b-a4b-awq",
        base_url="http://127.0.0.1:8040/v1",
        timeout_seconds=120,
        temperature=0.2,
        top_p=0.95,
        top_k=64,
        max_tokens=2048,
    )


def _deepseek_config() -> ProviderConfig:
    return ProviderConfig(
        name="deepseek",
        model="deepseek-flash",
        base_url="https://api.deepseek.com",
        timeout_seconds=45,
        temperature=0,
        max_tokens=1024,
        disable_thinking=True,
        requires_key=True,
    )


def _client(
    outcomes: list[Any], config: ProviderConfig | None = None
) -> tuple[OpenAICompatibleModelClient, _FakeOpenAI]:
    fake = _FakeOpenAI(outcomes)
    client = OpenAICompatibleModelClient(config or _local_config(), client=fake)  # type: ignore[arg-type]
    return client, fake


def _response(
    content: str | None = "hello",
    *,
    tool_calls: list[Any] | None = None,
) -> Any:
    message = SimpleNamespace(content=content, tool_calls=tool_calls or [])
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://example.invalid/chat/completions")


async def test_local_request_uses_gemma_sampling_and_no_deepseek_thinking() -> None:
    client, fake = _client([_response("hi")])
    tools = [
        {
            "type": "function",
            "function": {
                "name": "search_knowledge",
                "description": "search",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]

    response = await client.complete(messages=[], tools=tools, tool_choice="auto")

    assert response.content == "hi"
    call = fake.completions.calls[0]
    assert call["model"] == "gemma-4-26b-a4b-awq"
    assert call["temperature"] == 0.2
    assert call["top_p"] == 0.95
    assert call["max_tokens"] == 2048
    assert call["extra_body"] == {"top_k": 64}
    assert call["tools"] == tools
    assert call["tool_choice"] == "auto"


async def test_deepseek_request_keeps_bounded_options_and_thinking_disabled() -> None:
    client, fake = _client([_response("hi")], _deepseek_config())

    await client.complete(messages=[], tools=[], tool_choice="auto")

    call = fake.completions.calls[0]
    assert call["model"] == "deepseek-flash"
    assert call["temperature"] == 0
    assert call["max_tokens"] == 1024
    assert call["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "top_p" not in call


async def test_complete_sanitizes_internal_keys() -> None:
    client, fake = _client([_response("hi")])
    messages = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "search_knowledge", "arguments": "{}"},
                    "_cp_nested": "drop me",
                }
            ],
            "_cp_message_id": "assistant-1",
        },
        {"role": "tool", "tool_call_id": "call-1", "content": "{}", "_cp_extra": 1},
    ]

    await client.complete(messages=messages, tools=[], tool_choice="auto")

    call = fake.completions.calls[0]
    assert "_cp_" not in json.dumps(call["messages"])
    assert messages[0]["_cp_message_id"] == "assistant-1"


async def test_complete_parses_tool_calls() -> None:
    tool_call = SimpleNamespace(
        id="call-9",
        function=SimpleNamespace(name="update_booking_draft", arguments='{"notes":"x"}'),
    )
    client, _fake = _client([_response(None, tool_calls=[tool_call])])

    response = await client.complete(messages=[], tools=[], tool_choice="auto")

    assert response.content is None
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].id == "call-9"
    assert response.tool_calls[0].name == "update_booking_draft"
    assert response.tool_calls[0].arguments == '{"notes":"x"}'


async def test_timeout_is_retried_once() -> None:
    client, fake = _client([APITimeoutError(_request()), _response("recovered")])

    response = await client.complete(messages=[], tools=[], tool_choice="auto")

    assert response.content == "recovered"
    assert len(fake.completions.calls) == 2


async def test_server_error_is_retried_once() -> None:
    request = _request()
    server_error = APIStatusError(
        "upstream failed", response=httpx.Response(503, request=request), body=None
    )
    client, fake = _client([server_error, _response("recovered")])

    response = await client.complete(messages=[], tools=[], tool_choice="auto")

    assert response.content == "recovered"
    assert len(fake.completions.calls) == 2


async def test_client_error_is_not_retried_and_becomes_provider_error() -> None:
    request = _request()
    client_error = APIStatusError(
        "bad request", response=httpx.Response(400, request=request), body=None
    )
    client, fake = _client([client_error])

    with pytest.raises(ProviderError) as excinfo:
        await client.complete(messages=[], tools=[], tool_choice="auto")

    assert len(fake.completions.calls) == 1
    assert "bad request" not in str(excinfo.value)
    assert "temporarily unavailable" in str(excinfo.value)


async def test_unexpected_error_never_leaks_raw_message() -> None:
    client, _fake = _client([RuntimeError("secret-looking raw message")])

    with pytest.raises(ProviderError) as excinfo:
        await client.complete(messages=[], tools=[], tool_choice="auto")

    assert "secret-looking" not in str(excinfo.value)


async def test_raw_tool_schema_and_named_tool_choice_are_converted() -> None:
    client, fake = _client([_response("ok")])
    schema = {
        "name": "create_booking",
        "description": "create",
        "parameters": {"type": "object", "properties": {}},
    }

    await client.complete(
        messages=[{"role": "user", "content": "yes"}],
        tools=[schema],
        tool_choice="create_booking",
    )

    call = fake.completions.calls[0]
    assert call["tools"][0]["type"] == "function"
    assert call["tools"][0]["function"]["name"] == "create_booking"
    assert call["tool_choice"] == {
        "type": "function",
        "function": {"name": "create_booking"},
    }
