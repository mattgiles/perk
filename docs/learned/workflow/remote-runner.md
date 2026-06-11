---
title: The remote-runner dispatch + CI execution seam
read_when: You are working on `perk/runner.py` / `perk/run_worker.py`, the `perk-run.yml` workflow + `perk-remote-setup` composite action, the remote `--remote` dispatch path, the verify-by-discovery poll, or the worker-entry resolver.
---

# The remote-runner dispatch + CI execution seam

perk can dispatch a stage drive to a remote runner (today: GitHub Actions) instead of running it on
the local worktree. The seam spans Python (`perk/runner.py` dispatch + `perk/run_worker.py` CI
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

`perk/runner.py` defines a runner-agnostic `Runner` **Protocol** + value types
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
2. Read the local dispatch record from `scratch/runs/<run_id>/dispatch.json`.
3. Reconstruct the `RunHandle` (repopulating the GHA numeric run reference if applicable).
4. Dispatch the action to the resolved runner instance via `select_runner(record["runner"])`.

### Rerun reuse

When retrying/rerunning a remote execution, the supervisor reuses the existing GHA run ID by invoking `gh run rerun [--failed]` against the runner reference. It does not generate a new local ULID or mutate local dispatch records, ensuring history and tracking remain linked to the single canonical dispatch record.

## Fail-soft orchestrators & subprocess test trap

While event-stream reporting components are called unguarded, their internal reporting logic must be fully guarded (`try/except Exception: log + swallow`) to ensure failures in the telemetry/reporting layer never crash the primary execution loop.

**Subprocess Monkeypatching Test Trap:** When writing unit tests for these orchestrators, be extremely careful with subprocess capturing-fakes in parent test suites. Stub the reporting collaborator directly at its module-function seam (e.g., mocking the high-level python function that interfaces with `gh`) rather than letting the code make real or mock-subprocess shell out. Otherwise, internal `gh` calls can bypass or clobber the parent test suite's capture-fakes, resulting in leaky and brittle test runs.

## Local records truth with fail-soft overlays

Local dispatch JSON files (under `scratch/runs/<run_id>/dispatch.json`) are the absolute source of truth for supervisor read commands (such as `run list`). Any external calls to GHA, PR, or issue APIs are treated purely as best-effort overlays. Wrap all external API fetches in fail-soft `try` blocks that log warnings but never raise exceptions or alter command exit codes when network or API limits are hit.

## CI execution specifics (Node 2.2)

- **Fresh-runner git identity.** The headless `implement` drive commits via `bash` before `submit`
  pushes; `ubuntu-latest` has no `user.name`/`user.email` and perk's git layer never sets one. The
  composite setup must `git config --global` a `perk[bot]` identity — **`--global`** because it runs
  *before* the plan-branch checkout (a repo-local config against an unfinalized tree is fragile).
- **Auth model (a stated decision, recorded in `§8.14`).** The runner checks out + pushes with
  `PERK_GH_PAT` (a PAT), **not** `github.token` — only PAT-pushed commits trigger downstream CI;
  `GITHUB_TOKEN`-pushed commits don't.
- **Worker-entry resolution is a four-candidate ladder:** `PERK_WORKER_ENTRY` (env) → self-repo
  `extension/workerMain.ts` → consumer git-package clone
  (`.pi/git/<host>/<path>/extension/workerMain.ts`, `consumer-git`) → npm install
  (`.pi/npm/node_modules/@perk/pi/...`, `consumer-npm`). The `consumer-git` path is **derived from
  `GIT_PACKAGE`** (split on `/` after stripping `git:`) — never hardcoded segments, so a package-URL
  change can't silently desync the resolver. Importing `GIT_PACKAGE` into `run_worker` is cycle-free
  (`perk.init` does not import `perk.run_worker`).

## Honest fiction vs. loud deferral

Consumer remote drive genuinely can't run end-to-end in CI yet (`.pi/git` + `.pi/npm` are gitignored
and nothing in the composite runs `pi` to trigger pi's git-package `npm install`). Per "don't author
fiction": land the cheap/correct/unit-testable pieces now (the resolver candidate; the version-pinned
`git+https@v{__version__}` install mirroring `init._desired_skills_manifest`) but make the
genuinely-unbuildable consumer worker-deps step a **loud `::error::` + `exit 1` deferral**, not a
silently-broken `npm ci`. Self-repo keeps `npm ci`.

### Open follow-up: does a real remote launch load `@perk/pi` at all?

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

- `perk/runner.py` — the `Runner` Protocol, value types, `GitHubActionsRunner`, `select_runner`
- `perk/run_worker.py` — the CI worker entrypoint + the four-candidate worker-entry ladder
- `extension/workerMain.ts` — the worker entry the runner drives into
- `shared/contracts.md` §8.13 (Runner contract + dispatch record) / §8.14 (Actions runner artifact +
  CI worker entrypoint)
- `docs/learned/pi/headless-session-drive.md` — the drive the runner dispatches into
- `docs/learned/workflow/plan-ref-lifecycle.md` — the `cache.plan-ref` lifecycle + establish-before-consume
- `docs/learned/workflow/init-doctor.md` — the `doctor --fix` re-converge discipline
- `docs/learned/toolchain/worktree-node-modules.md` — worktree SDK resolution gotchas
