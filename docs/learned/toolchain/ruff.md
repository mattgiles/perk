---
title: ruff check vs ruff format — CI vs pre-commit hook
read_when: You are debugging a CI-green / commit-rejected discrepancy, or a commit appears to have not advanced after a pre-commit hook ran.
---

# `ruff check` vs `ruff format`

## The split

- **`just ci`** runs `ruff check` only — lint rules including E501 (line length). This is what the
  CI gate checks.
- **The pre-commit hook** runs `ruff-format` (style normalization — wrapping, spacing, etc.).

These are **independent checks**. CI can be fully green while the pre-commit hook would still
reformat files.

## The silent-failure trap: hook reformats but commit does NOT advance

When `ruff-format` reformats files on commit, it **aborts the commit** and leaves the reformatted
files **unstaged**. The commit is not created. This is easy to miss if you only check the exit code
or assume a message means success.

Recovery:
1. `git add -A` — stage the reformatted files.
2. Re-commit with the same message.
3. `git log` — verify the commit actually advanced (new hash at HEAD).

## Summary

| Check | Run by | Catches |
|---|---|---|
| `ruff check` | `just ci` | Lint rules (E501, etc.) |
| `ruff format` | Pre-commit hook | Style normalization |

Always verify `git log` advanced after a commit if a pre-commit hook is active.
