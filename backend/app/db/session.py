from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from app.settings import Settings
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker


def _ensure_sqlite_dir(database_url: str) -> None:
    if not database_url.startswith("sqlite:///"):
        return
    raw = database_url.removeprefix("sqlite:///")
    if raw.startswith(":memory:"):
        return
    Path(raw).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def create_engine_for(settings: Settings) -> Engine:
    _ensure_sqlite_dir(settings.database_url)
    is_sqlite = settings.database_url.startswith("sqlite")
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False} if is_sqlite else {},
        pool_pre_ping=True,
    )
    if is_sqlite:

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_connection: object, _record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def create_session_factory(settings: Settings) -> tuple[Engine, sessionmaker[Session]]:
    engine = create_engine_for(settings)
    return engine, sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
