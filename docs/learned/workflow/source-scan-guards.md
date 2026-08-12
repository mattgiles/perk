---
title: Source-scan guard tests
read_when: You are adding or extending a test that enforces call-site or string-literal confinement by scanning source (the surfaces guard), or deciding whether to allowlist a firing guard.
cluster: quality-and-guards
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
  type without tripping the guard. **Bringing a new `ctx.ui.*` method under governance reuses this
  recipe verbatim** (#628): add a `.`-prefixed pattern (`/\.setWorkingMessage\(/`) allowlisted to the
  surfaces module — the seam's OWN interface declaration (`setWorkingMessage(message?): void;` inside
  a `ui:{…}` structural target) has no leading dot, so it is correctly **not** flagged as a violation.
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

## The per-API allowlist variant (the write guards)

`tests/test_write_guard.py` + `extension/writeGuard.test.ts` extend the family: repo-wide
bare-write bans with justified **per-file** (Python) / **per-API** (TS — `writeFileSync` /
`appendFileSync` / `writeFile` / …) allowlists, enforcing that every `.perk/workflow/` write
routes through the atomic seam (see `workflow/session-data.md`). Notable mechanics:

- **The seam stays clean by construction** — the Python seam writes via `os.fdopen`, so it needs
  no allowlisting at all.
- **Patterns require `(` after the name** so `writeFileSync(` never double-matches `writeFile(`.
- Both guards carry **stale-allowlist self-checks** (an allowlist entry that no longer matches
  fails the guard).

## Guarding a path family across a phased migration

When a perk-owned dot-directory path root moves in phases (the `.pi/`→`.perk/` arc — see
`dot-directory-migration.md`), widen the family guard to cover BOTH homes so the family stays
guarded throughout the migration:

- **Widen the segment alternation** `".pi"` → `(".pi"|".perk")` so an operator-adjacent dot-segment
  matches at either the old or the new home.
- **Flip the non-vacuous self-check to the new reality.** Assert `paths.py` now matches via
  `".perk" / "skills"` while `cache.py` still matches via `".pi" / "workflow"` (the workflow cache
  hasn't moved) — plus a positive `.perk/skills` arm and a negative `.perk/npm` arm (`.pi/npm` is a
  discovery namespace, not a guarded family).
- **Keep synthetic positive guard asserts honest.** Once production no longer contains
  `".pi" / CONFIG_FILENAME` (the config helpers derive from `config_dir`), a synthetic positive arm
  keeps the derived-construction pattern exercised.

The cross-cutting reaffirmation: the guard's operator-adjacency match is a regression **backstop, not
a completeness proof** — split-across-variables construction (`d = root / ".pi"` then `d / name`) and
single-string forms (`".pi/workflow"`) escape it, so a manual census is still required. The
family-scoped guard also doubles as a **consumer-census oracle**: its first run enumerates the
production consumers a plan census missed.

## Limits

- The guard is **textual, not semantic** — a banned call inside a template literal or a
  string-built eval escapes it.
- Allowlisted files are unguarded by the confinement rule itself (only repo-wide rules like the
  `setWorkingIndicator` ban scan them).

## The binding convention these guards enforce

Rich-UI calls (`ui.notify`/`setStatus`/`setWidget`/`setFooter`) live ONLY in
`extension/surfaces/surfaces.ts` + `extension/surfaces/report.ts`; **extend the surfaces module rather than
allowlisting a new file** when the guard fires. `setWorkingMessage` is **governed-but-permitted**
(confined to the surfaces module via its own leading-dot rule); `setWorkingIndicator` is banned
everywhere (charter D5 rescinded). The convention is recorded in three places — AGENTS.md "Developing perk",
`shared/contracts.md` §8.3, charter §7 row 4.1 — keep them in sync if the allowlist ever changes.

## Sources

- Issues #337, #358 (PRs #333, #355)

## Cross-references

- `extension/surfacesGuard.test.ts` — the founding instance
- `docs/learned/pi/tui-surfaces.md` — the surfaces module the rich-UI guard protects
- `docs/learned/workflow/session-data.md` — the accessor seam the path guards confine
- `docs/learned/workflow/dot-directory-migration.md` — the `.pi/`→`.perk/` arc the path-family guard widens across
