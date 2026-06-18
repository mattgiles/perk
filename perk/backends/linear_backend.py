"""The Linear issue backend — plans, learn issues, labels, and the generic comment ops
(Objective #252, Node 2.2).

``LinearIssueBackend`` implements the issue-tier contract
(``perk.backends.issue_backend.IssueBackend``) over the Node 2.1 GraphQL client substrate
(``perk.backends.linear.LinearClient``), with team-scoped + label-scoped queries and body-marker
idempotency matching the ``find_plan_issue`` semantics of the GitHub backend. The objective tier
(Node 2.3) mirrors ``perk.github``'s behavior shapes
(the two-step create with comment-id backfill, header LBYL, authoritative roadmap writes +
best-effort comment re-renders, the Reconcilable splice).

Live: the resolver in the issues module constructs this backend on ``backend = "linear"`` (config
``[issues] team`` parsing, init/doctor readiness, and the contracts §8.21 amendment landed in Node
2.4). :func:`check_readiness` is the shared init/doctor readiness probe (auth + team + the four
perk labels), report-shaped (never raises), mirroring ``github.check_auth``'s degrade discipline.

**Linear-safe encoding.** Caller-composed bodies arrive in the GitHub encoding — HTML-comment
metadata-block delimiters + ``<details>`` wrappers (rendered by ``perk.plan``). Linear stores
descriptions/comments as ProseMirror documents and round-trips markdown on write/read; HTML
comments and ``<details>`` are not in its supported markdown set and must be assumed lossy
(inline code and code fences ARE supported). So every outgoing body is transcoded by
:func:`to_linear_markdown` into the inline-code sentinel encoding (``perk.plan``'s dual-encoding
engine parses both forms), and every incoming ``marker`` argument is transcoded the same way so
marker-keyed comment upserts stay idempotent end-to-end. The round-trip fidelity is verified
live at Node 4.1's smoke gate (flagged deferral — mitigated here, not proven).

**Identifier boundary ids (Node 4.1).** Boundary issue ids are the human Linear identifier
(``ENG-123``), not the UUID: plan worktrees become ``plan-ENG-123`` (exploiting Linear's
branch-name auto-link when the GitHub integration is installed), and every envelope/prompt
renders readably. Reads pass identifiers natively (``issue(id:)`` accepts the identifier
interchangeably with the UUID); the verified **mutations** (``issueUpdate``/``commentCreate``)
also take the boundary identifier directly (live-verified at the Mode 2 smoke gate, 2026-06-15 —
no identifier→UUID resolution layer remains). ``issueRelationCreate`` (objective blocking
relations) is UUID-only — it receives the issue UUID captured from the ``issueCreate`` response at
issue-create time. Comment ids remain UUIDs (comments have no identifier). The envelope id
re-shaping
formerly deferred here landed with Node 4.1 (always-string issue ids at every ``--json``
boundary — contracts §8.21).

Explicit deferrals (flagged, not silently omitted):

- **Live round-trip fidelity** — recorded at the live smoke gate
  (``docs/planning/linear-smoke-gate.md``).
- **Not-found discrimination** — *implemented* (Node 1.2, 2026-06-15 observation): the three
  not-found sites pair ``INPUT_ERROR in exc.codes`` with the ``"Entity not found"`` message
  prefix (``_is_entity_not_found``). The gate-8 row recorded ``INPUT_ERROR`` as a *generic*
  input-error code, so a ``.codes``-only tightening would have been too broad — hence the
  pairing.
- **Rate-limit retry/backoff** — *decided fail-loud* (Node 1.2): no RATELIMITED tripped at the
  smoke gate (gate-9, "not tripped at low volume"), so there is no observed behavior to justify
  backoff. The client keeps raising the typed ``LinearGraphQLError``; retry/backoff stays
  deferred until a live RATELIMITED is observed (``docs/planning/linear-smoke-gate.md``).
"""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

from perk import github, objective, objective_drift, plan
from perk.backends import issue_backend, objective_store
from perk.backends.issue_backend import IssueBackendError
from perk.backends.linear import (
    LinearClient,
    LinearGraphQLError,
    _is_entity_not_found,
    _require_dict,
    _require_list,
    _require_str,
)
from perk.backends.objective_store import ObjectiveStoreError
from perk.github import GitHubError

_PAGE_SIZE = 50

# Every perk HTML-comment marker — metadata-block delimiters AND the run-report marker —
# rewritten generically to its inline-code sentinel.
_PERK_MARKER_RE = re.compile(r"<!--\s*(/?perk:[^>]+?)\s*-->")

# The exact perk-rendered `<details>` wrapper shapes (perk.plan's html-style renderers).
_DETAILS_OPEN_RE = re.compile(r"^<details><summary><code>[^<]*</code></summary>$")
_DETAILS_CLOSE = "</details>"

# The best-effort node-status → Linear workflow-state `type` mirror (Node 3.3). The status block
# is the source of truth; this mirror only nudges the node-issue's workflow state to match (so the
# project board reflects the roadmap). `blocked` has no Linear equivalent — mapped to `started`
# (it is in-flight work, just stuck).
_NODE_STATUS_STATE_TYPE: dict[str, str] = {
    "pending": "unstarted",
    "planning": "started",
    "in_progress": "started",
    "done": "completed",
    "blocked": "started",
    "skipped": "canceled",
}


def to_linear_markdown(text: str) -> str:
    """Transcode perk's GitHub-encoded markers into the Linear-safe inline-code encoding.

    Rewrites every perk HTML-comment marker (``<!-- perk:… -->`` / ``<!-- /perk:… -->``) to its
    inline-code sentinel (`` `perk:…` `` / `` `/perk:…` ``) and drops the perk-rendered
    ``<details>`` wrapper lines. Identity for any other text (non-perk markers pass through
    untouched). Pure; applied to every outgoing body/description/comment and every incoming
    ``marker`` argument.
    """
    rewritten = _PERK_MARKER_RE.sub(lambda m: f"`{m.group(1)}`", text)
    lines = [
        line
        for line in rewritten.splitlines()
        if not (_DETAILS_OPEN_RE.match(line) or line == _DETAILS_CLOSE)
    ]
    result = "\n".join(lines)
    if rewritten.endswith("\n"):
        result += "\n"
    return result


def _hex_color(color: str) -> str:
    """Map the GitHub bare-hex label colors into Linear's ``#``-prefixed form."""
    return color if color.startswith("#") else f"#{color}"


def _request_issue_mutation(
    client: LinearClient,
    mutation: str,
    variables: dict[str, object],
    *,
    issue_id: str,
) -> dict[str, object]:
    """Run an issue-targeted mutation, preserving the not-found error mapping.

    The verified issue mutations (``issueUpdate``/``commentCreate``) take the boundary
    **identifier** directly (live-verified at the Mode 2 smoke gate). A missing entity surfaces
    as a ``LinearGraphQLError`` matching :func:`_is_entity_not_found`; re-raise it as the
    byte-identical ``IssueBackendError("Linear issue <id> not found")`` the old ``uuid_for``
    resolution emitted. Every other error propagates unchanged.
    """
    try:
        return client.request(mutation, variables)
    except LinearGraphQLError as exc:
        if _is_entity_not_found(exc):
            raise IssueBackendError(f"Linear issue {issue_id!r} not found") from exc
        raise


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
        variables: dict[str, object] = {
            "input": {
                "name": name,
                "color": _hex_color(color),
                "description": description,
                "teamId": self._client.team_id(self._team_key),
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
        return body if isinstance(body, str) else None

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
                    "description": description if isinstance(description, str) else "",
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
            milestone = node.get("projectMilestone")
            milestone_name: str | None = None
            if isinstance(milestone, dict):
                raw_name = cast("dict[str, object]", milestone).get("name")
                milestone_name = raw_name if isinstance(raw_name, str) else None
            result.append(
                {
                    "id": _require_str(node.get("id"), "issue id"),
                    "identifier": _require_str(node.get("identifier"), "issue identifier"),
                    "url": _require_str(node.get("url"), "issue url"),
                    "description": description if isinstance(description, str) else "",
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
                    "content": content if isinstance(content, str) else None,
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
        return content if isinstance(content, str) else None

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


class LinearIssueBackend:
    """``IssueBackend`` over Linear — constructor-bound ``team_key`` (lazily resolved + cached),
    human **identifiers** (``ENG-123``) as boundary issue ids (the verified mutations take the
    identifier directly; comment ids stay UUIDs), Linear-safe-encoded
    bodies, and the GitHub-twin behavior shapes for every plan/learn/label/comment op. A thin
    facade over the shared :class:`_LinearIssueOps` substrate."""

    # The `[issues] backend` vocabulary id — a module-level literal (never imported from the
    # resolver module, which will import us at wiring time).
    backend_id = "linear"

    def __init__(self, client: LinearClient, *, team_key: str, repo_root: Path) -> None:
        # The shared substrate (caches + every issue-op helper), also owned by
        # ``LinearObjectiveStore``. `repo_root` lives on `_ops` (the PR-tier `_get_pr` reads it).
        self._ops = _LinearIssueOps(client, team_key=team_key, repo_root=repo_root)
        # Re-exposed for the resolver tests that assert the bound team key.
        self._team_key = team_key

    # ------------------------------------------------------------------ labels

    def ensure_label(
        self, name: str, *, color: str, description: str, dry_run: bool = False
    ) -> issue_backend.Label:
        if dry_run:
            return issue_backend.Label(name=name, created=False)
        _, created = self._ops._ensure_label_id(name, color=color, description=description)
        return issue_backend.Label(name=name, created=created)

    # ------------------------------------------------------------------ plan issues

    def find_plan_issue(self, *, run_id: str) -> issue_backend.IssueRef | None:
        return self._ops._find_issue_by_run_id(
            label=plan.PLAN_LABEL, header_key=plan.PLAN_HEADER_KEY, run_id=run_id
        )

    def create_plan_issue(
        self, *, title: str, body: str, run_id: str | None, dry_run: bool = False
    ) -> issue_backend.IssueRef:
        if dry_run:
            return issue_backend.IssueRef(id="0", url="(dry-run)", existed=False)
        if run_id:
            existing = self.find_plan_issue(run_id=run_id)
            if existing is not None:
                return existing
        label_id, _ = self._ops._ensure_label_id(
            plan.PLAN_LABEL,
            color=plan.PLAN_LABEL_COLOR,
            description=plan.PLAN_LABEL_DESCRIPTION,
        )
        return self._ops._create_issue(
            title=title, description=to_linear_markdown(body), label_id=label_id
        )

    def update_plan_issue(
        self, *, issue_id: str, title: str, body_comment: str, dry_run: bool = False
    ) -> issue_backend.PlanUpdate:
        if dry_run:
            return issue_backend.PlanUpdate(
                issue_id=issue_id, body_updated=False, title_updated=False, dry_run=True
            )
        transcoded = to_linear_markdown(body_comment)
        comment_id: str | None = None
        for comment in self._ops._comments(issue_id):
            comment_body = comment.get("body")
            if isinstance(comment_body, str) and plan.extract_plan_body(comment_body) is not None:
                comment_id = _require_str(comment.get("id"), "comment id")
                break
        if comment_id is not None:
            self._ops._update_comment(comment_id, transcoded)
            body_updated = True
        else:
            self._ops._create_comment(issue_id, transcoded)
            body_updated = False
        self._ops._update_issue(issue_id, {"title": title}, what="update title")
        return issue_backend.PlanUpdate(
            issue_id=issue_id, body_updated=body_updated, title_updated=True, dry_run=False
        )

    def update_plan_header(
        self, *, issue_id: str, fields: dict[str, object], dry_run: bool = False
    ) -> issue_backend.PlanHeaderUpdate:
        unknown = set(fields) - plan.PLAN_HEADER_FIELDS
        if unknown:
            raise IssueBackendError(f"unknown plan-header field(s): {sorted(unknown)}")
        issue = self._ops._get_issue(issue_id, "id description")
        description = issue.get("description")
        body = description if isinstance(description, str) else ""
        header = plan.find_metadata_block(body, plan.PLAN_HEADER_KEY) or {}
        new_body = plan.replace_metadata_block(body, plan.PLAN_HEADER_KEY, {**header, **fields})
        if dry_run:
            return issue_backend.PlanHeaderUpdate(fields_updated=tuple(fields), dry_run=True)
        self._ops._update_issue(issue_id, {"description": new_body}, what="update plan-header")
        return issue_backend.PlanHeaderUpdate(fields_updated=tuple(fields), dry_run=False)

    def prepend_plan_callout(
        self, *, issue_id: str, callout: str, command: str, dry_run: bool = False
    ) -> bool:
        issue = self._ops._get_issue(issue_id, "id description")
        description = issue.get("description")
        body = description if isinstance(description, str) else ""
        new_body = plan.prepend_callout(body, callout, command=command)
        if new_body == body:
            return False
        if dry_run:
            return False
        self._ops._update_issue(issue_id, {"description": new_body}, what="prepend plan callout")
        return True

    def get_plan(self, *, issue_id: str) -> issue_backend.PlanState | None:
        issue = self._ops._issue_or_none(
            issue_id, "id identifier url title description state { type }"
        )
        if issue is None:
            return None
        description = issue.get("description")
        body = description if isinstance(description, str) else ""
        header = plan.find_metadata_block(body, plan.PLAN_HEADER_KEY) or {}
        pr_field = header.get("pr")
        pr = (
            self._get_pr(int(pr_field))
            if isinstance(pr_field, str | int) and str(pr_field).strip() and str(pr_field) != "None"
            else None
        )
        state = _require_dict(issue.get("state"), "issue.state")
        state_type = _require_str(state.get("type"), "issue.state.type")
        return issue_backend.PlanState(
            id=_require_str(issue.get("identifier"), "issue identifier"),
            url=_require_str(issue.get("url"), "issue url"),
            title=_require_str(issue.get("title"), "issue title"),
            header=header,
            pr=pr,
            state="CLOSED" if state_type in ("completed", "canceled") else "OPEN",
        )

    def _get_pr(self, number: int) -> github.PullRequest | None:
        """The PR tier is GitHub-universal for every backend (the protocol docstring). Late-bound
        module-attribute access (the adapter discipline) so test monkeypatches keep working."""
        try:
            return github.get_pr(number=number, repo_root=self._ops.repo_root)
        except GitHubError as exc:
            raise IssueBackendError(str(exc)) from exc

    def get_plan_body(self, *, issue_id: str) -> str | None:
        issue = self._ops._issue_or_none(issue_id, "id description")
        if issue is None:
            return None
        description = issue.get("description")
        candidates = [description if isinstance(description, str) else ""]
        candidates.extend(
            comment_body
            for comment in self._ops._comments(issue_id)
            if isinstance(comment_body := comment.get("body"), str)
        )
        for text in candidates:
            body = plan.extract_plan_body(text)
            if body:
                return body
        return None

    # ------------------------------------------------------------------ learn issues

    def find_learn_issue(self, *, run_id: str) -> issue_backend.IssueRef | None:
        return self._ops._find_issue_by_run_id(
            label=plan.LEARN_LABEL, header_key=plan.LEARN_HEADER_KEY, run_id=run_id
        )

    def create_learn_issue(
        self, *, title: str, body: str, run_id: str | None, plan_id: str, dry_run: bool = False
    ) -> issue_backend.IssueRef:
        if dry_run:
            return issue_backend.IssueRef(id="0", url="(dry-run)", existed=False)
        if run_id:
            existing = self.find_learn_issue(run_id=run_id)
            if existing is not None:
                return existing
        label_id, _ = self._ops._ensure_label_id(
            plan.LEARN_LABEL,
            color=plan.LEARN_LABEL_COLOR,
            description=plan.LEARN_LABEL_DESCRIPTION,
        )
        # Rendered directly in the inline-code style (no transcoding needed). The header `plan`
        # field stores the boundary `plan_id` string verbatim (headers are backend-owned opaque
        # values — GitHub stores its int issue number; Linear stores its string id).
        header = plan.render_metadata_block(
            plan.LEARN_HEADER_KEY,
            {"run_id": run_id, "created": plan.now_iso(), "plan": plan_id},
            style="inline-code",
        )
        full_body = f"{header}\n\n{to_linear_markdown(body.strip())}\n"
        return self._ops._create_issue(title=title, description=full_body, label_id=label_id)

    def list_learn_issues(self) -> tuple[issue_backend.LearnIssueSummary, ...]:
        summaries: list[issue_backend.LearnIssueSummary] = []
        selection = "id identifier title url description"
        for node in self._ops._list_label_issues(plan.LEARN_LABEL, selection):
            description = node.get("description")
            identifier = _require_str(node.get("identifier"), "issue identifier")
            summaries.append(
                issue_backend.LearnIssueSummary(
                    id=identifier,
                    title=_require_str(node.get("title"), "issue title"),
                    url=_require_str(node.get("url"), "issue url"),
                    body=description if isinstance(description, str) else "",
                )
            )
        return tuple(summaries)

    def close_and_label_consolidated(self, *, issue_id: str, dry_run: bool = False) -> bool:
        if dry_run:
            return True
        label_id, _ = self._ops._ensure_label_id(
            plan.CONSOLIDATED_LABEL,
            color=plan.CONSOLIDATED_LABEL_COLOR,
            description=plan.CONSOLIDATED_LABEL_DESCRIPTION,
        )
        # Additive labelling: read the existing label ids, union in the consolidated label
        # (issueUpdate's labelIds REPLACES the set — never write it without the existing ids).
        issue = self._ops._get_issue(issue_id, "id labels { nodes { id } }")
        labels = _require_dict(issue.get("labels"), "issue.labels")
        existing = [
            _require_str(_require_dict(raw, "label").get("id"), "label id")
            for raw in _require_list(labels.get("nodes"), "issue.labels.nodes")
        ]
        label_ids = existing if label_id in existing else [*existing, label_id]
        self._ops._update_issue(issue_id, {"labelIds": label_ids}, what="label consolidated")
        self._ops._update_issue(issue_id, {"stateId": self._ops._done_state_id()}, what="close")
        return True

    # ------------------------------------------------------------------ generic issue ops

    def close_issue(self, *, issue_id: str, dry_run: bool = False) -> bool:
        if dry_run:
            return False
        self._ops._update_issue(issue_id, {"stateId": self._ops._done_state_id()}, what="close")
        return True

    def add_issue_comment(
        self, *, issue_id: str, body: str, dry_run: bool = False
    ) -> issue_backend.CommentResult:
        if dry_run:
            return issue_backend.CommentResult(posted=False)
        self._ops._create_comment(issue_id, to_linear_markdown(body))
        return issue_backend.CommentResult(posted=True)

    def find_comment_id_by_marker(self, *, issue_id: str, marker: str) -> str | None:
        # The incoming marker is GitHub-encoded (e.g. the run-report HTML comment); transcode it
        # so it matches the transcoded comment this backend previously wrote.
        needle = to_linear_markdown(marker)
        for comment in self._ops._comments(issue_id):
            comment_body = comment.get("body")
            if isinstance(comment_body, str) and needle in comment_body:
                return _require_str(comment.get("id"), "comment id")
        return None

    def upsert_marked_comment(
        self, *, issue_id: str, marker: str, body: str, dry_run: bool = False
    ) -> issue_backend.CommentResult:
        if dry_run:
            return issue_backend.CommentResult(posted=False)
        transcoded = to_linear_markdown(body)
        comment_id = self.find_comment_id_by_marker(issue_id=issue_id, marker=marker)
        if comment_id is not None:
            self._ops._update_comment(comment_id, transcoded)
        else:
            self._ops._create_comment(issue_id, transcoded)
        return issue_backend.CommentResult(posted=True)


# ===========================================================================
# The objective-storage tier (Objective #548, Node 2.2): `LinearObjectiveStore`.
# The GitHub-twin objective behavior, lifted off `LinearIssueBackend` onto its own store behind
# the Node 2.1 `ObjectiveStore` contract. Owns its own `_LinearIssueOps` substrate (the registered
# collaborator) and maps `IssueBackendError` → `ObjectiveStoreError` at every method boundary
# (message preserved verbatim). `objective_id` is the human Linear identifier at the boundary.
# ===========================================================================


@contextmanager
def _translate_objective() -> Iterator[None]:
    """Map the issue substrate's native error into the objective-tier neutral one (verbatim)."""
    try:
        yield
    except IssueBackendError as exc:
        raise ObjectiveStoreError(str(exc)) from exc


def _objective_ref(ref: issue_backend.IssueRef) -> objective_store.ObjectiveRef:
    """Convert a substrate `IssueRef` into the objective-tier `ObjectiveRef` (same fields)."""
    return objective_store.ObjectiveRef(id=ref.id, url=ref.url, existed=ref.existed)


class LinearObjectiveStore:
    """``ObjectiveStore`` over Linear issues — the GitHub-twin objective tier (two-step create +
    comment-id backfill, header LBYL, authoritative roadmap writes with best-effort comment
    re-renders, the Reconcilable splice) behind the Node 2.1 contract. Owns its own
    :class:`_LinearIssueOps` substrate; maps ``IssueBackendError`` → ``ObjectiveStoreError`` at
    every boundary (message verbatim).

    **Dormant since Node 3.4:** the resolver's ``linear`` arm now constructs
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
                objective.OBJECTIVE_HEADER_KEY, header.to_data(), style="inline-code"
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
            body = description if isinstance(description, str) else ""
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
            body = description if isinstance(description, str) else ""
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
            body = raw_description if isinstance(raw_description, str) else ""
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
            body = raw_description if isinstance(raw_description, str) else ""
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
            body = raw_description if isinstance(raw_description, str) else ""
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

    def post_status_update(self, *, objective_id: str, body: str, dry_run: bool = False) -> bool:
        """The issue-backed store has no project status-update surface \u2014 always ``False``
        (no-op; Node 4.3)."""
        return False

    def detect_objective_drift(self, *, objective_id: str) -> objective_store.DriftReport:
        """The issue-backed store edits its roadmap block atomically with the issue body — no
        divergence surface, so the drift report is trivially empty (Node 4.4 / #612 no-op)."""
        return objective_store.DriftReport()

    def repair_objective_drift(
        self, *, objective_id: str, dry_run: bool = False
    ) -> objective_store.RepairResult:
        """The issue-backed store has no divergence surface — an empty no-op repair (#612)."""
        return objective_store.RepairResult(
            applied=(), failed=None, remaining=(), aborted=False, dry_run=dry_run
        )


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
                    content if isinstance(content, str) else "", objective.OBJECTIVE_HEADER_KEY
                )
                if header is not None and header.get("run_id") == run_id:
                    return objective_store.ObjectiveRef(
                        id=_require_str(proj.get("id"), "project id"),
                        url=_require_str(proj.get("url"), "project url"),
                        existed=True,
                    )
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
            # Transcode the whole overview so the HTML Reconcilable markers become inline-code
            # sentinels (the 4.1 reconcile splice is dual-encoding and finds them either way).
            overview = to_linear_markdown(f"{header_block}\n\n{manifest_block}\n\n{reconcilable}\n")
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
            node_uuid: dict[str, str] = {}
            for node in sorted(nodes, key=lambda n: objective.node_sort_key(n.id)):
                description = to_linear_markdown(
                    plan.render_metadata_block(
                        objective.OBJECTIVE_NODE_KEY,
                        objective.render_node_block(node),
                        style="inline-code",
                    )
                    + "\n\n"
                    + node.description
                )
                _ref, uuid = self._issue_ops._create_issue_raw(
                    title=objective.node_issue_title(node),
                    description=description,
                    label_id=None,
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
            overview = overview if isinstance(overview, str) else ""
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
                body = description if isinstance(description, str) else ""
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
            body = description_raw if isinstance(description_raw, str) else ""
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
            description=description if isinstance(description, str) else "",
            status=status,
            pr=pr,
            slug=slug if isinstance(slug, str) else None,
            comment=comment if isinstance(comment, str) else None,
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
            overview = overview if isinstance(overview, str) else ""
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
            overview = overview if isinstance(overview, str) else ""
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
            overview = overview if isinstance(overview, str) else ""
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

            # Materialize the single node-issue (objective-node block + prose), inline-code.
            node_description = to_linear_markdown(
                plan.render_metadata_block(
                    objective.OBJECTIVE_NODE_KEY,
                    objective.render_node_block(new_node),
                    style="inline-code",
                )
                + "\n\n"
                + new_node.description
            )
            _ref, new_uuid = self._issue_ops._create_issue_raw(
                title=objective.node_issue_title(new_node),
                description=node_description,
                label_id=None,
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
        preserving), else insert (inline-code) just before the Reconcilable region."""
        if plan.has_metadata_block(overview, objective.OBJECTIVE_MANIFEST_KEY):
            return plan.replace_metadata_block(overview, objective.OBJECTIVE_MANIFEST_KEY, data)
        block = to_linear_markdown(
            plan.render_metadata_block(objective.OBJECTIVE_MANIFEST_KEY, data, style="inline-code")
        )
        for marker in (
            to_linear_markdown(objective.OBJECTIVE_RECONCILABLE_MARKER_START),
            objective.OBJECTIVE_RECONCILABLE_MARKER_START,
        ):
            idx = overview.find(marker)
            if idx != -1:
                return f"{overview[:idx]}{block}\n\n{overview[idx:]}"
        return f"{overview.rstrip()}\n\n{block}\n"

    def _sync_manifest_node_description(
        self, objective_id: str, node_id: str, description: str
    ) -> None:
        """Update the matching manifest entry's description (structural identity sync)."""
        project = self._projects.project_or_none(objective_id, "content")
        overview = project.get("content") if project is not None else ""
        overview = overview if isinstance(overview, str) else ""
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
        overview = overview if isinstance(overview, str) else ""
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
        overview = overview if isinstance(overview, str) else ""
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
            body = body_raw if isinstance(body_raw, str) else ""
            milestone_raw = issue.get("milestone_name")
            milestone_name = milestone_raw if isinstance(milestone_raw, str) else None
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
        node_description = to_linear_markdown(
            plan.render_metadata_block(
                objective.OBJECTIVE_NODE_KEY,
                objective.render_node_block(entry),
                style="inline-code",
            )
            + "\n\n"
            + entry.description
        )
        _ref, uuid = self._issue_ops._create_issue_raw(
            title=objective.node_issue_title(entry),
            description=node_description,
            label_id=None,
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
        overview = overview if isinstance(overview, str) else ""
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


# ===========================================================================
# Shared readiness probe (Node 2.4) — used by both `perk init` and `perk doctor`.
# Report-shaped (never raises): every failure mode lands in a `LinearReadiness` field,
# mirroring `github.check_auth`'s degrade discipline. Offline-testable through a
# `LinearClient`-subclass fake.
# ===========================================================================

# The four perk labels (name, color, description), the readiness probe ensures/looks up.
_PERK_LABELS: tuple[tuple[str, str, str], ...] = (
    (plan.PLAN_LABEL, plan.PLAN_LABEL_COLOR, plan.PLAN_LABEL_DESCRIPTION),
    (plan.LEARN_LABEL, plan.LEARN_LABEL_COLOR, plan.LEARN_LABEL_DESCRIPTION),
    (plan.CONSOLIDATED_LABEL, plan.CONSOLIDATED_LABEL_COLOR, plan.CONSOLIDATED_LABEL_DESCRIPTION),
    (
        objective.OBJECTIVE_LABEL,
        objective.OBJECTIVE_LABEL_COLOR,
        objective.OBJECTIVE_LABEL_DESCRIPTION,
    ),
)


@dataclass(frozen=True)
class LinearReadiness:
    """The init/doctor Linear readiness snapshot (report-shaped; never raises)."""

    auth_ok: bool
    user: str | None
    team_ok: bool
    missing_labels: tuple[str, ...] = ()
    created_labels: tuple[str, ...] = ()
    error: str | None = None


def check_readiness(client: LinearClient, *, team_key: str, ensure_labels: bool) -> LinearReadiness:
    """Probe Linear readiness: viewer auth, team resolution, and the four perk labels.

    Report-shaped — every failure mode lands in a ``LinearReadiness`` field (never raises),
    mirroring ``github.check_auth``. Phases short-circuit: an auth failure skips team + labels; a
    team failure skips labels. With ``ensure_labels=False`` (doctor report path) labels are
    looked up only and missing names land in ``missing_labels``; with ``ensure_labels=True``
    (init + doctor ``--fix``) each label is ensured and names actually created land in
    ``created_labels`` (lookup-first idempotency → a converged workspace reports none).
    """
    # --- auth: one viewer query ---
    try:
        data = client.request("{ viewer { id name email } }")
    except IssueBackendError as exc:
        return LinearReadiness(auth_ok=False, user=None, team_ok=False, error=str(exc))
    viewer = data.get("viewer")
    user: str | None = None
    if isinstance(viewer, dict):
        viewer_dict = cast("dict[str, object]", viewer)
        name = viewer_dict.get("name")
        email = viewer_dict.get("email")
        user = name if isinstance(name, str) and name.strip() else None
        if user is None and isinstance(email, str) and email.strip():
            user = email

    # --- team: resolve the team UUID (the client's shared resolver) ---
    backend = LinearIssueBackend(client, team_key=team_key, repo_root=Path())
    try:
        client.team_id(team_key)
    except IssueBackendError as exc:
        return LinearReadiness(auth_ok=True, user=user, team_ok=False, error=str(exc))

    # --- labels: the four perk labels ---
    missing: list[str] = []
    created: list[str] = []
    try:
        for name, color, description in _PERK_LABELS:
            if ensure_labels:
                _, was_created = backend._ops._ensure_label_id(
                    name, color=color, description=description
                )
                if was_created:
                    created.append(name)
            elif backend._ops._lookup_label_id(name) is None:
                missing.append(name)
    except IssueBackendError as exc:
        return LinearReadiness(
            auth_ok=True,
            user=user,
            team_ok=True,
            missing_labels=tuple(missing),
            created_labels=tuple(created),
            error=str(exc),
        )
    return LinearReadiness(
        auth_ok=True,
        user=user,
        team_ok=True,
        missing_labels=tuple(missing),
        created_labels=tuple(created),
    )


# The workflow-state `type`s the node-status mirror (`_NODE_STATUS_STATE_TYPE`) needs. Derived from
# the map (never hand-listed) so the two stay in lockstep (= {unstarted, started, completed,
# canceled}).
_REQUIRED_STATE_TYPES: frozenset[str] = frozenset(_NODE_STATUS_STATE_TYPE.values())


@dataclass(frozen=True)
class LinearProjectReadiness:
    """Project-backed objective readiness snapshot (report-shaped; never raises).

    Probed only after `check_readiness` reports auth_ok && team_ok. `projects_ok` reflects a
    non-mutating Project read probe (the find-scan's prerequisite); `missing_state_types` are
    the node-status-mirror state types the team lacks. Both are warn-level / non-fatal.
    """

    projects_ok: bool
    projects_error: str | None = None
    missing_state_types: tuple[str, ...] = ()
    states_error: str | None = None


def _present_state_types(data: dict[str, object]) -> frozenset[str]:
    """Lenient parse of the present workflow-state `type` strings from a team-states payload.

    Skips malformed nodes rather than raising (this probe never raises): a non-dict ``team`` /
    ``states`` / node, or a non-str ``type``, is simply dropped.
    """
    team = data.get("team")
    if not isinstance(team, dict):
        return frozenset()
    states = cast("dict[str, object]", team).get("states")
    if not isinstance(states, dict):
        return frozenset()
    nodes = cast("dict[str, object]", states).get("nodes")
    if not isinstance(nodes, list):
        return frozenset()
    present: set[str] = set()
    for raw in cast("list[object]", nodes):
        if not isinstance(raw, dict):
            continue
        node_type = cast("dict[str, object]", raw).get("type")
        if isinstance(node_type, str):
            present.add(node_type)
    return frozenset(present)


def check_project_readiness(client: LinearClient, *, team_key: str) -> LinearProjectReadiness:
    """Probe project-backed objective readiness: Project read-access + the workflow-state types
    the node-status mirror needs. Report-shaped (never raises). The CALLER gates on auth_ok &&
    team_ok — this reuses the client's cached ``team_id`` (a cache hit after ``check_readiness``),
    so no auth/team re-probe.
    """
    team_id = client.team_id(team_key)

    # --- projects: a non-mutating Project read (the find-scan's prerequisite). Independent of the
    # states phase — does NOT short-circuit it. ---
    projects_ok = False
    projects_error: str | None = None
    try:
        client.request(
            "query($teamId: String!) { team(id: $teamId) { projects(first: 1) { nodes { id } } } }",
            {"teamId": team_id},
        )
        projects_ok = True
    except IssueBackendError as exc:
        projects_error = str(exc)

    # --- states: the workflow-state types the node-status mirror needs. ---
    missing_state_types: tuple[str, ...] = ()
    states_error: str | None = None
    try:
        data = client.request(
            "query($teamId: String!) { team(id: $teamId) { states { nodes { type } } } }",
            {"teamId": team_id},
        )
        present = _present_state_types(data)
        missing_state_types = tuple(sorted(_REQUIRED_STATE_TYPES - present))
    except IssueBackendError as exc:
        states_error = str(exc)

    return LinearProjectReadiness(
        projects_ok=projects_ok,
        projects_error=projects_error,
        missing_state_types=missing_state_types,
        states_error=states_error,
    )
