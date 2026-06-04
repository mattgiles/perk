---
title: init/doctor division and gitignore untrack pattern
read_when: You are adding a new transient file, fixing a tracked-but-should-be-ignored file, writing a doctor migration, or extending perk init's managed gitignore block.
---

# `init` / `doctor` division

## The split

- **`perk init` converges forward**: desired state, idempotent, never migrations. Maps to
  `perk/init.py` (`GITIGNORE_BODY`, `converge()`).
- **`perk doctor --fix` repairs legacy oddities**: one-off fixes for things `init` can't undo or
  that stem from historical inconsistencies. Maps to `perk/doctor.py` (`_MIGRATIONS`).

Keep `init` a clean forward path — never a pile of version branches. New desired state goes into
`init`'s `converge()`; one-off/legacy repairs go into `doctor`'s `_MIGRATIONS`.

## Gitignore untrack pattern

A gitignore rule is **inert for already-tracked files** — `git check-ignore` even reports a tracked
path as "not ignored" (confusing). Adding the rule to `.gitignore` without untracking the file
leaves it churning on every change.

The proper two-plane fix:

1. **`init`** — add the entry to `GITIGNORE_BODY` so it lives *inside* the managed block (init owns
   all managed gitignore entries; never hand-add outside the `# BEGIN/END perk managed` block).
2. **`doctor --fix`** — run `git rm --cached <file>` (kept on disk) and strip any stray ungrouped
   line. `is_tracked` / `rm_cached` helpers live in `perk/git.py`.

**Generalizable rule:** any file materialized into `.pi/workflow/` is transient and must be added
to the managed gitignore block in `init.py` (alongside `plan-ref.json`, `handoff/`, `scratch/`,
`markers/`).

## Doctor migration idempotency rule

`_MIGRATIONS` run **unconditionally on every `--fix`** (not gated on a failing check), so each
migration must be **idempotent** — it must return `[]` once converged. Failing idempotency breaks
the `again.fixed == []` idempotency tests.

## Cross-references

- `perk/init.py` — `GITIGNORE_BODY`, `converge()`
- `perk/doctor.py` — `_MIGRATIONS`
- `perk/git.py` — `is_tracked`, `rm_cached`
