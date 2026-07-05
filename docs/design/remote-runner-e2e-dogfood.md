# Dogfood: the remote runner end-to-end (Objective #1093, Node 2.2)

**Status:** validation record (the `provider-smoke-*` genre) for the live remote execution chain —
a real remote `implement` run and a real remote `address` run driven through perk's own dispatch
doors (`perk implement <N> --remote`, `perk plan resume <N> --remote`), with the evidence captured
inline. Part A is the repeatable procedure; Part B is the captured evidence + defect log from the
first execution.

The chain under proof: dispatch (`GitHubActionsRunner.dispatch`, contracts §8.13) → the managed
`perk-run.yml` (§8.14) → checkout → composite setup → `perk run-worker` positioning → the Node
headless worker (`extension/workerMain.ts` → `driveStage`) → extension tools registered → the
stage's terminating door (`submit` / thread resolution) → terminal reporting (§8.15: the
marker-keyed plan-issue comment + the job summary).

Scope notes (what this record does *not* prove): the **consumer-repo** remote drive (the
`consumer-npm` worker entry + pinned `@mgiles/perk` install path) remains execution-untested; there
is no recurring CI-gated live E2E — the proof is this documented procedure + its evidence. Landing
the sacrificial PR is out of scope: verification ends at "successful submit → terminal reporting",
and the sacrificial PR is closed unmerged so the procedure stays repeatable.

## Part A — the repeatable procedure

Each step names its actor: **(human)** for actions a session cannot take, **(session)** for
everything automatable. All perk dispatches run **from the main checkout, never from a plan
worktree** — `perk implement <N> --remote` rewrites the active `cache.plan-ref` of the checkout it
runs in, and in a `plan-<N>` worktree that file is the worktree's own durable binding.

1. **Preconditions (human).** Configure the runner prerequisites (once, if absent):
   - Repo secret `PERK_GH_PAT` — a repo-scoped PAT (contents + pull-requests + issues write; the
     runner checks out/pushes with it so downstream CI triggers).
   - Repo secret `ANTHROPIC_API_KEY` (or `OPENAI_API_KEY`) — the model key the remote worker
     resolves headlessly.
   - Repo variable `PERK_ENABLED` unset or not `'false'`.

   Verify with `perk doctor workflow check --verbose` — the `runner-enabled` / `runner-pat` /
   `runner-model` checks must be green (`runner-permissions` stays advisory `info` under the
   PAT-push model, §8.16).
2. **Wiring proof (session).** `perk doctor workflow smoke-test --wait` — the zero-spend smoke
   short-circuit (§8.19): dispatch + secrets validation + verify-by-discovery, no checkout, no
   drive, no model spend. Record the run URL.
3. **Sacrificial plan.** Author + save a minimal bounded plan for a trivial, low-risk throwaway
   change. Either the human runs `perk plan from <seed>` / `/plan` and approves, or — fully
   scripted — the session saves prepared plan markdown through the deterministic cold save door:
   `perk plan save --json --plan-file <file>` (what the first execution did). Note its issue
   number `<N>`.
4. **Seed the plan branch.** *(obsolete since PR #1129 — the fetch-or-create fallback is live on
   main and verified live in the Part B addendum; skip this step.)*
5. **Remote implement (session, main checkout).** `perk implement <N> --remote`. Record the
   dispatch JSON (`run_id`, `run_handle`). Poll with `gh run watch <run-ref>` and/or
   `perk workflow run list` — the discovery row is itself evidence of §8.13's canonical
   run-name discovery.
6. **Verify + capture (session).** Map each verification point to a concrete artifact (the Part B
   checklist below): checkout log, composite setup log, `run-worker` positioning + worker-entry
   stderr lines, tools registered (no `no_extension_tools`), the submitted PR (head `plan-<N>`),
   the `RunOutcome` JSON, the run-report comment + job summary, the discovery row, model +
   budget counters.
7. **Actionable feedback (session).** Self-post one review comment thread on a changed line of the
   sacrificial PR (via `gh api repos/{owner}/{repo}/pulls/<pr>/comments` with a diff anchor —
   GitHub forbids request-changes on your own PR, but `needs_address` also triggers on **any
   unresolved review thread**, which the PR author *can* create). The comment carries a small
   concrete request (e.g. "reword this sentence to …"). Verify it reads back as an unresolved
   thread: `gh pr view <pr> --json reviewThreads`.
8. **Mark the PR ready (session).** `gh pr ready <pr>` — the worker's `submit` opens a **draft**
   PR on purpose, and the resume classifier routes drafts to `ready_for_review` *without fetching
   feedback* (`needs_address` applies only to open non-draft PRs). Marking ready mirrors the real
   review flow and unlocks the address classification.
9. **Remote address (session, main checkout).** `perk plan resume <N> --remote --json` — capture
   the payload showing the classifier selected + dispatched `stage: "address"`, then the same
   poll/verify/capture loop as steps 5–6.
10. **Cleanup (session).** Close the sacrificial PR unmerged, delete `plan-<N>`, close the plan
    issue. This keeps the procedure repeatable without polluting main or the learn pipeline.
11. **Failure loop.** Any failed run is **evidence, not a restart**: capture
    `gh run view <run-ref> --log` excerpts + the `perk-run-<run_id>` artifact, log the defect in
    Part B's defect log (B-series numbering, continuing §8.14's B1–B6), fix it in the
    accompanying PR when the defect is in perk (or
    document it when environmental), and re-dispatch.

    One useful bootstrap discovered live: **worker-code fixes can ride the plan branch.** The
    runner installs perk/pi from the initial checkout but resolves the worker entry (`self`) from
    the *plan-branch* working tree — so an extension-plane fix cherry-picked onto `plan-<N>` takes
    effect on the very next dispatch, even before it merges to main (workflow-*template* fixes, by
    contrast, only go live after merge — dispatch always runs main's `perk-run.yml`).

## Part B — the captured evidence

Executed **2026-07-04** on `mattgiles/perk` (the self-repo; worker entry `self`). The sacrificial
plan was issue **#1127** ("Add a hello note describing the perk remote runner", saved via
`perk plan save --json --plan-file …`), its branch `plan-1127` seeded from `origin/main` (Part A
step 4 — the pre-merge workaround), its PR **#1128** closed unmerged, branch deleted, issue closed
(Part A step 10). Preconditions were green first:
`perk doctor workflow check --verbose` → `runner-enabled` (default-on), `runner-pat-secret`
(PERK_GH_PAT configured), `runner-model-secret` (ANTHROPIC_API_KEY), `runner-workflow-permissions`
(advisory info under the PAT-push model).

### The smoke run (wiring proof)

- Dispatch: `perk doctor workflow smoke-test --wait` → run_id `01KWPNS09ZNT87AW5P4QF7KR4Q`,
  run <https://github.com/mattgiles/perk/actions/runs/28708038228>.
- Result: `✓ smoke run succeeded` — secrets validated, runner reachable, zero model spend (every
  drive step short-circuited by the `smoke` guard, §8.19).

### The remote `implement` run

First dispatch **failed** (evidence — defect B7 below); the second completed end-to-end.

**Failed attempt:** `perk implement 1127 --remote` → run_id `01KWPNT8R2KC4SZYZK2EDEXHK5`, run
<https://github.com/mattgiles/perk/actions/runs/28708056777>. The whole chain up to the model turn
worked (checkout → setup → positioning → worker → started report); the drive died turn 1:
`RunOutcome` `{"status":"failed","terminal_signal":"model_error",… "message":"404 … model:
claude-3-5-haiku-20241022"}`. The terminal run-report comment on #1127 carries the same failure
summary — the failure loop worked exactly as designed.

**Successful run:** `perk implement 1127 --remote` (after the B7 fix rode `plan-1127`) → run_id
`01KWPPEDSR23S5VKH9GZR6NYZQ`, run <https://github.com/mattgiles/perk/actions/runs/28708339926>,
job green in 3m42s. Verification points → artifacts:

- **Checkout log** — `Check out the plan branch` fetched `plan-1127` and hard-reset to the remote
  tip (branch-exists arm; the fetch-or-create fallback was not yet on main).
- **Composite setup log** — uv + Python 3.13, Node 22, `uv tool install --from . perk`, pi via
  `npm install -g @earendil-works/pi-coding-agent`, `npm ci` (self worker-deps).
- **Positioning + worker entry** — `run-worker: positioning implement for plan #1127
  (run_id=01KWPPEDSR23S5VKH9GZR6NYZQ, base=main)`;
  `run-worker: worker entry=/home/runner/work/perk/perk/extension/workerMain.ts (self)`.
- **Model** — `perk worker: model anthropic/claude-opus-4-8` (the SDK-resolved default, B7 fix).
- **Tools registered** — no `no_extension_tools`; the drive called perk's real tools and ended on
  the terminating `submit` tool.
- **The submitted PR** — <https://github.com/mattgiles/perk/pull/1128>, head `plan-1127`, base
  `main`, containing the model-authored `docs/notes/remote-dogfood-hello.md`.
- **`RunOutcome` JSON** (stdout, in the step log) — `{"run_id":"01KWPPEDSR23S5VKH9GZR6NYZQ",
  "stage":"implement","status":"completed","terminal_signal":"submit_tool","pr":{"number":1128,…},
  "budget":{"turns":6,"tokens":941,"elapsed_ms":183600},"error":null}`; `run-worker: worker
  exited 0`.
- **Terminal reporting** — the marker-keyed comment on issue #1127
  (`<!-- perk:run-report:01KWPPEDSR23S5VKH9GZR6NYZQ -->`: Status completed, `submit_tool`, budget,
  `Opened PR #1128`, run link) + the `## perk remote implement` job summary on the run page.
- **Discovery row** — `perk workflow run list`:
  `01KWPPEDSR23S5VKH9GZR6NYZQ  implement  dispatched  completed  success  #1127  #1128(OPEN)`
  (§8.13 canonical run-name discovery).

### The remote `address` run

- **Actionable feedback** — a self-posted review thread on a changed line of
  `docs/notes/remote-dogfood-hello.md`
  (<https://github.com/mattgiles/perk/pull/1128#discussion_r3523301859>, "reword …"); read back
  `isResolved: false`.
- **Draft gate (procedure correction)** — `perk plan resume 1127 --remote --json` on the draft PR
  returned `next_action: ready_for_review` (drafts never fetch feedback); after `gh pr ready 1128`
  the resume classified + dispatched `stage: "address"` → run_id `01KWPPR28AFW94P5J1VSW725AW`, run
  <https://github.com/mattgiles/perk/actions/runs/28708472176>, green in 2m49s.
- **Classification evidence** — the dispatch JSON (`{"success": true, "stage": "address",
  "run_id": "01KWPPR28AFW94P5J1VSW725AW", …}`) is the classifier's output feeding the dispatch.
- **The fix commit** — `63b5dc0` "Reword 'plus' to 'and' in remote runner hello note" pushed to
  `plan-1127` by the drive.
- **Threads resolved** — the thread carries the worker's reply ("Reworded to …") and reads back
  `isResolved: true`.
- **`RunOutcome`** — `{"stage":"address","status":"completed","terminal_signal":
  "address_resolved","pr":null,"budget":{"turns":14,"tokens":4140,"elapsed_ms":129048},
  "error":null}`; exit 0; model `anthropic/claude-opus-4-8`.
- **Terminal reporting** — the marker-keyed run-report comment on #1127
  (`<!-- perk:run-report:01KWPPR28AFW94P5J1VSW725AW -->`, Status completed) + the job summary;
  discovery row `… address … completed success #1127`.

### Addendum — the create arm + diagnostics artifact, verified live (2026-07-05)

The two workflow fixes that landed unit-pinned-but-execution-untested in PR #1129 — the
fetch-or-create plan-branch checkout fallback (its **create arm**) and the
`Upload run diagnostics` artifact step — verified live with one fresh-plan remote `implement`
dispatched **without seeding the plan branch** (the whole point: Part A step 4's workaround is
obsolete). Preconditions re-verified green first (`perk doctor workflow check --verbose` →
`runner-enabled` default-on, `runner-pat-secret`, `runner-model-secret` (ANTHROPIC_API_KEY),
`runner-workflow-permissions` advisory info). No smoke run — a smoke writes nothing and uploads
nothing, so it verifies neither fix.

- **Sacrificial plan** — issue **#1144** ("Add a second hello note describing the perk remote
  runner", saved via `perk plan save --json --plan-file …` from the main checkout); its PR
  **#1145**. Fresh-branch proof before dispatch: `git ls-remote origin plan-1144` returned
  nothing, and nothing seeded it.
- **Dispatch** — `perk implement 1144 --remote` (main checkout) →
  `{"success": true, "stage": "implement", "run_id": "01KWT5BPGRBYKKTAN9QY17FDS9",
  "runner": "", "run_handle": {"runner": "", "kind": "github-actions",
  "run_ref": "28756599501", "url":
  "https://api.github.com/repos/mattgiles/perk/actions/runs/28756599501"}}`; run
  <https://github.com/mattgiles/perk/actions/runs/28756599501>, job green in 3m48s.
- **The create arm, live** — the `Check out the plan branch` step log:

  ```text
  fatal: couldn't find remote ref plan-1144
  ##[notice]plan branch plan-1144 not found; creating it from origin/main
  From https://github.com/mattgiles/perk
   * branch            main       -> FETCH_HEAD
  Switched to a new branch 'plan-1144'
  branch 'plan-1144' set up to track 'origin/main'.
  ```
- **The diagnostics artifact, live** — the `Upload run diagnostics` step ran (`name:
  perk-run-01KWT5BPGRBYKKTAN9QY17FDS9`, `path:
  .perk/workflow/scratch/runs/01KWT5BPGRBYKKTAN9QY17FDS9/`): "With the provided path, there will
  be 2 files uploaded … Final size is 980 bytes. Artifact ID is 8096290349". Downloaded with
  `gh run download 28756599501 --name perk-run-01KWT5BPGRBYKKTAN9QY17FDS9` — contents at the
  artifact root (v4 strips the `path` prefix): `events.ndjson`, `session-pointers.json`.
- **`events.ndjson` well-formed (§8.12)** — 15 lines, one JSON object per line; first line the
  `run_started` event, last line the terminal `run_finished` carrying the frozen `RunOutcome`
  that matches the step-log JSON byte-for-byte:

  ```text
  {"kind":"run_started","run_id":"01KWT5BPGRBYKKTAN9QY17FDS9","stage":"implement","seq":0,"t":25169}
  …
  {"kind":"run_finished","outcome":{"run_id":"01KWT5BPGRBYKKTAN9QY17FDS9","stage":"implement","status":"completed","terminal_signal":"submit_tool","pr":{"number":1145,"url":"https://github.com/mattgiles/perk/pull/1145"},"budget":{"turns":10,"tokens":1725,"elapsed_ms":185540},"error":null},"seq":14,"t":185540}
  ```
- **`RunOutcome`** — `{"run_id":"01KWT5BPGRBYKKTAN9QY17FDS9","stage":"implement","status":
  "completed","terminal_signal":"submit_tool","pr":{"number":1145,…},"budget":{"turns":10,
  "tokens":1725,"elapsed_ms":185540},"error":null}`; model `anthropic/claude-opus-4-8`;
  `run-worker: worker exited 0`; run-report comment posted on #1144.
- **Discovery row** — `perk workflow run list`:
  `01KWT5BPGRBYKKTAN9QY17FDS9  implement  dispatched  completed  success  #1144  #1145(OPEN)`.
- **env-1 reproduced (node 1.2 diagnostics, not fixed here)** — the drive-step log:

  ```text
  perk worker: extension load error — /home/runner/work/perk/perk/.pi/npm/node_modules/pi-web-access/index.ts: Failed to load extension: Cannot find module '/home/runner/work/perk/perk/node_modules/@earendil-works/pi-coding-agent/node_modules/@earendil-works/pi-ai/dist/index.js/compat'
  ```

  Non-fatal as before (perk's own tools registered; the drive completed on `submit`). This run's
  step logs + the `perk-run-01KWT5BPGRBYKKTAN9QY17FDS9` artifact are the fresh node-1.2 inputs.
  Incidental non-fatal observation in the same log: ``perk: skill binding: skill `perk-implement`
  for `stage:implement` is not installed under .agents/skills/perk-implement/SKILL.md`` —
  `.agents/skills/` is not tracked on main, so the runner checkout lacks the mirror; the drive
  proceeded regardless.
- **Cleanup (Part A step 10)** — PR #1145 closed unmerged, remote branch `plan-1144` deleted
  (`git ls-remote` empty again), issue #1144 closed.

### Defect log

Every failure hit during the dogfood, its diagnosis artifacts, and its disposition (B-series
numbering, continuing §8.14's B1–B6).

| # | Defect | Diagnosis artifacts | Disposition |
|---|--------|---------------------|-------------|
| B‑pre‑a | *(statically found, pre-execution)* fresh-plan remote implement fails at `git fetch origin plan-<N>` — nothing pushes the branch before dispatch | static read of `perk-run.yml` + `_drive_remote_target` (positions nothing, §8.13) | fixed in this PR: fetch-or-create checkout fallback (unit-pinned; the evidence runs used the seed-branch workaround); create arm verified live 2026-07-05 (see addendum) |
| B‑pre‑b | *(statically found, pre-execution)* the §8.12 events stream dies with the runner — no artifact upload | static read of `perk-run.yml` (no `upload-artifact` step) | fixed in this PR: `Upload run diagnostics` step (`perk-run-<run_id>`, `always() && !smoke`); not live for the 2026-07-04 evidence runs (dispatch runs main's workflow), whose streams survive only in the step logs; verified live 2026-07-05 (see addendum) |
| B7 | the worker's default model pick was `getAvailable()[0]` — the registry sorts alphabetically, so with an Anthropic key it selected the since-removed dated `claude-3-5-haiku-20241022`; the drive 404'd on turn 1 | run 28708056777 step log (`model_error`, provider 404); the terminal run-report comment on #1127 | fixed in this PR (`extension/worker/worker.ts`): an unset model now defers to the SDK's initial-model resolution (settings default → pi's per-provider defaults → first available); the worker logs the chosen model; unit-pinned in `worker.test.ts`. Cherry-picked onto `plan-1127` for the live re-dispatch (the worker entry resolves from the plan-branch checkout) |
| env‑1 | `pi-web-access` extension load error on the runner (`Cannot find module … pi-ai/dist/index.js/compat`) — the borrowed package fails to resolve a peer subpath under the runner's fresh `npm ci` layout | both 2026-07-04 drive logs (`perk worker: extension load error — … pi-web-access/index.ts`); reproduced 2026-07-05 on run 28756599501 (see addendum — step log + the `perk-run-01KWT5BPGRBYKKTAN9QY17FDS9` artifact are the fresh diagnostics) | environmental/non-fatal: perk's own extension + tools registered and both drives completed; documented, not fixed here (borrowed-package peer resolution on CI is out of this node's scope) |
| proc‑1 | the resume classifier routed the draft sacrificial PR to `ready_for_review`, not `address` (drafts never fetch feedback — designed behavior, §8.37) | the first resume JSON (`next_action: ready_for_review`) | procedure corrected, not a code change: Part A gained step 8 (`gh pr ready <pr>`) before the address dispatch |
