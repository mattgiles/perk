# Phase 3 · Turn 10 — Skip pi's project-trust prompt on worktree launches

Plan: GitHub #209.

## Problem

Recent pi releases prompt for **project trust** on interactive startup for any cwd with trust inputs
(`.pi/`, `AGENTS.md`, `.agents/skills`) and no saved decision in `~/.pi/agent/trust.json`. Trust is
keyed per canonical cwd. perk launches each worktree stage by `chdir`-ing into a freshly-created
`plan-<pr_id>` worktree (which carries the committed managed `.pi/` + `AGENTS.md`) and `execvpe`-ing
`pi`. Each worktree path is brand-new, so pi re-prompts for trust on every `perk implement` (and
every other worktree-stage launch).

## Decisions

1. **Scope.** Inject `--approve` only for worktree stages, gated by `stage.worktree != "none"`.
   `worktree: none` stages (`objective-author/save/plan`, `plan`, `save`) run in `repo_root` (trusted
   manually once) and are left untouched.
2. **Override.** Injection is unconditional for worktree stages but inserted **before** `pi_args`, so
   a user-supplied `--no-approve`/`-na` wins via pi's last-wins trust parsing. No config flag / env.
3. **Honest preview.** The argv is built once before the `dry_run` branch, so the dry-run JSON `argv`
   includes `--approve` for worktree stages too — faithful to the real exec.

## Prior art (pi distribution evidence)

- `dist/cli/args.js`: `--approve`/`-a` → `projectTrustOverride = true`; `--no-approve`/`-na` →
  `false`; assigned in the arg loop (last-wins).
- `dist/main.js`: when the override is `true`, `shouldResolveProjectTrust` is `false` and
  `projectTrusted` resolves to `true` regardless of `appMode` — suppresses the interactive prompt
  for this run only (no `trust.json` write).

## Implementation

`perk/launch.py` `launch_stage`: the single argv construction line now prepends
`trust_args = ["--approve"] if stage.worktree != "none" else []`. No other production changes;
`_drive_remote_target`, `perk/run_worker.py`, and `extension/worker.ts` are untouched (the Node
worker never goes through pi-CLI trust resolution).

## Tests (`tests/test_launch.py`)

- Updated `test_implement_dry_run_json_carries_worktree_and_plan_ref` for the new 3-element argv
  (`--approve` at index 1, prompt last).
- Added `test_worktree_stage_auto_approves_and_respects_user_no_approve`: `--approve` precedes a
  user `--no-approve` on `implement`; `--approve` absent on the `worktree: none` `plan` stage.

## Out of scope

- No `shared/contracts.md` amendment (local launch mechanics only; cross-plane Node-worker contract
  unchanged). No `perk init` / `perk doctor` change.

## Outcomes

- Implemented exactly as planned: `trust_args` gate in `launch_stage`, the two test changes, this
  turn doc. `just ci` green.
