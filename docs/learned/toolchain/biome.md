---
title: Biome / tsc gotchas in perk's pinned TS toolchain
read_when: You hit a Biome lint or tsc error in the extension (useIterableCallbackReturn, noAssignInExpressions, noUncheckedIndexedAccess) or a CI lint iteration on formatting.
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

## tsc strictness (`noUncheckedIndexedAccess`-style)

Indexed access into a record yields `T | undefined`, so `let dest = tables[""]` fails assignment to a
non-optional binding. Hold a `const root = {}` reference, **seed the record with it**
(`tables = { "": root }`), then assign `dest = root` — the local reference is non-optional even
though the index access isn't.

## Formatting is enforced in `lint` — auto-fix, don't hand-wrap

Biome formatting (line-wrapping long string literals, multi-line imports) is part of the `lint` gate.
**Run `npx biome check --write extension` to auto-fix before `run_ci`** rather than hand-wrapping —
hand-wrapping tends to disagree with Biome's formatter and burns an iteration. (This is the TS
analogue of the Python `ruff format` pre-commit trap — see `toolchain/ruff.md`.)

## Cross-references

- `extension/config.ts` — `parseTomlSubset` (where these three rules all bit at once)
- `docs/learned/toolchain/ruff.md` — the Python-side check-vs-format split
- `docs/learned/toolchain/worktree-node-modules.md` — why tsc/tests can use a stale SDK in a worktree
