# Record: the pinned Pi 1.1.0 install set in both remote installs and every install-guidance string

**Status:** dated evidence record. Measured and authored 2026-10-22 (UTC) on branch `plan-2750`
(base `126046a8`). It implements plan #2750 (Objective #2707, node 1.5): the adopted Pi pin and
its **pinned install set** are declared once in `src/perk/substrate/pi_host.py`
(`PI_ADOPTED_VERSION = "1.1.0"`, the seven-member `PI_COMPANION_PACKAGES`, the eight exact
`PI_INSTALL_SPECS`, `PI_INSTALL_COMMAND`); `REMOTE_PI_VERSION` becomes that fact under its remote
name; both remote installs and every install-guidance string name the pinned set; an admitted PATH
`pi` other than the adopted pin gains an advisory (doctor `warn`, successful-init warning); and the
extension's SDK-boundary refusal names the adopted-pin-plus-pinned-set shape and a public URL. The
precedents are [`pi-1.1.0-host-floor.md`](pi-1.1.0-host-floor.md) (this record keeps its shape),
[`pi-1.1.0-dev-pins.md`](pi-1.1.0-dev-pins.md) and
[`pi-1.1.0-characterization.md`](pi-1.1.0-characterization.md).

**Verdict: the pinned install set resolves every `@earendil-works/*` package to 1.1.0 — on the
operator's toolchain and under the remote Node line — the committed remote artifacts are the
owner's render, and every guidance string names the pinned command. PASS.** The control (the
bare exact package, lockfile-free) reproduced the float: the package at 1.1.0 over seven nested
companions at 1.4.0, and 1.1.0's codemode extension failing at module link. The treatment (the
eight exact specs in one global command) placed eight top-level siblings, all 1.1.0, nothing
nested; `pi --version` printed `1.1.0`; the codemode module linked. The consumer shape hoisted the
same eight at 1.1.0 and recorded each as an exact pin. pi-subagents 0.76.1's peer-alias resolver
found every alias inside each throwaway prefix (`missing: []`, `outside: []`). The two toolchain
runs are byte-identical apart from the Node/npm versions and timings. `perk doctor --fix` rewrote
exactly the `Install pi` line of `.github/actions/perk-remote-setup/action.yml` and the
`remote-setup-action` digest in `.perk/managed-state.toml`; `perk-run.yml` stayed byte-identical; a
second `--fix` fixed nothing.

**No certification claim.** Pi 1.1.0 stays **adopted**, not **certified**: this node changes how
the adopted pin is installed, not what is certified. The live remote legs (the consumer composite
and the self-repo `npm ci` worker on a real runner) and the live certification record stay node
7.1's; the reverify guide's pin-surface step and the docs-narrative reconciliation stay node 7.2's.
Not moved here: the four dev pins and the lockfile, the self-repo `npm ci` worker,
`SUBAGENTS_PACKAGE` (0.76.1), the doctor guidance stamp (0.75.0), `shared/host-floor.yaml`'s values,
`node.min_version` / `engines.node`, `CHANGELOG.md`, `docs/learned/*`, and the operator's Node.

## Host snapshot (Step 0, 2026-10-22T20:13Z)

| Fact | Observed |
|---|---|
| `command -v pi` / `pi --version` | `~/.local/share/mise/installs/node/26.12.1/bin/pi` / `1.1.0` |
| PATH `pi`'s package root | `…/node/26.12.1/lib/node_modules/@earendil-works/pi-coding-agent` (1.1.0); its seven companions nested under it at 1.1.0 (the node-6.1 manual repair); no sibling `@earendil-works/*` |
| `node --version` / `npm --version` | `v26.12.1` / `11.20.0` — unchanged before and after every step |
| `mise install node@22.23.4` | installed beside 22.19.0, 24.11.1, 26.3.0, 26.12.1; mise's default stays 26.12.1 (`~/.config/mise/config.toml`) |
| `mise exec node@22.23.4 -- node --version` / `npm --version` | `v22.23.4` / `10.9.9` |
| `.pi/npm/node_modules/pi-subagents` | 0.76.1 |
| `HEAD` | `126046a8` (already at `origin/main`; the rebase was a no-op) |

No install in this node touched the operator's global `pi`, any `.pi/npm` or the default Node:
the PATH `pi` and its nested companions read exactly as above after Step 5.

## Registry preflight (Step 0.3–0.4, 2026-10-22T20:13:57Z) — the STOP gate passed

`npm view @earendil-works/pi-coding-agent dist-tags --json` (recorded, not a stop):

```json
{
  "legacy-node20": "0.74.2",
  "latest": "1.4.0"
}
```

`npm view @earendil-works/<pkg>@1.1.0 name version dependencies peerDependencies --json` for the
eight family members — the `@earendil-works/*` entries verbatim (every other dependency is a
non-family package; the full outputs are in the run's scratch log):

| Package @1.1.0 | `@earendil-works/*` dependencies | `peerDependencies` |
|---|---|---|
| `pi-coding-agent` | `chord`, `pi-ai`, `pi-mcp`, `pi-tui`, `pi-codemode`, `pi-agent-core` — each `^1.1.0` | none |
| `chord` | none (`esbuild` 0.28.2) | none |
| `pi-agent-core` | `pi-ai` `^1.1.0` | none |
| `pi-ai` | `pi-telemetry` `^1.1.0` | none |
| `pi-codemode` | none (`quickjs-wasi` 3.6.2) | none |
| `pi-mcp` | none (`cross-spawn` 7.0.6) | none |
| `pi-telemetry` | none (no dependencies) | none |
| `pi-tui` | none (`marked` 18.0.11, `get-east-asian-width` 1.6.0) | none |

The family is closed at eight, every internal range is `^1.1.0`, and no member declares a family
peer. Pi's direct non-family pins are exact (`undici` 8.10.2, `typebox` 1.3.27, …; `pi-ai` →
`@anthropic-ai/sdk` 0.129.0); deeper transitives keep floating within their ranges (a residual).

## The public refusal URL (Step 0.5)

`gh api repos/mattgiles/perk/contents/docs/user-docs/reference/requirements-and-compatibility.md
--jq .path` → `docs/user-docs/reference/requirements-and-compatibility.md` (exit 0;
2026-10-22T20:14:11Z); `gh repo view mattgiles/perk` → `PUBLIC`. The page is edited in this PR,
never moved, and keeps its `## Version compatibility` heading; `hostAdmission.test.ts` pins the
URL's path and heading to the checkout.

## Surface census (Step 0.6)

The census listed only the surfaces the plan names plus four classified extras: the
`tests/test_init_t5.py::_lean_ci_env` fixture row (stays — fixture data, not guidance);
`src/perk/convergence/init/__init__.py`'s `PI_NPM_SPEC` re-export (stays);
`src/perk/convergence/init/review_cli.py`'s single-spec `npm.install_global(HUNK_NPM_SPEC)` (stays
— the widened signature keeps single-spec callers); the `justfile` `bump-pi` comment naming
`REMOTE_PI_VERSION` (still true, untouched); and `src/perk/substrate/host_floor.py`'s module
docstring naming the remote install pin as a distinct fact — amended in the same breath as
`shared/host-floor.yaml`'s header comment to name the adopted Pi pin.

## The preflight matrix (Step 5) — MEASURED, throwaway prefixes under the run's scratch dir

`preflight.sh <label> [runner…]` ran the matrix once on the host toolchain (plain `npm`/`node`)
and once with every `npm`/`node` invocation prefixed `mise exec node@22.23.4 --` (distinct
prefixes `pf-host/`, `pf-remote-line/`). A census walks every `node_modules` recursively and lists
each `@earendil-works/*` package with its path and version (nested ones included). Beyond the
plan's checks, each layout also printed `import.meta.resolve` for six family specifiers from inside
the package directory, so a pass cannot be credited by a walk-up into the worktree's own
`node_modules` above the scratch dir; every resolved path lay inside its own prefix in both runs.

The **remote-line run is the gate** for Step 6. Its log, verbatim except that the scratch dir is
abbreviated to `$SCRATCH` and the long `resolveHostPeerAliases` command lines are elided (the
command is the plan's P5 probe):

```text
################ preflight: remote-line (2026-10-22T20:19:59Z)
== host node (outside the runner): v26.12.1
$ mise exec node@22.23.4 -- node --version
v22.23.4
$ mise exec node@22.23.4 -- npm --version
10.9.9

======== P2 — control: bare exact package, lockfile-free global install
$ mise exec node@22.23.4 -- npm install -g --prefix $SCRATCH/pf-remote-line/ctrl @earendil-works/pi-coding-agent@1.1.0
added 120 packages in 8s
-- census ($SCRATCH/pf-remote-line/ctrl/lib/node_modules)
@earendil-works/pi-coding-agent 1.1.0
@earendil-works/pi-coding-agent/node_modules/@earendil-works/chord 1.4.0
@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-agent-core 1.4.0
@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-ai 1.4.0
@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-codemode 1.4.0
@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-mcp 1.4.0
@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-telemetry 1.4.0
@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-tui 1.4.0
total=8 nested=7
-- declarations import from …/ctrl/lib/node_modules/@earendil-works/pi-coding-agent
$ … node --input-type=module -e "const m = await import('@earendil-works/pi-codemode/declarations'); console.log(typeof m.MCP_TYPESCRIPT_PREAMBLE)"
undefined
-- codemode tool.js module link
$ … node --input-type=module -e "await import('./dist/extensions/codemode/tool.js'); console.log('linked')"
SyntaxError: The requested module '@earendil-works/pi-codemode/declarations' does not provide an export named 'MCP_TYPESCRIPT_PREAMBLE'
[exit=1]

======== P3 — treatment: the pinned install set, one global command
$ mise exec node@22.23.4 -- npm install -g --prefix $SCRATCH/pf-remote-line/pin @earendil-works/pi-coding-agent@1.1.0 @earendil-works/chord@1.1.0 @earendil-works/pi-agent-core@1.1.0 @earendil-works/pi-ai@1.1.0 @earendil-works/pi-codemode@1.1.0 @earendil-works/pi-mcp@1.1.0 @earendil-works/pi-telemetry@1.1.0 @earendil-works/pi-tui@1.1.0
added 130 packages in 7s
-- census ($SCRATCH/pf-remote-line/pin/lib/node_modules)
@earendil-works/chord 1.1.0
@earendil-works/pi-agent-core 1.1.0
@earendil-works/pi-ai 1.1.0
@earendil-works/pi-codemode 1.1.0
@earendil-works/pi-coding-agent 1.1.0
@earendil-works/pi-mcp 1.1.0
@earendil-works/pi-telemetry 1.1.0
@earendil-works/pi-tui 1.1.0
total=8 nested=0
-- bins
pi
pi-ai
$ mise exec node@22.23.4 -- $SCRATCH/pf-remote-line/pin/bin/pi --version
1.1.0
-- declarations import from …/pin/lib/node_modules/@earendil-works/pi-coding-agent
string
@earendil-works/pi-codemode/declarations -> $SCRATCH/pf-remote-line/pin/lib/node_modules/@earendil-works/pi-codemode/dist/declarations.js
@earendil-works/pi-ai -> $SCRATCH/pf-remote-line/pin/lib/node_modules/@earendil-works/pi-ai/dist/index.js
@earendil-works/pi-tui -> $SCRATCH/pf-remote-line/pin/lib/node_modules/@earendil-works/pi-tui/dist/index.js
@earendil-works/pi-agent-core -> $SCRATCH/pf-remote-line/pin/lib/node_modules/@earendil-works/pi-agent-core/dist/index.js
@earendil-works/chord -> $SCRATCH/pf-remote-line/pin/lib/node_modules/@earendil-works/chord/dist/index.js
@earendil-works/pi-mcp -> $SCRATCH/pf-remote-line/pin/lib/node_modules/@earendil-works/pi-mcp/dist/index.js
-- codemode tool.js module link
linked
[exit=0]

======== P4 — consumer shape: worker-deps install (with @mgiles/perk@4.0.0)
$ mise exec node@22.23.4 -- npm view @mgiles/perk@4.0.0 version
4.0.0
$ mise exec node@22.23.4 -- npm install @mgiles/perk@4.0.0 @earendil-works/pi-coding-agent@1.1.0 @earendil-works/chord@1.1.0 @earendil-works/pi-agent-core@1.1.0 @earendil-works/pi-ai@1.1.0 @earendil-works/pi-codemode@1.1.0 @earendil-works/pi-mcp@1.1.0 @earendil-works/pi-telemetry@1.1.0 @earendil-works/pi-tui@1.1.0 --prefix $SCRATCH/pf-remote-line/wk --legacy-peer-deps --save-exact
added 122 packages in 4s
-- census ($SCRATCH/pf-remote-line/wk/node_modules)
@earendil-works/chord 1.1.0
@earendil-works/pi-agent-core 1.1.0
@earendil-works/pi-ai 1.1.0
@earendil-works/pi-codemode 1.1.0
@earendil-works/pi-coding-agent 1.1.0
@earendil-works/pi-mcp 1.1.0
@earendil-works/pi-telemetry 1.1.0
@earendil-works/pi-tui 1.1.0
total=8 nested=0
-- $SCRATCH/pf-remote-line/wk/package.json
{
  "dependencies": {
    "@earendil-works/chord": "1.1.0",
    "@earendil-works/pi-agent-core": "1.1.0",
    "@earendil-works/pi-ai": "1.1.0",
    "@earendil-works/pi-codemode": "1.1.0",
    "@earendil-works/pi-coding-agent": "1.1.0",
    "@earendil-works/pi-mcp": "1.1.0",
    "@earendil-works/pi-telemetry": "1.1.0",
    "@earendil-works/pi-tui": "1.1.0",
    "@mgiles/perk": "4.0.0"
  }
}
-- declarations import from …/wk/node_modules/@earendil-works/pi-coding-agent
string
(the six resolve lines all under $SCRATCH/pf-remote-line/wk/node_modules/@earendil-works/…)

======== P5 — pi-subagents 0.76.1 resolveHostPeerAliases over the treatment layouts
-- root=$SCRATCH/pf-remote-line/pin/lib/node_modules/@earendil-works/pi-coding-agent prefix=$SCRATCH/pf-remote-line/pin
{"missing":[],"outside":[]}
{
 "@earendil-works/pi-coding-agent": "<prefix>/lib/node_modules/@earendil-works/pi-coding-agent/dist/index.js",
 "@earendil-works/pi-agent-core": "<prefix>/lib/node_modules/@earendil-works/pi-agent-core/dist/index.js",
 "@earendil-works/pi-tui": "<prefix>/lib/node_modules/@earendil-works/pi-tui/dist/index.js",
 "@earendil-works/pi-ai": "<prefix>/lib/node_modules/@earendil-works/pi-ai/dist/compat.js",
 "@earendil-works/pi-ai/compat": "<prefix>/lib/node_modules/@earendil-works/pi-ai/dist/compat.js",
 "@earendil-works/pi-ai/oauth": "<prefix>/lib/node_modules/@earendil-works/pi-ai/dist/oauth.js",
 "@earendil-works/pi-ai/providers/all": "<prefix>/lib/node_modules/@earendil-works/pi-ai/dist/providers/all.js",
 "typebox": "<prefix>/lib/node_modules/@earendil-works/pi-coding-agent/node_modules/typebox/build/index.mjs",
 "typebox/compile": "<prefix>/lib/node_modules/@earendil-works/pi-coding-agent/node_modules/typebox/build/compile/index.mjs",
 "typebox/value": "<prefix>/lib/node_modules/@earendil-works/pi-coding-agent/node_modules/typebox/build/value/index.mjs",
 "@earendil-works/chord": "<prefix>/lib/node_modules/@earendil-works/chord/dist/index.js",
 "@earendil-works/chord/context": "<prefix>/lib/node_modules/@earendil-works/chord/dist/context/index.js"
}
-- root=$SCRATCH/pf-remote-line/wk/node_modules/@earendil-works/pi-coding-agent prefix=$SCRATCH/pf-remote-line/wk
{"missing":[],"outside":[]}
(the same twelve aliases, each under <prefix>/node_modules/…; typebox hoisted at <prefix>/node_modules/typebox)
################ end preflight: remote-line; host node: v26.12.1
```

**The host run** (2026-10-22T20:19:35Z; Node `v26.12.1` / npm `11.20.0`) produced the same log
line for line: a `diff` of the two logs, with the prefix label and the `mise exec` prefix
normalized, differs only in the header timestamp, the `node`/`npm` version lines, the
`added N packages in Ns` timings and mise's `Reshimming mise <version>…` line (mise's npm hook
re-shims its own install dir; it does not scan a `--prefix`). Both runs: P2 `total=8 nested=7`
at 1.4.0 + `undefined` + the module-link `SyntaxError`; P3 `total=8 nested=0` all 1.1.0 +
`pi --version` `1.1.0` + `string` + `linked`; P4 `total=8 nested=0` all 1.1.0 + eight exact
`package.json` pins + `string`; P5 `{"missing":[],"outside":[]}` for both layouts. The host
`node --version` read `v26.12.1` before, between and after the runs. The throwaway prefixes were
removed afterwards; they never entered the diff.

**SOURCE-DERIVED facts the measurement now corroborates** (read at planning; not re-derived
here): npm's global install builds its ideal tree from an empty root plus the explicit specs, and
an edge whose target already resolves through the parent chain (for a global top-level package the
parent is the global root, so siblings count) is valid and never re-placed (`@npmcli/arborist`
`build-ideal-tree.js::#globalRootNode`, `place-dep.js`, `edge.js`; read at npm 11.20.0 — the npm
10.9.9 run above shows the same placement); Node's CJS and ESM resolvers walk from the package
directory up to `<prefix>/lib/node_modules/` (the `node_modules` segment is skipped, `lib` is not —
the P3 resolve lines show it); pi-subagents 0.76.1's `findPeerPackageDir`
(`src/runs/background/runner-aliases.js`) checks `<root>/node_modules/<pkg>` and then every
ancestor `node_modules` root, so global siblings resolve — and so would a dev graph above a
throwaway prefix, which is why P5 asserts `outside: []` and not only `missing: []`.

## The owner run (Step 6)

Only after the remote-line run passed: `uv run perk doctor --fix` in `$WT` (never the stale global
`perk`). Its `Fixed` block:

```text
Fixed
  - .github/actions/perk-remote-setup/action.yml: updated
  - .perk/local.toml: created
  - .perk/managed-state.toml: updated
```

The tracked diff — exactly the expected footprint:

```diff
--- a/.github/actions/perk-remote-setup/action.yml
+++ b/.github/actions/perk-remote-setup/action.yml
@@ -26,7 +26,7 @@ runs:
     - name: Install pi
       shell: bash
-      run: npm install -g @earendil-works/pi-coding-agent@1.1.0
+      run: npm install -g @earendil-works/pi-coding-agent@1.1.0 @earendil-works/chord@1.1.0 @earendil-works/pi-agent-core@1.1.0 @earendil-works/pi-ai@1.1.0 @earendil-works/pi-codemode@1.1.0 @earendil-works/pi-mcp@1.1.0 @earendil-works/pi-telemetry@1.1.0 @earendil-works/pi-tui@1.1.0
--- a/.perk/managed-state.toml
+++ b/.perk/managed-state.toml
@@ -18,7 +18,7 @@ hash = "sha256:b794695bee28c07cee56bfd2c21fd6126f6cd35fdad64d150c72818a6634820b"
 path = ".github/actions/perk-remote-setup/action.yml"
 kind = "file"
 version = "4.0.0"
-hash = "sha256:6c3867ad2cad206f1065e3158d8e465a0ff0e845fbf151127093cfa189f71376"
+hash = "sha256:c9385b6e90eb3561fde1e1485cc7dc93838b6ce82a5c168732784045d72a4dd7"
```

`perk-run.yml` stayed byte-identical; the self-repo worker-deps step stays `npm ci`. A second
`uv run perk doctor --fix` printed no `Fixed` block and changed nothing tracked.

**One unrelated fix failure, classified.** Both runs reported `✗ skills delivery failed: skills
update --sync exited 1` with every declared skill listed as `conflict`. This is local to the
implement worktree: its `.agents/skills/*` entries are symlinks the worktree setup points into the
main checkout's skills-CLI cache, while the worktree itself carries no skills-CLI state, so the
CLI (seeding a fresh local cache) sees every existing entry as a conflict. No tracked file moved,
the symlinks were untouched, and the report stayed `✓ healthy`. The owner run's untracked,
gitignored side effects — `.agents/local.yaml`, a 132 MB `.agents/cache/` clone cache and a
comment-only `.perk/local.toml` template — were removed to restore the worktree's prior state.
`tests/test_workflow_artifacts.py::test_committed_self_repo_remote_artifacts_are_the_owners_render`
pins the committed artifacts to the owner's render.

## Offline proofs (Step 7)

- **Pins, each shown red against the pre-change code.** With the pre-change `src/` restored and
  only the Step-1 substrate constants added (so collection succeeds), 17 of the new or updated
  Python pins failed — the remote-pin alias, every advisory row (env, doctor, init success, both
  init failure paths, the render mark), the onboarding label/prompt/install-call/`_boom`/"Node
  first" rows, the composite's `Install pi` literal and the consumer worker-deps literal — and the
  remediation rows asserting an empty `advisory` on not-ok rows. Against the fully pre-change
  tree, every touched Python file fails at import (the constants do not exist) and
  `hostAdmission.test.ts` fails at import (`REQUIREMENTS_DOC_URL`). All green on the change.
- **The family is closed against the characterized lockfile**
  (`tests/test_pi_host.py::test_pinned_install_family_is_closed_against_the_characterized_lockfile`):
  `package-lock.json`'s top-level `node_modules/@earendil-works/*` names are exactly
  `{PI_NPM_SPEC, *PI_COMPANION_PACKAGES}`, every family range those entries declare names a member,
  and none declares a family peer.
- **The refusal URL is pinned to the checkout** (`hostAdmission.test.ts`): the constant equals the
  literal URL, the path after `/blob/main/` exists, and the page contains `## Version
  compatibility`.
- **Targeted gates** (Step 9): the eight touched Python suites
  (`test_pi_host`, `test_env`, `test_doctor`, `test_init_onboarding`, `test_review_cli`,
  `test_workflow_artifacts`, `test_launch_materialize`, `test_init_t5`) — 536 passed;
  `node --test extension/substrate/hostAdmission.test.ts extension/index.test.ts` — 31 passed;
  ruff, Biome, `ty` and `tsc` clean. The run-all `run_ci` gate runs once, immediately before
  `/submit`. `just test-js-slow` is not run (D9: no dev, floor or supplier pin moves; the one TS
  change is a refusal text pinned in the fast tier).

## Decisions (D1–D10, resolved at planning with the operator; D2/D3/D8 revised across two review rounds)

- **D1 — one command, eight exact specs (the global shape).** Measured above. Rejected: a bare
  `@1.1.0` install followed by a second install inside the package directory (two network
  installs, the first landing the broken graph; a `$(npm root -g)` substitution; a second npm
  gateway function).
- **D2 — guidance plus an advisory; the init warning is a success-report promise.** Narrowed after
  review: failure reports (`missing_tool`, `not_a_repo`, `skills_conflict`, `legacy_config`,
  `skills_sync_failed`) carry no advisory; doctor reports the row on every run; the env `--json`
  row keeps its four keys. No new interactive gesture.
- **D3 — the TS refusal names the shape and a reachable public URL.** Revised twice: the refused
  Pi need not be the PATH `pi` (so "perk doctor prints it" can be false), and the docs tree ships
  in no distribution (so a repo-relative path is unreachable). Rejected: a shared cross-plane pin
  file so the TS plane could print the command itself (a sizeable widening for one message — a
  follow-up candidate).
- **D4 — the declaration moves to the substrate; `REMOTE_PI_VERSION` stays as its remote name**
  (an import-bound alias; `perk/substrate` cannot import `perk/run`).
- **D5 — `--save-exact` on the consumer worker-deps install** (P4's `package.json` shows the
  effect).
- **D6 — the family is a closed, offline-pinned tuple** (the lockfile test above; the registry
  preflight checks the same closure on the registry).
- **D7 — owner regeneration, never a hand edit** (the owner run above).
- **D8 — evidence measured in throwaway prefixes, with a control, on the operator's toolchain and
  once under the remote Node line via a one-off `mise exec`** (operator decision after review; the
  operator's Node was never changed — no `mise use`, no config edit, no `PATH` change outside the
  single invocations).
- **D9 — scope boundaries** (non-family transitives float; no doctor companion-graph probe; no
  host-floor value moves; no slow JS tier).
- **D10 — comments express intent** (no plan breadcrumbs in the reworded comments).

## Deviations from the plan's procedure

- **The advisory's insertion point.** Step 3.4 placed `warnings.extend(<advisories>)` directly
  after the env gate; but the `skills_sync_failed` report preserves the accumulated `warnings`, so
  that insertion would have leaked the advisory into a failure report, contradicting D2's explicit
  list. The line is added at the success return instead (the checks are final after the guided
  pass, so the content is identical), and a second error-path row pins the `skills_sync_failed`
  case beside the plan's `skills_conflict` row.
- **The module-link checks gained resolve-path probes** (`import.meta.resolve` from inside each
  package directory), beyond the plan's `typeof`/`linked` prints, for the same walk-up reason P5
  checks `outside`.
- **`host_floor.py`'s docstring** was amended with `shared/host-floor.yaml`'s header (census
  classification above).
- **`@mgiles/perk@4.0.0` is published**, so P4 included it (the plan made it conditional).

## Residuals and follow-ups

- Deeper non-family transitives float within their declared ranges (an ordinary npm fact).
- A later bare `npm install -g @earendil-works/pi-coding-agent@<x>` re-floats the companions
  beside the stale pinned siblings (the user docs say to always use the pinned command); `npm
  uninstall -g` of the package leaves the seven siblings; `pi-ai`'s own `pi-ai` bin is linked
  globally beside `pi`.
- Doctor cannot see a 1.1.0 package over floated companions (it reads `pi --version` only) — a
  doctor probe of the PATH `pi`'s companion graph is a follow-up candidate, not a node.
- The extension refusal cannot print the command itself (it links where the command lives) — a
  shared cross-plane pin file is a follow-up candidate.
- A failed init carries no advisory (by design, D2).
- **Operator host recommendation:** run `PI_INSTALL_COMMAND` on the host after merge — it converts
  the node-6.1 nested repair into the sibling layout. Nothing in this node requires it.
- **Handoffs.** Node 7.1: the live remote legs now install a pinned set — record the resolved
  census there. Node 7.2: the reverify guide's pin-surface step (the adopted pin + the family tuple
  + the closure preflight under the composite's Node line + the owner regeneration + the refusal
  URL), the learned-doc corrections, the ledger narrative.
- **`/learn` candidates:** `docs/learned/workflow/remote-runner.md` ("deliberately unpinned" is
  stale; the pinned set and the sibling layout; measure npm placement under the composite's Node
  line with a one-off `mise exec`); `docs/learned/toolchain/worktree-node-modules.md` § "Five
  version facts" (the adopted pin's substrate home; the pinned install set);
  `docs/learned/workflow/init-doctor.md` (the `EnvCheck.advisory` tier beside the optional tier;
  success-report-only warnings, inserted at the success return because `skills_sync_failed`
  preserves accumulated warnings); `docs/learned/pi/extension-api.md` (an SDK-boundary refusal may
  point at neither a PATH-dependent surface nor an unshipped docs path);
  `docs/learned/pi/subagents.md` (`findPeerPackageDir` reaches global siblings and any ancestor dev
  graph; Pi 1.4.0 dropped `chord`); the implement-worktree `perk doctor --fix` skills-sync
  `conflict` (symlinked `.agents/skills` without local skills-CLI state).
