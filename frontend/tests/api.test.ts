import { describe, expect, it, vi } from "vitest";

import { API_PATHS, ApiError, createApiClient } from "../src/api/client";
import { buildChatRequest, createPendingMessage } from "../src/lib/chat";
import type { BookingView, ChatResponse } from "../src/api/types";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function sampleBooking(overrides: Partial<BookingView> = {}): BookingView {
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

const chatResponse: ChatResponse = {
  conversation_id: "conversation-1",
  message_id: "message-1",
  assistant_message: "Which date would you prefer?",
  sources: [{ source_file: "doctors.csv", record_id: "D101" }],
  booking_draft: null,
  events: [],
};

describe("API client", () => {
  it("sends the exact chat contract body with same-origin credentials", async () => {
    const fetchMock = vi.fn(
      async (_input: string, _init?: RequestInit) => jsonResponse(chatResponse),
    );
    const client = createApiClient({ fetchImpl: fetchMock });
    const payload = buildChatRequest(
      null,
      createPendingMessage("hello", () => "message-1"),
    );

    await expect(client.sendChat(payload)).resolves.toEqual(chatResponse);

    expect(API_PATHS).toEqual({
      chat: "./api/chat",
      bookings: "./api/bookings",
      login: "./login",
      logout: "./logout",
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("./api/chat");
    expect(init?.method).toBe("POST");
    expect(init?.credentials).toBe("same-origin");
    expect(JSON.parse(String(init?.body))).toEqual({
      conversation_id: null,
      message_id: "message-1",
      message: "hello",
      patient_id: "P001",
    });
  });

  it("redirects once through the injected 401 handler", async () => {
    const onUnauthorized = vi.fn();
    const client = createApiClient({
      fetchImpl: async () =>
        jsonResponse({ error: { code: "unauthorized" } }, 401),
      onUnauthorized,
    });

    await expect(
      client.sendChat(
        buildChatRequest(null, createPendingMessage("hello", () => "message-1")),
      ),
    ).rejects.toMatchObject({ status: 401, code: "unauthorized" });
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it("surfaces the frozen error envelope", async () => {
    const client = createApiClient({
      fetchImpl: async () =>
        jsonResponse(
          {
            error: {
              code: "turn_in_progress",
              message: "A turn is already in progress.",
              retryable: true,
            },
            request_id: "request-1",
          },
          409,
        ),
    });

    const error = await client
      .sendChat(
        buildChatRequest(
          "conversation-1",
          createPendingMessage("hello", () => "message-1"),
        ),
      )
      .catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 409,
      code: "turn_in_progress",
      message: "A turn is already in progress.",
      retryable: true,
      requestId: "request-1",
    });
  });

  it("accepts either a bare bookings array or a bookings envelope", async () => {
    const booking = sampleBooking();
    const bare = createApiClient({
      fetchImpl: async () => jsonResponse([booking]),
    });
    expect(await bare.listBookings()).toEqual([booking]);

    const wrapped = createApiClient({
      fetchImpl: async () => jsonResponse({ bookings: [booking] }),
    });
    expect(await wrapped.listBookings()).toEqual([booking]);
  });

  it("rejects an unreadable bookings response", async () => {
    const client = createApiClient({
      fetchImpl: async () => jsonResponse({ unexpected: true }),
    });

    await expect(client.listBookings()).rejects.toMatchObject({
      code: "invalid_response",
    });
  });

  it("posts logout without rewriting the response", async () => {
    const fetchMock = vi.fn(
      async (_input: string, _init?: RequestInit) => new Response(null, { status: 204 }),
    );
    const client = createApiClient({ fetchImpl: fetchMock });

    await client.logout();

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("./logout");
    expect(init?.method).toBe("POST");
    expect(init?.credentials).toBe("same-origin");
  });

  it("does not throw on a failed logout request", async () => {
    const client = createApiClient({
      fetchImpl: async () => {
        throw new TypeError("network down");
      },
    });

    await expect(client.logout()).resolves.toBeUndefined();
  });
});
