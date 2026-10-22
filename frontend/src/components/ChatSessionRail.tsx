import { useEffect, useState } from "react";

import type { ConversationSummary } from "../api/types";
import { filterSessions, groupSessions, sessionWhen } from "../lib/sessions";

interface ChatSessionRailProps {
  sessions: ConversationSummary[];
  activeId: string | null;
  busy: boolean;
  query: string;
  onQueryChange: (value: string) => void;
  onNew: () => void;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
}

export function ChatSessionRail({
  sessions,
  activeId,
  busy,
  query,
  onQueryChange,
  onNew,
  onSelect,
  onDelete,
}: ChatSessionRailProps) {
  const [armed, setArmed] = useState<string | null>(null);
  const filtered = filterSessions(sessions, query);
  const groups = groupSessions(filtered);

  useEffect(() => {
    if (armed === null) {
      return;
    }
    const timer = window.setTimeout(() => {
      setArmed(null);
    }, 3000);
    return () => {
      window.clearTimeout(timer);
    };
  }, [armed]);

  return (
    <aside className="chat-rail" aria-label="Chat history">
      <div className="chat-rail-head">
        <button
          type="button"
          className="btn primary"
          onClick={onNew}
          disabled={busy}
          data-testid="new-conversation"
        >
          New chat
        </button>
        <input
          type="search"
          value={query}
          onChange={(event) => {
            onQueryChange(event.target.value);
          }}
          placeholder="Search chats…"
          aria-label="Search chats"
        />
      </div>
      {groups.length === 0 ? (
        <p className="sub chat-rail-empty">
          {query.trim() ? "No chats found." : "No chats yet."}
        </p>
      ) : (
        groups.map((group) => (
          <div className="chat-rail-group-wrap" key={group.label}>
            <div className="chat-rail-group">{group.label}</div>
            {group.sessions.map((session) => {
              const active = session.id === activeId;
              const working = Boolean(session.active_turn_id);
              return (
                <div className={active ? "arow cur" : "arow"} key={session.id}>
                  <button
                    type="button"
                    className="t"
                    title={session.title}
                    aria-current={active ? "page" : undefined}
                    onClick={() => {
                      if (!busy) {
                        onSelect(session.id);
                      }
                    }}
                  >
                    {session.title}
                  </button>
                  {working ? (
                    <span className="spinner" role="status" aria-label="Assistant is working">
                      <span className="vh">Assistant is working</span>
                    </span>
                  ) : null}
                  <span className="when">{sessionWhen(session.updated_at)}</span>
                  <button
                    type="button"
                    className={armed === session.id ? "btn small danger" : "btn small"}
                    aria-label={
                      armed === session.id
                        ? `Confirm delete chat: ${session.title}`
                        : `Delete chat: ${session.title}`
                    }
                    title={armed === session.id ? "Click again to delete" : "Delete chat"}
                    disabled={busy}
                    onClick={() => {
                      if (armed === session.id) {
                        setArmed(null);
                        onDelete(session.id);
                      } else {
                        setArmed(session.id);
                      }
                    }}
                  >
                    {armed === session.id ? "Delete?" : "×"}
                  </button>
                </div>
              );
            })}
          </div>
        ))
      )}
    </aside>
  );
}
