"""The GitHub gateway — Python plane, **verification-only** (contracts.md §8.4).

A thin ``gh``-shelling gateway implementing the two verification ops the init/doctor
surfaces need in Phase 0. It **never mutates** GitHub (Q9 — the first label is created
lazily by ``/plan-save`` in Phase 1). Mutation ops are named-only in §8.4 and land with
their stage handlers.

The TS extension authors the *same* operation names + payload shapes in Phase 1, so
``doctor`` can verify both planes and either can later swap ``gh``-shell → API-backed.
"""

import json
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from perk import plan

_PUSH_PERMISSIONS = frozenset({"WRITE", "MAINTAIN", "ADMIN"})

# Reads are quick; writes (issue/comment create) are slower — a longer ceiling (D5).
_READ_TIMEOUT = 15
_WRITE_TIMEOUT = 30


@dataclass(frozen=True)
class AuthStatus:
    """`gh auth status` result (§8.4 ``check_auth`` shape)."""

    ok: bool
    user: str | None
    scopes: tuple[str, ...]
    error: str | None


@dataclass(frozen=True)
class RepoAccess:
    """`gh repo view` result (§8.4 ``check_repo_access`` shape)."""

    ok: bool
    repo: str | None
    can_push: bool
    error: str | None

    @classmethod
    def skipped(cls) -> "RepoAccess":
        """Used when auth failed, so repo access was not checked."""
        return cls(ok=False, repo=None, can_push=False, error="skipped (not authenticated)")


class GitHubError(Exception):
    """The ``gh`` binary is missing or produced unparseable output."""


def _run(
    args: list[str], *, cwd: Path | None = None, timeout: int = _READ_TIMEOUT
) -> subprocess.CompletedProcess[str]:
    """Run ``gh`` capturing output. ``gh`` missing / a timeout -> ``GitHubError``."""
    try:
        return subprocess.run(
            ["gh", *args], cwd=cwd, check=False, capture_output=True, text=True, timeout=timeout
        )
    except FileNotFoundError as exc:
        raise GitHubError("gh not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitHubError(f"gh {' '.join(args)} timed out") from exc


def _parse_scopes(text: str) -> tuple[str, ...]:
    """Pull scopes from a ``gh auth status`` "Token scopes:" line (best-effort)."""
    for line in text.splitlines():
        if "Token scopes:" in line:
            raw = line.split("Token scopes:", 1)[1]
            return tuple(s.strip().strip("'\"") for s in raw.split(",") if s.strip())
    return ()


def check_auth() -> AuthStatus:
    """Verify GitHub authentication. Never mutates."""
    status = _run(["auth", "status"])
    if status.returncode != 0:
        return AuthStatus(
            ok=False, user=None, scopes=(), error=(status.stderr or status.stdout).strip()
        )
    scopes = _parse_scopes(status.stdout + status.stderr)
    user_proc = _run(["api", "user", "--jq", ".login"])
    user = user_proc.stdout.strip() if user_proc.returncode == 0 else None
    return AuthStatus(ok=True, user=user or None, scopes=scopes, error=None)


def check_repo_access(repo_root: Path) -> RepoAccess:
    """Verify the repo is readable/pushable for the authed user. Never mutates."""
    proc = _run(["repo", "view", "--json", "nameWithOwner,viewerPermission"], cwd=repo_root)
    if proc.returncode != 0:
        return RepoAccess(
            ok=False, repo=None, can_push=False, error=proc.stderr.strip() or "no GitHub repo"
        )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise GitHubError(f"unparseable `gh repo view` output: {exc}") from exc
    if not isinstance(data, dict):
        raise GitHubError(f"unexpected `gh repo view` payload: {data!r}")
    permission = data.get("viewerPermission")
    return RepoAccess(
        ok=True,
        repo=data.get("nameWithOwner"),
        can_push=permission in _PUSH_PERMISSIONS,
        error=None,
    )


# ===========================================================================
# Mutation operations (the first GitHub *writes*; T2a — contracts.md §8.4).
#
# Conventions established here and reused by submit/land (D3):
#   * REST `gh api` over porcelain (porcelain uses GraphQL -> a separate, often-exhausted
#     rate-limit quota; github-api-rate-limits).
#   * Large bodies via `-F body=@<file>`, never inline (ARG_MAX + abuse detection).
#   * Idempotency keyed on the header `run_id`, discovered via the list endpoint (not the
#     eventually-consistent search index), create-then-return.
#   * Error model by caller behaviour: `find_plan_issue` is a lookup -> returns `... | None`;
#     the mutations terminate on failure -> **raise** `GitHubError` (the command boundary
#     maps it to `UserFacingCliError`). Phase-0 reads keep their result dataclasses because
#     init/doctor branch on them.
# ===========================================================================


@dataclass(frozen=True)
class Label:
    """A label ensured to exist. ``created`` is False when it already existed (idempotent)."""

    name: str
    created: bool


@dataclass(frozen=True)
class PlanIssue:
    """A plan issue. ``existed`` is True when returned by idempotent dedup (not freshly created)."""

    number: int
    url: str
    existed: bool


@dataclass(frozen=True)
class CommentResult:
    """An issue comment. ``posted`` is False only for a dry run."""

    posted: bool


@contextmanager
def _body_file(content: str) -> Iterator[str]:
    """Write ``content`` to a temp file for ``-F body=@<path>`` (never inline). Cleaned up."""
    with tempfile.NamedTemporaryFile(
        "w", prefix="perk-body-", suffix=".md", delete=False, encoding="utf-8"
    ) as handle:
        handle.write(content)
        path = handle.name
    try:
        yield path
    finally:
        Path(path).unlink()


def _failed(proc: subprocess.CompletedProcess[str], what: str) -> GitHubError:
    return GitHubError(f"{what}: {(proc.stderr + proc.stdout).strip() or 'no output'}")


def create_label(
    name: str,
    *,
    color: str,
    description: str,
    repo_root: Path,
    dry_run: bool = False,
) -> Label:
    """Lazily create a repo label (REST). HTTP 422 "already exists" is success (idempotent)."""
    if dry_run:
        return Label(name=name, created=False)
    proc = _run(
        [
            "api",
            "repos/{owner}/{repo}/labels",
            "-X",
            "POST",
            "-f",
            f"name={name}",
            "-f",
            f"color={color}",
            "-f",
            f"description={description}",
        ],
        cwd=repo_root,
        timeout=_WRITE_TIMEOUT,
    )
    if proc.returncode == 0:
        return Label(name=name, created=True)
    if "already_exists" in (proc.stderr + proc.stdout) or "HTTP 422" in (proc.stderr + proc.stdout):
        return Label(name=name, created=False)
    raise _failed(proc, f"failed to create label {name!r}")


def find_plan_issue(*, run_id: str, repo_root: Path) -> PlanIssue | None:
    """Find an open ``perk:plan`` issue whose header ``run_id`` matches (idempotency lookup).

    Uses the **list** endpoint (not the eventually-consistent search index). Returns None for
    no match; raises ``GitHubError`` on an infra/query failure (never masks the error as None).
    """
    proc = _run(
        [
            "api",
            "repos/{owner}/{repo}/issues",
            "-X",
            "GET",
            "-f",
            f"labels={plan.PLAN_LABEL}",
            "-f",
            "state=open",
        ],
        cwd=repo_root,
    )
    if proc.returncode != 0:
        raise _failed(proc, "failed to list plan issues")
    try:
        issues = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise GitHubError(f"unparseable `gh api issues` output: {exc}") from exc
    if not isinstance(issues, list):
        return None
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        body = issue.get("body")
        if isinstance(body, str) and plan.extract_run_id(body) == run_id:
            return PlanIssue(
                number=int(issue["number"]), url=str(issue.get("html_url", "")), existed=True
            )
    return None


def create_plan_issue(
    *,
    title: str,
    body: str,
    repo_root: Path,
    run_id: str | None,
    labels: tuple[str, ...] = (plan.PLAN_LABEL,),
    dry_run: bool = False,
) -> PlanIssue:
    """Create the plan issue (REST, body via file). Idempotent on ``run_id``; raises on failure."""
    if dry_run:
        return PlanIssue(number=0, url="(dry-run)", existed=False)
    if run_id:
        existing = find_plan_issue(run_id=run_id, repo_root=repo_root)
        if existing is not None:
            return existing
    with _body_file(body) as body_path:
        args = [
            "api",
            "repos/{owner}/{repo}/issues",
            "-X",
            "POST",
            "-f",
            f"title={title}",
            "-F",
            f"body=@{body_path}",
        ]
        for label in labels:
            args += ["-f", f"labels[]={label}"]
        args += ["--jq", "{number: .number, url: .html_url}"]
        proc = _run(args, cwd=repo_root, timeout=_WRITE_TIMEOUT)
    if proc.returncode != 0:
        raise _failed(proc, "failed to create plan issue")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise GitHubError(f"unparseable `gh api issues` create output: {exc}") from exc
    if not isinstance(data, dict):
        raise GitHubError(f"unexpected create-issue payload: {data!r}")
    return PlanIssue(number=int(data["number"]), url=str(data["url"]), existed=False)


def add_issue_comment(
    *, issue: int, body: str, repo_root: Path, dry_run: bool = False
) -> CommentResult:
    """Post a comment on an issue (REST, body via file). Raises on failure."""
    if dry_run:
        return CommentResult(posted=False)
    with _body_file(body) as body_path:
        proc = _run(
            [
                "api",
                f"repos/{{owner}}/{{repo}}/issues/{issue}/comments",
                "-X",
                "POST",
                "-F",
                f"body=@{body_path}",
            ],
            cwd=repo_root,
            timeout=_WRITE_TIMEOUT,
        )
    if proc.returncode != 0:
        raise _failed(proc, f"failed to comment on issue #{issue}")
    return CommentResult(posted=True)
