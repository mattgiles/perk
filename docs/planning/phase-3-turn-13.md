# Phase 3 · Turn 13 — Mirror `.agents/skills/` into worktrees at launch

Plan: github #467.

## Problem

A perk session launched in a worktree (`stage.worktree` `create`/`reuse` — `implement`, `submit`,
`address`, `land`, `learn`) saw **zero skills**: pi tried to load
`.worktrees/plan-<N>/.agents/skills/perk-implement/SKILL.md` and failed with ENOENT. `.agents/skills/`
is gitignored, so `git worktree add` never checks it out, and pi discovers skills only up to the
worktree's own git root (never the main repo).

## Decisions (settled with the user, per plan)

1. **Per-skill symlinks** mirroring each entry of `repo_root/.agents/skills/*` into
   `<worktree>/.agents/skills/` — replicates the exact structure pi already discovers and delivers
   ALL skills (perk + borrowed). Not a single top-level dir symlink; not `skills update --sync`
   (network re-clone).
2. **Local cold-launch only** (`launch.launch_stage`). The remote-CI worker positions into
   `repo_root` itself (worktree == repo_root), so mirroring would be a self-referential no-op; the CI
   setup action owns delivery there.
3. **Loud-but-non-fatal** when `repo_root/.agents/skills/` is missing/empty: warn via `user_output`
   and continue. Doctor's fail-level `skills-delivery` check owns the hard gate.

## What got built

- `perk/run/launch.py::materialize_skills(repo_root, worktree)` — new positioning helper near
  `materialize_plan_body`. Skips a missing/empty source set (warns), mirrors each source skill dir as
  a per-skill symlink to `entry.resolve()` (single-hop to the real cache dir). Idempotent: an
  already-correct symlink is left untouched, a stale symlink is repointed, a real (non-symlink) entry
  is never clobbered.
- Wired into `launch_stage`'s `if stage.worktree != "none":` block, immediately after
  `materialize_plan_body` — after the `dry_run` early return, before `os.chdir`/`os.execvpe`.
- `shared/contracts.md` worktree-positioning paragraph amended to document the skill mirror.
- `tests/test_launch.py` — four new tests (see below).

## Cross-plane

- Python cold-door only. No TS change: `extension/substrate/bindingDelivery.ts` already reads
  `.agents/skills` from the worktree cwd and resolves automatically once mirrored. `shared/contracts.md`
  amended in the same turn.

## Out of scope / non-goals

- No change to `run_worker.position_worktree` (remote CI: worktree == repo_root).
- No new doctor check (existing `skills-delivery` check is the hard gate).
- No `.claude/skills` mirroring (Pi reads `.agents/skills`).

## Verification

- `just test` / `just ci` green.
- Manual: launch `perk implement`, confirm no `[skill] perk-implement` ENOENT and resolving per-skill
  symlinks in `<wt>/.agents/skills/`.
