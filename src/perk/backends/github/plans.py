from dataclasses import dataclass
from pathlib import Path
from typing import Any

from perk import plan
from perk.boundary import LenientParseModel, translate_validation_errors
from perk.github import _exec, prs

# ===========================================================================
# Mutation operations (the first GitHub *writes*; contracts.md §8.4).
#
# Conventions established here and reused by submit/land:
#   * REST `gh api` over porcelain (porcelain uses GraphQL -> a separate, often-exhausted
#     rate-limit quota).
#   * Large bodies via `-F body=@<file>`, never inline (ARG_MAX + abuse detection).
#   * Idempotency keyed on the header `run_id`, discovered via the list endpoint (not the
#     eventually-consistent search index), create-then-return.
#   * Error model by caller behaviour: `find_plan_issue` is a lookup -> returns `... | None`;
#     the mutations terminate on failure -> **raise** `GitHubError` (the command boundary
#     maps it to `UserFacingCliError`). The read helpers keep their result dataclasses because
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

    Parameterized by ``label``/``header_key``: the defaults find the ``perk:plan`` issue
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
    """Close an issue (PATCH ``state=closed``) — the supervisor's completion-audit auto-close.

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


def reopen_issue(*, number: int, repo_root: Path, dry_run: bool = False) -> bool:
    """Reopen a closed issue (GET ``state``, then PATCH ``state=open``) — converge-to-open.

    The mirror of :func:`close_issue` for the reopen-on-incomplete invariant: returns ``True``
    iff a reopen write actually happened; an already-open issue returns ``False`` without a
    write (converge, not toggle). Fail-loud: raises ``GitHubError`` on an infra failure.
    ``dry_run`` returns ``False`` without shelling.
    """
    if dry_run:
        return False
    issue = _exec._run_json(
        _exec._rest_args(f"repos/{{owner}}/{{repo}}/issues/{number}", method="GET"),
        what=f"failed to read issue #{number}",
        source="`gh api issues/{n}`",
        cwd=repo_root,
    )
    state = issue.get("state") if isinstance(issue, dict) else None
    if state == "open":
        return False
    state_proc = _exec._run(
        _exec._rest_args(
            f"repos/{{owner}}/{{repo}}/issues/{number}", method="PATCH", fields={"state": "open"}
        ),
        cwd=repo_root,
        timeout=_exec._WRITE_TIMEOUT,
    )
    if state_proc.returncode != 0:
        raise _exec._failed(state_proc, f"failed to reopen issue #{number}")
    return True


def find_learn_issue(*, run_id: str, repo_root: Path) -> PlanIssue | None:
    """Find an open ``perk:learn`` issue whose ``learn-header`` ``run_id`` matches.

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
    decision: str | None = None,
    target: str | None = None,
    dry_run: bool = False,
) -> PlanIssue:
    """Create the ``perk:learn`` knowledge-capture issue. Mirrors
    ``create_plan_issue`` but: lazily creates the ``perk:learn`` label, is **idempotent via
    ``find_learn_issue``** (not ``find_plan_issue``), and renders a ``learn-header`` block into the
    body so the finder can match. The optional ``decision``/``target`` captured classification
    rides the header (contracts.md §8.35). Raises ``GitHubError`` on failure."""
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
    header = plan.render_learn_header(
        run_id=run_id,
        created=plan.now_iso(),
        plan=plan_number,
        decision=decision,
        target=target,
        style="html",
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
    """A pre-existing issue read verbatim for in-place adoption (§8.29).

    ``title``/``body`` are untrusted human DATA; ``state`` is ``gh issue view``'s normalized
    ``"OPEN" | "CLOSED"`` casing.
    """

    number: int
    url: str
    title: str
    body: str
    state: str


class IssueReadModel(LenientParseModel):
    """Lenient parse of a ``gh issue view`` payload (the ``read_issue`` boundary).

    ``number`` is the issue identity and is required — ``gh issue view`` always returns it on a
    0-exit read, so a present-but-malformed payload raises a ``ValidationError`` the call site
    maps to a labelled ``GitHubError``. The keys are already snake/lower (no ``Field`` aliases).
    """

    number: int
    url: str = ""
    title: str = ""
    body: str = ""
    state: str = ""

    def to_domain(self) -> IssueRead:
        return IssueRead(
            number=self.number,
            url=self.url,
            title=self.title,
            body=self.body,
            state=self.state,
        )


def read_issue(*, number: int, repo_root: Path) -> IssueRead | None:
    """Read *any* issue's raw title + body + state for in-place adoption (§8.29).

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
    with translate_validation_errors(_exec.GitHubError, source=f"read issue #{number}"):
        return IssueReadModel.model_validate(data).to_domain()


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
# acyclic).


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


# ===========================================================================
# Plan-issue operations relocated from the PR gateway.
#
# These are plan-issue ops, coupled to the shared REST helpers above (`_get_issue_body`,
# `_patch_comment_body`, `add_issue_comment`, `read_issue`, `create_label`, `add_issue_label`) and
# the `CommentResult`/`PlanUpdate` dataclasses — so they belong with the plan-issue substrate, not
# the pure forge gateway. The lone PR-tier dependency is `get_plan` reading the linked PR via
# `prs.get_pr` (backend→gateway, the allowed import direction).
# ===========================================================================


@dataclass(frozen=True)
class PlanHeaderUpdate:
    """The result of a staged ``plan-header`` field write."""

    fields_updated: tuple[str, ...]
    dry_run: bool


@dataclass(frozen=True)
class PlanState:
    """A plan issue's observable state (for ``perk resume``): the parsed header + PR (if any)."""

    number: int
    url: str
    title: str
    header: dict[str, object]
    pr: prs.PullRequest | None
    # The issue's GitHub state (``OPEN``/``CLOSED``, uppercase as `gh issue view` returns it).
    # ``perk replan`` requires an OPEN plan so its in-place ``run_id`` upsert re-targets the same
    # issue rather than silently creating a new one.
    state: str = ""


def update_plan_header(
    *, issue: int, fields: dict[str, object], repo_root: Path, dry_run: bool = False
) -> PlanHeaderUpdate:
    """Merge ``fields`` into the issue body's ``plan-header`` block and PATCH it (REST).

    Rejects unknown header keys (LBYL on the schema). A dry run validates + composes only.
    """
    unknown = set(fields) - plan.PLAN_HEADER_FIELDS
    if unknown:
        raise _exec.GitHubError(f"unknown plan-header field(s): {sorted(unknown)}")
    body = _get_issue_body(issue, repo_root)
    header = plan.find_metadata_block(body, plan.PLAN_HEADER_KEY) or {}
    new_body = plan.replace_metadata_block(body, plan.PLAN_HEADER_KEY, {**header, **fields})
    if dry_run:
        return PlanHeaderUpdate(fields_updated=tuple(fields), dry_run=True)
    with _exec._body_file(new_body) as body_path:
        proc = _exec._run(
            _exec._rest_args(
                f"repos/{{owner}}/{{repo}}/issues/{issue}", method="PATCH", body_path=body_path
            ),
            cwd=repo_root,
            timeout=_exec._WRITE_TIMEOUT,
        )
    if proc.returncode != 0:
        raise _exec._failed(proc, f"failed to update plan-header on #{issue}")
    return PlanHeaderUpdate(fields_updated=tuple(fields), dry_run=False)


def prepend_plan_callout(
    *, issue: int, callout: str, command: str, repo_root: Path, dry_run: bool = False
) -> bool:
    """Idempotently prepend ``callout`` above the plan issue's description and PATCH it (REST).

    Keyed on the literal ``command`` string (``plan.prepend_callout``): a no-op when the callout
    is already present. Returns True when a write occurred, False when already present or on a
    dry run.
    """
    body = _get_issue_body(issue, repo_root)
    new_body = plan.prepend_callout(body, callout, command=command)
    if new_body == body:
        return False
    if dry_run:
        return False
    with _exec._body_file(new_body) as body_path:
        proc = _exec._run(
            _exec._rest_args(
                f"repos/{{owner}}/{{repo}}/issues/{issue}", method="PATCH", body_path=body_path
            ),
            cwd=repo_root,
            timeout=_exec._WRITE_TIMEOUT,
        )
    if proc.returncode != 0:
        raise _exec._failed(proc, f"failed to prepend plan callout on #{issue}")
    return True


def _find_plan_body_comment_id(issue: int, repo_root: Path) -> int | None:
    """Find the integer id of the issue comment carrying the ``plan-body`` block (REST list).

    perk does not store the plan-body comment id, so the re-save path discovers it by marker
    (mirrors :func:`get_plan_body`). The REST list returns an **integer** ``id`` usable for the
    comment-PATCH endpoint (the GraphQL node id from ``gh issue view`` is not). ``None`` when no
    comment matches (legacy issue / comment missing)."""
    raw = _exec._run_json(
        ["api", f"repos/{{owner}}/{{repo}}/issues/{issue}/comments"],
        what=f"failed to list comments on issue #{issue}",
        source="issue comments",
        cwd=repo_root,
        default="[]",
    )
    for c in raw if isinstance(raw, list) else []:
        if not isinstance(c, dict) or "id" not in c:
            continue
        if plan.extract_plan_body(str(c.get("body", ""))) is not None:
            return int(c["id"])
    return None


def find_comment_id_by_marker(*, issue: int, marker: str, repo_root: Path) -> int | None:
    """Find the integer id of the first issue comment whose body contains ``marker`` (REST list).

    Mirrors :func:`_find_plan_body_comment_id` (the REST list + integer-``id`` discipline — the
    GraphQL node id from ``gh issue view`` is not usable for the comment-PATCH endpoint). Used by
    :func:`upsert_marked_comment` to evolve a single marker-keyed comment (e.g. the per-run
    ``run-report`` note). ``None`` when no comment matches; raises ``GitHubError`` on infra failure.
    """
    raw = _exec._run_json(
        ["api", f"repos/{{owner}}/{{repo}}/issues/{issue}/comments"],
        what=f"failed to list comments on issue #{issue}",
        source="issue comments",
        cwd=repo_root,
        default="[]",
    )
    for c in raw if isinstance(raw, list) else []:
        if not isinstance(c, dict) or "id" not in c:
            continue
        if marker in str(c.get("body", "")):
            return int(c["id"])
    return None


def upsert_marked_comment(
    *, issue: int, marker: str, body: str, repo_root: Path, dry_run: bool = False
) -> CommentResult:
    """Post-or-update a single marker-keyed issue comment (idempotent on ``marker``).

    ``find_comment_id_by_marker`` -> PATCH the existing comment (``_patch_comment_body``) when
    found, else POST a fresh one (``add_issue_comment``). ``body`` MUST already embed ``marker``
    (the caller's responsibility) so the next upsert can find it. Lets a single comment evolve in
    place (started -> terminal) rather than spamming the issue. Returns the existing
    :class:`CommentResult` (``posted=False`` on dry run); raises ``GitHubError`` on infra failure.
    """
    if dry_run:
        return CommentResult(posted=False)
    comment_id = find_comment_id_by_marker(issue=issue, marker=marker, repo_root=repo_root)
    if comment_id is not None:
        _patch_comment_body(comment_id, body, repo_root)
        return CommentResult(posted=True)
    return add_issue_comment(issue=issue, body=body, repo_root=repo_root)


def update_plan_issue(
    *,
    number: int,
    title: str,
    body_comment: str,
    repo_root: Path,
    dry_run: bool = False,
) -> PlanUpdate:
    """Upsert an existing plan issue in place (the idempotent re-save path; contracts.md §8.4).

    PATCHes the ``plan-body`` comment with the revised markdown and PATCHes the issue title from
    the (possibly revised) plan H1. The anti-duplicate guarantee stays in ``create_plan_issue``;
    this only rewrites the existing issue's content. Legacy issues missing the ``plan-body``
    comment get a fresh comment POSTed (``body_updated`` False) so the plan body is never stranded.
    """
    if dry_run:
        return PlanUpdate(number=number, body_updated=False, title_updated=False, dry_run=True)

    comment_id = _find_plan_body_comment_id(number, repo_root)
    if comment_id is not None:
        _patch_comment_body(comment_id, body_comment, repo_root)
        body_updated = True
    else:
        add_issue_comment(issue=number, body=body_comment, repo_root=repo_root)
        body_updated = False

    proc = _exec._run(
        _exec._rest_args(
            f"repos/{{owner}}/{{repo}}/issues/{number}", method="PATCH", fields={"title": title}
        ),
        cwd=repo_root,
        timeout=_exec._WRITE_TIMEOUT,
    )
    if proc.returncode != 0:
        raise _exec._failed(proc, f"failed to update plan issue #{number} title")
    return PlanUpdate(number=number, body_updated=body_updated, title_updated=True, dry_run=False)


@dataclass(frozen=True)
class PlanAdoption:
    """The result of an in-place :func:`adopt_issue_as_plan` stamp (§8.29)."""

    number: int
    url: str
    dry_run: bool


def adopt_issue_as_plan(
    *,
    number: int,
    header_fields: dict[str, object],
    plan_markdown: str,
    callout: str,
    command: str,
    repo_root: Path,
    dry_run: bool = False,
) -> PlanAdoption:
    """Additively stamp perk plan metadata INTO a pre-existing issue — adopting it in place as a
    perk plan (§8.29), never minting a second object.

    The additive stamp (the GitHub in-place writer): (a) ensure + ADD the ``perk:plan`` label
    (never replaces the issue's labels); (b) stamp the ``plan-header`` block additively into the
    issue body (human prose preserved verbatim, **title untouched**) and (c) prepend the
    ``callout`` above it — one read-modify-write so both land in a single PATCH; (d) upsert the
    ``plan-body`` comment carrying ``plan_markdown`` (the same comment-discovery as
    :func:`update_plan_issue`, **without** the title PATCH). Idempotent on re-save. Rejects
    unknown header keys (LBYL on the schema). Raises ``GitHubError`` on an infra failure;
    ``dry_run`` reads only.
    """
    unknown = set(header_fields) - plan.PLAN_HEADER_FIELDS
    if unknown:
        raise _exec.GitHubError(f"unknown plan-header field(s): {sorted(unknown)}")
    src = read_issue(number=number, repo_root=repo_root)
    if src is None:
        raise _exec.GitHubError(f"issue #{number} not found")
    if dry_run:
        return PlanAdoption(number=number, url=src.url, dry_run=True)
    # (a) ensure + additively add the perk:plan label.
    create_label(
        plan.PLAN_LABEL,
        color=plan.PLAN_LABEL_COLOR,
        description=plan.PLAN_LABEL_DESCRIPTION,
        repo_root=repo_root,
    )
    add_issue_label(issue=number, label=plan.PLAN_LABEL, repo_root=repo_root)
    # (b)+(c) stamp the header additively + prepend the callout in one read-modify-write (title
    # untouched: only the issue *body* is PATCHed, never the title).
    body = _get_issue_body(number, repo_root)
    header = plan.find_metadata_block(body, plan.PLAN_HEADER_KEY) or {}
    new_body = plan.replace_metadata_block(body, plan.PLAN_HEADER_KEY, {**header, **header_fields})
    new_body = plan.prepend_callout(new_body, callout, command=command)
    with _exec._body_file(new_body) as body_path:
        proc = _exec._run(
            _exec._rest_args(
                f"repos/{{owner}}/{{repo}}/issues/{number}", method="PATCH", body_path=body_path
            ),
            cwd=repo_root,
            timeout=_exec._WRITE_TIMEOUT,
        )
    if proc.returncode != 0:
        raise _exec._failed(proc, f"failed to stamp plan-header on #{number}")
    # (d) upsert the plan-body comment (the update_plan_issue discovery, minus the title PATCH).
    body_comment = plan.render_plan_body(plan_markdown)
    comment_id = _find_plan_body_comment_id(number, repo_root)
    if comment_id is not None:
        _patch_comment_body(comment_id, body_comment, repo_root)
    else:
        add_issue_comment(issue=number, body=body_comment, repo_root=repo_root)
    return PlanAdoption(number=number, url=src.url, dry_run=False)


def get_plan(*, number: int, repo_root: Path) -> PlanState | None:
    """Read a plan issue's observable state (header + PR) for ``perk resume``.

    ``None`` when the issue does not exist; raises ``GitHubError`` on an infra failure.
    """
    data = _exec._run_json(
        ["issue", "view", str(number), "--json", "number,title,body,state,url"],
        what=f"failed to read plan issue #{number}",
        source="`gh issue view`",
        cwd=repo_root,
        none_on_not_found=True,
    )
    if data is None:
        return None
    header = plan.find_metadata_block(str(data.get("body", "")), plan.PLAN_HEADER_KEY) or {}
    pr_field = header.get("pr")
    pr = (
        prs.get_pr(number=int(pr_field), repo_root=repo_root)
        if isinstance(pr_field, str | int) and str(pr_field).strip() and str(pr_field) != "None"
        else None
    )
    return PlanState(
        number=int(data["number"]) if "number" in data else number,
        url=str(data.get("url", "")),
        title=str(data.get("title", "")),
        header=header,
        pr=pr,
        state=str(data.get("state", "")),
    )


def get_plan_body(*, number: int, repo_root: Path) -> str | None:
    """Fetch a plan issue's verbatim plan markdown (the ``plan-body`` block lives in the first
    comment; the issue body holds only the header). ``None`` when the issue or block is absent;
    raises ``GitHubError`` on an infra failure. Used to materialize the plan body for in-session
    checkpoints.
    """
    data = _exec._run_json(
        ["issue", "view", str(number), "--json", "body,comments"],
        what=f"failed to read plan issue #{number}",
        source="`gh issue view`",
        cwd=repo_root,
        none_on_not_found=True,
    )
    if data is None:
        return None
    candidates = [str(data.get("body", ""))]
    comments = data.get("comments")
    if isinstance(comments, list):
        candidates.extend(str(c.get("body", "")) for c in comments if isinstance(c, dict))
    for text in candidates:
        body = plan.extract_plan_body(text)
        if body:
            return body
    return None
