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
import re
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


# --- release-check: offline pass/fail judgment over the release state -----------------
#
# The judging sibling of the report-only ``gather()``: composes the changelog structural lint
# with version-lockstep, tag-agreement, and (under ``--for-publish``) clean-tree findings.
# Fully **offline** — it deliberately does not reuse ``gather()``, whose best-effort origin
# probe is a network op; every input here is local state.

# Deliberate one-line duplicate of ``bump._VERSION_RE`` — ``bump`` imports ``release``, so
# importing the other way would cycle.
_PLAIN_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_V_TAG_RE = re.compile(r"^v\d+\.\d+\.\d+$")


@dataclass(frozen=True)
class ReleaseCheck:
    """The release-validation report: all findings in changelog → version → tag → tree order."""

    findings: tuple[changelog.Finding, ...]

    def has_errors(self) -> bool:
        """Whether any finding is an ``error`` (a method, not a property — it iterates)."""
        return any(f.severity == "error" for f in self.findings)


def check_release(root: Path, *, for_publish: bool) -> ReleaseCheck:
    """Validate the release state of ``root`` — structural, offline, no builds.

    Composes ``changelog.check`` (its ``ChangelogError`` for a missing CHANGELOG propagates
    to the CLI error arm), version lockstep across the three surfaces, local tag agreement,
    and (under ``for_publish``) a clean-tree gate. Release-level findings carry ``line=None``.
    """
    findings: list[changelog.Finding] = list(changelog.check(root).findings)

    current = read_current_version(root)
    head = git.resolve_commit(root, "HEAD")
    if head is None:
        raise ReleaseError("head_unresolvable", "HEAD does not resolve to a commit")

    package_version = _read_package_json_version(root)
    if package_version != current:
        findings.append(
            changelog.Finding(
                "error",
                "version_mismatch",
                None,
                f"package.json version {package_version or 'missing'} \u2260 pyproject {current}",
            )
        )
    if _perk_version != current:
        findings.append(
            changelog.Finding(
                "warning",
                "runtime_stale",
                None,
                f"installed perk.__version__ {_perk_version} \u2260 pyproject {current} "
                "(the next `uv sync`/`uv run` heals it)",
            )
        )

    tag_name = f"v{current}"
    head_v_tags = [t for t in git.tags_pointing_at(root) if _V_TAG_RE.match(t)]
    if head_v_tags and tag_name not in head_v_tags:
        findings.append(
            changelog.Finding(
                "error",
                "tag_disagreement",
                None,
                f"HEAD is tagged {', '.join(head_v_tags)} but pyproject says {current} "
                f"(expected {tag_name})",
            )
        )
    else:
        # refs/tags/ pins tag-namespace resolution (a branch named vX.Y.Z cannot shadow it).
        tag_commit = git.resolve_commit(root, f"refs/tags/{tag_name}")
        if tag_commit is not None and tag_commit != head:
            findings.append(
                changelog.Finding(
                    "warning",
                    "tag_not_at_head",
                    None,
                    f"tag {tag_name} exists at {tag_commit[:7]} but HEAD is {head[:7]} "
                    "(did you forget to bump?)",
                )
            )

    if for_publish and git.is_dirty(root):
        findings.append(
            changelog.Finding("error", "dirty_tree", None, "the worktree has uncommitted changes")
        )

    return ReleaseCheck(tuple(findings))


class ReleaseCheckOut(OutputModel):
    """The ``--json`` envelope for a release-validation report."""

    success: bool
    error_type: str | None
    findings: tuple[changelog.FindingOut, ...]

    @classmethod
    def from_domain(cls, c: ReleaseCheck) -> "ReleaseCheckOut":
        has_errors = c.has_errors()
        return cls(
            success=not has_errors,
            error_type="check_failed" if has_errors else None,
            findings=tuple(changelog.FindingOut.from_domain(f) for f in c.findings),
        )


# --- release-tag: derive + create the annotated release tag ---------------------------


@dataclass(frozen=True)
class TagPlan:
    """A fully validated tag operation (commit fields are full 40-char SHAs)."""

    tag_name: str
    head_commit: str
    existing_commit: str | None
    already_at_head: bool


def plan_release_tag(root: Path) -> TagPlan:
    """Validate everything for ``release-tag`` — no writes.

    The tag name is **derived** (``v{pyproject version}``); free-form names are refused
    structurally (there is no name argument anywhere in the command). A pre-release/dev
    version in pyproject refuses with ``bad_version``. An existing tag at HEAD plans a
    no-op; an existing tag **elsewhere** is a ``tag_conflict`` (never silently no-op,
    never retag).
    """
    current = read_current_version(root)
    if _PLAIN_VERSION_RE.match(current) is None:
        raise ReleaseError("bad_version", f"not a plain X.Y.Z version: {current!r}")
    head = git.resolve_commit(root, "HEAD")
    if head is None:
        raise ReleaseError("head_unresolvable", "HEAD does not resolve to a commit")
    tag_name = f"v{current}"
    existing = git.resolve_commit(root, f"refs/tags/{tag_name}")
    if existing is not None and existing != head:
        raise ReleaseError(
            "tag_conflict",
            f"tag {tag_name} already exists at {existing[:7]} but HEAD is {head[:7]} "
            "\u2014 refusing to retag",
        )
    return TagPlan(
        tag_name=tag_name,
        head_commit=head,
        existing_commit=existing,
        already_at_head=existing == head,
    )


def execute_release_tag(root: Path, plan: TagPlan) -> None:
    """Create the annotated tag (a no-op when it already sits at HEAD).

    The optional push stays in the CLI layer so its ``io_step`` narration wraps exactly
    the network op.
    """
    if not plan.already_at_head:
        git.create_annotated_tag(root, plan.tag_name, message=plan.tag_name)


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
