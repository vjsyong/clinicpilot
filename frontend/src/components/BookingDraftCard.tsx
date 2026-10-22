import type { BookingDraftView } from "../api/types";

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

export function BookingDraftCard({ draft }: { draft: BookingDraftView }) {
  const missing = draft.missing_fields ?? [];
  const awaiting = draft.status === "awaiting_confirmation";

  return (
    <div
      className="proposal"
      data-testid="booking-draft"
      aria-label="Booking draft summary"
    >
      <div className="p-tag">Booking draft</div>
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

      {missing.length > 0 ? (
        <p className="sub">Still needed: {missing.join(", ")}.</p>
      ) : null}

      {awaiting ? (
        <p className="sub">
          Reply <b>yes</b> to confirm these exact details. Any change requires a new
          summary.
        </p>
      ) : null}

      {draft.notes ? <p className="sub">Notes: {draft.notes}</p> : null}
    </div>
  );
}
