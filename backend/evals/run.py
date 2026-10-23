"""Live DeepSeek evaluation runner for ClinicPilot.

Usage (from the repository root):

    uv run --project backend python backend/evals/run.py

This is not a pytest module. It uses a temporary SQLite database, real
persistence/retrieval services, a real in-process booking REST API, and the
real DeepSeek client. Without DEEPSEEK_API_KEY it reports ``skipped`` and exits
zero. Any failed assertion exits nonzero.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

CASES_PATH = Path(__file__).with_name("cases.json")
DATE_PLACEHOLDER = re.compile(r"\{\{date_plus_days:(\d+)\}\}")
EVAL_INTERNAL_KEY = "eval-internal-tool-key-0123456789abcdef"

__test__ = False


def main() -> int:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        from app.settings import Settings

        api_key = Settings().deepseek_api_key.strip()
    if not api_key:
        print(
            json.dumps(
                {
                    "status": "skipped",
                    "reason": "skipped: DEEPSEEK_API_KEY absent",
                    "cases": 0,
                },
                ensure_ascii=False,
            )
        )
        return 0
    try:
        report = asyncio.run(_run_live(api_key))
    except Exception as exc:  # pragma: no cover - live environment failure
        report = {
            "status": "failed",
            "error": f"eval setup failed ({type(exc).__name__})",
            "cases": [],
            "summary": {"total": 0, "passed": 0, "failed": 1},
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


async def _run_live(api_key: str) -> dict[str, Any]:
    import httpx
    from app.agent.controller import AgentController
    from app.agent.model_client import OpenAICompatibleModelClient, ProviderConfig
    from app.agent.tools import RestBookingApi
    from app.api.bookings import router as bookings_router
    from app.api.errors import install_error_handlers
    from app.clock import SystemClock
    from app.contracts import PATIENT_ID, TurnContext
    from app.db.models import Base
    from app.db.seed import seed_all
    from app.db.session import create_session_factory
    from app.retrieval.index import build_knowledge_index
    from app.retrieval.patient_context import (
        load_patient_context,
        load_patient_record,
        patient_record_payload,
    )
    from app.services.conversations import ConversationService
    from app.services.drafts import DraftService
    from app.settings import Settings
    from fastapi import FastAPI

    cases_document = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    cases = cases_document["cases"]

    with tempfile.TemporaryDirectory(prefix="clinicpilot-eval-") as temp_dir:
        database_url = f"sqlite:///{Path(temp_dir) / 'eval.db'}"
        settings = Settings(
            app_env="test",
            database_url=database_url,
            csv_dir=REPO_ROOT / "dkl_ai_interview_data",
            deepseek_api_key=api_key,
            deepseek_timeout_seconds=60.0,
            internal_api_base_url="http://internal.test",
            internal_tool_key=EVAL_INTERNAL_KEY,
            max_tool_rounds=6,
            max_history_messages=40,
        )
        engine, session_factory = create_session_factory(settings)
        try:
            Base.metadata.create_all(engine)
            seed_all(session_factory, settings)
            _seed_demo_session(session_factory)

            clock = SystemClock()
            internal_app = _build_internal_app(
                FastAPI,
                install_error_handlers,
                bookings_router,
                settings,
                clock,
                session_factory,
            )
            internal_client = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=internal_app),
                base_url=settings.internal_api_base_url,
                timeout=30.0,
            )
            index = build_knowledge_index(settings, session_factory)
            await index.prewarm()

            model = OpenAICompatibleModelClient(
                ProviderConfig(
                    name="deepseek",
                    model=settings.deepseek_model,
                    base_url=settings.deepseek_base_url,
                    timeout_seconds=settings.deepseek_timeout_seconds,
                    temperature=0,
                    max_tokens=1024,
                    disable_thinking=True,
                    requires_key=True,
                ),
                api_key=api_key,
            )
            conversations = ConversationService(session_factory, clock)
            drafts = DraftService(session_factory, clock, settings)
            booking_api = RestBookingApi(settings, client=internal_client)

            def patient_context_loader(_patient_id: str) -> str:
                return load_patient_context(session_factory)

            def patient_record_loader(_patient_id: str) -> dict[str, Any]:
                return patient_record_payload(load_patient_record(session_factory))

            controller = AgentController(
                settings=settings,
                clock=clock,
                model_client=model,
                index=index,
                drafts=drafts,
                conversations=conversations,
                booking_api=booking_api,
                patient_context_loader=patient_context_loader,
                patient_record_loader=patient_record_loader,
            )

            case_reports: list[dict[str, Any]] = []
            try:
                for case in cases:
                    case_reports.append(
                        await _run_case(
                            case,
                            controller=controller,
                            conversations=conversations,
                            clock=clock,
                            turn_context_cls=TurnContext,
                            patient_id=PATIENT_ID,
                        )
                    )
            finally:
                await model.aclose()
                await booking_api.aclose()
                await internal_client.aclose()

            passed = sum(1 for report in case_reports if report["passed"])
            failed = len(case_reports) - passed
            return {
                "status": "passed" if failed == 0 else "failed",
                "model": settings.deepseek_model,
                "cases": case_reports,
                "summary": {
                    "total": len(case_reports),
                    "passed": passed,
                    "failed": failed,
                },
            }
        finally:
            engine.dispose()


def _build_internal_app(
    fastapi_cls: Any,
    install_error_handlers: Any,
    bookings_router: Any,
    settings: Any,
    clock: Any,
    session_factory: Any,
) -> Any:
    app = fastapi_cls()
    app.state.settings = settings
    app.state.clock = clock
    app.state.session_factory = session_factory
    install_error_handlers(app)
    app.include_router(bookings_router)
    return app


def _seed_demo_session(session_factory: Any) -> None:
    from app.db.models import DemoSession

    now = datetime.now(UTC)
    with session_factory() as session:
        if session.get(DemoSession, 1) is None:
            session.add(
                DemoSession(
                    id=1,
                    token_hash=uuid.uuid4().hex,
                    created_at=now,
                    expires_at=now + timedelta(hours=2),
                )
            )
            session.commit()


async def _run_case(
    case: dict[str, Any],
    *,
    controller: Any,
    conversations: Any,
    clock: Any,
    turn_context_cls: Any,
    patient_id: str,
) -> dict[str, Any]:
    now = clock.now()
    conversation_id = await conversations.create_conversation(1, patient_id)
    failures: list[str] = []
    turn_reports: list[dict[str, Any]] = []
    last_result: Any = None

    for index, turn in enumerate(case["turns"]):
        message = _resolve_placeholders(turn["message"], now)
        ctx = turn_context_cls(
            conversation_id=conversation_id,
            turn_id=str(uuid.uuid4()),
            demo_session_id="1",
            patient_id=patient_id,
            user_text=message,
            now=clock.now(),
        )
        try:
            result = await controller.handle_turn(ctx)
        except Exception as exc:
            failures.append(f"turn {index + 1}: raised {type(exc).__name__}")
            break
        last_result = result
        turn_failures = _evaluate_expectation(turn.get("expect", {}), result, now)
        failures.extend(f"turn {index + 1}: {failure}" for failure in turn_failures)
        turn_reports.append(
            {
                "message": message,
                "assistant_message": result.assistant_message,
                "sources": [source.model_dump(mode="json") for source in result.sources],
                "draft_status": (
                    result.booking_draft.status if result.booking_draft is not None else None
                ),
                "draft_version": (
                    result.booking_draft.version if result.booking_draft is not None else None
                ),
                "events": [event.model_dump(mode="json") for event in result.events],
                "failures": turn_failures,
            }
        )

    if last_result is not None and case.get("expect"):
        case_failures = _evaluate_expectation(case["expect"], last_result, now)
        failures.extend(f"case: {failure}" for failure in case_failures)

    return {
        "id": case["id"],
        "description": case.get("description", ""),
        "passed": not failures,
        "failures": failures,
        "turns": turn_reports,
    }


def _evaluate_expectation(
    expectation: dict[str, Any],
    result: Any,
    now: datetime,
) -> list[str]:
    failures: list[str] = []
    text = result.assistant_message
    lowered = text.casefold()

    for phrase in expectation.get("assistant_contains", []):
        resolved = _resolve_placeholders(phrase, now)
        if resolved.casefold() not in lowered:
            failures.append(f"assistant text is missing {resolved!r}")
    contains_any = expectation.get("assistant_contains_any", [])
    if contains_any:
        resolved_any = [_resolve_placeholders(phrase, now) for phrase in contains_any]
        if not any(phrase.casefold() in lowered for phrase in resolved_any):
            failures.append(f"assistant text contains none of {resolved_any!r}")
    for phrase in expectation.get("assistant_not_contains", []):
        resolved = _resolve_placeholders(phrase, now)
        if resolved.casefold() in lowered:
            failures.append(f"assistant text contains forbidden {resolved!r}")

    source_pairs = {(source.source_file, source.record_id) for source in result.sources}
    source_files = {source.source_file for source in result.sources}
    for required in expectation.get("sources_include", []):
        pair = (required["source_file"], required["record_id"])
        if pair not in source_pairs:
            failures.append(f"missing source reference {pair!r}")
    for required_file in expectation.get("source_files", []):
        if required_file not in source_files:
            failures.append(f"missing source file {required_file!r}")

    if "booking_created" in expectation:
        created = any(event.type == "booking_created" for event in result.events)
        if created != bool(expectation["booking_created"]):
            failures.append(
                f"booking_created expected {expectation['booking_created']}, got {created}"
            )

    expected_booking = expectation.get("booking")
    if expected_booking:
        booking = next(
            (
                event.booking
                for event in result.events
                if event.type == "booking_created" and event.booking is not None
            ),
            None,
        )
        if booking is None:
            failures.append("booking_created event has no booking")
        else:
            for key, expected_value in expected_booking.items():
                actual_value = getattr(booking, key, None)
                resolved_value = _resolve_placeholders(expected_value, now)
                if str(actual_value) != str(resolved_value):
                    failures.append(
                        f"booking.{key} expected {resolved_value!r}, got {actual_value!r}"
                    )

    if "draft_status" in expectation:
        actual_status = result.booking_draft.status if result.booking_draft is not None else None
        if actual_status != expectation["draft_status"]:
            failures.append(
                f"draft_status expected {expectation['draft_status']!r}, got {actual_status!r}"
            )
    if "draft_version_at_least" in expectation:
        actual_version = result.booking_draft.version if result.booking_draft is not None else 0
        if actual_version < int(expectation["draft_version_at_least"]):
            failures.append(
                f"draft version {actual_version} is below {expectation['draft_version_at_least']}"
            )
    return failures


def _resolve_placeholders(value: Any, now: datetime) -> Any:
    if isinstance(value, str):

        def _replace(match: re.Match[str]) -> str:
            days = int(match.group(1))
            return (now.date() + timedelta(days=days)).isoformat()

        return DATE_PLACEHOLDER.sub(_replace, value)
    if isinstance(value, list):
        return [_resolve_placeholders(item, now) for item in value]
    if isinstance(value, dict):
        return {key: _resolve_placeholders(item, now) for key, item in value.items()}
    return value


if __name__ == "__main__":
    raise SystemExit(main())
