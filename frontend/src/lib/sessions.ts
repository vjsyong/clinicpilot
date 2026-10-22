import type { ConversationSummary } from "../api/types";

export interface SessionGroup {
  label: string;
  sessions: ConversationSummary[];
}

function dayValue(value: string): number {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return -1;
  }
  const midnight = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  return midnight.getTime();
}

export function groupSessions(
  sessions: ConversationSummary[],
  now: Date = new Date(),
): SessionGroup[] {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const yesterday = today - 24 * 60 * 60 * 1000;
  const groups: SessionGroup[] = [
    { label: "Today", sessions: [] },
    { label: "Yesterday", sessions: [] },
    { label: "Earlier", sessions: [] },
  ];
  for (const session of sessions) {
    const day = dayValue(session.updated_at);
    if (day === today) {
      groups[0].sessions.push(session);
    } else if (day === yesterday) {
      groups[1].sessions.push(session);
    } else {
      groups[2].sessions.push(session);
    }
  }
  return groups.filter((group) => group.sessions.length > 0);
}

export function sessionWhen(value: string, now: Date = new Date()): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const day = new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
  if (day === today) {
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  return `${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")} ${date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
}

export function filterSessions(
  sessions: ConversationSummary[],
  query: string,
): ConversationSummary[] {
  const wanted = query.trim().toLocaleLowerCase();
  if (!wanted) {
    return sessions;
  }
  return sessions.filter((session) => session.title.toLocaleLowerCase().includes(wanted));
}
