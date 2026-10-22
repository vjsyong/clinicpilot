# Proposal — density, typography floors, and border discipline

Status: **merged 2026-10-11**. Landed: `size-badge` and `size-nav-label`
raised 12px → 13px (compact `0.8rem` → `0.8125rem`, proportional at the 15px
root); new lint rule **TDS016 label-tier** (info) flags label-role classes
(`.badge`, `.nav-label`, `.cmd-group`) set below the comfortable target;
border discipline documented in INTERACTION.md (three rules + checklist
item 9). The lint floor stays an error; the tier check is adoption guidance.
Level-4 rendered items remain scheduled after the 0.6 line where applicable.

## Typography floors

Current floor: 12px micro-labels (F3, raised in 0.9.0). The review's point
stands: 12px is defensible for genuinely secondary metadata, but too small as
the *common* supporting-label size in an interface full of badges, audit
trails, and operational detail.

Proposed rule:

- **Comfortable density:** supporting labels (badges, meta rows, table
  headers, nav labels) target **13–14px** (0.8125–0.875rem at the 16px root).
- **12px is reserved** for tertiary metadata (timestamps in dense tables,
  keyboard hints, provenance footnotes).
- **Compact density** keeps its 15px root but inherits the same tiering
  proportionally — no label-like content under 12px at either density.
- Lint: the floor stays enforced; add a *tier* check flagging label-role
  classes below the comfortable target as `info` (adoption guidance, not an
  error).

## Border discipline

The system's square geometry is right; the risk is that every grouping gets
another rectangle. Proposed rules:

1. **Borders signal structure or interaction** — container edges, table rules,
   interactive boundaries (3:1 non-text where interactive). Not decoration.
2. **One border role per card.** Nested rectangles use background tint
   (`--card2`) or spacing instead of a second border.
3. **Grouping prefers spacing and typography** — section spacing and label
   treatment before another box; new work should need a reason to add a
   border, not a reason to remove one.
4. Documented in INTERACTION.md's review checklist as a pre-flight question:
   *"can this grouping be expressed with space and type instead of a box?"*

## Relationship to the review's hierarchy finding

Density and borders are half of the hierarchy problem; the other half is
priority order (see the response document, section A). Both land in the same
pass over the message-list and dashboard patterns.

---
*Open proposal — not binding until merged.*
