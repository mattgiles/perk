from pathlib import Path

from perk import plan
from perk.backends import issue_backend
from perk.backends.issue_backend import IssueBackendError
from perk.backends.linear import (
    LinearClient,
    LinearGraphQLError,
    _is_entity_not_found,
    _opt_dict,
    _opt_str,
    _require_dict,
    _require_list,
    _require_str,
)
from perk.backends.linear_backend._helpers import (
    _PAGE_SIZE,
    _hex_color,
    _is_present,
    _request_issue_mutation,
)


class _LinearIssueOps:
    """The shared Linear issue substrate (correction §3b): the GraphQL client, the
    constructor-bound team key, the issue-tier caches (done-state + labels), and every private
    issue-op helper. **Client-only** — it registers the :class:`LinearClient` and reaches all
    GraphQL machinery (``team_id``/``paginate``) through ``self._client``; it does
    NOT own that machinery. Both ``LinearIssueBackend`` (the issue tier) and the objective stores
    own one and delegate through it."""

    def __init__(self, client: LinearClient, *, team_key: str, repo_root: Path) -> None:
        self._client = client
        self._team_key = team_key
        # Public: the PR-tier ``github.get_pr`` call in ``LinearIssueBackend.get_plan`` reads it.
        self.repo_root = repo_root
        self._done_state_id_cache: str | None = None
        # type -> lowest-position state id of that type (the Node 3.3 workflow-state mirror).
        self._states_by_type: dict[str, str] | None = None
        self._label_ids: dict[str, str] = {}

    # ------------------------------------------------------------------ internal helpers

    def _done_state_id(self) -> str:
        """The team's first Done-category workflow state (lowest-position ``completed``)."""
        if self._done_state_id_cache is not None:
            return self._done_state_id_cache
        query = (
            "query($teamId: String!) { team(id: $teamId) "
            "{ states { nodes { id name type position } } } }"
        )
        data = self._client.request(query, {"teamId": self._client.team_id(self._team_key)})
        team = _require_dict(data.get("team"), "team")
        states = _require_dict(team.get("states"), "team.states")
        nodes = _require_list(states.get("nodes"), "team.states.nodes")
        completed: list[tuple[float, str]] = []
        for raw in nodes:
            node = _require_dict(raw, "workflow state")
            if node.get("type") != "completed":
                continue
            position = node.get("position")
            if not isinstance(position, int | float):
                raise IssueBackendError(
                    f"unexpected Linear payload shape (state position): {position!r}"
                )
            completed.append((float(position), _require_str(node.get("id"), "state id")))
        if not completed:
            raise IssueBackendError(
                f"Linear team {self._team_key!r} has no completed-type workflow state"
            )
        self._done_state_id_cache = min(completed)[1]
        return self._done_state_id_cache

    def _workflow_state_id(self, state_type: str) -> str | None:
        """The team's lowest-position workflow state of ``state_type`` (e.g. ``"started"``), or
        ``None`` when the team has no state of that type. Fetches every team state once (the same
        ``team { states { nodes { id name type position } } }`` query as :meth:`_done_state_id`)
        and caches a type → lowest-position-id map. Kept independent of ``_done_state_id`` (its own
        cache) to leave the learn-close path byte-stable.

        **Flagged (Phase-5 / Node 5.1 live gate):** the workflow-state mirror is not yet
        live-proven — covered offline here.
        """
        if self._states_by_type is None:
            query = (
                "query($teamId: String!) { team(id: $teamId) "
                "{ states { nodes { id name type position } } } }"
            )
            data = self._client.request(query, {"teamId": self._client.team_id(self._team_key)})
            team = _require_dict(data.get("team"), "team")
            states = _require_dict(team.get("states"), "team.states")
            nodes = _require_list(states.get("nodes"), "team.states.nodes")
            lowest: dict[str, tuple[float, str]] = {}
            for raw in nodes:
                node = _require_dict(raw, "workflow state")
                node_type = node.get("type")
                if not isinstance(node_type, str):
                    continue
                position = node.get("position")
                if not isinstance(position, int | float):
                    raise IssueBackendError(
                        f"unexpected Linear payload shape (state position): {position!r}"
                    )
                state_id = _require_str(node.get("id"), "state id")
                current = lowest.get(node_type)
                if current is None or float(position) < current[0]:
                    lowest[node_type] = (float(position), state_id)
            self._states_by_type = {key: value[1] for key, value in lowest.items()}
        return self._states_by_type.get(state_type)

    def _issue_or_none(self, issue_id: str, selection: str) -> dict[str, object] | None:
        """Fetch one issue by id; ``None`` when Linear reports the entity missing.

        ``issue_id`` may be the human identifier (``ENG-123``) or the UUID — ``issue(id:)``
        accepts both — reads need no identifier→UUID resolution.
        """
        query = f"query($id: String!) {{ issue(id: $id) {{ {selection} }} }}"
        try:
            data = self._client.request(query, {"id": issue_id})
        except LinearGraphQLError as exc:
            # Missing-entity discriminator: the observed `INPUT_ERROR` code paired with the
            # "Entity not found" message prefix
            # (docs/planning/linear-smoke-gate.md gate-8, 2026-06-15).
            # INPUT_ERROR alone is too broad, so both must match. Every other error re-raises.
            if _is_entity_not_found(exc):
                return None
            raise
        issue = data.get("issue")
        if issue is None:
            return None
        return _require_dict(issue, "issue")

    def _get_issue(self, issue_id: str, selection: str) -> dict[str, object]:
        """Fetch one issue by id; a missing issue raises (the mutation-path read)."""
        issue = self._issue_or_none(issue_id, selection)
        if issue is None:
            raise IssueBackendError(f"Linear issue {issue_id!r} not found")
        return issue

    def _comments(self, issue_id: str) -> list[dict[str, object]]:
        """All comments on an issue, sorted ascending by ``createdAt`` — pins GitHub's
        oldest-first first-match semantics without depending on Linear's connection ordering."""
        query = (
            "query($id: String!, $cursor: String) { issue(id: $id) "
            f"{{ comments(first: {_PAGE_SIZE}, after: $cursor) "
            "{ nodes { id body createdAt } pageInfo { hasNextPage endCursor } } } }"
        )
        nodes = self._client.paginate(query, {"id": issue_id}, "issue", "comments")
        return sorted(nodes, key=lambda c: _require_str(c.get("createdAt"), "comment createdAt"))

    # ------------------------------------------------------------------ human-engagement reads
    # The honest READ surface (Objective #682, Node 1.2). `_comments` (above) is deliberately
    # LEFT BYTE-STABLE — it feeds the marker-matching path, whose offline tests pin the
    # `{ id body createdAt }` selection. These are NEW, author-aware selections.

    def _comments_with_authors(self, issue_id: str) -> list[dict[str, object]]:
        """All comments on an issue with author identity + ``editedAt``, sorted ascending by
        ``createdAt`` (the same oldest-first ordering as :meth:`_comments`). A separate selection
        from the byte-stable marker-matching ``_comments`` — it adds ``editedAt`` + the ``user`` /
        ``botActor`` author fields the engagement read contract maps."""
        query = (
            "query($id: String!, $cursor: String) { issue(id: $id) "
            f"{{ comments(first: {_PAGE_SIZE}, after: $cursor) "
            "{ nodes { id body createdAt editedAt user { id name displayName } "
            "botActor { id name type } } pageInfo { hasNextPage endCursor } } } }"
        )
        nodes = self._client.paginate(query, {"id": issue_id}, "issue", "comments")
        return sorted(nodes, key=lambda c: _require_str(c.get("createdAt"), "comment createdAt"))

    def _description_edits(self, issue_id: str) -> list[dict[str, object]]:
        """The issue's description-edit history nodes (those carrying a ``descriptionUpdatedBy``),
        sorted ascending by ``createdAt``. Selects fields explicitly (the SDK ``relationChanges``
        pitfall, inventory §3.2). Linear's history exposes no inline diff — the mapping sets
        ``diff=None`` (a flagged deferral). An absent issue yields ``[]``."""
        query = (
            "query($id: String!, $cursor: String) { issue(id: $id) "
            f"{{ history(first: {_PAGE_SIZE}, after: $cursor) "
            "{ nodes { id createdAt actor { id name } descriptionUpdatedBy { id name } } "
            "pageInfo { hasNextPage endCursor } } } }"
        )
        try:
            nodes = self._client.paginate(query, {"id": issue_id}, "issue", "history")
        except LinearGraphQLError as exc:
            if _is_entity_not_found(exc):
                return []
            raise
        edits = [node for node in nodes if _is_present(node.get("descriptionUpdatedBy"))]
        return sorted(edits, key=lambda h: _require_str(h.get("createdAt"), "history createdAt"))

    def _agent_session_activities(self, issue_id: str) -> list[dict[str, object]]:
        """The activities of the issue's agent session, sorted ascending by ``createdAt``.

        Two reads: resolve the issue's session id, then page its activities. A missing issue or
        missing session reuses the ``_is_entity_not_found`` → empty pattern (returns ``[]``); every
        other failure (notably an auth failure on the personal API key — inventory §6.2) **raises**
        (the contract: ``read_agent_session`` raises on infra/auth failure)."""
        issue = self._issue_or_none(issue_id, "agentSessions(first: 1) { nodes { id } }")
        if issue is None:
            return []
        sessions = _opt_dict(issue.get("agentSessions"))
        if sessions is None:
            return []
        session_nodes = _require_list(sessions.get("nodes"), "issue.agentSessions.nodes")
        if not session_nodes:
            return []
        session_id = _require_str(
            _require_dict(session_nodes[0], "agentSession").get("id"), "agent session id"
        )
        query = (
            "query($id: String!, $cursor: String) { agentSession(id: $id) "
            f"{{ activities(first: {_PAGE_SIZE}, after: $cursor) "
            "{ nodes { id createdAt signal content { __typename "
            "... on AgentActivityPromptContent { body } "
            "... on AgentActivityThoughtContent { body } "
            "... on AgentActivityResponseContent { body } } } "
            "pageInfo { hasNextPage endCursor } } } }"
        )
        try:
            nodes = self._client.paginate(query, {"id": session_id}, "agentSession", "activities")
        except LinearGraphQLError as exc:
            if _is_entity_not_found(exc):
                return []
            raise
        return sorted(nodes, key=lambda a: _require_str(a.get("createdAt"), "activity createdAt"))

    def _ensure_label_id(self, name: str, *, color: str, description: str) -> tuple[str, bool]:
        """Lookup-first label idempotency. Returns ``(label UUID, created)``; caches.

        The lookup is deliberately **unscoped**: a workspace-level label with the name also
        counts (and would make a team-scoped create a duplicate-name error).
        """
        cached = self._label_ids.get(name)
        if cached is not None:
            return cached, False
        found = self._lookup_label_id(name)
        if found is not None:
            self._label_ids[name] = found
            return found, False
        mutation = (
            "mutation($input: IssueLabelCreateInput!) { issueLabelCreate(input: $input) "
            "{ success issueLabel { id } } }"
        )
        # No `teamId`: perk's `perk:*` labels are conceptually workspace-wide (Linear's
        # issues/labels.md recommends workspace-level labels for cross-team labels), and the
        # lookup is already unscoped (a workspace label counts), so a team-scoped create would
        # be a duplicate-name error against an existing workspace label.
        variables: dict[str, object] = {
            "input": {
                "name": name,
                "color": _hex_color(color),
                "description": description,
            }
        }
        try:
            data = self._client.request(mutation, variables)
        except LinearGraphQLError as exc:
            # A duplicate-name race: another writer created the label between lookup and
            # create — re-lookup and treat as existed.
            if "duplicate" in str(exc).lower() or "already exists" in str(exc).lower():
                refound = self._lookup_label_id(name)
                if refound is not None:
                    self._label_ids[name] = refound
                    return refound, False
            raise
        payload = _require_dict(data.get("issueLabelCreate"), "issueLabelCreate")
        if payload.get("success") is not True:
            raise IssueBackendError(f"failed to create Linear label {name!r}")
        label = _require_dict(payload.get("issueLabel"), "issueLabelCreate.issueLabel")
        label_id = _require_str(label.get("id"), "label id")
        self._label_ids[name] = label_id
        return label_id, True

    def _lookup_label_id(self, name: str) -> str | None:
        query = (
            "query($name: String!) { issueLabels(filter: { name: { eq: $name } }) "
            "{ nodes { id } } }"
        )
        data = self._client.request(query, {"name": name})
        labels = _require_dict(data.get("issueLabels"), "issueLabels")
        nodes = _require_list(labels.get("nodes"), "issueLabels.nodes")
        if not nodes:
            return None
        node = _require_dict(nodes[0], "issueLabels.nodes[0]")
        return _require_str(node.get("id"), "label id")

    def _list_label_issues(self, label: str, selection: str) -> list[dict[str, object]]:
        """List the team's **open** issues carrying ``label`` (the find_plan_issue-semantics
        listing: team-scoped, label-scoped, non-terminal workflow states only)."""
        query = (
            "query($teamId: ID!, $label: String!, $cursor: String) { "
            f"issues(first: {_PAGE_SIZE}, after: $cursor, filter: {{ "
            "team: { id: { eq: $teamId } }, "
            "labels: { name: { eq: $label } }, "
            'state: { type: { nin: ["completed", "canceled"] } } '
            f"}}) {{ nodes {{ {selection} }} pageInfo {{ hasNextPage endCursor }} }} }}"
        )
        return self._client.paginate(
            query, {"teamId": self._client.team_id(self._team_key), "label": label}, "issues"
        )

    def _find_issue_by_run_id(
        self, *, label: str, header_key: str, run_id: str
    ) -> issue_backend.IssueRef | None:
        """The ``find_plan_issue``-semantics core: list open label-scoped issues, match the
        header block's ``run_id``. None after exhausting pages; infra/query failures propagate
        (never masked as None)."""
        for node in self._list_label_issues(label, "id identifier url description"):
            description = node.get("description")
            if (
                isinstance(description, str)
                and plan.extract_run_id(description, header_key=header_key) == run_id
            ):
                identifier = _require_str(node.get("identifier"), "issue identifier")
                return issue_backend.IssueRef(
                    id=identifier,
                    url=_require_str(node.get("url"), "issue url"),
                    existed=True,
                )
        return None

    def _create_issue(
        self,
        *,
        title: str,
        description: str,
        label_id: str | None = None,
        project_id: str | None = None,
        milestone_id: str | None = None,
    ) -> issue_backend.IssueRef:
        """Create an issue, returning just the ``IssueRef`` (the common path)."""
        ref, _uuid = self._create_issue_raw(
            title=title,
            description=description,
            label_id=label_id,
            project_id=project_id,
            milestone_id=milestone_id,
        )
        return ref

    def _create_issue_raw(
        self,
        *,
        title: str,
        description: str,
        label_id: str | None = None,
        project_id: str | None = None,
        milestone_id: str | None = None,
    ) -> tuple[issue_backend.IssueRef, str]:
        """Create an issue, returning ``(IssueRef, uuid)``. The ``issueCreate`` response already
        carries the new issue's UUID, so the objective relation paths capture it here (for
        ``issueRelationCreate``, which is only verified for UUIDs) with no extra query."""
        mutation = (
            "mutation($input: IssueCreateInput!) { issueCreate(input: $input) "
            "{ success issue { id identifier url } } }"
        )
        # Conditional label/project/milestone attachment: only add the keys when set — omit,
        # never send an explicit `null`. Every plan/learn/objective caller passes a label, so the
        # input is byte-identical for them; node-issues (Node 3.2) pass `label_id=None` (they are
        # discovered by project membership + the node block, so they carry no perk label).
        issue_input: dict[str, object] = {
            "teamId": self._client.team_id(self._team_key),
            "title": title,
            "description": description,
            # Every perk-created issue (plan, learn, objective-issue, node-issue) is owned by the
            # API-key user, so it surfaces in their My Issues. The viewer UUID is resolved once
            # and cached on the client.
            "assigneeId": self._client.viewer_id(),
        }
        if label_id is not None:
            issue_input["labelIds"] = [label_id]
        if project_id is not None:
            issue_input["projectId"] = project_id
        if milestone_id is not None:
            issue_input["projectMilestoneId"] = milestone_id
        variables: dict[str, object] = {"input": issue_input}
        data = self._client.request(mutation, variables)
        payload = _require_dict(data.get("issueCreate"), "issueCreate")
        if payload.get("success") is not True:
            raise IssueBackendError(f"failed to create Linear issue {title!r}")
        issue = _require_dict(payload.get("issue"), "issueCreate.issue")
        identifier = _require_str(issue.get("identifier"), "issue identifier")
        uuid = _require_str(issue.get("id"), "issue id")
        ref = issue_backend.IssueRef(
            id=identifier,
            url=_require_str(issue.get("url"), "issue url"),
            existed=False,
        )
        return ref, uuid

    def _update_issue(self, issue_id: str, fields: dict[str, object], *, what: str) -> None:
        mutation = (
            "mutation($id: String!, $input: IssueUpdateInput!) "
            "{ issueUpdate(id: $id, input: $input) { success } }"
        )
        data = _request_issue_mutation(
            self._client, mutation, {"id": issue_id, "input": fields}, issue_id=issue_id
        )
        payload = _require_dict(data.get("issueUpdate"), "issueUpdate")
        if payload.get("success") is not True:
            raise IssueBackendError(f"failed to {what} on Linear issue {issue_id!r}")

    def _create_comment(self, issue_id: str, body: str) -> None:
        """Post a comment. ``body`` is already Linear-encoded (callers transcode once)."""
        mutation = (
            "mutation($input: CommentCreateInput!) { commentCreate(input: $input) { success } }"
        )
        variables: dict[str, object] = {"input": {"issueId": issue_id, "body": body}}
        data = _request_issue_mutation(self._client, mutation, variables, issue_id=issue_id)
        payload = _require_dict(data.get("commentCreate"), "commentCreate")
        if payload.get("success") is not True:
            raise IssueBackendError(f"failed to comment on Linear issue {issue_id!r}")

    def _create_comment_with_id(self, issue_id: str, body: str) -> str:
        """Post a comment and return its string UUID (the objective-body two-step create needs
        the id for the header backfill). ``body`` is already Linear-encoded (callers transcode
        once). Raises on failure or a malformed payload."""
        mutation = (
            "mutation($input: CommentCreateInput!) { commentCreate(input: $input) "
            "{ success comment { id } } }"
        )
        variables: dict[str, object] = {"input": {"issueId": issue_id, "body": body}}
        data = _request_issue_mutation(self._client, mutation, variables, issue_id=issue_id)
        payload = _require_dict(data.get("commentCreate"), "commentCreate")
        if payload.get("success") is not True:
            raise IssueBackendError(f"failed to comment on Linear issue {issue_id!r}")
        comment = _require_dict(payload.get("comment"), "commentCreate.comment")
        return _require_str(comment.get("id"), "comment id")

    def _comment_body_or_none(self, comment_id: str) -> str | None:
        """Fetch one comment's body by id; ``None`` when Linear reports the entity missing
        (mirrors ``_issue_or_none``'s observed `INPUT_ERROR` + "Entity not found" pairing)."""
        query = "query($id: String!) { comment(id: $id) { body } }"
        try:
            data = self._client.request(query, {"id": comment_id})
        except LinearGraphQLError as exc:
            if _is_entity_not_found(exc):
                return None
            raise
        comment = data.get("comment")
        if comment is None:
            return None
        body = _require_dict(comment, "comment").get("body")
        return _opt_str(body)

    def _update_comment(self, comment_id: str, body: str) -> None:
        """Patch a comment. ``body`` is already Linear-encoded (callers transcode once)."""
        mutation = (
            "mutation($id: String!, $input: CommentUpdateInput!) "
            "{ commentUpdate(id: $id, input: $input) { success } }"
        )
        data = self._client.request(mutation, {"id": comment_id, "input": {"body": body}})
        payload = _require_dict(data.get("commentUpdate"), "commentUpdate")
        if payload.get("success") is not True:
            raise IssueBackendError(f"failed to update Linear comment {comment_id!r}")

    def create_attachment(
        self, issue_id: str, *, url: str, title: str, subtitle: str | None = None
    ) -> None:
        """Create (or update-in-place) a native sidebar **attachment** on an issue.

        ``attachmentCreate`` is **idempotent by URL** (re-creating the same URL on the same issue
        updates the existing card — no id to track), so callers may post on every PR stamp without
        duplicates. ``issue_id`` is the boundary identifier directly (consistent with
        :meth:`_LinearProjectOps.attach_issue_to_project`), routed through
        :func:`_request_issue_mutation` for the same not-found mapping; checks ``success``.
        """
        mutation = (
            "mutation($input: AttachmentCreateInput!) { attachmentCreate(input: $input) "
            "{ success } }"
        )
        attachment_input: dict[str, object] = {"issueId": issue_id, "url": url, "title": title}
        if subtitle is not None:
            attachment_input["subtitle"] = subtitle
        data = _request_issue_mutation(
            self._client, mutation, {"input": attachment_input}, issue_id=issue_id
        )
        payload = _require_dict(data.get("attachmentCreate"), "attachmentCreate")
        if payload.get("success") is not True:
            raise IssueBackendError(f"failed to create attachment on Linear issue {issue_id!r}")
