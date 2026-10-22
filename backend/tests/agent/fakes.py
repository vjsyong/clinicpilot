"""Deterministic contract doubles for agent tests."""

from __future__ import annotations

import copy
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.clock import FrozenClock
from app.contracts import (
    PATIENT_ID,
    BookingDraftView,
    BookingView,
    DraftStatus,
    DraftUpdate,
    ModelResponse,
    ModelToolCall,
    ProviderError,
    RetrievedDocument,
    SourceRef,
    TurnContext,
)
from app.settings import Settings

DOCTORS: dict[str, tuple[str, str, str, str]] = {
    "D101": (
        "Dr. Sarah Jenkins",
        "C001",
        "Metro Care Health Clinic",
        "America/New_York",
    ),
    "D102": ("Dr. Michael Chang", "C001", "Metro Care Health Clinic", "America/New_York"),
    "D103": ("Dr. Elena Rostova", "C002", "Sunset Wellness Center", "America/Los_Angeles"),
    "D104": ("Dr. James Wilson", "C001", "Metro Care Health Clinic", "America/New_York"),
}

TREATMENTS: dict[str, str] = {
    "T001": "General Health Checkup",
    "T002": "Pediatric Vaccination",
    "T003": "Dermatology Consultation",
    "T004": "Flu Shot Injection",
    "T005": "Knee Pain Assessment",
}


class FakeDraftView(BookingDraftView):
    """BookingDraftView with explicit presentation state for tests."""


@dataclass
class FakeModelClient:
    responses: list[ModelResponse | Exception]
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def complete(
        self,
        *,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
        tool_choice: str | dict[str, Any] = "auto",
    ) -> ModelResponse:
        self.calls.append(
            {
                "messages": copy.deepcopy(list(messages)),
                "tools": copy.deepcopy(list(tools)),
                "tool_choice": copy.deepcopy(tool_choice),
            }
        )
        if not self.responses:
            raise AssertionError("FakeModelClient ran out of scripted responses")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@dataclass
class FakeConversationStore:
    messages: list[dict[str, Any]] = field(default_factory=list)
    saves: list[tuple[str, list[dict[str, Any]], datetime]] = field(default_factory=list)

    async def load_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        return copy.deepcopy(self.messages)

    async def save_messages(
        self, conversation_id: str, messages: list[dict[str, Any]], now: datetime
    ) -> None:
        self.messages = copy.deepcopy(messages)
        self.saves.append((conversation_id, copy.deepcopy(messages), now))

    async def last_assistant_message_id(self, conversation_id: str) -> str | None:
        for message in reversed(self.messages):
            if message.get("role") != "assistant":
                continue
            value = message.get("_cp_message_id")
            return value if isinstance(value, str) and value else None
        return None

    def add_assistant(self, content: str, message_id: str) -> None:
        self.messages.append(
            {"role": "assistant", "content": content, "_cp_message_id": message_id}
        )


@dataclass
class FakeDraftStore:
    conversation_id: str
    draft: FakeDraftView | None = None
    updates: list[dict[str, Any]] = field(default_factory=list)
    presentations: list[tuple[str, int]] = field(default_factory=list)
    clears: int = 0
    authorizations: list[str] = field(default_factory=list)
    booked: list[BookingView] = field(default_factory=list)
    failures: int = 0
    abandoned: int = 0

    def __post_init__(self) -> None:
        if self.draft is not None and not isinstance(self.draft, FakeDraftView):
            self.draft = FakeDraftView(**self.draft.model_dump())

    async def get(self, conversation_id: str) -> BookingDraftView | None:
        return self.draft

    async def update(self, conversation_id: str, changes: dict[str, Any]) -> DraftUpdate:
        self.updates.append(dict(changes))
        if self.draft is None or self.draft.status == DraftStatus.BOOKED.value:
            candidate = FakeDraftView(
                draft_id="draft-1",
                version=0,
                status=DraftStatus.COLLECTING_DETAILS.value,
            )
            created = True
        else:
            candidate = self.draft.model_copy(deep=True)
            created = False

        for key, value in changes.items():
            if key in {"doctor_id", "treatment_id", "local_date", "local_time", "notes"}:
                setattr(candidate, key, value)

        _apply_catalog(candidate)
        missing = _missing(candidate)
        changed = created or any(
            getattr(candidate, key) != getattr(self.draft, key)
            for key in (
                "doctor_id",
                "treatment_id",
                "local_date",
                "local_time",
                "notes",
            )
        )
        if not changed:
            return DraftUpdate(
                draft=candidate,
                missing_fields=missing,
                changed=False,
            )

        candidate.version = 1 if created else candidate.version + 1
        candidate.status = (
            DraftStatus.AWAITING_CONFIRMATION.value
            if not missing
            else DraftStatus.COLLECTING_DETAILS.value
        )
        candidate.confirmation_message_id = None
        candidate.confirmation_version = None
        self.draft = candidate
        return DraftUpdate(
            draft=candidate,
            missing_fields=missing,
            changed=True,
        )

    async def abandon(self, conversation_id: str) -> None:
        self.abandoned += 1
        if self.draft is not None:
            self.draft.status = DraftStatus.CANCELLED.value
            self.draft.confirmation_message_id = None
            self.draft.confirmation_version = None

    async def mark_presented(
        self, conversation_id: str, assistant_message_id: str, version: int
    ) -> None:
        self.presentations.append((assistant_message_id, version))
        if (
            self.draft is not None
            and self.draft.version == version
            and self.draft.status == DraftStatus.AWAITING_CONFIRMATION.value
        ):
            self.draft.confirmation_message_id = assistant_message_id
            self.draft.confirmation_version = version

    async def clear_presented(self, conversation_id: str) -> None:
        self.clears += 1
        if self.draft is not None:
            self.draft.confirmation_message_id = None
            self.draft.confirmation_version = None

    async def authorize(self, conversation_id: str, turn_id: str) -> BookingDraftView:
        if self.draft is None:
            raise ProviderError("missing draft")
        if _missing(self.draft):
            raise ProviderError("incomplete draft")
        if self.draft.status != DraftStatus.AWAITING_CONFIRMATION.value:
            raise ProviderError("not awaiting confirmation")
        if self.draft.confirmation_message_id is None:
            raise ProviderError("not presented")
        self.authorizations.append(turn_id)
        self.draft.status = DraftStatus.BOOKING_IN_PROGRESS.value
        return self.draft

    async def mark_booked(self, conversation_id: str, booking: BookingView) -> None:
        self.booked.append(booking)
        if self.draft is not None:
            self.draft.status = DraftStatus.BOOKED.value
            self.draft.booking_id = booking.booking_id
            self.draft.confirmation_message_id = None
            self.draft.confirmation_version = None

    async def mark_failed(self, conversation_id: str) -> None:
        self.failures += 1
        if self.draft is not None:
            self.draft.status = (
                DraftStatus.AWAITING_CONFIRMATION.value
                if not _missing(self.draft)
                else DraftStatus.COLLECTING_DETAILS.value
            )


@dataclass
class FakeBookingApi:
    bookings: list[BookingView] = field(default_factory=list)
    create_result: BookingView | None = None
    create_error: Exception | None = None
    list_error: Exception | None = None
    list_calls: list[str] = field(default_factory=list)
    create_calls: list[tuple[str, int]] = field(default_factory=list)

    async def list_bookings(self, patient_id: str = PATIENT_ID) -> list[BookingView]:
        self.list_calls.append(patient_id)
        if self.list_error is not None:
            raise self.list_error
        return list(self.bookings)

    async def create_booking(self, draft_id: str, draft_version: int) -> BookingView:
        self.create_calls.append((draft_id, draft_version))
        if self.create_error is not None:
            raise self.create_error
        if self.create_result is None:
            raise AssertionError("FakeBookingApi has no create_result")
        return self.create_result


@dataclass
class FakeIndex:
    documents: list[RetrievedDocument] = field(default_factory=list)
    calls: list[tuple[str, int, dict[str, str] | None]] = field(default_factory=list)

    def ready(self) -> bool:
        return True

    def search(
        self,
        query: str,
        limit: int = 5,
        filters: dict[str, str] | None = None,
    ) -> list[RetrievedDocument]:
        self.calls.append((query, limit, filters))
        return list(self.documents)

    async def prewarm(self) -> None:
        return None


@dataclass
class AgentHarness:
    controller: Any
    model: FakeModelClient
    conversations: FakeConversationStore
    drafts: FakeDraftStore
    booking_api: FakeBookingApi
    index: FakeIndex
    clock: FrozenClock
    settings: Settings

    def ctx(self, text: str, turn_id: str = "turn-1") -> TurnContext:
        return TurnContext(
            conversation_id=self.drafts.conversation_id,
            turn_id=turn_id,
            demo_session_id="1",
            patient_id=PATIENT_ID,
            user_text=text,
            now=self.clock.now(),
        )


def build_harness(
    responses: list[ModelResponse | Exception],
    *,
    draft: FakeDraftView | BookingDraftView | None = None,
    messages: list[dict[str, Any]] | None = None,
    booking_api: FakeBookingApi | None = None,
    index: FakeIndex | None = None,
    settings: Settings | None = None,
    patient_context: Callable[[str], Any] | None = None,
) -> AgentHarness:
    from app.agent.controller import AgentController

    active_settings = settings or Settings(
        _env_file=None,
        app_env="test",
        max_tool_rounds=6,
        max_history_messages=40,
        deepseek_api_key="",
    )
    clock = FrozenClock(datetime(2026, 10, 22, 12, 0, tzinfo=UTC))
    model = FakeModelClient(responses=responses)
    conversations = FakeConversationStore(messages=copy.deepcopy(messages or []))
    drafts = FakeDraftStore(conversation_id="conv-1", draft=draft)
    api = booking_api or FakeBookingApi()
    knowledge = index or FakeIndex()
    loader = patient_context or (
        lambda _patient_id: "Patient P001. Allergies: Penicillin, Peanuts."
    )
    controller = AgentController(
        settings=active_settings,
        clock=clock,
        model_client=model,
        index=knowledge,
        drafts=drafts,
        conversations=conversations,
        booking_api=api,
        patient_context_loader=loader,
    )
    return AgentHarness(
        controller=controller,
        model=model,
        conversations=conversations,
        drafts=drafts,
        booking_api=api,
        index=knowledge,
        clock=clock,
        settings=active_settings,
    )


def complete_draft(
    *,
    status: str = DraftStatus.AWAITING_CONFIRMATION.value,
    version: int = 2,
    presented: str | None = "msg-summary",
) -> FakeDraftView:
    doctor_name, clinic_id, clinic_name, timezone = DOCTORS["D101"]
    return FakeDraftView(
        draft_id="draft-1",
        version=version,
        status=status,
        doctor_id="D101",
        doctor_name=doctor_name,
        treatment_id="T001",
        treatment_name=TREATMENTS["T001"],
        clinic_id=clinic_id,
        clinic_name=clinic_name,
        local_date="2026-11-05",
        local_time="09:00",
        timezone=timezone,
        starts_at_utc=datetime(2026, 11, 5, 14, 0, tzinfo=UTC),
        confirmation_message_id=presented,
        confirmation_version=version if presented else None,
    )


def booking_view(**overrides: Any) -> BookingView:
    values: dict[str, Any] = {
        "booking_id": "B2001",
        "patient_id": PATIENT_ID,
        "doctor_id": "D101",
        "doctor_name": "Dr. Sarah Jenkins",
        "treatment_id": "T001",
        "treatment_name": "General Health Checkup",
        "clinic_id": "C001",
        "clinic_name": "Metro Care Health Clinic",
        "local_date": "2026-11-05",
        "local_time": "09:00",
        "timezone": "America/New_York",
        "starts_at_utc": datetime(2026, 11, 5, 14, 0, tzinfo=UTC),
        "status": "Confirmed",
        "notes": None,
    }
    values.update(overrides)
    return BookingView(**values)


def tool_call(name: str, arguments: str = "{}", call_id: str = "call-1") -> ModelToolCall:
    return ModelToolCall(id=call_id, name=name, arguments=arguments)


def text_response(content: str) -> ModelResponse:
    return ModelResponse(content=content)


def tool_response(*calls: ModelToolCall, content: str | None = None) -> ModelResponse:
    return ModelResponse(content=content, tool_calls=list(calls))


def source(source_file: str, record_id: str) -> RetrievedDocument:
    return RetrievedDocument(
        document_id=f"{source_file}:{record_id}",
        source_file=source_file,
        record_id=record_id,
        text=f"{source_file} {record_id}",
        metadata={"record_id": record_id},
    )


def source_refs(refs: Sequence[SourceRef]) -> set[tuple[str, str]]:
    return {(ref.source_file, ref.record_id) for ref in refs}


def _apply_catalog(draft: FakeDraftView) -> None:
    if draft.doctor_id in DOCTORS:
        name, clinic_id, clinic_name, timezone = DOCTORS[draft.doctor_id]
        draft.doctor_name = name
        draft.clinic_id = clinic_id
        draft.clinic_name = clinic_name
        draft.timezone = timezone
    if draft.treatment_id in TREATMENTS:
        draft.treatment_name = TREATMENTS[draft.treatment_id]
    draft.missing_fields = _missing(draft)


def _missing(draft: FakeDraftView) -> list[str]:
    missing = [
        field
        for field in ("doctor_id", "treatment_id", "local_date", "local_time", "timezone")
        if not getattr(draft, field)
    ]
    return missing
