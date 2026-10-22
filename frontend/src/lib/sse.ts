import type { ChatStreamEvent } from "../api/types";

export interface SseFrame {
  event: string;
  data: string;
}

export function parseSseBlock(block: string): SseFrame | null {
  let event = "";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      data.push(line.slice(5).trim());
    }
  }
  if (!event) {
    return null;
  }
  return { event, data: data.join("\n") };
}

export async function readSse(
  response: Response,
  onEvent: (event: ChatStreamEvent) => void,
): Promise<void> {
  if (!response.body) {
    throw new Error("The stream did not include a body.");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const frame = parseSseBlock(block);
      if (frame) {
        onEvent(toEvent(frame));
      }
      boundary = buffer.indexOf("\n\n");
    }
  }
}

function toEvent(frame: SseFrame): ChatStreamEvent {
  let data: unknown = {};
  if (frame.data) {
    try {
      data = JSON.parse(frame.data);
    } catch {
      data = {};
    }
  }
  return { event: frame.event, data } as ChatStreamEvent;
}
