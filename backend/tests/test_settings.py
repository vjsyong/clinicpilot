from __future__ import annotations

import pytest
from app.settings import Settings

PRODUCTION_PREFIX = "/audit-generated-prefix-0123456789/"
PRODUCTION_KEY = "a" * 48


def _production(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "app_env": "production",
        "demo_path_prefix": PRODUCTION_PREFIX,
        "demo_password_hash": (
            "$argon2id$v=19$m=65536,t=3,p=4$r1k152euUT2GSIwfX5Cktw$"
            "QgbThqLxmaEXvxnVL8rb6NlxtzTiQqhISPruf0hUlk8"
        ),
        "internal_tool_key": PRODUCTION_KEY,
        "local_model_base_url": "http://192.168.1.148:8040/v1",
        "local_model_id": "gemma-4-26b-a4b-awq",
        "deepseek_api_key": "",
        "deepseek_model": "deepseek-flash",
        "deepseek_base_url": "https://api.deepseek.com",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_production_accepts_a_local_only_configuration() -> None:
    _production().validate_runtime()


def test_production_accepts_an_optional_deepseek_backup() -> None:
    _production(deepseek_api_key="sk-production-0123456789abcdef").validate_runtime()


@pytest.mark.parametrize(
    "overrides",
    [
        {"local_model_base_url": ""},
        {"local_model_id": ""},
        {"local_model_base_url": "http://model-stub:9000/v1"},
        {"local_model_id": "ci-model-stub"},
        {"local_model_base_url": "https://example.com/v1"},
        {"deepseek_api_key": "sk-replace-with-a-real-key"},
        {
            "deepseek_api_key": "sk-production-0123456789abcdef",
            "deepseek_base_url": "https://example.com/v1",
        },
        {
            "deepseek_api_key": "sk-production-0123456789abcdef",
            "deepseek_base_url": "http://model-stub:9000/v1",
        },
    ],
)
def test_production_rejects_unsafe_provider_configuration(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(RuntimeError):
        _production(**overrides).validate_runtime()


def test_test_environment_can_use_the_controlled_stub() -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        demo_path_prefix="/ci-clinicpilot-0123456789/",
        demo_password_hash="",
        internal_tool_key="ci-internal-tool-key-0123456789abcdef",
        local_model_base_url="http://model-stub:9000/v1",
        local_model_id="ci-model-stub",
        deepseek_api_key="ci-stub",
        deepseek_model="ci-model-stub",
        deepseek_base_url="http://model-stub:9000/v1",
    )
    settings.validate_runtime()


@pytest.mark.parametrize(
    "field",
    ["local_model_base_url", "deepseek_base_url"],
)
def test_provider_urls_require_an_http_scheme(field: str) -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, **{field: "not-a-url"})  # type: ignore[arg-type]
