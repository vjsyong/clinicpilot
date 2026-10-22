# Triage Design System

Triage is the central, app-agnostic UI design authority for these products: one
token source of truth, one component runtime, one enforceable lint gate. It is
dependency-free and ships as plain CSS, a small JS behaviour file, and generated
tokens — no framework, no build step required to consume it.

- **Tokens** own every themable value (`tokens/tokens.json` → `tokens/tokens.css`).
- **Components** come from `core/` — the stylesheet plus `core/components.js`.
- **The interaction standard is binding** ([INTERACTION.md](INTERACTION.md)) and
  enforced by `lint/triage_lint.py`.
- **Verification is a declared ladder with an evidence contract**
  ([VERIFICATION.md](VERIFICATION.md)): every conformance claim cites rule id,
  component, location and evidence; a score is a gate, not evidence.
- Upgrading from 0.6? Start with the [migration guide](MIGRATION.md).

## Quickstart — global path (four lines)

Load the whole system globally and lay out pages with the shipped shell and
patterns:

```html
<link rel="stylesheet" href="tokens/tokens.css">
<link rel="stylesheet" href="core/base.css">
<!-- optional: page patterns (dashboards, detail pages, settings) -->
<link rel="stylesheet" href="core/patterns.css">
<script src="core/components.js" defer></script>
```

## Quickstart — scoped path

Drop Triage into an existing page without restyling the host: wrap the region
that uses Triage in `.triage` and load the scoped bundle. Load `core/reset.css`
alongside it — that is the supported pairing and the one that keeps root sizing
and density identical to the global bundle.

```html
<link rel="stylesheet" href="tokens/tokens.css">
<link rel="stylesheet" href="core/scoped.css">
<link rel="stylesheet" href="core/reset.css">

<div class="triage">
  <div class="card"><h3>Scoped card</h3><p>Only content inside .triage is styled.</p></div>
</div>
```

`core/scoped.css` wraps the component rules in
`@layer triage.components { @scope (.triage) { … } }`, so nothing outside the
`.triage` subtree is touched; `@font-face` and `@keyframes` stay global (they
cannot be scoped). `core/reset.css` is the global `@layer triage.reset` (minimal
box-sizing + body typography + link colour) that owns the root rem base. Both
generated files declare `@layer triage.reset, triage.components;`, so reset never
overrides a component and the load order does not matter.

**The scoped contract.** With `reset.css`, the scoped path matches the global
bundle: `html{font-size:var(--base-size)}` gives the 16px comfortable base, so
`data-density="compact"` renders the 15px compact base, and the body margin is
zeroed. If you load `core/scoped.css` **without** `reset.css`, the host owns root
sizing and typography: at default density a 16px host root matches the global
bundle, but `data-density="compact"` has no root effect — the `.triage`
body/components stay at the host root (16px) rather than shrinking to the global
compact 15px (~6.7% larger) — and the host body margin is kept. Use the
reset-less path only when the host deliberately owns root sizing/typography.

Browser support for `@scope` (validated in headless Chrome 149 and 151):

| Browser | First version with `@scope` |
|---|---|
| Chrome / Edge | 118 |
| Safari | 17.4 |
| Firefox | 128 |

On an older engine the scoped selectors are ignored, so fall back to the global
`core/base.css` path (the behaviour is otherwise identical).

### Component dependencies

Styling is pure CSS, but a family that needs behaviour is wired by a script —
`core/components.js` (data-attribute driven, dependency-free, degrades to plain
markup without JS) or `core/i18n.js`:

| Family | Needs | The script expects |
|---|---|---|
| Tabs | `core/components.js` | `[data-tabs]` wrapping `.tablist` + `.tab` and the tabpanels |
| Combobox / multi-select | `core/components.js` | `[data-combobox]` (`.cb-input`, `.cb-list`, `.cb-opt`; `data-multi`, `.cb-chips`, `[data-mirror]`) |
| Date picker | `core/components.js` | `[data-datepicker]` wrapping `.dp-input` + `.dp-pop` (`data-min`/`data-max`) |
| Command palette | `core/components.js` | `.dlg.cmd` (`.cmd-input`, `.cmd-item`) + `[data-cmd-open]` triggers |
| Dropzone / upload | `core/components.js` | `[data-drop]` with a `.drop` zone and a file input; dispatches `triage:files` |
| Notifications | `core/components.js` | `[data-notif]` panel; `[data-notif-read]` marks all read |
| Sortable tables | `core/components.js` | `[data-sort-table]` with `.th-sort` header buttons |
| Slider | `core/components.js` | `[data-slider]` with an `input[type=range]` and `.slider-val`/`output` |
| i18n (locale, messages, plurals, `dir`) | `core/i18n.js` | `window.triageI18n` (optional; only if you localise) |

Everything else — buttons, forms, cards, tables, badges, banners, menus, empty
states, save bars, and all page patterns — is CSS-only.

Fonts: `core/base.css` and `core/scoped.css` point `@font-face` at `fonts/`
(Geist + Geist Mono, OFL 1.1). Keep the `fonts/` directory next to `core/` and
`tokens/`, or override `--font-sans` / `--font-mono` with your own families.

Set the theme with `data-theme="light|dark"` on `<html>`; light is the default
and the dark palette also follows `prefers-color-scheme`.

Set the density with `data-density="compact"` on `<html>`; **comfortable** is the
default when the attribute is absent (or `"comfortable"`). Comfortable renders
body 16px, table/controls ~13–14px and every label ≥12px; compact lowers the root
to 15px (body ~15px, controls/table ~13px) while keeping every label ≥12px.

## One interactive component, copy-paste

Tabs wire themselves up from data attributes — no initialisation call:

```html
<div data-tabs>
  <div class="tablist" role="tablist">
    <button class="tab" role="tab" aria-selected="true" aria-controls="p1">Inbox</button>
    <button class="tab" role="tab" aria-controls="p2">Sent</button>
  </div>
  <div id="p1" role="tabpanel">42 messages</div>
  <div id="p2" role="tabpanel" hidden>18 messages</div>
</div>
```

`core/components.js` adds roving tabindex and Arrow/Home/End handling. It also
drives the date picker, combobox, command palette, dropzone, notifications,
sortable tables and sliders; every component degrades to plain markup without JS.

## Repository layout

```
tokens/tokens.json   source of truth for colour/type/space/motion (DTCG)
tokens/tokens.css    GENERATED from tokens.json — do not edit
src/core/*.css       canonical core stylesheets (base, additions, components, patterns, reset)
core/base.css        GENERATED from src/core/ — do not edit
core/scoped.css      GENERATED from src/core/ — the @scope(.triage) integration path
core/patterns.css    GENERATED from src/core/ — do not edit
core/reset.css       GENERATED from src/core/reset.css — opt-in global reset
core/components.js   hand-authored component runtime
tools/build_core.py  composes core/*.css; resolves {bp-*} breakpoint placeholders
tools/build_tokens.py generates tokens.css (font stacks, --base-size)
tools/token_map.py   token-consumption contract (writes spec/token-consumers.json)
spec/token-consumers.json  GENERATED — which consumers read each token
spec/token-metadata.json   hand-maintained reasons for metadata-only tokens
spec/states.json     component lifecycle + state contract
INTERACTION.md       the binding interaction standard
MIGRATION.md         0.6 → 0.12 upgrade guide
lint/                triage-lint engine, rules and tests
site/                the documentation & enforcement site
tests/browser/       headless-Chrome behaviour + contrast regressions
metrics/ui-baseline.json  GENERATED — deterministic UI baseline for the reference screens
```

## Token model

- Font stacks are derived from `typography.family-text` / `family-mono`.
- The root size is the relative `--base-size` (`1rem` = the 16px design base
  against the browser's 16px default), so a user text-size preference scales the
  whole rem scale. `typography.base-size` is the single source for both the root
  and the `--fs-*` division, so the authored px render at those px at the default.
  `html[data-density="compact"]` lowers `--base-size` to `0.9375rem` (15px) from a
  `com.triage.compact` token extension; `tools/build_tokens.py` emits that block.
- Core media queries use `{bp-sm}` / `{bp-phone}` / `{bp-phone-up}` / `{bp-md}` /
  `{bp-lg}` / `{bp-xl}` placeholders; `tools/build_core.py` substitutes the px
  value from `misc.breakpoint` at compose time.
- Spacing has one curated **preferred scale** (`2/4/8/12/16/24/32/48`), plus
  **semantic roles** that components consume by intent: `--space-page` (page
  padding), `--space-card` (card padding), `--space-field` (label/field gap and
  form-field padding) and `--space-control` (button/control inline padding). The
  fine/odd steps the shipped sheets still use are kept for compatibility and
  labelled legacy in `tokens.json`.
- Fixed chrome/column widths are **not** spacing gaps, so they emit in a separate
  `--layout-*` group from `misc.layout`: `--layout-sidebar` (236px),
  `--layout-content-max` (1160px) and `--layout-dock` (352px, the dock fallback).
- Every emitted token must have a documented consumer or a reason in
  `spec/token-metadata.json`; `python3 tools/token_map.py --check` enforces it.

## Docs site and gates

```bash
python3 site/serve.py            # docs site on http://127.0.0.1:8102
python3 build.py check           # full repo self-check (core/token sync, token map, spec, lint tests)
python3 tools/token_map.py --check   # token-consumption contract
python3 lint/triage_lint.py . --strict   # dogfood the linter on this repo
python3 tests/browser/run.py     # headless-Chrome behaviour + contrast regressions + UI baseline
python3 tests/browser/run.py --update-baseline   # regenerate metrics/ui-baseline.json (deliberate)
```

`tests/browser/run.py` measures computed styles and one fixed-size geometry box
for a representative selector list on the reference screens (dashboard, list,
form, viewer) plus the generated overlays docs page, at 1440 and 390 in
{light-comfortable, dark-comfortable, light-compact}. It compares the numbers to
the committed `metrics/ui-baseline.json` and fails by name on drift; use
`--update-baseline` only when a UI change is intentional. It prints a summary of
what it wrote, and the resulting diff is **reviewable generated output** (which
screens/widths/variants/elements changed) — read it before committing, not a
silent artifact.

The page-hierarchy contract (page title → section heading → card heading → body
→ meta, and the token each level uses) lives on the typography foundation page:
`/foundations/typography` → *Page hierarchy*.

After editing anything under `src/core/`, run `python3 build.py core`; after
editing `tokens/tokens.json`, run `python3 build.py tokens`. `build.py check`
fails if the generated files have drifted.

## Versioning and provenance

The version lives in `VERSION` (mirrored in `package.json` and the docs chrome)
and every release is recorded in `CHANGELOG.md`. Core stylesheets are canonical
under `src/core/`; the historical pack pipeline
(`tools/assemble_from_pack.py`, `tools/tokenize_core.py`) is provenance
maintenance only and refuses to run without `--force`, staging its output under
`dist/`. See `PROVENANCE.md` for lineage and `AGENTS.md` for the binding contract.
