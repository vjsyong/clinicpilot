import type { KeyboardEvent, RefObject } from "react";

import type { BookingDraftView, SourceRef } from "../api/types";
import type { ChatMessage } from "../lib/chat";
import { BookingDraftCard } from "./BookingDraftCard";

interface ChatPanelProps {
  messages: ChatMessage[];
  input: string;
  inFlight: boolean;
  error: string | null;
  canRetry: boolean;
  draft: BookingDraftView | null;
  success: string | null;
  transcriptRef: RefObject<HTMLDivElement | null>;
  onInputChange: (value: string) => void;
  onSend: () => void;
  onRetry: () => void;
  onNewConversation: () => void;
}

function userStatus(status: "sending" | "sent" | "failed"): string {
  switch (status) {
    case "sending":
      return "Sending…";
    case "failed":
      return "Not sent";
    default:
      return "Sent";
  }
}

function SourceList({ sources }: { sources: SourceRef[] }) {
  if (sources.length === 0) {
    return null;
  }

  return (
    <div className="tools-list" role="list" aria-label="Sources">
      {sources.map((source, index) => (
        <span
          className="tool-chip"
          role="listitem"
          data-testid="source-ref"
          key={`${source.source_file}:${source.record_id}:${index}`}
        >
          {source.source_file}:{source.record_id}
        </span>
      ))}
    </div>
  );
}

export function ChatPanel({
  messages,
  input,
  inFlight,
  error,
  canRetry,
  draft,
  success,
  transcriptRef,
  onInputChange,
  onSend,
  onRetry,
  onNewConversation,
}: ChatPanelProps) {
  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      onSend();
    }
  }

  return (
    <section className="card" id="chat-panel" aria-labelledby="chat-heading">
      <div className="card-h">
        <h2 id="chat-heading">Assistant</h2>
        <button
          className="btn small"
          type="button"
          data-testid="new-conversation"
          onClick={onNewConversation}
          disabled={inFlight}
        >
          New conversation
        </button>
      </div>

      <div className="chat-flex">
        <div
          className="chat"
          role="log"
          aria-live="polite"
          aria-relevant="additions text"
          aria-label="Conversation transcript"
          ref={transcriptRef}
        >
          {messages.length === 0 && !inFlight ? (
            <div className="chat-empty">
              <div className="chat-empty-title">How can we help?</div>
              <div className="sub">
                Ask about clinics, doctors, treatments, or book an appointment for P001.
              </div>
            </div>
          ) : null}

          {messages.map((message) =>
            message.kind === "user" ? (
              <div className="crow user" data-testid="message-user" key={message.messageId}>
                <div className="avatar you" aria-hidden="true">
                  You
                </div>
                <div className="bubble user">
                  <div className="prose">{message.text}</div>
                  <div className="meta">{userStatus(message.status)}</div>
                </div>
              </div>
            ) : (
              <div
                className="crow ai"
                data-testid="message-assistant"
                key={message.messageId}
              >
                <div className="avatar ai" aria-hidden="true">
                  AI
                </div>
                <div className="bubble ai">
                  <div className="prose">{message.text}</div>
                  <SourceList sources={message.sources} />
                </div>
              </div>
            ),
          )}

          {inFlight ? (
            <div className="crow ai">
              <div className="avatar ai" aria-hidden="true">
                AI
              </div>
              <div className="bubble ai">
                <p className="sub" role="status">
                  Assistant is responding…
                </p>
              </div>
            </div>
          ) : null}

          {success ? (
            <div className="msg ok" role="status" data-testid="booking-success">
              {success}
            </div>
          ) : null}

          {error ? (
            <div className="msg err" role="alert" data-testid="error-banner">
              <div className="spread">
                <span>{error}</span>
                <button
                  className="btn small"
                  type="button"
                  data-testid="chat-retry"
                  onClick={onRetry}
                  disabled={!canRetry || inFlight}
                >
                  Retry
                </button>
              </div>
            </div>
          ) : null}

          {draft ? <BookingDraftCard draft={draft} /> : null}
        </div>

        <form
          className="composer"
          onSubmit={(event) => {
            event.preventDefault();
            onSend();
          }}
        >
          <label className="vh" htmlFor="chat-input">
            Message
          </label>
          <textarea
            id="chat-input"
            data-testid="chat-input"
            name="message"
            rows={2}
            value={input}
            disabled={inFlight}
            onChange={(event) => onInputChange(event.target.value)}
            onKeyDown={handleKeyDown}
            aria-describedby="chat-input-hint"
            placeholder="Ask about clinics, treatments, or appointments…"
          />
          <div className="comp-row">
            <span className="sub" id="chat-input-hint">
              Enter sends · Shift+Enter for a new line
            </span>
            <span className="row">
              <button
                className="btn primary"
                type="submit"
                data-testid="chat-send"
                disabled={inFlight || input.trim().length === 0}
              >
                Send
              </button>
            </span>
          </div>
        </form>
      </div>
    </section>
  );
}
