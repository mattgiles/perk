# Phase 3 · Turn 7 — the GitHub Actions runner workflow (managed artifact) + the CI worker entrypoint

GitHub plan **#171** (Objective #137, Node 2.2). Node 2.1 (#167) flipped `--remote` into a real
drive: it mints a `run_id`, persists the `run_id→plan` linkage, verifies it, then triggers a
`workflow_dispatch` for the workflow file **`perk-run.yml`** (`runner.GITHUB_ACTIONS_WORKFLOW`),
verifying the run by matching the `run_id` embedded in the run-name. Until this turn, that workflow
file did not exist, so a real `--remote` dispatch surfaced a clean `gh`-sourced "workflow not found"
`dispatch_failed` (an honest failure, contracts.md §8.13).

This turn builds the **runner side of the cold remote door**:

1. **The managed workflow artifact** `.github/workflows/perk-run.yml` + its **composite setup
   action** `.github/actions/perk-remote-setup/action.yml`, installed by `perk init` and repaired by
   `perk doctor --fix` the way `init` already manages `.pi/workflow/`, `.pi/settings.json`, and the
   `AGENTS.md`/`.gitignore` blocks.
2. **The CI worker entrypoint** `perk run-worker` — the runner-side positioning + drive command. The
   workflow checks out the plan branch, then `perk run-worker` reconstructs the `cache.plan-ref` from
   the plan's GitHub state, materializes the handoff/plan-ref/plan-body into the checkout's
   `.pi/workflow/`, and spawns the Node headless worker (`extension/workerMain.ts`, Node 1.2) for the
   dispatched stage with `PERK_RUN_ID` in the env. Positioning is the runner's job (Gap 7); the
   worker consumes a prepared worktree and never re-mints.

It does **not** build the GitHub progress/terminal reporting (Node 2.3), the secrets/health checks
(Node 2.4), the supervisor command surfaces (Nodes 3.1/3.2), or the live doctor smoke (Node 3.3).

## Decisions

- **New module `perk/workflow_artifacts.py`** — the managed-artifact templates + their convergence:
  - `PERK_RUN_WORKFLOW` (the `perk-run.yml` body) and `PERK_REMOTE_SETUP_ACTION` (the composite
    action body), authored as Python string constants (code, not packaged data — packaging-safe, no
    wheel-data change).
  - `RUNNER_WORKFLOW_PATH = ".github/workflows/perk-run.yml"` and
    `REMOTE_SETUP_ACTION_PATH = ".github/actions/perk-remote-setup/action.yml"`.
  - `converge_runner_workflow(root, *, apply)` — a **full-file** managed convergence (write the file
    when absent or content-drifted; report drift on `apply=False`). Both files belong to the one
    `runner-workflow` capability.
  - The workflow honors the contract (§8.13 → §8.14): `run-name` **embeds `${{ inputs.run_id }}`**
    for verify-by-discovery; typed `workflow_dispatch` inputs **`run_id`, `stage`, `plan`, `base`**;
    per-plan `concurrency` group `perk-run-${{ inputs.plan }}`; a secret-validation step; a checkout
    of the plan branch (`plan-<plan>`); the composite setup; then `perk run-worker`.
- **`runner-workflow` capability** (`perk/capabilities.py`, `required=True`, `scope="both"`) +
  a `ManagedConvergence` in `init.managed_convergences()` + a `_MANAGED_GROUP` entry (`repository`).
  `init` applies it, `doctor` verifies/repairs it — both auto-wired through the shared SSOT.
- **New module `perk/run_worker.py` + `perk/cli/commands/run_worker_cmd.py`** — `perk run-worker
  --run-id --stage --plan [--base]`:
  - Reconstruct the plan-ref from GitHub (`github.get_plan` + `resume.reconstruct_plan_ref`); a
    missing plan ⇒ `UserFacingCliError(plan_not_found)`.
  - Validate the stage is a `doors.cold_remote: true` drivable stage (`implement`/`address`); else
    `UserFacingCliError(stage_not_drivable)`.
  - Materialize the worktree (cwd = the checked-out plan branch): `cache.ensure_layout`,
    `write_handoff({stage, mode})`, `write_plan_ref`, `launch._materialize_plan_body`.
  - Resolve the Node worker entrypoint (`PERK_WORKER_ENTRY` env override; else `<repo>/extension/
    workerMain.ts` for the self-repo; else `.pi/npm/node_modules/@perk/pi/extension/workerMain.ts`
    for a consumer) — a missing entry is a loud `UserFacingCliError(worker_entry_missing)`.
  - Spawn `node <entry> <stage> --worktree <repo_root>` with `PERK_RUN_ID=<run_id>` in the env
    (routed through one wrapper, monkeypatchable); forward the worker's exit code; emit the worker's
    structured outcome on stdout and a human summary on stderr.
- **`run-worker` is a CI-facing, deterministic exterior command** (no agentic reasoning): it
  positions and drives; the model/auth resolution is the Node worker's job (env-var key resolution,
  Gap 5).

## Same-turn doc updates

- `shared/contracts.md` — new **§8.14** (the Node 2.2 runner artifact: the managed workflow +
  composite action, the `perk run-worker` positioning entrypoint, and how it satisfies §8.13's
  `workflow_dispatch` input contract). §8.13's "until 2.2 lands" caveat is reconciled.
- `docs/cli-vs-pi.md` — `perk run-worker` is recorded as the runner-side positioning surface.

## Testing

- `tests/test_workflow_artifacts.py` (new): the templates honor the locked contract (`run-name`
  embeds `${{ inputs.run_id }}`, the four typed inputs, the per-plan concurrency, the secret-
  validation step, the `perk run-worker` invocation); `converge_runner_workflow` creates both files,
  is a no-op when converged, and reports/repairs drift.
- `tests/test_run_worker.py` (new): positioning materializes handoff/plan-ref/plan-body from a fake
  plan state; `plan_not_found`/`stage_not_drivable`/`worker_entry_missing` errors; the Node spawn
  argv + `PERK_RUN_ID` env + forwarded exit code (subprocess monkeypatched).
- `tests/test_doctor.py` coherence guard + `tests/test_capabilities.py` cover the new capability
  automatically (the new convergence is verified by `doctor`).

## Outcomes

Built as planned, with these refinements:

- **`converge_runner_workflow(root, self_repo, *, apply)` gained `self_repo`.** The workflow file is
  identical everywhere, but the composite action's `perk` install command is self-vs-consumer aware:
  the self-repo dogfoods the code under test (`uv tool install --from . perk`); a consumer installs
  the published distribution (`uv tool install perk`). The published-install version pinning + the
  surrounding secrets are flagged as Node 2.4's prereq concern, not authored here. `init`'s
  `ManagedConvergence` lambda threads the `self_repo` it already computes; `doctor` gets it for free
  (it calls `init.managed_convergences(root, self_repo)`).
- **The secret-validation step uses a terse `::error::` annotation** (the verbose erk wording blew
  the 100-col lint budget inside the template string). Functionally identical: empty `PERK_GH_PAT`
  fails the job with a clear annotation.
- **`--base` is accepted but unused by `run-worker`** (the plan branch is already checked out by the
  workflow). It is part of §8.13's input contract and is logged for parity/future use; recorded in
  the contract so the no-op is intentional, not a gap.
- The self-repo is converged: `.github/workflows/perk-run.yml` + `.github/actions/perk-remote-setup/
  action.yml` are committed (the self-repo install variant). `perk doctor` reports `runner-workflow`
  converged.

Deferred (named, not built): GitHub progress/terminal reporting (Node 2.3), runner secrets/health
checks (Node 2.4), supervisor command surfaces (Nodes 3.1/3.2), the live doctor smoke (Node 3.3).
