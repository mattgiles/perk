# Certification: Pi 1.4.0 + pi-subagents 0.81.0 on the landed tree

**Status:** dated evidence record. Measured 2026-10-25T01:34Z → 2026-10-25T03:48Z in one sitting.
Executor legs ran 01:34–02:43Z, 02:54–02:56Z (the W7a(i) re-run) and 03:28–03:48Z; owner legs ran
02:58–03:26Z. Authored 2026-10-25.

The record measures perk 4.1.0 at **H0 = `911b41484fef0539a8195915962f5047bbcebcfa`**
(`origin/main` at Step 0 = the implement branch's base = `$MAIN` HEAD) against:

- the operator's PATH **Pi 1.4.0**, installed with the single exact spec
  `npm install -g @earendil-works/pi-coding-agent@1.4.0` (one top-level package, its six companions
  nested inside it, all 1.4.0);
- **pi-subagents 0.81.0** by each installed supplier's own `package.json`, in `$WT/.pi/npm` (APFS
  clonefile), `$MAIN/.pi/npm`, `$CLONE/.pi/npm`, `$AUX/.pi/npm` and, where a leg used it,
  `$AUTHED/npm`. The registry's later 0.82.0 appears only in the Step 0 snapshot.

No H0′ was adopted. `origin/main` moved three times during the sitting, each time by the owner's
documentation commits; every drift set was confined to `docs/`, the decision rule's
source-equivalent allowlist, so nothing was invalidated and no convergence command ran:

| Drift gate (UTC) | Before | `origin/main` | Drift set (`git diff --name-only H0 origin/main`) |
|---|---|---|---|
| 01:59:50 | P2 staging | `46933378` | `docs/planning/issue-inventory-2026-10.md` |
| 02:02:24 | P2 drive | `46933378` | the same |
| 02:03:24 | R1 dispatch | `46933378` | the same |
| 02:16:09 | U-bg dispatch | `7df5fef3` | + `docs/design/archive/headless-worker.md`, `docs/design/archive/provider-contract.md` |
| 02:37:04 | W4 session | `7df5fef3` | the same |
| 03:17:05 | codemode `on` session | `6012a53f` | + `docs/planning/pi-durable-further-avenues.md` |
| 03:28:02 | codemode `only` session | `6012a53f` | the same |

Per-leg SHAs: `$WT` merge-base = H0 throughout; `$CLONE` detached at H0 and `plan-2773` pre-pushed
at H0; `$AUX` detached at H0; `$MAIN` HEAD was H0 at Step 0 and `7df5fef3` / `6012a53f` for the W4
and codemode sessions (source-equivalent); the R1 and U-bg jobs checked out `46933378` and
`7df5fef3` (source-equivalent); the R2 job checked out the consumer's `5843724f`.

Blob hashes at H0 (`git rev-parse H0:<path>`):

| Path | Blob |
|---|---|
| `src/perk/substrate/pi_host.py` | `42739be60911fffdc817ddd6db8ca54a267fbf98` |
| `src/perk/convergence/init/settings.py` | `c6266f7a07fdc4c00c0eae4006f64e1ad84dfea6` |
| `src/perk/convergence/doctor/checks.py` | `bf51284639c7f7578b176d846f4a4e128fcb594c` |
| `src/perk/run/workflow_artifacts.py` | `5139ffbea528050c14ac6057a6c35fcfbf02207d` |
| `shared/host-floor.yaml` | `f3174d96984073cff1a9bc4daef5d98ef7f22399` |
| `.pi/settings.json` | `efe9f2abdf6aef7529827b6cd3c3a8095c4150b0` |
| `.github/actions/perk-remote-setup/action.yml` | `e9543f6ffe8ad495c1f0c6478484b51c08b7e630` |
| `package.json` | `2d76ffbdacf2589560f3dc4840d8a4734c5630cb` |
| `package-lock.json` | `5a7223e33f4b12d272bfdea19716e215d3a13fd0` |

**Precedents:**

- [`pi-1.1.0-certification.md`](pi-1.1.0-certification.md): the row shape, the decision-rule
  mechanics, the instruments and the sacrificial plan bodies. Its rows are referenced, never
  rewritten: the 1.1.0 NOT RUN cells S3, S4a-live, X5a, X5b, C3-on, C1/C2/C3-only, U-bg, E5, R1 and
  R2-census are measured here as the same ids.
- [`pi-1.4.0-adoption.md`](pi-1.4.0-adoption.md): the pair adopted ahead of this certification.
- [`pi-subagents-0.76.1-lifecycle.md`](pi-subagents-0.76.1-lifecycle.md) § "Re-specified cells" and
  `docs/developers/pi-subagents-reverify.md` step 5: the W4/W6/W7a cells instantiated here.
- [`pi-subagents-0.76.1-pin.md`](pi-subagents-0.76.1-pin.md) § "The in-process identity proof":
  the I8 instrument.
- PR #2769 (the adoption) and PR #2771 (the W6 repair and the W4/W7a re-specification; also the
  PR-door subject).

## Verdict

**Verdict: PARTIAL.** The ledger has 101 rows: 91 required and 10 INFO.

- **INFO rows** (I2b, A4, A6b, S5-T4, W3, W7b, X4, X6, X7b, R2-drive): OBSERVED or recorded; X4
  and X6 are NOT RUN (not attempted).
- **PASS / MEASURED: 87 of the 91 required rows.** No row is CARRIED (no earlier record measured
  this pair live).
- **FAIL: none.** W7a(i)'s first staged run failed under the cell's original staging; the
  operator amended the staging (dated, Deviations) and the re-run passed. Run 1 stays recorded
  below as FAIL under the original staging.
- **NOT RUN: 4 required rows**, each `not attempted` — the owner ended the owner legs and chose
  PARTIAL (2026-10-25T03:45:49Z):

  | Rows | What they needed |
  |---|---|
  | X1, X2, X3 | owner keystrokes in S1 (selfcheck census + codemode census; `/plan` on/off; `/reload`, `/tree`, `/compact`, quit + `perk resume`) |
  | C3-only | two human browser DENYs in the codemode `only` session |

**Stamp: moves to 0.81.0.** Every required supplier row is PASS: S3, S4a-live, S5-T5, W1, W2, W4,
W5, W6, W7a, U-bg, X5a, X5b, I7b-PR and S7. `_SUBAGENTS_GUIDANCE_VERIFIED_VERSION` and
`tests/test_doctor.py::test_subagent_compat_verified_version_stamp_is_pinned` move to `"0.81.0"`;
`uv run perk doctor --verbose` then reads `✓ subagent-compat: pi-subagents 0.81.0 — the
guidance-verified version` (A2).

Measured rows and source-derived statements are kept separate:

- **LIVE** row: quotes a command run in this experiment against the PATH host, a real install, a
  real session or GitHub.
- **MEASURED (offline, real runtime, 1.4.0 SDK)** row: quotes a passing test line from the recorded
  TAP, spec or verbose-pytest invocations. Every such invocation's exit status was 0.
- **source-derived** statement: cites the lockfile-pinned
  `$WT/node_modules/@earendil-works/*/dist` files or `$WT/.pi/npm/node_modules/pi-subagents/src`
  (the source mirror has no `v1.4.0` tag, verified at Step 0).

## The decision rule (verbatim, pinned before measurement)

- **Required rows** are every row in families O, I, A, S, W, E, H, M, U, X, C, R not marked INFO. **INFO rows (never gating):** I2b, A4, A6b, S5-T4, W3, W7b, X4, X6, X7b, R2's drive outcome (R2-drive), U-fg when unstageable after one retry. **K rows are outside the counted gate**: each is a retention review — status RETAINED or RETIRED — citing the evidence rows it rests on (INFO rows allowed, e.g. K2 ← X4) and its re-checked retirement condition; a K row never becomes PASS/FAIL/NOT RUN and never moves the verdict.
- **NOT RUN reasons** are closed: `prerequisite` (a precondition **outside the pair** was absent — see the evidence-classification rule), `unstageable` (a **completed** drive could not produce the leg's condition after its allowed retry, or a staged-cell row's staging rule was not met after its three allowed stagings), `blocked (<row>)` (the row's only vehicle ended in another required row's FAIL — or, for **R2-census only**, in the INFO row R2-drive's non-completion after the composite's install steps succeeded, because that drive runs the released 4.1.0 worker, which is outside the pair; counts as NOT RUN), `not attempted` (time or owner availability). A NOT RUN is never a FAIL and never "met". **Staged cells** (W4, W6, W7a(i), W7a(ii), S5-T5) whose staging rule is not met are **re-run, never scored**, up to three stagings each; the fourth would-be run is instead `NOT RUN (unstageable)` with every staging recorded.
- **Evidence-classification rule (one causal rule, fixed before measurement).** `prerequisite` requires **independent evidence of the external cause recorded beside the row**: a runner secret absent or stale by name and date (`gh secret list`), a fixture unreachable (`git ls-remote` / `gh api` failure), or a **credential control** failing outside the pair. **Credential controls:** (local) before each local drive, for every model the drive will actually use: (i) the worker's own selection — `env $SCRUB PI_CODING_AGENT_DIR=$AUTHED pi --approve --mode json -p "Reply with exactly OK."` run from `$CLONE` with **no `--model`** (the same default-selection path the worker takes: no explicit model, a project `.pi/settings.json` without `defaultModel`, a global tier without one), whose JSON stream names the model it dispatched → recorded as `$WORKER_MODEL`; (ii) the resolver's binding, the same command with `--model openai/gpt-6-luna` — each under the watchdog → exit 0 and an assistant turn — recorded. The drive's run comment `Model: selected=…` must equal `$WORKER_MODEL`; if it does not, the control is re-run on the model the drive actually selected before any row riding that drive is classified (a dated note, not an amendment). (remote) presence by name is the only pre-check; with the key present, a worker or child auth failure is a FAIL unless the operator proves the key value invalid out-of-band (a direct provider call with the same value fails), a dated Deviation that reclassifies that row to `prerequisite`. With the controls green, any `runtime_init`, `model_auth`, `no_extension_tools`, zero-turn or classifier-auth exit **inside** the worker or a worker-spawned child is a **FAIL on the drive's row** (R0 for the local drive, R1 for the self-repo remote drive) and every row riding that drive is `blocked (<that row>)`; `model_not_found`/`no_model` likewise. The staging exemption (`unstageable`) is reserved for a drive whose `run_finished` is `completed/submit_tool` without a conflict.
- **Drift rule (a multi-sitting run).** `H0` = `git rev-parse origin/main` at Step 0 = the implement branch's base. Before each `origin/main`-reading leg (the P2 staging, each `perk plan` owner session from `$MAIN`, each `--remote` dispatch) and at the start of every sitting: `git fetch origin && git diff --name-only H0 origin/main`. Empty → proceed. Otherwise the **drift set** (that file list) decides mechanically. **Set A** (`extension/`, `agents/`, `prompts/`, `skills/`, `.agents/skills/`, `shared/`, `.pi/settings.json`, `package.json`, `package-lock.json`) → S, W, X, C, M, U, H, R1, I4–I8, E and K are invalidated. **Set B** (`src/perk/`, `shared/`, `pyproject.toml`, `uv.lock`, `.perk/config.toml`, `.perk/required-perk-version`, `.github/`, `.pi/settings.json`) → I, A, R, M, U, E1 and E5 are invalidated. **Set C** (only `tests/` or `extension/**/*.test.ts`) → the offline tier recordings (O) are re-run. **Source-equivalent (an explicit allowlist, nothing else):** `docs/` (excluding nothing under it, since no measured path reads `docs/`), `CHANGELOG.md`, `CONTEXT.md`, `README.md`, `LICENSE`, `.github/ISSUE_TEMPLATE/**` — a change confined to these invalidates nothing and is recorded as source-equivalent. **Any other path** (unlisted) is treated as Set A ∪ Set B and recorded with the reason. **Recovery from an invalidating drift:** rebase the implement branch onto `origin/main`; `git -C $MAIN pull --ff-only`; set `H0 :=` the new `origin/main`; **converge the installations** — in `$WT`: `uv sync --all-packages && npm ci` (the `[worktree] setup` commands, re-run by hand since the setup marker is already cleared), and the same in `$CLONE`/`$AUX` if they exist; **re-verify the pair** (Step 0's "On the pair" bullet: the installed supplier `0.81.0`, the dev pins `1.4.0`, the PATH `pi` 1.4.0 nested layout) — if the drift moved any of the five version facts or the dev pins, the certification subject moved: stop and replan (never measure a different pair under this record); **restart the measuring activation** — `/quit` S1 and `perk resume <run id>` before any in-process re-run (I7a, I7b, X rows, the PR door, S7), and launch every scripted/owner leg in a fresh process as always; then re-run every invalidated measured leg; legs not invalidated keep their evidence, each recorded with the SHA it ran at and the drift set's non-intersection as its source-equivalence proof. Every leg records its SHA (`$WT`: `git merge-base HEAD origin/main`; `$MAIN`/`$CLONE`: `git rev-parse HEAD`; remote: the job log's checkout SHA + `position_branch`'s positioning line + the census's `## git` block). The record's Status names H0 (and every H0′ adopted), the drift sets, and the convergence commands run.
- **Verdict.** `CERTIFIED` iff every required row is PASS/CARRIED/MEASURED. `PARTIAL` iff no required row FAILs but ≥ 1 required row is NOT RUN. `HELD` iff any required row FAILs.
- **The stamp (independent of the verdict).** `_SUBAGENTS_GUIDANCE_VERIFIED_VERSION` and `tests/test_doctor.py::test_subagent_compat_verified_version_stamp_is_pinned` move to `0.81.0` iff every **required supplier row** is PASS/CARRIED: **S3** (scout wave), **S4a-live** (mixed siblings + structured completion), **S5-T5** (untrusted-project discovery refusal), **W1, W2, W4, W5, W6, W7a**, **U-bg**, and the four browser-door cells **X5a, X5b, I7b-PR, S7**. Any NOT RUN or FAIL among them keeps the stamp at 0.75.0. `CERTIFIED` implies the stamp moves; `PARTIAL`/`HELD` combine with either stamp outcome.
- **The prose matrix (both dimensions, fixed now).** Every evidence-contingent surface carries two independent slots: (a) the *pair* slot — `CERTIFIED`: "certified on the exact pair by `pi-1.4.0-certification.md` (<date>); a later Pi is admitted but uncertified" / `PARTIAL`: "adopted; the certification record `pi-1.4.0-certification.md` (<date>) holds <n> required cells NOT RUN (<ids>)" / `HELD`: "adopted; the certification record `pi-1.4.0-certification.md` (<date>) holds <k> required FAIL(s) (<ids>) — the support claim is held"; (b) the *stamp* slot — moved: "the guidance stamp is 0.81.0 (the certification's supplier rows passed) and `subagent-compat` reads ok on a converged checkout" / stayed: "the guidance stamp stays 0.75.0 (<the failing/NOT RUN supplier rows>) and `subagent-compat` warns by design". The executor fills the slots from the measured outcome and chooses nothing.
- Amendments to this rule after measurement begins are dated operator decisions recorded in the record's Deviations section, never silent.

**Amendment (2026-10-25T02:54:34Z, operator):** W7a(i)'s staging additionally requires the child's
`events.jsonl` to show `subagent.run.started` before the abort. A stop that lands before the runner
starts its Pi child is a separate, recorded constrained capability: the engine's proof is honestly
`unknown` (`writer-close-unverified`) and perk renders it `child termination unconfirmed (unknown:
…)`. Run 1 stays FAIL under the original staging; only W7a(i) is re-run under the amended staging.

## Path abbreviations

| Abbreviation | Path |
|---|---|
| `$MAIN` | the main checkout, `/Users/mattgiles/dev/github/mattgiles/perk` |
| `$WT` | the implement worktree, `$MAIN/.worktrees/plan-2772` |
| `$SCRATCH` | `$WT/.perk/workflow/scratch/runs/01M5RB1PRYTYW25KSTDPZQKWXX/agent/certification` (gitignored; logs copied to `$SCRATCH/logs`) |
| `$TMP` | `mktemp -d -t perk-cert` (`…/T/perk-cert.3BRtdbO6N9`, removed at teardown) |
| `$AUTHED` | `$TMP/agent-authed`: a copy of `$MAIN/.pi/agent/auth.json` only |
| `$CLONE` | `$TMP/clone` (no-hardlinks clone, detached at H0) |
| `$AUX` | `$TMP/aux-clone` (bare-loading clone: no `node_modules` or `.venv`, an independent `.pi/npm`) |
| `$LOGS` | `$TMP/logs`, copied to `$SCRATCH/logs` |
| `$MODEL` | `anthropic/claude-haiku-5-5`, the cheapest Anthropic model in `pi-ai` 1.4.0's `dist/providers/data/anthropic.json` (input 0.1 / output 0.5) |
| `$WORKER_MODEL` | `anthropic/claude-opus-4-8`, the no-`--model` credential control's selection from `$CLONE` |

## Snapshot matrix

| Item | Value |
|---|---|
| perk | 4.1.0 (`perk --version`, `uv run perk --version` in `$WT`) at H0 |
| Editable CLI | `~/.local/share/uv/tools/perk/uv-receipt.toml` `editable = "$MAIN"`, sha256 `871c7f977d15fceacaa99187f4aa8794969329a89efcb0f1ee27482ba3777b92`. Identical before the P2 drive, throughout it (the observer saw no change), after the post-drive `just install-cli`, and at teardown |
| PATH `pi` | `~/.local/share/mise/installs/node/26.12.1/bin/pi` → `…/@earendil-works/pi-coding-agent/dist/bundle/cli.js`; `pi --version` 1.4.0 |
| Global layout | `$(npm root -g)/@earendil-works` = `pi-coding-agent` only (1.4.0); nested `pi-coding-agent/node_modules/@earendil-works` = `pi-agent-core pi-ai pi-codemode pi-mcp pi-telemetry pi-tui`, each 1.4.0 |
| node / npm / uv | v26.12.1 / 11.20.0 / 0.13.5 |
| Dev pins | `$WT/node_modules/@earendil-works/*` seven at 1.4.0, none nested; devDependencies `pi-agent-core`/`pi-ai`/`pi-coding-agent`/`pi-tui` `1.4.0`, `typebox` `1.3.27`; `engines.node` `^22.23.4 \|\| ^24.22.1 \|\| ^26.12.1` |
| Suppliers `$WT` | `.pi/settings.json` `npm:pi-subagents@0.81.0`; installed 0.81.0; `.pi/npm/package.json` inode 483986165, link count 1 (clonefile); pi-web-access 0.37.0; @plannotator/pi-extension 0.28.8; @tombell/pi-diff 0.0.4; @ff-labs/pi-fff 0.11.0; rpiv-todo 2.12.0; rpiv-ask-user-question 2.12.0; ponytail 5.0.0 |
| Suppliers `$MAIN` | the same versions; `.pi/npm/package.json` inode 481703563, link count 1; `pi-subagents/package.json` link count 1 |
| Suppliers `$CLONE` / `$AUX` | `cp -R $MAIN/.pi/npm`: inodes 484507763 / 484393391, link count 1, pi-subagents 0.81.0 |
| Floor / pin constants | floor `pi.min_version` 1.4.0, Node 22.23.4 (+ line floors 24.22.1, 26.12.1); `PI_ADOPTED_VERSION` 1.4.0; `PI_INSTALL_SPECS` the one exact spec; `PI_INSTALL_COMMAND` `npm install -g @earendil-works/pi-coding-agent@1.4.0`; `REMOTE_PI_VERSION = PI_ADOPTED_VERSION`; `SUBAGENTS_PACKAGE` `npm:pi-subagents@0.81.0`; stamp 0.75.0 at Step 0 |
| Registry dist-tags (Step 0) | `@earendil-works/pi-coding-agent` `latest` 1.4.0, `legacy-node20` 0.74.2; `pi-subagents` `latest` **0.82.0** (a later release, not substituted); `@mgiles/perk` 4.1.0 |
| Runner secrets | perk: `ANTHROPIC_API_KEY` 2026-07-04, `NPM_TOKEN` 2026-09-23, `OPENAI_API_KEY` 2026-10-25T01:31:22Z, `PERK_GH_PAT` 2026-10-25T01:30:01Z; consumer: `ANTHROPIC_API_KEY` 2026-07-06, `PERK_GH_PAT` 2026-10-25T01:30:10Z |
| Credential controls (from `$CLONE`, under `$AUTHED`) | (i) no `--model` → `anthropic/claude-opus-4-8` `OK`, exit 0, 22 s (= `$WORKER_MODEL`); (ii) `--model openai/gpt-6-luna` → `OK`, exit 0, 7 s |
| S1 (implement session) | run `01M5RB1PRYTYW25KSTDPZQKWXX`, Pi session `01a170b1-3155-7077-a2c0-9e5e6b984ad4`, model `anthropic/claude-opus-5-5`, agent dir `$MAIN/.pi/agent`; launched on the pair from its first process |
| W4 session | `uv run perk plan` from `$MAIN` (tmux, executor-driven): run `01M5REPKQJYS1GJ6TS7AD19NFJ`, Pi session `01a170eb-515a-774d-bb8a-5b6a99ecef72`, model `anthropic/claude-fable-5-1` |
| Codemode `on` session | `uv run perk plan` from `$MAIN` (owner): run `01M5RH4QEAM86VJHX2D0JA8P4S`, Pi session `01a17112-644a-7751-bc91-6c345f447e25`, model `anthropic/claude-fable-5-1` |
| Codemode `only` session | `uv run perk plan` from `$MAIN` (tmux, executor-driven): run `01M5RHKSPP472HZ31NA7FMQ4KE`, Pi session `01a17119-e8f0-77c1-9c78-e3e49b93d231` |
| P2 (local drive) | issue #2773, saved from `$CLONE` with run id `01M5RCMK2GR9TYWJVVTZS9Q82C`, header `base: cert-target`; drive run `01M5RCPVMBW7712AZCAQM0FT5G`; PR #2775 (base `cert-target`) |
| C2 | `6e455d0e9a424cf3bf6bfa25ee8cdd48a2b1e5b5` on `cert-target` |
| P1 (self-repo remote) | issue #2774; implement dispatch run_id `01M5RCRSQPSJPMWCPE3HHK5B68`, run_ref `40152994186`, PR #2776; address dispatch run_id `01M5RDG7A2K3RKTKT9TQKRP8DC`, run_ref `40153817184` |
| P3 (consumer) | `mattgiles/perk-consumer-dogfood#4`; dispatch run_id `01M5RCV1FMD8E8ND987VMK5SVD`, run_ref `40153069379`, consumer PR #5; fixture commit `5843724f` |
| P4 | the never-saved draft body for the W4 and C3 sessions (sha256 `b3e74d47…`) |
| Staging hashes | `$MAIN/.pi/npm/{package.json, package-lock.json, node_modules/.package-lock.json, node_modules/pi-subagents/package.json}`, `$MAIN/.pi/agent/{settings.json, trust.json}` and `$WT/.pi/settings.json`: byte-equal at Step 0 and at teardown (Teardown proof) |

## Offline tier

| Row | Recording | Window (UTC) | Result | Exit |
|---|---|---|---|---|
| O1 | `just test-js-slow` (TAP → `slow.tap`) | 01:39:11–01:40:56 | 1066/1066 `ok`, 0 `not ok` | 0 |
| O2 | `just test-js-fast` (TAP → `fast.tap`) | 01:40:56–01:41:25 | `# tests 3012` / `# pass 3012` / `# fail 0` / `# skipped 0` | 0 |
| O3 | `uv run pytest -rfEs` | 01:41:25–01:44:22 | `8546 passed, 1 skipped in 171.98s` (the skip: `test_native_sdk_bridge_live.py:152: needs a below-floor PATH pi (this one is admitted)`) | 0 |
| O4 | `pytest -v -n0` named set (fourteen files) | 01:44:22–01:46:26 | `772 passed in 120.95s` | 0 |
| O5 | `tests/test_native_sdk_bridge_live.py` | 01:46:26–01:47:07 | `2 passed, 1 skipped in 8.69s` | 0 |
| O6 | `node --test` I5–I6–E set (nine files) | 01:47:07–01:47:24 | `ℹ tests 101` / `ℹ pass 101` / `ℹ fail 0`; `✔ census drift guard: the installed consumers import exactly NATIVE_SDK_CENSUS` (it RAN) | 0 |
| O7 | `node --test extension/worker/sdkAdapter.test.ts` (H2) | 01:47:24–01:47:27 | `ℹ tests 50` / `ℹ pass 50` / `ℹ fail 0` | 0 |
| O8 | `just prose-review-test` / `just prose-review-check` | 01:47:27–01:49:09 | `560 passed, 6 warnings`; `tsc --noEmit` clean, `ℹ tests 367` / `ℹ pass 367` / `ℹ fail 0`, `✓ built` | 0 / 0 |
| O9 | one run-all `run_ci` immediately before `/submit`, on this record's tree plus the CHANGELOG bullet | at submit | green (`/submit` is gated on it) | — |

Verdict: O1–O9 PASS (MEASURED). No TypeScript source moved after O1, so the slow tier was not
re-run.

## I — Installs and identity

| Row | Procedure | Verbatim observation | Verdict | Class |
|---|---|---|---|---|
| I1 | Step 0 re-read: CLI identity and layout | `pi --version` 1.4.0, the realpath above, one global package with six nested companions at 1.4.0; perk 4.1.0, editable receipt `$MAIN` | PASS | LIVE |
| I2a | Dev pins, lockfile, named pin tests | seven `node_modules/@earendil-works/*` at 1.4.0, none nested; `tests/test_packaging.py::test_pi_toolchain_pin_lockstep PASSED`; `tests/test_pi_host.py::test_pinned_install_family_is_closed_against_the_characterized_lockfile PASSED`; `::test_the_family_declares_itself_exactly_in_the_characterized_lockfile PASSED`; `::test_install_command_is_the_pinned_set PASSED`; `::test_remote_install_pin_is_the_adopted_pin PASSED`; `tests/test_host_floor.py::test_real_host_floor_loads_validates_and_pins_the_floors PASSED` | PASS | LIVE + MEASURED |
| I2b | Floating non-family transitives (INFO) | `undici 8.10.2` (plus `jsdom/node_modules/undici 7.29.0`); `@anthropic-ai/sdk 0.129.0`; `marked-cjk-friendly 0.1.2` | OBSERVED | LIVE |
| I3 | Suppliers, staging method, pin tests | the supplier versions in the Snapshot matrix in both `$WT/.pi/npm` and `$MAIN/.pi/npm`; `.pi/npm/package.json` link count 1 in each, distinct inodes (483986165 vs 481703563); `test_the_installed_pi_subagents_is_the_managed_pin PASSED`; `tests/test_init_idempotent.py::test_subagents_borrow_is_version_pinned PASSED` | PASS | LIVE + MEASURED |
| I4 | Bare-clone loading from `$AUX`: `$SCRUB <hermetic> pi --approve --mode json -p /perk-selfcheck` under the watchdog + `bareImportGuard.test.ts` | `perk: selfcheck — 4.1.0: ok; shared=ok; ambient=reached (append=5376c); agents=reached (files=1); bridge=installed`; `npm:pi-subagents@0.81.0=1`; `host sdk: 1.4.0 (floor >= 1.4.0)`; `native sdk bridge: installed (roots=2, specifiers=8)`; 0 `Failed to load extension`; exit 0, 10 s. Guard 2/2 | PASS | LIVE |
| I5 | Host identity + bridge | the codemode `on` session's owner-typed selfcheck (JSONL line 8) and X7a: `host sdk: 1.4.0 (floor >= 1.4.0)`, `native sdk bridge: installed (roots=2, specifiers=8)`, `agents=reached`; the census drift guard RAN and passed in O6 | PASS | LIVE + MEASURED |
| I6 | Lazy imports / reload | `entryAdmission.test.ts` in O6 (101/101); live: an executor-driven interactive session in `$WT` (tmux, hermetic agent dir) read `native sdk bridge: installed (roots=2, specifiers=8)` before `/reload` and `installed (roots=2, specifiers=8, reused)` after | PASS | LIVE + MEASURED |
| I7a | `run_librarian {action: "refresh-docs", slug: "divio-documentation"}` from S1 (03:31:04–03:33:25Z, line 582) | published 8 pages, failures 0, scope `/`; receipt agent `perk.librarian`, `nativeStatus: "completed"`, exitCode 0, `termination: "confirmed"`, `bracket.ok: true`; runId `0c894514-2098-48a6-8f6c-ed6237a10668`, model `openai/gpt-6-sol`, 16 turns, 134489 ms, $0.195; capability audit `allowedAgents []`; `$MAIN` porcelain empty before and after | PASS | LIVE |
| I7b-plan | `start_draft_review_wave` launch (codemode `on` session, line 36) | asyncId `5697ca96-948e-4b77-8d66-6b7e12285ac1`; `launch.requested` = `launch.runnable` = `["grounding","decision-completeness","risk","ponytail"]`; `preflightFailures: []` | PASS | LIVE |
| I7b-PR | `start_review_wave` launch (S1, line 505) | asyncId `b148e0da-831e-47c1-816b-712fe8b63597`; requested = runnable = `[claimed-intent, correctness, tests, ponytail]`; `preflightFailures: []` | PASS | LIVE |
| I8 | The in-process identity proof, bridge on/off (`probe-foreground.ts`, the module tracer, one `perk.scout` child via `dispatchForeground` under `$AUTHED`) | ON (pid 4114): bridge `active`, both roots `bridged` before and after; status `completed`, value `{"ok": true}`, runId `578820ee-ff9c-4ef3-83a3-e81e4249c830`, `termination: "confirmed"`; census `seen` 276, **`leaks` 0**; exit 0, 10 s. OFF (`PERK_DISABLE_NATIVE_SDK_BRIDGE=1`, pid 4506): bridge `disabled`; child completed, `termination: "confirmed"`; census `seen` 301, **`leaks` 25** (`@earendil-works/pi-coding-agent` → the dev pin ×7, `pi-tui` ×5, `typebox` ×4, `pi-ai` ×3, `typebox/compile` ×3, `pi-agent-core` ×2, the host-entry `file:` URL ×1); 0 load errors, no watchdog line in either log | PASS | LIVE |

## A — Admission, doctor, convergence

| Row | Procedure | Verbatim observation | Verdict | Class |
|---|---|---|---|---|
| A1 | Live stubs `old` (`echo 1.1.0`) and `none` under `script -q /dev/null uv run perk`, plus the typed read via `_resolve_pi_executable` / `_admit_pi_host` (`a1-typed.py`) | old: "pi at $STUBS/old/pi is version 1.1.0; perk requires Pi >= 1.4.0. Upgrade it: npm install -g @earendil-works/pi-coding-agent@1.4.0 — perk init and perk doctor report the same requirement." exit 1. none: "pi CLI not found on PATH — install it: npm install -g @earendil-works/pi-coding-agent@1.4.0 (perk requires Pi >= 1.4.0 and Node.js on a supported release line: 22.x >= 22.23.4, 24.x >= 24.22.1, 26.x >= 26.12.1)." exit 1. Typed codes `pi_version_unsupported` / `pi_cli_missing`; the real host `admitted` 1.4.0 | PASS | LIVE + MEASURED |
| A2 | `uv run perk doctor --verbose` + `--json` from `$WT` (01:50:18Z), re-run after the stamp moved (03:41Z) | `pi` `status: "ok"`, detail `1.4.0 (floor >= 1.4.0)`, `remediation: ""`; `node` ok v26.12.1; `settings-wiring` ok; `artifact-health` ok ("7 managed artifacts up-to-date"); `subagent-package-scope` ok; `subagent-compat` **warn** (installed 0.81.0 vs stamp 0.75.0), healthy (42 ok, 4 warn), exit 0. After the stamp: `✓ subagent-compat: pi-subagents 0.81.0 — the guidance-verified version — report-only — the install is pinned by settings-wiring (npm:pi-subagents@0.81.0)` (the only non-ok row then is `config`, the gitignored `.perk/local.toml` removed at teardown) | PASS | LIVE |
| A2b | Companion-family refusal | `tests/test_pi_host.py::test_real_probe_of_the_broken_layout_is_incoherent PASSED`; `::test_incoherent_refusal_text_and_error_type PASSED`; `tests/test_env.py::test_pi_incoherent_is_not_ok PASSED` | MEASURED | MEASURED |
| A3e | Extension refusal on a real 1.1.0 (`$TMP/pi-global/1.1.0`, the eight 1.1.0-era exact specs; "added 130 packages in 13s"; eight top-level at 1.1.0, none nested) | `test_a_below_floor_real_pi_refuses_to_load_perk PASSED` (`1 passed in 16.38s`); raw `-p /perk-selfcheck`: `Failed to load extension … perk requires Pi >= 1.4.0; the Pi running this session is 1.1.0 (@earendil-works/pi-coding-agent VERSION) …`, naming `…/requirements-and-compatibility.md#version-compatibility`; exit 1, 8 s; 0 selfcheck lines. PATH `pi` still 1.4.0 afterwards | PASS | LIVE + MEASURED |
| A3w | Worker refusal on a real old SDK (`$AUX` `npm install --no-save` the eight 1.1.0 specs; "added 525 packages") | `error.type: "pi_version_unsupported"` "perk worker: the loaded Pi SDK (@earendil-works/pi-coding-agent) is version 1.1.0; perk requires Pi >= 1.4.0. …"; exit 1, 10 s; events `run_started` → `run_finished` | PASS | LIVE |
| A4 | Skew admission (INFO) | the registry's `latest` is 1.4.0 = the adopted pin: no newer release at Step 0, so the live arm has no subject. Skew admission stays MEASURED (`tests/test_pi_host.py`, O4) | OBSERVED (no newer release) | — |
| A5 | Node + remote agree (static) | `action.yml:21`, `ci.yml:33`, `release.yml:153,185` all `node-version: "22.23.4"`; `Install pi` = `npm install -g @earendil-works/pi-coding-agent@1.4.0`; `engines.node` `^22.23.4 \|\| ^24.22.1 \|\| ^26.12.1`; `test_committed_self_repo_remote_artifacts_are_the_owners_render PASSED`; the live replay is R1 | PASS | LIVE + MEASURED |
| A6a | `doctor --fix` recovery (delete `defaultTools` from `$WT/.pi/settings.json`) | drift line `settings-wiring drift — .pi/settings.json: compaction: reserveTokens=65536; defaultTools: +tool_search`; Fixed the same; `git diff --exit-code` exit 0; hash back to `f00ec02e…` | PASS | LIVE |
| A6b | Literal `PI_INSTALL_COMMAND` on a throwaway prefix under `mise exec node@22.23.4` (INFO) | node 22.23.4 / npm 10.9.9; "added 119 packages in 10s"; one top-level `pi-coding-agent`, six nested at 1.4.0; only `bin/pi`; `pi --version` 1.4.0 | OBSERVED | LIVE |
| A7 | `uv run perk init` ×2 from `$WT` with operator edits (`defaultTools: ["-tool_search"]`, `tuiMode: "regular"`) | zero changes both times (settings sha `ab61fbb0…` before = after both runs); exit 2 on the worktree skills sync (recorded, not a Pi effect); edits reverted; doctor healthy | PASS | LIVE |
| A8 | Write admission live, before §1.3 | bare `perk doctor --fix --json` (the editable `$MAIN` install) → exit 2, `error_type: "foreign_perk"`, "perk 4.1.0 is running from $MAIN, not from this checkout ($WT). … run them as `uv run perk …` here."; human arm exit 2; nothing written. `uv run perk doctor --fix` in `$WT` → exit 0, `Fixed: .perk/local.toml: created` (the expected fresh-worktree overlay) plus the skills-sync conflict; healthy (42 ok) | PASS | LIVE |
| A8b | Write admission, nested worktree | `tests/test_write_admission.py::test_a_nested_worktrees_perk_never_converges_main PASSED`; `::test_a_self_repo_that_is_not_the_running_checkout_is_foreign PASSED`; `::test_a_nested_worktrees_perk_converges_its_own_worktree PASSED` | MEASURED | MEASURED |

## S — Supplier children

| Row | Procedure | Verbatim observation | Verdict | Class |
|---|---|---|---|---|
| S1 | Bridge-live suite (O5) | `test_the_installed_pi_subagents_is_the_managed_pin PASSED`; `test_real_pi_selfcheck_reports_the_bridge_installed_and_both_consumers_loaded PASSED`; the below-floor arm skips here and runs as A3e | MEASURED | MEASURED |
| S2 | Offline wave suites | `ok 2680 - durable partial arrays take precedence in full: no event promotion or hole filling`; `ok 2681 - partial carrier cannot bypass unreadable status, nonterminal states, or generic failure`; `ok 2682 - partial normalization keeps absent, malformed and failed reports distinct`; `ok 2791 - W6: a roster-only running lane is lane-failed at native partial settlement; a roster-only lane whose runId does not correlate stays withheld`; `ok 2792 - W6: the durable workflow.value array is still the carrier; the roster only names the unfinished lane`; `ok 2793 - W6: a mismatched inventory withholds the diagnosis — the running lane stays missing-lane` | MEASURED | MEASURED |
| S3 | `run_scout_wave` with two briefs (`archive-headings`, `floor-claims`) in the codemode `on` session (line 71 → 72, 03:25:00.805Z) | `ok: true`; attempt `{flow: "scout", attempt: 1, state: "complete"}`, run `0143619a-ee79-4d6b-81a7-065589e2e9c2`; children `archive-headings` and `floor-claims` `success: true`, agent `perk.scout`, each child `status.json` `complete` with model `openai/gpt-6-sol`; both reports schema-valid `SCOUT_REPORT_SCHEMA` (`scope`, `findings` 2 and 4, `open_questions`) | PASS | LIVE |
| S4a-live | `probe-spawn.ts` `mixed` via `$SCRUB <authed> pi --approve --mode json -e … -p "/probe-spawn script $MODEL mixed"` from `$WT`; the structured half from S3 | spawn `success: true` (asyncId `6fbedb96-c3b7-48b7-b5c7-33c7fd154f32`); `status.json` `complete`; `workflow.value` `[{key: "probe-ok", ok: true, error: null}, {key: "probe-bad", ok: false, error: "Unknown subagent model 'perk-probe/does-not-exist' in the active Pi model registry."}]`; the probe-ok child log carries `[READ-ONLY MODE] (unscoped)` and its recovery descriptor `extensionBindings {"perk.parent-restrictions/1":{"readOnly":true}}`, model `$MODEL`; no probe-bad child dir; 0 load errors; exit 0, 13 s. Structured half: S3's schema-valid reports on the production transport | PASS | LIVE |
| S4b | Cancellation | → W7a | (W7a) | — |
| S4c | Deadline partial | → W6 | (W6) | — |
| S5-T1 | Packet delivery under `--approve`, no trust store (`probe-spawn.ts` `restricted`) | workflow `complete`, `workflow.value` `[{key: "probe", ok: true}]`; child log `[READ-ONLY MODE] (unscoped)`; descriptor `extensionBindings` readOnly; 0 trust lines; no `trust.json` written; exit 0, 8 s | PASS | LIVE |
| S5-T4 | `--no-approve` structural negative, project supplier only (INFO) | ping and spawn `probe-timeout`; no run dir; exit 0, 62 s | OBSERVED | LIVE |
| S5-T5 | Untrusted-project discovery refusal (staging and arms in Methodology) | staging met on the first staging: (a) `/probe-trust` → `isProjectTrusted: false`, (b) → `true`; (a) `ping` answered. **(a)** `--no-approve`: spawn `success: false`, `error.code: "execution_failed"`, message `{"ok":false,"errors":[{"kind":"agent","message":"runs.all item: Unknown agent 'project-marker'. Available agents:\n- claude-code (builtin) … - worker (builtin)", …}]}` — no run dir of any kind (no workflow dir, so no `start` record and no child dir). **(b)** `--approve`: spawn `success: true` (asyncId `5662cd28-a832-41d0-bf2d-599e2ea345c6`), `workflow.value` `[{key: "probe-project", ok: true}]`, child dir `36ea77bb…` (agent `project-marker`, output `OK`). **(c)** (INFO) the model's explicit `agentScope: "project"` call returned `agentScope: "project" requires project trust. This session declined trust for /private/var/…/untrusted, so project agents and project subagent settings are ignored. Re-run with agentScope: "user" or approve the project folder.` Sub-clause falsified: the refusal arrives at spawn preflight, so no lane ever "settles"; no FAIL clause holds | PASS (falsified sub-clause) | LIVE |
| S6 | Task restoration | `ok 903 - a live task is left alone: no restore, the gate allows before and after`; `ok 909 - control (active turn): a lane compacted before reporting is continued with its task restored` | MEASURED | MEASURED |
| S7 | Repeated collection in one activation (S1, line 529, 03:04:47.142Z) | `isError`, `{ok: false, error_type: "no_wave"}`, "no review wave is running in this activation — launch one with start_review_wave (collection is per activation: a wave launched before a /reload or a session switch is never collectable here, and no completion notice or wake is promised afterwards)" | PASS | LIVE |

## W — The supplier lifecycle legs

Every leg was followed by stop-and-confirm (`$SCRATCH/stop-confirm.sh`): async run dirs and
`status.json` states listed; every runner pid gone; `$WT/.pi/settings.json`,
`$MAIN/.pi/agent/settings.json` and `$MAIN/.pi/agent/trust.json` hashes unchanged
(`stop-confirm-*.log`). Every `/probe-wave` call carried `<mode> $MODEL`.

| Row | Procedure | Verbatim observation | Verdict | Class |
|---|---|---|---|---|
| W1 | `pi --approve --mode json -e probe-wave.ts -e probe-listener.ts -p "/probe-wave two $MODEL"` (02:18:18Z) | handle `e5560847-ac80-49e5-b9b2-1043c1261462`. Child `subagent:async-complete` payloads `88ffcd90` (02:18:41.706Z) and `4ed8b933` (02:18:43.631Z): `awaitedByWorkflow: true`, `parentWorkflowRunId` = the handle, mode single, agent `perk.scout`, ids/asyncDirs distinct from the handle's. Workflow payload 02:18:43.919Z (`awaitedByWorkflow` absent). Collect: `running` at 18246 ms, `settled` at 25940 ms (after the workflow payload). `complete: true`, reports lane-a and lane-b, `failures: []`; receipt children success; RPC sends `ping`, `spawn`. Exit 0, 31 s | PASS | LIVE |
| W2 | Same probe, fresh processes | `/probe-wave latency`: first `ping` reply at **124 ms** after `session_start`; first `spawn` reply (`wave.start` resolved) at **519 ms**. `/probe-foreground-latency`: `started` at 132 ms, **2 ms** after dispatch; foreground completed, `termination: "confirmed"` (runId `3eeb3662…`) | PASS | LIVE |
| W3 | Duplicate load under remembered trust (INFO): user-scope `packages: ["npm:pi-subagents@0.81.0"]` + `trust.json` | Pi installed into `$AUTHED/npm` ("added 7 packages in 7s"; the installed `package.json` 0.81.0); wave `complete: true`; 0 `perk: waves` lines, 0 `no_active_session` (no ghost observed); `doctor` (`PI_CODING_AGENT_DIR=$AUTHED`) `subagent-package-scope` **warn** "user: $AUTHED/settings.json; project: $WT/.pi/settings.json. pi dedupes packages by identity (project wins), but pi 0.85.1 loads user-scope extensions before project trust resolves …"; entry, `trust.json` and `$AUTHED/npm` removed afterwards | OBSERVED | LIVE |
| W4 | The guide's step-5 W4 cell (tmux `w4`, executor-driven, P4) | Staged on staging 1. (1) `plan_draft` (line 21) `sha256:b3e74d47…`. (2) `/plan-review-browser` → `start_draft_review_wave` result line 28 (02:38:52.114Z) `ok: true`, asyncId `e48192a5-5a7a-42f3-83c5-91390f69495b`, runnable `[grounding, decision-completeness, ponytail]`. (3) the `sleep 170` prompt → `bash` call line 31 at 02:39:07.000Z. (4) `status.json` `endedAt` 02:39:32.330Z (`complete`), the `bash` still running. (5) Escape at 02:39:47Z → line 32 `bash` result "Command aborted" (02:39:47.889Z), three `subagent-incremental-child-notify` (lines 33–35), line 36 assistant `stopReason: "error"`. (6) 30 s idle editor. (7) `/reload` 02:40:26Z → "Reloaded keybindings, extensions, …"; `status.json` `complete`, `workflow.value` three `ok: true` entries. (8) 60 s idle editor. (9) the collect prompt 02:41:37Z → `collect_draft_review_wave` line 44 `{ok: false, error_type: "no_wave", error: "no draft-review wave is running in this activation — … (collection is per activation: …)"}`. (10) `status.json` `complete`, three `ok: true`. Between (5) and (9) the JSONL holds no assistant message, no custom-message-started turn and no `subagent-notify` (the absence is recorded, not scored) → (a), (b), (c) met | PASS | LIVE |
| W5 | T2 (remembered trust, no flag) and T3 (`defaultProjectTrust: "always"`, `trust.json` removed), one restricted lane each | T2: `trust.json` `{"<realpath $WT>": true}`; child `21349e18` `[READ-ONLY MODE] (unscoped)`, descriptor `extensionBindings` readOnly, lane `ok: true`, no trust diagnostic, exit 0, 6 s. T3: child `4716d646` the same; no `trust.json` written; exit 0, 8 s | PASS | LIVE |
| W6 | `PERK_WAVE_TIMEOUT_MS=20000`, `/probe-wave deadline $MODEL` | Runs 1 (the 600-word lane) and 2 (`PROBE_LONG_WORDS=2500`) **not staged**: `lane-long` completed before the deadline (`complete: true`, both reports), never scored. Run 3 (staged; `PROBE_LONG_TASK` = "First run exactly `sleep 75` with bash (one call). Then read AGENTS.md and summarize it in 600 words."): RPC sends exactly `ping`, `spawn`; collect `running` 15531 ms → `settled` 20671 ms; `complete: false`; `reports` = `[lane-quick]`; `failures[0]` `{key: null, reason: "run-failed", detail: "wave run ended 'failed' (native partial: timeout): Workflow script timed out after 20000ms."}`; `failures[1]` `{key: "lane-long", reason: "lane-failed", detail: "lane still running at native partial settlement"}`; receipt `state: "failed"`, children `lane-quick` only. The completion payload (02:21:31.715Z) carried `terminalOutcome {state: "partial", reason: "timeout"}` and `results` `[lane-quick]`; `status.json` `workflowChildren` (`inventoryComplete: true`) `lane-long` `running` at settlement → criteria (1)–(6) met | PASS | LIVE |
| W7a | (i) cancel-while-running; (ii) reload-then-stop (tmux `w7aii`, executor-driven) | **(i) run 1** (staged under the original staging; the 600-word lane; `PROBE_CANCEL_DELAY_MS=10000`): abort 02:23:33.914Z with the child `running`, pid 25424; stop reply 02:23:33.936Z `success: true`; detail "wave 'scout' was cancelled; stop requested; child termination unconfirmed (pending: async workflow child lane-long is still running)"; scored status at stop + 60 s → `workflowTerminalProof {state: "unknown", reason: "async workflow child lane-long process-terminal proof is unknown"}` (child `process-terminal.json` `unknown`, `writer-close-unverified`, runner close exitCode 0) → **FAIL under the original staging**. The child's events show `subagent.run.started` at 02:23:35.904Z, after the stop: the runner had not started its Pi child. **(i) re-run** (amended staging, staging 1; probe sha `dba8bc36…`): child `subagent.run.started` 02:54:56.768Z; abort 02:55:06.804Z (child `running`, pid 33098); stop reply 02:55:06.839Z `success: true`; immediate proof `pending` ("async workflow child lane-long is still running"); status at stop + 60 s → **`observed`** (child `3c34014c` observed). **(ii)** `/probe-wave start-long` → handle `682930f6-2c65-4e42-9ca9-d3e1b96b7e5e`; < 1 s before `/reload` both `status.json` read `running` (workflow pid 29384, child pid 29637); after `/reload` the workflow is `stopped` "Workflow stopped because the extension session was replaced or reloaded." (`stopCause: null`); `/probe-stop` raw `{success: false, error: {code: "invalid_state", message: "Async run 682930f6-… is stopped; stop only supports running or queued async runs, or a paused whole run."}}`; adapter `{acknowledged: false, reason: "invalid_state: Async run … is stopped; …"}`, proof `pending`; rendered "stop refused (invalid_state: …); child termination unconfirmed (pending: async workflow child lane-long is still running)" | PASS (under the dated amendment; run 1 FAIL recorded) | LIVE |
| W7b | Model-facing `interrupt` / `stop` in the no-perk project `$TMP/noperk` (INFO) | user-scope `npm:pi-subagents@0.81.0` (installed 0.81.0), `anthropic/claude-sonnet-5-5` via `subagent` (after `subagents_enable`); async worker `7bded9c1-82f1-46ea-b380-5186504d2fa5`; `interrupt` → "Interrupt requested for async run …"; notice "Background task paused: **worker** … Paused after interrupt. Waiting for explicit next action."; status `paused`, process terminal observed; `stop` → "Stopped paused async run 7bded9c1-…." (the seal); status `stopped`, Error "Subagent stopped."; notice "Background task stopped: **unknown** …"; exit 0, 47 s. A single async run, not a workflow | OBSERVED | LIVE |

## E — Evidence and restoration

| Row | Procedure | Verbatim observation | Verdict | Class |
|---|---|---|---|---|
| E1 | `uv run perk learn evidence --render --json` from `$WT` after the owner legs (03:34Z) | exit 0; `success: true`, `plan_id: "2772"`; `render.sessions[0]` (`planning-session/main`): `entries_read: 202`, `malformed_lines: 0`, **`system_states: 3`**, `system_malformed: 0`; `grep -c '<system_state'` over the two chunks = 3 | PASS | LIVE |
| E2 | Nested evidence | `tests/test_learn_session_jsonl.py::test_nested_calls_project_the_released_grammar PASSED`; `::test_nested_calls_status_kept_verbatim_or_unknown PASSED` (and the other eight `test_nested_calls_*`) | MEASURED | MEASURED |
| E3 | MCP read-only floor + nested policy | `ok 1969 - direct call: the floored report child and the /plan gate block the MCP tool as not allowlisted; read-write does not block`; `ok 1970 - nested call: ctx.executeTool on the MCP tool meets the backstop (parent call id kept) …`; `ok 1972 - codemode script: in a cohort /plan gate the MCP builtin's auto-activated codemode stays on (lifted), …`; `ok 2295 - the nested policy holds under a child floor and inside the restoration window` | MEASURED | MEASURED |
| E4 | Restoration windows | `ok 2284 - the restoration window: a reload session_start or a session_tree opens it …`; `ok 2286 - the restoration window's close: agent_start installs the pre-change target and clears the memos; …`; `ok 2287 - the restoration window: a /tree restore that replaces the loadout supersedes the reload's pending family deferral …`; `ok 2289 - the restoration window stays shut at startup, and a bare session's agent_start installs nothing` | MEASURED | MEASURED |
| E5 | `perk pr feedback --json` on the P1 PR beside U-bg's classification | run from `$CLONE` with its plan-ref temporarily pointed at #2774 (restored after): exit 0; `counts {review_threads: 1, unresolved_threads: 0, discussion_comments: 0, reviews: 2}`; thread `PRRT_kwDOSru__s6v9oS-` resolved, `CERTIFICATION-CENSUS.md:48`, comment 4369343113; `pr: 2776` | PASS | LIVE |
| E6 | Own-name activation | `extension/substrate/ownNamesActivation.test.ts` in O6: all 12 titles `✔` (spike A/B, gate entry/exit, stage change, owner deactivation + re-advertisement, initially inactive, child-engine, bare session, registry filters, codemode, nested execution, hidden host) | MEASURED | MEASURED |

## H — Worker (offline e2e, real runtime, 1.4.0 SDK)

All 48 `e2e:` titles of `extension/worker/stageExecutionE2e.test.ts` are `ok` in `slow.tap` (lines
`ok 1019`–`ok 1066`; the list is in `$SCRATCH/H-lines.txt`). No title present at H0 falls outside
the families below.

| Row | Quoted lines (abridged) | Verdict |
|---|---|---|
| H1a | `ok 1045 - e2e: discovery opt-in — …`; `ok 1046 - e2e: discovery opt-out (-tool_search) — …`; `ok 1047 - e2e: -builtin:<name> disables a worker builtin — …` | MEASURED |
| H1b | `ok 1029 - e2e: no_model is decided AFTER extension registration (order pin) → zero-turn failed/no_model`; `ok 1030` (throwing availability read); `ok 1031` (explicit `--model`); `ok 1032` (default selection); `ok 1033 - … → zero-turn failed/model_auth`; `ok 1034 - … → zero-turn failed/model_not_found` | MEASURED |
| H1c | `ok 1048 - e2e: builtin:mcp connects the project's .pi/mcp.json — …`; `ok 1049 - e2e: a default-exposure project server is reached from the worker's builtin codemode, …`; `ok 1051 - e2e: -builtin:mcp disables the worker's MCP builtin — …` | MEASURED |
| H1d | `ok 1019 - e2e: implement HAPPY — …` through `ok 1028 - e2e: BUDGET — …` (10 titles) | MEASURED |
| H1e | `ok 1061 - e2e: COMPACTS IN-DRIVE AND COMPLETES — …`; `ok 1064` (token cap); `ok 1062 - e2e: RETRY RECOVERS — …`; `ok 1066` (retries exhausted); `ok 1065 - e2e: PREFLIGHT ABORT CANCELS A TURN-1 COMPACTION — …` | MEASURED |
| H1f | `ok 1063 - e2e: PROJECT OPT-OUT HONOURED — …` | MEASURED |
| H1g | `ok 1038 - e2e: MODEL-TOOL direct — …`; `ok 1039`; `ok 1040 - e2e: CODEMODE classify across the cap …`; `ok 1044 - e2e: PRODUCTION SHAPE — …`; `ok 1041`; `ok 1042`; `ok 1043` | MEASURED |
| H1h | `ok 1035 - e2e: the real worker entry admits the installed SDK and drives to completion, independent of PATH and the CLI stamp` | MEASURED |
| H2 | `H2.log`: `ℹ tests 50` / `ℹ pass 50` / `ℹ fail 0` | MEASURED |
| H3 | `ok 1048 - … its log lands in the throwaway dir; nothing global is read or written`; `ok 1050 - e2e: child-auth stand-ins — mid-drive, a subagent child's in-process and background construction calls resolve the REAL agent dir and its auth` | MEASURED |
| H4a–H4i | `ok 1052` (HTTP explicit header credentials) · `ok 1053` (registrations beside/colliding) · `ok 1054` (unavailable OAuth) · `ok 1055` (connection failures silent headless) · `ok 1056` (`enabled:false`) · `ok 1057` (mid-drive registration; expired session) · `ok 1058` (abort cancels an in-flight call) · `ok 1059` (abort during the startup wait) · `ok 1060` (shutdown closes every transport first) | MEASURED (9 rows) |
| H5a | `ok 1036 - e2e: a virtual model routes to a physical target with a different identity → completed`; `ok 1037 - e2e: a \`:thinking\` suffix on --model survives the reorder → …`; H2.log `✔ createDriveSession: selectedModel reads the session's selection before bind, after a failed bind, and null without one` | MEASURED |
| H5b | `tests/test_run_report.py::test_model_line_joins_every_dispatched_identity_in_order PASSED`; `::test_usage_line_renders_fresh_cache_and_cost PASSED`; `::test_step_summary_carries_model_and_usage_lines PASSED`; `::test_model_none_renders_unavailable_distinct_from_a_selectionless_session PASSED` | MEASURED |
| H5c | `ok 1496 - selfcheck (live): a session that never answered reports dispatched=none, n/a and unavailable usage` | MEASURED |

## M — Worker MCP (the local clone drive, P2)

| Row | Procedure | Verbatim observation | Verdict | Class |
|---|---|---|---|---|
| M1 | Project `.pi/mcp.json` fixture (`token cert-project`) reached by the worker's model | project marker pid 6231 at 02:03:20Z; calls log `{"at":"2026-10-25T02:03:55.432Z","id":3,"pid":6071,"args":{"text":"perk-certification"},"token":"cert-project"}` (pid = the worker); worker session line 29 `mcp__fixture__echo` details `{server: "fixture", tool: "echo"}`; census `## mcp` `perk-certification` | PASS | LIVE |
| M2 | `mcp.log` under the throwaway agent dir mid-drive; the dir gone after exit | `mcp.log` (45 bytes, beside a 23-byte `settings.json`) under `tmp-p2/perk-worker-agent-IQWCp6` at 02:03:55Z; that dir gone after exit; `perk worker: mcp config error` absent. **Sub-clause falsified** (as at 1.1.0): `ls $TMP/tmp-p2` was not empty — 2786 entries of the resolver child's `just test` residue (`perk-cwd-*` 1121, `perk-agent-*` 984, `perk-fake-subagents-*` 132, …) | PASS (falsified sub-clause) | LIVE |
| M3 | Global canary `$AUTHED/mcp.json` never spawns | no `mcp-global-canary.pid`, no `$AUTHED/mcp.log`; `auth.json`, `models-store.json`, `sessions/*` and the existing `missions/*` byte-equal. **Sub-clause falsified** (as at 1.1.0): `fff/frecency/{data,lock}.mdb` and `fff/history/lock.mdb` changed (pi-fff writes `PI_CODING_AGENT_DIR`), and `missions/` gained entries | PASS (falsified sub-clause) | LIVE |

## U — Subagent under the worker

| Row | Procedure | Verbatim observation | Verdict | Class |
|---|---|---|---|---|
| U-fg | The staged `/submit` conflict → `resolve_submit_conflicts` → in-process `perk.conflict-resolver` | `events.ndjson`: `submit` ok (seq 22, t=78500), `resolve_submit_conflicts` ok (seq 23, t=813480), `submit` ok (seq 24, t=824752), `run_finished` `completed/submit_tool` PR #2775. Submit #1 (line 47) `mergeable: false`, `conflicts: ["CHANGELOG.md"]`, base `cert-target`. Resolve (line 50) `kind: "resolved"`, report `{mode: "pr-rebase", outcome: "completed", verification: "passed", push: "succeeded"}`; receipt `termination: "confirmed"`, lock `released`, runId `8289c6e7-ce65-4cf0-bae3-884172f54ee0`, `nativeStatus: "completed"`, agent `perk.conflict-resolver`, exitCode 0. Meta: model `openai/gpt-6-luna`, 15 turns, 733024 ms, $0.0087; capability audit `allowedAgents []`; 0 `Intercom orchestration channel`, 0 `contact_supervisor`. Submit #2 (line 53) `existed: true`, `mergeable: true`, `conflicts: []`. PR #2775 (base `cert-target`) holds both CHANGELOG bullets. The resolver verified with `just test` (×3) after `uv sync --all-packages`, **not** `just ci`, so the receipt never moved | PASS | LIVE |
| U-bg | `uv run perk address 2774 --remote` after one review thread on PR #2776 (posted by the executor via `gh api` with the owner's approval: `CERTIFICATION-CENSUS.md:48`, comment 4369343113) | run `40153817184` success: `run-worker: positioned plan-2774 at the remote tip`; worker model `anthropic/claude-opus-4-8`; `classify_review_feedback` ok (seq 2, t=30460), `finalize_address` ok (seq 11, t=143469); `run_finished` `completed/address_resolved` (9 turns, 143475 ms); thread `PRRT_kwDOSru__s6v9oS-` `isResolved: true` with the worker's reply ("The file already ends with exactly one trailing newline at EOF. Verified three ways …"); run comment `Model: selected=anthropic/claude-opus-4-8; dispatched=anthropic/claude-opus-4-8 ×9` / `Usage: records=9; fresh=7393 (in=18 out=7375); cache read=271999 write=39473; cost=$0.5672`. The `perk.review-classifier` background child (`openai/gpt-6-sol`) completed with a bound classification with `OPENAI_API_KEY` present by name | PASS | LIVE |

## R — Remote and the local drive

| Row | Procedure | Verbatim observation | Verdict | Class |
|---|---|---|---|---|
| R0 | Local drive `uv run perk run-worker --run-id 01M5RCPVMBW7712AZCAQM0FT5G --stage implement --plan 2773` from `$CLONE`, `TMPDIR=$TMP/tmp-p2`, `PI_CODING_AGENT_DIR=$AUTHED`, watchdog GRACE 60 / CAP 5400 | `run-worker: positioned plan-2773 at the remote tip`; `perk worker: model anthropic/claude-opus-4-8`; 02:02:37–02:17:00Z, exit 0, 863 s; `run_finished` `completed/submit_tool`; 14 turns. `CERTIFICATION-CENSUS.md` on `plan-2773`: global `pi-coding-agent 1.4.0` + the six nested each 1.4.0; worker SDK seven at 1.4.0, `(none nested)`; `.pi/npm` `@earendil-works` `(none nested)`, pi-subagents 0.81.0; `merge-base` H0; `## mcp perk-certification`. Run comment `Model: selected=anthropic/claude-opus-4-8; dispatched=anthropic/claude-opus-4-8 ×14` (= `$WORKER_MODEL`) / `Usage: records=14; fresh=3581 (in=27 out=3554); cache read=431847 write=78933; cost=$0.7982` | PASS | LIVE |
| R1 | `uv run perk implement 2774 --remote` (dispatch 02:03:24Z) | `doctor workflow check --verbose` exit 0 (github-auth, github-repo, runner-pat-secret, runner-model-secret `ANTHROPIC_API_KEY, OPENAI_API_KEY`, runner-workflow). Run `40152994186` success: checkout `46933378`; `Set up Node` 22.23.4; `Install perk` `uv tool install --from . perk`; `Install pi` `npm install -g @earendil-works/pi-coding-agent@1.4.0` ("added 119 packages"); `Install Node worker deps` `npm ci` ("added 531 packages"); `run-worker: plan branch plan-2774 not found; creating it from origin/main`; `perk worker: implement completed (submit_tool) pr=#2776 · 5 turns, 1578 tok, 59144ms`. Census: host v22.23.4 / npm 10.9.9, `pi` 1.4.0 at `/opt/hostedtoolcache/node/22.23.4/x64/bin/pi`; global `pi-coding-agent 1.4.0` + six nested 1.4.0; worker SDK seven at 1.4.0, `(none nested)`; `.pi/npm` pi-subagents 0.81.0; `merge-base` `46933378`. Run comment `Model: selected=anthropic/claude-opus-4-8; dispatched=… ×5` / `Usage: records=5; fresh=1578 …; cost=$0.3096`; artifact `perk-run-01M5RCRSQPSJPMWCPE3HHK5B68` `run_started` → `run_finished` `completed/submit_tool` | PASS | LIVE |
| R2-census | Consumer composite (`$TMP/consumer` at `6a23863`) | `perk init` (editable 4.1.0) exit 0: `@mgiles/perk@4.0.0 → 4.1.0`, `pi-subagents@0.76.1 → @0.81.0`; `action.yml` node 22.23.4, `uv tool install perk==4.1.0`, `Install pi` the one exact 1.4.0 spec, `npm install @mgiles/perk@4.1.0 @earendil-works/pi-coding-agent@1.4.0 --prefix .pi/npm --legacy-peer-deps --save-exact`; commit `5843724f` pushed; workflow check exit 0 (advisory "Actions cannot create PRs"). Run `40153069379` success; census on `plan-4`: global `pi-coding-agent 1.4.0` + six nested 1.4.0; `.pi/npm/package.json` `"@earendil-works/pi-coding-agent": "1.4.0"` (exact) and `"@mgiles/perk": "4.1.0"`; `.pi/npm/node_modules/@earendil-works` seven **hoisted** at 1.4.0, `(none nested)`; pi-subagents 0.81.0; `@mgiles/perk` 4.1.0 | PASS | LIVE |
| R2-drive | INFO: worker = the released perk 4.1.0 (PyPI) + `@mgiles/perk` 4.1.0 (npm) — the pre-adoption exterior/interior artifacts — on the 1.4.0 SDK and the 0.81.0 supplier | `run-worker: worker entry=…/.pi/npm/perk-worker/extension/workerMain.ts (consumer-npm)`; `perk worker: implement completed (submit_tool) pr=#5 · 4 turns, 1514 tok, 47640ms`; run comment `Model: selected=anthropic/claude-opus-4-8; dispatched=… ×4` / `Usage: records=4; fresh=1514 …; cost=$0.1823` | OBSERVED (completed) | LIVE |

## X — Sessions and surfaces

| Row | Procedure | Verbatim observation | Verdict | Class |
|---|---|---|---|---|
| X1 | Owner `/perk-selfcheck`, a `tool_search` activation, a codemode census after a temporary `+codemode` (S1) | not run: the owner ended the owner legs and chose PARTIAL | NOT RUN (not attempted) | — |
| X2 | Owner `/plan` on → probes → `/plan` off (S1) | not run (as X1) | NOT RUN (not attempted) | — |
| X3 | `/reload`, `/tree`, `/compact` + one turn, quit + `perk resume <run id>` (S1) | not run (as X1). I6's `/reload … reused` reading was taken in an executor-driven session instead | NOT RUN (not attempted) | — |
| X4 | `/btw` ×2 + "Inject summary" (INFO) | not run | NOT RUN (not attempted) | — |
| X5a | Plan door five criteria (codemode `on` session) | See Browser doors: criteria 1–5 met | PASS | LIVE |
| X5b | PR door five criteria (`/pr-review-browser 2771`, S1) | See Browser doors: criteria 1–5 met | PASS | LIVE |
| X6 | Regular vs fullscreen (INFO) | not run | NOT RUN (not attempted) | — |
| X7a | Headless `$SCRUB <hermetic> pi --approve --mode json -p /perk-selfcheck` from `$WT` (01:38:42Z) | `perk: selfcheck — 4.1.0: ok; … agents=reached (files=1); bridge=installed`; `tools: 48 active / 67 registered`; discovery cohort; `host sdk: 1.4.0 (floor >= 1.4.0)`; `native sdk bridge: installed (roots=2, specifiers=8)`; 0 `Failed to load extension`; exit 0, 2 s | PASS | LIVE |
| X7b | Print-mode exit pair on stderr (INFO) | W1's print-mode run: `This extension ctx is stale after session replacement or reload. …` ×2 and `turn_end could not resolve the persisted assistant entry ID` ×1 | OBSERVED | LIVE |

## C — Codemode in a recorded read-only stage (`perk plan`)

The vehicle was the user-scope `$MAIN/.pi/agent/settings.json` += `"defaultTools": ["+codemode"]`,
`"codemode": {"mode": "on"}` (then `"only"`), restored at the end (sha256 `2aae99af…` before =
after). Each session was a fresh `uv run perk plan` from `$MAIN`; line 4 of each JSONL holds
`perk:workflow-state {mode: "read-only", stage: "plan"}`.

- `on` session (owner): selfcheck #1 (line 8) `tools: 18 active / 67 registered`, `builtin=6`
  (codemode declared), discovery cohort; selfcheck #2 (line 79) `20 / 67`, `builtin=6`. Its system
  prompt declares `read`, `bash`, `codemode`, `ffgrep`, `fffind`, `tool_search`,
  `ask_user_question`, `web_enable` and the plan tools.
- `only` session (executor-driven in tmux `conly`): selfchecks (lines 8, 22) `18 / 67`,
  `builtin=6`; its system prompt declares only `codemode`, `plan_draft`, `plan_review`,
  `run_librarian`, `run_scout_wave`, `start_draft_review_wave`, `tool_search` — `only` lifted.

| Row | Procedure | Verbatim observation | Verdict | Class |
|---|---|---|---|---|
| C1-on | One script batching `objective_stack_status({})`, `read AGENTS.md`, `bash git log -1 --oneline` | ONE codemode call (line 16); result line 17 (03:20:27.712Z): `objective_stack_status` `ok` (1792 ms), `read` `ok` (19 ms), `bash` `ok` (52 ms); the query value is structured `{ok: true, objective: "2767", status: {success: true, delivery: "incremental", train: null, no_train: "this objective uses incremental delivery; no delivery train exists", operations: [] …}}`; "Script completed / Wall time 2.0 seconds" | PASS | LIVE |
| C2-on | A script calling `tools.write({path: "cert-probe.txt", content: "x"})` | ONE codemode call (line 20); line 21 nested `write` `status: "error"`, `error: "perk read-only mode: write is blocked (file modifications disabled)."`; `$MAIN/cert-probe.txt` absent | PASS | LIVE |
| C3-on | `plan_draft` (direct) → `plan_review` → deny → revise → `plan_review` → deny | v1 `plan_draft` direct (line 26 → 31) `sha256:b3e74d47…`, 567 bytes; DENY #1 (line 54, 03:22:52.549Z) "The human DENIED the plan in the browser review — revise the working draft with plan_draft per this feedback; …" (names the writer); v2 `plan_draft` (line 61 → 66) `sha256:8222c606…`, 3238 bytes (distinct digest); `plan_review` (line 67 → 68) `{status: "completed", approved: false, feedback: "… Denied again — do not revise further; stop."}`; codemode declared throughout (both selfchecks `builtin=6`); never `/plan-save` | PASS | LIVE |
| C1-only | The C1 script in the `only` session | ONE codemode call (line 15) → line 16 (03:28:40.751Z): `objective_stack_status` `ok`, `read` `ok`, `bash` `ok` (git head `6012a53f`) | PASS | LIVE |
| C2-only | The C2 script in the `only` session | ONE codemode call (line 19) → line 20 (03:29:20.505Z): nested `write` `error` "perk read-only mode: write is blocked (file modifications disabled)."; file absent | PASS | LIVE |
| C3-only | Draft → deny → revise in the `only` session | not run: it needs two human browser DENYs and the owner had ended the owner legs | NOT RUN (not attempted) | — |

## Browser doors

### X5a — the plan door (codemode `on` session, JSONL `01a17112-…`)

| Criterion | Evidence | Met |
|---|---|---|
| 1. Launch | line 36 (03:21:25.254Z): requested = runnable `[grounding, decision-completeness, risk, ponytail]`, `preflightFailures: []` | yes |
| 2. Collect after the workflow notice | child notices lines 38–41 (03:21:59.024–03:22:10.143Z); workflow `subagent-notify` line 42 (03:22:10.438Z); `collect_draft_review_wave` line 44 (03:22:13.016Z) `complete: true`, covered 4/4, `failures: []`, `attempts[0]` `{flow: "draft-review", attempt: 1, state: "complete"}`, every child `success: true` | yes |
| 3. Delivery per angle, `replace: true` | grounding line 46; decision-completeness, risk and ponytail lines 50–52 (a first attempt to batch the three from one codemode script, line 47, was refused per nested call — see Constrained capabilities) | yes |
| 4. Decision after the last receipt | last receipt line 52 (03:22:26.546Z); DENY #1 line 54 (03:22:52.549Z); the second review's DENY returned at line 68 (03:23:52.581Z); nothing saved, no `/plan-save` | yes |
| 5. Owner observation | marker, in the owner's words *while the wave ran* (pasted in S1 line 547 at 03:21:52.211Z, before the first child notice): "Reviewer wave running — 4 lane(s): grounding, decision-completeness, risk, ponytail. Findings land here as annotations when the wave completes; decide after they arrive." The grounding annotation (merging the decision-completeness concern) returned in the DENY #1 feedback | yes |

Receipts (lines 46, 50–52):

| Angle | ok | mode | pushed | held | held_batches | deleted |
|---|---|---|---|---|---|---|
| grounding | true | plan | 1 | 0 | 0 | 0 |
| decision-completeness | true | plan | 0 | 0 | 0 | 0 |
| risk | true | plan | 0 | 0 | 0 | 0 |
| ponytail | true | plan | 0 | 0 | 0 | 0 |

### X5b — the PR door (`/pr-review-browser 2771`, S1)

| Criterion | Evidence | Met |
|---|---|---|
| 1. Launch | door turn line 501 (02:58:07.787Z); `start_review_wave` line 505 (02:58:29.053Z): requested = runnable `[claimed-intent, correctness, tests, ponytail]`, `preflightFailures: []` | yes |
| 2. Collect after the workflow notice | child notices lines 509–512 (02:59:42.807–03:00:41.319Z); `subagent-notify` line 513 (03:00:41.627Z); `collect_review_wave` line 522 (03:04:39.222Z) `complete: true`, 4/4, `failures: []`, `attempts[0]` `{flow: "adversarial-review", attempt: 1, state: "complete"}`, every child `success: true` | yes |
| 3. Delivery per angle, `replace: true` | lines 524–527 (03:04:45.023–.274Z) | yes |
| 4. Decision after the last receipt | last receipt line 527 (03:04:45.274Z); the owner saw the pushed annotation and then closed the tab ("i already closed the tab", line 541); nothing posted to GitHub (0 reviews on #2771 since 02:58Z); no browser respond message arrived | yes |
| 5. Owner observation | marker, in the owner's words (line 519, 03:04:24.077Z — after the workflow completed, before collection, while the code-owned marker still showed): "Reviewer wave running — 4 lane(s): claimed-intent, correctness, tests, ponytail. Findings land here as annotations when the wave completes; decide after they arrive." Annotations: "yes, I see the ponytail annotation" (line 535) | yes |

Findings: claimed-intent, correctness and tests clean (claimed-intent fyi only); ponytail (minor,
high) `docs/developers/pi-subagents-reverify.md:333`: the live-cell procedures are duplicated in
the dated lifecycle archive. Receipts: claimed-intent / correctness / tests `{ok: true, mode:
"review", pushed: 0, skipped: [], held: 0, held_batches: 0, deleted: 0}`; ponytail `{ok: true,
mode: "review", pushed: 1, held: 0, held_batches: 0, deleted: 0}`. Afterwards
`perk pr review cleanup --pr 2771` → "✓ removed review worktree review-2771".

## K — Keep-and-reverify (outside the gate)

Retirement conditions re-checked by anchor on the lockfile-pinned 1.4.0 dist.

| Row | Adaptation | Re-verified by | Retirement condition re-checked | Status |
|---|---|---|---|---|
| K1 | Host SDK bridge (`extension/substrate/nativeSdkBridge.ts`) | I5, I7a, I7b-plan, I7b-PR, S1, S3, **I8** | `pi-coding-agent/dist/core/extensions/loader.js` still has `const usesEmbeddedModules = isBunBinary \|\| isNodeSeaBinary \|\| isBundledNode;` and the `{ virtualModules: await getVirtualModules(), tryNative: false }` branch. The bridge retires only when the bridge-off control observes zero escapes; I8's control observed **25** | RETAINED |
| K2 | `/btw` live-runtime adaptation (`extension/vendor/btw/btw.ts`) | X4 (NOT RUN) | `pi-coding-agent/dist/core/model-registry.d.ts` still declares `private readonly runtime;` with no public accessor (source-derived) | RETAINED |
| K3 | Canonical projection + delivery predicates | E4, E6 (MEASURED); X3 NOT RUN | Pi projects the context; perk still verifies delivery on the selected branch (the restoration-window and own-names suites pass on the 1.4.0 SDK) | RETAINED |
| K4 | RPC context-less / stale-responder guards | S2; W3 (0 `no_active_session`); W7a (the RPC stop/status path answered) | a fix to Pi's separate `RpcClient` is not replacement evidence | RETAINED |
| K5 | Worker `finishTurn` gate + codemode `models: false` + `perk-worker-policy` | H1g | `pi-agent-core/dist/types.d.ts` `type: "tool_execution_update"` still carries no `usage` | RETAINED (CONSTRAINED) |
| K6 | Browser-owner adaptations: the code-owned `perk:wave` marker, and post-collection `push_annotations` | X5a, X5b (marker observed live on both doors; receipts) | `@plannotator/pi-extension` 0.28.8 still exposes no wave-status channel (no `wave` in its sources), so perk still owns the marker and the push | RETAINED |

## Classification lists

### Supported behavior

- Host admission on the bundled 1.4.0 CLI and the below-floor / missing-host refusals (A1, A3e,
  A3w); write admission (A8), doctor recovery (A6a), init idempotence (A7).
- Bare-clone loading, the bridge and its reload reuse (I4–I6); the in-process identity (I8).
- The in-process blocking children (I7a, U-fg) and the worker-spawned background child (U-bg).
- Worker MCP from the project config, with the global config untouched (M1, M3).
- The self-repo and consumer remote composites on the single-spec install (R1, R2-census).
- Codemode batching and the nested write refusal in `on` and `only` (C1, C2); draft → deny →
  revise with codemode declared (C3-on).
- Both browser doors to N/N with the marker observed (X5a, X5b), wave launch (I7b-plan, I7b-PR) and
  the per-activation collect refusal (S7, W4).
- Awaited-child events (W1), lazy-loading latency (W2), trust rows (W5, S5-T1), the untrusted
  discovery refusal (S5-T5), the deadline partial (W6), cancellation and reload-then-stop (W7a).

### Configuration opt-outs

- Discovery opt-out (`-tool_search`, H1a); compaction opt-out (H1f); `-builtin:mcp` (H1c).
- The user-scope `+codemode` / `codemode.mode` keys (the C vehicle).

### Retained adaptations

- K1–K6.

### Constrained capabilities

- **W7a(i) stop before the runner starts its Pi child:** pi-subagents 0.81.0 writes a permanent
  `unknown` (`writer-close-unverified`) process-terminal proof when the runner closes having never
  started a writer (`src/runs/background/process-terminal.js`,
  `allWriters.length === 0 && expectedEntries.length === 0`); perk renders it unconfirmed. The
  file is byte-identical in 0.82.0.
- **A nested action tool from a codemode script** is refused under the read-only gate
  (`push_annotations` from one script; the model recovered with direct calls).
- **M2/M3:** the drive-scoped `TMPDIR` reaches the resolver child; pi-fff and pi-subagents write
  into the real agent dir.

### Deferred work

- X1, X2, X3 and C3-only → a future certification's owner legs.
- The guide's W7a(i) staging row (`docs/developers/pi-subagents-reverify.md` step 5) should adopt
  the amended staging; this record does not move the guide's procedure.
- An upstream pi-subagents issue for the never-started-writer proof (draft in
  `$SCRATCH/upstream-issue-draft.md`, for the owner to file).
- A pi-subagents 0.82.0 bump must handle its new default `autoResume: true` (reload- or
  exit-interrupted workflows resume on reopen), which conflicts with perk's per-activation wave
  collection unless set to `false` (from an `npm pack` read of 0.82.0, never installed where this
  pair was measured).

## Falsified planning-time assumptions

- **"E6 measures own-name reconciliation under `toolActivation` `dynamic`/`eager`"** → no
  `toolActivation` setting exists in the 1.4.0 dist or in perk; E6 is the `ownNamesActivation.test.ts`
  suite as it stands (12/12).
- **"The 600-word `lane-long` outlasts a 20 s deadline"** → it finished in time twice (also at 2500
  words: the scout report's bounded shape makes length irrelevant); a `sleep 75` first step staged
  W6.
- **"W7a(i)'s staging (child `running` with a pid) guarantees a provable stop"** → a stop landing
  before the runner starts its Pi child leaves the proof permanently `unknown`
  (`writer-close-unverified`); the amended staging requires `subagent.run.started`.
- **"S5-T5 (a) settles a lane `ok: false`"** → the refusal arrives at spawn preflight
  (`execution_failed`, "runs.all item: Unknown agent 'project-marker'."): no workflow dir, no lane.
- **"A scratch agent dir isolates agent discovery"** → (a)'s available-agents list includes
  `diag-runner (user)` from the real `~/.agents` (`buildAgentDiscoverySources` reads
  `os.homedir()/.agents`).
- **"The remote `.pi/npm` matches the local one"** → Pi installs the remote `.pi/npm` from caret
  specs, so non-pinned siblings resolve newer on the runner (ponytail `^5.3.2`, plannotator
  `^0.28.30`, pi-web-access `^0.44.0`, rpiv `^2.15.0`); pi-subagents is exact.
- **"Saving a plan and dispatching `--remote` leave `$MAIN` unchanged"** (as at 1.1.0) → `plan save`,
  `implement --remote` and `address --remote` rewrote `$MAIN/.perk/workflow/plan-ref.json`; restored
  byte-equal each time.
- **"`perk pr review cleanup` removes every PR-door checkout"** → plannotator's own PR pool
  worktree (`…/T/plannotator-pr-mattgiles-perk-2771-…/pool/pr-2771`) stayed registered in
  `$MAIN`'s worktree list; removed at teardown.
- **"A DENY carries the human's comment"** → plannotator's deny has no dialogue; a comment rides
  the global annotation box. The first DENY therefore carried only the annotations — including a
  stale "Perk detached this review — the session reloaded or was replaced. …" note although the
  review was live (its decision reached the session), likely restored from the earlier W4 review
  surface.
- **The `subagent-package-scope` warn detail names "pi 0.85.1"** — a stale version in perk's own
  detail text.

## Deviations (dated)

- **2026-10-25 ~01:56Z (operator):** the untracked `$MAIN/docs/planning/issue-inventory-2026-10.md`
  (created after Step 0 by the owner's parallel session) is the owner's and was excluded from the
  teardown comparison (it was committed at `46933378` before teardown); the owner legs were batched
  after the executor legs; the executor posts the U-bg review thread via `gh api`.
- **R1, R2 and U-bg were dispatched during the P2 drive** (in parallel) from `$MAIN` at
  source-equivalent SHAs.
- **W4, W7a(ii), the codemode `only` session (C1/C2-only) and I6's reload reading were
  executor-driven** in tmux, not owner-typed (pane captures and JSONL in `$SCRATCH/logs`).
- **W6 runs 1–2 were not staged** and are not scored; the probe gained `PROBE_LONG_WORDS` and
  `PROBE_LONG_TASK` (a `sleep 75` first step) for run 3.
- **2026-10-25T02:54:34Z (operator amendment, verbatim intent "ok let's do that. i want the new
  stamp. it's the only option here."):** W7a(i)'s staging additionally requires
  `subagent.run.started` before the abort (header). The probe gained delta (4) (it waits for that
  event and logs it at abort). Run 1 stays FAIL under the original staging; a diagnostic run (a
  `sleep 75` task, 20 s delay; not scored) answered `observed` at stop + 60 s before the amendment.
- **X5b's collection was held one owner turn** so the marker could be read before collection: the
  workflow notice arrived at 03:00:41Z, the owner's marker reading at 03:04:24Z, the collect at
  03:04:39Z.
- **X5a / C3-on's first DENY carried no comment** — the executor's instructions omitted that
  plannotator's deny has no dialogue and a comment goes in the global annotation box. The operator
  ruled (03:25:55Z) that this counts as a pass and is not a gap.
- **E5 ran from `$CLONE`** with its plan-ref pointed at #2774, because the owner's parallel session
  was live in `$MAIN`.
- **I5's live selfcheck** is the codemode `on` session's owner-typed selfcheck and X7a, not an S1
  selfcheck.
- **The 0.82.0 delta peek** (`npm pack` into `$TMP`) answered an operator question mid-run; nothing
  from it was installed where the pair was measured.
- **03:26:18Z (operator):** the owner ended the owner legs; **03:45:49Z (operator):** "go with
  partial" — X1, X2, X3 and C3-only stay NOT RUN (not attempted).

## Methodology appendix

### Scaffold

```sh
# Step 0 ($WT, S1): H0, PATH pi + nested census, receipt hash, doctor --json, node/npm/uv, dev pins,
#   gh secret list (perk + consumer), npm view dist-tags, mirror tag check, the main-checkout staging
#   hashes + backups (plan-ref.json, agent settings.json, trust.json — present at Step 0)
TMP=$(mktemp -d -t perk-cert); AUTHED=$TMP/agent-authed   # holds only a copy of $MAIN/.pi/agent/auth.json
# P2 staging (D9)
git clone -q --no-hardlinks $MAIN $CLONE && git -C $CLONE remote set-url origin https://github.com/mattgiles/perk.git && git -C $CLONE fetch origin
git -C $CLONE checkout --detach H0; printf '[workflow]\nbase = "cert-target"\n' > $CLONE/.perk/local.toml
git -C $CLONE checkout -b cert-target H0   # + the C2 CHANGELOG bullet, committed and pushed (6e455d0e…)
(cd $CLONE && npm ci && cp -R $MAIN/.pi/npm .pi/npm)
uv run perk plan save --plan-file P2.md --json --run-id <fresh>   # from $CLONE → #2773, header base: cert-target
git -C $CLONE push origin H0:refs/heads/plan-2773
# credential controls from $CLONE (mcp.json moved aside): no --model → $WORKER_MODEL; --model openai/gpt-6-luna
# P2 drive (watchdog GRACE 60 CAP 5400) + p2-observe.sh polling every 5 s
env $SCRUB TMPDIR=$TMP/tmp-p2 PI_CODING_AGENT_DIR=$AUTHED GH_TOKEN=… uv run perk run-worker --run-id $RUN_P2 --stage implement --plan 2773
(cd $MAIN && just install-cli)   # receipt re-verified: unchanged
```

### Instruments (SHA-256; scratch, never committed)

The six 1.1.0 instruments were copied from the plan-2756 scratch dir after their SHA-256 matched
the 1.1.0 record's table (`probe-wave.ts` `5cf9b0d6…`, `probe-listener.ts` `39fd649d…`,
`probe-spawn.ts` `4be3a84f…`, `run-bounded.sh` `1114155f…`, `stop-confirm.sh` `c2482f98…`,
`tmux-pi.sh` `146ff6c4…`).

| Instrument | SHA-256 |
|---|---|
| `probe-wave.ts` (final; earlier revisions `70e24fd5…` (repoint, deltas 1–2, `PROBE_LONG_WORDS`: W1, W2, W6 runs 1–2) → `9b52c1bd…` (`PROBE_LONG_TASK`: W6 run 3, W7a(i) run 1 and the diagnostic, W7a(ii)) → final adds delta (4) for the amended W7a(i) re-run) | `dba8bc36633f6d2d1c283d1be1fdffb038978f1cd7ae0bf7b771e283dd13c770` |
| `probe-listener.ts` (unchanged) | `39fd649d8f13e8b8b521e8fb42f239f9ec72aa53af696b25b0c605f4429e306b` |
| `probe-spawn.ts` (+ `trustproject`, `/probe-trust`) | `fa7acaf91189757caf4bd5020b83e36d9bdb1293d7fcbd3b010d791ade6813ff` |
| `probe-foreground.ts` (the 0.76.1-pin record's, import repointed) | `6e010815f43a3a078238cc6f8b8e0cd0e52008f87cea2aa2b527ac0e18963752` |
| `census-eval.sh` (the 0.76.1-pin record's census evaluation, verbatim) | `69eb3d732f4d9e35c9107c79deb218c8311fcf3e5b54203befc8d7ca5fc18a3e` |
| `run-bounded.sh` | `1114155f63fdd2ecb8616dbdf9a890de09b693deb5f6f3cf4aa7bf6fd94b0843` |
| `stop-confirm.sh` | `c2482f98ea503c51fd779e7fcd7bdaa4e54afd6a44b830aff71ca04a6f207a6d` |
| `tmux-pi.sh` | `146ff6c427ef238d22085353437d33a3598812e6406bf7d4da25e82f5ef10e87` |
| `w7aii-drive.sh` (new; the W7a(ii) keystroke + read sequence) | `8ca21a5a30a8225cb44dcbf61836525838db787804fa09598973674e0792ccc4` |
| `p2-drive.sh` / `p2-observe.sh` (1.1.0, unchanged) | `2745d541…` / `e0f39fb9…` |
| `offline.sh` (O1–O8) | `d9132b052b3bd44b9d1a39f15588002d981dcf7360a1a4f6dd075ba777ae4f77` |
| `a1-typed.py` / `w7b-prompt.txt` (1.1.0, unchanged) | `cdc59f73…` / `14180ac0…` |
| `plans/P1.md` | `9411a3e605b16c1ff1cfb6d51ce2e35889d219b0c208d4e8d5ad88b905055510` |
| `plans/P2.md` | `1f878696a3facd380a2b16f0fe65e63b0c6f2292863c6f63c3d6e501c1492e63` |
| `plans/P3.md` | `2091c483605ab293d034459eea80b8b3412887d843877ad3f25e1f88c286ba1b` |
| `plans/P4.md` | `b3e74d478c7775930a06270aa732cef15e437e764fcf17aac517753e38bac4e4` |

### Launch environments

- `$SCRUB` = `env -u PERK_RUN_ID -u PERK_PROFILE_HANDOFF -u PERK_SELFCHECK -u PERK_DISABLE_NATIVE_SDK_BRIDGE -u PERK_CLI_VERSION -u PI_SUBAGENT_CHILD -u PI_SUBAGENT_CHILD_AGENT -u PI_SUBAGENT_EXTENSION_BINDINGS -u PI_SESSION_FILE -u PI_SESSION_ID -u PI_MODEL -u PI_PROVIDER -u PI_REASONING_LEVEL -u PI_CODING_AGENT`.
- **Hermetic** (I4, X7a, A3e raw run; I6 used a fresh hermetic dir under `$SCRATCH`): `PERK_SKIP_VERSION_CHECK=1 PI_CODING_AGENT_DIR=$TMP/agent-hermetic PI_OFFLINE=1 PI_SUBAGENTS_TEMP_ROOT=$TMP/subagents-tmp ANTHROPIC_API_KEY=perk-live-smoke-placeholder-never-sent`.
- **Authed** (W, S4a-live, S5, I8, controls, P2 drive): `$SCRUB PI_CODING_AGENT_DIR=$AUTHED PI_SUBAGENTS_TEMP_ROOT=$SCRATCH/subagents-tmp`, under `run-bounded.sh`.
- **S1, W4 and the codemode sessions:** perk-launched, agent dir `$MAIN/.pi/agent` (config-selected).

### Recorded test invocations

`offline.sh` ran O1–O8 in order; every exit status was 0 (`offline-exits.txt`). O4's named set:
`tests/test_pi_host.py tests/test_host_floor.py tests/test_packaging.py tests/test_write_admission.py
tests/test_env.py tests/test_fsclone.py tests/test_launch_materialize.py tests/test_run_report.py
tests/test_init_idempotent.py tests/test_workflow_artifacts.py tests/test_doctor.py
tests/test_learn_session_jsonl.py tests/test_subagent_agents.py tests/test_repo_local_agents.py`.
O6's set: `nativeSdkBridge`, `piAiCompatGuard`, `entryAdmission`, `hostAdmission`, `hostFloor`,
`ownNamesActivation`, `restorationWindow`, `mcpReadOnlyFloor`, `codemodeLift` (`.test.ts`).

### S5-T5 staging

`$TMP/untrusted`: `git init`; `.pi/settings.json` = `{}`; `.pi/agents/project-marker.md` with
frontmatter `name: project-marker`, `description: certification trust marker`, `tools: read` and
body "Reply with exactly OK."; user-scope `$AUTHED/settings.json` `{"packages":
["npm:pi-subagents@0.81.0"]}` (Pi installed it under `$AUTHED/npm`: "added 7 packages in 1s",
installed 0.81.0); no `$AUTHED/trust.json`, `defaultProjectTrust` unset. Arms (a) `--no-approve`,
(b) `--approve`, each `/probe-trust` then `/probe-spawn script $MODEL trustproject` in fresh
processes; (c) the model-driven explicit-scope prompt under `--no-approve --model $MODEL`.
Afterwards the user-scope entry and `$AUTHED/npm` were removed.

### The probe deltas (verbatim)

<details><summary>1.1.0 <code>probe-wave.ts</code> → this run's <code>probe-wave.ts</code> (repoint; the three step-5 deltas; <code>PROBE_LONG_*</code>; delta (4))</summary>

```diff
--- src-1.1.0/probe-wave.ts
+++ probe-wave.ts
@@ -6,10 +6,10 @@
 import { appendFileSync, existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
 import { dirname, join } from "node:path";
 import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
-import { dispatchForeground } from "$MAIN/.worktrees/plan-2756/extension/pi/v1/foregroundDelegation.ts";
-import { createReportWave } from "$MAIN/.worktrees/plan-2756/extension/waves/reportWave.ts";
-import { runScoutWave } from "$MAIN/.worktrees/plan-2756/extension/waves/scoutWave.ts";
-import { createRpcWaveAdapter } from "$MAIN/.worktrees/plan-2756/extension/waves/rpcAdapter.ts";
+import { dispatchForeground } from "$WT/extension/pi/v1/foregroundDelegation.ts";
+import { createReportWave } from "$WT/extension/waves/reportWave.ts";
+import { runScoutWave } from "$WT/extension/waves/scoutWave.ts";
+import { createRpcWaveAdapter } from "$WT/extension/waves/rpcAdapter.ts";
 
 const log = (label: string, value: unknown) => {
   const line = `probe: ${label} ${JSON.stringify(value, null, 2)}`;
@@ -168,16 +168,35 @@
   let t0 = Date.now();
   pi.on("session_start", () => { t0 = Date.now(); log("session_start", { at: new Date(t0).toISOString(), pid: process.pid }); });
   const rel = () => Date.now() - t0;
+  // 3.1 delta (2): the stop request's id is remembered so its reply is logged with a timestamp
+  // (the rpc-send/reply pair); the scored manual status is scheduled at that reply + 60 s.
+  const stopRequestIds = new Set<string>();
+  let stopReplyAt: number | null = null;
   const loggingBus = {
     emit(channel: string, data: unknown) {
-      if (channel === RPC_REQUEST) log("rpc-send", { method: (data as { method?: string })?.method, tMs: rel() });
+      if (channel === RPC_REQUEST) {
+        const d = data as { method?: string; requestId?: string };
+        if (d?.method === "stop" && typeof d.requestId === "string") stopRequestIds.add(d.requestId);
+        log("rpc-send", { method: d?.method, requestId: d?.requestId, tMs: rel(), at: new Date().toISOString() });
+      }
       pi.events.emit(channel, data);
     },
-    on(channel: string, handler: (data: unknown) => void) { return pi.events.on(channel, handler); },
+    on(channel: string, handler: (data: unknown) => void) {
+      const requestId = channel.startsWith(RPC_REPLY) ? channel.slice(RPC_REPLY.length) : null;
+      if (requestId === null) return pi.events.on(channel, handler);
+      return pi.events.on(channel, (data: unknown) => {
+        if (stopRequestIds.has(requestId)) {
+          const reply = data as { success?: boolean; error?: unknown };
+          if (stopReplyAt === null) stopReplyAt = Date.now();
+          log("rpc-stop-reply", { requestId, tMs: rel(), at: new Date().toISOString(), success: reply?.success, error: reply?.error ?? null });
+        }
+        handler(data);
+      });
+    },
   };
   const QUICK = (n: string) =>
     `Do not read files or run commands. Report exactly one finding: pointer "${n}", claim "OK", basis "verified", rationale "probe lane". scope: "none", open_questions [].`;
-  const LONG = "Read AGENTS.md and summarize it in 600 words.";
+  const LONG = process.env.PROBE_LONG_TASK ?? `Read AGENTS.md and summarize it in ${process.env.PROBE_LONG_WORDS ?? "600"} words.`;
   async function buildScout(briefs: { key: string; task: string }[], model: string, timeoutMs?: number) {
     let captured: Parameters<ReturnType<typeof createReportWave>["run"]>[0] | undefined;
     await runScoutWave({ run: async (r) => { captured = r; return undefined as never; } } as never,
@@ -234,18 +253,42 @@
         log("start", started.ok ? { ok: true, tMs: rel(), runId: started.runId, asyncDir: started.asyncDir, launch: started.launch } : started);
         if (!started.ok) { log("status", started.result); return; }
         if (process.env.PROBE_HANDLE_FILE) writeFileSync(process.env.PROBE_HANDLE_FILE, JSON.stringify({ runId: started.runId, asyncDir: started.asyncDir, at: new Date().toISOString() }));
-        if (mode === "start" || mode === "start-long") return; // interactive legs: the native notice, not collect, is observed
+        // 3.1 delta (1): start-long waits for the runner pid and logs the child before returning.
+        if (mode === "start-long") { log("runner", await waitRunnerPid(started.asyncDir)); return; }
+        if (mode === "start") return; // interactive legs: the native notice, not collect, is observed
+        let runner: unknown = null;
         if (mode === "cancel") {
-          log("runner", await waitRunnerPid(started.asyncDir));
+          runner = await waitRunnerPid(started.asyncDir);
+          log("runner", runner);
+          const childRunId = (runner as { runId?: string })?.runId;
+          const childEvents = childRunId ? join(dirname(started.asyncDir), childRunId, "events.jsonl") : "";
+          // Amended staging (delta 4): the child's runner must have started its Pi child
+          // (`subagent.run.started` in its events.jsonl) before the delay and the abort.
+          const runStarted = (): string | null => {
+            if (!childEvents || !existsSync(childEvents)) return null;
+            for (const line of readFileSync(childEvents, "utf8").split("\n")) {
+              if (!line.trim()) continue;
+              try { const e = JSON.parse(line) as { type?: string; ts?: number }; if (e.type === "subagent.run.started") return new Date(e.ts ?? 0).toISOString(); } catch { /* partial line */ }
+            }
+            return null;
+          };
+          const startedWaitUntil = Date.now() + 120_000;
+          while (runStarted() === null && Date.now() < startedWaitUntil) await new Promise((r) => setTimeout(r, 250));
+          log("child-run-started", { tMs: rel(), at: runStarted() });
           const delay = Number(process.env.PROBE_CANCEL_DELAY_MS ?? "0") || 0;
           if (delay > 0) await new Promise((r) => setTimeout(r, delay));
-          log("abort", { tMs: rel(), delayMs: delay });
+          const childStatus = childRunId ? readJson(join(dirname(started.asyncDir), childRunId, "status.json")) as { state?: string; pid?: number } : null;
+          log("abort", { tMs: rel(), at: new Date().toISOString(), delayMs: delay, childStateAtAbort: childStatus?.state ?? null, childPidAtAbort: childStatus?.pid ?? null, childRunStartedAtAbort: runStarted() });
           controller.abort();
         }
         const result = await drain(wave, started.ref);
         log("status", result);
         if (mode === "cancel") {
-          await new Promise((r) => setTimeout(r, 30_000));
+          // 3.1 delta (2): ONE scored status at the stop reply + 60 s (not 30 s after drain()).
+          const anchor = stopReplyAt ?? Date.now();
+          const wait = Math.max(0, anchor + 60_000 - Date.now());
+          log("manual-status-scheduled", { stopReplyAt: stopReplyAt === null ? null : new Date(stopReplyAt).toISOString(), waitMs: wait });
+          await new Promise((r) => setTimeout(r, wait));
           const st = await rpc(pi, "status", { id: started.runId });
           const details = ((st.data as Record<string, unknown>)?.details ?? {}) as Record<string, unknown>;
           log("manual-status", { tMs: rel(), success: st.success, error: st.error, workflowTerminalProof: details.workflowTerminalProof ?? null });
```

</details>

<details><summary>1.1.0 <code>probe-spawn.ts</code> → this run's (<code>trustproject</code> mode, <code>/probe-trust</code>)</summary>

```diff
--- src-1.1.0/probe-spawn.ts
+++ probe-spawn.ts
@@ -2,7 +2,8 @@
 // extension/waves/rpcAdapter.ts does (same envelope; the run handle lives in data.details), with
 // the spawn key, a pinned lane model and a lane mode, and waits for the run to settle so the
 // in-process workflow host is not killed by print-mode exit.
-//   /probe-spawn <script|workflowScript> <provider/model> [restricted|badmodel|missingbase|mixed|cancel|deadline]
+//   /probe-spawn <script|workflowScript> <provider/model> [restricted|badmodel|missingbase|mixed|cancel|deadline|trustproject]
+//   /probe-trust   (logs ctx.isProjectTrusted() — S5-T5 staging)
 // Auto-fire (SDK worker rows): PERK_PROBE_AUTO="<key> <model> [mode]" runs the same ping → spawn →
 // settle from session_start and writes PERK_PROBE_DONE (a JSON file) when it finishes.
 import { randomUUID } from "node:crypto";
@@ -97,7 +98,9 @@
               { ...item, key: "probe-quick", label: "probe-quick", model },
               { ...item, key: "probe-long", label: "probe-long", model, task: LONG },
             ]
-          : [item];
+          : mode === "trustproject"
+            ? [{ key: "probe-project", agent: "project-marker", label: "probe-project", task: "Reply with exactly OK.", model, worktree: false }]
+            : [item];
   const script =
     `const reports = await runs.all(${JSON.stringify(items, null, 2)});\n` +
     "return reports.map(({key, ok, error, structuredOutput}) => ({key, ok, error: error ?? null, report: structuredOutput ?? null}));";
@@ -136,10 +139,16 @@
     description: "characterization probe: ping + spawn one scout lane via the v1 RPC",
     handler: async (args) => {
       const [key = "script", model = "", mode = ""] = args.trim().split(/\s+/);
-      if (!model) { log("probe-error", "usage: /probe-spawn <script|workflowScript> <provider/model> [restricted|badmodel|missingbase|mixed|cancel|deadline]"); process.exitCode = 2; return; }
+      if (!model) { log("probe-error", "usage: /probe-spawn <script|workflowScript> <provider/model> [restricted|badmodel|missingbase|mixed|cancel|deadline|trustproject]"); process.exitCode = 2; return; }
       await probe(pi, key, model, mode);
     },
   });
+  pi.registerCommand("probe-trust", {
+    description: "S5-T5 staging: log ctx.isProjectTrusted() for this session",
+    handler: async (_args, ctx) => {
+      log("status", { cwd: process.cwd(), isProjectTrusted: ctx.isProjectTrusted() });
+    },
+  });
   const auto = process.env.PERK_PROBE_AUTO;
   if (auto) {
     let fired = false;
```

</details>

<details><summary>the 0.76.1-pin record's <code>probe-foreground.ts</code> → this run's (import repointed)</summary>

```diff
--- probe-foreground.record.ts
+++ probe-foreground.ts
@@ -2,7 +2,7 @@
 // own foreground-delegation transport, exactly as run_librarian / the conflict resolver do.
 //   /probe-foreground <provider/model>
 import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
-import { dispatchForeground } from "$WT/extension/pi/v1/foregroundDelegation.ts";
+import { dispatchForeground } from "$WT/extension/pi/v1/foregroundDelegation.ts";
 
 const log = (label: string, value: unknown) =>
   console.error(`probe: ${label} ${JSON.stringify(value, null, 2)}`);
```

</details>

### The census delta (D8; applied identically to P1, P2 and P3)

```diff
--- src-1.1.0/P2.md
+++ plans/P2.md
@@ -8,14 +8,18 @@
   echo "## git"; git rev-parse HEAD; git merge-base HEAD origin/main 2>/dev/null || echo "(no origin/main)"
   echo "## global @earendil-works"; G="$(npm root -g)/@earendil-works"
   for p in "$G"/*/; do n=$(basename "$p"); echo "$n $(node -p "require('$p/package.json').version")"; done
-  echo "## nested under pi-coding-agent"; ls "$G/pi-coding-agent/node_modules/@earendil-works" 2>/dev/null || echo "(none)"
+  echo "## nested under pi-coding-agent"
+  N="$G/pi-coding-agent/node_modules/@earendil-works"
+  if [ -d "$N" ]; then for p in "$N"/*/; do echo "$(basename "$p") $(node -p "require('$p/package.json').version")"; done; else echo "(none)"; fi
   echo "## worker SDK node_modules/@earendil-works"
   for p in node_modules/@earendil-works/*/; do [ -d "$p" ] && echo "$(basename "$p") $(node -p "require('./$p/package.json').version")"; done
-  ls node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works 2>/dev/null || echo "(none nested)"
+  N="$PWD/node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works"
+  if [ -d "$N" ]; then for p in "$N"/*/; do echo "$(basename "$p") $(node -p "require('$p/package.json').version")"; done; else echo "(none nested)"; fi
   echo "## .pi/npm/package.json"; cat .pi/npm/package.json 2>/dev/null || echo "(absent)"
   echo "## .pi/npm/node_modules/@earendil-works"
   for p in .pi/npm/node_modules/@earendil-works/*/; do [ -d "$p" ] && echo "$(basename "$p") $(node -p "require('./$p/package.json').version")"; done
-  ls .pi/npm/node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works 2>/dev/null || echo "(none nested)"
+  N="$PWD/.pi/npm/node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works"
+  if [ -d "$N" ]; then for p in "$N"/*/; do echo "$(basename "$p") $(node -p "require('$p/package.json').version")"; done; else echo "(none nested)"; fi
   echo "## pi-subagents"; node -p "require('./.pi/npm/node_modules/pi-subagents/package.json').version" 2>/dev/null || echo "(absent)"
   echo "## @mgiles/perk"; node -p "require('./.pi/npm/node_modules/@mgiles/perk/package.json').version" 2>/dev/null || echo "(absent)"
 } > CERTIFICATION-CENSUS.md
```

### The sacrificial plan bodies (verbatim, as amended)

<details><summary>P1 — <code>plans/P1.md</code></summary>

````markdown
# Certification probe (throwaway): self-repo remote census

Create `CERTIFICATION-CENSUS.md` at the repository root by running exactly this shell block once with redirection (never type the output yourself); commit only that file (plus the CHANGELOG edit where this plan asks for one); do not run the CI gate; then submit.

```sh
{
  echo "## host"; date -u +%FT%TZ; node --version; npm --version; command -v pi; pi --version
  echo "## git"; git rev-parse HEAD; git merge-base HEAD origin/main 2>/dev/null || echo "(no origin/main)"
  echo "## global @earendil-works"; G="$(npm root -g)/@earendil-works"
  for p in "$G"/*/; do n=$(basename "$p"); echo "$n $(node -p "require('$p/package.json').version")"; done
  echo "## nested under pi-coding-agent"
  N="$G/pi-coding-agent/node_modules/@earendil-works"
  if [ -d "$N" ]; then for p in "$N"/*/; do echo "$(basename "$p") $(node -p "require('$p/package.json').version")"; done; else echo "(none)"; fi
  echo "## worker SDK node_modules/@earendil-works"
  for p in node_modules/@earendil-works/*/; do [ -d "$p" ] && echo "$(basename "$p") $(node -p "require('./$p/package.json').version")"; done
  N="$PWD/node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works"
  if [ -d "$N" ]; then for p in "$N"/*/; do echo "$(basename "$p") $(node -p "require('$p/package.json').version")"; done; else echo "(none nested)"; fi
  echo "## .pi/npm/package.json"; cat .pi/npm/package.json 2>/dev/null || echo "(absent)"
  echo "## .pi/npm/node_modules/@earendil-works"
  for p in .pi/npm/node_modules/@earendil-works/*/; do [ -d "$p" ] && echo "$(basename "$p") $(node -p "require('./$p/package.json').version")"; done
  N="$PWD/.pi/npm/node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works"
  if [ -d "$N" ]; then for p in "$N"/*/; do echo "$(basename "$p") $(node -p "require('$p/package.json').version")"; done; else echo "(none nested)"; fi
  echo "## pi-subagents"; node -p "require('./.pi/npm/node_modules/pi-subagents/package.json').version" 2>/dev/null || echo "(absent)"
  echo "## @mgiles/perk"; node -p "require('./.pi/npm/node_modules/@mgiles/perk/package.json').version" 2>/dev/null || echo "(absent)"
} > CERTIFICATION-CENSUS.md
```
````

</details>

<details><summary>P2 — <code>plans/P2.md</code></summary>

````markdown
# Certification probe (throwaway): worker MCP + install census

Create `CERTIFICATION-CENSUS.md` at the repository root by running exactly this shell block once with redirection (never type the output yourself); commit only that file (plus the CHANGELOG edit where this plan asks for one); do not run the CI gate; then submit.

```sh
{
  echo "## host"; date -u +%FT%TZ; node --version; npm --version; command -v pi; pi --version
  echo "## git"; git rev-parse HEAD; git merge-base HEAD origin/main 2>/dev/null || echo "(no origin/main)"
  echo "## global @earendil-works"; G="$(npm root -g)/@earendil-works"
  for p in "$G"/*/; do n=$(basename "$p"); echo "$n $(node -p "require('$p/package.json').version")"; done
  echo "## nested under pi-coding-agent"
  N="$G/pi-coding-agent/node_modules/@earendil-works"
  if [ -d "$N" ]; then for p in "$N"/*/; do echo "$(basename "$p") $(node -p "require('$p/package.json').version")"; done; else echo "(none)"; fi
  echo "## worker SDK node_modules/@earendil-works"
  for p in node_modules/@earendil-works/*/; do [ -d "$p" ] && echo "$(basename "$p") $(node -p "require('./$p/package.json').version")"; done
  N="$PWD/node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works"
  if [ -d "$N" ]; then for p in "$N"/*/; do echo "$(basename "$p") $(node -p "require('$p/package.json').version")"; done; else echo "(none nested)"; fi
  echo "## .pi/npm/package.json"; cat .pi/npm/package.json 2>/dev/null || echo "(absent)"
  echo "## .pi/npm/node_modules/@earendil-works"
  for p in .pi/npm/node_modules/@earendil-works/*/; do [ -d "$p" ] && echo "$(basename "$p") $(node -p "require('./$p/package.json').version")"; done
  N="$PWD/.pi/npm/node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works"
  if [ -d "$N" ]; then for p in "$N"/*/; do echo "$(basename "$p") $(node -p "require('$p/package.json').version")"; done; else echo "(none nested)"; fi
  echo "## pi-subagents"; node -p "require('./.pi/npm/node_modules/pi-subagents/package.json').version" 2>/dev/null || echo "(absent)"
  echo "## @mgiles/perk"; node -p "require('./.pi/npm/node_modules/@mgiles/perk/package.json').version" 2>/dev/null || echo "(absent)"
} > CERTIFICATION-CENSUS.md
```

Then call the MCP tool `mcp__fixture__echo` once with `{"text": "perk-certification"}` and append its result with `printf '## mcp\n%s\n' '<the result text>' >> CERTIFICATION-CENSUS.md`. Then add, as the **first bullet** of the `### Fixed` section under `## [Unreleased]` in `CHANGELOG.md` (if `## [Unreleased]` has no `### Fixed` section, create one directly after the `<!-- As of … -->` line), the single bullet `- Certification probe (throwaway; never merged): worker install census. (0000000)`. Do not edit any other line of `CHANGELOG.md`. If the submit reports merge conflicts, follow its guidance to resolve them.
````

</details>

<details><summary>P3 — <code>plans/P3.md</code></summary>

````markdown
# Certification probe (throwaway): consumer composite census

Create `CERTIFICATION-CENSUS.md` at the repository root by running exactly this shell block once with redirection (never type the output yourself); commit only that file (plus the CHANGELOG edit where this plan asks for one); do not run the CI gate; then submit.

```sh
{
  echo "## host"; date -u +%FT%TZ; node --version; npm --version; command -v pi; pi --version
  echo "## git"; git rev-parse HEAD; git merge-base HEAD origin/main 2>/dev/null || echo "(no origin/main)"
  echo "## global @earendil-works"; G="$(npm root -g)/@earendil-works"
  for p in "$G"/*/; do n=$(basename "$p"); echo "$n $(node -p "require('$p/package.json').version")"; done
  echo "## nested under pi-coding-agent"
  N="$G/pi-coding-agent/node_modules/@earendil-works"
  if [ -d "$N" ]; then for p in "$N"/*/; do echo "$(basename "$p") $(node -p "require('$p/package.json').version")"; done; else echo "(none)"; fi
  echo "## worker SDK node_modules/@earendil-works"
  for p in node_modules/@earendil-works/*/; do [ -d "$p" ] && echo "$(basename "$p") $(node -p "require('./$p/package.json').version")"; done
  N="$PWD/node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works"
  if [ -d "$N" ]; then for p in "$N"/*/; do echo "$(basename "$p") $(node -p "require('$p/package.json').version")"; done; else echo "(none nested)"; fi
  echo "## .pi/npm/package.json"; cat .pi/npm/package.json 2>/dev/null || echo "(absent)"
  echo "## .pi/npm/node_modules/@earendil-works"
  for p in .pi/npm/node_modules/@earendil-works/*/; do [ -d "$p" ] && echo "$(basename "$p") $(node -p "require('./$p/package.json').version")"; done
  N="$PWD/.pi/npm/node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works"
  if [ -d "$N" ]; then for p in "$N"/*/; do echo "$(basename "$p") $(node -p "require('$p/package.json').version")"; done; else echo "(none nested)"; fi
  echo "## pi-subagents"; node -p "require('./.pi/npm/node_modules/pi-subagents/package.json').version" 2>/dev/null || echo "(absent)"
  echo "## @mgiles/perk"; node -p "require('./.pi/npm/node_modules/@mgiles/perk/package.json').version" 2>/dev/null || echo "(absent)"
} > CERTIFICATION-CENSUS.md
```
````

</details>

<details><summary>P4 — <code>plans/P4.md</code> (never saved)</summary>

````markdown
# Certification throwaway (never saved): add one glossary line to CONTEXT.md

A throwaway draft body for the certification's browser-door and lifecycle sessions. It is drafted
with `plan_draft`, reviewed in the browser and DENIED; it is never saved, never implemented.

## Summary

Add a single glossary line for **Certification record** to `CONTEXT.md`, pointing at
`docs/design/archive/`.

## Steps

1. Add the one line under the glossary's alphabetical position.
2. No other file changes.

## Acceptance

- `CONTEXT.md` gains exactly one line; nothing else moves.
````

</details>

### D9 staging

- `$CLONE/.perk/local.toml` was exactly `[workflow]` / `base = "cert-target"`.
- C2 (`6e455d0e9a424cf3bf6bfa25ee8cdd48a2b1e5b5`) inserted
  `- Certification target (throwaway; never merged): the staged divergence for the resolver leg. (0000000)`
  as the first bullet of `## [Unreleased]`'s `### Fixed`.
- `plan-2773` was pre-pushed at H0. The worker's own bullet at the same point produced the
  `CHANGELOG.md` conflict on the first submit.

## Teardown proof

The following were removed or closed before the block below was captured:

- **Closed:** PRs #2775 and #2776 (unmerged), consumer PR #5 (unmerged); issues #2773, #2774 and
  `perk-consumer-dogfood#4`. No throwaway issue was created by the W4 or codemode sessions.
- **Deleted:** remote branches `cert-target`, `plan-2773`, `plan-2774` and the consumer's `plan-4`.
- **Removed:** `$TMP` (after the receipt check), `$SCRATCH/subagents-tmp`, the census dirs,
  plannotator's PR pool worktree for #2771.
- **Removed from `$WT`:** the `doctor --fix` residue (`.perk/local.toml`, `.agents/cache`,
  `.agents/local.yaml`) and the E1 bundle.
- **Restored:** `$MAIN/.pi/agent/settings.json` and `$MAIN/.perk/workflow/plan-ref.json`, from their
  backups. The consumer fixture stays converged at `5843724f`.

```text
# teardown 2026-10-25T03:40:01Z
$ git -C $MAIN status --porcelain
(exit 0; 0 lines)
$ git -C $MAIN rev-parse HEAD
6012a53f7e241d96377a27386c38fde09ca927c7
$ shasum -a 256 <MAIN staging + agent settings/trust + WT settings>
8db12e19e5071f57c741c0bf0f653179b57a4f695f3ff7abbc518563eff546b3  $MAIN/.pi/npm/package.json
d6b79498a12d9ef199dc11eff3264ffadbcac7138237469fa4ce4c3b65b0028b  $MAIN/.pi/npm/package-lock.json
fcf348c3fe9682da593e2b8a0fbf3998ff598d290f484ed500897534feebb610  $MAIN/.pi/npm/node_modules/.package-lock.json
4b8ecf969b00a0a5d5717ce76e24a6ec2a1b0e16b8ca57c97c2976d5681ee574  $MAIN/.pi/npm/node_modules/pi-subagents/package.json
2aae99afb27cd7a7a1abfb6d32897a3d28c4242db2c567400abd03c42054bf39  $MAIN/.pi/agent/settings.json
7a702522a062fe9c8ec6cde36726d2bb91e9d32a5cbd2f8d480d2b21ebce37fa  $MAIN/.pi/agent/trust.json
f00ec02e391a571f27ee8dfc72d57757f65f8faa1723f745c7c523a67d82ef1d  $WT/.pi/settings.json
$ diff <(Step 0 hashes) <(now)
byte-equal (7/7)
$ shasum -a 256 $MAIN/.perk/workflow/plan-ref.json
59fd540b3ac81f64a41944439155341d0978c2bbc9c626263828d2076c3cdad9
$ grep editable ~/.local/share/uv/tools/perk/uv-receipt.toml; shasum
requirements = [{ name = "perk", editable = "$MAIN" }]
871c7f977d15fceacaa99187f4aa8794969329a89efcb0f1ee27482ba3777b92
$ ls $(npm root -g)/@earendil-works; nested versions
pi-coding-agent 
pi-agent-core 1.4.0 pi-ai 1.4.0 pi-codemode 1.4.0 pi-mcp 1.4.0 pi-telemetry 1.4.0 pi-tui 1.4.0 
$ pgrep -fl perk-cert
(exit 1)
$ tmux ls
no server running on /private/tmp/tmux-502/default
$ ls -d $TMP
ls: $TMP: No such file or directory
$ git worktree list | grep -c plannotator-pr-mattgiles-perk-2771
0
$ git -C $WT status --porcelain
(exit 0)
$ perk --version
perk 4.1.0
$ pi --version
1.4.0
$ PR/issue states + remote branches
PR #2775 CLOSED
PR #2776 CLOSED
consumer PR #5 CLOSED
#2773 CLOSED
#2774 CLOSED
consumer #4 CLOSED
ls-remote cert-target plan-2773 plan-2774 plan-4: 0 + 0 refs
```

The `$WT` porcelain above predates this record's own commits; the PR carries only this record,
the stamp literals, the prose surfaces and the CHANGELOG bullet.

## `/learn` candidates

- **Stale learned docs:** `docs/learned/pi/subagents.md` § Sources / § History (0.75.0 / 0.76.1),
  `docs/learned/workflow/report-waves.md`, `docs/learned/workflow/borrowed-packages.md`,
  `docs/learned/toolchain/worktree-node-modules.md` § "Pi pin-bump mechanics" (the single-spec
  nested layout; the stamp now 0.81.0).
- **For `docs/learned/pi/subagents.md`:** the never-started-writer stop leaves the proof
  permanently `unknown` (W7a(i)); 0.82.0's default workflow auto-resume vs perk's per-activation
  collection; `/reload` still stops in-process workflows (W7a(ii)); the untrusted-discovery
  refusal arrives at spawn preflight (S5-T5); `~/.agents` user agents leak into scratch agent dirs.
- **For `docs/learned/pi/tool-loadout.md`:** a nested action tool (`push_annotations`) from a
  codemode script is refused under the read-only gate; `only` hides the direct read tools from the
  declared set.
- **For the browser doors:** plannotator's deny has no dialogue (comments ride the global box); a
  stale "Perk detached this review" note can surface in a later review's feedback; plannotator's
  PR pool worktree outlives `perk pr review cleanup`; ask for the marker before collecting, even
  after the workflow notice.
- **For the certification procedure:** a sleep-first lane task is the reliable way to stage a
  deadline partial; the remote `.pi/npm` resolves non-pinned siblings newer than local.
- **Isolation gaps** (unchanged from 1.1.0): the drive-scoped `TMPDIR` reaches worker children;
  pi-fff and pi-subagents write into the real agent dir.
- **Doctor text:** the `subagent-package-scope` warn detail still names "pi 0.85.1".
