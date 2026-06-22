from contextlib import suppress
from dataclasses import replace
from pathlib import Path

from perk import objective, objective_drift, plan
from perk.backends import engagement, objective_store
from perk.backends.issue_backend import IssueBackendError
from perk.backends.linear import (
    LinearClient,
    _opt_str,
    _require_dict,
    _require_list,
    _require_str,
)
from perk.backends.linear_backend._helpers import (
    _NODE_STATUS_STATE_TYPE,
    _description_edit,
    _engagement_comment,
    _translate_objective,
    to_linear_markdown,
)
from perk.backends.linear_backend.issue_ops import _LinearIssueOps
from perk.backends.linear_backend.project_ops import _LinearProjectOps

# ===========================================================================
# The project-backed objective-storage tier (Objective #548, Node 3.2):
# `LinearProjectObjectiveStore`. A Linear **Project** is the objective (overview content =
# header + Reconcilable prose, no roadmap table); the roadmap is materialized as node-**issues**
# attached to the project (each carrying an `objective-node` block), phases as project milestones,
# and explicit `depends_on` edges as blocking relations. The roadmap is derived live from the
# node-issues — it is NOT stored in the overview.
#
# Node 3.2 implemented `find_objective` + `create_objective`; Node 3.3 completes the contract with
# `get_objective` + the three `update_*` methods, so the store now satisfies the full
# `ObjectiveStore` protocol (conformance binding in the tests). Still dormant — NOT resolver-wired
# (that is Node 3.4). One shared `client` gives both owned op classes a single shared
# `_team_id_cache` (the single-shared-cache property, now via the client). Every
# method body wraps in `_translate_objective()` (IssueBackendError → ObjectiveStoreError, verbatim).
#
# Read model (`get_objective`): the roadmap is derived live from the project's node-issues — each
# carries an `objective-node` block (id/status/description + optional slug/comment; NO
# pr/depends_on) and, once Node 3.4 writes it, a `plan-header` block whose `pr` field is the plan
# backlink. `depends_on` is reconstructed from blocking relations (`issue_blocked_by`). The
# overview holds the `objective-header` block + the Reconcilable prose region.
# ===========================================================================


class LinearProjectObjectiveStore:
    """A project-backed ``ObjectiveStore`` over Linear Projects — the full contract (Node 3.2
    ``find`` + ``create``; Node 3.3 ``get`` + the three ``update_*`` methods). Dormant: not
    resolver-wired (Node 3.4)."""

    backend_id = "linear"

    def __init__(self, client: LinearClient, *, team_key: str, repo_root: Path) -> None:
        self._client = client
        self._issue_ops = _LinearIssueOps(client, team_key=team_key, repo_root=repo_root)
        self._projects = _LinearProjectOps(client, team_key=team_key, repo_root=repo_root)

    def find_objective(self, *, run_id: str) -> objective_store.ObjectiveRef | None:
        """Find the project whose overview ``objective-header`` block carries ``run_id``. Scans
        the team's projects (dual-encoding-tolerant header parse); ``None`` after the full scan.
        Infra failures propagate (mapped to ``ObjectiveStoreError``), never masked as ``None``."""
        with _translate_objective():
            for proj in self._projects.list_projects():
                content = proj.get("content")
                header = plan.find_metadata_block(
                    _opt_str(content) or "", objective.OBJECTIVE_HEADER_KEY
                )
                if header is not None and header.get("run_id") == run_id:
                    return objective_store.ObjectiveRef(
                        id=_require_str(proj.get("id"), "project id"),
                        url=_require_str(proj.get("url"), "project url"),
                        existed=True,
                    )
            return None

    def read_objective_source(
        self, *, source_id: str
    ) -> objective_store.AdoptableObjectiveSource | None:
        """Read a Linear **Project** (and its issues) verbatim as an adoptable objective source
        (#709, §8.30): prose = the project overview ``content`` (untrusted DATA); ``issues`` = the
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
        PLACE (#709, §8.30), never minting a second project.

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

            # --- compose the overview, preserving the original verbatim (Immutable archive) ---
            header = objective.ObjectiveHeader(
                run_id=run_id,
                created=plan.now_iso(),
                objective_comment_id=None,
                status=status,
                base=base,
                adopted_from=source_id,
            )
            header_block = plan.render_metadata_block(
                objective.OBJECTIVE_HEADER_KEY, header.to_data(), style="inline-code"
            )
            grouped = objective.group_nodes_by_phase(nodes)
            names = objective.enrich_phase_names(prose, [key for key, _ in grouped])
            manifest_names = {f"{key[0]}{key[1]}": value for key, value in names.items()}
            manifest_block = plan.render_metadata_block(
                objective.OBJECTIVE_MANIFEST_KEY,
                objective.render_manifest_block(nodes, manifest_names),
                style="inline-code",
            )
            reconcilable = (
                f"{objective.OBJECTIVE_RECONCILABLE_MARKER_START}\n"
                f"{prose.strip()}\n"
                f"{objective.OBJECTIVE_RECONCILABLE_MARKER_END}"
            )
            archive_note = objective.render_adopted_overview_note(original_overview)
            composed = f"{reconcilable}\n\n{header_block}\n\n{manifest_block}\n"
            if archive_note:
                # The Immutable archive note lives BELOW the closing Reconcilable marker.
                composed = f"{composed}\n{archive_note}\n"
            overview = to_linear_markdown(composed)
            # Adopt in place: PATCH the existing project's overview (NOT create_project).
            overview = plan.prepend_callout(
                overview,
                objective.objective_callout(source_id),
                command=f"perk objective plan {source_id}",
            )
            self._projects.update_project_content(source_id, overview)

            # --- one milestone per phase, de-duped against the project's EXISTING milestones ---
            known_milestones: dict[str, str] = {
                _require_str(m["name"], "milestone name"): _require_str(m["id"], "milestone id")
                for m in self._projects.project_milestones(source_id)
            }
            phase_milestone: dict[tuple[int, str], str] = {}
            for key, _phase_nodes in grouped:
                phase_milestone[key] = self._projects.ensure_phase_milestone(
                    project_id=source_id, name=names[key], known=known_milestones
                )

            node_label_id, _ = self._issue_ops._ensure_label_id(
                objective.OBJECTIVE_NODE_LABEL,
                color=objective.OBJECTIVE_NODE_LABEL_COLOR,
                description=objective.OBJECTIVE_NODE_LABEL_DESCRIPTION,
            )
            node_uuid: dict[str, str] = {}
            for node in sorted(nodes, key=lambda n: objective.node_sort_key(n.id)):
                node_block = plan.render_metadata_block(
                    objective.OBJECTIVE_NODE_KEY,
                    objective.render_node_block(node),
                    style="inline-code",
                )
                milestone_id = phase_milestone[objective.derive_phase(node.id)]
                if node.id in resolved_adopt:
                    # Mapped: stamp the node block ADDITIVELY into the existing issue (title + human
                    # body verbatim), attach to the phase milestone, add the node label additively.
                    target = resolved_adopt[node.id]
                    uuid = _require_str(target.get("id"), "issue id")
                    existing_body = _require_str(target.get("description"), "issue description")
                    new_desc = to_linear_markdown(f"{existing_body.rstrip()}\n\n{node_block}\n")
                    full = self._issue_ops._get_issue(
                        uuid, "id description labels { nodes { id } }"
                    )
                    labels = _require_dict(full.get("labels"), "issue.labels")
                    label_ids = [
                        _require_str(_require_dict(raw, "label").get("id"), "label id")
                        for raw in _require_list(labels.get("nodes"), "issue.labels.nodes")
                    ]
                    if node_label_id not in label_ids:
                        label_ids = [*label_ids, node_label_id]
                    self._issue_ops._update_issue(
                        uuid,
                        {"description": new_desc, "labelIds": label_ids},
                        what="stamp objective-node block",
                    )
                    self._projects.attach_issue_to_milestone(
                        issue_id=uuid, milestone_id=milestone_id
                    )
                    node_uuid[node.id] = uuid
                else:
                    # Unmapped: mint a fresh node-issue (the create_objective path).
                    description = to_linear_markdown(node.description + "\n\n" + node_block)
                    _ref, uuid = self._issue_ops._create_issue_raw(
                        title=objective.node_issue_title(node),
                        description=description,
                        label_id=node_label_id,
                        project_id=source_id,
                        milestone_id=milestone_id,
                    )
                    node_uuid[node.id] = uuid

            # --- blocking relations for EXPLICIT depends_on only (dep BLOCKS node) ---
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

            return objective_store.ObjectiveRef(id=source_id, url=project_url, existed=False)

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
        """Create the project-backed objective: a project (overview = header + Reconcilable prose),
        one milestone per phase, one node-issue per roadmap node (in ``node_sort_key`` order),
        and a blocking relation per EXPLICIT ``depends_on`` edge. Idempotent on ``run_id``."""
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

            # --- compose the overview: header block + Reconcilable(prose); NO roadmap table ---
            header = objective.ObjectiveHeader(
                run_id=run_id,
                created=plan.now_iso(),
                objective_comment_id=None,
                status=status,
                base=base,
            )
            header_block = plan.render_metadata_block(
                objective.OBJECTIVE_HEADER_KEY, header.to_data(), style="inline-code"
            )
            # The phase names (enriched from the prose `### Phase N:` headers) seed BOTH the
            # milestone loop below and the persisted manifest's pinned `phases` map.
            grouped = objective.group_nodes_by_phase(nodes)
            names = objective.enrich_phase_names(body, [key for key, _ in grouped])
            manifest_names = {f"{key[0]}{key[1]}": value for key, value in names.items()}
            # The drift baseline (#612): the `objective-manifest` block pins the intended roadmap's
            # structural identity + the canonical phase names, between the header block and the
            # Reconcilable region. Status/pr are excluded (live/observed state).
            manifest_block = plan.render_metadata_block(
                objective.OBJECTIVE_MANIFEST_KEY,
                objective.render_manifest_block(nodes, manifest_names),
                style="inline-code",
            )
            reconcilable = (
                f"{objective.OBJECTIVE_RECONCILABLE_MARKER_START}\n"
                f"{body.strip()}\n"
                f"{objective.OBJECTIVE_RECONCILABLE_MARKER_END}"
            )
            # Prose-first composition (Pillar 2): the human Reconcilable prose renders FIRST, the
            # machine blocks (header + manifest) follow. Reads are position-independent
            # (find_metadata_block / replace_reconcilable_section scan by marker), so only the
            # render order changes. Transcode the whole overview so the HTML Reconcilable markers
            # become inline-code sentinels (the reconcile splice is dual-encoding either way).
            overview = to_linear_markdown(f"{reconcilable}\n\n{header_block}\n\n{manifest_block}\n")
            created = self._projects.create_project(name=title, content=overview)
            project_id = created["id"]
            assert isinstance(project_id, str)
            url = created["url"]
            assert isinstance(url, str)

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
            # Routed through the name-keyed `ensure_phase_milestone` seam (Node 4.3). The project
            # is brand-new, so `known` is seeded EMPTY: every phase name is a guaranteed miss and
            # creates a milestone, keeping this path's network calls byte-identical to the prior
            # blind-create loop (no extra `project_milestones` read; same `create_project_milestone`
            # sequence). The seam's reusable value is its `known is None` branch for a future
            # `add_node`-to-an-existing-objective path.
            known_milestones: dict[str, str] = {}
            phase_milestone: dict[tuple[int, str], str] = {}
            for key, _phase_nodes in grouped:
                phase_milestone[key] = self._projects.ensure_phase_milestone(
                    project_id=project_id, name=names[key], known=known_milestones
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
                # Prose-first (Pillar 2): the node's prose description renders FIRST, the
                # `objective-node` block follows (reads scan by marker, position-independent).
                description = to_linear_markdown(
                    node.description
                    + "\n\n"
                    + plan.render_metadata_block(
                        objective.OBJECTIVE_NODE_KEY,
                        objective.render_node_block(node),
                        style="inline-code",
                    )
                )
                _ref, uuid = self._issue_ops._create_issue_raw(
                    title=objective.node_issue_title(node),
                    description=description,
                    label_id=node_label_id,
                    project_id=project_id,
                    milestone_id=phase_milestone[objective.derive_phase(node.id)],
                )
                # The issue UUID comes straight from the `issueCreate` response — no extra query.
                # `issueRelationCreate` is only verified for UUIDs, so relations keep them.
                node_uuid[node.id] = uuid

            # --- blocking relations for EXPLICIT depends_on only (dep BLOCKS node) ---
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

            return objective_store.ObjectiveRef(id=project_id, url=url, existed=False)

    def get_objective(self, *, objective_id: str) -> objective_store.ObjectiveState | None:
        """Reconstruct the objective state from the project + its node-issues. ``None`` when the
        project is absent. The roadmap is derived live from the node-issues (never stored as a
        block): each ``objective-node`` block gives id/status/description/slug/comment; ``pr`` is
        read from the same node-issue's ``plan-header`` block (``None`` until Node 3.4 writes it);
        ``depends_on`` is reconstructed from blocking relations. Nodes are returned sorted by
        :func:`objective.node_sort_key` — never Linear's connection order.

        Lossy round-trip (documented): an explicit ``depends_on=()`` is indistinguishable from
        "no relation" and reads back as ``None`` (sequential inference then applies downstream).
        """
        with _translate_objective():
            project = self._projects.project_or_none(objective_id, "id url name content")
            if project is None:
                return None
            overview = project.get("content")
            overview = _opt_str(overview) or ""
            header = plan.find_metadata_block(overview, objective.OBJECTIVE_HEADER_KEY) or {}
            issues = self._projects.project_issues(objective_id)

            # First pass: build the (identifier, uuid, node) triples + the identifier->node-id map.
            # Issues with no `objective-node` block are foreign (human/cross-project) and are never
            # reinterpreted as roadmap nodes.
            parsed: list[tuple[str, objective.ObjectiveNode]] = []
            uuid_by_identifier: dict[str, str] = {}
            identifier_to_node: dict[str, str] = {}
            for issue in issues:
                identifier = _require_str(issue.get("identifier"), "issue identifier")
                description = issue.get("description")
                body = _opt_str(description) or ""
                block = plan.find_metadata_block(body, objective.OBJECTIVE_NODE_KEY)
                if block is None:
                    continue
                node = self._node_from_block(block, identifier, body)
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
            return objective_store.ObjectiveState(
                id=objective_id,
                url=_require_str(project.get("url"), "project url"),
                title=_require_str(project.get("name"), "project name"),
                header=header,
                nodes=tuple(sorted_nodes),
            )

    def _find_node_issue(
        self, objective_id: str, node_id: str
    ) -> tuple[str, str, str, str, dict[str, object]] | None:
        """Locate the project's node-issue carrying the ``objective-node`` block for ``node_id``.

        Returns ``(uuid, identifier, url, body, block)`` — the node-issue's UUID, its human
        identifier, its url, its description body, and the parsed ``objective-node`` block — or
        ``None`` when no node-issue matches. Shared by :meth:`update_objective_node` and
        :meth:`save_node_plan`.
        """
        for issue in self._projects.project_issues(objective_id):
            description_raw = issue.get("description")
            body = _opt_str(description_raw) or ""
            candidate = plan.find_metadata_block(body, objective.OBJECTIVE_NODE_KEY)
            if candidate is not None and candidate.get("id") == node_id:
                return (
                    _require_str(issue.get("id"), "issue id"),
                    _require_str(issue.get("identifier"), "issue identifier"),
                    _require_str(issue.get("url"), "issue url"),
                    body,
                    candidate,
                )
        return None

    @staticmethod
    def _node_from_block(
        block: dict[str, object], identifier: str, body: str
    ) -> objective.ObjectiveNode:
        """Reconstruct an ``ObjectiveNode`` from its ``objective-node`` block. A malformed block
        (missing/invalid ``id``/``status``) raises ``IssueBackendError``.

        **The plan backlink is the node-issue's own identifier** (Node 3.4 unification, refining
        Node 3.3): in the project model the plan *is* the node-issue, so the backlink is
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
        # The plan backlink: the node-issue's own identifier whenever a plan has been saved into it
        # (a `plan-header` block is present), else None. Self-referential by the unification model;
        # stable across submit clobbering `plan-header.pr` with the GitHub PR number.
        pr = (
            objective.canonical_pr(identifier)
            if plan.has_metadata_block(body, plan.PLAN_HEADER_KEY)
            else None
        )
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
        ``pr``, and the backlink's single home is the node-issue's own ``plan-header`` (Node 3.4),
        read back by :meth:`get_objective`. Passing ``pr`` here is a no-op on the stored block.

        ``comment_updated`` is always ``False`` — the project model has no objective-body comment
        table (the roadmap is derived from node-issues, not a rendered comment).
        """
        with _translate_objective():
            found = self._find_node_issue(objective_id, node_id)
            if found is None:
                raise IssueBackendError(f"objective node {node_id!r} not found on {objective_id!r}")
            issue_uuid, identifier, _url, node_body, block = found

            node = self._node_from_block(block, identifier, node_body)
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

            # Authoritative write: re-render the `objective-node` block (form-preserving
            # inline-code; `render_node_block` excludes `pr`, so a passed `pr` never lands).
            new_body = plan.replace_metadata_block(
                node_body, objective.OBJECTIVE_NODE_KEY, objective.render_node_block(new_node)
            )
            self._issue_ops._update_issue(
                issue_uuid, {"description": new_body}, what="update objective node"
            )

            # Manifest-sync (#612): a `description` change updates the matching manifest entry
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
                except IssueBackendError:
                    pass

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
            # Manifest phase-pin refresh (#612): in the SAME write, re-derive the phase names from
            # the spliced overview (a reconcile may have rewritten a `### Phase N:` header) and
            # refresh the manifest `phases` pins so the pin stays authoritative. Node descriptions
            # are synced via `update_objective_node`, not here. No-op when no manifest block exists.
            spliced = self._refresh_manifest_phase_pins(spliced)
            self._projects.update_project_content(objective_id, spliced)
            return objective_store.ObjectiveBodyUpdate(
                objective_id=objective_id, comment_id=None, updated=True, dry_run=False
            )

    def update_objective_header(
        self, *, objective_id: str, fields: dict[str, object], dry_run: bool = False
    ) -> objective_store.ObjectiveHeaderUpdate:
        """Merge ``fields`` into the overview's ``objective-header`` block (form-preserving).
        Rejects keys outside ``objective.OBJECTIVE_HEADER_FIELDS`` (LBYL)."""
        with _translate_objective():
            unknown = set(fields) - objective.OBJECTIVE_HEADER_FIELDS
            if unknown:
                raise IssueBackendError(f"unknown objective-header field(s): {sorted(unknown)}")
            project = self._projects.project_or_none(objective_id, "content")
            if project is None:
                raise IssueBackendError(f"objective {objective_id!r} not found")
            overview = project.get("content")
            overview = _opt_str(overview) or ""
            header = plan.find_metadata_block(overview, objective.OBJECTIVE_HEADER_KEY) or {}
            new_overview = plan.replace_metadata_block(
                overview, objective.OBJECTIVE_HEADER_KEY, {**header, **fields}
            )
            if dry_run:
                return objective_store.ObjectiveHeaderUpdate(
                    fields_updated=tuple(fields), dry_run=True
                )
            self._projects.update_project_content(objective_id, new_overview)
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
            manifest, _manifest_errors = objective.parse_manifest(overview)
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
            # Prose-first (Pillar 2): prose description first, then the `objective-node` block.
            node_description = to_linear_markdown(
                new_node.description
                + "\n\n"
                + plan.render_metadata_block(
                    objective.OBJECTIVE_NODE_KEY,
                    objective.render_node_block(new_node),
                    style="inline-code",
                )
            )
            _ref, new_uuid = self._issue_ops._create_issue_raw(
                title=objective.node_issue_title(new_node),
                description=node_description,
                label_id=node_label_id,
                project_id=objective_id,
                milestone_id=milestone_id,
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
                        issue_id=found[0], related_issue_id=new_uuid
                    )

            # Manifest-sync (#612): on a manifest-bearing objective, append the new node's entry
            # (id/slug/description; explicit `depends_on`) and pin a new phase name when the node
            # opens a phase not already in the manifest. Skips entirely on a pre-manifest objective
            # (no manifest to maintain; `doctor --fix` backfill remains the path).
            self._sync_manifest_add_node(objective_id, new_node)

            return objective_store.ObjectiveNodeAdd(
                objective_id=objective_id, node_id=new_id, comment_updated=False, dry_run=False
            )

    # ================================================================== manifest sync (#612)
    # The persisted `objective-manifest` block is the drift baseline; these keep it current on the
    # live write paths. Every one is a clean no-op on a pre-manifest objective (no manifest block).

    def _insert_or_replace_manifest(self, overview: str, data: dict[str, object]) -> str:
        """Upsert the manifest block into an overview: replace in place when present (form-
        preserving), else insert (inline-code) just AFTER the Reconcilable region (prose-first:
        machine blocks follow the human prose; Pillar 2). Falls back to an append when no
        Reconcilable region is present."""
        if plan.has_metadata_block(overview, objective.OBJECTIVE_MANIFEST_KEY):
            return plan.replace_metadata_block(overview, objective.OBJECTIVE_MANIFEST_KEY, data)
        block = to_linear_markdown(
            plan.render_metadata_block(objective.OBJECTIVE_MANIFEST_KEY, data, style="inline-code")
        )
        for marker in (
            to_linear_markdown(objective.OBJECTIVE_RECONCILABLE_MARKER_END),
            objective.OBJECTIVE_RECONCILABLE_MARKER_END,
        ):
            idx = overview.find(marker)
            if idx != -1:
                after = idx + len(marker)
                return f"{overview[:after]}\n\n{block}{overview[after:]}"
        return f"{overview.rstrip()}\n\n{block}\n"

    def _sync_manifest_node_description(
        self, objective_id: str, node_id: str, description: str
    ) -> None:
        """Update the matching manifest entry's description (structural identity sync)."""
        project = self._projects.project_or_none(objective_id, "content")
        overview = project.get("content") if project is not None else ""
        overview = _opt_str(overview) or ""
        manifest, _errors = objective.parse_manifest(overview)
        if manifest is None or all(n.id != node_id for n in manifest.nodes):
            return
        new_nodes = [
            replace(n, description=description) if n.id == node_id else n for n in manifest.nodes
        ]
        data = objective.render_manifest_block(new_nodes, manifest.phase_names)
        new_overview = plan.replace_metadata_block(overview, objective.OBJECTIVE_MANIFEST_KEY, data)
        self._projects.update_project_content(objective_id, new_overview)

    def _sync_manifest_add_node(self, objective_id: str, new_node: objective.ObjectiveNode) -> None:
        """Append the new node's entry to the manifest, pinning a brand-new phase's name."""
        project = self._projects.project_or_none(objective_id, "content")
        overview = project.get("content") if project is not None else ""
        overview = _opt_str(overview) or ""
        manifest, _errors = objective.parse_manifest(overview)
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
            phase = objective.derive_phase(new_node.id)
            phase_names[phase_key] = objective.enrich_phase_names(overview, [phase])[phase]
        data = objective.render_manifest_block([*manifest.nodes, entry], phase_names)
        new_overview = plan.replace_metadata_block(overview, objective.OBJECTIVE_MANIFEST_KEY, data)
        self._projects.update_project_content(objective_id, new_overview)

    def _refresh_manifest_phase_pins(self, overview: str) -> str:
        """Refresh the manifest's `phases` pins to MATCH the spliced overview's `### Phase N:`
        headers — the overview is the authority on a reconcile, so a pin tracks exactly what
        `enrich_phase_names` derives, including **reverting to the `Phase N` default** when a
        reconcile removed (or defaulted) a phase header (never preserving a now-stale custom name).
        Returns the (possibly-rewritten) overview; a no-op when no manifest block exists or nothing
        changed."""
        manifest, _errors = objective.parse_manifest(overview)
        if manifest is None:
            return overview
        keys = sorted({objective.derive_phase(n.id) for n in manifest.nodes})
        found = objective.enrich_phase_names(overview, keys)
        new_phase_names = dict(manifest.phase_names)
        for key in keys:
            new_phase_names[f"{key[0]}{key[1]}"] = found[key]
        if new_phase_names == manifest.phase_names:
            return overview
        data = objective.render_manifest_block(list(manifest.nodes), new_phase_names)
        return plan.replace_metadata_block(overview, objective.OBJECTIVE_MANIFEST_KEY, data)

    # ============================================================ drift detect / repair (#612)

    def _build_observed_snapshot(self, objective_id: str) -> objective_drift.ObservedSnapshot:
        """Build the offline-diffable :class:`ObservedSnapshot` from the live project state (the
        ONLY network step of the drift pass). Raises ``IssueBackendError`` when the project is
        absent. Foreign issues (no ``objective-node`` block) are excluded; a node-issue with a
        present-but-unparseable block is retained with ``block_valid=False``."""
        project = self._projects.project_or_none(objective_id, "id url name content")
        if project is None:
            raise IssueBackendError(f"objective {objective_id!r} not found")
        overview = project.get("content")
        overview = _opt_str(overview) or ""
        manifest, manifest_errors = objective.parse_manifest(overview)
        header_ok = plan.find_metadata_block(overview, objective.OBJECTIVE_HEADER_KEY) is not None
        reconcilable_ok = objective.replace_reconcilable_section(overview, "") is not None

        milestone_names = tuple(
            _require_str(m["name"], "milestone name")
            for m in self._projects.project_milestones(objective_id)
        )
        issues = self._projects.project_issues_with_milestones(objective_id)

        identifier_to_node: dict[str, str] = {}
        parsed: list[
            tuple[str, str, str | None, objective.NodeStatus | None, str | None, bool, bool]
        ] = []
        for issue in issues:
            identifier = _require_str(issue.get("identifier"), "issue identifier")
            uuid = _require_str(issue.get("id"), "issue id")
            body_raw = issue.get("description")
            body = _opt_str(body_raw) or ""
            milestone_raw = issue.get("milestone_name")
            milestone_name = _opt_str(milestone_raw)
            if not plan.has_metadata_block(body, objective.OBJECTIVE_NODE_KEY):
                continue  # foreign issue — not a roadmap node
            block = plan.find_metadata_block(body, objective.OBJECTIVE_NODE_KEY)
            node_id: str | None = None
            status: objective.NodeStatus | None = None
            block_valid = True
            if block is None:
                block_valid = False  # block present but unparseable
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
            has_plan_header = plan.has_metadata_block(body, plan.PLAN_HEADER_KEY)
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
        """Build the observed snapshot and diff it against the manifest baseline (#612)."""
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
        """Apply the safe/unambiguous repairs in order, stop at the first failed write (#612)."""
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

    # --- human-engagement reads (Objective #682, Node 2.3) ---
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
        # preview-grade deferral, not overpromised (Node 4.3 live gate).
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
            uuid = found[0]
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
            created_uuid[node_id] = found[0]
            return found[0]
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
        """Recreate a missing node-issue from its manifest entry (block + prose, under its phase
        milestone); record it in ``recreated_ids`` and DEFER **all** its blocking relations to the
        post-loop edge sweep (so every endpoint — in either direction — exists before any edge)."""
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
        # Prose-first (Pillar 2): prose description first, then the `objective-node` block.
        node_description = to_linear_markdown(
            entry.description
            + "\n\n"
            + plan.render_metadata_block(
                objective.OBJECTIVE_NODE_KEY,
                objective.render_node_block(entry),
                style="inline-code",
            )
        )
        _ref, uuid = self._issue_ops._create_issue_raw(
            title=objective.node_issue_title(entry),
            description=node_description,
            label_id=node_label_id,
            project_id=objective_id,
            milestone_id=milestone_id,
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
        project = self._projects.project_or_none(objective_id, "content")
        overview = project.get("content") if project is not None else ""
        overview = _opt_str(overview) or ""
        data = objective.render_manifest_block(nodes, phase_names)
        self._projects.update_project_content(
            objective_id, self._insert_or_replace_manifest(overview, data)
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
        """Write the plan **into** the objective's node-issue (the node↔plan unification).

        Merges the ``plan-header`` block into the node-issue description (Linear-safe inline-code)
        and upserts the plan body as a single node-issue comment; the title, the ``objective-node``
        block, and the node prose are untouched. Returns the **node-issue** ref
        (``existed=True``). Raises ``ObjectiveStoreError`` when the node is not found.

        ``dry_run`` returns ``None`` (resolving the node-issue requires a network read; the caller
        falls back to the offline compose-preview).
        """
        if dry_run:
            return None
        with _translate_objective():
            found = self._find_node_issue(objective_id, node_id)
            if found is None:
                raise IssueBackendError(f"objective node {node_id!r} not found on {objective_id!r}")
            uuid, identifier, url, body, _block = found

            # Merge the plan-header block into the node-issue description, Linear-safe
            # (inline-code). Form-preserving replace when present; else compose+append inline-code
            # (NEVER the bare replace_metadata_block append path — it appends in lossy HTML form).
            if plan.has_metadata_block(body, plan.PLAN_HEADER_KEY):
                new_desc = plan.replace_metadata_block(body, plan.PLAN_HEADER_KEY, header_fields)
            else:
                header_block = plan.render_metadata_block(
                    plan.PLAN_HEADER_KEY, header_fields, style="inline-code"
                )
                new_desc = f"{body.rstrip()}\n\n{header_block}\n"
            # The node-issue IS the plan issue here, so lead its description with the copyable
            # `perk impl <ENG-N>` callout. Keyed on the command string, so a re-save (this method
            # re-runs on every objective-linked save) never duplicates it.
            new_desc = plan.prepend_callout(
                new_desc,
                plan.plan_callout(identifier),
                command=f"perk impl {identifier}",
            )
            self._issue_ops._update_issue(
                uuid, {"description": new_desc}, what="write node plan-header"
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

        **Flagged not-live-proven** (the 1.4 spike did not cover project state) — verify at the
        Node 5.1 smoke gate alongside ``list_projects`` / ``_workflow_state_id``.
        """
        if dry_run:
            return False
        with _translate_objective():
            self._projects.set_project_state(objective_id, "completed")
        return True

    def post_status_update(self, *, objective_id: str, body: str, dry_run: bool = False) -> bool:
        """Post a Project **Update** to the Linear Project (the status-report feed; Node 4.3).

        ``dry_run`` returns ``False`` without a write; else posts ``projectUpdateCreate`` and
        returns ``True``. Call sites wrap this fail-open (the update is bookkeeping, never
        load-bearing). Flagged not-live-proven \u2014 verify at the Node 5.1 smoke gate.
        """
        if dry_run:
            return False
        with _translate_objective():
            self._projects.create_project_update(project_id=objective_id, body=body)
        return True
