import { Fragment, type ReactNode } from "react";

import type { SourceRef } from "../api/types";

interface MarkdownProps {
  text: string;
  sources?: SourceRef[];
  onSource?: (source: SourceRef) => void;
}

const INLINE_PATTERN =
  /`([^`\n]+)`|\[doc:([A-Za-z0-9_-]+)\]|\[([^\]]+)\]\(([^)\s]+)\)|\*\*([^*]+)\*\*|__([^_]+)__|\*([^*\n]+)\*|_([^_\n]+)_/g;

function safeHref(href: string): string | null {
  if (href.startsWith("https://") || href.startsWith("http://")) {
    return href;
  }
  if (href.startsWith("/") && !href.startsWith("//") && !href.startsWith("/\\")) {
    return href;
  }
  return null;
}

function renderInline(
  text: string,
  keyPrefix: string,
  sources: SourceRef[],
  onSource?: (source: SourceRef) => void,
): ReactNode[] {
  const nodes: ReactNode[] = [];
  let cursor = 0;
  let index = 0;
  const pattern = new RegExp(INLINE_PATTERN.source, "g");

  let match = pattern.exec(text);
  while (match !== null) {
    if (match.index > cursor) {
      nodes.push(<Fragment key={`${keyPrefix}-t-${index}`}>{text.slice(cursor, match.index)}</Fragment>);
      index += 1;
    }
    const key = `${keyPrefix}-i-${index}`;
    const codeText = match[1];
    const citationId = match[2];
    const linkLabel = match[3];
    const linkTarget = match[4];
    const boldText = match[5] ?? match[6];
    const italicText = match[7] ?? match[8];
    if (codeText !== undefined) {
      nodes.push(<code key={key}>{codeText}</code>);
    } else if (citationId !== undefined) {
      const source = sources.find((item) => item.record_id === citationId);
      if (source && onSource) {
        nodes.push(
          <button
            key={key}
            type="button"
            className="source-ref"
            title={`Open ${source.source_file}:${source.record_id}`}
            onClick={() => {
              onSource(source);
            }}
          >
            [{source.record_id}]
          </button>,
        );
      } else {
        nodes.push(<Fragment key={key}>[{citationId}]</Fragment>);
      }
    } else if (linkLabel !== undefined && linkTarget !== undefined) {
      const href = safeHref(linkTarget);
      if (href) {
        const external = href.startsWith("http");
        nodes.push(
          <a
            key={key}
            href={href}
            {...(external ? { target: "_blank", rel: "noopener noreferrer" } : {})}
          >
            {renderInline(linkLabel, `${key}-label`, sources, onSource)}
          </a>,
        );
      } else {
        nodes.push(<Fragment key={key}>{linkLabel}</Fragment>);
      }
    } else if (boldText !== undefined) {
      nodes.push(
        <b key={key}>{renderInline(boldText, `${key}-b`, sources, onSource)}</b>,
      );
    } else if (italicText !== undefined) {
      nodes.push(
        <i key={key}>{renderInline(italicText, `${key}-em`, sources, onSource)}</i>,
      );
    }
    index += 1;
    cursor = match.index + match[0].length;
    match = pattern.exec(text);
  }

  if (cursor < text.length) {
    nodes.push(<Fragment key={`${keyPrefix}-t-${index}`}>{text.slice(cursor)}</Fragment>);
  }
  return nodes;
}

const BLOCK_START = /^(```|#{1,6}\s+|>\s?|[-*+]\s+|\d+[.)]\s+|(-{3,}|\*{3,}|_{3,})$)/;

export function Markdown({ text, sources = [], onSource }: MarkdownProps) {
  const lines = (text ?? "").replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    const stripped = line.trim();
    if (!stripped) {
      index += 1;
      continue;
    }
    if (stripped.startsWith("```")) {
      const code: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith("```")) {
        code.push(lines[index]);
        index += 1;
      }
      index += 1;
      blocks.push(
        <pre className="md-pre" key={`code-${index}`}>
          <code>{code.join("\n")}</code>
        </pre>,
      );
      continue;
    }
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(stripped)) {
      blocks.push(<hr key={`hr-${index}`} />);
      index += 1;
      continue;
    }
    const heading = /^(#{1,6})\s+(.*)$/.exec(stripped);
    if (heading) {
      blocks.push(
        <div className="md-h" key={`h-${index}`}>
          {renderInline(heading[2], `h-${index}`, sources, onSource)}
        </div>,
      );
      index += 1;
      continue;
    }
    if (stripped.startsWith(">")) {
      const quote: string[] = [];
      while (index < lines.length && lines[index].trim().startsWith(">")) {
        quote.push(lines[index].trim().replace(/^>\s?/, ""));
        index += 1;
      }
      blocks.push(
        <blockquote key={`q-${index}`}>
          {quote.map((item, quoteIndex) => (
            <p key={`q-${index}-${quoteIndex}`}>
              {renderInline(item, `q-${index}-${quoteIndex}`, sources, onSource)}
            </p>
          ))}
        </blockquote>,
      );
      continue;
    }
    if (/^[-*+]\s+/.test(stripped)) {
      const items: ReactNode[] = [];
      while (index < lines.length && /^\s*[-*+]\s+/.test(lines[index])) {
        const item = lines[index].trim().replace(/^[-*+]\s+/, "");
        items.push(
          <li key={`ul-${index}`}>
            {renderInline(item, `ul-${index}`, sources, onSource)}
          </li>,
        );
        index += 1;
      }
      blocks.push(<ul key={`ul-${index}`}>{items}</ul>);
      continue;
    }
    if (/^\d+[.)]\s+/.test(stripped)) {
      const items: ReactNode[] = [];
      while (index < lines.length && /^\s*\d+[.)]\s+/.test(lines[index])) {
        const item = lines[index].trim().replace(/^\d+[.)]\s+/, "");
        items.push(
          <li key={`ol-${index}`}>
            {renderInline(item, `ol-${index}`, sources, onSource)}
          </li>,
        );
        index += 1;
      }
      blocks.push(<ol key={`ol-${index}`}>{items}</ol>);
      continue;
    }

    const paragraph: string[] = [];
    while (index < lines.length) {
      const candidate = lines[index].trim();
      if (!candidate || BLOCK_START.test(candidate)) {
        break;
      }
      paragraph.push(candidate);
      index += 1;
    }
    blocks.push(
      <p key={`p-${index}`}>
        {paragraph.map((item, paragraphIndex) => (
          <Fragment key={`p-${index}-${paragraphIndex}`}>
            {paragraphIndex > 0 ? <br /> : null}
            {renderInline(item, `p-${index}-${paragraphIndex}`, sources, onSource)}
          </Fragment>
        ))}
      </p>,
    );
  }

  return <div className="md">{blocks}</div>;
}
