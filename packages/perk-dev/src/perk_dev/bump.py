"""The release-roll **mutator** for ``perk-dev bump-version``.

Validate-first, then delegate the writes to the tools that own each surface: ``uv version
--no-sync`` (pyproject.toml + uv.lock), ``npm version --no-git-tag-version`` (package.json +
package-lock.json), and finally the CHANGELOG.md roll (a pure ``changelog.roll_unreleased``
transform). Every refusal fires **before** any mutation — ``plan_bump`` performs no writes and
spawns no subprocesses; ``execute`` performs only the writes.
"""

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from perk.substrate import git, npm
from perk_dev import changelog, release

_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


class BumpError(Exception):
    """A recoverable bump failure carrying a machine ``error_type`` + human message."""

    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message


def parse_version(s: str) -> tuple[int, int, int]:
    """``(major, minor, patch)`` from a strict ``X.Y.Z`` string, else ``bad_version``.

    Deliberately narrower than uv's full grammar: no ``v`` prefix, no pre-release/dev
    suffixes — perk releases are plain three-component versions.
    """
    if _VERSION_RE.match(s) is None:
        raise BumpError("bad_version", f"not a plain X.Y.Z version: {s!r}")
    major, minor, patch = s.split(".")
    return int(major), int(minor), int(patch)


def _compute_target(current: str, *, explicit: str | None, bump: str | None) -> str:
    """The target version string — explicit ``X.Y.Z``, or ``current`` bumped by one component."""
    if explicit is not None:
        parse_version(explicit)
        return explicit
    major, minor, patch = parse_version(current)
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def _require_greater(current: str, target: str) -> None:
    """Refuse ``not_greater`` when ``target`` ≤ ``current`` (a mistaken downgrade/re-set)."""
    if parse_version(target) <= parse_version(current):
        raise BumpError(
            "not_greater", f"target {target} is not greater than the current version {current}"
        )


def resolve_target(current: str, *, explicit: str | None, bump: str | None) -> str:
    """Compute + gate the target version (``bad_version`` / ``not_greater``).

    ``plan_bump`` composes the two halves directly so the changelog's
    ``duplicate_release_header`` refusal (the clearer signal on a re-run) preempts
    ``not_greater``.
    """
    target = _compute_target(current, explicit=explicit, bump=bump)
    _require_greater(current, target)
    return target


def _run(args: list[str], *, cwd: Path, timeout: int = 120) -> str:
    """Run one delegated write tool; any failure raises ``BumpError`` (``<tool>_failed``).

    Mirrors ``perk.substrate.npm._run``: ``check=False`` + returncode inspection, captured
    text output, explicit timeout, OSError → domain error. npm's quiet-env keys are layered
    for every call (uv ignores the ``npm_config_*`` keys harmlessly).
    """
    tool = args[0]
    cmd = " ".join(args)
    try:
        proc = subprocess.run(
            args,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, **npm._QUIET_ENV},
        )
    except subprocess.TimeoutExpired as exc:
        raise BumpError(f"{tool}_failed", f"{cmd} timed out") from exc
    except OSError as exc:
        raise BumpError(f"{tool}_failed", f"{cmd} could not run: {exc}") from exc
    if proc.returncode != 0:
        raise BumpError(f"{tool}_failed", f"{cmd} failed: {proc.stderr.strip() or proc.returncode}")
    return proc.stdout


@dataclass(frozen=True)
class BumpPlan:
    """A fully validated bump, ready to execute (or print, under ``--dry-run``)."""

    current_version: str
    target_version: str
    date: str
    head_short: str
    marker_behind_head: bool
    rolled: changelog.RolledChangelog


def plan_bump(root: Path, *, explicit: str | None, bump: str | None, today: str) -> BumpPlan:
    """Validate everything and compute the roll — **no writes, no subprocesses**.

    Check ordering: the roll's ``duplicate_release_header`` refusal runs before the
    ``not_greater`` gate, so a re-run after a completed bump gets the clearer message.
    """
    current = release.read_current_version(root)
    target = _compute_target(current, explicit=explicit, bump=bump)
    head = git.resolve_commit(root, "HEAD")
    if head is None:
        raise BumpError("head_unresolvable", "HEAD does not resolve to a commit")
    head_short = head[:7]
    changelog_path = root / "CHANGELOG.md"
    if not changelog_path.is_file():
        raise changelog.ChangelogError("changelog_not_found", f"{changelog_path} not found")
    text = changelog_path.read_text(encoding="utf-8")
    rolled = changelog.roll_unreleased(text, version=target, date=today, head_short=head_short)
    _require_greater(current, target)
    marker_hash = changelog.find_marker(text)
    marker_commit = git.resolve_commit(root, marker_hash) if marker_hash is not None else None
    return BumpPlan(
        current_version=current,
        target_version=target,
        date=today,
        head_short=head_short,
        marker_behind_head=marker_commit is not None and marker_commit != head,
        rolled=rolled,
    )


def execute(root: Path, plan: BumpPlan) -> None:
    """Perform the writes: ``uv version`` → ``npm version`` → CHANGELOG.md.

    A ``uv`` failure leaves the tree untouched. An ``npm`` failure after ``uv`` succeeded
    names the partial state — never silent.
    """
    _run(["uv", "version", plan.target_version, "--no-sync"], cwd=root)
    try:
        _run(
            ["npm", "version", plan.target_version, "--no-git-tag-version", "--allow-same-version"],
            cwd=root,
        )
    except BumpError as exc:
        raise BumpError(
            "npm_failed",
            f"{exc.message}\n"
            f"Partial state: pyproject.toml and uv.lock are already at {plan.target_version}; "
            "package.json, package-lock.json, and CHANGELOG.md are untouched. Fix npm, restore "
            "the bumped files (`git restore pyproject.toml uv.lock`), and re-run.",
        ) from exc
    (root / "CHANGELOG.md").write_text(plan.rolled.text, encoding="utf-8")
