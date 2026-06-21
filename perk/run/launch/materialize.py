"""Worktree materialization helpers for the cold-door launch (Node 2.3 module->package split).

The canonical materialization paths relocated verbatim from the pre-split ``perk/run/launch.py``:
the ``[worktree] setup`` runner (:func:`run_worktree_setup`), the plan-body cache
(:func:`materialize_plan_body`, also consumed by ``run_worker.position_worktree``), and the
per-skill symlink mirror (:func:`materialize_skills`). ``_WORKTREE_SETUP_TIMEOUT_S`` (the
per-command wall-clock cap) travels with :func:`run_worktree_setup` and is re-exported by the
package facade so ``launch._WORKTREE_SETUP_TIMEOUT_S`` resolves verbatim.
"""

import subprocess
from pathlib import Path
from typing import Any

from perk.backends import issues
from perk.backends.issue_backend import IssueBackendError
from perk.cli.ensure import UserFacingCliError
from perk.github import GitHubError
from perk.state import cache
from perk.substrate.output import user_output

# Per-command wall-clock cap for `[worktree] setup` commands (10 minutes) — `uv sync` / `npm ci`
# can be slow on a cold cache, but a hung command must not wedge the launch forever.
_WORKTREE_SETUP_TIMEOUT_S = 600


def run_worktree_setup(worktree: Path, commands: list[str]) -> None:
    """Run the project's `[worktree] setup` commands, in order, inside a freshly created worktree.

    Each command runs via ``bash -lc <command>`` (the same mechanism the CI executor uses) with
    ``cwd`` = the worktree and **inherited** stdio so progress streams live. Each command has a
    ``_WORKTREE_SETUP_TIMEOUT_S`` (10-minute) wall-clock cap.

    Abort-on-failure: a non-zero exit, a timeout, or a missing ``bash`` raises a
    ``UserFacingCliError`` (``error_type="worktree_setup_failed"``) and stops before any later
    command runs — the caller aborts the launch (the worktree is left in place for a fixed re-run).
    A no-op when ``commands`` is empty (no subprocess).

    The single canonical setup-execution path; the cold door and ``perk worktree create`` both
    consume it (mirrors ``materialize_plan_body``).
    """
    for command in commands:
        user_output(f"  $ {command}")
        try:
            result = subprocess.run(
                ["bash", "-lc", command],
                cwd=worktree,
                check=False,
                timeout=_WORKTREE_SETUP_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired as exc:
            raise UserFacingCliError(
                f"worktree setup command timed out after {_WORKTREE_SETUP_TIMEOUT_S}s: {command}",
                error_type="worktree_setup_failed",
            ) from exc
        except FileNotFoundError as exc:
            raise UserFacingCliError(
                f"worktree setup needs `bash` on PATH to run: {command}\n"
                "Install bash, or remove the [worktree] setup commands.",
                error_type="worktree_setup_failed",
            ) from exc
        if result.returncode != 0:
            raise UserFacingCliError(
                f"worktree setup command failed: {command} (exit {result.returncode})",
                error_type="worktree_setup_failed",
            )


def materialize_plan_body(repo_root: Path, worktree: Path, plan_ref: dict[str, Any] | None) -> None:
    """Fetch the plan body from its canonical source and cache it into the worktree (P2.T2c).

    Public: ``run_worker.position_worktree`` is the second consumer (the one canonical path for
    plan-body materialization, §1.10).

    Best-effort: a missing/empty id or any backend failure is reported but never blocks the
    launch (checkpoints simply stay inert). Honest, not silent. Backend-agnostic: the resolved
    issue backend owns the id shape (GitHub numeric, Linear ``ENG-123``).
    """
    if plan_ref is None:
        return
    pr_id = str(plan_ref.get("pr_id", "")).strip()
    if not pr_id:
        return
    try:
        body = issues.resolve_issue_backend(repo_root).get_plan_body(issue_id=pr_id)
    except (GitHubError, IssueBackendError) as exc:
        user_output(f"  (checkpoints: could not fetch plan #{pr_id} body — {exc})")
        return
    if body:
        cache.write_plan_body(worktree, body)


def materialize_skills(repo_root: Path, worktree: Path) -> None:
    """Mirror repo_root's `.agents/skills/*` into the worktree as per-skill symlinks.

    Linked worktrees never carry the gitignored `.agents/skills/` tree, and pi discovers skills
    only up to the worktree's own git root (never the main repo), so without this a worktree
    session sees zero skills (ENOENT on `perk-implement/SKILL.md`). Replicates the exact per-skill
    structure pi already discovers in repo_root, delivering ALL skills (perk + borrowed).

    Best-effort + loud-but-non-fatal: a missing/empty source set (perk init never ran / skills sync
    failed) warns and continues — doctor's fail-level `skills-delivery` check owns the hard gate.
    Idempotent (D4 resume): an already-correct symlink is left untouched; a stale symlink is
    repointed; a real (non-symlink) entry already present is left alone (never clobbered).
    """
    src = repo_root / ".agents" / "skills"
    if not src.is_dir():
        user_output(
            "  (skills: repo .agents/skills/ missing — run `perk init`; "
            "this session may have no skills)"
        )
        return
    sources = [entry for entry in sorted(src.iterdir()) if entry.is_dir()]
    if not sources:
        user_output("  (skills: repo .agents/skills/ is empty — run `perk init`)")
        return
    dst = worktree / ".agents" / "skills"
    dst.mkdir(parents=True, exist_ok=True)
    linked = 0
    for entry in sources:
        target = entry.resolve()  # single-hop symlink to the real skill dir (cache or self)
        link = dst / entry.name
        if link.is_symlink():
            if link.readlink() == target:
                continue
            link.unlink()
        elif link.exists():
            continue  # a real dir/file already there — never clobber
        link.symlink_to(target, target_is_directory=True)
        linked += 1
    if linked:
        user_output(f"  (skills: mirrored {linked} skill(s) into the worktree)")
