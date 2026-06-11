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

## `RUF100` fires on a `# noqa` for a non-enabled rule

A `# noqa: N801` on a class name with an underscore (`ReviewComment_Inline`) drew a **`RUF100`**
(unused-noqa) — because `N801` isn't in the enabled rule set, the noqa suppresses nothing and ruff
flags it as unused. **Don't paper over a lint with a noqa for a rule the config doesn't run**; pick a
clean name instead (e.g. rename `ReviewComment_Inline` → `InlineReviewComment`).

Similarly, pre-emptively adding `# noqa` to a broad `except Exception:` block before any specific lint
rules are enabled/triggered for it will cause Ruff to raise a `RUF100` (unused noqa) error, because the
block is not actively violating any active lint rules.

And tie the multi-line-collapse case to the format-on-commit trap above: the pre-commit `ruff-format`
hook reformats (e.g. collapses a multi-line call) on commit, and `just lint` / `ruff check` won't
catch what `ruff format` *changes* — expect a first-commit "files modified", then `git add -A` +
re-commit.

## Template string E501 (line length) rule

Embedded multiline string templates (such as inline workflow YAML blocks defined inside Python files)
are still subject to standard lint checks. If any line inside an embedded multiline string exceeds
the 100-column limit, Ruff will raise an `E501` lint error. You must shorten or wrap lines within
these multiline templates to stay under the column limit.

## `ruff SIM105`: replace `try/except: pass` with `contextlib.suppress`

Ruff rule `SIM105` flags standard `try: ... except Exception: pass` (or `except baseclass: pass`)
patterns. Instead of a manual pass block, use `contextlib.suppress(...)` to cleanly and idiomatically
ignore exceptions. It reduces boilerplate and makes the exception suppression intent explicit.

## Preview-rule enablement drags cross-bucket fixes forward

Enabling `preview = true` + `explicit-preview-rules = true` with newly selected rules surfaces
**repo-wide** diagnostics, not just in the enabling change's module list. When a backlog assigns
rule-*enablement* to one node and rule-*fixes* to another, enablement forcibly pulls those fixes
forward — budget for mechanical cross-bucket collateral in the enabling node, and reconcile the
donor node's description afterward. The same policy applies on a later **ruff version bump**: it
may surface new diagnostics on the selected preview rules — treat them as mechanical collateral.

Small addendum: after manual edits, run `ruff check --fix` + format rather than chasing orphaned
imports by hand — F401 auto-removal handles them.

## Summary

| Check | Run by | Catches |
|---|---|---|
| `ruff check` | `just ci` | Lint rules (E501, etc.) |
| `ruff format` | Pre-commit hook | Style normalization |

Always verify `git log` advanced after a commit if a pre-commit hook is active.
