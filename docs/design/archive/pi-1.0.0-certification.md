# Certification: published Pi 1.0.0 as perk's host floor

**Status:** dated evidence record. Measured 2026-10-08 (03:12–06:16Z autonomous rows; owner legs
11:40–13:30Z; the PR-door rows after the PR exists); authored 2026-10-08. It certifies perk 3.9.0 at `c829e46260fbea45cdd067a6c13d2fc1137d7d5e`
(plus the A6a fix commit `e8903aba`, a one-key reorder of the committed `.pi/settings.json`) against
the operator's **published Pi 1.0.0** host and **pi-subagents 0.75.0**. It implements plan #2682
(Objective #2656, node 5.1). The precedents are
[`pi-1.0.0-characterization.md`](pi-1.0.0-characterization.md) (instruments, scrubbed environment,
watchdog), [`pi-subagents-0.75.0-reverify.md`](pi-subagents-0.75.0-reverify.md) (probe modes, trust
rows, the five browser-door criteria) and [`pi-1.0.0-mcp-restoration.md`](pi-1.0.0-mcp-restoration.md)
(the MCP matrix script).

**Verdict: PENDING the PR-door rows.** Of the 51 ledger rows, 46 are required and 5 are INFO
(I2b, A6b, S4c, X7b, X7c — all OBSERVED). 43 of the 46 required rows PASS (A6a after one
owner-approved fix, E1 with a falsified sub-clause). The other 3 — X5b, S7, and I7b's PR-door
launch proof — need this node's PR and are appended after it exists. No required row has failed,
and none is UNOBSERVED. The publication decision (CERTIFIED or HELD) follows those three rows.

Measured rows and source-derived statements are kept separate. A **LIVE** row quotes a command run
in this experiment against the PATH host or a real install. A **MEASURED (offline, real runtime,
1.0.0 SDK)** row quotes a passing test's verbatim TAP `ok` / pytest `PASSED` / spec `✔` line from
the recorded invocations (methodology appendix) — never as live behaviour. A **CARRIED** row
restates an earlier record that measured exactly Pi 1.0.0 + pi-subagents 0.75.0. A
**source-derived** statement cites `<path>@v1.0.0`, read with `git -C <mirror> show v1.0.0:<path>`
from the library mirror `docs/library/source-code/github.com/earendil-works/pi` (tag `v1.0.0` =
`a13d35a742c6ef8462812a28fbe1d8c8b7431c32`; the mirror's `HEAD` `b7dfc049` is past the tag and was
never read as evidence).

Verdicts: **PASS** · **FAIL** · **OBSERVED** (informational) · **UNOBSERVED — NOT PASSED**.
Classifications (fixed before measuring): **SUPPORTED** · **OPT-OUT** · **ADAPTATION** ·
**CONSTRAINED** · **DEFERRED**. Rows marked **INFO** are informational; every other row is required.

**Path abbreviations in quotes:** `$MAIN` = `/Users/mattgiles/dev/github/mattgiles/perk`.
`$WT` = `$MAIN/.worktrees/plan-2682` (this node's implement worktree). `$TMP` =
`/var/folders/90/…/T/perk-cert.sFyjMXQRbx` (outside every checkout). `$CLONE` = `$TMP/clone`,
`$PIHOME` = `$TMP/pi-global`, `$STUBS` = `$TMP/stubs`, `$WORKWT` = `$TMP/worker-wt`,
`$LOGS` = `$TMP/logs`, `$HERMETIC` / `$AUTHED` = `$TMP/agent-hermetic` / `$TMP/agent-authed`.
`$SCRATCH` = `$WT/.perk-certification`. `$MODEL` = `anthropic/claude-opus-5-5`. `~/.local/…/26.3.0`
= `/Users/mattgiles/.local/share/mise/installs/node/26.3.0`. Inside table cells, `\|` is the table
escape for `|`. Apart from these substitutions, quotes are verbatim.

## Snapshot matrix

| Component | Version / value | Provenance |
|---|---|---|
| perk | 3.9.0 @ `c829e462` (measurement HEAD of branch `plan-2682` = `main`); A6a's rerun at `e8903aba` | `git rev-parse HEAD`; `pyproject.toml` / `package.json` |
| Installed `perk` CLI (launched this implement session) | 3.9.0, an editable `uv tool` install of `$MAIN` (`requirements = [{ name = "perk", editable = "$MAIN" }]`), so its launch admission is the checkout's own code at the same commit | `~/.local/share/uv/tools/perk/uv-receipt.toml`; `perk --version` |
| `pi` on PATH | **1.0.0**, `~/.local/…/26.3.0/bin/pi` → `~/.local/…/26.3.0/lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js` | `which pi`, `readlink -f`, `pi --version`, the package's `package.json` `version` |
| `node` | v26.3.0 (PATH); v22.19.0 via `mise exec node@22.19.0` for A5 | `node --version` |
| Dev pins (`$WT`, after the setup hook's `npm ci`) | `@earendil-works/{pi-coding-agent,pi-ai,pi-tui,pi-agent-core}` exact **1.0.0** on disk, in `package.json` and in the lockfile; `typebox` 1.3.27; `pi-telemetry` floats at 1.0.4 | each `node_modules/*/package.json`; `npm ls` |
| pi-subagents / pi-web-access / Plannotator | 0.75.0 / 0.33.0 / 0.27.21 in both `$WT/.pi/npm` and `$MAIN/.pi/npm` (`$WT`'s copy is the hardlink-shared materialization: `package.json` inode 147622898, link count 25, in both) | on-disk `package.json`; `ls -li` |
| `$CLONE/.pi/npm` | an independent copy (`package.json` inode 466757775, link count 1) | `cp -R "$MAIN/.pi/npm" "$CLONE/.pi/npm"`; `ls -li` |
| `SUBAGENTS_PACKAGE` | `npm:pi-subagents@0.75.0` | `src/perk/convergence/init/settings.py:99` |
| Host floor | `pi.min_version: "1.0.0"`, `node.min_version: "22.19.0"` | `shared/host-floor.yaml` |
| `REMOTE_PI_VERSION` | `1.0.0` (`_PI_GLOBAL_INSTALL = f"npm install -g {PI_NPM_SPEC}@{REMOTE_PI_VERSION}"`, `_WORKER_DEPS_SELF = "npm ci"`) | `src/perk/run/workflow_artifacts.py:177–193` |
| npm registry (Step 0, 03:12Z) | pi-coding-agent versions end `1.0.1, 1.0.2, 1.0.3, 1.0.4, 1.1.0`; dist-tags `latest: 1.1.0`, `legacy-node20: 0.74.2`. 1.0.4 (the latest 1.0.x) is used only in A4; 1.1.0 appears only in A6b | `npm view @earendil-works/pi-coding-agent versions --json \| tail -5`; `… dist-tags --json` |
| Mirror tag | `v1.0.0` = `a13d35a742c6ef8462812a28fbe1d8c8b7431c32` | `git -C <mirror> rev-parse v1.0.0` |
| `$MODEL` | `anthropic/claude-opus-5-5` | `$PI_PROVIDER/$PI_MODEL` of the implement session |
| Planning session (S3, X5a, E1) | run `01M4CD2S1JP09PE4PXB472RG4X`, Pi session `01a118d1-6c82-744f-ab6a-2cd3f3080205`, JSONL `$MAIN/.pi/agent/sessions/--Users-mattgiles-dev-github-mattgiles-perk--/2026-10-08T00-02-20-418Z_01a118d1-6c82-744f-ab6a-2cd3f3080205.jsonl` (264 lines, header `version: 3`, sha1 `8aa3c658754d49ae80d541d1d684ed5e77718271`) | `wc -l`, `shasum`, `head -1` |
| Implement session (X legs) | run `01M4CQM5Z7PVWA75AGA4R3V6JR`, Pi session `01a1197c-a605-711b-83b9-9ed4d0e50067` | `$PERK_RUN_ID`, `$PI_SESSION_ID` |
| MAIN staging hashes (Step 0; re-checked at teardown) | `package.json` `4ddfc113…a93dfeb`; `package-lock.json` `f6051165…a9e5f16`; `node_modules/.package-lock.json` `44454e0d…a4064a`; `node_modules/pi-subagents/package.json` `919f8468…3ac3f3d` | `shasum -a 256` |
| MAIN porcelain | empty at Step 0 | `git -C $MAIN status --porcelain` |

## Offline tier (Step 2)

| Invocation | Verbatim summary |
|---|---|
| `run_ci check="lint-py,lint-js,typecheck-py,typecheck-js,typecheck-prose-review,test-py-fast,test-py-slow,test-js"` | `perk CI: selected checks passed.` — `✓ lint-py (6s)`, `✓ lint-js (10s)`, `✓ typecheck-py (7s)`, `✓ typecheck-js (70s)`, `✓ typecheck-prose-review (19s)`, `✓ test-py-fast (251s)`, `✓ test-py-slow (241s)`, `✓ test-js (115s)`; every named row executed (each carries a duration), none skipped |
| `just test-js-slow … --test-reporter-destination="$LOGS/slow.tap"` (03:19:37–03:23:05Z) | `# tests 1000` / `# pass 1000` / `# fail 0` / `# cancelled 0` / `# skipped 0`; exit 0 |
| `just test-js-fast … --test-reporter-destination="$LOGS/fast.tap"` (03:23:11–03:23:55Z) | `# tests 2796` / `# pass 2796` / `# fail 0` / `# cancelled 0` / `# skipped 0`; exit 0 |
| `uv run pytest -rfEs` (03:24:02–03:26:41Z) | `SKIPPED [1] tests/test_native_sdk_bridge_live.py:152: needs a below-floor PATH pi (this one is admitted)` / `================= 8363 passed, 1 skipped in 154.10s (0:02:34) ==================` |

The one skip is the below-floor test, which A3e runs on a real 0.99.2.

## I — Actual installations

| Row | Procedure | Verbatim observation | Verdict | Class |
|---|---|---|---|---|
| I1 CLI | `which pi; readlink -f "$(which pi)"; pi --version`; the package's `package.json` | `~/.local/…/26.3.0/bin/pi` → `~/.local/…/26.3.0/lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js`; `pi --version` → `1.0.0`; `package.json` `version` → `1.0.0` (LIVE) | PASS | SUPPORTED |
| I2a SDK + lockfile | on-disk versions, `package.json` devDeps, lockfile, `npm ls …` in `$WT`; recorded pytest | `node_modules/@earendil-works/pi-coding-agent 1.0.0` (same for `pi-ai`, `pi-tui`, `pi-agent-core`); devDependencies `"@earendil-works/pi-agent-core": "1.0.0"`, `"pi-ai": "1.0.0"`, `"pi-coding-agent": "1.0.0"`, `"pi-tui": "1.0.0"`, `"typebox": "1.3.27"`; lockfile root devDependencies and the four top-level entries `1.0.0`, `node_modules/typebox 1.3.27`; `npm ls` resolves every copy at `@1.0.0` with `typebox@1.3.27 deduped`, `npm ls exit=0`; `tests/test_packaging.py::test_pi_toolchain_pin_lockstep PASSED` (`1 passed in 0.31s`) | PASS | SUPPORTED |
| I2b floating transitive (INFO) | `node_modules/@earendil-works/pi-telemetry/package.json` | `1.0.4` | OBSERVED | SUPPORTED |
| I3 suppliers | `.pi/npm/node_modules/{pi-subagents,pi-web-access,@plannotator/pi-extension}` in `$WT` and `$MAIN`; recorded pytest | both checkouts: `pi-subagents 0.75.0`, `pi-web-access 0.33.0`, `@plannotator/pi-extension 0.27.21`; `SUBAGENTS_PACKAGE = "npm:pi-subagents@0.75.0"`; `tests/test_native_sdk_bridge_live.py::test_the_installed_pi_subagents_is_the_managed_pin PASSED` (`1 passed in 0.09s`) | PASS | SUPPORTED |
| I4 bare-clone loading | from `$CLONE` (`ls -d node_modules .venv` → both `No such file or directory`; no ancestor `node_modules`): `$SCRUB <hermetic> ~/.local/…/26.3.0/bin/pi --approve --mode json -p /perk-selfcheck` under the watchdog; `node --test --test-reporter=spec extension/bareImportGuard.test.ts` in `$WT` | `perk: selfcheck — 3.9.0: ok; shared=ok; ambient=reached (append=5359c); agents=reached (files=1); bridge=installed`; `host sdk: 1.0.0 (floor >= 1.0.0)`; `native sdk bridge: installed (roots=2, specifiers=8)` with roots `$CLONE/.pi/npm/node_modules/pi-subagents`, `…/pi-web-access`; 0 `Failed to load extension`; `exit=0 elapsed=10s` (LIVE). Guard: `✔ production extension sources import only node:/relative/host specifiers (zero bare npm deps)`, `ℹ tests 2` / `ℹ pass 2` / `ℹ fail 0` | PASS | SUPPORTED |
| I5 host identity + bridge | X7a's selfcheck; `node --test --test-reporter=spec extension/substrate/nativeSdkBridge.test.ts` and `extension/piAiCompatGuard.test.ts` in `$WT` | `native sdk bridge: installed (roots=2, specifiers=8)` / `host: ~/.local/…/26.3.0/lib/node_modules/@earendil-works/pi-coding-agent/dist/index.js` / `roots: 2 — $WT/.pi/npm/node_modules/pi-subagents, $WT/.pi/npm/node_modules/pi-web-access` (LIVE); `✔ census drift guard: the installed consumers import exactly NATIVE_SDK_CENSUS (408.51925ms)`, `ℹ tests 32` / `ℹ pass 32` / `ℹ fail 0` / `ℹ skipped 0`; `✔ the SDK-resolved pi-ai exports ./compat (unpinned pi-web-access imports it)`, 1/1 | PASS | ADAPTATION (K1) |
| I6 lazy imports / reload | `node --test --test-reporter=spec extension/entryAdmission.test.ts`; owner `/reload` → `/perk-selfcheck` | `ℹ tests 10` / `ℹ pass 10` / `ℹ fail 0`, incl. `✔ extension: the entry links nothing SDK-bearing before admission and refuses an old SDK`, `✔ control: the composition root IS link-fatal under that SDK`, `✔ worker: a below-floor SDK missing the adapter's exports is refused typed (exit 1), despite a passing PATH pi`, `✔ worker: usage errors still precede the admission (exit 2, no outcome)`. Owner leg (X3's `/reload`, selfcheck at 11:46:12Z): `perk: selfcheck — 3.9.0: ok; shared=ok; ambient=reached (append=5359c); agents=reached (files=1); bridge=installed` / `host sdk: 1.0.0 (floor >= 1.0.0)` / `native sdk bridge: installed (roots=2, specifiers=8, reused)` (LIVE) | PASS | SUPPORTED |
| I7a in-process blocking child | `run_librarian {action: "refresh-docs", slug: "divio-documentation"}` in the implement session (03:35:10Z) | `Published documentation entry \`divio-documentation\` → $MAIN/docs/library/documentation/divio-documentation (status unknown; pages published 8, failures accepted 0, scope default).`; details `kind: "published"`, receipt `agent: "perk.librarian"`, `nativeStatus: "completed"`, `exitCode: 0`, `termination: "confirmed"`, `bracket: {"ok": true}`; the child's session JSONL (56 lines) has 0 `Failed to load extension`; `$MAIN` porcelain empty before and after (LIVE) | PASS | ADAPTATION (K1 identity proof) |
| I7b wave launch | the planning session's `run_scout_wave` (S3) and draft-review wave (X5a); the PR-door wave (X5b) | S3: 6/6 `perk.scout` children `success: true`, attempt `state: "complete"`; X5a: `launch.requested` = `launch.runnable` = `["grounding", "decision-completeness", "risk", "ponytail"]`, `preflightFailures: []`. X5b: ⟨PENDING — after the PR⟩ | ⟨PENDING⟩ | ADAPTATION (K1 launch proof) |

I7a note: the catalog entry read `status: "fresh"` before the refresh and `status: "unknown"`
(`checked_at: null`, `evidence: "none"`) after it — a publish resets the freshness evidence until
the next `perk librarian check`. Not a criterion.

## A — Admission and setup

| Row | Procedure | Verbatim observation | Verdict | Class |
|---|---|---|---|---|
| A1 launch refusals (live stubs) | stubs `old`/`rc`/`junk`/`empty`/`slow` at `$STUBS/<case>/pi`, each verified first (`PATH="$STUBS/<case>:$PATH" command -v pi` → the stub); `cd $WT && PATH="$STUBS/<case>:$PATH" script -q /dev/null uv run perk` (a pty: see deviations); `old` also through `perk resume 01M4CD2S1JP09PE4PXB472RG4X` and two dry-run arms; `none`: `PATH="$STUBS/none-bin" command -v pi` → `exit=1` first, then `PATH="$STUBS/none-bin" /usr/bin/script -q /dev/null "$(command -v uv)" run perk`; the typed code read through the launch path's own functions (`pi_exec._resolve_pi_executable` → `pi_exec._admit_pi_host`) under each PATH | `old`: `Error: pi at $STUBS/old/pi is version 0.99.2; perk requires Pi >= 1.0.0. Upgrade it: npm install -g @earendil-works/pi-coding-agent — perk init and perk doctor report the same requirement.` `exit=1`; `rc`: same text with `version 1.0.0-rc.1`, `exit=1`; `junk`: `Error: could not verify the Pi version of $STUBS/junk/pi (pi --version printed 'banana' instead of a version); perk requires Pi >= 1.0.0. Reinstall it: npm install -g @earendil-works/pi-coding-agent.` `exit=1`; `empty`: `… (pi --version printed '' instead of a version) …` `exit=1`; `slow`: `… (pi --version timed out after 20 s) …` `exit=1 elapsed=20s`; `none`: `Error: pi CLI not found on PATH — install it: npm install -g @earendil-works/pi-coding-agent (perk requires Pi >= 1.0.0 and Node >= 22.19.0).` `exit=1`, no session. Resumed path (`old`): `reopening run 01M4CD2S1JP09PE4PXB472RG4X's recorded conversation … pi --session …` then the same `version 0.99.2` refusal, `exit=1`. Dry-run (`old`): `perk resume 01M4CD2S1JP09PE4PXB472RG4X --dry-run` → `resume --dry-run (recorded session — resolve only, no launch)` … `"dry_run": true}` `exit=0`; `perk plan --dry-run` → `would launch stage 'plan' in $MAIN` … `exit=0` (no probe: a probe would have refused). Typed codes: `old: error_type=pi_version_unsupported`, `rc: error_type=pi_version_unsupported`, `junk`/`empty`/`slow`: `error_type=pi_version_unverifiable`, `none: error_type=pi_cli_missing`, real host: `admitted ~/.local/…/26.3.0/bin/pi`. Admitted arm: `script -q … uv run perk` on the real host → `opening a plain Pi session in $WT: pi`, the TUI footer `perk v3.9.0 … plan-2682`, `/quit` → `exit=0 elapsed=21s`, 0 `Failed to load extension`; and this implement session's own cold launch (the editable 3.9.0 install = the same code) | PASS | SUPPORTED |
| A2 init/doctor rows | `PATH="$STUBS/old:$PATH" uv run perk doctor --verbose` and `--json`; same with `junk`; `uv run perk doctor --verbose` on the real host | `old`: `✗ pi: pi missing/outdated — 0.99.2 (floor >= 1.0.0)`, Remediation `Upgrade Pi to >= 1.0.0 (found 0.99.2): npm install -g @earendil-works/pi-coding-agent.`, `exit=1`; JSON `{"name": "pi", "group": "environment", "status": "fail", "message": "pi missing/outdated", "detail": "0.99.2 (floor >= 1.0.0)", "remediation": "Upgrade Pi to >= 1.0.0 (found 0.99.2): npm install -g @earendil-works/pi-coding-agent."}`, `exit=1`. `junk`: `✗ pi: pi missing/outdated — version unverifiable (pi --version printed 'banana' instead of a version)`, remediation `Reinstall Pi (>= 1.0.0 required): npm install -g @earendil-works/pi-coding-agent.` Real: `✓ node: node ok — v26.3.0`, `✓ pi: pi ok — 1.0.0 (floor >= 1.0.0)`. The node check compares the full floor (`src/perk/convergence/env.py::_check_node`: "The full Node floor (not just the major)") | PASS | SUPPORTED |
| A3e extension refusal, REAL below-floor Pi | `npm install -g --prefix "$PIHOME/0.99.2" @earendil-works/pi-coding-agent@0.99.2` (`added 147 packages in 8s`; `$PIHOME/0.99.2/bin/pi --version` → `0.99.2`); `PATH="$PIHOME/0.99.2/bin:$PATH" uv run pytest -v -n0 tests/test_native_sdk_bridge_live.py::test_a_below_floor_real_pi_refuses_to_load_perk`; raw `$SCRUB <hermetic> $PIHOME/0.99.2/bin/pi --approve --mode json -p /perk-selfcheck` from `$WT` | `tests/test_native_sdk_bridge_live.py::test_a_below_floor_real_pi_refuses_to_load_perk PASSED` (`1 passed in 13.73s`); raw: `Error: Failed to load extension "$WT/extension/index.ts": Failed to load extension: perk requires Pi >= 1.0.0; the Pi running this session is 0.99.2 (@earendil-works/pi-coding-agent VERSION). Upgrade it: npm install -g @earendil-works/pi-coding-agent — perk init and perk doctor report the same requirement.` / `Hint: Start without extensions using "pi -ne".` / `exit=1 elapsed=16s`; 0 `perk: selfcheck` lines. The PATH `pi` stayed 1.0.0 (re-checked after the install) | PASS | SUPPORTED |
| A3w worker refusal, REAL old SDK | in `$CLONE`: `npm install --no-save @earendil-works/pi-coding-agent@0.87.0` (`VERSION 0.87.0 createToolSearchExtension undefined createCodemodeExtension undefined`); `env $SCRUB PERK_RUN_ID=cert PI_CODING_AGENT_DIR=$HERMETIC node extension/workerMain.ts implement --worktree "$WORKWT" --model perk-probe/none`; then `rm -rf node_modules` and the same with `@0.99.2` | 0.87.0: `exit=1`; stdout `{"run_id":"cert","stage":"implement","status":"failed","terminal_signal":"model_error",…,"error":{"type":"pi_version_unsupported","message":"perk worker: the loaded Pi SDK (@earendil-works/pi-coding-agent) is version 0.87.0; perk requires Pi >= 1.0.0. Reinstall the worker's SDK at a supported version: npm ci in this checkout (self-repo), or re-run the remote setup's worker-deps install (consumer).",…}}`; `events.ndjson` exactly `{"kind":"run_started",…,"seq":0,…}` and `{"kind":"run_finished",…,"seq":1,…}`. 0.99.2: the same shape with `version 0.99.2`, `exit=1`, the same two events. No `SyntaxError`, no exit 2 | PASS | SUPPORTED |
| A4 floor-satisfying skew admitted | in `$CLONE`: `rm -rf node_modules; npm install --no-save @earendil-works/pi-coding-agent@1.0.4` (the latest 1.0.x); the A3w command; PATH CLI 1.0.0; offline pins | on-disk `pi-coding-agent 1.0.4` (PATH `pi: 1.0.0`); `exit=1`, stdout `"error":{"type":"model_not_found","message":"model 'perk-probe/none' not found in the registry (resolved after extension registration): Model \"perk-probe/none\" not found. Use --list-models to see available models.",…}` — admission passed, the drive reached selection after extension registration. MEASURED: `ok 1849 - admitHostSdk: 1.0.1 is admitted as 1.0.1`, `ok 614 - host admission: a floor-satisfying, unequal host SDK activates independently of the CLI stamp` (fast.tap), `tests/test_pi_host.py::test_the_dev_pin_satisfies_the_floor_and_the_cli_is_admitted_independently PASSED`. 1.0.4 is not certified — the row proves independence only | PASS | SUPPORTED |
| A5 Node + remote setup agree (local replay) | `npm install -g --prefix "$PIHOME/remote" @earendil-works/pi-coding-agent@1.0.0` (= `_PI_GLOBAL_INSTALL`); in `$CLONE` after `rm -rf node_modules`: `mise exec node@22.19.0 -- npm ci` (= `_WORKER_DEPS_SELF`), then `mise exec node@22.19.0 -- node --test --test-reporter=spec extension/worker/stageExecutionE2e.test.ts --test-name-pattern "real worker entry"`; static pytest; `grep -n node-version …`; `engines.node` | `$PIHOME/remote/bin/pi --version` → `1.0.0`; `v22.19.0` / npm `10.9.3`; `npm ci` → `added 628 packages in 12s`, the four SDK packages `1.0.0`; e2e under v22.19.0: `✔ e2e: the real worker entry admits the installed SDK and drives to completion, independent of PATH and the CLI stamp (6338.727167ms)`, the whole file `ℹ tests 34` / `ℹ pass 34` / `ℹ fail 0` (the name pattern was not applied, see deviations); `test_composite_action_pins_pi_and_node_for_both_repo_kinds PASSED`, `test_composite_action_node_version_renders_from_the_shared_floor PASSED`, `test_remote_pi_version_is_a_release_at_or_above_the_floor PASSED` (`9 passed, 11 deselected`); `.github/workflows/ci.yml:31`, `release.yml:151`, `release.yml:183`, `.github/actions/perk-remote-setup/action.yml:20` all `node-version: "22.19.0"`; `action.yml:28: run: npm install -g @earendil-works/pi-coding-agent@1.0.0`, `action.yml:48: run: npm ci`; `engines.node` `>=22.19.0` | PASS | SUPPORTED |
| A6a recovery: `doctor --fix` | delete the `defaultTools` key from `$WT/.pi/settings.json`; `uv run perk doctor --verbose`; `uv run perk doctor --fix`; `git diff --exit-code -- .pi/settings.json` | **First run (at `c829e462`) — FAIL:** `✗ settings-wiring: settings-wiring drift — .pi/settings.json: compaction: reserveTokens=65536; defaultTools: +tool_search`; Fixed `- .pi/settings.json: compaction: reserveTokens=65536; defaultTools: +tool_search`; then `git diff --exit-code` printed the key re-added at the END of the object (`-  "defaultTools": [ …` above `"subagents"`, `+  "defaultTools": [ …` after `"compaction"`) and `exit=1`; `perk doctor --verbose` then read `✓ settings-wiring: settings-wiring converged`. **Diagnosis:** the value is restored exactly; `_converge_discovery` appends the key, and the committed file held it mid-object. **Fix (owner-approved, fix-or-hold):** `e8903aba` seats `defaultTools` at the end of the committed file (same value; the blob equals the repaired one, `6a94a314`); doctor `✓ settings-wiring: settings-wiring converged`, `✓ artifact-health: 7 managed artifacts up-to-date`. **Rerun — PASS:** the same drift line, the same Fixed line, `$ git diff --exit-code -- .pi/settings.json` → `exit=0` | PASS (after one fix) | SUPPORTED |
| A6b the literal upgrade command (INFO) | `npm install -g --prefix "$PIHOME/literal" @earendil-works/pi-coding-agent` (the refusal's unpinned text) | `added 121 packages in 8s`; `$PIHOME/literal/bin/pi --version → 1.1.0`; `probe_pi_host` → `PiHost(…, outcome='admitted', observed='1.1.0', required='1.0.0', detail='')`. A5's pinned install is the certified variant | OBSERVED | SUPPORTED |
| A7 init idempotent + preference-preserving | `uv run perk init` on converged `$WT` (twice: the first only created the gitignored `.perk/local.toml`); set `"tuiMode": "regular"` and `defaultTools: ["-tool_search"]`; `uv run perk init`; read back; `uv run perk doctor`; `git checkout -- .pi/settings.json`; recorded pytest | second init: no `Completed before failure` list (zero changes); after the operator edits: zero changes, `tuiMode = 'regular' \| defaultTools = ['-tool_search']`, `settings byte-identical to the operator edit after init`; doctor `✓ settings-wiring: settings-wiring converged`, `exit=0`; `git show HEAD:.pi/settings.json \| grep -c tuiMode` → `0`, `git grep -n tuiMode -- src/perk extension ':!*.test.ts'` → no match; `test_init_converges_and_is_idempotent PASSED`, `test_init_preserves_existing_tui_mode[regular]`/`[fullscreen]` PASSED, `test_explicit_tui_mode_survives_a_settings_repair[regular]`/`[fullscreen]` PASSED, `test_discovery_opt_out_and_empty_selection_are_not_drift[opt-out]`/`[empty]`/`[no-string-entries]` PASSED (`8 passed in 4.11s`). Every `perk init` here exited 2 on the skills-CLI sync — see the note below | PASS | OPT-OUT |

**A7 / A6a note — the worktree skills sync (pre-existing, not Pi).** Every `perk init` and
`perk doctor --fix` in `$WT` ended with `✗ skills delivery failed: \`skills update --sync\` exited
1: ERROR: agent-browser/agent-browser: conflict; astral/ruff: conflict; …` (init `exit=2`; doctor
lists it under `Fix failures` and still reports `✓ healthy (43 ok)`). `$WT/.agents/skills/*` are
links into `$MAIN/.agents/cache/…` while the worktree-local skills state is missing, so the
`skills` CLI reports unmanaged destination conflicts. `run_init` converges every managed piece
before the sync (`src/perk/convergence/init/__init__.py::run_init`), so the convergence result is
observable. `docs/learned/workflow/init-external-cli.md` records the same worktree `conflict`
failure and its owner-controlled repair; no repair was applied here.

## S — Supplier children (pi-subagents 0.75.0 on the 1.0.0 host)

| Row | Procedure | Verbatim observation | Verdict | Class |
|---|---|---|---|---|
| S1 bridge-live suite | `uv run pytest -v -n0 -rfEs tests/test_native_sdk_bridge_live.py` on the PATH host | `test_the_installed_pi_subagents_is_the_managed_pin PASSED`, `test_real_pi_selfcheck_reports_the_bridge_installed_and_both_consumers_loaded PASSED`, `test_a_below_floor_real_pi_refuses_to_load_perk SKIPPED` — `SKIPPED [1] tests/test_native_sdk_bridge_live.py:152: needs a below-floor PATH pi (this one is admitted)`; `2 passed, 1 skipped in 9.63s` | PASS | ADAPTATION (K1) |
| S2 offline wave suites | fast.tap lines; `node --test --test-reporter=spec extension/waves/rpcAdapter.test.ts` and `…/draftReviewWave.test.ts` for attribution | MEASURED: `ok 2653 - runScoutWave: one failed lane ⇒ incomplete under strict, siblings retained, ONE spawn (no retry)`; `ok 2583 - settlement grace: a native partial completion arriving after the engine deadline but inside the grace is retained`; `ok 2561 - wave.run: an AbortSignal cancels the wave and stops the run best-effort`; `ok 2596 - collect: running retains the ref; the later collect drains once; a second collect is none`; `ok 2604 - rpc round-trip: every child carries the constant packet and caller-checkout placement`; `ok 2616 - rpc integration: a native partial delivered inside the settlement grace is retained through the real adapter`; draftReviewWave spec `✔ the agent def completes via structured_output with the schema's required fields — no fenced-JSON completion` (15/15); rpcAdapter spec `✔ the pinned context-less code is pi-subagents' no_active_session` (= `ok 2639`), `ℹ tests 20` / `ℹ pass 20` / `ℹ fail 0` | PASS | SUPPORTED |
| S3 live scout wave | the planning JSONL's `run_scout_wave` call (line 52, 00:06:08Z) and result (line 54, 00:11:36Z); the workflow receipt of run `3d78df70-…`; `perk learn evidence --render --json` (E1) copied the JSONL byte-identically | result details `ok: true`, 6 `reports`; attempt `{"runId": "3d78df70-fc0a-4620-903b-b9a26a0cb246", "state": "complete", "flow": "scout"}` with six children `worker-e2e-census`, `supplier-children`, `admission-setup`, `evidence-restoration`, `release-convergence`, `sessions-surfaces`, each `agent: "perk.scout"`, `success: true`; `workflow-receipt.json` `state complete`, every child `completed perk.scout openai/gpt-6-sol`; `status.json` `state complete mode workflow` (LIVE, the planning session) | PASS | SUPPORTED |
| S4a mixed siblings + packet + structured completion | the 0.75.0 probe with an added `mixed` mode (appendix); `$SCRUB <authed> ~/.local/…/26.3.0/bin/pi --approve --mode json -e .perk-certification/probe-spawn.ts -p "/probe-spawn script $MODEL mixed"` from `$WT` under the watchdog (03:49:47–03:50:39Z) | spawn `success: true` (asyncId `9b30fbd7-…`); `status.json` `"state": "complete"`; `workflow.value` `[{"key": "probe-ok", "ok": true, "error": null, "report": null}, {"key": "probe-bad", "ok": false, "error": "Unknown subagent model 'perk-probe/does-not-exist' in the active Pi model registry.", "report": null}]`; `probe-ok` child `ab747216-…` (`status.json` `state complete`, runner `pid` 26752): `output-0.log` (1628 bytes) carries `[READ-ONLY MODE] (unscoped)` and ends `OK`; recovery descriptor `.extensionBindings {"perk.parent-restrictions/1": {"readOnly": true}}`, `.model "anthropic/claude-opus-5-5"`; `probe-bad` (`durationMs: 42`): no child directory (`ls …/5d661eb9-…` → `No such file or directory`); 0 `Failed to load extension`; `exit=0 elapsed=52s` (LIVE; T1 `--approve` re-measured) | PASS | SUPPORTED |
| S4b cancellation | an added `cancel` mode: one lane with "Read AGENTS.md and summarize it in 600 words.", wait for the runner pid, RPC `stop {id: <asyncId>}` (as `extension/waves/rpcAdapter.ts::stop`), settle | `probe: runner {"key": "probe-cancel", "runId": "e7959a75-…", "pid": 27662, "state": "running", …}`; `probe: stop {… "method": "stop", "success": true, "data": {… "previousState": "running", "state": "stopping", "message": "Stop requested for async run 5e6eca61-….")}}`; settled `"state": "stopped"`, step `"status": "stopped"`, `"error": "Workflow stopped by RPC."`; child `status.json` `state stopped pid 27662 error Subagent stopped by user.`; the runner pid gone afterwards; `exit=0 elapsed=6s` (LIVE) | PASS | SUPPORTED |
| S4c deadline partial (INFO) | an added `deadline` mode: quick + long lanes, spawn `timeoutMs: 20000` | `"state": "failed"`, `"failureKind": "timeout"`, `"error": "Workflow script timed out after 20000ms."`; `probe-quick` `completed` (`durationMs: 5401`, output `OK`); `probe-long` `running` in the snapshot, its child later `state failed … error Subagent timed out after 19820ms.`; the receipt's `"terminalOutcome": {"state": "partial", "reason": "timeout"}` with `entries.probe-quick` (`resumability: resumable`) retained; after the parent settled, pi-subagents printed `Failed to send incremental child completion notification for 'probe-long': Error: This extension ctx is stale …` (the late child event); `exit=0 elapsed=22s` | OBSERVED | DEFERRED (live) |
| S5 trust rows | T1 re-measured by S4a; T2/T3/T4 CARRIED (`pi-subagents-0.75.0-reverify.md` T2/T3/T4: a 1.0.0 throwaway + 0.75.0) | T1 (S4a): `--approve` → the packet + notice in the child. CARRIED T2: "remembered trust: no flag; `$AUTHED/trust.json` = `{"$TW": true}` … child `a00c5789…` (pid 47941), lane `ok: true`, bindings + notice as T1; exit 0 after 8 s". CARRIED T3: "`defaultProjectTrust: \"always\"` … child `afc44f1f…` (pid 48260), lane `ok: true`, bindings + notice as T1; no `trust.json` written; exit 0 after 8 s". CARRIED T4: "`probe: ping {\"error\": {\"code\": \"probe-timeout\", \"message\": \"ping\"}}` and the same for `spawn` — pi-subagents, a project package, did not load; no run directory" | PASS | SUPPORTED |
| S6 task restoration | fast.tap (see falsified assumptions: the tier is fast, not slow) | MEASURED: `ok 847 - a non-draft brief restores byte-exactly under the same role-neutral preamble`; `ok 842 - session_compact restores once per compaction; the gate then allows` (`extension/pi/v1/childTaskRestore.test.ts`); `ok 1784 - queue text is the preamble, a blank line, and the prompt byte-for-byte` (`extension/substrate/childTaskRestore.test.ts`) | PASS | SUPPORTED |
| S7 repeated collection (live) | at the PR door (X5b): a second `collect_review_wave` after the first drains | ⟨PENDING — after the PR⟩ | ⟨PENDING⟩ | SUPPORTED |

## E — Evidence and restoration

| Row | Procedure | Verbatim observation | Verdict | Class |
|---|---|---|---|---|
| E1 `/learn` evidence on 1.0.0 system entries | `uv run perk learn evidence --render --json` from `$WT` (03:55:53Z); grep the chunks; recorded pytest | `success: true`; `render.sessions[0]`: `"role": "planning-session/main"`, `"entries_read": 263`, `"entries_kept": 212`, `"entries_pruned": 51`, `"malformed_lines": 0`, chunks `planning-main.md`, `planning-main-2.md`; the copied JSONL is byte-identical to the planning JSONL (`cmp`). The chunks end at the session's leaf (`<tool_result tool="plan_review" error="false" id="acbe1420">plan APPROVED by reviewer.` — file line 264), and the branch walk crosses the system entry at line 203 (the entries after it, lines 204–264, render). `grep -c '<message role="system"'` → `0` in both chunks: the planning JSONL's two system entries (lines 9, 203) carry `content: ""` with the substance in `sections` (`['preamble', 'tools', 'rules', 'docs', 'addendum', 'project_context', 'skills', 'cwd']`; `['tools', 'rules']`), and contracts §8.35 prunes an empty snapshot/delta as non-substantive (`src/perk/learn/normalize.py` module docstring); all 64 system entries in the host's 60 most recent session files are empty-content the same way. MEASURED: `test_parse_system_snapshot_projects_ancestry_and_empty_text`, `test_parse_file_resume_tree_compaction_with_system_entries`, `test_branch_walk_survives_a_system_entry_between_branch_nodes`, `test_system_text_is_bounded_and_rendered_as_system_never_user`, `test_empty_system_deltas_are_never_dedup_candidates` all PASSED (`5 passed in 0.14s`) | PASS (owner-confirmed; the "rendered with bounded text" clause falsified) | SUPPORTED |
| E2 nested evidence intact | recorded pytest | `test_render_nested_calls_inside_the_parent_tool_result PASSED`, `test_render_parent_error_is_the_outer_flag_never_a_childs PASSED`, `test_render_evidence_system_snapshot_and_incomplete_nested_calls PASSED`, `tests/test_learn_session_jsonl.py::test_parse_file_nested_calls_never_make_the_line_malformed PASSED` (`4 passed in 0.10s`) | PASS | SUPPORTED |
| E3 delayed MCP registration vs control | the script copied byte-for-byte from `pi-1.0.0-mcp-restoration.md` **## The script (verbatim)** to `$SCRATCH/mcp-restoration.test.ts` (sha256 `5986f3d23e39c3435d0b8dbd147fd2afdc87324d29702139a33fdbb65cc22fcb`); `node --test .perk-certification/mcp-restoration.test.ts` from `$WT` (03:54:34Z) | `VERSION=1.0.0 node=v26.3.0`; `ℹ tests 12` / `ℹ pass 12` / `ℹ fail 0`; the 26 `RESULT` lines are identical, in order, to the record's 1.0.0 post-fix block (`diff` empty) — `RESULT W1-L1 PERK KEPT declared=yes` / `RESULT W1-L1 CONTROL KEPT declared=yes` / `RESULT W1-L2 PERK KEPT declared=yes` / `RESULT W1-L2 CONTROL KEPT declared=yes` / `RESULT W1-L2b PERK KEPT declared=yes` / `RESULT W1-L2b CONTROL KEPT declared=yes` / `RESULT W1-L3 PERK KEPT declared=yes` / `RESULT W1-L3 CONTROL KEPT declared=yes` / `RESULT W1-L4 PERK KEPT declared=no` / `RESULT W1-L4 CONTROL KEPT declared=yes` / `RESULT W1-L5 PERK KEPT declared=no` / `RESULT W1-L5 CONTROL KEPT declared=yes` / `RESULT W1-L6 PERK KEPT declared=yes` / `RESULT W1-L6 CONTROL KEPT declared=yes` / `RESULT W1-G1 PERK KEPT declared=no` / `RESULT W1-G1 CONTROL KEPT declared=yes` / `RESULT W1-G1-CD CONTROL LOST declared=no` / `RESULT W1-G1-CA CONTROL KEPT declared=yes` / `RESULT S1 PERK LOST declared=n/a` / `RESULT S1-C CONTROL LOST declared=n/a` / `RESULT W2-T1 PERK KEPT declared=n/a` / `RESULT W2-T1-C CONTROL KEPT declared=n/a` / `RESULT W2-T2 PERK KEPT declared=n/a` / `RESULT W2-T2-C CONTROL KEPT declared=n/a` / `RESULT W2-T2-CD CONTROL LOST declared=n/a` / `RESULT W2-T2-CA CONTROL KEPT declared=n/a`. Classification: W1-L1, W1-L2, W1-L2b, W1-L3, W1-L4, W1-L5, W1-L6, W1-G1, W2-T1, W2-T2 → `PARITY` (C KEPT, P KEPT; `declared=no` on L4/L5/G1 PERK is the read-only presentation, as the record explains); S1 → `NO-WINDOW` (C LOST) | PASS | SUPPORTED |
| E4 restoration-window suites | fast.tap | MEASURED: `ok 2043 - the window after /reload (A): every perk install only adds until the run starts; the first request declares none of the names the close removed; the late tool comes back`; `ok 2044 - a /tree restore inside the window (A): after /reload, navigating back to a leaf whose transcript declared an activated family member keeps it through the next run; the rest of the family is switched off`; `ok 2045 - a sendMessage-triggered turn inside the window (A): no before_agent_start, yet its first request declares none of the removed names and the removals land`; `toolGating.test.ts`: `ok 2170 - the restoration window: a reload session_start or a session_tree opens it — …`, `ok 2171 - the restoration window's presentation: …`, `ok 2172 - the restoration window's close: …`, `ok 2173 - the restoration window: a /tree restore that replaces the loadout supersedes the reload's pending family deferral — …`, `ok 2174 - a prime inside the restoration window of an inactive pending member lifts its deferral: …`, `ok 2175 - the restoration window stays shut at startup, and a bare session's agent_start installs nothing` | PASS | SUPPORTED |

## W — Worker (real runtime, 1.0.0 SDK)

Every W1 line is from `slow.tap` (`extension/worker/stageExecutionE2e.test.ts`, the only file
carrying these titles) — MEASURED (offline, real runtime, 1.0.0 SDK). A5 re-ran the same file on
Node 22.19.0 against `$CLONE`'s `npm ci` install: 34/34.

| Row | Verbatim TAP lines | Verdict | Class |
|---|---|---|---|
| W1a native tools, opt-outs, disable | `ok 992 - e2e: discovery opt-in — the worker joins the cohort through its builtin tool_search; a search re-declares a deferred member`; `ok 993 - e2e: discovery opt-out (-tool_search) — the builtin is registered but inactive; the family stays declared`; `ok 994 - e2e: -builtin:<name> disables a worker builtin — neither loads, even when defaultTools names it` | PASS | OPT-OUT |
| W1b provider before selection; explicit/default model | `ok 976 - e2e: no_model is decided AFTER extension registration (order pin) → zero-turn failed/no_model`; `ok 977 - e2e: a throwing availability read after services → zero-turn runtime_init, agentDir removed`; `ok 978 - e2e: explicit --model selects an extension-registered provider with a saved credential → completed`; `ok 979 - e2e: default selection honours a saved non-first default from an extension provider → completed`; `ok 980 - e2e: an explicit model whose provider has no configured auth → zero-turn failed/model_auth`; `ok 981 - e2e: an unknown explicit model → zero-turn failed/model_not_found`; `ok 983 - e2e: a virtual model routes to a physical target with a different identity → completed`; ``ok 984 - e2e: a `:thinking` suffix on --model survives the reorder → session thinking level applied`` | PASS | SUPPORTED |
| W1c MCP census | `ok 995 - e2e: the worker loads no builtin:mcp — .pi/mcp.json is inert and a project registerMcpServer is reported, never connected` | PASS | DEFERRED (MCP in the worker) |
| W1d terminal success / abort / caps | `ok 967 - e2e: implement HAPPY — faux model calls submit → completed/submit_tool + full event stream`; `ok 968 - e2e: implement HAPPY (file sink) — the production NDJSON sink writes the same stream shape`; `ok 969 - e2e: address HAPPY — finalize_address ok → completed/address_resolved`; `ok 970 - e2e: implement PREMATURE-IDLE — model goes idle without submit → failed/agent_idle_incomplete`; `ok 971 - e2e: FAILING-TOOL — submit fails → capped tool_outcome summary + failed/agent_idle_incomplete`; `ok 973 - e2e: NO-EXTENSION-TOOLS — empty packages list → zero-turn failed/no_extension_tools`; `ok 974 - e2e: EXTERNAL-ABORT — a mid-drive abort ends the real session → aborted/external_abort`; `ok 975 - e2e: BUDGET — the turn cap trips the watchdog on the real session → budget_exhausted/budget` | PASS | SUPPORTED |
| W1e compaction + retry follow the settings | `ok 996 - e2e: COMPACTS IN-DRIVE AND COMPLETES — a threshold compaction runs before the next request and is counted once`; `ok 999 - e2e: COMPACTION TRIPS THE TOKEN CAP — the run ends at the compaction boundary with zero further provider requests`; `ok 997 - e2e: RETRY RECOVERS — a retryable provider error is retried and the drive completes`; `ok 1000 - e2e: RETRIES EXHAUSTED — the last unrecovered error is terminal → failed/model_error`; `ok 972 - e2e: MODEL_ERROR — a non-retryable provider error → failed/model_error, no retry` | PASS | SUPPORTED |
| W1f compaction opt-out | `ok 998 - e2e: PROJECT OPT-OUT HONOURED — compaction.enabled false in the project settings → no compaction` | PASS | OPT-OUT |
| W1g model-tool accounting, the cap bar, non-token refusal | `ok 985 - e2e: MODEL-TOOL direct — a model-using tool's reported usage is counted once; warming off, compaction and retry on Pi's defaults`; `ok 986 - e2e: MODEL-TOOL nested — a model-using tool called from a codemode script is counted once`; `ok 987 - e2e: CODEMODE classify across the cap (test-only models:true) — counted once at turn_end, no further request, no usage on partials`; `ok 988 - e2e: mid-script EXTERNAL abort with a call in flight — the held call is aborted, no call starts after the abort`; `ok 989 - e2e: mid-script WALL-CLOCK exhaustion — the watchdog aborts a running script`; `ok 990 - e2e: queued concurrency after an abort — the queued calls never reach the provider`; `ok 991 - e2e: PRODUCTION SHAPE — the worker's own builtin codemode (models:WORKER_CODEMODE_MODELS) + the typed refusal; refusals are non-terminal` | PASS | CONSTRAINED |
| W1h the real entry | `ok 982 - e2e: the real worker entry admits the installed SDK and drives to completion, independent of PATH and the CLI stamp` | PASS | SUPPORTED |
| W2 unit pins | spec runs for attribution; fast.tap | `extension/worker/sdkAdapter.test.ts` `ℹ tests 38` / `ℹ pass 38` / `ℹ fail 0`, incl. `✔ workerBuiltinExtensions: Pi's codemode then tool-search with the CLI's builtin identity, no MCP` (factory identity/order) and `ok 2710 - formatExtensionError: Pi's ExtensionError renders path, event and message; other values fall back`; `extension/worker/stageExecution.test.ts` 54/54; `extension/worker/modelCallPolicy.test.ts` 16/16, incl. `✔ WORKER_CODEMODE_MODELS: the worker-owned codemode has no \`models\` namespace`; `ok 1860 - precondition: the installed SDK this suite runs on is admitted by the shipped floor` (`hostAdmission.test.ts`, 14/14) | PASS | SUPPORTED |
| W3 auth isolation + per-factory answer | W1c's assertions + source at `v1.0.0` | W1c asserts `existsSync(join(result.globalAgentDir, name)) === false` for `mcp.log` and `mcp-auth.json` (`stageExecutionE2e.test.ts:1620`); W1d's HAPPY asserts no new `perk-worker-agent-*` survives the drive (`:347–360`). Source: `packages/coding-agent/src/extensions/tool-search/{index,tool}.ts@v1.0.0` and `extensions/codemode/{index,tool,execute,worker}.ts@v1.0.0` — 0 matches for `getAgentDir\|homedir\|CONFIG_DIR`; `packages/codemode/` — 0 matches for `getAgentDir\|homedir`; `extensions/mcp/index.ts@v1.0.0:342` `options.logPath ?? join(getAgentDir(), "mcp.log")`, `:1178` `loadMcpConfig({ agentDir: getAgentDir(), …})`; `extensions/mcp/oauth.ts@v1.0.0:137` `new FileAuthStorageBackend(join(getAgentDir(), "mcp-auth.json"))` | PASS | DEFERRED (MCP routing, isolation fixture, headless OAuth refusal) |

## X — Existing sessions and surfaces

| Row | Procedure | Verbatim observation | Verdict | Class |
|---|---|---|---|---|
| X1 interactive discovery + model-only boundaries | owner `/perk-selfcheck` (11:40:25Z); the implementer's `tool_search {"query": "objective_stack_status"}`; owner `/perk-selfcheck` (11:45:57Z); a codemode script `const names = Object.keys(tools).sort(); return { count: names.length, names };` (11:46:48Z, after a temporary `+codemode` and `/reload` — see deviations) | Before: `tools: 35 active / 66 registered`, `per source: ..=22 (21288c)`, `discovery: cohort (family: objective_stack_status, collect_review_wave, collect_draft_review_wave, push_annotations)`. Search: `Loaded 1 tool. They are available from your next call:` / `- objective_stack_status: Report an objective's stacked delivery train: …`. After: `tools: 37 active / 66 registered`, `per source: ..=24 (23678c)` — `objective_stack_status` plus `push_annotations`, which a third search (`"run a TypeScript script calling tools"`) loaded (`Loaded 1 tool. …` / `- push_annotations: …`; never called). Codemode: `{"count":23,"names":["add_objective_node","ask_user_question","bash","bg_wait","collect_draft_review_wave","collect_review_wave","edit","fffind","ffgrep","objective_node","objective_stack_adopt","objective_stack_land","objective_stack_recover","objective_stack_status","post_pr_review","push_annotations","read","reconcile_objective","run_ci","submit_pr_review","todo","web_enable","write"]}`. That is 13 direct perk tools (the registered catalog's `action`/`query` kinds; its 4 authoring-stage drafts are scoped out of `implement`) and none of its 24 model-only tools (`terminal` 9, `interactive` 1, `orchestration` 13, `host` 1) (LIVE). MEASURED: `ok 800 - exposure census: model-only iff terminal/interactive/orchestration/host; readOnlyHint iff not blocked` | PASS | SUPPORTED |
| X2 read-only suspension | owner `/plan` on → the implementer: `bash npm install x --dry-run` (see deviations), `bash echo test > /tmp/perk-x2-probe.txt`, `edit`, `tool_search "codemode"`; owner `/perk-selfcheck` (12:12:38Z) → owner `/plan` off → a codemode call and an `edit` | Read-only: `perk read-only mode: command blocked (not allowlisted).` / `Command: npm install x --dry-run` / `Reason: matches the destructive veto /\bnpm\s+(install\|uninstall\|update\|ci\|link\|publish)/i`; the redirect: `Reason: matches the destructive veto /(^\|[^<])>(?!>)/`; `edit` and `write` were not declared to the model, so no call could be made; `tool_search "codemode"` → `No matching tools found.`; selfcheck `tools: 20 active / 66 registered`, `per source: ..=7 (7323c); builtin=5 (3327c); …`, `perk:mode-context ×1 (910c) live=1`, `native sdk bridge: installed (roots=2, specifiers=8, reused)`. Released (12:58:20Z): codemode `return { restored: true, n: Object.keys(tools).length }` → `{"restored":true,"n":23}`; `edit` → `Successfully replaced 1 block(s) in .perk/workflow/scratch/runs/01M4CQM5Z7PVWA75AGA4R3V6JR/agent/progress.md.` (LIVE). MEASURED: `ok 2205 - gate suspension: only the builtin-sourced codemode; suspended while read-only, restored at release when still registered` | PASS | SUPPORTED |
| X3 resume / tree / compaction | owner, each followed by `/perk-selfcheck`: `/reload`; `/tree` to an earlier entry and back; `/compact` + one ordinary turn; quit + `uv run perk resume 01M4CQM5Z7PVWA75AGA4R3V6JR` from `$WT`. Readings are the session file's `perk:report-detail` entries | Every summary reads `perk: selfcheck — 3.9.0: ok; shared=ok; ambient=reached (append=5359c); agents=reached (files=1); bridge=installed` with `host sdk: 1.0.0 (floor >= 1.0.0)`. **`/reload`** (11:46:12Z): `native sdk bridge: installed (roots=2, specifiers=8, reused)`, `tools: 55 active / 66 registered` (the restoration window: installs only add until the run starts, E4 `ok 2043`). **`/tree`** (13:14:55Z): the entry at 13:14:40Z is parented on `f7ad4d3a` (an earlier tool result) and the one at 13:14:50Z on `d6f36498` (the leaf); `branch: 579 entries`, `reused`, nothing re-injected (`perk:agent-scratch ×1 (425c) live=1; perk:mode-context ×1 (910c) live=1; perk:plan-adapter-plannotator ×1 (1682c) live=1; perk:plan-context ×1 (1688c) live=1`). **`/compact`** (compaction 13:17:20Z; turn "continue" 13:20:46Z; selfcheck 13:21:26Z): `branch: 602 entries; binding-header-copies=3`, `perk contexts: perk:agent-scratch ×2 (850c) live=1; perk:binding-context ×1 (126c) live=1; perk:mode-context ×1 (910c) live=0; perk:plan-adapter-plannotator ×1 (1682c) live=0; perk:plan-context ×1 (1688c) live=0; other custom_message ×0 (0c)`: the guidance appears once while its history holds two copies, and the pre-compaction injections are `live=0`. **Resume** (the same session file reopened; selfcheck 13:24:45Z): `native sdk bridge: installed (roots=2, specifiers=8)` — no `reused`, a fresh process — with `branch: 621 entries` and the same `perk contexts:` line (LIVE). MEASURED: `ok 2152 - mode-context is once-only per SELECTED BRANCH: a copy compaction summarized out of context does not re-inject` | PASS | SUPPORTED (K3 ADAPTATION) |
| X4 `/btw` | owner: two `/btw` turns on main-context facts, then "Inject summary into main chat"; the session file | Two `btw-thread-entry` entries (13:12:09Z, 13:12:43Z), both `"question": "Which matrix rows are still pending in this certification?"` and answered from the main conversation's state (the first `Rows still pending: …` names X3's remaining sub-steps, X6, and X5b/S7/I7b after the PR; the second `Nothing has changed since my last answer. …`); then `btw-thread-reset` (13:13:03.558Z) and exactly one `"role": "user"` message (13:13:03.617Z) starting `Summary of my BTW side conversation:` (LIVE). MEASURED: `ok 2386 - liveModelRuntime recovers the live runtime from the real ModelRegistry facade` | PASS | ADAPTATION (K2) |
| X5a browser review — plan door | the planning JSONL; the owner's observation | see [Browser doors](#browser-doors) | PASS | SUPPORTED |
| X5b browser review — PR door | owner `/pr-review-browser <PR>` in the implement session | ⟨PENDING — after the PR⟩ | ⟨PENDING⟩ | SUPPORTED |
| X6 regular / fullscreen | the implement session (Pi's fullscreen default, no perk seed — A7); owner `$(which pi) --tui-mode regular` from `$WT` in a separate terminal, `/perk-selfcheck`, inspect, quit | Owner: fullscreen footer, status slot and widgets readable — "1. yes"; "2. nothing cut off in either mode". The regular-mode session wrote no JSONL (see deviations). MEASURED: `ok 2359 - rich-UI calls live only in the surfaces module (surfaces/surfaces.ts + surfaces/report.ts)`, `ok 2360 - setWorkingIndicator is never called (charter D5 rescinded)`, `ok 2361 - the data-only pi-tui allowlist entries carry no pi-tui import (import-aware, lexed specifiers)` (`extension/surfacesGuard.test.ts`) | PASS | OPT-OUT |
| X7a headless selfcheck | `$SCRUB <hermetic> ~/.local/…/26.3.0/bin/pi --approve --mode json -p /perk-selfcheck` from `$WT` under the watchdog (03:31:35Z) | `perk: selfcheck — 3.9.0: ok; shared=ok; ambient=reached (append=5359c); agents=reached (files=1); bridge=installed`; `tools: 50 active / 66 registered`; `discovery: cohort (family: objective_stack_status, collect_review_wave, collect_draft_review_wave, push_annotations)`; `host sdk: 1.0.0 (floor >= 1.0.0)`; `native sdk bridge: installed (roots=2, specifiers=8)`; 0 `Failed to load extension`; `exit=0 elapsed=2s` (LIVE) | PASS | SUPPORTED |
| X7b print-mode exit pair (INFO) | X7a and S4a stderr | X7a: none (no model turn). S4a, once: `Extension error (<boundary>): turn_end could not resolve the persisted assistant entry ID` / `Extension error ($WT/extension/index.ts): This extension ctx is stale after session replacement or reload. …`; S4b the same pair once | OBSERVED | SUPPORTED |
| X7c #2660 repro (INFO) | `/probe-spawn script $MODEL missingbase` (`$WT` dirty by `$SCRATCH`) and the `badmodel` control, both under the watchdog | `missingbase`: lane `Worktree admission failed for 'probe' at $WT: worktree isolation requires a clean git working tree. Commit or stash changes first. …`; stderr 19× `turn_end could not resolve …`, 37× stale-ctx, 18× `perk: loadout presentation failed`; `watchdog: pi still running 60s after the probe's terminal line (elapsed 67s) — TERM pgid 28480`; `exit=143 elapsed=72s`. `badmodel`: `Unknown subagent model 'perk-probe/does-not-exist' …`, 2 / 2 / 0, `exit=0 elapsed=17s`. Matches 1.2's X1/X1b (not perk-attributable; #2660) | OBSERVED | SUPPORTED |

### Browser doors

The five criteria are `pi-subagents-0.75.0-reverify.md` §Browser doors (D6): (1) every requested
lane runnable, no preflight failure; (2) `complete: true`, N/N covered, no failures; (3) exactly one
`replace: true` push per covered angle, every receipt the ok arm with `held == 0` and
`held_batches == 0`; (4) the browser decision after the last push receipt in file order; (5) the
owner's observation of the `perk:wave` marker and the annotations. A DENY is a valid decision.

**X5a — plan door — PASS.** Host: the PATH Pi 1.0.0, pi-subagents 0.75.0 in `$MAIN/.pi/npm`, perk
3.9.0 at `c829e462` (the planning session ran from `$MAIN`). Instrument: the planning JSONL (file
lines below).

- **(1) Launch.** Line 206 calls `start_draft_review_wave {"angles": ["grounding",
  "decision-completeness", "risk"]}`. Line 207 (02:47:52Z): "Draft-review workflow accepted with
  4/4 post-preflight runnable lane(s) — grounding, decision-completeness, risk, ponytail (asyncId
  8b50bd4b-8881-4da1-83a7-4a21d7089e19)."; `details.launch` `{"requested": ["grounding",
  "decision-completeness", "risk", "ponytail"], "runnable": [same], "preflightFailures": []}`.
- **(2) Collect.** After the workflow-completion notice (line 213, 02:52:46Z, `subagent-notify`
  "Background task completed: **workflow**"), line 215 (02:52:51Z): "Draft-review wave complete:
  covered 4/4 lane(s)." — `complete: true`, `covered` all four, `failures: []`; one attempt
  `{"runId": "8b50bd4b-…", "state": "complete", "flow": "draft-review"}` whose four
  `perk.draft-reviewer` children are `success: true` (the receipt: each `completed …
  openai/gpt-6-astra`).
- **(3) Delivery.** Four `push_annotations` calls, one per angle, each `replace: true`:

  | Angle | Receipt (line) | `pushed` | `held` | `held_batches` | `deleted` |
  |---|---|---|---|---|---|
  | grounding | "Annotations — perk:grounding: pushed 5." (217) | 5 | 0 | 0 | 0 |
  | decision-completeness | "Annotations — perk:decision-completeness: pushed 3." (219) | 3 | 0 | 0 | 0 |
  | risk | "Annotations — perk:risk: pushed 1." (221) | 1 | 0 | 0 | 0 |
  | ponytail | "Annotations — nothing to push." (223) | 0 | 0 | 0 | 0 |

  Every receipt is `{"ok": true, "mode": "plan", …, "skipped": []}`.
- **(4) Decision order.** The owner DENIED; the feedback turn is line 225 (02:55:42Z, "The human
  DENIED the plan in the browser review …"), after the last receipt (line 223, 02:53:59Z).
- **(5) Owner observation.** Asked once while this row was written: "Yes — marker and all nine".
- The second round (line 258 `plan_review` → line 264 "plan APPROVED by reviewer.") ran no wave.

**X5b — PR door.** ⟨PENDING — appended after the PR exists⟩

## K — Keep-and-reverify

| Row | Adaptation | Re-verified by | Retirement condition re-checked at `v1.0.0` | Status |
|---|---|---|---|---|
| K1 | Host SDK bridge (`extension/substrate/nativeSdkBridge.ts`) | I5, I7a, I7b, S1, S3 | Under the PATH `dist/bundle/cli.js`, `packages/coding-agent/src/core/extensions/loader.ts@v1.0.0:44` sets `usesEmbeddedModules = isBunBinary \|\| isNodeSeaBinary \|\| isBundledNode` and `:563–572` hands jiti `{ virtualModules: await getVirtualModules(), tryNative: false }`. `tryNative` governs only jiti's up-front native attempt: the installed bundle's inlined jiti 2.7.0 (`dist/bundle/chunks/jiti-loader-C3NU2SDH.js`) still computes `S2=n2.forceTranspile??(!C2&&!(w2&&n2.async)&&(…))` and, for an ESM module imported async, takes `debug(t3,"[native]",…)` → `nativeImportOrRequire(…)` — Node's native loader, where `virtualModules` do not apply. pi-subagents' and pi-web-access's compiled `.js` entries therefore still bypass Pi's SDK instances | RETAINED |
| K2 | `/btw` live-runtime adaptation (`extension/vendor/btw/btw.ts::liveModelRuntime`) | X4 + `ok 2386 - liveModelRuntime recovers the live runtime from the real ModelRegistry facade` | `packages/coding-agent/src/core/model-registry.ts@v1.0.0:49` `private readonly runtime: ModelRuntime;` — no public accessor (every member delegates to `this.runtime.*`) | RETAINED |
| K3 | Canonical projection + delivery predicates | X3's `live=` readings; `ok 2152 - mode-context is once-only per SELECTED BRANCH: a copy compaction summarized out of context does not re-inject` | Pi projects the context; perk still verifies delivery on the selected branch | RETAINED |
| K4 | RPC context-less / stale-responder guards (`rpcAdapter.ts::WAVE_RPC_CONTEXTLESS_ERROR_CODE`) | S2 (`ok 2639 - the pinned context-less code is pi-subagents' no_active_session`, the four `hold:` cases); S3/X5a show no `no_active_session` error (the planning JSONL's 6 matches are report text, tool output and the planner's own reasoning, not RPC errors; both attempts `state: "complete"`, `failures: []`) | a fix to Pi's separate `RpcClient` is not replacement evidence | RETAINED |
| K5 | Worker `finishTurn` gate (`sdkAdapter.ts::installGate`) + codemode `models: false` + `perk-worker-policy` (`worker/modelCallPolicy.ts`) | W1d `BUDGET`, W1g `PRODUCTION SHAPE`, `CODEMODE classify across the cap` (no usage on partials) | `packages/agent/src/agent-loop.ts@v1.0.0:179–291`: between `finishTurn` (`:286`) and the next `streamAssistantResponse` (`:242`) the loop checks no `signal.aborted` — the only stop is `finishTurn`'s `{action: "end"}`; `packages/agent/src/types.ts@v1.0.0:528` `{ type: "tool_execution_update"; toolCallId: string; toolName: string; args: any; partialResult: any }` — no `usage`, as emitted by `agent-loop.ts@v1.0.0:778–787` | RETAINED (CONSTRAINED) |

## Classification lists

### Supported behavior

- **Host admission:** the launch refuses a below-floor, pre-release, unverifiable or missing Pi
  with typed codes and upgrade guidance, on fresh and resumed paths alike (A1); init/doctor report
  the same floor (A2); the extension refuses to load on a real Pi 0.99.2 (A3e); the worker refuses
  a real 0.87.0 or 0.99.2 SDK (A3w); a floor-satisfying SDK newer than the CLI is admitted
  independently (A4); the remote setup installs exactly Pi 1.0.0 on Node 22.19.0 (A5); `doctor
  --fix` restores a deleted `defaultTools` byte-identically (A6a).
- **Installation:** CLI, SDK pins and suppliers at their certified versions (I1–I3); a bare clone
  loads perk with zero bare npm dependencies (I4); the thin entries link nothing SDK-bearing before
  admission and survive `/reload` (I6).
- **pi-subagents 0.75.0 children on the 1.0.0 host:** the offline wave suites (S2), a live scout
  wave (S3), mixed siblings with the restriction packet and structured completion (S4a), RPC
  cancellation (S4b), the four trust rows (S5) and task restoration (S6). Repeated collection (S7)
  is appended after the PR.
- **Evidence and restoration:** `/learn` evidence over Pi 1.0.0 system entries (E1) and nested
  calls (E2); delayed MCP registration at parity with the control (E3); the restoration windows
  after `/reload`, `/tree` and `sendMessage` (E4).
- **Worker:** native tool discovery, provider registration before model selection, terminal
  outcomes and caps, compaction and retry following the repo settings, and the real entry (W1a,
  W1b, W1d, W1e, W1h, W2).
- **Sessions:** interactive discovery and the model-only boundary (X1), read-only suspension and
  release (X2), `/reload`, `/tree`, `/compact` and resume (X3), the headless selfcheck (X7a), and the
  plan browser door (X5a). The PR browser door (X5b) is appended after the PR.

### Configuration opt-outs

- `-tool_search` in `defaultTools` (W1a; the interactive opt-out is preserved by init/doctor, A7).
- `-builtin:<name>` for a worker builtin (W1a).
- `compaction.enabled: false` in the project settings (W1f).
- `retry.enabled` (the worker follows Pi's retry settings, W1e).
- `PERK_DISABLE_NATIVE_SDK_BRIDGE` (I5's `install: PERK_DISABLE_NATIVE_SDK_BRIDGE=1 disables …` and the `opt-out` fixture).
- `tuiMode` — user-owned; perk seeds none and preserves an existing value (A7, X6).

### Retained adaptations

K1 (host SDK bridge), K2 (`/btw` live runtime), K3 (canonical projection + delivery predicates),
K4 (RPC context-less / stale-responder guards). K5 is retained as a constraint (below).

### Constrained capabilities

- Worker codemode runs with `models: false` (`WORKER_CODEMODE_MODELS`), and `perk-worker-policy`
  refuses image-generation and classifier calls with a typed, non-terminal refusal (W1g, W2, K5).
- The worker's turn cap is enforced at `finishTurn` (Pi 1.0.0 has no abort check before the next
  request), and partial tool updates carry no usage, so a model call inside a script is counted
  once at `turn_end` (K5).

### Deferred work

- **MCP in the worker** — the worker supplies no MCP factory (W1c); routing, an isolation fixture
  for `getAgentDir()`-defaulted `mcp.log` / `mcp-auth.json`, and a headless OAuth refusal are
  unbuilt (W3).
- **The live deadline-partial** — S4c observed a retained `partial` on a 20 s deadline, but the
  required evidence stays the offline S2 rows.
- **The `/btw` private-runtime retirement** — waits for a public `ModelRegistry` runtime accessor
  (K2).

## Falsified planning-time assumptions

1. **Bare `perk` needs a terminal** (A1). Without a TTY it refuses before any probe (`Error: bare
   \`perk\` opens an interactive Pi session, which needs a terminal on stdin and stdout …`); the
   arms ran under `script -q /dev/null` (a pty).
2. **`perk --dry-run` does not exist** (A1: `Error: No such option '--dry-run'.`, exit 2). The
   dry-run arms are `perk resume <run> --dry-run` and `perk plan --dry-run`.
3. **The typed refusal code is not printed** by the human launch path ("the human failure path
   renders only the message"); A1 reads it through the launch path's own functions.
4. **A6a's byte criterion** assumed the repair restores the key in place; it re-appends it (fixed
   by `e8903aba`).
5. **E1's "system entries rendered with bounded text"**: Pi 1.0.0 persists system entries with
   `content: ""` and the substance in `sections`; §8.35 prunes them (owner-confirmed PASS).
6. **S6's tests are in the fast tier**, not `slow.tap`.
7. **A5's `--test-name-pattern`** after the file positional was not applied on Node 22.19.0; the
   whole e2e file ran (34/34), the real-entry test included.
8. **`perk init` in a perk worktree exits 2** on the skills-CLI sync (`conflict`), a recorded
   worktree gotcha, not a Pi effect (A7 note).
9. **The registry moved past 1.0.4**: `latest` is 1.1.0, so A4 used 1.0.4 (the latest 1.0.x) and
   A6b's unpinned install resolved 1.1.0.

## Methodology appendix

### Scaffold (Steps 0–1)

```sh
# Step 0 ($WT)
git rev-parse HEAD                                   # c829e46260fbea45cdd067a6c13d2fc1137d7d5e
which pi; readlink -f "$(which pi)"; pi --version    # 1.0.0
npm view @earendil-works/pi-coding-agent versions --json | tail -5; npm view … dist-tags --json
git -C "$MIRROR" rev-parse v1.0.0                    # a13d35a7…
MODEL="$PI_PROVIDER/$PI_MODEL"                       # anthropic/claude-opus-5-5
shasum -a 256 "$MAIN/.pi/npm/package.json" "$MAIN/.pi/npm/package-lock.json" \
  "$MAIN/.pi/npm/node_modules/.package-lock.json" "$MAIN/.pi/npm/node_modules/pi-subagents/package.json"
git -C "$MAIN" status --porcelain                    # (empty)
# Step 1
TMP=$(mktemp -d -t perk-cert)                        # no ancestor node_modules/.perk/.pi (walked)
git clone -q --no-hardlinks "$MAIN" "$CLONE" && git -C "$CLONE" checkout plan-2682
cp -R "$MAIN/.pi/npm" "$CLONE/.pi/npm"               # independent copy (inode 466757775, links 1)
mkdir -p "$PIHOME" "$STUBS" "$WORKWT" "$LOGS" "$HERMETIC" "$AUTHED" "$TMP/subagents-tmp" "$SCRATCH"
cp "$MAIN/.pi/agent/auth.json" "$AUTHED/auth.json"   # credentials only
# WORKWT, planted as extension/testing/harness.ts::scaffoldWorkerWorktree does:
#   .pi/settings.json                    {"packages": ["$CLONE"]}
#   .perk/workflow/handoff/cert.json     {"run_id": "cert", "consumed": false, "mode": "read-write", "stage": "implement"}
#   .perk/workflow/plan-ref.json         {"provider": "github", "pr_id": "148", "url": "https://github.com/mattgiles/perk/issues/148", "labels": [], "objective_id": "137"}
#   git init -q
# STUBS: old → `echo 0.99.2`; rc → `echo 1.0.0-rc.1`; junk → `echo banana`; empty → `exit 0`;
#   slow → `sleep 25; echo 1.0.0`; none-bin → symlinks to uv git gh node npm sh bash env uname, no pi
```

Instruments (`shasum -a 256`, Step 1):

| File | sha256 |
|---|---|
| `$SCRATCH/run-bounded.sh` (1.1's watchdog, extracted verbatim from `pi-1.0.0-characterization.md`) | `1114155f63fdd2ecb8616dbdf9a890de09b693deb5f6f3cf4aa7bf6fd94b0843` |
| `$SCRATCH/probe-spawn.ts` (1.2's probe + the three modes below) | `4be3a84fe9113b66d7bde8f4a620d4942877a6781dd32967358bd813ac27185a` |
| 1.2's probe as extracted, before the modes | `72cb2372580b80137a727ae2a19430770d05a2211cfb78cb7346563bf7ec6d2d` |
| `$SCRATCH/mcp-restoration.test.ts` (extracted verbatim from `pi-1.0.0-mcp-restoration.md`) | `5986f3d23e39c3435d0b8dbd147fd2afdc87324d29702139a33fdbb65cc22fcb` |

### Launch environments

`$SCRUB` is 1.1's: `env -u PERK_RUN_ID -u PERK_PROFILE_HANDOFF -u PERK_SELFCHECK -u
PERK_DISABLE_NATIVE_SDK_BRIDGE -u PERK_CLI_VERSION -u PI_SUBAGENT_CHILD -u PI_SUBAGENT_CHILD_AGENT -u
PI_SUBAGENT_EXTENSION_BINDINGS -u PI_SESSION_FILE -u PI_SESSION_ID -u PI_MODEL -u PI_PROVIDER -u
PI_REASONING_LEVEL -u PI_CODING_AGENT`. `env | grep -E '^(PI_|PERK_)' | sort` after it:

| Layer | Rows | `PI_*` / `PERK_*` |
|---|---|---|
| hermetic | I4, X7a, A3e (raw) | `PERK_SKIP_VERSION_CHECK=1`, `PI_CODING_AGENT_DIR=$HERMETIC`, `PI_OFFLINE=1`, `PI_SUBAGENTS_TEMP_ROOT=$TMP/subagents-tmp` (+ `ANTHROPIC_API_KEY=perk-live-smoke-placeholder-never-sent`) |
| authed | S4a–c, X7c | `PERK_SKIP_VERSION_CHECK=1`, `PI_CODING_AGENT_DIR=$AUTHED`, `PI_SUBAGENTS_TEMP_ROOT=$TMP/subagents-tmp` |
| worker | A3w, A4 | `$SCRUB` + `PERK_RUN_ID=cert`, `PI_CODING_AGENT_DIR=$HERMETIC` |

The probe's own `env` dump (S4a) shows exactly `PI_CODING_AGENT_DIR`, `PERK_SKIP_VERSION_CHECK`,
`PI_SUBAGENTS_TEMP_ROOT` and the in-process `PI_CODING_AGENT: "true"`. Every `perk` command ran as
`uv run perk …` from `$WT` (A1's `none` arm through the absolute `uv`). Every manual `pi` named the
absolute executable and ran under `run-bounded.sh` (GRACE 60 s, CAP 330 s); the watchdog fired only
on X7c `missingbase`. Every command's output went to `$LOGS/<row>.log`.

### Recorded test invocations

```sh
run_ci check="lint-py,lint-js,typecheck-py,typecheck-js,typecheck-prose-review,test-py-fast,test-py-slow,test-js"
just test-js-slow --test-reporter-destination=stdout --test-reporter=tap --test-reporter-destination="$LOGS/slow.tap"
just test-js-fast --test-reporter-destination=stdout --test-reporter=tap --test-reporter-destination="$LOGS/fast.tap"
uv run pytest -rfEs 2>&1 | tee "$LOGS/pytest-full.log"
uv run pytest -v -n0 -rfEs <node ids> 2>&1 | tee "$LOGS/<row>-pytest.log"      # I2a I3 S1 A3e A4 A5 A6a A7 E1 E2
node --test --test-reporter=spec <file> 2>&1 | tee "$LOGS/<row>.log"          # I4 I5 I6 S2 W2 (attribution)
```

The TAP stream carries no file names, so a title shared by several files (the draft-review
`structured_output` title appears in five) was attributed with a spec run of the named file.

### The probe's added modes (the delta against 1.2's probe, verbatim)

```diff
-import { join } from "node:path";
+import { dirname, join } from "node:path";
@@
+// cancel mode: the workflow journal names each started child's runId; the child's status.json (a
+// sibling async dir) carries the runner pid once the runner process exists.
+async function waitForRunnerPid(asyncDir: string, timeoutMs = 90_000): Promise<unknown> {
+  const until = Date.now() + timeoutMs;
+  while (Date.now() < until) {
+    const journal = join(asyncDir, "workflow-children.jsonl");
+    if (existsSync(journal)) {
+      for (const line of readFileSync(journal, "utf8").split("\n")) {
+        if (!line.trim()) continue;
+        const rec = JSON.parse(line) as { type?: string; runId?: string; key?: string };
+        if (rec.type !== "start" || typeof rec.runId !== "string") continue;
+        const childStatus = join(dirname(asyncDir), rec.runId, "status.json");
+        if (!existsSync(childStatus)) continue;
+        const st = JSON.parse(readFileSync(childStatus, "utf8")) as { pid?: number; state?: string };
+        if (typeof st.pid === "number") return { key: rec.key, runId: rec.runId, pid: st.pid, state: st.state, childStatus };
+      }
+    }
+    await new Promise((r) => setTimeout(r, 1000));
+  }
+  return { probeTimeout: "runner-pid" };
+}
@@
+  // Certification modes (5.1): mixed = an OK restricted lane beside a bad-model lane; cancel = one
+  // long lane stopped over the RPC once its runner pid exists; deadline = quick + long lanes under a
+  // 20 s spawn timeout.
+  const LONG = "Read AGENTS.md and summarize it in 600 words.";
+  const items =
+    mode === "mixed"
+      ? [
+          { ...item, key: "probe-ok", label: "probe-ok", model, extensionBindings: { "perk.parent-restrictions/1": { readOnly: true } } },
+          { ...item, key: "probe-bad", label: "probe-bad", model: "perk-probe/does-not-exist" },
+        ]
+      : mode === "cancel"
+        ? [{ ...item, key: "probe-cancel", label: "probe-cancel", model, task: LONG }]
+        : mode === "deadline"
+          ? [
+              { ...item, key: "probe-quick", label: "probe-quick", model },
+              { ...item, key: "probe-long", label: "probe-long", model, task: LONG },
+            ]
+          : [item];
   const script =
-    `const reports = await runs.all(${JSON.stringify([item], null, 2)});\n` +
+    `const reports = await runs.all(${JSON.stringify(items, null, 2)});\n` +
@@
-      intercomBridge: { mode: "off" }, timeoutMs: 120_000,
+      intercomBridge: { mode: "off" }, timeoutMs: mode === "deadline" ? 20_000 : 120_000,
@@
+  if (mode === "cancel") {
+    const runner = await waitForRunnerPid(details.asyncDir);
+    log("runner", runner);
+    log("stop", await call(pi, "stop", { id: details.asyncId }));
+  }
   log("status", await settle(details.asyncDir));
```

The usage strings also list the three new modes. The watchdog is
[`pi-1.0.0-characterization.md`](pi-1.0.0-characterization.md)'s `run-bounded.sh`, unchanged. The
MCP script is [`pi-1.0.0-mcp-restoration.md`](pi-1.0.0-mcp-restoration.md)'s, unchanged (sha256
above).

### Deviations from the plan's procedure

- **A1** ran each `uv run perk` arm under `script -q /dev/null` (bare `perk` needs a TTY); the
  `none` arm named `/usr/bin/script` and the absolute `uv` (its PATH holds only the symlinks). The
  dry-run arms are `perk resume … --dry-run` and `perk plan --dry-run`. The admitted plain-session
  arm was driven through the same pty (`/quit` after 12 s) rather than by the owner.
- **A1/A2** typed codes: read through `perk.run.pi_exec._resolve_pi_executable` /
  `_admit_pi_host` (the launch path's own functions) under each stub PATH.
- **A3w/A4/A5** `npm install --no-save <pkg>` reifies the whole dev tree, so the top-level
  `pi-ai`/`pi-tui`/`pi-agent-core` stayed 1.0.0 beside the swapped `pi-coding-agent`; the admission
  reads only `pi-coding-agent`'s `VERSION`.
- **A5** ran `npm ci` and the e2e under `mise exec node@22.19.0` (mise provisioned it, so the INFO
  arm was not needed).
- **A6a** was rerun once after the owner-approved fix `e8903aba`.
- **A6a/A7** created `$WT/.perk/local.toml` (gitignored, comment-only); it was removed after each
  row.
- **E1** reused the bundle `perk learn evidence` writes under `$WT/.perk/workflow/scratch/` (gitignored).
- The planning JSONL was copied to `$LOGS/planning-session.jsonl` for the S3/X5a extraction.
- **X1's codemode step.** Pi registers its builtin codemode `defaultActive: false`
  (`packages/coding-agent/src/extensions/codemode/index.ts@v1.0.0:41`), and `tool_search` does not
  surface it (`"codemode"` → `No matching tools found.`). A temporary `+codemode` in
  `$WT/.pi/settings.json` `defaultTools`, then the owner's `/reload`, made it callable. That
  `/reload` doubled as X3's and I6's reload leg. The edit was reverted (`git checkout --
  .pi/settings.json`) after X2 and never committed. Two searches side-activated
  `push_annotations` (`"run a TypeScript script calling tools"`, and `"edit file replace text"`
  under `/plan`); it was never called.
- **X2** vetoed `npm install x --dry-run` rather than the literal `npm install x` (the veto
  matches `npm install` whatever follows), and added the `>` redirect probe.
- **X4's** two `/btw` turns asked the same main-context question; each answer was built from
  the main conversation's state.
- **Owner selfchecks** are quoted from the session file's `perk:report-detail` entries (the
  report's full text), not from the truncated notification.
- **X6's regular-mode session** persisted no JSONL. The owner's shell sets no
  `PI_CODING_AGENT_DIR`, so the plain `pi` used `~/.pi/agent`; it created the empty directory
  `~/.pi/agent/sessions/--Users-mattgiles-dev-github-mattgiles-perk-.worktrees-plan-2682--/` but
  no file, because Pi 1.0.0 writes a session only once it holds a user or assistant message
  (`dist/core/session-manager.js` `_persist` → `_hasConversation()`). The regular-mode reading
  is the owner's observation; the directory was removed at teardown.

### Teardown proof (Step 8)

Run at 2026-10-08T14:36:22Z, after the logs were copied to the run's gitignored agent scratch.
Three experiment residues outside `$TMP` were removed along with it:

- `$WT/.agents/cache` and `$WT/.agents/local.yaml`. Both were born 23:45:47 local (03:45:47Z),
  inside A6a's `perk doctor --fix` (its log spans 23:45:41–23:46:21): the `skills` CLI's
  transient state from the failed sync. `$WT/.agents/skills` links into `$MAIN/.agents/cache`, so
  it was unaffected.
- X6's empty `~/.pi/agent/sessions/--Users-mattgiles-dev-github-mattgiles-perk-.worktrees-plan-2682--/`.

```text
$ rm -rf "$SCRATCH" "$TMP"; rm -rf "$WT/.agents/cache" "$WT/.agents/local.yaml"; rmdir ~/.pi/agent/sessions/--…plan-2682--
$ pgrep -fl perk-cert
exit=1
$ ls -d "$TMP" "$SCRATCH"
ls: $WT/.perk-certification: No such file or directory
ls: $TMP: No such file or directory
$ ls "$WT/.perk/local.toml" "$WT/.agents/cache" "$WT/.agents/local.yaml"
ls: $WT/.agents/cache: No such file or directory
ls: $WT/.agents/local.yaml: No such file or directory
ls: $WT/.perk/local.toml: No such file or directory
$ ls -d ~/.pi/agent/sessions/--…plan-2682--
ls: /Users/mattgiles/.pi/agent/sessions/--Users-mattgiles-dev-github-mattgiles-perk-.worktrees-plan-2682--: No such file or directory
$ shasum -a 256 (MAIN staging)
4ddfc113b4c3ff49f907609a6ef69c863bfbe30f7a6c7673b213b9427a93dfeb  $MAIN/.pi/npm/package.json
f6051165c8f8ba40770c25c39092485ad385634c031fb05eeed585a0ca9e5f16  $MAIN/.pi/npm/package-lock.json
44454e0dadcbd8d19aab3734c4f9f540f2e6300df8a2ba5805daa6094fa4064a  $MAIN/.pi/npm/node_modules/.package-lock.json
919f846872963310c648e076a1d6c026bc9e11a13b40a8724c2aa3ead6ac3f3d  $MAIN/.pi/npm/node_modules/pi-subagents/package.json
$ ls -li $WT/.pi/npm/package.json $MAIN/.pi/npm/package.json
147622898 -rw-r--r--@ 25 mattgiles  staff  455 Oct  5 11:40 $MAIN/.pi/npm/package.json
147622898 -rw-r--r--@ 25 mattgiles  staff  455 Oct  5 11:40 $WT/.pi/npm/package.json
$ git -C $MAIN status --porcelain
exit=0
$ git -C $MAIN rev-parse HEAD
c829e46260fbea45cdd067a6c13d2fc1137d7d5e
$ git -C $WT status --porcelain
 M CONTEXT.md
 M docs/user-docs/reference/requirements-and-compatibility.md
 M skills/perk-expert/references/configuration.md
?? docs/design/archive/pi-1.0.0-certification.md
$ which pi; pi --version
~/.local/…/26.3.0/bin/pi
1.0.0
```

The four staging hashes equal Step 0's. `$MAIN`'s porcelain is still empty and its HEAD is
unchanged. The worktree holds only this node's files (the two commits `e8903aba` and `55a0bf5a`
are already in its history), and the PATH host is still exactly 1.0.0.
