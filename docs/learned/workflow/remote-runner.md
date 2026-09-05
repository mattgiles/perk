---
title: The remote-runner dispatch + CI execution seam
read_when: You are working on `src/perk/run/` (runner, run_worker, discovery), the `perk-run.yml` workflow + `perk-remote-setup` action, the `--remote` dispatch path, or the worker-entry resolver.
cluster: doors-and-launch
---

# The remote-runner dispatch + CI execution seam

perk can dispatch a stage drive to a remote runner (today: GitHub Actions) instead of running it on
the local worktree. The seam spans Python (`src/perk/run/runner.py` dispatch +
`src/perk/run/run_worker.py` CI entrypoint), a managed CI artifact (`.github/workflows/perk-run.yml` + the `perk-remote-setup`
composite action), and the TS worker the runner ultimately drives (`extension/workerMain.ts` →
`driveStage`). This doc captures the non-obvious shape and the load-bearing rules.

> **One Code Rule.** Everything below names files and describes behavior; it does not reproduce
> source. Read the pointers.

## Distillation

- The seam is declarative (rendered YAML, unit-testable) + imperative (live execution) — the
  declarative-correct / execution-untested GAP is a first-class risk (six defects shipped silent
  in it) — "The seam in two halves — and the gap between them".
- The dispatch abstraction is the `Runner` Protocol — "The `Runner` contract".
- Two distinct run ids exist (perk's `run_id` vs the remote workflow-run handle) — NEVER
  conflate them — "Two distinct run ids — never conflate".
- Dispatch is establish-before-consume: write → read back → assert round-trip, hard-fail on
  mismatch; failed records are kept, never deleted — "Establish-before-consume, realized".
- Discovery is truth-with-a-local-cache, fail-soft everywhere — "Discovery truth with a local
  cache, fail-soft everywhere".
- An unbuildable step lands as a LOUD deferral (`::error::` + exit 1), never a silently-broken
  placeholder — "Honest fiction vs. loud deferral" (its deferral has since been realized).
- "Consumer dogfood facts" is a point-in-time validation record, not recurring coverage.

## The seam in two halves — and the gap between them

The seam has a **declarative** half and an **imperative** half, and only the first is
regression-testable:

- **Declarative (testable):** init/doctor capability registration, contracts `§8.13`/`§8.14`, and
  the *rendered* YAML of `perk-run.yml` + the composite action. Unit tests assert the rendered input
  contract, step presence, and repo-kind branching, and locked every fix.
- **Imperative (proven live on both worker-entry paths):** the live
  `plan → dispatch → checkout → setup → drive → report` chain completed real remote `implement`
  and `address` runs end-to-end through perk's own doors on the self-repo (2026-07-04 — the
  procedure + captured evidence are `docs/design/archive/remote-runner-e2e-dogfood.md`), and on the
  consumer path (2026-07-06 — the staged `consumer-npm` entry in a scratch consumer repo on the
  released distributions; `docs/design/archive/remote-runner-consumer-dogfood.md`). Both proofs are
  point-in-time — there is no recurring CI-gated live E2E.

**The cross-cutting lesson (from #176):** a managed CI artifact's string-template body is
unit-testable, but its end-to-end *execution* is not. The six B1–B6 defects in the Node 2.2 path all
shipped **silent** in exactly this gap — unit tests cannot catch "a fresh `ubuntu-latest` runner has
no git identity" or "the consumer worker-clone can't exist because `.pi/git` is gitignored." Treat
the **declarative-correct / execution-untested gap as a first-class risk** when authoring a CI seam.
The live dogfood confirmed the lesson: it caught **B7** (the worker's `getAvailable()[0]` default
picked an alphabetically-first — i.e. oldest, since-removed — model and 404'd the drive) plus a
fresh-plan checkout failure, both invisible to the unit pins; and it surfaced a useful bootstrap —
worker-*code* fixes ride the plan branch (the `self` entry resolves from the plan-branch checkout)
while workflow-*template* fixes go live only after merging to main (dispatch pins main's
`perk-run.yml`). The consumer dogfood re-confirmed the lesson with **B-pre-c** (zero runtime deps
+ `--legacy-peer-deps` leaves the worker's import set open) and **B8**
(`ERR_UNSUPPORTED_NODE_MODULES_TYPE_STRIPPING` at spawn) — both invisible to the unit pins.

## The `Runner` contract

`src/perk/run/runner.py` defines a runner-agnostic `Runner` **Protocol** + value types
(`RunHandle` — with its `RunHandleModel` boundary — and `RunObservation`) + the concrete
`GitHubActionsRunner` + `select_runner`. The **persisted dispatch record** is
`src/perk/state/cache.py`'s `Dispatch` (frozen dataclass) + `DispatchModel` (the LenientParseModel
boundary), written/read via `cache.write_dispatch` / `cache.read_dispatch` (+
`cache.list_dispatch_records`) from the `--remote` drive in `src/perk/run/launch/remote.py`.
`observe`/`cancel` were implemented at the **library level (not stubbed)** so the supervisor
surfaces that followed consumed settled shapes; the supervisor *command surfaces*, deferred at the
time, have since landed — `perk workflow run list`/`cancel`/`retry` are registered
(`src/perk/cli/commands/workflow/run/__init__.py`; their translation pipeline is §"Runner-control
seam shape" below). The old `remote_not_driven` error was **retired** in favor of three honest
error types:
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

The dispatch record rides the existing `.perk/workflow/scratch/runs/<run_id>/dispatch.json` path
(`cache.run_scratch_dir`) — a path `perk init` already creates and `.gitignore` already excludes
(the single `/.perk/workflow/` entry). **No new
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
recovers those fields, and `Runner.discover` turns the
listing into `DiscoveredRun`s (smoke runs and foreign titles filtered out); the orchestration
lives in `src/perk/run/discovery.py`. Local dispatch JSON
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
- **Remote drives deliver `.agents/skills/` via the real skills-CLI sync** — the composite
  installs the `skills` CLI (`go install` from source; darwin-only release binaries) and
  `position_worktree` runs the canonical `sync_skills` gesture against the checkout's committed
  manifests. Fatal at both tiers (a failed install fails the job; a failed sync raises
  `skills_sync_failed` pre-spawn) — no skills, no drive; see `skill-bindings.md` for the full
  account, including why the local worktree *mirror* cannot work on the runner.
- **Worker-entry resolution is a three-candidate ladder:** `PERK_WORKER_ENTRY` (env) → self-repo
  `extension/workerMain.ts` → the consumer npm install. On the third rung the install lands under
  `.pi/npm/node_modules/@mgiles/perk`, and `_stage_consumer_entry` re-homes it as a staged
  full-package copy at `.pi/npm/perk-worker/`, spawning the staged `extension/workerMain.ts`
  (Node hard-refuses type-stripping `.ts` files under any `node_modules`). Verified anchor:
  `run_worker.py::resolve_worker_entry`'s `WorkerEntry.source` comment reads
  `"env" | "self" | "consumer-npm"`. **The `consumer-git` candidate** (the
  `.pi/git/<host>/<path>/extension/workerMain.ts` clone path) **was retired** once the npm install path
  superseded it — its `_git_clone_worker_entry` helper is gone (the `from perk.convergence import
  init` import in `run_worker.py` later returned for an unrelated reason: the positioning-time
  `init.sync_skills` skills delivery).

- **Resolver-candidate vs migration-helper have independent lifecycles.** Dropping the `consumer-git`
  *candidate* does **not** mean retiring the clone-path SSOT: `consumer_git_clone_root` + `GIT_PACKAGE`
  (now in `settings.py`) **stay**, because the doctor forward-migration `_remove_orphaned_git_clone`
  (`src/perk/convergence/doctor/fixes.py`) still `rmtree`s an orphaned `.pi/git/<host>/<path>`. **Rule: a
  resolver candidate for a retired path can go the moment a superseding path exists; the *cleanup
  migration* for already-deployed consumers outlives it** — don't conflate "stop probing X" with
  "delete the derivation of X's location." (See `init-doctor.md` for the migration seam.)

## Honest fiction vs. loud deferral

Consumer remote drive genuinely can't run end-to-end in CI yet (`.pi/npm` is gitignored and nothing in
the composite runs `pi` to trigger the extension load). The original posture (per "don't author
fiction") landed the cheap/correct/unit-testable pieces and made the genuinely-unbuildable consumer
worker-deps step a **loud `::error::` + `exit 1` deferral**, not a silently-broken `npm ci`.

**Update — the deferral has since been realized.** Once perk owned the `.pi/npm` install, the
`_WORKER_DEPS_CONSUMER` placeholder went from `echo "::error::…"; exit 1` to the real pinned
**two-spec** install `npm install @mgiles/perk@{__version__} @earendil-works/pi-coding-agent
--prefix .pi/npm --legacy-peer-deps` — the second spec is the B-pre-c fix: the package ships zero
runtime deps and `--legacy-peer-deps` skips peers, so without the SDK's real deps the worker's
import set stays open (anchor: `src/perk/run/workflow_artifacts.py::_WORKER_DEPS_CONSUMER`; `_NPM_NAME =
NPM_PACKAGE.removeprefix("npm:")` derives from the same settings SSOT). Self-repo keeps `npm ci`.
The path stayed labeled execution-untested until the 2026-07-06 consumer dogfood proved it live
(`docs/design/archive/remote-runner-consumer-dogfood.md`) — the durable rule stands: a realized-but-
unverified path must never be presented as proven.

**Grep ALL contracts mentions when reconciling.** Retiring the deferral needed a **third** §8.14 site
beyond the two obvious ones (the composite worker-deps bullet + the worker-entry ladder step) — the
`smoke-test` parenthetical ("the consumer worker-deps step is a loud … deferral"). A
`grep -n "consumer-git\|Node 2.4\|loud.*deferral\|\.pi/git"` across `contracts.md` surfaced it; the
deferral was even labelled inconsistently ("Node-2.4" vs "Node-2.2") across sites — version labels are
drift magnets (reinforces `doc-reconciliation.md`).

### Resolved: the remote worker loads `@mgiles/perk` via disk-layered settings

The e2e worker tier originally surfaced this as an open gap: `defaultCreateRuntime`'s in-memory
settings **ignored disk `.pi/settings.json` packages**, so a remote worker would have registered
zero extension tools. Resolved by layering disk settings
(`SettingsManager.create(worktree, throwawayAgentDir)` + `applyOverrides`) so the managed project
`packages` list resolves — the same package set as a warm session — backstopped by a post-bind
preflight: the stage's terminating tool must be registered, else a zero-turn
`failed`/`no_extension_tools` outcome (contracts.md §8.11). The live proofs have since landed on
both paths (the two dogfood records). Mechanics: `docs/learned/pi/headless-session-drive.md`.

## Consumer dogfood facts (fix delivery, probe outcomes, residual risks)

- **Consumer fix-delivery asymmetry.** In a consumer repo NO fix rides a consumer plan branch:
  worker code = the published npm tarball, the CLI = PyPI, the workflow/composite = the consumer's
  committed tree. Pre-release deviation classes, each a labeled hand-edit re-converged at the next
  release + `perk init`: template fixes → hand-apply to the committed `action.yml`/`perk-run.yml`;
  worker code → `npm install github:mattgiles/perk#plan-<N>`; Python CLI →
  `uv tool install git+https://github.com/mattgiles/perk@plan-<N>`. Committing worker code to the
  consumer's plan branch would flip entry resolution to `self` and destroy the proof.
- **A live probe confirms premises even when the predicted symptom never fires.** The first live
  defect can mask later ones: B-pre-c (zero runtime deps + `--legacy-peer-deps` ⇒ SDK never lands)
  was verified at the install layer (`added 1 package`), but its predicted `ERR_MODULE_NOT_FOUND`
  never fired because B8 died earlier in the same spawn. A confirm-or-refute plan arm should
  anticipate the third outcome: *fails-differently*.
- **Residual risks, documented not fixed:** (1) the fully-canonical published-registry consumer
  path stays unproven until a release ships both fixes — the scratch fixture
  `mattgiles/perk-consumer-dogfood` carries labeled deviations; the first post-release dispatch
  re-proves it; (2) the SDK spec is deliberately unpinned (evergreen posture — version skew
  unbounded by tests); (3) the staging copy is unit-tested against synthetic package layouts only;
  (4) the staged entry's non-fatal `MODULE_TYPELESS_PACKAGE_JSON` reparse warning — the
  `"type": "module"` fix deliberately deferred (it changes the in-session extension-loading
  surface).

## Relocating a workflow-shell step into the Python worker

Moving a workflow-shell step into the Python worker **breaks every pre-existing test that
invokes the entry function** — tests calling the worker entry in a non-git tmp cwd that was
previously inert start running real git. The working pattern: an autouse no-op stub fixture for
the drive-mechanics tests, **paired with one explicit orchestration-order test using a recording
stub** (branch positioning → worktree positioning → spawn). The pairing matters: an autouse stub
alone leaves the new wiring *unobserved* — nothing would notice if the entry stopped calling the
positioning step entirely. (The deploy-gap residual is already covered by the
workflow-template-fixes-go-live-only-after-merging rule above — cross-reference it, don't
restate.)

## `doctor --fix` re-converge pulls in unrelated drift

Regenerating committed self-repo artifacts via `perk doctor --fix` re-converges the **whole repo**,
so it can pull in **unrelated pre-existing drift** (a stray skill-manifest entry, a `.gitignore`
reorder). After a `--fix` re-converge, diff *every* touched file and `git checkout` drift outside the
plan's surface — `--fix` converges the whole repo, not just your target artifact. Cross-ref
`init-doctor.md`.

## Cross-references

- `src/perk/run/runner.py` — the `Runner` Protocol, value types, `GitHubActionsRunner`, `select_runner`
- `src/perk/run/run_worker.py` — the CI worker entrypoint + the three-candidate worker-entry ladder
- `src/perk/convergence/doctor/fixes.py` — `_remove_orphaned_git_clone` (the cleanup migration that
  outlives the retired `consumer-git` resolver candidate)
- `extension/workerMain.ts` — the worker entry the runner drives into
- `shared/contracts.md` §8.13 (Runner contract + dispatch record) / §8.14 (Actions runner artifact +
  CI worker entrypoint)
- `docs/learned/pi/headless-session-drive.md` — the drive the runner dispatches into
- `docs/learned/workflow/plan-ref-lifecycle.md` — the `cache.plan-ref` lifecycle + establish-before-consume
- `docs/learned/workflow/init-doctor.md` — the `doctor --fix` re-converge discipline; also the
  retire-an-orphaned-lifecycle recipe + the `_MIGRATIONS` filesystem-rmtree seam
- `docs/learned/toolchain/worktree-node-modules.md` — worktree SDK resolution gotchas
