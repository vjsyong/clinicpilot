# Proposal — invariants vs theme opinions (adoption profiles)

Status: **closed, rejected by the owner (2026-10-11)**. Forks remain the answer
for adopting teams; the brand stays Geist-first; no theme-file mechanism is
added. The problem the review
named: an app-agnostic library currently enforces product-specific absolutes —
zero radius (with a `!important` reset), Geist/Geist Mono, black primary
buttons, a near-monochrome palette, and a restrictive token-override policy.
That is correct for a tightly controlled product; it is friction for adopters.

## The split

**Core invariants — always enforced, not themable:**

- status semantics (ok / warn / err communicate state, never decoration)
- accessible interactions: focus always visible, keyboard parity, accessible
  names, contrast pairs (TDS004, TDS011, TDS014, TDS015)
- state contracts: every component ships its documented states
  (`spec/states.json`)
- reversibility: armed delete / show-the-reverse / confirm for one-way actions
- traceability: rule-traceable evidence (see verification-levels proposal)

**Theme opinions — overridable through a declared theme file:**

- corner radius (default 0; profile may set a radius token scale)
- typeface (default Geist/Geist Mono; profile may swap family tokens)
- emphasis fills (default black primary buttons; profile may re-map)
- accent and palette hues
- density defaults

## Proposed mechanism

1. An optional `theme.json` (or `.triagerc` extension) declares the adopting
   product's overrides, token-by-token, with sources.
2. The lint gate reads the profile: in `profile: strict` (default) TDS003
   (non-zero-radius) and TDS008 (off-system font) fire as today; in
   `profile: adopt` they check that overrides come from the declared theme
   file (undeclared deviations still fail).
3. Core CSS keeps zero-radius defaults; the `!important` reset moves behind
   the radius token so a profile can change it declaratively.
4. Invariants are never profile-switchable.

## Open questions for the owner

- Is `adopt` a supported mode for Triage-as-a-library, or should forks remain
  the answer? (Recommendation: adopt mode, because forks already happen and
  are invisible to the lint gate.)
- Does the brand stay Geist-first in adopt mode? (Recommendation: brand pages
  yes; product surfaces follow the profile.)

---
*Open proposal — not binding until merged.*
