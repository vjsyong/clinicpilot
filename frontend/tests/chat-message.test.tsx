import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { ChatMessageView } from "../src/components/ChatMessage";
import type { BookingDraftView, BookingView, NextStep } from "../src/api/types";
import type { AssistantChatMessage } from "../src/lib/chat";

const booking: BookingView = {
  booking_id: "B2001",
  patient_id: "P001",
  doctor_id: "D104",
  doctor_name: "Dr. James Wilson",
  treatment_id: "T001",
  treatment_name: "Joint & Pain Consultation",
  clinic_id: "C001",
  clinic_name: "Metro Care Health Clinic",
  local_date: "2026-10-23",
  local_time: "09:00",
  timezone: "America/New_York",
  starts_at_utc: "2026-10-23T13:00:00Z",
  status: "Confirmed",
  notes: "Back pain",
};

const bookedDraft: BookingDraftView = {
  draft_id: "draft-1",
  version: 2,
  status: "booked",
  doctor_id: booking.doctor_id,
  doctor_name: booking.doctor_name,
  treatment_id: booking.treatment_id,
  treatment_name: booking.treatment_name,
  clinic_id: booking.clinic_id,
  clinic_name: booking.clinic_name,
  local_date: booking.local_date,
  local_time: booking.local_time,
  timezone: booking.timezone,
  starts_at_utc: booking.starts_at_utc,
  notes: booking.notes,
  missing_fields: [],
  booking_id: booking.booking_id,
};

const deleteStep: NextStep = {
  kind: "confirm_action",
  action_id: booking.booking_id,
  booking_id: booking.booking_id,
  action_booking: booking,
  missing_fields: [],
  suggestions: [],
  message: `Delete booking ${booking.booking_id}?`,
};

function assistantMessage(overrides: Partial<AssistantChatMessage> = {}): AssistantChatMessage {
  return {
    kind: "assistant",
    messageId: "assistant-1",
    text: `Delete booking ${booking.booking_id}?`,
    sources: [],
    tools: [],
    draft: bookedDraft,
    events: [],
    nextStep: deleteStep,
    ...overrides,
  };
}

function render(message: AssistantChatMessage): string {
  return renderToStaticMarkup(
    <ChatMessageView
      message={message}
      currentDraft={bookedDraft}
      inFlight={false}
      onSource={() => undefined}
      onConfirm={() => undefined}
    />,
  );
}

describe("ChatMessageView action cards", () => {
  it("renders only the delete confirmation, not a second booking draft card", () => {
    const html = render(assistantMessage());

    expect(html).toContain('data-testid="confirm-action"');
    expect(html).not.toContain('data-testid="booking-draft"');
  });

  it("still renders the booking draft when there is no action card", () => {
    const html = render(
      assistantMessage({
        text: "Here is the current booking summary.",
        draft: { ...bookedDraft, status: "awaiting_confirmation" },
        nextStep: {
          kind: "confirm_booking",
          draft_version: bookedDraft.version,
          missing_fields: [],
          suggestions: [],
        },
      }),
    );

    expect(html).toContain('data-testid="booking-draft"');
    expect(html).not.toContain('data-testid="confirm-action"');
  });
});
