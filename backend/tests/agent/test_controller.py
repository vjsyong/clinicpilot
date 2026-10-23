from __future__ import annotations

from typing import Any

import pytest
from app.agent.controller import is_confirmation_phrase, normalize_confirmation_text
from app.agent.summary import canonical_summary
from app.agent.tools import BookingApiError, ToolResult
from app.contracts import DraftStatus, ModelResponse, ProviderError
from app.settings import Settings
from tests.agent.fakes import (
    FakeBookingApi,
    FakeDraftView,
    FakeIndex,
    booking_view,
    build_harness,
    complete_draft,
    source,
    source_refs,
    text_response,
    tool_call,
    tool_response,
)


def _presented_messages(draft: FakeDraftView) -> list[dict[str, Any]]:
    return [
        {
            "role": "assistant",
            "content": canonical_summary(draft),
            "_cp_message_id": draft.confirmation_message_id or "msg-summary",
        }
    ]


async def test_collecting_draft_becomes_complete_and_presents_summary() -> None:
    draft = complete_draft(status=DraftStatus.COLLECTING_DETAILS.value, version=1)
    draft.local_time = None
    draft.missing_fields = ["local_time"]
    harness = build_harness(
        [
            tool_response(
                tool_call(
                    "update_booking_draft",
                    '{"local_time":"09:30"}',
                )
            ),
            text_response("Everything is ready."),
        ],
        draft=draft,
    )

    result = await harness.controller.handle_turn(harness.ctx("Use 9:30 in the morning"))

    assert result.booking_draft is not None
    assert result.booking_draft.status == DraftStatus.AWAITING_CONFIRMATION.value
    assert "Booking summary:" in result.assistant_message
    assert "09:30" in result.assistant_message
    assert harness.drafts.presentations
    message_id, version = harness.drafts.presentations[-1]
    assert version == result.booking_draft.version
    assert harness.conversations.messages[-1]["_cp_message_id"] == message_id
    assert harness.booking_api.create_calls == []
    assert harness.drafts.updates == [{"local_time": "09:30"}]


async def test_yes_please_authorizes_and_creates_exactly_once() -> None:
    draft = complete_draft(presented="msg-summary")
    booking = booking_view()
    api = FakeBookingApi(create_result=booking)
    harness = build_harness(
        [text_response("I will take care of that.")],
        draft=draft,
        messages=_presented_messages(draft),
        booking_api=api,
    )

    result = await harness.controller.handle_turn(harness.ctx("  Yes please.  "))

    assert harness.drafts.authorizations == ["turn-1"]
    assert api.create_calls == [("draft-1", 2)]
    assert len(api.create_calls) == 1
    assert len(result.events) == 1
    assert result.events[0].type == "booking_created"
    assert result.events[0].booking == booking
    assert harness.drafts.booked == [booking]
    assert result.booking_draft is not None
    assert result.booking_draft.status == DraftStatus.BOOKED.value
    assert "B2001" in result.assistant_message
    assert "Dr. Sarah Jenkins" in result.assistant_message
    assert "General Health Checkup" in result.assistant_message
    assert "2026-11-05 at 09:00" in result.assistant_message
    assert "America/New_York" in result.assistant_message
    tools = harness.model.calls[0]["tools"]
    assert [tool["function"]["name"] for tool in tools] == ["create_booking"]


async def test_yes_but_wednesday_is_a_correction_not_confirmation() -> None:
    draft = complete_draft(presented="msg-summary")
    harness = build_harness(
        [
            tool_response(
                tool_call(
                    "update_booking_draft",
                    '{"local_date":"2026-11-12"}',
                )
            ),
            text_response("I updated the date."),
        ],
        draft=draft,
        messages=_presented_messages(draft),
    )

    result = await harness.controller.handle_turn(harness.ctx("yes, but make it Wednesday"))

    assert harness.drafts.authorizations == []
    assert harness.booking_api.create_calls == []
    assert result.booking_draft is not None
    assert result.booking_draft.version == 3
    assert result.booking_draft.local_date == "2026-11-12"
    assert result.booking_draft.status == DraftStatus.AWAITING_CONFIRMATION.value
    assert "2026-11-12" in result.assistant_message
    assert harness.drafts.presentations
    assert harness.drafts.presentations[-1][1] == 3


async def test_unrelated_yes_after_interruption_cannot_authorize() -> None:
    draft = complete_draft(presented="msg-summary")
    policy_doc = source("clinics.csv", "C001")
    harness = build_harness(
        [
            tool_response(tool_call("search_knowledge", '{"query":"cancellation policy"}')),
            text_response("Cancellations need at least 24 hours notice."),
            text_response("Please review the current booking summary before confirming."),
        ],
        draft=draft,
        messages=_presented_messages(draft),
        index=FakeIndex(documents=[policy_doc]),
    )

    first = await harness.controller.handle_turn(
        harness.ctx("What is the cancellation policy?", "turn-policy")
    )
    assert "24 hours" in first.assistant_message
    assert first.booking_draft is not None
    assert first.booking_draft.status == DraftStatus.AWAITING_CONFIRMATION.value
    assert harness.drafts.clears >= 1
    assert harness.booking_api.create_calls == []
    assert first.next_step is not None
    assert first.next_step.kind != "confirm_booking"

    second = await harness.controller.handle_turn(harness.ctx("yes", "turn-yes"))

    assert second.assistant_message
    assert harness.drafts.authorizations == []
    assert harness.booking_api.create_calls == []


@pytest.mark.parametrize(
    "claim",
    [
        "Your appointment is booked and the bookings table has been refreshed.",
        "Your appointment is confirmed.",
        "Appointment confirmed for 2026-12-15 at 15:00.",
        "I have scheduled your appointment.",
        "Your appointment has been scheduled for next Tuesday.",
        "You're all set for your visit.",
        "I've got you booked in.",
        "The booking was created successfully.",
    ],
)
async def test_generated_success_claim_without_write_is_corrected(claim: str) -> None:
    draft = complete_draft(presented=None)
    harness = build_harness([text_response(claim)], draft=draft)

    result = await harness.controller.handle_turn(harness.ctx("hello"))

    assert harness.booking_api.create_calls == []
    assert result.events == []
    assert "No booking was created" in result.assistant_message
    assert "Booking summary:" in result.assistant_message
    assert harness.drafts.presentations


async def test_generated_success_claim_without_a_draft_does_not_mention_a_saved_draft() -> None:
    harness = build_harness([text_response("Your appointment has been confirmed.")])

    result = await harness.controller.handle_turn(harness.ctx("hello"))

    assert harness.booking_api.create_calls == []
    assert result.events == []
    assert "No booking was created" in result.assistant_message
    assert "draft is still saved" not in result.assistant_message
    assert harness.drafts.presentations == []


async def test_confirmation_rejected_when_last_assistant_id_does_not_match() -> None:
    draft = complete_draft(presented="msg-old")
    harness = build_harness(
        [text_response("Please review the current summary and confirm again.")],
        draft=draft,
        messages=[
            {
                "role": "assistant",
                "content": canonical_summary(draft),
                "_cp_message_id": "msg-new",
            }
        ],
    )

    result = await harness.controller.handle_turn(harness.ctx("yes"))

    assert result.assistant_message
    assert harness.drafts.authorizations == []
    assert harness.booking_api.create_calls == []
    assert harness.drafts.clears >= 1


async def test_booking_api_failure_preserves_draft_and_marks_failed() -> None:
    draft = complete_draft(presented="msg-summary")
    version = draft.version
    api = FakeBookingApi(
        create_error=BookingApiError(
            "The booking service is temporarily unavailable.",
            status_code=503,
            retryable=True,
        )
    )
    harness = build_harness(
        [tool_response(tool_call("create_booking"))],
        draft=draft,
        messages=_presented_messages(draft),
        booking_api=api,
    )

    result = await harness.controller.handle_turn(harness.ctx("yes"))

    assert result.events == []
    assert harness.drafts.failures == 1
    assert harness.drafts.booked == []
    assert api.create_calls == [("draft-1", version)]
    assert result.booking_draft is not None
    assert result.booking_draft.status == DraftStatus.AWAITING_CONFIRMATION.value
    assert result.booking_draft.version == version
    assert "draft is still saved" in result.assistant_message
    assert "Booking summary:" in result.assistant_message


async def test_provider_failure_on_normal_turn_raises_and_performs_no_write() -> None:
    harness = build_harness([ProviderError("provider down")])

    with pytest.raises(ProviderError):
        await harness.controller.handle_turn(harness.ctx("hello"))

    assert harness.conversations.saves == []
    assert harness.booking_api.create_calls == []
    assert harness.booking_api.list_calls == []
    assert harness.drafts.updates == []
    assert harness.drafts.presentations == []


async def test_confirmation_provider_failure_still_reports_persisted_booking() -> None:
    draft = complete_draft(presented="msg-summary")
    booking = booking_view(booking_id="B2999")
    api = FakeBookingApi(create_result=booking)
    harness = build_harness(
        [ProviderError("provider down")],
        draft=draft,
        messages=_presented_messages(draft),
        booking_api=api,
    )

    result = await harness.controller.handle_turn(harness.ctx("yes please"))

    assert api.create_calls == [("draft-1", 2)]
    assert len(result.events) == 1
    assert result.events[0].booking is not None
    assert result.events[0].booking.booking_id == "B2999"
    assert "B2999" in result.assistant_message
    assert harness.drafts.booked == [booking]


async def test_success_does_not_need_a_post_write_model_call() -> None:
    draft = complete_draft(presented="msg-summary")
    booking = booking_view(booking_id="B2777")
    harness = build_harness(
        [
            text_response("Checking..."),
            ProviderError("the extra call must not happen"),
        ],
        draft=draft,
        messages=_presented_messages(draft),
        booking_api=FakeBookingApi(create_result=booking),
    )

    result = await harness.controller.handle_turn(harness.ctx("yes"))

    assert len(harness.model.calls) == 1
    assert "B2777" in result.assistant_message
    assert len(result.events) == 1


async def test_create_booking_outside_authorized_confirmation_is_refused() -> None:
    harness = build_harness(
        [
            tool_response(tool_call("create_booking")),
            text_response("I need the canonical summary confirmed first."),
        ]
    )

    result = await harness.controller.handle_turn(harness.ctx("book it"))

    assert result.assistant_message
    assert harness.booking_api.create_calls == []
    assert harness.drafts.authorizations == []
    tool_messages = [
        message for message in harness.conversations.messages if message["role"] == "tool"
    ]
    assert len(tool_messages) == 1
    assert '"confirmation_required"' in tool_messages[0]["content"]


async def test_abandon_booking_draft_calls_the_store() -> None:
    draft = complete_draft(presented="msg-summary")
    harness = build_harness(
        [
            tool_response(tool_call("abandon_booking_draft")),
            text_response("I cancelled the draft."),
        ],
        draft=draft,
        messages=_presented_messages(draft),
    )

    result = await harness.controller.handle_turn(harness.ctx("forget it"))

    assert harness.drafts.abandoned == 1
    assert harness.booking_api.create_calls == []
    assert result.booking_draft is not None
    assert result.booking_draft.status == DraftStatus.CANCELLED.value
    assert "cancelled" in result.assistant_message.casefold()


async def test_tool_rounds_are_bounded() -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        max_tool_rounds=2,
        max_history_messages=40,
        deepseek_api_key="",
    )
    api = FakeBookingApi(bookings=[booking_view()])
    harness = build_harness(
        [
            tool_response(tool_call("get_patient_bookings", "{}", "call-a")),
            tool_response(tool_call("get_patient_bookings", "{}", "call-b")),
        ],
        settings=settings,
        booking_api=api,
    )

    result = await harness.controller.handle_turn(harness.ctx("show my bookings"))

    assert len(harness.model.calls) == 2
    assert len(api.list_calls) == 2
    assert api.list_calls == ["P001", "P001"]
    assert result.assistant_message


async def test_invalid_tool_name_is_rejected_without_execution() -> None:
    harness = build_harness(
        [
            tool_response(tool_call("delete_everything", "{}")),
            text_response("I cannot do that."),
        ]
    )

    result = await harness.controller.handle_turn(harness.ctx("delete everything"))

    assert result.assistant_message == "I cannot do that."
    tool_messages = [
        message for message in harness.conversations.messages if message["role"] == "tool"
    ]
    assert len(tool_messages) == 1
    assert "Unknown tool" in tool_messages[0]["content"]
    assert harness.booking_api.create_calls == []


async def test_patient_record_tool_returns_server_owned_context() -> None:
    context = "Treatment history: Blood pressure normal (120/80)."
    harness = build_harness(
        [
            tool_response(tool_call("get_patient_record", "{}")),
            text_response("Your last recorded blood pressure was 120/80."),
        ],
        patient_context=lambda _patient_id: context,
    )

    result = await harness.controller.handle_turn(
        harness.ctx("What is my last measured blood pressure?")
    )

    assert "120/80" in result.assistant_message
    tool_messages = [
        message for message in harness.conversations.messages if message["role"] == "tool"
    ]
    assert len(tool_messages) == 1
    assert "120/80" in tool_messages[0]["content"]
    assert harness.booking_api.create_calls == []


def _assert_paired(messages: list[dict[str, Any]]) -> None:
    call_ids: set[str] = set()
    for message in messages:
        if message.get("role") == "assistant":
            for call in message.get("tool_calls") or []:
                call_ids.add(call["id"])
        elif message.get("role") == "tool":
            assert message["tool_call_id"] in call_ids, "orphaned tool result"


async def test_tool_call_result_pairing_survives_history_trimming() -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        max_tool_rounds=4,
        max_history_messages=10,
        deepseek_api_key="",
    )
    old_messages: list[dict[str, Any]] = [
        {"role": "user", "content": "old 0", "_cp_message_id": "u-old-0"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "old-call-1",
                    "type": "function",
                    "function": {"name": "get_patient_bookings", "arguments": "{}"},
                }
            ],
            "_cp_message_id": "a-old-1",
        },
        {"role": "tool", "tool_call_id": "old-call-1", "content": "{}"},
        {"role": "assistant", "content": "old answer 1", "_cp_message_id": "a-old-2"},
        {"role": "user", "content": "old 1", "_cp_message_id": "u-old-1"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "old-call-2",
                    "type": "function",
                    "function": {"name": "get_patient_bookings", "arguments": "{}"},
                }
            ],
            "_cp_message_id": "a-old-3",
        },
        {"role": "tool", "tool_call_id": "old-call-2", "content": "{}"},
        {"role": "assistant", "content": "old answer 2", "_cp_message_id": "a-old-4"},
        {"role": "user", "content": "old 2", "_cp_message_id": "u-old-2"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "old-call-3",
                    "type": "function",
                    "function": {"name": "get_patient_bookings", "arguments": "{}"},
                }
            ],
            "_cp_message_id": "a-old-5",
        },
        {"role": "tool", "tool_call_id": "old-call-3", "content": "{}"},
        {"role": "assistant", "content": "old answer 3", "_cp_message_id": "a-old-6"},
    ]
    harness = build_harness(
        [
            tool_response(tool_call("get_patient_bookings", "{}", "new-call")),
            text_response("Here are your bookings."),
        ],
        messages=old_messages,
        settings=settings,
        booking_api=FakeBookingApi(bookings=[]),
    )

    result = await harness.controller.handle_turn(harness.ctx("show bookings", "u-new"))

    assert result.assistant_message == "Here are your bookings."
    model_messages = harness.model.calls[0]["messages"]
    history = model_messages[1:]
    assert len(history) <= settings.max_history_messages
    assert history[0]["role"] != "tool"
    _assert_paired(history)
    assert history[-1]["_cp_message_id"] == "u-new"


async def test_sources_are_deduped_and_bookings_use_p001_only() -> None:
    doctor = source("doctors.csv", "D104")
    treatment = source("treatments.csv", "T005")
    harness = build_harness(
        [
            tool_response(
                tool_call("search_knowledge", '{"query":"knee pain"}', "s1"),
                tool_call("search_knowledge", '{"query":"knee specialist"}', "s2"),
                tool_call("get_patient_bookings", "{}", "b1"),
            ),
            text_response("Dr. James Wilson in Orthopedics can assess your knee."),
        ],
        index=FakeIndex(documents=[doctor, treatment, doctor]),
        booking_api=FakeBookingApi(bookings=[booking_view()]),
    )

    result = await harness.controller.handle_turn(harness.ctx("my knee hurts"))

    assert source_refs(result.sources) == {
        ("doctors.csv", "D104"),
        ("treatments.csv", "T005"),
    }
    assert len(result.sources) == 2
    assert harness.booking_api.list_calls == ["P001"]
    assert len(harness.index.calls) == 2

    tool_messages = [
        message for message in harness.conversations.messages if message["role"] == "tool"
    ]
    assert any("B2001" in message["content"] for message in tool_messages)


def test_confirmation_normalization_is_narrow() -> None:
    assert is_confirmation_phrase("  YES!!! ")
    assert is_confirmation_phrase("Yes, Please.".replace(",", ""))
    assert normalize_confirmation_text("  Go   ahead.  ") == "go ahead"
    assert not is_confirmation_phrase("yes, but Wednesday")
    assert not is_confirmation_phrase("yes please also book a taxi")
    assert not is_confirmation_phrase("ok")


def test_tool_result_helpers_are_compact_json() -> None:
    result = ToolResult.ok({"value": 1})
    assert result.content == '{"ok":true,"value":1}'
    error = ToolResult.error("bad", code="x")
    assert error.is_error
    assert '"ok":false' in error.content
    assert '"code":"x"' in error.content


def test_model_response_helpers_do_not_mutate() -> None:
    response = ModelResponse(content="x")
    assert response.tool_calls == []


@pytest.mark.parametrize(
    "claim",
    [
        "Your appointment is confirmed.",
        "Appointment confirmed for 2026-12-15 at 15:00.",
        "I have scheduled your appointment.",
        "Your appointment has been scheduled.",
        "You're all set for your appointment.",
        "I've booked that for you.",
    ],
)
async def test_unpersisted_success_variants_are_not_forwarded(claim: str) -> None:
    harness = build_harness([text_response(claim)])

    result = await harness.controller.handle_turn(harness.ctx("Book an appointment"))

    assert result.events == []
    assert harness.booking_api.create_calls == []
    assert result.assistant_message != claim
    assert "No booking was created" in result.assistant_message


async def test_non_booking_prose_is_not_treated_as_a_success_claim() -> None:
    answer = "To book an appointment, ask me for a date and time."
    harness = build_harness([text_response(answer)])

    result = await harness.controller.handle_turn(harness.ctx("How do I book?"))

    assert result.assistant_message == answer


async def test_success_claim_for_an_existing_booking_uses_canonical_details() -> None:
    draft = complete_draft(status=DraftStatus.BOOKED.value, presented=None)
    draft.booking_id = "B2001"
    harness = build_harness(
        [text_response("Your appointment is confirmed.")],
        draft=draft,
    )

    result = await harness.controller.handle_turn(harness.ctx("Is my appointment confirmed?"))

    assert result.events == []
    assert "B2001" in result.assistant_message
    assert "No booking was created" not in result.assistant_message


async def test_regeneration_does_not_duplicate_the_existing_user_message() -> None:
    harness = build_harness(
        [text_response("Answer.")],
        messages=[
            {
                "role": "user",
                "content": "hello",
                "_cp_message_id": "turn-regen",
            }
        ],
    )

    await harness.controller.handle_turn(harness.ctx("hello", "turn-regen"))

    users = [message for message in harness.conversations.messages if message.get("role") == "user"]
    assert len(users) == 1
    assert users[0]["_cp_message_id"] == "turn-regen"
    assert users[0]["content"] == "hello"


async def test_confirmation_stream_emits_booking_tool_events() -> None:
    booking = booking_view()
    draft = complete_draft(presented="msg-summary")
    harness = build_harness(
        [text_response("Confirmed.")],
        draft=draft,
        messages=_presented_messages(draft),
        booking_api=FakeBookingApi(create_result=booking),
    )
    events: list[tuple[str, dict[str, Any]]] = []

    async def emit(event: str, data: dict[str, Any]) -> None:
        events.append((event, data))

    result = await harness.controller.handle_turn(harness.ctx("yes"), emit=emit)

    assert result.events[0].type == "booking_created"
    starts = [data for name, data in events if name == "tool_start"]
    ends = [data for name, data in events if name == "tool_end"]
    assert starts[0]["name"] == "create_booking"
    assert ends[0]["ok"] is True
    assert booking.booking_id in ends[0]["summary"]


def _incomplete_slot_draft():
    return complete_draft(presented=None).model_copy(
        update={
            "local_date": None,
            "local_time": None,
            "starts_at_utc": None,
            "missing_fields": ["local_date", "local_time"],
            "status": DraftStatus.COLLECTING_DETAILS.value,
        }
    )


async def test_incomplete_yes_is_replaced_with_dated_suggestions() -> None:
    draft = _incomplete_slot_draft()
    harness = build_harness(
        [text_response('To book, review the summary and reply "yes".')],
        draft=draft,
    )

    result = await harness.controller.handle_turn(harness.ctx("yes"))

    assert harness.booking_api.create_calls == []
    assert result.next_step is not None
    assert result.next_step.kind == "choose_slot"
    assert result.next_step.suggestions
    assert "Suggested clinic-local times" in result.assistant_message
    assert 'reply "yes"' not in result.assistant_message
    assert "Still need" in result.assistant_message or "still need" in result.assistant_message


async def test_patient_reported_pain_is_preserved_in_the_draft_notes() -> None:
    draft = _incomplete_slot_draft()
    harness = build_harness(
        [text_response("Which day would you like?")],
        draft=draft,
    )

    result = await harness.controller.handle_turn(harness.ctx("My knee hurts"))

    assert result.booking_draft is not None
    assert result.booking_draft.notes == "Patient reports: My knee hurts"
    assert harness.drafts.draft is not None
    assert harness.drafts.draft.notes == "Patient reports: My knee hurts"


async def test_requesting_the_summary_re_presents_and_returns_confirm() -> None:
    draft = complete_draft(presented=None)
    harness = build_harness(
        [text_response("Here is the current booking summary.")],
        draft=draft,
    )

    result = await harness.controller.handle_turn(harness.ctx("Show me the booking summary"))

    assert result.next_step is not None
    assert result.next_step.kind == "confirm_booking"
    assert "Booking summary:" in result.assistant_message
    assert harness.drafts.presentations


async def test_complete_draft_returns_a_confirm_step_and_version() -> None:
    draft = complete_draft(presented="msg-summary")
    harness = build_harness(
        [text_response("Here is the summary again.")],
        draft=draft,
        messages=_presented_messages(draft),
    )

    result = await harness.controller.handle_turn(harness.ctx("What is the summary?"))

    assert result.next_step is not None
    assert result.next_step.kind == "confirm_booking"
    assert result.next_step.draft_version == draft.version


async def test_delete_booking_requires_a_separate_explicit_confirmation() -> None:
    booking = booking_view()
    harness = build_harness(
        [
            tool_response(
                tool_call(
                    "delete_patient_booking",
                    '{"booking_id":"B2001"}',
                )
            ),
            text_response("I can remove that booking."),
        ],
        booking_api=FakeBookingApi(bookings=[booking], delete_result=booking),
    )

    first = await harness.controller.handle_turn(harness.ctx("Delete booking B2001"))

    assert harness.booking_api.delete_calls == []
    assert first.next_step is not None
    assert first.next_step.kind == "confirm_action"
    assert first.next_step.action_booking is not None
    assert first.next_step.action_booking.booking_id == "B2001"
    assert "Reply yes" in first.assistant_message

    second = await harness.controller.handle_turn(harness.ctx("yes"))

    assert harness.booking_api.delete_calls == ["B2001"]
    assert second.events[0].type == "booking_deleted"
    assert second.events[0].booking is not None
    assert "removed from the active list" in second.assistant_message
    assert "audit record is retained" in second.assistant_message


async def test_delete_proposal_does_not_attach_a_stale_booked_draft_card() -> None:
    booking = booking_view(booking_id="B2001")
    booked_draft = complete_draft(status=DraftStatus.BOOKED.value, presented=None).model_copy(
        update={"booking_id": "B2001"}
    )
    harness = build_harness(
        [
            tool_response(tool_call("delete_patient_booking", '{"booking_id":"B2001"}')),
            text_response("I can remove that booking."),
        ],
        draft=booked_draft,
        booking_api=FakeBookingApi(bookings=[booking], delete_result=booking),
    )
    events: list[tuple[str, dict[str, Any]]] = []

    async def emit(event: str, data: dict[str, Any]) -> None:
        events.append((event, data))

    result = await harness.controller.handle_turn(harness.ctx("Delete booking B2001"), emit=emit)

    assert result.next_step is not None
    assert result.next_step.kind == "confirm_action"
    assert result.booking_draft is None
    assert [event for event, _ in events if event == "draft"] == []


@pytest.mark.parametrize(
    "answer",
    [
        "Yes, Metro Care Health Clinic is open on weekdays.",
        "I can confirm the clinic opens at 08:00 on weekdays.",
    ],
)
async def test_a_normal_answer_is_not_replaced_with_booking_guidance(answer: str) -> None:
    harness = build_harness([text_response(answer)])

    result = await harness.controller.handle_turn(harness.ctx("Is the clinic open?"))

    assert result.assistant_message == answer
    assert "Tell me the doctor" not in result.assistant_message


async def test_delete_is_not_executed_by_a_non_confirmation() -> None:
    booking = booking_view()
    harness = build_harness(
        [
            tool_response(tool_call("delete_patient_booking", '{"booking_id":"B2001"}')),
            text_response("I can remove that booking."),
            text_response("Let me know if you want to proceed."),
        ],
        booking_api=FakeBookingApi(bookings=[booking], delete_result=booking),
    )

    await harness.controller.handle_turn(harness.ctx("Delete booking B2001"))
    await harness.controller.handle_turn(harness.ctx("Actually, what are the hours?"))

    assert harness.booking_api.delete_calls == []


async def test_deleting_the_current_created_booking_clears_the_draft() -> None:
    booking = booking_view(booking_id="B2001")
    booked_draft = complete_draft(status=DraftStatus.BOOKED.value, presented=None).model_copy(
        update={"booking_id": "B2001"}
    )
    harness = build_harness(
        [
            tool_response(tool_call("delete_patient_booking", '{"booking_id":"B2001"}')),
            text_response("I can remove that booking."),
        ],
        draft=booked_draft,
        booking_api=FakeBookingApi(bookings=[booking], delete_result=booking),
    )

    first = await harness.controller.handle_turn(harness.ctx("Delete booking B2001"))
    assert first.next_step is not None
    assert first.next_step.kind == "confirm_action"

    second = await harness.controller.handle_turn(harness.ctx("yes"))

    assert harness.booking_api.delete_calls == ["B2001"]
    assert harness.drafts.abandoned == 1
    assert second.booking_draft is None
    assert second.events[0].type == "booking_deleted"


async def test_yes_does_not_recover_a_booked_draft_without_a_pending_action() -> None:
    draft = complete_draft(status=DraftStatus.BOOKED.value, presented=None).model_copy(
        update={"booking_id": "B2001"}
    )
    harness = build_harness([text_response("I can help with that.")], draft=draft)

    result = await harness.controller.handle_turn(harness.ctx("yes"))

    assert harness.booking_api.create_calls == []
    assert "Booking confirmed." not in result.assistant_message


async def test_bulk_delete_proposals_are_confirmed_and_deleted_together() -> None:
    first_booking = booking_view(booking_id="B2001")
    second_booking = booking_view(booking_id="B2002", local_time="10:00")
    harness = build_harness(
        [
            tool_response(
                tool_call("delete_patient_booking", '{"booking_id":"B2001"}', "call-1"),
                tool_call("delete_patient_booking", '{"booking_id":"B2002"}', "call-2"),
            ),
            text_response("I can remove both bookings."),
        ],
        booking_api=FakeBookingApi(bookings=[first_booking, second_booking]),
    )

    first = await harness.controller.handle_turn(harness.ctx("Cancel all of my bookings"))

    assert first.next_step is not None
    assert first.next_step.kind == "confirm_action"
    assert [booking.booking_id for booking in first.next_step.action_bookings] == [
        "B2001",
        "B2002",
    ]
    assert harness.booking_api.delete_calls == []

    second = await harness.controller.handle_turn(harness.ctx("yes"))

    assert harness.booking_api.delete_calls == ["B2001", "B2002"]
    assert [event.booking.booking_id for event in second.events if event.booking is not None] == [
        "B2001",
        "B2002",
    ]
    assert "B2001" in second.assistant_message
    assert "B2002" in second.assistant_message


async def test_bulk_delete_reports_partial_failures() -> None:
    first_booking = booking_view(booking_id="B2001")
    second_booking = booking_view(booking_id="B2002", local_time="10:00")
    harness = build_harness(
        [
            tool_response(
                tool_call("delete_patient_booking", '{"booking_id":"B2001"}', "call-1"),
                tool_call("delete_patient_booking", '{"booking_id":"B2002"}', "call-2"),
            ),
            text_response("I can remove both bookings."),
        ],
        booking_api=FakeBookingApi(
            bookings=[first_booking, second_booking],
            delete_errors={"B2002": BookingApiError("Booking service unavailable.")},
        ),
    )

    await harness.controller.handle_turn(harness.ctx("Cancel all of my bookings"))
    result = await harness.controller.handle_turn(harness.ctx("yes"))

    assert harness.booking_api.delete_calls == ["B2001", "B2002"]
    assert [event.booking.booking_id for event in result.events if event.booking] == ["B2001"]
    assert "B2001" in result.assistant_message
    assert "Could not remove: B2002" in result.assistant_message


async def test_delete_confirmation_is_bound_to_the_last_assistant_message() -> None:
    booking = booking_view(booking_id="B2001")
    harness = build_harness(
        [
            tool_response(tool_call("delete_patient_booking", '{"booking_id":"B2001"}')),
            text_response("I can remove that booking."),
            text_response("Anything else?"),
        ],
        booking_api=FakeBookingApi(bookings=[booking], delete_result=booking),
    )

    first = await harness.controller.handle_turn(harness.ctx("Delete booking B2001"))
    assert first.next_step is not None
    assert first.next_step.kind == "confirm_action"

    harness.conversations.messages.append(
        {
            "role": "assistant",
            "content": "Anything else?",
            "_cp_message_id": "other-message",
        }
    )
    await harness.controller.handle_turn(harness.ctx("yes"))

    assert harness.booking_api.delete_calls == []


async def test_reset_is_proposed_but_never_executed_by_the_model() -> None:
    harness = build_harness(
        [
            tool_response(tool_call("request_demo_reset", "{}")),
            text_response("I can reset the demo."),
        ]
    )

    result = await harness.controller.handle_turn(harness.ctx("Reset the demo"))

    assert result.next_step is not None
    assert result.next_step.kind == "confirm_action"
    assert result.next_step.action_id == "reset"
    assert "Reset the shared demo workspace?" in result.assistant_message
    assert result.events == []
