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
interchangeably with the UUID); **mutations** resolve identifier→UUID through the cached
:meth:`LinearIssueBackend._uuid_for` lookup (mutation ``id`` args are not documented to accept
identifiers). Comment ids remain UUIDs (comments have no identifier). The envelope id re-shaping
formerly deferred here landed with Node 4.1 (always-string issue ids at every ``--json``
boundary — contracts §8.21).

Explicit deferrals (flagged, not silently omitted):

- **Live round-trip fidelity** — recorded at the live smoke gate (``docs/linear-smoke-gate.md``).
- **Not-found discrimination** — *implemented* (Node 1.2, 2026-06-15 observation): the three
  not-found sites pair ``INPUT_ERROR in exc.codes`` with the ``"Entity not found"`` message
  prefix (``_is_entity_not_found``). The gate-8 row recorded ``INPUT_ERROR`` as a *generic*
  input-error code, so a ``.codes``-only tightening would have been too broad — hence the
  pairing.
- **Rate-limit retry/backoff** — *decided fail-loud* (Node 1.2): no RATELIMITED tripped at the
  smoke gate (gate-9, "not tripped at low volume"), so there is no observed behavior to justify
  backoff. The client keeps raising the typed ``LinearGraphQLError``; retry/backoff stays
  deferred until a live RATELIMITED is observed (``docs/linear-smoke-gate.md``).
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from perk import github, objective, plan
from perk.backends import issue_backend
from perk.backends.issue_backend import IssueBackendError
from perk.backends.linear import LinearGraphQLError
from perk.github import GitHubError

_PAGE_SIZE = 50

# Every perk HTML-comment marker — metadata-block delimiters AND the run-report marker —
# rewritten generically to its inline-code sentinel.
_PERK_MARKER_RE = re.compile(r"<!--\s*(/?perk:[^>]+?)\s*-->")

# The exact perk-rendered `<details>` wrapper shapes (perk.plan's html-style renderers).
_DETAILS_OPEN_RE = re.compile(r"^<details><summary><code>[^<]*</code></summary>$")
_DETAILS_CLOSE = "</details>"


class GraphQLClient(Protocol):
    """The structural client seam: ``LinearClient`` satisfies it; offline tests pass a fake."""

    def request(
        self, query: str, variables: dict[str, object] | None = None
    ) -> dict[str, object]: ...


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


def _require_dict(value: object, what: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise IssueBackendError(f"unexpected Linear payload shape ({what}): {value!r}")
    return cast("dict[str, object]", value)


def _require_list(value: object, what: str) -> list[object]:
    if not isinstance(value, list):
        raise IssueBackendError(f"unexpected Linear payload shape ({what}): {value!r}")
    return cast("list[object]", value)


def _require_str(value: object, what: str) -> str:
    if not isinstance(value, str):
        raise IssueBackendError(f"unexpected Linear payload shape ({what}): {value!r}")
    return value


def _hex_color(color: str) -> str:
    """Map the GitHub bare-hex label colors into Linear's ``#``-prefixed form."""
    return color if color.startswith("#") else f"#{color}"


_ENTITY_NOT_FOUND_CODE = "INPUT_ERROR"


def _is_entity_not_found(exc: LinearGraphQLError) -> bool:
    """A missing-entity error: Linear returns the generic ``INPUT_ERROR`` code with an
    ``"Entity not found: <Entity>"`` message (observed at the live smoke gate, 2026-06-15 —
    docs/linear-smoke-gate.md gate-8 row). ``INPUT_ERROR`` alone is too broad (a generic
    input-error code), so pair it with the message prefix."""
    return _ENTITY_NOT_FOUND_CODE in exc.codes and "entity not found" in str(exc).lower()


class LinearIssueBackend:
    """``IssueBackend`` over Linear — constructor-bound ``team_key`` (lazily resolved + cached),
    human **identifiers** (``ENG-123``) as boundary issue ids (mutations resolve them to UUIDs
    via the cached :meth:`_uuid_for`; comment ids stay UUIDs), Linear-safe-encoded bodies, and
    the GitHub-twin behavior shapes for every plan/learn/label/comment op."""

    # The `[issues] backend` vocabulary id — a module-level literal (never imported from the
    # resolver module, which will import us at wiring time).
    backend_id = "linear"

    def __init__(self, client: GraphQLClient, *, team_key: str, repo_root: Path) -> None:
        # `repo_root` exists solely for the PR-tier `github.get_pr` call in `get_plan` —
        # the PR tier is GitHub-universal for every backend (the protocol docstring).
        self._client = client
        self._team_key = team_key
        self._repo_root = repo_root
        self._team_id_cache: str | None = None
        self._done_state_id_cache: str | None = None
        self._label_ids: dict[str, str] = {}
        # Boundary-id → issue UUID (the mutation-path resolution; seeded by every issue read).
        self._uuid_cache: dict[str, str] = {}

    # ------------------------------------------------------------------ internal helpers

    def _team_id(self) -> str:
        """Resolve (and cache) the team UUID from the constructor-bound team key."""
        if self._team_id_cache is not None:
            return self._team_id_cache
        query = "query($key: String!) { teams(filter: { key: { eq: $key } }) { nodes { id } } }"
        data = self._client.request(query, {"key": self._team_key})
        teams = _require_dict(data.get("teams"), "teams")
        nodes = _require_list(teams.get("nodes"), "teams.nodes")
        if not nodes:
            raise IssueBackendError(f"Linear team {self._team_key!r} not found")
        node = _require_dict(nodes[0], "teams.nodes[0]")
        self._team_id_cache = _require_str(node.get("id"), "team id")
        return self._team_id_cache

    def _done_state_id(self) -> str:
        """The team's first Done-category workflow state (lowest-position ``completed``)."""
        if self._done_state_id_cache is not None:
            return self._done_state_id_cache
        query = (
            "query($teamId: String!) { team(id: $teamId) "
            "{ states { nodes { id name type position } } } }"
        )
        data = self._client.request(query, {"teamId": self._team_id()})
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

    def _paginate(
        self, query: str, variables: dict[str, object], *path: str
    ) -> list[dict[str, object]]:
        """Generic cursor loop over a ``nodes`` + ``pageInfo`` connection at ``path``.

        ``query`` must accept a ``$cursor: String`` variable and select
        ``pageInfo { hasNextPage endCursor }``. Malformed payload shapes raise (never silently
        truncate).
        """
        nodes: list[dict[str, object]] = []
        cursor: str | None = None
        while True:
            data = self._client.request(query, {**variables, "cursor": cursor})
            connection: object = data
            for key in path:
                connection = _require_dict(connection, ".".join(path)).get(key)
            conn = _require_dict(connection, ".".join(path))
            for raw in _require_list(conn.get("nodes"), "nodes"):
                nodes.append(_require_dict(raw, "node"))
            page_info = _require_dict(conn.get("pageInfo"), "pageInfo")
            if not page_info.get("hasNextPage"):
                return nodes
            cursor = _require_str(page_info.get("endCursor"), "endCursor")

    def _issue_or_none(self, issue_id: str, selection: str) -> dict[str, object] | None:
        """Fetch one issue by id; ``None`` when Linear reports the entity missing.

        ``issue_id`` may be the human identifier (``ENG-123``) or the UUID — ``issue(id:)``
        accepts both. A successful read seeds the ``_uuid_for`` cache.
        """
        query = f"query($id: String!) {{ issue(id: $id) {{ {selection} }} }}"
        try:
            data = self._client.request(query, {"id": issue_id})
        except LinearGraphQLError as exc:
            # Missing-entity discriminator: the observed `INPUT_ERROR` code paired with the
            # "Entity not found" message prefix (docs/linear-smoke-gate.md gate-8, 2026-06-15).
            # INPUT_ERROR alone is too broad, so both must match. Every other error re-raises.
            if _is_entity_not_found(exc):
                return None
            raise
        issue = data.get("issue")
        if issue is None:
            return None
        payload = _require_dict(issue, "issue")
        uuid = payload.get("id")
        if isinstance(uuid, str) and uuid:
            self._uuid_cache[issue_id] = uuid
        return payload

    def _get_issue(self, issue_id: str, selection: str) -> dict[str, object]:
        """Fetch one issue by id; a missing issue raises (the mutation-path read)."""
        issue = self._issue_or_none(issue_id, selection)
        if issue is None:
            raise IssueBackendError(f"Linear issue {issue_id!r} not found")
        return issue

    def _uuid_for(self, issue_id: str) -> str:
        """Resolve a boundary id (identifier-or-UUID) to the issue UUID — the mutation path.

        ``issue(id:)`` *reads* accept the human identifier interchangeably with the UUID;
        mutation ``id``/``issueId`` args are not documented to, so every mutation routes its
        target id through here. Cached; issue reads seed the cache, so the common
        mutate-after-read path issues no extra query.
        """
        cached = self._uuid_cache.get(issue_id)
        if cached is not None:
            return cached
        query = "query UuidForIssue($id: String!) { issue(id: $id) { id } }"
        try:
            data = self._client.request(query, {"id": issue_id})
        except LinearGraphQLError as exc:
            # Same observed `INPUT_ERROR` + "Entity not found" pairing as `_issue_or_none`.
            if _is_entity_not_found(exc):
                raise IssueBackendError(f"Linear issue {issue_id!r} not found") from exc
            raise
        issue = data.get("issue")
        if issue is None:
            raise IssueBackendError(f"Linear issue {issue_id!r} not found")
        uuid = _require_str(_require_dict(issue, "issue").get("id"), "issue id")
        self._uuid_cache[issue_id] = uuid
        return uuid

    def _comments(self, issue_id: str) -> list[dict[str, object]]:
        """All comments on an issue, sorted ascending by ``createdAt`` — pins GitHub's
        oldest-first first-match semantics without depending on Linear's connection ordering."""
        query = (
            "query($id: String!, $cursor: String) { issue(id: $id) "
            f"{{ comments(first: {_PAGE_SIZE}, after: $cursor) "
            "{ nodes { id body createdAt } pageInfo { hasNextPage endCursor } } } }"
        )
        nodes = self._paginate(query, {"id": issue_id}, "issue", "comments")
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
                "teamId": self._team_id(),
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
        return self._paginate(query, {"teamId": self._team_id(), "label": label}, "issues")

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
                self._uuid_cache[identifier] = _require_str(node.get("id"), "issue id")
                return issue_backend.IssueRef(
                    id=identifier,
                    url=_require_str(node.get("url"), "issue url"),
                    existed=True,
                )
        return None

    def _create_issue(
        self, *, title: str, description: str, label_id: str
    ) -> issue_backend.IssueRef:
        mutation = (
            "mutation($input: IssueCreateInput!) { issueCreate(input: $input) "
            "{ success issue { id identifier url } } }"
        )
        variables: dict[str, object] = {
            "input": {
                "teamId": self._team_id(),
                "title": title,
                "description": description,
                "labelIds": [label_id],
            }
        }
        data = self._client.request(mutation, variables)
        payload = _require_dict(data.get("issueCreate"), "issueCreate")
        if payload.get("success") is not True:
            raise IssueBackendError(f"failed to create Linear issue {title!r}")
        issue = _require_dict(payload.get("issue"), "issueCreate.issue")
        identifier = _require_str(issue.get("identifier"), "issue identifier")
        self._uuid_cache[identifier] = _require_str(issue.get("id"), "issue id")
        return issue_backend.IssueRef(
            id=identifier,
            url=_require_str(issue.get("url"), "issue url"),
            existed=False,
        )

    def _update_issue(self, issue_id: str, fields: dict[str, object], *, what: str) -> None:
        mutation = (
            "mutation($id: String!, $input: IssueUpdateInput!) "
            "{ issueUpdate(id: $id, input: $input) { success } }"
        )
        data = self._client.request(mutation, {"id": self._uuid_for(issue_id), "input": fields})
        payload = _require_dict(data.get("issueUpdate"), "issueUpdate")
        if payload.get("success") is not True:
            raise IssueBackendError(f"failed to {what} on Linear issue {issue_id!r}")

    def _create_comment(self, issue_id: str, body: str) -> None:
        """Post a comment. ``body`` is already Linear-encoded (callers transcode once)."""
        mutation = (
            "mutation($input: CommentCreateInput!) { commentCreate(input: $input) { success } }"
        )
        variables: dict[str, object] = {
            "input": {"issueId": self._uuid_for(issue_id), "body": body}
        }
        data = self._client.request(mutation, variables)
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
        variables: dict[str, object] = {
            "input": {"issueId": self._uuid_for(issue_id), "body": body}
        }
        data = self._client.request(mutation, variables)
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

    # ------------------------------------------------------------------ labels

    def ensure_label(
        self, name: str, *, color: str, description: str, dry_run: bool = False
    ) -> issue_backend.Label:
        if dry_run:
            return issue_backend.Label(name=name, created=False)
        _, created = self._ensure_label_id(name, color=color, description=description)
        return issue_backend.Label(name=name, created=created)

    # ------------------------------------------------------------------ plan issues

    def find_plan_issue(self, *, run_id: str) -> issue_backend.IssueRef | None:
        return self._find_issue_by_run_id(
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
        label_id, _ = self._ensure_label_id(
            plan.PLAN_LABEL,
            color=plan.PLAN_LABEL_COLOR,
            description=plan.PLAN_LABEL_DESCRIPTION,
        )
        return self._create_issue(
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
        for comment in self._comments(issue_id):
            comment_body = comment.get("body")
            if isinstance(comment_body, str) and plan.extract_plan_body(comment_body) is not None:
                comment_id = _require_str(comment.get("id"), "comment id")
                break
        if comment_id is not None:
            self._update_comment(comment_id, transcoded)
            body_updated = True
        else:
            self._create_comment(issue_id, transcoded)
            body_updated = False
        self._update_issue(issue_id, {"title": title}, what="update title")
        return issue_backend.PlanUpdate(
            issue_id=issue_id, body_updated=body_updated, title_updated=True, dry_run=False
        )

    def update_plan_header(
        self, *, issue_id: str, fields: dict[str, object], dry_run: bool = False
    ) -> issue_backend.PlanHeaderUpdate:
        unknown = set(fields) - plan.PLAN_HEADER_FIELDS
        if unknown:
            raise IssueBackendError(f"unknown plan-header field(s): {sorted(unknown)}")
        issue = self._get_issue(issue_id, "id description")
        description = issue.get("description")
        body = description if isinstance(description, str) else ""
        header = plan.find_metadata_block(body, plan.PLAN_HEADER_KEY) or {}
        new_body = plan.replace_metadata_block(body, plan.PLAN_HEADER_KEY, {**header, **fields})
        if dry_run:
            return issue_backend.PlanHeaderUpdate(fields_updated=tuple(fields), dry_run=True)
        self._update_issue(issue_id, {"description": new_body}, what="update plan-header")
        return issue_backend.PlanHeaderUpdate(fields_updated=tuple(fields), dry_run=False)

    def get_plan(self, *, issue_id: str) -> issue_backend.PlanState | None:
        issue = self._issue_or_none(issue_id, "id identifier url title description state { type }")
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
            return github.get_pr(number=number, repo_root=self._repo_root)
        except GitHubError as exc:
            raise IssueBackendError(str(exc)) from exc

    def get_plan_body(self, *, issue_id: str) -> str | None:
        issue = self._issue_or_none(issue_id, "id description")
        if issue is None:
            return None
        description = issue.get("description")
        candidates = [description if isinstance(description, str) else ""]
        candidates.extend(
            comment_body
            for comment in self._comments(issue_id)
            if isinstance(comment_body := comment.get("body"), str)
        )
        for text in candidates:
            body = plan.extract_plan_body(text)
            if body:
                return body
        return None

    # ------------------------------------------------------------------ learn issues

    def find_learn_issue(self, *, run_id: str) -> issue_backend.IssueRef | None:
        return self._find_issue_by_run_id(
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
        label_id, _ = self._ensure_label_id(
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
        return self._create_issue(title=title, description=full_body, label_id=label_id)

    def list_learn_issues(self) -> tuple[issue_backend.LearnIssueSummary, ...]:
        summaries: list[issue_backend.LearnIssueSummary] = []
        selection = "id identifier title url description"
        for node in self._list_label_issues(plan.LEARN_LABEL, selection):
            description = node.get("description")
            identifier = _require_str(node.get("identifier"), "issue identifier")
            self._uuid_cache[identifier] = _require_str(node.get("id"), "issue id")
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
        label_id, _ = self._ensure_label_id(
            plan.CONSOLIDATED_LABEL,
            color=plan.CONSOLIDATED_LABEL_COLOR,
            description=plan.CONSOLIDATED_LABEL_DESCRIPTION,
        )
        # Additive labelling: read the existing label ids, union in the consolidated label
        # (issueUpdate's labelIds REPLACES the set — never write it without the existing ids).
        issue = self._get_issue(issue_id, "id labels { nodes { id } }")
        labels = _require_dict(issue.get("labels"), "issue.labels")
        existing = [
            _require_str(_require_dict(raw, "label").get("id"), "label id")
            for raw in _require_list(labels.get("nodes"), "issue.labels.nodes")
        ]
        label_ids = existing if label_id in existing else [*existing, label_id]
        self._update_issue(issue_id, {"labelIds": label_ids}, what="label consolidated")
        self._update_issue(issue_id, {"stateId": self._done_state_id()}, what="close")
        return True

    # ------------------------------------------------------------------ generic issue ops

    def close_issue(self, *, issue_id: str, dry_run: bool = False) -> bool:
        if dry_run:
            return False
        self._update_issue(issue_id, {"stateId": self._done_state_id()}, what="close")
        return True

    def add_issue_comment(
        self, *, issue_id: str, body: str, dry_run: bool = False
    ) -> issue_backend.CommentResult:
        if dry_run:
            return issue_backend.CommentResult(posted=False)
        self._create_comment(issue_id, to_linear_markdown(body))
        return issue_backend.CommentResult(posted=True)

    def find_comment_id_by_marker(self, *, issue_id: str, marker: str) -> str | None:
        # The incoming marker is GitHub-encoded (e.g. the run-report HTML comment); transcode it
        # so it matches the transcoded comment this backend previously wrote.
        needle = to_linear_markdown(marker)
        for comment in self._comments(issue_id):
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
            self._update_comment(comment_id, transcoded)
        else:
            self._create_comment(issue_id, transcoded)
        return issue_backend.CommentResult(posted=True)

    # ------------------------------------------------------------------ objective issues
    # The GitHub-twin objective tier (Node 2.3): two-step create + comment-id backfill, header
    # LBYL, authoritative roadmap writes with best-effort comment re-renders, the Reconcilable
    # splice. Issue descriptions are composed directly in the inline-code style; comment bodies
    # are transcoded (the rendered markers come from `objective.py`'s HTML constants).

    def find_objective_issue(self, *, run_id: str) -> issue_backend.IssueRef | None:
        return self._find_issue_by_run_id(
            label=objective.OBJECTIVE_LABEL,
            header_key=objective.OBJECTIVE_HEADER_KEY,
            run_id=run_id,
        )

    def create_objective_issue(
        self,
        *,
        title: str,
        body: str,
        run_id: str,
        status: str = "active",
        roadmap_nodes: list[objective.ObjectiveNode] | None = None,
        dry_run: bool = False,
    ) -> issue_backend.IssueRef:
        if dry_run:
            return issue_backend.IssueRef(id="0", url="(dry-run)", existed=False)
        existing = self.find_objective_issue(run_id=run_id)
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

        label_id, _ = self._ensure_label_id(
            objective.OBJECTIVE_LABEL,
            color=objective.OBJECTIVE_LABEL_COLOR,
            description=objective.OBJECTIVE_LABEL_DESCRIPTION,
        )

        # Composed directly in the inline-code style (no transcoding needed — the
        # `create_learn_issue` precedent).
        header = objective.ObjectiveHeader(
            run_id=run_id, created=plan.now_iso(), objective_comment_id=None, status=status
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

        created = self._create_issue(title=title, description=issue_body, label_id=label_id)

        # The body comment: rendered with the HTML markers (objective.py's constants), then
        # transcoded to the inline-code sentinels.
        comment_body = to_linear_markdown(objective.render_body_comment(nodes, prose=body.strip()))
        comment_id = self._create_comment_with_id(created.id, comment_body)
        self.update_objective_header(
            issue_id=created.id, fields={"objective_comment_id": comment_id}
        )
        return created

    def get_objective(self, *, issue_id: str) -> issue_backend.ObjectiveState | None:
        issue = self._issue_or_none(issue_id, "id identifier url title description")
        if issue is None:
            return None
        description = issue.get("description")
        body = description if isinstance(description, str) else ""
        header = plan.find_metadata_block(body, objective.OBJECTIVE_HEADER_KEY) or {}
        nodes, errors = objective.parse_roadmap_nodes(body)
        if errors:
            raise IssueBackendError(
                f"invalid objective roadmap on {issue_id!r}: " + "; ".join(errors)
            )
        return issue_backend.ObjectiveState(
            id=_require_str(issue.get("identifier"), "issue identifier"),
            url=_require_str(issue.get("url"), "issue url"),
            title=_require_str(issue.get("title"), "issue title"),
            header=header,
            nodes=tuple(nodes),
        )

    def update_objective_header(
        self, *, issue_id: str, fields: dict[str, object], dry_run: bool = False
    ) -> issue_backend.ObjectiveHeaderUpdate:
        unknown = set(fields) - objective.OBJECTIVE_HEADER_FIELDS
        if unknown:
            raise IssueBackendError(f"unknown objective-header field(s): {sorted(unknown)}")
        issue = self._get_issue(issue_id, "id description")
        description = issue.get("description")
        body = description if isinstance(description, str) else ""
        header = plan.find_metadata_block(body, objective.OBJECTIVE_HEADER_KEY) or {}
        # Form-preserving merge: replace_metadata_block keeps the inline-code form on Linear
        # bodies.
        new_body = plan.replace_metadata_block(
            body, objective.OBJECTIVE_HEADER_KEY, {**header, **fields}
        )
        if dry_run:
            return issue_backend.ObjectiveHeaderUpdate(fields_updated=tuple(fields), dry_run=True)
        self._update_issue(issue_id, {"description": new_body}, what="update objective-header")
        return issue_backend.ObjectiveHeaderUpdate(fields_updated=tuple(fields), dry_run=False)

    def update_objective_node(
        self,
        *,
        issue_id: str,
        node_id: str,
        status: objective.NodeStatus | None = None,
        pr: str | None = None,
        description: str | None = None,
        dry_run: bool = False,
    ) -> issue_backend.ObjectiveNodeUpdate:
        issue = self._get_issue(issue_id, "id description")
        raw_description = issue.get("description")
        body = raw_description if isinstance(raw_description, str) else ""
        nodes, errors = objective.parse_roadmap_nodes(body)
        if errors:
            raise IssueBackendError("invalid objective roadmap: " + "; ".join(errors))
        updated = objective.update_node(
            nodes, node_id, status=status, pr=pr, description=description
        )
        if updated is None:
            raise IssueBackendError(f"objective node {node_id!r} not found on {issue_id!r}")
        if dry_run:
            return issue_backend.ObjectiveNodeUpdate(
                issue_id=issue_id, node_id=node_id, comment_updated=False, dry_run=True
            )

        # Authoritative write: the roadmap block in the issue description (form-preserving).
        new_body = plan.replace_metadata_block(
            body, objective.OBJECTIVE_ROADMAP_KEY, objective.render_roadmap_block(updated)
        )
        self._update_issue(issue_id, {"description": new_body}, what="update objective roadmap")

        # Best-effort comment table re-render (the frontmatter is the source of truth): any
        # miss along the chain leaves comment_updated=False.
        comment_updated = False
        header = plan.find_metadata_block(new_body, objective.OBJECTIVE_HEADER_KEY) or {}
        comment_id = header.get("objective_comment_id")
        # Linear stores its string UUID; tolerate an int for symmetry with GitHub's numeric id.
        if isinstance(comment_id, str | int) and str(comment_id).strip():
            comment_body = self._comment_body_or_none(str(comment_id))
            if comment_body is not None:
                rerendered = objective.rerender_body_table(comment_body, updated)
                if rerendered is not None:
                    self._update_comment(str(comment_id), rerendered)
                    comment_updated = True
        return issue_backend.ObjectiveNodeUpdate(
            issue_id=issue_id, node_id=node_id, comment_updated=comment_updated, dry_run=False
        )

    def update_objective_body(
        self, *, issue_id: str, prose: str, dry_run: bool = False
    ) -> issue_backend.ObjectiveBodyUpdate:
        issue = self._get_issue(issue_id, "id description")
        raw_description = issue.get("description")
        body = raw_description if isinstance(raw_description, str) else ""
        header = plan.find_metadata_block(body, objective.OBJECTIVE_HEADER_KEY) or {}
        comment_id = header.get("objective_comment_id")
        if not isinstance(comment_id, str | int) or not str(comment_id).strip():
            raise IssueBackendError(f"objective {issue_id!r} has no body comment")
        comment_key = str(comment_id)
        comment_body = self._comment_body_or_none(comment_key)
        if comment_body is None:
            raise IssueBackendError(f"objective {issue_id!r} has no body comment")
        # Transcode the prose on the way in — reconciled prose is caller-authored markdown and
        # may legitimately carry perk markers (identity for plain text).
        spliced = objective.replace_reconcilable_section(comment_body, to_linear_markdown(prose))
        if spliced is None:
            raise IssueBackendError(
                f"objective {issue_id!r} body comment has no reconcilable region"
            )
        if dry_run:
            return issue_backend.ObjectiveBodyUpdate(
                issue_id=issue_id, comment_id=comment_key, updated=False, dry_run=True
            )
        self._update_comment(comment_key, spliced)
        return issue_backend.ObjectiveBodyUpdate(
            issue_id=issue_id, comment_id=comment_key, updated=True, dry_run=False
        )


# ===========================================================================
# Shared readiness probe (Node 2.4) — used by both `perk init` and `perk doctor`.
# Report-shaped (never raises): every failure mode lands in a `LinearReadiness` field,
# mirroring `github.check_auth`'s degrade discipline. Offline-testable through the
# `GraphQLClient` protocol fake.
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


def check_readiness(
    client: GraphQLClient, *, team_key: str, ensure_labels: bool
) -> LinearReadiness:
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

    # --- team: resolve the team UUID (reuses the backend's `_team_id`) ---
    backend = LinearIssueBackend(client, team_key=team_key, repo_root=Path())
    try:
        backend._team_id()
    except IssueBackendError as exc:
        return LinearReadiness(auth_ok=True, user=user, team_ok=False, error=str(exc))

    # --- labels: the four perk labels ---
    missing: list[str] = []
    created: list[str] = []
    try:
        for name, color, description in _PERK_LABELS:
            if ensure_labels:
                _, was_created = backend._ensure_label_id(
                    name, color=color, description=description
                )
                if was_created:
                    created.append(name)
            elif backend._lookup_label_id(name) is None:
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
