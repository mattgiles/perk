import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from pydantic import AliasChoices, Field

from perk.boundary import LenientParseModel, translate_validation_errors
from perk.github import _exec

# ===========================================================================
# Review-feedback ops (the `/address` loop; contracts.md §8.4).
#
# Review threads and their resolution are **GraphQL-only** (there is no REST endpoint for
# `isResolved` or the `resolveReviewThread`/`addPullRequestReviewThreadReply` mutations), so these
# ops shell `gh api graphql` (the lone exceptions to the REST-over-porcelain convention, alongside
# `mark_pr_ready`). Discussion comments live on the issue and stay REST. The GraphQL shapes are
# durable prior art (§8.4).
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


class _Actor(LenientParseModel):
    """A GraphQL ``Actor`` selection (``{login}``); ``login`` is null when the actor is absent."""

    login: str | None = None


class ReviewCommentModel(LenientParseModel):
    """Lenient parse of a GraphQL review-thread comment node (camelCase keys).

    ``comment_id`` (the node's ``databaseId``) stays ``int | None`` — it is documented as
    absent on some nodes and is NOT the thread's identity, so its tolerance is preserved.
    """

    comment_id: int | None = Field(None, validation_alias=AliasChoices("databaseId"))
    body: str = ""
    author: _Actor | None = None
    path: str | None = None
    line: int | None = None
    created_at: str | None = Field(None, validation_alias=AliasChoices("createdAt"))

    def to_domain(self) -> ReviewComment:
        return ReviewComment(
            comment_id=self.comment_id,
            body=self.body,
            author=(self.author.login if self.author else None),
            path=self.path,
            line=self.line,
            created_at=self.created_at,
        )


@dataclass(frozen=True)
class ReviewThread:
    """A PR review thread (inline conversation). ``thread_id`` is the GraphQL node id."""

    thread_id: str
    is_resolved: bool
    is_outdated: bool
    path: str | None
    line: int | None
    comments: tuple[ReviewComment, ...]


class ReviewThreadModel(LenientParseModel):
    """Lenient parse of a GraphQL review-thread node (camelCase keys).

    ``id`` is the thread identity and is required — a malformed/absent id raises a
    ``ValidationError`` the call site maps to a labelled ``GitHubError``. ``comments`` are
    validated and converted separately by the caller, then passed into ``to_domain``.
    """

    id: str
    is_resolved: bool = Field(False, validation_alias=AliasChoices("isResolved"))
    is_outdated: bool = Field(False, validation_alias=AliasChoices("isOutdated"))
    path: str | None = None
    line: int | None = None

    def to_domain(self, *, comments: tuple[ReviewComment, ...]) -> ReviewThread:
        return ReviewThread(
            thread_id=self.id,
            is_resolved=self.is_resolved,
            is_outdated=self.is_outdated,
            path=self.path,
            line=self.line,
            comments=comments,
        )


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


class ReviewModel(LenientParseModel):
    """Lenient parse of a GraphQL PR-review node (camelCase keys).

    ``id`` is the review identity and is required; all other fields keep tolerant defaults so the
    happy path is byte-identical to the prior hand-rolled converter.
    """

    id: str
    author: _Actor | None = None
    body: str = ""
    state: str = ""
    submitted_at: str | None = Field(None, validation_alias=AliasChoices("submittedAt"))

    def to_domain(self) -> Review:
        return Review(
            review_id=self.id,
            author=(self.author.login if self.author else None),
            body=self.body,
            state=self.state,
            submitted_at=self.submitted_at,
        )


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


@dataclass(frozen=True)
class ResolveThreadRequest:
    """One review thread to reply-then-resolve (the typed batch item)."""

    thread_id: str
    comment: str | None = None


def _graphql_proc(
    query: str,
    *,
    repo_root: Path,
    str_vars: dict[str, str] | None = None,
    int_vars: dict[str, int] | None = None,
    timeout: int = _exec._READ_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    """Run a ``gh api graphql`` call. String vars via ``-f``, numeric via ``-F`` (typed). Returns
    the raw proc (callers decide raise-vs-capture)."""
    args = ["api", "graphql", "-f", f"query={query}"]
    for key, value in (str_vars or {}).items():
        args += ["-f", f"{key}={value}"]
    for key, value in (int_vars or {}).items():
        args += ["-F", f"{key}={value}"]
    return _exec._run(args, cwd=repo_root, timeout=timeout)


def _graphql(
    query: str,
    *,
    repo_root: Path,
    str_vars: dict[str, str] | None = None,
    int_vars: dict[str, int] | None = None,
    timeout: int = _exec._READ_TIMEOUT,
    what: str,
) -> dict[str, object]:
    """``_graphql_proc`` + raise-on-failure + parse (the read-op convention)."""
    proc = _graphql_proc(
        query, repo_root=repo_root, str_vars=str_vars, int_vars=int_vars, timeout=timeout
    )
    if proc.returncode != 0:
        raise _exec._failed(proc, what)
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise _exec.GitHubError(f"unparseable graphql output ({what}): {exc}") from exc
    if not isinstance(data, dict):
        raise _exec.GitHubError(f"unexpected graphql payload ({what}): {data!r}")
    return data


def _nodes(obj: object, *path: str) -> list[dict[str, object]]:
    """Walk ``obj[path...]`` (None-safe) to a ``{nodes: [...]}`` and return its node list."""
    cur = _exec._opt_dict(obj)
    for key in path:
        cur = _exec._opt_dict(cur.get(key)) if cur is not None else None
    return _exec._dicts(cur.get("nodes")) if cur is not None else []


def _pr_node(payload: dict[str, object]) -> dict[str, object]:
    """Walk ``payload.data.repository.pullRequest`` (None-safe) to the PR node (``{}`` when any
    hop is absent/null) so the ``_nodes`` walk below starts from a dict."""
    cur: dict[str, object] | None = payload
    for key in ("data", "repository", "pullRequest"):
        cur = _exec._opt_dict(cur.get(key)) if cur is not None else None
    return cur if cur is not None else {}


def _parse_review_threads(payload: dict[str, object]) -> tuple[ReviewThread, ...]:
    pr = _pr_node(payload)
    threads: list[ReviewThread] = []
    for node in _nodes(pr, "reviewThreads"):
        comments = tuple(
            ReviewCommentModel.model_validate(c).to_domain() for c in _nodes(node, "comments")
        )
        threads.append(ReviewThreadModel.model_validate(node).to_domain(comments=comments))
    return tuple(threads)


def _parse_reviews(payload: dict[str, object]) -> tuple[Review, ...]:
    pr = _pr_node(payload)
    return tuple(ReviewModel.model_validate(node).to_domain() for node in _nodes(pr, "reviews"))


def get_pr_feedback(*, pr_number: int, repo_root: Path) -> PrFeedback:
    """Fetch a PR's reviewer feedback: review threads + PR-level reviews (GraphQL) and discussion
    comments (REST). The three sources are kept **separate** (counted apart). Read-only; raises
    ``GitHubError`` on an infra failure. This is what the classify child runs (`perk pr feedback`).
    """
    owner, repo = _exec._owner_repo(repo_root)
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
    raw_comments = _exec._run_json(
        ["api", f"repos/{{owner}}/{{repo}}/issues/{pr_number}/comments"],
        what=f"failed to fetch discussion comments for PR #{pr_number}",
        source="issue comments",
        cwd=repo_root,
        default="[]",
    )
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
    with translate_validation_errors(
        _exec.GitHubError, source=f"parse review threads for PR #{pr_number}"
    ):
        review_threads = _parse_review_threads(threads_payload)
    with translate_validation_errors(
        _exec.GitHubError, source=f"parse reviews for PR #{pr_number}"
    ):
        reviews = _parse_reviews(reviews_payload)
    return PrFeedback(
        pr_number=pr_number,
        review_threads=review_threads,
        discussion_comments=discussion,
        reviews=reviews,
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
            timeout=_exec._WRITE_TIMEOUT,
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
        timeout=_exec._WRITE_TIMEOUT,
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
    *, batch: list[ResolveThreadRequest], repo_root: Path, dry_run: bool = False
) -> BatchResolveResult:
    """Reply-then-resolve a batch of review threads. ``batch`` items are ``ResolveThreadRequest``.
    Top-level ``success`` is True only when **all** resolved. Per-item failures are captured;
    a hard infra failure (gh missing / timeout) raises ``GitHubError`` (via ``_run``)."""
    if dry_run:
        results = tuple(
            ThreadResolveResult(
                thread_id=item.thread_id,
                success=True,
                comment_added=bool(item.comment),
                error=None,
            )
            for item in batch
        )
        return BatchResolveResult(success=True, results=results)
    results = tuple(
        _resolve_single(
            thread_id=item.thread_id,
            comment=item.comment,
            repo_root=repo_root,
        )
        for item in batch
    )
    return BatchResolveResult(success=all(r.success for r in results), results=results)


# ===========================================================================
# PR review ops (the `/pr-review` automated-review door + the `/review` submission substrate;
# contracts.md §8.4).
#
# The read (`get_pr_review_context`) gathers everything the fresh-context `perk.pr-reviewer` child
# needs to review the active PR (diff + PR text + plan body); the mutations send the child's
# verdict back to the PR. The post is **verdict-driven**: an `actionable` verdict submits an
# advisory COMMENT review via `post_pr_review` (the `review-post` CLI never passes `event`, so the
# `/pr-review` posture stays hardcoded-COMMENT — the reviewer can never approve/request-changes);
# a `clean` verdict posts exactly one 👍 reaction to the PR description via `add_pr_reaction` —
# nothing review-shaped lands on the PR. The `/review` flow submits through the same op with an
# explicit `event` (`perk pr review-submit`). Resilience is **event-aware** (see `post_pr_review`):
# a failed COMMENT review degrades to one discussion comment so an advisory review ALWAYS lands; a
# failed formal event (APPROVE/REQUEST_CHANGES) is retried once with the comments folded into the
# body and the event preserved — never converted into a non-review comment, never a silent verdict
# drop — with an own-PR 422 surfacing as `OwnPrReviewError`. The reaction has no fallback ladder
# (nothing review-shaped is lost) — a failure raises, per the gateway's mutations-raise convention.
# ===========================================================================


@dataclass(frozen=True)
class PrReviewContext:
    """The read-only context a `/pr-review` child needs to review the active PR.

    ``plan_body`` is the materialized plan markdown (or ``None`` when unavailable)."""

    pr_number: int
    base_ref: str
    head_ref: str
    title: str
    body: str
    diff: str
    plan_body: str | None


class OwnPrReviewError(_exec.GitHubError):
    """GitHub rejected a formal review (APPROVE/REQUEST_CHANGES) on the author's own PR.

    Classified on failure from the 422's stable ``your own pull request`` substring — a retry
    would fail identically, so callers surface it as a distinct error arm instead.
    """


@dataclass(frozen=True)
class InlineReviewComment:
    """One inline review finding (anchored to a diff line; vs. the review-thread
    ``ReviewComment`` above, which is a fetched comment, not a finding to post).

    ``side`` defaults to ``"RIGHT"`` (added lines/context) so existing constructors are
    byte-identical; ``"LEFT"`` anchors a deleted line (the guest-reviewer contract, §8.4)."""

    path: str
    line: int
    body: str
    side: str = "RIGHT"


@dataclass(frozen=True)
class ReviewPostResult:
    """The outcome of posting a `/pr-review`. ``mode`` records WHICH path landed the review."""

    ok: bool
    # "review" (inline-anchored review) | "comment_fallback" (discussion comment, COMMENT arm) |
    # "review_folded" (formal event retried with comments folded into the body) |
    # "reaction" (clean verdict — a single 👍 on the PR description, nothing else)
    mode: str
    pr_number: int
    comment_count: int
    error: str | None = None


def get_pr_review_context(
    *, pr_number: int, branch: str, repo_root: Path, plan_body: str | None
) -> PrReviewContext:
    """Gather the active PR's review context (diff + PR text + plan body). Read-only; raises
    ``GitHubError`` on an infra failure. ``branch`` is the head ref (already resolved by the
    caller). ``plan_body`` is resolved backend-neutrally by the consumer (the cache mirror, else the
    backend's ``get_plan_body``) and passed straight through — the gateway never reads plan/issue
    state."""
    data = _exec._run_json(
        [
            "api",
            f"repos/{{owner}}/{{repo}}/pulls/{pr_number}",
            "--jq",
            "{title: .title, body: .body, base: .base.ref, head: .head.ref}",
        ],
        what=f"failed to read PR #{pr_number}",
        source=f"`gh api pulls/{pr_number}`",
        cwd=repo_root,
        default="{}",
    )
    if not isinstance(data, dict):
        raise _exec.GitHubError(f"unexpected PR payload: {data!r}")

    diff_proc = _exec._run(["pr", "diff", str(pr_number)], cwd=repo_root)
    if diff_proc.returncode != 0:
        raise _exec._failed(diff_proc, f"failed to read the diff for PR #{pr_number}")

    return PrReviewContext(
        pr_number=pr_number,
        base_ref=str(data.get("base") or branch),
        head_ref=str(data.get("head") or branch),
        title=str(data.get("title") or ""),
        body=str(data.get("body") or ""),
        diff=diff_proc.stdout,
        plan_body=plan_body,
    )


def _render_review_comment(summary: str, comments: list[InlineReviewComment]) -> str:
    """Render the summary + inline findings as a single markdown body (the fallback paths: a
    discussion comment on the COMMENT arm, a folded review body on the formal arms). A LEFT-side
    anchor keeps its side marker so folded bodies preserve the deleted-line addressing."""
    parts = [summary.rstrip()]
    if comments:
        parts.append("\n---\n\n**Inline findings:**")
        for c in comments:
            side_marker = " (LEFT)" if c.side == "LEFT" else ""
            parts.append(f"- `{c.path}:{c.line}`{side_marker} — {c.body}")
    return "\n".join(parts).rstrip() + "\n"


def get_pr_diff(*, pr_number: int, repo_root: Path) -> str | None:
    """The PR's unified diff via ``gh pr diff`` — the merge-base 3-dot diff, which is exactly what
    GitHub validates review-comment anchors against. Lookup convention: a missing PR returns
    ``None``; any other failure raises ``GitHubError``."""
    proc = _exec._run(["pr", "diff", str(pr_number)], cwd=repo_root)
    if proc.returncode == 0:
        return proc.stdout
    if _exec._is_not_found(proc):
        return None
    raise _exec._failed(proc, f"failed to read the diff for PR #{pr_number}")


_OWN_PR_SUBSTRING = "your own pull request"


def _is_own_pr_rejection(proc: subprocess.CompletedProcess[str]) -> bool:
    """Did a failed review POST report GitHub's own-PR 422 (``Can not approve your own pull
    request`` / ``Can not request changes on your own pull request``)?"""
    return _OWN_PR_SUBSTRING in (proc.stderr + proc.stdout).lower()


def _post_review(
    *, pr_number: int, event: str, body: str, comments: list[dict[str, object]], repo_root: Path
) -> subprocess.CompletedProcess[str]:
    """One atomic review POST (``POST .../pulls/{n}/reviews``) — comments + body + event land
    together or not at all (GitHub 422s the whole submission on any bad anchor)."""
    payload: dict[str, object] = {"event": event, "body": body, "comments": comments}
    with _exec._body_file(json.dumps(payload)) as input_path:
        return _exec._run(
            [
                "api",
                f"repos/{{owner}}/{{repo}}/pulls/{pr_number}/reviews",
                "-X",
                "POST",
                "--input",
                input_path,
            ],
            cwd=repo_root,
            timeout=_exec._WRITE_TIMEOUT,
        )


def post_pr_review(
    *,
    pr_number: int,
    summary: str,
    comments: list[InlineReviewComment],
    repo_root: Path,
    dry_run: bool = False,
    event: str = "COMMENT",
) -> ReviewPostResult:
    """Submit ONE atomic review (comments + body + event). ``event`` is the wire spelling
    (``COMMENT`` (default) | ``APPROVE`` | ``REQUEST_CHANGES``); the default keeps every existing
    caller (`/pr-review`'s advisory COMMENT posture) byte-identical.

    The last-resort ladder is **event-aware**:

    - ``COMMENT`` — on failure (e.g. bad line anchors), degrade to a single discussion comment
      (``mode: "comment_fallback"``) so an advisory review always lands; raises only when even the
      fallback fails.
    - ``APPROVE``/``REQUEST_CHANGES`` — a formal verdict is NEVER converted into a non-review
      comment. An own-PR 422 raises ``OwnPrReviewError`` (no retry — it would fail identically).
      Otherwise one retry with the comments folded into the body and the **event preserved**
      (``mode: "review_folded"``); a failed retry (or a bare-verdict failure) raises loudly.
    """
    if dry_run:
        return ReviewPostResult(
            ok=True, mode="review", pr_number=pr_number, comment_count=len(comments)
        )

    proc = _post_review(
        pr_number=pr_number,
        event=event,
        body=summary,
        comments=[
            {"path": c.path, "line": c.line, "side": c.side, "body": c.body} for c in comments
        ],
        repo_root=repo_root,
    )
    if proc.returncode == 0:
        return ReviewPostResult(
            ok=True, mode="review", pr_number=pr_number, comment_count=len(comments)
        )

    if event != "COMMENT":
        return _formal_review_fallback(
            proc,
            pr_number=pr_number,
            event=event,
            summary=summary,
            comments=comments,
            repo_root=repo_root,
        )

    # COMMENT arm: inline-anchored submission failed (commonly: a `line` not present in the diff).
    # Fall back to a single discussion comment so the advisory review is never lost.
    body = _render_review_comment(summary, comments)
    with _exec._body_file(body) as body_path:
        fallback = _exec._run(
            _exec._rest_args(
                f"repos/{{owner}}/{{repo}}/issues/{pr_number}/comments",
                method="POST",
                body_path=body_path,
            ),
            cwd=repo_root,
            timeout=_exec._WRITE_TIMEOUT,
        )
    if fallback.returncode != 0:
        raise _exec._failed(fallback, f"failed to post the review for PR #{pr_number}")
    return ReviewPostResult(
        ok=True, mode="comment_fallback", pr_number=pr_number, comment_count=len(comments)
    )


def _formal_review_fallback(
    proc: subprocess.CompletedProcess[str],
    *,
    pr_number: int,
    event: str,
    summary: str,
    comments: list[InlineReviewComment],
    repo_root: Path,
) -> ReviewPostResult:
    """The formal-event (APPROVE/REQUEST_CHANGES) arm of the ladder: classify own-PR first (the
    POST is atomic, so the failure landed nothing), then retry ONCE with the comments folded into
    the body and the event preserved — never a silent verdict drop, never a non-review comment.
    Fold-all is the honest reading: GitHub's atomic rejection does not reliably identify the
    offending comment."""
    if _is_own_pr_rejection(proc):
        raise OwnPrReviewError(
            f"GitHub rejected the {event} review on PR #{pr_number}: "
            f"{(proc.stderr + proc.stdout).strip() or 'no output'}"
        )
    if not comments:
        # A bare verdict: an identical retry is pointless — fail loudly.
        raise _exec._failed(proc, f"failed to submit the {event} review for PR #{pr_number}")
    retry = _post_review(
        pr_number=pr_number,
        event=event,
        body=_render_review_comment(summary, comments),
        comments=[],
        repo_root=repo_root,
    )
    if retry.returncode == 0:
        return ReviewPostResult(
            ok=True, mode="review_folded", pr_number=pr_number, comment_count=len(comments)
        )
    # The first 422 may have been anchor-shaped with the own-PR rejection surfacing only now.
    if _is_own_pr_rejection(retry):
        raise OwnPrReviewError(
            f"GitHub rejected the {event} review on PR #{pr_number}: "
            f"{(retry.stderr + retry.stdout).strip() or 'no output'}"
        )
    raise _exec._failed(retry, f"failed to submit the {event} review for PR #{pr_number}")


def add_pr_reaction(*, pr_number: int, repo_root: Path, dry_run: bool = False) -> ReviewPostResult:
    """Post a single 👍 reaction to the PR description (the `clean`-verdict artifact — nothing
    review-shaped lands on the PR). The issues reactions endpoint covers PRs; a duplicate 👍 from
    the same user is a server-side no-op, so re-running `/pr-review` stays idempotent. A non-zero
    exit raises ``GitHubError`` (mutations raise; no fallback ladder — nothing review-shaped is
    lost)."""
    if dry_run:
        return ReviewPostResult(ok=True, mode="reaction", pr_number=pr_number, comment_count=0)
    proc = _exec._run(
        _exec._rest_args(
            f"repos/{{owner}}/{{repo}}/issues/{pr_number}/reactions",
            method="POST",
            fields={"content": "+1"},
        ),
        cwd=repo_root,
        timeout=_exec._WRITE_TIMEOUT,
    )
    if proc.returncode != 0:
        raise _exec._failed(proc, f"failed to react to PR #{pr_number}")
    return ReviewPostResult(ok=True, mode="reaction", pr_number=pr_number, comment_count=0)
