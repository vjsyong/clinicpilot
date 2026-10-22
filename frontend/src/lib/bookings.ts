import type { BookingView } from "../api/types";

export type TemporalLabel = "upcoming" | "past" | "cancelled";

function normalizedStatus(booking: BookingView): string {
  return booking.status.trim().toLowerCase();
}

export function isUpcoming(booking: BookingView, now: number = Date.now()): boolean {
  const startsAt = Date.parse(booking.starts_at_utc);
  if (Number.isNaN(startsAt)) {
    return false;
  }
  const status = normalizedStatus(booking);
  return startsAt > now && status !== "cancelled" && status !== "completed";
}

export function temporalLabel(booking: BookingView, now: number = Date.now()): TemporalLabel {
  if (normalizedStatus(booking) === "cancelled") {
    return "cancelled";
  }
  return isUpcoming(booking, now) ? "upcoming" : "past";
}

export function bookingSlot(booking: BookingView): string {
  return `${booking.local_date} at ${booking.local_time} (${booking.timezone})`;
}
