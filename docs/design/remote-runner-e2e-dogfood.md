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
3. **Sacrificial plan (human).** Author + save a minimal bounded plan for a trivial, low-risk
   throwaway change (the session drafts the seed text; the human runs `perk plan from <seed>` or
   `/plan` and approves). Note its issue number `<N>`.
4. **Seed the plan branch (session — workaround; skip once the fetch-or-create fallback is live
   on main).** Until the workflow's fetch-or-create checkout fallback has merged to main
   (dispatches always run **main's** `perk-run.yml` — the dispatcher triggers with
   `ref=<default branch>`), a fresh plan's remote implement fails at `git fetch origin plan-<N>`.
   Seed the branch from the plan's base:

   ```sh
   git push origin origin/<base>:refs/heads/plan-<N>
   ```
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
8. **Remote address (session, main checkout).** `perk plan resume <N> --remote --json` — capture
   the payload showing `next_action: address` (the resume classifier feeding the dispatch), then
   the same poll/verify/capture loop as steps 5–6.
9. **Cleanup (session).** Close the sacrificial PR unmerged, delete `plan-<N>`, close the plan
   issue. This keeps the procedure repeatable without polluting main or the learn pipeline.
10. **Failure loop.** Any failed run is **evidence, not a restart**: capture
    `gh run view <run-ref> --log` excerpts + (once the diagnostics-upload step is on main) the
    `perk-run-<run_id>` artifact, log the defect in Part B's defect log (B-series numbering,
    continuing §8.14's B1–B6), fix it in the accompanying PR when the defect is in perk (or
    document it when environmental), and re-dispatch.

## Part B — the captured evidence

### The smoke run (wiring proof)

*To be filled during execution.*

### The remote `implement` run

*To be filled during execution.* Checklist of verification points, each mapped to an artifact:

- [ ] Checkout log — plan branch fetched + hard-reset (or created from base).
- [ ] Composite setup log — uv/Node/perk/pi/worker-deps install lines.
- [ ] `run-worker: positioning …` + `worker entry=… (self)` stderr lines.
- [ ] Tools registered — no `no_extension_tools`; tool activity in the drive log;
      `RunOutcome.pr` non-null.
- [ ] The submitted PR URL (head `plan-<N>`).
- [ ] `RunOutcome` JSON (status `completed`, exit 0).
- [ ] The run-report comment URL on the plan issue + the job-summary text.
- [ ] The `perk workflow run list` discovery row.
- [ ] The model that ran + budget counters.

### The remote `address` run

*To be filled during execution.*

- [ ] The `next_action: address` resume JSON.
- [ ] Classification evidence from the drive log.
- [ ] The fix commit pushed to `plan-<N>`.
- [ ] Threads resolved (`gh pr view --json reviewThreads` → `isResolved: true`).
- [ ] The terminal run-report comment; exit 0.

### Defect log

*To be filled during execution.* Every failure hit during the dogfood, its diagnosis artifacts,
and its fix commit (B-series numbering).

| # | Defect | Diagnosis artifacts | Disposition |
|---|--------|---------------------|-------------|
| — | *(statically found, pre-execution)* fresh-plan remote implement fails at `git fetch origin plan-<N>` — nothing pushes the branch before dispatch | static read of `perk-run.yml` + `_drive_remote_target` (positions nothing, §8.13) | fixed in this PR: fetch-or-create checkout fallback (unit-pinned; live on the first post-merge fresh-plan dispatch) |
| — | *(statically found, pre-execution)* the §8.12 events stream dies with the runner — no artifact upload | static read of `perk-run.yml` (no `upload-artifact` step) | fixed in this PR: `Upload run diagnostics` step (`perk-run-<run_id>`, `always() && !smoke`) |
