from __future__ import annotations

import pytest
from app.agent.model_client import build_model_router
from app.contracts import ProviderNotConfiguredError
from app.services.provider_settings import ProviderSettings
from app.settings import Settings


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        local_model_base_url="http://127.0.0.1:8040/v1",
        local_model_id="gemma-4-26b-a4b-awq",
        deepseek_model="deepseek-flash",
        deepseek_base_url="https://api.deepseek.com",
    )


def test_provider_settings_store_and_mask_the_key() -> None:
    providers = ProviderSettings()
    assert providers.configured() is False
    assert providers.masked_hint() is None

    providers.set_key("sk-test-abcdefghijklmnop")
    assert providers.configured() is True
    assert providers.get_key() == "sk-test-abcdefghijklmnop"
    assert providers.masked_hint() == "••••mnop"

    providers.clear()
    assert providers.configured() is False
    assert providers.get_key() == ""


def test_provider_settings_reject_empty_and_oversized_keys() -> None:
    providers = ProviderSettings()
    with pytest.raises(ValueError):
        providers.set_key("   ")
    with pytest.raises(ValueError):
        providers.set_key("x" * 513)


def test_router_reports_availability() -> None:
    providers = ProviderSettings()
    router = build_model_router(_settings(), providers)

    assert router.available("local") is True
    assert router.available("deepseek") is False

    providers.set_key("sk-test-key")
    assert router.available("deepseek") is True


async def test_router_rejects_deepseek_without_a_key() -> None:
    router = build_model_router(_settings(), ProviderSettings())

    with pytest.raises(ProviderNotConfiguredError):
        await router.complete(messages=[], tools=[], model="deepseek")


async def test_router_rejects_an_unknown_provider() -> None:
    router = build_model_router(_settings(), ProviderSettings())

    with pytest.raises(ProviderNotConfiguredError):
        await router.complete(messages=[], tools=[], model="other")
