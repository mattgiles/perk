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

3. **Handle a failure.** If any setup command exits non-zero (or times out, or `bash` is missing),
   perk **aborts the launch** before starting `pi` and reports the failing command. The worktree is
   left in place — fix the problem, then re-run the same stage: the existing worktree is reused
   (idempotent) and setup runs again.

4. **Override per-user (optional).** `[worktree] setup` is overlay-aware: a `local.toml`
   `[worktree] setup` array **replaces** the committed one wholesale (e.g. to point at a personal
   absolute path). It is not merged element-by-element.

## Security note

The setup hook runs the project's **committed** commands automatically when you run a perk stage in
the repo — there is no separate trust gate (the same boundary as `[compaction]`/`[issues]`, plus the
cold door's `pi --approve` for the run). **Do not run perk stages in untrusted clones.**

---

← Back to the [how-to router](index.md).
