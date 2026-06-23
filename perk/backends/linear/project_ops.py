from datetime import UTC, datetime
from pathlib import Path

from perk.backends.issue_backend import IssueBackendError
from perk.backends.linear._helpers import (
    _PAGE_SIZE,
    _request_issue_mutation,
)
from perk.backends.linear.client import (
    LinearClient,
    LinearGraphQLError,
    _is_entity_not_found,
    _opt_dict,
    _opt_str,
    _require_dict,
    _require_str,
)


class _LinearProjectOps:
    """The dormant Linear *Projects* substrate (Objective #548, Node 3.1) — the GraphQL ops the
    not-yet-built ``LinearProjectObjectiveStore`` (Nodes 3.2-3.4) will consume, exactly the shapes
    proven live at the Node 1.4 spike (``docs/planning/linear-smoke-gate.md``, "Mode 3").

    **Client-only** (correction §3b): it registers the :class:`LinearClient` and reaches all
    GraphQL machinery (``team_id``/``paginate``) through ``self._client`` — it does
    NOT compose an ``_LinearIssueOps``. The single shared ``_team_id_cache`` is the client's: a
    consuming store owns one client and constructs both op
    classes over it, so the cache is shared automatically.

    Methods return parsed primitives/dicts — the ``ObjectiveRef``/``ObjectiveState`` mapping lives
    in the consuming store (Node 3.2), not here. **Dormant**: no production caller constructs this
    yet (only the offline tests do), so there is no cross-plane behavior change in this node.
    """

    def __init__(self, client: LinearClient, *, team_key: str, repo_root: Path) -> None:
        self._client = client
        self._team_key = team_key
        # Stored for the mandated symmetric signature with `_LinearIssueOps` (unused here today).
        self._repo_root = repo_root

    # ------------------------------------------------------------------ projects

    def create_project(self, *, name: str, content: str) -> dict[str, object]:
        """Create a project with overview ``content`` at create (the 2024 create-then-update
        wrinkle does NOT apply — proven at the spike). ``teamIds`` is a **list**. Returns the
        parsed ``{id, url}`` project dict; ``id`` is the opaque project UUID."""
        mutation = (
            "mutation($input: ProjectCreateInput!) { projectCreate(input: $input) "
            "{ success project { id url } } }"
        )
        variables: dict[str, object] = {
            "input": {
                "teamIds": [self._client.team_id(self._team_key)],
                "name": name,
                "content": content,
                # The API-key user owns the objective: project lead. A `startDate` of today
                # (ISO `YYYY-MM-DD`) is REQUIRED for Linear's project graphs (target date stays
                # unset — perk has no deadline signal).
                "leadId": self._client.viewer_id(),
                "startDate": datetime.now(UTC).date().isoformat(),
            }
        }
        data = self._client.request(mutation, variables)
        payload = _require_dict(data.get("projectCreate"), "projectCreate")
        if payload.get("success") is not True:
            raise IssueBackendError(f"failed to create Linear project {name!r}")
        project = _require_dict(payload.get("project"), "projectCreate.project")
        return {
            "id": _require_str(project.get("id"), "project id"),
            "url": _require_str(project.get("url"), "project url"),
        }

    def update_project_content(self, project_id: str, content: str) -> None:
        """Patch a project's overview ``content``. Project ids are opaque UUIDs — there is no
        human identifier for a project."""
        mutation = (
            "mutation($id: String!, $input: ProjectUpdateInput!) "
            "{ projectUpdate(id: $id, input: $input) { success project { id content } } }"
        )
        data = self._client.request(mutation, {"id": project_id, "input": {"content": content}})
        payload = _require_dict(data.get("projectUpdate"), "projectUpdate")
        if payload.get("success") is not True:
            raise IssueBackendError(f"failed to update Linear project {project_id!r}")

    def set_project_state(self, project_id: str, state: str) -> None:
        """Set a project's ``state`` (e.g. ``"completed"`` to mark the objective complete on land).
        Project ids are opaque UUIDs (no human identifier).

        **Flagged (Phase-5 / Node 5.1 live gate):** ``projectUpdate(input:{state})`` is NOT yet
        live-proven — the 1.4 spike covered create/overview/milestone/attach/relation, not project
        state. Covered offline here; verify live before relying on it.
        """
        mutation = (
            "mutation($id: String!, $input: ProjectUpdateInput!) "
            "{ projectUpdate(id: $id, input: $input) { success } }"
        )
        data = self._client.request(mutation, {"id": project_id, "input": {"state": state}})
        payload = _require_dict(data.get("projectUpdate"), "projectUpdate")
        if payload.get("success") is not True:
            raise IssueBackendError(f"failed to set state on Linear project {project_id!r}")

    def project_or_none(self, project_id: str, selection: str) -> dict[str, object] | None:
        """Fetch one project by id; ``None`` when Linear reports the entity missing (a bogus
        ``project(id)`` matches the issue not-found shape — ``INPUT_ERROR`` + "Entity not found:
        Project" — so ``_is_entity_not_found`` keys on it). Every other error re-raises."""
        query = f"query($id: String!) {{ project(id: $id) {{ {selection} }} }}"
        try:
            data = self._client.request(query, {"id": project_id})
        except LinearGraphQLError as exc:
            if _is_entity_not_found(exc):
                return None
            raise
        project = data.get("project")
        if project is None:
            return None
        return _require_dict(project, "project")

    def project_milestones(self, project_id: str) -> list[dict[str, object]]:
        """All milestones (phases) of a project, as ``[{id, name}, …]``. **Milestone order is NOT
        insertion order** — callers key phases by *name*, never list position."""
        query = (
            "query($id: String!, $cursor: String) { project(id: $id) "
            f"{{ projectMilestones(first: {_PAGE_SIZE}, after: $cursor) "
            "{ nodes { id name } pageInfo { hasNextPage endCursor } } } }"
        )
        nodes = self._client.paginate(query, {"id": project_id}, "project", "projectMilestones")
        return [
            {
                "id": _require_str(node.get("id"), "milestone id"),
                "name": _require_str(node.get("name"), "milestone name"),
            }
            for node in nodes
        ]

    def _project_comments(self, project_id: str) -> list[dict[str, object]]:
        """All comments on a project (the project-level discussion threads) with author identity +
        ``editedAt``, sorted ascending by ``createdAt`` (oldest-first, mirroring the issue reads).
        Author-aware selection mirroring ``_LinearIssueOps._comments_with_authors`` — feeds the
        objective-level engagement read (Node 2.3).

        (Implementer note: if ``Project.comments`` proves unavailable live in Node 4.3, fall back to
        the top-level ``comments(filter: { project: { id: { eq: $id } } })`` form — the
        SDK-confirmed alternative; the neutral mapping is unchanged.)
        """
        query = (
            "query($id: String!, $cursor: String) { project(id: $id) "
            f"{{ comments(first: {_PAGE_SIZE}, after: $cursor) "
            "{ nodes { id body createdAt editedAt user { id name displayName } "
            "botActor { id name type } } pageInfo { hasNextPage endCursor } } } }"
        )
        nodes = self._client.paginate(query, {"id": project_id}, "project", "comments")
        return sorted(nodes, key=lambda c: _require_str(c.get("createdAt"), "comment createdAt"))

    def project_issues(self, project_id: str) -> list[dict[str, object]]:
        """All issues attached to a project, as ``[{id, identifier, url, description}, …]``
        (paginated). ``description`` may be ``""`` — one query then yields every node-issue body for
        the read path (``get_objective``) and the node-issue ``url`` for the unification write
        (``save_node_plan`` returns the node-issue ref)."""
        query = (
            "query($id: String!, $cursor: String) { project(id: $id) "
            f"{{ issues(first: {_PAGE_SIZE}, after: $cursor) "
            "{ nodes { id identifier url description } pageInfo { hasNextPage endCursor } } } }"
        )
        nodes = self._client.paginate(query, {"id": project_id}, "project", "issues")
        result: list[dict[str, object]] = []
        for node in nodes:
            description = node.get("description")
            result.append(
                {
                    "id": _require_str(node.get("id"), "issue id"),
                    "identifier": _require_str(node.get("identifier"), "issue identifier"),
                    "url": _require_str(node.get("url"), "issue url"),
                    "description": _opt_str(description) or "",
                }
            )
        return result

    def project_issues_for_adoption(self, project_id: str) -> list[dict[str, object]]:
        """All issues attached to a project **with titles**, as
        ``[{id, identifier, url, title, description}, …]`` (paginated). A **sibling** of
        :meth:`project_issues` (in-place objective adoption needs each existing issue's title to
        seed the authoring DATA and to preserve it verbatim on the mapped-issue stamp; #709,
        §8.30); the byte-stable ``project_issues`` query is deliberately left untouched (mirrors
        the ``project_issues_with_milestones`` sibling precedent). ``description``/``title`` may be
        ``""``.

        **Flagged (Phase-5 / Node 5.1 live gate):** this title-bearing selection is NOT yet
        live-proven for adoption — covered offline here; verify live at Node 4.3.
        """
        query = (
            "query($id: String!, $cursor: String) { project(id: $id) "
            f"{{ issues(first: {_PAGE_SIZE}, after: $cursor) "
            "{ nodes { id identifier url title description } "
            "pageInfo { hasNextPage endCursor } } } }"
        )
        nodes = self._client.paginate(query, {"id": project_id}, "project", "issues")
        result: list[dict[str, object]] = []
        for node in nodes:
            description = node.get("description")
            title = node.get("title")
            result.append(
                {
                    "id": _require_str(node.get("id"), "issue id"),
                    "identifier": _require_str(node.get("identifier"), "issue identifier"),
                    "url": _require_str(node.get("url"), "issue url"),
                    "title": _opt_str(title) or "",
                    "description": _opt_str(description) or "",
                }
            )
        return result

    def project_issues_with_milestones(self, project_id: str) -> list[dict[str, object]]:
        """All issues attached to a project **with milestone membership**, as
        ``[{id, identifier, url, description, milestone_name}, …]`` (paginated). A **sibling** of
        :meth:`project_issues` (the drift snapshot needs each node-issue's phase milestone); the
        byte-stable ``project_issues`` query is deliberately left untouched. ``milestone_name`` is
        ``None`` when the issue is attached to no milestone.

        **Flagged (Phase-5 / Node 5.1 live gate):** this milestone-join selection is NOT yet
        live-proven — #619's Mode 4 gate proved create/milestone/attach/relation, not this query.
        Covered offline here; verify live before relying on it.
        """
        query = (
            "query($id: String!, $cursor: String) { project(id: $id) "
            f"{{ issues(first: {_PAGE_SIZE}, after: $cursor) "
            "{ nodes { id identifier url description projectMilestone { id name } } "
            "pageInfo { hasNextPage endCursor } } } }"
        )
        nodes = self._client.paginate(query, {"id": project_id}, "project", "issues")
        result: list[dict[str, object]] = []
        for node in nodes:
            description = node.get("description")
            milestone = _opt_dict(node.get("projectMilestone"))
            milestone_name: str | None = None
            if milestone is not None:
                milestone_name = _opt_str(milestone.get("name"))
            result.append(
                {
                    "id": _require_str(node.get("id"), "issue id"),
                    "identifier": _require_str(node.get("identifier"), "issue identifier"),
                    "url": _require_str(node.get("url"), "issue url"),
                    "description": _opt_str(description) or "",
                    "milestone_name": milestone_name,
                }
            )
        return result

    def list_projects(self) -> list[dict[str, object]]:
        """All of the team's projects, as ``[{id, url, content}, …]`` (``content`` may be
        ``None``) — the find-by-run-id scan source for the project-backed objective store. Team-
        scoped + paginated over ``("team", "projects")``.

        **Flagged (Phase-5 / Node 5.1 live gate):** this projects-list query shape is NOT yet
        live-proven — the 1.4 spike covered create/overview/milestone/attach/relation, not
        list-projects. Covered offline here; verify live before relying on it.
        """
        query = (
            "query($teamId: String!, $cursor: String) { team(id: $teamId) "
            f"{{ projects(first: {_PAGE_SIZE}, after: $cursor) "
            "{ nodes { id url content } pageInfo { hasNextPage endCursor } } } }"
        )
        nodes = self._client.paginate(
            query, {"teamId": self._client.team_id(self._team_key)}, "team", "projects"
        )
        result: list[dict[str, object]] = []
        for node in nodes:
            content = node.get("content")
            result.append(
                {
                    "id": _require_str(node.get("id"), "project id"),
                    "url": _require_str(node.get("url"), "project url"),
                    "content": _opt_str(content),
                }
            )
        return result

    def create_project_milestone(self, *, project_id: str, name: str) -> str:
        """Create a milestone (phase) on a project; returns the milestone id."""
        mutation = (
            "mutation($input: ProjectMilestoneCreateInput!) "
            "{ projectMilestoneCreate(input: $input) { success projectMilestone { id name } } }"
        )
        variables: dict[str, object] = {"input": {"projectId": project_id, "name": name}}
        data = self._client.request(mutation, variables)
        payload = _require_dict(data.get("projectMilestoneCreate"), "projectMilestoneCreate")
        if payload.get("success") is not True:
            raise IssueBackendError(f"failed to create Linear project milestone {name!r}")
        milestone = _require_dict(
            payload.get("projectMilestone"), "projectMilestoneCreate.projectMilestone"
        )
        return _require_str(milestone.get("id"), "milestone id")

    def ensure_phase_milestone(
        self, *, project_id: str, name: str, known: dict[str, str] | None = None
    ) -> str:
        """Name-keyed lookup-or-create for a phase milestone; returns its id (Node 4.3).

        **Name is the deterministic key** — milestone order is NOT insertion order (the 1.4
        smoke-gate finding), so a phase is matched by its enriched ``### Phase N: …`` name, never
        list position. When ``known`` (a prefetched ``{name: id}`` map) is supplied it is used as
        the lookup table (and updated in place with any freshly-created id), amortizing the
        :meth:`project_milestones` read across a batch; when ``known`` is ``None`` the project's
        milestones are listed once to build the table. The existing id for ``name`` is reused; a
        miss creates a new milestone via :meth:`create_project_milestone`.

        This is the **\"kept in sync on node add\"** seam: ``create_objective`` routes its
        create-time milestone loop through it (with a seeded-empty ``known`` so its network calls
        stay byte-identical to the blind-create predecessor), and a future ``add_node``-to-an-
        existing-objective reuses the same primitive with ``known=None`` to reuse a phase's
        milestone or mint one for a brand-new phase. The phase-header-text-drift duplicate-milestone
        edge is Node 4.4's repair concern.
        """
        table: dict[str, str] = (
            {
                _require_str(m["name"], "milestone name"): _require_str(m["id"], "milestone id")
                for m in self.project_milestones(project_id)
            }
            if known is None
            else known
        )
        existing = table.get(name)
        if existing is not None:
            return existing
        created = self.create_project_milestone(project_id=project_id, name=name)
        table[name] = created
        return created

    def create_project_update(self, *, project_id: str, body: str) -> str:
        """Post a Project **Update** (the status-report feed) and return its id (Node 4.3).

        ``input = {projectId, body}`` only — the optional ``health`` field is deliberately omitted
        (D3). Raises ``IssueBackendError`` on ``success != True``.

        **Flagged (Phase-5 / Node 5.1 live gate):** ``projectUpdateCreate`` is NOT yet live-proven
        \u2014 the 1.4 spike covered create/overview/milestone/attach/relation, not project updates.
        Covered offline here; verify live before relying on it (mirrors ``set_project_state`` /
        ``list_projects``).
        """
        mutation = (
            "mutation($input: ProjectUpdateCreateInput!) "
            "{ projectUpdateCreate(input: $input) { success projectUpdate { id } } }"
        )
        variables: dict[str, object] = {"input": {"projectId": project_id, "body": body}}
        data = self._client.request(mutation, variables)
        payload = _require_dict(data.get("projectUpdateCreate"), "projectUpdateCreate")
        if payload.get("success") is not True:
            raise IssueBackendError(f"failed to create Linear project update on {project_id!r}")
        update = _require_dict(payload.get("projectUpdate"), "projectUpdateCreate.projectUpdate")
        return _require_str(update.get("id"), "project update id")

    def attach_issue_to_project(self, *, issue_id: str, project_id: str) -> None:
        """Attach an existing issue to a project. Inlines the ``issueUpdate`` mutation (send
        ``issueUpdate(id:$id, input:{projectId})`` with the boundary identifier directly, check
        ``success``) — decoupling over DRY: a 2-line mutation duplication is the accepted cost of
        not borrowing ``_LinearIssueOps._update_issue``. The GraphQL document stays byte-faithful
        to the issue-tier update, and routes through :func:`_request_issue_mutation` for the same
        not-found mapping."""
        mutation = (
            "mutation($id: String!, $input: IssueUpdateInput!) "
            "{ issueUpdate(id: $id, input: $input) { success } }"
        )
        data = _request_issue_mutation(
            self._client,
            mutation,
            {"id": issue_id, "input": {"projectId": project_id}},
            issue_id=issue_id,
        )
        payload = _require_dict(data.get("issueUpdate"), "issueUpdate")
        if payload.get("success") is not True:
            raise IssueBackendError(f"failed to attach to project on Linear issue {issue_id!r}")

    def attach_issue_to_milestone(self, *, issue_id: str, milestone_id: str) -> None:
        """Reattach an existing issue to a project milestone (the deleted-phase-milestone repair).

        Sends ``issueUpdate(id:$id, input:{projectMilestoneId})`` with the **bare boundary
        identifier** routed through :func:`_request_issue_mutation` (the same not-found mapping the
        post-#622 :meth:`attach_issue_to_project` uses) — decoupling over DRY, exactly mirroring
        that sibling's inline mutation. No identifier→UUID resolution (``uuid_for`` was deleted in
        #622). Checks ``success``.

        **Flagged (Phase-5 / Node 5.1 live gate):** ``issueUpdate(input:{projectMilestoneId})`` is
        NOT yet live-proven — #619's Mode 4 gate proved create/milestone/attach/relation, not this
        mutation. Covered offline here; verify live before relying on it.
        """
        mutation = (
            "mutation($id: String!, $input: IssueUpdateInput!) "
            "{ issueUpdate(id: $id, input: $input) { success } }"
        )
        data = _request_issue_mutation(
            self._client,
            mutation,
            {"id": issue_id, "input": {"projectMilestoneId": milestone_id}},
            issue_id=issue_id,
        )
        payload = _require_dict(data.get("issueUpdate"), "issueUpdate")
        if payload.get("success") is not True:
            raise IssueBackendError(f"failed to attach to milestone on Linear issue {issue_id!r}")

    # ------------------------------------------------------------------ documents (reserved)

    def create_document(self, *, project_id: str, title: str, content: str) -> str:
        """Create a document attached to a project; returns the document id. The **reserved**
        overview fallback — the canonical overview path is the Project ``content`` (per the 1.4
        decision), not a document."""
        mutation = (
            "mutation($input: DocumentCreateInput!) { documentCreate(input: $input) "
            "{ success document { id title content } } }"
        )
        variables: dict[str, object] = {
            "input": {"projectId": project_id, "title": title, "content": content}
        }
        data = self._client.request(mutation, variables)
        payload = _require_dict(data.get("documentCreate"), "documentCreate")
        if payload.get("success") is not True:
            raise IssueBackendError(f"failed to create Linear document {title!r}")
        document = _require_dict(payload.get("document"), "documentCreate.document")
        return _require_str(document.get("id"), "document id")

    def document_content_or_none(self, document_id: str) -> str | None:
        """Fetch one document's ``content`` by id; ``None`` when Linear reports the entity missing
        (a bogus ``document(id)`` matches ``_is_entity_not_found``). Every other error re-raises."""
        query = "query($id: String!) { document(id: $id) { content } }"
        try:
            data = self._client.request(query, {"id": document_id})
        except LinearGraphQLError as exc:
            if _is_entity_not_found(exc):
                return None
            raise
        document = data.get("document")
        if document is None:
            return None
        content = _require_dict(document, "document").get("content")
        return _opt_str(content)

    # ------------------------------------------------------------------ relations (blocks)

    def create_issue_relation(self, *, issue_id: str, related_issue_id: str) -> str:
        """Create a ``blocks`` relation (``issue_id`` blocks ``related_issue_id``); returns the
        relation id. Both args are **resolved UUIDs supplied by the caller** — this does NOT route
        through ``_is_entity_not_found``: a bad id here returns ``INVALID_INPUT`` / "Argument
        Validation Error" (argument validation fires before entity lookup), which fails loud."""
        mutation = (
            "mutation($input: IssueRelationCreateInput!) { issueRelationCreate(input: $input) "
            "{ success issueRelation { id type } } }"
        )
        variables: dict[str, object] = {
            "input": {
                "issueId": issue_id,
                "relatedIssueId": related_issue_id,
                "type": "blocks",
            }
        }
        data = self._client.request(mutation, variables)
        payload = _require_dict(data.get("issueRelationCreate"), "issueRelationCreate")
        if payload.get("success") is not True:
            raise IssueBackendError(
                f"failed to create Linear issue relation {issue_id!r} blocks {related_issue_id!r}"
            )
        relation = _require_dict(payload.get("issueRelation"), "issueRelationCreate.issueRelation")
        return _require_str(relation.get("id"), "relation id")

    def issue_blocks(self, issue_id: str) -> list[str]:
        """The identifiers of issues this one **blocks** — ``relations`` filtered to
        ``type == "blocks"`` (Linear returns all relation types; direction is carried by the
        field, the enum stays ``"blocks"`` on both directions)."""
        query = (
            "query($id: String!, $cursor: String) { issue(id: $id) "
            f"{{ relations(first: {_PAGE_SIZE}, after: $cursor) "
            "{ nodes { type relatedIssue { identifier } } "
            "pageInfo { hasNextPage endCursor } } } }"
        )
        nodes = self._client.paginate(query, {"id": issue_id}, "issue", "relations")
        identifiers: list[str] = []
        for node in nodes:
            if node.get("type") != "blocks":
                continue
            related = _require_dict(node.get("relatedIssue"), "relation.relatedIssue")
            identifiers.append(_require_str(related.get("identifier"), "related issue identifier"))
        return identifiers

    def issue_blocked_by(self, issue_id: str) -> list[str]:
        """The identifiers of issues that **block** this one (the ``depends_on`` sources for Node
        3.3) — ``inverseRelations`` filtered to ``type == "blocks"`` (there is no ``"blockedBy"``
        enum value; the inverse field carries the direction)."""
        query = (
            "query($id: String!, $cursor: String) { issue(id: $id) "
            f"{{ inverseRelations(first: {_PAGE_SIZE}, after: $cursor) "
            "{ nodes { type issue { identifier } } "
            "pageInfo { hasNextPage endCursor } } } }"
        )
        nodes = self._client.paginate(query, {"id": issue_id}, "issue", "inverseRelations")
        identifiers: list[str] = []
        for node in nodes:
            if node.get("type") != "blocks":
                continue
            blocker = _require_dict(node.get("issue"), "inverseRelation.issue")
            identifiers.append(_require_str(blocker.get("identifier"), "blocker issue identifier"))
        return identifiers
