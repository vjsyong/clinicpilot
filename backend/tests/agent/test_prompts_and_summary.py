from __future__ import annotations

from datetime import UTC, datetime

from app.agent.prompts import build_system_prompt
from app.agent.summary import canonical_summary
from app.contracts import PATIENT_ID
from tests.agent.fakes import complete_draft


def test_canonical_summary_contains_every_required_fact() -> None:
    draft = complete_draft()
    summary = canonical_summary(draft)

    assert "Dr. Sarah Jenkins (D101)" in summary
    assert "General Health Checkup (T001)" in summary
    assert "Metro Care Health Clinic (C001)" in summary
    assert "2026-11-05 at 09:00" in summary
    assert "America/New_York" in summary
    assert 'Reply "yes" to confirm' in summary


def test_canonical_summary_tolerates_incomplete_draft() -> None:
    draft = complete_draft()
    draft.local_date = None
    draft.doctor_name = None

    summary = canonical_summary(draft)

    assert "D101" in summary
    assert "date not selected" in summary


def test_system_prompt_contains_scope_time_context_and_draft() -> None:
    draft = complete_draft()
    now = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)

    prompt = build_system_prompt(now, "Allergies: Penicillin", draft)

    assert PATIENT_ID in prompt
    assert "Current time (UTC): 2026-10-22T12:00+00:00" in prompt
    assert "America/New_York" in prompt
    assert "America/Los_Angeles" in prompt
    assert "Allergies: Penicillin" in prompt
    assert "get_patient_record" in prompt
    assert "recorded measurements" in prompt
    assert "Do not read private patient records" not in prompt
    assert "D101" in prompt
    assert "awaiting_confirmation" in prompt
    assert "no allergist" in prompt
    assert "dedicated" not in prompt.lower()
    assert "never invent a combined total" in prompt.lower()
    assert "call 911" in prompt
    assert "yes, yes please, confirm, confirmed" in prompt
    assert "must not discard an active booking draft" in prompt
    assert "immediately previous assistant message" in prompt
    assert canonical_summary(draft).splitlines()[0] in prompt


def test_system_prompt_handles_no_draft_and_no_patient_context() -> None:
    prompt = build_system_prompt(datetime(2026, 10, 22, 12, 0, tzinfo=UTC), None, None)
    assert "No booking draft is active." in prompt
    assert "Patient context is temporarily unavailable." in prompt
