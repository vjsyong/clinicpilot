from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from app.agent.model_client import DeepSeekModelClient
from app.contracts import ProviderError
from app.settings import Settings
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


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        deepseek_api_key="test-key",
        deepseek_model="deepseek-flash",
        deepseek_base_url="https://example.invalid",
        deepseek_timeout_seconds=5,
    )


def _response(
    content: str | None = "hello",
    *,
    tool_calls: list[Any] | None = None,
) -> Any:
    message = SimpleNamespace(content=content, tool_calls=tool_calls or [])
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://example.invalid/chat/completions")


async def test_complete_sanitizes_internal_keys_and_sets_bounded_options() -> None:
    fake = _FakeOpenAI([_response("hi")])
    client = DeepSeekModelClient(_settings(), client=fake)  # type: ignore[arg-type]
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

    response = await client.complete(messages=messages, tools=tools, tool_choice="auto")

    assert response.content == "hi"
    call = fake.completions.calls[0]
    assert call["model"] == "deepseek-flash"
    assert call["temperature"] == 0
    assert 0 < call["max_tokens"] <= 4096
    assert call["extra_body"] == {"thinking": {"type": "disabled"}}
    assert call["tools"] == tools
    assert call["tool_choice"] == "auto"
    assert "_cp_" not in json.dumps(call["messages"])
    assert messages[0]["_cp_message_id"] == "assistant-1"


async def test_complete_parses_tool_calls() -> None:
    tool_call = SimpleNamespace(
        id="call-9",
        function=SimpleNamespace(name="update_booking_draft", arguments='{"notes":"x"}'),
    )
    fake = _FakeOpenAI([_response(None, tool_calls=[tool_call])])
    client = DeepSeekModelClient(_settings(), client=fake)  # type: ignore[arg-type]

    response = await client.complete(messages=[], tools=[], tool_choice="auto")

    assert response.content is None
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].id == "call-9"
    assert response.tool_calls[0].name == "update_booking_draft"
    assert response.tool_calls[0].arguments == '{"notes":"x"}'


async def test_timeout_is_retried_once() -> None:
    fake = _FakeOpenAI([APITimeoutError(_request()), _response("recovered")])
    client = DeepSeekModelClient(_settings(), client=fake)  # type: ignore[arg-type]

    response = await client.complete(messages=[], tools=[], tool_choice="auto")

    assert response.content == "recovered"
    assert len(fake.completions.calls) == 2


async def test_server_error_is_retried_once() -> None:
    request = _request()
    server_error = APIStatusError(
        "upstream failed", response=httpx.Response(503, request=request), body=None
    )
    fake = _FakeOpenAI([server_error, _response("recovered")])
    client = DeepSeekModelClient(_settings(), client=fake)  # type: ignore[arg-type]

    response = await client.complete(messages=[], tools=[], tool_choice="auto")

    assert response.content == "recovered"
    assert len(fake.completions.calls) == 2


async def test_client_error_is_not_retried_and_becomes_provider_error() -> None:
    request = _request()
    client_error = APIStatusError(
        "bad request", response=httpx.Response(400, request=request), body=None
    )
    fake = _FakeOpenAI([client_error])
    client = DeepSeekModelClient(_settings(), client=fake)  # type: ignore[arg-type]

    with pytest.raises(ProviderError) as excinfo:
        await client.complete(messages=[], tools=[], tool_choice="auto")

    assert len(fake.completions.calls) == 1
    assert "bad request" not in str(excinfo.value)
    assert "temporarily unavailable" in str(excinfo.value)


async def test_unexpected_error_never_leaks_raw_message() -> None:
    fake = _FakeOpenAI([RuntimeError("secret-looking raw message")])
    client = DeepSeekModelClient(_settings(), client=fake)  # type: ignore[arg-type]

    with pytest.raises(ProviderError) as excinfo:
        await client.complete(messages=[], tools=[], tool_choice="auto")

    assert "secret-looking" not in str(excinfo.value)


async def test_raw_tool_schema_and_named_tool_choice_are_converted() -> None:
    fake = _FakeOpenAI([_response("ok")])
    client = DeepSeekModelClient(_settings(), client=fake)  # type: ignore[arg-type]
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
