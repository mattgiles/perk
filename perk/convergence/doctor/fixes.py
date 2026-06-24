"""The ``--fix`` repair layer: config re-seed, Linear labels, and the migration seam."""

import shutil
from collections.abc import Callable
from pathlib import Path

from perk.backends import linear
from perk.backends.issue_backend import IssueBackendError
from perk.backends.linear import client as linear_client
from perk.convergence import init
from perk.convergence.doctor.data import Check
from perk.convergence.doctor.linear_checks import _linear_selected
from perk.substrate import git
from perk.substrate.config import load_committed_issues_team

# --- fixes ----------------------------------------------------------------------------------


def _strip_ungrouped_ignore_line(text: str, line: str) -> str:
    """Drop standalone ``line`` occurrences that sit OUTSIDE the perk-managed block.

    `init` now owns the line *inside* the managed block; an identical hand-added line outside it
    is a stray duplicate. Lines within `# BEGIN/END perk managed` are preserved untouched.
    """
    out: list[str] = []
    inside = False
    for raw in text.splitlines(keepends=True):
        stripped = raw.strip()
        if stripped == init.GITIGNORE_BEGIN:
            inside = True
        elif stripped == init.GITIGNORE_END:
            inside = False
        elif not inside and stripped == line:
            continue
        out.append(raw)
    return "".join(out)


def _untrack_materialized_plan_cache(root: Path) -> tuple[list[str], list[str]]:
    """Repair the legacy tracked `cache.plan` body + its stray ungrouped `.gitignore` line.

    `.pi/workflow/plan.md` is a transient materialized cache (contracts.md §8.1) — it must be
    gitignored (now in the managed block) and never tracked. Early repos committed it and
    hand-added an ungrouped `/.pi/workflow/plan.md` ignore line *outside* the managed block.
    This forward-only repair removes the stray line and `git rm --cached`s the file; it is a
    no-op (returns `([], [])`) once converged, so `--fix` stays idempotent. Returns
    ``(changes, errors)`` — a failed untrack is reported, never swallowed.
    """
    changes: list[str] = []
    errors: list[str] = []
    rel = ".pi/workflow/plan.md"
    gitignore = root / ".gitignore"
    if gitignore.is_file():
        text = gitignore.read_text(encoding="utf-8")
        pruned = _strip_ungrouped_ignore_line(text, f"/{rel}")
        if pruned != text:
            gitignore.write_text(pruned, encoding="utf-8")
            changes.append(".gitignore: removed stray /.pi/workflow/plan.md (now managed)")
    if git.is_tracked(root, rel):
        try:
            git.rm_cached(root, rel)
            changes.append(".pi/workflow/plan.md: untracked (transient cache.plan body)")
        except git.GitError as exc:
            errors.append(f"{rel}: untrack failed (git rm --cached): {exc}")
    return changes, errors


def _remove_orphaned_git_clone(root: Path) -> tuple[list[str], list[str]]:
    """Migrate a former git-clone consumer forward by removing the orphaned on-disk clone.

    The `npm:@mgiles/perk` install path superseded pi's `git:`-clone extension lifecycle, leaving a
    consumer that was previously on the clone with an orphaned `.pi/git/<host>/<path>` tree. This
    forward-only repair `rmtree`s it once (filesystem-only, gitignored path — no network); it is a
    no-op (returns `([], [])`) once the clone is absent, so `--fix` stays idempotent. Returns
    ``(changes, errors)`` — a failed removal is reported, never swallowed.
    """
    changes: list[str] = []
    errors: list[str] = []
    clone = init.consumer_git_clone_root(root)
    if clone.is_dir():
        rel = clone.relative_to(root)
        try:
            shutil.rmtree(clone)
            changes.append(
                f"{rel}: removed orphaned perk clone (migrated to @mgiles/perk npm install)"
            )
        except OSError as exc:
            errors.append(f"{rel}: orphaned-clone removal failed (rmtree): {exc}")
    return changes, errors


# The legacy/one-off migration seam.
# Forward-only repairs for oddities `init` does not undo (e.g. a previously-tracked transient
# cache file). Each must be idempotent: a no-op (`([], [])`) once the repo is converged; each
# returns `(changes, errors)` so failures land loudly on `fix_errors`.
_MIGRATIONS: tuple[Callable[[Path], tuple[list[str], list[str]]], ...] = (
    _untrack_materialized_plan_cache,
    _remove_orphaned_git_clone,
)


def _fix_config(root: Path) -> list[str]:
    """Re-seed *missing* config files only (never overwrite a present/edited one)."""
    changes: list[str] = []
    init.converge_config(root, changes, force=False, interactive=False)
    return changes


def _fix_linear_labels(root: Path) -> tuple[list[str], list[str]]:
    """The verify-gated `--fix` label repair: ensure the five perk labels in Linear.

    Only acts when linear is selected AND key + team are available (otherwise the warn-level
    `linear` group already carries the remediation — nothing repairable here). Idempotent
    (lookup-first → no created labels once converged), satisfying the doctor idempotency rule.
    Returns ``(fixed, errors)``.
    """
    if not _linear_selected(root):
        return [], []
    team = load_committed_issues_team(root)
    if team is None:
        return [], []
    try:
        client = linear_client.client_from_env()
    except IssueBackendError:
        return [], []
    readiness = linear.check_readiness(client, team_key=team, ensure_labels=True)
    fixed = [f"Linear: created label {name}" for name in readiness.created_labels]
    errors = [f"Linear: label ensure failed: {readiness.error}"] if readiness.error else []
    return fixed, errors


def _apply_fixes(root: Path, self_repo: bool, checks: list[Check]) -> tuple[list[str], list[str]]:
    fixed: list[str] = []
    errors: list[str] = []
    mc_by_name = {mc.name: mc for mc in init.managed_convergences(root, self_repo)}
    for check in [c for c in checks if c.status == "fail"]:
        if check.name in mc_by_name:
            fixed.extend(mc_by_name[check.name].converge(True))
        elif check.name == "config":
            fixed.extend(_fix_config(root))
        elif check.name == "extension-install":
            # Install/reinstall the pinned @mgiles/perk under .pi/npm/ (the perk-owned install)
            # under a cross-process lock; best-effort + non-fatal. Only triggers when the
            # verify-gated check flagged `fail` (absent/mismatch) — a real change, so a message
            # is returned.
            message = init.materialize_extension_install(root, self_repo=self_repo)
            if message is not None:
                fixed.append(message)
    for migration in _MIGRATIONS:
        changes, migration_errors = migration(root)
        fixed.extend(changes)
        errors.extend(migration_errors)
    return fixed, errors
