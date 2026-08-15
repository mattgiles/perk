---
title: "Workflow and CI"
description: "The [worktree], [workflow], [ci], and [[ci.checks]] keys that position work and verify changes."
sidebar:
  order: 3032
---

# Workflow and CI

These tables position work, add project-specific plan guidance, select the default target branch,
and define the checks that verify changes.

## `[worktree]`

Where `perk worktree create` and the cold-door stage launchers place worktrees.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `root` | string | `.worktrees` | A relative path resolves against the repo root; an absolute path is used as-is. |
| `setup` | array of strings | _(none)_ | Shell commands run via `bash -lc`, in order, inside each **newly materialized** worktree — freshly created *or* restored from the remote plan branch — before `pi` starts (`cwd` = the worktree). A non-zero exit, timeout, or missing `bash` **aborts the launch** (the worktree is left for a fixed re-run, and the pending-setup marker makes the re-run retry the hook — a failed setup is never silently skipped). Command output is captured and shown only on failure. Skipped on valid local resume/reuse, dry-runs (which preview the planned commands), and the remote runner. Overlay-aware — a `local.toml` `[worktree] setup` array replaces this one wholesale. |

```toml
[worktree]
root = ".worktrees"
setup = ["uv sync"]
```

## `[workflow]`

Project-supplied plan-authoring guidance and the default target branch.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `plan_authoring` | string | _(none)_ | Appended into the plan-authoring context injection inside `plan` sessions. Gotcha: a bare skill name in addendum prose is only model-reachable when that skill is model-invocable; a skill hidden via `disable-model-invocation: true` must be referenced with its read path (`.agents/skills/<name>/SKILL.md`). |
| `base` | string | _(GitHub default branch)_ | The default target branch plans and objectives base off and target. Overrides the repo's GitHub default; an objective's own `--base` wins for its node plans. Pinned at save time — see [Target a non-default base branch](../../how-to/target-a-non-default-base-branch.md). |

```toml
[workflow]
plan_authoring = "Prefer the smallest diff that satisfies the acceptance criteria."
base = "develop"
```

## `[ci]`

How work is verified — and whether it is trusted. The `trusted` policy key sits directly above
the `[[ci.checks]]` commands it green-lights.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `trusted` | bool | _(unset ⇒ untrusted)_ | `true` (a **native boolean**) marks the `[[ci.checks]]` below trusted — they run without a per-session confirm (including headless). A quoted `"true"` does **not** grant trust. |

```toml
[ci]
trusted = true
```

### `[[ci.checks]]`

An array-of-tables: each `[[ci.checks]]` row declares one check. The in-session CI executor
consumes the rows: warm `/ci` gives the one-line overall summary, while the `run_ci` tool returns
the detailed per-check report. `/ready` does not run checks; it only marks the draft PR ready for
review, so run the checks first.

Checks run **concurrently**. Declared order governs the detailed **report** order, not execution
order. Each row must therefore be independently runnable; when sequencing matters, put the
ordered steps inside one row's `command` (for example, `"build && test"`). `/ci` and the
`run_ci` `check` argument accept one name or a comma-separated list (for example,
`/ci lint,test`) to re-verify a subset in one call.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `name` | string | _(required)_ | The check name, selected by `/ci <name>`. |
| `command` | string (shell command) | _(required)_ | The command to run. |
| `glob` | string | _(unset)_ | A comma-separated pattern string such as `"*.ts,*.tsx"`. When set, the check is **skipped** on the run-all path if no changed file against the repo's trunk matches; unset means the check always runs. |

**Change-scoped gating.** A check with a `glob` runs only when at least one changed file
(merge-base against the detected trunk, plus untracked files) matches one of its patterns. A
pattern with no `/` matches a file's basename at any depth, so `*.py` gates any Python file;
`**` crosses directories and `*` matches one path segment. Gating applies only when running
**all** checks: an explicit `/ci <name>` always runs that check. Any git error **fails open** and
runs all checks, so uncertainty never produces a false success.

```toml
[[ci.checks]]
name = "lint"
command = "just lint"
glob = "*.py,*.ts"

[[ci.checks]]
name = "test"
command = "just test"
```

## Related

- **Do:** [How to target a non-default base branch](../../how-to/target-a-non-default-base-branch.md) — set and verify the target branch.
- **Do:** [How to configure and verify CI checks](../../how-to/configure-and-verify-ci-checks.md) — add trusted checks and run the gate.
- **Do:** [How to run a worktree setup hook](../../how-to/run-a-worktree-setup-hook.md) — prepare newly materialized worktrees.
