import { useCallback, useEffect, useRef, useState } from "react";

import type {
  BookingDraftView,
  ConversationSummary,
  SlotSuggestion,
  SourceRef,
} from "../api/types";
import type { AssistantChatMessage, ChatMessage } from "../lib/chat";
import { BookingDraftCard } from "./BookingDraftCard";
import { ChatMessageView } from "./ChatMessage";
import { ChatSessionRail } from "./ChatSessionRail";
import { Composer } from "./Composer";
import { MobileHistorySheet } from "./MobileHistorySheet";
import { SourceInspector } from "./SourceInspector";

interface ChatPanelProps {
  sessions: ConversationSummary[];
  activeId: string | null;
  messages: ChatMessage[];
  draft: BookingDraftView | null;
  input: string;
  inFlight: boolean;
  canRetry: boolean;
  error: string | null;
  loading: boolean;
  historyError: string | null;
  onInputChange: (value: string) => void;
  onSend: () => void;
  onPrompt: (text: string) => void;
  onStop: () => void;
  onRetry: () => void;
  onRegenerate: (message: AssistantChatMessage) => void;
  onConfirm: () => void;
  onChooseSlot: (slot: SlotSuggestion) => void;
  onReset: () => void;
  onNew: () => void;
  onLogout: () => void;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
}

const SUGGESTIONS = [
  "What are C001's hours?",
  "Who treats knee pain?",
  "Book a knee consultation",
  "Show my appointments",
];

export function ChatPanel({
  sessions,
  activeId,
  messages,
  draft,
  input,
  inFlight,
  canRetry,
  error,
  loading,
  historyError,
  onInputChange,
  onSend,
  onPrompt,
  onStop,
  onRetry,
  onRegenerate,
  onConfirm,
  onChooseSlot,
  onReset,
  onNew,
  onLogout,
  onSelect,
  onDelete,
}: ChatPanelProps) {
  const transcriptRef = useRef<HTMLDivElement | null>(null);
  const atBottomRef = useRef(true);
  const [atBottom, setAtBottom] = useState(true);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [source, setSource] = useState<SourceRef | null>(null);

  const scrollToBottom = useCallback(() => {
    const transcript = transcriptRef.current;
    if (!transcript) {
      return;
    }
    transcript.scrollTop = transcript.scrollHeight;
    atBottomRef.current = true;
    setAtBottom(true);
  }, []);

  useEffect(() => {
    const last = messages[messages.length - 1];
    if (atBottomRef.current || last?.kind === "user") {
      atBottomRef.current = true;
      scrollToBottom();
    }
  }, [messages, inFlight, scrollToBottom]);

  const handleScroll = useCallback(() => {
    const transcript = transcriptRef.current;
    if (!transcript) {
      return;
    }
    const distance =
      transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight;
    const near = distance < 80;
    atBottomRef.current = near;
    setAtBottom(near);
  }, []);

  const activeSession = sessions.find((session) => session.id === activeId);
  const lastAssistant = [...messages]
    .reverse()
    .find((message) => message.kind === "assistant");
  const lastAssistantId = lastAssistant?.messageId;
  const canRegenerate =
    lastAssistant !== undefined &&
    !lastAssistant.streaming &&
    !lastAssistant.events.some((event) => event.type === "booking_created") &&
    lastAssistant.draft?.status !== "booked";
  const hasAttachedDraft =
    draft !== null &&
    messages.some(
      (message) =>
        message.kind === "assistant" &&
        message.draft?.draft_id === draft.draft_id &&
        message.draft.version === draft.version,
    );

  return (
    <section className="assistant-page" aria-labelledby="assistant-heading">
      <div className="page-head am-head">
        <div>
          <h1 className="page-title" id="assistant-heading">
            Assistant
          </h1>
          <div className="page-desc">
            Grounded in the clinic knowledge base. Every search and tool step is visible.
          </div>
        </div>
      </div>

      <div className="chat-layout">
        <ChatSessionRail
          sessions={sessions}
          activeId={activeId}
          busy={inFlight || loading}
          query={query}
          onQueryChange={setQuery}
          onNew={onNew}
          onSelect={onSelect}
          onDelete={onDelete}
        />

        <div className="chat-main">
          <div className="chat-head">
            <button
              type="button"
              className="iconbtn"
              aria-label="Chat history"
              onClick={() => {
                setHistoryOpen(true);
              }}
            >
              ☰
            </button>
            <div className="ch-title">{activeSession?.title ?? "Assistant"}</div>
            <button
              type="button"
              className="iconbtn"
              aria-label="New chat"
              onClick={onNew}
              disabled={inFlight || loading}
            >
              +
            </button>
          </div>

          <div className="chat-flex">
            <div className="jumpwrap">
              <div
                className="chat"
                role="log"
                aria-live="polite"
                aria-relevant="additions text"
                aria-label="Conversation transcript"
                aria-busy={inFlight}
                ref={transcriptRef}
                onScroll={handleScroll}
                data-testid="chat-transcript"
              >
                {loading && messages.length === 0 ? (
                  <p className="sub" role="status">
                    Loading chat…
                  </p>
                ) : null}

                {!loading && messages.length === 0 && !inFlight ? (
                  <div className="chat-empty">
                    <div className="chat-empty-icon" aria-hidden="true">
                      ✚
                    </div>
                    <div className="chat-empty-title">How can we help?</div>
                    <div className="sub">
                      Ask about clinics, doctors, treatments, or book an appointment for P001.
                    </div>
                    <div className="chips">
                      {SUGGESTIONS.map((suggestion) => (
                        <button
                          type="button"
                          className="chip"
                          key={suggestion}
                          onClick={() => {
                            onPrompt(suggestion);
                          }}
                        >
                          {suggestion}
                        </button>
                      ))}
                    </div>
                  </div>
                ) : null}

                {messages.map((message) => (
                  <ChatMessageView
                    key={message.messageId}
                    message={message}
                    currentDraft={draft}
                    inFlight={inFlight}
                    onSource={setSource}
                    onConfirm={
                      message.messageId === lastAssistantId ? onConfirm : undefined
                    }
                    onChooseSlot={
                      message.messageId === lastAssistantId ? onChooseSlot : undefined
                    }
                    onReset={message.messageId === lastAssistantId ? onReset : undefined}
                    onRegenerate={
                      canRegenerate &&
                      message.kind === "assistant" &&
                      message.messageId === lastAssistantId
                        ? onRegenerate
                        : undefined
                    }
                  />
                ))}

                {draft && draft.status !== "booked" && !hasAttachedDraft ? (
                  <div className="crow ai">
                    <div className="avatar ai" aria-hidden="true">
                      AI
                    </div>
                    <div className="bubble ai">
                      <BookingDraftCard
                        draft={draft}
                        currentDraft={draft}
                        inFlight={inFlight}
                        onConfirm={onConfirm}
                        onChooseSlot={onChooseSlot}
                      />
                    </div>
                  </div>
                ) : null}
              </div>

              {!atBottom ? (
                <button
                  type="button"
                  className="btn small"
                  id="jump"
                  onClick={scrollToBottom}
                >
                  ↓ Jump to latest
                </button>
              ) : null}
            </div>

            {historyError ? (
              <div className="msg err" role="alert">
                {historyError}
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

            <Composer
              input={input}
              inFlight={inFlight}
              disabled={loading}
              onInputChange={onInputChange}
              onSend={onSend}
              onStop={onStop}
            />
          </div>
        </div>
      </div>

      <MobileHistorySheet
        open={historyOpen}
        onClose={() => {
          setHistoryOpen(false);
        }}
      >
        <ChatSessionRail
          sessions={sessions}
          activeId={activeId}
          busy={inFlight || loading}
          query={query}
          onQueryChange={setQuery}
          onNew={() => {
            setHistoryOpen(false);
            onNew();
          }}
          onSelect={(id) => {
            setHistoryOpen(false);
            onSelect(id);
          }}
          onDelete={onDelete}
        />
        <div className="sheet-foot">
          <span className="sub">
            <span className="dot ok" aria-hidden="true" /> Patient P001 · session active
          </span>
          <button type="button" className="btn small" onClick={onLogout}>
            Log out
          </button>
        </div>
      </MobileHistorySheet>

      <SourceInspector
        source={source}
        onClose={() => {
          setSource(null);
        }}
      />
    </section>
  );
}
