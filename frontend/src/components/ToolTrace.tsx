import type { ToolTrace as ToolTraceEntry } from "../api/types";

function mark(tool: ToolTraceEntry): string {
  if (tool.running) {
    return "⏳";
  }
  return tool.ok ? "✓" : "✗";
}

function chipClass(tool: ToolTraceEntry): string {
  if (tool.running) {
    return "tool-chip";
  }
  return tool.ok ? "tool-chip ok" : "tool-chip err";
}

export function ToolTrace({ tools }: { tools: ToolTraceEntry[] }) {
  if (tools.length === 0) {
    return null;
  }
  const last = tools[tools.length - 1];
  const count = `${tools.length} tool call${tools.length === 1 ? "" : "s"}`;
  const summary = last.running ? `running ${last.name}...` : `${last.name} → ${last.summary}`;

  return (
    <details className="tools">
      <summary>
        ⚙ {count} · {mark(last)} {summary}
      </summary>
      <div className="tools-list">
        {tools.map((tool, index) => (
          <span
            className={chipClass(tool)}
            key={tool.id ?? `${tool.name}-${index}`}
            title={JSON.stringify(tool.args)}
          >
            {mark(tool)} {tool.name}
            {tool.summary && !tool.running ? ` → ${tool.summary}` : null}
            {tool.sources.length > 0
              ? ` · ${tool.sources.length} source${tool.sources.length === 1 ? "" : "s"}`
              : null}
          </span>
        ))}
      </div>
    </details>
  );
}
