"""Worktree materialization helpers for the cold-door launch.

The canonical materialization paths:
the ``[worktree] setup`` runner (:func:`run_worktree_setup`), the plan-body cache
(:func:`materialize_plan_body`, also consumed by ``run_worker.position_worktree``), the
per-skill symlink mirror (:func:`materialize_skills`), and the extension-install clone-copy
(:func:`materialize_extensions`). The launch banner (:func:`print_launch_banner`) heads a real
launch's output. ``_WORKTREE_SETUP_TIMEOUT_S`` (the per-command wall-clock cap) travels with
:func:`run_worktree_setup` and is re-exported by the package facade so
``launch._WORKTREE_SETUP_TIMEOUT_S`` resolves verbatim.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import click

from perk import __version__, plan
from perk.backends import resolve
from perk.backends.issue_backend import IssueBackendError
from perk.cli.ensure import UserFacingCliError
from perk.convergence.init.extension_install import consumer_npm_install_root
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


def materialize_plan_body(repo_root: Path, worktree: Path, plan_ref: plan.PlanRef | None) -> None:
    """Fetch the plan body from its canonical source and cache it into the worktree.

    Public: ``run_worker.position_worktree`` is the second consumer (the one canonical path for
    plan-body materialization, §1.10).

    Best-effort: a missing/empty id or any backend failure is reported but never blocks the
    launch (checkpoints simply stay inert). Honest, not silent. Backend-agnostic: the resolved
    issue backend owns the id shape (GitHub numeric, Linear ``ENG-123``).
    """
    if plan_ref is None:
        return
    pr_id = plan_ref.pr_id.strip()
    if not pr_id:
        return
    try:
        body = resolve.resolve_issue_backend(repo_root).get_plan_body(issue_id=pr_id)
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
    # The success count is folded into the launch banner (computed up front from repo_root);
    # only the missing/empty-source warnings above are emitted here.


def _count_skill_sources(repo_root: Path) -> int:
    """Count the skill dirs in ``repo_root/.agents/skills/`` — the exact set
    :func:`materialize_skills` mirrors. Best-effort: ``0`` when the dir is absent, never raises."""
    src = repo_root / ".agents" / "skills"
    try:
        return len([entry for entry in src.iterdir() if entry.is_dir()])
    except OSError:
        return 0


def _count_extension_packages(repo_root: Path) -> int:
    """Count the ``packages`` entries in ``repo_root/.pi/settings.json`` — the extensions pi loads.
    Best-effort: ``0`` on any read/JSON error."""
    settings = repo_root / ".pi" / "settings.json"
    try:
        data = json.loads(settings.read_text(encoding="utf-8"))
        packages = data.get("packages")
        return len(packages) if isinstance(packages, list) else 0
    except (OSError, ValueError, AttributeError):
        return 0


def render_launch_banner(*, skills: int, extensions: int) -> str:
    """The 4-line perk launch banner: the compact box-drawing wordmark, the version, and a summary
    line that absorbs the old ``(skills: mirrored …)`` line plus the extension count."""
    return (
        " \u250c\u2500\u2510\u250c\u2500\u2510\u252c\u2500\u2510\u250c\u2500\u2510\n"
        " \u251c\u2500\u2518\u251c\u2524 \u251c\u252c\u2518\u251c\u2534\u2510\n"
        f" \u2534  \u2514\u2500\u2518\u2534\u2514\u2500\u2534 \u2534   perk v{__version__}\n"
        f" {skills} skills \u00b7 {extensions} extensions ready"
    )


def print_launch_banner(repo_root: Path) -> None:
    """Render the launch banner from ``repo_root``'s up-front counts and emit it via
    ``user_output``. Both counts are knowable before any worktree work, so the first render is
    already accurate — no re-render.

    TTY-gated styling: the summary line is dimmed only on an interactive stderr with ``NO_COLOR``
    unset; ``--json``/piped/CI output stays plain and escape-code-free.
    """
    skills = _count_skill_sources(repo_root)
    extensions = _count_extension_packages(repo_root)
    wordmark, _, summary = render_launch_banner(skills=skills, extensions=extensions).rpartition(
        "\n"
    )
    if sys.stderr.isatty() and not os.environ.get("NO_COLOR"):
        summary = click.style(summary, dim=True)
    user_output(f"{wordmark}\n{summary}")


def _clone_npm_tree(src: Path, dst: Path) -> None:
    """Clone the converged npm install tree ``src`` into ``dst``, preferring cheap isolation.

    First attempt per-file **hardlinks** (``copy_function=os.link``) — near-instant and disk-free;
    npm only ever add/replaces a package via rename, which breaks the link, so the main checkout's
    inodes are never mutated in place. On ``OSError`` (cross-device ``EXDEV``, or no hardlink
    support) fall back to a deep copy (``copy2`` is reflink/clonefile-accelerated on APFS/Btrfs,
    a full copy elsewhere — still fully isolated).
    """
    try:
        shutil.copytree(src, dst, copy_function=os.link, dirs_exist_ok=True)
    except OSError:
        shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(src, dst, dirs_exist_ok=True)


def materialize_extensions(repo_root: Path, worktree: Path) -> None:
    """Stage the converged repo-root ``.pi/npm/`` into the worktree so pi installs nothing at
    startup (a silent + faster launch beneath the banner).

    A fresh worktree starts with an empty gitignored ``.pi/npm/``; at startup pi would ``npm
    install`` every configured extension with inherited stdio (the ``added N packages`` noise). A
    faithful copy of the converged repo-root install satisfies pi's ``needsInstall`` short-circuit
    for every package. Copying (not symlinking) preserves per-worktree isolation: an in-dev
    extension a worktree adopts stays in the worktree and never leaks to the main checkout.

    Loud-but-non-fatal + idempotent (D4 resume), mirroring :func:`materialize_skills`: a staging
    failure warns and degrades to pi installing in-session (the noise reappears below the banner)
    but never blocks the launch.
    """
    src = consumer_npm_install_root(repo_root)
    src_modules = src / "node_modules"
    try:
        src_empty = not src_modules.is_dir() or not any(src_modules.iterdir())
    except OSError:
        src_empty = True
    if src_empty:
        user_output("  (extensions: repo .pi/npm not staged — pi will install them in-session)")
        return
    dst = worktree / ".pi" / "npm"
    dst_modules = dst / "node_modules"
    try:
        if dst_modules.is_dir() and any(dst_modules.iterdir()):
            return  # idempotent resume: a populated install is already present — never clobber
    except OSError:
        pass  # treat an unreadable dst as absent and re-stage
    try:
        _clone_npm_tree(src, dst)
    except OSError as exc:
        user_output(
            f"  (extensions: could not stage .pi/npm — {exc}; pi will install them in-session)"
        )
