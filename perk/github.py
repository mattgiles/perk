"""The GitHub gateway — Python plane, **verification-only** (contracts.md §8.4).

A thin ``gh``-shelling gateway implementing the two verification ops the init/doctor
surfaces need in Phase 0. It **never mutates** GitHub (Q9 — the first label is created
lazily by ``/plan-save`` in Phase 1). Mutation ops are named-only in §8.4 and land with
their stage handlers.

The TS extension authors the *same* operation names + payload shapes in Phase 1, so
``doctor`` can verify both planes and either can later swap ``gh``-shell → API-backed.
"""

import json
import re
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from perk import objective, plan

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


def find_plan_issue(
    *,
    run_id: str,
    repo_root: Path,
    label: str = plan.PLAN_LABEL,
    header_key: str = plan.PLAN_HEADER_KEY,
) -> PlanIssue | None:
    """Find an open ``label``-scoped issue whose metadata-block ``run_id`` matches (idempotency).

    Uses the **list** endpoint (not the eventually-consistent search index). Returns None for
    no match; raises ``GitHubError`` on an infra/query failure (never masks the error as None).

    Parameterized by ``label``/``header_key`` (P2.T8b): the defaults find the ``perk:plan`` issue
    (``plan-header``); ``find_learn_issue`` passes ``perk:learn``/``learn-header`` so the learn
    lookup is **label-scoped** and cannot match the plan issue (which shares the same ``run_id``).
    """
    proc = _run(
        [
            "api",
            "repos/{owner}/{repo}/issues",
            "-X",
            "GET",
            "-f",
            f"labels={label}",
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
        if isinstance(body, str) and plan.extract_run_id(body, header_key=header_key) == run_id:
            return PlanIssue(
                number=int(issue["number"]), url=str(issue.get("html_url", "")), existed=True
            )
    return None


def find_learn_issue(*, run_id: str, repo_root: Path) -> PlanIssue | None:
    """Find an open ``perk:learn`` issue whose ``learn-header`` ``run_id`` matches (P2.T8b).

    The label-scoped twin of ``find_plan_issue``: scoped to ``perk:learn`` + the ``learn-header``
    block so it never returns the plan issue (which shares the plan's ``run_id`` under the
    ``warm: keep`` learn stage). Returns None for no match; raises on an infra failure.
    """
    return find_plan_issue(
        run_id=run_id,
        repo_root=repo_root,
        label=plan.LEARN_LABEL,
        header_key=plan.LEARN_HEADER_KEY,
    )


def create_learn_issue(
    *,
    title: str,
    body: str,
    repo_root: Path,
    run_id: str | None,
    plan_number: int,
    dry_run: bool = False,
) -> PlanIssue:
    """Create the ``perk:learn`` knowledge-capture issue (P2.T8b, D10). Mirrors
    ``create_plan_issue`` but: lazily creates the ``perk:learn`` label, is **idempotent via
    ``find_learn_issue``** (not ``find_plan_issue``), and renders a ``learn-header`` block into the
    body so the finder can match. Raises ``GitHubError`` on failure."""
    if dry_run:
        return PlanIssue(number=0, url="(dry-run)", existed=False)
    if run_id:
        existing = find_learn_issue(run_id=run_id, repo_root=repo_root)
        if existing is not None:
            return existing
    create_label(
        plan.LEARN_LABEL,
        color=plan.LEARN_LABEL_COLOR,
        description=plan.LEARN_LABEL_DESCRIPTION,
        repo_root=repo_root,
    )
    header = plan.render_metadata_block(
        plan.LEARN_HEADER_KEY,
        {"run_id": run_id, "created": plan.now_iso(), "plan": plan_number},
    )
    full_body = f"{header}\n\n{body.strip()}\n"
    return create_plan_issue(
        title=title,
        body=full_body,
        repo_root=repo_root,
        run_id=None,  # idempotency already handled above via find_learn_issue
        labels=(plan.LEARN_LABEL,),
    )


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


# ===========================================================================
# Objective ops (P2.T9 — objective storage + mechanics; contracts.md §8.4).
#
# Mirrors the plan/learn idempotency + two-step create exactly: REST `gh api`, bodies via file,
# idempotency keyed on the header `run_id` via the LIST endpoint (label-scoped to
# `perk:objective`), the `perk:objective` label created lazily, mutations RAISE / lookups return
# `... | None`. The objective body holds two blocks (`objective-header` + `objective-roadmap`); the
# first comment holds the rendered table (`objective-body`). Status is explicit-only (open #3).
# ===========================================================================


@dataclass(frozen=True)
class ObjectiveIssue:
    """An objective issue. ``existed`` is True when returned by idempotent dedup."""

    number: int
    url: str
    existed: bool


@dataclass(frozen=True)
class ObjectiveState:
    """An objective's observable state: header + roadmap nodes (``perk objective show``)."""

    number: int
    url: str
    title: str
    header: dict[str, object]
    nodes: tuple[objective.ObjectiveNode, ...]


@dataclass(frozen=True)
class ObjectiveHeaderUpdate:
    """The result of a staged ``objective-header`` field write."""

    fields_updated: tuple[str, ...]
    dry_run: bool


@dataclass(frozen=True)
class ObjectiveNodeUpdate:
    """The result of an ``update_objective_node`` write (body + comment both re-rendered)."""

    number: int
    node_id: str
    comment_updated: bool
    dry_run: bool


def find_objective_issue(*, run_id: str, repo_root: Path) -> ObjectiveIssue | None:
    """Find an open ``perk:objective`` issue whose ``objective-header`` ``run_id`` matches.

    The label-scoped twin of ``find_plan_issue`` (delegates to the parameterized finder); returns
    None for no match, raises on an infra failure.
    """
    found = find_plan_issue(
        run_id=run_id,
        repo_root=repo_root,
        label=objective.OBJECTIVE_LABEL,
        header_key=objective.OBJECTIVE_HEADER_KEY,
    )
    if found is None:
        return None
    return ObjectiveIssue(number=found.number, url=found.url, existed=True)


def _post_comment_with_id(*, issue: int, body: str, repo_root: Path) -> int:
    """Post a comment and return its numeric id (REST, body via file). Raises on failure."""
    with _body_file(body) as body_path:
        proc = _run(
            [
                "api",
                f"repos/{{owner}}/{{repo}}/issues/{issue}/comments",
                "-X",
                "POST",
                "-F",
                f"body=@{body_path}",
                "--jq",
                "{id: .id}",
            ],
            cwd=repo_root,
            timeout=_WRITE_TIMEOUT,
        )
    if proc.returncode != 0:
        raise _failed(proc, f"failed to post objective body comment on #{issue}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise GitHubError(f"unparseable comment-create output: {exc}") from exc
    if not isinstance(data, dict) or "id" not in data:
        raise GitHubError(f"unexpected comment-create payload: {data!r}")
    return int(data["id"])


def create_objective_issue(
    *,
    title: str,
    body: str,
    repo_root: Path,
    run_id: str,
    status: str = "active",
    dry_run: bool = False,
) -> ObjectiveIssue:
    """Create the ``perk:objective`` issue (the two-step create). ``body`` is the authored
    objective markdown; any embedded roadmap nodes are parsed from it. Idempotent on ``run_id``;
    raises ``GitHubError`` on failure.

    Steps: (1) idempotency check; (2) lazily create the ``perk:objective`` label; (3) compose the
    issue body = ``objective-header`` (``objective_comment_id: null``) + ``objective-roadmap``
    blocks; (4) POST the issue; (5) post the ``objective-body`` comment (rendered table + prose),
    capturing its id; (6) backfill ``objective_comment_id`` into the header.
    """
    if dry_run:
        return ObjectiveIssue(number=0, url="(dry-run)", existed=False)

    existing = find_objective_issue(run_id=run_id, repo_root=repo_root)
    if existing is not None:
        return existing

    nodes, errors = objective.parse_roadmap_nodes(body)
    if errors:
        raise GitHubError("invalid objective roadmap: " + "; ".join(errors))

    create_label(
        objective.OBJECTIVE_LABEL,
        color=objective.OBJECTIVE_LABEL_COLOR,
        description=objective.OBJECTIVE_LABEL_DESCRIPTION,
        repo_root=repo_root,
    )

    header = objective.ObjectiveHeader(
        run_id=run_id, created=plan.now_iso(), objective_comment_id=None, status=status
    )
    header_block = plan.render_metadata_block(objective.OBJECTIVE_HEADER_KEY, header.to_data())
    roadmap_block = plan.render_metadata_block(
        objective.OBJECTIVE_ROADMAP_KEY, objective.render_roadmap_block(nodes)
    )
    issue_body = f"{header_block}\n\n{roadmap_block}\n"

    created = create_plan_issue(
        title=title,
        body=issue_body,
        repo_root=repo_root,
        run_id=None,  # idempotency already handled above
        labels=(objective.OBJECTIVE_LABEL,),
    )

    comment_body = objective.render_body_comment(nodes, prose=body.strip())
    comment_id = _post_comment_with_id(issue=created.number, body=comment_body, repo_root=repo_root)
    update_objective_header(
        number=created.number,
        fields={"objective_comment_id": comment_id},
        repo_root=repo_root,
    )
    return ObjectiveIssue(number=created.number, url=created.url, existed=False)


def get_objective(*, number: int, repo_root: Path) -> ObjectiveState | None:
    """Read an objective issue's state (header + roadmap nodes). ``None`` when absent; raises on
    an infra failure."""
    proc = _run(["issue", "view", str(number), "--json", "number,title,body,url"], cwd=repo_root)
    if proc.returncode != 0:
        haystack = (proc.stderr + proc.stdout).lower()
        if "not found" in haystack or "404" in haystack:
            return None
        raise _failed(proc, f"failed to read objective issue #{number}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise GitHubError(f"unparseable `gh issue view` output: {exc}") from exc
    body = str(data.get("body", ""))
    header = plan.find_metadata_block(body, objective.OBJECTIVE_HEADER_KEY) or {}
    nodes, errors = objective.parse_roadmap_nodes(body)
    if errors:
        raise GitHubError(f"invalid objective roadmap on #{number}: " + "; ".join(errors))
    return ObjectiveState(
        number=int(data["number"]) if "number" in data else number,
        url=str(data.get("url", "")),
        title=str(data.get("title", "")),
        header=header,
        nodes=tuple(nodes),
    )


def update_objective_header(
    *, number: int, fields: dict[str, object], repo_root: Path, dry_run: bool = False
) -> ObjectiveHeaderUpdate:
    """Merge ``fields`` into the issue body's ``objective-header`` block and PATCH it (REST).

    Rejects unknown header keys (LBYL). A dry run validates + composes only.
    """
    unknown = set(fields) - objective.OBJECTIVE_HEADER_FIELDS
    if unknown:
        raise GitHubError(f"unknown objective-header field(s): {sorted(unknown)}")
    body = _get_issue_body(number, repo_root)
    header = plan.find_metadata_block(body, objective.OBJECTIVE_HEADER_KEY) or {}
    new_body = plan.replace_metadata_block(
        body, objective.OBJECTIVE_HEADER_KEY, {**header, **fields}
    )
    if dry_run:
        return ObjectiveHeaderUpdate(fields_updated=tuple(fields), dry_run=True)
    with _body_file(new_body) as body_path:
        proc = _run(
            [
                "api",
                f"repos/{{owner}}/{{repo}}/issues/{number}",
                "-X",
                "PATCH",
                "-F",
                f"body=@{body_path}",
            ],
            cwd=repo_root,
            timeout=_WRITE_TIMEOUT,
        )
    if proc.returncode != 0:
        raise _failed(proc, f"failed to update objective-header on #{number}")
    return ObjectiveHeaderUpdate(fields_updated=tuple(fields), dry_run=False)


def _get_comment_body(comment_id: int, repo_root: Path) -> str | None:
    proc = _run(
        ["api", f"repos/{{owner}}/{{repo}}/issues/comments/{comment_id}", "--jq", ".body"],
        cwd=repo_root,
    )
    if proc.returncode != 0:
        if "404" in (proc.stderr + proc.stdout):
            return None
        raise _failed(proc, f"failed to read comment #{comment_id}")
    return proc.stdout


def _patch_comment_body(comment_id: int, body: str, repo_root: Path) -> None:
    with _body_file(body) as body_path:
        proc = _run(
            [
                "api",
                f"repos/{{owner}}/{{repo}}/issues/comments/{comment_id}",
                "-X",
                "PATCH",
                "-F",
                f"body=@{body_path}",
            ],
            cwd=repo_root,
            timeout=_WRITE_TIMEOUT,
        )
    if proc.returncode != 0:
        raise _failed(proc, f"failed to update comment #{comment_id}")


def update_objective_node(
    *,
    number: int,
    node_id: str,
    status: objective.NodeStatus | None = None,
    pr: str | None = None,
    description: str | None = None,
    repo_root: Path,
    dry_run: bool = False,
) -> ObjectiveNodeUpdate:
    """Update one roadmap node (explicit-status-only): re-render the ``objective-roadmap`` block
    in the issue body (authoritative) AND the rendered table in the ``objective-body`` comment.

    Raises ``GitHubError`` if the node is not found or the roadmap is invalid; the comment
    re-render is best-effort (the frontmatter is the source of truth).
    """
    body = _get_issue_body(number, repo_root)
    nodes, errors = objective.parse_roadmap_nodes(body)
    if errors:
        raise GitHubError("invalid objective roadmap: " + "; ".join(errors))
    updated = objective.update_node(nodes, node_id, status=status, pr=pr, description=description)
    if updated is None:
        raise GitHubError(f"objective node {node_id!r} not found on #{number}")
    if dry_run:
        return ObjectiveNodeUpdate(
            number=number, node_id=node_id, comment_updated=False, dry_run=True
        )

    new_body = plan.replace_metadata_block(
        body, objective.OBJECTIVE_ROADMAP_KEY, objective.render_roadmap_block(updated)
    )
    with _body_file(new_body) as body_path:
        proc = _run(
            [
                "api",
                f"repos/{{owner}}/{{repo}}/issues/{number}",
                "-X",
                "PATCH",
                "-F",
                f"body=@{body_path}",
            ],
            cwd=repo_root,
            timeout=_WRITE_TIMEOUT,
        )
    if proc.returncode != 0:
        raise _failed(proc, f"failed to update objective roadmap on #{number}")

    comment_updated = False
    header = plan.find_metadata_block(new_body, objective.OBJECTIVE_HEADER_KEY) or {}
    comment_id = header.get("objective_comment_id")
    if isinstance(comment_id, int):
        comment_body = _get_comment_body(comment_id, repo_root)
        if comment_body is not None:
            rerendered = objective.rerender_body_table(comment_body, updated)
            if rerendered is not None:
                _patch_comment_body(comment_id, rerendered, repo_root)
                comment_updated = True
    return ObjectiveNodeUpdate(
        number=number, node_id=node_id, comment_updated=comment_updated, dry_run=False
    )


# ===========================================================================
# PR lifecycle ops (P1.T5 — submit/land/resume; contracts.md §8.4).
#
# Same conventions as the plan write: REST `gh api` over porcelain (the lone exception is
# `mark_pr_ready` — there is no REST endpoint for draft->ready, so it shells `gh pr ready`,
# which is GraphQL), bodies via file, idempotency via the list endpoint + find-then-return,
# mutations raise / lookups return `... | None`.
# ===========================================================================


@dataclass(frozen=True)
class PullRequest:
    """A pull request. ``existed`` is True when found (idempotent), False when freshly created."""

    number: int
    url: str
    is_draft: bool
    state: str  # "OPEN" | "MERGED" | "CLOSED" (normalized)
    existed: bool


@dataclass(frozen=True)
class PlanHeaderUpdate:
    """The result of a staged ``plan-header`` field write."""

    fields_updated: tuple[str, ...]
    dry_run: bool


@dataclass(frozen=True)
class PrBodyUpdate:
    """The result of a PR-body re-write (P2.T8a — the create-then-update footer write)."""

    number: int
    dry_run: bool


@dataclass(frozen=True)
class PlanState:
    """A plan issue's observable state (for ``perk resume``): the parsed header + PR (if any)."""

    number: int
    url: str
    title: str
    header: dict[str, object]
    pr: PullRequest | None


def _owner(repo_root: Path) -> str:
    """The repo owner login (for the ``head=<owner>:<branch>`` PR list filter)."""
    proc = _run(["repo", "view", "--json", "owner", "--jq", ".owner.login"], cwd=repo_root)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise _failed(proc, "failed to resolve repo owner")
    return proc.stdout.strip()


def _pr_state(pr: dict[str, Any]) -> str:
    """Normalize a REST PR object's state into OPEN | MERGED | CLOSED."""
    if pr.get("merged") is True or pr.get("merged_at"):
        return "MERGED"
    return "OPEN" if pr.get("state") == "open" else "CLOSED"


def _pull_request(pr: dict[str, Any], *, existed: bool) -> PullRequest:
    return PullRequest(
        number=int(pr["number"]),
        url=str(pr.get("html_url", "")),
        is_draft=bool(pr.get("draft", False)),
        state=_pr_state(pr),
        existed=existed,
    )


def default_branch(repo_root: Path) -> str:
    """The repo's default branch (the PR base). Raises ``GitHubError`` on failure."""
    proc = _run(
        ["repo", "view", "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name"],
        cwd=repo_root,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise _failed(proc, "failed to resolve the default branch")
    return proc.stdout.strip()


def find_pr_for_branch(*, branch: str, repo_root: Path) -> PullRequest | None:
    """Find a PR whose head is ``branch`` (idempotency lookup; list endpoint, all states).

    Prefers an open PR (the submit-reuse case); raises on an infra failure, never masks it.
    """
    proc = _run(
        [
            "api",
            "repos/{owner}/{repo}/pulls",
            "-X",
            "GET",
            "-f",
            f"head={_owner(repo_root)}:{branch}",
            "-f",
            "state=all",
        ],
        cwd=repo_root,
    )
    if proc.returncode != 0:
        raise _failed(proc, f"failed to list PRs for {branch!r}")
    try:
        items = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise GitHubError(f"unparseable `gh api pulls` output: {exc}") from exc
    if not isinstance(items, list) or not items:
        return None
    chosen = next((p for p in items if p.get("state") == "open"), items[0])
    return _pull_request(chosen, existed=True)


def create_pr(
    *,
    head: str,
    base: str,
    title: str,
    body: str,
    repo_root: Path,
    draft: bool = True,
    dry_run: bool = False,
) -> PullRequest:
    """Open a PR (REST, body via file). Idempotent: an existing PR for ``head`` is returned."""
    if dry_run:
        return PullRequest(number=0, url="(dry-run)", is_draft=draft, state="OPEN", existed=False)
    existing = find_pr_for_branch(branch=head, repo_root=repo_root)
    if existing is not None:
        return existing
    with _body_file(body) as body_path:
        proc = _run(
            [
                "api",
                "repos/{owner}/{repo}/pulls",
                "-X",
                "POST",
                "-f",
                f"title={title}",
                "-f",
                f"head={head}",
                "-f",
                f"base={base}",
                "-F",
                f"body=@{body_path}",
                "-F",
                f"draft={'true' if draft else 'false'}",
                "--jq",
                "{number: .number, html_url: .html_url, draft: .draft, state: .state}",
            ],
            cwd=repo_root,
            timeout=_WRITE_TIMEOUT,
        )
    if proc.returncode != 0:
        raise _failed(proc, "failed to create PR")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise GitHubError(f"unparseable `gh api pulls` create output: {exc}") from exc
    if not isinstance(data, dict):
        raise GitHubError(f"unexpected create-PR payload: {data!r}")
    return _pull_request(data, existed=False)


def update_plan_header(
    *, issue: int, fields: dict[str, object], repo_root: Path, dry_run: bool = False
) -> PlanHeaderUpdate:
    """Merge ``fields`` into the issue body's ``plan-header`` block and PATCH it (REST).

    Rejects unknown header keys (LBYL on the schema). A dry run validates + composes only.
    """
    unknown = set(fields) - plan.PLAN_HEADER_FIELDS
    if unknown:
        raise GitHubError(f"unknown plan-header field(s): {sorted(unknown)}")
    body = _get_issue_body(issue, repo_root)
    header = plan.find_metadata_block(body, plan.PLAN_HEADER_KEY) or {}
    new_body = plan.replace_metadata_block(body, plan.PLAN_HEADER_KEY, {**header, **fields})
    if dry_run:
        return PlanHeaderUpdate(fields_updated=tuple(fields), dry_run=True)
    with _body_file(new_body) as body_path:
        proc = _run(
            [
                "api",
                f"repos/{{owner}}/{{repo}}/issues/{issue}",
                "-X",
                "PATCH",
                "-F",
                f"body=@{body_path}",
            ],
            cwd=repo_root,
            timeout=_WRITE_TIMEOUT,
        )
    if proc.returncode != 0:
        raise _failed(proc, f"failed to update plan-header on #{issue}")
    return PlanHeaderUpdate(fields_updated=tuple(fields), dry_run=False)


def _get_issue_body(issue: int, repo_root: Path) -> str:
    proc = _run(["api", f"repos/{{owner}}/{{repo}}/issues/{issue}", "--jq", ".body"], cwd=repo_root)
    if proc.returncode != 0:
        raise _failed(proc, f"failed to read issue #{issue}")
    return proc.stdout


def get_pr(*, number: int, repo_root: Path) -> PullRequest | None:
    """Fetch a PR by number (REST). ``None`` if it does not exist; raises on infra failure."""
    proc = _run(["api", f"repos/{{owner}}/{{repo}}/pulls/{number}"], cwd=repo_root)
    if proc.returncode != 0:
        if "404" in (proc.stderr + proc.stdout):
            return None
        raise _failed(proc, f"failed to read PR #{number}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise GitHubError(f"unparseable `gh api pulls/{number}` output: {exc}") from exc
    return _pull_request(data, existed=True)


def get_pr_body(*, number: int, repo_root: Path) -> str | None:
    """Fetch a PR's body markdown (REST). ``None`` if the PR does not exist; raises on infra
    failure. Used by ``perk pr-check`` to re-validate the live checkout footer (P2.T8a)."""
    proc = _run(["api", f"repos/{{owner}}/{{repo}}/pulls/{number}", "--jq", ".body"], cwd=repo_root)
    if proc.returncode != 0:
        if "404" in (proc.stderr + proc.stdout):
            return None
        raise _failed(proc, f"failed to read PR #{number} body")
    return proc.stdout


def update_pr_body(
    *, number: int, body: str, repo_root: Path, dry_run: bool = False
) -> PrBodyUpdate:
    """Re-write a PR's body (REST ``PATCH .../pulls/{n}``, body via file; mirrors
    :func:`update_plan_header`). P2.T8a's create-then-update footer write: the checkout footer
    needs the **PR** number, unknown until ``create_pr`` returns. Idempotent (overwrites). The PR
    body is distinct from the issue body -- no collision with ``update_plan_header``."""
    if dry_run:
        return PrBodyUpdate(number=number, dry_run=True)
    with _body_file(body) as body_path:
        proc = _run(
            [
                "api",
                f"repos/{{owner}}/{{repo}}/pulls/{number}",
                "-X",
                "PATCH",
                "-F",
                f"body=@{body_path}",
            ],
            cwd=repo_root,
            timeout=_WRITE_TIMEOUT,
        )
    if proc.returncode != 0:
        raise _failed(proc, f"failed to update PR #{number} body")
    return PrBodyUpdate(number=number, dry_run=False)


_CHECKOUT_RE = re.compile(r"gh pr checkout\s+(\d+)")
_PLAIN_FOOTER_RE = re.compile(r"`gh pr checkout\s+(\d+)`")
_HTML_FOOTER_RE = re.compile(r"<code>[^<]*gh pr checkout", re.IGNORECASE)


def validate_pr_body(body: str, *, pr_number: int) -> tuple[str, ...]:
    """Validate the PR body's checkout footer (P2.T8a, D5). Empty tuple == valid.

    **Footer-scoped only** -- the ``<details>`` plan embed is explicitly fine; the footer must be
    a plain-backtick `` `gh pr checkout <pr_number>` `` line carrying the **PR** number (not the
    issue number -- erk's single most common agent mistake). The three checks:

    1. the checkout footer is present,
    2. it carries the correct PR number (word-boundary: ``#12`` != ``...checkout 123``),
    3. it is plain backtick, not wrapped in HTML (``<code>...</code>`` breaks supervisor copy).
    """
    all_numbers = _CHECKOUT_RE.findall(body)
    if not all_numbers:
        return (f"checkout footer missing (expected `gh pr checkout {pr_number}`)",)
    errors: list[str] = []
    html_wrapped = bool(_HTML_FOOTER_RE.search(body))
    if html_wrapped:
        errors.append("checkout footer must be a plain-backtick line, not HTML-wrapped")
    plain_numbers = _PLAIN_FOOTER_RE.findall(body)
    if str(pr_number) not in plain_numbers:
        if str(pr_number) not in all_numbers:
            errors.append(f"checkout footer carries the wrong number (expected PR #{pr_number})")
        elif not html_wrapped:
            errors.append("checkout footer is present but not a plain-backtick line")
    return tuple(errors)


def get_plan(*, number: int, repo_root: Path) -> PlanState | None:
    """Read a plan issue's observable state (header + PR) for ``perk resume``.

    ``None`` when the issue does not exist; raises ``GitHubError`` on an infra failure.
    """
    proc = _run(
        ["issue", "view", str(number), "--json", "number,title,body,state,url"], cwd=repo_root
    )
    if proc.returncode != 0:
        if "not found" in (proc.stderr + proc.stdout).lower() or "404" in (
            proc.stderr + proc.stdout
        ):
            return None
        raise _failed(proc, f"failed to read plan issue #{number}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise GitHubError(f"unparseable `gh issue view` output: {exc}") from exc
    header = plan.find_metadata_block(str(data.get("body", "")), plan.PLAN_HEADER_KEY) or {}
    pr_field = header.get("pr")
    pr = (
        get_pr(number=int(pr_field), repo_root=repo_root)
        if isinstance(pr_field, str | int) and str(pr_field).strip() and str(pr_field) != "None"
        else None
    )
    return PlanState(
        number=int(data["number"]) if "number" in data else number,
        url=str(data.get("url", "")),
        title=str(data.get("title", "")),
        header=header,
        pr=pr,
    )


def get_plan_body(*, number: int, repo_root: Path) -> str | None:
    """Fetch a plan issue's verbatim plan markdown (the ``plan-body`` block lives in the first
    comment; the issue body holds only the header). ``None`` when the issue or block is absent;
    raises ``GitHubError`` on an infra failure. Used to materialize the plan body for in-session
    checkpoints (P2.T2c).
    """
    proc = _run(["issue", "view", str(number), "--json", "body,comments"], cwd=repo_root)
    if proc.returncode != 0:
        haystack = (proc.stderr + proc.stdout).lower()
        if "not found" in haystack or "404" in haystack:
            return None
        raise _failed(proc, f"failed to read plan issue #{number}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise GitHubError(f"unparseable `gh issue view` output: {exc}") from exc
    candidates = [str(data.get("body", ""))]
    comments = data.get("comments")
    if isinstance(comments, list):
        candidates.extend(str(c.get("body", "")) for c in comments if isinstance(c, dict))
    for text in candidates:
        body = plan.extract_plan_body(text)
        if body:
            return body
    return None


def mark_pr_ready(*, number: int, repo_root: Path, dry_run: bool = False) -> None:
    """Mark a draft PR ready for review (the lone GraphQL op — there is no REST endpoint).

    Called only on a draft PR (the worker checks `is_draft` first); raises on failure.
    """
    if dry_run:
        return
    proc = _run(["pr", "ready", str(number)], cwd=repo_root, timeout=_WRITE_TIMEOUT)
    if proc.returncode != 0:
        raise _failed(proc, f"failed to mark PR #{number} ready")


def merge_pr(
    *, number: int, repo_root: Path, commit_message: str | None = None, dry_run: bool = False
) -> PullRequest:
    """Squash-merge a PR (REST `PUT .../merge`). Idempotent: an already-merged PR is success.

    The caller checks `state != MERGED` before merging; the ``already merged`` net guards a race.
    """
    if dry_run:
        return PullRequest(number=number, url="", is_draft=False, state="MERGED", existed=True)
    args = [
        "api",
        f"repos/{{owner}}/{{repo}}/pulls/{number}/merge",
        "-X",
        "PUT",
        "-f",
        "merge_method=squash",
    ]
    if commit_message:
        args += ["-f", f"commit_message={commit_message}"]
    proc = _run(args, cwd=repo_root, timeout=_WRITE_TIMEOUT)
    if proc.returncode == 0:
        return PullRequest(number=number, url="", is_draft=False, state="MERGED", existed=True)
    if "already merged" in (proc.stderr + proc.stdout).lower():
        return PullRequest(number=number, url="", is_draft=False, state="MERGED", existed=True)
    raise _failed(proc, f"failed to merge PR #{number}")


# ===========================================================================
# Review-feedback ops (P2.T7 — the `/address` loop; contracts.md §8.4).
#
# Review threads and their resolution are **GraphQL-only** (there is no REST endpoint for
# `isResolved` or the `resolveReviewThread`/`addPullRequestReviewThreadReply` mutations), so these
# ops shell `gh api graphql` (the lone exceptions to the REST-over-porcelain convention, alongside
# `mark_pr_ready`). Discussion comments live on the issue and stay REST. The GraphQL shapes are
# verbatim from erk (`.prior-art/erk/.../graphql_queries.py`), the durable prior art (§8.4).
#
# Error model (§8.4): `get_pr_feedback` is a read that **raises** `GitHubError` on infra failure;
# `resolve_review_threads` captures *per-item* failures into its result (so one bad thread does not
# sink the batch) but still raises on a hard infra failure (gh missing / timeout, via `_run`).
# ===========================================================================

GET_PR_REVIEW_THREADS_QUERY = """query($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      reviewThreads(first: 100) {
        nodes {
          id
          isResolved
          isOutdated
          path
          line
          comments(first: 20) {
            nodes {
              databaseId
              body
              author { login }
              path
              line: originalLine
              createdAt
            }
          }
        }
      }
    }
  }
}"""

GET_PR_REVIEWS_QUERY = """query($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      reviews(first: 100, states: [CHANGES_REQUESTED, APPROVED, COMMENTED]) {
        nodes {
          id
          author { login }
          body
          state
          submittedAt
        }
      }
    }
  }
}"""

RESOLVE_REVIEW_THREAD_MUTATION = """mutation($threadId: ID!) {
  resolveReviewThread(input: {threadId: $threadId}) {
    thread {
      id
      isResolved
    }
  }
}"""

ADD_REVIEW_THREAD_REPLY_MUTATION = """mutation($threadId: ID!, $body: String!) {
  addPullRequestReviewThreadReply(input: {pullRequestReviewThreadId: $threadId, body: $body}) {
    comment {
      id
      body
    }
  }
}"""


@dataclass(frozen=True)
class ReviewComment:
    """A single comment within a review thread (the inline-code conversation)."""

    comment_id: int | None  # databaseId; may be absent on some nodes
    body: str
    author: str | None
    path: str | None
    line: int | None
    created_at: str | None


@dataclass(frozen=True)
class ReviewThread:
    """A PR review thread (inline conversation). ``thread_id`` is the GraphQL node id."""

    thread_id: str
    is_resolved: bool
    is_outdated: bool
    path: str | None
    line: int | None
    comments: tuple[ReviewComment, ...]


@dataclass(frozen=True)
class DiscussionComment:
    """A PR/issue discussion comment (the conversation tab; a distinct API from threads)."""

    comment_id: int
    body: str
    author: str | None
    created_at: str | None


@dataclass(frozen=True)
class Review:
    """A PR-level review (CHANGES_REQUESTED / APPROVED / COMMENTED), not an inline thread."""

    review_id: str
    author: str | None
    body: str
    state: str
    submitted_at: str | None


@dataclass(frozen=True)
class PrFeedback:
    """All of a PR's reviewer feedback, with the three sources kept separate (counted apart)."""

    pr_number: int
    review_threads: tuple[ReviewThread, ...]
    discussion_comments: tuple[DiscussionComment, ...]
    reviews: tuple[Review, ...]


@dataclass(frozen=True)
class ThreadResolveResult:
    """One thread's resolution outcome (per-item; never raises into the batch)."""

    thread_id: str
    success: bool
    comment_added: bool
    error: str | None


@dataclass(frozen=True)
class BatchResolveResult:
    """A batch resolution result. ``success`` is True only if **all** threads resolved."""

    success: bool
    results: tuple[ThreadResolveResult, ...]


def _owner_repo(repo_root: Path) -> tuple[str, str]:
    """The ``(owner, repo)`` pair (for GraphQL variables; REST uses gh's auto-fill placeholders)."""
    proc = _run(
        ["repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"], cwd=repo_root
    )
    if proc.returncode != 0 or "/" not in proc.stdout:
        raise _failed(proc, "failed to resolve owner/repo")
    owner, _, name = proc.stdout.strip().partition("/")
    return owner, name


def _graphql_proc(
    query: str,
    *,
    repo_root: Path,
    str_vars: dict[str, str] | None = None,
    int_vars: dict[str, int] | None = None,
    timeout: int = _READ_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    """Run a ``gh api graphql`` call. String vars via ``-f``, numeric via ``-F`` (typed). Returns
    the raw proc (callers decide raise-vs-capture)."""
    args = ["api", "graphql", "-f", f"query={query}"]
    for key, value in (str_vars or {}).items():
        args += ["-f", f"{key}={value}"]
    for key, value in (int_vars or {}).items():
        args += ["-F", f"{key}={value}"]
    return _run(args, cwd=repo_root, timeout=timeout)


def _graphql(
    query: str,
    *,
    repo_root: Path,
    str_vars: dict[str, str] | None = None,
    int_vars: dict[str, int] | None = None,
    timeout: int = _READ_TIMEOUT,
    what: str,
) -> dict[str, Any]:
    """``_graphql_proc`` + raise-on-failure + parse (the read-op convention)."""
    proc = _graphql_proc(
        query, repo_root=repo_root, str_vars=str_vars, int_vars=int_vars, timeout=timeout
    )
    if proc.returncode != 0:
        raise _failed(proc, what)
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise GitHubError(f"unparseable graphql output ({what}): {exc}") from exc
    if not isinstance(data, dict):
        raise GitHubError(f"unexpected graphql payload ({what}): {data!r}")
    return data


def _nodes(obj: Any, *path: str) -> list[dict[str, Any]]:
    """Walk ``obj[path...]`` (None-safe) to a ``{nodes: [...]}`` and return its node list."""
    cur: Any = obj
    for key in path:
        cur = (cur or {}).get(key) if isinstance(cur, dict) else None
    nodes = (cur or {}).get("nodes") if isinstance(cur, dict) else None
    return [n for n in nodes if isinstance(n, dict)] if isinstance(nodes, list) else []


def _parse_review_threads(payload: dict[str, Any]) -> tuple[ReviewThread, ...]:
    pr = ((payload.get("data") or {}).get("repository") or {}).get("pullRequest") or {}
    threads: list[ReviewThread] = []
    for node in _nodes(pr, "reviewThreads"):
        comments = tuple(
            ReviewComment(
                comment_id=int(c["databaseId"]) if c.get("databaseId") is not None else None,
                body=str(c.get("body", "")),
                author=((c.get("author") or {}).get("login")),
                path=c.get("path"),
                line=c.get("line"),
                created_at=c.get("createdAt"),
            )
            for c in _nodes(node, "comments")
        )
        threads.append(
            ReviewThread(
                thread_id=str(node.get("id", "")),
                is_resolved=bool(node.get("isResolved", False)),
                is_outdated=bool(node.get("isOutdated", False)),
                path=node.get("path"),
                line=node.get("line"),
                comments=comments,
            )
        )
    return tuple(threads)


def _parse_reviews(payload: dict[str, Any]) -> tuple[Review, ...]:
    pr = ((payload.get("data") or {}).get("repository") or {}).get("pullRequest") or {}
    return tuple(
        Review(
            review_id=str(node.get("id", "")),
            author=((node.get("author") or {}).get("login")),
            body=str(node.get("body", "")),
            state=str(node.get("state", "")),
            submitted_at=node.get("submittedAt"),
        )
        for node in _nodes(pr, "reviews")
    )


def get_pr_feedback(*, pr_number: int, repo_root: Path) -> PrFeedback:
    """Fetch a PR's reviewer feedback: review threads + PR-level reviews (GraphQL) and discussion
    comments (REST). The three sources are kept **separate** (counted apart). Read-only; raises
    ``GitHubError`` on an infra failure. This is what the classify child runs (`perk pr-feedback`).
    """
    owner, repo = _owner_repo(repo_root)
    threads_payload = _graphql(
        GET_PR_REVIEW_THREADS_QUERY,
        repo_root=repo_root,
        str_vars={"owner": owner, "repo": repo},
        int_vars={"number": pr_number},
        what=f"failed to fetch review threads for PR #{pr_number}",
    )
    reviews_payload = _graphql(
        GET_PR_REVIEWS_QUERY,
        repo_root=repo_root,
        str_vars={"owner": owner, "repo": repo},
        int_vars={"number": pr_number},
        what=f"failed to fetch reviews for PR #{pr_number}",
    )
    comments_proc = _run(
        ["api", f"repos/{{owner}}/{{repo}}/issues/{pr_number}/comments"], cwd=repo_root
    )
    if comments_proc.returncode != 0:
        raise _failed(comments_proc, f"failed to fetch discussion comments for PR #{pr_number}")
    try:
        raw_comments = json.loads(comments_proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise GitHubError(f"unparseable issue comments output: {exc}") from exc
    discussion = tuple(
        DiscussionComment(
            comment_id=int(c["id"]),
            body=str(c.get("body", "")),
            author=((c.get("user") or {}).get("login")),
            created_at=c.get("created_at"),
        )
        for c in (raw_comments if isinstance(raw_comments, list) else [])
        if isinstance(c, dict) and "id" in c
    )
    return PrFeedback(
        pr_number=pr_number,
        review_threads=_parse_review_threads(threads_payload),
        discussion_comments=discussion,
        reviews=_parse_reviews(reviews_payload),
    )


def _resolve_single(*, thread_id: str, comment: str | None, repo_root: Path) -> ThreadResolveResult:
    """Reply (optional) then resolve one thread. Captures failure per-item (never raises into the
    batch); an already-resolved thread re-resolves to success (the mutation is idempotent)."""
    comment_added = False
    if comment:
        reply = _graphql_proc(
            ADD_REVIEW_THREAD_REPLY_MUTATION,
            repo_root=repo_root,
            str_vars={"threadId": thread_id, "body": comment},
            timeout=_WRITE_TIMEOUT,
        )
        if reply.returncode != 0:
            return ThreadResolveResult(
                thread_id=thread_id,
                success=False,
                comment_added=False,
                error=(reply.stderr + reply.stdout).strip() or "reply failed",
            )
        comment_added = True
    resolved = _graphql_proc(
        RESOLVE_REVIEW_THREAD_MUTATION,
        repo_root=repo_root,
        str_vars={"threadId": thread_id},
        timeout=_WRITE_TIMEOUT,
    )
    if resolved.returncode != 0:
        return ThreadResolveResult(
            thread_id=thread_id,
            success=False,
            comment_added=comment_added,
            error=(resolved.stderr + resolved.stdout).strip() or "resolve failed",
        )
    return ThreadResolveResult(
        thread_id=thread_id, success=True, comment_added=comment_added, error=None
    )


def resolve_review_threads(
    *, batch: list[dict[str, Any]], repo_root: Path, dry_run: bool = False
) -> BatchResolveResult:
    """Reply-then-resolve a batch of review threads. ``batch`` items are ``{thread_id, comment?}``.
    Top-level ``success`` is True only when **all** resolved. Per-item failures are captured;
    a hard infra failure (gh missing / timeout) raises ``GitHubError`` (via ``_run``)."""
    if dry_run:
        results = tuple(
            ThreadResolveResult(
                thread_id=str(item["thread_id"]),
                success=True,
                comment_added=bool(item.get("comment")),
                error=None,
            )
            for item in batch
        )
        return BatchResolveResult(success=True, results=results)
    results = tuple(
        _resolve_single(
            thread_id=str(item["thread_id"]), comment=item.get("comment"), repo_root=repo_root
        )
        for item in batch
    )
    return BatchResolveResult(success=all(r.success for r in results), results=results)
