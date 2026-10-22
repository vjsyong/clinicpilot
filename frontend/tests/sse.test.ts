import { describe, expect, it } from "vitest";

import { parseSseBlock, readSse } from "../src/lib/sse";
import type { ChatStreamEvent } from "../src/api/types";

describe("SSE parsing", () => {
  it("parses event and data lines", () => {
    expect(parseSseBlock('event: content\ndata: {"delta":"hi"}')).toEqual({
      event: "content",
      data: '{"delta":"hi"}',
    });
    expect(parseSseBlock(": keep-alive")).toBeNull();
  });

  it("reads events from a streaming response", async () => {
    const body = [
      'event: session\ndata: {"conversation_id":"c1","turn_id":"t1","message_id":"m1"}\n\n',
      'event: content\ndata: {"delta":"Hello"}\n\n',
      'event: done\ndata: {"assistant_message":"Hello"}\n\n',
    ].join("");
    const events: ChatStreamEvent[] = [];

    await readSse(new Response(body), (event) => {
      events.push(event);
    });

    expect(events.map((event) => event.event)).toEqual(["session", "content", "done"]);
    expect(events[1].data).toEqual({ delta: "Hello" });
  });

  it("tolerates malformed event data", async () => {
    const events: ChatStreamEvent[] = [];

    await readSse(new Response("event: status\ndata: not-json\n\n"), (event) => {
      events.push(event);
    });

    expect(events).toHaveLength(1);
    expect(events[0].event).toBe("status");
    expect(events[0].data).toEqual({});
  });
});
