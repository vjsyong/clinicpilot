import { useEffect, useState } from "react";

import type { BookingView } from "../api/types";
import { bookingSlot, temporalLabel } from "../lib/bookings";

interface BookingsPanelProps {
  bookings: BookingView[];
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
  onEdit: (booking: BookingView) => void;
  onDelete: (booking: BookingView) => Promise<void> | void;
  onReset: () => Promise<void> | void;
}

function toneFor(booking: BookingView): string {
  switch (temporalLabel(booking)) {
    case "upcoming":
      return "badge ok";
    case "cancelled":
      return "badge err";
    default:
      return "badge";
  }
}

function labelFor(booking: BookingView): string {
  switch (temporalLabel(booking)) {
    case "upcoming":
      return "upcoming";
    case "cancelled":
      return "cancelled";
    default:
      return "past";
  }
}

export function BookingsPanel({
  bookings,
  loading,
  error,
  onRefresh,
  onEdit,
  onDelete,
  onReset,
}: BookingsPanelProps) {
  const [armedDelete, setArmedDelete] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [resetting, setResetting] = useState(false);

  useEffect(() => {
    if (armedDelete === null) {
      return;
    }
    const timer = window.setTimeout(() => {
      setArmedDelete(null);
    }, 4000);
    return () => {
      window.clearTimeout(timer);
    };
  }, [armedDelete]);

  async function deleteBooking(booking: BookingView) {
    setDeleting(booking.booking_id);
    try {
      await onDelete(booking);
      setArmedDelete(null);
    } finally {
      setDeleting(null);
    }
  }

  async function resetDemo() {
    const confirmed = window.confirm(
      "Reset the shared demo? This restores P001's seed bookings B1001 and B1004, " +
        "clears all active chats and drafts, and keeps the audit record. " +
        "This affects every visitor.",
    );
    if (!confirmed) {
      return;
    }
    setResetting(true);
    try {
      await onReset();
    } finally {
      setResetting(false);
    }
  }

  return (
    <section className="card" id="bookings-panel" aria-labelledby="bookings-heading">
      <div className="card-h">
        <div>
          <h2 id="bookings-heading">Bookings</h2>
          <span className="sub">
            Patient P001
            {bookings.length > 0
              ? ` · ${bookings.length} ${bookings.length === 1 ? "appointment" : "appointments"}`
              : null}
          </span>
        </div>
        <div className="row">
          <button
            className="btn small"
            type="button"
            data-testid="refresh-bookings"
            onClick={onRefresh}
            disabled={loading}
          >
            {loading ? "Refreshing…" : "Refresh"}
          </button>
          <button
            className="btn small danger"
            type="button"
            data-testid="reset-demo"
            onClick={() => {
              void resetDemo();
            }}
            disabled={resetting}
          >
            {resetting ? "Resetting…" : "Reset demo"}
          </button>
        </div>
      </div>

      <div data-testid="bookings-table" aria-busy={loading}>
        {error ? (
          <div className="msg err" role="alert">
            <div className="spread">
              <span>{error}</span>
              <button className="btn small" type="button" onClick={onRefresh}>
                Try again
              </button>
            </div>
          </div>
        ) : null}

        {loading && bookings.length === 0 ? (
          <p className="sub" role="status">
            Loading bookings…
          </p>
        ) : null}

        {!loading && !error && bookings.length === 0 ? (
          <div className="empty">
            <h4>No appointments yet</h4>
            <p>Ask the assistant to find a doctor and book a time for P001.</p>
          </div>
        ) : null}

        {bookings.length > 0 ? (
          <div className="tablewrap">
            <table className="tbl mcards">
              <caption className="vh">Bookings for patient P001</caption>
              <thead>
                <tr>
                  <th scope="col">Date and time</th>
                  <th scope="col">Status</th>
                  <th scope="col">Doctor</th>
                  <th scope="col">Treatment</th>
                  <th scope="col">Clinic</th>
                  <th scope="col">Booking</th>
                  <th scope="col">Notes</th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                {bookings.map((booking) => (
                  <tr key={booking.booking_id} data-testid="booking-row">
                    <td>
                      <time dateTime={booking.starts_at_utc}>{bookingSlot(booking)}</time>
                    </td>
                    <td>
                      <span className={toneFor(booking)}>{labelFor(booking)}</span>{" "}
                      <span className="sub">{booking.status}</span>
                    </td>
                    <td>{booking.doctor_name}</td>
                    <td>{booking.treatment_name}</td>
                    <td>{booking.clinic_name}</td>
                    <td>
                      <span className="mono">{booking.booking_id}</span>
                    </td>
                    <td>{booking.notes && booking.notes.trim().length > 0 ? booking.notes : "—"}</td>
                    <td>
                      <div className="rowacts">
                        <button
                          type="button"
                          className="btn small"
                          data-testid="edit-booking"
                          onClick={() => {
                            onEdit(booking);
                          }}
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          className={armedDelete === booking.booking_id ? "btn small danger" : "btn small"}
                          data-testid="delete-booking"
                          aria-label={
                            armedDelete === booking.booking_id
                              ? `Confirm delete booking ${booking.booking_id}`
                              : `Delete booking ${booking.booking_id}`
                          }
                          disabled={deleting === booking.booking_id}
                          onClick={() => {
                            if (armedDelete === booking.booking_id) {
                              void deleteBooking(booking);
                            } else {
                              setArmedDelete(booking.booking_id);
                            }
                          }}
                        >
                          {armedDelete === booking.booking_id ? "Confirm delete" : "Delete"}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>
    </section>
  );
}
