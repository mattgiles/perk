---
title: Source-scan guard tests
read_when: You are adding or extending a test that enforces call-site or string-literal confinement by scanning source (the surfaces guard, the session-data path guards), or a guard fires and you're deciding whether to allowlist.
---

# Source-scan guard tests

A framework test file can enforce architectural discipline — "this call/literal appears only in
the sanctioned seam" — with zero new dependencies, by scanning production source text. The recipe
below was established by `extension/surfacesGuard.test.ts` (rich-UI confinement) and refined by
the session-data path guards in both planes.

## The node:test-as-grep-guard recipe

- **Leading-dot patterns skip declarations.** `/\.setStatus\(/` matches *call/member* sites
  (`handle.setStatus(`) but not structural-type **declarations** (`setStatus(slot: string): void;`
  in a `ui: {…}` interface) — those have no leading dot. This lets modules carry the UI interface
  type without tripping the guard.
- **Naive comment stripping is fine when justified.** Strip `/* */` then `//.*$` before matching;
  this would eat `//` inside string literals, but that's acceptable when no banned token plausibly
  appears in a string/URL — say so in a comment rather than building a real lexer.
- **Self-check against vacuous scans.** Assert the discovered file list is non-empty AND contains
  known anchors. Without this, a layout change silently empties the scan and the guard passes
  forever.
- **Scan production only.** Exclude `*.test.ts` and `testing/` — test fakes legitimately
  *implement* the banned surface. Use recursive readdir so future subdirectories are covered by
  default; normalize `path.sep` → `/` since recursive readdir returns OS-separator paths.
- **Per-line regex execution** gives direct 1-based line numbers for `file:line: match` violation
  messages; include remediation pointers (which seams to use instead) in the assertion message.

## String-literal-ban refinements

When banning a *string literal* (vs a call site), two additions:

- **A pattern-matches-the-seam self-check**: assert the allowlisted seam file itself matches the
  banned pattern (e.g. `cache.ts`/`cache.py` carry the `"scratch"`/`"runs"` literals). A pure
  files-nonempty self-check doesn't catch the pattern rotting when the seam is refactored.
- **In Python, scope segment-literal bans to path construction** — the quoted segment adjacent to
  a `/` operator (`(/\s*["'](scratch|runs)["'])|(["'](scratch|runs)["']\s*/)`) — because the same
  word may be a legitimate dict key elsewhere. The two planes' patterns may deliberately differ —
  match each plane's actual hazard, don't force symmetry.

## Limits

- The guard is **textual, not semantic** — a banned call inside a template literal or a
  string-built eval escapes it.
- Allowlisted files are unguarded by the confinement rule itself (only repo-wide rules like the
  `setWorkingIndicator` ban scan them).

## The binding convention these guards enforce

Rich-UI calls (`ui.notify`/`setStatus`/`setWidget`/`setFooter`) live ONLY in
`extension/surfaces/surfaces.ts` + `extension/surfaces/report.ts`; **extend the surfaces module rather than
allowlisting a new file** when the guard fires. `setWorkingIndicator` is banned everywhere
(charter D5 rescinded). The convention is recorded in three places — AGENTS.md "Developing perk",
`shared/contracts.md` §8.3, charter §7 row 4.1 — keep them in sync if the allowlist ever changes.

## Sources

- Issues #337, #358 (PRs #333, #355)

## Cross-references

- `extension/surfacesGuard.test.ts` — the founding instance
- `docs/learned/pi/tui-surfaces.md` — the surfaces module the rich-UI guard protects
- `docs/learned/workflow/session-data.md` — the accessor seam the path guards confine
