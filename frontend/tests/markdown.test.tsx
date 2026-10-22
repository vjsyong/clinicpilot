import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import { Markdown } from "../src/components/Markdown";

const sources = [{ source_file: "doctors.csv", record_id: "D104" }];

describe("Markdown", () => {
  it("renders headings, lists, bold text, and inline code", () => {
    const html = renderToStaticMarkup(
      <Markdown text={"# Hours\n\n- **Mon-Fri**\n- Sat\n\nUse `C001`."} />,
    );

    expect(html).toContain('class="md-h"');
    expect(html).toContain("<ul>");
    expect(html).toContain("<b>Mon-Fri</b>");
    expect(html).toContain("<code>C001</code>");
  });

  it("links known citations and leaves unknown ones as text", () => {
    const html = renderToStaticMarkup(
      <Markdown
        text={"See [doc:D104] and [doc:D999]."}
        sources={sources}
        onSource={() => undefined}
      />,
    );

    expect(html).toContain("source-ref");
    expect(html).toContain("[D104]");
    expect(html).toContain("[D999]");
    expect(html.match(/source-ref/g) ?? []).toHaveLength(1);
  });

  it("drops unsafe link destinations but keeps the label", () => {
    const html = renderToStaticMarkup(
      <Markdown text={"[click](javascript:alert(1))"} />,
    );

    expect(html).not.toContain("javascript:");
    expect(html).toContain("click");
  });

  it("allows http and same-origin relative links", () => {
    const html = renderToStaticMarkup(
      <Markdown text={"[site](https://example.com) and [hours](/demo/source)"} />,
    );

    expect(html).toContain('href="https://example.com"');
    expect(html).toContain('href="/demo/source"');
    expect(html).toContain('rel="noopener noreferrer"');
  });

  it("escapes raw HTML instead of rendering it", () => {
    const raw = ["<", "img", ' src=x onerror="alert(1)">'].join("");
    const html = renderToStaticMarkup(<Markdown text={raw} />);

    expect(html).toContain("&lt;img");
    expect(html).not.toContain(["<", "img"].join(""));
  });

  it("renders fenced code blocks", () => {
    const html = renderToStaticMarkup(
      <Markdown text={"```\nC001\n```"} />,
    );

    expect(html).toContain('class="md-pre"');
    expect(html).toContain("C001");
  });
});
