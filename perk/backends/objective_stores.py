"""The objective-storage tier seam (Objective #548, Node 2.2): the concrete stores + the resolver.

Node 2.1 (``perk/backends/objective_store.py``) shipped the objective-tier **contract** — the
``ObjectiveStore`` ``Protocol``, the result dataclasses, and ``ObjectiveStoreError``.
This module makes it live: ``GitHubObjectiveStore`` is a thin delegation adapter over
``perk.github``'s objective-tier module functions (the same functions ``GitHubIssueBackend`` used to
delegate to — the equivalence lock for the move) and ``resolve_objective_store`` is the resolver
every objective-tier consumer goes through.

**The Linear arm is project-backed** (Objective #548, Node 3.4): ``resolve_objective_store``
constructs ``LinearProjectObjectiveStore`` (a Linear **Project** is the objective; the roadmap is
materialised as one node-issue per node), so every Linear objective consumer is project-backed. The
issue-backed ``LinearObjectiveStore`` is kept dormant (directly-constructable, still unit-tested);
retiring it is a later cleanup.

The ``[issues]`` selection is single-sourced: ``resolve_objective_store_id`` re-exports
``perk.backends.issues.resolve_issue_backend_id`` (an objective and its plan/learn issues share one
backend selection — both populations live in the same tracker), so the dispatch never forks.

Adapter disciplines (mirroring ``perk.backends.issues``):

- **Late-bound delegation.** ``GitHubObjectiveStore`` resolves each delegate via attribute access on
  the ``github`` module object at call time, so existing ``monkeypatch.setattr(github, ...)``
  fixtures keep intercepting unchanged.
- **Constructor-bound repo context.** ``repo_root`` is bound once at construction; methods take no
  repo parameter (the contract discipline).
- **String ids at the boundary.** GitHub's int issue/comment numbers are stringified on the way out;
  incoming ``objective_id`` strings are ``int()``-converted at the edge — a non-numeric id raises
  ``ObjectiveStoreError``.
- **Error mapping at the boundary.** Every delegate call wraps ``GitHubError`` into
  ``ObjectiveStoreError(str(exc)) from exc`` — message text preserved verbatim.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from perk import github, objective
from perk.backends import linear, linear_backend, objective_store
from perk.backends.issue_backend import IssueBackendError
from perk.backends.issues import (
    GITHUB_BACKEND_ID,
    LINEAR_BACKEND_ID,
    resolve_issue_backend_id,
)
from perk.backends.objective_store import ObjectiveStoreError
from perk.github import GitHubError
from perk.substrate import config


@contextmanager
def _translate() -> Iterator[None]:
    """Map the GitHub objective tier's native error into the backend-neutral one (verbatim)."""
    try:
        yield
    except GitHubError as exc:
        raise ObjectiveStoreError(str(exc)) from exc


def _number(objective_id: str) -> int:
    """Convert a boundary string id to GitHub's numeric issue number (honest failure on junk)."""
    try:
        return int(objective_id)
    except ValueError as exc:
        raise ObjectiveStoreError(
            f"GitHub objective ids are numeric; got {objective_id!r}"
        ) from exc


def _objective_ref(found: github.ObjectiveIssue) -> objective_store.ObjectiveRef:
    return objective_store.ObjectiveRef(id=str(found.number), url=found.url, existed=found.existed)


class GitHubObjectiveStore:
    """``ObjectiveStore`` over GitHub Issues — a thin adapter over ``perk.github``'s objective-tier
    functions (constructor-bound ``repo_root``; str ids at the boundary; ``GitHubError`` →
    ``ObjectiveStoreError``). A verbatim move of ``GitHubIssueBackend``'s objective methods."""

    backend_id = GITHUB_BACKEND_ID

    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root

    def find_objective(self, *, run_id: str) -> objective_store.ObjectiveRef | None:
        with _translate():
            found = github.find_objective_issue(run_id=run_id, repo_root=self._repo_root)
        return None if found is None else _objective_ref(found)

    def create_objective(
        self,
        *,
        title: str,
        body: str,
        run_id: str,
        status: str = "active",
        roadmap_nodes: list[objective.ObjectiveNode] | None = None,
        dry_run: bool = False,
    ) -> objective_store.ObjectiveRef:
        with _translate():
            created = github.create_objective_issue(
                title=title,
                body=body,
                repo_root=self._repo_root,
                run_id=run_id,
                status=status,
                roadmap_nodes=roadmap_nodes,
                dry_run=dry_run,
            )
        return _objective_ref(created)

    def get_objective(self, *, objective_id: str) -> objective_store.ObjectiveState | None:
        number = _number(objective_id)
        with _translate():
            state = github.get_objective(number=number, repo_root=self._repo_root)
        if state is None:
            return None
        return objective_store.ObjectiveState(
            id=str(state.number),
            url=state.url,
            title=state.title,
            header=state.header,
            nodes=state.nodes,
        )

    def update_objective_header(
        self, *, objective_id: str, fields: dict[str, object], dry_run: bool = False
    ) -> objective_store.ObjectiveHeaderUpdate:
        number = _number(objective_id)
        with _translate():
            updated = github.update_objective_header(
                number=number, fields=fields, repo_root=self._repo_root, dry_run=dry_run
            )
        return objective_store.ObjectiveHeaderUpdate(
            fields_updated=updated.fields_updated, dry_run=updated.dry_run
        )

    def update_objective_node(
        self,
        *,
        objective_id: str,
        node_id: str,
        status: objective.NodeStatus | None = None,
        pr: str | None = None,
        description: str | None = None,
        dry_run: bool = False,
    ) -> objective_store.ObjectiveNodeUpdate:
        number = _number(objective_id)
        with _translate():
            updated = github.update_objective_node(
                number=number,
                node_id=node_id,
                status=status,
                pr=pr,
                description=description,
                repo_root=self._repo_root,
                dry_run=dry_run,
            )
        return objective_store.ObjectiveNodeUpdate(
            objective_id=str(updated.number),
            node_id=updated.node_id,
            comment_updated=updated.comment_updated,
            dry_run=updated.dry_run,
        )

    def update_objective_body(
        self, *, objective_id: str, prose: str, dry_run: bool = False
    ) -> objective_store.ObjectiveBodyUpdate:
        number = _number(objective_id)
        with _translate():
            updated = github.update_objective_body(
                number=number, prose=prose, repo_root=self._repo_root, dry_run=dry_run
            )
        return objective_store.ObjectiveBodyUpdate(
            objective_id=str(updated.number),
            comment_id=None if updated.comment_id is None else str(updated.comment_id),
            updated=updated.updated,
            dry_run=updated.dry_run,
        )

    def save_node_plan(
        self,
        *,
        objective_id: str,
        node_id: str,
        header_fields: dict[str, object],
        plan_markdown: str,
        dry_run: bool = False,
    ) -> objective_store.ObjectiveRef | None:
        """GitHub does NOT unify node + plan (the roadmap lives in one objective issue's body, not
        in per-node issues) — always ``None`` so the caller takes the standalone plan-issue path."""
        return None

    def close_objective(self, *, objective_id: str, dry_run: bool = False) -> bool:
        """Close the GitHub objective issue (byte-identical to the issue tier's prior close)."""
        number = _number(objective_id)
        with _translate():
            return github.close_issue(number=number, repo_root=self._repo_root, dry_run=dry_run)


def resolve_objective_store_id(repo_root: Path) -> str:
    """Resolve the repo's objective-store selection — single-sourced off the ``[issues]`` table.

    An objective and its plan/learn issues share one backend selection (both populations live in the
    same tracker), so this re-exports ``resolve_issue_backend_id`` rather than reading a separate
    config key. Unknown/malformed config raises ``IssueBackendError`` (every caller's existing error
    boundary handles it).
    """
    return resolve_issue_backend_id(repo_root)


def resolve_objective_store(repo_root: Path) -> objective_store.ObjectiveStore:
    """Resolve the repo's objective store from the committed ``[issues]`` config table.

    Mirrors ``resolve_issue_backend``: ``resolve_objective_store_id`` validates the selection and
    this constructs the matching store. The Linear arm requires a committed ``[issues] team`` and
    the ``LINEAR_API_KEY`` env var (either missing raises the same hinted ``IssueBackendError``
    ``resolve_issue_backend`` raises). Construction is lazy (no network).
    """
    backend_id = resolve_objective_store_id(repo_root)
    if backend_id == GITHUB_BACKEND_ID:
        return GitHubObjectiveStore(repo_root)
    if backend_id == LINEAR_BACKEND_ID:
        team = config.load_committed_issues_team(repo_root)
        if team is None:
            raise IssueBackendError(
                '[issues] team is required when backend = "linear" — '
                "set the Linear team key in .pi/perk.toml"
            )
        client = linear.client_from_env()
        return linear_backend.LinearProjectObjectiveStore(
            client, team_key=team, repo_root=repo_root
        )
    raise IssueBackendError(f"no backend implementation for {backend_id!r}")
