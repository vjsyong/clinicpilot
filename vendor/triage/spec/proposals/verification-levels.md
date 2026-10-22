# Proposal — four verification levels, with rule-traceable evidence

Status: **merged 2026-10-11 as [VERIFICATION.md](../VERIFICATION.md)** plus
`evidence` declarations in `spec/states.json` (L1 for all 35 components; L2
browser test ids where fixtures exist: btn, iconbtn, menu-item, chip, tbl,
badge, dlg, dp, cmd). L1 shipped, L2 partial (gaps listed in the document),
L3 proposed, L4 the pre-registered cross-product experiment scheduled after
the 0.6 line. The rule catalogue stays as-is.

## The contract change (the important part)

Every conformance claim must cite:

    rule id  ·  component/artifact  ·  implementation location  ·  evidence

Evidence is a measurement (contrast ratio, computed style), a captured artifact
(screenshot hash, transcript), or a test id. A global score (e.g. 100/100) is a
gate, not evidence: it may fail a build but may not be quoted as proof that a
specific requirement holds.

## The levels

### Level 1 — Static conformance  (current strength)
Tokens, selectors, declarations, structure. Evidence: lint run + states matrix.
Status: **shipped** (TDS001–015, `tools/verify.py`, CI gate).

### Level 2 — Behavioural conformance  (partial)
Keyboard interactions, state transitions, focus restoration, validation flows,
lifecycle (busy/disarm/restore). Evidence: headless-Chrome test ids.
Current coverage: fixtures exist for badges, interaction, layout, contrast,
roles, screens; datepicker arithmetic is pinned (DST fixture).
**Gaps to close:** overlays (armed delete + menus), combobox, command palette,
dialog focus-restore, mobile sheet lifecycle. Each closed gap adds its test id
to the component's row in `spec/states.json`.

### Level 3 — Rendered conformance  (proposed)
Screenshots and runtime conditions: responsive overflow, 200% text zoom, dark
mode, reduced motion, print, forced-colors, visual regression.
Proposed mechanism: extend `tests/browser` with a screenshot pass keyed by
component id, diffed against `metrics/ui-baseline.json`; overflow and zoom
assertions recorded per component. Evidence: baseline diff + condition matrix.

### Level 4 — Product conformance  (proposed experiment)
Real workflows: task success, error recovery, comprehension, provenance.
Proposed as a **cross-product agent experiment**, pre-registered:

- N independent agents implement the same workflow briefs twice: with the
  Triage authority, and with a minimal baseline (no authority).
- Paired comparison per brief, per agent.
- Pre-registered measures: task success (defined per brief), accessibility
  findings (automated + manual checklist), responsive quality (breakpoint
  sweep), exception frequency (gaps filed), human interventions required.
- Go/no-go: Triage must beat baseline on task success and a11y with no
  regression in exception frequency; otherwise the authority overclaims and
  the gaps become the next work items.
- Compliance score is recorded but is explicitly **not** a success criterion.

## Component coverage declaration

`spec/states.json` gains an optional `evidence` field per component:
`{"L1": "lint+states", "L2": ["test id", ...], "L3": "baseline hash", "L4": void}`.
Components without declared L2/L3 evidence are labelled in the catalogue rather
than implied to be verified.

---
*Open proposal — not binding until merged.*
