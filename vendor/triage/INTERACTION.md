# Interaction standard

One recurring action, one mechanism. This is the binding interaction contract for
every product that consumes Triage: when a screen disagrees with this document,
the screen is wrong. It is written in the shipped class and token vocabulary of
the canonical core sources (`src/core/{base,additions,components,patterns}.css`,
composed into the generated `core/base.css` and `core/patterns.css`) — every
class named here is defined there, and every value is a token.

The historical app-era record this document replaces is kept verbatim at
[`site/docs-from-app/ui-conventions.md`](site/docs-from-app/ui-conventions.md);
that file uses pre-rename names and is a provenance record, not the standard.

## Action grammar

### Item deletes — armed, two-step

Deleting an entity listed in the UI (a rule, flow, classifier, template, chat,
record) is a two-step, in-place action. No `confirm()` dialog, ever, for these.

- The trigger carries `.arm-del` (icon-only triggers may use `.icon-del`) and
  `data-arm-label="Press again to delete <thing> <name>"`, with a matching
  `aria-label="Delete <thing> <name>"` in the initial state.
- First activation *arms* it: it gains `.armed`, the label becomes
  `Confirm delete` (or the trash glyph for `.icon-del`), and the `aria-label`
  announces the arm. It auto-disarms after 4 s, on `Escape`, on any outside
  click, and when its enclosing `details.menu` closes.
- Second activation performs the delete.
- Inside a menu the item is `menu-item danger arm-del`; the menu stays open
  through arming so the second click lands.
- After the delete, announce the result (see Feedback): a redirect renders an
  `.msg` banner, an in-place action calls `toast()`. Armed is not a substitute
  for feedback.

Implementation: `window.__triageArmDel` in `core/shell.js`.

```html
<button class="btn small danger arm-del" type="submit"
        data-arm-label="Press again to delete rule 'News'"
        aria-label="Delete rule 'News'">Delete</button>
```

### One-way / high-stakes actions — `confirm()`

Actions that are irreversible, security-relevant, or affect more than the clicked
item keep a native `confirm()` whose sentence names the object and the
consequence. Representative set:

| Action | Consequence copy must say |
|---|---|
| Remove account | its tokens + config entry are deleted |
| Reset cached OAuth tokens | you will need to authorise again |
| Rebuild the search index | the stored content itself is untouched |
| Clear a chat | clears this chat only |
| Enable an auto-apply/agent mode | it will act on its own |
| Approve a plugin with a browser view | it can transmit content by navigating itself |

`onsubmit="return confirm('…')"` on the form; keep the string apostrophe-safe and
do not interpolate names into a single-quoted JS string.

### Reversible mutations — show the reverse

Edits that can be undone in place (remove ⇄ re-include, snooze ⇄ wake now,
tag ⇄ untag, clear ⇄ restore) need no confirmation and no danger styling. Put the
reverse control next to the action.

## State controls (on / off)

Use `.px-sw` for every boolean enable/disable of an entity. It auto-submits on
change and the route then announces the new state.

- Markup: a `<label class="px-sw">` wrapping an `<input type="checkbox">` and a
  `<span class="px-tr"></span>` track. The whole switch-only form carries
  `inline px-swf` (`form.inline.px-swf`) so it centres against adjacent buttons.
- Verbs are only **Enable** / **Disable** — never Pause/Resume or On/Off.
  `title` and `aria-label` name the entity.
- Status transitions that are not booleans (Retire, approve, save permissions)
  stay text buttons.
- Geometry (keep all three together when restyling): a 36×21 track, a 15×15
  `border-box` knob inset 2px via `.px-sw .px-tr::after`; on coarse pointers the
  switch gets a 44px hit area.
- `.px-sw` needs JS (it is the rich control). The plain `Enabled` checkbox in an
  editor stays the no-JS path.

## Feedback

- **Server / redirect** → an `.msg` banner at the top of the content. Kinds are
  exactly `.msg.ok` (success), `.msg.warn` (partial) and `.msg.err` (failure).
  There is no `info` kind — use `ok` for a benign outcome and `warn` when only
  part of it worked.
- **In-place (JS / fetch)** → `toast(msg, kind)` from `core/shell.js`, which
  renders a `.toast2` with the same three kinds at top-right (bottom on phones).
  Host it once per page in `<div class="toasts" id="toasts" aria-live="polite">`.
  One toast at a time.
- No page-local toast markup and no query-param toasts.
- Announce every mutation unless the new state is self-evident in the same
  viewport (row reorder, paging, filters). Wording is past tense and names the
  object: "Rule 'News' disabled.", "Chat deleted.", "Sample moved to the in-set."

## Lists & row actions

- Clicking a row opens the record; secondary actions live in `.rowacts`, revealed
  on hover/focus on desktop and always visible on touch.
- Desktop: relevant actions inline with `.ra-inline`; the rest in a
  `details.menu` with `.ra-menu` and a `.menu-pop`. Touch (≤767px): `.ra-inline`
  hides and the `⋯` menu shows. Every `.rowacts` ships both variants.
- Dense tables use the `.tbl.mcards` collapsed-card anatomy; card lists may show
  their few actions inline.
- Menu items are sentence case (`Edit`, `Delete…`); a destructive item carries
  `menu-item danger arm-del`.
- Bulk actions live in `.bulkbar`, which appears only with a selection (the
  server adds `.on`); its triggers live in `.tactions`.

## Save bars & editors

- Editors end in a `.savebar`: primary **Save \<thing\>** plus **Cancel**. The way
  out of an editor is Cancel; "Back" is only for a navigation backlink.
- Server-side validation renders at the top of the form and receives focus.
- Settings cards keep scoped partial saves; a card never submits fields it does
  not own.

## Empty states

- `.empty` anatomy: optional icon, an `h4` title, one line of reason, and at most
  one CTA (`.btn primary`). Use it for any list or card with nothing to show.
- Micro-empties inside a feed may be a single `.sub` line ("Nothing logged at this
  level yet.").
- Never a bare blank area or a bare "failed": give a specific reason and one
  recovery action.

## Copy

- Use the shared `cp(text, el)` helper (from `core/shell.js`) or a `.copy`
  element, and mark `.copy` for the copy-to-clipboard affordance.
- Never call `navigator.clipboard` from page code — the helper owns the fallback
  and the confirmation labelling.

## Auto-submit selects

A control that mutates exactly one value may auto-submit on `change`, and when it
does it must announce via an `.msg` banner or `toast()`. Rows with several
controls keep an explicit Save.

## Labels & accessibility

- Sentence case for buttons, links and menu items.
- Name the object in destructive labels and `aria-label`s.
- Keep the global `:focus-visible` ring; never remove focus styling.
- 44px minimum touch targets on coarse pointers.
- Colour is never the only signal — pair it with text or an icon.
- Every interactive element needs an accessible name (`lint/triage_lint.py`
  enforces TDS014/TDS015).

## Border discipline

The system's square geometry is right; the risk is that every grouping gets
another rectangle. Borders obey three rules:

1. **Borders signal structure or interaction** — container edges, table
   rules, interactive boundaries (3:1 non-text where interactive). Not
   decoration.
2. **One border role per card.** Nested rectangles use the background tint
   (`--card2`) or spacing instead of a second border.
3. **Grouping prefers space and typography.** Section spacing and label
   treatment come before another box; new work should need a reason to add
   a border, not a reason to remove one.

## Exceptions register (deliberate deviations)

| Exception | Why |
|---|---|
| Log toolbar Pause/Resume | a live-view control, not an entity's enabled state |
| Row reorder (up/down) is silent | the new order is visible in place |
| A reversible sample `Remove` is plain, not armed | fully reversible via the adjacent re-include control |
| Editor `Enabled` checkboxes | form context: the Save bar is the commit step |
| `confirm()` for the high-stakes set above | arming cannot carry the consequence |

## Review checklist (new or changed screen)

1. Delete/remove is armed (entity), `confirm()` (high-stakes) or paired with its
   reverse (reversible) — and it announces afterwards.
2. On/off uses `.px-sw`, Enable/Disable copy, and the route announces.
3. Feedback is an `.msg` banner on redirect and `toast()` in place — three kinds
   only.
4. New forms: submit guard works, labels are Save/Cancel.
5. Row actions use `.rowacts` with `.ra-inline` + `.ra-menu`, sentence case.
6. Empty state uses the `.empty` anatomy with one primary CTA.
7. Copy uses the shared `cp`/`.copy` helper.
8. Every interactive element has an accessible name and the focus ring is intact.
9. Borders: can this grouping be expressed with space and type instead of a
   box? One border role per card; nested rectangles use `--card2` or spacing,
   never a second border. Borders signal structure or interaction only (see
   "Border discipline" above).
