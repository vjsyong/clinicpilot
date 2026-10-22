import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, api } from "../api/client";
import type {
  BookingDraftView,
  ChatStreamEvent,
  ConversationSummary,
  SlotSuggestion,
  SourceRef,
  ToolTrace,
} from "../api/types";
import {
  buildChatRequest,
  createPendingMessage,
  markFailed,
  messagesFromTranscript,
  slotPrompt,
  toRetry,
  type AssistantChatMessage,
  type ChatMessage,
  type FailedMessage,
  type PendingMessage,
} from "../lib/chat";
import { conversationTitle } from "../lib/sessions";

const STORAGE_KEY = "clinicpilot.conversation";

function storeConversation(id: string | null): void {
  try {
    if (id) {
      localStorage.setItem(STORAGE_KEY, id);
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  } catch {
    // Storage is optional; the in-memory session still works.
  }
}

function errorMessage(caught: unknown): string {
  if (caught instanceof ApiError) {
    return caught.message;
  }
  if (caught instanceof Error && caught.message) {
    return caught.message;
  }
  return "Something went wrong. Please try again.";
}

function statusFor(stage: string): string {
  switch (stage) {
    case "thinking":
      return "Thinking…";
    case "confirming":
      return "Checking the booking summary…";
    case "booking":
      return "Creating the booking…";
    case "booked":
      return "Finishing…";
    default:
      return "Working…";
  }
}

function updateAssistant(
  messages: ChatMessage[],
  messageId: string,
  update: (message: AssistantChatMessage) => AssistantChatMessage,
): ChatMessage[] {
  return messages.map((message) =>
    message.kind === "assistant" && message.messageId === messageId
      ? update(message)
      : message,
  );
}

function toolEnd(
  tools: ToolTrace[],
  event: { id: string; name: string; ok: boolean; summary: string; sources?: SourceRef[] },
): ToolTrace[] {
  let matched = false;
  const next = tools.map((tool) => {
    if (!matched && (tool.id === event.id || (!tool.id && tool.name === event.name))) {
      matched = true;
      return {
        ...tool,
        ok: event.ok,
        summary: event.summary,
        sources: event.sources ?? tool.sources,
        running: false,
      };
    }
    return tool;
  });
  if (matched) {
    return next;
  }
  return [
    ...next,
    {
      id: event.id,
      name: event.name,
      args: {},
      ok: event.ok,
      summary: event.summary,
      sources: event.sources ?? [],
      running: false,
    },
  ];
}

interface UseAssistantOptions {
  onBookingCreated: () => void;
}

export function useAssistant({ onBookingCreated }: UseAssistantOptions) {
  const [sessions, setSessions] = useState<ConversationSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState<BookingDraftView | null>(null);
  const [input, setInput] = useState("");
  const [inFlight, setInFlight] = useState(false);
  const [failed, setFailed] = useState<FailedMessage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeTurnId, setActiveTurnId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [historyError, setHistoryError] = useState<string | null>(null);

  const conversationIdRef = useRef<string | null>(null);
  const inFlightRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  const liveMessageIdRef = useRef<string | null>(null);
  const currentTextRef = useRef("");
  const terminalRef = useRef(false);
  const stopRequestedRef = useRef(false);
  const attachedTurnRef = useRef<string | null>(null);
  const currentUserMessageIdRef = useRef<string | null>(null);
  const mountedRef = useRef(true);
  const bookingCallbackRef = useRef(onBookingCreated);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    bookingCallbackRef.current = onBookingCreated;
  }, [onBookingCreated]);

  const setConversation = useCallback((id: string | null) => {
    conversationIdRef.current = id;
    setActiveId(id);
    storeConversation(id);
  }, []);

  const refreshSessions = useCallback(async (): Promise<ConversationSummary[]> => {
    try {
      const listed = await api.listConversations();
      setSessions(listed);
      setHistoryError(null);
      return listed;
    } catch (caught) {
      setHistoryError(errorMessage(caught));
      return [];
    }
  }, []);

  const upsertSession = useCallback((id: string, turnId: string) => {
    const now = new Date().toISOString();
    const title = conversationTitle(currentTextRef.current);
    setSessions((current) => {
      const existing = current.find((session) => session.id === id);
      if (existing) {
        return current.map((session) =>
          session.id === id
            ? { ...session, updated_at: now, active_turn_id: turnId }
            : session,
        );
      }
      return [
        {
          id,
          title,
          created_at: now,
          updated_at: now,
          message_count: 0,
          turn_count: 0,
          active_turn_id: turnId,
        },
        ...current,
      ];
    });
  }, []);

  const finishStreaming = useCallback(
    (messageId: string, update: (message: AssistantChatMessage) => AssistantChatMessage) => {
      setMessages((current) => updateAssistant(current, messageId, update));
      inFlightRef.current = false;
      setInFlight(false);
      setActiveTurnId(null);
      liveMessageIdRef.current = null;
      abortRef.current = null;
    },
    [],
  );

  const handleEvent = useCallback(
    (messageId: string, event: ChatStreamEvent) => {
      if (event.event === "session") {
        upsertSession(event.data.conversation_id, event.data.turn_id);
        setConversation(event.data.conversation_id);
        setActiveTurnId(event.data.turn_id);
        const userId = currentUserMessageIdRef.current;
        if (userId) {
          setMessages((current) =>
            current.map((message) =>
              message.kind === "user" && message.messageId === userId
                ? { ...message, status: "sent" as const }
                : message,
            ),
          );
        }
        return;
      }
      if (event.event === "status") {
        const label = statusFor(event.data.stage);
        setMessages((current) =>
          updateAssistant(current, messageId, (message) => ({
            ...message,
            statusLabel: label,
          })),
        );
        return;
      }
      if (event.event === "content") {
        setMessages((current) =>
          updateAssistant(current, messageId, (message) => ({
            ...message,
            text: message.text + event.data.delta,
          })),
        );
        return;
      }
      if (event.event === "content_break") {
        setMessages((current) =>
          updateAssistant(current, messageId, (message) => ({
            ...message,
            text: message.text ? `${message.text}\n\n` : message.text,
          })),
        );
        return;
      }
      if (event.event === "tool_start") {
        const tool: ToolTrace = {
          id: event.data.id,
          name: event.data.name,
          args: event.data.args,
          ok: true,
          summary: "",
          sources: [],
          running: true,
        };
        setMessages((current) =>
          updateAssistant(current, messageId, (message) => ({
            ...message,
            tools: [...message.tools, tool],
            statusLabel: `Running ${event.data.name}…`,
          })),
        );
        return;
      }
      if (event.event === "tool_end") {
        setMessages((current) =>
          updateAssistant(current, messageId, (message) => ({
            ...message,
            tools: toolEnd(message.tools, event.data),
            statusLabel: "Thinking…",
          })),
        );
        return;
      }
      if (event.event === "sources") {
        setMessages((current) =>
          updateAssistant(current, messageId, (message) => ({
            ...message,
            sources: event.data.sources,
          })),
        );
        return;
      }
      if (event.event === "draft") {
        setDraft(event.data.draft);
        setMessages((current) =>
          updateAssistant(current, messageId, (message) => ({
            ...message,
            draft: event.data.draft,
          })),
        );
        return;
      }
      if (event.event === "next_step") {
        setMessages((current) =>
          updateAssistant(current, messageId, (message) => ({
            ...message,
            nextStep: event.data.next_step,
          })),
        );
        return;
      }
      if (event.event === "done") {
        terminalRef.current = true;
        finishStreaming(messageId, (message) => ({
          ...message,
          text: event.data.assistant_message,
          sources: event.data.sources ?? [],
          draft: event.data.booking_draft ?? null,
          events: event.data.events ?? [],
          nextStep: event.data.next_step ?? null,
          streaming: false,
          statusLabel: undefined,
          error: undefined,
        }));
        setDraft(event.data.booking_draft ?? null);
        if (
          (event.data.events ?? []).some(
            (item) =>
              item.type === "booking_created" ||
              item.type === "booking_updated" ||
              item.type === "booking_deleted",
          )
        ) {
          bookingCallbackRef.current();
        }
        void refreshSessions();
        return;
      }
      if (event.event === "error") {
        terminalRef.current = true;
        finishStreaming(messageId, (message) => ({
          ...message,
          streaming: false,
          statusLabel: undefined,
          error: event.data.message,
        }));
        const userId = currentUserMessageIdRef.current ?? messageId;
        setError(event.data.message);
        setFailed(markFailed({ messageId: userId, text: currentTextRef.current }, event.data.message));
        setMessages((current) =>
          current.map((message) =>
            message.kind === "user" && message.messageId === userId
              ? { ...message, status: "failed" as const }
              : message,
          ),
        );
        void refreshSessions();
        return;
      }
      if (event.event === "stopped") {
        terminalRef.current = true;
        finishStreaming(messageId, (message) => ({
          ...message,
          streaming: false,
          statusLabel: undefined,
          stopped: true,
        }));
        void refreshSessions();
      }
    },
    [finishStreaming, refreshSessions, setConversation, upsertSession],
  );

  const runTurn = useCallback(
    async (pending: PendingMessage) => {
      const assistantId = `assistant-live-${pending.messageId}`;
      liveMessageIdRef.current = assistantId;
      currentTextRef.current = pending.text;
      currentUserMessageIdRef.current = pending.messageId;
      terminalRef.current = false;
      stopRequestedRef.current = false;
      inFlightRef.current = true;
      setInFlight(true);
      setError(null);
      setFailed(null);
      setMessages((current) => {
        const withoutExisting = current.filter(
          (message) =>
            !(message.kind === "assistant" && message.messageId === assistantId),
        );
        return [
          ...withoutExisting,
          {
            kind: "assistant",
            messageId: assistantId,
            text: "",
            sources: [],
            tools: [],
            draft: null,
            events: [],
            nextStep: null,
            createdAt: new Date().toISOString(),
            streaming: true,
            statusLabel: "Thinking…",
          },
        ];
      });

      const controller = new AbortController();
      abortRef.current = controller;
      try {
        await api.streamChat(
          buildChatRequest(conversationIdRef.current, pending),
          (event) => {
            handleEvent(assistantId, event);
          },
          controller.signal,
        );
        if (!terminalRef.current && !controller.signal.aborted) {
          const message = "The assistant stream ended unexpectedly. Please retry.";
          setError(message);
          setFailed(markFailed(pending, message));
          finishStreaming(assistantId, (assistant) => ({
            ...assistant,
            streaming: false,
            statusLabel: undefined,
            error: message,
          }));
          setMessages((current) =>
            current.map((item) =>
              item.kind === "user" && item.messageId === pending.messageId
                ? { ...item, status: "failed" as const }
                : item,
            ),
          );
        }
      } catch (caught) {
        if (controller.signal.aborted && stopRequestedRef.current) {
          return;
        }
        if (!mountedRef.current) {
          return;
        }
        const message = errorMessage(caught);
        setError(message);
        setFailed(markFailed(pending, message));
        finishStreaming(assistantId, (assistant) => ({
          ...assistant,
          streaming: false,
          statusLabel: undefined,
          error: message,
        }));
        if (mountedRef.current) {
          setMessages((current) =>
            current.map((item) =>
              item.kind === "user" && item.messageId === pending.messageId
                ? { ...item, status: "failed" as const }
                : item,
            ),
          );
          void refreshSessions();
        }
      }
    },
    [finishStreaming, handleEvent, refreshSessions],
  );

  const loadConversation = useCallback(
    async (id: string) => {
      const transcript = await api.getConversation(id);
      const loaded = messagesFromTranscript(transcript);
      const activeTurn = transcript.conversation.active_turn_id ?? null;
      let messageId: string | null = null;
      if (activeTurn) {
        const lastAssistant = [...loaded].reverse().find((item) => item.kind === "assistant");
        if (lastAssistant && lastAssistant.kind === "assistant") {
          messageId = lastAssistant.messageId;
          lastAssistant.streaming = true;
          lastAssistant.statusLabel = "Reconnecting…";
        }
      }
      currentUserMessageIdRef.current =
        transcript.turns.at(-1)?.client_message_id ?? null;
      setConversation(id);
      setMessages(loaded);
      setDraft(transcript.draft ?? null);
      setInput("");
      setFailed(null);
      setError(null);
      setActiveTurnId(activeTurn);
      const lastTurn = transcript.turns.at(-1);
      if (!activeTurn && lastTurn?.status === "failed") {
        setFailed({
          messageId: lastTurn.client_message_id,
          text: lastTurn.user,
          errorMessage: "This turn did not complete. Please retry.",
        });
        setError("The last turn did not complete. Please retry.");
      }

      if (activeTurn && messageId && attachedTurnRef.current !== activeTurn) {
        attachedTurnRef.current = activeTurn;
        liveMessageIdRef.current = messageId;
        inFlightRef.current = true;
        setInFlight(true);
        const controller = new AbortController();
        abortRef.current = controller;
        try {
          await api.attachChatRun(
            activeTurn,
            (event) => {
              handleEvent(messageId, event);
            },
            controller.signal,
          );
        } catch (caught) {
          if (!(caught instanceof ApiError && caught.status === 404)) {
            setError(errorMessage(caught));
          }
          const refreshed = await api.getConversation(id);
          setMessages(messagesFromTranscript(refreshed));
          setDraft(refreshed.draft ?? null);
          setActiveTurnId(refreshed.conversation.active_turn_id ?? null);
          inFlightRef.current = false;
          setInFlight(false);
        } finally {
          if (attachedTurnRef.current === activeTurn) {
            attachedTurnRef.current = null;
          }
        }
      }
    },
    [handleEvent, setConversation],
  );

  const regenerate = useCallback(
    async (assistant: AssistantChatMessage) => {
      if (inFlightRef.current) {
        return;
      }
      const conversation = conversationIdRef.current;
      if (!conversation) {
        return;
      }
      const index = messages.findIndex((message) => message.messageId === assistant.messageId);
      if (index < 0) {
        return;
      }
      const user = [...messages.slice(0, index)]
        .reverse()
        .find((message) => message.kind === "user");
      if (!user || user.kind !== "user") {
        return;
      }
      const assistantId = `assistant-live-${user.messageId}-regen`;
      liveMessageIdRef.current = assistantId;
      currentTextRef.current = user.text;
      currentUserMessageIdRef.current = user.messageId;
      terminalRef.current = false;
      stopRequestedRef.current = false;
      inFlightRef.current = true;
      setInFlight(true);
      setError(null);
      setFailed(null);
      setMessages((current) => [
        ...current.slice(0, index),
        {
          kind: "assistant",
          messageId: assistantId,
          text: "",
          sources: [],
          tools: [],
          draft: null,
          events: [],
          nextStep: null,
          createdAt: new Date().toISOString(),
          streaming: true,
          statusLabel: "Regenerating…",
        },
      ]);
      const controller = new AbortController();
      abortRef.current = controller;
      try {
        await api.regenerateChat(
          { conversation_id: conversation, message_id: user.messageId },
          (event) => {
            handleEvent(assistantId, event);
          },
          controller.signal,
        );
        if (!terminalRef.current && !controller.signal.aborted) {
          const message = "The assistant stream ended unexpectedly. Please retry.";
          setError(message);
          finishStreaming(assistantId, (item) => ({
            ...item,
            streaming: false,
            statusLabel: undefined,
            error: message,
          }));
        }
      } catch (caught) {
        if (!(controller.signal.aborted && stopRequestedRef.current)) {
          const message = errorMessage(caught);
          await loadConversation(conversation);
          if (mountedRef.current) {
            setError(message);
          }
        }
      }
    },
    [finishStreaming, handleEvent, loadConversation, messages],
  );

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const listed = await api.listConversations();
        if (cancelled) {
          return;
        }
        setSessions(listed);
        const stored = (() => {
          try {
            return localStorage.getItem(STORAGE_KEY);
          } catch {
            return null;
          }
        })();
        const target = listed.find((session) => session.id === stored) ?? listed[0] ?? null;
        if (target) {
          await loadConversation(target.id);
        } else {
          setConversation(null);
        }
      } catch (caught) {
        if (!cancelled) {
          setHistoryError(errorMessage(caught));
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
      abortRef.current?.abort();
    };
  }, [loadConversation, setConversation]);

  const sendText = useCallback(
    (value: string) => {
      const text = value.trim();
      if (text.length === 0 || inFlightRef.current) {
        return;
      }
      const pending = createPendingMessage(text);
      setInput("");
    setError(null);
    setFailed(null);
    setMessages((current) => [
      ...current,
      {
        kind: "user",
        messageId: pending.messageId,
        text: pending.text,
        status: "sending",
        createdAt: new Date().toISOString(),
      },
    ]);
      void runTurn(pending);
    },
    [runTurn],
  );

  const send = useCallback(() => {
    sendText(input);
  }, [input, sendText]);

  const confirmBooking = useCallback(() => {
    sendText("yes");
  }, [sendText]);

  const chooseSlot = useCallback(
    (slot: SlotSuggestion) => {
      sendText(slotPrompt(slot));
    },
    [sendText],
  );

  const retry = useCallback(() => {
    if (!failed || inFlightRef.current) {
      return;
    }
    const pending = toRetry(failed);
    setFailed(null);
    setError(null);
    setMessages((current) => {
      const index = current.findIndex(
        (message) => message.kind === "user" && message.messageId === pending.messageId,
      );
      if (index < 0) {
        return current;
      }
      return [
        ...current.slice(0, index + 1).map((message) =>
          message.kind === "user" && message.messageId === pending.messageId
            ? { ...message, status: "sending" as const }
            : message,
        ),
        ...current.slice(index + 1).filter((message) => message.kind !== "assistant"),
      ];
    });
    void runTurn(pending);
  }, [failed, runTurn]);

  const stop = useCallback(() => {
    const turnId = activeTurnId;
    const messageId = liveMessageIdRef.current;
    if (!turnId) {
      return;
    }
    stopRequestedRef.current = true;
    void api.stopChatRun(turnId).catch(() => {
      abortRef.current?.abort();
      if (messageId) {
        finishStreaming(messageId, (message) => ({
          ...message,
          streaming: false,
          statusLabel: undefined,
          stopped: true,
        }));
      }
    });
  }, [activeTurnId, finishStreaming]);

  const newConversation = useCallback(() => {
    if (inFlightRef.current) {
      return;
    }
    attachedTurnRef.current = null;
    liveMessageIdRef.current = null;
    currentUserMessageIdRef.current = null;
    setConversation(null);
    setMessages([]);
    setDraft(null);
    setInput("");
    setFailed(null);
    setError(null);
    setHistoryError(null);
    setActiveTurnId(null);
  }, [setConversation]);

  const selectConversation = useCallback(
    async (id: string) => {
      if (inFlightRef.current || id === conversationIdRef.current) {
        return;
      }
      setLoading(true);
      try {
        await loadConversation(id);
        setHistoryError(null);
      } catch (caught) {
        setHistoryError(errorMessage(caught));
        if (caught instanceof ApiError && caught.status === 404) {
          setConversation(null);
        }
      } finally {
        setLoading(false);
      }
    },
    [loadConversation, setConversation],
  );

  const deleteConversation = useCallback(
    async (id: string) => {
      if (inFlightRef.current && id === conversationIdRef.current) {
        return;
      }
      try {
        await api.deleteConversation(id);
        setSessions((current) => current.filter((session) => session.id !== id));
        if (id === conversationIdRef.current) {
          newConversation();
        }
      } catch (caught) {
        setHistoryError(errorMessage(caught));
      }
    },
    [newConversation],
  );

  const resetWorkspace = useCallback(async () => {
    await api.resetDemo();
    newConversation();
    await refreshSessions();
    bookingCallbackRef.current();
  }, [newConversation, refreshSessions]);

  return {
    sessions,
    activeId,
    messages,
    draft,
    input,
    inFlight,
    failed,
    error,
    activeTurnId,
    loading,
    historyError,
    setInput,
    send,
    sendText,
    confirmBooking,
    chooseSlot,
    regenerate,
    retry,
    stop,
    newConversation,
    selectConversation,
    deleteConversation,
    resetWorkspace,
    refreshSessions,
  };
}
