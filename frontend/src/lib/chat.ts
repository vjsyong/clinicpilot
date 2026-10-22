import type {
  BookingDraftView,
  ChatEvent,
  ChatRequest,
  ConversationTranscript,
  NextStep,
  SlotSuggestion,
  SourceRef,
  ToolTrace,
} from "../api/types";
import { PATIENT_ID } from "../api/types";

export interface PendingMessage {
  messageId: string;
  text: string;
}

export interface FailedMessage extends PendingMessage {
  errorMessage: string;
}

export interface UserChatMessage {
  kind: "user";
  messageId: string;
  text: string;
  status: "sending" | "sent" | "failed";
  createdAt?: string;
}

export interface AssistantChatMessage {
  kind: "assistant";
  messageId: string;
  text: string;
  sources: SourceRef[];
  tools: ToolTrace[];
  draft: BookingDraftView | null;
  events: ChatEvent[];
  nextStep: NextStep | null;
  createdAt?: string;
  streaming?: boolean;
  statusLabel?: string;
  reasoning?: string;
  error?: string;
  stopped?: boolean;
}

export type ChatMessage = UserChatMessage | AssistantChatMessage;

let fallbackCounter = 0;

export function createMessageId(): string {
  const cryptoApi = globalThis.crypto;

  if (cryptoApi && typeof cryptoApi.randomUUID === "function") {
    return cryptoApi.randomUUID();
  }

  if (cryptoApi && typeof cryptoApi.getRandomValues === "function") {
    const bytes = new Uint8Array(16);
    cryptoApi.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
    return [
      hex.slice(0, 8),
      hex.slice(8, 12),
      hex.slice(12, 16),
      hex.slice(16, 20),
      hex.slice(20),
    ].join("-");
  }

  fallbackCounter += 1;
  return [
    "client",
    Date.now().toString(36),
    fallbackCounter.toString(36),
    Math.random().toString(36).slice(2, 10),
  ].join("-");
}

export function createPendingMessage(
  text: string,
  idFactory: () => string = createMessageId,
): PendingMessage {
  return { messageId: idFactory(), text };
}

export function markFailed(message: PendingMessage, errorMessage: string): FailedMessage {
  return {
    messageId: message.messageId,
    text: message.text,
    errorMessage,
  };
}

export function toRetry(message: FailedMessage): PendingMessage {
  return {
    messageId: message.messageId,
    text: message.text,
  };
}

export function buildChatRequest(
  conversationId: string | null,
  message: PendingMessage,
): ChatRequest {
  return {
    conversation_id: conversationId,
    message_id: message.messageId,
    message: message.text,
    patient_id: PATIENT_ID,
  };
}

export function messagesFromTranscript(transcript: ConversationTranscript): ChatMessage[] {
  const messages: ChatMessage[] = [];
  for (const turn of transcript.turns) {
    messages.push({
      kind: "user",
      messageId: turn.client_message_id,
      text: turn.user,
      status: turn.status === "failed" ? "failed" : "sent",
      createdAt: turn.created_at,
    });
    messages.push({
      kind: "assistant",
      messageId: `${turn.turn_id}-assistant`,
      text: turn.assistant ?? "",
      sources: turn.sources,
      tools: turn.tools,
      draft: turn.booking_draft ?? null,
      events: turn.events,
      nextStep: turn.next_step ?? null,
      createdAt: turn.created_at,
      statusLabel: turn.status === "in_progress" ? "Still working..." : undefined,
      error:
        turn.status === "failed" && !turn.assistant
          ? "This turn did not complete. Please retry."
          : undefined,
    });
  }
  return messages;
}

export function slotPrompt(slot: SlotSuggestion): string {
  return `Please use ${slot.label} (${slot.local_date} at ${slot.local_time} ${slot.timezone}).`;
}
