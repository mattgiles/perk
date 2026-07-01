"""``GitHubObjectiveStore`` — the objective-tier adapter over the GitHub substrate.

The objective-tier **contract** (``perk/backends/objective_store.py``) defines the
``ObjectiveStore`` ``Protocol``, the result dataclasses, and ``ObjectiveStoreError``. This module
makes the GitHub objective store live: ``GitHubObjectiveStore`` is a thin delegation adapter over
the sibling objective/plan substrate (``perk.backends.github.objectives`` and
``perk.backends.github.plans``). The resolver every objective-tier consumer goes through lives in
``perk/backends/resolve.py`` (mirroring the issue tier).

Adapter disciplines (mirroring ``perk/backends/github/backend.py``):

- **Late-bound delegation.** Each delegate is resolved via attribute access on the substrate
  **module object** at call time, so existing ``monkeypatch.setattr(<module>, ...)`` fixtures keep
  intercepting unchanged.
- **Constructor-bound repo context.** ``repo_root`` is bound once at construction; methods take no
  repo parameter (the contract discipline).
- **String ids at the boundary.** GitHub's int issue/comment numbers are stringified on the way out;
  incoming ``objective_id`` strings are ``int()``-converted at the edge — a non-numeric id raises
  ``ObjectiveStoreError``.
- **Error mapping at the boundary.** Every delegate call wraps ``GitHubError`` into
  ``ObjectiveStoreError(str(exc)) from exc`` — message text preserved verbatim.

The ``read_issue``/``close_issue`` delegates reach the plan/issue substrate (``plans``): a GitHub
objective **is** a single issue, so reading it for adoption and closing it on completion are
plan-tier ops. ``backend_id`` is a module-level literal (``"github"``, exactly as
``GitHubIssueBackend.backend_id``) so this module imports nothing from ``resolve.py`` — the resolver
imports this class, and a back-import would be circular.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from perk import objective
from perk.backends import engagement, objective_store
from perk.backends.github import engagement as gh_engagement
from perk.backends.github import objectives, plans
from perk.backends.github.backend import (
    _description_edit as _gh_description_edit,
)
from perk.backends.github.backend import (
    _engagement_comment as _gh_engagement_comment,
)
from perk.backends.objective_store import ObjectiveStoreError
from perk.github import GitHubError


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


def _objective_ref(found: objectives.ObjectiveIssue) -> objective_store.ObjectiveRef:
    return objective_store.ObjectiveRef(id=str(found.number), url=found.url, existed=found.existed)


class GitHubObjectiveStore:
    """``ObjectiveStore`` over GitHub Issues — a thin adapter over the GitHub objective/plan
    substrate (constructor-bound ``repo_root``; str ids at the boundary; ``GitHubError`` →
    ``ObjectiveStoreError``). A verbatim move of ``GitHubIssueBackend``'s objective methods."""

    backend_id = "github"

    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root

    def find_objective(self, *, run_id: str) -> objective_store.ObjectiveRef | None:
        with _translate():
            found = objectives.find_objective_issue(run_id=run_id, repo_root=self._repo_root)
        return None if found is None else _objective_ref(found)

    def read_objective_source(
        self, *, source_id: str
    ) -> objective_store.AdoptableObjectiveSource | None:
        """Read a GitHub issue verbatim as an adoptable objective source (§8.30): prose = the
        issue body, ``issues=()`` (no child issues), id = the issue number string. Returned even
        when CLOSED — the cold door does the not-open refusal (via
        ``IssueBackend.read_issue.state``).
        """
        number = _number(source_id)
        with _translate():
            src = plans.read_issue(number=number, repo_root=self._repo_root)
        if src is None:
            return None
        return objective_store.AdoptableObjectiveSource(
            id=str(src.number),
            url=src.url,
            title=src.title,
            prose=src.body,
            issues=(),
        )

    def adopt_source_as_objective(
        self,
        *,
        source_id: str,
        title: str,
        prose: str,
        run_id: str,
        status: str = "active",
        base: str | None = None,
        roadmap_nodes: list[objective.ObjectiveNode],
        adopt_map: dict[str, str],
        dry_run: bool = False,
    ) -> objective_store.ObjectiveRef | None:
        """Stamp perk objective metadata additively into the GitHub issue in place (§8.30).
        ``adopt_map`` is ignored (GitHub objectives have no child issues). ``dry_run`` → ``None``
        (the caller falls back to the offline compose-preview)."""
        if dry_run:
            return None
        number = _number(source_id)
        with _translate():
            adopted = objectives.adopt_issue_as_objective(
                number=number,
                title=title,
                prose=prose,
                repo_root=self._repo_root,
                run_id=run_id,
                status=status,
                base=base,
                roadmap_nodes=roadmap_nodes,
            )
        return objective_store.ObjectiveRef(
            id=str(adopted.number), url=adopted.url, existed=adopted.existed
        )

    def supersede_objective(
        self,
        *,
        old_objective_id: str,
        title: str,
        prose: str,
        run_id: str,
        status: str = "active",
        base: str | None = None,
        roadmap_nodes: list[objective.ObjectiveNode],
        carry_map: dict[str, str],
        dry_run: bool = False,
    ) -> objective_store.ObjectiveRef | None:
        """Create a net-new objective issue superseding + closing ``old_objective_id`` (the
        supersede model). ``carry_map`` is ignored (GitHub objectives have no child issues — carried
        nodes are authored fresh rows). ``dry_run`` → ``None`` (the cold door's ``--dry-run`` is
        offline)."""
        if dry_run:
            return None
        old_number = _number(old_objective_id)
        with _translate():
            created = objectives.supersede_objective_issue(
                old_number=old_number,
                title=title,
                prose=prose,
                repo_root=self._repo_root,
                run_id=run_id,
                status=status,
                base=base,
                roadmap_nodes=roadmap_nodes,
            )
        return _objective_ref(created)

    def create_objective(
        self,
        *,
        title: str,
        body: str,
        run_id: str,
        status: str = "active",
        base: str | None = None,
        roadmap_nodes: list[objective.ObjectiveNode] | None = None,
        dry_run: bool = False,
    ) -> objective_store.ObjectiveRef:
        with _translate():
            created = objectives.create_objective_issue(
                title=title,
                body=body,
                repo_root=self._repo_root,
                run_id=run_id,
                status=status,
                base=base,
                roadmap_nodes=roadmap_nodes,
                dry_run=dry_run,
            )
        return _objective_ref(created)

    def get_objective(self, *, objective_id: str) -> objective_store.ObjectiveState | None:
        number = _number(objective_id)
        with _translate():
            state = objectives.get_objective(number=number, repo_root=self._repo_root)
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
            updated = objectives.update_objective_header(
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
            updated = objectives.update_objective_node(
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
            updated = objectives.update_objective_body(
                number=number, prose=prose, repo_root=self._repo_root, dry_run=dry_run
            )
        return objective_store.ObjectiveBodyUpdate(
            objective_id=str(updated.number),
            comment_id=None if updated.comment_id is None else str(updated.comment_id),
            updated=updated.updated,
            dry_run=updated.dry_run,
        )

    def add_objective_node(
        self,
        *,
        objective_id: str,
        phase: int,
        description: str,
        status: objective.NodeStatus = objective.NodeStatus.PENDING,
        slug: str | None = None,
        depends_on: tuple[str, ...] | None = None,
        comment: str | None = None,
        dry_run: bool = False,
    ) -> objective_store.ObjectiveNodeAdd:
        number = _number(objective_id)
        with _translate():
            added = objectives.add_objective_node(
                number=number,
                phase=phase,
                description=description,
                status=status,
                slug=slug,
                depends_on=depends_on,
                comment=comment,
                repo_root=self._repo_root,
                dry_run=dry_run,
            )
        return objective_store.ObjectiveNodeAdd(
            objective_id=str(added.number),
            node_id=added.node_id,
            comment_updated=added.comment_updated,
            dry_run=added.dry_run,
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
            return plans.close_issue(number=number, repo_root=self._repo_root, dry_run=dry_run)

    def post_status_update(self, *, objective_id: str, body: str, dry_run: bool = False) -> bool:
        """GitHub has no Project Updates surface — always ``False`` (no-op)."""
        return False

    def detect_objective_drift(self, *, objective_id: str) -> objective_store.DriftReport:
        """GitHub's roadmap block is edited atomically with the issue body — no divergence surface,
        so the drift report is trivially empty (the no-op precedent)."""
        return objective_store.DriftReport()

    def repair_objective_drift(
        self, *, objective_id: str, dry_run: bool = False
    ) -> objective_store.RepairResult:
        """GitHub has no divergence surface — an empty no-op repair."""
        return objective_store.RepairResult(
            applied=(), failed=None, remaining=(), aborted=False, dry_run=dry_run
        )

    # --- human-engagement reads ---
    # Honest over the objective issue itself (a GitHub objective IS a single issue): reuse the
    # issue-tier honest engagement reads (perk/backends/github/engagement.py) + the shared mappers
    # from perk/backends/github/backend.py. `read_node_engagement` stays a clean no-op
    # (single-issue objective — no per-node issues).

    def read_comments(self, *, objective_id: str) -> tuple[engagement.EngagementComment, ...]:
        """Honest over the objective issue's comments (reuse `gh_engagement.read_issue_comments` +
        the shared `backend._engagement_comment` mapper)."""
        number = _number(objective_id)
        with _translate():
            rows = gh_engagement.read_issue_comments(issue=number, repo_root=self._repo_root)
        return tuple(_gh_engagement_comment(row) for row in rows)

    def read_description_edits(
        self, *, objective_id: str
    ) -> tuple[engagement.DescriptionEdit, ...]:
        """Honest over the objective issue's description edit history (reuse
        `gh_engagement.read_description_edits` + the shared `backend._description_edit` mapper)."""
        number = _number(objective_id)
        with _translate():
            rows = gh_engagement.read_description_edits(issue=number, repo_root=self._repo_root)
        return tuple(_gh_description_edit(row) for row in rows)

    def read_agent_session(self, *, objective_id: str) -> engagement.AgentSessionRead:
        return engagement.EMPTY_AGENT_SESSION

    def read_node_engagement(self, *, objective_id: str, node_id: str) -> engagement.NodeEngagement:
        # GitHub objectives are one issue with no per-node issues — honest no-op (Linear-first).
        return engagement.EMPTY_NODE_ENGAGEMENT
