from pathlib import Path

from perk import objective, plan
from perk.backends import engagement, objective_store
from perk.backends.issue_backend import IssueBackendError
from perk.backends.linear._helpers import (
    _objective_ref,
    _translate_objective,
    to_linear_markdown,
)
from perk.backends.linear.client import (
    LinearClient,
    _opt_dict,
    _opt_str,
    _require_str,
)
from perk.backends.linear.issue_ops import _LinearIssueOps

# ===========================================================================
# The objective-storage tier: `LinearObjectiveStore`.
# The GitHub-twin objective behavior, lifted off `LinearIssueBackend` onto its own store behind
# the `ObjectiveStore` contract. Owns its own `_LinearIssueOps` substrate (the registered
# collaborator) and maps `IssueBackendError` → `ObjectiveStoreError` at every method boundary
# (message preserved verbatim). `objective_id` is the human Linear identifier at the boundary.
# ===========================================================================


class LinearObjectiveStore:
    """``ObjectiveStore`` over Linear issues — the GitHub-twin objective tier (two-step create +
    comment-id backfill, header LBYL, authoritative roadmap writes with best-effort comment
    re-renders, the Reconcilable splice) behind the ``ObjectiveStore`` contract. Owns its own
    :class:`_LinearIssueOps` substrate; maps ``IssueBackendError`` → ``ObjectiveStoreError`` at
    every boundary (message verbatim).

    **Dormant:** the resolver's ``linear`` arm now constructs
    :class:`LinearProjectObjectiveStore` (project-backed), so this issue-backed store is never
    resolver-wired in production. It is kept as a directly-constructable class with its own unit
    tests; retiring it is a later cleanup."""

    # The objective-backend vocabulary id — a module-level literal (never imported from the
    # resolver module, which imports us at wiring time). Mirrors `LinearIssueBackend.backend_id`.
    backend_id = "linear"

    def __init__(self, client: LinearClient, *, team_key: str, repo_root: Path) -> None:
        self._ops = _LinearIssueOps(client, team_key=team_key, repo_root=repo_root)

    def find_objective(self, *, run_id: str) -> objective_store.ObjectiveRef | None:
        with _translate_objective():
            found = self._ops._find_issue_by_run_id(
                label=objective.OBJECTIVE_LABEL,
                header_key=objective.OBJECTIVE_HEADER_KEY,
                run_id=run_id,
            )
        return None if found is None else _objective_ref(found)

    def read_objective_source(
        self, *, source_id: str
    ) -> objective_store.AdoptableObjectiveSource | None:
        """Dormant issue-backed store: no project-source surface — always ``None`` (§8.30)."""
        return None

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
        """Dormant issue-backed store: does NOT support in-place adoption — always ``None`` (the
        unambiguous "doesn't adopt" signal, mirroring ``save_node_plan → None``; §8.30)."""
        return None

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
        """Dormant issue-backed store: does NOT support superseding — always ``None`` (the
        unambiguous "doesn't support it" signal, mirroring ``adopt_source_as_objective → None``)."""
        return None

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
        if dry_run:
            return objective_store.ObjectiveRef(id="0", url="(dry-run)", existed=False)
        with _translate_objective():
            existing = self.find_objective(run_id=run_id)
            if existing is not None:
                return existing

            if roadmap_nodes is None:
                nodes, errors = objective.parse_roadmap_nodes(body)
                if errors:
                    raise IssueBackendError("invalid objective roadmap: " + "; ".join(errors))
            else:
                nodes = list(roadmap_nodes)

            # Storage backstop: no surface may store a node-less objective. Placed after the dedup
            # short-circuit and the dry-run early-return, before any label/issue write.
            if not nodes:
                raise IssueBackendError(
                    "objective roadmap is empty: an objective needs at least one node"
                )

            label_id, _ = self._ops._ensure_label_id(
                objective.OBJECTIVE_LABEL,
                color=objective.OBJECTIVE_LABEL_COLOR,
                description=objective.OBJECTIVE_LABEL_DESCRIPTION,
            )

            # Composed directly in the inline-code style (no transcoding needed — the
            # `create_learn_issue` precedent).
            header = objective.ObjectiveHeader(
                run_id=run_id,
                created=plan.now_iso(),
                objective_comment_id=None,
                status=status,
                base=base,
            )
            header_block = plan.render_metadata_block(
                objective.OBJECTIVE_HEADER_KEY,
                objective.render_header_block(header),
                style="inline-code",
            )
            roadmap_block = plan.render_metadata_block(
                objective.OBJECTIVE_ROADMAP_KEY,
                objective.render_roadmap_block(nodes),
                style="inline-code",
            )
            issue_body = f"{header_block}\n\n{roadmap_block}\n"

            created = self._ops._create_issue(
                title=title, description=issue_body, label_id=label_id
            )

            # The body comment: rendered with the HTML markers (objective.py's constants), then
            # transcoded to the inline-code sentinels.
            comment_body = to_linear_markdown(
                objective.render_body_comment(nodes, prose=body.strip())
            )
            # Prepend the copyable `perk objective plan <ENG-N>` callout (the identifier is known
            # here). The callout is sentinel-free portable Markdown, so prepending after transcoding
            # is byte-equivalent to before.
            comment_body = plan.prepend_callout(
                comment_body,
                objective.objective_callout(created.id),
                command=f"perk objective plan {created.id}",
            )
            comment_id = self._ops._create_comment_with_id(created.id, comment_body)
            self.update_objective_header(
                objective_id=created.id, fields={"objective_comment_id": comment_id}
            )
            return _objective_ref(created)

    def get_objective(self, *, objective_id: str) -> objective_store.ObjectiveState | None:
        with _translate_objective():
            issue = self._ops._issue_or_none(objective_id, "id identifier url title description")
            if issue is None:
                return None
            description = issue.get("description")
            body = _opt_str(description) or ""
            header = plan.find_metadata_block(body, objective.OBJECTIVE_HEADER_KEY) or {}
            nodes, errors = objective.parse_roadmap_nodes(body)
            if errors:
                raise IssueBackendError(
                    f"invalid objective roadmap on {objective_id!r}: " + "; ".join(errors)
                )
            return objective_store.ObjectiveState(
                id=_require_str(issue.get("identifier"), "issue identifier"),
                url=_require_str(issue.get("url"), "issue url"),
                title=_require_str(issue.get("title"), "issue title"),
                header=header,
                nodes=tuple(nodes),
            )

    def update_objective_header(
        self, *, objective_id: str, fields: dict[str, object], dry_run: bool = False
    ) -> objective_store.ObjectiveHeaderUpdate:
        with _translate_objective():
            unknown = set(fields) - objective.OBJECTIVE_HEADER_FIELDS
            if unknown:
                raise IssueBackendError(f"unknown objective-header field(s): {sorted(unknown)}")
            issue = self._ops._get_issue(objective_id, "id description")
            description = issue.get("description")
            body = _opt_str(description) or ""
            header = plan.find_metadata_block(body, objective.OBJECTIVE_HEADER_KEY) or {}
            # Form-preserving merge: replace_metadata_block keeps the inline-code form on Linear
            # bodies.
            new_body = plan.replace_metadata_block(
                body, objective.OBJECTIVE_HEADER_KEY, {**header, **fields}
            )
            if dry_run:
                return objective_store.ObjectiveHeaderUpdate(
                    fields_updated=tuple(fields), dry_run=True
                )
            self._ops._update_issue(
                objective_id, {"description": new_body}, what="update objective-header"
            )
            return objective_store.ObjectiveHeaderUpdate(
                fields_updated=tuple(fields), dry_run=False
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
        with _translate_objective():
            issue = self._ops._get_issue(objective_id, "id description")
            raw_description = issue.get("description")
            body = _opt_str(raw_description) or ""
            nodes, errors = objective.parse_roadmap_nodes(body)
            if errors:
                raise IssueBackendError("invalid objective roadmap: " + "; ".join(errors))
            updated = objective.update_node(
                nodes, node_id, status=status, pr=pr, description=description
            )
            if updated is None:
                raise IssueBackendError(f"objective node {node_id!r} not found on {objective_id!r}")
            if dry_run:
                return objective_store.ObjectiveNodeUpdate(
                    objective_id=objective_id, node_id=node_id, comment_updated=False, dry_run=True
                )

            # Authoritative write: the roadmap block in the issue description (form-preserving).
            new_body = plan.replace_metadata_block(
                body, objective.OBJECTIVE_ROADMAP_KEY, objective.render_roadmap_block(updated)
            )
            self._ops._update_issue(
                objective_id, {"description": new_body}, what="update objective roadmap"
            )

            # Best-effort comment table re-render (the frontmatter is the source of truth): any
            # miss along the chain leaves comment_updated=False.
            comment_updated = False
            header = plan.find_metadata_block(new_body, objective.OBJECTIVE_HEADER_KEY) or {}
            comment_id = header.get("objective_comment_id")
            # Linear stores its string UUID; tolerate an int for symmetry with GitHub's numeric id.
            if isinstance(comment_id, str | int) and str(comment_id).strip():
                comment_body = self._ops._comment_body_or_none(str(comment_id))
                if comment_body is not None:
                    rerendered = objective.rerender_body_table(comment_body, updated)
                    if rerendered is not None:
                        self._ops._update_comment(str(comment_id), rerendered)
                        comment_updated = True
            return objective_store.ObjectiveNodeUpdate(
                objective_id=objective_id,
                node_id=node_id,
                comment_updated=comment_updated,
                dry_run=False,
            )

    def update_objective_body(
        self, *, objective_id: str, prose: str, dry_run: bool = False
    ) -> objective_store.ObjectiveBodyUpdate:
        with _translate_objective():
            issue = self._ops._get_issue(objective_id, "id description")
            raw_description = issue.get("description")
            body = _opt_str(raw_description) or ""
            header = plan.find_metadata_block(body, objective.OBJECTIVE_HEADER_KEY) or {}
            comment_id = header.get("objective_comment_id")
            if not isinstance(comment_id, str | int) or not str(comment_id).strip():
                raise IssueBackendError(f"objective {objective_id!r} has no body comment")
            comment_key = str(comment_id)
            comment_body = self._ops._comment_body_or_none(comment_key)
            if comment_body is None:
                raise IssueBackendError(f"objective {objective_id!r} has no body comment")
            # Transcode the prose on the way in — reconciled prose is caller-authored markdown and
            # may legitimately carry perk markers (identity for plain text).
            spliced = objective.replace_reconcilable_section(
                comment_body, to_linear_markdown(prose)
            )
            if spliced is None:
                raise IssueBackendError(
                    f"objective {objective_id!r} body comment has no reconcilable region"
                )
            if dry_run:
                return objective_store.ObjectiveBodyUpdate(
                    objective_id=objective_id, comment_id=comment_key, updated=False, dry_run=True
                )
            self._ops._update_comment(comment_key, spliced)
            return objective_store.ObjectiveBodyUpdate(
                objective_id=objective_id, comment_id=comment_key, updated=True, dry_run=False
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
        """Insert a new node into ``phase`` (auto-assigned ``<phase>.<n>``): re-render the
        authoritative roadmap block in the objective issue description (form-preserving) AND
        best-effort re-render the body-comment table. Mirrors :meth:`update_objective_node`."""
        with _translate_objective():
            issue = self._ops._get_issue(objective_id, "id description")
            raw_description = issue.get("description")
            body = _opt_str(raw_description) or ""
            nodes, errors = objective.parse_roadmap_nodes(body)
            if errors:
                raise IssueBackendError("invalid objective roadmap: " + "; ".join(errors))
            result = objective.add_node(
                nodes,
                phase=phase,
                description=description,
                status=status,
                slug=slug,
                depends_on=depends_on,
                comment=comment,
            )
            if result is None:
                raise IssueBackendError(
                    f"could not add node to phase {phase} on {objective_id!r} (id collision)"
                )
            updated, new_id = result
            if dry_run:
                return objective_store.ObjectiveNodeAdd(
                    objective_id=objective_id, node_id=new_id, comment_updated=False, dry_run=True
                )

            # Authoritative write: the roadmap block in the issue description (form-preserving).
            new_body = plan.replace_metadata_block(
                body, objective.OBJECTIVE_ROADMAP_KEY, objective.render_roadmap_block(updated)
            )
            self._ops._update_issue(
                objective_id, {"description": new_body}, what="add objective roadmap node"
            )

            # Best-effort comment table re-render (the frontmatter is the source of truth).
            comment_updated = False
            header = plan.find_metadata_block(new_body, objective.OBJECTIVE_HEADER_KEY) or {}
            comment_id = header.get("objective_comment_id")
            if isinstance(comment_id, str | int) and str(comment_id).strip():
                comment_body = self._ops._comment_body_or_none(str(comment_id))
                if comment_body is not None:
                    rerendered = objective.rerender_body_table(comment_body, updated)
                    if rerendered is not None:
                        self._ops._update_comment(str(comment_id), rerendered)
                        comment_updated = True
            return objective_store.ObjectiveNodeAdd(
                objective_id=objective_id,
                node_id=new_id,
                comment_updated=comment_updated,
                dry_run=False,
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
        """The issue-backed store does NOT unify node + plan (the roadmap is a table in one
        objective issue's body, not per-node issues) — always ``None`` so the caller takes the
        standalone plan-issue path."""
        return None

    def close_objective(self, *, objective_id: str, dry_run: bool = False) -> bool:
        """Move the Linear objective issue to its Done state (equivalent to
        ``LinearIssueBackend.close_issue``). ``dry_run`` returns ``False`` without a write."""
        if dry_run:
            return False
        with _translate_objective():
            self._ops._update_issue(
                objective_id, {"stateId": self._ops._done_state_id()}, what="close"
            )
        return True

    def reopen_objective(self, *, objective_id: str, dry_run: bool = False) -> bool:
        """Move a ``completed``-type objective issue back to the team's ``started`` state —
        converge-to-open (the mirror of ``close_objective``). ONLY the ``completed`` state type
        reopens: ``canceled`` (a human cancel is not perk's to undo) and the already-open types
        return ``False`` without a write. A team with no ``started`` state raises inside the
        translate CM (an infra anomaly, not a policy skip). ``dry_run`` returns ``False`` without
        a write.
        """
        if dry_run:
            return False
        with _translate_objective():
            issue = self._ops._get_issue(objective_id, "state { type }")
            state = _opt_dict(issue.get("state"))
            state_type = None if state is None else state.get("type")
            if state_type != "completed":
                return False
            state_id = self._ops._workflow_state_id("started")
            if state_id is None:
                raise IssueBackendError(
                    f"cannot reopen {objective_id}: the team has no 'started' workflow state"
                )
            self._ops._update_issue(objective_id, {"stateId": state_id}, what="reopen")
        return True

    def post_status_update(self, *, objective_id: str, body: str, dry_run: bool = False) -> bool:
        """The issue-backed store has no project status-update surface \u2014 always ``False``
        (no-op)."""
        return False

    def detect_objective_drift(self, *, objective_id: str) -> objective_store.DriftReport:
        """The issue-backed store edits its roadmap block atomically with the issue body — no
        divergence surface, so the drift report is trivially empty (no-op)."""
        return objective_store.DriftReport()

    def repair_objective_drift(
        self, *, objective_id: str, dry_run: bool = False
    ) -> objective_store.RepairResult:
        """The issue-backed store has no divergence surface — an empty no-op repair."""
        return objective_store.RepairResult(
            applied=(), failed=None, remaining=(), aborted=False, dry_run=dry_run
        )

    # --- human-engagement reads ---
    # Empty/no-op: the issue-backed store has no honest project-level objective-read surface.

    def read_comments(self, *, objective_id: str) -> tuple[engagement.EngagementComment, ...]:
        return ()

    def read_description_edits(
        self, *, objective_id: str
    ) -> tuple[engagement.DescriptionEdit, ...]:
        return ()

    def read_agent_session(self, *, objective_id: str) -> engagement.AgentSessionRead:
        return engagement.EMPTY_AGENT_SESSION

    def read_node_engagement(self, *, objective_id: str, node_id: str) -> engagement.NodeEngagement:
        # Dormant issue-backed store: the roadmap lives in one issue body, no per-node issues.
        return engagement.EMPTY_NODE_ENGAGEMENT
