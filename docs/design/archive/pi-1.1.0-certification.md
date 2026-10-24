# Certification: Pi 1.1.0 + pi-subagents 0.76.1 on the landed tree

**Status:** dated evidence record. Measured 2026-10-23T23:51Z → 2026-10-24T03:36Z in one sitting.
Executor legs ran 23:51–00:58Z; owner legs ran 00:58–03:20Z; E1 and teardown ran 03:29–03:36Z.
Authored 2026-10-24.

The record measures perk 4.0.0 at **H0 = `497021367f7d4bd784c3123c611b4834480a702e`**
(`origin/main` at Step 0 = the implement branch's base = `$MAIN` HEAD) against:

- the operator's PATH **Pi 1.1.0**, installed with `PI_INSTALL_COMMAND` in the eight-sibling global
  layout;
- **pi-subagents 0.76.1**, staged in `$WT/.pi/npm` (APFS clonefile), `$MAIN/.pi/npm` and
  `$CLONE/.pi/npm`.

No H0′ was adopted. The drift gate (`git fetch origin && git diff --name-only H0 origin/main`) came
back **empty** at all three points it ran: the P2 staging (00:13:42Z), R1 (00:50:04Z) and the
codemode `perk plan` session (02:33:27Z). Every leg therefore ran at H0:

- `$WT` merge-base = H0.
- `$MAIN` HEAD = H0.
- `$CLONE` was detached at H0, and `plan-2759` was pre-pushed at H0.
- The R1/R2 remote job logs show checkout SHAs H0 and `6a238632` (consumer).

Blob hashes at H0 (`git rev-parse H0:<path>`):

| Path | Blob |
|---|---|
| `src/perk/substrate/pi_host.py` | `3e7f6fa2f04be7312b26e73141dffd74d0a03a26` |
| `src/perk/convergence/init/settings.py` | `7de1331f0cdb423fcab360f667d8b0685197cdbc` |
| `shared/host-floor.yaml` | `58441a8e651d0928b8c2171471be02b19d8b132a` |
| `.pi/settings.json` | `50da88fda04df3e10d80aaad6fa1cb73f8098af0` |
| `.github/actions/perk-remote-setup/action.yml` | `c6d44a11556e9f73ccc1d1530e513a1ab337b23c` |
| `src/perk/run/launch/materialize.py` | `dda49348d8de4a7e018c3bbf2f93d9a51b3e50f9` |

**Precedents:**

- [`pi-1.0.0-certification.md`](pi-1.0.0-certification.md): the row shape, the five
  browser-door criteria and the probe-spawn instrument.
- [`pi-1.0.0-characterization.md`](pi-1.0.0-characterization.md): the watchdog and the scrubbed
  environment.
- [`pi-1.1.0-characterization.md`](pi-1.1.0-characterization.md): T11, carried.
- [`pi-subagents-0.76.1-lifecycle.md`](pi-subagents-0.76.1-lifecycle.md): the deferred live legs
  W1–W7b, run verbatim here.
- [`pi-subagents-descendant-ceilings.md`](pi-subagents-descendant-ceilings.md): the 2.1 probe.
- [`pi-1.1.0-codemode-lift.md`](pi-1.1.0-codemode-lift.md): the deferred live leg, run here as the
  C rows.
- Commit `e12291ff`, which reconverged the wiring the stale PyPI perk 4.0.0 had reverted.
- PR #2758 (`49702136`): companion-family verification, write admission and clonefile worktree
  staging.

X5b, S7 and I7b's PR-door proof were PENDING at 1.0.0. Their 1.1.0 equivalents are rows X5b, S7 and
I7b-PR here.

## Verdict

**Verdict: HELD.** The ledger has 90 rows: 81 required and 9 INFO.

- **INFO rows** (I2b, A6b, S5-T4, W3, W7b, X4, X6, X7b, R2-drive): all OBSERVED or recorded, except
  R2-drive, which is NOT RUN.
- **PASS / MEASURED / CARRIED:** 66 of the 81 required rows.
- **FAIL: 3 required rows.** All three are supplier-lifecycle rows on pi-subagents 0.76.1:
  - **W4**: the retained wake path cannot be reached interactively. Pi refuses a mid-turn
    `/reload`. The interrupt drops Pi's queued completion notice, and the wake retained across the
    reload is orphaned (staged twice).
  - **W6**: the slow lane is reported as `missing-lane` ("absent from the wave aggregate") instead of
    `lane-failed`. 0.76.1's partial `results` omit a still-running `runs.all` lane.
  - **W7a**: (i) the pending reason reads "async workflow child lane-long is still running", never
    "Workflow dispatch is still open.", and the later status can stay `unknown`
    (`writer-close-unverified`). (ii) A `/reload` mid-wave *stops* the in-process workflow, so the
    later RPC `stop` gets `invalid_state … is stopped`, not "no live run controller available to
    stop."
- **NOT RUN: 12 required rows**, each with a closed reason:

  | Rows | Reason |
  |---|---|
  | S3, X5a, X5b, C3-on, C1-only, C2-only, C3-only, S4a-live (its structured-completion half rides S3) | not attempted |
  | U-bg, E5, R1, R2-census | prerequisite |

**Stamp: stays 0.75.0.** The required supplier rows that are not PASS/CARRIED are:

- FAIL: W4, W6, W7a.
- NOT RUN: S3, S4a-live, U-bg, X5a, X5b.

`_SUBAGENTS_GUIDANCE_VERIFIED_VERSION` and its test literal therefore do not move, and
`subagent-compat` warns by design (A2).

Measured rows and source-derived statements are kept separate:

- **LIVE** row: quotes a command run in this experiment against the PATH host, a real install, a
  real session or GitHub.
- **MEASURED (offline, real runtime, 1.1.0 SDK)** row: quotes a passing test line from the recorded
  TAP or verbose-pytest invocations. Every such invocation's exit status was 0 (appendix).
- **CARRIED** row: restates an earlier record that measured exactly this pair.
- **source-derived** statement: cites the lockfile-pinned
  `node_modules/@earendil-works/*/dist` files or `$WT/.pi/npm/node_modules/pi-subagents/src` (the
  mirror's `v1.1.0` tag is absent, verified at Step 0).

## The decision rule (verbatim, pinned before measurement)

- **Required rows** are every row in families I, A, S, W, E, H, M, U, X, C, R not marked INFO. **INFO rows (never gating):** I2b, A6b, S5-T4, W3, W7b, X4, X6, X7b, R2's drive outcome, U-fg when unstageable after one retry. **K rows are outside the counted gate**: each is a retention review — status RETAINED or RETIRED — citing the evidence rows it rests on (INFO rows allowed, e.g. K2 ← X4) and its re-checked retirement condition; a K row never becomes PASS/FAIL/NOT RUN and never moves the verdict.
- **NOT RUN reasons** are closed: `prerequisite` (a precondition **outside the pair** was absent — see the evidence-classification rule), `unstageable` (a **completed** drive could not produce the leg's condition after its allowed retry), `blocked (<row>)` (the row's only vehicle ended in another required row's FAIL; counts as NOT RUN, and the verdict is already HELD), `not attempted` (time or owner availability). A NOT RUN is never a FAIL and never "met".
- **Evidence-classification rule (one causal rule, fixed before measurement).** `prerequisite` requires **independent evidence of the external cause recorded beside the row**: a runner secret absent by name (`gh secret list`), a fixture unreachable (`git ls-remote` / `gh api` failure), or a **credential control** failing outside the pair. **Credential controls:** (local) before each local drive, for every model the drive will use (the `implement` stage model and `conflict-resolver`), `env $SCRUB PI_CODING_AGENT_DIR=$AUTHED pi --approve --mode json --model <m> -p "Reply with exactly OK."` under the watchdog → exit 0 and an assistant turn — recorded; (remote) presence by name is the only pre-check; with the key present, a worker or child auth failure is a FAIL unless the operator proves the key value invalid out-of-band (a direct provider call with the same value fails), a dated Deviation that reclassifies that row to `prerequisite`. With the controls green, any `runtime_init`, `model_auth`, `no_extension_tools`, zero-turn or classifier-auth exit **inside** the worker or a worker-spawned child is a **FAIL on the drive's row** (R0 for the local drive, R1 for the self-repo remote drive) and every row riding that drive is `blocked (<that row>)`; `model_not_found`/`no_model` likewise. The staging exemption (`unstageable`) is reserved for a drive whose `run_finished` is `completed/submit_tool` without a conflict.
- **Drift rule (a multi-sitting run).** `H0` = `git rev-parse origin/main` at Step 0 = the implement branch's base. Before each `origin/main`-reading leg (the P2 staging, each `perk plan` owner session from `$MAIN`, each `--remote` dispatch) and at the start of every sitting: `git fetch origin && git diff --name-only H0 origin/main`. Empty → proceed. Otherwise the **drift set** (that file list) decides mechanically: if it touches `extension/`, `agents/`, `shared/`, `.pi/settings.json`, `package.json` or `package-lock.json` → S, W, X, C, M, U, H, R1, I4–I7, E and K are invalidated; if it touches `src/perk/`, `shared/`, `pyproject.toml`, `uv.lock`, `.perk/config.toml`, `.perk/required-perk-version`, `.github/` or `.pi/settings.json` → I, A, R, M, U, E1 and E5 are invalidated; if it touches only `tests/` or `extension/**/*.test.ts` → the offline tier recordings (§1.1) are re-run; anything else (`docs/`, `CHANGELOG.md`, `skills/`, `CONTEXT.md`, …) invalidates nothing and is recorded as source-equivalent. An invalidating drift means: rebase the implement branch onto `origin/main`, `git -C $MAIN pull --ff-only`, set `H0 :=` the new `origin/main`, re-run every invalidated measured leg; legs not invalidated keep their evidence, each recorded with the SHA it ran at and the drift set's non-intersection as its source-equivalence proof. Every leg records its SHA (`$WT`: `git merge-base HEAD origin/main`; `$MAIN`/`$CLONE`: `git rev-parse HEAD`; remote: the job log's checkout SHA + `position_branch`'s positioning line + the census's `## git` block). The record's Status names H0 (and every H0' adopted) and the per-leg SHAs.
- **Verdict.** `CERTIFIED` iff every required row is PASS/CARRIED/MEASURED. `PARTIAL` iff no required row FAILs but ≥ 1 required row is NOT RUN. `HELD` iff any required row FAILs.
- **The stamp (independent of the verdict).** `_SUBAGENTS_GUIDANCE_VERIFIED_VERSION` and `tests/test_doctor.py::test_subagent_compat_verified_version_stamp_is_pinned` move to `0.76.1` iff every **required supplier row** is PASS/CARRIED: **S3** (scout wave), **S4a-live** (mixed siblings + structured completion), **W1, W2, W4, W5, W6, W7a**, **U-bg**, and the four browser-door cells **X5a, X5b, I7b-PR, S7**. Any NOT RUN or FAIL among them keeps the stamp at 0.75.0. `CERTIFIED` implies the stamp moves; `PARTIAL`/`HELD` combine with either stamp outcome.
- **The prose matrix (both dimensions, fixed now).** Every evidence-contingent surface carries two independent slots: (a) the *pair* slot — `CERTIFIED`: "certified on the exact pair by `pi-1.1.0-certification.md` (<date>); a later Pi is admitted but uncertified" / `PARTIAL`: "adopted; the certification record holds <n> required cells NOT RUN (<ids>)" / `HELD`: "adopted; the certification record holds <k> required FAIL(s) (<ids>) — the support claim is held"; (b) the *stamp* slot — moved: "the guidance stamp is 0.76.1 (the certification's supplier rows passed) and `subagent-compat` reads ok on a converged checkout" / stayed: "the guidance stamp stays 0.75.0 (<the failing/NOT RUN supplier rows>) and `subagent-compat` warns by design". The executor fills the slots from the measured outcome and chooses nothing.
- Amendments to this rule after measurement begins are dated operator decisions recorded in the record's Deviations section, never silent.

## Path abbreviations

| Abbreviation | Path |
|---|---|
| `$MAIN` | the main checkout, `/Users/mattgiles/dev/github/mattgiles/perk` |
| `$WT` | the implement worktree, `$MAIN/.worktrees/plan-2756` |
| `$SCRATCH` | `$WT/.perk/workflow/scratch/runs/01M5NJS7A0G0V2X0T3VZJYPRRT/agent/certification` (gitignored; logs copied to `$SCRATCH/logs`) |
| `$TMP` | `mktemp -d -t perk-cert` (`…/T/perk-cert.qaoraubVHT`, removed at teardown) |
| `$AUTHED` | `$TMP/agent-authed`: a copy of `$MAIN/.pi/agent/auth.json` only |
| `$CLONE` | `$TMP/clone` (no-hardlinks clone, detached at H0) |
| `$AUX` | `$TMP/aux-clone` (bare-loading clone: no `node_modules` or `.venv`, an independent `.pi/npm`) |
| `$LOGS` | `$TMP/logs`, copied to `$SCRATCH/logs` |
| `$MODEL` | `anthropic/claude-haiku-5-5`, the cheapest Anthropic model in `pi-ai` 1.1.0's `dist/providers/data/anthropic.json` (input 0.1 / output 0.5) |

## Snapshot matrix

| Item | Value |
|---|---|
| perk | 4.0.0 (`perk --version`, `uv run perk --version` in `$WT`) at H0 |
| Editable CLI | `~/.local/share/uv/tools/perk/uv-receipt.toml` `editable = "$MAIN"`, sha256 `871c7f977d15fceacaa99187f4aa8794969329a89efcb0f1ee27482ba3777b92`. Identical before the P2 drive, during it, after the post-drive `just install-cli`, and at teardown |
| PATH `pi` | `~/.local/share/mise/installs/node/26.12.1/bin/pi` → `…/@earendil-works/pi-coding-agent/dist/bundle/cli.js`; `pi --version` 1.1.0 |
| Sibling census | `$(npm root -g)/@earendil-works` = `chord pi-agent-core pi-ai pi-codemode pi-coding-agent pi-mcp pi-telemetry pi-tui`, each 1.1.0; `pi-coding-agent/node_modules/@earendil-works` absent |
| node / npm / uv | v26.12.1 / 11.20.0 / 0.13.5 |
| Dev pins | `$WT/node_modules/@earendil-works/*` eight at 1.1.0, none nested; devDependencies `pi-agent-core`/`pi-ai`/`pi-coding-agent`/`pi-tui` `1.1.0`; `engines.node` `^22.23.4 \|\| ^24.22.1 \|\| ^26.12.1` |
| Suppliers `$WT` | `.pi/settings.json` `npm:pi-subagents@0.76.1`; installed 0.76.1; `.pi/npm/package.json` inode 481768618, link count 1 (clonefile); pi-web-access 0.37.0; @plannotator/pi-extension 0.28.8 |
| Suppliers `$MAIN` | pi-subagents 0.76.1; `.pi/npm/package.json` inode 481703563, link count 1. **Finding:** `$MAIN/.pi/npm/node_modules/pi-subagents/package.json` inode 480847879 has link count **2**; the other link is `.worktrees/plan-2757` (a pre-#2758 hard-link staging of another worktree, untouched) |
| Suppliers `$CLONE` | `cp -R $MAIN/.pi/npm`: inode 482301332, link count 1, manifest equal |
| Supplier / floor constants | `SUBAGENTS_PACKAGE` `npm:pi-subagents@0.76.1`; floor `>= 1.1.0` (`shared/host-floor.yaml`); `PI_ADOPTED_VERSION` 1.1.0; `PI_INSTALL_COMMAND`, the eight-spec global install (A6b ran it literally) |
| Registry dist-tags (Step 0) | `@earendil-works/pi-coding-agent` `latest` 1.4.0, `legacy-node20` 0.74.2; `pi-subagents` `latest` 0.81.0 |
| `$MODEL` | `anthropic/claude-haiku-5-5` |
| Runner secrets (names) | perk: `ANTHROPIC_API_KEY`, `NPM_TOKEN`, `PERK_GH_PAT` (**no `OPENAI_API_KEY`**); consumer: `ANTHROPIC_API_KEY`, `PERK_GH_PAT`. `PERK_GH_PAT` last updated 2026-07-04T13:36:36Z (perk) and 2026-07-06T11:56:29Z (consumer) |
| Credential controls (local, under `$AUTHED`) | `anthropic/claude-opus-5-5` → `OK`, exit 0, 15 s; `openai/gpt-6-luna` → `OK`, exit 0, 2 s |
| S1 (implement session) | run `01M5NJS7A0G0V2X0T3VZJYPRRT`, Pi session `01a16b2c-e15f-7790-8acd-588dcba70dd3`, model `anthropic/claude-opus-5-5`, agent dir `$MAIN/.pi/agent` (config-selected). The worktree launched `create-fresh` on the pair from its first process, so no S0 |
| Codemode `on` session | `uv run perk plan` from `$MAIN`: run `01M5NW4D0VNQCE2P1Z0PNX8Z4Z`, Pi session `01a16bc2-36a3-7081-9a3e-3b3b68f3fe3e`, model `anthropic/claude-fable-5-1` (the user-scope `defaultModel`). The `only` session was not run |
| P2 (local drive) | issue #2759, saved with run id `01M5NM6E1ACWP4V5AHVF5JS237`, header `base: cert-target`; drive run `01M5NM999QGD9ND0R85WZEW28X`; PR #2760 (base `cert-target`) |
| C2 | `7e0926f38fdf450956a733da6690c748bdaa9e9f` on `cert-target` |
| P1 (self-repo remote) | issue #2761, saved with run id `01M5NP5ZGEHGACF6PED5YHYCBZ`; dispatch run_id `01M5NP73F7ATYKEXCB82K8RSZE`, run_ref `40046985036` |
| P3 (consumer) | `mattgiles/perk-consumer-dogfood#3`, saved with run id `01M5NP9392QPSDAN32DR9MM4QC`; dispatch run_id `01M5NP9E4MSG4DC4F0A3SZVQG1`, run_ref `40047089241` |
| Staging hashes | `$MAIN/.pi/npm/{package.json, package-lock.json, node_modules/.package-lock.json, node_modules/pi-subagents/package.json}`, `$MAIN/.pi/agent/{settings.json, trust.json}` and `$WT/.pi/settings.json`: byte-equal at Step 0 and at teardown (Teardown proof) |

## Offline tier

| Recording | Window (UTC) | Result | Exit |
|---|---|---|---|
| `just test-js-slow` (TAP → `slow.tap`) | 23:53:37–23:55:15 | 1066/1066 `ok`, 0 `not ok` | 0 |
| `just test-js-fast` (TAP → `fast.tap`) | 23:55:15–23:55:43 | 2998 tests, 0 `not ok` | 0 |
| `uv run pytest -rfEs` | 23:55:43–23:58:33 | `8545 passed, 1 skipped in 166.33s` (the skip: `test_native_sdk_bridge_live.py:152: needs a below-floor PATH pi (this one is admitted)`) | 0 |
| `pytest -v -n0` named set (+ `tests/test_packaging.py`) | 23:58:33–23:59:00 | `262 passed in 19.09s` | 0 |
| `tests/test_native_sdk_bridge_live.py` | 23:59:00–23:59:09 | `2 passed, 1 skipped in 7.98s` | 0 |
| `node --test` I5–I6 set | 23:59:09–23:59:20 | `ℹ tests 59` / `ℹ pass 59` / `ℹ fail 0` | 0 |
| `node --test extension/worker/sdkAdapter.test.ts` (H2) | 23:59:20–23:59:24 | `ℹ tests 50` / `ℹ pass 50` / `ℹ fail 0` | 0 |
| E1–E2 pytest (added; `tests/test_learn_session_jsonl.py` and the evidence render) | 00:00:01–00:00:35 | `46 passed, 43 deselected` | 0 |
| A7 pytest (stamp + init tests) | 00:03:52–00:03:59 | 19 passed | 0 |

## I — Installs and identity

| Row | Procedure | Verbatim observation | Verdict | Class |
|---|---|---|---|---|
| I1 | Step 0 re-read: CLI identity and layout | `pi --version` 1.1.0, the realpath above, eight siblings at 1.1.0, none nested; perk 4.0.0, editable receipt `$MAIN` | PASS | LIVE |
| I2a | Dev pins, lockfile, named pin tests | eight `node_modules/@earendil-works/*` at 1.1.0, none nested; lockfile root devDeps agree; `tests/test_packaging.py::test_pi_toolchain_pin_lockstep PASSED`; `tests/test_pi_host.py::test_pinned_install_family_is_closed_against_the_characterized_lockfile PASSED` | PASS | LIVE + MEASURED |
| I2b | Floating non-family transitives (INFO) | `undici 8.10.2` (plus `jsdom/node_modules/undici 7.29.0`); `@anthropic-ai/sdk 0.129.0` | OBSERVED | LIVE |
| I3 | Suppliers, staging method, pin test | pi-subagents 0.76.1, pi-web-access 0.37.0 and @plannotator/pi-extension 0.28.8 in both `$WT/.pi/npm` and `$MAIN/.pi/npm`; `.pi/npm/package.json` link count 1 in each, distinct inodes (481768618 vs 481703563); `test_the_installed_pi_subagents_is_the_managed_pin PASSED` | PASS | LIVE + MEASURED |
| I4 | Bare-clone loading from `$AUX`: `$SCRUB <hermetic> pi --approve --mode json -p /perk-selfcheck` under the watchdog + `bareImportGuard.test.ts` | `$AUX/.pi/npm` inode 482142101, links 1. `perk: selfcheck — 4.0.0: ok; … bridge=installed`; `native sdk bridge: installed (roots=2, specifiers=8)`; 0 `Failed to load extension`; exit 0, 12 s. Guard 2/2 | PASS | LIVE |
| I5 | Host identity + bridge | S1 selfcheck: `host sdk: 1.1.0 (floor >= 1.1.0)`, `native sdk bridge: installed (roots=2, specifiers=8)`; census drift guard in the I5–I6 run (59/59) | PASS | LIVE + MEASURED |
| I6 | Lazy imports / reload | `entryAdmission.test.ts` in I5–I6 (59/59); the X3 `/reload` selfcheck reads `native sdk bridge: installed (roots=2, specifiers=8, reused)` | PASS | LIVE + MEASURED |
| I7a | `run_librarian {action: "refresh-docs", slug: "divio-documentation"}` from S1 | published 8 pages, failures 0; receipt agent `perk.librarian`, `nativeStatus: "completed"`, exitCode 0, `termination: "confirmed"`, `bracket.ok: true`; runId `47ff1b90-0292-401d-97ed-dbc7626e5883`, model `openai/gpt-6-sol`, 30 turns, 264627 ms, $0.456; capability audit `allowedAgents []`; `$MAIN` porcelain empty before and after | PASS | LIVE |
| I7b-plan | `start_draft_review_wave` launch (codemode `on` session, JSONL line 37) | asyncId `43d431f5-d6cb-4713-9814-c9b09de2fe32`; `launch.requested` = `launch.runnable` = `["grounding","decision-completeness","risk","ponytail"]`; `preflightFailures: []` | PASS | LIVE |
| I7b-PR | `start_review_wave` launch (S1, JSONL line 668) | asyncId `9ec43bd5-6dd4-441f-abf5-0d81a95a97d8`; requested = runnable = `[claimed-intent, correctness, tests, ponytail]`; `preflightFailures: []` | PASS | LIVE |

## A — Admission, doctor, convergence

| Row | Procedure | Verbatim observation | Verdict | Class |
|---|---|---|---|---|
| A1 | Live stubs `old` (`echo 1.0.4`) and `none` under `script -q /dev/null uv run perk`, plus the typed read via `_resolve_pi_executable` / `_admit_pi_host` (`a1-typed.py`) | old: "pi at $STUBS/old/pi is version 1.0.4; perk requires Pi >= 1.1.0. Upgrade it: <PI_INSTALL_COMMAND> — perk init and perk doctor report the same requirement." exit 1. none: "pi CLI not found on PATH — install it: <PI_INSTALL_COMMAND> (perk requires Pi >= 1.1.0 and Node.js on a supported release line: 22.x >= 22.23.4, 24.x >= 24.22.1, 26.x >= 26.12.1)." exit 1. Typed codes `pi_version_unsupported` / `pi_cli_missing`; the real host `admitted` 1.1.0 | PASS | LIVE + MEASURED |
| A2 | `uv run perk doctor --verbose` + `--json` from `$WT` | `pi` `status: "ok"`, detail `1.1.0 (floor >= 1.1.0)`, `remediation: ""` (no advisory, no `— companions:`); `node` ok v26.12.1; `settings-wiring` converged; `artifact-health` ok (7); `subagent-compat` **warn** (installed 0.76.1 vs stamp 0.75.0, truthful because the stamp does not move); `subagent-package-scope` ok; healthy, exit 0 | PASS | LIVE |
| A2b | Companion-family refusal | `tests/test_pi_host.py::test_real_probe_of_the_broken_layout_is_incoherent PASSED`; `::test_incoherent_refusal_text_and_error_type PASSED`; `tests/test_env.py::test_pi_incoherent_is_not_ok PASSED` | MEASURED | MEASURED |
| A3e | Extension refusal on a real 1.0.4 (`$TMP/pi-global/1.0.4`, added 120 packages) | `test_a_below_floor_real_pi_refuses_to_load_perk PASSED` (`1 passed in 3.16s`); raw `-p /perk-selfcheck`: `Failed to load extension … perk requires Pi >= 1.1.0; the Pi running this session is 1.0.4 …`, naming `REQUIREMENTS_DOC_URL` (`…#version-compatibility`); exit 1, 9 s; 0 selfcheck lines | PASS | LIVE + MEASURED |
| A3w | Worker refusal on a real old SDK (`$AUX` `npm install --no-save …@1.0.4`) | `error.type: pi_version_unsupported` "… is version 1.0.4; perk requires Pi >= 1.1.0 …"; exit 1; events `run_started` → `run_finished` | PASS | LIVE |
| A4 | Skew admitted: `latest` 1.4.0 | admission passes; `model_not_found` after extension registration; exit 1, 12 s. 1.4.0 is not certified | PASS | LIVE |
| A5 | Node + remote agree (static) | `action.yml`, `ci.yml` and `release.yml` all `node-version: "22.23.4"`; `engines.node` `^22.23.4 \|\| ^24.22.1 \|\| ^26.12.1`; `test_committed_self_repo_remote_artifacts_are_the_owners_render` green | PASS | LIVE |
| A6a | `doctor --fix` recovery (delete `defaultTools` from `$WT/.pi/settings.json`) | drift line `settings-wiring drift — .pi/settings.json: compaction: reserveTokens=65536; defaultTools: +tool_search`; Fixed the same; `git diff --exit-code` exit 0 | PASS | LIVE |
| A6b | Literal `PI_INSTALL_COMMAND` on a throwaway prefix under `mise exec node@22.23.4` (INFO) | node 22.23.4 / npm 10.9.9; added 130 packages; eight siblings at 1.1.0, none nested; `pi` 1.1.0 | OBSERVED | LIVE |
| A7 | `uv run perk init` ×2 from `$WT` | zero changes both times; exit 2 on the worktree skills sync (recorded, not a Pi effect); the operator edits (`tuiMode` regular, `-tool_search`) preserved byte-identical; doctor healthy; A7 pytest 19 passed | PASS | LIVE + MEASURED |
| A8 | Write admission live | bare `perk doctor --fix --json` (the editable `$MAIN` install) → exit 2, `error_type: "foreign_perk"`, message naming `$MAIN`, `$WT` and `uv run perk …`; human arm exit 2; porcelain unchanged, nothing written. `uv run perk doctor --fix` in `$WT` → exit 0. **Sub-clause falsified:** "nothing fixed" does not hold, because it reported `.perk/local.toml: created` (a fresh worktree lacks the gitignored overlay, the same `config` fail Step 0's doctor showed) and left `.agents/cache` + `.agents/local.yaml` (removed at teardown). Bare `uv run perk doctor` (no `--fix`) is never gated: exit 1 (`config` only) | PASS (falsified sub-clause) | LIVE |
| A8b | Write admission, nested worktree | `tests/test_write_admission.py::test_a_nested_worktrees_perk_never_converges_main PASSED`; `::test_a_self_repo_that_is_not_the_running_checkout_is_foreign PASSED`; `::test_a_nested_worktrees_perk_converges_its_own_worktree PASSED` | MEASURED | MEASURED |

## S — Supplier children

| Row | Procedure | Verbatim observation | Verdict | Class |
|---|---|---|---|---|
| S1 | Bridge-live suite | `test_the_installed_pi_subagents_is_the_managed_pin PASSED`; `test_real_pi_selfcheck_reports_the_bridge_installed_and_both_consumers_loaded PASSED`; 2 passed, 1 skipped (the below-floor arm, run as A3e) | MEASURED | MEASURED |
| S2 | Offline wave suites | `ok 2672 - durable partial arrays take precedence in full: no event promotion or hole filling`; `ok 2673 - partial carrier cannot bypass unreadable status, nonterminal states, or generic failure`; `ok 2674 - partial normalization keeps absent, malformed and failed reports distinct`; fast tier 0 `not ok` | MEASURED | MEASURED |
| S3 | `run_scout_wave` (two briefs) in the codemode `on` session | not run: the owner quit the `on` session before the scout prompt and ended the owner legs ("i already quit that session … can we just … wrap?") | NOT RUN (not attempted) | — |
| S4a-carried | Restriction packet reaching a restricted child | CARRIED from [`pi-1.1.0-characterization.md`](pi-1.1.0-characterization.md) T11 (exact pair) | CARRIED | CARRIED |
| S4a-live | `probe-spawn.ts` `mixed` (SHA `4be3a84f…`) via `$SCRUB <authed> pi --approve --mode json -e … -p "/probe-spawn script $MODEL mixed"` from `$WT`; the structured half is credited from S3 | Mixed-sibling half met: spawn `success: true` (asyncId `56ecc972-4090-4720-80cf-599a0e1f2739`); `status.json` `complete`; `workflow.value` `[{key: "probe-ok", ok: true, error: null}, {key: "probe-bad", ok: false, error: "Unknown subagent model 'perk-probe/does-not-exist' in the active Pi model registry."}]`; the probe-ok child log carries `[READ-ONLY MODE] (unscoped)` with recovery descriptor `extensionBindings {"perk.parent-restrictions/1":{"readOnly":true}}`; no probe-bad child dir; exit 0, 29 s. Structured half (a schema-valid `SCOUT_REPORT_SCHEMA` report) **not measured** because S3 did not run. W1's production-transport lanes completed schema-valid against the probe's own `PROBE_SCHEMA` (corroboration only) | NOT RUN (not attempted, structured half) | LIVE |
| S4b | Cancellation | → W7a | (W7a) | — |
| S4c | Deadline partial | → W6 | (W6) | — |
| S5-T1 | Packet delivery under `--approve` | CARRIED from `pi-1.1.0-characterization.md` T11. T2/T3 = W5 | CARRIED | CARRIED |
| S5-T4 | `--no-approve` structural negative, headless (INFO) | ping/spawn `probe-timeout`; no run dir; exit 0 after 62 s | OBSERVED | LIVE |
| S6 | Task restoration | `ok 903 - a live task is left alone: no restore, the gate allows before and after`; `ok 909 - control (active turn): a lane compacted before reporting is continued with its task restored` | MEASURED | MEASURED |
| S7 | Repeated collection in one activation (S1, line 686) | `{ok: false, error_type: "no_wave", error: "no review wave is running in this activation — launch one with start_review_wave (collection is per activation: …)"}` | PASS | LIVE |

## W — The supplier lifecycle legs (verbatim from the lifecycle record's deferred legs)

Every leg was followed by stop-and-confirm (`$SCRATCH/stop-confirm.sh`): async run dirs and
`status.json` states listed; every runner pid gone; `$WT/.pi/settings.json`,
`$MAIN/.pi/agent/settings.json` and `$MAIN/.pi/agent/trust.json` hashes unchanged
(`stop-confirm-*.log`).

| Row | Procedure | Verbatim observation | Verdict | Class |
|---|---|---|---|---|
| W1 | `pi --approve --mode json -e probe-wave.ts -e probe-listener.ts -p "/probe-wave two"` (00:29:14Z) | handle `76886f42-46c0-4c69-a5cf-dd090c5da164`. Child `subagent:async-complete` events `5749e394` (00:29:49.070Z, lane-b) and `3a9a83f1` (00:29:50.525Z, lane-a): `awaitedByWorkflow: true`, `parentWorkflowRunId` = the handle, mode single, agent `perk.scout`. Workflow event 00:29:50.773Z (`awaitedByWorkflow` absent). Collect: running at 19083 ms, settled at 27220 ms (after the root event). `complete: true`, both lanes reported, receipt children success. Exit 0, 37 s | PASS | LIVE |
| W2 | Same probe, fresh process (00:30:09Z) | first `ping` reply at **149 ms** after `session_start`; first `spawn` reply (`wave.start` resolved) at **637 ms**; W2b `/probe-foreground-latency` `started` at 137 ms (1 ms after dispatch); foreground completed, `termination: confirmed` (runId `898b9426`) | PASS | LIVE |
| W3 | Duplicate load under remembered trust (INFO): user-scope `packages: ["npm:pi-subagents@0.76.1"]` + `trust.json` | Pi installed into `$AUTHED/npm` ("added 7 packages in 2s", 0.76.1); wave complete; 0 `perk: waves` lines and 0 `no_active_session`, so no ghost observed; `doctor` (`PI_CODING_AGENT_DIR=$AUTHED`) `subagent-package-scope` **warn** "pi-subagents is configured in both user and project scope"; the user-scope entry, `trust.json` and `$AUTHED/npm` removed afterwards | OBSERVED | LIVE |
| W4 | Same-session `/reload` with a staged queued wake (tmux; `/probe-wakes` lives in `probe-wave.ts`) | Staging 1 (session `01a16b5b-25d1-73e5-8653-f85ddb44c71d`): workflow `e6ffbb36` completed at 00:41:58.026Z while the parent streamed the `sleep 120` turn; 0 `subagent-notify`; `wakes 1` (00:42:26Z, 00:42:36Z). `/reload` mid-turn → "Warning: Wait for the current response to finish before reloading." Escape at 00:42:54Z → toolResult "Command aborted" (a lane-a `subagent-incremental-child-notify` was delivered at 00:42:54.900Z). `/reload` → Reloaded; post-reload same session id, `wakes 1`; 70 s+ idle → no `subagent-notify` and no "Subagent updates above."; nudge "Reply with exactly OK." → OK, still no notice, `wakes 1` (orphan). Staging 2 (session `01a16b5e-a449-7547-8557-1efd36f77696`): completion 00:46:03.803Z, `wakes 1`; Escape → no notice and the editor not restored; `wakes 1` before and after reload; 30 s idle → 0 notify, 0 wake turn. No stale-ctx lines interactively. Finding, recorded as the record specifies: **retention path unreachable interactively** | FAIL | LIVE |
| W5 | T2 (remembered trust, no flag) and T3 (`defaultProjectTrust: "always"`, `trust.json` removed), one restricted lane each | T2: `trust.json` `{"<realpath $WT>": true}`; child `64c51305` `[READ-ONLY MODE] (unscoped)`, descriptor `extensionBindings` readOnly, lane `ok: true`, no trust diagnostic, exit 0, 6 s. T3: child `bb0bab42` the same; no `trust.json` written; exit 0, 6 s | PASS | LIVE |
| W6 | `PERK_WAVE_TIMEOUT_MS=20000`, lane-quick + lane-long ("Read AGENTS.md and summarize it in 600 words.") | run 1: `complete: false`; failures `run-failed` "wave run ended 'failed' (native partial: timeout): Workflow script timed out after 20000ms." and lane-long **`missing-lane` "lane 'lane-long' is absent from the wave aggregate"**; lane-quick report retained; settled at 20969 ms; RPC sent only `ping`, `spawn` (no perk stop/status). `status.json` `workflowChildren` lane-long state `running`; receipt entries lane-quick only; `terminalOutcome` partial/timeout. Run 2 was unstaged (lane-long finished in time; not scored). Run 3 (listener) was staged: completion payload `results=[lane-quick]`, lane-long only in `workflowChildren` → `missing-lane` again. Source: `pi-subagents/src/runs/foreground/subagent-executor.js:5813` `results: workflowResultChildren(partial.children…)` — a still-running `runs.all` lane is not in `partial.children`. Expected `lane-failed` (`lane still running at native partial settlement`) | FAIL | LIVE + source |
| W7a | (i) Probe `AbortSignal` while running; (ii) `/reload` mid-wave (tmux), then RPC `stop` for the pre-reload run | (i) run 1 (abort 1 s after runner pid 90908): one `stop` at 1529 ms and one `status` at 1608 ms; detail "wave 'scout' was cancelled; stop requested; child termination unconfirmed (pending: async workflow child lane-long is still running)"; manual `status` at 31625 ms → `unknown` "async workflow child lane-long process-terminal proof is unknown" (child `process-terminal.json` `unknown`, reason `writer-close-unverified`, runner close observed exitCode 0); a late status from a fresh process is still `unknown`. Run 2 (`PROBE_CANCEL_DELAY_MS=8000`): same pending reason; status → `observed`. The pinned "Workflow dispatch is still open." never appeared. (ii) start-long → handle `368f4ddb-33b5-4f34-9a1b-c2bcfcd66d98`; `/reload` at 00:40:18Z → workflow `stopped` "Workflow stopped because the extension session was replaced or reloaded."; `/probe-stop` → raw `success: false`, `invalid_state` "Async run 368f4ddb-… is stopped; stop only supports running async runs."; rendered "stop refused (invalid_state: Async run … is stopped; stop only supports running async runs.); child termination observed (engine process-terminal proof)". Expected "no live run controller available to stop." | FAIL | LIVE |
| W7b | Model-facing `interrupt` / `stop` in the no-perk project `$TMP/noperk` (INFO) | user-scope pi-subagents@0.76.1 ("added 7 packages in 4s"), `anthropic/claude-sonnet-5-5` via `subagent` (after `subagents_enable`); async worker `721f85ea-5be9-4cc1-a550-b0f58467f76e`; `interrupt` → "Interrupt requested for async run …", notice "Background task paused: **worker** … Paused after interrupt. Waiting for explicit next action."; `stop` → "Stopped paused async run 721f85ea-…" (the seal); status `stopped`, Error "Subagent stopped by user.", notice "Background task stopped: **unknown** …"; exit 0, 73 s. A single async run, not a workflow | OBSERVED | LIVE |

## E — Evidence and restoration

| Row | Procedure | Verbatim observation | Verdict | Class |
|---|---|---|---|---|
| E1 | `uv run perk learn evidence --render --json` from `$WT` after the owner legs (03:29Z) | exit 0; `success: true`, `plan_id: "2756"`; `render.sessions[0]` (`planning-session/main`, Pi session `01a16aaa-aed6-7324-a8cf-235a592b0863` on this host's 1.1.0): `entries_read: 182`, `malformed_lines: 0`, **`system_states: 2`**, `system_malformed: 0`; `grep -c '<system_state'` over the two chunks = 2 | PASS | LIVE |
| E2 | Nested evidence | `tests/test_learn_session_jsonl.py::test_nested_calls_project_the_released_grammar PASSED`; `::test_nested_calls_status_kept_verbatim_or_unknown PASSED` (E1–E2 pytest: 46 passed). The evidence is pytest, not TAP | MEASURED | MEASURED |
| E3 | MCP read-only floor + restoration window | `ok 1962 - direct call: the floored report child and the /plan gate block the MCP tool as not allowlisted; read-write does not block`; `ok 1963 - nested call: ctx.executeTool on the MCP tool meets the backstop (parent call id kept) …`; `ok 1965 - codemode script: in a cohort /plan gate the MCP builtin's auto-activated codemode stays on (lifted), and its script's MCP call meets the bac…`; `ok 2288 - the nested policy holds under a child floor and inside the restoration window` | MEASURED | MEASURED |
| E4 | Restoration windows | `ok 2277 - the restoration window: a reload session_start or a session_tree opens it …`; `ok 2279 - the restoration window's close: agent_start installs the pre-change target and clears the memos; …`; `ok 2282 - the restoration window stays shut at startup, and a bare session's agent_start installs nothing` | MEASURED | MEASURED |
| E5 | `perk pr feedback --json` on the P1 PR beside U-bg's classification | no P1 PR exists (R1 never reached the worker) and U-bg is NOT RUN (prerequisite) | NOT RUN (prerequisite) | — |

## H — Worker (offline e2e, real runtime, 1.1.0 SDK)

Every title listed in the plan's H enumeration is `ok` in `slow.tap` (lines `ok 1019`–`ok 1066`).
The full title list is in `$SCRATCH/H-lines.txt`.

| Row | Quoted lines (abridged) | Verdict |
|---|---|---|
| H1a | `ok 1045 - e2e: discovery opt-in — …`; `ok 1046 - e2e: discovery opt-out (-tool_search) — …`; `ok 1047 - e2e: -builtin:<name> disables a worker builtin — …` | MEASURED |
| H1b | `ok 1029 - e2e: no_model is decided AFTER extension registration (order pin) → zero-turn failed/no_model`; `ok 1030`; `ok 1031`; `ok 1032`; `ok 1033 - … → zero-turn failed/model_auth`; `ok 1034 - … → zero-turn failed/model_not_found` | MEASURED |
| H1c | `ok 1048 - e2e: builtin:mcp connects the project's .pi/mcp.json — …`; `ok 1049 - e2e: a default-exposure project server is reached from the worker's builtin codemode, …`; `ok 1051 - e2e: -builtin:mcp disables the worker's MCP builtin — …` | MEASURED |
| H1d | `ok 1019 - e2e: implement HAPPY — …` through `ok 1028 - e2e: BUDGET — …` (10 titles) | MEASURED |
| H1e | `ok 1061 - e2e: COMPACTS IN-DRIVE AND COMPLETES — …`; `ok 1064`; `ok 1062 - e2e: RETRY RECOVERS — …`; `ok 1066`; `ok 1065 - e2e: PREFLIGHT ABORT CANCELS A TURN-1 COMPACTION — …` | MEASURED |
| H1f | `ok 1063 - e2e: PROJECT OPT-OUT HONOURED — …` | MEASURED |
| H1g | `ok 1038 - e2e: MODEL-TOOL direct — …`; `ok 1039`; `ok 1040 - e2e: CODEMODE classify across the cap …`; `ok 1044 - e2e: PRODUCTION SHAPE — …`; `ok 1041`; `ok 1042`; `ok 1043` | MEASURED |
| H1h | `ok 1035 - e2e: the real worker entry admits the installed SDK and drives to completion, independent of PATH and the CLI stamp` | MEASURED |
| H2 | `H2.log`: `ℹ tests 50` / `ℹ pass 50` / `ℹ fail 0` | MEASURED |
| H3 | `ok 1048 - … its log lands in the throwaway dir; nothing global is read or written`; `ok 1050 - e2e: child-auth stand-ins — mid-drive, a subagent child's in-process and background construction calls resolve the REAL agent dir and its auth` | MEASURED |
| H4a–H4i | `ok 1052` (HTTP explicit header credentials) · `ok 1053` (registrations beside/colliding) · `ok 1054` (unavailable OAuth) · `ok 1055` (connection failures silent headless) · `ok 1056` (`enabled:false`) · `ok 1057` (mid-drive registration; expired session) · `ok 1058` (abort cancels an in-flight call) · `ok 1059` (abort during the startup wait) · `ok 1060` (shutdown closes every transport first) | MEASURED (9 rows) |
| H5a | `ok 1036 - e2e: a virtual model routes to a physical target with a different identity → completed`; `ok 1037 - e2e: a \`:thinking\` suffix on --model survives the reorder → …`; H2.log `✔ createDriveSession: selectedModel reads the session's selection before bind, after a failed bind, and null without one` | MEASURED |
| H5b | `tests/test_run_report.py::test_model_line_joins_every_dispatched_identity_in_order PASSED`; `::test_usage_line_renders_fresh_cache_and_cost PASSED`; `::test_step_summary_carries_model_and_usage_lines PASSED`; `::test_model_none_renders_unavailable_distinct_from_a_selectionless_session PASSED` | MEASURED |
| H5c | `ok 1490 - selfcheck (live): a session that never answered reports dispatched=none, n/a and unavailable usage` | MEASURED |

## M — Worker MCP (the local clone drive, P2)

| Row | Procedure | Verbatim observation | Verdict | Class |
|---|---|---|---|---|
| M1 | Project `.pi/mcp.json` fixture (`token cert-project`) reached by the worker's model | project marker pid 16049 at 00:18:06Z; calls log `{"at":"2026-10-24T00:18:45.643Z","id":3,"pid":15875,"args":{"text":"perk-certification"},"token":"cert-project"}` (pid = the worker 15875); worker session `mcp__fixture__echo` → "perk-certification", details `{server: fixture, tool: echo}` | PASS | LIVE |
| M2 | `mcp.log` under the throwaway agent dir mid-drive; the dir gone after exit | `mcp.log` at 00:18:47Z under `tmp-p2/perk-worker-agent-JGNypM` (45 bytes, beside `settings.json`); that dir gone after exit; `perk worker: mcp config error` absent. **Sub-clause falsified:** `ls $TMP/tmp-p2` was not empty. It held 2777 entries of the resolver child's `just test` residue (it inherited the drive-scoped `TMPDIR`), plus jiti, node-compile-cache and `pi-subagents-uid-502` | PASS (falsified sub-clause) | LIVE |
| M3 | Global canary `$AUTHED/mcp.json` never spawns | no `mcp-global-canary.pid`, no `$AUTHED/mcp.log`; pre-existing `$AUTHED` files byte-equal. **Sub-clause falsified** ("`$AUTHED` unchanged except `sessions/`"): new `fff/` (pi-fff's frecency DB at 00:18:02; `pi-fff` reads `process.env.PI_CODING_AGENT_DIR` directly), plus `missions/` and `run-history.jsonl` (pi-subagents, from the resolver child) | PASS (falsified sub-clause) | LIVE |

## U — Subagent under the worker

| Row | Procedure | Verbatim observation | Verdict | Class |
|---|---|---|---|---|
| U-fg | The staged `/submit` conflict → `resolve_submit_conflicts` → in-process `perk.conflict-resolver` | `events.ndjson`: `submit` ok (seq 20, t=84990), `resolve_submit_conflicts` ok (seq 21, t=563085), `submit` ok (seq 22, t=575857), `run_finished` `completed/submit_tool` PR #2760. Submit #1 `mergeable: false`, conflicts `["CHANGELOG.md"]`, base `cert-target`. Resolve receipt `termination: confirmed`, `nativeStatus: completed`, agent `perk.conflict-resolver`, exitCode 0, lock released, runId `f54a185f-ecf4-4807-9026-79409c3c9dbe`. Meta: model `openai/gpt-6-luna`, 17 turns, 475905 ms, $0.0093; capability audit `allowedAgents []`; 0 `Intercom orchestration channel`, 0 `contact_supervisor`. Submit #2 `existed: true`, `mergeable: true`, head `b9dddf38`. PR #2760 (base `cert-target`) holds both CHANGELOG bullets. The resolver verified with `just lint typecheck test changelog-check` (+ `just sync`) and `just test && just changelog-check`, **not** `just ci`, so the receipt never moved (871c7f97… throughout; the post-drive `just install-cli` left the same hash) | PASS | LIVE |
| U-bg | `address --remote` classification by a worker-spawned background child | `OPENAI_API_KEY` absent by name from the runner (Step 0 `gh secret list`), and the operator left it absent (decision 2026-10-23 ~23:53Z). Independently, its vehicle R1 never reached the worker | NOT RUN (prerequisite) | — |

## R — Remote and the local drive

| Row | Procedure | Verbatim observation | Verdict | Class |
|---|---|---|---|---|
| R0 | Local drive `uv run perk run-worker --run-id $RUN_P2 --stage implement --plan 2759` from `$CLONE`, `TMPDIR=$TMP/tmp-p2`, `PI_CODING_AGENT_DIR=$AUTHED`, watchdog GRACE 60 / CAP 5400 | `run-worker: positioned plan-2759 at the remote tip`; 00:17:04–00:27:31Z, exit 0, 627 s; `run_finished` `completed/submit_tool`; 11 turns, $0.7409. `CERTIFICATION-CENSUS.md` on `plan-2759`: eight global siblings at 1.1.0, none nested; `merge-base` H0; `.pi/npm` pi-subagents 0.76.1; `## mcp perk-certification`. Run comment: `Model: selected=anthropic/claude-opus-4-8; dispatched=anthropic/claude-opus-4-8 ×11` / `Usage: records=11; fresh=3274 (in=21 out=3253); cache read=322105 write=79741; cost=$0.7409` (the worker used the SDK default chain; see falsified assumptions) | PASS | LIVE |
| R1 | `uv run perk implement 2761 --remote` (dispatch 00:50:46Z) | `doctor workflow check --verbose` exit 0 (github-auth, github-repo, runner-pat-secret, runner-model-secret, runner-workflow). Run `40046985036` (headSha H0) concluded failure: "Validate required secrets" succeeded; `actions/checkout@v4` (`token: secrets.PERK_GH_PAT`) → 3× `##[error]fatal: could not read Username for 'https://github.com': terminal prompts disabled`; composite and drive skipped. External evidence: the PAT was set 2026-07-04 (~110 days; consistent with expiry). The last green `perk-run` was `28762381016` (2026-07-06). Reclassified by the operator's dated decision (Deviations) | NOT RUN (prerequisite) | LIVE |
| R2-census | Consumer composite (`$TMP/consumer` at `caa8836`) | `perk init` (editable 4.0.0) exit 0: `@mgiles/perk@1.1.0 → 4.0.0`, pi-subagents → `@0.76.1`; `action.yml` node 22.23.4, `uv tool install perk==4.0.0`, the eight-spec `Install pi`, `npm install @mgiles/perk@4.0.0 <eight> --prefix .pi/npm --legacy-peer-deps --save-exact`; commit `6a238632` pushed; doctor exit 0 (advisory "Actions cannot create PRs"). Run `40047089241` failed identically at checkout (00:52:13–44Z). Consumer `PERK_GH_PAT` set 2026-07-06 | NOT RUN (prerequisite) | LIVE |
| R2-drive | INFO | no worker ran (the checkout failed) | NOT RUN (prerequisite) | — |

## X — Sessions and surfaces

| Row | Procedure | Verbatim observation | Verdict | Class |
|---|---|---|---|---|
| X1 | Owner `/perk-selfcheck`, a `tool_search` activation, and a codemode census after a temporary `+codemode` (user-scope `$MAIN/.pi/agent/settings.json` + `/reload`; reverted after X2, hash `2aae99af…` before = after) | Selfcheck (S1 line 558): `tools: 35 active / 66 registered`; `discovery: cohort (family: objective_stack_status, collect_review_wave, collect_draft_review_wave, push_annotations)`; `model: selected=anthropic/claude-opus-5-5 …; dispatched=anthropic/claude-opus-5-5; same`; `responses: … ×257; errors=0; aborted=2`; `usage: records=261 …`; `context: projection=118 … used=125308 (13%)`; `wave children: usage=unavailable`; bridge `installed (roots=2, specifiers=8)`. `tool_search "objective stack status"` → "Loaded 1 tool" `objective_stack_status` → "Objective #2707: this objective uses incremental delivery; no delivery train exists". Codemode `ALL_TOOLS` (22): read, bash, edit, write, objective_stack_adopt/recover/land/status, post_pr_review, submit_pr_review, collect_review_wave, collect_draft_review_wave, push_annotations, run_ci, reconcile_objective, add_objective_node, bg_wait, ffgrep, fffind, web_enable, todo, ask_user_question. **None** of the model-only names (submit, ready, land, learn, run_learn_wave, objective_stack_sync, classify_review_feedback, finalize_address, run_pr_review_wave, start_review_wave, run_librarian, objective_node, resolve_submit_conflicts). No `plan_draft` (the bounded writer is out of stage in `implement`). Post-reload selfcheck: 36 active, builtin=6, bridge `… reused` | PASS | LIVE |
| X2 | Owner `/plan` on → probes → `/plan` off | Tools at line 591: read, bash, tool_search, subagents_enable, ffgrep, fffind, todo, ask_user_question, web_enable, plan_draft, plan_review, run_librarian, start_draft_review_wave, objective_node (no edit, write or codemode). `npm install x --dry-run` → "perk read-only mode: command blocked (not allowlisted). … Reason: matches the destructive veto /\bnpm\s+(install\|uninstall\|update\|ci\|link\|publish)/i"; `echo probe > …` → "… matches the destructive veto /(^\|[^<])>(?!>)/", file absent; `tool_search "codemode"` and `"edit"` → "No matching tools found."; selfcheck 20 active, builtin=5. `/plan` off (01:13:18Z) → 34 tools with codemode, edit and write restored. The transition notice is a UI notify (not persisted). The interactive applied arm is source-derived ("plan mode OFF — full tool access restored.", `plan.ts` announce; `gateTransitionNotice` null on applied); owner confirmation not given | PASS (rendering clause source-derived) | LIVE + source |
| X3 | `/reload`, `/tree`, `/compact` + one turn, quit + resume, each followed by `/perk-selfcheck` | `/reload` (line 714): bridge `installed (roots=2, specifiers=8, reused)`; 55/66 (codemode still active in-process after the settings revert); `binding-header-copies=3`. `/tree`: 36/66, branch 718, `reused`. `/compact` (entry line 725, 01:45:01Z) + one turn re-injected `perk:agent-scratch` + `perk:binding-context`; selfcheck: `binding-header-copies=4`; contexts `agent-scratch ×3 live=1`, `binding-context ×2 live=1`, `mode-context ×1 live=0`, `plan-adapter-plannotator ×1 live=0`; projection 20 messages. Resume (lines 747–750): bridge `installed (roots=2, specifiers=8)` (no `reused`); 35/66, builtin=5; skills **16 visible + 23 hidden** (stage launch: 12 + 2); `PERK_RUN_ID` absent from the resumed shell. Launch output (owner's words): only Pi's own "Package Updates Available … Run pi update --extensions" banners for pi-web-access, @plannotator/pi-extension, @juicesharp/rpiv-todo, @juicesharp/rpiv-ask-user-question, @dietrichgebert/ponytail, "and similar for new pi version"; **no `detached …` line** | PASS | LIVE |
| X4 | `/btw` ×2 + "Inject summary into main chat" (INFO) | lines 650/651 `btw-thread-entry`; line 652 `btw-thread-reset` (01:25:08.651Z) + line 653 user message "Summary of my BTW side conversation …". The side thread had no tool access ("exact filename not confirmed") | OBSERVED | LIVE |
| X5a | Plan door five criteria (codemode `on` session) | See Browser doors: criteria 1–3 and the marker clause met; **criterion 4 (DENY after the last receipt) not exercised** because the owner ran `/plan-save` instead | NOT RUN (not attempted) | LIVE |
| X5b | PR door five criteria (`/pr-review-browser 2755`, S1) | See Browser doors: criteria 1–4 met; annotations confirmed; **the running-marker clause unobserved** (the executor asked after collection, which clears the marker) | NOT RUN (not attempted) | LIVE |
| X6 | Regular vs fullscreen (INFO) | the owner: the session runs fullscreen and looks normal; the regular-mode comparison was skipped | OBSERVED (partial) | LIVE |
| X7a | Headless `$SCRUB <hermetic> pi --approve --mode json -p /perk-selfcheck` from `$WT` | selfcheck ok; `tools: 50 active / 66 registered`; discovery cohort; `host sdk: 1.1.0`; bridge `installed (roots=2, specifiers=8)`; 0 `Failed to load extension`; exit 0, 2 s | PASS | LIVE |
| X7b | Print-mode exit pair on stderr (INFO) | W1's print-mode run: the stale-ctx pair ×2 + `turn_end` on stderr; none interactively (W4) | OBSERVED | LIVE |

## C — Codemode in a recorded read-only stage (`perk plan`, mode `on`)

The vehicle was the user-scope `$MAIN/.pi/agent/settings.json` += `"defaultTools": ["+codemode"]`,
`"codemode": {"mode": "on"}`, restored at the end with the hash equal to before. The session was a
fresh `uv run perk plan` from `$MAIN`. Line 4 holds `perk:workflow-state`
`{run_id: "01M5NW4D0VNQCE2P1Z0PNX8Z4Z", mode: "read-only", stage: "plan"}`, and selfcheck #1
(line 8) reads `tools: 20 active / 66 registered`, `builtin=6` (codemode declared), discovery
cohort.

| Row | Procedure | Verbatim observation | Verdict | Class |
|---|---|---|---|---|
| C1-on | One script batching `objective_stack_status({})`, `read AGENTS.md` and `bash git log -1 --oneline` | ONE codemode call (line 15, `toolu_012hZuN2JxKPR8DH883xLKDQ`); toolResult line 16 `nestedCalls.complete: true`: `objective_stack_status` `ok` (2118 ms), `read` `ok` (20 ms), `bash` `ok` (55 ms). The query value is structured `{ ok: true, objective: "2707", status: { success: true, delivery: "incremental", train: null, no_train: "this objective uses incremental delivery; no delivery train exists", operations: [] … } }`; `git_head` "49702136 Verify the Pi host graph, …"; "Script completed / Wall time 2.3 seconds" | PASS | LIVE |
| C2-on | A script calling `tools.write({path: "cert-probe.txt", content: "x"})` | ONE codemode call (line 19); line 20 nested `write` `status: "error"`, `error: "perk read-only mode: write is blocked (file modifications disabled)."`; `ls $MAIN/cert-probe.txt` → No such file or directory | PASS | LIVE |
| C3-on | `plan_draft` (direct) → `plan_review` → deny → revise | v1 landed: `plan_draft` direct (line 27) → `sha256:be8f43c24dabfc9064f8c93b86fd5369648048f3b9b55ceb2e5044dece7e17b5`, 1932 bytes. Codemode stayed declared (system messages at lines 9 and 35). **Not exercised:** the deny, the DENIED text naming the writer, and v2 with a distinct digest. The owner ran `/plan-save` instead (03:13:47Z: `active_plan_ref` #2762, mode `read-write`) | NOT RUN (not attempted) | LIVE |
| C1-only / C2-only / C3-only | The `only` session | not launched: the owner ended the owner legs | NOT RUN (not attempted) | — |

## Browser doors

### X5a — the plan door (codemode `on` session, JSONL `01a16bc2-…`)

| Criterion | Evidence | Met |
|---|---|---|
| 1. Launch | line 37 (02:39:07.007Z): requested = runnable `[grounding, decision-completeness, risk, ponytail]`, `preflightFailures: []` | yes |
| 2. Collect after the workflow notice | child notices lines 39–42; workflow `subagent-notify` line 43 (02:40:00.595Z) "Background task completed: **workflow** … Workflow completed with 4 child run(s)"; `collect_draft_review_wave` line 46 (02:40:03.201Z) `complete: true`, covered 4/4, `failures: []`, `attempts[0].state: "complete"`, every child `success: true` (`perk.draft-reviewer`) | yes |
| 3. Delivery per angle, `replace: true` | four `push_annotations` in one message (line 47), every report clean (`findings: []`) | yes |
| 4. Decision after the last receipt | last receipt line 51 (02:40:09.747Z); no browser decision arrived. The owner ran `/plan-save` (03:13:47Z) instead of denying | **not exercised** |
| 5. Owner observation | marker, in the owner's words *while the wave ran*: "the review wave is still running, but i see: Global / perk:wave · now / Reviewer wave running — 4 lane(s): grounding, decision-completeness, risk, ponytail. Findings land here as annotations when the wave completes; decide after they arrive." The annotation half is vacuous (zero findings) | marker yes |

Receipts (lines 48–51):

| Angle | ok | mode | pushed | held | held_batches | deleted |
|---|---|---|---|---|---|---|
| grounding | true | plan | 0 | 0 | 0 | 0 |
| decision-completeness | true | plan | 0 | 0 | 0 | 0 |
| risk | true | plan | 0 | 0 | 0 | 0 |
| ponytail | true | plan | 0 | 0 | 0 | 0 |

### X5b — the PR door (`/pr-review-browser 2755`, S1)

| Criterion | Evidence | Met |
|---|---|---|
| 1. Launch | line 668 (01:26:33.028Z): requested = runnable `[claimed-intent, correctness, tests, ponytail]`, `preflightFailures: []` | yes |
| 2. Collect after the workflow notice | child notices lines 672–675; `subagent-notify` line 676 (01:30:25.199Z); `collect_review_wave` line 679 `complete: true`, 4/4, `failures: []` | yes |
| 3. Delivery per angle, `replace: true` | lines 681–684 | yes |
| 4. Decision after the last receipt | last receipt line 684 (01:30:45.383Z); the owner's turn at 01:34:29.557Z; the owner closed the tab, nothing posted to GitHub, and no browser respond message arrived | yes |
| 5. Owner observation | "1. i do not see it. i see 4 comments tagged." The four tagged annotations were confirmed. The marker was not seen because the question came after collection, and `reviewWave.ts` clears the marker at a complete collection (an instrument timing miss, not a pair observation) | annotations yes; **marker not observed** |

Findings and receipts: claimed-intent (minor) `docs/design/prose-prompt-map.yaml:455`; correctness
(major) `extension/delivery/address.ts:290`; tests (major) `extension/pi/v1/delivery/address.test.ts:1085`;
ponytail (minor) `agents/review-classifier.md:22`. Every receipt was `{ok: true, mode: "review",
pushed: 1, skipped: [], held: 0, held_batches: 0, deleted: 0}`. Afterwards
`perk pr review cleanup --pr 2755` → "✓ removed review worktree review-2755".

## K — Keep-and-reverify (outside the gate)

| Row | Adaptation | Re-verified by | Retirement condition re-checked on the 1.1.0 dist | Status |
|---|---|---|---|---|
| K1 | Host SDK bridge (`extension/substrate/nativeSdkBridge.ts`) | I5, I7a, I7b-plan, I7b-PR, S1 (S3 NOT RUN) | `pi-coding-agent/dist/core/extensions/loader.js:21` `const usesEmbeddedModules = isBunBinary \|\| isNodeSeaBinary \|\| isBundledNode;` and `:473` `? { virtualModules: await getVirtualModules(), tryNative: false }`. These loader lines match the 1.0.0 record's jiti analysis, so on the bundled PATH CLI the supplier `.js` entries still resolve outside Pi's instances unless bridged. Every selfcheck reported `installed (roots=2, specifiers=8)` | RETAINED |
| K2 | `/btw` live-runtime adaptation (`extension/vendor/btw/btw.ts`) | X4 (INFO) | `pi-coding-agent/dist/core/model-registry.d.ts:22` `private readonly runtime;`: still no public accessor | RETAINED |
| K3 | Canonical projection + delivery predicates | X3 (`live=` readings; `mode-context ×1 live=0` after compaction; binding/scratch re-injected) | Pi projects the context; perk still verifies delivery on the selected branch | RETAINED |
| K4 | RPC context-less / stale-responder guards | S2; W7a (the RPC stop/status path answered, with no context-less error); W3 (0 `no_active_session`) | a fix to Pi's separate `RpcClient` is not replacement evidence | RETAINED |
| K5 | Worker `finishTurn` gate + codemode `models: false` + `perk-worker-policy` | H1g (`BUDGET`, `PRODUCTION SHAPE`, `CODEMODE classify across the cap`) | `pi-agent-core/dist/types.d.ts:479` `type: "tool_execution_update"`: the partial update still carries no `usage` | RETAINED (CONSTRAINED) |
| K6 | Browser-owner adaptations: the code-owned `perk:wave` marker, and post-collection `push_annotations` onto the primed plannotator surface | X5a (marker observed live; receipts), X5b (receipts; annotations) | `@plannotator/pi-extension` 0.28.8 exposes no native wave-status channel, so perk still owns the marker (`extension/pi/v1/providers/waveStatus.ts`) and the annotation push | RETAINED |

## Classification lists

### Supported behavior

- Host admission on the bundled 1.1.0 CLI; the below-floor and missing-host refusals; skew
  admission (A1–A4).
- Write admission (A8), doctor recovery (A6a) and init idempotence (A7).
- Bare-clone loading and the bridge (I4, I5).
- The in-process blocking child (I7a) and the conflict resolver under the worker (U-fg).
- Worker MCP from the project config, with the global config untouched (M1, M3).
- Codemode script batching and the nested write refusal in a recorded read-only stage (C1-on,
  C2-on).
- Wave launch on both doors (I7b-plan, I7b-PR), collection (X5a/X5b criteria 1–3) and the
  per-activation collect refusal (S7).
- Awaited-child events (W1), lazy-loading latency (W2) and the trust rows (W5).

### Configuration opt-outs

- Discovery opt-out (`-tool_search`, H1a).
- Compaction opt-out (H1f).
- `-builtin:mcp` (H1c).
- The user-scope `+codemode` / `codemode.mode` keys (the C vehicle).

### Retained adaptations

- K1–K6.

### Constrained capabilities

- **W4:** the reload-retained wake is unreachable interactively.
- **W6:** a deadline partial reports a still-running lane as `missing-lane`.
- **W7a:** the pending reason text, `writer-close-unverified` → `unknown`, and `/reload` stopping
  an in-process workflow.
- **M3:** the real agent dir gains supplier state (`fff/`, `missions/`, `run-history.jsonl`).

### Deferred work

- The certification gaps:
  - S3, the S4a-live structured half, X5a criterion 4, the X5b marker clause, C3-on, and the
    `only` session → re-run on the next certification.
  - U-bg, E5, R1, R2 → need valid runner PATs and `OPENAI_API_KEY`.
- **W6 and W7a repair designs:** perk could classify a lane named only in `workflowChildren` (state
  `running`) as `lane-failed`, and could accept 0.76.1's pending/stopped reasons in its stop
  rendering. Both are handed to the procedure-and-docs reconcile as design candidates (no
  production code moved here).

## Falsified planning-time assumptions

- **Fixed at replan:** "A precursor PR was needed" → `e12291ff` reconverged `main` directly
  (`1d849434 → e12291ff`).
- **Fixed at replan:** "The worktree `.pi/npm` must be detached by hand" → #2758's clonefile staging.
- **Fixed at replan:** "`disableBuiltins` disables the `subagent` tool" → it disables the builtin
  agent defs.
- **Fixed at replan:** "`createReportWave` can run a mixed-model wave" → `ReportAssignment` has no
  per-assignment `model`.
- **"The local drive's worker runs the `implement` stage model (`anthropic/claude-opus-5-5`)"** →
  `run-worker` passes no `--model`, so the worker took the SDK default chain:
  `anthropic/claude-opus-4-8`.
- **A8 "nothing fixed"** → a fresh worktree lacks `.perk/local.toml`; `doctor --fix` creates it.
- **M2 "`ls $TMP/tmp-p2` empty"** → the resolver child inherits the drive-scoped `TMPDIR`, and its
  verification leaves residue.
- **M3 "`$AUTHED` unchanged except `sessions/`"** → pi-fff writes `fff/` to
  `PI_CODING_AGENT_DIR`, and pi-subagents writes `missions/` and `run-history.jsonl`.
- **"The resolver may run `just ci`"** → it chose `just lint typecheck test changelog-check`, so the
  `install-cli` rebinding hazard did not fire. The containment held either way.
- **"E2 quotes TAP lines"** → E2's nested-evidence proof is pytest.
- **W6** "the slow lane is `lane-failed`" → 0.76.1's partial `results` omit running `runs.all`
  lanes; perk reports `missing-lane`.
- **W7a(i)** "pending: Workflow dispatch is still open." → the reason names the running child, and a
  `writer-close-unverified` proof leaves the status `unknown`.
- **W7a(ii)** "no live run controller" → 0.76.1's `/reload` stops in-process workflows; the later
  `stop` gets `invalid_state`.
- **W4** "a staged wake survives the reload and delivers" → Pi refuses a mid-turn `/reload`, the
  interrupt drops the queued notice, and the retained wake is orphaned.
- **"`$MAIN/.pi/npm` has link count 1 throughout"** → `pi-subagents/package.json` shares an inode
  with `.worktrees/plan-2757` (a pre-#2758 worktree), untouched.
- **"Saving a plan and dispatching `--remote` leave `$MAIN` unchanged"** → `plan save`,
  `implement --remote` and `/plan-save` each rewrite `$MAIN/.perk/workflow/plan-ref.json`
  (gitignored), restored byte-equal each time.
- **"The runner secrets are valid"** → both `PERK_GH_PAT`s (July 2026) fail `actions/checkout`.
- **"Discovery cohort deferral hides `objective_stack_status`"** → it is deferred in the direct
  loadout but listed in codemode's `ALL_TOOLS` and callable from a script (C1-on, X1).
- **"Codemode leaves with the settings revert"** → the active codemode tool persists across the
  settings revert and `/reload` in-process; only a fresh process (resume) dropped it.

## Deviations (dated)

- **2026-10-23 ~23:53Z (operator):** `OPENAI_API_KEY` stays absent, so U-bg is NOT RUN
  (prerequisite).
- **2026-10-24T00:58:21Z (operator):** R1 and R2 are reclassified to NOT RUN (prerequisite) on the
  out-of-band evidence (the job logs' checkout rejection of `PERK_GH_PAT`; secrets dated
  2026-07-04/06), instead of rotating the PATs.
- **W4 and W7a(ii) were executor-driven** in tmux (`tmux-pi.sh`), not owner-typed. The keystrokes
  and pane captures are in `W4-pane-staging{1,2}.txt` and `W7a-ii-pane.txt`.
- **W4's `/probe-wakes`** lives in `probe-wave.ts`, not a separate `probe-wakes.ts`.
- **W6 and W7a(i) diagnostic re-runs:** W6 runs 2–3 (run 2 unstaged, not scored) and W7a(i) run 2
  (`PROBE_CANCEL_DELAY_MS=8000`) were extra diagnostics.
- **P2 credential controls** ran in `$TMP/ctl` with the canary moved aside.
- **The X5b marker question was asked after collection**, an instrument timing error. It was
  corrected for X5a, where the owner observed the marker while the wave ran.
- **X3's resume:** the owner ran `perk resume 2756` (the PLAN arm → `pi --resume` picker, then
  selected S1) instead of the RUN_ID arm. A dry-run of that arm shows `command: pi --resume`,
  `session_file: null`, `agent_dir_source: "env"`. Both arms share `pi_exec.exec_pi` (no
  skill-exposure argv, no `--approve`, `PERK_RUN_ID` removed).
- **X1/X2's `+codemode` stayed active in S1** after the settings revert (in-process). It was gone
  only after the resume.
- **2026-10-24T03:13:47Z (operator slip):** `/plan-save` in the codemode `on` session instead of the
  browser DENY. It created throwaway issue #2762 (closed at teardown). The operator chose to
  continue that session and record X5a criterion 4 and C3-on's revise as NOT RUN.
- **~03:20Z (operator):** the owner ended the owner legs before S3 and the `only` session. They are
  recorded NOT RUN (not attempted).
- **The S4a-live structured half** is not substituted from W1 (whose schema is the probe's, not
  `SCOUT_REPORT_SCHEMA`).

## Methodology appendix

### Scaffold

```sh
# Step 0 ($WT, S1): H0, PATH pi + siblings, receipt hash, doctor --json, node/npm/uv,
#   dev pins, gh secret list (perk + consumer), npm view dist-tags, mirror tag check, the main-checkout staging hashes
TMP=$(mktemp -d -t perk-cert); AUTHED=$TMP/agent-authed   # holds only a copy of $MAIN/.pi/agent/auth.json
# P2 staging (D4)
git clone -q --no-hardlinks $MAIN $CLONE && git -C $CLONE remote set-url origin <github url> && git -C $CLONE fetch origin
git -C $CLONE checkout --detach H0
printf '[workflow]\nbase = "cert-target"\n' > $CLONE/.perk/local.toml
git -C $CLONE checkout -b cert-target H0   # + the C2 CHANGELOG bullet, committed and pushed (7e0926f3…)
uv run perk plan save --plan-file P2.md --json --run-id <fresh>   # → #2759, header base: cert-target
git -C $CLONE push origin H0:refs/heads/plan-2759
# P2 drive (watchdog GRACE 60 CAP 5400)
env $SCRUB TMPDIR=$TMP/tmp-p2 PI_CODING_AGENT_DIR=$AUTHED GH_TOKEN=… uv run perk run-worker --run-id $RUN_P2 --stage implement --plan 2759
(cd $MAIN && just install-cli)   # receipt re-verified: unchanged
```

### Instruments (SHA-256; scratch, never committed)

| Instrument | SHA-256 |
|---|---|
| `run-bounded.sh` (the 1.0.0 characterization watchdog, byte-for-byte) | `1114155f63fdd2ecb8616dbdf9a890de09b693deb5f6f3cf4aa7bf6fd94b0843` |
| `probe-ceilings.extracted.ts` (the 2.1 probe, extracted) | `05ed7297556b24dd3655b5ff9ea6d6d87400f01827ed9c0cfe5a6e02274003da` |
| `probe-ceilings.ts` (instantiated) | `4b844fb9169a562dff8eba55538f5faba887735cd8e2ae62f9e2a7b6c3dc8cd1` |
| `probe-wave.ts` (final; earlier revisions `63160802…` → `0db389b1…` → `8aa68f2f…`) | `5cf9b0d6b50c8fdf9fc24edc513c3f13b4fe0ed2fc99cd0eb30d1868e5fe0324` |
| `probe-listener.ts` (final; earlier `7f185872…`) | `39fd649d8f13e8b8b521e8fb42f239f9ec72aa53af696b25b0c605f4429e306b` |
| `probe-spawn.ts` (the 1.0.0 record's, reconstructed byte-exactly) | `4be3a84fe9113b66d7bde8f4a620d4942877a6781dd32967358bd813ac27185a` |
| `probe-spawn-1.2.ts` (1.2's probe, the reconstruction base) | `72cb2372580b80137a727ae2a19430770d05a2211cfb78cb7346563bf7ec6d2d` |
| `stop-confirm.sh` | `c2482f98ea503c51fd779e7fcd7bdaa4e54afd6a44b830aff71ca04a6f207a6d` |
| `tmux-pi.sh` | `146ff6c427ef238d22085353437d33a3598812e6406bf7d4da25e82f5ef10e87` |
| `offline.sh` | `ed338bc5dda8e4f2f906898bcafc62ee2e3a9a3f508b2f75df6a5590e6532718` |
| `p2-drive.sh` | `2745d5410d44248a12c076552e3f54e7eee8861da64901da20cb21de567859d1` |
| `p2-observe.sh` | `e0f39fb9d445757b83370877792257a7b95eeb47c582e2d3581e575cfaa2701a` |
| `a1-typed.py` | `cdc59f73937856bc58ff9cb42183ef7907dad21c7e4d68765a82e07867da5b54` |
| `w7b-prompt.txt` | `14180ac00d50de6b2a78c91d4abadce256c5503bc2e02f18dfde90f69e6a5eaa` |
| `plans/P1.md` | `f835b0c6245300a24b15b350c3647308bd456b1bb82dee68f026b94260506d62` |
| `plans/P2.md` | `c328c62407317f2f90e726686b7456895f19ffb36975314d5d61c071c158d0a0` |
| `plans/P3.md` | `208da7564742cbd5570e6e94c678afa7495a7f5b63729b1239d8363d48059bb1` |

### Launch environments

- `$SCRUB` = `env -u PERK_RUN_ID -u PERK_PROFILE_HANDOFF -u PERK_SELFCHECK -u PERK_DISABLE_NATIVE_SDK_BRIDGE -u PERK_CLI_VERSION -u PI_SUBAGENT_CHILD -u PI_SUBAGENT_CHILD_AGENT -u PI_SUBAGENT_EXTENSION_BINDINGS -u PI_SESSION_FILE -u PI_SESSION_ID -u PI_MODEL -u PI_PROVIDER -u PI_REASONING_LEVEL -u PI_CODING_AGENT`.
- **Hermetic** (I4, X7a, A-row stubs): `PERK_SKIP_VERSION_CHECK=1 PI_CODING_AGENT_DIR=$TMP/agent-hermetic PI_OFFLINE=1 PI_SUBAGENTS_TEMP_ROOT=$TMP/subagents-tmp ANTHROPIC_API_KEY=perk-live-smoke-placeholder-never-sent`.
- **Authed** (W, S4a-live, S5-T4, controls, P2 drive): `$SCRUB PI_CODING_AGENT_DIR=$AUTHED PI_SUBAGENTS_TEMP_ROOT=$SCRATCH/subagents-tmp`, under `run-bounded.sh`.
- **S1 and the codemode session:** perk-launched, agent dir `$MAIN/.pi/agent` (config-selected).

### Recorded test invocations

The Offline tier table lists every invocation with its UTC window and exit status (all 0;
`offline-exits.txt`).

### The probe deltas (verbatim)

<details><summary>2.1 probe extracted → instantiated (<code>probe-ceilings.extracted.ts</code> → <code>probe-ceilings.ts</code>)</summary>

```diff
--- probe-ceilings.extracted.ts	2026-10-23 20:21:47
+++ probe-ceilings.ts	2026-10-23 20:21:47
@@ -6,9 +6,9 @@
 import { readdirSync, readFileSync } from "node:fs";
 import { join } from "node:path";
 import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
-import { dispatchForeground } from "$WT/extension/pi/v1/foregroundDelegation.ts";
-import { createReportWave } from "$WT/extension/waves/reportWave.ts";
-import { runScoutWave } from "$WT/extension/waves/scoutWave.ts";
+import { dispatchForeground } from "/Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2756/extension/pi/v1/foregroundDelegation.ts";
+import { createReportWave } from "/Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2756/extension/waves/reportWave.ts";
+import { runScoutWave } from "/Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2756/extension/waves/scoutWave.ts";
 
 const log = (label: string, value: unknown) =>
   console.error(`probe: ${label} ${JSON.stringify(value, null, 2)}`);
```

</details>

<details><summary>instantiated 2.1 probe → <code>probe-wave.ts</code> (the W1–W7a probe)</summary>

```diff
--- probe-ceilings.ts	2026-10-23 20:21:47
+++ probe-wave.ts	2026-10-23 20:39:42
@@ -3,15 +3,19 @@
 //   /probe-foreground <provider/model> <agent> <spawn-target> <requestId>   (L2, L3)
 //   /probe-scout <provider/model>                                            (L1)
 //   /probe-rpc-bg <provider/model> <agent> <spawn-target>                    (L4)
-import { readdirSync, readFileSync } from "node:fs";
-import { join } from "node:path";
+import { appendFileSync, existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
+import { dirname, join } from "node:path";
 import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
 import { dispatchForeground } from "/Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2756/extension/pi/v1/foregroundDelegation.ts";
 import { createReportWave } from "/Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2756/extension/waves/reportWave.ts";
 import { runScoutWave } from "/Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2756/extension/waves/scoutWave.ts";
+import { createRpcWaveAdapter } from "/Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2756/extension/waves/rpcAdapter.ts";
 
-const log = (label: string, value: unknown) =>
-  console.error(`probe: ${label} ${JSON.stringify(value, null, 2)}`);
+const log = (label: string, value: unknown) => {
+  const line = `probe: ${label} ${JSON.stringify(value, null, 2)}`;
+  if (process.env.PROBE_LOG_FILE) appendFileSync(process.env.PROBE_LOG_FILE, `${new Date().toISOString()} ${line}\n`);
+  else console.error(line);
+};
 
 const PROBE_SCHEMA = {
   type: "object",
@@ -158,4 +162,162 @@
       }
     },
   });
+  // ---- 7.1 W-leg modes (the delta against the 2.1 probe) --------------------------------------
+  // t0 = this activation's session_start; every W timestamp is relative to it. The logging bus
+  // wraps pi.events so every RPC method perk's own transport SENDS is logged (W6: no stop/status).
+  let t0 = Date.now();
+  pi.on("session_start", () => { t0 = Date.now(); log("session_start", { at: new Date(t0).toISOString(), pid: process.pid }); });
+  const rel = () => Date.now() - t0;
+  const loggingBus = {
+    emit(channel: string, data: unknown) {
+      if (channel === RPC_REQUEST) log("rpc-send", { method: (data as { method?: string })?.method, tMs: rel() });
+      pi.events.emit(channel, data);
+    },
+    on(channel: string, handler: (data: unknown) => void) { return pi.events.on(channel, handler); },
+  };
+  const QUICK = (n: string) =>
+    `Do not read files or run commands. Report exactly one finding: pointer "${n}", claim "OK", basis "verified", rationale "probe lane". scope: "none", open_questions [].`;
+  const LONG = "Read AGENTS.md and summarize it in 600 words.";
+  async function buildScout(briefs: { key: string; task: string }[], model: string, timeoutMs?: number) {
+    let captured: Parameters<ReturnType<typeof createReportWave>["run"]>[0] | undefined;
+    await runScoutWave({ run: async (r) => { captured = r; return undefined as never; } } as never,
+      { briefs, model, ...(timeoutMs !== undefined ? { timeoutMs } : {}) });
+    return captured!;
+  }
+  async function waitRunnerPid(asyncDir: string, timeoutMs = 120_000): Promise<unknown> {
+    const until = Date.now() + timeoutMs;
+    while (Date.now() < until) {
+      const journal = join(asyncDir, "workflow-children.jsonl");
+      if (existsSync(journal)) {
+        for (const line of readFileSync(journal, "utf8").split("\n")) {
+          if (!line.trim()) continue;
+          const rec = JSON.parse(line) as { type?: string; runId?: string; key?: string };
+          if (rec.type !== "start" || typeof rec.runId !== "string") continue;
+          const st = readJson(join(dirname(asyncDir), rec.runId, "status.json")) as { pid?: number; state?: string };
+          if (typeof st?.pid === "number") return { key: rec.key, runId: rec.runId, pid: st.pid, state: st.state };
+        }
+      }
+      await new Promise((r) => setTimeout(r, 1000));
+    }
+    return { probeTimeout: "runner-pid" };
+  }
+  async function drain(wave: ReturnType<typeof createReportWave>, ref: unknown) {
+    for (;;) {
+      const collected = await wave.collect(ref as never);
+      log("collect", { kind: collected.kind, tMs: rel() });
+      if (collected.kind === "settled") return collected.result;
+      if (collected.kind === "none") return null;
+    }
+  }
+
+  pi.registerCommand("probe-wave", {
+    description: "W legs: /probe-wave <two|latency|deadline|cancel|start> <provider/model>",
+    handler: async (args) => {
+      const [mode = "", model = ""] = args.trim().split(/\s+/);
+      if (!mode || !model) { log("probe-error", "usage"); process.exitCode = 2; return; }
+      log("launch", { pid: process.pid, cwd: process.cwd(), mode, model, tMs: rel(), tempRoot: process.env.PI_SUBAGENTS_TEMP_ROOT, waveTimeout: process.env.PERK_WAVE_TIMEOUT_MS ?? null });
+      try {
+        if (mode === "latency") {
+          const ping = await rpc(pi, "ping", undefined, 5_000);
+          log("latency-ping", { tMs: rel(), success: ping.success });
+        }
+        const wave = createReportWave(loggingBus);
+        const briefs =
+          mode === "two" ? [{ key: "lane-a", task: QUICK("lane-a") }, { key: "lane-b", task: QUICK("lane-b") }]
+          : mode === "deadline" ? [{ key: "lane-quick", task: QUICK("lane-quick") }, { key: "lane-long", task: LONG }]
+          : mode === "cancel" || mode === "start-long" ? [{ key: "lane-long", task: LONG }]
+          : [{ key: "lane-a", task: QUICK("lane-a") }];
+        // deadline: no request timeoutMs, so PERK_WAVE_TIMEOUT_MS (transport.waveTimeoutMs) is the engine deadline.
+        const request = await buildScout(briefs, model, mode === "deadline" ? undefined : 180_000);
+        const controller = new AbortController();
+        const started = await wave.start(request, { signal: controller.signal });
+        log("start", started.ok ? { ok: true, tMs: rel(), runId: started.runId, asyncDir: started.asyncDir, launch: started.launch } : started);
+        if (!started.ok) { log("status", started.result); return; }
+        if (process.env.PROBE_HANDLE_FILE) writeFileSync(process.env.PROBE_HANDLE_FILE, JSON.stringify({ runId: started.runId, asyncDir: started.asyncDir, at: new Date().toISOString() }));
+        if (mode === "start" || mode === "start-long") return; // interactive legs: the native notice, not collect, is observed
+        if (mode === "cancel") {
+          log("runner", await waitRunnerPid(started.asyncDir));
+          const delay = Number(process.env.PROBE_CANCEL_DELAY_MS ?? "0") || 0;
+          if (delay > 0) await new Promise((r) => setTimeout(r, delay));
+          log("abort", { tMs: rel(), delayMs: delay });
+          controller.abort();
+        }
+        const result = await drain(wave, started.ref);
+        log("status", result);
+        if (mode === "cancel") {
+          await new Promise((r) => setTimeout(r, 30_000));
+          const st = await rpc(pi, "status", { id: started.runId });
+          const details = ((st.data as Record<string, unknown>)?.details ?? {}) as Record<string, unknown>;
+          log("manual-status", { tMs: rel(), success: st.success, error: st.error, workflowTerminalProof: details.workflowTerminalProof ?? null });
+        }
+      } catch (error) {
+        log("probe-error", String(error)); process.exitCode = 2;
+      }
+    },
+  });
+
+  pi.registerCommand("probe-stop", {
+    description: "W7a(ii): RPC stop + perk's adapter stop/terminalProof for the run in PROBE_HANDLE_FILE",
+    handler: async () => {
+      const h = readJson(process.env.PROBE_HANDLE_FILE ?? "") as { runId?: string; asyncDir?: string };
+      log("handle", h);
+      if (!h?.runId || !h?.asyncDir) { log("probe-error", "no handle"); return; }
+      try {
+        const raw = await rpc(pi, "stop", { id: h.runId });
+        log("rpc-stop", raw);
+      } catch (error) { log("rpc-stop-threw", String(error)); }
+      const adapter = createRpcWaveAdapter(loggingBus);
+      const stop = await adapter.stop({ asyncId: h.runId, asyncDir: h.asyncDir });
+      const proof = await adapter.terminalProof({ asyncId: h.runId, asyncDir: h.asyncDir });
+      const rendered = [stop.acknowledged ? "stop requested" : `stop refused (${stop.reason})`,
+        proof.state === "observed" ? "child termination observed (engine process-terminal proof)" : `child termination unconfirmed (${proof.state}: ${proof.reason})`].join("; ");
+      log("adapter", { stop, proof, rendered });
+    },
+  });
+
+  pi.registerCommand("probe-status", {
+    description: "one RPC status {id} for the run in PROBE_HANDLE_FILE (or the given id)",
+    handler: async (args) => {
+      const id = args.trim() || (readJson(process.env.PROBE_HANDLE_FILE ?? "") as { runId?: string })?.runId;
+      const st = await rpc(pi, "status", { id });
+      const details = ((st.data as Record<string, unknown>)?.details ?? {}) as Record<string, unknown>;
+      log("status-rpc", { id, success: st.success, error: st.error, workflowTerminalProof: details.workflowTerminalProof ?? null });
+    },
+  });
+
+  pi.registerCommand("probe-wakes", {
+    description: "W4: this session id + its queued completion wakes",
+    handler: async (_args, ctx) => {
+      const sm = (ctx as unknown as { sessionManager: { getSessionId(): string } }).sessionManager;
+      const store = (globalThis as Record<symbol, unknown>)[Symbol.for("pi-subagents.queued-completion-wakes.v2")] as WeakMap<object, { wakes?: unknown[] }> | undefined;
+      const entry = store?.get(sm as object);
+      const out = { at: new Date().toISOString(), sessionId: sm.getSessionId(), store: store ? "present" : "absent", wakes: entry?.wakes?.length ?? null };
+      log("wakes", out);
+      if (process.env.PROBE_WAKES_LOG) writeFileSync(process.env.PROBE_WAKES_LOG, `${JSON.stringify(out)}\n`, { flag: "a" });
+    },
+  });
+
+  pi.registerCommand("probe-foreground-latency", {
+    description: "W2: the started tuple of one foreground child relative to session_start",
+    handler: async (args) => {
+      const model = args.trim();
+      const requestId = `probe-w2-${Date.now()}`;
+      let startedAt: number | null = null;
+      const off = pi.events.on("prompt-template:subagent:started", (d) => {
+        const r = d as Record<string, unknown>;
+        if (r?.requestId === requestId && startedAt === null) { startedAt = rel(); log("started", { tMs: startedAt, runId: r.runId }); }
+      });
+      const dispatchedAt = rel();
+      log("dispatch", { tMs: dispatchedAt, requestId });
+      try {
+        const outcome = await dispatchForeground(
+          pi.events,
+          { agent: "perk.scout", task: probeBrief("perk.scout"), cwd: process.cwd(), schema: PROBE_SCHEMA, model },
+          { requestId, ownerRunId: "probe", nodeId: "w2" },
+          new AbortController().signal,
+        );
+        log("status", { startedTMs: startedAt, startedAfterDispatchMs: startedAt === null ? null : startedAt - dispatchedAt, outcome });
+      } catch (error) { log("probe-error", String(error)); process.exitCode = 2; } finally { off(); }
+    },
+  });
 }
```

</details>

<details><summary><code>probe-listener.ts</code> (new; full text)</summary>

```ts
// $SCRATCH/probe-listener.ts — throwaway; logs every `subagent:async-complete` payload (the
// channel 0.76.1's ping advertises as events.asyncComplete) with a timestamp to PROBE_EVENTS_LOG.
import { appendFileSync } from "node:fs";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
  const out = process.env.PROBE_EVENTS_LOG;
  pi.events.on("subagent:async-complete", (data: unknown) => {
    const d = (data ?? {}) as Record<string, unknown>;
    const row = { at: new Date().toISOString(), id: d.id, runId: d.runId, asyncDir: d.asyncDir, awaitedByWorkflow: d.awaitedByWorkflow ?? null, parentWorkflowRunId: d.parentWorkflowRunId ?? null, state: d.state, success: d.success, mode: d.mode, agent: d.agent, keys: Object.keys(d), terminalOutcome: d.terminalOutcome ?? null, results: Array.isArray(d.results) ? (d.results as Record<string, unknown>[]).map((r) => ({ workflowKey: r.workflowKey, state: r.state, success: r.success, runId: r.runId })) : null, workflowChildren: (d.workflowChildren as { children?: unknown[] } | undefined)?.children ?? null };
    if (out) appendFileSync(out, `${JSON.stringify(row)}\n`);
    console.error(`listener: async-complete ${JSON.stringify(row)}`);
  });
}
```

</details>

<details><summary>1.2's <code>probe-spawn-1.2.ts</code> → the 1.0.0 record's <code>probe-spawn.ts</code> (S4a-live, W5)</summary>

```diff
--- probe-spawn-1.2.ts	2026-10-23 20:19:10
+++ probe-spawn.ts	2026-10-23 20:19:29
@@ -2,12 +2,12 @@
 // extension/waves/rpcAdapter.ts does (same envelope; the run handle lives in data.details), with
 // the spawn key, a pinned lane model and a lane mode, and waits for the run to settle so the
 // in-process workflow host is not killed by print-mode exit.
-//   /probe-spawn <script|workflowScript> <provider/model> [restricted|badmodel|missingbase]
+//   /probe-spawn <script|workflowScript> <provider/model> [restricted|badmodel|missingbase|mixed|cancel|deadline]
 // Auto-fire (SDK worker rows): PERK_PROBE_AUTO="<key> <model> [mode]" runs the same ping → spawn →
 // settle from session_start and writes PERK_PROBE_DONE (a JSON file) when it finishes.
 import { randomUUID } from "node:crypto";
 import { existsSync, readFileSync, writeFileSync } from "node:fs";
-import { join } from "node:path";
+import { dirname, join } from "node:path";
 import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
 
 const REQUEST = "subagents:rpc:v1:request";
@@ -50,6 +50,28 @@
   return { probeTimeout: "settle", last };
 }
 
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
+
 async function probe(pi: ExtensionAPI, key: string, model: string, mode: string): Promise<{ outcome: string; asyncDir?: string; reply?: Reply }> {
   const item = {
     key: "probe", agent: "perk.scout", label: "probe", worktree: false,
@@ -58,8 +80,26 @@
     ...(mode === "restricted" ? { extensionBindings: { "perk.parent-restrictions/1": { readOnly: true } } } : {}),
     ...(mode === "missingbase" ? { worktree: true, baseRef: "refs/heads/perk-probe-missing" } : {}),
   };
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
     "return reports.map(({key, ok, error, structuredOutput}) => ({key, ok, error: error ?? null, report: structuredOutput ?? null}));";
   log("env", Object.fromEntries(Object.entries(process.env).filter(([k]) => /^(PI_|PERK_)/.test(k))));
   log("ping", await call(pi, "ping"));
@@ -68,7 +108,7 @@
     reply = await call(pi, "spawn", {
       [key]: script, async: true, mission: false, context: "fresh", model,
       acceptance: { level: "none", reason: "characterization probe" },
-      intercomBridge: { mode: "off" }, timeoutMs: 120_000,
+      intercomBridge: { mode: "off" }, timeoutMs: mode === "deadline" ? 20_000 : 120_000,
     });
     if (reply.error?.code !== "no_active_session") break;
     log("spawn-retry", { attempt, reply });
@@ -82,6 +122,11 @@
     process.exitCode = 2;
     return { outcome: "probe-error", reply };
   }
+  if (mode === "cancel") {
+    const runner = await waitForRunnerPid(details.asyncDir);
+    log("runner", runner);
+    log("stop", await call(pi, "stop", { id: details.asyncId }));
+  }
   log("status", await settle(details.asyncDir));
   return { outcome: "settled", asyncDir: details.asyncDir, reply };
 }
@@ -91,7 +136,7 @@
     description: "characterization probe: ping + spawn one scout lane via the v1 RPC",
     handler: async (args) => {
       const [key = "script", model = "", mode = ""] = args.trim().split(/\s+/);
-      if (!model) { log("probe-error", "usage: /probe-spawn <script|workflowScript> <provider/model> [restricted|badmodel|missingbase]"); process.exitCode = 2; return; }
+      if (!model) { log("probe-error", "usage: /probe-spawn <script|workflowScript> <provider/model> [restricted|badmodel|missingbase|mixed|cancel|deadline]"); process.exitCode = 2; return; }
       await probe(pi, key, model, mode);
     },
   });
```

</details>

### The sacrificial plan bodies (verbatim)

<details><summary>P1 — <code>plans/P1.md</code></summary>

```markdown
# Certification probe (throwaway): self-repo remote census

Create `CERTIFICATION-CENSUS.md` at the repository root by running exactly this shell block once with redirection (never type the output yourself); commit only that file (plus the CHANGELOG edit where this plan asks for one); do not run the CI gate; then submit.

```sh
{
  echo "## host"; date -u +%FT%TZ; node --version; npm --version; command -v pi; pi --version
  echo "## git"; git rev-parse HEAD; git merge-base HEAD origin/main 2>/dev/null || echo "(no origin/main)"
  echo "## global @earendil-works"; G="$(npm root -g)/@earendil-works"
  for p in "$G"/*/; do n=$(basename "$p"); echo "$n $(node -p "require('$p/package.json').version")"; done
  echo "## nested under pi-coding-agent"; ls "$G/pi-coding-agent/node_modules/@earendil-works" 2>/dev/null || echo "(none)"
  echo "## worker SDK node_modules/@earendil-works"
  for p in node_modules/@earendil-works/*/; do [ -d "$p" ] && echo "$(basename "$p") $(node -p "require('./$p/package.json').version")"; done
  ls node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works 2>/dev/null || echo "(none nested)"
  echo "## .pi/npm/package.json"; cat .pi/npm/package.json 2>/dev/null || echo "(absent)"
  echo "## .pi/npm/node_modules/@earendil-works"
  for p in .pi/npm/node_modules/@earendil-works/*/; do [ -d "$p" ] && echo "$(basename "$p") $(node -p "require('./$p/package.json').version")"; done
  ls .pi/npm/node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works 2>/dev/null || echo "(none nested)"
  echo "## pi-subagents"; node -p "require('./.pi/npm/node_modules/pi-subagents/package.json').version" 2>/dev/null || echo "(absent)"
  echo "## @mgiles/perk"; node -p "require('./.pi/npm/node_modules/@mgiles/perk/package.json').version" 2>/dev/null || echo "(absent)"
} > CERTIFICATION-CENSUS.md
```
```

</details>

<details><summary>P2 — <code>plans/P2.md</code></summary>

```markdown
# Certification probe (throwaway): worker MCP + install census

Create `CERTIFICATION-CENSUS.md` at the repository root by running exactly this shell block once with redirection (never type the output yourself); commit only that file (plus the CHANGELOG edit where this plan asks for one); do not run the CI gate; then submit.

```sh
{
  echo "## host"; date -u +%FT%TZ; node --version; npm --version; command -v pi; pi --version
  echo "## git"; git rev-parse HEAD; git merge-base HEAD origin/main 2>/dev/null || echo "(no origin/main)"
  echo "## global @earendil-works"; G="$(npm root -g)/@earendil-works"
  for p in "$G"/*/; do n=$(basename "$p"); echo "$n $(node -p "require('$p/package.json').version")"; done
  echo "## nested under pi-coding-agent"; ls "$G/pi-coding-agent/node_modules/@earendil-works" 2>/dev/null || echo "(none)"
  echo "## worker SDK node_modules/@earendil-works"
  for p in node_modules/@earendil-works/*/; do [ -d "$p" ] && echo "$(basename "$p") $(node -p "require('./$p/package.json').version")"; done
  ls node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works 2>/dev/null || echo "(none nested)"
  echo "## .pi/npm/package.json"; cat .pi/npm/package.json 2>/dev/null || echo "(absent)"
  echo "## .pi/npm/node_modules/@earendil-works"
  for p in .pi/npm/node_modules/@earendil-works/*/; do [ -d "$p" ] && echo "$(basename "$p") $(node -p "require('./$p/package.json').version")"; done
  ls .pi/npm/node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works 2>/dev/null || echo "(none nested)"
  echo "## pi-subagents"; node -p "require('./.pi/npm/node_modules/pi-subagents/package.json').version" 2>/dev/null || echo "(absent)"
  echo "## @mgiles/perk"; node -p "require('./.pi/npm/node_modules/@mgiles/perk/package.json').version" 2>/dev/null || echo "(absent)"
} > CERTIFICATION-CENSUS.md
```

Then call the MCP tool `mcp__fixture__echo` once with `{"text": "perk-certification"}` and append its result with `printf '## mcp\n%s\n' '<the result text>' >> CERTIFICATION-CENSUS.md`. Then add, as the **first bullet** of the `### Fixed` section under `## [Unreleased]` in `CHANGELOG.md` (if `## [Unreleased]` has no `### Fixed` section, create one directly after the `<!-- As of … -->` line), the single bullet `- Certification probe (throwaway; never merged): worker install census. (0000000)`. Do not edit any other line of `CHANGELOG.md`. If the submit reports merge conflicts, follow its guidance to resolve them.
```

</details>

<details><summary>P3 — <code>plans/P3.md</code></summary>

```markdown
# Certification probe (throwaway): consumer composite census

Create `CERTIFICATION-CENSUS.md` at the repository root by running exactly this shell block once with redirection (never type the output yourself); commit only that file (plus the CHANGELOG edit where this plan asks for one); do not run the CI gate; then submit.

```sh
{
  echo "## host"; date -u +%FT%TZ; node --version; npm --version; command -v pi; pi --version
  echo "## git"; git rev-parse HEAD; git merge-base HEAD origin/main 2>/dev/null || echo "(no origin/main)"
  echo "## global @earendil-works"; G="$(npm root -g)/@earendil-works"
  for p in "$G"/*/; do n=$(basename "$p"); echo "$n $(node -p "require('$p/package.json').version")"; done
  echo "## nested under pi-coding-agent"; ls "$G/pi-coding-agent/node_modules/@earendil-works" 2>/dev/null || echo "(none)"
  echo "## worker SDK node_modules/@earendil-works"
  for p in node_modules/@earendil-works/*/; do [ -d "$p" ] && echo "$(basename "$p") $(node -p "require('./$p/package.json').version")"; done
  ls node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works 2>/dev/null || echo "(none nested)"
  echo "## .pi/npm/package.json"; cat .pi/npm/package.json 2>/dev/null || echo "(absent)"
  echo "## .pi/npm/node_modules/@earendil-works"
  for p in .pi/npm/node_modules/@earendil-works/*/; do [ -d "$p" ] && echo "$(basename "$p") $(node -p "require('./$p/package.json').version")"; done
  ls .pi/npm/node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works 2>/dev/null || echo "(none nested)"
  echo "## pi-subagents"; node -p "require('./.pi/npm/node_modules/pi-subagents/package.json').version" 2>/dev/null || echo "(absent)"
  echo "## @mgiles/perk"; node -p "require('./.pi/npm/node_modules/@mgiles/perk/package.json').version" 2>/dev/null || echo "(absent)"
} > CERTIFICATION-CENSUS.md
```
```

</details>

### D4 staging

- `$CLONE/.perk/local.toml` was exactly `[workflow]` / `base = "cert-target"`.
- C2 (`7e0926f38fdf450956a733da6690c748bdaa9e9f`) inserted
  `- Certification target (throwaway; never merged): the staged divergence for the resolver leg. (0000000)`
  as the first bullet of `## [Unreleased]`'s `### Fixed`.
- `plan-2759` was pre-pushed at H0. The worker's own bullet at the same point produced the
  `CHANGELOG.md` conflict.

## Teardown proof

The following were removed or closed before the block below was captured:

- **Closed:** PR #2760 (unmerged) and issues #2759, #2761, #2762 and `perk-consumer-dogfood#3`.
- **Deleted:** remote branches `cert-target` and `plan-2759`. `plan-2761` was never created, since R1
  stopped at checkout.
- **Removed:** `$TMP` (after the receipt check) and `$SCRATCH/subagents-tmp`.
- **Removed from `$WT`:** the `doctor --fix` residue (`.perk/local.toml`, `.agents/cache`,
  `.agents/local.yaml`) and the E1 bundle.
- **Restored:** `$MAIN/.pi/agent/settings.json` and `$MAIN/.perk/workflow/plan-ref.json`, from
  their backups.

```text
# teardown 2026-10-24T03:36:06Z
$ git -C $MAIN status --porcelain
(exit 0; empty)
$ git -C $MAIN rev-parse HEAD
497021367f7d4bd784c3123c611b4834480a702e
$ shasum -a 256 <MAIN staging + agent settings/trust + WT settings>
5008364f38802d392ee734c01e8525b82a361587207bf0ca9aa44b083988111a  $MAIN/.pi/npm/package.json
1bc6af5bb460aba3344da87b404b26ab1914947df97ec781c304c62c982abadc  $MAIN/.pi/npm/package-lock.json
d5095cb4d3dad11a019d2d530b84b3d1e157a24055afb1ebc85327dfdfb3e72c  $MAIN/.pi/npm/node_modules/.package-lock.json
6302e37ac9dc7eb42866aa7e09debf10f3c41f04d779207708ddbebc1292f60b  $MAIN/.pi/npm/node_modules/pi-subagents/package.json
2aae99afb27cd7a7a1abfb6d32897a3d28c4242db2c567400abd03c42054bf39  $MAIN/.pi/agent/settings.json
7a702522a062fe9c8ec6cde36726d2bb91e9d32a5cbd2f8d480d2b21ebce37fa  $MAIN/.pi/agent/trust.json
7d9749d98ae1d94f41d64958b1e65ad646d44715175abe73bb0206fe2b0f0516  $WT/.pi/settings.json
$ diff <(Step 0 hashes) <(now)
byte-equal (7/7)
$ shasum -a 256 $MAIN/.perk/workflow/plan-ref.json
6b4b287df82c308105905cb8b16ee66bf2deb7a68945f7d7fbef31e6964e5aaf
$ grep editable ~/.local/share/uv/tools/perk/uv-receipt.toml; shasum; perk --version
editable = "/Users/mattgiles/dev/github/mattgiles/perk"
871c7f977d15fceacaa99187f4aa8794969329a89efcb0f1ee27482ba3777b92
perk 4.0.0
$ pi --version; ls $(npm root -g)/@earendil-works; nested
1.1.0
chord pi-agent-core pi-ai pi-codemode pi-coding-agent pi-mcp pi-telemetry pi-tui 
1.1.0 1.1.0 1.1.0 1.1.0 1.1.0 1.1.0 1.1.0 1.1.0 
(none nested)
$ pgrep -fl perk-cert
(exit 1)
$ tmux ls
no server running on /private/tmp/tmux-502/default
$ ls -d $TMP
ls: $TMP: No such file or directory
$ git ls-remote origin cert-target plan-2759 plan-2761
(empty)
$ gh pr view 2760 / gh issue view 2759 2761 2762 / consumer#3 state
CLOSED
#2759 CLOSED
#2761 CLOSED
#2762 CLOSED
consumer#3 CLOSED
$ git -C $WT status --porcelain
(empty)
```

## `/learn` candidates

- **Stale `0.75.0` mentions** in `docs/learned/pi/subagents.md`, `docs/learned/workflow/report-waves.md`
  and `docs/learned/workflow/borrowed-packages.md` (the stamp stays 0.75.0, but the pin is 0.76.1).
- **For `docs/learned/toolchain/worktree-node-modules.md` and `docs/learned/pi/subagents.md`:**
  - Pi's `installedNpmMatchesConfiguredVersion` reinstall rule: "the settings line is the lever",
    observed on `$MAIN`.
  - #2758's clonefile staging. A pre-#2758 worktree (`plan-2757`) still shares a hard link with
    `$MAIN`'s supplier.
  - The resume-vs-stage launch difference: `perk resume` applies no skill-exposure scoping (16+23
    vs 12+2 skills), drops `PERK_RUN_ID`, and starts a fresh bridge (no `reused`).
- **For `docs/learned/workflow/plan-save-surfaces.md` and
  `workflow/mergeability-and-conflict-resolution.md`:**
  - The `plan save` run-id inheritance, and the `[workflow] base` local-overlay pin as a
    conflict-staging lever.
  - `plan save`, `implement --remote` and `/plan-save` rewrite the main checkout's `plan-ref.json`
    cache.
- **For `workflow/mergeability-and-conflict-resolution.md`:** the resolver's `just ci` →
  `install-cli` rebinding hazard. It did not fire here (the resolver chose narrower checks), and
  the containment stays.
- **For `docs/learned/pi/subagents.md`:**
  - 0.76.1's partial `results` omit running `runs.all` lanes (W6).
  - `/reload` stops in-process workflows (W7a ii).
  - `writer-close-unverified` leaves the status `unknown` (W7a i).
  - The interrupt drops Pi's queued completion notice, orphaning the reload-retained wake (W4).
- **For `docs/learned/pi/tool-loadout.md`:**
  - A cohort-deferred direct tool is still in codemode's `ALL_TOOLS`.
  - The active codemode tool survives a settings revert + `/reload` in-process.
- **Run-worker model selection:** `run-worker` passes no `--model`, so the local worker uses the
  SDK default chain, not the stage model.
- **Isolation gaps for `pi-fff`, pi-subagents and the drive-scoped `TMPDIR`:**
  - `pi-fff` and pi-subagents write into the real agent dir.
  - A drive-scoped `TMPDIR` is inherited by worker-spawned children.
- **Secret expiry:** runner PATs have an expiry that no doctor check surfaces
  (`runner-pat-secret` checks presence only).
