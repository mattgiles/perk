# Characterization: published Pi 1.1.0 + pi-subagents 0.76.1 against perk 4.0.0

**Status:** dated evidence record. Measured 2026-10-09 (16:11–16:25Z); authored 2026-10-09. It
characterizes perk 4.0.0 at revision `8eefff4d308b4d2794a3e6761036015e4e76d391` against the
**published** pair **Pi exact 1.1.0 + pi-subagents exact 0.76.1** in a throwaway detached
worktree, `$MAIN/.worktrees/pi-1.1.0-characterization` (removed at teardown). It implements plan
#2708 (Objective #2707, node 1.1). The precedents are
[`pi-1.0.0-characterization.md`](pi-1.0.0-characterization.md) (its shape and its probe/watchdog,
reused byte-for-byte) and [`docs/developers/pi-subagents-reverify.md`](../../developers/pi-subagents-reverify.md).

**Verdict: characterization complete. 62 counted ledger rows: 34 PASS / 1 FAIL / 3 REPRODUCED /
24 OBSERVED / 0 UNOBSERVED** (D5a, S14 and S15 restate a measured row and are listed by
reference, not counted).

- **No phase-gate blocker.** T9 (perk loads on 1.1.0 with 0.76.1; the native-SDK bridge installs)
  and T10a (0.76.1 launches a background child on 1.1.0) both PASS, and the child completes `OK`
  (T10b). 1.2's premise (perk on the 1.1.0 SDK) and 1.3's premise (0.76.1 on the 1.1.0 host) hold.
- **1.2 lockfile preview (D1).** Pi 1.1.0 ships no `npm-shrinkwrap.json`, so npm dedupes the
  former nested tree: `added 12 packages, removed 134 packages, and changed 29 packages`;
  `package-lock.json` 11642 → 9852 lines, 758 → 636 entries, 175 entries differ — 8
  `@earendil-works/*` top-level (3 added: `chord`, `pi-codemode`, `pi-mcp`; 5 moved to 1.1.0), 134
  nested pi-coding-agent entries removed (every nested `@earendil-works/*` copy among them),
  24 non-Pi top-level version moves (17 forced by the edited lockfile's own declarations — incl.
  `@anthropic-ai/sdk` 0.129.0 and `undici` 8.10.2, pinned exact by pi-ai / pi-coding-agent — and
  7 revertable), 9 top-level additions hoisted from the removed nested tree. `hasShrinkwrap` is
  gone, no `@earendil-works/*` nested copy remains (a 12-entry non-Pi nested tree does), `npm ls`
  is clean, and `npm install --package-lock-only` is byte-identical.
- **1.3 census headline (T7, S8, T13).** The census drift guard passes against 0.76.1 on disk
  (`tests 32 / pass 32 / fail 0`): no `NATIVE_SDK_CENSUS` widening, no `BRIDGE_SCHEMA` bump.
  0.76.1's resolver finds every host alias at the top level (`"missing": []`). The two
  supplier-pin pytest assertions fail exactly as predicted (T8b, T8c) and the doctor stamp warns
  (T12a) — all three move with the pin in 1.3.
- **No pin moved and nothing landed.** Every `package.json`/`package-lock.json`/`.pi/settings.json`
  edit was a throwaway edit inside the detached worktree, on an independent copy of `.pi/npm`;
  both were deleted at teardown. The main checkout's supplier staging hashes are identical at
  Step 0, after the swap and after teardown, and its `git status --porcelain` still shows only
  the untracked ledger seed. This PR adds this file and the ledger copy
  (`docs/planning/pre-pi-durable-true-up.md`) and nothing else.
- **The fix list 1.1.0 forces on 1.2 is two lines** (T1): `emitSettled` in
  `extension/pi/v1/delivery/commitCompact.test.ts:71` and `extension/pi/v1/draftCompact.test.ts:51`
  emits `{ type: "agent_settled" }` without the now-required `aborted` (TS2345). Everything else is
  green: Biome, ruff, ty, both other tsc projects, the full node:test glob (3796/3796, real
  codemode and the real worker entry on the 1.1.0 SDK) and pytest apart from the two predicted
  pin assertions. 1.2's fallout sweep also corrects the stale `toolGating.ts` header (D3).
- **Headless exit (T10c) and wake (T10d), facts only.** Both completed spawn legs exited 0 (14 s,
  8 s) without the watchdog; the X1 exit pair printed once each. The completion notice was
  followed by the user message `Subagent updates above.` and a started turn that produced no
  assistant message before the print-mode parent exited.

Measured rows and source-derived statements are kept separate throughout. A **measured** row
quotes a command run in this experiment. A **source-derived** statement cites
`<path>@abe508e1` (Pi, the `Release v1.1.0` commit `abe508e1b89912adde45528136c3221eb69acdd7` in
the pi-source mirror, whose fetched tags stop at `v1.0.3`) or `<path>@7d072b91` (pi-subagents,
`7d072b91dca7e1aa915282f0159cec0175d65efa` = the npm `gitHead` of 0.76.1), with an installed-dist
`grep -n` witness from the throwaway. Every repair design below is source-derived and **NOT
MEASURED**.

**Path abbreviations in quotes:** `$MAIN` = `/Users/mattgiles/dev/github/mattgiles/perk`.
`$IMPL` = `$MAIN/.worktrees/plan-2708` (the implement worktree). `$WT` =
`$MAIN/.worktrees/pi-1.1.0-characterization`. `$SCRATCH` = `$WT/.perk-characterization`.
`$AUTHED` = `/var/folders/90/b55dzd451137c93rcngpgdh00000gp/T/perk-pi11-authed.PfenkbdQy1` and
`$HERMETIC` = `…/T/perk-pi11-hermetic.SK59csCyrj` (the two throwaway agent dirs). `$PIMIRROR` =
`$MAIN/docs/library/source-code/github.com/earendil-works/pi`; `$SAMIRROR` =
`$MAIN/docs/library/source-code/github.com/nicobailon/pi-subagents`. Apart from these
substitutions, quotes are verbatim.

## Snapshot matrix

| Component | Version / value | Provenance |
|---|---|---|
| perk | 4.0.0 @ `8eefff4d` (the throwaway was detached at `$IMPL`'s HEAD) | `git -C $WT rev-parse HEAD`; `uv run perk --version` → `perk 4.0.0` |
| Dev pins (throwaway only) | `@earendil-works/{pi-agent-core,pi-ai,pi-coding-agent,pi-tui}` **1.1.0** exact; `typebox` 1.3.27, `typescript` 6.0.3 unchanged | `npm install --save-dev --save-exact …@1.1.0` (`git diff -- package.json`: the four lines `1.0.0` → `1.1.0`) |
| Root on-disk, top-level | `chord`, `pi-agent-core`, `pi-ai`, `pi-codemode`, `pi-coding-agent`, `pi-mcp`, `pi-telemetry`, `pi-tui` — **all 1.1.0** | each `node_modules/@earendil-works/*/package.json` `version` |
| Root on-disk, nested | `pi-coding-agent/node_modules/@earendil-works/` **absent**; `pi-coding-agent/npm-shrinkwrap.json` **absent**; 12 non-Pi nested entries remain (`@silvia-odwyer/photon-node` 0.3.4, `chalk` 6.0.0, `graceful-fs` 4.2.11, `grok-mermaid` 0.2.3, `highlight.js` 10.7.3, `hosted-git-info` 9.0.3, `ignore` 7.0.8, `jiti` 2.7.0, `minimatch` 10.2.6, `proper-lockfile` 4.1.2 (+ its nested `retry` 0.12.0), `signal-exit` 3.0.7) | `ls`, lockfile keys under `…/pi-coding-agent/node_modules/` (146 at HEAD → 12) |
| **Resolved CLI** | **1.1.0**, `$WT/node_modules/.bin/pi` → `$WT/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js` | `which pi`, `readlink -f "$(which pi)"`, `pi --version` (PATH-prefixed; also inside each scrubbed launch env) |
| **Resolved SDK** | **1.1.0**, `$WT/node_modules/@earendil-works/pi-coding-agent/package.json`; selfcheck `host: $WT/node_modules/@earendil-works/pi-coding-agent/dist/index.js`, `host sdk: 1.1.0 (floor >= 1.0.0)` | on-disk `package.json`; T9 census |
| **Worker SDK** | **1.1.0**: from `$WT/extension`, `import.meta.resolve('@earendil-works/pi-coding-agent')` → `file://$WT/node_modules/@earendil-works/pi-coding-agent/dist/index.js`; that package's `"version": "1.1.0"`. Behavioural witness: T6i `ok 3762 - e2e: the real worker entry admits the installed SDK and drives to completion, …` | Step 1.5 instrument (the worker's bare SDK specifiers live in `extension/substrate/hostSdkVersion.ts:14` and `extension/worker/sdkAdapter.ts:37`, both under `extension/`) |
| **Supplier** | pi-subagents **0.76.1**, `$WT/.pi/npm/node_modules/pi-subagents/package.json` (`pi.extensions: ["./index.js"]`, keyword `extension`); its install also added `@js-temporal/polyfill` 0.5.1 + `jsbi` 4.3.2 (`added 3 packages`) | `grep '"version"'` after `rm -rf` + `npm install pi-subagents@0.76.1 --prefix .pi/npm --legacy-peer-deps`; lockfile diff vs `$MAIN/.pi/npm/package-lock.json` |
| `pi` on PATH (outside the throwaway shell) | **1.0.0**, `~/.local/share/mise/installs/node/26.3.0/bin/pi` → `…/lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js` | Step 0.3 `which pi`, `readlink -f`, `pi --version` |
| `node` | v26.3.0 | `node --version` |
| `$MODEL` (lane model, every spawn leg) | `anthropic/claude-opus-5-5` | `$PI_PROVIDER/$PI_MODEL` of the implement session, read at Step 0 before any scrub |
| Auth preflight | `{"openai": "api_key", "anthropic": "api_key"}` — `$MODEL`'s provider is an `api_key` entry; `$AUTHED/auth.json` copied at 16:22:38Z, after the offline tier | `jq 'map_values(.type)' "$MAIN/.pi/agent/auth.json"` (types only) |
| `.pi/npm` independence | MAIN `package.json` inode 147622898 (link count 27 — hardlink-shared with materialized worktrees), copy inode 468905007 (link count 1); `package-lock.json` 147622913 (27) vs 468905006 (1) | `ls -li` after `cp -R` |
| MAIN staging hashes (Step 0, after the 0.76.1 swap, after teardown: all three identical) | `package.json` `d4f22073…49637b9`; `package-lock.json` `85c7e5a5…22ab2f50`; `node_modules/.package-lock.json` `ae5ba99e…a77302`; `node_modules/pi-subagents/package.json` `919f8468…ac3f3d` (MAIN pi-subagents stays 0.75.0) | `shasum -a 256` at Step 0.4, Step 1.10, Step 7 |
| Ledger seed | `$MAIN/docs/planning/pre-pi-durable-true-up.md`, 467 lines, SHA-256 `977e10d6104049953071b3cd8dbe2ad692e8f51766c82da42a11f71b04f54ea4` | `shasum -a 256`, `wc -l` at Step 0.4 |
| npm registry (Step 0, 2026-10-09T16:11Z) | pi-coding-agent versions end `1.0.2, 1.0.3, 1.0.4, 1.1.0`, `latest` 1.1.0; `@1.1.0` `_hasShrinkwrap = false`, `engines.node = '>=22.19.0'`, `time.modified = '2026-10-07T22:16:27.157Z'`; pi-subagents versions end `0.76.0, 0.76.1`, `latest` 0.76.1, `@0.76.1` `gitHead` `7d072b91dca7e1aa915282f0159cec0175d65efa`, peers `typebox *`, `pi-ai >=0.86.1`, `pi-tui *`, `pi-agent-core *`, `pi-coding-agent *` | `npm view …` |
| npm registry (authoring, 2026-10-09T16:28Z) | unchanged: pi-coding-agent `latest` 1.1.0, pi-subagents `latest` 0.76.1 — no newer release than the subjects | `npm view … dist-tags` |
| Mirror SHAs | `$PIMIRROR`: `abe508e1 Release v1.1.0` (`packages/coding-agent/package.json` `"version": "1.1.0"`), `v1.0.0` = `a13d35a7…`; `$SAMIRROR`: `7d072b91 chore(release): v0.76.1` (`"version": "0.76.1"`), `ad56bf92 chore(release): v0.75.0` | `git log --oneline -1`, `git show <sha>:<path>`; no refresh |

The subjects stayed **exact 1.1.0** and **exact 0.76.1**; no newer release appeared during the
experiment.

## Offline evidence (T1–T8f)

All ran in the PATH-prefixed throwaway shell (`which pi` = `$WT/node_modules/.bin/pi`,
`pi --version` = `1.1.0`, recorded in the T1 and T8a logs). The baseline (provenance) invocation —
the same command in `$IMPL` at HEAD on the 1.0.0 pins and PATH 1.0.0 — was run for T1 (exit 0) and
for the doctor rows (T12d); no other offline row failed.

| Row | Command | Verbatim summary | Verdict → owner |
|---|---|---|---|
| T1 | `npm run typecheck` | `extension/pi/v1/delivery/commitCompact.test.ts(71,40): error TS2345: Argument of type '{ type: "agent_settled"; }' is not assignable to parameter of type 'RunnerEmitEvent'.` / `  Property 'aborted' is missing in type '{ type: "agent_settled"; }' but required in type 'AgentSettledEvent'.` and the identical pair for `extension/pi/v1/draftCompact.test.ts(51,40)`; `exit=2`. No other diagnostic (no `ToolLoadout`, renderer or `tool_execution_end` error). Baseline in `$IMPL` (1.0.0): `> tsc --noEmit` … `exit=0` | FAIL → 1.2 |
| T2 | `npm run prose-review:typecheck` | `> perk-prose-review@0.0.0 typecheck` / `> tsc --noEmit` … `exit=0` | PASS → no-action |
| T3 | `npm run docs:typecheck` | `astro sync && tsc --noEmit` … `[types] Generated 1.79s` … `exit=0`. The one `[WARN] [astro-expressive-code] … language "gitignore"` line is content, not Pi | PASS → no-action |
| T4 | `just typecheck-py` | `uv run ty check` / `All checks passed!` / `exit=0` | PASS → no-action |
| T5 | `just lint` | `All checks passed!` (ruff) / `Checked 505 files in 315ms. No fixes applied.` (Biome) / `exit=0` | PASS → no-action |
| T6a | the `just test-js` line with paired reporters (methodology) | `# tests 3796` / `# suites 0` / `# pass 3796` / `# fail 0` / `# cancelled 0` / `# skipped 0` / `# todo 0`; `exit=0` (200 s). No failing test, so no `T6x<k>` row | PASS → no-action |
| T6b | TAP, `bareImportGuard` | `ok 295 - production extension sources import only node:/relative/host specifiers (zero bare npm deps)`; `ok 296 - synthetic positive: fabricated bare imports (static, side-effect, dynamic, require) are flagged` | PASS → no-action |
| T6c | TAP, `piAiCompatGuard` | `ok 2231 - the SDK-resolved pi-ai exports ./compat (unpinned pi-web-access imports it)` — with no nested pi-ai at 1.1.0, the guard read the top-level copy | PASS → no-action |
| T6d | TAP, `hostAdmission` | `ok 2788 - precondition: the installed SDK this suite runs on is admitted by the shipped floor` | PASS → no-action |
| T6e | TAP, `nativeSdkBridge` census guard (in-suite) | `ok 2881 - census drift guard: the installed consumers import exactly NATIVE_SDK_CENSUS` | PASS → no-action |
| T6f | TAP, `restorationWindow` | `ok 2971 - the window after /reload (A): …`, `ok 2972 - a /tree restore inside the window (A): …`, `ok 2973 - a sendMessage-triggered turn inside the window (A): …` | PASS → no-action |
| T6g | TAP, `discoveryPilot` | all 13: `ok 2737 - cohort join (A): …` through `ok 2749 - converged seed (A): …` (incl. `ok 2738 - reload (A): a real /reload re-runs the factory …`) | PASS → no-action |
| T6h | TAP, `perkToolSeam` real codemode script | `ok 815 - a real codemode script: an action soft failure rejects (catchable), an action success resolves to text, a query soft failure resolves to its structured value` | PASS → no-action |
| T6i | TAP, `stageExecutionE2e` | `ok 3762 - e2e: the real worker entry admits the installed SDK and drives to completion, independent of PATH and the CLI stamp`; real-codemode cases `ok 3766 - e2e: MODEL-TOOL nested — …`, `ok 3767 - e2e: CODEMODE classify across the cap …`, `ok 3768 - e2e: mid-script EXTERNAL abort …`, `ok 3769 - e2e: mid-script WALL-CLOCK exhaustion …`, `ok 3770 - e2e: queued concurrency after an abort …`, `ok 3771 - e2e: PRODUCTION SHAPE — the worker's own builtin codemode (models:WORKER_CODEMODE_MODELS) + the typed refusal; refusals are non-terminal` | PASS → no-action |
| T6j | TAP, `hostSdk` | `ok 2795 - hostSdkNamespaces: the captured values are this process's own instances` (and `ok 2794 - hostSdkNamespaces: exactly the census keys, each a namespace with ≥ 1 export`) | PASS → no-action |
| T7 | `node --test extension/substrate/nativeSdkBridge.test.ts` (0.76.1 on disk) | `✔ census drift guard: the installed consumers import exactly NATIVE_SDK_CENSUS (203.268458ms)`; `ℹ tests 32` / `ℹ pass 32` / `ℹ fail 0` / `ℹ cancelled 0` / `ℹ skipped 0`; `exit=0` | PASS → 1.3 |
| T8a | `uv run pytest -rfEs` (PATH-prefixed, `PI_SUBAGENTS_TEMP_ROOT` exported) | `============ 2 failed, 8361 passed, 1 skipped in 111.43s (0:01:51) =============`; the two failures are exactly T8b and T8c, the skip is T8d. No `T8x<k>` row | PASS → no-action |
| T8b | `tests/test_native_sdk_bridge_live.py::test_the_installed_pi_subagents_is_the_managed_pin` | `FAILED`: ``AssertionError: $WT/.pi/npm/node_modules/pi-subagents/package.json is pi-subagents 0.76.1, not the managed pin npm:pi-subagents@0.75.0 — run `perk init` (or `pi install`) in the main checkout to converge the install`` / `assert '0.76.1' == '0.75.0'` | REPRODUCED → 1.3 |
| T8c | `::test_real_pi_selfcheck_reports_the_bridge_installed_and_both_consumers_loaded` | `FAILED` at the trailing assertion (`tests/test_native_sdk_bridge_live.py:144`): `assert 'npm:pi-subagents@0.75.0=' in '    per source: ..=37 (40160c); builtin=5 (3327c); npm:@ff-labs/pi-fff=2 (3134c); npm:@juicesharp/rpiv-ask-user-question=1 (3761c); npm:@juicesharp/rpiv-todo=1 (1936c); npm:pi-subagents@0.76.1=3 (5248c); npm:pi-web-access=1 (314c)'`. The earlier assertions (exit 0, `bridge=installed`, both consumer roots, ≥ 1 tool per consumer, no `Failed to load extension`) passed to reach it | REPRODUCED → 1.3 |
| T8d | `::test_a_below_floor_real_pi_refuses_to_load_perk` | `SKIPPED [1] tests/test_native_sdk_bridge_live.py:152: needs a below-floor PATH pi (this one is admitted)` | OBSERVED → no-action |
| T8e | `tests/test_packaging.py::test_pi_toolchain_pin_lockstep` | `PASSED` at the 1.1.0 pins | PASS → no-action |
| T8f | `tests/test_pi_host.py::test_the_dev_pin_satisfies_the_floor_and_the_cli_is_admitted_independently` + `tests/test_workflow_artifacts.py::test_remote_pi_version_is_a_release_at_or_above_the_floor` | both `PASSED` | PASS → no-action |

T8b–T8f are the targeted re-run `uv run pytest -v -n0 -rfEs <six node ids>`:
`==================== 2 failed, 3 passed, 1 skipped in 1.61s ====================`.

**T1: what the two diagnostics are.** Both are the same test helper,
`async function emitSettled(h: PerkSession): Promise<void> { await
h.session.extensionRunner.emit({ type: "agent_settled" }); }`, which fires the real one-shot
settle hook. At 1.1.0 `AgentSettledEvent` requires `aborted: boolean`
(`packages/coding-agent/src/core/extensions/types.ts@abe508e1:1005–1009`). Under node:test's type
stripping both suites still pass (T6a), because perk's `agent_settled` listeners ignore the
payload. `extension/worker/sdkAdapter.test.ts:239` (`translateEvent({ type: "agent_settled" })`)
does not fail, because `translateEvent` takes perk's own `DriveEvent` shape.

## Live evidence

### Ledger (T9–T13)

| Row | Procedure (host / env) | Observation (verbatim quotes follow the table) | Verdict → owner |
|---|---|---|---|
| T9 | 1.1.0, hermetic, `pi --approve --mode json -p /perk-selfcheck` | exit 0 in 1 s; `bridge=installed`; `npm:pi-subagents@0.76.1=3 (5248c)`; `host: $WT/node_modules/@earendil-works/pi-coding-agent/dist/index.js`; `host sdk: 1.1.0 (floor >= 1.0.0)`; both roots under `$WT/.pi/npm/node_modules/`; `tools: 50 active / 66 registered`; 0 `Failed to load extension` (stdout and stderr) | PASS → 1.2 |
| T10a | 1.1.0, authed, `run-bounded.sh … pi --approve --mode json -e $SCRATCH/probe-spawn.ts -p "/probe-spawn script $MODEL"` | `ping` `"success": true` (methods `ping, status, manage, spawn, steer, interrupt, stop, resume, cost`); spawn `"success": true`, handle `ddb3d9d1-4f86-4652-8df1-312ae44c31ff`, `scriptDigest` `5dc0a658…6189e` (identical to the 1.0.0 record's B5 — same probe, same script); runner-start witness: child dir `84ef72f3-78ff-4c0c-afad-80c644b5247e` with `status.json` (`pid` 74650, `processTerminal.runnerProcessInstanceId` `db9cdcd0-821b-4d28-b036-de48622575c4`, runner `exitCode: 0`) and runner logs; no refusal, alias, version-change or auth text anywhere in the log | PASS → 1.3 |
| T10b | same launch: the child | lane `{"key": "probe", "ok": true, "error": null, "report": null}`; workflow `state: "complete"`; child `status.json` `state: "complete"`, step `model: "anthropic/claude-opus-5-5"`, `durationMs: 9002`; recovery descriptor `"modelOrigin": "explicit"`; `output-0.log` ends `OK` | PASS → 1.3 |
| T10c | same launch: print-mode exit | `exit=0 elapsed=14s`; no `watchdog:` line (the watchdog did not fire); the X1 pair printed exactly once each (`turn_end could not resolve the persisted assistant entry ID` ×1, `This extension ctx is stale …` ×1), after the last JSON event. T11 (same shape): `exit=0 elapsed=8s`, X1 ×1, no watchdog | OBSERVED → 2.4 |
| T10d | same launch: wake delivery | Event order on stdout: `custom subagent-incremental-child-notify` (`Workflow child completed: **probe**` …) → `custom subagent-notify` (`Background task completed: **workflow**` …) → `agent_start` → `turn_start` → `system` message → **user message `Subagent updates above.`** → `custom perk:agent-scratch` → no further JSON event (no assistant `message_start`, no `turn_end`/`agent_end`). The persisted session holds `custom_message subagent-incremental-child-notify`, `custom_message subagent-notify`, `message system`, `message user "Subagent updates above."`, `custom_message perk:agent-scratch` and **no assistant entry**. T11 shows the same sequence | OBSERVED → 2.2 |
| T11 | as T10 with `… $MODEL restricted` | child `daf48258-b903-4660-bf3f-4f5c894520cb` launched (`pid` 75262, runner `cb5f8579-3c0d-43ff-8936-ad506c853c0e`, exit 0) and completed `ok: true`, step `durationMs: 3403` (workflow trace 4553 ms); recovery descriptor carries `"extensionBindings": {"perk.parent-restrictions/1": {"readOnly": true}}`, `launchResolvedExtensions.effective: ["sha256:76d80921221130b3"]`; `output-0.log` (1628 bytes) shows `[READ-ONLY MODE] (unscoped)` before `OK`; no trust diagnostic | OBSERVED → 2.2 |
| T12a | `uv run perk doctor --verbose` (+ `--json`), the throwaway's perk 4.0.0, PATH-prefixed | `⚠ subagent-compat: pi-subagents 0.76.1 installed — perk's guidance was verified against 0.75.0 — npm:pi-subagents@0.75.0 is the settings pin (settings-wiring); mechanics perk's guidance leans on are source-read-derived at the verified version and unverified at the installed one` | REPRODUCED → 1.3 |
| T12b | same run: `settings-wiring` + `artifact-health` | `✗ settings-wiring: settings-wiring drift — .pi/settings.json: updated npm:pi-subagents@0.76.1 -> npm:pi-subagents@0.75.0; compaction: reserveTokens=65536` and `⚠ artifact-health: artifact health: 6 up-to-date, 1 locally-modified — .pi/settings.json (settings-wiring): locally-modified` | OBSERVED → no-action |
| T12c | same run: the `pi` row | `✓ pi: pi ok — 1.1.0 (floor >= 1.0.0)` (JSON: `"detail":"1.1.0 (floor >= 1.0.0)"`) — the PATH-prefixed 1.1.0 host, admitted | PASS → no-action |
| T12d | same run: every other non-green row | `✗ config: config missing — .perk/local.toml` (also red in the baseline doctor in `$IMPL`, whose only red it is: `✗ 1 check(s) failed`); `✗ skills-delivery: 32 perk skill(s) not delivered …`, `⚠ bindings: bindings: 27 problem(s) …`, `✗ workflow-dir: workflow-dir drift — .perk/workflow/: created` — throwaway-only, as in the 1.0.0 record's A12 note (a hand-made `git worktree add` never gets launch-time skill delivery or a converged workflow dir). No other red, so no `T12x<k>` row | OBSERVED → no-action |
| T13 | `grep -rl resolveHostPeerAliases …/pi-subagents/src`; `node $SCRATCH/resolver-probe.mjs <runner-aliases.js> <pi-coding-agent root>` | the export lives in `src/runs/background/runner-aliases.js` (also referenced from `async-execution.js` and the `.d.ts`); `"missing": []`; all 12 aliases resolve to **top-level** `$WT/node_modules/@earendil-works/*` / `$WT/node_modules/typebox` paths (no nested tree) | PASS → 1.3 |

### Verbatim quotes

**T9 selfcheck summary and census:**

```text
perk: perk-selfcheck — running…
perk: selfcheck — 4.0.0: ok; shared=ok; ambient=reached (append=5376c); agents=reached (files=1); bridge=installed
census:
  base-prompt: pi-default (not measured)
  append-system-prompt: 5376c
  context-files: 1 file(s), 7039c — $WT/AGENTS.md=7039c
  skills: 2 visible + 1 hidden; prompt-section=1260c
  tools: 50 active / 66 registered; schemas=57880c; guidelines=0c; snippets=4448c
    per source: ..=37 (40160c); builtin=5 (3327c); npm:@ff-labs/pi-fff=2 (3134c); npm:@juicesharp/rpiv-ask-user-question=1 (3761c); npm:@juicesharp/rpiv-todo=1 (1936c); npm:pi-subagents@0.76.1=3 (5248c); npm:pi-web-access=1 (314c)
  discovery: cohort (family: objective_stack_status, collect_review_wave, collect_draft_review_wave, push_annotations)
  branch: 4 entries; binding-header-copies=0
    perk contexts: none; other custom_message ×0 (0c)
  host sdk: 1.1.0 (floor >= 1.0.0)
  native sdk bridge: installed (roots=2, specifiers=8)
    host: $WT/node_modules/@earendil-works/pi-coding-agent/dist/index.js
    roots: 2 — $WT/.pi/npm/node_modules/pi-subagents, $WT/.pi/npm/node_modules/pi-web-access
```

**T10 probe env** (inside the launched process): `PI_CODING_AGENT_DIR: "$AUTHED"`,
`PERK_SKIP_VERSION_CHECK: "1"`, `PI_SUBAGENTS_TEMP_ROOT: "$SCRATCH/subagents-tmp"`,
`PI_CODING_AGENT: "true"`.

**T10a spawn reply (handle) and T10b status/lane row:**

```text
probe: spawn(script, anthropic/claude-opus-5-5) {
  "success": true,
  "data": {
    "text": "Run fan-out: 0/64 used, 64 remaining\nAsync workflow [ddb3d9d1-4f86-4652-8df1-312ae44c31ff]\n\nThe async run is detached. Do not run sleep timers or polling loops just to wait for it.\nThis is a non-interactive run: Pi auto-drains current-session subagent work at agent_end so detached children are not abandoned. …",
    "details": { "mode": "workflow", "runId": "ddb3d9d1-4f86-4652-8df1-312ae44c31ff",
      "asyncId": "ddb3d9d1-4f86-4652-8df1-312ae44c31ff",
      "asyncDir": "$SCRATCH/subagents-tmp/async-subagent-runs/ddb3d9d1-4f86-4652-8df1-312ae44c31ff",
      "workflow": { …, "scriptDigest": "5dc0a658d9dd1f46a29bf3987b42cc90ad635a09e8af476a785ac0c977d6189e" }, … } } }
probe: status { … "state": "complete", … "pid": 74538,
  "steps": [ { "agent": "perk.scout", "label": "probe", "status": "completed", "async": true,
    "runId": "84ef72f3-78ff-4c0c-afad-80c644b5247e", "durationMs": 10071 } ],
  "workflow": { "value": [ { "key": "probe", "ok": true, "error": null, "report": null } ], … },
  "totalCost": { "inputTokens": 4, "outputTokens": 4, "costUsd": 0.025581 }, … }
```

T10 child directory `async-subagent-runs/84ef72f3-78ff-4c0c-afad-80c644b5247e/`: `control`,
`events.jsonl`, `output-0.log`, `process-terminal-candidate.json`, `process-terminal.json`,
`recovery-descriptor.json`, `result-index`, `result-pending`, `run-fanout-budget.json`,
`runner.stderr.log` (0 bytes), `runner.stdout.log` (0 bytes), `status.json`,
`subagent-log-84ef72f3-78ff-4c0c-afad-80c644b5247e.md` — the same 13 entries as the 1.0.0 record's
C0/B5 child. The workflow directory `ddb3d9d1…/` holds `control`, `events.jsonl`,
`run-fanout-budget.json`, `status.json`, `workflow-children.jsonl`, `workflow-receipt.json`.
`output-0.log`:

```text
Task: Reply with exactly the single word OK and nothing else. Do not read any file.
OK
```

**T10c/T10d tail of the T10 log** (stderr, after the last JSON event; then the watchdog's line):

```text
Extension error (<boundary>): turn_end could not resolve the persisted assistant entry ID
Extension error ($WT/extension/index.ts): This extension ctx is stale after session replacement or reload. Do not use a captured pi or command ctx after ctx.newSession(), ctx.fork(), ctx.switchSession(), or ctx.reload(). For newSession, fork, and switchSession, move post-replacement work into withSession and use the ctx passed to withSession. For reload, do not use the old ctx after await ctx.reload().
exit=0 elapsed=14s
```

The completion notice (`subagent-notify`, `display: false`) read: `Background task completed:
**workflow**` / `Workflow receipt: $SCRATCH/subagents-tmp/async-subagent-runs/ddb3d9d1-…/workflow-receipt.json`
/ `Workflow completed with 1 child run(s). Return: [ { "key": "probe", "ok": true, "error": null,
"report": null } ] Trace: 2 event(s).` / … / `Child runs: probe=84ef72f3-… (completed)`. The wake
message that followed it: `{"type":"message_start","message":{"role":"user","content":[{"type":"text","text":"Subagent updates above."}],…}}`.

**T11 child transcript (`output-0.log`, 1628 bytes; T10's is 87 bytes):**

```text
Task: Reply with exactly the single word OK and nothing else. Do not read any file.
[READ-ONLY MODE] (unscoped)
You are in perk read-only mode — a structurally enforced exploration mode (not advisory):
- edit/write are blocked; bash is restricted to an allowlist of read-only commands.
…
Do not attempt to make changes.
OK
```

**T13, the host-alias census against the 1.1.0 root** (`<NM>` = `$WT/node_modules`):

```json
{
  "aliases": {
    "@earendil-works/pi-coding-agent": "<NM>/@earendil-works/pi-coding-agent/dist/index.js",
    "@earendil-works/pi-agent-core": "<NM>/@earendil-works/pi-agent-core/dist/index.js",
    "@earendil-works/pi-tui": "<NM>/@earendil-works/pi-tui/dist/index.js",
    "@earendil-works/pi-ai": "<NM>/@earendil-works/pi-ai/dist/compat.js",
    "@earendil-works/pi-ai/compat": "<NM>/@earendil-works/pi-ai/dist/compat.js",
    "@earendil-works/pi-ai/oauth": "<NM>/@earendil-works/pi-ai/dist/oauth.js",
    "@earendil-works/pi-ai/providers/all": "<NM>/@earendil-works/pi-ai/dist/providers/all.js",
    "typebox": "<NM>/typebox/build/index.mjs",
    "typebox/compile": "<NM>/typebox/build/compile/index.mjs",
    "typebox/value": "<NM>/typebox/build/value/index.mjs",
    "@earendil-works/chord": "<NM>/@earendil-works/chord/dist/index.js",
    "@earendil-works/chord/context": "<NM>/@earendil-works/chord/dist/context/index.js"
  },
  "missing": []
}
```

At 1.0.0 every alias but the root resolved under `pi-coding-agent/node_modules/` (1.0.0 record,
A10); at 1.1.0 every alias resolves to a deduped top-level copy.

### Notes on the unplanned and partial observations

- **T10c/T10d: a completed lane's print-mode exit on 1.1.0 + 0.76.1.** Measured: the parent
  exited 0 in 14 s (T10) and 8 s (T11) — the 1.0.0 record's B5/B6 took 23 s and 8 s — with the X1
  pair once, as on 0.99.2 and 1.0.0. New relative to that record: after the completion notice,
  0.76.1 steers the user message `Subagent updates above.`, a turn starts
  (`agent_start`/`turn_start`/system/user/perk's `perk:agent-scratch` injection), and the process
  exits with no assistant message on stdout or in the session file. **Not established:** whether
  that turn issued a provider request, why it produced no assistant entry, and whether the X1
  `turn_end` boundary error belongs to that turn. Attribution is 2.4's (and 2.2's for the wake).
- **T10/T11: perk minted run ids in the throwaway.** `PERK_RUN_ID` was scrubbed, so perk's
  extension minted its own (`[PERK AGENT SCRATCH run=01M4GQKFVR93RXE1KBW57JW3C6 …]`) and created
  `$WT/.perk/workflow/`; T12d's `workflow-dir` red reads that half-made directory. Throwaway-only.
- **T12c text.** perk 4.0.0's `pi` doctor row prints the version and floor
  (`1.1.0 (floor >= 1.0.0)`), not the resolved path the plan predicted; the path is the Step 1.7
  `which pi`.
- **T11 trust state.** Only `--approve` was exercised, as in the 1.0.0 record.

## Audit of the released delta

Each row: the fact with its release-commit citation, the installed-dist witness (`$WT/node_modules/@earendil-works/pi-coding-agent/dist/…` = `<D>`, `$WT/node_modules/@earendil-works/<pkg>/…` = `<NM>/<pkg>`, `$WT/.pi/npm/node_modules/pi-subagents/…` = `<SA>`), perk's assumption and anchor (read at `8eefff4d` in `$IMPL`, identical to the throwaway's tracked tree), one verdict, one owner. Every OBSERVED row that hands work to a node points at its repair design below.

### Pi 1.0.1 → 1.1.0

| Row | Pi fact (source-derived; dist witness) | perk assumption / anchor | Verdict → owner |
|---|---|---|---|
| D1 packaging | `packages/coding-agent/package.json@v1.0.0:38` `"npm-shrinkwrap.json"` (in `files`), `:48` `"shrinkwrap": "node ../../scripts/generate-coding-agent-shrinkwrap.mjs"`, `:49` `"prepublishOnly": "npm run clean && npm run build && npm run shrinkwrap"`; at `abe508e1:47` `"prepublishOnly": "npm run clean && npm run build"` and no `shrinkwrap`/`files` entry; `git ls-tree v1.0.0` lists `packages/coding-agent/npm-shrinkwrap.json`, `abe508e1` does not. `packages/coding-agent/CHANGELOG.md@abe508e1` § [1.0.1] `### Removed`: "Removed `npm-shrinkwrap.json` from the published package. npm installations no longer pin transitive dependencies, and library consumers can now override them." Registry `_hasShrinkwrap = false`. Dist: `<D>/../package.json:47` same `prepublishOnly`; `ls <D>/../npm-shrinkwrap.json` → `No such file or directory` | `package-lock.json:1517` `"hasShrinkwrap": true` (the installed 1.0.0). The Step 1.4 preview (header bullet; methodology) is the data | OBSERVED → 1.2 |
| D2 tool selectors vs child MCP registration | `core/sdk.ts@abe508e1:285–286` `const toolModifiers = options.tools?.some(isToolModifier) ? options.tools : undefined;` / `const selectedToolNames = toolModifiers ? applyToolModifiers(defaultToolNames, toolModifiers) : options.tools;`; `core/agent-session.ts@abe508e1:281–283` "A non-empty list without `mcp__` entries also keeps MCP tools registered for codemode and tool_search; only tool_search can declare them."; `:504–505` `_allowlistFiltersMcp = config.allowedToolNames.length === 0 \|\| config.allowedToolNames.some((entry) => entry.startsWith("mcp__"))`; `:1540` `return !this._allowlistFiltersMcp && isMcpToolName(name);`; `:1551` `return this._getToolExposure(name) !== "direct" && this._toolRegistry.has("tool_search");`; `:116` imports `createToolNameMatcher` (`*` patterns). These govern tools that **are registered**. Supplier: `src/runs/shared/child-session.ts@7d072b91:424–425` `const builtinMcpTools = launch.builtinMcpTools ?? []; const builtinMcp = builtinMcpTools.length ? selectedBuiltinMcpExtension(pi, builtinMcpTools) : undefined;`; `src/runs/shared/mcp-direct-tool-allowlist.ts@7d072b91:121` `if (selectors.length === 0) return { selections: [], unresolvedSelectors: [] };`. Dist: `<D>/core/sdk.js:151`, `<D>/core/agent-session.js:195` (`_allowlistFiltersMcp =`), `<SA>/src/runs/shared/child-session.js:325`, `<SA>/src/runs/shared/mcp-direct-tool-allowlist.js:29` | perk never passes `--tools`/`--exclude-tools` (non-test `src/perk extension`: only the `extension/substrate/toolGating.ts:63` comment "The exclusion contract: Pi's `--tools`/`--exclude-tools` …"); the 14 defs' `tools:` lists name no `mcp__`/`mcp:`/`codemode`/`tool_search`; `extension/waves` + `pi/v1/foregroundDelegation.ts` carry no `mcpDirectTools`/`builtinMcpTools`/`mcp:` → **a perk report child loads no native MCP extension on either Pi version** | OBSERVED → 2.3 |
| D3 loadout guidelines | `core/extensions/types.ts@abe508e1:556–557` "A tool's `promptGuidelines`. Hidden declarations leave them out of the system prompt." `getPromptGuidelines(name: string): readonly string[];`; `core/system-prompt.ts@abe508e1:150` `const declaredTools = selectedTools.filter((name) => !hiddenTools.includes(name));` (CHANGELOG § [1.0.4] Fixed: "`ToolLoadout` gains `getPromptGuidelines()`"). Dist: `<D>/core/extensions/types.d.ts:433`, `<D>/core/system-prompt.js:76`, `<D>/core/agent-session.js:1173` | `extension/substrate/toolGating.ts:23–24` "Hidden tools stay active and callable; their prompt snippets drop out of the request, their guidelines do not." — stale at 1.1.0. perk's `ToolLoadout` fakes are casts (`toolGating.test.ts:141,804` `as unknown as ToolLoadout`), so T1 shows no diagnostic | PASS → 1.2 |
| D4 codemode `only` | `extensions/codemode/tool.ts@abe508e1:373–376` `hiddenDeclarations: mode === "only" ? callable.filter((tool) => isDirect(tool) && declaredNames.has(tool.name)).map((tool) => tool.name) : []` — identical at `v1.0.0:358–361` (an interaction anchor, not a 1.1.0 delta). Dist: `<D>/extensions/codemode/tool.js:238` | `extension/substrate/toolPolicy.ts:441` `codemode: { gated: "blocked", registrar: "extension", suspendedUnderGate: true }`; the writers `plan_draft`, `objective_draft`, `objective_refinement_draft` are kind `action` → exposure `direct` | OBSERVED → 4.3 |
| D5a `agent_settled.aborted` required | `core/extensions/types.ts@abe508e1:1005–1009` `export interface AgentSettledEvent { type: "agent_settled"; /** Whether the run ended because it was aborted, for example with Escape. */ aborted: boolean; }` (absent at `v1.0.0`); CHANGELOG § [1.1.0] Added "Added `aborted` to `agent_settled` session, extension, and JSON events". Dist: `<D>/core/extensions/types.d.ts:780` | the two typed `emitSettled` fixtures | FAIL → 1.2 (= T1; listed by reference) |
| D5b renderer / `tool_execution_end` fields | `types.ts@abe508e1:496` `durationMs: number \| undefined;`, `:498` `outputPad: number;` (`ToolRenderContext`), `:1094` `durationMs?: number;` (`ToolExecutionEndEvent`). Dist: `<D>/core/extensions/types.d.ts:376,378,855` | perk renderers/consumers: `extension/worker/sdkAdapter.ts:243 translateEvent` (handles `turn_end`/`tool_execution_end`/`compaction_end`/`auto_retry_start`); no perk fixture constructs a `ToolRenderContext`. T1 has no diagnostic on them; T6a green | PASS → no-action |
| D5c cancellation translation | as D5a | perk's cancellation derives from its own signal/budget; `translateEvent` ignores `agent_settled`; `pi.on("agent_settled", async (_event, ctx) …)` in `extension/pi/v1/objective.ts:236` and `drivenCompaction.ts:126` ignore the payload | OBSERVED → 1.2 |
| D6a restoration window | `core/agent-session.ts@abe508e1:447` `private _pendingToolNames = new Set<string>();`, `:1524` `if (previous.some((name) => !active.has(name))) this._pendingToolNames.clear();`, `:3590` `nextActiveToolNames.push(...this._pendingToolNames);` — `git diff v1.0.0 abe508e1` changes **no** `_pendingToolNames` line (8 occurrences at both); the reload path now re-applies `defaultToolModifiers` (`:3667–3670` `applyToolModifiers(this.settingsManager.getDefaultTools() ?? DEFAULT_TOOL_NAMES, this._defaultToolModifiers)`). Dist: `<D>/core/agent-session.js:142,192` | perk's `defaultTools: ["+tool_search"]` (the modifier form) and the restoration-window repair; T6f + T6g green | PASS → no-action |
| D6b MCP lifecycle | `extensions/mcp/config.ts@abe508e1:145` `export function loadMcpConfig(options: { agentDir: string; cwd: string; projectTrusted: boolean })` with project overrides (`:9–10` "A project entry without `command`, `url`, or `type` overrides only `enabled`, `exposure`, and `toolExposure` …"); `runtime.ts@abe508e1:486` `await Promise.all([client?.close().catch(() => undefined), this.opening?.catch(() => undefined)]);`; `oauth.ts@abe508e1:51` `const OAUTH_REQUEST_TIMEOUT_MS = 15_000;`, `:229` `AbortSignal.timeout(OAUTH_REQUEST_TIMEOUT_MS)`; `index.ts@abe508e1:1249–1250` `pi.on("session_shutdown", async () => { session.abort();` (CHANGELOG § [1.1.0] Changed: "`pi mcp login --timeout` to limit the whole sign-in"). Dist: `<D>/extensions/mcp/config.js:105`, `runtime.js:407`, `oauth.js:166`, `index.js:1111–1112`; `<D>/extensions/mcp/cli.js:57` still prints `--timeout <seconds>     How long login waits for the browser (default: 300)` | perk has no MCP code; the worker supplies `createCodemodeExtension({ models: WORKER_CODEMODE_MODELS })` + `createToolSearchExtension()` only | OBSERVED → 5.2 |
| D7 `McpExtensionOptions` | `extensions/mcp/index.ts@abe508e1:69–90`: `loadConfig?: (ctx: ExtensionContext) => LoadedMcpConfig;`, `createTransport?: McpTransportFactory;`, `credentials?: McpOAuthCredentialStore;`, `logPath?: string;`, `openUrl?: (url: string) => void;`, `updateConfig?: (entry: McpServerEntry, patch: McpServerConfigPatch) => void;`, `startupWaitMs?: number;`; `src/index.ts@abe508e1:410` `export { createMcpExtension, type McpExtensionOptions, type McpTransportFactory } from "./extensions/mcp/index.ts";` — `McpOAuthCredentialStore` not root-exported. Dist: `<D>/index.d.ts:32` same export, `grep -c McpOAuthCredentialStore <D>/index.d.ts` = 0; `<D>/extensions/mcp/index.d.ts:35–54` the seven fields | perk imports none (WP5 is unbuilt) | OBSERVED → 5.1 |
| D8 Azure rename | `packages/ai/src/providers/azure.ts@abe508e1:46` `id: "azure",`; `packages/coding-agent/CHANGELOG.md@abe508e1` § [1.0.3] `### Breaking Changes`, verbatim: "Renamed the Azure provider from `azure-openai-responses` to `azure`. Rename the provider key in `auth.json` (or run `/login` again), in `models.json`, and in `settings.json` (`defaultProvider`, `enabledModels` patterns, and `modelThinkingLevels` keys). Sessions that used the old provider fall back to another model when resumed, and their prompt cache is not reused. The `AZURE_OPENAI_*` environment variables are unchanged". Dist: `<NM>/pi-ai/dist/providers/azure.js:36` | `rg -i azure src extension shared docs/user-docs skills/perk-expert` → 0 matches. This record is the documentation; no credential rewrite, no alias | PASS → no-action |
| D9 Node engines | `packages/coding-agent/package.json@abe508e1:106` `"node": ">=22.19.0"` (same at `v1.0.0:107`); installed `<D>/../package.json:106` same | `package.json:17` `"node": ">=22.19.0"`; `shared/host-floor.yaml` `node.min_version: "22.19.0"` | PASS → no-action |
| D10 codemode runtime | `extensions/codemode/execute.ts@abe508e1:274` `` `==> text ${index}/${total} <==` ``, `:278` `` `<console_output>\n…\n</console_output>` ``; `packages/codemode/src/runtime/prelude-source.ts@abe508e1:40–41` `MAX_OUTPUT_CHARS = 16 * 1024 * 1024` / `MAX_OUTPUT_ITEMS = 100_000`, `:28` "Before anything else the prelude freezes the built-ins and makes the built-in globals read-only."; `extensions/codemode/tool.ts@abe508e1:147` "`await searchTools(query, …)`, `await describeTool(name)`, `await describeNamespace(name)`". Dist: `<D>/extensions/codemode/execute.js:227,231`, `<NM>/pi-codemode/dist/runtime/prelude-source.js:40–41` | executable codemode consumers: `extension/pi/perkToolSeam.test.ts` (T6h) and the real-codemode cases in `extension/worker/stageExecutionE2e.test.ts` (T6i); wave scripts run in the supplier's workflow host, not Pi codemode | PASS → no-action |
| D11 export maps | installed `pi-agent-core` exports `. ./package.json`; `pi-ai` `. ./models ./compat ./providers/* ./api/* ./utils/* ./oauth ./bedrock-provider ./bun-oauth`; `chord` `. ./context ./delta ./bundler ./node ./package.json` (= `packages/{agent,ai}/package.json@abe508e1`) | `bareImportGuard` (T6b) and the 0.76.1 resolver (T13) | PASS → no-action |
| D12 sweep | Released 1.0.1–1.1.0 items with no perk surface (`packages/coding-agent/CHANGELOG.md@abe508e1`): OSC 7501 program status (`PI_PROGRAM_STATUS`); Claude Haiku 5.5; GPT-6 Luna / llama.cpp decision models / Cloudflare Clef classifiers and codemode `models.classify()` images; `samplingParamsByThinkingLevel`; the Nix flake; `pi update` managed installs keeping two releases; `.env` loading in standalone binaries; MCP CIMD client registration (`oauth.clientRegistration: "cimd"`; and `packages/mcp/CHANGELOG.md@abe508e1` § [1.0.1] Breaking: `OAuthClientProvider.clientMetadataUrl` → `clientMetadataDocument(metadata)`); `pi.registerToolRenderer()`; Anthropic inline tool definitions; the `brace-expansion` 5.0.12 pin; codemode images saved to files / `tools.read()` image blocks; `Home`/`End` keys; provider retries (`server_busy`, capacity, Mistral, Bedrock); TUI/terminal/Herdr/Termux/Kitty fixes; the pnpm restart hint; the 3.5-chars/token estimate; `/mcp` live manager; `outputPad` on `!` output | perk has no surface for any of them (no provider, TUI-terminal, MCP or managed-install code) | OBSERVED → no-action |
| D13 pi-ai: stream functions | `packages/ai/CHANGELOG.md@abe508e1` § [1.1.0] `### Breaking Changes`: "A stream function must return an `AssistantMessageEventStream`, for example from `createAssistantMessageEventStream()`; a hand-written `EventStream<AssistantMessageEvent, AssistantMessage>` subclass no longer type-checks in its place" | perk writes no stream function: `rg AssistantMessageEventStream\|createAssistantMessageEventStream\|extends EventStream` over `extension src tools packages docs/site/src` → 0; its faux models come from pi-ai's own faux provider (`btw.test.ts`); T1 has no such diagnostic | PASS → no-action |
| D14 pi-tui: `Terminal.setProgramStatus` | `packages/tui/CHANGELOG.md@abe508e1` § [1.1.0] `### Breaking Changes`: "`Terminal` implementations must provide `setProgramStatus(status)`; a terminal without OSC 7501 support can implement it as a no-op" | perk implements no `Terminal` (`rg 'implements Terminal\|setProgramStatus'` → 0); T1 green on it | PASS → no-action |

The `packages/{agent,ai,tui}` changelogs' Breaking Changes between the 1.0.0 and 1.1.0 release
commits contain exactly three items: the pi-ai stream-function rule (D13), the pi-ai Azure rename
(1.0.3; = D8, `azureProvider`/`AZURE_MODELS` from `providers/azure`), and the pi-tui `Terminal`
method (D14). `packages/agent/CHANGELOG.md` has none (1.1.0 adds `durationMs` to tool results and
`tool_execution_end`). `packages/codemode` and `packages/mcp` were scanned too: the codemode items
are D10's; the mcp 1.0.1 breaking change is in D12.

### pi-subagents 0.75.0 → 0.76.1

Source: `CHANGELOG.md@7d072b91` § [0.76.1] (2026-10-05) and § [0.76.0] (2026-10-04).

| Row | Supplier fact (source-derived; dist witness) | perk assumption / anchor | Verdict → owner |
|---|---|---|---|
| S1 headless completion delivery | `src/extension/index.ts@7d072b91:811` `if (!ctx.hasUI) await drainOutstandingWork({ state, events: pi.events, hasPendingSupervisorRequest: supervisorChannel.hasPendingRequests }).then(resultWatcher.deliverPendingResults);` (0.76.0 Fixed: "Finished results are now handed to Pi before the turn ends, and Pi runs the completion turn next"). Dist: `<SA>/src/extension/index.js:719`. Measured by T10c (and the spawn reply's "Pi auto-drains current-session subagent work at agent_end") | perk's headless report waves (#2660's reproduction) | OBSERVED → 2.4 |
| S2 wake prompt | `src/shared/parent-wake.ts@7d072b91:3` `export const PARENT_WAKE_TEXT = "Subagent updates above.";`, `:43` `pi.sendMessage(message, { triggerTurn: false });`, `:47` `pi.sendUserMessage(PARENT_WAKE_TEXT, { deliverAs: "steer" });` (0.76.1 Fixed, #2688). Dist: `<SA>/src/shared/parent-wake.js:1`. Measured by T10d | perk's collection rule ("only the matching workflow-completion notice authorizes collection") is model-read prose | OBSERVED → 2.2 |
| S3 queued-completion liveness across reload | `src/runs/background/notify.ts@7d072b91:155` `hasPendingDelivery(): boolean;`, `:159` `bindSession(…)`, `:611–613` `queuedWakesSymbol = Symbol.for("pi-subagents.queued-completion-wakes.v2")` on `globalThis` (a process-global `WeakMap`), `:922` `hasPendingDelivery: () => pending.size > 0 \|\| unstartedWakes.length > 0`. Dist: `<SA>/src/runs/background/notify.js` (`hasPendingDelivery`) | `extension/waves/reportWave.ts:639` `const records = new WeakMap<ReportWaveRef, PendingRecord>();` — per-activation records; no collection across reload | OBSERVED → 2.2 |
| S4 in-process version-change refusal | `index.ts@7d072b91:15` `` throw new Error(`pi-subagents ${installedVersion} is installed, but this Pi process still has ${loadedPackageVersion} loaded. Restart Pi to load the update; /reload cannot replace extension modules that Node has already loaded.`); `` Dist: `<SA>/index.js:11`. Never triggered here: no Pi process spanned the swap | perk's supplier install path (`perk init` / Pi's package install) | OBSERVED → 1.3 |
| S5 bare `ModelRuntime.create()`, `getAgentDir()`, env inheritance, detached runners | `src/runs/shared/child-session.ts@7d072b91:414` `runtime ??= pi.ModelRuntime.create()…`, `:427–428` `? await pi.ModelRuntime.create() : await sharedRuntime(pi);`, `:429` `const agentDir = getAgentDir();`; `src/runs/background/async-execution.ts@7d072b91:737` `...omitGitRoutingEnv(omitExtensionBindingsEnv(process.env)),`, `:750` `...backgroundProcessOptions(),`, `:866` `proc.unref();`; `src/runs/shared/background-process-options.ts@7d072b91:6` `detached: platform !== "win32",`. Dist: `<SA>/src/runs/shared/child-session.js:314,327,329`, `<SA>/src/runs/background/async-execution.js:486,617`, `<SA>/src/runs/shared/background-process-options.js:3` | the seed's WP5 `PI_CODING_AGENT_DIR` override + explicit `ModelRuntime.create({authPath, modelsPath})` | OBSERVED → 5.1 |
| S6 `parseFrontmatterList` | `src/agents/frontmatter.ts@7d072b91:46–47` `export function parseFrontmatterList(raw: string \| undefined): string[] \| undefined { if (raw === undefined) return undefined;` … `:56` `.filter(Boolean);` → a blank value `[]`, a literal `[]` `["[]"]`; `src/runs/shared/capability-ceiling.ts@7d072b91:66` `normalizeCapabilityCeilingAllowedAgents`, `:90` `normalizeList("allowedAgents", /^[A-Za-z0-9_.:-]+$/u)` (`[]` fails it). Dist: `<SA>/src/agents/frontmatter.js:43` | 14 defs, none carries `allowedAgents` (`grep -l allowedAgents agents/*.md .pi/agents/perk-dev/*.md` → 0) | OBSERVED → 2.1 |
| S7 RPC spawn key | `src/extension/rpc.ts@7d072b91:523` `function spawnParams(…)`, `:525` `if (Object.hasOwn(input, "workflowScript")) throw new SubagentRpcError("invalid_params", "RPC spawn workflowScript was removed; pass inline script text as script.");`, `:526` the same for `workflowScriptPath` ("pass the file as workflow: …"). Dist: `<SA>/src/extension/rpc.js:378,380`. Measured by T10a (`script` accepted) | `extension/testing/fakeSubagents.ts:152` rejects only `workflowScript` (note for 2.2's fakes) | PASS → no-action |
| S8 SDK import census | the eight `NATIVE_SDK_CENSUS` specifiers (`extension/substrate/nativeSdkBridge.ts:27–36`); measured by T7 against the installed 0.76.1 | `BRIDGE_SCHEMA = 2` (`:46`) | PASS → 1.3 |
| S9 manifest | installed `<SA>/package.json`: `pi` = `{"extensions":["./index.js"],"skills":["./skills"],"prompts":["./prompts"]}` and `peerDependencies` both **identical** to the installed 0.75.0; `keywords` gains `extension` (0.76.1 Changed); `dependencies` gains `@js-temporal/polyfill` 0.5.1 (0.76.0 schedules) | perk loads the package through `.pi/settings.json` `npm:pi-subagents@<pin>` | OBSERVED → no-action |
| S10 partial output | `src/runs/foreground/execution.ts@7d072b91:1547` `result.outputPartial = true;`, `:1570` `` `…\n\nPartial output before timeout:\n${fullOutput}` `` (0.76.0 Fixed: "The partial text is never saved as the output file and never counts as acceptance evidence"). Dist: `<SA>/src/runs/foreground/execution.js:1511`, `<SA>/src/runs/background/result-watcher.js:435` | `ReportWave` treats finished native partials as incomplete evidence | OBSERVED → 2.3 |
| S11 capacity | `src/extension/config.ts@7d072b91:95` `abandonedSlotReleaseAfterMs` (0.76.0); 0.76.1 Fixed: `stop` on a paused run whose result was already delivered "marks it stopped and the slot is freed"; `subagent doctor` "now reads the same pool for both active async capacity and the spawn budget". Dist: `<SA>/src/extension/config.js:105` | perk's writers (resolver, librarian) and their lock rules | OBSERVED → 2.2 |
| S12 child prompt order | `src/runs/shared/subagent-prompt-runtime.ts@7d072b91:225–226` "Pi's base prompt stays first so providers that recognize it by its opening still do." `` return `${rewritten}\n\n${boundary}${structured}`; `` (commit `17e17673`, #2693). Dist: `<SA>/src/runs/shared/subagent-prompt-runtime.js:206` | all 14 perk defs use `systemPromptMode: replace` (14/14) | OBSERVED → no-action |
| S13 `outputSchema` + `output` file | 0.76.0 Fixed: "If the child returns a structured result and does not write the file itself, the file now holds that result as indented JSON." Dist: `<SA>/src/runs/foreground/execution.js:1473` `JSON.stringify(result.structuredOutput, null, 2)` | perk's report lanes are output-free (`extension/waves/transport.ts:59` "String path fields only; output-free.") | OBSERVED → no-action |
| S14 doctor stamp | = T12a | `_SUBAGENTS_GUIDANCE_VERIFIED_VERSION = "0.75.0"` | REPRODUCED → 1.3 (= T12a; listed by reference) |
| S15 supplier-pin assertions | = T8b + T8c | `SUBAGENTS_PACKAGE = "npm:pi-subagents@0.75.0"` | REPRODUCED → 1.3 (= T8b, T8c; listed by reference) |

## Repair designs handed to owners

Every paragraph in this section is **source-derived and NOT MEASURED**: it states what the
owning node should build or prove, grounded in the citations above.

### 1.2 — adopt the 1.1.0 SDK pins

- **Forced fixes (T1, D5a).** Add `aborted: false` to `emitSettled`'s event in
  `extension/pi/v1/delivery/commitCompact.test.ts:71` and `extension/pi/v1/draftCompact.test.ts:51`.
  Nothing else in tsc, Biome, ruff, ty, node:test or pytest is forced by 1.1.0.
- **Cancellation translation (D5c).** perk derives cancellation from its own signal/budget and
  never reads `agent_settled`'s payload. 1.2 decides whether `translateEvent` (or a settle
  consumer) should read `aborted` — Pi's own statement is that it tells "a cancelled run from a
  finished one" — and, if so, adds typed fixtures carrying both `aborted: true` and `false`.
  Settlement still does not establish perk workflow success.
- **Lockfile rule (D1).** Keep the graph npm produces for 1.1.0: the 134 nested removals and the 8
  `@earendil-works/*` top-level entries are the intended upgrade, not churn. Of the 24 non-Pi
  top-level version moves, `lockrevert.mjs` classes 7 as revertable against the edited lockfile's
  declarations (`@aws-sdk/credential-provider-node`, `@aws-sdk/eventstream-handler-node`,
  `@aws-sdk/middleware-eventstream`, `@aws-sdk/middleware-websocket`, `@babel/runtime`,
  `@smithy/signature-v4`, `ws`) and 17 as forced. Two forced moves come from the 1.1.0 packages'
  own exact pins (`@anthropic-ai/sdk` 0.129.0 by pi-ai; `undici` 8.10.2 by pi-coding-agent, which
  the removed nested copy used to satisfy), as does the `brace-expansion` 5.0.12 addition. The
  other 15 forced `@aws-sdk/*`/`@smithy/*` moves are forced only relative to the re-resolved
  credential-provider chain's new declarations, which hangs off the revertable
  `credential-provider-node` move: revert the chain as one unit or keep it, never piecemeal. Then
  `npm prune`, a byte-identical `npm install --package-lock-only`, and a green `npm ci`.
  `piAiCompatGuard` now reads the top-level pi-ai (T6c); `docs/learned/pi/headless-session-drive.md`'s
  nested-pi-ai probe guidance is 1.0.0-era (no nested copy exists at 1.1.0) and the learned
  pin-bump "keep the shrinkwrapped tree" clause is too — both route through `/learn`.
- **Comment correction (D3).** `extension/substrate/toolGating.ts:23–24` ("their guidelines do
  not") is false at ≥ 1.0.4 and rides 1.2's fallout sweep.

### 1.3 — adopt the 0.76.1 supplier

- **Census (T7, S8, T13).** No `NATIVE_SDK_CENSUS` widening and no `BRIDGE_SCHEMA` bump: the drift
  guard passes against the installed 0.76.1 and the resolver finds every alias.
- **Pin-bound assertions (T8b, T8c, S15).** Both move with `SUBAGENTS_PACKAGE`; no test edit
  beyond the pin. T9 is the independent bridge witness for the new pin.
- **Stamp (T12a, S14).** The WARN is truthful until 7.1's live evidence; the stamp moves only then.
- **Install procedure (S4).** Install into `.pi/npm` with Pi stopped and start a fresh process —
  never `pi update`, never `/reload` across the swap (0.76.1 refuses an in-process version change).
  7.2's reverify guide says "upgrade with a fresh process". The swap also adds
  `@js-temporal/polyfill` + `jsbi` to `.pi/npm` (S9).

### 2.1 — descendant ceilings (S6)

Write `allowedAgents:` with an **empty value** in each leaf def; a literal `allowedAgents: []`
parses to `["[]"]`, which `normalizeCapabilityCeilingAllowedAgents`'s name pattern rejects. Test
actual definition loading through the supplier's parser, foreground and background.

### 2.2 — supplier lifecycle (T10d, T11, S2, S3, S11)

- **Wake (S2, T10d).** The parent now receives the completion notice and then the user message
  `Subagent updates above.`. Verify the workflow-completion notice is still the artifact that
  authorizes collection and that perk's `sendMessage` consumers neither swallow nor misread the
  wake message; T10d shows the woken turn produced no assistant entry in print mode — 2.2 covers
  the interactive/worker behaviour.
- **Liveness across reload (S3).** 0.76.1 keeps queued completion wakes in a process-global map
  and re-binds them to the new session; perk's `ReportWave` records are per activation. Keep the
  no-collection-across-reload rule; 2.3 characterizes freshness on relaunch.
- **Capacity (S11).** A freed supplier slot (`abandonedSlotReleaseAfterMs`, `stop` on a delivered
  paused run) is not proof a writer stopped.
- **Restriction packet (T11).** Delivery works on 0.76.1 under `--approve`; the other trust states
  are 2.2's. `fakeSubagents.ts` should also reject `workflowScriptPath` (S7).

### 2.3 — MCP selectors and partials (D2, S10)

First establish the registration path being proven against: (a) the supplier-child path — no
native MCP factory without `mcp:` selectors, so measure a child's actual tool list (a lane whose
task reports its tool names) with and without a trusted-project `mcp.json`; (b) the gate under
the restriction packet for a session that **does** register an MCP tool (the parent/planning
session, or a child whose launch names selectors) — the `tool_call` backstop plus
`toolPolicy.ts`'s MCP posture `unknown` → blocked, nested calls per 4.2. A floor proof without a
registered MCP tool is vacuous. Never add `excludeTools: mcp__*` blindly: supplier `excludeTools`
forwarding is not Pi's selector, and it proves nothing where no MCP tool is registered. Finished
native partials (`outputPartial: true`) remain INCOMPLETE evidence.

### 2.4 — headless delivery (T10c, S1)

The #2660 reproduction baseline on the new pair is T10c: a completed lane's print-mode parent
exits 0 in 8–14 s with the X1 pair once and an assistant-less wake turn. The refused-lane case
and its no-perk control are 2.4's to build; attribute nothing from release notes.

### 4.3 — codemode `only` (D4)

`prepareCodemodeLoadout` hides every direct-exposure declared tool in `only`, and perk's three
bounded writers are direct actions. Lift `only` only if a supported exposure/loadout treatment
keeps `plan_draft`, `objective_draft` and `objective_refinement_draft` directly declared;
otherwise `only` stays suspended, with a dated deviation.

### 5.1 — worker MCP isolation (D7, S5)

Use the public `McpExtensionOptions` (`loadConfig`, `credentials`, `logPath`, `openUrl`,
`updateConfig`; `createTransport`/`startupWaitMs` as needed) to scope the worker's MCP factory,
typing the store as `NonNullable<McpExtensionOptions["credentials"]>`. Do **not** override
`PI_CODING_AGENT_DIR`: supplier children call a bare `ModelRuntime.create()` and `getAgentDir()`,
and background runners inherit `process.env` (minus git routing and extension bindings), so the
override would move their model auth. Runners are detached and unref'd: disposal must not assume
they die with the parent.

### 5.2 — MCP lifecycle (D6b)

The shutdown row must observe every transport closed (`close` awaits `opening`) **before** the
throwaway directory is removed. The OAuth row must rely on the `openUrl`/`credentials` refusal,
not on the 15 s request timeout or `pi mcp login --timeout` (whose installed help text still
describes only the browser wait).

## The ledger

Every finding, each with exactly one verdict and one owner. D5a, S14 and S15 restate a measured
row and appear here only through it.

| Row | Finding | Verdict | Owner |
|---|---|---|---|
| T1 | root tsc red at 1.1.0: two `emitSettled` fixtures lack the required `agent_settled.aborted` (baseline green) | FAIL | 1.2 |
| T2 | prose-review tsc green | PASS | no-action |
| T3 | docs-site astro sync + tsc green | PASS | no-action |
| T4 | ty green | PASS | no-action |
| T5 | ruff + Biome green | PASS | no-action |
| T6a | node:test 3796/3796, 0 cancelled, 0 skipped, on the 1.1.0 SDK | PASS | no-action |
| T6b | `bareImportGuard` both tests | PASS | no-action |
| T6c | `piAiCompatGuard` (top-level pi-ai) | PASS | no-action |
| T6d | `hostAdmission` precondition: the installed 1.1.0 SDK is admitted | PASS | no-action |
| T6e | in-suite census drift guard | PASS | no-action |
| T6f | `restorationWindow` three window tests | PASS | no-action |
| T6g | `discoveryPilot` 13 tests | PASS | no-action |
| T6h | `perkToolSeam` real codemode script | PASS | no-action |
| T6i | `stageExecutionE2e`: real worker entry admits 1.1.0; real-codemode cases | PASS | no-action |
| T6j | `hostSdk` own-instance namespaces | PASS | no-action |
| T7 | census drift guard vs 0.76.1 | PASS | 1.3 |
| T8a | pytest `2 failed, 8361 passed, 1 skipped`, failures = T8b + T8c | PASS | no-action |
| T8b | managed-pin assertion fails on 0.76.1 | REPRODUCED | 1.3 |
| T8c | live selfcheck test fails only at the trailing pin assertion | REPRODUCED | 1.3 |
| T8d | below-floor test skipped on the admitted host | OBSERVED | no-action |
| T8e | pin lockstep at 1.1.0 | PASS | no-action |
| T8f | dev pin ≥ floor; remote pin ≥ floor | PASS | no-action |
| T9 | perk loads on 1.1.0 + 0.76.1; bridge installed | PASS | 1.2 |
| T10a | 0.76.1 launches a background child on 1.1.0 (runner-start witness) | PASS | 1.3 |
| T10b | that child completes `OK` | PASS | 1.3 |
| T10c | print-mode exit after a completed lane: exit 0, 14 s / 8 s, X1 once, no watchdog | OBSERVED | 2.4 |
| T10d | wake: notice → `Subagent updates above.` → started turn with no assistant entry | OBSERVED | 2.2 |
| T11 | restriction packet delivered on 0.76.1 (`[READ-ONLY MODE]` before `OK`) | OBSERVED | 2.2 |
| T12a | doctor `subagent-compat` WARN on 0.76.1 | REPRODUCED | 1.3 |
| T12b | doctor `settings-wiring` drift + `artifact-health` on the throwaway edit | OBSERVED | no-action |
| T12c | doctor `pi` row admits the 1.1.0 host | PASS | no-action |
| T12d | doctor scaffold-only reds (+ the pre-existing `config` red) | OBSERVED | no-action |
| T13 | 0.76.1 resolver: `missing: []`, all top-level | PASS | 1.3 |
| D1 | no shrinkwrap ≥ 1.0.1; the lockfile-shape preview | OBSERVED | 1.2 |
| D2 | selectors govern registered tools; perk report children register no MCP factory | OBSERVED | 2.3 |
| D3 | hidden declarations drop their guidelines; perk's header comment is stale; fakes still type-check | PASS | 1.2 |
| D4 | codemode `only` hides direct declared tools (unchanged since 1.0.0) | OBSERVED | 4.3 |
| D5b | renderer / `tool_execution_end` field additions break nothing | PASS | no-action |
| D5c | cancellation translation ignores `aborted` | OBSERVED | 1.2 |
| D6a | `_pendingToolNames` unchanged; reload re-applies modifiers; T6f/T6g green | PASS | no-action |
| D6b | MCP project overrides, close-awaits-opening, OAuth timeout/abort | OBSERVED | 5.2 |
| D7 | `McpExtensionOptions` public; credential store not root-exported | OBSERVED | 5.1 |
| D8 | Azure provider renamed to `azure`; perk has no reference | PASS | no-action |
| D9 | Node `>=22.19.0` unchanged and matched | PASS | no-action |
| D10 | codemode output separators, caps, frozen built-ins, async search | PASS | no-action |
| D11 | export maps perk and the supplier rely on still present | PASS | no-action |
| D12 | the no-surface sweep | OBSERVED | no-action |
| D13 | pi-ai stream-function breaking change; perk writes none | PASS | no-action |
| D14 | pi-tui `Terminal.setProgramStatus` breaking change; perk implements none | PASS | no-action |
| S1 | headless drain-then-deliver (measured by T10c) | OBSERVED | 2.4 |
| S2 | `Subagent updates above.` wake (measured by T10d) | OBSERVED | 2.2 |
| S3 | queued completion wakes survive reload (process-global) | OBSERVED | 2.2 |
| S4 | in-process version-change refusal | OBSERVED | 1.3 |
| S5 | bare `ModelRuntime.create()`, `getAgentDir()`, inherited env, detached unref'd runners | OBSERVED | 5.1 |
| S6 | `parseFrontmatterList`: blank → `[]`, `[]` → `["[]"]` | OBSERVED | 2.1 |
| S7 | `script` accepted; `workflowScript`/`workflowScriptPath` rejected | PASS | no-action |
| S8 | eight-specifier SDK census unchanged (measured by T7) | PASS | 1.3 |
| S9 | manifest/peers unchanged; `extension` keyword; new Temporal polyfill dep | OBSERVED | no-action |
| S10 | `outputPartial` + labelled partial output | OBSERVED | 2.3 |
| S11 | abandoned-slot release; `stop` on a delivered paused run; doctor pool | OBSERVED | 2.2 |
| S12 | Pi's base prompt first for `append` children; perk uses `replace` | OBSERVED | no-action |
| S13 | `outputSchema` result written to the output file as JSON; perk lanes output-free | OBSERVED | no-action |

Tally (62 counted rows): **PASS 34** (T2–T5, T6a–T6j, T7, T8a, T8e, T8f, T9, T10a, T10b, T12c,
T13, D3, D5b, D6a, D8, D9, D10, D11, D13, D14, S7, S8); **FAIL 1** (T1); **REPRODUCED 3** (T8b,
T8c, T12a); **OBSERVED 24** (T8d, T10c, T10d, T11, T12b, T12d, D1, D2, D4, D5c, D6b, D7, D12, S1,
S2, S3, S4, S5, S6, S9, S10, S11, S12, S13); **UNOBSERVED 0**. By reference, not counted: D5a
(= T1), S14 (= T12a), S15 (= T8b + T8c). Every planned row ran, so no row is a dependent
`UNOBSERVED — NOT PASSED`; no `T6x<k>`, `T8x<k>` or `T12x<k>` row arose.

## Falsified planning-time assumptions

1. **"tsc is green at 1.1.0" (expected but unproven).** It is red: two typed `emitSettled`
   fixtures lack `agent_settled.aborted`. Of the plan's two likely breakers only `aborted` broke;
   the `ToolLoadout` growth did not, because perk's fakes are `as unknown as ToolLoadout` casts.
2. **"The install leaves no nested pi-coding-agent tree."** No nested `@earendil-works/*` copy and no
   shrinkwrap remain, but a 12-entry non-Pi nested tree does (versions that differ from the
   top-level: `chalk` 6.0.0, `ignore` 7.0.8, `jiti` 2.7.0, … — snapshot matrix). The nested key
   count fell from 146 to 12.
3. **"Orphans such as `ignore`."** None: `npm ls` exits 0 with no `extraneous`/`invalid`/`missing`
   line; `ignore` 7.0.8 now lives in the remaining nested tree, not as a top-level orphan.
4. **Lockfile class (d) "incidental re-resolutions whose ranges did not change (`@aws-sdk/*`,
   `@smithy/*`, `ws`, `@babel/runtime`, …)".** By declared range, only 7 entries are unchanged-range
   moves, and one of them (`undici` 8.10.0 → 8.10.2) is not incidental: pi-coding-agent pins
   `8.10.2` exactly, formerly served by its nested copy. Most `@aws-sdk/*`/`@smithy/*` moves are in
   class (c), a chain whose declared ranges moved because its head re-resolved.
5. **T12c's predicted text `✓ pi: pi ok — $WT/node_modules/.bin/pi`.** perk 4.0.0 prints
   `✓ pi: pi ok — 1.1.0 (floor >= 1.0.0)`.
6. **"`extension/workerMain.ts`, which imports the SDK by bare specifier."** `workerMain.ts` itself
   imports no SDK specifier; it loads `substrate/hostSdkVersion.ts` (namespace import at `:14`) and
   the stage seam, whose `worker/sdkAdapter.ts:37` imports the SDK. Both resolve from `extension/`,
   so the Step 1.5 instrument is unchanged.
7. **"T8b–T8f are read from a targeted rerun of … the five node ids."** T8f names two tests, so
   the rerun had six node ids.
8. Confirmed rather than falsified, recorded for completeness: the census guard passes against
   0.76.1; 0.76.1 launches and completes a child on 1.1.0; `resolveHostPeerAliases` is still
   exported from `runner-aliases.js`; Node accepts the paired-reporter T6 line; pytest is exactly
   `N passed, 2 failed, 1 skipped`; `$MODEL`'s credential is `api_key`; the pi-subagents peers are
   unchanged; no newer release than either subject exists.

## Methodology appendix

### Scaffold (Steps 0–1)

```sh
# Step 0 (in $IMPL)
npm view @earendil-works/pi-coding-agent versions --json | tail -5
npm view @earendil-works/pi-coding-agent dist-tags --json
npm view @earendil-works/pi-coding-agent@1.1.0 _hasShrinkwrap engines.node time.modified
npm view pi-subagents versions --json | tail -3; npm view pi-subagents dist-tags --json
npm view pi-subagents@0.76.1 gitHead peerDependencies --json
git -C "$PIMIRROR" log --oneline -1 abe508e1
git -C "$PIMIRROR" show abe508e1:packages/coding-agent/package.json | grep '"version"'
git -C "$SAMIRROR" show 7d072b91:package.json | grep '"version"'
git rev-parse HEAD; which pi; readlink -f "$(which pi)"; pi --version; node --version
MODEL="$PI_PROVIDER/$PI_MODEL"                                                      # anthropic/claude-opus-5-5
shasum -a 256 "$MAIN/.pi/npm/package.json" "$MAIN/.pi/npm/package-lock.json" \
  "$MAIN/.pi/npm/node_modules/.package-lock.json" "$MAIN/.pi/npm/node_modules/pi-subagents/package.json"
git -C "$MAIN" status --porcelain                                                   # ?? docs/planning/pre-pi-durable-true-up.md
shasum -a 256 "$MAIN/docs/planning/pre-pi-durable-true-up.md"; git worktree list | wc -l   # 154
ls "$MAIN/.worktrees"; pgrep -fl "pi-1.1.0-characterization" || true                # none
# Step 1
git worktree add --detach "$WT" HEAD && mkdir -p "$SCRATCH/subagents-tmp"
# … cleanup.sh written here (see below), before any install
(cd "$WT" && uv sync --all-packages && npm ci)                                      # added 647 packages
(cd "$WT" && npm install --save-dev --save-exact @earendil-works/pi-coding-agent@1.1.0 @earendil-works/pi-ai@1.1.0 \
  @earendil-works/pi-tui@1.1.0 @earendil-works/pi-agent-core@1.1.0)                  # added 12 packages, removed 134 packages, and changed 29 packages in 4s
git diff --stat -- package.json package-lock.json    # 2 files changed, 417 insertions(+), 2207 deletions(-)
grep -c '"hasShrinkwrap"' package-lock.json           # 0
git show HEAD:package-lock.json > "$SCRATCH/base-package-lock.json"
node "$SCRATCH/lockdiff.mjs" "$SCRATCH/base-package-lock.json" package-lock.json
node "$SCRATCH/lockrevert.mjs" "$SCRATCH/base-package-lock.json" package-lock.json
npm ls @earendil-works/pi-coding-agent @earendil-works/pi-ai @earendil-works/pi-tui @earendil-works/pi-agent-core typebox   # exit 0
npm ls 2>&1 | grep -E 'extraneous|invalid|missing' || true                           # (none)
npm install --package-lock-only                       # up to date; sha256 5311cc4c… before and after
(cd "$WT/extension" && node --input-type=module -e "console.log(import.meta.resolve('@earendil-works/pi-coding-agent'))")
cp -R "$MAIN/.pi/npm" "$WT/.pi/npm"                   # independent copy, never the hardlink materializer
export PATH="$WT/node_modules/.bin:$PATH"             # the 1.1.0 host, per shell
HERMETIC=$(mktemp -d -t perk-pi11-hermetic)           # AUTHED is made at Step 3, after the offline tier
sed -i '' 's/"npm:pi-subagents@0.75.0"/"npm:pi-subagents@0.76.1"/' "$WT/.pi/settings.json"
rm -rf "$WT/.pi/npm/node_modules/pi-subagents"
(cd "$WT" && npm install pi-subagents@0.76.1 --prefix .pi/npm --legacy-peer-deps)  # added 3 packages
# Step 3 preflight
jq 'map_values(.type)' "$MAIN/.pi/agent/auth.json"
AUTHED=$(mktemp -d -t perk-pi11-authed); cp "$MAIN/.pi/agent/auth.json" "$AUTHED/auth.json"
```

The T6a line (`just test-js` with a paired second reporter; each reporter has its destination):

```sh
node --test --test-reporter=dot --test-reporter-destination=stdout --test-reporter=tap \
  --test-reporter-destination="$SCRATCH/T6.tap" --test-concurrency=$(( $(getconf _NPROCESSORS_ONLN) * 2 )) \
  "extension/**/*.test.ts" "docs/site/src/**/*.test.mjs" "packages/perk-dev/**/*.test.mjs"
```

### Launch environments

`$SCRUB` (prepended to every manually launched `pi`):

```sh
env -u PERK_RUN_ID -u PERK_PROFILE_HANDOFF -u PERK_SELFCHECK -u PERK_DISABLE_NATIVE_SDK_BRIDGE \
  -u PERK_CLI_VERSION -u PI_SUBAGENT_CHILD -u PI_SUBAGENT_CHILD_AGENT -u PI_SUBAGENT_EXTENSION_BINDINGS \
  -u PI_SESSION_FILE -u PI_SESSION_ID -u PI_MODEL -u PI_PROVIDER -u PI_REASONING_LEVEL -u PI_CODING_AGENT
```

| Legs | Host | `env \| grep -E '^(PI_\|PERK_)' \| sort` after `$SCRUB` + layer |
|---|---|---|
| T9 (hermetic) | 1.1.0 (`which pi` inside the env = `$WT/node_modules/.bin/pi`, `1.1.0`) | `PERK_SKIP_VERSION_CHECK=1`, `PI_CODING_AGENT_DIR=$HERMETIC`, `PI_OFFLINE=1`, `PI_SUBAGENTS_TEMP_ROOT=$SCRATCH/subagents-tmp` (+ `ANTHROPIC_API_KEY=perk-live-smoke-placeholder-never-sent`, not a `PI_*` name) |
| T10, T11 (authed) | 1.1.0 | `PERK_SKIP_VERSION_CHECK=1`, `PI_CODING_AGENT_DIR=$AUTHED`, `PI_SUBAGENTS_TEMP_ROOT=$SCRATCH/subagents-tmp` |

Inside each launched process the probe's dump also shows `PI_CODING_AGENT: "true"` (set by Pi in
process). The offline rows (T1–T8) and the doctor run (T12) inherited the implement session's
environment unscrubbed, with the PATH prefix and (T8) an exported `PI_SUBAGENTS_TEMP_ROOT`; the
live bridge test builds its own scrubbed env. No credential is env-borne.

Commands (from `$WT`):

```sh
$SCRUB <hermetic> pi --approve --mode json -p /perk-selfcheck                                                                   # T9
GRACE=60 CAP=330 $SCRATCH/run-bounded.sh $SCRATCH/T10.log $SCRUB <authed> pi --approve --mode json -e $SCRATCH/probe-spawn.ts -p "/probe-spawn script $MODEL"              # T10
GRACE=60 CAP=330 $SCRATCH/run-bounded.sh $SCRATCH/T11.log $SCRUB <authed> pi --approve --mode json -e $SCRATCH/probe-spawn.ts -p "/probe-spawn script $MODEL restricted"   # T11
uv run perk doctor --verbose; uv run perk doctor --json                                                                       # T12 (and once in $IMPL, PATH 1.0.0)
node $SCRATCH/resolver-probe.mjs "$WT/.pi/npm/node_modules/pi-subagents/src/runs/background/runner-aliases.js" "$WT/node_modules/@earendil-works/pi-coding-agent"   # T13
```

### The probe extension and the watchdog

`$SCRATCH/probe-spawn.ts` and `$SCRATCH/run-bounded.sh` were extracted byte-for-byte from
[`pi-1.0.0-characterization.md`](pi-1.0.0-characterization.md) § "The probe extension (verbatim;
no C0 repair was applied)" and § "The watchdog added after A11" (`awk` over the fenced blocks; 84
and 19 lines, SHA-256 `4ac6314f…b0a038` and `1114155f…0b0843`) and **reused unchanged**: no probe
repair was needed (T10a succeeded first time) and the watchdog never fired.

### `resolver-probe.mjs` (T13; paths come in as `argv`)

```js
const [aliasesModule, packageRoot] = process.argv.slice(2); const { resolveHostPeerAliases } = await import(aliasesModule); console.log(JSON.stringify(resolveHostPeerAliases(packageRoot), null, 2));
```

### `lockdiff.mjs` (Step 1.4, D1)

```js
// lockdiff.mjs <base-lockfile> <edited-lockfile> — per `packages` key: added / removed /
// version-changed entries, split into (a) @earendil-works/* top-level, (b) the former nested
// pi-coding-agent tree (node_modules/@earendil-works/pi-coding-agent/node_modules/*),
// (c) entries whose declared range changed (a dependent's dependency range moved),
// (d) incidental re-resolutions whose ranges did not change, (e) everything else.
import { readFileSync } from "node:fs";

const [basePath, editedPath] = process.argv.slice(2);
const base = JSON.parse(readFileSync(basePath, "utf8")).packages;
const edited = JSON.parse(readFileSync(editedPath, "utf8")).packages;
const NESTED = "node_modules/@earendil-works/pi-coding-agent/node_modules/";
const name = (key) => key.slice(key.lastIndexOf("node_modules/") + "node_modules/".length);

// Every declared range for a package name, across all dependents outside the former nested
// tree (the edited lockfile has none, so its declarations would otherwise always "change").
function ranges(packages) {
  const out = new Map();
  for (const [key, entry] of Object.entries(packages)) {
    if (key.startsWith(NESTED)) continue;
    for (const field of ["dependencies", "devDependencies", "optionalDependencies", "peerDependencies"]) {
      for (const [dep, range] of Object.entries(entry[field] ?? {})) {
        if (!out.has(dep)) out.set(dep, new Set());
        out.get(dep).add(range);
      }
    }
  }
  return out;
}
const baseRanges = ranges(base);
const editedRanges = ranges(edited);
const sameRanges = (dep) => {
  const a = [...(baseRanges.get(dep) ?? [])].sort().join("|");
  const b = [...(editedRanges.get(dep) ?? [])].sort().join("|");
  return a === b;
};

const rows = [];
for (const key of new Set([...Object.keys(base), ...Object.keys(edited)])) {
  if (key === "") continue;
  const a = base[key];
  const b = edited[key];
  let change;
  if (a && !b) change = `removed ${a.version}`;
  else if (!a && b) change = `added ${b.version}`;
  else if (a.version !== b.version) change = `${a.version} -> ${b.version}`;
  else continue;
  let cls;
  if (key.startsWith(NESTED)) cls = "b nested pi-coding-agent tree";
  else if (key.startsWith("node_modules/@earendil-works/")) cls = "a @earendil-works/* top-level";
  else if (!sameRanges(name(key))) cls = "c declared range changed";
  else if (a && b) cls = "d incidental re-resolution (ranges unchanged)";
  else cls = "e added/removed (ranges unchanged)";
  rows.push({ cls, key, change });
}

const byClass = Map.groupBy(rows, (r) => r.cls);
for (const cls of [...byClass.keys()].sort()) {
  const group = byClass.get(cls);
  const kinds = { added: 0, removed: 0, changed: 0 };
  for (const r of group) kinds[r.change.startsWith("added") ? "added" : r.change.startsWith("removed") ? "removed" : "changed"]++;
  console.log(`## (${cls}) — ${group.length} entries (added ${kinds.added}, removed ${kinds.removed}, version-changed ${kinds.changed})`);
  for (const r of group.sort((x, y) => x.key.localeCompare(y.key))) console.log(`  ${r.key}: ${r.change}`);
}
console.log(`## total: ${rows.length} entries differ; base ${Object.keys(base).length - 1} entries, edited ${Object.keys(edited).length - 1} entries`);
```

Its output (class headers and every non-nested entry). The 134 class-(b) keys, all
`node_modules/@earendil-works/pi-coding-agent/node_modules/*` and all removed, are: 10 under
`@earendil-works/` (`chord`, `pi-agent-core`, `pi-ai` — plus pi-ai's own nested `agent-base`,
`https-proxy-agent`, `openai` — `pi-codemode`, `pi-mcp`, `pi-telemetry`, `pi-tui`), 19 `@aws-sdk/*`
+ 1 `@aws/*`, 26 `@esbuild/*`, 9 `@protobufjs/*`, 6 `@smithy/*`, 5 other scoped (`@anthropic-ai/sdk`,
`@babel/runtime`, `@google/genai`, `@stablelib/base64`, `@types/node`) and 58 unscoped (incl.
`esbuild`, `undici`, `ws`, `typebox`, and 2 nested-in-nested):

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

The 7 class-(c) and 2 class-(e) additions are packages hoisted from the removed nested tree to the
top level (`cross-spawn`, `quickjs-wasi`, `which`, …; `brace-expansion` 5.0.12 is pi-coding-agent's
exact pin).

### `lockrevert.mjs` (D1 revertability; read-only)

```js
// lockrevert.mjs <base-lockfile> <edited-lockfile> — for every top-level, non-@earendil-works entry
// whose version changed, does the BASE version still satisfy every range the EDITED lockfile
// declares for that name? yes → "revertable"; no → "FORCED" (naming the ranges it would break).
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const semver = createRequire(`${process.cwd()}/`)("semver");
const [basePath, editedPath] = process.argv.slice(2);
const base = JSON.parse(readFileSync(basePath, "utf8")).packages;
const edited = JSON.parse(readFileSync(editedPath, "utf8")).packages;
const NESTED = "node_modules/@earendil-works/pi-coding-agent/node_modules/";
for (const key of Object.keys(edited).sort()) {
  if (!key || key.startsWith(NESTED) || key.startsWith("node_modules/@earendil-works/")) continue;
  if (!base[key] || base[key].version === edited[key].version) continue;
  const name = key.slice(key.lastIndexOf("node_modules/") + "node_modules/".length);
  const broken = [];
  for (const [dependent, entry] of Object.entries(edited))
    for (const field of ["dependencies", "optionalDependencies", "peerDependencies"]) {
      const range = entry[field]?.[name];
      if (range && !semver.satisfies(base[key].version, range)) broken.push(`${dependent || "<root>"}=${range}`);
    }
  console.log(`${broken.length ? "FORCED" : "revertable"} ${key} ${base[key].version} -> ${edited[key].version}${broken.length ? ` (breaks ${broken.join(" ")})` : ""}`);
}
```

Result: **revertable** `@aws-sdk/credential-provider-node`, `@aws-sdk/eventstream-handler-node`,
`@aws-sdk/middleware-eventstream`, `@aws-sdk/middleware-websocket`, `@babel/runtime`,
`@smithy/signature-v4`, `ws`; **FORCED** `@anthropic-ai/sdk` (breaks `pi-ai=0.129.0`), `undici`
(breaks `pi-coding-agent=8.10.2`), and the other 15 `@aws-sdk/*`/`@smithy/*` entries of class (c)
(e.g. `@aws-sdk/core 3.978.0 -> 3.978.1 (breaks …/credential-provider-env=^3.978.1 …)`), each
broken range declared by another re-resolved chain member.

### `cleanup.sh` (reap, then `--remove`)

```bash
#!/usr/bin/env bash
# cleanup.sh [--remove] — reap every experiment-owned process, then (with --remove) delete the
# throwaway. Self-contained: MAIN/WT/SCRATCH are derived from this file's own location; the two
# agent dirs come from $SCRATCH/agent-dirs.env (written when each dir is created) or the env.
# Runs on every hard stop, interruption, partial setup, before any probe retry, before authoring,
# and at teardown. The pgrep patterns also match this script's own command line and the shell
# that invoked it, so this process, its ancestors and its own subshells are excluded from the kill
# list.
SCRATCH=$(cd "$(dirname "$0")" && pwd)
WT=$(dirname "$SCRATCH")
MAIN=$(cd "$WT" && dirname "$(git rev-parse --path-format=absolute --git-common-dir)")
[ -f "$SCRATCH/agent-dirs.env" ] && . "$SCRATCH/agent-dirs.env"
PATTERNS=("$SCRATCH" "pi-1.1.0-characterization" "perk-pi11")

chain() { local p=$1; while [ -n "$p" ] && [ "$p" -gt 1 ]; do echo "$p"; p=$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' '); done; }
SELF=" $(chain $$ | tr '\n' ' ') "
# ours = an ancestor of this script, or a process whose own ancestor chain passes through $$.
ours() { case "$SELF" in *" $1 "*) return 0;; esac; case " $(chain "$1" | tr '\n' ' ') " in *" $$ "*) return 0;; esac; return 1; }
listing() { for pat in "${PATTERNS[@]}"; do echo "pgrep -fl \"$pat\":"; pgrep -fl -- "$pat" | while read -r pid rest; do ours "$pid" || echo "  $pid $rest"; done; done; }
pids() { for pat in "${PATTERNS[@]}"; do pgrep -f -- "$pat"; done | sort -u | while read -r pid; do ours "$pid" || echo "$pid"; done; }

echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) reap: before"; listing
for round in 1 2 3; do
  victims=$(pids)
  [ -z "$victims" ] && break
  echo "round $round: TERM $victims"; kill -TERM $victims 2>/dev/null; sleep 5
  survivors=$(pids); [ -n "$survivors" ] && { echo "round $round: KILL $survivors"; kill -KILL $survivors 2>/dev/null; sleep 1; }
done
echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) reap: after"; listing
[ -n "$(pids)" ] && { echo "reap: survivors remain"; exit 1; }

[ "${1:-}" = "--remove" ] || exit 0
echo "=== remove"
git -C "$MAIN" worktree remove --force "$WT"; echo "git worktree remove --force exit=$?"
git -C "$MAIN" worktree prune; echo "git worktree prune exit=$?"
for d in "${HERMETIC:-}" "${AUTHED:-}"; do [ -n "$d" ] && { rm -rf "$d"; echo "rm -rf $d exit=$?"; ls -d "$d" 2>&1; }; done
ls -d "$WT" 2>&1
echo "=== MAIN staging hashes"
shasum -a 256 "$MAIN/.pi/npm/package.json" "$MAIN/.pi/npm/package-lock.json" \
  "$MAIN/.pi/npm/node_modules/.package-lock.json" "$MAIN/.pi/npm/node_modules/pi-subagents/package.json"
echo "=== git -C \$MAIN status --porcelain"; git -C "$MAIN" status --porcelain
```

`$SCRATCH/agent-dirs.env` held `HERMETIC=…` (written at Step 1.7) and `AUTHED=…` (Step 3). The
reap half ran after T9, after T10 and after T11 (only the after-listings were kept: all empty),
then before Step 4 (16:25:06Z), before authoring (16:28:59Z) and at teardown (16:38:02Z), where
the before- and after-listings were all empty — no experiment-owned process remained after any
reap.

### Deviations from the plan's procedure

- **Cleanup order.** `cleanup.sh` was written immediately after `git worktree add` (Step 1.1),
  not at Step 1.9, so a partial setup could already be cleaned.
- **Cleanup instrument repair (one).** Its first version listed and killed its own subshells and
  ancestors, because the `pgrep -f` patterns match its own command line (`bash $SCRATCH/cleanup.sh`)
  — it then reported `reap: survivors remain`. Repaired by excluding this process's ancestors and
  every process whose ancestor chain passes through it (the `chain`/`ours` functions above). The
  repaired script was validated on a planted detached process
  (`nohup bash -c "exec -a '$SCRATCH/fake-runner' sleep 600" &`): `round 1: TERM 11813`, then
  empty listings. This was before any experiment process existed.
- **`lockdiff.mjs` repair (one).** Its first version computed declared ranges over the whole
  lockfile, so every dependency the removed nested tree declared counted as "range changed".
  Repaired to exclude the nested tree from both range sets (the version above). `lockrevert.mjs` is
  an added read-only instrument for 1.2's revert rule.
- **Auth types read twice.** Once at Step 0 (types only) and again at the Step 3 preflight; the
  copy was made only at Step 3.
- **T1 provenance.** The baseline invocation ran for T1 although the owner rules already classify
  typed-fixture breakage (exit 0 at 1.0.0 — the red is 1.1.0's).
- **T8b–T8f.** Six node ids (T8f names two tests).
- **D5 split** into D5a (by reference to T1), D5b and D5c so each carries one verdict; **D13/D14**
  appended by the Breaking-Changes scan; the codemode and mcp package changelogs were scanned too.
- **T9** ran without the watchdog (exit 0 in 1 s); T10/T11 ran under it.
- **Mirror reads.** A `git grep` over the partial-clone pi mirror tried to fetch a missing blob
  from its promisor remote and failed (`fatal: could not fetch … from promisor remote`); every
  citation was then read with per-file `git show <sha>:<path>`. No mirror was refreshed; the
  pi-subagents mirror's working tree was never read.
- **Excerpts.** `rg`/`grep` excerpts of perk sources were read at `8eefff4d` in `$IMPL`, identical
  to the throwaway's tracked tree.

### The ledger copy (Step 6)

`docs/planning/pre-pi-durable-true-up.md` is the MAIN seed (SHA-256 `977e10d6…54ea4`, 467 lines)
copied byte-for-byte, then given Edits A, B and C and two link lines.
`diff "$MAIN/docs/planning/pre-pi-durable-true-up.md" docs/planning/pre-pi-durable-true-up.md`
prints exactly these hunks (1 line removed, 19 added; 467 → 485 lines):

```text
145c145        Edit A — the sequencing sentence replaced (the rest of the paragraph byte-identical)
271a272,273    Edit C — the WP4 callout + blank line
299a302,303    Edit C — blank line + the WP5 callout
389a394,401    Edit B — the new section: heading, intro line, the three deviations
390a403,406    Edit B — "### Dispositions the characterization falsified" + "None — …"
432a449        [objective-2707]: https://github.com/mattgiles/perk/issues/2707
465a483        [characterization-1.1.0]: ../design/archive/pi-1.1.0-characterization.md
```

The copy's SHA-256 before the edits equalled the seed's (`977e10d6…54ea4`). The MAIN seed is left
where it is, untracked and untouched.

### Teardown proof (Step 7)

```text
=== 2026-10-09T16:38:02Z  cleanup.sh --remove, reap: before
                          pgrep -fl "$SCRATCH"                      → (none)
                          pgrep -fl "pi-1.1.0-characterization"     → (none)
                          pgrep -fl "perk-pi11"                     → (none)
=== 2026-10-09T16:38:02Z  reap: after                               → (none), (none), (none)
=== remove   git worktree remove --force "$WT"   exit=0
             git worktree prune                  exit=0
             rm -rf "$HERMETIC"                  exit=0  (ls: … No such file or directory)
             rm -rf "$AUTHED"                    exit=0  (ls: … No such file or directory)
             ls -d "$WT"                         → No such file or directory
=== MAIN staging hashes (after teardown)
d4f22073171068d1f4eb3c54a20dab4ed818cc6c5a725455fe129e0ea49637b9  $MAIN/.pi/npm/package.json
85c7e5a5b2d71081a191d8fcaf6186b0f49b5eb34fe985c62b020b1722ab2f50  $MAIN/.pi/npm/package-lock.json
ae5ba99e949608f21ea272d2c14ceb47c284f9260bf326e00701c74ea8a77302  $MAIN/.pi/npm/node_modules/.package-lock.json
919f846872963310c648e076a1d6c026bc9e11a13b40a8724c2aa3ead6ac3f3d  $MAIN/.pi/npm/node_modules/pi-subagents/package.json
    (identical at Step 0.4, after the Step 1.10 swap, and here)
=== git -C "$MAIN" status --porcelain     → ?? docs/planning/pre-pi-durable-true-up.md   (unchanged from Step 0;
                                             seed SHA-256 still 977e10d6…54ea4)
=== 2026-10-09T16:38:12Z
    git worktree list | wc -l             → 154 (as at Step 0); 0 entries match pi-1.1.0-characterization;
                                             the `worktree` path set is identical to the pre-experiment set
    ls "$MAIN/.worktrees"                 → identical to the Step 0 listing (plan-1416 … plan-2708,
                                             review-2243, review-2246, review-2249, worktrees)
    pgrep -fl "pi-1.1.0-characterization" → (none) pgrep exit=1
    git -C "$IMPL" status --porcelain     → ?? docs/design/archive/pi-1.1.0-characterization.md
                                             ?? docs/planning/pre-pi-durable-true-up.md
```

Removing the worktree deleted `$SCRATCH`, including the experiment-local pi-subagents temp root
(final run listing: `84ef72f3…`, `daf48258…`, `ddb3d9d1…`, `f9eaf416…`), the throwaway
`package*.json` / `.pi/settings.json` / `.pi/npm` edits, the probe, the watchdog, the scripts and
the logs; both agent dirs (sessions and the `auth.json` copy) went with `rm -rf`. Only this text
survives.
