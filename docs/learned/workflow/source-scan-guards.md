---
title: Source-scan guard tests
read_when: You are adding source/corpus guards, docs↔runtime censuses, marked fact tables, family maps, compile-time policy registries, or vacuity proofs.
cluster: quality-and-guards
---

# Source-scan guard tests

A framework test file can enforce architectural discipline — "this call/literal appears only in
the sanctioned seam" — with zero new dependencies, by scanning production source text. The recipe
below was established by `extension/surfacesGuard.test.ts` (rich-UI confinement) and refined by
the session-data path guards in both planes.

## Distillation

- Every guard needs a non-vacuity proof for its selector, pattern, and newly required entry.
- Guard both an artifact and the wiring that consumes it; source validity alone does not prove
  runtime effect.
- Secret targets must be provably untracked and ignored in the actual checkout; probe errors
  refuse the write, and late verification failures restore prior state.
- Ratcheted baselines name exact live exceptions and fail when an entry matches nothing.
- Live-corpus assertions beat frozen membership lists when concurrent changes can grow the set.
- Byte gates measure original bytes but normalize decoded newlines for text-reader parity; every
  counting rule needs a discriminating boundary fixture.
- Hub-and-children families keep one literal map, then guard its partition, hub census, live click
  tree, and two levels of non-vacuity — "Hub + N children family guards".
- A prose promise must name the guard's real allowlist; marked fact regions are validated on every
  canonical and mirrored surface — "Promise parity" and "Marker-bounded fact tables".
- Docs↔runtime censuses compare marked regions set-equal to live harness authorities, with no
  hand-maintained third list — "Docs↔runtime census guards".
- Editorial boundaries discover their corpus at runtime and use fence-aware scanners with
  mutation-style unit coverage — "Editorial-boundary guards".
- External-SDK policy registries pair compile-time key exhaustiveness with runtime unknown-field
  findings; adoption of a corpus guard includes the normalization sweep — "Compile-time census
  pins" and "Guard-adoption ripple".
- Import-graph guards fail on unresolvable specifiers, freeze birth censuses, and pin direction
  prefix arrays to literal contract lists — "Import-graph guard vacuity holes".

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

## Secret-writer safety is separate from atomicity

- **Ignored does not mean safe for secrets.** An ignore rule does not untrack an existing file,
  and main-worktree redirection means the proof must inspect the actual target checkout. The
  config writer in `src/perk/substrate/config.py` refuses unless that target is both untracked
  and gitignored, using the ignore probe in `src/perk/substrate/git.py`; a `GitError` is an
  unverifiable state and also refuses. Never reinterpret a broken safety probe as permission.
- **Atomic replace covers only pre-replace failure.** If read-back verification can fail after
  replacement, retain and restore the old bytes — or remove the newly created file — before
  raising. Give this late-failure rollback arm its own regression test rather than assuming the
  atomic primitive covers it.
- **Repo-wide write guards inspect recovery arms too.** A restore write inside an exception path
  must still use the sanctioned atomic seam. If an allowlist is unavoidable, keep it narrowly
  justified around that arm; never weaken the target-safety checks to make the guard pass.

## The spec↔artifact agreement guard

When an implementation artifact *transcribes* a binding design record, the guard
(`tests/test_docs_site_tokens.py` — the visual-blueprint token stylesheet) parses **both** the
record (markdown tables/snippets) and the artifact and asserts value-exact agreement, with no
hand-maintained expectation table. Three review-hardened rules:

1. **Zero third transcriptions** — parse every guarded value from the binding source, scoping
   section extraction (`text.index(start)` → `index(end)`) so nearby non-binding snippets can't
   be picked up. Test literals would let a reconciled blueprint edit pass while stale.
2. **Guard the wiring, not just the artifact** — also assert the integration seam that makes the
   leaf effective (the ordered `customCss` list in `docs/site/astro.config.mjs` + the entry
   resolving to the guarded stylesheet).
3. **Describe a normalizing comparison honestly** — never claim byte equality for a check that
   normalizes quotes/whitespace/hex case.

Plus: parser-sanity row-count asserts so a silently-empty markdown parse can't pass vacuously,
and a no-extras sweep (declared tokens not bound by the blueprint fail).

### Guards that pass while proving nothing

- **"Exact prefix, then validate the rest" is vacuous when the rest is empty.** A guard admitting
  a new required item must assert that item explicitly before generic tail-shape checks. The
  ordered `customCss` check once stayed green with the new entry deleted; the same rule applies
  when four expected hrefs must exist in order.
- **An exported artifact does not prove consumption.** Validation of `sidebar.mjs` survived
  deletion of the `sidebar` config key. Facts about config use belong in post-build or output
  assertions that exercise the consumer, not only in unit tests of the exported module.
- **Prefer live-corpus facts to frozen enumerations.** A fixed member list can remain internally
  valid while concurrent work grows the real set beyond it.

### Making a reconciliation rule structural

Assert the **entire** `devDependencies` mapping equals a literal dict (names AND versions) —
that defeats range expressions, dropped deps, and silent additions, turning a "changing a pin
requires objective reconciliation" design rule into CI structure.

## Hub + N children family guards

A reference hub split into several child pages needs one hand-maintained placement artifact, not
separate expected lists in every test. In `tests/test_user_docs_cli_reference.py`, the literal
`FAMILY_MAP` maps each page to its root-token set. Guard the map itself: pages form the intended
partition, every token has one placement, and known roots occur where expected.

The hub's marked census region is then compared set-equal to live roots minus an explicit
allowlist, with spot checks for known anchors. The extractor must recognize every documented-entry
shape that actually exists; scan the corpus before choosing its syntax rather than fitting a
regex to one convenient row. Prove non-vacuity at two levels: the overall family has enough
members and each child contributes enough roots for its role. The live side must walk the actual
click tree. A copied fingerprint constant only proves that two stale transcriptions still agree.

## Prose promises must match guard contracts

When prose says a test guarantees "every X", the same edit must compare that sentence with the
test's exclusions. State the allowlist or exception class in the prose. A guard can be internally
correct while its surrounding documentation promises a stronger property; treating the test name
as proof of the sentence hides that mismatch.

## Marker-bounded fact tables

Fact tables that are partly hand-authored and partly source-derived use unique, ordered
`perk:reference-facts:<key>:start` / `end` regions. The reusable extractor in
`tests/test_user_docs_reference_facts.py` validates marker uniqueness, order, non-overlap, and a
non-empty body before comparing facts. Guard every surface that carries the table, including
mirrors; marking only the canonical page turns the unmarked copy into an invisible drift surface.

One gap remains intentionally open. The perk-expert provider table has no reference-facts markers,
and the current provider check compares only provider-id order. Seam, default, and package columns
can drift silently on both surfaces. Gate membership is wired, but adding mirror markers and
extending the column comparison is follow-up guard work, not something the existing test proves.

## Docs↔runtime census guards

A census region should be set-equal to a live authority, never to a third expected list. Depending
on the surface, the authority may be a real extension harness session's registrations, an exported
tool census, or `loadRegistry()`. Hygiene checks make failures diagnostic: each marker occurs once,
the region is non-empty, each row carries exactly one code-form name, names are unique, and known
anchors are present.

Loading the extension from a docs test needs hermetic session state. Change into a scaffolded
temporary repo during extension load and neutralize `PERK_RUN_ID`; otherwise the checkout's own
`.perk/config.toml` can alter registrations and make a docs census depend on developer state.
`docs/site/src/in-session-reference.test.mjs` is the docs-site instance; its cross-scope execution
posture is described in `toolchain/docs-site-astro-starlight.md`.

## Editorial-boundary guards

An authoring boundary becomes structural only when the guard discovers its page set from the live
corpus rather than a frozen filename list. For fenced Markdown, scan with CommonMark-compatible
closing semantics so labels inside examples are not mistaken for editorial prose. Keep scanner
unit tests beside the guard and cover both directions: a real offender is found, while fenced
counterexamples remain exempt. Pin the test in `DOCS_CHECK_PYTEST_TARGETS`, and report label
violations as label problems rather than collapsing them into a generic parse failure. The
reference implementation is `tests/test_explanation_boundary.py`.

## Compile-time census pins against external SDKs

A hand-maintained per-field policy registry can be made exhaustive by checking it against
`keyof ExternalSdkType` with TypeScript's `satisfies` operator. An SDK field addition then breaks
`tsc` before a runtime scan can miss it. Pair that compile-time pin with a runtime
unclassified-field finding: one guards catalog completeness, the other protects values entering
through dynamic paths. In `tools/prose-map/catalog.ts`, registry insertion order also determines
generated fragment order, so exact output ordering is part of the policy surface.

## Guard-adoption ripple

Introducing a corpus-wide shape guard over an established convention requires a same-change
normalization sweep. Grandfathering existing drift makes the new rule vacuous where it matters
most. Expect a broad item-shape extractor to widen after it meets the real corpus, while narrower
quadrant or placement guards remain strict. This is discovery, not a reason to weaken the adopted
contract.

## Live-corpus guard craft

From the user-docs metadata guard (`tests/test_user_docs_metadata.py`), craft that generalizes to
any filesystem-walk corpus guard:

- **Collect ALL offenders per check before asserting** — one failure names every offending file,
  instead of a fix-one-rerun loop.
- **Add a non-vacuity floor** (`test_corpus_is_non_empty`, ≥40 routed files) — a filesystem-walk
  guard must prove its own selector still bites.
- **Exclude `bool` when validating YAML ints** (`isinstance(order, bool)`) — `bool` is an `int`
  subclass, so YAML `true` would pass a bare `isinstance(x, int)` check.
- **When two independent metadata records must agree**, a contiguous-run check over the sorted
  sequence proves mutual consistency cheaply.

## Ratcheted baselines

A temporary docs-link exception baseline is strongest as an exact frozen set of `{source, url}`
pairs, with each entry commented by the roadmap node responsible for removing it. Match every
live finding against that set, but also fail when a baseline entry matches zero live findings:
that stale-entry arm turns the baseline into a shrink-only ratchet and enforces burn-down. Let the
checked-in constants be the default parameters; tests can pass empty baselines through the same
seam to stay hermetic without weakening production behavior.

## Import-graph guard vacuity holes

Guards over the module import graph (direction rules, layering bans) have their own vacuity
holes (#2168):

- **Phantom-node vacuity.** Resolve every relative specifier against the scanned corpus; an
  unresolvable specifier is a guard *failure* (assert the `unresolved` set is empty), never a
  silent vertex — a typo'd or moved module otherwise falls out of the graph and its edges go
  unguarded. Add a discriminating control: a lax (extensionless) specifier and its extensioned
  twin must resolve to the same corpus member.
- **Anchor floors are real only when the predicate is corpus membership.** Freeze the birth
  census, keep a single registration path, and assert anchors are non-empty, in-directory, and
  corpus members — an anchor list checked only for non-emptiness can rot into names the scan no
  longer visits.
- **Direction rules over prefix arrays:** pin the arrays to literal contract lists (deepEqual)
  and drive the full source×target cross-product — a prefix array that silently gains or loses a
  member changes the rule without failing any test.

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

Two sibling rules from typed-capability migrations:

- **Capability guards must ban the concrete adapters.** Banning abstract interiors while the
  minting constructor stays importable is green-but-bypassable — enumerate the constructors that
  mint the capability and ban those (#2185).
- **Exact-set equality over the live production edge map doubles as the non-vacuity floor** —
  pair it with a positive floor proving the extractor still sees the guarded vocabulary (#2172).

## Byte-threshold corpus-gate craft

The learned-doc distillation scan in `src/perk/learn/docs_sync.py` exposed three test-design seams
that generalize to any corpus gate with byte and text semantics:

- **Separate measurement from parsing.** Keep the threshold on the original bytes, but normalize
  decoded CRLF and lone CR to LF before line parsing when the contract promises parity with a
  text-mode reader. Raw decode performs no universal-newline translation; without normalization,
  checkout newline style changes the verdict. Pin both CRLF and CR cases, and see
  `workflow/prompt-templates.md` for the same hazard at a rendering boundary.
- **Use a multibyte discriminator for byte limits.** ASCII fixtures cannot tell byte-counting from
  character-counting. Include content whose character count is under the boundary while encoded
  bytes cross it.
- **Give every stated counting rule a boundary fixture.** If interior blank lines count toward a
  header extent, for example, test that fact directly rather than hoping another size case covers
  it incidentally.

## Limits

- The guard is **textual, not semantic** — a banned call inside a template literal or a
  string-built eval escapes it.
- Allowlisted files are unguarded by the confinement rule itself (only repo-wide rules like the
  `setWorkingIndicator` ban scan them).
- The inverse false-positive: an import-direction guard that bans a module-path *string* trips on
  innocent docstring prose — a cross-reference reads as a violation though nothing imports.
  Posture: **rephrase the prose, don't allowlist** — a module-path literal in a docstring is
  dispensable provenance, and an allowlist entry would weaken the guard for real imports.
- **Lexical guards false-match prose generally** — expect to word around them or give them
  syntax-discriminating fixtures (the "ready"-as-tool and `from "` message-string instances)
  (#2033).
- **A prose-vocabulary guard is a narrow lexical sweep**, honestly scoped: compiled
  (regex, reason) tuples, locatable failure payloads, no allowlist, and explicitly accepted
  false-negative room (#2044).

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
