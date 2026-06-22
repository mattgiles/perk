"""Honest human-engagement reads for the GitHub issue backend (Objective #682, Node 1.3).

Two read-only ``gh api graphql`` queries — issue comments and issue description edit history —
each a single cursor-paginated GraphQL connection. github-native result rows
(:class:`IssueCommentRow` / :class:`DescriptionEditRow`) carry raw author fields; the
backend-tier mapping to the neutral engagement contract lives in the issue-backend adapter (this
package never imports the backend tier — the one-way import guard).

Mechanism notes (contracts.md §8.25):

- ``gh api graphql`` does **not** auto-template ``{owner}/{repo}`` (unlike REST ``gh api``), so the
  queries pass ``owner``/``name``/``number`` as explicit variables (via ``_exec._owner_repo``).
- A not-found issue surfaces as a non-zero ``gh`` exit ("Could not resolve to an Issue …"), folded
  to ``[]`` via ``_exec._is_not_found`` (the gateway's lookup convention); every other failure
  raises ``GitHubError``.
- ``IssueComment.lastEditedAt`` gives the edited flag; ``author{__typename databaseId login}``
  gives the bot/human discriminator + opaque id. ``Issue.userContentEdits`` gives ``editedAt`` /
  ``editor`` / a best-effort ``diff`` (may be null).
"""

from dataclasses import dataclass
from pathlib import Path

from perk.github import _exec

# Each Actor selection resolves login + a typed databaseId via inline fragments; `__typename ==
# "Bot"` is the bot discriminator.
_ACTOR_SELECTION = (
    "login __typename "
    "... on User { databaseId } ... on Bot { databaseId } "
    "... on Organization { databaseId } ... on Mannequin { databaseId }"
)

_COMMENTS_QUERY = (
    "query($owner: String!, $name: String!, $number: Int!, $cursor: String) { "
    "repository(owner: $owner, name: $name) { issue(number: $number) { "
    "comments(first: 100, after: $cursor) { "
    "nodes { id body createdAt lastEditedAt author { " + _ACTOR_SELECTION + " } } "
    "pageInfo { hasNextPage endCursor } } } } }"
)

_DESCRIPTION_EDITS_QUERY = (
    "query($owner: String!, $name: String!, $number: Int!, $cursor: String) { "
    "repository(owner: $owner, name: $name) { issue(number: $number) { "
    "userContentEdits(first: 100, after: $cursor) { "
    "nodes { editedAt diff editor { " + _ACTOR_SELECTION + " } } "
    "pageInfo { hasNextPage endCursor } } } } }"
)


@dataclass(frozen=True)
class IssueCommentRow:
    """A github-native issue-comment row (raw author fields; mapped to the neutral contract by the
    backend adapter). ``edited_at`` is ``None`` for an unedited comment."""

    id: str
    body: str
    created_at: str
    edited_at: str | None
    author_login: str | None
    author_id: str | None
    author_is_bot: bool


@dataclass(frozen=True)
class DescriptionEditRow:
    """A github-native description-edit row from ``Issue.userContentEdits``. ``diff`` is best-effort
    (``None`` when GitHub returns null)."""

    edited_at: str
    diff: str | None
    editor_login: str | None
    editor_id: str | None
    editor_is_bot: bool


def _actor_fields(node: object) -> tuple[str | None, str | None, bool]:
    """Parse a GraphQL ``Actor`` selection → ``(login, id, is_bot)``. ``id`` is the stringified
    ``databaseId`` (``None`` when absent); ``is_bot`` is ``__typename == "Bot"``."""
    d = _exec._opt_dict(node)
    if d is None:
        return None, None, False
    raw_id = d.get("databaseId")
    actor_id = str(raw_id) if raw_id is not None else None
    return (
        _exec._opt_str(d.get("login")),
        actor_id,
        d.get("__typename") == "Bot",
    )


def _connection(obj: object, path: str) -> dict[str, object] | None:
    """Walk ``obj.data.repository.issue.<path>`` (None-safe) to the connection dict (else None)."""
    cur = _exec._opt_dict(obj)
    for key in ("data", "repository", "issue", path):
        cur = _exec._opt_dict(cur.get(key)) if cur is not None else None
    return cur


def _graphql_nodes(
    *, query: str, issue: int, repo_root: Path, path: str, what: str
) -> list[dict[str, object]]:
    """Cursor-loop a single GraphQL connection at ``data.repository.issue.<path>``.

    Runs ``gh api graphql`` (string vars via ``-f``, the numeric ``number`` via ``-F``, the
    ``cursor`` via ``-f`` only once we have one) following ``pageInfo.endCursor`` while
    ``hasNextPage``. A non-zero exit folds ``_exec._is_not_found`` → ``[]`` (a genuinely missing
    issue) else raises ``_exec._failed``; a ``null`` ``repository``/``issue`` connection also
    yields ``[]``.
    """
    owner, name = _exec._owner_repo(repo_root)
    nodes: list[dict[str, object]] = []
    cursor: str | None = None
    while True:
        args = [
            "api",
            "graphql",
            "-f",
            f"query={query}",
            "-f",
            f"owner={owner}",
            "-f",
            f"name={name}",
            "-F",
            f"number={issue}",
        ]
        if cursor is not None:
            args += ["-f", f"cursor={cursor}"]
        proc = _exec._run(args, cwd=repo_root)
        if proc.returncode != 0:
            if _exec._is_not_found(proc):
                return []
            raise _exec._failed(proc, what)
        payload = _exec._parse_json(proc, source=what)
        connection = _connection(payload, path)
        if connection is None:
            return nodes
        nodes += _exec._dicts(connection.get("nodes"))
        page_info = _exec._opt_dict(connection.get("pageInfo"))
        if not (page_info is not None and page_info.get("hasNextPage")):
            return nodes
        end_cursor = page_info.get("endCursor")
        if not isinstance(end_cursor, str):
            return nodes
        cursor = end_cursor


def read_issue_comments(*, issue: int, repo_root: Path) -> list[IssueCommentRow]:
    """Read an issue's comments (oldest-first) via ``gh api graphql``. A missing issue → ``[]``."""
    nodes = _graphql_nodes(
        query=_COMMENTS_QUERY,
        issue=issue,
        repo_root=repo_root,
        path="comments",
        what=f"failed to read comments for issue #{issue}",
    )
    rows: list[IssueCommentRow] = []
    for node in nodes:
        login, actor_id, is_bot = _actor_fields(node.get("author"))
        rows.append(
            IssueCommentRow(
                id=str(node.get("id", "")),
                body=str(node.get("body", "")),
                created_at=str(node.get("createdAt", "")),
                edited_at=_exec._opt_str(node.get("lastEditedAt")),
                author_login=login,
                author_id=actor_id,
                author_is_bot=is_bot,
            )
        )
    rows.sort(key=lambda r: r.created_at)
    return rows


def read_description_edits(*, issue: int, repo_root: Path) -> list[DescriptionEditRow]:
    """Read an issue's description edit history (oldest-first) via ``gh api graphql``. The honest
    source is ``Issue.userContentEdits``; ``diff`` is best-effort. A missing issue → ``[]``."""
    nodes = _graphql_nodes(
        query=_DESCRIPTION_EDITS_QUERY,
        issue=issue,
        repo_root=repo_root,
        path="userContentEdits",
        what=f"failed to read description edits for issue #{issue}",
    )
    rows: list[DescriptionEditRow] = []
    for node in nodes:
        login, actor_id, is_bot = _actor_fields(node.get("editor"))
        rows.append(
            DescriptionEditRow(
                edited_at=str(node.get("editedAt", "")),
                diff=_exec._opt_str(node.get("diff")),
                editor_login=login,
                editor_id=actor_id,
                editor_is_bot=is_bot,
            )
        )
    rows.sort(key=lambda r: r.edited_at)
    return rows
