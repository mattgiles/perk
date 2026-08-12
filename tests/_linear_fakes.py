"""Shared fake substrate for the `test_linear_*` suite — both fake styles.

The scripted `_FakeLinear` (response-keyed: each test scripts exact wire responses) plus the
response constants/builders, cross-tier assert helpers, the issue/store conformance
constructors, and the not-found / milestone builders shared across ≥2 split files; AND the
stateful `FakeLinearWorkspace` (an in-memory Linear workspace executing mutations against
state — the lifecycle/journal/transfer suites' substrate). Leading underscore so pytest does
not collect this module.
"""

import itertools
import json
import uuid
from pathlib import Path
from typing import cast

from perk.backends import issue_backend, objective_store
from perk.backends.linear import LinearIssueBackend, LinearObjectiveStore
from perk.backends.linear import attachments as linear_attachments
from perk.backends.linear.client import LinearClient, LinearGraphQLError

_TEAM_RESPONSE: dict[str, object] = {"teams": {"nodes": [{"id": "team-1"}]}}
_STATES_RESPONSE: dict[str, object] = {
    "team": {
        "states": {
            "nodes": [
                {"id": "state-later", "name": "Archived", "type": "completed", "position": 9},
                {"id": "state-done", "name": "Done", "type": "completed", "position": 3},
                {"id": "state-todo", "name": "Todo", "type": "unstarted", "position": 1},
            ]
        }
    }
}
_LABEL_FOUND: dict[str, object] = {"issueLabels": {"nodes": [{"id": "lbl-1"}]}}
_LABEL_ABSENT: dict[str, object] = {"issueLabels": {"nodes": []}}


def _page(nodes: list[dict[str, object]], *, has_next: bool = False, cursor: str | None = None):
    return {"nodes": nodes, "pageInfo": {"hasNextPage": has_next, "endCursor": cursor}}


def _no_issues() -> dict[str, object]:
    return {"issues": _page([])}


class _FakeLinear(LinearClient):
    """A scripted ``LinearClient`` subclass: records every ``(query, variables)`` pair; responses
    keyed by query-substring match in insertion order. A queue with >1 entries pops per call (the
    last entry is then reused); an ``Exception`` entry is raised. Subclasses ``LinearClient`` (no
    ``super().__init__``) so it INHERITS the real ``team_id``/``paginate`` machinery driven by this
    scripted ``request`` — the team cache is initialized directly."""

    def __init__(self, responses: dict[str, list[object]] | None = None) -> None:
        self.requests: list[tuple[str, dict[str, object]]] = []
        self._responses = {key: list(queue) for key, queue in (responses or {}).items()}
        self._team_id_cache: dict[str, str] = {}
        # Pre-seeded so `viewer_id()` resolves without a scripted `viewer` arm on every
        # issue/project create (the request path is covered by `test_linear.py` against a
        # MockTransport and by the stateful `FakeLinearWorkspace`). `assigneeId`/`leadId`
        # assertions use this sentinel.
        self._viewer_id_cache: str | None = "viewer-1"

    def request(self, query: str, variables: dict[str, object] | None = None) -> dict[str, object]:
        self.requests.append((query, variables or {}))
        for needle, queue in self._responses.items():
            if needle in query:
                value = queue.pop(0) if len(queue) > 1 else queue[0]
                if isinstance(value, Exception):
                    raise value
                assert isinstance(value, dict)
                return cast("dict[str, object]", value)
        raise AssertionError(f"unscripted Linear query: {query}")


def _make_backend(
    responses: dict[str, list[object]] | None = None,
) -> tuple[issue_backend.IssueBackend, _FakeLinear]:
    """The static conformance check: ty verifies the backend satisfies the protocol."""
    fake = _FakeLinear(responses)
    backend: issue_backend.IssueBackend = LinearIssueBackend(
        fake, team_key="ENG", repo_root=Path("/repo")
    )
    return backend, fake


def _make_store(
    responses: dict[str, list[object]] | None = None,
) -> tuple[objective_store.ObjectiveStore, _FakeLinear]:
    """The objective-tier twin of ``_make_backend``: ty verifies ``LinearObjectiveStore`` satisfies
    the ``ObjectiveStore`` protocol."""
    fake = _FakeLinear(responses)
    store: objective_store.ObjectiveStore = LinearObjectiveStore(
        fake, team_key="ENG", repo_root=Path("/repo")
    )
    return store, fake


def _queries(fake: _FakeLinear, needle: str) -> list[tuple[str, dict[str, object]]]:
    return [(q, v) for q, v in fake.requests if needle in q]


def _input_payload(variables: dict[str, object]) -> dict[str, object]:
    payload = variables["input"]
    assert isinstance(payload, dict)
    return cast("dict[str, object]", payload)


def _perk_attachment_node(
    kind: str, fields: dict[str, object], *, url: str, att_id: str = "att-1"
) -> dict[str, object]:
    """A wire-shaped ``{id, url, metadata}`` attachment node carrying a perk envelope — built
    through the production encoder so fixtures track the envelope schema."""
    card = linear_attachments.encode(kind, fields)
    return {"id": att_id, "url": url, "metadata": card.metadata}


def _attachments_for_url_miss() -> dict[str, object]:
    return {"attachmentsForURL": {"nodes": []}}


def _attachments_for_url_hit(
    *,
    identifier: str,
    url: str,
    state_type: str = "unstarted",
    project: dict[str, object] | None = None,
) -> dict[str, object]:
    """An ``attachmentsForURL`` response whose first node's ``issue`` matches the production
    selection (identifier / url / state.type / project)."""
    return {
        "attachmentsForURL": {
            "nodes": [
                {
                    "issue": {
                        "identifier": identifier,
                        "url": url,
                        "state": {"type": state_type},
                        "project": project,
                    }
                }
            ]
        }
    }


def _attachment_create_ok() -> dict[str, object]:
    return {"attachmentCreate": {"success": True}}


def _att_creates(fake: "_FakeLinear") -> list[dict[str, object]]:
    """Every ``attachmentCreate`` input payload, in call order."""
    return [_input_payload(v) for _, v in _queries(fake, "attachmentCreate(")]


def _att_fields(att_input: dict[str, object]) -> dict[str, object]:
    """Decode an ``attachmentCreate`` input's envelope ``payload_json`` back to fields."""
    metadata = att_input["metadata"]
    assert isinstance(metadata, dict)
    payload_json = cast("dict[str, object]", metadata)["payload_json"]
    assert isinstance(payload_json, str)
    fields = json.loads(payload_json)
    assert isinstance(fields, dict)
    return cast("dict[str, object]", fields)


def _not_found_error() -> LinearGraphQLError:
    return LinearGraphQLError(
        "Linear GraphQL error: Entity not found: Issue", codes=("INPUT_ERROR",)
    )


def _project_not_found(entity: str = "Project") -> LinearGraphQLError:
    return LinearGraphQLError(
        f"Linear GraphQL error: Entity not found: {entity}", codes=("INPUT_ERROR",)
    )


def _milestone_create(mid: str) -> dict[str, object]:
    return {
        "projectMilestoneCreate": {
            "success": True,
            "projectMilestone": {"id": mid, "name": "Phase"},
        }
    }


_PAGE = 2  # deliberately tiny so the suite exercises the cursor loop on real data

_TEAM_KEY = "ENG"
_TEAM_UUID = "team-uuid-1"

_STATES: list[dict[str, object]] = [
    {"id": "st-todo", "name": "Todo", "type": "unstarted", "position": 0},
    {"id": "st-done", "name": "Done", "type": "completed", "position": 1},
    {"id": "st-canceled", "name": "Canceled", "type": "canceled", "position": 2},
]


def _not_found() -> LinearGraphQLError:
    return LinearGraphQLError(
        "Linear GraphQL error: Entity not found: Issue", codes=("INPUT_ERROR",)
    )


class FakeLinearWorkspace(LinearClient):
    """A stateful in-memory Linear workspace subclassing ``linear.LinearClient``.

    Routes requests by the same query-substring conventions the scripted ``_FakeLinear`` uses,
    but executes against state: create/update/comment/label mutations mutate it; reads paginate
    (page size ``_PAGE`` so the cursor loop runs). Unknown entity ids raise
    ``LinearGraphQLError("… Entity not found", codes=())`` — exercising the backend's documented
    ``"not found"``-substring tolerance. **Mutations accept the identifier OR the UUID** (the
    Mode 2 live finding, 2026-06-15: ``issueUpdate``/``commentCreate`` take the bare ``PER-<n>``
    identifier interchangeably with the UUID, same as the read path), so there is no
    identifier→UUID resolution layer to pin.
    """

    def __init__(self) -> None:
        self.issues: dict[str, dict[str, object]] = {}  # uuid -> issue
        self.labels: dict[str, str] = {}  # name -> uuid
        self.projects: dict[str, dict[str, object]] = {}  # uuid -> project
        self.milestones: dict[str, dict[str, object]] = {}  # uuid -> {id, name, project_id}
        self.relations: list[tuple[str, str]] = []  # (blocker_uuid, blocked_uuid)
        # idempotent-by-URL attachments: (issue_uuid, url) -> {id, title, subtitle, metadata}.
        # Re-creates REPLACE the record in place, keeping the same attachment id (the
        # live-verified upsert-by-(url, issueId) + REPLACE-metadata semantics).
        self.attachments: dict[tuple[str, str], dict[str, object]] = {}
        self.requests: list[tuple[str, dict[str, object]]] = []
        self._seq = itertools.count(1)
        self._clock = itertools.count(1)
        # Subclasses LinearClient (no super().__init__) to inherit the shared team_id/paginate
        # machinery driven by this scripted request; init the id caches directly.
        self._team_id_cache: dict[str, str] = {}
        self._viewer_id_cache: str | None = None

    # ------------------------------------------------------------------ state helpers

    def _issue_by_any_id(self, value: str) -> dict[str, object] | None:
        """Reads accept the identifier OR the UUID (the documented `issue(id:)` tolerance)."""
        found = self.issues.get(value)
        if found is not None:
            return found
        for issue in self.issues.values():
            if issue["identifier"] == value:
                return issue
        return None

    def _issue_for_mutation(self, value: str) -> dict[str, object]:
        """Mutations accept the identifier OR the UUID (the Mode 2 live finding) — junk is an
        unknown entity."""
        found = self._issue_by_any_id(value)
        if found is None:
            raise _not_found()
        return found

    def issue_by_identifier(self, identifier: str) -> dict[str, object]:
        found = self._issue_by_any_id(identifier)
        assert found is not None, f"no workspace issue {identifier!r}"
        return found

    def state_type(self, issue: dict[str, object]) -> str:
        state_id = issue["state_id"]
        return str(next(s["type"] for s in _STATES if s["id"] == state_id))

    def label_names(self, issue: dict[str, object]) -> set[str]:
        ids = cast("list[str]", issue["label_ids"])
        return {name for name, label_id in self.labels.items() if label_id in ids}

    def attachments_of(self, issue: dict[str, object]) -> list[dict[str, object]]:
        """Attachment cards on an issue (by its UUID)."""
        return [v for (iid, _url), v in self.attachments.items() if iid == issue["id"]]

    def attachment_nodes_of(self, issue: dict[str, object]) -> list[dict[str, object]]:
        """The wire-shaped ``{id, url, metadata}`` attachment nodes on an issue."""
        return [
            {"id": v["id"], "url": url, "metadata": v.get("metadata")}
            for (iid, url), v in self.attachments.items()
            if iid == issue["id"]
        ]

    def delete_issue(self, issue_uuid: str) -> None:
        """Delete an issue, cascading its relations AND attachments (Linear cascades both)."""
        del self.issues[issue_uuid]
        self.relations[:] = [(bk, bl) for bk, bl in self.relations if issue_uuid not in (bk, bl)]
        for key in [k for k in self.attachments if k[0] == issue_uuid]:
            del self.attachments[key]

    def comments_of(self, issue: dict[str, object]) -> list[dict[str, object]]:
        return cast("list[dict[str, object]]", issue["comments"])

    def add_foreign_comment(self, identifier: str, body: str) -> None:
        """Simulate a Linear GitHub-integration linkback comment (a foreign writer)."""
        issue = self.issue_by_identifier(identifier)
        self.comments_of(issue).append(
            {"id": f"cmt-{uuid.uuid4().hex[:8]}", "body": body, "createdAt": self._now()}
        )

    def _now(self) -> str:
        return f"2026-06-12T00:00:{next(self._clock):02d}Z"

    def _create_issue(self, payload: dict[str, object]) -> dict[str, object]:
        number = next(self._seq)
        identifier = f"{_TEAM_KEY}-{number}"
        issue: dict[str, object] = {
            "id": f"iss-{uuid.uuid4().hex[:8]}",
            "identifier": identifier,
            "url": f"https://linear.app/test/issue/{identifier}",
            "title": payload.get("title", ""),
            "description": payload.get("description", ""),
            "state_id": payload.get("stateId", "st-todo"),
            "label_ids": list(cast("list[str]", payload.get("labelIds", []))),
            # Every perk-created issue is assigned to the API-key user (the viewer).
            "assignee_id": payload.get("assigneeId"),
            # node-issues (project-backed objectives) carry a projectId; plan/learn issues None.
            "project_id": payload.get("projectId"),
            "milestone_id": payload.get("projectMilestoneId"),
            "comments": [],
        }
        self.issues[str(issue["id"])] = issue
        return issue

    # ------------------------------------------------------------------ project helpers

    def project_by_id(self, project_id: str) -> dict[str, object]:
        found = self.projects.get(project_id)
        assert found is not None, f"no workspace project {project_id!r}"
        return found

    def project_state(self, project_id: str) -> str:
        return str(self.project_by_id(project_id)["state"])

    def _milestone_node_of(self, issue: dict[str, object]) -> dict[str, object] | None:
        mid = issue.get("milestone_id")
        if mid is None:
            return None
        milestone = self.milestones.get(str(mid))
        return None if milestone is None else {"id": milestone["id"], "name": milestone["name"]}

    def _project_issue_node(
        self, issue: dict[str, object], *, with_milestone: bool = False
    ) -> dict[str, object]:
        node: dict[str, object] = {
            "id": issue["id"],
            "identifier": issue["identifier"],
            "url": issue["url"],
            "title": issue["title"],
            "description": issue["description"],
            "labels": {
                "nodes": [{"id": label_id} for label_id in cast("list[str]", issue["label_ids"])]
            },
            "attachments": {"nodes": self.attachment_nodes_of(issue)},
        }
        if with_milestone:
            node["projectMilestone"] = self._milestone_node_of(issue)
        return node

    # ------------------------------------------------------------------ wire shapes

    def _page_of(self, nodes: list[dict[str, object]], cursor: object) -> dict[str, object]:
        start = int(str(cursor)) if isinstance(cursor, str) and cursor else 0
        chunk = nodes[start : start + _PAGE]
        has_next = start + _PAGE < len(nodes)
        return {
            "nodes": chunk,
            "pageInfo": {"hasNextPage": has_next, "endCursor": str(start + _PAGE)},
        }

    def _issue_node(self, issue: dict[str, object]) -> dict[str, object]:
        """Every field any production selection reads (extra keys are harmless)."""
        return {
            "id": issue["id"],
            "identifier": issue["identifier"],
            "url": issue["url"],
            "title": issue["title"],
            "description": issue["description"],
            "state": {"type": self.state_type(issue)},
            "labels": {"nodes": [{"id": i} for i in cast("list[str]", issue["label_ids"])]},
            "attachments": {"nodes": self.attachment_nodes_of(issue)},
        }

    # ------------------------------------------------------------------ the client seam

    def request(self, query: str, variables: dict[str, object] | None = None) -> dict[str, object]:
        v = variables or {}
        self.requests.append((query, v))
        if "viewer" in query:
            return {"viewer": {"id": "u1", "name": "Fake User", "email": "f@x.io"}}
        if "teams(filter" in query:
            if v.get("key") == _TEAM_KEY:
                return {"teams": {"nodes": [{"id": _TEAM_UUID}]}}
            return {"teams": {"nodes": []}}
        if "projects(first" in query:  # team's project list (find_objective scan) — before team(id
            assert v.get("teamId") == _TEAM_UUID
            nodes = [
                {"id": p["id"], "url": p["url"], "name": p.get("name"), "content": p["content"]}
                for p in self.projects.values()
            ]
            return {"team": {"projects": self._page_of(nodes, v.get("cursor"))}}
        if "team(id" in query:
            assert v.get("teamId") == _TEAM_UUID
            return {"team": {"states": {"nodes": list(_STATES)}}}
        if "project(id" in query:  # project reads — before the generic issues(first/issue(id arms
            project = self.projects.get(str(v.get("id", "")))
            if project is None:
                raise _not_found()
            if "issues(first" in query:
                with_milestone = "projectMilestone" in query
                nodes = [
                    self._project_issue_node(issue, with_milestone=with_milestone)
                    for issue in self.issues.values()
                    if issue.get("project_id") == project["id"]
                ]
                return {"project": {"issues": self._page_of(nodes, v.get("cursor"))}}
            if "projectMilestones" in query:
                nodes = [
                    {"id": m["id"], "name": m["name"]}
                    for m in self.milestones.values()
                    if m["project_id"] == project["id"]
                ]
                return {"project": {"projectMilestones": self._page_of(nodes, v.get("cursor"))}}
            return {
                "project": {
                    "id": project["id"],
                    "url": project["url"],
                    "name": project["name"],
                    "content": project["content"],
                    "state": project["state"],
                }
            }
        if "issueLabels(filter" in query:
            label_id = self.labels.get(str(v.get("name")))
            return {"issueLabels": {"nodes": [{"id": label_id}] if label_id else []}}
        if "issueLabelCreate(" in query:
            payload = cast("dict[str, object]", v["input"])
            name = str(payload["name"])
            if name in self.labels:
                raise LinearGraphQLError("Linear GraphQL error: duplicate label name", codes=())
            label_id = f"lbl-{uuid.uuid4().hex[:8]}"
            self.labels[name] = label_id
            return {"issueLabelCreate": {"success": True, "issueLabel": {"id": label_id}}}
        if "issues(first" in query:
            assert v.get("teamId") == _TEAM_UUID
            label_id = self.labels.get(str(v.get("label")))
            nodes = [
                self._issue_node(issue)
                for issue in self.issues.values()
                if label_id is not None
                and label_id in cast("list[str]", issue["label_ids"])
                and self.state_type(issue) not in ("completed", "canceled")
            ]
            return {"issues": self._page_of(nodes, v.get("cursor"))}
        if "comments(first" in query:  # before the generic issue(id arm — same prefix
            issue = self._issue_by_any_id(str(v.get("id", "")))
            if issue is None:
                raise _not_found()
            return {"issue": {"comments": self._page_of(self.comments_of(issue), v.get("cursor"))}}
        if "comment(id" in query:
            for issue in self.issues.values():
                for comment in self.comments_of(issue):
                    if comment["id"] == v.get("id"):
                        return {"comment": {"body": comment["body"]}}
            raise _not_found()
        if "inverseRelations(" in query:  # blockers of this issue (depends_on sources)
            issue = self._issue_by_any_id(str(v.get("id", "")))
            if issue is None:
                raise _not_found()
            blockers: list[dict[str, object]] = [
                {"type": "blocks", "issue": {"identifier": self.issues[bk]["identifier"]}}
                for bk, bl in self.relations
                if bl == issue["id"]
            ]
            return {"issue": {"inverseRelations": self._page_of(blockers, v.get("cursor"))}}
        if "relations(" in query:  # issues this one blocks
            issue = self._issue_by_any_id(str(v.get("id", "")))
            if issue is None:
                raise _not_found()
            blocked: list[dict[str, object]] = [
                {"type": "blocks", "relatedIssue": {"identifier": self.issues[bl]["identifier"]}}
                for bk, bl in self.relations
                if bk == issue["id"]
            ]
            return {"issue": {"relations": self._page_of(blocked, v.get("cursor"))}}
        if "issue(id" in query:
            issue = self._issue_by_any_id(str(v.get("id", "")))
            if issue is None:
                raise _not_found()
            return {"issue": self._issue_node(issue)}
        if "issueCreate(" in query:
            payload = cast("dict[str, object]", v["input"])
            assert payload.get("teamId") == _TEAM_UUID
            issue = self._create_issue(payload)
            return {
                "issueCreate": {
                    "success": True,
                    "issue": {
                        "id": issue["id"],
                        "identifier": issue["identifier"],
                        "url": issue["url"],
                    },
                }
            }
        if "issueUpdate(" in query:
            issue = self._issue_for_mutation(str(v.get("id", "")))
            payload = cast("dict[str, object]", v["input"])
            if "title" in payload:
                issue["title"] = payload["title"]
            if "description" in payload:
                issue["description"] = payload["description"]
            if "labelIds" in payload:
                issue["label_ids"] = list(cast("list[str]", payload["labelIds"]))
            if "stateId" in payload:
                issue["state_id"] = payload["stateId"]
            if "projectMilestoneId" in payload:
                issue["milestone_id"] = payload["projectMilestoneId"]
            if "projectId" in payload:
                issue["project_id"] = payload["projectId"]
            return {"issueUpdate": {"success": True}}
        if "commentCreate(" in query:
            payload = cast("dict[str, object]", v["input"])
            issue = self._issue_for_mutation(str(payload.get("issueId", "")))
            comment = {
                "id": f"cmt-{uuid.uuid4().hex[:8]}",
                "body": payload["body"],
                "createdAt": self._now(),
            }
            self.comments_of(issue).append(comment)
            return {"commentCreate": {"success": True, "comment": {"id": comment["id"]}}}
        if "commentUpdate(" in query:
            for issue in self.issues.values():
                for comment in self.comments_of(issue):
                    if comment["id"] == v.get("id"):
                        payload = cast("dict[str, object]", v["input"])
                        comment["body"] = payload["body"]
                        return {"commentUpdate": {"success": True}}
            raise _not_found()
        if "projectCreate(" in query:
            payload = cast("dict[str, object]", v["input"])
            assert payload.get("teamIds") == [_TEAM_UUID]
            pid = f"proj-{uuid.uuid4().hex[:8]}"
            project: dict[str, object] = {
                "id": pid,
                "url": f"https://linear.app/test/project/{pid}",
                "name": payload.get("name", ""),
                "content": payload.get("content", ""),
                # Default "planned": create sets no live state; the started nudge moves it on work.
                "state": "planned",
                "lead_id": payload.get("leadId"),
                "start_date": payload.get("startDate"),
            }
            self.projects[pid] = project
            return {
                "projectCreate": {
                    "success": True,
                    "project": {"id": pid, "url": project["url"]},
                }
            }
        if "projectUpdate(" in query:
            project = self.project_by_id(str(v.get("id", "")))
            payload = cast("dict[str, object]", v["input"])
            if "content" in payload:
                project["content"] = payload["content"]
            if "state" in payload:
                project["state"] = payload["state"]
            return {"projectUpdate": {"success": True}}
        if "projectUpdateCreate(" in query:
            payload = cast("dict[str, object]", v["input"])
            self.project_by_id(str(payload.get("projectId", "")))  # entity check
            uid = f"pu-{uuid.uuid4().hex[:8]}"
            return {"projectUpdateCreate": {"success": True, "projectUpdate": {"id": uid}}}
        if "projectMilestoneCreate(" in query:
            payload = cast("dict[str, object]", v["input"])
            mid = f"ms-{uuid.uuid4().hex[:8]}"
            self.milestones[mid] = {
                "id": mid,
                "name": payload.get("name", ""),
                "project_id": payload.get("projectId"),
            }
            return {
                "projectMilestoneCreate": {
                    "success": True,
                    "projectMilestone": {"id": mid, "name": payload.get("name", "")},
                }
            }
        if "attachmentsForURL(" in query:
            url = str(v.get("url", ""))
            hits: list[dict[str, object]] = []
            for (iid, att_url), _value in self.attachments.items():
                if att_url != url:  # exact match only
                    continue
                issue = self.issues.get(iid)
                if issue is None:
                    continue
                project = self.projects.get(str(issue.get("project_id") or ""))
                hits.append(
                    {
                        "issue": {
                            "identifier": issue["identifier"],
                            "url": issue["url"],
                            "state": {"type": self.state_type(issue)},
                            "project": None
                            if project is None
                            else {
                                "id": project["id"],
                                "url": project["url"],
                                "name": project["name"],
                            },
                        }
                    }
                )
            return {"attachmentsForURL": {"nodes": hits}}
        if "attachmentCreate(" in query:
            payload = cast("dict[str, object]", v["input"])
            issue = self._issue_for_mutation(str(payload.get("issueId", "")))
            key = (str(issue["id"]), str(payload["url"]))  # idempotent by (issue, url)
            existing = self.attachments.get(key)
            # REPLACE-in-place semantics (live-verified): same id, whole record replaced.
            att_id = existing["id"] if existing is not None else f"att-{uuid.uuid4().hex[:8]}"
            self.attachments[key] = {
                "id": att_id,
                "title": payload.get("title"),
                "subtitle": payload.get("subtitle"),
                "metadata": payload.get("metadata"),
            }
            return {"attachmentCreate": {"success": True, "attachment": {"id": att_id}}}
        if "entityExternalLinkCreate(" in query:
            # Routed even though the caller is fail-open — the fake's unrouted AssertionError is
            # not in the fail-open catch set. Records the link on the project.
            payload = cast("dict[str, object]", v["input"])
            project = self.project_by_id(str(payload.get("projectId", "")))
            links = cast("list[dict[str, object]]", project.setdefault("external_links", []))
            links.append({"label": payload.get("label"), "url": payload.get("url")})
            return {"entityExternalLinkCreate": {"success": True}}
        if "issueRelationCreate(" in query:
            payload = cast("dict[str, object]", v["input"])
            blocker = str(payload["issueId"])
            blocked = str(payload["relatedIssueId"])
            # ids are issue UUIDs captured at issue-create time (issueRelationCreate is UUID-only)
            assert blocker in self.issues and blocked in self.issues
            rid = f"rel-{uuid.uuid4().hex[:8]}"
            self.relations.append((blocker, blocked))
            return {
                "issueRelationCreate": {
                    "success": True,
                    "issueRelation": {"id": rid, "type": "blocks"},
                }
            }
        raise AssertionError(f"unrouted Linear query: {query}")
