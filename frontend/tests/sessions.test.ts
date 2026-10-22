import { describe, expect, it } from "vitest";

import type { ConversationSummary } from "../src/api/types";
import { filterSessions, groupSessions, sessionWhen } from "../src/lib/sessions";

function session(
  id: string,
  title: string,
  updatedAt: string,
): ConversationSummary {
  return {
    id,
    title,
    created_at: updatedAt,
    updated_at: updatedAt,
    message_count: 2,
    turn_count: 1,
    active_turn_id: null,
  };
}

const NOW = new Date("2026-10-22T12:00:00Z");

describe("assistant sessions", () => {
  it("groups sessions into today, yesterday, and earlier", () => {
    const local = (daysAgo: number) =>
      new Date(
        NOW.getFullYear(),
        NOW.getMonth(),
        NOW.getDate() - daysAgo,
        9,
        0,
      ).toISOString();
    const groups = groupSessions(
      [
        session("1", "Today chat", local(0)),
        session("2", "Yesterday chat", local(1)),
        session("3", "Old chat", local(21)),
      ],
      NOW,
    );

    expect(groups.map((group) => group.label)).toEqual(["Today", "Yesterday", "Earlier"]);
    expect(groups[0].sessions[0].title).toBe("Today chat");
  });

  it("filters sessions by title", () => {
    const sessions = [
      session("1", "Knee consultation", "2026-10-22T09:00:00Z"),
      session("2", "Clinic hours", "2026-10-22T08:00:00Z"),
    ];

    expect(filterSessions(sessions, "knee").map((item) => item.id)).toEqual(["1"]);
    expect(filterSessions(sessions, "  ")).toEqual(sessions);
  });

  it("formats today as a time and earlier days with a date", () => {
    const today = new Date(
      NOW.getFullYear(),
      NOW.getMonth(),
      NOW.getDate(),
      9,
      5,
    ).toISOString();
    const earlier = new Date(
      NOW.getFullYear(),
      NOW.getMonth(),
      NOW.getDate() - 21,
      9,
      5,
    ).toISOString();
    expect(sessionWhen(today, NOW)).toMatch(/\d{2}:\d{2}/);
    expect(sessionWhen(earlier, NOW)).toMatch(/\d{2}-\d{2}/);
  });
});
