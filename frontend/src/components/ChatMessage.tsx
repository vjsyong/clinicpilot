import { useState } from "react";

import type {
  BookingDraftView,
  BookingView,
  SlotSuggestion,
  SourceRef,
} from "../api/types";
import type { AssistantChatMessage, UserChatMessage } from "../lib/chat";
import { sourceLabel, sourceKey } from "../lib/sources";
import { BookingDraftCard } from "./BookingDraftCard";
import { Markdown } from "./Markdown";
import { ToolTrace } from "./ToolTrace";

interface ChatMessageProps {
  message: UserChatMessage | AssistantChatMessage;
  currentDraft: BookingDraftView | null;
  inFlight: boolean;
  onSource: (source: SourceRef) => void;
  onConfirm?: () => void;
  onChooseSlot?: (slot: SlotSuggestion) => void;
  onReset?: () => void;
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

function BookingSuccess({
  booking,
  updated,
}: {
  booking: BookingView;
  updated: boolean;
}) {
  return (
    <div className="msg ok" role="status" data-testid="booking-success">
      <b>{updated ? "Booking updated." : "Booking confirmed."}</b> {booking.booking_id} ·{" "}
      {booking.local_date} at {booking.local_time} ({booking.timezone})
    </div>
  );
}

function ConfirmActionCard({
  message,
  inFlight,
  onConfirm,
  onReset,
}: {
  message: AssistantChatMessage;
  inFlight: boolean;
  onConfirm?: () => void;
  onReset?: () => void;
}) {
  const step = message.nextStep;
  if (!step || step.kind !== "confirm_action") {
    return null;
  }
  if (step.action_id === "reset") {
    return (
      <div className="proposal" data-testid="confirm-action">
        <div className="p-tag">Confirm action</div>
        <div className="spread">
          <b>Reset shared demo workspace</b>
          <span className="badge warn">needs confirmation</span>
        </div>
        <p className="sub">
          Restores B1001 and B1004, clears active chats and drafts, and keeps the
          audit record. This affects every visitor.
        </p>
        <div className="row">
          <button
            type="button"
            className="btn danger"
            data-testid="confirm-reset-demo"
            disabled={inFlight || !onReset}
            onClick={onReset}
          >
            Reset demo
          </button>
        </div>
      </div>
    );
  }
  const booking = step.action_booking;
  if (!booking) {
    return null;
  }
  return (
    <div className="proposal" data-testid="confirm-action">
      <div className="p-tag">Confirm action</div>
      <div className="spread">
        <b>Delete booking {booking.booking_id}</b>
        <span className="badge warn">needs confirmation</span>
      </div>
      <div className="kv">
        <span className="k">Doctor</span>
        <span>{booking.doctor_name}</span>
        <span className="k">Treatment</span>
        <span>{booking.treatment_name}</span>
        <span className="k">Appointment</span>
        <span>
          {booking.local_date} at {booking.local_time} ({booking.timezone})
        </span>
      </div>
      <p className="sub">
        This hides the booking from the active list. The audit record is retained.
      </p>
      <div className="row">
        <button
          type="button"
          className="btn danger"
          data-testid="confirm-delete-booking"
          disabled={inFlight || !onConfirm}
          onClick={onConfirm}
        >
          Delete booking
        </button>
      </div>
    </div>
  );
}

export function ChatMessageView({
  message,
  currentDraft,
  inFlight,
  onSource,
  onConfirm,
  onChooseSlot,
  onReset,
  onRegenerate,
}: ChatMessageProps) {
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

  const bookingEvent = message.events.find(
    (event) =>
      (event.type === "booking_created" || event.type === "booking_updated") &&
      event.booking,
  );
  const booking = bookingEvent?.booking;
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
        {booking ? <BookingSuccess booking={booking} updated={bookingEvent?.type === "booking_updated"} /> : null}
        <ConfirmActionCard
          message={message}
          inFlight={inFlight}
          onConfirm={onConfirm}
          onReset={onReset}
        />
        {message.draft && !booking && message.nextStep?.kind !== "confirm_action" ? (
          <BookingDraftCard
            draft={message.draft}
            nextStep={message.nextStep}
            currentDraft={currentDraft}
            inFlight={inFlight}
            onConfirm={onConfirm}
            onChooseSlot={onChooseSlot}
          />
        ) : null}
      </div>
    </div>
  );
}
