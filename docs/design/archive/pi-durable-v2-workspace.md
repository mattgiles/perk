# pi-durable v2 workspace — resolution and carve-out record

**Status:** measurement/evidence record, executed **2026-10-27** on branch `plan-2850` (plan
#2850 — Objective #2847, node 1.2), Node v24.22.1, npm workspace install at the worktree root. It
backs the binding record [`../pi-durable-v2-foundations.md`](../pi-durable-v2-foundations.md) §1
(*Perk host facts*) and §2 (*Location*, *Verification*, *Durable pin*).

**Verdict.** The private workspace `extension/pi/v2/` (`perk-v2`) resolves its three declared
packages to exactly their declared pins, all hoisted to the root `node_modules` (no nested
install); it ships in no tarball; v1 still links its whole import graph from a bare checkout with
the v2 source present and v2's dependencies absent; and v2's own guards, tiers and rows run apart
from every v1 surface.

## SOURCE-DERIVED

- **Declared pins** (`extension/pi/v2/package.json` `dependencies`, exact — `.npmrc`
  `save-exact=true`): `@earendil-works/pi-durable` 1.4.0, `@earendil-works/chord` 1.4.0,
  `@earendil-works/pi-ai` 1.4.0. pi-ai is declared because the host entry imports `createModels`
  from `@earendil-works/pi-ai/models` (`HarnessOptions.models` is required); it is the same exact
  version as the root dev pin, so npm dedupes it to one copy.
- **Registry closure** (`npm view`, planning day): `pi-durable@1.4.0` depends on `chord` 1.4.0,
  `pi-ai` 1.4.0, `pi-codemode` 1.4.0, `pi-telemetry` 1.4.0, `@silvia-odwyer/photon` 0.3.3,
  `diff` 8.0.4, `typebox` 1.3.27 (`engines.node >=22.19.0`); `chord@1.4.0` depends on `typebox`
  1.3.27 + `pi-telemetry` 1.4.0.
- **Expected hoist.** The committed lockfile already carried pi-ai, pi-codemode, pi-telemetry
  (1.4.0), diff 8.0.4 and typebox 1.3.27 at the top level, so the install should add exactly
  three packages (pi-durable, chord, photon) — every version coinciding — and hoist everything to
  the root `node_modules`, leaving no `extension/pi/v2/node_modules`.

## MEASURED

**Install.** `npm install` at the worktree root reported `added 4 packages` — the three registry
packages plus the `perk-v2` workspace link. `npm install --package-lock-only` afterwards left the
lockfile byte-identical; `npm ci` succeeded; `npm ls @earendil-works/pi-durable
@earendil-works/chord @earendil-works/pi-ai` exited 0.

**Lockfile diff** (`package-lock.json`, 57 insertions / 91 deletions): new entries
`extension/pi/v2` (the workspace), `node_modules/@earendil-works/pi-durable`,
`node_modules/@earendil-works/chord`, `node_modules/@silvia-odwyer/photon` and
`node_modules/perk-v2` (the link); the root `workspaces` list gains `extension/pi/v2`. The
deletions are 90 `"dev": true` flags (plus two `"devOptional": true` additions): pi-ai's
dependency subtree is now reachable from a workspace's runtime `dependencies`, so npm no longer
marks it dev-only. Kept whole, as an intentional dependency change.

**`npm ls`** over the v2 closure (one copy of each; v2's subtree shown):

```
├─┬ perk-v2@0.0.0 -> ./extension/pi/v2
│ ├─┬ @earendil-works/chord@1.4.0
│ │ ├── @earendil-works/pi-telemetry@1.4.0 deduped
│ │ └── typebox@1.3.27 deduped
│ ├── @earendil-works/pi-ai@1.4.0 deduped
│ └─┬ @earendil-works/pi-durable@1.4.0
│   ├── @earendil-works/chord@1.4.0 deduped
│   ├── @earendil-works/pi-ai@1.4.0 deduped
│   ├── @earendil-works/pi-codemode@1.4.0 deduped
│   ├── @earendil-works/pi-telemetry@1.4.0 deduped
│   ├── @silvia-odwyer/photon@0.3.3
│   ├── diff@8.0.4 deduped
│   └── typebox@1.3.27 deduped
```

(`npm ls … typebox diff` also lists `@pierre/diffs`' own `diff@9.0.0` under the prose-review
workspace — unrelated to v2.) Exit 0.

**Resolved locations** from inside the workspace (`cd extension/pi/v2 && node --input-type=module
-e '… import.meta.resolve(s) …'`):

| entry | resolves to |
|---|---|
| `@earendil-works/pi-durable` | `<root>/node_modules/@earendil-works/pi-durable/dist/index.js` |
| `@earendil-works/chord/context` | `<root>/node_modules/@earendil-works/chord/dist/context/index.js` |
| `@earendil-works/pi-ai/models` | `<root>/node_modules/@earendil-works/pi-ai/dist/models.js` |

`extension/pi/v2/node_modules` does not exist — the expected hoist holds.
`extension/pi/v2/host.test.ts` re-checks the version half on every run (each declared package
resolves to a `package.json` at exactly its declared pin).

**Pack exclusion.** `npm pack --dry-run --json` lists 350 files, none under `extension/pi/v2/`.
With the root `files` negation `!extension/pi/v2/` removed, the same command ships seven v2 files
(`host.ts`, `package.json`, `tsconfig.json`, and four `testing/` modules) — the negation is
load-bearing. `tests/test_packaging.py::test_npm_pack_lists_shipped_and_excludes_dev` and
`perk_dev.build.NPM_TARBALL_FORBIDDEN_PREFIXES` pin it.

**Bare-checkout load proof** (`extension/bareCheckoutLoad.test.ts`): passed — with no peer linked
the v1 probe fails `ERR_MODULE_NOT_FOUND` (`@earendil-works/pi-coding-agent`, from
`substrate/hostSdkVersion.ts`); with the five `peerDependencies` symlinked in, the probe links
`extension/index.ts`, `pi/activation.ts` and `worker/stageExecution.ts` and prints its marker; the
v2 probe fails `ERR_MODULE_NOT_FOUND` on `@earendil-works/chord` imported from
`extension/pi/v2/host.ts`. Wall: 1.0 s standalone, 5.3 s inside a full `test-js` run at 2 × 32
cores under host load ~19 — far below the 20 s slow-tier threshold, so it stays in the fast tier.

**Tiers.** `just test-v2` ran 15 cases in 0.5 s wall. `just test-v2-slow` printed `perk v2: the
slow tier selected no files — it stays empty until the first *.slow.test.ts lands` and exited 0.
The v1 suite (`just test-js`): **218** files on `origin/main`; **220** after — the three v2 test
files the old raw `extension/**/*.test.ts` glob would have swallowed are excluded, and
`extension/testing/v1Corpus.test.ts` + `extension/bareCheckoutLoad.test.ts` are added (183 fast,
37 slow). Full run: 79 s wall; its only failures were four browser-door cases that read
`PLANNOTATOR_PORT` from the measuring shell's environment, and they pass with it unset — unrelated
to this change.

**Guard controls** (planted in the live tree, then reverted):

| plant | fails |
|---|---|
| `import "../../substrate/config.ts"` in `pi/v2/host.ts` | `layeringGuard` — `v2ToV1` |
| `import "./pi/v2/host.ts"` in `extension/index.ts` | `layeringGuard` — `v1ToV2`; `importDirectionGuard` — unresolved specifier |
| `import "../pi/v2/host.ts"` in `extension/substrate/config.test.ts` | `layeringGuard` — `v1ToV2` |
| `import "perk-v2/host.ts"` in `extension/substrate/config.test.ts` (the npm workspace link `node_modules/perk-v2` resolves it to `extension/pi/v2/host.ts`) | `layeringGuard` — `v1ToV2` (added after review: the first cut checked only relative specifiers, and every guard passed this plant) |
| `pi/v2/kernel/probe.ts` importing `../host.ts` | `layeringGuard` — layer `violations` |
| `pi/v2/kernel/probe.ts` importing `@earendil-works/pi-durable` | `layeringGuard` — `leaked` |

**Row scheduling.** Driving `extension/delivery/ci.ts::runCiChecks` over the live
`[[ci.checks]]` rows with an injected changed set: `extension/substrate/config.test.ts` alone
schedules `lint-js typecheck-js test-js test-v2` (the v1-test-only edit reaches the cross-import
guard through `test-v2`'s `extension/**` glob); `extension/pi/v2/host.ts` alone schedules those
plus `typecheck-v2` and `test-v2-slow`; a docs-only change schedules none. (A live run-all
`run_ci` on this branch sees the whole branch diff, so the in-process gate is the isolated
observation.)
