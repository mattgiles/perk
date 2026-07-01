"""Deterministic release **facts** for ``perk-dev release-info``.

A report-only gatherer: it exits successfully whenever the facts can be gathered at all,
regardless of mismatches, a missing tag, or a stale changelog marker — pass/fail judgment
belongs to ``release-check``. Errors are reserved for a report that would be meaningless
(no repo, no readable ``[project].version``, no HEAD); everything else degrades to ``None``
fields.

Two semantics worth knowing:

- The ``v{current_version}`` origin probe is **best-effort network**: ``tag_on_remote`` is a
  tri-state — ``True``/``False`` when the remote answered, ``None`` when there is no origin
  remote or the probe failed (offline). A probe failure never fails the report.
- ``runtime_version`` is ``perk.__version__`` — the *installed* metadata, which lags the
  pyproject SSOT until a bump has been ``uv sync``'d. That staleness is exactly what the
  field exposes.
"""

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path

from perk import __version__ as _perk_version
from perk.boundary import OutputModel
from perk.substrate import git
from perk_dev import changelog


class ReleaseError(Exception):
    """A recoverable release-facts failure carrying a machine ``error_type`` + human message."""

    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message


@dataclass(frozen=True)
class ReleaseInfo:
    """The full release-state facts report (commit fields are full 40-char SHAs)."""

    current_version: str
    package_json_version: str | None
    runtime_version: str
    tag_name: str
    tag_exists: bool
    tag_commit: str | None
    tag_at_head: bool
    tag_on_remote: bool | None
    remote_tag_commit: str | None
    latest_release_version: str | None
    latest_release_date: str | None
    head_commit: str
    marker_hash: str | None
    marker_commit: str | None
    marker_at_head: bool


def read_current_version(root: Path) -> str:
    """``[project].version`` from ``root/pyproject.toml`` — the version SSOT.

    It anchors the whole report (the tag name derives from it), so failures here are
    errors, not nulls. Also the current-version seam for ``perk_dev.bump``.
    """
    path = root / "pyproject.toml"
    if not path.is_file():
        raise ReleaseError("pyproject_not_found", f"{path} not found")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ReleaseError("bad_pyproject", f"{path} is not valid TOML: {exc}") from exc
    project = data.get("project")
    version = project.get("version") if isinstance(project, dict) else None
    if not isinstance(version, str):
        raise ReleaseError("bad_pyproject", f"{path} has no [project].version string")
    return version


def _read_package_json_version(root: Path) -> str | None:
    """The ``version`` string from ``root/package.json``, or ``None`` (a fact, not a failure)."""
    path = root / "package.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    version = data.get("version") if isinstance(data, dict) else None
    return version if isinstance(version, str) else None


def _probe_remote_tag(root: Path, tag_name: str) -> tuple[bool | None, str | None]:
    """``(tag_on_remote, remote_tag_commit)`` from the best-effort origin probe.

    No origin remote → ``(None, None)`` (unknowable, not "absent"); a failed probe
    (offline / timeout) → ``(None, None)``; the remote answered → ``(True, sha)`` or
    ``(False, None)``.
    """
    if not git.has_remote(root):
        return None, None
    try:
        sha = git.remote_tag_commit(root, tag_name)
    except git.GitError:
        return None, None
    if sha is None:
        return False, None
    return True, sha


def gather(root: Path) -> ReleaseInfo:
    """The release-state facts for ``root`` (report-only: mismatches are facts, not errors)."""
    current_version = read_current_version(root)
    head_commit = git.resolve_commit(root, "HEAD")
    if head_commit is None:
        raise ReleaseError("head_unresolvable", "HEAD does not resolve to a commit")

    tag_name = f"v{current_version}"
    # refs/tags/ pins tag-namespace resolution (a branch named vX.Y.Z cannot shadow the tag).
    tag_commit = git.resolve_commit(root, f"refs/tags/{tag_name}")
    # Probed even when the local tag is missing — a remote-only tag is a reportable state.
    tag_on_remote, remote_tag_commit = _probe_remote_tag(root, tag_name)

    changelog_path = root / "CHANGELOG.md"
    latest: tuple[str, str] | None = None
    marker_hash: str | None = None
    if changelog_path.is_file():
        text = changelog_path.read_text(encoding="utf-8")
        latest = changelog.latest_release(text)
        marker_hash = changelog.find_marker(text)
    marker_commit = git.resolve_commit(root, marker_hash) if marker_hash is not None else None

    return ReleaseInfo(
        current_version=current_version,
        package_json_version=_read_package_json_version(root),
        runtime_version=_perk_version,
        tag_name=tag_name,
        tag_exists=tag_commit is not None,
        tag_commit=tag_commit,
        tag_at_head=tag_commit is not None and tag_commit == head_commit,
        tag_on_remote=tag_on_remote,
        remote_tag_commit=remote_tag_commit,
        latest_release_version=latest[0] if latest is not None else None,
        latest_release_date=latest[1] if latest is not None else None,
        head_commit=head_commit,
        marker_hash=marker_hash,
        marker_commit=marker_commit,
        marker_at_head=marker_commit is not None and marker_commit == head_commit,
    )


class ReleaseInfoOut(OutputModel):
    """The ``--json`` envelope for a release-state report (field order is load-bearing)."""

    success: bool
    error_type: str | None
    current_version: str
    package_json_version: str | None
    runtime_version: str
    tag_name: str
    tag_exists: bool
    tag_commit: str | None
    tag_at_head: bool
    tag_on_remote: bool | None
    remote_tag_commit: str | None
    latest_release_version: str | None
    latest_release_date: str | None
    head_commit: str
    marker_hash: str | None
    marker_commit: str | None
    marker_at_head: bool

    @classmethod
    def from_domain(cls, r: ReleaseInfo) -> "ReleaseInfoOut":
        return cls(
            success=True,
            error_type=None,
            current_version=r.current_version,
            package_json_version=r.package_json_version,
            runtime_version=r.runtime_version,
            tag_name=r.tag_name,
            tag_exists=r.tag_exists,
            tag_commit=r.tag_commit,
            tag_at_head=r.tag_at_head,
            tag_on_remote=r.tag_on_remote,
            remote_tag_commit=r.remote_tag_commit,
            latest_release_version=r.latest_release_version,
            latest_release_date=r.latest_release_date,
            head_commit=r.head_commit,
            marker_hash=r.marker_hash,
            marker_commit=r.marker_commit,
            marker_at_head=r.marker_at_head,
        )
