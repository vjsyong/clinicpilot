import { describe, expect, it } from "vitest";

import type { BookingView } from "../src/api/types";
import { bookingSlot, isUpcoming, temporalLabel } from "../src/lib/bookings";

function booking(overrides: Partial<BookingView>): BookingView {
  return {
    booking_id: "BK-100",
    patient_id: "P001",
    doctor_id: "D101",
    doctor_name: "Dr. Maya Chen",
    treatment_id: "T001",
    treatment_name: "General Consultation",
    clinic_id: "C001",
    clinic_name: "Downtown Clinic",
    local_date: "2026-11-17",
    local_time: "15:00",
    timezone: "America/New_York",
    starts_at_utc: "2026-11-17T20:00:00Z",
    status: "booked",
    notes: null,
    ...overrides,
  };
}

const NOW = Date.parse("2026-10-22T12:00:00Z");

describe("booking presentation", () => {
  it("marks a future non-cancelled booking as upcoming", () => {
    const upcoming = booking({});
    expect(isUpcoming(upcoming, NOW)).toBe(true);
    expect(temporalLabel(upcoming, NOW)).toBe("upcoming");
  });

  it("never presents a past booking as upcoming", () => {
    const past = booking({ starts_at_utc: "2026-09-01T20:00:00Z" });
    expect(isUpcoming(past, NOW)).toBe(false);
    expect(temporalLabel(past, NOW)).toBe("past");
  });

  it("never presents a cancelled booking as upcoming", () => {
    const cancelled = booking({ status: "cancelled" });
    expect(isUpcoming(cancelled, NOW)).toBe(false);
    expect(temporalLabel(cancelled, NOW)).toBe("cancelled");
  });

  it("never presents a completed booking as upcoming", () => {
    const completed = booking({ status: "completed" });
    expect(isUpcoming(completed, NOW)).toBe(false);
  });

  it("treats an unreadable timestamp as not upcoming", () => {
    expect(isUpcoming(booking({ starts_at_utc: "not-a-date" }), NOW)).toBe(false);
  });

  it("shows local date, local time, and timezone together", () => {
    expect(bookingSlot(booking({ timezone: "America/Los_Angeles" }))).toBe(
      "2026-11-17 at 15:00 (America/Los_Angeles)",
    );
  });
});
