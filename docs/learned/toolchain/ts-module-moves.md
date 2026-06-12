---
title: The two-commit TS module move recipe (mv + import sweep)
read_when: You are moving extension TS modules into a subdirectory (the extension-layout tranches), auditing a path-rewrite sweep, or a justfile/Node test glob is dropping nested tests.
---

# Moving TS modules: the two-commit mv + sweep recipe

The operational layer over `docs/design/extension-layout.md` Decision 2, validated end-to-end by
the `extension/doors/` tranche (PR #436). The recipe: one **pure-mv commit** (only `git mv`, no
content edits), then one **import-sweep commit** (path rewrites + the formatter pass). The facts
below are what a repeat tranche needs and need not re-derive.

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

## Cross-references

- `docs/design/extension-layout.md` — Decision 2 (the layout this recipe executes)
- `docs/learned/toolchain/biome.md` — the import reorder + the `--write` diff-review discipline
- `docs/learned/toolchain/worktree-node-modules.md` — fresh-worktree npm ci before tsc/node --test
