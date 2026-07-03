---
title: The remote-runner dispatch + CI execution seam
read_when: You are working on `perk/run/runner.py` / `perk/run/run_worker.py` / `perk/run/discovery.py`, the `perk-run.yml` workflow + `perk-remote-setup` composite action, the remote `--remote` dispatch path, the verify-by-discovery poll, the canonical run-name discovery (`parse_run_name` / `Runner.discover` — local dispatch records demoted to cache), or the worker-entry resolver (the three-candidate ladder, `consumer-git` retired) and the realized consumer worker-deps `@perk/pi` install (formerly a loud deferral).
---

# The remote-runner dispatch + CI execution seam

perk can dispatch a stage drive to a remote runner (today: GitHub Actions) instead of running it on
the local worktree. The seam spans Python (`perk/run/runner.py` dispatch + `perk/run/run_worker.py` CI
entrypoint), a managed CI artifact (`.github/workflows/perk-run.yml` + the `perk-remote-setup`
composite action), and the TS worker the runner ultimately drives (`extension/workerMain.ts` →
`driveStage`). This doc captures the non-obvious shape and the load-bearing rules.

> **One Code Rule.** Everything below names files and describes behavior; it does not reproduce
> source. Read the pointers.

## The seam in two halves — and the gap between them

The seam has a **declarative** half and an **imperative** half, and only the first is
regression-testable:

- **Declarative (testable):** init/doctor capability registration, contracts `§8.13`/`§8.14`, and
  the *rendered* YAML of `perk-run.yml` + the composite action. Unit tests assert the rendered input
  contract, step presence, and repo-kind branching, and locked every fix.
- **Imperative (NOT covered):** the live `plan → dispatch → checkout → setup → drive` chain. No test
  or dogfood run executes it end-to-end until a live `--remote` smoke runs it.

**The cross-cutting lesson (from #176):** a managed CI artifact's string-template body is
unit-testable, but its end-to-end *execution* is not. The six B1–B6 defects in the Node 2.2 path all
shipped **silent** in exactly this gap — unit tests cannot catch "a fresh `ubuntu-latest` runner has
no git identity" or "the consumer worker-clone can't exist because `.pi/git` is gitignored." Treat
the **declarative-correct / execution-untested gap as a first-class risk** when authoring a CI seam.
The standing follow-up — a live remote smoke — is folded into Node 3.3 (`doctor workflow`).

## The `Runner` contract (Node 2.1)

`perk/run/runner.py` defines a runner-agnostic `Runner` **Protocol** + value types
(`RunHandle`/`RunObservation`/`DispatchRecord`) + the concrete `GitHubActionsRunner` + `select_runner`.
`observe`/`cancel` are implemented at the **library level (not stubbed)** so the supervisor nodes
(3.1/3.2) consume settled shapes — only the supervisor *command surfaces* are deferred to those
nodes. The old `remote_not_driven` error was **retired** in favor of three honest error types:
`no_plan_ref` / `dispatch_state_unverified` / `dispatch_failed`. (Scrub *prose* mentions of a retired
token too — a retired-token guard catches comments, not just code.)

## Two distinct run ids — never conflate

This is the easy mistake the contract (`§8.13`) calls out explicitly:

- perk **`run_id`** (a ULID) is the canonical correlation key **and** the run-discovery token — a
  `workflow_dispatch` input embedded in the workflow's `run-name`.
- the GitHub Actions **numeric run id** is a *separate* runner-side handle, stored as
  `RunHandle.run_ref`.

Additionally, reconfirm that **`plan_ref.pr_id` is the plan's GitHub issue ID (the plan issue number)**, *not* the pull request number. The actual PR is derived when needed by calling `github.get_plan(...)` with the issue ID.

## The pinned `workflow_dispatch` contract

The dispatch contract is pinned so the verify-by-discovery poll works:

- the workflow file MUST be named `perk-run.yml` (`runner.GITHUB_ACTIONS_WORKFLOW`),
- typed inputs `{run_id, stage, plan, base}`,
- `run-name` MUST embed `${{ inputs.run_id }}` so the poll (match `display_title`/`name` *contains*
  the token) succeeds.

## Establish-before-consume, realized

The `§8.2` discipline here is write-then-read-back-then-assert, hard-fail on mismatch (never a silent
`pass`): `cache.write_dispatch` → `cache.read_dispatch` → assert `run_id` + `plan_ref.pr_id`
round-tripped → raise `dispatch_state_unverified` on mismatch. The **pre-trigger linkage is the hard
gate**; the finalize write-back (status→dispatched + handle) is **best-effort / loud-but-non-fatal**.
Failed-dispatch records are deliberately **kept** (`status:"failed"` + `error`) for later supervisor
visibility — never deleted.

The dispatch record rides the existing `scratch/runs/<run_id>/dispatch.json` path — a path
`perk init` already creates and `.gitignore` already excludes (`/.pi/workflow/scratch/`). **No new
cache layout / gitignore / init / doctor change was needed**; reuse the run-scoped scratch dir for
per-run durable artifacts rather than adding a `SUBDIRS` entry. Cross-ref `plan-ref-lifecycle.md` and
the `§8.2` establish-before-consume discipline.

## "Dry-run" is not "no subprocess"

A side-effect-free `--dry-run` preview can still **shell out**. `_drive_remote_target`'s dry-run is
write-free (no `dispatch.json`, no trigger) but still calls `github.default_branch(repo_root)` (a
`gh repo view`) to build the `inputs` preview — wrapped in a `GitHubError` try/except with a loud
`"main"` fallback (so a CliRunner test on a repo with no real GitHub remote passes: `gh` fails fast →
fallback). A cold-door dry-run needing a PR number must **skip PR resolution** (which shells `gh`):
use `pr_number=0` under `--dry-run` (mirroring `create_pr`'s dry-run) and only `require_github` when
not dry-run. Don't assume "dry-run" means "no subprocess".

## `sleep` injection must reach the actual poll call

`github.trigger_workflow` takes injectable `sleep`/`max_attempts`, but `GitHubActionsRunner.dispatch`
may call it **without forwarding them** — so it uses the real `time.sleep` + default `max_attempts`.
A runner-level exhaustion test would therefore sleep for real (~minutes). The discipline that works:
test poll/backoff + exhaustion at the **github-gateway level** (with an injected no-op `sleep`), and
test the runner's `GitHubError→RunnerError` wrapping by **monkeypatching the gateway call to raise**.
Don't try to exercise exhaustion through the runner.

## Smoke-test short-circuit pattern

To enable universal, zero-spend GHA smoke testing of workflows, introduce an additive `smoke` boolean input inside `workflow_dispatch`. When `smoke` is set to true, the workflow should immediately exit successfully (a fast short-circuit) without spinning up heavy runner jobs or committing real resources. This allows verifying GHA dispatch wiring, API credentials, and input contract integrity instantly and safely.

## Runner-control seam shape

The supervisor controls (such as `cancel` and `retry`/`rerun` commands) operate via a strict translation pipeline:
1. Resolve the `run_id` (ULID) from command arguments.
2. Resolve it to a `RunHandle` via the two-rung ladder (`resolve_target`, contracts §8.18): the
   local dispatch record (`scratch/runs/<run_id>/dispatch.json`) is the **cache accelerator**;
   on a miss (no record, or a handle-less record whose finalize write-back never landed) fall
   back to the **canonical GHA discovery** (`discovery.find_discovered_run` — exact match on the
   run-name's parsed `run_id` token), so any machine can control a run it never dispatched.
3. Dispatch the action to the resolved runner instance via `select_runner(...)` (the record's
   runner ref when one exists, else the reconstructed handle's).

### Rerun reuse

When retrying/rerunning a remote execution, the supervisor reuses the existing GHA run ID by invoking `gh run rerun [--failed]` against the runner reference. It does not generate a new local ULID or mutate local dispatch records, ensuring history and tracking remain linked to the single canonical dispatch record.

## Fail-soft orchestrators & subprocess test trap

While event-stream reporting components are called unguarded, their internal reporting logic must be fully guarded (`try/except Exception: log + swallow`) to ensure failures in the telemetry/reporting layer never crash the primary execution loop.

**Subprocess Monkeypatching Test Trap:** When writing unit tests for these orchestrators, be extremely careful with subprocess capturing-fakes in parent test suites. Stub the reporting collaborator directly at its module-function seam (e.g., mocking the high-level python function that interfaces with `gh`) rather than letting the code make real or mock-subprocess shell out. Otherwise, internal `gh` calls can bypass or clobber the parent test suite's capture-fakes, resulting in leaky and brittle test runs.

## Discovery truth with a local cache, fail-soft everywhere

The **canonical existence source for remote runs is GitHub's own run enumeration**: the managed
workflow's run-name embeds `perk {stage} · plan #{plan} · {run_id}`, `runner.parse_run_name`
recovers those fields, and `Runner.discover` (orchestrated by `perk/run/discovery.py`) turns the
listing into `DiscoveredRun`s (smoke runs and foreign titles filtered out). Local dispatch JSON
files (under `scratch/runs/<run_id>/dispatch.json`) are a **cache/correlation accelerator** —
they enrich discovered rows (plan url, objective backlink, precise dispatch time) and are the
only durable trace of failed/never-triggered dispatches. Supervisor read surfaces (`run list`,
the `objective run` gate) enumerate GitHub first and degrade **fail-soft** to the local-cache
view on a discovery error: wrap every external fetch in fail-soft `try` blocks that log one-line
stderr notes but never raise or alter exit codes when network or API limits are hit.

## CI execution specifics (Node 2.2)

- **Fresh-runner git identity.** The headless `implement` drive commits via `bash` before `submit`
  pushes; `ubuntu-latest` has no `user.name`/`user.email` and perk's git layer never sets one. The
  composite setup must `git config --global` a `perk[bot]` identity — **`--global`** because it runs
  *before* the plan-branch checkout (a repo-local config against an unfinalized tree is fragile).
- **Auth model (a stated decision, recorded in `§8.14`).** The runner checks out + pushes with
  `PERK_GH_PAT` (a PAT), **not** `github.token` — only PAT-pushed commits trigger downstream CI;
  `GITHUB_TOKEN`-pushed commits don't.
- **Worker-entry resolution is a three-candidate ladder:** `PERK_WORKER_ENTRY` (env) → self-repo
  `extension/workerMain.ts` → npm install (`.pi/npm/node_modules/@perk/pi/...`, `consumer-npm`).
  Verified anchor: `run_worker.py::resolve_worker_entry`'s `WorkerEntry.source` comment now reads
  `"env" | "self" | "consumer-npm"`. **The `consumer-git` candidate** (the
  `.pi/git/<host>/<path>/extension/workerMain.ts` clone path) **was retired** once the npm install path
  superseded it — its `_git_clone_worker_entry` helper and the now-unused `from perk.convergence import
  init` import in `run_worker.py` are gone.

- **Resolver-candidate vs migration-helper have independent lifecycles.** Dropping the `consumer-git`
  *candidate* does **not** mean retiring the clone-path SSOT: `consumer_git_clone_root` + `GIT_PACKAGE`
  (now in `settings.py`) **stay**, because the doctor forward-migration `_remove_orphaned_git_clone`
  (`perk/convergence/doctor/fixes.py`) still `rmtree`s an orphaned `.pi/git/<host>/<path>`. **Rule: a
  resolver candidate for a retired path can go the moment a superseding path exists; the *cleanup
  migration* for already-deployed consumers outlives it** — don't conflate "stop probing X" with
  "delete the derivation of X's location." (See `extension-clone-lifecycle.md` for the migration seam.)

## Honest fiction vs. loud deferral

Consumer remote drive genuinely can't run end-to-end in CI yet (`.pi/npm` is gitignored and nothing in
the composite runs `pi` to trigger the extension load). The original posture (per "don't author
fiction") landed the cheap/correct/unit-testable pieces and made the genuinely-unbuildable consumer
worker-deps step a **loud `::error::` + `exit 1` deferral**, not a silently-broken `npm ci`.

**Update — the deferral has since been realized.** Once perk owned the `.pi/npm` install, the
`_WORKER_DEPS_CONSUMER` placeholder went from `echo "::error::…"; exit 1` to a real pinned
`npm install @perk/pi@{__version__} --prefix .pi/npm --legacy-peer-deps` — the exact arg shape of
`npm.install` / `extension_install._pinned_spec()` (`workflow_artifacts.py` derives `_NPM_NAME =
NPM_PACKAGE.removeprefix("npm:")` from the same settings SSOT). Self-repo keeps `npm ci`. **Keep the
honest note: end-to-end consumer remote drive is still execution-untested** (the
`defaultCreateRuntime` disk-settings follow-up below) — downgrading a hard `exit 1` to a real-but-
unverified path is **not** the same as claiming it proven.

**Grep ALL contracts mentions when reconciling.** Retiring the deferral needed a **third** §8.14 site
beyond the two obvious ones (the composite worker-deps bullet + the worker-entry ladder step) — the
`smoke-test` parenthetical ("the consumer worker-deps step is a loud … deferral"). A
`grep -n "consumer-git\|Node 2.4\|loud.*deferral\|\.pi/git"` across `contracts.md` surfaced it; the
deferral was even labelled inconsistently ("Node-2.4" vs "Node-2.2") across sites — version labels are
drift magnets (reinforces `doc-reconciliation.md`).

### Open follow-up: does a real remote launch load `@mgiles/perk` at all?

The first real execution of the runner path (the e2e worker test tier) surfaced an unresolved gap:
`defaultCreateRuntime`'s in-memory settings **ignore disk `.pi/settings.json` packages**, so a
remote worker as currently written would register zero extension tools. A real remote launch must
either inject `resourceLoaderOptions.extensionFactories`, install the package, or layer disk
settings — unresolved; recorded in the objective #137 reconcile and
`docs/planning/phase-3-turn-11.md`. Mechanics: `docs/learned/pi/headless-session-drive.md`.

## `doctor --fix` re-converge pulls in unrelated drift

Regenerating committed self-repo artifacts via `perk doctor --fix` re-converges the **whole repo**,
so it can pull in **unrelated pre-existing drift** (a stray skill-manifest entry, a `.gitignore`
reorder). After a `--fix` re-converge, diff *every* touched file and `git checkout` drift outside the
plan's surface — `--fix` converges the whole repo, not just your target artifact. Cross-ref
`init-doctor.md`.

## Cross-references

- `perk/run/runner.py` — the `Runner` Protocol, value types, `GitHubActionsRunner`, `select_runner`
- `perk/run/run_worker.py` — the CI worker entrypoint + the three-candidate worker-entry ladder
- `perk/convergence/doctor/fixes.py` — `_remove_orphaned_git_clone` (the cleanup migration that
  outlives the retired `consumer-git` resolver candidate)
- `docs/learned/workflow/extension-clone-lifecycle.md` — the retired git-clone lifecycle + the
  `_MIGRATIONS` filesystem-rmtree seam
- `extension/workerMain.ts` — the worker entry the runner drives into
- `shared/contracts.md` §8.13 (Runner contract + dispatch record) / §8.14 (Actions runner artifact +
  CI worker entrypoint)
- `docs/learned/pi/headless-session-drive.md` — the drive the runner dispatches into
- `docs/learned/workflow/plan-ref-lifecycle.md` — the `cache.plan-ref` lifecycle + establish-before-consume
- `docs/learned/workflow/init-doctor.md` — the `doctor --fix` re-converge discipline
- `docs/learned/toolchain/worktree-node-modules.md` — worktree SDK resolution gotchas
