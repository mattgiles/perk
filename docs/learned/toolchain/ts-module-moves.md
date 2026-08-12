---
title: The two-commit TS module move recipe (mv + import sweep)
read_when: You are moving extension TS modules into a subdirectory (the extension-layout tranches), auditing a path-rewrite sweep, or a justfile/Node test glob is dropping nested tests.
cluster: code-migration
---

# Moving TS modules: the two-commit mv + sweep recipe

The operational layer over `docs/design/extension-layout.md` Decision 2, validated end-to-end by
the `extension/doors/` tranche (PR #436). The recipe: one **pure-mv commit** (only `git mv`, no
content edits), then one **import-sweep commit** (path rewrites + the formatter pass). The facts
below are what a repeat tranche needs and need not re-derive.

## Resolve moved files' imports against their *pre-move* directory (the two-mode rule)

The central sweep hazard: after `git mv`, a moved file's `./cache.ts` import still *resolves
syntactically* relative to its **new** directory — so a naive "resolve against the file's current
parent, remap, re-relativize" sweep **silently no-ops on exactly the files that need fixing** (this
bit the first sweep attempt). **Anti-pattern:** a single resolve-against-current pass.

The correct rule is **two-mode**:

- For files in the **just-moved** directories, resolve each relative import against the **old**
  location (the pre-move directory — extension root for the doors/ tranche).
- For everything else (root files, previously-moved dirs like `doors/`), resolve against the
  **actual current** directory.

Then map mover stems → new directory and recompute the relative path. A ~30-line Python script
implementing that rule swept all ~60 affected files per tranche.

**`tsc --noEmit` is a complete sweep oracle** — a `TS2307` (cannot find module) is a missed import,
so no manual import auditing is needed once tsc is clean. Note the audit must tolerate more than
block reordering: **Biome reorders import-brace *members*** (the names inside `import { … }`), not
just whole import lines — so the `git diff -U0 | grep '^[+-]' | grep -v import/from/.ts` content
audit must tolerate reordered member lines too.

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

## Sed with an explicit stay-at-root module allowlist beats a generic rewrite

Rewrite only the **named root modules** (`s|from "\./(cache|coldDoor|…)\.ts"|from "../\1"|`).
That leaves movers' self-imports (a test importing its own module, e.g. `./submit.ts` in
`submit.test.ts`) untouched **by construction** — no special-casing of tests-import-own-module.

## Test-count parity, cheaply

Compare a `node -e` `globSync("extension/**/*.test.ts").length` count against the pre-move flat
count. Faster and more precise than diffing TAP output, and it directly proves a recursive-glob
fix didn't drop nested tests.

## Glob facts that need no re-verification in later tranches

- The source-scan guards (`surfacesGuard`/`cacheGuard`) scan recursively via
  `import.meta.dirname` — they cover new subdirectories with zero changes.
- tsconfig / biome / package.json globs are recursive already.
- The justfile's `"extension/**/*.test.ts"` **MUST stay quoted**: Node ≥22 self-expands `**`;
  unquoted, the shell flattens it under non-globstar bash and nested tests silently drop.

## Sources

- Issue #440 (plan #435 → PR #436) — the doors/ tranche
- Issue #451 (plan #445 → PR #448) — tranches 2+3 (the two-mode pre-move resolution rule)

## Cross-references

- `docs/design/extension-layout.md` — Decision 2 (the layout this recipe executes)
- `docs/learned/toolchain/biome.md` — the import reorder + the `--write` diff-review discipline
- `docs/learned/toolchain/worktree-node-modules.md` — fresh-worktree npm ci before tsc/node --test
