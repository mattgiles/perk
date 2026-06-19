from dataclasses import dataclass
from pathlib import Path
from typing import Any

from perk import plan
from perk.github import _exec

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


@dataclass(frozen=True)
class PlanUpdate:
    """The result of an in-place ``update_plan_issue`` upsert (re-save path).

    ``body_updated`` is True when the existing ``plan-body`` comment was PATCHed; False when no
    such comment was found and a fresh one was POSTed instead (legacy fallback) or on a dry run.
    """

    number: int
    body_updated: bool
    title_updated: bool
    dry_run: bool


def _list_label_issues(label: str, *, repo_root: Path, what: str) -> list[Any]:
    """The shared label-scoped open-issue LIST read (the **list** endpoint, not the
    eventually-consistent search index). Returns the raw issue list (``[]`` when the payload is
    not a list); callers keep their own per-entry filtering/mapping. Raises ``GitHubError`` on an
    infra/query failure (never masks it)."""
    issues = _exec._run_json(
        _exec._rest_args(
            "repos/{owner}/{repo}/issues",
            method="GET",
            fields={"labels": label, "state": "open"},
        ),
        what=what,
        source="`gh api issues`",
        cwd=repo_root,
        default="[]",
    )
    return issues if isinstance(issues, list) else []


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
    proc = _exec._run(
        _exec._rest_args(
            "repos/{owner}/{repo}/labels",
            method="POST",
            fields={"name": name, "color": color, "description": description},
        ),
        cwd=repo_root,
        timeout=_exec._WRITE_TIMEOUT,
    )
    if proc.returncode == 0:
        return Label(name=name, created=True)
    if "already_exists" in (proc.stderr + proc.stdout) or "HTTP 422" in (proc.stderr + proc.stdout):
        return Label(name=name, created=False)
    raise _exec._failed(proc, f"failed to create label {name!r}")


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
    issues = _list_label_issues(label, repo_root=repo_root, what="failed to list plan issues")
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        body = issue.get("body")
        if isinstance(body, str) and plan.extract_run_id(body, header_key=header_key) == run_id:
            return PlanIssue(
                number=int(issue["number"]), url=str(issue.get("html_url", "")), existed=True
            )
    return None


@dataclass(frozen=True)
class LearnIssueSummary:
    """An open ``perk:learn`` issue, materialized for the learn-docs factory inbox (hop-2)."""

    number: int
    title: str
    url: str
    body: str


def list_learn_issues(*, repo_root: Path) -> tuple[LearnIssueSummary, ...]:
    """List every open ``perk:learn`` issue (number/title/url/body) for the learn-docs factory.

    Reuses the ``find_plan_issue`` list call (the LIST endpoint, not the eventually-consistent
    search index), scoped to ``perk:learn``. Raises ``GitHubError`` on an infra/query failure
    (never masks it as an empty list); skips non-dict entries.
    """
    issues = _list_label_issues(
        plan.LEARN_LABEL, repo_root=repo_root, what="failed to list learn issues"
    )
    summaries: list[LearnIssueSummary] = []
    for issue in issues:
        if not isinstance(issue, dict) or "number" not in issue:
            continue
        # `gh api .../issues` returns PRs too; the perk:learn label filter excludes them, but guard
        # defensively against any pull_request entry leaking through.
        if "pull_request" in issue:
            continue
        summaries.append(
            LearnIssueSummary(
                number=int(issue["number"]),
                title=str(issue.get("title", "")),
                url=str(issue.get("html_url", "")),
                body=str(issue.get("body", "")),
            )
        )
    return tuple(summaries)


def close_and_label_consolidated(*, issue: int, repo_root: Path, dry_run: bool = False) -> bool:
    """Close a consumed ``perk:learn`` issue + add the ``perk:consolidated`` label (hop-2, on land).

    Lazily creates the ``perk:consolidated`` label, ADDS it (POST ``.../labels`` — does not replace
    the issue's existing labels), then PATCHes the issue ``state=closed``. Idempotent: re-closing /
    re-labelling an already-consolidated issue is success. Returns ``True`` on success; raises
    ``GitHubError`` on an infra failure.
    """
    if dry_run:
        return True
    create_label(
        plan.CONSOLIDATED_LABEL,
        color=plan.CONSOLIDATED_LABEL_COLOR,
        description=plan.CONSOLIDATED_LABEL_DESCRIPTION,
        repo_root=repo_root,
    )
    label_proc = _exec._run(
        _exec._rest_args(
            f"repos/{{owner}}/{{repo}}/issues/{issue}/labels",
            method="POST",
            fields={"labels[]": plan.CONSOLIDATED_LABEL},
        ),
        cwd=repo_root,
        timeout=_exec._WRITE_TIMEOUT,
    )
    if label_proc.returncode != 0:
        raise _exec._failed(label_proc, f"failed to label issue #{issue} consolidated")
    state_proc = _exec._run(
        _exec._rest_args(
            f"repos/{{owner}}/{{repo}}/issues/{issue}", method="PATCH", fields={"state": "closed"}
        ),
        cwd=repo_root,
        timeout=_exec._WRITE_TIMEOUT,
    )
    if state_proc.returncode != 0:
        raise _exec._failed(state_proc, f"failed to close issue #{issue}")
    return True


def close_issue(*, number: int, repo_root: Path, dry_run: bool = False) -> bool:
    """Close an issue (PATCH ``state=closed``) — the supervisor's completion-audit auto-close (D8).

    Mirrors :func:`close_and_label_consolidated`'s REST PATCH shape (minus the labelling). Unlike
    the post-merge bookkeeping path, this is **fail-loud**: a user-invoked completion close raises
    ``GitHubError`` on an infra failure rather than swallowing it. Idempotent: re-closing an
    already-closed issue is success. ``dry_run`` returns ``False`` without shelling.
    """
    if dry_run:
        return False
    state_proc = _exec._run(
        _exec._rest_args(
            f"repos/{{owner}}/{{repo}}/issues/{number}", method="PATCH", fields={"state": "closed"}
        ),
        cwd=repo_root,
        timeout=_exec._WRITE_TIMEOUT,
    )
    if state_proc.returncode != 0:
        raise _exec._failed(state_proc, f"failed to close issue #{number}")
    return True


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
    with _exec._body_file(body) as body_path:
        args = _exec._rest_args(
            "repos/{owner}/{repo}/issues",
            method="POST",
            fields={"title": title},
            body_path=body_path,
        )
        for label in labels:
            args += ["-f", f"labels[]={label}"]
        args += ["--jq", "{number: .number, url: .html_url}"]
        data = _exec._run_json(
            args,
            what="failed to create plan issue",
            source="`gh api issues` create",
            cwd=repo_root,
            timeout=_exec._WRITE_TIMEOUT,
        )
    if not isinstance(data, dict):
        raise _exec.GitHubError(f"unexpected create-issue payload: {data!r}")
    return PlanIssue(number=int(data["number"]), url=str(data["url"]), existed=False)


@dataclass(frozen=True)
class IssueRead:
    """A pre-existing issue read verbatim for in-place adoption (#706, §8.29).

    ``title``/``body`` are untrusted human DATA; ``state`` is ``gh issue view``'s normalized
    ``"OPEN" | "CLOSED"`` casing.
    """

    number: int
    url: str
    title: str
    body: str
    state: str


def read_issue(*, number: int, repo_root: Path) -> IssueRead | None:
    """Read *any* issue's raw title + body + state for in-place adoption (#706, §8.29).

    Unlike :func:`get_plan` / :func:`get_plan_body` (which need a perk metadata block), this reads
    a non-perk human issue verbatim (``gh issue view`` — ``state`` is its ``"OPEN"``/``"CLOSED"``
    casing). ``None`` when the issue does not exist; raises ``GitHubError`` on an infra failure.
    """
    data = _exec._run_json(
        ["issue", "view", str(number), "--json", "number,title,body,state,url"],
        what=f"failed to read issue #{number}",
        source="`gh issue view`",
        cwd=repo_root,
        none_on_not_found=True,
    )
    if data is None:
        return None
    return IssueRead(
        number=int(data["number"]) if "number" in data else number,
        url=str(data.get("url", "")),
        title=str(data.get("title", "")),
        body=str(data.get("body", "")),
        state=str(data.get("state", "")),
    )


def add_issue_label(*, issue: int, label: str, repo_root: Path, dry_run: bool = False) -> bool:
    """Additively ADD ``label`` to an existing issue (POST ``.../labels`` — does **not** replace
    the issue's existing labels; mirrors :func:`close_and_label_consolidated`'s label shape).

    Idempotent: re-adding an already-present label is success. Returns ``True`` on a real add,
    ``False`` on a dry run; raises ``GitHubError`` on an infra failure.
    """
    if dry_run:
        return False
    proc = _exec._run(
        _exec._rest_args(
            f"repos/{{owner}}/{{repo}}/issues/{issue}/labels",
            method="POST",
            fields={"labels[]": label},
        ),
        cwd=repo_root,
        timeout=_exec._WRITE_TIMEOUT,
    )
    if proc.returncode != 0:
        raise _exec._failed(proc, f"failed to add label {label!r} to issue #{issue}")
    return True


def add_issue_comment(
    *, issue: int, body: str, repo_root: Path, dry_run: bool = False
) -> CommentResult:
    """Post a comment on an issue (REST, body via file). Raises on failure."""
    if dry_run:
        return CommentResult(posted=False)
    with _exec._body_file(body) as body_path:
        proc = _exec._run(
            _exec._rest_args(
                f"repos/{{owner}}/{{repo}}/issues/{issue}/comments",
                method="POST",
                body_path=body_path,
            ),
            cwd=repo_root,
            timeout=_exec._WRITE_TIMEOUT,
        )
    if proc.returncode != 0:
        raise _exec._failed(proc, f"failed to comment on issue #{issue}")
    return CommentResult(posted=True)


# The four generic issue/comment REST helpers below are shared plumbing for the
# objective and PR modules (relocated here to keep the intra-package import DAG
# acyclic — see docs/planning/objective-349-perk-layout.md, D3 deviation).


def _get_issue_body(issue: int, repo_root: Path) -> str:
    proc = _exec._run(
        ["api", f"repos/{{owner}}/{{repo}}/issues/{issue}", "--jq", ".body"], cwd=repo_root
    )
    if proc.returncode != 0:
        raise _exec._failed(proc, f"failed to read issue #{issue}")
    return proc.stdout


def _post_comment_with_id(*, issue: int, body: str, repo_root: Path) -> int:
    """Post a comment and return its numeric id (REST, body via file). Raises on failure."""
    with _exec._body_file(body) as body_path:
        data = _exec._run_json(
            _exec._rest_args(
                f"repos/{{owner}}/{{repo}}/issues/{issue}/comments",
                method="POST",
                body_path=body_path,
                jq="{id: .id}",
            ),
            what=f"failed to post objective body comment on #{issue}",
            source="comment-create",
            cwd=repo_root,
            timeout=_exec._WRITE_TIMEOUT,
        )
    if not isinstance(data, dict) or "id" not in data:
        raise _exec.GitHubError(f"unexpected comment-create payload: {data!r}")
    return int(data["id"])


def _get_comment_body(comment_id: int, repo_root: Path) -> str | None:
    proc = _exec._run(
        ["api", f"repos/{{owner}}/{{repo}}/issues/comments/{comment_id}", "--jq", ".body"],
        cwd=repo_root,
    )
    if proc.returncode != 0:
        if _exec._is_not_found(proc):
            return None
        raise _exec._failed(proc, f"failed to read comment #{comment_id}")
    return proc.stdout


def _patch_comment_body(comment_id: int, body: str, repo_root: Path) -> None:
    with _exec._body_file(body) as body_path:
        proc = _exec._run(
            _exec._rest_args(
                f"repos/{{owner}}/{{repo}}/issues/comments/{comment_id}",
                method="PATCH",
                body_path=body_path,
            ),
            cwd=repo_root,
            timeout=_exec._WRITE_TIMEOUT,
        )
    if proc.returncode != 0:
        raise _exec._failed(proc, f"failed to update comment #{comment_id}")
