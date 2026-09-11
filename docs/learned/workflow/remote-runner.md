---
title: The remote-runner dispatch + CI execution seam
read_when: You are working on `src/perk/run/` (runner, run_worker, discovery), the `perk-run.yml` workflow + `perk-remote-setup` action, the `--remote` dispatch path, or the worker-entry resolver.
cluster: doors-and-launch
---

# The remote-runner dispatch + CI execution seam

perk can dispatch a drivable stage (`implement`/`address`) to a remote runner — today GitHub
Actions. The seam: `src/perk/run/launch/remote.py` (`_drive_remote_target`) +
`src/perk/run/runner.py` dispatch; `src/perk/run/workflow_artifacts.py` renders the managed
`.github/workflows/perk-run.yml` + `perk-remote-setup` composite; `src/perk/run/run_worker.py` is
the CI entrypoint that spawns `extension/workerMain.ts`. `shared/contracts.md` §8.13–§8.19 hold
the normative specs; this doc keeps only the rules, traps, and dated residuals.

## Two run identities

perk's **`run_id`** (a ULID, `src/perk/state/run_id.py`) is the canonical correlation key **and**
the run-discovery token — a `workflow_dispatch` input embedded in the workflow's `run-name`
(`perk {stage} · plan #{plan} · {run_id}`, workflow file `runner.GITHUB_ACTIONS_WORKFLOW`). The
GitHub Actions numeric id is a *separate* runner-side handle, `RunHandle.run_ref`; `perk workflow
run …` takes the former. `github.trigger_workflow` matches the token by *containment* in
`display_title`/`name`; `runner.parse_run_name` recovers the fields by an *exact* regex + ULID
check; `tests/test_workflow_artifacts.py::test_run_name_template_and_parser_are_in_lockstep` holds
them in lockstep. `plan` / `plan_ref.pr_id` is the **plan issue id**, never a PR number — the PR
is derived via the issue backend's `get_plan(...).pr`.

## Dispatch: establish the record before the trigger

`_drive_remote_target` positions nothing locally. After resolving the plan (`no_plan_ref` without
one) and minting the `run_id`, it applies §8.2 establish-before-consume to its own record:
`cache.write_dispatch` → `cache.read_dispatch` → assert `run_id` + `plan_ref.pr_id` round-tripped,
else a **hard** `dispatch_state_unverified`. Only then `Runner.dispatch`; a `RunnerError`/
`GitHubError` rewrites the record `status:"failed"` + `error` and raises `dispatch_failed` — the
failed record is **kept**, the only durable trace of a run that never started. The finalize
write-back (`status:"dispatched"` + `run_handle`) is loud-but-non-fatal; the pre-trigger linkage is
the gate. `--dry-run` writes and triggers nothing but is **not** subprocess-free: it still shells
`github.default_branch` when the plan has no pinned base (falling back loudly to `"main"`) —
never equate "dry-run" with "no shell-out".

## Discovery is GitHub truth; the record is a cache

The rendered run-name, enumerable via the GHA run listing, **is** the record that a remote run
exists: any machine reconstructs the run + a `RunHandle` from it with zero local state
(`Runner.discover` via `src/perk/run/discovery.py`, a sibling module because `cache` imports
`runner`; never writing back). The local record only *enriches* and keeps failed/never-triggered
dispatches visible — §8.17's `both`/`local`/`discovered` rows.

- **Reads fail soft.** `perk workflow run list` never `require_github`s; a discovery
  `RunnerError` degrades to the local-cache view with one stderr note, per-row overlays likewise,
  exit code unchanged. The deliberate inversion is `discovery.active_writer_plan_ids` (§8.49): an
  unreadable observation is never "no active writer", so it propagates.
- **Control climbs a two-rung ladder** (`resolve_target`, §8.18): a record *with* a handle wins;
  otherwise (no record, or a handle-less record whose finalize never landed)
  `discovery.find_discovered_run` — exact `run_id` match — so any machine can cancel/retry a run
  it never dispatched. `run_not_found` vs `run_not_dispatched` name the two misses.
- **Retry reuses the same run** (`gh run rerun [--failed]` on the existing `run_ref`): no new
  ULID, no `cache.write_dispatch`, no pre-flight `observe` gate.

## Smoke is an input, not a stage

`perk doctor workflow smoke-test` (`src/perk/run/workflow_smoke.py::dispatch_smoke`, §8.19) proves
what no static check can — the workflow dispatches, a job starts, secrets are readable in the
Actions context — by triggering `perk-run.yml` **directly** with `stage=smoke`, `plan=smoke`,
`smoke="true"`. Only `Validate required secrets` + the `Smoke check` echo run; checkout, composite
setup, drive and diagnostics upload all carry `if: inputs.smoke != 'true'`. It mints a `run_id`
but writes **no** dispatch record and creates no GitHub artifact, and `Runner.discover` drops
`stage == runner.SMOKE_STAGE`, so supervisor surfaces never see it.

## Remote worker resolution and consumer dependency staging

The runner side is a chain a local Pi launch never runs (§8.14): checkout with `PERK_GH_PAT` →
the `perk-remote-setup` composite → `gh auth setup-git` → `perk run-worker`, which reconstructs
the plan-ref from the backend, positions the plan branch (`position_branch`, incremental or
stacked), materializes handoff/plan-ref/plan-body, delivers `.agents/skills/` via the skills-CLI
sync — **fatal**, pre-spawn (`skills_sync_failed`; see `skill-bindings.md` for the local-mirror
contrast) — then spawns `node` on the resolved entry with `PERK_RUN_ID` and forwards its exit
code. The composite sets the `perk[bot]` git identity `--global` (it runs before the plan-branch
checkout); the worker loads the managed `.pi/settings.json` packages via disk-layered settings
behind a terminating-tool preflight (`no_extension_tools`) —
`docs/learned/pi/headless-session-drive.md`.

- **Worker-entry resolution is a candidate ladder** (`run_worker.resolve_worker_entry`):
  `PERK_WORKER_ENTRY` (`env`) → self-repo `extension/workerMain.ts` (`self`) → the consumer npm
  install under `.pi/npm/node_modules/@mgiles/perk` (`consumer-npm`), **staged** by
  `_stage_consumer_entry` as a fresh full-package copy (`node_modules` excluded) at
  `.pi/npm/perk-worker/`, because Node refuses to type-strip `.ts` under any `node_modules`
  (`ERR_UNSUPPORTED_NODE_MODULES_TYPE_STRIPPING`); package-root resources ride along, bare imports
  walk up to `.pi/npm/node_modules`. A miss is loud (`worker_entry_missing`).
- **Consumer deps are a two-spec install** (`workflow_artifacts._WORKER_DEPS_CONSUMER`):
  `@mgiles/perk@{__version__}` plus the *unpinned* `@earendil-works/pi-coding-agent` under
  `--prefix .pi/npm --legacy-peer-deps`. The SDK spec is load-bearing: `@mgiles/perk` ships zero
  runtime deps (pi is a peer) and `--legacy-peer-deps` skips peers, so the perk spec alone leaves
  the worker's import set open. Self-repo: `npm ci`.
- **In a consumer repo no fix rides a plan branch** — worker code is the npm tarball, the CLI is
  PyPI, the workflow/composite is the consumer's committed tree; committing worker code to a
  consumer plan branch flips resolution to `self` and voids the proof.
- **A retired resolver candidate outlives its cleanup migration.** The `consumer-git` rung is
  gone, but `settings.GIT_PACKAGE` + `consumer_git_clone_root` stay because doctor's
  `_remove_orphaned_git_clone` (`src/perk/convergence/doctor/fixes.py`) still removes deployed
  clones — "stop probing X" is not "delete the derivation of X".

## The declarative/imperative gap

The seam's **declarative** half — rendered YAML, `init`/`doctor` convergence, the contracts — is
unit-pinned; its **imperative** half — the live dispatch → checkout → setup → drive → report chain
— only a real run reaches. Every defect the dogfoods logged lived in that gap: treat
declarative-correct / execution-untested as a first-class risk in any plan touching the seam, and
live proofs as point-in-time, never recurring coverage. Fixes deploy asymmetrically —
`GitHubActionsRunner.dispatch` triggers the **default branch's** `perk-run.yml`, so a template fix
goes live only after merge, while a self-repo worker-*code* fix rides the plan branch (the `self`
rung). Editing `PERK_RUN_WORKFLOW` means re-converging the committed self-repo copy in the same
change — and `perk doctor --fix` converges the *whole* repo, so revert drift outside your surface
(`init-doctor.md`).

## Test traps

- **Injected `sleep` must reach the poll.** `github.trigger_workflow` takes `sleep`/`max_attempts`
  but `GitHubActionsRunner.dispatch` does not forward them (`dispatch_smoke` does). Test
  backoff/exhaustion at the gateway (`tests/test_github.py`, no-op sleep) and the runner's
  `GitHubError → RunnerError` wrapping by monkeypatching the gateway to raise — never drive
  exhaustion through the runner (it sleeps for real).
- **Relocating a shell step into the Python entry** (`position_branch`) turns inert tests into
  real git runs. `tests/test_run_worker.py` pairs an autouse *recording* stub with one explicit
  orchestration-order test (branch → worktree → spawn); an autouse stub alone leaves the wiring
  unobserved. Stub `gh`/git collaborators at their module seams (`run_report.report_started`,
  `init.sync_skills`, `git.main_worktree_root`) — a global `subprocess.run` fake swallows them.
- **Reporting is fail-soft for expected failures only.** `run_report.report_started`/
  `report_terminal` catch `IssueBackendError` (log + swallow, exit code untouched); anything else
  is a bug and surfaces (`broad-catch-narrowing.md`).

## Residual risks and history (dated)

- **2026-07-04 / 2026-07-06** — the self-repo and consumer chains were each proven live once
  (`docs/design/archive/remote-runner-e2e-dogfood.md`,
  `docs/design/archive/remote-runner-consumer-dogfood.md`); their defect logs own the chronicle.
  Durable lessons: the first live defect can mask the next (B8 died before B-pre-c's predicted
  `ERR_MODULE_NOT_FOUND` could fire — plan for *fails-differently*); the worker's default model
  must defer to the SDK's own resolution (B7; `headless-session-drive.md`).
- **Open at this writing:** no recurring CI-gated live E2E; the published-registry consumer path
  is proven only through labeled hand-edits in the scratch fixture (no post-release canonical
  re-proof recorded); the SDK spec in `_WORKER_DEPS_CONSUMER` is deliberately unpinned; the staged
  entry reparses under a `MODULE_TYPELESS_PACKAGE_JSON` warning (`package.json` declares no
  `"type"`); the stacked `position_branch` arm has never run live (`objective-delivery.md`).
- **Retired:** the `consumer-git` worker-entry candidate; the `remote_not_driven` error type (now
  `no_plan_ref` / `dispatch_state_unverified` / `dispatch_failed`); the consumer worker-deps
  `::error::` deferral.

## Cross-references

- `shared/contracts.md` §8.13 · §8.14 · §8.17/§8.18 · §8.19 — the normative specs
- `docs/learned/pi/headless-session-drive.md`, `docs/learned/workflow/skill-bindings.md`,
  `docs/learned/workflow/init-doctor.md`, `docs/learned/toolchain/worktree-node-modules.md`
