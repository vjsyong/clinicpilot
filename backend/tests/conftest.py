from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from app.auth.password import hash_password
from app.clock import FrozenClock
from app.contracts import TurnContext, TurnResult
from app.db.models import Base
from app.db.seed import seed_all
from app.db.session import create_session_factory
from app.main import create_app
from app.settings import REPO_ROOT, Settings
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

TEST_PASSWORD = "test-password"
TEST_INTERNAL_KEY = "test-internal-tool-key-0123456789abcdef"
ORIGIN = {"Origin": "http://testserver"}


@dataclass
class FakeIndex:
    def ready(self) -> bool:
        return True

    def search(self, query: str, limit: int = 5, filters: Any = None) -> list[Any]:
        return []

    async def prewarm(self) -> None:
        return None


class FakeController:
    def __init__(self) -> None:
        self.calls: list[TurnContext] = []

    async def handle_turn(self, ctx: TurnContext) -> TurnResult:
        self.calls.append(ctx)
        return TurnResult(assistant_message=f"echo: {ctx.user_text}")


@dataclass
class DBHarness:
    settings: Settings
    engine: Engine
    session_factory: sessionmaker[Session]


@dataclass
class AppHarness:
    client: TestClient
    app: FastAPI
    controller: FakeController
    settings: Settings
    session_factory: sessionmaker[Session]
    clock: FrozenClock


@pytest.fixture(scope="session")
def demo_password_hash() -> str:
    return hash_password(TEST_PASSWORD)


@pytest.fixture
def frozen_clock() -> FrozenClock:
    return FrozenClock(datetime(2026, 10, 22, 12, 0, tzinfo=UTC))


@pytest.fixture
def db(tmp_path: Path, demo_password_hash: str) -> DBHarness:
    settings = Settings(
        _env_file=None,
        app_env="test",
        demo_path_prefix="/demo/",
        demo_password_hash=demo_password_hash,
        internal_tool_key=TEST_INTERNAL_KEY,
        database_url=f"sqlite:///{tmp_path / 'clinicpilot-test.db'}",
        csv_dir=REPO_ROOT / "dkl_ai_interview_data",
        frontend_dist_dir=tmp_path / "dist",
    )
    engine, session_factory = create_session_factory(settings)
    Base.metadata.create_all(engine)
    seed_all(session_factory, settings)
    harness = DBHarness(settings=settings, engine=engine, session_factory=session_factory)
    yield harness
    engine.dispose()


@pytest.fixture
def harness(db: DBHarness, frozen_clock: FrozenClock) -> AppHarness:
    controller = FakeController()

    def controller_factory(*_args: Any, **_kwargs: Any) -> FakeController:
        return controller

    def index_factory(*_args: Any, **_kwargs: Any) -> FakeIndex:
        return FakeIndex()

    asgi = create_app(
        db.settings,
        controller_factory=controller_factory,
        index_factory=index_factory,
    )
    with TestClient(asgi) as client:
        fastapi_app: FastAPI = asgi.app  # type: ignore[attr-defined]
        fastapi_app.state.clock = frozen_clock
        fastapi_app.state.controller = controller
        yield AppHarness(
            client=client,
            app=fastapi_app,
            controller=controller,
            settings=db.settings,
            session_factory=fastapi_app.state.session_factory,
            clock=frozen_clock,
        )


@pytest.fixture
def login() -> Any:
    def _login(
        client: TestClient,
        password: str = TEST_PASSWORD,
        next_value: str = "",
        *,
        origin: bool = True,
    ) -> Any:
        headers = dict(ORIGIN) if origin else {}
        return client.post(
            "/demo/login",
            data={"password": password, "next": next_value},
            headers=headers,
            follow_redirects=False,
        )

    return _login


@pytest.fixture
def frontend_dist(db: DBHarness) -> Path:
    dist = db.settings.frontend_dist_dir
    assets = dist / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    (dist / "index.html").write_text(
        "<!doctype html><html><head><title>ClinicPilot</title></head>"
        '<body><div id="root"></div></body></html>',
        encoding="utf-8",
    )
    (assets / "app.js").write_text("console.log('clinicpilot');", encoding="utf-8")
    return dist
