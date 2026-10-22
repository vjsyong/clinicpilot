"""Bounded tool-calling controller for ClinicPilot.

The model proposes; this controller validates tool names/arguments, owns draft
and confirmation state, performs the single authorized booking write, and never
claims success from generated prose.
"""

from __future__ import annotations

import inspect
import logging
import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.agent.model_client import DeepSeekModelClient
from app.agent.prompts import build_system_prompt
from app.agent.schemas import (
    CONFIRMATION_TOOL,
    QueryFilters,
    ToolValidationError,
    tool_definitions,
    validate_tool_arguments,
)
from app.agent.summary import canonical_summary
from app.agent.tools import (
    BookingApiError,
    RestBookingApi,
    ToolResult,
    booking_tool_result,
    bookings_tool_result,
    invalid_tool_result,
)
from app.clock import SystemClock
from app.contracts import (
    PATIENT_ID,
    BookingApi,
    BookingDraftView,
    BookingView,
    Clock,
    ConversationStore,
    DraftStatus,
    DraftStore,
    Event,
    KnowledgeIndex,
    ModelClient,
    ModelResponse,
    ModelToolCall,
    RetrievedDocument,
    SourceRef,
    TurnContext,
    TurnResult,
)
from app.services.booking_views import booking_success_text, booking_view_from_draft
from app.settings import Settings

logger = logging.getLogger("clinicpilot.agent")

DEFAULT_FALLBACK_MESSAGE = (
    "I can help with clinic information and appointments. What would you like to do?"
)
CONFIRMATION_REJECTED_MESSAGE = (
    "I couldn't verify that confirmation because the current booking summary was "
    "not the immediately preceding message. Please review the summary and confirm "
    "again."
)
BOOKING_FAILURE_MESSAGE = (
    "I could not create the booking, so there is no confirmed appointment. Your "
    "draft is still saved."
)
INTERNAL_BOOKING_FAILURE_MESSAGE = (
    "I could not complete the booking because the booking service failed. Your "
    "draft is still saved."
)
NO_BOOKING_CREATED_MESSAGE = (
    "No booking was created. Your draft is still saved. To book, review the "
    'summary below and reply "yes".'
)

_BOOKING_SUCCESS_CLAIM = re.compile(
    r"(?:\b(?:your\s+)?(?:appointment|booking|reservation)\s+"
    r"(?:is|has\s+been|was|has)\s+(?:now\s+)?"
    r"(?:booked|confirmed|scheduled|reserved|complete|all\s+set)\b"
    r"|\b(?:appointment|booking|reservation)\s+confirmed\b"
    r"|\byou(?:'re|\s+are)\s+(?:now\s+)?(?:booked|confirmed|all\s+set)\b"
    r"|\bi(?:'ve|\s+have)?\s+(?:booked|scheduled|reserved)\b"
    r"|\bsuccessfully\s+(?:booked|scheduled|reserved)\b"
    r"|\bbooking\s+confirmed\b"
    r"|\bappointment\s+confirmed\b)",
    re.IGNORECASE,
)

_TRAILING_PUNCTUATION = re.compile(r"[.!?]+$")
_WHITESPACE = re.compile(r"\s+")
_CONFIRMATION_PHRASES = frozenset(
    {
        "yes",
        "yes please",
        "confirm",
        "confirmed",
        "go ahead",
        "book it",
        "yes book it",
        "yes confirm",
        "please book it",
    }
)


@dataclass(slots=True)
class _ToolOutcome:
    result: ToolResult
    presentation: BookingDraftView | None = None
    presentation_changed: bool = False


class AgentController:
    """Implements ``app.contracts.AgentController`` with injectable dependencies."""

    def __init__(
        self,
        settings: Settings,
        clock: Clock,
        model_client: ModelClient,
        index: KnowledgeIndex,
        drafts: DraftStore,
        conversations: ConversationStore,
        booking_api: BookingApi,
        patient_context_loader: Callable[..., Any] | None = None,
    ) -> None:
        self._settings = settings
        self._clock = clock
        self._model_client = model_client
        self._index = index
        self._drafts = drafts
        self._conversations = conversations
        self._booking_api = booking_api
        self._patient_context_loader = patient_context_loader
        # ``None`` means this conversation's presented marker was explicitly
        # cleared, which prevents an in-process stale summary from authorizing.
        self._presented: dict[str, tuple[int, str] | None] = {}

    async def handle_turn(self, ctx: TurnContext) -> TurnResult:
        messages = list(await self._conversations.load_messages(ctx.conversation_id))
        draft = await self._drafts.get(ctx.conversation_id)
        last_assistant_id = await self._conversations.last_assistant_message_id(ctx.conversation_id)
        _last_id, last_assistant_content, last_presentation = _last_assistant(messages)

        messages.append(
            {
                "role": "user",
                "content": ctx.user_text,
                "_cp_message_id": ctx.turn_id,
            }
        )

        if _eligible_confirmation(
            self,
            ctx.conversation_id,
            draft,
            last_assistant_id,
            last_assistant_content,
            last_presentation,
            ctx.user_text,
        ):
            return await self._confirmation_turn(ctx, messages)

        await self._invalidate_presentation(ctx.conversation_id)

        # A committed booking may still need to be reported after a lost
        # response. Only a confirmation retry uses this recovery path; ordinary
        # follow-up questions continue normally.
        if (
            draft is not None
            and draft.status == DraftStatus.BOOKED.value
            and is_confirmation_phrase(ctx.user_text)
        ):
            recovered = await self._booked_success(ctx, messages, draft)
            if recovered is not None:
                return recovered

        return await self._normal_turn(ctx, messages, draft)

    async def _confirmation_turn(
        self,
        ctx: TurnContext,
        messages: list[dict[str, Any]],
    ) -> TurnResult:
        try:
            authorized = await self._drafts.authorize(ctx.conversation_id, ctx.turn_id)
        except Exception as exc:
            logger.warning("Confirmation authorization failed (%s).", type(exc).__name__)
            return await self._confirmation_unavailable(ctx, messages)

        self._presented[ctx.conversation_id] = None
        prompt = build_system_prompt(ctx.now, await self._load_patient_context(), authorized)
        response = await self._confirmation_model_call(ctx, messages, prompt)
        calls = list(response.tool_calls) if response is not None else []

        booking: BookingView | None = None
        failure_message: str | None = None
        try:
            booking = await self._booking_api.create_booking(
                authorized.draft_id, authorized.version
            )
        except BookingApiError as exc:
            failure_message = exc.safe_message
        except Exception as exc:
            logger.warning("Booking API failure (%s).", type(exc).__name__)
            failure_message = INTERNAL_BOOKING_FAILURE_MESSAGE

        if failure_message is not None:
            recovered = await self._recover_after_failed_booking(ctx, messages)
            if recovered is not None:
                return recovered

        if calls:
            messages.append(_assistant_tool_call_message(calls, content=None))
            for call in calls:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": _confirmation_tool_content(call, booking, failure_message),
                    }
                )

        if failure_message is not None or booking is None:
            return await self._booking_failed(
                ctx,
                messages,
                authorized,
                failure_message or INTERNAL_BOOKING_FAILURE_MESSAGE,
            )

        try:
            await self._drafts.mark_booked(ctx.conversation_id, booking)
        except Exception as exc:
            logger.warning("Could not mark draft booked (%s).", type(exc).__name__)

        view = await self._current_draft(ctx.conversation_id)
        if view is None or view.status != DraftStatus.BOOKED.value:
            view = authorized.model_copy(update={"status": DraftStatus.BOOKED.value})

        assistant_id = str(uuid.uuid4())
        messages.append(_assistant_text_message(booking_success_text(booking), assistant_id))
        await self._conversations.save_messages(ctx.conversation_id, messages, ctx.now)
        self._presented.pop(ctx.conversation_id, None)
        return TurnResult(
            assistant_message=booking_success_text(booking),
            sources=[],
            booking_draft=view,
            events=[Event(type="booking_created", booking=booking)],
        )

    async def _confirmation_model_call(
        self,
        ctx: TurnContext,
        messages: list[dict[str, Any]],
        prompt: str,
    ) -> ModelResponse | None:
        request = [
            {"role": "system", "content": prompt},
            *_trim_messages(messages, self._settings.max_history_messages),
        ]
        try:
            return await self._model_client.complete(
                messages=request,
                tools=tool_definitions([CONFIRMATION_TOOL]),
                tool_choice="auto",
            )
        except Exception as exc:
            # The server has already authorized this exact draft. A provider
            # outage must not block a confirmed write; the deterministic answer
            # is built from the persisted record instead.
            logger.warning(
                "Confirmation model call failed (%s); using the authorized booking.",
                type(exc).__name__,
            )
            return None

    async def _confirmation_unavailable(
        self,
        ctx: TurnContext,
        messages: list[dict[str, Any]],
    ) -> TurnResult:
        try:
            await self._drafts.clear_presented(ctx.conversation_id)
        except Exception as exc:
            logger.warning("Could not clear presentation (%s).", type(exc).__name__)
        self._presented[ctx.conversation_id] = None
        view = await self._current_draft(ctx.conversation_id)
        return await self._finish_failure(ctx, messages, view, CONFIRMATION_REJECTED_MESSAGE)

    async def _booking_failed(
        self,
        ctx: TurnContext,
        messages: list[dict[str, Any]],
        authorized: BookingDraftView,
        message: str,
    ) -> TurnResult:
        view = await self._current_draft(ctx.conversation_id)
        if view is not None and view.status == DraftStatus.BOOKED.value:
            recovered = await self._booked_success(ctx, messages, view)
            if recovered is not None:
                return recovered
        try:
            await self._drafts.mark_failed(ctx.conversation_id)
        except Exception as exc:
            logger.warning("Could not mark draft failed (%s).", type(exc).__name__)
        if view is None:
            view = authorized
        return await self._finish_failure(
            ctx, messages, view, f"{message} {BOOKING_FAILURE_MESSAGE}"
        )

    async def _recover_after_failed_booking(
        self, ctx: TurnContext, messages: list[dict[str, Any]]
    ) -> TurnResult | None:
        view = await self._current_draft(ctx.conversation_id)
        if view is None or view.status != DraftStatus.BOOKED.value:
            return None
        return await self._booked_success(ctx, messages, view)

    async def _booked_success(
        self,
        ctx: TurnContext,
        messages: list[dict[str, Any]],
        view: BookingDraftView,
    ) -> TurnResult | None:
        booking = booking_view_from_draft(view)
        if booking is None:
            logger.warning("Booked draft %s is missing canonical details.", view.draft_id)
            return None
        current = await self._current_draft(ctx.conversation_id)
        if current is not None and current.status == DraftStatus.BOOKED.value:
            view = current
        else:
            view = view.model_copy(
                update={"status": DraftStatus.BOOKED.value, "booking_id": booking.booking_id}
            )
        text = booking_success_text(booking)
        assistant_id = str(uuid.uuid4())
        messages.append(_assistant_text_message(text, assistant_id))
        await self._conversations.save_messages(ctx.conversation_id, messages, ctx.now)
        self._presented.pop(ctx.conversation_id, None)
        return TurnResult(
            assistant_message=text,
            sources=[],
            booking_draft=view,
            events=[Event(type="booking_created", booking=booking)],
        )

    async def _invalidate_presentation(self, conversation_id: str) -> None:
        self._presented[conversation_id] = None
        try:
            await self._drafts.clear_presented(conversation_id)
        except Exception as exc:
            logger.warning("Could not clear presentation (%s).", type(exc).__name__)

    async def _finish_failure(
        self,
        ctx: TurnContext,
        messages: list[dict[str, Any]],
        view: BookingDraftView | None,
        message: str,
    ) -> TurnResult:
        text = message
        presented: BookingDraftView | None = None
        if (
            view is not None
            and view.status == DraftStatus.AWAITING_CONFIRMATION.value
            and not view.missing_fields
        ):
            presented = view
            text = f"{message}\n\n{canonical_summary(view)}"

        assistant_id = str(uuid.uuid4())
        if presented is not None:
            try:
                await self._drafts.mark_presented(
                    ctx.conversation_id, assistant_id, presented.version
                )
                self._presented[ctx.conversation_id] = (
                    presented.version,
                    assistant_id,
                )
            except Exception as exc:
                logger.warning(
                    "Could not mark replacement summary presented (%s).",
                    type(exc).__name__,
                )
                self._presented[ctx.conversation_id] = None
        else:
            try:
                await self._drafts.clear_presented(ctx.conversation_id)
            except Exception as exc:
                logger.warning("Could not clear presentation (%s).", type(exc).__name__)
            self._presented[ctx.conversation_id] = None

        messages.append(_assistant_text_message(text, assistant_id, presented))
        await self._conversations.save_messages(ctx.conversation_id, messages, ctx.now)
        return TurnResult(
            assistant_message=text,
            sources=[],
            booking_draft=view,
            events=[],
        )

    async def _normal_turn(
        self,
        ctx: TurnContext,
        messages: list[dict[str, Any]],
        draft: BookingDraftView | None,
    ) -> TurnResult:
        prompt = build_system_prompt(ctx.now, await self._load_patient_context(), draft)
        definitions = tool_definitions()
        sources: dict[tuple[str, str], SourceRef] = {}
        presentation: BookingDraftView | None = None
        final_text = ""

        for _round in range(self._settings.max_tool_rounds):
            request = [
                {"role": "system", "content": prompt},
                *_trim_messages(messages, self._settings.max_history_messages),
            ]
            response = await self._model_client.complete(
                messages=request,
                tools=definitions,
                tool_choice="auto",
            )
            calls = list(response.tool_calls)
            if not calls:
                final_text = (response.content or "").strip()
                break

            assistant_id = str(uuid.uuid4())
            messages.append(_assistant_tool_call_message(calls, response.content, assistant_id))
            for call in calls:
                outcome = await self._execute_tool(ctx, call, sources)
                if outcome.presentation_changed:
                    presentation = outcome.presentation
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": outcome.result.content,
                    }
                )

        view = await self._current_draft(ctx.conversation_id)
        presented_view = presentation

        # Generated prose must never assert a completed booking on its own. If
        # the model claims success in a turn where no booking was persisted,
        # replace the claim with a deterministic correction. When a complete
        # draft exists, re-present its canonical summary so the next explicit
        # "yes" is a fresh, valid confirmation.
        if final_text and _claims_booking_success(final_text):
            existing_booking = (
                booking_view_from_draft(view)
                if view is not None and view.status == DraftStatus.BOOKED.value
                else None
            )
            if existing_booking is not None:
                final_text = booking_success_text(existing_booking)
            else:
                final_text = NO_BOOKING_CREATED_MESSAGE
                if (
                    view is not None
                    and view.status == DraftStatus.AWAITING_CONFIRMATION.value
                    and not view.missing_fields
                ):
                    presented_view = view

        if (
            presented_view is not None
            and view is not None
            and view.status == DraftStatus.AWAITING_CONFIRMATION.value
            and view.version == presented_view.version
            and view.draft_id == presented_view.draft_id
        ):
            presented_view = view

        if (
            presented_view is not None
            and presented_view.status == DraftStatus.AWAITING_CONFIRMATION.value
            and not presented_view.missing_fields
        ):
            summary = canonical_summary(presented_view)
            if summary not in final_text:
                final_text = f"{final_text}\n\n{summary}".strip() if final_text else summary
            assistant_id = str(uuid.uuid4())
            try:
                await self._drafts.mark_presented(
                    ctx.conversation_id, assistant_id, presented_view.version
                )
                self._presented[ctx.conversation_id] = (
                    presented_view.version,
                    assistant_id,
                )
            except Exception as exc:
                logger.warning("Could not mark summary presented (%s).", type(exc).__name__)
                self._presented[ctx.conversation_id] = None
        else:
            if not final_text:
                final_text = DEFAULT_FALLBACK_MESSAGE
            assistant_id = str(uuid.uuid4())
            if (view is not None and view.status == DraftStatus.AWAITING_CONFIRMATION.value) or (
                draft is not None and draft.status == DraftStatus.AWAITING_CONFIRMATION.value
            ):
                try:
                    await self._drafts.clear_presented(ctx.conversation_id)
                except Exception as exc:
                    logger.warning("Could not clear presentation (%s).", type(exc).__name__)
                self._presented[ctx.conversation_id] = None

        messages.append(_assistant_text_message(final_text, assistant_id, presented_view))
        await self._conversations.save_messages(ctx.conversation_id, messages, ctx.now)
        return TurnResult(
            assistant_message=final_text,
            sources=list(sources.values()),
            booking_draft=view,
            events=[],
        )

    async def _execute_tool(
        self,
        ctx: TurnContext,
        call: ModelToolCall,
        sources: dict[tuple[str, str], SourceRef],
    ) -> _ToolOutcome:
        try:
            arguments = validate_tool_arguments(call.name, call.arguments)
        except ToolValidationError as exc:
            return _ToolOutcome(invalid_tool_result(call, str(exc)))

        if call.name == "search_knowledge":
            return await self._search(arguments, sources)
        if call.name == "get_patient_bookings":
            return await self._list_bookings()
        if call.name == "update_booking_draft":
            return await self._update_draft(ctx, arguments)
        if call.name == "abandon_booking_draft":
            return await self._abandon_draft(ctx)
        if call.name == "create_booking":
            return _ToolOutcome(
                ToolResult.error(
                    "Booking requires an explicit confirmation of the current canonical summary.",
                    code="confirmation_required",
                )
            )
        return _ToolOutcome(invalid_tool_result(call, f"Unknown tool: {call.name}"))

    async def _search(
        self,
        arguments: dict[str, Any],
        sources: dict[tuple[str, str], SourceRef],
    ) -> _ToolOutcome:
        query = arguments["query"]
        raw_filters = arguments.get("filters")
        filters: QueryFilters | None = None
        if isinstance(raw_filters, dict):
            filters = {str(key): str(value) for key, value in raw_filters.items()}
        try:
            if not self._index.ready():
                await self._index.prewarm()
            documents = self._index.search(query, limit=5, filters=filters)
        except Exception as exc:
            logger.warning("Knowledge search failed (%s).", type(exc).__name__)
            return _ToolOutcome(
                ToolResult.error(
                    "The clinic knowledge base could not be searched right now.",
                    code="search_failed",
                )
            )

        results: list[dict[str, Any]] = []
        for document in documents:
            _record_source(document, sources)
            results.append(
                {
                    "document_id": document.document_id,
                    "source_file": document.source_file,
                    "record_id": document.record_id,
                    "text": document.text,
                    "metadata": dict(document.metadata),
                }
            )
        return _ToolOutcome(ToolResult.ok({"results": results}))

    async def _list_bookings(self) -> _ToolOutcome:
        try:
            bookings = await self._booking_api.list_bookings(PATIENT_ID)
        except BookingApiError as exc:
            return _ToolOutcome(
                ToolResult.error(exc.safe_message, code=exc.code or "booking_read_failed")
            )
        except Exception as exc:
            logger.warning("Booking read failed (%s).", type(exc).__name__)
            return _ToolOutcome(
                ToolResult.error(
                    "The booking service could not be reached. No booking data was read.",
                    code="booking_read_failed",
                )
            )
        return _ToolOutcome(bookings_tool_result(bookings))

    async def _update_draft(
        self,
        ctx: TurnContext,
        arguments: dict[str, Any],
    ) -> _ToolOutcome:
        try:
            update = await self._drafts.update(ctx.conversation_id, arguments)
        except Exception as exc:
            logger.warning("Draft update failed (%s).", type(exc).__name__)
            return _ToolOutcome(
                ToolResult.error(
                    "The booking draft could not be updated.",
                    code="draft_update_failed",
                )
            )

        if update.errors:
            return _ToolOutcome(
                ToolResult.error(
                    "; ".join(update.errors),
                    code="draft_invalid",
                    details={
                        "errors": list(update.errors),
                        "missing_fields": list(update.missing_fields),
                        "draft": _dump_draft(update.draft),
                    },
                )
            )

        if update.draft is None:
            return _ToolOutcome(
                ToolResult.ok(
                    {
                        "changed": update.changed,
                        "draft": None,
                        "missing_fields": list(update.missing_fields),
                    }
                )
            )

        draft = update.draft
        payload: dict[str, Any] = {
            "changed": update.changed,
            "draft": _dump_draft(draft),
            "missing_fields": list(update.missing_fields),
        }
        awaiting = draft.status == DraftStatus.AWAITING_CONFIRMATION.value
        if awaiting and not draft.missing_fields:
            payload["summary"] = canonical_summary(draft)
        return _ToolOutcome(
            ToolResult.ok(payload),
            presentation=draft if awaiting and not draft.missing_fields else None,
            presentation_changed=True,
        )

    async def _abandon_draft(self, ctx: TurnContext) -> _ToolOutcome:
        try:
            await self._drafts.abandon(ctx.conversation_id)
        except Exception as exc:
            logger.warning("Draft abandon failed (%s).", type(exc).__name__)
            return _ToolOutcome(
                ToolResult.error(
                    "The booking draft could not be cancelled.",
                    code="draft_abandon_failed",
                )
            )
        self._presented[ctx.conversation_id] = None
        return _ToolOutcome(
            ToolResult.ok({"abandoned": True}),
            presentation=None,
            presentation_changed=True,
        )

    async def _current_draft(self, conversation_id: str) -> BookingDraftView | None:
        try:
            return await self._drafts.get(conversation_id)
        except Exception as exc:
            logger.warning("Could not load current draft (%s).", type(exc).__name__)
            return None

    async def _load_patient_context(self) -> Any:
        loader = self._patient_context_loader
        if loader is None:
            return None
        try:
            value = loader(PATIENT_ID) if _loader_accepts_argument(loader) else loader()
            if inspect.isawaitable(value):
                value = await value
            return value
        except Exception as exc:
            logger.warning("Patient context loader failed (%s).", type(exc).__name__)
            return "Patient context is temporarily unavailable."


def build_controller(
    settings: Settings,
    session_factory: Any,
    clock: Clock | None = None,
    index: KnowledgeIndex | None = None,
) -> AgentController:
    """Wire the production controller.

    Retrieval and service imports are intentionally lazy so this module can be
    imported while those packages are being developed in parallel. ``index``
    lets the application reuse the already-prewarmed readiness index instead of
    loading a second embedding model.
    """
    from app.retrieval.index import build_knowledge_index
    from app.retrieval.patient_context import load_patient_context
    from app.services.conversations import ConversationService
    from app.services.drafts import DraftService

    active_clock = clock or SystemClock()
    knowledge_index = index or build_knowledge_index(settings, session_factory)

    def patient_context_loader(_patient_id: str) -> Any:
        return load_patient_context(session_factory)

    return AgentController(
        settings=settings,
        clock=active_clock,
        model_client=DeepSeekModelClient(settings),
        index=knowledge_index,
        drafts=DraftService(session_factory, active_clock, settings),
        conversations=ConversationService(session_factory, active_clock),
        booking_api=RestBookingApi(settings),
        patient_context_loader=patient_context_loader,
    )


def normalize_confirmation_text(text: str) -> str:
    normalized = _WHITESPACE.sub(" ", text.strip().lower())
    return _TRAILING_PUNCTUATION.sub("", normalized).strip()


def is_confirmation_phrase(text: str) -> bool:
    return normalize_confirmation_text(text) in _CONFIRMATION_PHRASES


def _eligible_confirmation(
    controller: AgentController,
    conversation_id: str,
    draft: BookingDraftView | None,
    last_assistant_id: str | None,
    last_assistant_content: str | None,
    last_presentation: tuple[str, int] | None,
    user_text: str,
) -> bool:
    if draft is None:
        return False
    if draft.status != DraftStatus.AWAITING_CONFIRMATION.value:
        return False
    if draft.missing_fields:
        return False
    if not is_confirmation_phrase(user_text):
        return False
    if not last_assistant_id:
        return False

    if conversation_id in controller._presented:
        tracked = controller._presented[conversation_id]
        if tracked is None:
            return False
        if tracked[0] != draft.version or tracked[1] != last_assistant_id:
            return False

    presented_version = draft.confirmation_version
    if presented_version != draft.version:
        return False
    presented_attribute = draft.confirmation_message_id
    if not presented_attribute or presented_attribute != last_assistant_id:
        return False
    if last_presentation is not None:
        return last_presentation == (draft.draft_id, draft.version)
    if not last_assistant_content:
        return False
    return canonical_summary(draft) in last_assistant_content


def _last_assistant(
    messages: Sequence[Mapping[str, Any]],
) -> tuple[str | None, str | None, tuple[str, int] | None]:
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        message_id = message.get("_cp_message_id")
        content = message.get("content")
        marker = message.get("_cp_presentation")
        presentation: tuple[str, int] | None = None
        if isinstance(marker, Mapping):
            draft_id = marker.get("draft_id")
            version = marker.get("version")
            if isinstance(draft_id, str) and isinstance(version, int):
                presentation = (draft_id, version)
        return (
            message_id if isinstance(message_id, str) and message_id else None,
            content if isinstance(content, str) else None,
            presentation,
        )
    return None, None, None


def _assistant_text_message(
    content: str,
    message_id: str,
    presented: BookingDraftView | None = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "role": "assistant",
        "content": content,
        "_cp_message_id": message_id,
    }
    if presented is not None:
        message["_cp_presentation"] = {
            "draft_id": presented.draft_id,
            "version": presented.version,
        }
    return message


def _assistant_tool_call_message(
    calls: Sequence[ModelToolCall],
    content: str | None,
    message_id: str | None = None,
) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": content or None,
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in calls
        ],
        "_cp_message_id": message_id or str(uuid.uuid4()),
    }


def _confirmation_tool_content(
    call: ModelToolCall,
    booking: BookingView | None,
    failure_message: str | None,
) -> str:
    if failure_message is not None:
        return ToolResult.error(failure_message, code="booking_failed").content
    if call.name != CONFIRMATION_TOOL:
        return ToolResult.error(
            "Only create_booking is available after confirmation.",
            code="unavailable_tool",
        ).content
    if booking is None:
        return ToolResult.error(INTERNAL_BOOKING_FAILURE_MESSAGE, code="booking_failed").content
    return booking_tool_result(booking).content


def _claims_booking_success(text: str) -> bool:
    return _BOOKING_SUCCESS_CLAIM.search(text) is not None


def _record_source(
    document: RetrievedDocument,
    sources: dict[tuple[str, str], SourceRef],
) -> None:
    key = (document.source_file, document.record_id)
    if key not in sources:
        sources[key] = SourceRef(source_file=document.source_file, record_id=document.record_id)


def _dump_draft(draft: BookingDraftView | None) -> dict[str, Any] | None:
    if draft is None:
        return None
    return draft.model_dump(mode="json")


def _trim_messages(messages: Sequence[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Keep the most recent messages without orphaning tool results.

    The current user message is always retained even if a tool loop temporarily
    exceeds the configured budget.
    """
    if limit <= 0 or len(messages) <= limit:
        return list(messages)

    start = len(messages) - limit
    while start < len(messages) and messages[start].get("role") == "tool":
        start += 1

    last_user = -1
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].get("role") == "user":
            last_user = index
            break
    if last_user >= 0 and start > last_user:
        start = last_user

    return list(messages[start:])


def _loader_accepts_argument(loader: Callable[..., Any]) -> bool:
    try:
        signature = inspect.signature(loader)
    except (TypeError, ValueError):
        return True
    for parameter in signature.parameters.values():
        if parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.VAR_POSITIONAL,
        ):
            return True
    return False


__all__ = [
    "AgentController",
    "BookingApiError",
    "booking_success_text",
    "build_controller",
    "is_confirmation_phrase",
    "normalize_confirmation_text",
]
