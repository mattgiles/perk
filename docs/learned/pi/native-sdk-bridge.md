---
title: The host-SDK bridge — why native consumers loaded a second SDK graph, the registerHooks facades, and the guard interplay
read_when: You are touching extension/substrate/nativeSdkBridge.ts or hostSdk.ts, the perk init packages-order rule, a Pi/pi-subagents/pi-web-access bump that changes SDK identity, or a selfcheck bridge= state.
cluster: pi-extension
---

# The host-SDK bridge

The normative home is `shared/contracts.md` §8.73 (install point, census, consumer roots, host
entry, facades, states) — this doc does not restate it. It records the WHY behind the mechanism, the
Node and Pi facts it rests on, and the repo-specific traps that recur when touching it. Version
numbers are event stamps, never currency claims.

## Why two Pi packages load a second SDK graph

Verified against pi-coding-agent 0.87.0 / jiti 2.7.0 / Node ≥ 22.19: jiti's `evalModule` skips
transpilation when the module is ESM and the import is async, falling through to Node's native
loader — so only packages whose entry is compiled `.js` (`pi-subagents`, `pi-web-access`) bypass
Pi's `VIRTUAL_MODULES`/alias map and resolve `@earendil-works/*` from `node_modules`. Every
`.ts`-entry package shares the host instances for free. Check the entry extension before assuming a
package shares the host SDK. Measured effect (n=1 — re-measure, never copy;
`docs/design/archive/perk-startup-baseline.md`): SDK modules outside the host root 2,799 → 0.

## Pi package load order and the `perk init` ordering rule

Pi loads `packages` sequentially in project-settings array order (all package resources share one
precedence rank); top-level `extensions` and agent-dir extensions load BEFORE every package, so a
package extension can never bridge them. A per-extension load failure is caught and Pi continues.
Hence `perk/convergence/init/settings.py::_order_perk_before_native_consumers` keeps perk's entry
ahead of the native consumers (drift ⇒ `settings-wiring` `fail`); the bridge installs as the
factory's first statement, warns at `session_start` when it is not `installed`, and reports a
`bridge=` field in `/perk-selfcheck`.

## `node:module.registerHooks` facts

- The `resolve` hook fires for every `import`/`import()`, cached modules included; `load` fires only
  on a first fetch. Any "this package is being entered now" transition lives in `load`, not
  `resolve` (the `preloaded-consumer` fixture re-imports a cached entry to prove it).
- The most recently registered hook runs first and `nextResolve` reaches earlier hooks — a perk-dev
  `--import` tracer sees pass-throughs, never the bridge's short-circuited facades.

## Facade addressing

One physical `file:` URL (the real host entry) plus a `?perk-native-sdk-bridge=<spec>` query per
specifier, so `fileURLToPath(import.meta.resolve(...))` and pi-subagents' exact-entry
`import(pathToFileURL(realpath(dist/index.js)))` both land on the host. The facade source imports
nothing: it reads the namespace from a `globalThis[Symbol.for(...)]` slot captured by
`extension/substrate/hostSdk.ts` (pi-tui via the `extension/surfaces/surfaces.ts` re-export), so
identity is preserved.

## Why a bespoke conditional-exports resolver

Flag-less `import.meta.resolve(spec, parentURL)` ignores the parent argument (it resolved perk's own
devDependency copy); `createRequire(argv1).resolve` applies `require` conditions the host's `"."`
export lacks (`ERR_PACKAGE_PATH_NOT_EXPORTED`). The resolver mirrors Node's `resolvePackageTarget`
tri-state — `undefined` = no match, `null` = blocked, string = selected; arrays remember a `null`
block — with the disk check only AFTER selection. Collapsing the tri-state to a boolean made
`{ node: null, default }` fall through where Node blocks.

## Embedded-host detection

`process.argv[1]` is realpath-walked to a `package.json` named `@earendil-works/pi-coding-agent`;
anything else is `unsupported:embedded-host` — which makes every harness test inert with no
test-only switch.

## The claim-then-register commit and its provable rollback

The state vocabulary is a closed `BridgeState` union. The registry record is visible inside the
`registerHooks` callback. `releaseClaim` deletes the slot, writes `undefined` through a
non-configurable accessor, and neutralizes the record in place (`kind: "orphaned"`, roots cleared)
so `isBridgeRegistry` rejects it and a later activation declines. Rule: an atomic commit protocol's
rollback path needs its own failure mode and its own test. The `late.js` fixture (a module no
scenario loads until every status object is dropped) proves the hooks are process-owned.

## Which SDK identity a child runs under

Verified against pi-subagents 0.70.1:

- **Blocking `subagent` (`async: false`)** — `loadHostPiCodingAgent` imports the host package by
  absolute entry in the parent process, so the child shares the host identity (the exact-entry
  facade mapping).
- **Detached single run (`async: true`)** — a separate `node` runs `subagent-runner.js` with
  `--import runner-peer-preload.mjs`; there the bridge is `unsupported:embedded-host` by design.
- **Wave lanes** (`runs.all` under `workflowAwaitAsync: true`) are detached-runner children awaited
  via result files. A `run_scout_wave` proves the parent-side launch under the bridge; the blocking
  call is the leg that proves the in-process import.

The child-policy side is `pi/subagents.md` § "Native child execution" (Execution profile).

## Guard interplay (repo-specific, recurs)

- `surfacesGuard`'s pi-tui *specifier* rule is a text match, so a file naming
  `@earendil-works/pi-tui` as DATA trips it — back the allowlist entry with an import-aware lexed
  assertion (`extractSpecifiers`: the bridge imports node builtins only; `hostSdk.ts` reaches
  pi-tui only via `surfaces.ts`).
- `bareImportGuard`'s `\bimport\s*["']…["']` net trips on a string literal holding the Node
  export-condition name `import` — build such vocabularies from one split string.
- `tests/test_contracts_anchors.py::test_no_provenance_vocabulary` bans `**Status` — rephrase
  concept labels (`**The bridge status**`).
- `installedPackageGuard`'s sanctioned set is a per-file map — tests and fixtures import
  `NATIVE_CONSUMER_INSTALL_ROOT` rather than spell the path.
- Fixture trees needing `node_modules/`/`dist/` segments cannot be committed (gitignored) —
  materialize them from a `[source → destination]` table into `mkdtemp`.

## Process notes

The implement session runs the PRE-change extension, so in-session dogfood of a new
extension-level mechanism is impossible — plan the human pass. `pi --mode rpc` + `new_session`
proves a second factory activation in one process (the RPC notify carries only the selfcheck
summary line). Hermetic live smoke: `pi --approve` (writes no `trust.json`), the suite's throwaway
`PI_CODING_AGENT_DIR`, a placeholder `ANTHROPIC_API_KEY` (print mode's upfront auth check), and
scrub every behaviour-changing env var (`PERK_DISABLE_NATIVE_SDK_BRIDGE`, `PI_SUBAGENT_CHILD*`,
`PERK_SELFCHECK`, `PERK_RUN_ID`, `PERK_PROFILE_HANDOFF`).

## Residual risks (dated, at landing)

- A consumer evaluated before the bridge whose first post-install activity is a fresh module from
  outside its root reads as entered.
- CJS `require()` of a census specifier is unobserved.
- Bun/compiled-SEA Pi, embedded SDK hosts, user-scope `packages`, and agent-dir/`-e` extensions
  stay unbridged by design.
- Census widening = extend `NATIVE_SDK_CENSUS` + bump `BRIDGE_SCHEMA`. The drift guard scans only a
  live `.pi/npm/node_modules` install and `t.skip`s elsewhere (a CI network-install census arm was
  struck at review — immutable pinned files can never observe a newer version).

## Cross-references

- `shared/contracts.md` §8.73; `extension/substrate/nativeSdkBridge.ts`,
  `extension/substrate/hostSdk.ts`, `extension/surfaces/surfaces.ts`;
  `perk/convergence/init/settings.py`
- `docs/learned/workflow/startup-profiling.md` — the module census that measured the second graph
- `docs/learned/pi/subagents.md` — child execution profile
- `docs/learned/workflow/source-scan-guards.md` — the guard-refinement craft
