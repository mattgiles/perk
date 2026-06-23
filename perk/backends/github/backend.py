"""``GitHubIssueBackend`` — the issue-tier adapter over the GitHub substrate.

The issue-tier **contract** (``perk/backends/issue_backend.py``) defines the ``IssueBackend``
``Protocol``, the backend-neutral result dataclasses, and ``IssueBackendError``.
This module makes the GitHub backend live: ``GitHubIssueBackend`` is a thin delegation adapter over
the plan/issue substrate ``perk.backends.github.plans`` (the GitHub backend's private implementation
substrate, a sibling in this package). The resolver every issue-tier consumer goes through lives in
``perk/backends/resolve.py``.

This module imports the substrate (``perk.backends.github.plans``) and the contract
(``perk.backends.issue_backend``); the pure forge gateway ``perk/github/`` never references the
backend tier (the one-way import guard).

Adapter disciplines:

- **Late-bound delegation.** Every method resolves its delegate via attribute access on the
  ``plans`` module object (and, for the engagement reads, the ``gh_engagement`` module object) at
  call time, so existing ``monkeypatch.setattr(...)`` test fixtures keep intercepting unchanged —
  even when the patch lands after backend construction.
- **Constructor-bound repo context.** ``repo_root`` is bound once at construction and threaded
  into every delegate call; methods take no repo parameter (the contract discipline).
- **String ids at the boundary.** GitHub's int issue/comment numbers are stringified on the way
  out; incoming ``issue_id`` strings are ``int()``-converted at the edge — a non-numeric id
  raises ``IssueBackendError`` (the GitHub backend legitimately requires numeric ids).
- **Error mapping at the boundary.** Every delegate call wraps ``GitHubError`` into
  ``IssueBackendError(str(exc)) from exc`` — message text preserved verbatim (consumers map on
  substrings, and tests assert messages).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from perk.backends import engagement, issue_backend
from perk.backends.github import engagement as gh_engagement
from perk.backends.github import plans
from perk.backends.issue_backend import IssueBackendError
from perk.github import GitHubError


@contextmanager
def _translate() -> Iterator[None]:
    """Map the GitHub backend's native error into the backend-neutral one (message verbatim)."""
    try:
        yield
    except GitHubError as exc:
        raise IssueBackendError(str(exc)) from exc


def _number(issue_id: str) -> int:
    """Convert a boundary string id to GitHub's numeric issue number (honest failure on junk)."""
    try:
        return int(issue_id)
    except ValueError as exc:
        raise IssueBackendError(f"GitHub issue ids are numeric; got {issue_id!r}") from exc


def _issue_ref(found: plans.PlanIssue) -> issue_backend.IssueRef:
    return issue_backend.IssueRef(id=str(found.number), url=found.url, existed=found.existed)


def _actor(name: str | None, actor_id: str | None) -> engagement.Actor | None:
    """Build an :class:`Actor`, or ``None`` when GitHub resolved neither field (a deleted/
    unresolvable account) — so its author classifies as ``unknown``, not ``human`` (mirrors
    Linear's ``_actor_or_none``)."""
    if name is None and actor_id is None:
        return None
    return engagement.Actor(id=actor_id, name=name)


def _engagement_comment(row: gh_engagement.IssueCommentRow) -> engagement.EngagementComment:
    """Map a github-native comment row into an :class:`EngagementComment` (untrusted body). The
    author is classified via :func:`engagement.classify_author`: a bot row routes to ``bot_actor``,
    a human row to ``user``; the body feeds the ``perk:*`` sentinel heuristic."""
    actor = _actor(row.author_login, row.author_id)
    author = engagement.classify_author(
        body=row.body,
        user=None if row.author_is_bot else actor,
        bot_actor=actor if row.author_is_bot else None,
    )
    return engagement.EngagementComment(
        id=row.id,
        body=row.body,
        created_at=row.created_at,
        edited_at=row.edited_at,
        author=author,
    )


def _description_edit(row: gh_engagement.DescriptionEditRow) -> engagement.DescriptionEdit:
    """Map a github-native description-edit row into a :class:`DescriptionEdit`. ``diff`` is passed
    through best-effort (``None`` when GitHub returned null); author keyed on the editor."""
    actor = _actor(row.editor_login, row.editor_id)
    author = engagement.classify_author(
        body="",
        user=None if row.editor_is_bot else actor,
        bot_actor=actor if row.editor_is_bot else None,
    )
    return engagement.DescriptionEdit(created_at=row.edited_at, author=author, diff=row.diff)


class GitHubIssueBackend:
    """``IssueBackend`` over GitHub Issues — a thin adapter over ``perk.github``'s issue-tier
    functions (constructor-bound ``repo_root``; str ids at the boundary; ``GitHubError`` →
    ``IssueBackendError``)."""

    backend_id = "github"

    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root

    # --- labels ---

    def ensure_label(
        self, name: str, *, color: str, description: str, dry_run: bool = False
    ) -> issue_backend.Label:
        with _translate():
            label = plans.create_label(
                name,
                color=color,
                description=description,
                repo_root=self._repo_root,
                dry_run=dry_run,
            )
        return issue_backend.Label(name=label.name, created=label.created)

    # --- plan issues ---

    def find_plan_issue(self, *, run_id: str) -> issue_backend.IssueRef | None:
        with _translate():
            found = plans.find_plan_issue(run_id=run_id, repo_root=self._repo_root)
        return None if found is None else _issue_ref(found)

    def create_plan_issue(
        self, *, title: str, body: str, run_id: str | None, dry_run: bool = False
    ) -> issue_backend.IssueRef:
        with _translate():
            created = plans.create_plan_issue(
                title=title, body=body, repo_root=self._repo_root, run_id=run_id, dry_run=dry_run
            )
        return _issue_ref(created)

    def update_plan_issue(
        self, *, issue_id: str, title: str, body_comment: str, dry_run: bool = False
    ) -> issue_backend.PlanUpdate:
        number = _number(issue_id)
        with _translate():
            updated = plans.update_plan_issue(
                number=number,
                title=title,
                body_comment=body_comment,
                repo_root=self._repo_root,
                dry_run=dry_run,
            )
        return issue_backend.PlanUpdate(
            issue_id=str(updated.number),
            body_updated=updated.body_updated,
            title_updated=updated.title_updated,
            dry_run=updated.dry_run,
        )

    def update_plan_header(
        self, *, issue_id: str, fields: dict[str, object], dry_run: bool = False
    ) -> issue_backend.PlanHeaderUpdate:
        number = _number(issue_id)
        with _translate():
            updated = plans.update_plan_header(
                issue=number, fields=fields, repo_root=self._repo_root, dry_run=dry_run
            )
        return issue_backend.PlanHeaderUpdate(
            fields_updated=updated.fields_updated, dry_run=updated.dry_run
        )

    def prepend_plan_callout(
        self, *, issue_id: str, callout: str, command: str, dry_run: bool = False
    ) -> bool:
        number = _number(issue_id)
        with _translate():
            return plans.prepend_plan_callout(
                issue=number,
                callout=callout,
                command=command,
                repo_root=self._repo_root,
                dry_run=dry_run,
            )

    def get_plan(self, *, issue_id: str) -> issue_backend.PlanState | None:
        number = _number(issue_id)
        with _translate():
            state = plans.get_plan(number=number, repo_root=self._repo_root)
        if state is None:
            return None
        return issue_backend.PlanState(
            id=str(state.number),
            url=state.url,
            title=state.title,
            header=state.header,
            pr=state.pr,
            state=state.state,
        )

    def get_plan_body(self, *, issue_id: str) -> str | None:
        number = _number(issue_id)
        with _translate():
            return plans.get_plan_body(number=number, repo_root=self._repo_root)

    # --- in-place issue adoption (§8.29) ---

    def read_issue(self, *, issue_id: str) -> issue_backend.AdoptableIssue | None:
        number = _number(issue_id)
        with _translate():
            found = plans.read_issue(number=number, repo_root=self._repo_root)
        if found is None:
            return None
        return issue_backend.AdoptableIssue(
            id=str(found.number),
            url=found.url,
            title=found.title,
            body=found.body,
            # Normalize `gh issue view`'s casing into the contract's OPEN/CLOSED vocabulary.
            state="CLOSED" if found.state.upper() == "CLOSED" else "OPEN",
        )

    def adopt_issue_as_plan(
        self,
        *,
        issue_id: str,
        header_fields: dict[str, object],
        plan_markdown: str,
        callout: str,
        command: str,
        dry_run: bool = False,
    ) -> issue_backend.IssueRef:
        number = _number(issue_id)
        with _translate():
            adoption = plans.adopt_issue_as_plan(
                number=number,
                header_fields=header_fields,
                plan_markdown=plan_markdown,
                callout=callout,
                command=command,
                repo_root=self._repo_root,
                dry_run=dry_run,
            )
        return issue_backend.IssueRef(id=str(adoption.number), url=adoption.url, existed=True)

    # --- learn issues ---

    def find_learn_issue(self, *, run_id: str) -> issue_backend.IssueRef | None:
        with _translate():
            found = plans.find_learn_issue(run_id=run_id, repo_root=self._repo_root)
        return None if found is None else _issue_ref(found)

    def create_learn_issue(
        self, *, title: str, body: str, run_id: str | None, plan_id: str, dry_run: bool = False
    ) -> issue_backend.IssueRef:
        plan_number = _number(plan_id)
        with _translate():
            created = plans.create_learn_issue(
                title=title,
                body=body,
                repo_root=self._repo_root,
                run_id=run_id,
                plan_number=plan_number,
                dry_run=dry_run,
            )
        return _issue_ref(created)

    def list_learn_issues(self) -> tuple[issue_backend.LearnIssueSummary, ...]:
        with _translate():
            summaries = plans.list_learn_issues(repo_root=self._repo_root)
        return tuple(
            issue_backend.LearnIssueSummary(id=str(s.number), title=s.title, url=s.url, body=s.body)
            for s in summaries
        )

    def close_and_label_consolidated(self, *, issue_id: str, dry_run: bool = False) -> bool:
        number = _number(issue_id)
        with _translate():
            return plans.close_and_label_consolidated(
                issue=number, repo_root=self._repo_root, dry_run=dry_run
            )

    # --- generic issue ops ---

    def close_issue(self, *, issue_id: str, dry_run: bool = False) -> bool:
        number = _number(issue_id)
        with _translate():
            return plans.close_issue(number=number, repo_root=self._repo_root, dry_run=dry_run)

    def add_issue_comment(
        self, *, issue_id: str, body: str, dry_run: bool = False
    ) -> issue_backend.CommentResult:
        number = _number(issue_id)
        with _translate():
            result = plans.add_issue_comment(
                issue=number, body=body, repo_root=self._repo_root, dry_run=dry_run
            )
        return issue_backend.CommentResult(posted=result.posted)

    def find_comment_id_by_marker(self, *, issue_id: str, marker: str) -> str | None:
        number = _number(issue_id)
        with _translate():
            comment_id = plans.find_comment_id_by_marker(
                issue=number, marker=marker, repo_root=self._repo_root
            )
        return None if comment_id is None else str(comment_id)

    def upsert_marked_comment(
        self, *, issue_id: str, marker: str, body: str, dry_run: bool = False
    ) -> issue_backend.CommentResult:
        number = _number(issue_id)
        with _translate():
            result = plans.upsert_marked_comment(
                issue=number, marker=marker, body=body, repo_root=self._repo_root, dry_run=dry_run
            )
        return issue_backend.CommentResult(posted=result.posted)

    # --- human-engagement reads ---
    # Honest where GitHub exposes the primitive: comments + description edits via read-only
    # `gh api graphql`. Agent sessions stay the only stub — GitHub has no agent-session
    # surface, so the derived stop signal is a clean no-op (the Linear-only surface).

    def read_comments(self, *, issue_id: str) -> tuple[engagement.EngagementComment, ...]:
        number = _number(issue_id)
        with _translate():
            rows = gh_engagement.read_issue_comments(issue=number, repo_root=self._repo_root)
        return tuple(_engagement_comment(row) for row in rows)

    def read_description_edits(self, *, issue_id: str) -> tuple[engagement.DescriptionEdit, ...]:
        number = _number(issue_id)
        with _translate():
            rows = gh_engagement.read_description_edits(issue=number, repo_root=self._repo_root)
        return tuple(_description_edit(row) for row in rows)

    def read_agent_session(self, *, issue_id: str) -> engagement.AgentSessionRead:
        # GitHub has no agent-session surface (the Linear-only no-op).
        return engagement.EMPTY_AGENT_SESSION
