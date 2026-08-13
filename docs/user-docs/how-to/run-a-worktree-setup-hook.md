---
title: "How to run a worktree setup hook"
description: "Declare worktree setup commands once so every freshly created perk worktree starts with a ready environment."
sidebar:
  order: 2120
sidebarGroup: "Core workflow"
---

# How to run a worktree setup hook

Declare `[worktree] setup` commands once and have every **freshly created** perk worktree run them —
in order, before `pi` starts — so a new session begins with a ready environment (dependencies
installed, codegen done, etc.).

**Prerequisite:** a `.perk/config.toml` (run [`perk init`](../reference/cli.md#perk-init) once if you
have not). The `[worktree]` table is written there by default.

## Steps

1. **Declare the commands.** Add a `setup` array to the `[worktree]` table in `.perk/config.toml` — an
   ordered list of shell command lines:

   ```toml
   [worktree]
   root = ".worktrees"
   setup = ["uv sync", "npm ci"]
   ```

   A single command is a one-element array. Each entry runs via `bash -lc <command>` with the new
   worktree as its working directory. Its output is **captured** — the launch narration shows each
   command as a `$ …` sub-bullet — and the full output is printed only if the command fails.

2. **Trigger it.** The hook fires whenever perk **freshly creates** a worktree:
   - a cold-door stage launch (e.g. `perk implement`) that creates the `plan-<id>` worktree, and
   - a manual `perk worktree create NAME`.

   It is **skipped** on idempotent resume/reuse (the worktree already exists), on `--dry-run` (which
   only previews the planned commands), and on the remote runner (CI environment setup belongs to
   the GitHub Actions composite action).

3. **Handle a failure.** If any setup command exits non-zero, exceeds its 10-minute cap, or
   cannot start because `bash` is missing, perk **aborts the launch** before starting `pi` and
   reports the failing command. The worktree is left in place. A normal retry reuses that
   worktree and skips the hook, so fix the problem and run the failed and not-yet-run setup
   commands yourself in the worktree before retrying the stage.

4. **Override per-user (optional).** `[worktree] setup` is overlay-aware: a `local.toml`
   `[worktree] setup` array **replaces** the committed one wholesale (e.g. to point at a personal
   absolute path). It is not merged element-by-element.

## Security note

The setup hook runs the project's **committed** commands automatically when you run a perk stage in
the repo — there is no separate trust gate (the same boundary as `[compaction]`/`[issues]`, plus the
cold door's `pi --approve` for the run). **Do not run perk stages in untrusted clones.**

## Related

- **Do:** [How to drive a change through the full spine](drive-the-full-spine.md) — the stage
  launches that cut the fresh worktrees this hook prepares.
- **Look up:** [Configuration files](../reference/configuration.md) — the `[worktree]` keys and
  local-overlay replacement semantics.
- **Understand:** [How perk thinks](../explanation/how-perk-thinks.md) — why every stage starts in
  a fresh, isolated worktree.
