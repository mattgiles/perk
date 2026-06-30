---
title: perk TUI surfaces — surfaces module, composed status slot, factory widgets, the perk-owned footer
read_when: You are touching extension/surfaces/surfaces.ts or any perk-rendered TUI surface (footer, widgets, status slot), adding a rich-UI call, or testing widget/footer rendering through the harness.
---

# perk TUI surfaces

Objective #251's charter convergence built perk's TUI presence in four moves: the surfaces module
(node 2.1), the themed/windowed checkpoints widget (2.2), the composed single `perk` status slot
(2.3), and the perk-owned `setFooter` footer (3.1). This doc consolidates the cross-cutting laws,
pi API facts, and test recipes those turns established.

## The surfaces module = `surfaces.ts` + `report.ts`

"The surfaces module" is **two files**: `extension/surfaces/surfaces.ts` plus `extension/surfaces/report.ts`
(`report` is re-exported from surfaces). The node-4.1 rich-UI regression guard treats exactly
these two as the sanctioned rich-UI call sites — `setFooter` calls were deliberately confined to
`surfaces.ts`; don't add `ctx.ui.setFooter` (or any other direct rich-UI call) elsewhere.

Two structural invariants to preserve:

- **`surfaces.ts` is dependency-free by design**: renderers take *structural* progress params
  (e.g. a `ProgressState`/`ProgressStep` shape) rather than importing controller state types —
  that avoids an import cycle with the surface controllers. Keep it that way when adding renderers.
- **The glyph + height-budget constants are charter-law data**, pinned only by
  `extension/surfaces/surfaces.test.ts` until consumers bind them — they are not dead code.

## The composed single `perk` status slot

Pi's default footer sorts extension statuses **alphabetically by slot key**, so an extension
cannot order multiple slots. The only ordering lever is collapsing into ONE slot and composing the
segments yourself: a fixed segment order, two-space join, and an empty composition publishing
`undefined` to clear the slot. (This composition is exactly what the custom footer later reuses.)

- **Shared segment-store handle**: the handle is created once in `extension/index.ts` and threaded
  into each publisher (checkpoints, objective). This preserves the extension's
  zero-module-level-mutable-state invariant, and the shared map means one controller's recompose
  preserves the other's segment regardless of controller registration order.
- **Headless `set` must be a FULL no-op** — it must never touch the segment map. If a headless set
  recorded text, a later *headful* set of the **other** segment would resurrect ghost
  headless-era text into the composed line. A test pins this.
- No width handling is needed in the composition: pi's footer truncates the joined status line
  itself.

## The RPC dual-publish law (contractual — contracts.md P2.T2c)

Pi's RPC mode drops component-factory widgets and `setFooter` entirely; only `string[]` widgets
and `setStatus` forward. Any perk surface moving to a themed factory or the custom footer must
keep a `setStatus`/string twin as the RPC-visible fallback. The custom footer filters its own slot
key out of `getExtensionStatuses()` to avoid double display (the composed `perk` slot keeps
publishing via `setStatus` even though the footer renders the segments directly).

## `setFooter` adoption facts (verified against pi 0.78.1)

- **Factory assignability needs method syntax**: the factory accepts a *narrower structural*
  argument only if the mirror interfaces (theme-like, footer-data-like, `requestRender`) are
  declared with TS *method* syntax — method members are bivariant; property-arrow syntax breaks
  the assignability.
- **`sanitizeStatusText` is not exported** from pi — reimplement locally (newline/tab → space,
  collapse spaces, trim).
- **`ctx.getContextUsage()`** returns `{ tokens, contextWindow, percent }` (tokens/percent
  nullable). There is **no model-change or context-usage event** for extensions — footer
  reactivity must be render-driven (read `ctx.model`/usage live in `render()`).
- **Replaced-footer dispose is undocumented**: pi's contract for disposing a *replaced* footer
  factory is unverified — hence the once-only install flag in `index.ts` (re-installing per
  `session_start` could leak the previous factory's subscriptions). Accepted trade: the install
  closures capture the *first* session's `ctx`; if pi ever invalidated old context objects, the
  footer's model/context would silently freeze. Revisit if pi documents dispose-on-replace.
- **The footer is a single last-wins slot** — extensions receive `session_start` in settings load
  order, so a later-loaded package calling `ctx.ui.setFooter` silently replaces perk's footer (no
  error, no log). Borrowed packages must never call it; see `workflow/borrowed-packages.md` for
  the vetting grep and the retirement recipe.
- **`setWorkingIndicator` is never called** (charter D5 rescinded): its frames are pre-baked
  verbatim strings with no theme hook — structurally incompatible with the
  never-pre-bake-theme-colors law. Re-check that API constraint before any "brand the spinner"
  idea.

## Widget / windower patterns

- **"~N lines" charter budgets resolve as *content* lines**, with elision markers extra (e.g.
  "~4 lines" ⇒ ≤6 rendered). This is the precedent for any future budgeted surface.
- **The pure-windower shape generalizes** to any bounded list surface: a `step | elision` item
  union, the anchor clamped to sit second in the window, and no-current ⟹ anchor last.
- **`truncateToWidth` (pi-tui) emits `...` plus ANSI resets, never `…`** — assert truncation via
  `visibleWidth(line) <= width` (also exported from `@earendil-works/pi-tui`), never `.length` or
  `.endsWith("…")`. It is ANSI-aware on input, so pre-themed `theme.fg(...)` strings pass through
  safely.

## Harness recipes

- **Factory widgets**: invoke the factory with an undefined TUI + a passthrough fake theme
  (`fg: (_c, t) => t`) and record `component.render(80)` — existing `string[]` value asserts
  survive unchanged. Capture `placement` from the `setWidget` options arg as a new optional record
  field. Gotcha: widening a recorder to push the options param makes legacy calls record
  `options: undefined`, churning `deepEqual` fixtures even on "unchanged" paths.
- **Command status/widget effects go through `invokeCommand`**, never `runCommandHandler` — the
  latter synthesizes its own command ctx without the statuses/widgets capture arrays, so
  `setStatus` calls inside the handler are invisible to `h.statuses`. The real prompt path binds
  the capturing UI.
- **"Slot never touched" asserts don't survive a shared composed slot**: a controller clearing its
  *absent* segment still publishes `setStatus("perk", undefined)` on every `session_start` — the
  assert must become "no *defined* value ever set".
- **The startup banner lands in `h.notifies` in every headful session** — count-based notify
  assertions are fragile; filter by severity instead (see also `pi/extension-seams.md`).
- **`node --test extension/` fails** (MODULE_NOT_FOUND on the dir); the suite runs as
  `node --test extension/*.test.ts` (what the justfile does).

## Width-sweep invariant testing

For drop-order / responsive rendering, don't snapshot specific widths. Sweep width downward
asserting (a) rank-monotonicity — if drop-rank r survives, every higher rank survives — and
(b) never-exceed-width at every step; then assert the sweep actually exercised all ranks. This
shape is robust to padding-math tweaks where width snapshots churn.

## Plan-fidelity micro-lesson

When a plan names a helper AND gives an output example, verify they agree before assuming the
helper is reusable as-is — the footer plan's own `200k` example forced a change to the existing
token formatter (which rendered `200.0k`), rippling into other consumers of the shared helper.

## Vendoring a TS extension that touches pi-tui (#628)

Three concerns surfaced vendoring `btw`/`whimsical` from upstream into the perk extension:

### The dual-copy pi-tui CLASS type clash

Two physical pi-tui copies (the top-level dep vs the **nested** copy bundled inside
`@earendil-works/pi-coding-agent`) make tsc treat **value classes with private fields** as **distinct
nominal types** (`Types have separate declarations of a private property 'previousLines'`). The
symptom: `ctx.ui.custom`'s factory hands you the *nested-copy* `TUI`, but `new MyOverlay(topLevelTUI)`
fails. **Functions and interfaces/types do NOT clash** (structural) — only value classes with private
members. The fix that worked **without a dep bump or deep-path import**: at the single pi boundary,
type the clash-prone params as **structural slices** of only the methods used (`{ requestRender(): void }`,
etc.); for a value you must instantiate/extend, import it as a VALUE from top-level pi-tui, but import
the **keybindings manager from `@earendil-works/pi-coding-agent`** (it re-exports the nested copy, so
it matches the `ui.custom` factory param); returning an overlay where a structural `Component` is
expected type-checks structurally. **Version skew is the trap** — "confirmed exported" is true but
silently assumes a single copy.

### Bringing a new `ctx.ui.*` method under governance (the `setWorkingMessage` seam)

A new rich-UI method gets a **headless-no-op seam** in the surfaces module over a **minimal
structural target** (early-return when `!hasUI`), mirroring the existing report/standing-widget
recipe; `whimsical` flavors pi's existing default working indicator with a text-only label.
`setWorkingMessage` is **governed-but-permitted**; `setWorkingIndicator` stays **banned** (D5
rescinded).

### The charter "bounded exception that proves the rule" pattern

`/btw`'s entire UI is a `ctx.ui.custom` overlay the charter §6 D6 **declines** — recorded **not** by
rescinding the decline but as a **named, sole, bounded exception**, permitted ONLY because it is
human-invoked (no model tool, not a stage/door), `hasUI`-gated, and never machine-reachable; the
exception's boundary IS the rule's criterion. Recorded **in lockstep across the three discipline
records** (`docs/design/tui-charter.md`, `shared/contracts.md`, `AGENTS.md`) per the "amend the
contract / update user docs, don't drift" rule, with glyph conformance during the port.

## Taming a foreign extension's `console.error` TUI clobber (`/pr-review-local`)

**The reusable insight — in-process vs subprocess clobber.** A foreign extension's terminal noise is
interceptable **only** when it's the extension's own `console.error` (same Node process). plannotator's
git/gh subprocesses use captured output, so they never leak; the only clobber is its in-process
`console.error` painting over pi's managed TUI input box. **Verify this distinction first** — if the
noise were inherited subprocess stdio, a JS console swap would be useless.

**The console-swap helper pattern** (`extension/substrate/consoleCapture.ts`, `interceptConsoleError` —
the first production console-swap; prior swaps were all test-local):

- **Injected sink, never `ui.notify`.** The helper takes a caller-supplied sink and stays a pure
  substrate module (keeps it out of the `surfaces/` allowlist that `surfacesGuard.test.ts` enforces);
  the door passes a sink that routes through the already-allowed `report()` seam.
- **Debounce-driven restore, with `quietMs` exceeding the producer's worst-case silence.** Setup emits
  a burst then quiets, so restore after `quietMs` with no new line; start the timer immediately so a
  zero-line case still restores; a `finally` backstop also restores. The shipped value was corrected
  `1500ms → 6000ms` in review because the producer can pause ~4s between lines — **tune a debounce to
  the producer's worst-case silence, not the typical gap.**
- **Idempotent + never-clobber-a-newer-patcher restore** (reassign only if the slot is still our
  replacement), **post-restore deactivation** (a stale reference delegates to the original), and a
  **re-entrancy guard** (a `console.error` fired from inside the sink delegates to the original) —
  defense-in-depth.
- **Injectable scheduler** (defaults to `setTimeout`/`clearTimeout` with `unref`) for deterministic
  fake-clock unit tests of debounce/reset/zero-line/idempotency.

**Scope.** Headful-only — the interceptor installs only after the command's `hasUI` guard (raw
`console.error` is what clobbers a TUI). No Python, no new tool/command/stage, no
`shared/contracts.md` change.

## Cross-references

- `extension/surfaces/surfaces.ts`, `extension/surfaces/report.ts` — the surfaces module (the only sanctioned
  rich-UI call sites)
- `extension/index.ts` — shared segment-store handle creation, once-only footer install
- `extension/testing/harness.ts` — factory-widget/placement capture, `invokeCommand`
- `shared/contracts.md` P2.T2c — the RPC dual-publish contract
- `docs/design/tui-charter.md` — the charter the surfaces converge to
- `docs/learned/pi/extension-seams.md` — `report()` and the consolidation-seam recipe
- `docs/learned/workflow/borrowed-packages.md` — the setFooter-clobber vetting/retirement recipe
