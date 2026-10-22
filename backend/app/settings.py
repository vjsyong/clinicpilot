from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
DEV_PATH_PREFIX = "/demo/"
DEV_PASSWORD = "clinicpilot-demo"  # noqa: S105 - documented non-production default
DEV_INTERNAL_KEY = "dev-internal-tool-key-change-me"

_PREFIX_RE = re.compile(r"^/[a-z0-9](?:[a-z0-9-]*[a-z0-9])?/$")
_PLACEHOLDER_MARKERS = ("change-me", "changeme", "placeholder", "replace-me", "example")
_TEST_PROVIDER_MARKERS = (
    "ci-stub",
    "ci-model-stub",
    "model-stub",
    "clinicpilot-ci",
    "eval-internal",
)
_PRODUCTION_PROVIDER_URL = "https://api.deepseek.com/"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["development", "test", "production"] = "development"
    demo_path_prefix: str = DEV_PATH_PREFIX
    demo_password_hash: str = ""
    internal_tool_key: str = DEV_INTERNAL_KEY
    internal_api_base_url: str = "http://127.0.0.1:8000"

    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-flash"
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_timeout_seconds: float = 45.0

    database_url: str = f"sqlite:///{REPO_ROOT / 'data' / 'clinicpilot.db'}"
    frontend_dist_dir: Path = REPO_ROOT / "frontend" / "dist"
    csv_dir: Path = REPO_ROOT / "dkl_ai_interview_data"

    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_revision: str = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"

    cloudflare_tunnel_token: str = ""

    max_tool_rounds: int = Field(default=6, ge=1, le=12)
    max_message_chars: int = Field(default=4000, ge=200, le=20000)
    max_history_messages: int = Field(default=40, ge=10, le=200)
    session_ttl_hours: int = Field(default=8, ge=1, le=72)

    @field_validator("demo_path_prefix")
    @classmethod
    def _normalize_prefix(cls, value: str) -> str:
        value = "/" + value.strip("/") + "/"
        return value

    @field_validator("internal_api_base_url")
    @classmethod
    def _normalize_internal_base(cls, value: str) -> str:
        # The agent adapter appends relative paths ("api/bookings"), so the
        # configured internal base must end in a slash and include the runtime
        # prefix (or be a bare origin).
        return value if value.endswith("/") else value + "/"

    @field_validator("database_url")
    @classmethod
    def _absolutize_sqlite(cls, value: str) -> str:
        # Resolve relative SQLite paths against the repository root, not the
        # caller's working directory. This keeps `alembic` (repo root) and the
        # documented `(cd backend && ...)` commands on the same database.
        prefix = "sqlite:///"
        if not value.startswith(prefix):
            return value
        raw = value[len(prefix) :]
        if not raw or raw.startswith("/") or raw.startswith(":memory:"):
            return value
        return prefix + str((REPO_ROOT / raw).resolve())

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def secure_cookies(self) -> bool:
        return self.is_production

    @property
    def cookie_path(self) -> str:
        return self.demo_path_prefix

    @property
    def static_dir(self) -> Path:
        return self.frontend_dist_dir

    def require_valid_prefix(self) -> None:
        if not _PREFIX_RE.fullmatch(self.demo_path_prefix):
            raise RuntimeError("DEMO_PATH_PREFIX must be /<lowercase-slug>/")
        slug = self.demo_path_prefix.strip("/")
        if len(slug) < 4 or len(slug) > 64:
            raise RuntimeError("DEMO_PATH_PREFIX slug must be 4-64 characters")

    def validate_runtime(self) -> None:
        """Fail closed on unsafe production configuration."""
        self.require_valid_prefix()
        if not self.is_production:
            return

        errors: list[str] = []
        slug = self.demo_path_prefix.strip("/")
        if self.demo_path_prefix == DEV_PATH_PREFIX or len(slug) < 12:
            errors.append("DEMO_PATH_PREFIX must be a generated secret slug (>=12 chars)")
        if not self.demo_password_hash.startswith("$argon2"):
            errors.append("DEMO_PASSWORD_HASH must be an Argon2id hash")
        if len(self.internal_tool_key) < 32:
            errors.append("INTERNAL_TOOL_KEY must be at least 32 characters")
        if not self.deepseek_api_key or self.deepseek_api_key.startswith("sk-replace"):
            errors.append("DEEPSEEK_API_KEY is required")
        provider_text = " ".join(
            [self.deepseek_api_key, self.deepseek_model, self.deepseek_base_url]
        ).lower()
        if any(marker in provider_text for marker in _TEST_PROVIDER_MARKERS):
            errors.append("production must not use the controlled CI/evaluation provider stub")
        if self.deepseek_base_url.rstrip("/") + "/" != _PRODUCTION_PROVIDER_URL:
            errors.append("DEEPSEEK_BASE_URL must be the production DeepSeek endpoint")
        combined = " ".join(
            [self.demo_password_hash, self.internal_tool_key, self.deepseek_api_key]
        ).lower()
        if any(marker in combined for marker in _PLACEHOLDER_MARKERS):
            errors.append("production credentials still contain placeholder values")
        if errors:
            raise RuntimeError("Unsafe production configuration: " + "; ".join(errors))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
