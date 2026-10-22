import { describe, expect, it } from "vitest";

import {
  buildChatRequest,
  createMessageId,
  createPendingMessage,
  markFailed,
  toRetry,
} from "../src/lib/chat";

describe("chat request helpers", () => {
  it("creates a user message with a client-generated UUID", () => {
    const message = createPendingMessage("Book a knee consultation");

    expect(message.text).toBe("Book a knee consultation");
    expect(message.messageId).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
  });

  it("generates distinct message ids", () => {
    expect(createMessageId()).not.toBe(createMessageId());
  });

  it("builds the exact contract body for the first turn", () => {
    const message = createPendingMessage("Hello", () => "fixed-message-id");

    expect(buildChatRequest(null, message)).toEqual({
      conversation_id: null,
      message_id: "fixed-message-id",
      message: "Hello",
      patient_id: "P001",
    });
  });

  it("reuses the same message id and text when a failed turn is retried", () => {
    const original = createPendingMessage("Book me in", () => "retry-me");
    const failed = markFailed(original, "Provider unavailable.");
    const retry = toRetry(failed);

    expect(retry).toEqual({ messageId: "retry-me", text: "Book me in" });
    expect(markFailed(retry, "still down").errorMessage).toBe("still down");
    expect(buildChatRequest("conversation-1", retry)).toEqual({
      conversation_id: "conversation-1",
      message_id: "retry-me",
      message: "Book me in",
      patient_id: "P001",
    });
  });

  it("keeps the conversation id returned by the first response", () => {
    const message = createPendingMessage("Next question", () => "second-message");

    expect(buildChatRequest("conversation-1", message).conversation_id).toBe(
      "conversation-1",
    );
  });
});
