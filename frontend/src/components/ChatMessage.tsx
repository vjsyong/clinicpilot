import { useState } from "react";

import type { BookingView, SourceRef } from "../api/types";
import type { AssistantChatMessage, UserChatMessage } from "../lib/chat";
import { sourceLabel, sourceKey } from "../lib/sources";
import { BookingDraftCard } from "./BookingDraftCard";
import { Markdown } from "./Markdown";
import { ToolTrace } from "./ToolTrace";

interface ChatMessageProps {
  message: UserChatMessage | AssistantChatMessage;
  onSource: (source: SourceRef) => void;
  onRegenerate?: (message: AssistantChatMessage) => void;
}

function userStatus(status: UserChatMessage["status"]): string {
  switch (status) {
    case "sending":
      return "Sending…";
    case "failed":
      return "Not sent";
    default:
      return "Sent";
  }
}

function timeLabel(value?: string): string {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function SourceList({
  sources,
  onSource,
}: {
  sources: SourceRef[];
  onSource: (source: SourceRef) => void;
}) {
  if (sources.length === 0) {
    return null;
  }
  return (
    <div className="tools-list" aria-label="Cited sources">
      {sources.map((source) => (
        <button
          type="button"
          className="tool-chip"
          data-testid="source-ref"
          key={sourceKey(source)}
          title={`${source.source_file}:${source.record_id}`}
          onClick={() => {
            onSource(source);
          }}
        >
          {sourceLabel(source)} {source.record_id}
        </button>
      ))}
    </div>
  );
}

function BookingSuccess({ booking }: { booking: BookingView }) {
  return (
    <div className="msg ok" role="status" data-testid="booking-success">
      <b>Booking confirmed.</b> {booking.booking_id} · {booking.local_date} at{" "}
      {booking.local_time} ({booking.timezone})
    </div>
  );
}

export function ChatMessageView({ message, onSource, onRegenerate }: ChatMessageProps) {
  const [copied, setCopied] = useState(false);

  if (message.kind === "user") {
    return (
      <div className="crow user" data-testid="message-user">
        <div className="avatar you" aria-hidden="true">
          You
        </div>
        <div className="bubble user">
          <div className="prose">{message.text}</div>
          <div className="meta">
            <span>{userStatus(message.status)}</span>
            <span>{timeLabel(message.createdAt)}</span>
          </div>
        </div>
      </div>
    );
  }

  const booking = message.events.find(
    (event) => event.type === "booking_created" && event.booking,
  )?.booking;
  const citedSources = message.sources.filter((source) =>
    message.text.includes(`[doc:${source.record_id}]`),
  );
  const canCopy = message.text.trim().length > 0;

  return (
    <div
      className="crow ai"
      data-testid="message-assistant"
      data-streaming={message.streaming ? "true" : "false"}
    >
      <div className="avatar ai" aria-hidden="true">
        AI
      </div>
      <div className="bubble ai">
        {message.streaming && message.statusLabel ? (
          <p className="status" role="status">
            {message.statusLabel}
          </p>
        ) : null}
        {message.reasoning ? (
          <details className="think">
            <summary>Reasoning</summary>
            <pre>{message.reasoning}</pre>
          </details>
        ) : null}
        <ToolTrace tools={message.tools} />
        {message.text ? (
          <Markdown text={message.text} sources={message.sources} onSource={onSource} />
        ) : null}
        <SourceList sources={citedSources} onSource={onSource} />
        <div className="meta">
          {canCopy ? (
            <button
              type="button"
              className="copy"
              onClick={() => {
                void copyText(message.text).then((ok) => {
                  if (ok) {
                    setCopied(true);
                    window.setTimeout(() => {
                      setCopied(false);
                    }, 1500);
                  }
                });
              }}
            >
              {copied ? "copied" : "copy"}
            </button>
          ) : null}
          <span>{timeLabel(message.createdAt)}</span>
          {onRegenerate && message.text ? (
            <button
              type="button"
              className="copy"
              title="Regenerate reply"
              aria-label="Regenerate reply"
              onClick={() => {
                onRegenerate(message);
              }}
            >
              ↻
            </button>
          ) : null}
        </div>
        {message.error ? (
          <div className="msg err" role="alert">
            {message.error}
          </div>
        ) : null}
        {message.stopped ? <div className="msg warn">Stopped.</div> : null}
        {booking ? <BookingSuccess booking={booking} /> : null}
        {message.draft && !booking ? <BookingDraftCard draft={message.draft} /> : null}
      </div>
    </div>
  );
}
