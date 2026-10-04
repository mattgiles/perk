# Characterization: published Pi 1.0.0 against perk 3.9

**Status:** dated evidence record. Measured 2026-10-03 (14:12–14:42Z); Leg I (owner, interactive)
2026-10-04; authored 2026-10-04. It characterizes perk 3.9.0 at revision
`8ddbc2ad826c31184e9aa7a60b1bfed478f3234a` against **published** Pi 1.0.0 in a throwaway
detached worktree, `$MAIN/.worktrees/pi-1.0.0-characterization` (removed at teardown). It
implements plan #2657 (Objective #2656, node 1.1). The precedents are
[`pi-0.99.2-baseline-verification.md`](pi-0.99.2-baseline-verification.md) and
[`pi-subagents-child-capability-characterization.md`](pi-subagents-child-capability-characterization.md).

**Verdict: characterization complete. 36 ledger rows: 22 PASS / 2 FAIL / 4 REPRODUCED /
8 OBSERVED / 0 UNOBSERVED.**

- **No phase-gate blocker.** A9 (perk loads on 1.0.0 with 0.73.1), B2 (perk loads on 1.0.0 with
  0.75.0) and B5a (0.75.0 launches a background child on 1.0.0) all PASS. The host-move
  precondition is met: perk 3.9 loads and its native-SDK bridge installs on the 1.0.0 host.
  1.2's premise also holds: 0.75.0 launches and completes a child there.
- **The 0.73.1 refusal reproduced, twice** (A10 resolver probe, A11 real RPC spawn): `…
  does not provide @earendil-works/pi-agent-core/node.` One lane was measured. The check runs
  per lane in `spawnRunner` (source-derived), so on a 1.0.0 host with perk's pinned pi-subagents
  0.73.1, every background wave lane should refuse the same way.
- **Interim operator risk (D5, owner 4.1).** The remote runner action installs Pi unversioned
  (`npm install -g @earendil-works/pi-coding-agent`). npm `latest` was 1.0.1 at Step 0 and is
  1.0.2 at authoring time. Neither patch release was measured here. Their registry
  `pi-agent-core` manifests also omit the `./node` export (source-derived, see the snapshot
  matrix). The remote runner pairs that host with the repo's pinned `npm:pi-subagents@0.73.1`.
  Until 1.2 lands, remote wave lanes should therefore refuse the way A11 did. A11x also shows
  that, on the one refused lane measured, the headless print-mode parent **did not exit** (killed
  after about 7 minutes). The fix belongs to 4.1 and 1.2; this record states the exposure.
- **No pin moved and nothing landed.** Every `package.json`/`package-lock.json`/`.pi/settings.json`
  edit was a throwaway edit inside the detached worktree, and the experiment ran on an
  independent copy of `.pi/npm`. Both were deleted at teardown. The main checkout's supplier
  staging hashes are identical before and after, and its `git status --porcelain` is empty. This
  PR adds this file and nothing else. No code, pin, contract, user-doc or CHANGELOG change.
- **The 4.2 fix list is empty.** At the 1.0.0 pins, tsc, Biome, ruff, ty, the full node:test suite
  and the full pytest suite are green as they stand.

Measured rows and source-derived statements are kept separate throughout. A **measured** row
quotes the output of a command run in this experiment. A **source-derived** statement cites
`<path>@v1.0.0` in the tagged library mirror (`docs/library/source-code/github.com/earendil-works/pi`,
tag `v1.0.0` = `a13d35a742c6ef8462812a28fbe1d8c8b7431c32`), with an installed-dist `grep`
witness where one exists. A passing test is never quoted as observed live behaviour.

**Path abbreviations in quotes:** `$MAIN` = `/Users/mattgiles/dev/github/mattgiles/perk`.
`$WT` = `$MAIN/.worktrees/pi-1.0.0-characterization`. `$SCRATCH` = `$WT/.perk-characterization`.
`$AUTHED` and `$HERMETIC` are the two throwaway agent dirs
(`/var/folders/90/…/T/perk-pi1-authed.BvXisNY0Uy` and `…/perk-pi1-hermetic.jSCDYNfqRD`). Apart
from these substitutions, quotes are verbatim.

## Snapshot matrix

| Component | Version / value | Provenance |
|---|---|---|
| perk | 3.9.0 @ `8ddbc2ad` (the throwaway was detached at the implement worktree's HEAD) | `git -C $WT rev-parse HEAD` |
| Dev pins (throwaway only) | `@earendil-works/{pi-agent-core,pi-ai,pi-client,pi-coding-agent,pi-server,pi-tui}` **1.0.0** exact; `typebox` 1.3.27, `typescript` 6.0.3 unchanged | `npm install --save-dev --save-exact …@1.0.0` (`git diff -- package.json`) |
| Root on-disk, top-level | pi-coding-agent 1.0.0, pi-ai 1.0.0, pi-agent-core 1.0.0, pi-tui 1.0.0, pi-client 1.0.0, pi-server 1.0.0, **pi-protocol 1.0.1, chord 1.0.1, pi-telemetry 1.0.1** | each `node_modules/@earendil-works/*/package.json` `version` |
| Root on-disk, nested | `pi-coding-agent/node_modules/@earendil-works/{pi-ai,pi-agent-core,pi-tui,pi-mcp,pi-codemode,chord,pi-telemetry}` all 1.0.0. The nested set did not shrink | each nested `package.json` |
| typebox / jiti | typebox 1.3.27 (top-level and nested under pi-coding-agent); jiti 2.7.0 (nested under pi-coding-agent only) | on-disk `package.json` |
| `npm ls` agreement gate | every resolved pi-coding-agent / pi-ai / pi-tui / pi-agent-core / pi-client / pi-server copy at 1.0.0; typebox 1.3.27 deduped; jiti 2.7.0; pi-client → pi-protocol 1.0.1; exit 0 | `npm ls @earendil-works/pi-coding-agent @earendil-works/pi-ai @earendil-works/pi-tui @earendil-works/pi-agent-core @earendil-works/pi-client @earendil-works/pi-server typebox jiti` |
| Lockfile delta (4.2 preview) | `package-lock.json` 453 lines (`2 files changed, 222 insertions(+), 243 deletions(-)` with `package.json`). 38 entries changed: 16 `@earendil-works/*` (9 top-level, 7 nested); 17 `@aws-sdk/*` and 3 `@smithy/*` patch re-resolutions (e.g. `@aws-sdk/core` 3.978.0 → 3.978.1, `@smithy/core` 3.34.1 → 3.35.1); `ws` 8.21.0 → 8.22.0; `ignore` 7.0.8 removed. No package added except by version change | per-entry `version` comparison of `git show HEAD:package-lock.json` vs the edited lockfile |
| `pi` on PATH (outside the throwaway shell) | **0.99.2**, `~/.local/share/mise/installs/node/26.3.0/bin/pi` → `…/lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js` | `which pi`, `readlink -f`, `pi --version` |
| `pi` in the throwaway shell (`PATH="$WT/node_modules/.bin:$PATH"`) | **1.0.0**, `$WT/node_modules/.bin/pi` → `$WT/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js` | same three commands, PATH-prefixed |
| `node` | v26.3.0 | `node --version` |
| `$MODEL` (lane model for every spawn leg) | `anthropic/claude-opus-5-5` | `$PI_PROVIDER/$PI_MODEL` of the implement session, read before any scrub |
| pi-subagents, arm A | 0.73.1 | `$WT/.pi/npm/node_modules/pi-subagents/package.json` after the copy |
| pi-subagents, arm B | 0.75.0 | same file after `rm -rf` + `npm install pi-subagents@0.75.0 --prefix .pi/npm --legacy-peer-deps` |
| pi-web-access / Plannotator | 0.33.0 / 0.27.21 | on-disk `package.json` |
| `.pi/npm` independence | MAIN `package.json` inode 147622898 (link count 14: the main staging is hardlink-shared with materialized worktrees); copy inode 460313937 (link count 1). Same for `package-lock.json`: 147622913 vs 460313936 | `ls -li` after `cp -R` |
| MAIN staging hashes (before, after the 0.75.0 install, after teardown: all three identical) | `package.json` `eb487ac3…8444ad0`; `package-lock.json` `3efbddc2…ec93f6c6`; `node_modules/.package-lock.json` `a44bd4b4…eeb00fd`; `node_modules/pi-subagents/package.json` `12ddb985…7e193` (MAIN pi-subagents stays 0.73.1) | `shasum -a 256` at Step 0, Step 5.1, Step 9.3 |
| npm registry (Step 0, 2026-10-03T14:12Z) | pi-coding-agent versions end `0.99.1, 0.99.2, 1.0.0, 1.0.1`; pi-subagents end `0.74.0, 0.75.0`; `engines.node` of 1.0.0 `>=22.19.0` | `npm view … versions --json` |
| npm registry (authoring, 2026-10-04T19:25Z) | pi-coding-agent `latest` = **1.0.2** (published 2026-10-04T00:56Z); `pi-agent-core@1.0.1` and `@1.0.2` `exports` = `.` and `./package.json` only; pi-subagents `latest` = 0.75.0 | `npm view … time`, `npm view @earendil-works/pi-agent-core@1.0.{1,2} exports` (registry metadata, not installed) |

The subjects stayed **exact 1.0.0** and **exact 0.75.0** although newer Pi patches appeared during
the experiment.

## Offline evidence (A1–A8, arm A: 0.73.1 staged, 1.0.0 pins)

All ran in the PATH-prefixed throwaway shell, with `which pi` = `$WT/node_modules/.bin/pi` and
`pi --version` = `1.0.0` recorded in the A1/A8 logs. No check failed, so the baseline (provenance)
invocation in the implement worktree was never needed for A1–A8.

| Row | Command | Verbatim summary | Verdict → owner |
|---|---|---|---|
| A1 | `npm run typecheck` (root tsc) | `> tsc --noEmit` … `exit=0` (no diagnostics) | PASS → no-action |
| A2 | `npm run prose-review:typecheck` | `> perk-prose-review@0.0.0 typecheck` / `> tsc --noEmit` … `exit=0` | PASS → no-action |
| A3 | `npm run docs:typecheck` | `astro sync && tsc --noEmit` … `[types] Generated 2.82s` … `exit=0`. The one `[WARN] [astro-expressive-code] … language "gitignore"` line is a content-highlighting warning unrelated to Pi | PASS → no-action |
| A4 | `just typecheck-py` | `uv run ty check` / `All checks passed!` | PASS → no-action |
| A5 | `just lint` | `All checks passed!` (ruff) / `Checked 488 files in 356ms. No fixes applied.` (Biome) | PASS → no-action |
| A6 | `just test-js` command line, with a TAP reporter to file added for counts | `# tests 3655` / `# pass 3655` / `# fail 0` / `# cancelled 0` / `# skipped 0` / `# todo 0`; `exit=0` | PASS → no-action |
| A7 | `node --test extension/substrate/nativeSdkBridge.test.ts` | `✔ census drift guard: the installed consumers import exactly NATIVE_SDK_CENSUS (1669.244333ms)`; `ℹ tests 32` / `ℹ pass 32` / `ℹ fail 0` / `ℹ skipped 0` | PASS → no-action |
| A8 | `uv run pytest -rfEs` (PATH-prefixed, `PI_SUBAGENTS_TEMP_ROOT` exported) | `======================= 8242 passed in 182.12s (0:03:02) =======================` (no skips) | PASS → no-action |

**A1: the production value imports tsc confirmed to exist at 1.0.0** (read from source; tsc
green): `extension/worker/sdkAdapter.ts`: `@earendil-works/pi-coding-agent {
createAgentSessionFromServices, createAgentSessionRuntime, createAgentSessionServices,
ModelRuntime, resolveCliModel, SessionManager, SettingsManager }`; `extension/vendor/btw/btw.ts`:
`pi-coding-agent { createAgentSession, createExtensionRuntime, getMarkdownTheme, SessionManager }`
and `pi-tui { Container, Input, Markdown, truncateToWidth, visibleWidth }`;
`extension/pi/v1/selfcheck.ts`: `pi-coding-agent { formatSkillsForPrompt }`;
`extension/pi/v1/foregroundDelegation.ts`: `pi-coding-agent { getAgentDir }`;
`extension/surfaces/surfaces.ts`: `pi-tui { truncateToWidth, visibleWidth }`. The
`satisfies`-pinned `tools/prose-map/selector.ts::TOOL_FIELD_POLICIES` still type-checks, so 1.0.0
adds no new `ToolDefinition` key.

**A6: named guards inside the run (TAP lines):** `ok 295 - production extension sources import
only node:/relative/host specifiers (zero bare npm deps)`, `ok 296 - synthetic positive:
fabricated bare imports … are flagged` (`bareImportGuard`), `ok 2218 - the SDK-resolved pi-ai
exports ./compat (unpinned pi-web-access imports it)` (`piAiCompatGuard`), `ok 802 - a real
codemode script: …` (`perkToolSeam`), `ok 2762 - hostSdkNamespaces: exactly the census keys…`,
and `ok 2849 - census drift guard: …`. The real-runtime tiers (`stageExecutionE2e`,
`sdkAdapter`, `hostSdk`) therefore ran on the 1.0.0 SDK.

**A8: the two named tests, in a targeted re-run** (`uv run pytest -v -n0 -rfEs …`):
`tests/test_packaging.py::test_pi_toolchain_pin_lockstep PASSED`,
`tests/test_native_sdk_bridge_live.py::test_the_installed_pi_subagents_is_the_managed_pin PASSED`,
`tests/test_native_sdk_bridge_live.py::test_real_pi_selfcheck_reports_the_bridge_installed_and_both_consumers_loaded PASSED`
(`3 passed in 1.74s`). The live bridge test resolves `shutil.which("pi")`, so in this shell it
launched the 1.0.0 host.

## Live evidence

### Ledger (C0, A9–A12, B1–B7, Leg I)

| Row | Procedure (host / env) | Observation (verbatim quotes follow the table) | Verdict → owner |
|---|---|---|---|
| C0 | Control: PATH 0.99.2 host, authed, `/probe-spawn workflowScript $MODEL`, 0.73.1 | `ping` success; spawn `success: true` with `data.details.asyncId`/`asyncDir`; workflow `state: "complete"`; lane `{"key": "probe", "ok": true, "error": null, "report": null}`; child dir `8287fb86…` has `status.json` (`state: "complete"`, runner `pid` 80997, `processTerminal.runnerProcessInstanceId` `ae577e0f…`, exit 0, `model: "anthropic/claude-opus-5-5"`); child output `OK`; pi exit 0 after 33 s. **No probe repair was needed** | PASS → no-action |
| A9 | 1.0.0 host, hermetic, `pi --approve --mode json -p /perk-selfcheck`, 0.73.1 | exit 0; `bridge=installed`; both consumer roots under `$WT/.pi/npm/node_modules/`; `npm:pi-subagents@0.73.1=3`, `npm:pi-web-access=1`; `tools: 50 active / 66 registered`; host `$WT/node_modules/@earendil-works/pi-coding-agent/dist/index.js`; 0 `Failed to load extension` | PASS → no-action |
| A10 | Resolver probe: 0.73.1's `resolveHostPeerAliases` against the 1.0.0 package root | `"missing": ["@earendil-works/pi-agent-core/node"]`; the other 12 specifiers (11 `HOST_PEER_ALIASES` + 2 chord − `./node`) resolve to realpaths under the 1.0.0 package | REPRODUCED → 1.2 |
| A11 | RPC spawn on the 1.0.0 host, authed, `$MODEL`, `workflowScript`, 0.73.1 | spawn `success: true` (handle `ddcda0f0…`); workflow `state: "complete"` after 0.4 s; lane `ok: false`, error contains `Background children require the host npm package (@earendil-works/pi-coding-agent) with its dependencies; $WT/node_modules/@earendil-works/pi-coding-agent does not provide @earendil-works/pi-agent-core/node.` (lane `durationMs: 48`, cost 0). The refused child's dir `d8dea062…` holds only `recovery-descriptor.json` + `run-fanout-budget.json`: no `status.json`, no runner logs, no `process-terminal.json`. So the refusal is pre-spawn | REPRODUCED → 1.2 |
| A11x | (unplanned observation in the same A11 launch) | The 1.0.0 parent **did not exit** after the probe's `status` line. Its stderr looped `Extension error (<boundary>): turn_end could not resolve the persisted assistant entry ID` (87×) with `perk: loadout presentation failed — Error: This extension ctx is stale after session replacement or reload. …` (86×) and perk's `Extension error (…/extension/index.ts): This extension ctx is stale …` until the 420 s command timeout killed it. No further JSON events were emitted after the first turn's custom message. See the A11x note below | OBSERVED → 1.2 |
| A12 | `uv run perk doctor --verbose` (+ `--json`), the throwaway's `.venv/bin/perk` 3.9.0, 1.0.0 shell | `✓ subagent-compat: pi-subagents 0.73.1 — the guidance-verified version — report-only — the install is pinned by settings-wiring (npm:pi-subagents@0.73.1)`; `• extension-install: self-repo — local package, no npm install`; `✓ pi: pi ok — $WT/node_modules/.bin/pi`. Other reds are scaffold-only (A12 note) | PASS → no-action |
| B1 | `node --test extension/substrate/nativeSdkBridge.test.ts`, 0.75.0 on disk | `✔ census drift guard: the installed consumers import exactly NATIVE_SDK_CENSUS (11185.211167ms)`; `ℹ tests 32` / `ℹ pass 32` / `ℹ fail 0` / `ℹ skipped 0` | PASS → no-action |
| B2 | A9's command, 0.75.0 staged | identical to A9 except the per-source row reads `npm:pi-subagents@0.75.0=3 (5248c)`; exit 0; 0 `Failed to load extension` | PASS → no-action |
| B3 | Resolver probe against the 0.75.0 install (same module path and export name; anchor `src/runs/background/runner-aliases.js`) | `"missing": []`; all 12 aliases resolve. 0.75.0 marks `./node` `optional: true` and skips an optional subpath the package does not declare (`if (optional && packageDir && target === undefined) continue;`). A declared-but-missing file still fails | PASS → 1.2 |
| B4 | RPC spawn, 1.0.0 host, authed, `workflowScript`, 0.75.0 | `"success": false`, `"code": "invalid_params"`, `"message": "RPC spawn workflowScript was removed; pass inline script text as script."`; no run dir created; pi exit 0 after 6 s | REPRODUCED → 1.2 |
| B5a | RPC spawn, 1.0.0 host, authed, `script`, 0.75.0: launched | spawn `success: true` (handle `50234e24…`, `scriptDigest` `5dc0a658…`); workflow `state: "complete"`; no `pi-agent-core/node` or `Background children require` text anywhere; runner-start witness: child dir `5bf09a8d…` with `status.json` (`pid` 47370, `runnerProcessInstanceId` `ab112456…`, runner exit 0) and runner logs; pi exit 0 after 23 s | PASS → 1.2 |
| B5b | same launch: child completed | lane `{"key": "probe", "ok": true, "error": null, "report": null}`; child `status: "complete"`, `model: "anthropic/claude-opus-5-5"`, `durationMs: 16719`; output `OK` | PASS → 1.2 |
| B6 | RPC spawn, `script`, lane carries `extensionBindings: {"perk.parent-restrictions/1": {readOnly: true}}`, `--approve`, 0.75.0 | The child launched (runner `pid` 48081, `runnerProcessInstanceId` `cec8702a…`) and completed `ok: true` in 5691 ms. Its recovery descriptor carries `"extensionBindings": {"perk.parent-restrictions/1": {"readOnly": true}}`. Its transcript shows perk's `[READ-ONLY MODE] (unscoped)` notice before `OK`, so perk's extension loaded in the child and applied the packet. No trust diagnostic was emitted; `launchResolvedExtensions.effective: ["sha256:045add3c07b4efc5"]`. pi exit 0 after 8 s | OBSERVED → 1.2 |
| B7a | `uv run perk doctor --verbose` (+ `--json`), 0.75.0 staged: `subagent-compat` | `⚠ subagent-compat: pi-subagents 0.75.0 installed — perk's guidance was verified against 0.73.1 — npm:pi-subagents@0.73.1 is the settings pin (settings-wiring); mechanics perk's guidance leans on are source-read-derived at the verified version and unverified at the installed one; 0.74.0+ is known incompatible (it removed the workflowScript RPC spawn parameter perk's waves send)` | REPRODUCED → 1.2 |
| B7b | same doctor run: the edited pin | `✗ settings-wiring: settings-wiring drift — .pi/settings.json: updated npm:pi-subagents@0.75.0 -> npm:pi-subagents@0.73.1; compaction: reserveTokens=65536` and `⚠ artifact-health: artifact health: 6 up-to-date, 1 locally-modified — .pi/settings.json (settings-wiring): locally-modified` | OBSERVED → no-action |
| X1 | print-mode exit on a completed run, both hosts (C0 0.99.2; B5, B6 1.0.0) | Each run emits the pair `Extension error (<boundary>): turn_end could not resolve the persisted assistant entry ID` / `Extension error (…/extension/index.ts): This extension ctx is stale after session replacement or reload. …` exactly once, then exits 0. Present on the 0.99.2 control too, so it predates 1.0.0 | OBSERVED → no-action |
| Leg I | Owner, interactive 1.0.0 session from the throwaway (0.75.0 staged), fullscreen default, then `--tui-mode regular` | Owner's report, verbatim: "everything looked good:", followed by the pasted `/perk-selfcheck` output (`perk: selfcheck — 3.9.0: ok; shared=ok; ambient=reached (append=5359c); agents=reached (files=1); bridge=installed` … `npm:pi-subagents@0.75.0=3 (...` … `native sdk bridge: installed (roots=2, specifiers=8)` … `host: $WT/node_modules/@earendil-works/pi-coding-agent/dist/index.js`). The owner reported no separate per-mode notes | PASS → no-action |

### Verbatim quotes

**Selfcheck summary and census, A9** (B2 is identical except the per-source row reads
`npm:pi-subagents@0.75.0=3 (5248c)`):

```text
perk: selfcheck — 3.9.0: ok; shared=ok; ambient=reached (append=5359c); agents=reached (files=1); bridge=installed
census:
  base-prompt: pi-default (not measured)
  append-system-prompt: 5359c
  context-files: 1 file(s), 6889c — $WT/AGENTS.md=6889c
  skills: 3 visible + 0 hidden; prompt-section=1861c
  tools: 50 active / 66 registered; schemas=57880c; guidelines=0c; snippets=4448c
    per source: ..=37 (40160c); builtin=5 (3327c); npm:@ff-labs/pi-fff=2 (3134c); npm:@juicesharp/rpiv-ask-user-question=1 (3761c); npm:@juicesharp/rpiv-todo=1 (1936c); npm:pi-subagents@0.73.1=3 (5248c); npm:pi-web-access=1 (314c)
  discovery: cohort (family: objective_stack_status, collect_review_wave, collect_draft_review_wave, push_annotations)
  branch: 4 entries; binding-header-copies=0
    perk contexts: none; other custom_message ×0 (0c)
  native sdk bridge: installed (roots=2, specifiers=8)
    host: $WT/node_modules/@earendil-works/pi-coding-agent/dist/index.js
    roots: 2 — $WT/.pi/npm/node_modules/pi-subagents, $WT/.pi/npm/node_modules/pi-web-access
```

**A10, the host-alias census against the 1.0.0 root.** For brevity, `<PCA>` stands for
`$WT/node_modules/@earendil-works/pi-coding-agent` and `<NM>` for `<PCA>/node_modules`:

```json
{
  "aliases": {
    "@earendil-works/pi-coding-agent": "<PCA>/dist/index.js",
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
  "missing": [
    "@earendil-works/pi-agent-core/node"
  ]
}
```

B3's output has the same 12 `aliases` entries and `"missing": []`. The 1.0.0 nested
`pi-agent-core/package.json` `exports` keys are `.` and `./package.json` only. The 1.0.0 host is
not pre-chord (its version does not match `^0\.(\d+)\.\d+$`), so both chord aliases are required
and resolve.

**C0 spawn reply** (`data.details`, abridged to the handle fields) and **lane row**:

```text
"success": true,
"details": { "mode": "workflow", "runId": "13d96661-f47f-4d24-9ac7-a1b308c54d00",
  "asyncId": "13d96661-f47f-4d24-9ac7-a1b308c54d00",
  "asyncDir": "$SCRATCH/subagents-tmp/async-subagent-runs/13d96661-f47f-4d24-9ac7-a1b308c54d00", … }
status: "state": "complete" … "workflow": { "value": [ { "key": "probe", "ok": true, "error": null, "report": null } ] }
```

C0 child directory `async-subagent-runs/8287fb86-6559-4cbe-acdb-827d84ee8f8c/`: `control/`,
`events.jsonl`, `output-0.log`, `process-terminal-candidate.json`, `process-terminal.json`,
`recovery-descriptor.json`, `result-index/`, `result-pending/`, `run-fanout-budget.json`,
`runner.stderr.log` (empty), `runner.stdout.log` (empty), `status.json`,
`subagent-log-8287fb86….md`. `output-0.log` reads `Task: Reply with exactly the single word OK
and nothing else. Do not read any file.` / `OK`.

**A11 lane error (full):**

```text
Run fan-out: 1/64 used, 63 remaining
Failed to start async run 'd8dea062-28fe-457c-b579-1706c51c1a5d': Background children require the host npm package (@earendil-works/pi-coding-agent) with its dependencies; $WT/node_modules/@earendil-works/pi-coding-agent does not provide @earendil-works/pi-agent-core/node.
```

`async-subagent-runs/` before A11: `13d96661…`, `8287fb86…` (C0). After A11: those two plus
`d8dea062-28fe-457c-b579-1706c51c1a5d` (only `recovery-descriptor.json`, `run-fanout-budget.json`)
and `ddcda0f0-09bf-4cc2-b7da-8b70070db3ab` (the workflow). The pre-spawn model selection passed:
the recovery descriptor records `"model": "anthropic/claude-opus-5-5"`, `"modelOrigin":
"explicit"`.

**B4 reply:**

```json
{ "version": 1, "requestId": "cb4a6b3e-b327-433f-b4b6-b433d2452466", "method": "spawn", "success": false,
  "error": { "code": "invalid_params", "message": "RPC spawn workflowScript was removed; pass inline script text as script." } }
```

**B5 reply (handle) and lane row:**

```text
"success": true,
"details": { "mode": "workflow", "runId": "50234e24-f3d7-42c5-88f1-35001b427826",
  "asyncId": "50234e24-f3d7-42c5-88f1-35001b427826",
  "asyncDir": "$SCRATCH/subagents-tmp/async-subagent-runs/50234e24-f3d7-42c5-88f1-35001b427826",
  "workflow": { …, "scriptDigest": "5dc0a658d9dd1f46a29bf3987b42cc90ad635a09e8af476a785ac0c977d6189e" }, … }
status: "state": "complete" … "workflow": { "value": [ { "key": "probe", "ok": true, "error": null, "report": null } ] }
```

B5 child directory `async-subagent-runs/5bf09a8d-10ab-466a-9513-168c5e13cfd9/` has the same 13
entries as C0's. Its `status.json` reads `"state": "complete"`, `"pid": 47370`,
`processTerminal.state: "observed"`, runner instance `ab112456-18a1-46fb-b4ca-0aa198a975f5`
`exitCode: 0`. `output-0.log` reads `… Do not read any file.` / `OK`. The 0.75.0 `ping` reply
(B4–B6) matches 0.73.1's (C0) field for field, apart from request and session ids.

**B6 child transcript (`output-0.log`, 1628 bytes; B5's is 87 bytes):**

```text
Task: Reply with exactly the single word OK and nothing else. Do not read any file.
[READ-ONLY MODE] (unscoped)
You are in perk read-only mode — a structurally enforced exploration mode (not advisory):
- edit/write are blocked; bash is restricted to an allowlist of read-only commands.
…
Do not attempt to make changes.
OK
```

### Notes on the unplanned and partial observations

- **A11x: a headless parent that does not exit after a refused lane.** Measured: the loop above.
  Pi 1.0.0 printed the `turn_end` boundary error 87 times. perk's `prepareLoadout` hook
  (`extension/substrate/toolGating.ts:438`, `perk: loadout presentation failed — …`) logged 86
  times, each time over a stale extension ctx. Comparison runs: C0 (0.99.2, completed lane), B5
  and B6 (1.0.0, completed lanes) each printed the exit pair (X1) once and exited 0 in 33 s, 23 s
  and 8 s. B4 (1.0.0, no run) exited 0 in 6 s. Source-derived context, not measured:
  pi-subagents 0.73.1 runs `drainOutstandingWork` (`src/runs/background/auto-drain.js`, default
  timeout 30 min) from its `agent_end` handler when `!ctx.hasUI`. In Pi 1.0.0, `prepareLoadout` is
  invoked while a request's tool loadout is prepared (`dist/core/agent-session.js:1143`).
  **Not established:** the cause; whether the repeated turns issued provider requests (no
  assistant-message event reached stdout); and whether a refused lane would wedge a 0.99.2 parent
  too. That last control cannot be built, because 0.99.2 never refuses. Owner 1.2 adopts 0.75.0,
  which does not refuse on 1.0.0 (B5a). The remaining exposure is the interim remote-runner risk
  in the header.
- **A12: doctor reds outside the two named rows.** `✗ config: config missing —
  .perk/local.toml` is also red in the baseline doctor run in the implement worktree (0.99.2 PATH
  host, `$MAIN/.worktrees/plan-2657`). That run reported `✗ 1 check(s) failed`, i.e. this red is
  pre-existing. Three more reds appear only in the throwaway: `✗ skills-delivery: 32 perk
  skill(s) not delivered …`, `⚠ bindings: bindings: 27 problem(s) …` and `✗ workflow-dir:
  workflow-dir drift — .perk/workflow/: created`. They are artifacts of a hand-made
  `git worktree add`, which never got perk's launch-time skill delivery or workflow dir. They have
  nothing to do with Pi 1.0.0. Owner: no-action.
- **B6 trust state.** Only `--approve` was exercised. 0.74.0's changelog says children now follow
  the parent's project trust. 1.2 covers the other trust states.

## Audit of the smaller released changes

Each row gives the Pi 1.0.0 fact with its citation in the tagged mirror, the installed-dist witness
(`$WT/node_modules/@earendil-works/pi-coding-agent/dist/…`, `grep -n`), perk's assumption and its
anchor (read at `8ddbc2ad`), and one verdict with one owner.

| Row | Pi 1.0.0 fact (source-derived; dist witness) | perk assumption / anchor | Verdict → owner |
|---|---|---|---|
| D1 `--provider` without `--model` | `packages/coding-agent/src/main.ts@v1.0.0:472` `` `--provider requires --model (for example: --provider ${parsed.provider} --model <pattern>)` ``; dist `main.js:363` same | perk never emits `--provider`: `rg -e '"--provider"' src extension` (non-test) has no match. `_build_argv`/`_stage_model_argv` emit only `--model`/`--thinking`; operator `pi_args` pass-through is the only path. Pi's explicit error is the wanted behaviour | PASS → no-action |
| D2 `quietStartup: "header"` | `core/settings-manager.ts@v1.0.0:112` `export type QuietStartup = boolean \| "header";` (`:150` `quietStartup?: QuietStartup; // default: false`); dist `core/settings-manager.d.ts:78` same | `git grep -i quietStartup -- src extension shared .pi tests`: no match; `.pi/settings.json` has no key | PASS → no-action |
| D3 codemode `"name" in tools` | `packages/codemode/src/runtime/prelude-source.ts@v1.0.0:116–133`: `guard()` wraps `tools` in a `Proxy` whose only trap is `get`, which throws `tools.<x> does not exist. …` for an unknown member. The source comment reads "`in` checks still work." Installed `pi-codemode/dist/runtime/prelude-source.js:117` `return new Proxy(target, {` | perk authors no codemode fragment probing an optional member. `git grep -E '"[a-z_]+" in tools'` finds none; the only executable fragments (`extension/pi/perkToolSeam.test.ts:470–473`) call the registered `tools.probe_action`/`tools.probe_query`, green in A6 (`ok 802`) | PASS → no-action |
| D4 Node `>=22.19.0` | `packages/coding-agent/package.json@v1.0.0:106–107` `"node": ">=22.19.0"`, identical at `v0.99.2` (not a 1.0.0 change); installed `{"node":">=22.19.0"}`; also `1.0.2` (registry) | `>=22` everywhere: `src/perk/convergence/env.py:15` `_MIN_NODE_MAJOR = 22` (+ `:5`, `:54`, `:62`, `:106` messages); `package.json` `"engines": {"node": ">=22"}`; `.github/actions/perk-remote-setup/action.yml:20`, `src/perk/run/workflow_artifacts.py:207`, `.github/workflows/ci.yml:31`, `.github/workflows/release.yml:151,183` `node-version: "22"`; `docs/user-docs/reference/requirements-and-compatibility.md:20` "Version 22 or newer" and `:80` "Node 22.15 or newer"; `README.md:59` `node >= 22`; `docs/site/package.json` `>=22.12.0`; `docs/site/README.md:173,313` already names `>=22.19.0`; `.npmrc` `engine-strict=true` | FAIL → 4.1 |
| D5 remote Pi install is unversioned | — (npm `latest` moved 1.0.0 → 1.0.1 → 1.0.2 within three days) | `.github/actions/perk-remote-setup/action.yml:28` and `src/perk/run/workflow_artifacts.py:215` `run: npm install -g @earendil-works/pi-coding-agent`; `requirements-and-compatibility.md:21` "Version 0.99.2 or newer". The remote host gets `latest` (1.0.2 today) with the pinned pi-subagents 0.73.1. That should give A11's refusal and possibly A11x's non-exit (interim operator risk, header) | FAIL → 4.1 |
| D6 fullscreen default | `core/settings-manager.ts@v1.0.0:184` `tuiMode?: TuiMode; // default: "fullscreen"`, `:1349` `=== "regular" ? "regular" : "fullscreen"`; `cli/args.ts@v1.0.0:326` `--tui-mode <mode>              TUI mode: fullscreen (default) or regular`; dist `core/settings-manager.js:951` | `src/perk/convergence/init/settings.py:543–561` `_converge_tui_mode` seeds `"fullscreen"` when absent, which is now the default value. Pi 1.0.0 did not rewrite `.pi/settings.json` (throwaway `git diff` showed only the B-arm pin edit) | OBSERVED → 4.4 |
| D7 MCP factory defaults | `extensions/mcp/index.ts@v1.0.0:69–80` `McpExtensionOptions` defaults: `mcp.json` from the agent dir + trusted project, `credentials` → `mcp-auth.json` in the agent dir, `logPath` → `mcp.log` (`:342` `join(getAgentDir(), "mcp.log")`); `src/index.ts@v1.0.0:408` exports `createMcpExtension, type McpExtensionOptions, type McpTransportFactory`, not `McpOAuthCredentialStore`; dist `index.d.ts:32` same, `grep -c McpOAuthCredentialStore dist/index.d.ts` = 0; `extensions/mcp/oauth.d.ts:9` "Credentials live in `<agent-dir>/mcp-auth.json`, keyed by server name and URL." | perk has no MCP code (`git grep -i -e createMcpExtension -e McpExtensionOptions -e mcp-auth -- src extension`: no match); the worker supplies no factories | OBSERVED → 3.3 |
| D8 MCP restoration window | `core/agent-session.ts@v1.0.0:431` `private _pendingToolNames = new Set<string>();`, `:1494` `if (previous.some((name) => !active.has(name))) this._pendingToolNames.clear();`, `:3542` `nextActiveToolNames.push(...this._pendingToolNames);` (0 occurrences at `v0.99.2`); dist `core/agent-session.js:141,1091,2852` | perk reconciles active tools with `pi.setActiveTools` (`extension/substrate/toolGating.ts:247,249,417`). A reconciliation that deactivates any tool clears Pi's pending-restoration set | OBSERVED → 2.2 |
| D9 removed `pi-agent-core` subpaths: perk | `packages/agent/package.json@v1.0.0` `exports`: `.` and `./package.json` (at `v0.99.2` also `./node ./harness/context ./experimental/pico3 ./harness/env/nodejs ./harness/runtime/reducer ./harness/session ./harness/session/testing`); installed top-level and nested agent-core: `. ./package.json` | perk imports none of them: `bareImportGuard` (A6 `ok 295`/`ok 296`) and A1 green | PASS → no-action |
| D10 removed `pi-agent-core` subpaths: supplier | same fact | 0.73.1 requires `./node` | REPRODUCED → 1.2 (= A10 + A11; not double-counted) |
| D11 `pi-ai` `./compat`, `./oauth`, `./providers/*`; chord `.`/`./context` | `packages/ai/package.json@v1.0.0` exports `. ./models ./compat ./providers/* ./api/* ./utils/* ./oauth ./bedrock-provider ./bun-oauth`; installed nested pi-ai identical; installed nested chord `. ./context ./delta ./bundler ./node ./package.json` | 0.73.1's aliases for these all resolve (A10); `piAiCompatGuard` green (A6 `ok 2218`) | PASS → no-action |
| D12 bare-import census | — | `extension/bareImportGuard.test.ts` (A6 `ok 295`/`ok 296`) | PASS → no-action (= A6) |
| D13 `NATIVE_SDK_CENSUS` vs 0.73.1 | — | A7 | PASS → no-action (= A7) |
| D14 `NATIVE_SDK_CENSUS` vs 0.75.0 | — | B1 | PASS → no-action (= B1) |
| D15 `pi-client`/`pi-server` 1.0.0 | installed at 1.0.0 (pi-client pulls `pi-protocol` 1.0.1) | perk imports neither (`git grep -e @earendil-works/pi-client -e @earendil-works/pi-server -- extension src tools docs/site packages shared ':!*.md'`: no match); A1 green | OBSERVED → 4.2 |
| D16 TUI/theme on 1.0.0 (fullscreen + regular, perk footer/status/widgets) | fullscreen default (D6) | surfaces charter (`docs/design/tui-charter.md`) | PASS → no-action (= Leg I) |

**Changelog note (source-derived).** The removal of the subpaths is **documented**, but only in
`packages/agent/CHANGELOG.md@v1.0.0` (`### Breaking Changes`): "… The `./node`, `./harness/*`,
and `./experimental/pico3` subpath exports are gone. The package now contains only `Agent`, the
agent loop, the proxy stream, and their types. Use `@earendil-works/pi-durable` for durable
sessions." `packages/coding-agent/CHANGELOG.md@v1.0.0`'s 1.0.0 section does not mention it. The
installed `pi-agent-core` package ships no `CHANGELOG.md`, so this fact has no dist witness.

**pi-subagents 0.74.0 / 0.75.0 changelog (installed `CHANGELOG.md`).** Headings: `## [0.75.0] -
2026-10-02` (`### Highlights`, `### Added`, `### Changed`, `### Fixed`); `## [0.74.0] -
2026-09-30` (same four). Neither release has a `### Removed` section. The one removal is in
0.74.0 `### Changed`: "**Breaking:** … The `workflowScript` and `workflowScriptPath` parameters
were removed, and calls that still pass them fail with an error that shows the new forms. RPC
`spawn` takes inline script text as `script` and a path or workflow name as `workflow`." 0.75.0
`### Fixed`: "Background subagents failed to start on Pi 1.0.0 with "does not provide
@earendil-works/pi-agent-core/node", because Pi 1.0.0 no longer ships that module. They now start
without it, and still fail if Pi includes the module but the file is missing." Supplier resources:
the `pi.{extensions,skills,prompts}` manifest field and `peerDependencies` are identical between
0.73.1 and 0.75.0. The `skills/`, `prompts/` and `agents/` file lists are identical too: nothing
was removed. Content changed in `skills/council-mode/SKILL.md`, `skills/pi-subagents/SKILL.md`,
five `skills/pi-subagents/references/*.md`, and `prompts/review-loop.md`.

## The ledger

Every finding, each with exactly one verdict and one owner. D10, D12, D13, D14 and D16 restate a
measured row and appear here only through that row.

| Row | Finding | Verdict | Owner |
|---|---|---|---|
| C0 | The probe launches and completes a child on 0.99.2 + 0.73.1 (instrument valid, no repair) | PASS | no-action |
| A1 | tsc green at 1.0.0 types | PASS | no-action |
| A2 | prose-review workspace tsc green | PASS | no-action |
| A3 | docs-site astro sync + tsc green | PASS | no-action |
| A4 | ty green | PASS | no-action |
| A5 | ruff + Biome green | PASS | no-action |
| A6 | node:test 3655/3655, 0 skipped, on the 1.0.0 SDK | PASS | no-action |
| A7 | census drift guard vs 0.73.1 | PASS | no-action |
| A8 | pytest 8242 passed (live bridge smoke on the 1.0.0 host; pin-lockstep at 1.0.0) | PASS | no-action |
| A9 | perk loads on 1.0.0 with 0.73.1; bridge installed | PASS | no-action |
| A10 | 0.73.1 resolver: `missing: ["@earendil-works/pi-agent-core/node"]` | REPRODUCED | 1.2 |
| A11 | 0.73.1 real spawn on 1.0.0 refused pre-spawn with the alias sentence | REPRODUCED | 1.2 |
| A11x | headless 1.0.0 parent did not exit after the refused lane (cause unattributed) | OBSERVED | 1.2 |
| A12 | doctor on 1.0.0 + 0.73.1: `subagent-compat` ✓, `extension-install` self-repo | PASS | no-action |
| B1 | census drift guard vs 0.75.0 | PASS | no-action |
| B2 | perk loads on 1.0.0 with 0.75.0; bridge installed | PASS | no-action |
| B3 | 0.75.0 resolver: `missing: []`; `./node` optional-when-undeclared | PASS | 1.2 |
| B4 | 0.75.0 rejects `workflowScript`: `invalid_params` / "RPC spawn workflowScript was removed; pass inline script text as script." | REPRODUCED | 1.2 |
| B5a | 0.75.0 launches a background child on 1.0.0 (runner-start witness) | PASS | 1.2 |
| B5b | that child completes `OK` | PASS | 1.2 |
| B6 | restriction packet under 0.75.0 + `--approve`: child launched, perk read-only notice applied | OBSERVED | 1.2 |
| B7a | doctor `subagent-compat` warns on 0.75.0 with the 0.74.0+ incompatibility text (the stamp 1.2 retires) | REPRODUCED | 1.2 |
| B7b | doctor `settings-wiring` drift + `artifact-health` locally-modified on the edited pin | OBSERVED | no-action |
| X1 | print-mode exit pair (`turn_end` boundary error + perk stale-ctx error), once per completed run on both hosts | OBSERVED | no-action |
| Leg I | interactive 1.0.0 TUI (fullscreen + regular), owner-reported "everything looked good" | PASS | no-action |
| D1 | `--provider` without `--model` errors; perk never emits it | PASS | no-action |
| D2 | `QuietStartup` gains `"header"`; perk never touches it | PASS | no-action |
| D3 | codemode `tools` Proxy throws on unknown members; perk has no optional-member probe | PASS | no-action |
| D4 | Pi requires Node `>=22.19.0`; perk declares `>=22` at every site | FAIL | 4.1 |
| D5 | remote runner installs Pi `latest` unversioned (interim risk with 0.73.1) | FAIL | 4.1 |
| D6 | `tuiMode` fullscreen is now Pi's default; perk still seeds it | OBSERVED | 4.4 |
| D7 | MCP factory defaults to the global agent dir; `McpOAuthCredentialStore` not root-exported | OBSERVED | 3.3 |
| D8 | `_pendingToolNames` restoration set cleared on any deactivation | OBSERVED | 2.2 |
| D9 | removed `pi-agent-core` subpaths: perk imports none | PASS | no-action |
| D11 | `pi-ai` `./compat`/`./oauth`/`./providers/*`, chord `.`/`./context` still exported | PASS | no-action |
| D15 | `pi-client`/`pi-server` installed at 1.0.0, unused by perk | OBSERVED | 4.2 |

Tally: PASS 22 (C0, A1–A9, A12, B1, B2, B3, B5a, B5b, Leg I, D1, D2, D3, D9, D11); FAIL 2 (D4,
D5); REPRODUCED 4 (A10, A11, B4, B7a); OBSERVED 8 (A11x, B6, B7b, X1, D6, D7, D8, D15);
UNOBSERVED 0. Every planned row ran, so none is a dependent `UNOBSERVED — NOT PASSED` row.

### 4.2: typecheck and test fixes 1.0.0 types force

**None.** At the 1.0.0 pins, with no source change, these are green: `npm run typecheck` (A1),
`npm run prose-review:typecheck` (A2), `npm run docs:typecheck` (A3), `just typecheck-py` (A4),
`just lint` (A5), the full node:test glob (A6) and the full pytest suite (A8).
`test_pi_toolchain_pin_lockstep` passes at 1.0.0. Inputs for 4.2's pin move (not fixes):

- The lockfile churn preview from the snapshot matrix. Besides the 16 `@earendil-works/*`
  entries, npm re-resolved 17 `@aws-sdk/*`, 3 `@smithy/*` and `ws` to newer patches and dropped
  `ignore`. The 0.99.2 record trimmed such incidental re-resolutions back to base.
- Top-level `chord`, `pi-telemetry` and `pi-protocol` resolved to **1.0.1**, while
  pi-coding-agent's nested copies are 1.0.0.
- Pi 1.0.1 and 1.0.2 now exist. 4.2 chooses the target; this record certifies only 1.0.0.

## Falsified planning-time assumptions

1. **"The 1.0.0 CHANGELOG section does not mention" the `./node` removal.** That holds only for
   `packages/coding-agent/CHANGELOG.md`. `packages/agent/CHANGELOG.md@v1.0.0` documents it
   explicitly under `### Breaking Changes` (quoted above).
2. **"No child run directory appears (the refusal is pre-spawn)" (A11).** A directory does
   appear: `d8dea062…/` with `recovery-descriptor.json` and `run-fanout-budget.json`. The
   refusal is still pre-spawn: there is no `status.json`, runner log or process-terminal proof,
   and the lane failed in 48 ms.
3. **"Pi latest = 1.0.0 today" (D5).** npm `latest` was 1.0.1 at Step 0 (published
   2026-10-03T12:35Z) and 1.0.2 at authoring time (published 2026-10-04T00:56Z).
4. **An implicit expectation that a refused lane would let the print-mode parent exit like a
   completed one.** A11x: it did not. This was not stated in the plan, but the procedure (one
   command per row, no watchdog) assumed it. B4–B6 then ran under a watchdog (methodology).
5. The planning-time session model (`anthropic/claude-fable-5-1`) was not the implement
   session's. `$MODEL` was `anthropic/claude-opus-5-5`, read at Step 0 as the procedure
   prescribes. This is not a contradiction, only a different value.
6. Confirmed rather than falsified, recorded for completeness: tsc green at 1.0.0; the drift guard
   passes against 0.75.0; `pi.events.on` returns an unsubscribe on both hosts (C0 needed no
   repair); `status.json` carries `state` with terminal value `complete`; a `runs.all` item
   accepts `model` (the child's `status.json` and recovery descriptor record
   `anthropic/claude-opus-5-5`, `modelOrigin: "explicit"`).

## Methodology appendix

### Scaffold (Steps 0–1)

```sh
# Step 0 (implement worktree): registry, mirror tag, HEAD, PATH pi, MODEL, MAIN staging hashes
npm view @earendil-works/pi-coding-agent versions --json | tail -5
npm view pi-subagents versions --json | tail -3
git -C "$MAIN/docs/library/source-code/github.com/earendil-works/pi" rev-parse v1.0.0   # a13d35a7…
git rev-parse HEAD; which pi; readlink -f "$(which pi)"; pi --version; node --version
MODEL="$PI_PROVIDER/$PI_MODEL"                                                      # anthropic/claude-opus-5-5
shasum -a 256 "$MAIN/.pi/npm/package.json" "$MAIN/.pi/npm/package-lock.json" \
  "$MAIN/.pi/npm/node_modules/.package-lock.json" "$MAIN/.pi/npm/node_modules/pi-subagents/package.json"
# Step 1
git worktree add --detach "$WT" HEAD && mkdir -p "$SCRATCH/subagents-tmp"
(cd "$WT" && uv sync --all-packages && npm ci)
(cd "$WT" && npm install --save-dev --save-exact @earendil-works/pi-coding-agent@1.0.0 @earendil-works/pi-ai@1.0.0 \
  @earendil-works/pi-tui@1.0.0 @earendil-works/pi-server@1.0.0 @earendil-works/pi-client@1.0.0 @earendil-works/pi-agent-core@1.0.0)
cp -R "$MAIN/.pi/npm" "$WT/.pi/npm"            # independent copy, never the hardlink materializer
export PATH="$WT/node_modules/.bin:$PATH"      # the 1.0.0 host, per shell
HERMETIC=$(mktemp -d -t perk-pi1-hermetic); AUTHED=$(mktemp -d -t perk-pi1-authed)
cp "$MAIN/.pi/agent/auth.json" "$AUTHED/auth.json"   # credentials only (providers: openai, anthropic; api_key)
# Step 5.1 (arm B)
sed -i '' 's/"npm:pi-subagents@0.73.1"/"npm:pi-subagents@0.75.0"/' "$WT/.pi/settings.json"
rm -rf "$WT/.pi/npm/node_modules/pi-subagents"
(cd "$WT" && npm install pi-subagents@0.75.0 --prefix .pi/npm --legacy-peer-deps)
```

### Launch environments

`$SCRUB` (prepended to every manually launched `pi`):

```sh
env -u PERK_RUN_ID -u PERK_PROFILE_HANDOFF -u PERK_SELFCHECK -u PERK_DISABLE_NATIVE_SDK_BRIDGE \
  -u PERK_CLI_VERSION -u PI_SUBAGENT_CHILD -u PI_SUBAGENT_CHILD_AGENT -u PI_SUBAGENT_EXTENSION_BINDINGS \
  -u PI_SESSION_FILE -u PI_SESSION_ID -u PI_MODEL -u PI_PROVIDER -u PI_REASONING_LEVEL -u PI_CODING_AGENT
```

The `PI_*`/`PERK_*` names in each launched environment, as recorded by `env | grep -E
'^(PI_|PERK_)' | sort` after the scrub (no credential is env-borne):

| Legs | Host | `PI_*` / `PERK_*` after `$SCRUB` |
|---|---|---|
| C0 | PATH 0.99.2 (no prefix; verified `which pi` = mise path, `pi --version` = 0.99.2) | `PERK_SKIP_VERSION_CHECK=1`, `PI_CODING_AGENT_DIR=$AUTHED`, `PI_SUBAGENTS_TEMP_ROOT=$SCRATCH/subagents-tmp` |
| A9, B2 (hermetic) | 1.0.0 | `PERK_SKIP_VERSION_CHECK=1`, `PI_CODING_AGENT_DIR=$HERMETIC`, `PI_OFFLINE=1`, `PI_SUBAGENTS_TEMP_ROOT=$SCRATCH/subagents-tmp` (+ `ANTHROPIC_API_KEY=perk-live-smoke-placeholder-never-sent`) |
| A11, B4, B5, B6 (authed) | 1.0.0 | `PERK_SKIP_VERSION_CHECK=1`, `PI_CODING_AGENT_DIR=$AUTHED`, `PI_SUBAGENTS_TEMP_ROOT=$SCRATCH/subagents-tmp` |
| Leg I (authed) | 1.0.0, `$WT/node_modules/.bin/pi --approve` (then `--tui-mode regular`) | same as the authed row |

Inside each process, the probe's `env` dump also shows `PI_CODING_AGENT: "true"`. Pi sets it in
process; it is not inherited. The offline checks (A1–A8) and doctor runs (A12, B7) inherited the
implement session's environment unscrubbed, as a `run_ci` run would, with the PATH prefix and
(A8) an exported `PI_SUBAGENTS_TEMP_ROOT`. The live bridge test builds its own scrubbed env.

Commands (from `$WT`):

```sh
$SCRUB <authed> pi --approve --mode json -e .perk-characterization/probe-spawn.ts -p "/probe-spawn workflowScript $MODEL"   # C0 (0.99.2), A11 (1.0.0), B4
$SCRUB <hermetic> pi --approve --mode json -p /perk-selfcheck                                                               # A9, B2
$SCRUB <authed> pi --approve --mode json -e .perk-characterization/probe-spawn.ts -p "/probe-spawn script $MODEL"            # B5
$SCRUB <authed> pi --approve --mode json -e .perk-characterization/probe-spawn.ts -p "/probe-spawn script $MODEL restricted" # B6
```

### The resolver probe (A10, B3; absolute paths)

```sh
node --input-type=module -e 'import { resolveHostPeerAliases } from "$WT/.pi/npm/node_modules/pi-subagents/src/runs/background/runner-aliases.js"; console.log(JSON.stringify(resolveHostPeerAliases("$WT/node_modules/@earendil-works/pi-coding-agent"), null, 2))'
```

The module path and the export name are unchanged in 0.75.0 (`grep -rl "pi-agent-core/node"
.pi/npm/node_modules/pi-subagents/src --include=*.js` → `src/runs/background/runner-aliases.js`).

### The probe extension (verbatim; no C0 repair was applied)

```ts
// .perk-characterization/probe-spawn.ts — throwaway; drives pi-subagents' v1 RPC exactly as
// extension/waves/rpcAdapter.ts does (same envelope; the run handle lives in
// data.details), with either spawn key and a pinned lane model, and waits for the run to settle
// so the in-process workflow host is not killed by print-mode exit.
//   /probe-spawn <workflowScript|script> <provider/model> [restricted]
import { randomUUID } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const REQUEST = "subagents:rpc:v1:request";
const REPLY = "subagents:rpc:v1:reply:";
const log = (label: string, value: unknown) =>
  console.error(`probe: ${label} ${JSON.stringify(value, null, 2)}`);

interface Reply {
  success?: boolean;
  data?: { text?: string; details?: { asyncId?: string; asyncDir?: string } };
  error?: { code?: string; message?: string };
}

function call(pi: ExtensionAPI, method: string, params?: unknown, timeoutMs = 30_000): Promise<Reply> {
  const requestId = randomUUID();
  return new Promise((resolve) => {
    const off = pi.events.on(`${REPLY}${requestId}`, (data: unknown) => {
      clearTimeout(timer);
      off();
      resolve(data as Reply);
    });
    const timer = setTimeout(() => { off(); resolve({ error: { code: "probe-timeout", message: method } }); }, timeoutMs);
    pi.events.emit(REQUEST, { version: 1, requestId, method, ...(params === undefined ? {} : { params }), source: { extension: "perk-probe" } });
  });
}

// Terminal-state vocabulary as observed in status.json; C0 validates it (adapt + record if wrong).
const TERMINAL = new Set(["complete", "completed", "failed", "partial", "stopped", "cancelled", "error"]);
async function settle(asyncDir: string, timeoutMs = 180_000): Promise<unknown> {
  const statusPath = join(asyncDir, "status.json");
  const until = Date.now() + timeoutMs;
  let last: unknown = null;
  while (Date.now() < until) {
    if (existsSync(statusPath)) {
      last = JSON.parse(readFileSync(statusPath, "utf8"));
      const state = (last as { state?: string }).state ?? "";
      if (TERMINAL.has(state)) return last;
    }
    await new Promise((r) => setTimeout(r, 2000));
  }
  return { probeTimeout: "settle", last };
}

export default function (pi: ExtensionAPI) {
  pi.registerCommand("probe-spawn", {
    description: "characterization probe: ping + spawn one scout lane via the v1 RPC",
    handler: async (args) => {
      const [key = "workflowScript", model = "", mode = ""] = args.trim().split(/\s+/);
      if (!model) { log("probe-error", "usage: /probe-spawn <workflowScript|script> <provider/model> [restricted]"); process.exitCode = 2; return; }
      const item = {
        key: "probe", agent: "perk.scout", label: "probe", worktree: false, model,
        task: "Reply with exactly the single word OK and nothing else. Do not read any file.",
        ...(mode === "restricted" ? { extensionBindings: { "perk.parent-restrictions/1": { readOnly: true } } } : {}),
      };
      const script =
        `const reports = await runs.all(${JSON.stringify([item], null, 2)});\n` +
        "return reports.map(({key, ok, error, structuredOutput}) => ({key, ok, error: error ?? null, report: structuredOutput ?? null}));";
      log("env", Object.fromEntries(Object.entries(process.env).filter(([k]) => /^(PI_|PERK_)/.test(k))));
      log("ping", await call(pi, "ping"));
      const reply = await call(pi, "spawn", {
        [key]: script, async: true, mission: false, context: "fresh", model,
        acceptance: { level: "none", reason: "characterization probe" },
        intercomBridge: { mode: "off" }, timeoutMs: 120_000,
      });
      log(`spawn(${key}, ${model}${mode ? `, ${mode}` : ""})`, reply);
      if (reply.success !== true) return; // the rejection itself is the evidence (B4) or a FAIL row
      const details = reply.data?.details;
      if (typeof details?.asyncId !== "string" || typeof details?.asyncDir !== "string") {
        log("probe-error", "success reply without data.details.asyncId/asyncDir — handle extraction wrong, fix the probe");
        process.exitCode = 2;
        return;
      }
      log("status", await settle(details.asyncDir));
    },
  });
}
```

### The watchdog added after A11 (B4–B6)

After A11x, each spawn leg on the 1.0.0 host ran under this wrapper. The watchdog never fired:
B4 exited in 6 s, B5 in 23 s and B6 in 8 s, all with code 0.

```bash
#!/usr/bin/env bash
# run-bounded.sh <log> <cmd...> — runs cmd (output appended to log) in its own process group; once the
# probe has reported its terminal line (probe: status / a non-success spawn reply / probe-error) it
# allows GRACE seconds for a clean exit, and caps the whole run at CAP seconds; on either limit it
# TERMs (then KILLs) the process group and records the watchdog action.
log=$1; shift
GRACE=${GRACE:-60}; CAP=${CAP:-330}
set -m
"$@" >>"$log" 2>&1 &
pid=$!; start=$(date +%s); terminal_at=""
while kill -0 "$pid" 2>/dev/null; do
  now=$(date +%s)
  if [ -z "$terminal_at" ] && { grep -q '^probe: status' "$log" || grep -q '^probe: probe-error' "$log" || { grep -q '^probe: spawn(' "$log" && grep -q '"success": false' "$log"; }; }; then terminal_at=$now; fi
  if [ -n "$terminal_at" ] && [ $((now - terminal_at)) -ge "$GRACE" ]; then echo "watchdog: pi still running ${GRACE}s after the probe's terminal line (elapsed $((now - start))s) — TERM pgid $pid" >>"$log"; kill -TERM -- "-$pid" 2>/dev/null; sleep 5; kill -KILL -- "-$pid" 2>/dev/null; break; fi
  if [ $((now - start)) -ge "$CAP" ]; then echo "watchdog: cap ${CAP}s reached — TERM pgid $pid" >>"$log"; kill -TERM -- "-$pid" 2>/dev/null; sleep 5; kill -KILL -- "-$pid" 2>/dev/null; break; fi
  sleep 2
done
wait "$pid"; rc=$?
echo "exit=$rc elapsed=$(( $(date +%s) - start ))s" >>"$log"
```

### Deviations from the plan's procedure

- **A6.** The recipe's command line ran unchanged, plus
  `--test-reporter=tap --test-reporter-destination=<file>` beside the `dot` reporter (sent to
  `stdout`), to get counts.
- **A8.** `-rfEs` was added to the full run. The two named tests then got a targeted `-v -n0`
  re-run to record their individual `PASSED` lines.
- **A11.** It ran without a watchdog. The harness's 420 s command timeout killed the non-exiting
  parent, so the block's trailing directory listing was captured post hoc. B4–B6 used
  `run-bounded.sh`.
- **A12 provenance.** One extra baseline doctor run in the implement worktree (0.99.2 PATH host)
  classified the doctor reds.
- **Leg I.** The command also named the absolute `$WT/node_modules/.bin/pi`, so `env` could not
  resolve a different `pi`.
- **Agent dirs.** They were created as `mktemp -d -t perk-pi1-{hermetic,authed}` under the
  per-user `$TMPDIR`.
- **Registry.** It was re-read at authoring time (Pi 1.0.2 appeared mid-experiment).
- **Excerpts.** `rg`/`git grep` excerpts in the audit were read at `8ddbc2ad` in the implement
  worktree, which is identical to the throwaway's tracked tree.

### Teardown proof (Step 9)

```text
=== 2026-10-04T19:28:02Z  9.1 pgrep -fl "$SCRATCH" (before)            → (none) pgrep exit=1
                          pgrep -fl "pi-1.0.0-characterization"          → (none) pgrep exit=1
                          pgrep -fl "perk-pi1"                           → (none) pgrep exit=1
=== 9.2 git worktree remove --force "$WT"    exit=0
        git worktree prune                   exit=0
        rm -rf "$HERMETIC" "$AUTHED"         exit=0  (ls: … No such file or directory, both)
        ls -d "$WT"                          → No such file or directory
=== 9.1 re-check (after)                     → (none) pgrep exit=1, (none) pgrep exit=1
=== 9.3 MAIN staging hashes (after teardown)
eb487ac34430113f7a9b0889cc9e6390d13f619bf77c92cdf3df32d0d8444ad0  $MAIN/.pi/npm/package.json
3efbddc27643abb1b4befc5bcd15fdfdc0901f0731e318ba78c4064aec93f6c6  $MAIN/.pi/npm/package-lock.json
a44bd4b4f6af44715fc0383f19e99edb2f84898694291f121323d08feeeb00fd  $MAIN/.pi/npm/node_modules/.package-lock.json
12ddb98564785d4d012c308a07fe286aa2f0d463fe8af70012813af4cf17e193  $MAIN/.pi/npm/node_modules/pi-subagents/package.json
    (identical to Step 0 and to the Step 5.1 non-contamination check)
=== git -C "$MAIN" status --porcelain        → (empty; also empty at Step 0)
=== git worktree list                        → 140 entries, 0 matching pi-1.0.0-characterization;
                                               the `worktree` path set is identical to the pre-experiment set
=== ls "$MAIN/.worktrees"                    → plan-1416 plan-1697 plan-2299 plan-2300 plan-2386 plan-2641
                                               plan-2643 plan-2645 plan-2647 plan-2649 plan-2652 plan-2654
                                               plan-2657 review-2243 review-2246 review-2249 worktrees
                                               (the pre-experiment listing minus pi-1.0.0-characterization)
=== git -C <implement worktree> status --porcelain → (empty before this record was written)
```

Removing the worktree deleted `$SCRATCH`, including the experiment-local pi-subagents temp root
(final run listing: `06433335…`, `13d96661…`, `1d7947c3…`, `50234e24…`, `5bf09a8d…`,
`8287fb86…`, `d8dea062…`, `ddcda0f0…`) and both throwaway agent dirs (sessions and
`auth.json` copy). The probe, the watchdog, the logs and the throwaway `package*.json` /
`.pi/settings.json` edits went with it. Only this text survives.
