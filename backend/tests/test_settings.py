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
        "deepseek_api_key": "sk-production-0123456789abcdef",
        "deepseek_model": "deepseek-flash",
        "deepseek_base_url": "https://api.deepseek.com",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_production_accepts_the_real_provider_endpoint() -> None:
    _production().validate_runtime()


@pytest.mark.parametrize(
    "overrides",
    [
        {"deepseek_api_key": "ci-stub"},
        {"deepseek_model": "ci-model-stub"},
        {"deepseek_base_url": "http://model-stub:9000/v1"},
        {"deepseek_base_url": "https://example.com/v1"},
        {"deepseek_base_url": "http://api.deepseek.com"},
    ],
)
def test_production_rejects_controlled_stub_or_untrusted_provider(
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
        deepseek_api_key="ci-stub",
        deepseek_model="ci-model-stub",
        deepseek_base_url="http://model-stub:9000/v1",
    )
    settings.validate_runtime()
