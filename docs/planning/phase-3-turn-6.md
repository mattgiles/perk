# Phase 3 · Turn 6 — the `Runner` contract + flip `remote_not_driven` into a real drive

GitHub plan **#167** (Objective #137, Node 2.1). Through P2.T8c a `--remote` launch of a drivable
stage (`implement`/`address`) *resolved* a remote target descriptor and exited with a stable
`remote_not_driven` — it persisted no intent and triggered nothing. This turn makes the remote door
a **real drive**: mint a perk `run_id`, persist the `run_id→plan` linkage, read it back to verify,
then trigger a runner that is discovered + matched back to the `run_id`.

It builds the **Python dispatch driver + the runner library** only. It does **not** build the GitHub
Actions workflow YAML (Node 2.2), the GitHub progress/terminal reporting (Node 2.3), the
secrets/health checks (Node 2.4), or the supervisor command surfaces (Nodes 3.1/3.2).

## Decisions

- **New module `perk/runner.py`** — a runner-agnostic library (no CLI/Click):
  - Value types (frozen dataclasses, JSON-stable): `RunHandle` (`runner`/`kind`/`run_ref`/`url`),
    `RunObservation` (`status`/`conclusion`/`url`), `DispatchRecord` (the durable linkage).
  - The `Runner` `Protocol`: `dispatch`/`observe`/`cancel`. `RunnerError` on a dispatch failure.
  - `GitHubActionsRunner` (`kind="github-actions"`) is the first implementation; `select_runner(ref)`
    yields one for any ref (the "keep future runners open" seam — the ref is recorded, not yet mapped
    to a runner kind). `GITHUB_ACTIONS_WORKFLOW = "perk-run.yml"` is locked here, built in 2.2.
  - **Two distinct run ids, never conflated.** perk's `run_id` (a ULID) is the canonical correlation
    key and is *itself* the run-discovery token (a workflow input embedded in the run-name); the
    GitHub Actions numeric run id is the runner-side `RunHandle.run_ref`.
- **`perk/github.py`** gains `WorkflowRun` + three ops routed through `_run`: `trigger_workflow`
  (dispatch then poll/backoff `min(2**attempt, 8)` discovering the run whose `display_title`/`name`
  contains the `match_token`; injected `sleep`/`max_attempts` keep it unit-testable; hard
  `GitHubError` on a `skipped`/`cancelled` match or exhaustion), `get_workflow_run`,
  `cancel_workflow_run`.
- **`perk/cache.py`** gains `dispatch_path`/`write_dispatch`/`read_dispatch` over
  `scratch/runs/<run_id>/dispatch.json` (`run_id` authoritative on write, mirroring `write_handoff`).
  No `SUBDIRS`/`init`/`.gitignore` change — `scratch/runs/` already exists and is gitignored.
- **`perk/launch.py`** — `_surface_remote_target`/`RemoteTarget` are replaced by
  `_drive_remote_target(*, stage, target, repo_root, dry_run)`. `launch_stage` calls it and
  **returns** (the remote path never reaches the exec block). Ordering: resolve plan (`no_plan_ref`
  if absent) → mint `run_id` → resolve `base` (loud `"main"` fallback) → **dry-run = side-effect-free
  preview** → **persist + read-back-verify** (`dispatch_state_unverified` on mismatch) → **trigger**
  (`dispatch_failed` + a `status:"failed"` record on error) → finalize `status:"dispatched"` + handle
  → surface human + `--json`.
- **`remote_not_driven` is retired.** New error types: `no_plan_ref`, `dispatch_state_unverified`,
  `dispatch_failed`. CLI `--remote` help (stages/implement/resume) updated; the stale "Phase-3 worker
  drives it" prose is replaced.

## Same-turn doc updates

- `shared/contracts.md` — new **§8.13** (the `Runner` contract, the dispatch record shape + location,
  the persist-then-trigger + read-back-verify ordering, the `workflow_dispatch` input contract that
  is the Node 2.2 dependency, and the retirement of `remote_not_driven`).
- `docs/cli-vs-pi.md` §4.5 status block — records the drive now persists intent + triggers.
- `docs/design/headless-worker.md` Forward notes — points to the dispatch driver.

## Testing

- `tests/test_runner.py` (new): `RunHandle`/`DispatchRecord` round-trip; `GitHubActionsRunner.dispatch`
  argv + discovered handle; `RunnerError` on exhaustion and on a `cancelled` match; `observe`/`cancel`
  mapping; `select_runner` carries the ref; `write_dispatch`/`read_dispatch` round-trip + authoritative
  `run_id` + `None` for absent.
- `tests/test_github.py` (extend): `trigger_workflow` poll/backoff (no-op `sleep`, late match) +
  `GitHubError` on a non-zero `gh workflow run`.
- `tests/test_launch.py` / `tests/test_cli_stages.py`: dry-run = dispatch preview (`success:true`,
  writes nothing); real-drive (`status:"dispatched"` + handle, `--json` carries `run_handle`);
  failure (`status:"failed"` + `dispatch_failed`); `no_plan_ref`. `remote_blocked` kept.
- `grep` guard: no remaining `remote_not_driven` token in `perk/` or `tests/`.

## Outcomes

Landed as planned, no deviations. `just ci` green.
