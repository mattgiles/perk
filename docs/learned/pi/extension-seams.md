---
title: Extension consolidation seams — minimal structural interfaces, the report() seam, the P1/P2/P3 triage
read_when: You are collapsing a repeated context-dependent idiom in the extension into one tested function, building a seam like report()/branchOf, or deciding which call sites a single-message seam can absorb.
---

# Extension consolidation seams

When the same context-dependent idiom (notify-if-UI-else-log, branch lookup, …) is repeated across
the extension, perk collapses it into one small tested seam. This doc captures the *shape* of those
seams — the recipe, the traps, and the triage for sites that don't fit — distilled from the
headless-safe `report()` seam (`extension/report.ts`) and its predecessor `branchOf`/`BranchSource`.

## The minimal-structural-interface recipe

Export a **tiny structural interface** that the real `ExtensionContext` satisfies *and* a test fake
implements trivially — `ReportTarget` (`hasUI` + `ui.notify`) in the report seam, mirroring
`BranchSource`/`branchOf`. This keeps the seam unit-testable offline (headful/headless × options ×
severity) without importing the SDK context. Return the built string from the seam for reuse as
tool-result text.

## "One idiom" is often 1 base + 1 superset — prefer an opt-in flag

The framing "the idiom is `ctx.hasUI ? ctx.ui.notify : console.error`" was demonstrably wrong: the
dominant error shape (the cold-door error closures) both notified-if-UI **and** always
console-logged, so failures land in run logs even in a TUI. The reconciliation was an opt-in
`alsoLog` boolean on one `report()` — preserving byte-for-byte existing behavior while keeping a
single seam, cleaner than forking the API or forcing every caller onto one shape. **Always grep the
actual call sites before trusting a one-line framing of "the idiom."**

## The de-prefixing trap when a seam owns the prefix

`report()` owns the `perk: <scope> — ` prefix, so any migrated message that *embedded its own*
`"perk: "` double-prefixes — strip it at migration. Scope/message token overlap then yields cosmetic
doubling (scope `checkpoints` + a message starting `checkpoints deferred`). That drift is acceptable
**only because** the suite substring-matches meaningful tokens, never full-string equality — verify
that assumption per-suite before accepting cosmetic drift.

## Not every site fits a single-message seam (the P1/P2/P3 triage)

- **P1 (migratable):** same message in both branches, severity-driven, no follow-up turn.
- **P2 (excluded):** command-echoes with *different* rich-headful vs terse headless text plus a
  `sendUserMessage` follow-up — a single-message seam loses information.
- **P3 (excluded):** self-prefixed status renders (already begin `perk N …`) and background
  catch-block diagnostics with no UI pairing — forcing them through the seam double-prefixes or
  invents a notify. A stderr-only `logError(scope, message)` sibling could absorb the P3
  catch-logs — deliberately deferred.

## Accepted-drift discipline

When a migration changes a message's prefix or severity-gating (e.g. planSave's final echo gained
the seam's prefix and the headless info-log), **flag it in the plan** and let tests adjudicate — the
planSave change deliberately inherited the seam's fail-safe.

## Cross-references

- `extension/report.ts` — `report()`, `ReportTarget`
- `docs/learned/pi/extension-api.md` — the SDK context the structural interface slices
- `docs/learned/workflow/warm-door-commands.md` — the warm doors whose error paths these seams serve
