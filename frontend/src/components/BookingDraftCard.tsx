import type { BookingDraftView, NextStep, SlotSuggestion } from "../api/types";

function valueOrFallback(value: string | null | undefined): string {
  return value && value.trim().length > 0 ? value : "Not set";
}

function statusTone(status: string): string {
  switch (status) {
    case "booked":
      return "badge ok";
    case "awaiting_confirmation":
      return "badge acc";
    case "cancelled":
      return "badge err";
    case "booking_in_progress":
      return "badge warn";
    default:
      return "badge";
  }
}

function humanize(value: string): string {
  return value.replaceAll("_", " ");
}

function fieldLabel(value: string): string {
  return {
    doctor_id: "doctor",
    treatment_id: "treatment",
    local_date: "date",
    local_time: "time",
    timezone: "timezone",
  }[value] ?? humanize(value);
}

interface BookingDraftCardProps {
  draft: BookingDraftView;
  nextStep?: NextStep | null;
  currentDraft?: BookingDraftView | null;
  inFlight?: boolean;
  onConfirm?: () => void;
  onChooseSlot?: (slot: SlotSuggestion) => void;
}

export function BookingDraftCard({
  draft,
  nextStep = null,
  currentDraft = null,
  inFlight = false,
  onConfirm,
  onChooseSlot,
}: BookingDraftCardProps) {
  const missing = draft.missing_fields ?? [];
  const awaiting = draft.status === "awaiting_confirmation";
  const isCurrent =
    currentDraft === null ||
    (currentDraft.draft_id === draft.draft_id && currentDraft.version === draft.version);
  const stale = currentDraft !== null && !isCurrent;
  const canConfirm =
    awaiting &&
    missing.length === 0 &&
    isCurrent &&
    !inFlight &&
    Boolean(onConfirm) &&
    nextStep?.kind === "confirm_booking";
  const suggestions =
    isCurrent && nextStep?.kind === "choose_slot" ? nextStep.suggestions : [];

  if (stale) {
    return (
      <div className="msg warn" role="status">
        This booking card was replaced by a newer summary.
      </div>
    );
  }

  return (
    <div
      className="proposal"
      data-testid="booking-draft"
      aria-label="Booking draft summary"
    >
      <div className="p-tag">
        {draft.editing_booking_id ? `Editing ${draft.editing_booking_id}` : "Booking draft"}
      </div>
      <div className="spread">
        <b>{valueOrFallback(draft.doctor_name)}</b>
        <span className={statusTone(draft.status)}>{humanize(draft.status)}</span>
      </div>

      <div className="kv">
        <span className="k">Treatment</span>
        <span>{valueOrFallback(draft.treatment_name)}</span>
        <span className="k">Clinic</span>
        <span>{valueOrFallback(draft.clinic_name)}</span>
        <span className="k">Date</span>
        <span>{valueOrFallback(draft.local_date)}</span>
        <span className="k">Time</span>
        <span>{valueOrFallback(draft.local_time)}</span>
        <span className="k">Timezone</span>
        <span>{valueOrFallback(draft.timezone)}</span>
      </div>

      {draft.notes ? <p className="sub">Notes: {draft.notes}</p> : null}

      {missing.length > 0 ? (
        <p className="sub">
          Still needed: {missing.map(fieldLabel).join(", ")}.
        </p>
      ) : null}

      {suggestions.length > 0 ? (
        <div className="stack">
          <div className="sub">
            Suggested clinic-local times. These are not verified clinician availability.
          </div>
          <div className="chips">
            {suggestions.map((slot) => (
              <button
                type="button"
                className="chip"
                key={`${slot.local_date}-${slot.local_time}`}
                disabled={inFlight}
                onClick={() => {
                  onChooseSlot?.(slot);
                }}
              >
                {slot.label}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {awaiting && missing.length === 0 && nextStep?.kind === "confirm_booking" ? (
        <p className="sub">
          Confirm this exact booking, or tell me what you would like to change.
        </p>
      ) : null}

      {canConfirm || (awaiting && missing.length === 0 && !onConfirm) ? (
        <div className="row">
          {canConfirm ? (
            <button
              type="button"
              className="btn primary"
              data-testid="confirm-booking"
              disabled={inFlight}
              onClick={onConfirm}
            >
              Confirm booking
            </button>
          ) : null}
          <button
            type="button"
            className="btn small"
            disabled={inFlight}
            onClick={() => {
              document.getElementById("chat-input")?.focus();
            }}
          >
            Change details
          </button>
        </div>
      ) : null}
    </div>
  );
}
