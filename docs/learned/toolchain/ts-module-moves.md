---
title: The two-commit TS module move recipe (mv + import sweep)
read_when: You are moving extension TS modules into a subdirectory (the extension-layout tranches), auditing a path-rewrite sweep, or a justfile/Node test glob is dropping nested tests.
cluster: code-migration
---

# Moving TS modules: the two-commit mv + sweep recipe

The operational layer over `docs/design/archive/extension-layout.md` Decision 2. The recipe: one
**pure-mv commit** (only `git mv`, no content edits), then one **import-sweep commit** (path
rewrites + the formatter pass). It was validated by the three extension-layout tranches of 2026-06
(`doors/` — PR #436; `factories/`+`checkpoints/`+`adapters/`+`worker/` and `substrate/`+`surfaces/`
— PR #448). `extension/doors/` itself is **gone** — evacuated into owning homes and deleted by
PR #2144 (2026-09-04); today's feature homes are the ones `extension/importDirectionGuard.test.ts`
Rule B enumerates (`authoring/`, `codeReview/`, `delivery/`, `learning/`, `library/`, …), with
Pi-facing registrations under `extension/pi/v1/`. The facts below are what a repeat tranche needs
and need not re-derive.

## Resolve moved files' imports against their *pre-move* directory (the two-mode rule)

The central sweep hazard: after `git mv`, a moved file's `./cache.ts` import still *resolves
syntactically* relative to its **new** directory — so a naive "resolve against the file's current
parent, remap, re-relativize" sweep **silently no-ops on exactly the files that need fixing** (this
bit the first sweep attempt). **Anti-pattern:** a single resolve-against-current pass.

The correct rule is **two-mode**:

- For files in the **just-moved** directories, resolve each relative import against the **old**
  location (the pre-move directory — the extension root for a first tranche).
- For everything else (root files, previously-moved directories), resolve against the **actual
  current** directory.

Then map mover stems → new directory and recompute the relative path. A ~30-line Python script
implementing that rule swept all ~60 affected files per tranche.

**`tsc --noEmit` is the complete oracle for resolvable static TS import specifiers** — a `TS2307`
(cannot find module) is a missed import, string-literal `import()` included. It is blind to path
*literals*: guard allowlists / self-checks / message text keyed on `/`-joined extension-relative
paths (the `readdirSync(import.meta.dirname, { recursive: true })` scanners in
`extension/*Guard.test.ts` — `surfacesGuard`, `cacheGuard`, `pathsGuard`, `writeGuard`,
`coldDoorGuard`, `bareImportGuard`, `installedPackageGuard`, `importDirectionGuard` today), a module
whose own location is load-bearing (`extension/substrate/resources.ts::packageRoot`'s own-depth
`".."` arithmetic), the justfile / `package.json` globs, and the cross-plane literals
(`package.json` `pi.extensions` → `./extension/index.ts`; `pyproject.toml`'s
`extension/hunkFeedback/perkFeedback.ts` force-include + `src/perk/_resources.py`'s sibling path;
`src/perk/run/run_worker.py`'s `extension/workerMain.ts` entry ladder). **Rule:** after tsc is
clean, `rg` the whole repo for every moved path and run the guards standalone to see their
non-vacuous self-checks still fire (`docs/design/archive/extension-layout.md` Decision 3 is the
recorded audit list). Note the audit must tolerate more than block reordering: **Biome reorders
import-brace *members*** (the names inside `import { … }`), not just whole import lines — so the
`git diff -U0 | grep '^[+-]' | grep -v import/from/.ts` content audit must tolerate reordered
member lines too.

For multi-tranche moves the guard mechanics need no rework: the source-scan guards' self-check keys
are `/`-joined extension-relative paths and the recursive scan covers new subdirs with **zero
changes**; pair every tranche with the post-move `*.test.ts`-count parity audit below.

## Blame survives both commits

The pure-mv commit records clean `R` renames; after the import-sweep commit the **cumulative diff
vs. base still shows ~R096–R099 similarity** for every moved file. So the sweep can touch every
moved file's imports without breaking rename detection — don't contort the sweep to avoid
"touching moved files".

## Audit the sweep on non-import lines

Biome re-sorts the import block after path rewrites (see `toolchain/biome.md`), so an
"only path literals changed" audit must **filter out import/`from "` lines** over `git diff`
rather than expecting byte-minimal edits — whole-import-line moves are part of the sweep, not a
violation.

## The sed allowlist is the single-destination special case

When ONE directory moves out of the root and the only cross-boundary edges are mover→stayer, a
sed over the named stay-at-root stems (`./<stem>.ts` → `../<stem>`) is the two-mode rule
degenerate to one mode: movers' self-imports (a test importing its own module, e.g. `./submit.ts`
in `submit.test.ts`) and mover→mover imports stay `./` **by construction** — no special-casing.
Tranche 1 (issue #440) used it; the stems it named (`cache`, `coldDoor`) are themselves now under
`substrate/`. It stops being sufficient the moment two destination directories move together, a
stayer imports a mover (`index.ts`'s paths), or a previously-moved directory is involved — then run
the two-mode script. The two sections describe **one rule at two sizes**, not two competing
techniques.

## Test-count parity, cheaply

Compare a `node -e` `globSync("extension/**/*.test.ts").length` count against the pre-move flat
count. Faster and more precise than diffing TAP output, and it directly proves a recursive-glob
fix didn't drop nested tests.

## Glob facts that need no re-verification in later tranches

- The source-scan guards (the `extension/*Guard.test.ts` `import.meta.dirname` scanners named
  above) scan recursively — they cover new subdirectories with zero changes.
- tsconfig / biome / package.json globs are recursive already.
- The justfile's `"extension/**/*.test.ts"` **MUST stay quoted**: Node ≥22 self-expands `**`;
  unquoted, the shell flattens it under non-globstar bash and nested tests silently drop.

## Extraction-migration sweep rules (the door→typed-op train)

Move/sweep mechanics from the door→typed-op extraction train (the seam-design craft lives in
`pi/extension-seams.md` § "Door→typed-op extraction craft" — one owner each, cross-referenced):

- **Plan the move verbatim, but budget a post-move simplification pass** — extraction surfaces
  dead branches and coverage overlap that only become visible once the code sits in its new home
  (#2190).
- **When a plan says both "move verbatim" AND names a specific delta, the delta is what gets
  silently swallowed** — verify each plan-specified departure as its own checklist item, separate
  from the verbatim-move check (#2173).
- **An API-deletion layer's test migration must delete local shims that reconstruct the old
  signature** — a helper rebuilding the deleted shape keeps dead-API coverage green (#2189).
- **Rename sweeps reach comments/doc-comments even in tiers declared behavior-untouched** — a
  "no changes to X" non-goal covers behavior, not narration (#2189, #2175).
- **Retirement sweeps cover derived enumerations and counts**, not just identifiers — a retired
  member's absence changes counts and "one of N" prose elsewhere (#2174).
- **Grep the whole repo for the doomed path, not the known-anchor list** — the executable grep is
  the acceptance, the plan's inventory is a floor (#2180).
- **After a dedupe-into-engine refactor, sweep for exports/test knobs whose last caller was a
  deleted duplicate** — orphaned seams survive tsc and tests (#2183).

## Sources

- Issue #440 (plan #435 → PR #436) — the doors/ tranche
- Issue #451 (plan #445 → PR #448) — tranches 2+3 (the two-mode pre-move resolution rule)
- PR #2144 — `doors/` evacuated and deleted (2026-09-04)

## Cross-references

- `docs/design/archive/extension-layout.md` — Decision 2 (the layout this recipe executes)
- `docs/learned/toolchain/biome.md` — the import reorder + the `--write` diff-review discipline
- `docs/learned/toolchain/worktree-node-modules.md` — fresh-worktree npm ci before tsc/node --test
- `docs/learned/pi/extension-seams.md` — "Door→typed-op extraction craft" (the seam-design half of
  the extraction train)
- `docs/learned/workflow/objective-delivery.md` — the façade-slice migration pattern (scope/review
  economics of typed-seam slices)
- `docs/learned/workflow/execution-path-parity.md` — migration parity pins over registration
  objects
