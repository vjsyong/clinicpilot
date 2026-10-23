import { Fragment, useEffect, useMemo, useState } from "react";

import { api } from "../api/client";
import type {
  AuditEnvelope,
  AuditEvent,
  AuditPricing,
  ConversationSummary,
} from "../api/types";

interface ExplorerPanelProps {
  onOpenConversation: (id: string) => void;
  onReset: () => Promise<void>;
}

interface Usage {
  prompt_tokens?: number;
  completion_tokens?: number;
  cached_tokens?: number;
  total_tokens?: number;
}

function usageOf(event: AuditEvent): Usage | null {
  const raw = event.payload.usage;
  return raw && typeof raw === "object" ? (raw as Usage) : null;
}

function costOf(event: AuditEvent, pricing: AuditPricing): number | null {
  const usage = usageOf(event);
  if (!usage) {
    return null;
  }
  if (
    pricing.input_per_million_usd === 0 &&
    pricing.output_per_million_usd === 0 &&
    pricing.cached_input_per_million_usd === 0
  ) {
    return null;
  }
  const prompt = Number(usage.prompt_tokens ?? 0);
  const cached = Math.min(prompt, Number(usage.cached_tokens ?? 0));
  const uncached = Math.max(0, prompt - cached);
  const completion = Number(usage.completion_tokens ?? 0);
  return (
    (uncached / 1_000_000) * pricing.input_per_million_usd +
    (cached / 1_000_000) * pricing.cached_input_per_million_usd +
    (completion / 1_000_000) * pricing.output_per_million_usd
  );
}

function money(value: number | null): string {
  if (value === null) {
    return "—";
  }
  if (value < 0.01) {
    return `$${value.toFixed(4)}`;
  }
  return `$${value.toFixed(2)}`;
}

function timeLabel(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function eventTone(status: string): string {
  return status === "error" ? "badge err" : "badge ok";
}

export function ExplorerPanel({ onOpenConversation, onReset }: ExplorerPanelProps) {
  const [audit, setAudit] = useState<AuditEnvelope | null>(null);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [eventType, setEventType] = useState("all");
  const [resetting, setResetting] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void Promise.all([api.audit(300), api.listConversations()])
      .then(([loadedAudit, loadedConversations]) => {
        if (!cancelled) {
          setAudit(loadedAudit);
          setConversations(loadedConversations);
          setError(null);
          setLoading(false);
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "Could not load the audit.");
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  const titles = useMemo(
    () => new Map(conversations.map((conversation) => [conversation.id, conversation.title])),
    [conversations],
  );
  const events = useMemo(() => {
    const all = audit?.events ?? [];
    return eventType === "all" ? all : all.filter((event) => event.event_type === eventType);
  }, [audit, eventType]);
  const summary = useMemo(() => {
    const all = audit?.events ?? [];
    const modelCalls = all.filter((event) => event.event_type === "model_call");
    const toolCalls = all.filter((event) => event.event_type === "tool_call");
    const actions = all.filter((event) => event.event_type === "action");
    const tokens = modelCalls.reduce(
      (total, event) => total + Number(usageOf(event)?.total_tokens ?? 0),
      0,
    );
    const cost = audit
      ? modelCalls.reduce((total, event) => total + (costOf(event, audit.pricing) ?? 0), 0)
      : 0;
    const hasCost = audit
      ? modelCalls.some((event) => costOf(event, audit.pricing) !== null)
      : false;
    return {
      modelCalls: modelCalls.length,
      toolCalls: toolCalls.length,
      actions: actions.length,
      tokens,
      cost: hasCost ? cost : null,
    };
  }, [audit]);

  async function resetDemo() {
    const confirmed = window.confirm(
      "Reset the shared demo? This restores P001's seed bookings B1001 and B1004, " +
        "clears all active chats and drafts, and keeps this audit record. " +
        "This affects every visitor.",
    );
    if (!confirmed) {
      return;
    }
    setResetting(true);
    try {
      await onReset();
      setRefreshKey((value) => value + 1);
    } finally {
      setResetting(false);
    }
  }

  return (
    <section className="card" id="explorer-panel" aria-labelledby="explorer-heading">
      <div className="card-h">
        <div>
          <h2 id="explorer-heading">Agent Explorer</h2>
          <span className="sub">
            Messages, model calls, tools, actions, tokens, and estimated cost for this
            browser session.
          </span>
        </div>
        <div className="row">
          <button
            className="btn small"
            type="button"
            onClick={() => {
              setLoading(true);
              setRefreshKey((value) => value + 1);
            }}
            disabled={loading}
          >
            {loading ? "Refreshing…" : "Refresh"}
          </button>
          <button
            className="btn small danger"
            type="button"
            onClick={() => {
              void resetDemo();
            }}
            disabled={resetting}
          >
            {resetting ? "Resetting…" : "Reset demo"}
          </button>
        </div>
      </div>

      {error ? (
        <div className="msg err" role="alert">
          {error}
        </div>
      ) : null}

      <div className="kv explorer-summary">
        <span className="k">Model calls</span>
        <span>{summary.modelCalls}</span>
        <span className="k">Tool calls</span>
        <span>{summary.toolCalls}</span>
        <span className="k">Actions</span>
        <span>{summary.actions}</span>
        <span className="k">Tokens</span>
        <span>{summary.tokens.toLocaleString()}</span>
        <span className="k">Estimated cost</span>
        <span>{summary.cost === null ? "Rates not configured" : money(summary.cost)}</span>
      </div>

      <div className="row explorer-filter">
        <label className="sub" htmlFor="audit-type">
          Event type
        </label>
        <select
          id="audit-type"
          value={eventType}
          onChange={(event) => {
            setEventType(event.target.value);
          }}
        >
          <option value="all">All events</option>
          <option value="model_call">Model calls</option>
          <option value="tool_call">Tool calls</option>
          <option value="action">Actions</option>
        </select>
      </div>

      {loading && !audit ? (
        <p className="sub" role="status">
          Loading audit…
        </p>
      ) : null}

      {!loading && events.length === 0 ? (
        <div className="empty">
          <h4>No trace events yet</h4>
          <p>Send a message in the Assistant tab and its model/tool trace will appear here.</p>
        </div>
      ) : null}

      {events.length > 0 ? (
        <div className="tablewrap">
          <table className="tbl">
            <caption className="vh">Agent audit events for this browser session</caption>
            <thead>
              <tr>
                <th scope="col">Time</th>
                <th scope="col">Type</th>
                <th scope="col">Name</th>
                <th scope="col">Status</th>
                <th scope="col">Conversation</th>
                <th scope="col">Model</th>
                <th scope="col">Tokens</th>
                <th scope="col">Cost</th>
                <th scope="col">Details</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => {
                const usage = usageOf(event);
                const conversationTitle = event.conversation_id
                  ? titles.get(event.conversation_id)
                  : null;
                const isExpanded = expandedId === event.id;
                return (
                  <Fragment key={event.id}>
                    <tr data-testid="audit-event">
                      <td>{timeLabel(event.created_at)}</td>
                      <td>
                        <span className="mono">{event.event_type}</span>
                      </td>
                      <td>{event.name}</td>
                      <td>
                        <span className={eventTone(event.status)}>{event.status}</span>
                      </td>
                      <td>
                        {event.conversation_id && conversationTitle ? (
                          <button
                            type="button"
                            className="copy"
                            onClick={() => {
                              onOpenConversation(event.conversation_id ?? "");
                            }}
                          >
                            {conversationTitle}
                          </button>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td>
                        {String(
                          event.payload.response_model ??
                            event.payload.model ??
                            "—",
                        )}
                      </td>
                      <td>{usage ? Number(usage.total_tokens ?? 0).toLocaleString() : "—"}</td>
                      <td>{audit ? money(costOf(event, audit.pricing)) : "—"}</td>
                      <td>
                        <button
                          type="button"
                          className="btn small"
                          aria-expanded={isExpanded}
                          onClick={() => {
                            setExpandedId(isExpanded ? null : event.id);
                          }}
                        >
                          Payload {isExpanded ? "▾" : "▸"}
                        </button>
                      </td>
                    </tr>
                    {isExpanded ? (
                      <tr className="explorer-payload-row">
                        <td colSpan={9}>
                          <pre className="explorer-json">
                            {JSON.stringify(event.payload, null, 2)}
                          </pre>
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}

      {audit ? (
        <p className="sub">
          Cost is an estimate using {audit.pricing.version} rates; verify against
          current provider pricing.
        </p>
      ) : null}
    </section>
  );
}
