# Proposal — a formal machine-action provenance record

Status: **merged 2026-10-11 as component `.prov` (beta) at 0.13.0**. Landed:
the `.prov` stylesheet block (grid record, eight fields, folded labelled
explanation), the `spec/states.json` component entry (selector coverage,
a11y notes, beta lifecycle), live usage in `examples/viewer.html`, and the
rendering rules reflected in [VERIFICATION.md](../VERIFICATION.md)'s
evidence contract. The lintable selector presence follows the existing
`.btn` pattern; a rendered (L3) baseline remains future work.

## The record (proposed component `prov`, fields required unless noted)

- **action** — what was done or proposed, in one line.
- **initiating authority** — human, agent, or model, with identifier and
  version (e.g. `model:claude-x@2026-09` or `human:sean`).
- **input evidence** — references to the inputs that justified the action
  (message ids, extracted fields, cited rules).
- **rule / policy** — the rule id or policy version the action was evaluated
  against (or explicit `none`).
- **evaluation outcome** — how the action scored against that rule
  (pass / fail / not-applicable), with the measurement if one exists.
- **timestamp** — ISO 8601.
- **resulting state change** — what changed as a result (e.g. `queued`,
  `applied to row 412`, `archived`).
- **available reversal** — how to undo, or explicit `irreversible`.

Optional, clearly labelled as supplementary:
- **explanation** — model-generated narrative. Rendered *below* the record,
  never inline as if it were evidence.
- **confidence** — only when calibrated against a validation set, with the
  calibration reference; otherwise omitted. (`91% confidence` without
  calibration implies warranted certainty the system cannot demonstrate.)

## Rendering rules

1. Collapsed reasoning and tool disclosures are transcripts; they may sit
   behind a fold inside the record, but the eight required fields must be
   visible without expanding a transcript.
2. Audit rows reuse the same record shape — one schema for all machine actions.
3. The record must be addressable (stable id) so reviews and exports can cite
   it.

## Why a component contract and not a convention

Conventions drift; contracts are lintable. Once shipped, a `prov` record can be
required in the same way `.btn` states are: by selector presence plus state
coverage, and (Level 3) a rendered baseline.

---
*Open proposal — not binding until merged.*
