import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from perk import plan
from perk.github import _exec, plans

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
    base_ref: str = ""  # the PR's actual base branch (from REST `base.ref`); "" when synthetic


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
    # The issue's GitHub state (``OPEN``/``CLOSED``, uppercase as `gh issue view` returns it).
    # ``perk replan`` requires an OPEN plan so its in-place ``run_id`` upsert re-targets the same
    # issue rather than silently creating a new one.
    state: str = ""


def _owner(repo_root: Path) -> str:
    """The repo owner login (for the ``head=<owner>:<branch>`` PR list filter)."""
    proc = _exec._run(["repo", "view", "--json", "owner", "--jq", ".owner.login"], cwd=repo_root)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise _exec._failed(proc, "failed to resolve repo owner")
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
        base_ref=str((pr.get("base") or {}).get("ref", "")),
    )


def default_branch(repo_root: Path) -> str:
    """The repo's default branch (the PR base). Raises ``GitHubError`` on failure."""
    proc = _exec._run(
        ["repo", "view", "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name"],
        cwd=repo_root,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise _exec._failed(proc, "failed to resolve the default branch")
    return proc.stdout.strip()


def find_pr_for_branch(*, branch: str, repo_root: Path) -> PullRequest | None:
    """Find a PR whose head is ``branch`` (idempotency lookup; list endpoint, all states).

    Prefers an open PR (the submit-reuse case); raises on an infra failure, never masks it.
    """
    items = _exec._run_json(
        _exec._rest_args(
            "repos/{owner}/{repo}/pulls",
            method="GET",
            fields={"head": f"{_owner(repo_root)}:{branch}", "state": "all"},
        ),
        what=f"failed to list PRs for {branch!r}",
        source="`gh api pulls`",
        cwd=repo_root,
        default="[]",
    )
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
    with _exec._body_file(body) as body_path:
        args = _exec._rest_args(
            "repos/{owner}/{repo}/pulls",
            method="POST",
            fields={"title": title, "head": head, "base": base},
            body_path=body_path,
        )
        args += [
            "-F",
            f"draft={'true' if draft else 'false'}",
            "--jq",
            "{number: .number, html_url: .html_url, draft: .draft, state: .state, "
            "base: {ref: .base.ref}}",
        ]
        data = _exec._run_json(
            args,
            what="failed to create PR",
            source="`gh api pulls` create",
            cwd=repo_root,
            timeout=_exec._WRITE_TIMEOUT,
        )
    if not isinstance(data, dict):
        raise _exec.GitHubError(f"unexpected create-PR payload: {data!r}")
    return _pull_request(data, existed=False)


def update_plan_header(
    *, issue: int, fields: dict[str, object], repo_root: Path, dry_run: bool = False
) -> PlanHeaderUpdate:
    """Merge ``fields`` into the issue body's ``plan-header`` block and PATCH it (REST).

    Rejects unknown header keys (LBYL on the schema). A dry run validates + composes only.
    """
    unknown = set(fields) - plan.PLAN_HEADER_FIELDS
    if unknown:
        raise _exec.GitHubError(f"unknown plan-header field(s): {sorted(unknown)}")
    body = plans._get_issue_body(issue, repo_root)
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
    body = plans._get_issue_body(issue, repo_root)
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
) -> plans.CommentResult:
    """Post-or-update a single marker-keyed issue comment (idempotent on ``marker``).

    ``find_comment_id_by_marker`` -> PATCH the existing comment (``_patch_comment_body``) when
    found, else POST a fresh one (``add_issue_comment``). ``body`` MUST already embed ``marker``
    (the caller's responsibility) so the next upsert can find it. Lets a single comment evolve in
    place (started -> terminal) rather than spamming the issue. Returns the existing
    :class:`CommentResult` (``posted=False`` on dry run); raises ``GitHubError`` on infra failure.
    """
    if dry_run:
        return plans.CommentResult(posted=False)
    comment_id = find_comment_id_by_marker(issue=issue, marker=marker, repo_root=repo_root)
    if comment_id is not None:
        plans._patch_comment_body(comment_id, body, repo_root)
        return plans.CommentResult(posted=True)
    return plans.add_issue_comment(issue=issue, body=body, repo_root=repo_root)


def update_plan_issue(
    *,
    number: int,
    title: str,
    body_comment: str,
    repo_root: Path,
    dry_run: bool = False,
) -> plans.PlanUpdate:
    """Upsert an existing plan issue in place (the idempotent re-save path; contracts.md §8.4).

    PATCHes the ``plan-body`` comment with the revised markdown and PATCHes the issue title from
    the (possibly revised) plan H1. The anti-duplicate guarantee stays in ``create_plan_issue``;
    this only rewrites the existing issue's content. Legacy issues missing the ``plan-body``
    comment get a fresh comment POSTed (``body_updated`` False) so the plan body is never stranded.
    """
    if dry_run:
        return plans.PlanUpdate(
            number=number, body_updated=False, title_updated=False, dry_run=True
        )

    comment_id = _find_plan_body_comment_id(number, repo_root)
    if comment_id is not None:
        plans._patch_comment_body(comment_id, body_comment, repo_root)
        body_updated = True
    else:
        plans.add_issue_comment(issue=number, body=body_comment, repo_root=repo_root)
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
    return plans.PlanUpdate(
        number=number, body_updated=body_updated, title_updated=True, dry_run=False
    )


def get_pr(*, number: int, repo_root: Path) -> PullRequest | None:
    """Fetch a PR by number (REST). ``None`` if it does not exist; raises on infra failure."""
    data = _exec._run_json(
        ["api", f"repos/{{owner}}/{{repo}}/pulls/{number}"],
        what=f"failed to read PR #{number}",
        source=f"`gh api pulls/{number}`",
        cwd=repo_root,
        none_on_not_found=True,
    )
    if data is None:
        return None
    return _pull_request(data, existed=True)


def get_pr_body(*, number: int, repo_root: Path) -> str | None:
    """Fetch a PR's body markdown (REST). ``None`` if the PR does not exist; raises on infra
    failure. Used by ``perk pr check`` to re-validate the live checkout footer (P2.T8a)."""
    proc = _exec._run(
        ["api", f"repos/{{owner}}/{{repo}}/pulls/{number}", "--jq", ".body"], cwd=repo_root
    )
    if proc.returncode != 0:
        if _exec._is_not_found(proc):
            return None
        raise _exec._failed(proc, f"failed to read PR #{number} body")
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
    with _exec._body_file(body) as body_path:
        proc = _exec._run(
            _exec._rest_args(
                f"repos/{{owner}}/{{repo}}/pulls/{number}", method="PATCH", body_path=body_path
            ),
            cwd=repo_root,
            timeout=_exec._WRITE_TIMEOUT,
        )
    if proc.returncode != 0:
        raise _exec._failed(proc, f"failed to update PR #{number} body")
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
        state=str(data.get("state", "")),
    )


def get_plan_body(*, number: int, repo_root: Path) -> str | None:
    """Fetch a plan issue's verbatim plan markdown (the ``plan-body`` block lives in the first
    comment; the issue body holds only the header). ``None`` when the issue or block is absent;
    raises ``GitHubError`` on an infra failure. Used to materialize the plan body for in-session
    checkpoints (P2.T2c).
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


def mark_pr_ready(*, number: int, repo_root: Path, dry_run: bool = False) -> None:
    """Mark a draft PR ready for review (the lone GraphQL op — there is no REST endpoint).

    Called only on a draft PR (the worker checks `is_draft` first); raises on failure.
    """
    if dry_run:
        return
    proc = _exec._run(["pr", "ready", str(number)], cwd=repo_root, timeout=_exec._WRITE_TIMEOUT)
    if proc.returncode != 0:
        raise _exec._failed(proc, f"failed to mark PR #{number} ready")


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
    proc = _exec._run(args, cwd=repo_root, timeout=_exec._WRITE_TIMEOUT)
    if proc.returncode == 0:
        return PullRequest(number=number, url="", is_draft=False, state="MERGED", existed=True)
    if "already merged" in (proc.stderr + proc.stdout).lower():
        return PullRequest(number=number, url="", is_draft=False, state="MERGED", existed=True)
    raise _exec._failed(proc, f"failed to merge PR #{number}")
