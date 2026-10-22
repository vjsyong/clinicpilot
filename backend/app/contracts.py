"""Frozen cross-package contracts.

WP1 (persistence/auth/API), WP2 (agent/retrieval), and WP3 (frontend) code
against these representations. Changing anything here requires the integrator
to update docs/contracts.md and every consumer in the same change.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

PATIENT_ID = "P001"


class DraftStatus(StrEnum):
    COLLECTING_DETAILS = "collecting_details"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    BOOKING_IN_PROGRESS = "booking_in_progress"
    BOOKED = "booked"
    CANCELLED = "cancelled"


class ChatTurnStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class SourceRef(BaseModel):
    source_file: str
    record_id: str


class RetrievedDocument(BaseModel):
    document_id: str
    source_file: str
    record_id: str
    text: str
    metadata: dict[str, str] = Field(default_factory=dict)


class Evidence(BaseModel):
    """One ranked knowledge result with retrieval provenance."""

    document: RetrievedDocument
    score: float
    channels: list[str] = Field(default_factory=list)
    excerpt: str = ""


class BookingDraftView(BaseModel):
    draft_id: str
    version: int
    status: str
    doctor_id: str | None = None
    doctor_name: str | None = None
    treatment_id: str | None = None
    treatment_name: str | None = None
    clinic_id: str | None = None
    clinic_name: str | None = None
    local_date: str | None = None
    local_time: str | None = None
    timezone: str | None = None
    starts_at_utc: datetime | None = None
    notes: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    booking_id: str | None = None
    editing_booking_id: str | None = None
    confirmation_message_id: str | None = None
    confirmation_version: int | None = None


class BookingView(BaseModel):
    booking_id: str
    patient_id: str
    doctor_id: str
    doctor_name: str
    treatment_id: str
    treatment_name: str
    clinic_id: str
    clinic_name: str
    local_date: str
    local_time: str
    timezone: str
    starts_at_utc: datetime
    status: str
    notes: str | None = None


class Event(BaseModel):
    type: str
    booking: BookingView | None = None
    action_id: str | None = None
    detail: str | None = None


class SlotSuggestion(BaseModel):
    local_date: str
    local_time: str
    timezone: str
    label: str


class NextStep(BaseModel):
    kind: Literal[
        "collect_details",
        "choose_slot",
        "confirm_booking",
        "confirm_action",
        "completed",
    ]
    missing_fields: list[str] = Field(default_factory=list)
    suggestions: list[SlotSuggestion] = Field(default_factory=list)
    draft_version: int | None = None
    action_id: str | None = None
    booking_id: str | None = None
    action_booking: BookingView | None = None
    message: str | None = None


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message_id: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=4000)
    patient_id: str | None = PATIENT_ID


class ChatResponse(BaseModel):
    conversation_id: str
    message_id: str
    assistant_message: str
    sources: list[SourceRef] = Field(default_factory=list)
    booking_draft: BookingDraftView | None = None
    events: list[Event] = Field(default_factory=list)
    next_step: NextStep | None = None


class ConversationSummary(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int
    turn_count: int
    active_turn_id: str | None = None


class ToolTrace(BaseModel):
    id: str | None = None
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    ok: bool = True
    summary: str = ""
    sources: list[SourceRef] = Field(default_factory=list)


class TranscriptTurn(BaseModel):
    turn_id: str
    client_message_id: str
    user: str
    status: str
    created_at: datetime
    assistant: str | None = None
    sources: list[SourceRef] = Field(default_factory=list)
    booking_draft: BookingDraftView | None = None
    tools: list[ToolTrace] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    next_step: NextStep | None = None


class ConversationTranscript(BaseModel):
    conversation: ConversationSummary
    turns: list[TranscriptTurn]
    draft: BookingDraftView | None = None


class DraftUpdate(BaseModel):
    draft: BookingDraftView | None = None
    missing_fields: list[str] = Field(default_factory=list)
    changed: bool = False
    errors: list[str] = Field(default_factory=list)


class TurnContext(BaseModel):
    conversation_id: str
    turn_id: str
    demo_session_id: str
    patient_id: str = PATIENT_ID
    user_text: str
    now: datetime


class TurnResult(BaseModel):
    assistant_message: str
    sources: list[SourceRef] = Field(default_factory=list)
    booking_draft: BookingDraftView | None = None
    events: list[Event] = Field(default_factory=list)
    next_step: NextStep | None = None


class ModelToolCall(BaseModel):
    id: str
    name: str
    arguments: str


class ModelUsage(BaseModel):
    model: str | None = None
    response_model: str | None = None
    response_id: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    finish_reason: str | None = None
    latency_ms: int | None = None


class ModelResponse(BaseModel):
    content: str | None = None
    tool_calls: list[ModelToolCall] = Field(default_factory=list)
    usage: ModelUsage | None = None


class ErrorDetail(BaseModel):
    code: str
    message: str
    retryable: bool = False


class ErrorResponse(BaseModel):
    error: ErrorDetail
    request_id: str


class ProviderError(RuntimeError):
    """External generation provider failed; safe to surface as a retryable 502."""


class Clock(Protocol):
    def now(self) -> datetime: ...


class ConversationStore(Protocol):
    async def load_messages(self, conversation_id: str) -> list[dict[str, Any]]: ...

    async def save_messages(
        self, conversation_id: str, messages: list[dict[str, Any]], now: datetime
    ) -> None: ...

    async def last_assistant_message_id(self, conversation_id: str) -> str | None: ...


class DraftStore(Protocol):
    async def get(self, conversation_id: str) -> BookingDraftView | None: ...

    async def update(self, conversation_id: str, changes: dict[str, Any]) -> DraftUpdate: ...

    async def abandon(self, conversation_id: str) -> None: ...

    async def mark_presented(
        self, conversation_id: str, assistant_message_id: str, version: int
    ) -> None: ...

    async def clear_presented(self, conversation_id: str) -> None: ...

    async def authorize(self, conversation_id: str, turn_id: str) -> BookingDraftView: ...

    async def mark_booked(self, conversation_id: str, booking: BookingView) -> None: ...

    async def mark_failed(self, conversation_id: str) -> None: ...


class BookingApi(Protocol):
    async def list_bookings(self, patient_id: str = PATIENT_ID) -> list[BookingView]: ...

    async def create_booking(self, draft_id: str, draft_version: int) -> BookingView: ...

    async def delete_booking(self, booking_id: str) -> BookingView: ...


class KnowledgeIndex(Protocol):
    def ready(self) -> bool: ...

    def search(
        self,
        query: str,
        limit: int = 5,
        filters: dict[str, str] | None = None,
    ) -> list[RetrievedDocument]: ...

    def search_evidence(
        self,
        query: str,
        limit: int = 5,
        filters: dict[str, str] | None = None,
    ) -> list[Evidence]: ...

    def lookup(self, source_file: str, record_id: str) -> RetrievedDocument | None: ...

    async def prewarm(self) -> None: ...


class ModelClient(Protocol):
    async def complete(
        self,
        *,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
        tool_choice: str | dict[str, Any] = "auto",
    ) -> ModelResponse: ...


class AuditRecorder(Protocol):
    async def record(
        self,
        *,
        demo_session_id: int,
        conversation_id: str | None,
        turn_id: str | None,
        event_type: str,
        name: str,
        status: str,
        payload: dict[str, Any],
    ) -> None: ...


class AgentController(Protocol):
    async def handle_turn(self, ctx: TurnContext, emit: Any = None) -> TurnResult: ...
