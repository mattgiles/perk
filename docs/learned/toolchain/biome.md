---
title: Biome / tsc gotchas in perk's pinned TS toolchain
read_when: You hit a Biome lint or tsc error in the extension (useIterableCallbackReturn — incl. forEach expression-body assertions, noAssignInExpressions, noUncheckedIndexedAccess, noUselessUndefinedInitialization, noControlCharactersInRegex), a TS parameter-property failing under `node --test`, an `Omit<Union, K>` collapsing a discriminated union, the `organizeImports` assist not running under `biome format`, editing prose inside a template literal before a `--write` run (the backtick-mangling trap), auditing a `--write` pass after an import-path sweep, or a CI lint iteration on formatting (incl. new-file collapse — run `biome check --write` first).
---

# Biome / tsc gotchas

perk's TypeScript plane is gated by Biome (lint + format) and `tsc`, run via `just ci` (the `lint`
check). A few idiomatic JS patterns are rejected and cost a CI iteration if you don't pre-empt them.
The triggering examples below came from the `parseTomlSubset` rewrite (`extension/substrate/config.ts`) but the
rules are general.

## Biome lint rules that reject idiomatic JS

- **`useIterableCallbackReturn`** — `arr.forEach((x, i) => map.set(...))` is flagged because the
  arrow *returns* the `Map`. Use a plain `for` loop when the body's expression returns a value.
  The same trips on a `forEach` arrow whose expression body's **callee returns a value** — e.g. an
  assertion like `arr.forEach((e, i) => assert.equal(...))` — use a block body (`{ ... }`).
- **`noAssignInExpressions`** — the idiomatic `(arrays[name] ??= []).push(row)` is rejected. Expand
  to an explicit `let rows = arrays[name]; if (!rows) { rows = []; arrays[name] = rows; }`.
- **`noUselessUndefinedInitialization` → `noImplicitAnyLet` (the `let x = undefined` trap chain).**
  Biome rewrites `let x = undefined` to `let x;`, which then trips `noImplicitAnyLet`. Resolve by
  giving an explicit type instead of an initializer: e.g. `let model: Model<Api> | undefined;`.

## `noControlCharactersInRegex` rejects a sentinel placeholder — single-pass alternation instead

Translating a glob to a regex, the obvious two-stage approach is to first protect `**` (a
multi-segment wildcard) from the single-`*` rule by replacing it with a sentinel, then translate the
remaining `*`, then restore the sentinel. **Anti-pattern:** a control-character sentinel like `\^@`
(`\x00`) trips Biome's `noControlCharactersInRegex` the moment it lands in a regex literal.

The clean fix is a **single-pass alternation replace** that handles both wildcards in one go, with
the **two-star alternative ordered first** so the single-star rule never clobbers it — no sentinel
needed (allowed as an explicitly-marked example):

```ts
escaped.replace(/\\\*\\\*|\\\*/g, (m) => (m === "\\*\\*" ? ".*" : "[^/]*"));
```

Generalize: when a two-pass rewrite tempts you toward a placeholder, a single alternation with the
longer pattern listed first does the same job without a sentinel (and without the control-char
lint).

## Node 22 type-stripping rejects TS parameter properties

`constructor(private readonly x: T) {}` throws `ERR_UNSUPPORTED_TYPESCRIPT_SYNTAX` under
`node --test` — parameter properties are not erasable, and the test runner only strips types, it does
not transpile. Declare the field on the class and assign it in the constructor body instead.
Generalize: assume only **erasable** TS is allowed in `*.test.ts` (same class of trap as other
strip-only limits).

## tsc strictness (`noUncheckedIndexedAccess`-style)

Indexed access into a record yields `T | undefined`, so `let dest = tables[""]` fails assignment to a
non-optional binding. Hold a `const root = {}` reference, **seed the record with it**
(`tables = { "": root }`), then assign `dest = root` — the local reference is non-optional even
though the index access isn't.

## `Omit<Union, K>` collapses a discriminated union — use a distributive Omit

Building an emitter whose `emit()` accepts "any variant minus the stamped fields" (e.g.
`seq`/`t`), the obvious `Omit<RunEvent, "seq"|"t">` reduces to **only the common properties** — so
per-variant fields become tsc type errors. Fix: a distributive conditional over a **naked** type
param:

```ts
type DistributiveOmit<T, K extends PropertyKey> = T extends unknown ? Omit<T, K> : never;
```

Distribution fires only when the checked type is the naked param `T`; **inlining the union in the
conditional does NOT distribute.** Reusable any time you stamp common fields onto a union member.

## Unescaped backticks in template-literal prose + `--write` = silent mangling

A markdown-style backtick inside a template-literal prose constant terminates the string — and
`biome check --write` then "repairs" the parse break into garbage code instead of erroring. The
corruption is visible only by reading `git diff` after the format pass. Rules: escape backticks as
`` \` `` when editing prose inside template literals, and always review the diff after any
`--write` run on touched files — **formatter exit 0 ≠ semantic preservation**.

## Biome reorders imports during path-rewrite sweeps

After rewriting import paths (e.g. a module-move sweep), `biome check --write` re-sorts the import
block — expect whole-import-line moves when auditing "only path literals changed". See
`toolchain/ts-module-moves.md` for the full two-commit mv+sweep recipe.

## Formatting is enforced in `lint` — auto-fix, don't hand-wrap

Biome formatting (line-wrapping long string literals, multi-line imports) is part of the `lint` gate.
**Run `npx biome check --write extension` to auto-fix before `run_ci`** rather than hand-wrapping —
hand-wrapping tends to disagree with Biome's formatter and burns an iteration. Biome also prefers
collapsed single-line signatures/arrays on new files — run `biome check --write` on any new file
before CI. (This is the TS
analogue of the Python `ruff format` pre-commit trap — see `toolchain/ruff.md`.)

**Why `check --write`, not `format --write`:** `organizeImports` is an **assist** action, applied
**only by `biome check --write`, not `biome format --write`**. So `npm run format` (which runs
`biome format`) will **not** sort imports, and CI's `biome check` then fails on the unsorted order.
Always run `npx biome check --write extension` to apply import sorting alongside formatting.

## Cross-references

- `extension/substrate/config.ts` — `parseTomlSubset` (where these three rules all bit at once)
- `docs/learned/toolchain/ruff.md` — the Python-side check-vs-format split
- `docs/learned/toolchain/worktree-node-modules.md` — why tsc/tests can use a stale SDK in a worktree
- `docs/learned/toolchain/ts-module-moves.md` — the two-commit mv+sweep recipe whose audits hit the import reorder
- `docs/learned/workflow/config-tables.md` — the `[[ci]]` glob convention this regex translates
