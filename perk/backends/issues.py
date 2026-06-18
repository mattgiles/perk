"""The issue-tracking tier seam (Objective #252, Node 1.2): the GitHub backend + the resolver.

Node 1.1 (``perk/backends/issue_backend.py``) shipped the issue-tier **contract** — the
``IssueBackend`` ``Protocol``, the backend-neutral result dataclasses, and ``IssueBackendError``.
This module makes it live: ``GitHubIssueBackend`` is a thin delegation adapter over
``perk.github``'s issue-tier module functions (which remain the GitHub backend's private
implementation substrate), and ``resolve_issue_backend`` is the resolver every issue-tier
consumer goes through.

This is deliberately the only module that imports both ``perk.github`` and
``perk.backends.issue_backend`` (preserving Node 1.1's one-way import guard: ``perk/github/``
never references the contract).

Adapter disciplines:

- **Late-bound delegation.** Every method resolves its delegate via attribute access on the
  ``github`` module object at call time (``github.get_plan(...)``), so existing
  ``monkeypatch.setattr(github, ...)`` test fixtures keep intercepting unchanged — even when the
  patch lands after backend construction.
- **Constructor-bound repo context.** ``repo_root`` is bound once at construction and threaded
  into every delegate call; methods take no repo parameter (the contract discipline).
- **String ids at the boundary.** GitHub's int issue/comment numbers are stringified on the way
  out; incoming ``issue_id`` strings are ``int()``-converted at the edge — a non-numeric id
  raises ``IssueBackendError`` (the GitHub backend legitimately requires numeric ids).
- **Error mapping at the boundary.** Every delegate call wraps ``GitHubError`` into
  ``IssueBackendError(str(exc)) from exc`` — message text preserved verbatim (consumers map on
  substrings, and tests assert messages).
"""

import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from perk import github
from perk.backends import engagement, issue_backend, linear, linear_backend
from perk.backends.issue_backend import IssueBackendError
from perk.github import GitHubError
from perk.substrate import config

# The `[issues] backend` vocabulary (contracts.md §8.21). Both "github" (default) and "linear"
# are live selections; "linear" additionally requires a committed `[issues] team` and the
# `LINEAR_API_KEY` env var (resolved in `resolve_issue_backend`).
GITHUB_BACKEND_ID = "github"
LINEAR_BACKEND_ID = "linear"
KNOWN_ISSUE_BACKENDS = (GITHUB_BACKEND_ID, LINEAR_BACKEND_ID)


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


def _issue_ref(found: github.PlanIssue) -> issue_backend.IssueRef:
    return issue_backend.IssueRef(id=str(found.number), url=found.url, existed=found.existed)


def _actor(name: str | None, actor_id: str | None) -> engagement.Actor:
    return engagement.Actor(id=actor_id, name=name)


def _engagement_comment(row: github.IssueCommentRow) -> engagement.EngagementComment:
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


def _description_edit(row: github.DescriptionEditRow) -> engagement.DescriptionEdit:
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

    backend_id = GITHUB_BACKEND_ID

    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root

    # --- labels ---

    def ensure_label(
        self, name: str, *, color: str, description: str, dry_run: bool = False
    ) -> issue_backend.Label:
        with _translate():
            label = github.create_label(
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
            found = github.find_plan_issue(run_id=run_id, repo_root=self._repo_root)
        return None if found is None else _issue_ref(found)

    def create_plan_issue(
        self, *, title: str, body: str, run_id: str | None, dry_run: bool = False
    ) -> issue_backend.IssueRef:
        with _translate():
            created = github.create_plan_issue(
                title=title, body=body, repo_root=self._repo_root, run_id=run_id, dry_run=dry_run
            )
        return _issue_ref(created)

    def update_plan_issue(
        self, *, issue_id: str, title: str, body_comment: str, dry_run: bool = False
    ) -> issue_backend.PlanUpdate:
        number = _number(issue_id)
        with _translate():
            updated = github.update_plan_issue(
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
            updated = github.update_plan_header(
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
            return github.prepend_plan_callout(
                issue=number,
                callout=callout,
                command=command,
                repo_root=self._repo_root,
                dry_run=dry_run,
            )

    def get_plan(self, *, issue_id: str) -> issue_backend.PlanState | None:
        number = _number(issue_id)
        with _translate():
            state = github.get_plan(number=number, repo_root=self._repo_root)
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
            return github.get_plan_body(number=number, repo_root=self._repo_root)

    # --- learn issues ---

    def find_learn_issue(self, *, run_id: str) -> issue_backend.IssueRef | None:
        with _translate():
            found = github.find_learn_issue(run_id=run_id, repo_root=self._repo_root)
        return None if found is None else _issue_ref(found)

    def create_learn_issue(
        self, *, title: str, body: str, run_id: str | None, plan_id: str, dry_run: bool = False
    ) -> issue_backend.IssueRef:
        plan_number = _number(plan_id)
        with _translate():
            created = github.create_learn_issue(
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
            summaries = github.list_learn_issues(repo_root=self._repo_root)
        return tuple(
            issue_backend.LearnIssueSummary(id=str(s.number), title=s.title, url=s.url, body=s.body)
            for s in summaries
        )

    def close_and_label_consolidated(self, *, issue_id: str, dry_run: bool = False) -> bool:
        number = _number(issue_id)
        with _translate():
            return github.close_and_label_consolidated(
                issue=number, repo_root=self._repo_root, dry_run=dry_run
            )

    # --- generic issue ops ---

    def close_issue(self, *, issue_id: str, dry_run: bool = False) -> bool:
        number = _number(issue_id)
        with _translate():
            return github.close_issue(number=number, repo_root=self._repo_root, dry_run=dry_run)

    def add_issue_comment(
        self, *, issue_id: str, body: str, dry_run: bool = False
    ) -> issue_backend.CommentResult:
        number = _number(issue_id)
        with _translate():
            result = github.add_issue_comment(
                issue=number, body=body, repo_root=self._repo_root, dry_run=dry_run
            )
        return issue_backend.CommentResult(posted=result.posted)

    def find_comment_id_by_marker(self, *, issue_id: str, marker: str) -> str | None:
        number = _number(issue_id)
        with _translate():
            comment_id = github.find_comment_id_by_marker(
                issue=number, marker=marker, repo_root=self._repo_root
            )
        return None if comment_id is None else str(comment_id)

    def upsert_marked_comment(
        self, *, issue_id: str, marker: str, body: str, dry_run: bool = False
    ) -> issue_backend.CommentResult:
        number = _number(issue_id)
        with _translate():
            result = github.upsert_marked_comment(
                issue=number, marker=marker, body=body, repo_root=self._repo_root, dry_run=dry_run
            )
        return issue_backend.CommentResult(posted=result.posted)

    # --- human-engagement reads (Objective #682, Node 1.3) ---
    # Honest where GitHub exposes the primitive: comments + description edits via read-only
    # `gh api graphql` (Node 1.3). Agent sessions stay the only stub — GitHub has no agent-session
    # surface, so the derived stop signal is a clean no-op (the Linear-only surface).

    def read_comments(self, *, issue_id: str) -> tuple[engagement.EngagementComment, ...]:
        number = _number(issue_id)
        with _translate():
            rows = github.read_issue_comments(issue=number, repo_root=self._repo_root)
        return tuple(_engagement_comment(row) for row in rows)

    def read_description_edits(self, *, issue_id: str) -> tuple[engagement.DescriptionEdit, ...]:
        number = _number(issue_id)
        with _translate():
            rows = github.read_description_edits(issue=number, repo_root=self._repo_root)
        return tuple(_description_edit(row) for row in rows)

    def read_agent_session(self, *, issue_id: str) -> engagement.AgentSessionRead:
        # GitHub has no agent-session surface (the Linear-only no-op).
        return engagement.EMPTY_AGENT_SESSION


def resolve_issue_backend_id(repo_root: Path) -> str:
    """Resolve the repo's `[issues] backend` selection to a known backend id — or raise.

    Reads the **committed** `.pi/perk.toml` only (``load_committed_issues_backend``; the local
    overlay is deliberately never read — the backend decides where canonical durable state is
    written). Absent or ``"github"`` → ``GITHUB_BACKEND_ID``; ``"linear"`` → ``LINEAR_BACKEND_ID``.
    Unknown values **raise** ``IssueBackendError`` (falling back silently would write canonical
    issues to the wrong tracker); a malformed committed TOML is mapped into ``IssueBackendError``
    too.
    """
    try:
        selected = config.load_committed_issues_backend(repo_root)
    except tomllib.TOMLDecodeError as exc:
        raise IssueBackendError(
            f".pi/perk.toml is not valid TOML ({exc}); run `perk doctor`"
        ) from exc
    if selected is None or selected == GITHUB_BACKEND_ID:
        return GITHUB_BACKEND_ID
    if selected == LINEAR_BACKEND_ID:
        return LINEAR_BACKEND_ID
    known = ", ".join(KNOWN_ISSUE_BACKENDS)
    raise IssueBackendError(f"unknown issue backend {selected!r} (known: {known})")


def resolve_issue_backend(repo_root: Path) -> issue_backend.IssueBackend:
    """Resolve the repo's issue backend from the committed `[issues]` config table.

    Config-driven selection is live: ``resolve_issue_backend_id`` validates the selection (raising
    ``IssueBackendError`` on unknown/malformed config — every caller's existing error boundary
    handles it) and this constructs the matching backend. The Linear arm additionally requires a
    committed ``[issues] team`` (the Linear team key) and the ``LINEAR_API_KEY`` env var; either
    missing raises a hinted ``IssueBackendError``. Construction is lazy (no network): the team
    UUID is resolved on first use.
    """
    backend_id = resolve_issue_backend_id(repo_root)
    if backend_id == GITHUB_BACKEND_ID:
        return GitHubIssueBackend(repo_root)
    if backend_id == LINEAR_BACKEND_ID:
        team = config.load_committed_issues_team(repo_root)
        if team is None:
            raise IssueBackendError(
                '[issues] team is required when backend = "linear" — '
                "set the Linear team key in .pi/perk.toml"
            )
        client = linear.client_from_env(repo_root=repo_root)
        return linear_backend.LinearIssueBackend(client, team_key=team, repo_root=repo_root)
    raise IssueBackendError(f"no backend implementation for {backend_id!r}")
