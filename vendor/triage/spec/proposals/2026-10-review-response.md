# Response to the October 2026 critical review (v0.12.1)

Direction: the review's core demand is accepted — the system's documentation must
not compete with its normative layer, and conformance must mean more than a lint
score. Status of each point: **fixed now**, **proposal drafted** (this
directory), or **needs an owner decision**.

## The framing point — documentation drift
**Fixed now.** The audit page now opens with its reading order:
normative layer (`spec/rules.json`, `spec/states.json`, `tokens/tokens.json`,
`INTERACTION.md`) > historical layer (audit register, CHANGELOG, PROVENANCE —
statuses kept current, never normative) > open proposals (this directory).
Four stale entries were corrected in the same pass: F9 (sprite shipped — 174
glyphs in `icons/sprite.svg`), F14 (packaging exists — `make package` +
hash-tracked artifacts), the layer checklist's "untokenised foundations" row,
and the closing recommendations list, which still advised fixing contrast items
resolved in 0.9/0.2.

## A. Visual hierarchy (P1) — accepted
The three-level model is right: attention/decision first, then what happened and
what can be done, then system telemetry. The message-list and dashboard patterns
get a hierarchy pass against that model. The proposed experiment (below) can
measure whether it lands.

## B/C. Verification depth (P0) — proposal drafted
`verification-levels.md`: four explicit levels — static, behavioural, rendered,
product — with two rules added to the contract: **every conformance claim cites
its rule id and its implementation evidence** (replacing score-as-evidence), and
level coverage is **declared per component**, not implied by the catalogue size.

## D. Invariants vs opinions (P2) — proposal drafted, owner decision needed
`theme-profiles.md`: invariants stay unconditional (status semantics,
accessibility, state contracts, reversibility, traceability); theme opinions
(radius, typeface, button fills, accent, density) move behind a declared theme
file, with the current strict profile as the default identity.

## E. Density and borders (P2) — proposal drafted
`density-borders.md`: supporting labels toward 13–14px in comfortable density
(12px reserved for genuinely secondary metadata), plus explicit border
discipline — borders for structure and interaction only; grouping prefers
spacing and typography.

## F. Provenance vs reasoning (P1) — proposal drafted
`provenance-contract.md`: a formal machine-action record — action, initiating
authority, input evidence, rule/model version, evaluation outcome, timestamp,
resulting state change, available reversal. Model explanations supplement the
record, never substitute for it; confidence numbers require calibration
evidence or are omitted.

## The suggested validation experiment — accepted
Protocol in `verification-levels.md` (Level 4 section). Pre-registered
measures: task success, accessibility findings, responsive quality, exception
frequency, human interventions. Compliance score is recorded but is not a
success criterion — the question is whether compliant builds actually behave
better and stay understandable.

## Owner decisions (2026-10-11)

Ruled on the Design Authority 0.6 decision page
(`workspaces/owner-decisions-0.6`):

- `theme-profiles.md`: **rejected**. Forks remain the answer; the brand
  stays Geist-first; no theme-file mechanism.
- `verification-levels.md`, `density-borders.md`, `provenance-contract.md`:
  **advance to merge** through the repository's normal review route. The
  Level-4 rendered experiment is scheduled after the 0.6 line.

---
*Open proposals — nothing here is binding until merged into the normative layer.*
