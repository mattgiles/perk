# Record: perk's Pi development pins at exact 1.1.0

**Status:** dated evidence record. Measured and authored 2026-10-09 on branch `plan-2710`
(base `840c0057`). It implements plan #2710 (Objective #2707, node 1.2): perk's four
`@earendil-works/*` development pins move from exact `1.0.0` to exact **`1.1.0`**, and the
lockfile is committed as npm produces it for 1.1.0. The precedents are
[`pi-1.0.0-dev-pins.md`](pi-1.0.0-dev-pins.md) (the last pin bump; this record keeps its shape)
and [`pi-1.1.0-characterization.md`](pi-1.1.0-characterization.md) (whose D1 lockfile preview
this record re-measures).

**Verdict: the dev pins and the lockfile sit at exact 1.1.0, and the committed lockfile is node
1.1's characterized graph byte for byte.** The four devDependencies (`pi-coding-agent`, `pi-ai`,
`pi-tui`, `pi-agent-core`) are each `"1.1.0"`; `typebox` stays `1.3.27`. The committed
`package-lock.json` hashes to the same SHA-256 (`5311cc4c…`) node 1.1 recorded for its throwaway
1.1.0 install. tsc (root, docs-site, prose-review), ty, ruff, Biome, both node:test tiers, the
full pytest suite and the live bridge smoke on both CLIs are green on the 1.1.0 install. One
forced test-fixture repair (rung 2); one behaviour change, adopted at planning: the
driven-compaction seam now reads `agent_settled.aborted`.

**No floor claim.** This record certifies nothing and gates nothing. The host floor
(`shared/host-floor.yaml`, `pi.min_version: "1.0.0"`), the remote install pin
(`REMOTE_PI_VERSION = "1.0.0"`), the pi-subagents supplier pin (`npm:pi-subagents@0.75.0`),
`.pi/settings.json`, the managed remote artifacts and the doctor guidance stamp are untouched.

## Registry preflight (Step 0, 2026-10-09T19:45Z)

Both stop gates were green, so the bump proceeded.

- **Gate A — the target.** `npm view @earendil-works/pi-coding-agent dist-tags --json` →
  `{"legacy-node20": "0.74.2", "latest": "1.1.0"}`;
  `npm view @earendil-works/pi-coding-agent@1.1.0 _hasShrinkwrap` → `false`. No newer release
  than the target.
- **Gate B — the floating transitives.** For each package, `npm view <pkg> versions --json`,
  then `semver.maxSatisfying(versions, "^1.1.0")` with the worktree's `semver`:

  | Package | Declared by | Published versions ≥ 1.0.0 | `maxSatisfying(^1.1.0)` | Other satisfying |
  |---|---|---|---|---|
  | `@earendil-works/chord` | pi-coding-agent `^1.1.0` | 1.0.0–1.0.4, 1.1.0 | `1.1.0` | none |
  | `@earendil-works/pi-codemode` | pi-coding-agent `^1.1.0` | 1.0.0–1.0.4, 1.1.0 | `1.1.0` | none |
  | `@earendil-works/pi-mcp` | pi-coding-agent `^1.1.0` | 1.0.0–1.0.4, 1.1.0 | `1.1.0` | none |
  | `@earendil-works/pi-telemetry` | pi-ai `^1.1.0` | 1.0.0–1.0.4, 1.1.0 | `1.1.0` | none |

  So the graph npm produces at bump time is the graph node 1.1 characterized.

## Snapshot matrix

| Component | Version | Provenance |
|---|---|---|
| Dev pins | `@earendil-works/{pi-agent-core,pi-ai,pi-coding-agent,pi-tui}` 1.1.0; `typebox` 1.3.27; `typescript` 6.0.3; `@types/node` 22.19.19; `@biomejs/biome` 2.4.16 | `package.json` `devDependencies`; the lockfile root entry mirrors it |
| Top-level dist on disk | `node_modules/@earendil-works/{chord,pi-agent-core,pi-ai,pi-codemode,pi-coding-agent,pi-mcp,pi-telemetry,pi-tui}` all 1.1.0; `typebox` 1.3.27 | each package's own `package.json`, read after `npm ci` |
| Floating transitives | `chord`, `pi-codemode`, `pi-mcp` (`^1.1.0` from pi-coding-agent) and `pi-telemetry` (`^1.1.0` from pi-ai), all 1.1.0. Held by the lockfile only, with no fifth pin | gate B above; perk imports none of them |
| Nested under pi-coding-agent | no `@earendil-works/*`, no `npm-shrinkwrap.json`. 12 non-Pi entries remain, all present in the base: `@silvia-odwyer/photon-node` 0.3.4, `chalk` 6.0.0, `graceful-fs` 4.2.11, `grok-mermaid` 0.2.3, `highlight.js` 10.7.3, `hosted-git-info` 9.0.3, `ignore` 7.0.8, `jiti` 2.7.0, `minimatch` 10.2.6, `proper-lockfile` 4.1.2 (+ its nested `retry` 0.12.0), `signal-exit` 3.0.7 | lockfile keys under `node_modules/@earendil-works/pi-coding-agent/node_modules/`; `ls node_modules/@earendil-works/pi-coding-agent/npm-shrinkwrap.json` → absent |
| `npm ls` gate | exit 0; every copy at 1.1.0, one `typebox@1.3.27`, all deduped (verbatim below) | `npm ls @earendil-works/pi-coding-agent @earendil-works/pi-ai @earendil-works/pi-tui @earendil-works/pi-agent-core typebox` |
| `node` / `npm` | v26.3.0 / 11.16.0 | `node --version`, `npm --version` |
| PATH `pi` | 1.0.0 (the mise global install; the pins never upgrade it) | `pi --version` |
| Pinned CLI | 1.1.0 (1.0.0 before the bump) | `node_modules/.bin/pi --version` |
| Worker SDK resolution | `file://…/.worktrees/plan-2710/node_modules/@earendil-works/pi-coding-agent/dist/index.js`, package `version` 1.1.0 | `import.meta.resolve('@earendil-works/pi-coding-agent')` from `extension/` |
| Registry | `latest` 1.1.0 | gate A |
| Native consumers | pi-subagents 0.75.0 (unchanged), pi-web-access 0.37.0, Plannotator `@plannotator/pi-extension` 0.28.8 | the worktree's `.pi/npm/node_modules/**/package.json` |
| Toolchain | tsc 6.0.3, Biome 2.4.16, ruff 0.15.15, ty 0.0.40 | `--version` |

The `npm ls` gate output after the bump, `npm prune` and `npm ci`:

```text
@mgiles/perk@4.0.0 /Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2710
├─┬ @earendil-works/pi-agent-core@1.1.0
│ ├── @earendil-works/pi-ai@1.1.0 deduped
│ └── typebox@1.3.27 deduped
├─┬ @earendil-works/pi-ai@1.1.0
│ └── typebox@1.3.27 deduped
├─┬ @earendil-works/pi-coding-agent@1.1.0
│ ├── @earendil-works/pi-agent-core@1.1.0 deduped
│ ├── @earendil-works/pi-ai@1.1.0 deduped
│ ├── @earendil-works/pi-tui@1.1.0 deduped
│ └── typebox@1.3.27 deduped
├── @earendil-works/pi-tui@1.1.0
└── typebox@1.3.27
```

## Lockfile delta (base `840c0057` → committed)

`just bump-pi 1.1.0` ran once (D7). Its install line reported
`added 12 packages, removed 134 packages, and changed 29 packages in 4s`, and `git diff -- package.json`
is exactly the four `"1.0.0"` → `"1.1.0"` lines. The `npm ls` gate line exited 0. The
`npm run typecheck` line failed as predicted, so the recipe stopped there:

```text
extension/pi/v1/delivery/commitCompact.test.ts(71,40): error TS2345: Argument of type '{ type: "agent_settled"; }' is not assignable to parameter of type 'RunnerEmitEvent'.
  Property 'aborted' is missing in type '{ type: "agent_settled"; }' but required in type 'AgentSettledEvent'.
extension/pi/v1/draftCompact.test.ts(51,40): error TS2345: Argument of type '{ type: "agent_settled"; }' is not assignable to parameter of type 'RunnerEmitEvent'.
  Property 'aborted' is missing in type '{ type: "agent_settled"; }' but required in type 'AgentSettledEvent'.
error: recipe `bump-pi` failed on line 51 with exit code 2
```

`lockdiff.mjs` and `lockrevert.mjs` were recreated verbatim from the characterization record's
methodology appendix (64 and 23 lines) and run against `git show HEAD:package-lock.json`.

**`lockdiff` classes**, the 134 removed nested keys elided:

```text
## (a @earendil-works/* top-level) — 8 entries (added 3, removed 0, version-changed 5)
  node_modules/@earendil-works/chord: added 1.1.0
  node_modules/@earendil-works/pi-agent-core: 1.0.0 -> 1.1.0
  node_modules/@earendil-works/pi-ai: 1.0.0 -> 1.1.0
  node_modules/@earendil-works/pi-codemode: added 1.1.0
  node_modules/@earendil-works/pi-coding-agent: 1.0.0 -> 1.1.0
  node_modules/@earendil-works/pi-mcp: added 1.1.0
  node_modules/@earendil-works/pi-telemetry: 1.0.4 -> 1.1.0
  node_modules/@earendil-works/pi-tui: 1.0.0 -> 1.1.0
## (b nested pi-coding-agent tree) — 134 entries (added 0, removed 134, version-changed 0)
## (c declared range changed) — 24 entries (added 7, removed 0, version-changed 17)
  node_modules/@anthropic-ai/sdk: 0.124.0 -> 0.129.0
  node_modules/@aws-sdk/core: 3.978.0 -> 3.978.1
  node_modules/@aws-sdk/credential-provider-env: 3.972.71 -> 3.972.72
  node_modules/@aws-sdk/credential-provider-http: 3.972.73 -> 3.972.74
  node_modules/@aws-sdk/credential-provider-ini: 3.973.16 -> 3.973.17
  node_modules/@aws-sdk/credential-provider-login: 3.972.78 -> 3.972.79
  node_modules/@aws-sdk/credential-provider-process: 3.972.71 -> 3.972.72
  node_modules/@aws-sdk/credential-provider-sso: 3.973.15 -> 3.973.16
  node_modules/@aws-sdk/credential-provider-sso/node_modules/@aws-sdk/token-providers: 3.1129.0 -> 3.1138.0
  node_modules/@aws-sdk/credential-provider-web-identity: 3.972.77 -> 3.972.78
  node_modules/@aws-sdk/nested-clients: 3.997.45 -> 3.997.46
  node_modules/@aws-sdk/signature-v4-multi-region: 3.996.46 -> 3.996.47
  node_modules/@aws-sdk/types: 3.974.5 -> 3.974.6
  node_modules/@aws-sdk/xml-builder: 3.972.40 -> 3.972.41
  node_modules/@smithy/core: 3.34.1 -> 3.35.2
  node_modules/@smithy/signature-v4: 5.7.3 -> 5.7.4
  node_modules/@smithy/types: 4.18.0 -> 4.19.0
  node_modules/balanced-match: added 4.0.4
  node_modules/brace-expansion: added 5.0.12
  node_modules/isexe: added 2.0.0
  node_modules/path-key: added 3.1.1
  node_modules/shebang-command: added 2.0.0
  node_modules/shebang-regex: added 3.0.0
  node_modules/which: added 2.0.2
## (d incidental re-resolution (ranges unchanged)) — 7 entries (added 0, removed 0, version-changed 7)
  node_modules/@aws-sdk/credential-provider-node: 3.972.83 -> 3.972.84
  node_modules/@aws-sdk/eventstream-handler-node: 3.972.34 -> 3.972.35
  node_modules/@aws-sdk/middleware-eventstream: 3.972.29 -> 3.972.30
  node_modules/@aws-sdk/middleware-websocket: 3.972.53 -> 3.972.54
  node_modules/@babel/runtime: 7.29.7 -> 7.29.10
  node_modules/undici: 8.10.0 -> 8.10.2
  node_modules/ws: 8.21.0 -> 8.22.0
## (e added/removed (ranges unchanged)) — 2 entries (added 2, removed 0, version-changed 0)
  node_modules/cross-spawn: added 7.0.6
  node_modules/quickjs-wasi: added 3.6.2
## total: 175 entries differ; base 758 entries, edited 636 entries
```

**`lockrevert` classification**, verbatim except that the long `breaks` lists of the chain
members are abbreviated with `…`:

```text
FORCED node_modules/@anthropic-ai/sdk 0.124.0 -> 0.129.0 (breaks node_modules/@earendil-works/pi-ai=0.129.0)
FORCED node_modules/@aws-sdk/core 3.978.0 -> 3.978.1 (breaks node_modules/@aws-sdk/credential-provider-env=^3.978.1 …)
FORCED node_modules/@aws-sdk/credential-provider-env 3.972.71 -> 3.972.72 (breaks node_modules/@aws-sdk/credential-provider-ini=^3.972.72 node_modules/@aws-sdk/credential-provider-node=^3.972.72)
FORCED node_modules/@aws-sdk/credential-provider-http 3.972.73 -> 3.972.74 (breaks node_modules/@aws-sdk/credential-provider-ini=^3.972.74 node_modules/@aws-sdk/credential-provider-node=^3.972.74)
FORCED node_modules/@aws-sdk/credential-provider-ini 3.973.16 -> 3.973.17 (breaks node_modules/@aws-sdk/credential-provider-node=^3.973.17)
FORCED node_modules/@aws-sdk/credential-provider-login 3.972.78 -> 3.972.79 (breaks node_modules/@aws-sdk/credential-provider-ini=^3.972.79)
revertable node_modules/@aws-sdk/credential-provider-node 3.972.83 -> 3.972.84
FORCED node_modules/@aws-sdk/credential-provider-process 3.972.71 -> 3.972.72 (breaks node_modules/@aws-sdk/credential-provider-ini=^3.972.72 node_modules/@aws-sdk/credential-provider-node=^3.972.72)
FORCED node_modules/@aws-sdk/credential-provider-sso 3.973.15 -> 3.973.16 (breaks node_modules/@aws-sdk/credential-provider-ini=^3.973.16 node_modules/@aws-sdk/credential-provider-node=^3.973.16)
FORCED node_modules/@aws-sdk/credential-provider-sso/node_modules/@aws-sdk/token-providers 3.1129.0 -> 3.1138.0 (breaks node_modules/@aws-sdk/client-bedrock-runtime=3.1127.0 node_modules/@aws-sdk/credential-provider-sso=3.1138.0)
FORCED node_modules/@aws-sdk/credential-provider-web-identity 3.972.77 -> 3.972.78 (breaks node_modules/@aws-sdk/credential-provider-ini=^3.972.78 node_modules/@aws-sdk/credential-provider-node=^3.972.78)
revertable node_modules/@aws-sdk/eventstream-handler-node 3.972.34 -> 3.972.35
revertable node_modules/@aws-sdk/middleware-eventstream 3.972.29 -> 3.972.30
revertable node_modules/@aws-sdk/middleware-websocket 3.972.53 -> 3.972.54
FORCED node_modules/@aws-sdk/nested-clients 3.997.45 -> 3.997.46 (breaks node_modules/@aws-sdk/credential-provider-ini=^3.997.46 …)
FORCED node_modules/@aws-sdk/signature-v4-multi-region 3.996.46 -> 3.996.47 (breaks node_modules/@aws-sdk/nested-clients=^3.996.47)
FORCED node_modules/@aws-sdk/types 3.974.5 -> 3.974.6 (breaks node_modules/@aws-sdk/core=^3.974.6 …)
FORCED node_modules/@aws-sdk/xml-builder 3.972.40 -> 3.972.41 (breaks node_modules/@aws-sdk/core=^3.972.41)
revertable node_modules/@babel/runtime 7.29.7 -> 7.29.10
FORCED node_modules/@smithy/core 3.34.1 -> 3.35.2 (breaks node_modules/@aws-sdk/core=^3.35.0 …)
revertable node_modules/@smithy/signature-v4 5.7.3 -> 5.7.4
FORCED node_modules/@smithy/types 4.18.0 -> 4.19.0 (breaks node_modules/@aws-sdk/core=^4.19.0 …)
FORCED node_modules/undici 8.10.0 -> 8.10.2 (breaks node_modules/@earendil-works/pi-coding-agent=8.10.2 node_modules/jsdom=^7.25.0)
revertable node_modules/ws 8.21.0 -> 8.22.0
```

That is **7 revertable** (`@aws-sdk/credential-provider-node`, `@aws-sdk/eventstream-handler-node`,
`@aws-sdk/middleware-eventstream`, `@aws-sdk/middleware-websocket`, `@babel/runtime`,
`@smithy/signature-v4`, `ws`) and **17 FORCED**: `@anthropic-ai/sdk` by pi-ai's exact pin, `undici`
by pi-coding-agent's exact pin, and 15 `@aws-sdk/*`/`@smithy/*` chain members, each forced only by
another re-resolved member's range. Two instrument notes. `undici`'s second "break" is spurious:
`lockrevert` matches dependents by name regardless of nesting, and `jsdom`'s `^7.25.0` is served by
its own nested `node_modules/jsdom/node_modules/undici` 7.29.0 in both lockfiles, so the base
8.10.0 never satisfied it either. The pi-coding-agent pin alone forces the move. Also,
`lockdiff`'s class (d) is not the same as "revertable": `undici` is (d) and still FORCED, because
pi-coding-agent's `8.10.2` declaration existed in the base too and was served by the nested copy
that is now gone.

**Kept: everything (D2).** No entry was reverted or hand-edited. The committed lockfile is npm's
own output for the 1.1.0 pins. The node text's rule ("revert only re-resolutions the edited
lockfile's own declarations do not force") was set aside at planning on 2026-10-09 by operator
decision, recorded as a dated deviation in the plan's Assumptions and as item 4 of the program
ledger ([`pre-pi-durable-true-up.md`](../../planning/pre-pi-durable-true-up.md) § "Deviations
recorded by Objective #2707"). The classification above is evidence only. The 15-entry chain
therefore stays as one unit.

**`npm prune`:** `up to date in 484ms`, with no removals (nothing was orphaned at 1.1.0).

**Shape checks:** `grep -c '"hasShrinkwrap"' package-lock.json` → `0`. No key starts with
`node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works/`. 636 entries, 9852
lines (11642 at base).

**Non-version churn:** none. No same-version entry changed any field (the root entry's
`devDependencies` is the only same-key difference). The lockfile carries two `"peer": true`
entries before and after, so there was no peer churn. pi-ai's and pi-coding-agent's `bin`
fields are unchanged.

**Validation:**

- **Byte-identical.** `shasum -a 256 package-lock.json` →
  `5311cc4ccecf2c1078f27351c1b438687b7bcd13490319f2fd6c8396d9f5e936`. After
  `npm install --package-lock-only` ("up to date in 422ms") the hash is identical and the
  `git diff --stat` is unchanged.
- **`npm ci`.** Exit 0, "added 525 packages in 8s", and the lockfile hash is unchanged afterwards.
- **`npm ls`.** `npm ls 2>&1 | grep -E 'extraneous|invalid|missing'` prints nothing.
- **Diff size.** `git diff --stat 840c0057 -- package.json package-lock.json`:
  `2 files changed, 417 insertions(+), 2207 deletions(-)`.

## Suite ledger (1.1.0 install, worktree `node_modules` + `.pi/npm`)

| Check | Result |
|---|---|
| `npm run typecheck` (root tsc) | the two TS2345 above before the fixture fix; green after it, with no other 1.1.0 diagnostic |
| `npm run docs:typecheck` (astro sync + tsc) | green |
| `npm run prose-review:typecheck` | green |
| `just typecheck-py` (ty) | green |
| `just lint-py` (ruff) + `just lint-js` (Biome) | green |
| `just test-js-fast` (173 files) | **2796 / 2796**, 0 skipped (TAP summary); "census drift guard: the installed consumers import exactly NATIVE_SDK_CENSUS" ran, not skipped |
| `just test-js-slow` (36 files) | **1001 / 1001**, 0 skipped. 2796 + 1001 = 3797 is node 1.1's 3796 plus the one new abort test |
| `uv run pytest` (full) | **8363 passed, 1 skipped**. The skip is `test_a_below_floor_real_pi_refuses_to_load_perk` ("needs a below-floor PATH pi"); node 1.1's two supplier-pin failures do not occur because the supplier stays 0.75.0 |
| Live bridge smoke, PATH `pi` 1.0.0 | `tests/test_native_sdk_bridge_live.py`: 2 passed, 1 skipped |
| Live bridge smoke, pinned CLI 1.1.0 | 2 passed, 1 skipped with `PATH="$PWD/node_modules/.bin:$PATH"`. This is the 1.1.0 CLI with the unchanged 0.75.0 supplier, the intermediate pair node 1.1 never ran |
| `/perk-selfcheck`, both hosts | identical: `selfcheck — 4.0.0: ok; shared=ok; ambient=reached (append=5376c); agents=reached (files=1); bridge=installed`; `native sdk bridge: installed (roots=2, specifiers=8)`; per-source rows `npm:pi-subagents@0.75.0=3`, `npm:pi-web-access=1` |
| `extension/substrate/hostAdmission.test.ts` | 14 / 14, including "precondition: the installed SDK this suite runs on is admitted by the shipped floor" against the installed 1.1.0 |
| `extension/piAiCompatGuard.test.ts` | 1 / 1, reading the deduped top-level pi-ai (no nested copy exists) |
| `extension/worker/stageExecutionE2e.test.ts` (real-runtime worker e2e) | 34 / 34 |
| `extension/substrate/restorationWindow.test.ts` | 3 / 3, none skipped (`hostRestoresPending` is re-verified at this pin bump) |
| `extension/worker/sdkAdapter.test.ts` | 38 / 38, including the settled-aborted `translateEvent` pin |
| `extension/pi/v1/delivery/commitCompact.test.ts` / `draftCompact.test.ts` | 37 / 37 and 16 / 16 |
| `bump-pi` gate lines run individually (D7) | the `npm ls` gate exits 0; `node --test extension/piAiCompatGuard.test.ts` 1 / 1; `test_pi_toolchain_pin_lockstep` passes (with `tests/test_pi_host.py` and `tests/test_workflow_artifacts.py`: 47 passed) |

**Final gate** at `4ed85111` (the complete change). This paragraph is the only later edit, and it
is docs-only:

```text
perk CI: all checks passed.
✓ lint-py (0s)
✓ lint-js (5s)
✓ typecheck-py (8s)
✓ typecheck-js (52s)
✓ typecheck-prose-review (24s)
✓ test-py-fast (132s)
✓ test-py-slow (55s)
✓ test-js (34s)
✓ docs-check (128s)
⊘ changelog-check (skipped — no changed files match CHANGELOG.md)
```

The first run-all at the same commit failed one case in `test-py-fast`:
`tests/test_implement_cmd.py::test_implement_explicit_id_inside_linked_worktree_writes_main_selector_only`
failed with `git worktree list failed: fatal: not a git repository` inside its tmp repo, and the
other 8309 passed. The change touches no Python logic. The case passed alone 3 / 3 (the file 9 / 9
each time) and in the earlier standalone full `uv run pytest` above. It is recorded as a flake
under the gate's concurrent checks, not triaged further here. The re-run above is the gate of
record.

## Fixes taken (with triage-ladder rung)

There were no rung-1 (install staleness), rung-3 (test expectation) or rung-4 (production
defect) repairs.

1. **Rung 2, a 1.1.0 type diagnostic.** `AgentSettledEvent` requires `aborted: boolean` at
   1.1.0. The `emitSettled` helpers in `extension/pi/v1/delivery/commitCompact.test.ts` and
   `extension/pi/v1/draftCompact.test.ts` now take `aborted = false` and emit
   `{ type: "agent_settled", aborted }`. Every existing call keeps the default.

**Adopted at planning, not a repair:** the driven-compaction abort arm
(`extension/pi/v1/drivenCompaction.ts`, behind `/commit-and-compact` and `/draft-and-compact`).
The seam consumes the one-shot record first. Then, if the event reports `event.aborted === true`,
it reports
`the driven run was aborted — compaction skipped; run /compact to compact anyway.` and skips both
the compaction and the continuation, before any door's settle verdict. The check is
value-detected: a 1.0.x host has no field and settles as before. It goes exactly as wide as Pi's
flag, which `AgentSession.abort()` alone sets: Escape while the model streams or tools run. Two
Escape states are residuals, recorded here and not handled:

- Escape during a retry wait calls `abortRetry()`.
- Escape during an automatic compaction calls `abortCompaction()`.

Each aborts only its own controller, never the run. Such a run settles `aborted: false` and takes
the ordinary path (settle → arbitration → compaction → continuation). The existing dirty-arm test
now passes `aborted: false` explicitly and names that path. No synthetic test can reach those two
handlers, because they live in Pi's interactive mode. The SDK worker still ignores
`agent_settled`: `translateEvent` of a settled-aborted plain-object fixture is pinned `null`,
`DriveEvent` is unchanged, and the worker's abort verdict stays its own signal/budget trip.
`objective.ts`'s budget re-render keeps ignoring the payload too.

**Comment and contract corrections:**

- The `toolGating.ts` header: since Pi 1.0.4, hidden tools' guidelines leave the prompt too.
- `shared/contracts.md` §8.40's hidden-tool sentence: it now states the current
  `buildSystemPromptSections` / `declaredTools` mechanism and keeps the 0.99.2–1.0.3 behaviour as
  history. The `hiddenTools` / `declaredTools` path was read in the installed 1.1.0
  `dist/core/system-prompt.js`.
- The two nested-pi-ai comments, in `piAiCompatGuard.test.ts` and
  `test_pi_toolchain_pin_lockstep`.
- One intent comment at `translateEvent`'s untranslated tail.

## Planning-time assumptions the measurement falsified

No count was falsified. Node 1.1's D1 preview held entry for entry:

- install summary 12 added / 134 removed / 29 changed;
- lockdiff 8 / 134 / 24 / 9: 8 `@earendil-works/*` top-level, 134 nested removals, 24 non-Pi
  version moves (17 in class c + 7 in class d) and 9 hoisted additions (7 in c + 2 in e);
  758 → 636 entries, 175 differing;
- lockrevert 7 revertable / 17 FORCED;
- 12 non-Pi nested entries left;
- the same lockfile SHA-256 as node 1.1's throwaway.

`npm prune` was the expected no-op. `--package-lock-only` was byte-identical. No peer or bin churn
appeared.

Three expectations differed in detail:

- **"The allow-scripts warnings are benign."** `npm ci` printed none at all, only
  `added 525 packages in 8s` (647 at the 1.0.0 record).
- **Node 1.1's prose summary of `undici`.** It recorded "breaks pi-coding-agent=8.10.2". The
  verbatim `lockrevert` line also names `jsdom=^7.25.0`, a name-matching artifact (see the
  instrument notes above). The classification is unaffected.
- **"`typebox` shows as not deduped"** (the 1.0.0-era learned bullet). It no longer holds:
  every `typebox` reference in the gate output is deduped onto the one top-level 1.3.27. This
  belongs to `/learn` candidate (1) below and is not edited here.

## Consequences and residuals

- **The self-repo remote worker's SDK moves to 1.1.0** through its `npm ci` worker-deps step.
  This was not verified live; node 7.1 owns the remote row.
- **The main checkout's root `node_modules` lags** at 1.0.0 until the operator runs `npm ci` there
  after the merge. Never run the suites from a lagging root.
- **The two residual Escape states** described under "Fixes taken". They are named in the seam
  header and the user docs, and handed to node 7.2's documentation reconciliation if Pi later
  widens the flag.
- **`/learn` candidates.** Not edited here; carried verbatim from the plan so the learn stage can
  harvest them:
  1. `docs/learned/toolchain/worktree-node-modules.md` § "Pi pin-bump mechanics" — the "keep
     pi-coding-agent's whole nested tree — it ships `hasShrinkwrap: true`" clause and the
     "`typebox` shows as not deduped" bullet are ≤ 1.0.0 facts; at ≥ 1.0.1 there is no
     shrinkwrap, the nested `@earendil-works/*` tree disappears, four `@earendil-works/*`
     transitives float at `^<version>` held only by the lockfile (registry preflight before a
     bump), and the 1.1.0 record is the new pointer.
  2. `docs/learned/pi/headless-session-drive.md` § the e2e worker tier — "pi-coding-agent bundles
     its own nested `@earendil-works/pi-ai`" holds only for the shrinkwrapped ≤ 1.0.0 line; the
     per-instance rule and the resolve-through-pi-coding-agent recipe still apply (they fall back
     to the deduped top-level).
  3. `docs/learned/pi/tool-loadout.md` "Accepted residual" — a hidden declaration's guidelines
     also leave the prompt at ≥ 1.0.4 (`buildSystemPromptSections` filters `declaredTools`;
     re-verify before rewriting).
  4. `agent_settled.aborted` is set only by `session.abort()` — Escape during retry backoff or
     auto-compaction does not set it.

  Also for 7.2: `docs/developers/pi-subagents-reverify.md`'s pin-bump wording.
- **Teardown.** The base lockfile copy, `lockdiff.mjs`, `lockrevert.mjs`, the registry outputs,
  the TAP reports and a `/perk-selfcheck` probe script lived under the run's gitignored scratch
  directory (`.perk/workflow/scratch/runs/…/agent/`). Nothing there was committed.
