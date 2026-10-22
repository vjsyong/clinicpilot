import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { API_PATHS, ApiError, api } from "./api/client";
import type { BookingDraftView, BookingView } from "./api/types";
import { AppHeader } from "./components/AppHeader";
import { BookingsPanel } from "./components/BookingsPanel";
import { ChatPanel } from "./components/ChatPanel";
import {
  buildChatRequest,
  createPendingMessage,
  markFailed,
  toRetry,
  type ChatMessage,
  type FailedMessage,
  type PendingMessage,
} from "./lib/chat";
import { readRuntimeConfig } from "./lib/config";

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error && error.message.length > 0) {
    return error.message;
  }
  return "Something went wrong. Please try again.";
}

export function App() {
  const config = useMemo(() => readRuntimeConfig(), []);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [inFlight, setInFlight] = useState(false);
  const [failed, setFailed] = useState<FailedMessage | null>(null);
  const [chatError, setChatError] = useState<string | null>(null);
  const [draft, setDraft] = useState<BookingDraftView | null>(null);
  const [bookingSuccess, setBookingSuccess] = useState<string | null>(null);
  const [bookings, setBookings] = useState<BookingView[]>([]);
  const [bookingsLoading, setBookingsLoading] = useState(true);
  const [bookingsError, setBookingsError] = useState<string | null>(null);

  const conversationIdRef = useRef<string | null>(null);
  const inFlightRef = useRef(false);
  const transcriptRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    document.title = config.appName;
  }, [config.appName]);

  useEffect(() => {
    const transcript = transcriptRef.current;
    if (!transcript) {
      return;
    }
    if (messages.length === 0) {
      transcript.scrollTop = 0;
      return;
    }
    transcript.scrollTop = transcript.scrollHeight;
  }, [messages, inFlight, draft, bookingSuccess, chatError]);

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      try {
        const loaded = await api.listBookings();
        if (!cancelled) {
          setBookings(loaded);
          setBookingsError(null);
        }
      } catch (error) {
        if (
          !cancelled &&
          !(error instanceof ApiError && error.status === 401)
        ) {
          setBookingsError(describeError(error));
        }
      } finally {
        if (!cancelled) {
          setBookingsLoading(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const refreshBookings = useCallback(async () => {
    setBookingsLoading(true);
    setBookingsError(null);
    try {
      const loaded = await api.listBookings();
      setBookings(loaded);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        return;
      }
      setBookingsError(describeError(error));
    } finally {
      setBookingsLoading(false);
    }
  }, []);

  const deliver = useCallback(
    async (message: PendingMessage) => {
      setInFlight(true);
      try {
        const response = await api.sendChat(
          buildChatRequest(conversationIdRef.current, message),
        );

        conversationIdRef.current = response.conversation_id;
        setMessages((current) => [
          ...current.map((item) =>
            item.kind === "user" && item.messageId === message.messageId
              ? { ...item, status: "sent" as const }
              : item,
          ),
          {
            kind: "assistant",
            messageId: `assistant-${response.message_id}`,
            text: response.assistant_message,
            sources: response.sources ?? [],
          },
        ]);
        setDraft(response.booking_draft ?? null);
        setFailed(null);
        setChatError(null);

        const events = response.events ?? [];
        if (events.some((event) => event.type === "booking_created")) {
          const created =
            events.find((event) => event.type === "booking_created" && event.booking)
              ?.booking ?? null;
          setBookingSuccess(
            created
              ? `Appointment ${created.booking_id} confirmed for ${created.local_date} at ${created.local_time} (${created.timezone}).`
              : "Appointment confirmed.",
          );
          void refreshBookings();
        }
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          return;
        }
        const failedMessage = markFailed(message, describeError(error));
        setMessages((current) =>
          current.map((item) =>
            item.kind === "user" && item.messageId === message.messageId
              ? { ...item, status: "failed" as const }
              : item,
          ),
        );
        setFailed(failedMessage);
        setChatError(failedMessage.errorMessage);
      } finally {
        inFlightRef.current = false;
        setInFlight(false);
      }
    },
    [refreshBookings],
  );

  const send = useCallback(() => {
    const text = input.trim();
    if (text.length === 0 || inFlightRef.current) {
      return;
    }

    inFlightRef.current = true;
    const message = createPendingMessage(text);
    setInput("");
    setFailed(null);
    setChatError(null);
    setMessages((current) => [
      ...current,
      {
        kind: "user",
        messageId: message.messageId,
        text: message.text,
        status: "sending",
      },
    ]);
    void deliver(message);
  }, [deliver, input]);

  const retry = useCallback(() => {
    if (!failed || inFlightRef.current) {
      return;
    }

    inFlightRef.current = true;
    const message = toRetry(failed);
    setFailed(null);
    setChatError(null);
    setMessages((current) =>
      current.map((item) =>
        item.kind === "user" && item.messageId === message.messageId
          ? { ...item, status: "sending" as const }
          : item,
      ),
    );
    void deliver(message);
  }, [deliver, failed]);

  const newConversation = useCallback(() => {
    if (inFlightRef.current) {
      return;
    }

    conversationIdRef.current = null;
    setMessages([]);
    setDraft(null);
    setBookingSuccess(null);
    setFailed(null);
    setChatError(null);
    setInput("");
  }, []);

  const logout = useCallback(async () => {
    await api.logout();
    window.location.assign(API_PATHS.login);
  }, []);

  return (
    <div className="app" data-testid="workbench">
      <a className="skip" href="#main">
        Skip to content
      </a>
      <aside className="side" id="workbench-side" aria-label="ClinicPilot">
        <div className="side-top">
          <span className="brand">
            <span className="brand-mark" aria-hidden="true">
              CP
            </span>
            <span className="brand-name">ClinicPilot</span>
          </span>
          <div className="brand-sub">Patient P001</div>
        </div>
        <nav className="nav" aria-label="Workbench">
          <div className="nav-label">Workbench</div>
          <a className="nav-item active" href="#chat-panel" aria-current="page">
            Chat
          </a>
          <a className="nav-item" href="#bookings-panel">
            Bookings
          </a>
        </nav>
        <div className="side-foot">
          <div className="sf-row">
            <span className="dot ok" aria-hidden="true" />
            <span>Session active</span>
          </div>
          <div className="sf-row">
            <span>Shared demo patient</span>
          </div>
        </div>
      </aside>

      <div className="main">
        <main className="content" id="main">
          <AppHeader
            appName={config.appName}
            onLogout={() => {
              void logout();
            }}
          />

          <div className="split-grid">
            <ChatPanel
              messages={messages}
              input={input}
              inFlight={inFlight}
              error={chatError}
              canRetry={failed !== null}
              draft={draft}
              success={bookingSuccess}
              transcriptRef={transcriptRef}
              onInputChange={setInput}
              onSend={send}
              onRetry={retry}
              onNewConversation={newConversation}
            />

            <BookingsPanel
              bookings={bookings}
              loading={bookingsLoading}
              error={bookingsError}
              onRefresh={() => {
                void refreshBookings();
              }}
            />
          </div>

          <div className="foot">
            Patient P001 · conversations are private to this browser session; bookings are
            shared.
          </div>
        </main>
      </div>
    </div>
  );
}
