---
title: Biome / tsc gotchas in perk's pinned TS toolchain
read_when: You hit a Biome lint or tsc error in the extension (useIterableCallbackReturn, noAssignInExpressions, noUncheckedIndexedAccess, noUselessUndefinedInitialization), a TS parameter-property failing under `node --test`, an `Omit<Union, K>` collapsing a discriminated union, the `organizeImports` assist not running under `biome format`, or a CI lint iteration on formatting.
---

# Biome / tsc gotchas

perk's TypeScript plane is gated by Biome (lint + format) and `tsc`, run via `just ci` (the `lint`
check). A few idiomatic JS patterns are rejected and cost a CI iteration if you don't pre-empt them.
The triggering examples below came from the `parseTomlSubset` rewrite (`extension/config.ts`) but the
rules are general.

## Biome lint rules that reject idiomatic JS

- **`useIterableCallbackReturn`** — `arr.forEach((x, i) => map.set(...))` is flagged because the
  arrow *returns* the `Map`. Use a plain `for` loop when the body's expression returns a value.
- **`noAssignInExpressions`** — the idiomatic `(arrays[name] ??= []).push(row)` is rejected. Expand
  to an explicit `let rows = arrays[name]; if (!rows) { rows = []; arrays[name] = rows; }`.
- **`noUselessUndefinedInitialization` → `noImplicitAnyLet` (the `let x = undefined` trap chain).**
  Biome rewrites `let x = undefined` to `let x;`, which then trips `noImplicitAnyLet`. Resolve by
  giving an explicit type instead of an initializer: e.g. `let model: Model<Api> | undefined;`.

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

## Formatting is enforced in `lint` — auto-fix, don't hand-wrap

Biome formatting (line-wrapping long string literals, multi-line imports) is part of the `lint` gate.
**Run `npx biome check --write extension` to auto-fix before `run_ci`** rather than hand-wrapping —
hand-wrapping tends to disagree with Biome's formatter and burns an iteration. (This is the TS
analogue of the Python `ruff format` pre-commit trap — see `toolchain/ruff.md`.)

**Why `check --write`, not `format --write`:** `organizeImports` is an **assist** action, applied
**only by `biome check --write`, not `biome format --write`**. So `npm run format` (which runs
`biome format`) will **not** sort imports, and CI's `biome check` then fails on the unsorted order.
Always run `npx biome check --write extension` to apply import sorting alongside formatting.

## Cross-references

- `extension/config.ts` — `parseTomlSubset` (where these three rules all bit at once)
- `docs/learned/toolchain/ruff.md` — the Python-side check-vs-format split
- `docs/learned/toolchain/worktree-node-modules.md` — why tsc/tests can use a stale SDK in a worktree
