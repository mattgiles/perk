from contextlib import suppress
from dataclasses import dataclass, replace
from pathlib import Path

from perk import objective, plan
from perk.backends import engagement, issue_backend, objective_store
from perk.backends.issue_backend import IssueBackendError
from perk.backends.linear import attachments
from perk.backends.linear._helpers import (
    _NODE_STATUS_STATE_TYPE,
    _description_edit,
    _engagement_comment,
    _note,
    _translate_objective,
    to_linear_markdown,
)
from perk.backends.linear.client import (
    LinearClient,
    _opt_dict,
    _opt_str,
    _require_dict,
    _require_list,
    _require_str,
)
from perk.backends.linear.issue_ops import _LinearIssueOps
from perk.backends.linear.project_ops import _attachment_nodes, _LinearProjectOps
from perk.objective import drift as objective_drift


def _row_attachment_nodes(row: dict[str, object]) -> list[dict[str, object]]:
    """The raw attachment node list off a project-issue row (already normalized by the
    ``project_issues*`` selections; ``[]`` when absent)."""
    raw = row.get("attachments")
    if not isinstance(raw, list):
        return []
    result: list[dict[str, object]] = []
    for item in raw:
        node = _opt_dict(item)
        if node is not None:
            result.append(node)
    return result


# The per-project metadata sentinel issue's title (Linear exposes no public project-attachment
# mutation and no arbitrary project metadata — a canceled, empty sentinel issue attached to the
# project is the all-inside-Linear carrier of the objective-header + objective-manifest
# attachments). Discovery keys on the header ATTACHMENT, never this title.
_SENTINEL_TITLE = "Perk: objective metadata"


@dataclass(frozen=True)
class _Sentinel:
    """The located metadata sentinel issue: its ids + raw attachment nodes (the header and
    manifest envelopes ride them)."""

    uuid: str
    identifier: str
    attachments: list[dict[str, object]]


def _sentinel_from_rows(rows: list[dict[str, object]]) -> _Sentinel | None:
    """Find the metadata sentinel among already-fetched project-issue rows (zero extra queries
    for consumers that already list project issues): the issue carrying an ``objective-header``
    kind attachment. ``None`` when the project has no sentinel (not a perk objective)."""
    for row in rows:
        att_nodes = _row_attachment_nodes(row)
        if attachments.has_perk_attachment(att_nodes, kind=attachments.OBJECTIVE_HEADER_KIND):
            return _Sentinel(
                uuid=_require_str(row.get("id"), "issue id"),
                identifier=_require_str(row.get("identifier"), "issue identifier"),
                attachments=att_nodes,
            )
    return None


@dataclass(frozen=True)
class _NodeIssueHit:
    """One located node-issue: its ids, human body, the decoded ``objective-node`` payload (and
    the found attachment's own URL — the upsert identity writers must reuse), and the raw
    attachment nodes (for coexisting-envelope reads, e.g. the plan attachment)."""

    uuid: str
    identifier: str
    url: str
    body: str
    payload: dict[str, object]
    payload_url: str
    attachments: list[dict[str, object]]


# ===========================================================================
# The project-backed objective-storage tier: `LinearProjectObjectiveStore`. A Linear **Project**
# is the objective (overview content = header + Reconcilable prose, no roadmap table); the roadmap
# is materialized as node-**issues** attached to the project (each carrying an `objective-node`
# block), phases as project milestones, and explicit `depends_on` edges as blocking relations. The
# roadmap is derived live from the node-issues — it is NOT stored in the overview.
#
# The store satisfies the full `ObjectiveStore` protocol (conformance binding in the tests) and is
# the resolver's `linear` arm. One shared `client` gives both owned op classes a single shared
# `_team_id_cache` (the single-shared-cache property, now via the client). Every method body wraps
# in `_translate_objective()` (IssueBackendError → ObjectiveStoreError, verbatim).
#
# Read model (`get_objective`): the roadmap is derived live from the project's node-issues — each
# carries an `objective-node` block (id/status/description + optional slug/comment; NO
# pr/depends_on) and a `plan-header` block whose `pr` field is the plan backlink. `depends_on` is
# reconstructed from blocking relations (`issue_blocked_by`). The overview holds the
# `objective-header` block + the Reconcilable prose region.
# ===========================================================================


class LinearProjectObjectiveStore:
    """A project-backed ``ObjectiveStore`` over Linear Projects — the full contract
    (``find`` + ``create``, ``get``, and the three ``update_*`` methods). The resolver's ``linear``
    arm."""

    backend_id = "linear"

    def __init__(self, client: LinearClient, *, team_key: str, repo_root: Path) -> None:
        self._client = client
        self._issue_ops = _LinearIssueOps(client, team_key=team_key, repo_root=repo_root)
        self._projects = _LinearProjectOps(client, team_key=team_key, repo_root=repo_root)

    def find_objective(self, *, run_id: str) -> objective_store.ObjectiveRef | None:
        """Find the objective by ``run_id``: one workspace-wide ``attachmentsForURL`` query on the
        run_id-keyed ``objective-header`` attachment URL, taking the project ref from the
        metadata sentinel's own ``project``. ``None`` on no match. State-independent by design
        (the sentinel is born canceled). Infra failures propagate (mapped to
        ``ObjectiveStoreError``), never masked as ``None``."""
        with _translate_objective():
            issue = self._issue_ops.find_issue_by_attachment_url(
                attachments.objective_header_url(run_id)
            )
            if issue is None:
                return None
            project = _opt_dict(issue.get("project"))
            if project is None:
                raise IssueBackendError(
                    f"objective-header attachment for run_id {run_id!r} rides an issue with no "
                    "project (a broken metadata sentinel)"
                )
            return objective_store.ObjectiveRef(
                id=_require_str(project.get("id"), "project id"),
                url=_require_str(project.get("url"), "project url"),
                existed=True,
            )

    def find_open_objective_by_origin(
        self, *, origin: objective.ObjectiveOrigin, exclude_run_id: str | None = None
    ) -> objective_store.ObjectiveRef | None:
        """The exhaustive-or-raise open-by-origin lookup (§8.24) — **team-scoped in v1** (a
        cross-team origin-stamped objective is invisible; documented limitation).

        Sweeps EVERY team project (``list_projects``, the existing paginated read) and resolves
        each project's metadata sentinel (``_find_sentinel`` — the sentinel IS the authoritative
        objective identity; no Reconcilable-marker heuristic). A sentinel-less project is
        skipped — the only sane arm for a team containing ordinary (non-perk) projects, and the
        same accepted create-crash orphan window ``find_objective`` already tolerates. A
        kind-matched header attachment with a malformed payload raises
        (``attachments.find_perk_attachment`` is fail-loud — the uncertainty raise); an origin
        outside the closed vocabulary raises via ``objective.origin_value``. A surviving match
        costs ONE ``project_or_none`` state read: ``completed``/``canceled`` ⇒ closed, skipped;
        anything else (including a missing state) ⇒ open. The sweep costs one ``project_issues``
        query per team project — the price of authority on a rare launch-time path (never a TAB
        path); every query composed here (``list_projects`` / ``project_issues`` /
        ``project_or_none``) is an existing production query shape.
        """
        with _translate_objective():
            for project in self._projects.list_projects():
                project_id = _require_str(project.get("id"), "project id")
                sentinel = self._find_sentinel(project_id)
                if sentinel is None:
                    continue  # not a perk objective (or the accepted create-crash orphan)
                header_att = attachments.find_perk_attachment(
                    sentinel.attachments, kind=attachments.OBJECTIVE_HEADER_KIND
                )
                if header_att is None:
                    continue  # unreachable in practice: the sentinel keys on this kind
                try:
                    stored = objective.origin_value(header_att.payload.get("origin"))
                except ValueError as exc:
                    raise IssueBackendError(f"objective {project_id!r}: {exc}") from exc
                if stored is None or stored is not origin:
                    continue
                run_id = header_att.payload.get("run_id")
                if (
                    exclude_run_id is not None
                    and isinstance(run_id, str)
                    and run_id == exclude_run_id
                ):
                    continue
                state_row = self._projects.project_or_none(project_id, "id url state")
                state = None if state_row is None else _opt_str(state_row.get("state"))
                if state in ("completed", "canceled"):
                    continue  # closed — not part of the open population
                url = None if state_row is None else _opt_str(state_row.get("url"))
                if url is None:
                    url = _require_str(project.get("url"), "project url")
                return objective_store.ObjectiveRef(id=project_id, url=url, existed=True)
            return None

    def read_objective_source(
        self, *, source_id: str
    ) -> objective_store.AdoptableObjectiveSource | None:
        """Read a Linear **Project** (and its issues) verbatim as an adoptable objective source
        (§8.30): prose = the project overview ``content`` (untrusted DATA); ``issues`` = the
        project's existing issues (title/body verbatim). ``None`` when the project is absent;
        infra failures propagate (mapped to ``ObjectiveStoreError``)."""
        with _translate_objective():
            project = self._projects.project_or_none(source_id, "id url name content")
            if project is None:
                return None
            content = project.get("content")
            prose = _opt_str(content) or ""
            issues = tuple(
                objective_store.AdoptableSourceIssue(
                    id=_require_str(issue.get("id"), "issue id"),
                    identifier=_require_str(issue.get("identifier"), "issue identifier"),
                    url=_require_str(issue.get("url"), "issue url"),
                    title=_require_str(issue.get("title"), "issue title"),
                    body=_require_str(issue.get("description"), "issue description"),
                )
                for issue in self._projects.project_issues_for_adoption(source_id)
                # A metadata sentinel is never an adoptable/mappable candidate.
                if not attachments.has_perk_attachment(
                    _row_attachment_nodes(issue), kind=attachments.OBJECTIVE_HEADER_KIND
                )
            )
            return objective_store.AdoptableObjectiveSource(
                id=source_id,
                url=_require_str(project.get("url"), "project url"),
                title=_require_str(project.get("name"), "project name"),
                prose=prose,
                issues=issues,
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
        """Stamp perk's objective metadata **additively** into a pre-existing Linear Project IN
        PLACE (§8.30), never minting a second project.

        Composes the new overview preserving the original verbatim (MODEL prose in the Reconcilable
        region + header(``adopted_from=source_id``) + manifest + the ``Adopted-from`` Immutable
        archive note), one milestone per phase (de-duped against existing milestones), node-issues
        (mapped → the ``objective-node`` block stamped additively into the existing issue,
        title/body verbatim, + phase milestone + the ``perk:objective-node`` label; unmapped → fresh
        node-issue), and a blocking relation per explicit ``depends_on``. Idempotent on ``run_id``.
        ``dry_run`` → ``None``; an empty ``roadmap_nodes`` raises."""
        if dry_run:
            return None
        with _translate_objective():
            existing = self.find_objective(run_id=run_id)
            if existing is not None:
                return existing

            nodes = list(roadmap_nodes)
            if not nodes:
                raise IssueBackendError(
                    "objective roadmap is empty: an objective needs at least one node"
                )

            project = self._projects.project_or_none(source_id, "id url name content")
            if project is None:
                raise IssueBackendError(f"Linear project {source_id!r} not found")
            project_url = _require_str(project.get("url"), "project url")
            original_overview = project.get("content")
            original_overview = _opt_str(original_overview) or ""

            # Resolve each adopt_map value (an id OR human identifier) to an existing project-issue
            # record — fail-loud on an id not in the project (the author named a non-member issue).
            existing_issues = self._projects.project_issues_for_adoption(source_id)
            by_key: dict[str, dict[str, object]] = {}
            for issue in existing_issues:
                if attachments.has_perk_attachment(
                    _row_attachment_nodes(issue), kind=attachments.OBJECTIVE_HEADER_KIND
                ):
                    continue  # a metadata sentinel is never a mappable candidate
                by_key[_require_str(issue.get("id"), "issue id")] = issue
                by_key[_require_str(issue.get("identifier"), "issue identifier")] = issue
            resolved_adopt: dict[str, dict[str, object]] = {}
            for node_id, source_issue in adopt_map.items():
                target = by_key.get(source_issue)
                if target is None:
                    raise IssueBackendError(
                        f"objective node {node_id!r} adopts issue {source_issue!r}, which is not a "
                        f"member of project {source_id!r}"
                    )
                resolved_adopt[node_id] = target

            # --- compose the overview, preserving the original verbatim (Immutable archive);
            # the header(`adopted_from`) + manifest ride the adopted project's fresh sentinel ---
            grouped = objective.group_nodes_by_phase(nodes)
            names = objective.enrich_phase_names(prose, [key for key, _ in grouped])
            overview = self._compose_overview(prose, original_overview=original_overview)
            # Adopt in place: PATCH the existing project's overview (NOT create_project).
            overview = plan.prepend_callout(
                overview,
                objective.objective_callout(source_id),
                command=f"perk objective plan {source_id}",
            )
            self._projects.update_project_content(source_id, overview)

            header = objective.ObjectiveHeader(
                run_id=run_id,
                created=plan.now_iso(),
                objective_comment_id=None,
                status=status,
                base=base,
                adopted_from=source_id,
            )
            manifest_names = {f"{key[0]}{key[1]}": value for key, value in names.items()}
            self._create_metadata_sentinel(
                project_id=source_id,
                run_id=run_id,
                header_fields=objective.render_header_block(header),
                manifest_fields=objective.render_manifest_block(nodes, manifest_names),
            )

            # --- one milestone per phase, de-duped against the project's EXISTING milestones ---
            known_milestones: dict[str, str] = {
                _require_str(m["name"], "milestone name"): _require_str(m["id"], "milestone id")
                for m in self._projects.project_milestones(source_id)
            }
            phase_milestone = self._resolve_phase_milestones(
                source_id, grouped, names, known=known_milestones
            )

            node_label_id, _ = self._issue_ops._ensure_label_id(
                objective.OBJECTIVE_NODE_LABEL,
                color=objective.OBJECTIVE_NODE_LABEL_COLOR,
                description=objective.OBJECTIVE_NODE_LABEL_DESCRIPTION,
            )
            node_uuid: dict[str, str] = {}
            for node in sorted(nodes, key=lambda n: objective.node_sort_key(n.id)):
                milestone_id = phase_milestone[objective.derive_phase(node.id)]
                if node.id in resolved_adopt:
                    # Mapped: stamp the node block ADDITIVELY into the existing issue (title + human
                    # body verbatim), attach to the phase milestone, add the node label additively.
                    node_uuid[node.id] = self._stamp_adopted_node_issue(
                        node,
                        resolved_adopt[node.id],
                        milestone_id=milestone_id,
                        label_id=node_label_id,
                    )
                else:
                    # Unmapped: mint a fresh node-issue (the create_objective path).
                    node_uuid[node.id] = self._materialize_node_issue(
                        node,
                        project_id=source_id,
                        milestone_id=milestone_id,
                        label_id=node_label_id,
                    )

            self._create_dependency_relations(nodes, node_uuid)

            return objective_store.ObjectiveRef(id=source_id, url=project_url, existed=False)

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
        delivery: objective.DeliveryPolicy | None = None,
        delivery_lineage: str | None = None,
        close_predecessor: bool = True,
        dry_run: bool = False,
    ) -> objective_store.ObjectiveRef | None:
        """Re-author the objective as a **net-new project** that supersedes + completes the old one.

        Creates the new project (overview header carries ``supersedes=<old>``) and its node-issues,
        **except** for ``carry_map`` nodes: instead of minting a fresh node-issue, the mapped
        existing node-issue is **moved** into the new project (preserving identity / open PRs /
        discussion), its ``objective-node`` block re-stamped to the new roadmap node id and
        re-attached to the new project's phase milestone. Then closes the old project fail-open
        (``superseded_by`` stamp, Cancel every dropped un-carried still-open node-issue, mark
        complete). Idempotent on ``run_id``; ``dry_run`` → ``None``; an empty ``roadmap_nodes``
        raises.

        **Origin carry (§8.24):** before composing the successor header, the create arm resolves
        the OLD project's sentinel and validates its stored header ``origin`` through
        ``objective.origin_value`` (a junk stored value raises), stamping the carried value into
        the successor — no parameter (origin stays store/launch-owned). A sentinel-less /
        header-less old project carries nothing (tolerant of the documented create-crash orphan
        window). The read happens before ``projectCreate`` so a junk origin never orphans a
        half-made successor project.

        ``close_predecessor=False`` is the §8.53 deferred-close arm: no old-side stamp / cancels /
        completion (those move to :meth:`finalize_supersession`), and the found-by-``run_id`` arm
        is **convergent** — it verifies + completes the interrupted subordinate creation writes
        (manifest attachment, overview callout, milestones, each carried move re-applied
        idempotently, missing fresh node-issues, dependency relations). The
        ``close_predecessor=True`` found-arm keeps today's early return byte-unchanged.

        **Flagged not-live-proven** (mirrors the other project-store mutations) — verify at the
        Linear smoke gate.
        """
        if dry_run:
            return None
        with _translate_objective():
            existing = self.find_objective(run_id=run_id)
            if existing is not None:
                if not close_predecessor:
                    self._converge_superseding_project(
                        project_id=existing.id,
                        prose=prose,
                        nodes=list(roadmap_nodes),
                        carry_map=carry_map,
                    )
                return existing

            nodes = list(roadmap_nodes)
            if not nodes:
                raise IssueBackendError(
                    "objective roadmap is empty: an objective needs at least one node"
                )

            # The origin carry (§8.24): read the OLD sentinel's stored origin (validated — junk
            # raises) before any successor write. Sentinel-less/header-less carries nothing.
            carried_origin: objective.ObjectiveOrigin | None = None
            old_sentinel = self._find_sentinel(old_objective_id)
            if old_sentinel is not None:
                old_header_att = attachments.find_perk_attachment(
                    old_sentinel.attachments, kind=attachments.OBJECTIVE_HEADER_KIND
                )
                if old_header_att is not None:
                    try:
                        carried_origin = objective.origin_value(
                            old_header_att.payload.get("origin")
                        )
                    except ValueError as exc:
                        raise IssueBackendError(f"objective {old_objective_id!r}: {exc}") from exc

            # --- create the new (superseding) project + its overview + its fresh sentinel
            # (header carries `supersedes=<old>`) ---
            grouped = objective.group_nodes_by_phase(nodes)
            names = objective.enrich_phase_names(prose, [key for key, _ in grouped])
            overview = self._compose_overview(prose)
            created = self._projects.create_project(name=title, content=overview)
            project_id = created["id"]
            assert isinstance(project_id, str)
            url = created["url"]
            assert isinstance(url, str)
            header = objective.ObjectiveHeader(
                run_id=run_id,
                created=plan.now_iso(),
                objective_comment_id=None,
                status=status,
                base=base,
                supersedes=old_objective_id,
                delivery=None if delivery is None else delivery.value,
                delivery_lineage=delivery_lineage,
                origin=None if carried_origin is None else carried_origin.value,
            )
            manifest_names = {f"{key[0]}{key[1]}": value for key, value in names.items()}
            self._create_metadata_sentinel(
                project_id=project_id,
                run_id=run_id,
                header_fields=objective.render_header_block(header),
                manifest_fields=objective.render_manifest_block(nodes, manifest_names),
            )
            overview = plan.prepend_callout(
                overview,
                objective.objective_callout(project_id),
                command=f"perk objective plan {project_id}",
            )
            self._projects.update_project_content(project_id, overview)

            known_milestones: dict[str, str] = {}
            phase_milestone = self._resolve_phase_milestones(
                project_id, grouped, names, known=known_milestones
            )

            node_label_id, _ = self._issue_ops._ensure_label_id(
                objective.OBJECTIVE_NODE_LABEL,
                color=objective.OBJECTIVE_NODE_LABEL_COLOR,
                description=objective.OBJECTIVE_NODE_LABEL_DESCRIPTION,
            )
            node_uuid: dict[str, str] = {}
            for node in sorted(nodes, key=lambda n: objective.node_sort_key(n.id)):
                milestone_id = phase_milestone[objective.derive_phase(node.id)]
                if node.id in carry_map:
                    # Carried: MOVE the existing node-issue into the new project (identity / open
                    # PRs / discussion preserved), re-stamp its node id, re-attach to the phase.
                    node_uuid[node.id] = self._move_carried_node_issue(
                        node,
                        carry_map[node.id],
                        new_project_id=project_id,
                        milestone_id=milestone_id,
                        label_id=node_label_id,
                    )
                else:
                    # Non-carried: mint fresh (the create path).
                    node_uuid[node.id] = self._materialize_node_issue(
                        node,
                        project_id=project_id,
                        milestone_id=milestone_id,
                        label_id=node_label_id,
                    )
            self._create_dependency_relations(nodes, node_uuid)

            if close_predecessor:
                # --- close the old objective LAST, fail-open (bookkeeping never fails the
                # create) ---
                self._close_superseded_objective(old_objective_id, new_id=project_id)

            return objective_store.ObjectiveRef(id=project_id, url=url, existed=False)

    def _converge_superseding_project(
        self,
        *,
        project_id: str,
        prose: str,
        nodes: list[objective.ObjectiveNode],
        carry_map: dict[str, str],
    ) -> None:
        """The deferred-close found-arm's convergent materialization (§8.53, D10): verify and
        complete the create's subordinate writes on an already-found superseding project.

        Found-by-``run_id`` implies the sentinel + its header attachment exist (discovery IS the
        header attachment), so convergence covers everything after it: the manifest attachment
        (upserted when absent), the overview callout (the idempotent ``prepend_callout``),
        milestones (name-keyed ensure over the LIVE milestone table), every carried move
        re-applied (each write inside :meth:`_move_carried_node_issue` is an idempotent
        re-move / re-stamp / re-attach), fresh node-issues recovered by their atomic create-time
        fingerprint when the attachment write was interrupted (and created only when truly
        absent), and dependency relations created only for missing edges."""
        sentinel = self._require_sentinel(project_id)
        grouped = objective.group_nodes_by_phase(nodes)
        names = objective.enrich_phase_names(prose, [key for key, _ in grouped])
        manifest_att = attachments.find_perk_attachment(
            sentinel.attachments, kind=attachments.OBJECTIVE_MANIFEST_KIND
        )
        if manifest_att is None:
            manifest_names = {f"{key[0]}{key[1]}": value for key, value in names.items()}
            self._upsert_sentinel_manifest(
                sentinel, objective.render_manifest_block(nodes, manifest_names)
            )

        project = self._projects.project_or_none(project_id, "id url content")
        if project is not None:
            content = _opt_str(project.get("content")) or ""
            with_callout = plan.prepend_callout(
                content,
                objective.objective_callout(project_id),
                command=f"perk objective plan {project_id}",
            )
            if with_callout != content:
                self._projects.update_project_content(project_id, with_callout)

        known_milestones: dict[str, str] = {
            _require_str(m["name"], "milestone name"): _require_str(m["id"], "milestone id")
            for m in self._projects.project_milestones(project_id)
        }
        phase_milestone = self._resolve_phase_milestones(
            project_id, grouped, names, known=known_milestones
        )

        node_label_id, _ = self._issue_ops._ensure_label_id(
            objective.OBJECTIVE_NODE_LABEL,
            color=objective.OBJECTIVE_NODE_LABEL_COLOR,
            description=objective.OBJECTIVE_NODE_LABEL_DESCRIPTION,
        )
        node_uuid: dict[str, str] = {}
        recovery_rows: list[dict[str, object]] | None = None
        for node in sorted(nodes, key=lambda n: objective.node_sort_key(n.id)):
            milestone_id = phase_milestone[objective.derive_phase(node.id)]
            if node.id in carry_map:
                # Idempotent re-move: attach-to-project converges, the node-block upsert
                # replaces in place (same URL), labels add additively, milestone re-attaches.
                node_uuid[node.id] = self._move_carried_node_issue(
                    node,
                    carry_map[node.id],
                    new_project_id=project_id,
                    milestone_id=milestone_id,
                    label_id=node_label_id,
                )
            else:
                existing_node = self._find_node_issue(project_id, node.id)
                if existing_node is not None:
                    node_uuid[node.id] = existing_node.uuid
                else:
                    # The issue create and objective-node attachment are two observable writes.
                    # Lazily inspect the create-time fingerprint only when the attachment-backed
                    # lookup misses, then resume that exact issue instead of minting a duplicate.
                    if recovery_rows is None:
                        recovery_rows = self._projects.project_issues_for_materialization_recovery(
                            project_id
                        )
                    recovered_uuid = self._recover_fresh_node_issue(
                        node,
                        rows=recovery_rows,
                        milestone_id=milestone_id,
                        label_id=node_label_id,
                    )
                    node_uuid[node.id] = recovered_uuid or self._materialize_node_issue(
                        node,
                        project_id=project_id,
                        milestone_id=milestone_id,
                        label_id=node_label_id,
                    )
        self._converge_dependency_relations(nodes, node_uuid)

    def _converge_dependency_relations(
        self, nodes: list[objective.ObjectiveNode], node_uuid: dict[str, str]
    ) -> None:
        """The convergent twin of :meth:`_create_dependency_relations`: create a blocking
        relation only for the explicit ``depends_on`` edges NOT already present (read via
        ``issue_blocked_by``) — a rerun never duplicates a relation."""
        identifier_by_uuid: dict[str, str] = {}
        for node in nodes:
            if not node.depends_on:
                continue
            existing = set(self._projects.issue_blocked_by(node_uuid[node.id]))
            for dep in node.depends_on:
                if dep not in node_uuid:
                    raise IssueBackendError(
                        f"objective roadmap node {node.id!r} depends on unknown node {dep!r}"
                    )
                dep_uuid = node_uuid[dep]
                if dep_uuid not in identifier_by_uuid:
                    full = self._issue_ops._get_issue(dep_uuid, "id identifier")
                    identifier_by_uuid[dep_uuid] = _require_str(
                        full.get("identifier"), "issue identifier"
                    )
                if identifier_by_uuid[dep_uuid] in existing or dep_uuid in existing:
                    continue
                self._projects.create_issue_relation(
                    issue_id=dep_uuid, related_issue_id=node_uuid[node.id]
                )

    def _move_carried_node_issue(
        self,
        node: objective.ObjectiveNode,
        source_issue_id: str,
        *,
        new_project_id: str,
        milestone_id: str,
        label_id: str,
    ) -> str:
        """Move an existing node-issue into the superseding project (the carry path): attach it to
        the new project, re-stamp the ``objective-node`` attachment to ``node``'s id — reusing
        the EXISTING attachment's URL (the upsert identity), so the same-URL upsert replaces in
        place and never orphans a stale card — re-attach it to the phase milestone, add the node
        label additively. Returns the issue UUID (for relation creation — ``issueRelationCreate``
        is UUID-only)."""
        self._projects.attach_issue_to_project(issue_id=source_issue_id, project_id=new_project_id)
        full = self._issue_ops._get_issue(
            source_issue_id,
            "id identifier labels { nodes { id } } "
            "attachments(first: 50) { nodes { id url metadata } }",
        )
        uuid = _require_str(full.get("id"), "issue id")
        identifier = _require_str(full.get("identifier"), "issue identifier")
        existing = attachments.find_perk_attachment(
            _attachment_nodes(full), kind=attachments.OBJECTIVE_NODE_KIND
        )
        self._issue_ops.upsert_perk_attachment(
            uuid,
            kind=attachments.OBJECTIVE_NODE_KIND,
            url=existing.url if existing is not None else attachments.node_url(identifier),
            fields=objective.render_node_block(node),
        )
        labels = _require_dict(full.get("labels"), "issue.labels")
        label_ids = [
            _require_str(_require_dict(raw, "label").get("id"), "label id")
            for raw in _require_list(labels.get("nodes"), "issue.labels.nodes")
        ]
        if label_id not in label_ids:
            label_ids = [*label_ids, label_id]
        self._issue_ops._update_issue(
            uuid,
            {"labelIds": label_ids},
            what="move carried node-issue",
        )
        self._projects.attach_issue_to_milestone(issue_id=uuid, milestone_id=milestone_id)
        return uuid

    def _close_superseded_objective(self, old_objective_id: str, *, new_id: str) -> None:
        """Close the superseded objective fail-open: one implementation, two postures — the
        raising :meth:`_finalize_supersession` wrapped so a failure here NEVER fails the create
        (the new objective already exists) — the bookkeeping posture (mirrors
        ``post_status_update``)."""
        try:
            self._finalize_supersession(old_objective_id, new_id=new_id)
        except IssueBackendError as exc:
            _note(f"closing superseded objective {old_objective_id!r} skipped (non-fatal): {exc}")

    def finalize_supersession(self, *, old_objective_id: str, new_objective_id: str) -> bool:
        """The §8.53 deferred close — **raising** and **idempotent**: stamp ``superseded_by``
        into the old sentinel header (skipped when already stamped; a conflicting stamp raises),
        Cancel every dropped still-open node-issue remaining on the old project (carried
        node-issues were already MOVED out — an issue lives in one Linear project), mark the
        project complete (skipped when already completed/canceled), and post a best-effort
        status update."""
        with _translate_objective():
            self._finalize_supersession(old_objective_id, new_id=new_objective_id)
        return True

    def _finalize_supersession(self, old_objective_id: str, *, new_id: str) -> None:
        """The raising, idempotent close side (shared by :meth:`finalize_supersession` and the
        fail-open :meth:`_close_superseded_objective` wrapper)."""
        old_sentinel = self._find_sentinel(old_objective_id)
        if old_sentinel is not None:
            header_att = attachments.find_perk_attachment(
                old_sentinel.attachments, kind=attachments.OBJECTIVE_HEADER_KIND
            )
            stamped = header_att.payload.get("superseded_by") if header_att is not None else None
            if stamped is None or stamped == "":
                self._upsert_sentinel_header(old_sentinel, {"superseded_by": new_id})
            elif stamped != new_id:
                raise IssueBackendError(
                    f"objective {old_objective_id!r} is already superseded by {stamped!r} — "
                    f"refusing to re-stamp it as {new_id!r}"
                )
        self._cancel_dropped_open_node_issues(old_objective_id, {})
        if self._projects.project_state(old_objective_id) not in ("completed", "canceled"):
            self._projects.set_project_state(old_objective_id, "completed")
            try:
                self._projects.create_project_update(
                    project_id=old_objective_id,
                    body=(
                        f"This objective was superseded and marked complete; unfinished work was "
                        f"carried forward into the successor objective ({new_id})."
                    ),
                )
            except IssueBackendError as exc:
                _note(
                    f"superseded objective {old_objective_id!r} status update skipped "
                    f"(non-fatal): {exc}"
                )

    def _cancel_dropped_open_node_issues(
        self, old_objective_id: str, carry_map: dict[str, str]
    ) -> None:
        """Cancel every dropped (un-carried) still-open node-issue on the old project — node-issues
        whose Linear state type is neither ``completed`` nor ``canceled`` and whose id/identifier is
        not a ``carry_map`` value (the carried issues have already been moved out). ``done``
        node-issues are left untouched (history stays Done). Best-effort: a missing ``canceled``
        team state leaves them open (no-op)."""
        carried = set(carry_map.values())
        canceled_state_id: str | None = None
        canceled_resolved = False
        for issue in self._projects.project_issues(old_objective_id):
            if not attachments.has_perk_attachment(
                _row_attachment_nodes(issue), kind=attachments.OBJECTIVE_NODE_KIND
            ):
                continue  # foreign issue (or the metadata sentinel) — not a roadmap node
            uuid = _require_str(issue.get("id"), "issue id")
            identifier = _require_str(issue.get("identifier"), "issue identifier")
            if uuid in carried or identifier in carried:
                continue
            full = self._issue_ops._get_issue(uuid, "state { type }")
            state = _opt_dict(full.get("state"))
            state_type = _opt_str(state.get("type")) if state is not None else None
            if state_type in ("completed", "canceled"):
                continue
            if not canceled_resolved:
                canceled_state_id = self._issue_ops._workflow_state_id("canceled")
                canceled_resolved = True
            if canceled_state_id is not None:
                self._issue_ops._update_issue(
                    uuid, {"stateId": canceled_state_id}, what="cancel dropped node-issue"
                )

    # ------------------------------------------------------------------ gist projects (§8.41)

    def create_gist_source(
        self, *, title: str, prose: str, run_id: str, dry_run: bool = False
    ) -> objective_store.ObjectiveRef | None:
        """Create an objective-scoped gist as a deliberately light Linear **project**: name =
        ``title``, overview = an inline-code ``gist-header`` block + the transcoded prose. No
        milestones, no node-issues, no metadata sentinel — the overview block IS the identity
        (the pre-sentinel ``find_objective`` scan pattern; projects have no attachments).
        Idempotent on ``run_id`` via the projects scan (dual-encoding-tolerant). ``dry_run`` →
        ``None`` (falls through to the issue-tier dry-run compose preview)."""
        if dry_run:
            return None
        with _translate_objective():
            existing = self._find_gist_project(run_id)
            if existing is not None:
                return existing
            header = plan.render_gist_header(
                run_id=run_id,
                created=plan.now_iso(),
                scope=str(plan.GistScope.OBJECTIVE),
                style="inline-code",
            )
            overview = f"{header}\n\n{to_linear_markdown(prose.strip())}\n"
            created = self._projects.create_project(name=title, content=overview)
            return objective_store.ObjectiveRef(
                id=_require_str(created.get("id"), "project id"),
                url=_require_str(created.get("url"), "project url"),
                existed=False,
            )

    def _find_gist_project(self, run_id: str) -> objective_store.ObjectiveRef | None:
        """The run_id-keyed gist-project find: scan the team's projects for a ``gist-header``
        block whose ``run_id`` matches (dual-encoding-tolerant — gist projects write the
        inline-code form, but the scan reads both)."""
        for project in self._projects.list_projects():
            content = _opt_str(project.get("content")) or ""
            if plan.extract_run_id(content, header_key=plan.GIST_HEADER_KEY) == run_id:
                return objective_store.ObjectiveRef(
                    id=_require_str(project.get("id"), "project id"),
                    url=_require_str(project.get("url"), "project url"),
                    existed=True,
                )
        return None

    def list_gist_sources(self) -> tuple[issue_backend.GistSummary, ...]:
        """Every gist project (a project whose overview carries a ``gist-header`` block), with
        the stored ``scope`` and ``adopted`` = a Reconcilable region in the same overview.
        Adoption (``adopt_source_as_objective``) recomposes the overview around the Reconcilable
        markers and moves the headers onto the sentinel's attachments — so the marker pair, not
        an ``objective-header`` block, is the overview-level objectivehood signal; the original
        gist overview (with its ``gist-header``) survives verbatim in the Immutable archive note,
        which is what keeps the adopted project visible to this scan."""
        with _translate_objective():
            summaries: list[issue_backend.GistSummary] = []
            for project in self._projects.list_projects():
                content = _opt_str(project.get("content")) or ""
                if not plan.has_metadata_block(content, plan.GIST_HEADER_KEY):
                    continue
                header = plan.parse_gist_header(content)
                summaries.append(
                    issue_backend.GistSummary(
                        id=_require_str(project.get("id"), "project id"),
                        title=_opt_str(project.get("name")) or "",
                        url=_require_str(project.get("url"), "project url"),
                        body=content,
                        scope=None
                        if header is None or header.scope is None
                        else header.scope.value,
                        # The dual-encoding marker probe (the doctor's reconcilable_ok idiom):
                        # a splice that succeeds means the Reconcilable pair is present.
                        adopted=objective.replace_reconcilable_section(content, "") is not None,
                    )
                )
            return tuple(summaries)

    def create_objective(
        self,
        *,
        title: str,
        body: str,
        run_id: str,
        status: str = "active",
        base: str | None = None,
        roadmap_nodes: list[objective.ObjectiveNode] | None = None,
        delivery: objective.DeliveryPolicy | None = None,
        delivery_lineage: str | None = None,
        origin: objective.ObjectiveOrigin | None = None,
        dry_run: bool = False,
    ) -> objective_store.ObjectiveRef:
        """Create the project-backed objective: a project (overview = header + Reconcilable prose),
        one milestone per phase, one node-issue per roadmap node (in ``node_sort_key`` order),
        and a blocking relation per EXPLICIT ``depends_on`` edge. Idempotent on ``run_id``.
        ``origin`` (§8.24) stamps into the sentinel's initial header attachment atomically;
        ``None`` keeps the attachment payload key-set identical."""
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

            # Storage backstop: no surface may store a node-less objective (mirrors the
            # issue-backed store's message). After dedup + dry-run, before any backend write.
            if not nodes:
                raise IssueBackendError(
                    "objective roadmap is empty: an objective needs at least one node"
                )

            # --- compose the overview: Reconcilable(prose) only; the header + manifest ride the
            # metadata sentinel's attachments. The phase names (enriched from the prose
            # `### Phase N:` headers) seed BOTH the milestone loop below and the manifest's
            # pinned `phases` map.
            grouped = objective.group_nodes_by_phase(nodes)
            names = objective.enrich_phase_names(body, [key for key, _ in grouped])
            overview = self._compose_overview(body)
            created = self._projects.create_project(name=title, content=overview)
            project_id = created["id"]
            assert isinstance(project_id, str)
            url = created["url"]
            assert isinstance(url, str)

            # The metadata sentinel FIRST (fail-loud — it carries the objective's identity; a
            # crash before it lands orphans a header-less project invisible to find_objective,
            # the accepted one-round-trip window), before milestones/node-issues.
            header = objective.ObjectiveHeader(
                run_id=run_id,
                created=plan.now_iso(),
                objective_comment_id=None,
                status=status,
                base=base,
                delivery=None if delivery is None else delivery.value,
                delivery_lineage=delivery_lineage,
                origin=None if origin is None else origin.value,
            )
            manifest_names = {f"{key[0]}{key[1]}": value for key, value in names.items()}
            self._create_metadata_sentinel(
                project_id=project_id,
                run_id=run_id,
                header_fields=objective.render_header_block(header),
                manifest_fields=objective.render_manifest_block(nodes, manifest_names),
            )

            # Prepend the copyable `perk objective plan <project-uuid>` callout to the overview (the
            # project UUID is only known after create). One extra write, mirroring the existing
            # post-create `update_project_content` pattern; the splice helpers preserve text around
            # their blocks, so the callout is durable across reconciles/manifest re-renders.
            overview = plan.prepend_callout(
                overview,
                objective.objective_callout(project_id),
                command=f"perk objective plan {project_id}",
            )
            self._projects.update_project_content(project_id, overview)

            # --- one milestone per phase (enriched names), in grouped order ---
            # Routed through the name-keyed `ensure_phase_milestone` seam. The project
            # is brand-new, so `known` is seeded EMPTY: every phase name is a guaranteed miss and
            # creates a milestone, keeping this path's network calls byte-identical to the prior
            # blind-create loop (no extra `project_milestones` read; same `create_project_milestone`
            # sequence). The seam's reusable value is its `known is None` branch for a future
            # `add_node`-to-an-existing-objective path.
            known_milestones: dict[str, str] = {}
            phase_milestone = self._resolve_phase_milestones(
                project_id, grouped, names, known=known_milestones
            )

            # --- one node-issue per node (node-block + description), in node_sort_key order ---
            # Each node-issue carries the workspace `perk:objective-node` label (resolved once,
            # then cached): additive human-filterability, never load-bearing for discovery.
            node_label_id, _ = self._issue_ops._ensure_label_id(
                objective.OBJECTIVE_NODE_LABEL,
                color=objective.OBJECTIVE_NODE_LABEL_COLOR,
                description=objective.OBJECTIVE_NODE_LABEL_DESCRIPTION,
            )
            node_uuid: dict[str, str] = {}
            for node in sorted(nodes, key=lambda n: objective.node_sort_key(n.id)):
                # The issue UUID comes straight from the `issueCreate` response — no extra query.
                # `issueRelationCreate` is only verified for UUIDs, so relations keep them.
                node_uuid[node.id] = self._materialize_node_issue(
                    node,
                    project_id=project_id,
                    milestone_id=phase_milestone[objective.derive_phase(node.id)],
                    label_id=node_label_id,
                )

            self._create_dependency_relations(nodes, node_uuid)

            return objective_store.ObjectiveRef(id=project_id, url=url, existed=False)

    def list_objective_completion_candidates(self) -> tuple[objective_store.ObjectiveSummary, ...]:
        """The bounded completion/browse read over ONE ``first: 50`` state-bearing projects page
        (:meth:`_LinearProjectOps.list_projects_one_page` — the shared ``list_projects`` is
        deliberately untouched). Two filters:

        (a) perk-objectivehood via the Reconcilable marker pair in the overview content — a
        **best-effort heuristic** (the authoritative identity is the sentinel's header
        attachment, but sentinel discovery is per-project: N+1 queries, unacceptable per TAB); a
        crash-window orphan project or a marker-drifted objective may mis-classify — cosmetic,
        since every invoked command still validates through :meth:`get_objective`; and

        (b) ``state not in {"completed", "canceled"}`` — a missing/``None`` state passes (no
        observation is never treated as closed).

        Sorted ``createdAt``-descending locally (the query promises no order)."""
        with _translate_objective():
            rows: list[tuple[str, objective_store.ObjectiveSummary]] = []
            for project in self._projects.list_projects_one_page():
                content = _opt_str(project.get("content")) or ""
                if objective.replace_reconcilable_section(content, "") is None:
                    continue
                state = _opt_str(project.get("state"))
                if state in ("completed", "canceled"):
                    continue
                rows.append(
                    (
                        _opt_str(project.get("createdAt")) or "",
                        objective_store.ObjectiveSummary(
                            id=_require_str(project.get("id"), "project id"),
                            title=_opt_str(project.get("name")) or "",
                        ),
                    )
                )
            rows.sort(key=lambda pair: pair[0], reverse=True)
            return tuple(summary for _created, summary in rows)

    def get_objective(self, *, objective_id: str) -> objective_store.ObjectiveState | None:
        """Reconstruct the objective state from the project + its node-issues. ``None`` when the
        project is absent. The roadmap is derived live from the node-issues (never stored as a
        block): each ``objective-node`` block gives id/status/description/slug/comment; ``pr`` is
        read from the same node-issue's ``plan-header`` block (``None`` until it is written);
        ``depends_on`` is reconstructed from blocking relations. Nodes are returned sorted by
        :func:`objective.node_sort_key` — never Linear's connection order.

        Lossy round-trip (documented): an explicit ``depends_on=()`` is indistinguishable from
        "no relation" and reads back as ``None`` (sequential inference then applies downstream).

        Native-cancellation observation (§8.54): the state-bearing sibling query also observes
        each node-issue's native workflow-state type. A roadmap node whose native state type is
        ``canceled`` reads back with effective ``status=SKIPPED`` while its PERSISTED attachment
        status rides ``native_cancellations`` — the attachment is perk's persisted status; native
        canceled is the explicit external-intent read override. ``canceled`` is the only
        overriding state type (missing/unknown types observe nothing; completed/started/unstarted
        stay attachment-driven). Foreign issues and the born-canceled metadata sentinel never
        enter provenance (neither carries an ``objective-node`` attachment).
        """
        with _translate_objective():
            project = self._projects.project_or_none(objective_id, "id url name state")
            if project is None:
                return None
            issues = self._projects.project_issues_for_objective_projection(objective_id)
            # The header rides the metadata sentinel (found in the same scan — zero extra
            # queries). A project with no sentinel is not a perk objective.
            sentinel = _sentinel_from_rows(issues)
            if sentinel is None:
                return None
            header_att = attachments.find_perk_attachment(
                sentinel.attachments, kind=attachments.OBJECTIVE_HEADER_KIND
            )
            header = header_att.payload if header_att is not None else {}

            # First pass: build the (identifier, uuid, node) triples + the identifier->node-id map.
            # Issues with no `objective-node` block are foreign (human/cross-project) and are never
            # reinterpreted as roadmap nodes.
            parsed: list[tuple[str, objective.ObjectiveNode]] = []
            uuid_by_identifier: dict[str, str] = {}
            identifier_to_node: dict[str, str] = {}
            cancellations: list[objective_store.NativeCancellation] = []
            for issue in issues:
                identifier = _require_str(issue.get("identifier"), "issue identifier")
                att_nodes = _row_attachment_nodes(issue)
                node_att = attachments.find_perk_attachment(
                    att_nodes, kind=attachments.OBJECTIVE_NODE_KIND
                )
                if node_att is None:
                    continue  # foreign issue or the metadata sentinel — not a roadmap node
                node = self._node_from_payload(
                    node_att.payload,
                    identifier,
                    has_plan=attachments.has_perk_attachment(
                        att_nodes, kind=attachments.PLAN_HEADER_KIND
                    ),
                )
                if issue.get("state_type") == "canceled":
                    # The native-cancellation read override: provenance keeps the persisted
                    # attachment status; only the effective status projects as SKIPPED.
                    cancellations.append(
                        objective_store.NativeCancellation(
                            node_id=node.id, persisted_status=node.status
                        )
                    )
                    node = replace(node, status=objective.NodeStatus.SKIPPED)
                parsed.append((identifier, node))
                uuid_by_identifier[identifier] = _require_str(issue.get("id"), "issue id")
                identifier_to_node[identifier] = node.id

            # Second pass: depends_on from blocking relations. Each blocker identifier maps back to
            # its node id (foreign/cross-project blockers are dropped — they are not roadmap deps).
            # An empty result reads back as `None` (sequential inference applies downstream).
            resolved: list[objective.ObjectiveNode] = []
            for identifier, node in parsed:
                blockers = self._projects.issue_blocked_by(uuid_by_identifier[identifier])
                dep_ids = [identifier_to_node[b] for b in blockers if b in identifier_to_node]
                resolved.append(replace(node, depends_on=tuple(dep_ids) if dep_ids else None))

            sorted_nodes = sorted(resolved, key=lambda n: objective.node_sort_key(n.id))
            # Only a positive completed/canceled project state reads closed (fail-open).
            project_state = _opt_str(project.get("state"))
            return objective_store.ObjectiveState(
                id=objective_id,
                url=_require_str(project.get("url"), "project url"),
                title=_require_str(project.get("name"), "project name"),
                header=header,
                nodes=tuple(sorted_nodes),
                native_cancellations=tuple(
                    sorted(cancellations, key=lambda c: objective.node_sort_key(c.node_id))
                ),
                state="closed" if project_state in ("completed", "canceled") else "open",
            )

    def _find_node_issue(self, objective_id: str, node_id: str) -> _NodeIssueHit | None:
        """Locate the project's node-issue whose ``objective-node`` attachment carries
        ``node_id``. ``None`` when no node-issue matches. Shared by
        :meth:`update_objective_node` and :meth:`save_node_plan`."""
        for issue in self._projects.project_issues(objective_id):
            att_nodes = _row_attachment_nodes(issue)
            candidate = attachments.find_perk_attachment(
                att_nodes, kind=attachments.OBJECTIVE_NODE_KIND
            )
            if candidate is not None and candidate.payload.get("id") == node_id:
                description_raw = issue.get("description")
                return _NodeIssueHit(
                    uuid=_require_str(issue.get("id"), "issue id"),
                    identifier=_require_str(issue.get("identifier"), "issue identifier"),
                    url=_require_str(issue.get("url"), "issue url"),
                    body=_opt_str(description_raw) or "",
                    payload=candidate.payload,
                    payload_url=candidate.url,
                    attachments=att_nodes,
                )
        return None

    @staticmethod
    def _node_from_payload(
        block: dict[str, object], identifier: str, *, has_plan: bool
    ) -> objective.ObjectiveNode:
        """Reconstruct an ``ObjectiveNode`` from its ``objective-node`` attachment payload. A
        malformed payload (missing/invalid ``id``/``status``) raises ``IssueBackendError``.

        **The plan backlink is the node-issue's own identifier** (the node↔plan unification): in
        the project model the plan *is* the node-issue, so the backlink is
        self-referential. It is derived as ``canonical_pr(identifier)`` whenever the node-issue
        carries a ``plan-header`` block (i.e. a plan has been saved into it), else ``None``. This is
        stable across ``pr submit`` overwriting ``plan-header.pr`` with the GitHub PR number, so
        the land-path match (``nodes_for_pr(nodes, plan_ref.pr_id == identifier)``) holds after
        submit without changing ``nodes_for_pr`` / ``pr submit`` / ``pr land``.
        """
        node_id = block.get("id")
        status_raw = block.get("status")
        if not isinstance(node_id, str) or not node_id:
            raise IssueBackendError(f"invalid objective node on {identifier}: missing id")
        if not isinstance(status_raw, str):
            raise IssueBackendError(f"invalid objective node on {identifier}: missing status")
        try:
            status = objective.NodeStatus(status_raw)
        except ValueError as exc:
            raise IssueBackendError(
                f"invalid objective node on {identifier}: bad status {status_raw!r}"
            ) from exc
        description = block.get("description")
        slug = block.get("slug")
        comment = block.get("comment")
        # The plan backlink: the node-issue's own identifier whenever a plan has been saved into
        # it (``has_plan`` — a plan-header attachment is present), else None. Self-referential by
        # the unification model; stable across submit clobbering `plan-header.pr` with the GitHub
        # PR number.
        pr = objective.canonical_pr(identifier) if has_plan else None
        return objective.ObjectiveNode(
            id=node_id,
            description=_opt_str(description) or "",
            status=status,
            pr=pr,
            slug=_opt_str(slug),
            comment=_opt_str(comment),
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
        """Update one roadmap node-issue: re-render its ``objective-node`` block (authoritative,
        form-preserving) and best-effort mirror the node status onto the issue's Linear workflow
        state.

        ``pr`` is intentionally NOT persisted to the node block — ``render_node_block`` excludes
        ``pr``, and the backlink's single home is the node-issue's own ``plan-header``,
        read back by :meth:`get_objective`. Passing ``pr`` here is a no-op on the stored block.

        ``comment_updated`` is always ``False`` — the project model has no objective-body comment
        table (the roadmap is derived from node-issues, not a rendered comment).
        """
        with _translate_objective():
            found = self._find_node_issue(objective_id, node_id)
            if found is None:
                raise IssueBackendError(f"objective node {node_id!r} not found on {objective_id!r}")
            issue_uuid = found.uuid

            node = self._node_from_payload(
                found.payload,
                found.identifier,
                has_plan=attachments.has_perk_attachment(
                    found.attachments, kind=attachments.PLAN_HEADER_KIND
                ),
            )
            updated = objective.update_node(
                [node], node_id, status=status, pr=pr, description=description
            )
            assert updated is not None  # the match above guarantees the node exists
            new_node = updated[0]

            if dry_run:
                return objective_store.ObjectiveNodeUpdate(
                    objective_id=objective_id,
                    node_id=node_id,
                    comment_updated=False,
                    dry_run=True,
                )

            # Authoritative write: upsert the `objective-node` attachment, REUSING the found
            # attachment's URL — the upsert identity (re-deriving from the current identifier
            # would mint a second card if the identifier ever diverged from the stored key, e.g.
            # a cross-team move). `render_node_block` excludes `pr`, so a passed `pr` never lands.
            self._issue_ops.upsert_perk_attachment(
                issue_uuid,
                kind=attachments.OBJECTIVE_NODE_KIND,
                url=found.payload_url,
                fields=objective.render_node_block(new_node),
            )

            # Manifest-sync: a `description` change updates the matching manifest entry
            # (structural identity); a status/pr-only change does NOT touch the manifest. Skips
            # cleanly when the objective carries no manifest block (a pre-manifest objective).
            if description is not None:
                self._sync_manifest_node_description(objective_id, node_id, description)

            # Best-effort workflow-state mirror: nudge the issue's Linear state to match the new
            # status. The status block is the source of truth — a missing state type or a Linear
            # hiccup must never fail the node update (fail-open).
            if status is not None:
                try:
                    state_type = _NODE_STATUS_STATE_TYPE.get(status.value)
                    state_id = (
                        self._issue_ops._workflow_state_id(state_type)
                        if state_type is not None
                        else None
                    )
                    if state_id is not None:
                        self._issue_ops._update_issue(
                            issue_uuid, {"stateId": state_id}, what="mirror node status"
                        )
                except IssueBackendError as exc:
                    _note(f"node status mirror skipped (non-fatal): {exc}")

                # Project lifecycle nudge (Pillar 7): when a node enters a `started`-type status
                # (planning/in_progress/blocked), advance the project Planned→Started so an active
                # objective stops displaying as "Planned". Forward-only by construction — this only
                # ever writes `started`; completion is owned by `close_objective`. Idempotent (a
                # same-state write is a no-op) and fail-open (same posture as the mirror above).
                if _NODE_STATUS_STATE_TYPE.get(status.value) == "started":
                    with suppress(IssueBackendError):
                        self._projects.set_project_state(objective_id, "started")

            return objective_store.ObjectiveNodeUpdate(
                objective_id=objective_id,
                node_id=node_id,
                comment_updated=False,
                dry_run=False,
            )

    def write_node_cancellation_status(
        self,
        *,
        objective_id: str,
        node_id: str,
        expected_status: objective.NodeStatus,
        new_status: objective.NodeStatus,
        require_native_canceled: bool | None,
        require_no_raw_publish_claims: bool,
        dry_run: bool = False,
    ) -> objective_store.CancellationRepairOutcome:
        """The §8.54 attachment-only conditional compare-and-write (the
        ``NativeCancellationMetadataWriter`` seam) — the narrow projected-cancellation
        repair owned by ``Delivery.recover``'s cancellation-metadata variant (surfaced
        through ``perk objective doctor --fix``) and exposed to it via the persistence
        authority's optional writer capability.

        Performs a FRESH state-bearing read at the effect boundary (the projection sibling
        query), locates the node-issue, and checks every predicate against that fresh read:
        the persisted attachment status must equal ``expected_status`` (already at
        ``new_status`` → ``ALREADY_CONVERGED``; anything else → ``STALE``), the native
        workflow-state type must be canceled when ``require_native_canceled`` is True (not
        canceled when False; unchecked when ``None`` — the rollback arm), and the node-issue's
        ``plan-header`` attachment must carry NO raw ``pr``/checkpoint claims when
        ``require_no_raw_publish_claims``. Any failed predicate is ``STALE`` (skipped, never
        an abort). The write upserts ONLY the ``objective-node`` attachment — it never calls
        the generic status update and never mirrors/re-cancels the workflow state.
        ``dry_run`` validates the predicates and returns the would-be outcome without a
        write.
        """
        with _translate_objective():
            rows = self._projects.project_issues_for_objective_projection(objective_id)
            found: dict[str, object] | None = None
            payload: dict[str, object] | None = None
            payload_url: str | None = None
            att_nodes: list[dict[str, object]] = []
            for row in rows:
                nodes = _row_attachment_nodes(row)
                candidate = attachments.find_perk_attachment(
                    nodes, kind=attachments.OBJECTIVE_NODE_KIND
                )
                if candidate is not None and candidate.payload.get("id") == node_id:
                    found = row
                    payload = candidate.payload
                    payload_url = candidate.url
                    att_nodes = nodes
                    break
            if found is None or payload is None or payload_url is None:
                return objective_store.CancellationRepairOutcome.STALE
            status_raw = payload.get("status")
            if not isinstance(status_raw, str):
                return objective_store.CancellationRepairOutcome.STALE
            try:
                persisted = objective.NodeStatus(status_raw)
            except ValueError:
                return objective_store.CancellationRepairOutcome.STALE
            if persisted is new_status:
                return objective_store.CancellationRepairOutcome.ALREADY_CONVERGED
            if persisted is not expected_status:
                return objective_store.CancellationRepairOutcome.STALE
            state_type = found.get("state_type")
            if require_native_canceled is True and state_type != "canceled":
                return objective_store.CancellationRepairOutcome.STALE
            if require_native_canceled is False and state_type == "canceled":
                return objective_store.CancellationRepairOutcome.STALE
            if require_no_raw_publish_claims:
                plan_att = attachments.find_perk_attachment(
                    att_nodes, kind=attachments.PLAN_HEADER_KIND
                )
                if plan_att is not None:
                    header = plan_att.payload
                    for key in ("pr", "parent_checkpoint_sha", "published_head_sha"):
                        if header.get(key) is not None:
                            return objective_store.CancellationRepairOutcome.STALE
            if dry_run:
                return objective_store.CancellationRepairOutcome.APPLIED
            identifier = _require_str(found.get("identifier"), "issue identifier")
            node = self._node_from_payload(payload, identifier, has_plan=False)
            self._issue_ops.upsert_perk_attachment(
                _require_str(found.get("id"), "issue id"),
                kind=attachments.OBJECTIVE_NODE_KIND,
                url=payload_url,
                fields=objective.render_node_block(replace(node, status=new_status)),
            )
            return objective_store.CancellationRepairOutcome.APPLIED

    def update_objective_body(
        self, *, objective_id: str, prose: str, dry_run: bool = False
    ) -> objective_store.ObjectiveBodyUpdate:
        """Splice ``prose`` into the Reconcilable region of the project **overview** (form-
        preserving). ``comment_id`` is always ``None`` — the overview is project ``content``, not a
        comment."""
        with _translate_objective():
            project = self._projects.project_or_none(objective_id, "content")
            if project is None:
                raise IssueBackendError(f"objective {objective_id!r} not found")
            overview = project.get("content")
            overview = _opt_str(overview) or ""
            spliced = objective.replace_reconcilable_section(overview, to_linear_markdown(prose))
            if spliced is None:
                raise IssueBackendError(
                    f"objective {objective_id!r} overview has no reconcilable region"
                )
            if dry_run:
                return objective_store.ObjectiveBodyUpdate(
                    objective_id=objective_id, comment_id=None, updated=False, dry_run=True
                )
            self._projects.update_project_content(objective_id, spliced)
            # Manifest phase-pin refresh: re-derive the phase names from the spliced overview (a
            # reconcile may have rewritten a `### Phase N:` header) and refresh the sentinel
            # manifest's `phases` pins so the pin stays authoritative. Node descriptions are
            # synced via `update_objective_node`, not here. No-op when no manifest exists.
            self._refresh_manifest_phase_pins(objective_id, spliced)
            return objective_store.ObjectiveBodyUpdate(
                objective_id=objective_id, comment_id=None, updated=True, dry_run=False
            )

    def journal_carrier_id(self, *, objective_id: str) -> str | None:
        """The journal carrier is the Project **metadata sentinel issue** (§8.43): resolve it
        from the project-issues scan (the ``_find_sentinel`` path) and return its
        **identifier** (usable with ``LinearIssueBackend``'s comment ops). ``None`` when the
        project is absent; a project WITHOUT a sentinel is a broken perk objective — raises
        (translated ``ObjectiveStoreError``, mirroring the broken-sentinel raise)."""
        with _translate_objective():
            project = self._projects.project_or_none(objective_id, "id")
            if project is None:
                return None
            return self._require_sentinel(objective_id).identifier

    def update_objective_header(
        self, *, objective_id: str, fields: dict[str, object], dry_run: bool = False
    ) -> objective_store.ObjectiveHeaderUpdate:
        """Merge ``fields`` into the metadata sentinel's ``objective-header`` attachment (the
        same merge-and-upsert discipline as ``update_plan_header``). Rejects keys outside
        ``objective.OBJECTIVE_HEADER_FIELDS`` (LBYL)."""
        with _translate_objective():
            unknown = set(fields) - objective.OBJECTIVE_HEADER_FIELDS
            if unknown:
                raise IssueBackendError(f"unknown objective-header field(s): {sorted(unknown)}")
            sentinel = self._require_sentinel(objective_id)
            if dry_run:
                return objective_store.ObjectiveHeaderUpdate(
                    fields_updated=tuple(fields), dry_run=True
                )
            self._upsert_sentinel_header(sentinel, fields)
            return objective_store.ObjectiveHeaderUpdate(
                fields_updated=tuple(fields), dry_run=False
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
        """Insert a new node-**issue** into the project: compute the next ``<phase>.<n>`` id from
        the live roadmap (read back from the node-issues), then materialize ONE node-issue (the
        ``objective-node`` block + prose) under the phase's milestone (reused when the phase exists,
        minted for a brand-new phase via the name-keyed :meth:`ensure_phase_milestone` seam) and add
        a blocking relation per EXPLICIT ``depends_on`` edge (the dep BLOCKS the new node).

        ``comment_updated`` is always ``False`` — the project model has no objective-body comment
        table (the roadmap is derived from node-issues). A ``dry_run`` reads the roadmap + computes
        the new id, then returns without any write.

        **Flagged not-live-proven** (mirrors the other project-store mutations) — verify at the Node
        5.1 smoke gate.
        """
        with _translate_objective():
            state = self.get_objective(objective_id=objective_id)
            if state is None:
                raise IssueBackendError(f"objective {objective_id!r} not found")
            result = objective.add_node(
                list(state.nodes),
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
            # The stacked tail-append guard (contracts.md §8.66), against this same fresh
            # roadmap read (the header rides the same read's metadata sentinel) — dry-run
            # included.
            objective_store.ensure_stacked_tail_append(state.header, list(state.nodes), updated)
            new_node = next(n for n in updated if n.id == new_id)
            if dry_run:
                return objective_store.ObjectiveNodeAdd(
                    objective_id=objective_id, node_id=new_id, comment_updated=False, dry_run=True
                )

            # Resolve (or mint) the phase milestone by name (`known=None` lists the project's
            # milestones once — the seam's add-node branch). Once a manifest exists,
            # `manifest.phase_names` is the phase-name AUTHORITY for an existing phase (a node-add
            # must never re-derive a different name from externally-edited overview prose, which
            # would attach the node to a wrong/new milestone while the manifest stays pinned to the
            # old one); `enrich_phase_names` only SEEDS the name for a brand-new phase.
            project = self._projects.project_or_none(objective_id, "content")
            overview = project.get("content") if project is not None else ""
            overview = _opt_str(overview) or ""
            phase_key = objective.derive_phase(new_id)
            sentinel = self._find_sentinel(objective_id)
            manifest = self._sentinel_manifest(sentinel)[0] if sentinel is not None else None
            phase_key_str = objective.phase_key_str(new_id)
            if manifest is not None and phase_key_str in manifest.phase_names:
                milestone_name = manifest.phase_names[phase_key_str]
            else:
                milestone_name = objective.enrich_phase_names(overview, [phase_key])[phase_key]
            milestone_id = self._projects.ensure_phase_milestone(
                project_id=objective_id, name=milestone_name, known=None
            )

            # Materialize the single node-issue (objective-node block + prose), inline-code,
            # carrying the workspace `perk:objective-node` label (mirrors `create_objective`).
            node_label_id, _ = self._issue_ops._ensure_label_id(
                objective.OBJECTIVE_NODE_LABEL,
                color=objective.OBJECTIVE_NODE_LABEL_COLOR,
                description=objective.OBJECTIVE_NODE_LABEL_DESCRIPTION,
            )
            new_uuid = self._materialize_node_issue(
                new_node,
                project_id=objective_id,
                milestone_id=milestone_id,
                label_id=node_label_id,
            )

            # Blocking relations for EXPLICIT depends_on only (dep BLOCKS the new node).
            # `new_uuid` is the create-time UUID (issueRelationCreate is UUID-only).
            if new_node.depends_on:
                for dep in new_node.depends_on:
                    found = self._find_node_issue(objective_id, dep)
                    if found is None:
                        raise IssueBackendError(
                            f"objective node {new_id!r} depends on unknown node {dep!r}"
                        )
                    self._projects.create_issue_relation(
                        issue_id=found.uuid, related_issue_id=new_uuid
                    )

            # Manifest-sync: on a manifest-bearing objective, append the new node's entry
            # (id/slug/description; explicit `depends_on`) and pin a new phase name when the node
            # opens a phase not already in the manifest. Skips entirely on a pre-manifest objective
            # (no manifest to maintain; `doctor --fix` backfill remains the path).
            self._sync_manifest_add_node(objective_id, new_node)

            return objective_store.ObjectiveNodeAdd(
                objective_id=objective_id, node_id=new_id, comment_updated=False, dry_run=False
            )

    # ============================================ objective-write sub-steps
    # Behavior-preserving helpers shared by `create_objective` / `adopt_source_as_objective` /
    # `add_objective_node`. The orchestrators keep the once-only `_ensure_label_id` resolution and
    # pass the resolved ids + milestone map down, so the GraphQL call sequence is byte-identical.

    @staticmethod
    def _compose_overview(prose: str, *, original_overview: str | None = None) -> str:
        """Compose an objective's overview: clean human prose inside the Reconcilable markers
        (text-region delimiters for `/objective-reconcile`'s splice — NOT key-value metadata; the
        header + manifest ride the metadata sentinel's attachments). Transcoded so the HTML
        Reconcilable markers become inline-code sentinels. For an adopted project, the Immutable
        `Adopted-from` archive note (preserving the original overview verbatim) renders BELOW the
        closing marker."""
        reconcilable = (
            f"{objective.OBJECTIVE_RECONCILABLE_MARKER_START}\n"
            f"{prose.strip()}\n"
            f"{objective.OBJECTIVE_RECONCILABLE_MARKER_END}"
        )
        composed = f"{reconcilable}\n"
        if original_overview is not None:
            archive_note = objective.render_adopted_overview_note(original_overview)
            if archive_note:
                composed = f"{composed}\n{archive_note}\n"
        return to_linear_markdown(composed)

    # ============================================ the metadata sentinel (contracts.md §8.21)
    # Linear exposes no public project-attachment mutation and no arbitrary project metadata, so
    # each perk objective carries ONE canceled, empty sentinel issue on the project holding two
    # attachments — kind `objective-header` and kind `objective-manifest` (independent write
    # cadences: status stamps vs. manifest syncs; separate attachments keep each write a simple
    # whole-envelope upsert).

    def _create_metadata_sentinel(
        self,
        *,
        project_id: str,
        run_id: str,
        header_fields: dict[str, object],
        manifest_fields: dict[str, object],
    ) -> None:
        """Create the per-project metadata sentinel (fail-loud — it carries the objective's
        identity), immediately after ``projectCreate`` and before milestones/node-issues: an
        empty issue born directly in the team's canceled state (cosmetic — when the team has no
        canceled state it is created open; the sentinel is load-bearing storage either way),
        carrying the run_id-keyed header + manifest attachments. One best-effort
        human-discoverability call adds it to the project's Resources (fail-open)."""
        state_id = self._issue_ops._workflow_state_id("canceled")
        ref, uuid = self._issue_ops._create_issue_raw(
            title=_SENTINEL_TITLE,
            description="",
            project_id=project_id,
            state_id=state_id,
        )
        self._issue_ops.upsert_perk_attachment(
            uuid,
            kind=attachments.OBJECTIVE_HEADER_KIND,
            url=attachments.objective_header_url(run_id),
            fields=header_fields,
        )
        self._issue_ops.upsert_perk_attachment(
            uuid,
            kind=attachments.OBJECTIVE_MANIFEST_KIND,
            url=attachments.objective_manifest_url(run_id),
            fields=manifest_fields,
        )
        try:
            self._projects.create_entity_external_link(
                project_id=project_id, label="Perk metadata", url=ref.url
            )
        except IssueBackendError as exc:
            _note(f"sentinel Resources link skipped (non-fatal): {exc}")

    def _find_sentinel(self, project_id: str) -> _Sentinel | None:
        """Locate the project's metadata sentinel (its own ``project_issues`` scan — the write
        paths' entry; readers that already hold the rows use :func:`_sentinel_from_rows`)."""
        return _sentinel_from_rows(self._projects.project_issues(project_id))

    def _require_sentinel(self, project_id: str) -> _Sentinel:
        sentinel = self._find_sentinel(project_id)
        if sentinel is None:
            raise IssueBackendError(
                f"objective {project_id!r} has no perk metadata sentinel (not a perk objective)"
            )
        return sentinel

    def _upsert_sentinel_header(self, sentinel: _Sentinel, fields: dict[str, object]) -> None:
        """Merge ``fields`` into the sentinel's header attachment and upsert the whole envelope
        (same merge discipline as ``update_plan_header``; the found attachment's URL is the
        upsert identity)."""
        found = attachments.find_perk_attachment(
            sentinel.attachments, kind=attachments.OBJECTIVE_HEADER_KIND
        )
        if found is None:
            raise IssueBackendError(
                f"metadata sentinel {sentinel.identifier!r} has no objective-header attachment"
            )
        self._issue_ops.upsert_perk_attachment(
            sentinel.uuid,
            kind=attachments.OBJECTIVE_HEADER_KIND,
            url=found.url,
            fields={**found.payload, **fields},
        )

    def _upsert_sentinel_manifest(self, sentinel: _Sentinel, data: dict[str, object]) -> None:
        """Upsert the sentinel's manifest attachment (whole-envelope; reuses the existing
        attachment's URL, else keys a fresh one on the header's run_id — the backfill arm)."""
        found = attachments.find_perk_attachment(
            sentinel.attachments, kind=attachments.OBJECTIVE_MANIFEST_KIND
        )
        if found is not None:
            url = found.url
        else:
            header_att = attachments.find_perk_attachment(
                sentinel.attachments, kind=attachments.OBJECTIVE_HEADER_KIND
            )
            run_id = header_att.payload.get("run_id") if header_att is not None else None
            if not isinstance(run_id, str) or not run_id:
                raise IssueBackendError(
                    f"metadata sentinel {sentinel.identifier!r} has no manifest attachment and "
                    "no header run_id to key one"
                )
            url = attachments.objective_manifest_url(run_id)
        self._issue_ops.upsert_perk_attachment(
            sentinel.uuid,
            kind=attachments.OBJECTIVE_MANIFEST_KIND,
            url=url,
            fields=data,
        )

    @staticmethod
    def _sentinel_manifest(sentinel: _Sentinel) -> tuple[objective.Manifest | None, list[str]]:
        """Read + validate the sentinel's manifest attachment. Same absent-vs-malformed contract
        as ``objective.parse_manifest``: absent attachment → ``(None, [])`` (a valid backfill
        target); present-but-malformed → ``(None, [error…])``; valid → ``(Manifest, [])``."""
        try:
            found = attachments.find_perk_attachment(
                sentinel.attachments, kind=attachments.OBJECTIVE_MANIFEST_KIND
            )
        except IssueBackendError as exc:
            return None, [str(exc)]
        if found is None:
            return None, []
        return objective.parse_manifest_data(found.payload)

    def _resolve_phase_milestones(
        self,
        project_id: str,
        grouped: list[tuple[tuple[int, str], list[objective.ObjectiveNode]]],
        names: dict[tuple[int, str], str],
        *,
        known: dict[str, str],
    ) -> dict[tuple[int, str], str]:
        """Resolve one milestone per phase (in grouped order) via the name-keyed
        :meth:`ensure_phase_milestone` seam. ``known`` is the caller's seed: the project's EXISTING
        milestones for adopt (de-dupe), an empty dict for create (every name a guaranteed miss —
        byte-identical to the prior blind-create loop)."""
        phase_milestone: dict[tuple[int, str], str] = {}
        for key, _phase_nodes in grouped:
            phase_milestone[key] = self._projects.ensure_phase_milestone(
                project_id=project_id, name=names[key], known=known
            )
        return phase_milestone

    def _recover_fresh_node_issue(
        self,
        node: objective.ObjectiveNode,
        *,
        rows: list[dict[str, object]],
        milestone_id: str,
        label_id: str,
    ) -> str | None:
        """Resume an issue whose create succeeded before its node attachment write.

        Linear cannot attach perk metadata atomically in ``issueCreate``. It does atomically store
        a transfer-local fingerprint: target project (the query scope), node-id-prefixed title,
        clean description, phase milestone, and the perk node label. An exact unique match with no
        node attachment is therefore the interrupted fresh issue. Ambiguity or a conflicting node
        attachment fails closed; absence lets the caller mint normally.
        """
        expected_title = objective.node_issue_title(node)
        expected_description = to_linear_markdown(node.description)
        matches: list[dict[str, object]] = []
        for row in rows:
            label_ids = row.get("label_ids")
            if (
                row.get("title") != expected_title
                or row.get("description") != expected_description
                or row.get("milestone_id") != milestone_id
                or not isinstance(label_ids, (list, tuple))
                or label_id not in label_ids
            ):
                continue
            node_attachment = attachments.find_perk_attachment(
                _row_attachment_nodes(row), kind=attachments.OBJECTIVE_NODE_KIND
            )
            if node_attachment is not None:
                raise IssueBackendError(
                    f"fresh-node recovery candidate {row.get('identifier')!r} for node "
                    f"{node.id!r} already carries a conflicting objective-node attachment"
                )
            matches.append(row)
        if not matches:
            return None
        if len(matches) > 1:
            identifiers = [row.get("identifier") for row in matches]
            raise IssueBackendError(
                f"fresh-node recovery for {node.id!r} is ambiguous across issues {identifiers!r}"
            )

        row = matches[0]
        uuid = _require_str(row.get("id"), "issue id")
        identifier = _require_str(row.get("identifier"), "issue identifier")
        self._issue_ops.upsert_perk_attachment(
            uuid,
            kind=attachments.OBJECTIVE_NODE_KIND,
            url=attachments.node_url(identifier),
            fields=objective.render_node_block(node),
        )
        return uuid

    def _materialize_node_issue(
        self,
        node: objective.ObjectiveNode,
        *,
        project_id: str,
        milestone_id: str,
        label_id: str,
    ) -> str:
        """Mint a fresh node-issue (a clean prose-only description; the `objective-node` payload
        rides an attachment keyed on the fresh identifier) under the phase milestone, carrying
        the `perk:objective-node` label; return the create-time UUID (straight off `issueCreate`,
        no extra query). The fresh-mint path shared by `create_objective`, `add_objective_node`,
        adopt's unmapped branch, and the drift-repair recreate arm."""
        ref, uuid = self._issue_ops._create_issue_raw(
            title=objective.node_issue_title(node),
            description=to_linear_markdown(node.description),
            label_id=label_id,
            project_id=project_id,
            milestone_id=milestone_id,
        )
        self._issue_ops.upsert_perk_attachment(
            uuid,
            kind=attachments.OBJECTIVE_NODE_KIND,
            url=attachments.node_url(ref.id),
            fields=objective.render_node_block(node),
        )
        return uuid

    def _stamp_adopted_node_issue(
        self,
        node: objective.ObjectiveNode,
        target: dict[str, object],
        *,
        milestone_id: str,
        label_id: str,
    ) -> str:
        """Adopt's MAPPED branch: upsert the `objective-node` attachment onto the existing issue
        (title + human body preserved VERBATIM — no metadata splice), attach it to the phase
        milestone, and add the node label additively. Returns the issue's UUID."""
        uuid = _require_str(target.get("id"), "issue id")
        identifier = _require_str(target.get("identifier"), "issue identifier")
        self._issue_ops.upsert_perk_attachment(
            uuid,
            kind=attachments.OBJECTIVE_NODE_KIND,
            url=attachments.node_url(identifier),
            fields=objective.render_node_block(node),
        )
        full = self._issue_ops._get_issue(uuid, "id labels { nodes { id } }")
        labels = _require_dict(full.get("labels"), "issue.labels")
        label_ids = [
            _require_str(_require_dict(raw, "label").get("id"), "label id")
            for raw in _require_list(labels.get("nodes"), "issue.labels.nodes")
        ]
        if label_id not in label_ids:
            label_ids = [*label_ids, label_id]
        self._issue_ops._update_issue(
            uuid,
            {"labelIds": label_ids},
            what="add objective-node label",
        )
        self._projects.attach_issue_to_milestone(issue_id=uuid, milestone_id=milestone_id)
        return uuid

    def _create_dependency_relations(
        self, nodes: list[objective.ObjectiveNode], node_uuid: dict[str, str]
    ) -> None:
        """Sweep EXPLICIT `depends_on` edges into blocking relations (the dep BLOCKS the node).
        Shared by `create_objective` + adopt; byte-identical (`add_objective_node` uses the per-dep
        `_find_node_issue` variant for a single new node)."""
        for node in nodes:
            if not node.depends_on:
                continue
            for dep in node.depends_on:
                if dep not in node_uuid:
                    raise IssueBackendError(
                        f"objective roadmap node {node.id!r} depends on unknown node {dep!r}"
                    )
                self._projects.create_issue_relation(
                    issue_id=node_uuid[dep], related_issue_id=node_uuid[node.id]
                )

    # ================================================================== manifest sync
    # The sentinel's `objective-manifest` attachment is the drift baseline; these keep it current
    # on the live write paths. Every one is a clean no-op on a pre-manifest objective (no
    # manifest attachment).

    def _sync_manifest_node_description(
        self, objective_id: str, node_id: str, description: str
    ) -> None:
        """Update the matching manifest entry's description (structural identity sync)."""
        sentinel = self._find_sentinel(objective_id)
        if sentinel is None:
            return
        manifest, _errors = self._sentinel_manifest(sentinel)
        if manifest is None or all(n.id != node_id for n in manifest.nodes):
            return
        new_nodes = [
            replace(n, description=description) if n.id == node_id else n for n in manifest.nodes
        ]
        data = objective.render_manifest_block(new_nodes, manifest.phase_names)
        self._upsert_sentinel_manifest(sentinel, data)

    def _sync_manifest_add_node(self, objective_id: str, new_node: objective.ObjectiveNode) -> None:
        """Append the new node's entry to the manifest, pinning a brand-new phase's name."""
        sentinel = self._find_sentinel(objective_id)
        if sentinel is None:
            return
        manifest, _errors = self._sentinel_manifest(sentinel)
        if manifest is None:
            return  # pre-manifest objective — doctor --fix backfill is the path
        entry = objective.ObjectiveNode(
            id=new_node.id,
            description=new_node.description,
            status=objective.NodeStatus.PENDING,
            depends_on=new_node.depends_on or (),
            slug=new_node.slug,
        )
        phase_names = dict(manifest.phase_names)
        phase_key = objective.phase_key_str(new_node.id)
        if phase_key not in phase_names:
            project = self._projects.project_or_none(objective_id, "content")
            overview = project.get("content") if project is not None else ""
            overview = _opt_str(overview) or ""
            phase = objective.derive_phase(new_node.id)
            phase_names[phase_key] = objective.enrich_phase_names(overview, [phase])[phase]
        data = objective.render_manifest_block([*manifest.nodes, entry], phase_names)
        self._upsert_sentinel_manifest(sentinel, data)

    def _refresh_manifest_phase_pins(self, objective_id: str, overview: str) -> None:
        """Refresh the manifest's `phases` pins to MATCH the spliced overview's `### Phase N:`
        headers — the overview is the authority on a reconcile, so a pin tracks exactly what
        `enrich_phase_names` derives, including **reverting to the `Phase N` default** when a
        reconcile removed (or defaulted) a phase header (never preserving a now-stale custom
        name). A no-op when no sentinel/manifest exists or nothing changed."""
        sentinel = self._find_sentinel(objective_id)
        if sentinel is None:
            return
        manifest, _errors = self._sentinel_manifest(sentinel)
        if manifest is None:
            return
        keys = sorted({objective.derive_phase(n.id) for n in manifest.nodes})
        found = objective.enrich_phase_names(overview, keys)
        new_phase_names = dict(manifest.phase_names)
        for key in keys:
            new_phase_names[f"{key[0]}{key[1]}"] = found[key]
        if new_phase_names == manifest.phase_names:
            return
        data = objective.render_manifest_block(list(manifest.nodes), new_phase_names)
        self._upsert_sentinel_manifest(sentinel, data)

    # ============================================================ drift detect / repair

    def _build_observed_snapshot(self, objective_id: str) -> objective_drift.ObservedSnapshot:
        """Build the offline-diffable :class:`ObservedSnapshot` from the live project state (the
        ONLY network step of the drift pass). Raises ``IssueBackendError`` when the project is
        absent. Foreign issues (no ``objective-node`` attachment) are excluded; a node-issue
        with a present-but-unparseable payload is retained with ``block_valid=False``."""
        project = self._projects.project_or_none(objective_id, "id url name content")
        if project is None:
            raise IssueBackendError(f"objective {objective_id!r} not found")
        overview = project.get("content")
        overview = _opt_str(overview) or ""
        reconcilable_ok = objective.replace_reconcilable_section(overview, "") is not None

        milestone_names = tuple(
            _require_str(m["name"], "milestone name")
            for m in self._projects.project_milestones(objective_id)
        )
        issues = self._projects.project_issues_with_milestones(objective_id)
        # The header + manifest ride the metadata sentinel's attachments (found in the same
        # issues scan). A sentinel-less project has neither.
        sentinel = _sentinel_from_rows(issues)
        header_ok = sentinel is not None
        if sentinel is not None:
            manifest, manifest_errors = self._sentinel_manifest(sentinel)
        else:
            manifest, manifest_errors = None, []

        identifier_to_node: dict[str, str] = {}
        parsed: list[
            tuple[str, str, str | None, objective.NodeStatus | None, str | None, bool, bool]
        ] = []
        for issue in issues:
            identifier = _require_str(issue.get("identifier"), "issue identifier")
            uuid = _require_str(issue.get("id"), "issue id")
            att_nodes = _row_attachment_nodes(issue)
            milestone_raw = issue.get("milestone_name")
            milestone_name = _opt_str(milestone_raw)
            if not attachments.has_perk_attachment(att_nodes, kind=attachments.OBJECTIVE_NODE_KIND):
                continue  # foreign issue (or the metadata sentinel) — not a roadmap node
            block: dict[str, object] | None
            try:
                node_att = attachments.find_perk_attachment(
                    att_nodes, kind=attachments.OBJECTIVE_NODE_KIND
                )
            except IssueBackendError:
                node_att = None  # envelope present but payload unparseable
            block = node_att.payload if node_att is not None else None
            node_id: str | None = None
            status: objective.NodeStatus | None = None
            block_valid = True
            if block is None:
                block_valid = False  # payload present but unparseable
            else:
                raw_id = block.get("id")
                raw_status = block.get("status")
                if isinstance(raw_id, str) and raw_id:
                    node_id = raw_id
                else:
                    block_valid = False
                if isinstance(raw_status, str):
                    try:
                        status = objective.NodeStatus(raw_status)
                    except ValueError:
                        block_valid = False
                else:
                    block_valid = False
            has_plan_header = attachments.has_perk_attachment(
                att_nodes, kind=attachments.PLAN_HEADER_KIND
            )
            if node_id is not None:
                identifier_to_node[identifier] = node_id
            parsed.append(
                (identifier, uuid, node_id, status, milestone_name, has_plan_header, block_valid)
            )

        nodes: list[objective_drift.ObservedNode] = []
        for (
            identifier,
            uuid,
            node_id,
            status,
            milestone_name,
            has_plan_header,
            block_valid,
        ) in parsed:
            blockers = self._projects.issue_blocked_by(uuid)
            depends_on_observed = tuple(
                identifier_to_node[b] for b in blockers if b in identifier_to_node
            )
            unknown_blockers = tuple(b for b in blockers if b not in identifier_to_node)
            nodes.append(
                objective_drift.ObservedNode(
                    node_id=node_id,
                    identifier=identifier,
                    status=status,
                    milestone_name=milestone_name,
                    has_plan_header=has_plan_header,
                    depends_on_observed=depends_on_observed,
                    unknown_blockers=unknown_blockers,
                    block_valid=block_valid,
                )
            )
        return objective_drift.ObservedSnapshot(
            manifest=manifest,
            manifest_errors=tuple(manifest_errors),
            nodes=tuple(nodes),
            milestone_names=milestone_names,
            header_ok=header_ok,
            reconcilable_ok=reconcilable_ok,
        )

    def detect_objective_drift(self, *, objective_id: str) -> objective_drift.DriftReport:
        """Build the observed snapshot and diff it against the manifest baseline."""
        with _translate_objective():
            return objective_drift.detect_drift(self._build_observed_snapshot(objective_id))

    @staticmethod
    def _ordered_repairs(
        report: objective_drift.DriftReport,
    ) -> list[objective_drift.DriftCondition]:
        """The deterministic repair order: a manifest backfill short-circuits everything; otherwise
        milestone → node-issue → dependency (parents before edges), then by node id."""
        repairable = [c for c in report.conditions if c.repairable]
        absent = [c for c in repairable if c.code is objective_drift.DriftCode.MANIFEST_ABSENT]
        if absent:
            return absent
        order = {
            objective_drift.DriftCode.DELETED_PHASE_MILESTONE: 0,
            objective_drift.DriftCode.MISSING_NODE_ISSUE: 1,
            objective_drift.DriftCode.DEPENDENCY_MISSING_IN_LINEAR: 2,
        }
        return sorted(
            repairable, key=lambda c: (order.get(c.code, 99), c.node_id or "", c.target or "")
        )

    def repair_objective_drift(
        self, *, objective_id: str, dry_run: bool = False
    ) -> objective_store.RepairResult:
        """Apply the safe/unambiguous repairs in order, stop at the first failed write."""
        with _translate_objective():
            snapshot = self._build_observed_snapshot(objective_id)
            ordered = self._ordered_repairs(objective_drift.detect_drift(snapshot))
            if dry_run:
                return objective_store.RepairResult(
                    applied=tuple(objective_store.RepairAction(c.code, c.node_id) for c in ordered),
                    failed=None,
                    remaining=tuple(
                        c
                        for c in objective_drift.detect_drift(snapshot).conditions
                        if not c.repairable
                    ),
                    aborted=False,
                    dry_run=True,
                )
            applied: list[objective_store.RepairAction] = []
            failed: objective_store.RepairAction | None = None
            aborted = False
            created_uuid: dict[str, str] = {}
            # Node-issue recreation is deferred-edge: ALL missing node-issues are created first
            # (recorded in `recreated_ids`), then a single post-loop sweep restores every manifest
            # edge **touching a recreated node** that Linear is still missing. Detection cannot
            # raise a `DEPENDENCY_MISSING_IN_LINEAR` action while either endpoint is absent
            # (objective_drift only diffs deps between two observed nodes), so the recreate path
            # owns BOTH directions: a recreated node's own `depends_on` AND an already-existing
            # dependent's edge to the recreated node. Observed↔observed missing edges stay with the
            # explicit `DEPENDENCY_MISSING_IN_LINEAR` repairs in the loop (no overlap — the sweep
            # skips edges whose endpoints are both already-observed).
            recreated_ids: set[str] = set()
            for cond in ordered:
                try:
                    self._apply_repair(objective_id, snapshot, cond, created_uuid, recreated_ids)
                except IssueBackendError as exc:
                    failed = objective_store.RepairAction(cond.code, cond.node_id, str(exc))
                    aborted = True
                    break
                applied.append(objective_store.RepairAction(cond.code, cond.node_id))
            if not aborted and recreated_ids and snapshot.manifest is not None:
                failed = self._restore_recreated_node_edges(
                    objective_id, snapshot, recreated_ids, created_uuid
                )
                aborted = failed is not None
            remaining = objective_drift.detect_drift(
                self._build_observed_snapshot(objective_id)
            ).conditions
            return objective_store.RepairResult(
                applied=tuple(applied),
                failed=failed,
                remaining=remaining,
                aborted=aborted,
                dry_run=False,
            )

    # --- human-engagement reads ---
    # Honest project-level reads: project comments are the project's discussion threads;
    # description edits stay an honest empty (no project-level edit-history primitive). The fourth
    # flow consumer (`/objective-reconcile`) composes these with the per-node
    # `read_node_engagement`.

    def read_comments(self, *, objective_id: str) -> tuple[engagement.EngagementComment, ...]:
        """Honest over the Linear project's comments (project-level discussion threads), mapped
        through the shared ``_engagement_comment`` mapper. ``ObjectiveStoreError`` on an
        infra/auth failure (translated)."""
        with _translate_objective():
            return tuple(
                _engagement_comment(node) for node in self._projects._project_comments(objective_id)
            )

    def read_description_edits(
        self, *, objective_id: str
    ) -> tuple[engagement.DescriptionEdit, ...]:
        # Honest empty: Linear projects expose no description-edit-history primitive analogous to
        # issue `history.descriptionUpdatedBy` (the project's "edits" signal lives on its
        # node-issues, which the per-node `read_node_engagement` sections carry). A flagged
        # preview-grade deferral, not overpromised (a live gate).
        return ()

    def read_agent_session(self, *, objective_id: str) -> engagement.AgentSessionRead:
        return engagement.EMPTY_AGENT_SESSION

    def read_node_engagement(self, *, objective_id: str, node_id: str) -> engagement.NodeEngagement:
        """Read the node-issue's pre-planning engagement (comments + description edits).

        Honest for the project model: resolve the node-issue via :meth:`_find_node_issue`, then map
        its comments + description-history rows through ``_engagement_comment`` /
        ``_description_edit`` (the same neutral mappers the issue-tier reads use). An unresolvable
        node → the empty bundle. ``ObjectiveStoreError`` on an infra/auth failure (translated)."""
        with _translate_objective():
            found = self._find_node_issue(objective_id, node_id)
            if found is None:
                return engagement.EMPTY_NODE_ENGAGEMENT
            uuid = found.uuid
            comments = tuple(
                _engagement_comment(node) for node in self._issue_ops._comments_with_authors(uuid)
            )
            edits = tuple(
                _description_edit(node) for node in self._issue_ops._description_edits(uuid)
            )
            return engagement.NodeEngagement(comments=comments, description_edits=edits)

    def _apply_repair(
        self,
        objective_id: str,
        snapshot: objective_drift.ObservedSnapshot,
        cond: objective_drift.DriftCondition,
        created_uuid: dict[str, str],
        recreated_ids: set[str],
    ) -> None:
        """Dispatch one repairable condition to its writer (backfill is the no-manifest case)."""
        code = cond.code
        if code is objective_drift.DriftCode.MANIFEST_ABSENT:
            self._backfill_manifest(objective_id, snapshot)
            return
        manifest = snapshot.manifest
        assert manifest is not None  # every non-backfill repair has a parsed manifest baseline
        if code is objective_drift.DriftCode.DELETED_PHASE_MILESTONE:
            self._repair_deleted_milestone(objective_id, snapshot, manifest, cond)
        elif code is objective_drift.DriftCode.MISSING_NODE_ISSUE:
            self._repair_missing_node(objective_id, manifest, cond, created_uuid, recreated_ids)
        elif code is objective_drift.DriftCode.DEPENDENCY_MISSING_IN_LINEAR:
            self._repair_missing_dependency(objective_id, cond, created_uuid)

    def _resolve_node_uuid(
        self, objective_id: str, node_id: str, created_uuid: dict[str, str]
    ) -> str | None:
        """The node-issue UUID for ``node_id`` — from this pass's freshly-created map, else the live
        project; ``None`` when no node-issue exists."""
        if node_id in created_uuid:
            return created_uuid[node_id]
        found = self._find_node_issue(objective_id, node_id)
        if found is not None:
            created_uuid[node_id] = found.uuid
            return found.uuid
        return None

    def _repair_deleted_milestone(
        self,
        objective_id: str,
        snapshot: objective_drift.ObservedSnapshot,
        manifest: objective.Manifest,
        cond: objective_drift.DriftCondition,
    ) -> None:
        """Recreate a missing phase milestone (by pinned name) and reattach the phase's nodes."""
        pinned_name = cond.target
        assert pinned_name is not None
        phase_key = next((k for k, v in manifest.phase_names.items() if v == pinned_name), None)
        milestone_id = self._projects.ensure_phase_milestone(
            project_id=objective_id, name=pinned_name, known=None
        )
        if phase_key is not None:
            for obs in snapshot.nodes:
                if obs.node_id is not None and objective.phase_key_str(obs.node_id) == phase_key:
                    self._projects.attach_issue_to_milestone(
                        issue_id=obs.identifier, milestone_id=milestone_id
                    )

    def _restore_recreated_node_edges(
        self,
        objective_id: str,
        snapshot: objective_drift.ObservedSnapshot,
        recreated_ids: set[str],
        created_uuid: dict[str, str],
    ) -> objective_store.RepairAction | None:
        """Post-recreation edge sweep: restore every manifest edge **touching a recreated node**
        that Linear is still missing — in BOTH directions (the recreated node's own ``depends_on``
        AND an already-existing dependent's edge to it), which detection could not see while an
        endpoint was absent. Skips edges already present in Linear and observed↔observed edges
        (owned by the explicit dependency repair). Returns a failed :class:`RepairAction` on the
        first unresolvable endpoint (fail-loud), else ``None``."""
        manifest = snapshot.manifest
        assert manifest is not None
        observed_edges = {
            (dep, obs.node_id)
            for obs in snapshot.nodes
            if obs.node_id is not None
            for dep in obs.depends_on_observed
        }
        for node in manifest.nodes:
            for dep in node.depends_on or ():
                if (dep, node.id) in observed_edges:
                    continue  # already a blocking relation in Linear
                if node.id not in recreated_ids and dep not in recreated_ids:
                    continue  # observed↔observed — owned by the explicit dependency repair
                node_uuid = self._resolve_node_uuid(objective_id, node.id, created_uuid)
                dep_uuid = self._resolve_node_uuid(objective_id, dep, created_uuid)
                if node_uuid is None or dep_uuid is None:
                    return objective_store.RepairAction(
                        objective_drift.DriftCode.MISSING_NODE_ISSUE,
                        node.id,
                        f"cannot restore manifest edge {dep}→{node.id}: node-issue not found",
                    )
                self._projects.create_issue_relation(issue_id=dep_uuid, related_issue_id=node_uuid)
        return None

    def _repair_missing_node(
        self,
        objective_id: str,
        manifest: objective.Manifest,
        cond: objective_drift.DriftCondition,
        created_uuid: dict[str, str],
        recreated_ids: set[str],
    ) -> None:
        """Recreate a missing node-issue from its manifest entry (via the shared mint path:
        prose description + the node attachment, under its phase milestone); record it in
        ``recreated_ids`` and DEFER **all** its blocking relations to the post-loop edge sweep
        (so every endpoint — in either direction — exists before any edge)."""
        node_id = cond.node_id
        entry = next((n for n in manifest.nodes if n.id == node_id), None)
        if entry is None or node_id is None:
            return
        phase_key = objective.phase_key_str(node_id)
        pinned_name = manifest.phase_names.get(
            phase_key, objective.phase_label(objective.derive_phase(node_id))
        )
        milestone_id = self._projects.ensure_phase_milestone(
            project_id=objective_id, name=pinned_name, known=None
        )
        node_label_id, _ = self._issue_ops._ensure_label_id(
            objective.OBJECTIVE_NODE_LABEL,
            color=objective.OBJECTIVE_NODE_LABEL_COLOR,
            description=objective.OBJECTIVE_NODE_LABEL_DESCRIPTION,
        )
        uuid = self._materialize_node_issue(
            entry,
            project_id=objective_id,
            milestone_id=milestone_id,
            label_id=node_label_id,
        )
        created_uuid[node_id] = uuid
        recreated_ids.add(node_id)

    def _repair_missing_dependency(
        self,
        objective_id: str,
        cond: objective_drift.DriftCondition,
        created_uuid: dict[str, str],
    ) -> None:
        """Re-add a manifest blocking relation (dep BLOCKS node) absent from Linear."""
        node_id, dep = cond.node_id, cond.target
        assert node_id is not None and dep is not None
        node_uuid = self._resolve_node_uuid(objective_id, node_id, created_uuid)
        dep_uuid = self._resolve_node_uuid(objective_id, dep, created_uuid)
        if node_uuid is None or dep_uuid is None:
            raise IssueBackendError(f"cannot create relation {dep}→{node_id}: node-issue not found")
        self._projects.create_issue_relation(issue_id=dep_uuid, related_issue_id=node_uuid)

    def _backfill_manifest(
        self, objective_id: str, snapshot: objective_drift.ObservedSnapshot
    ) -> None:
        """Backfill an absent manifest from the live roadmap (the canonical read path) + observed
        milestone membership (phase pins fall back to the default label for unmilestoned phases)."""
        state = self.get_objective(objective_id=objective_id)
        if state is None:
            raise IssueBackendError(f"objective {objective_id!r} not found")
        nodes = list(state.nodes)
        phase_names: dict[str, str] = {}
        for obs in snapshot.nodes:
            if obs.node_id is not None and obs.milestone_name:
                phase_names.setdefault(objective.phase_key_str(obs.node_id), obs.milestone_name)
        for node in nodes:
            key = objective.phase_key_str(node.id)
            phase_names.setdefault(key, objective.phase_label(objective.derive_phase(node.id)))
        data = objective.render_manifest_block(nodes, phase_names)
        self._upsert_sentinel_manifest(self._require_sentinel(objective_id), data)

    def save_node_plan(
        self,
        *,
        objective_id: str,
        node_id: str,
        header_fields: dict[str, object],
        plan_markdown: str,
        dry_run: bool = False,
    ) -> objective_store.ObjectiveRef | None:
        """Write the plan **into** the objective's node-issue (the node↔plan unification).

        Upserts the ``plan-header`` attachment onto the node-issue (a unified node-issue carries
        two perk envelopes — node + plan — disambiguated by ``kind``) and upserts the plan body
        as a single node-issue comment; the title, the ``objective-node`` attachment, and the
        node prose are untouched. Returns the **node-issue** ref (``existed=True``). Raises
        ``ObjectiveStoreError`` when the node is not found.

        ``dry_run`` returns ``None`` (resolving the node-issue requires a network read; the caller
        falls back to the offline compose-preview).
        """
        if dry_run:
            return None
        with _translate_objective():
            found = self._find_node_issue(objective_id, node_id)
            if found is None:
                raise IssueBackendError(f"objective node {node_id!r} not found on {objective_id!r}")
            uuid, identifier, url = found.uuid, found.identifier, found.url

            # Upsert the plan-header attachment. Reuse an existing plan attachment's URL (the
            # upsert identity); a first save keys it on the header's run_id, else the identifier
            # (a run-id-less plan is never found by run_id anyway).
            existing = attachments.find_perk_attachment(
                found.attachments, kind=attachments.PLAN_HEADER_KIND
            )
            if existing is not None:
                plan_url = existing.url
            else:
                run_id = header_fields.get("run_id")
                key = run_id if isinstance(run_id, str) and run_id else identifier
                plan_url = attachments.plan_header_url(key)
            self._issue_ops.upsert_perk_attachment(
                uuid,
                kind=attachments.PLAN_HEADER_KIND,
                url=plan_url,
                fields=header_fields,
            )
            # The node-issue IS the plan issue here, so lead its description with the copyable
            # `perk impl <ENG-N>` callout. Keyed on the command string, so a re-save (this method
            # re-runs on every objective-linked save) never duplicates it; the human/node prose
            # below it is untouched.
            new_desc = plan.prepend_callout(
                found.body,
                plan.plan_callout(identifier),
                command=f"perk impl {identifier}",
            )
            if new_desc != found.body:
                self._issue_ops._update_issue(
                    uuid, {"description": new_desc}, what="prepend plan callout"
                )

            # Upsert the plan body as a single inline-code comment (title untouched). Find an
            # existing plan-body comment via the comment list; patch it if found, else create it.
            body_comment = plan.render_plan_body(plan_markdown, style="inline-code")
            existing_comment_id: str | None = None
            for comment in self._issue_ops._comments(uuid):
                comment_body = comment.get("body")
                if isinstance(comment_body, str) and plan.extract_plan_body(comment_body):
                    existing_comment_id = _require_str(comment.get("id"), "comment id")
                    break
            if existing_comment_id is not None:
                self._issue_ops._update_comment(existing_comment_id, body_comment)
            else:
                self._issue_ops._create_comment(uuid, body_comment)

            return objective_store.ObjectiveRef(id=identifier, url=url, existed=True)

    def close_objective(self, *, objective_id: str, dry_run: bool = False) -> bool:
        """Mark the Linear **Project** complete (``projectUpdate(state:"completed")``) — a Project
        is not an issue, so completion retires the Project, not an issue. ``dry_run`` returns
        ``False`` without a write.

        **Flagged not-live-proven** (the spike did not cover project state) — verify at the
        smoke gate alongside ``list_projects`` / ``_workflow_state_id``.
        """
        if dry_run:
            return False
        with _translate_objective():
            self._projects.set_project_state(objective_id, "completed")
        return True

    def reopen_objective(self, *, objective_id: str, dry_run: bool = False) -> bool:
        """Move a ``completed`` Linear Project back to ``started`` — converge-to-open (the mirror
        of ``close_objective``). ONLY ``completed`` reopens: any other state — including
        ``canceled`` (a human cancel is not perk's to undo) and the already-open states — returns
        ``False`` without a write. ``dry_run`` returns ``False`` without a write.
        """
        if dry_run:
            return False
        with _translate_objective():
            if self._projects.project_state(objective_id) != "completed":
                return False
            self._projects.set_project_state(objective_id, "started")
        return True

    def post_status_update(self, *, objective_id: str, body: str, dry_run: bool = False) -> bool:
        """Post a Project **Update** to the Linear Project (the status-report feed).

        ``dry_run`` returns ``False`` without a write; else posts ``projectUpdateCreate`` and
        returns ``True``. Call sites wrap this fail-open (the update is bookkeeping, never
        load-bearing). Flagged not-live-proven \u2014 verify at the smoke gate.
        """
        if dry_run:
            return False
        with _translate_objective():
            self._projects.create_project_update(project_id=objective_id, body=body)
        return True
