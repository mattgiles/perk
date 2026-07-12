"""Shared scripted-fake substrate for the `test_linear_*` suite.

The scripted `_FakeLinear` (response-keyed, distinct from the stateful `FakeLinearWorkspace`
in `test_linear_lifecycle.py`) plus the response constants/builders, cross-tier assert helpers,
the issue/store conformance constructors, and the not-found / milestone builders shared across
≥2 split files. Leading underscore so pytest does not collect this module.
"""

import json
from pathlib import Path
from typing import cast

from perk import plan
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


def _inline_plan_description(run_id: str) -> str:
    return plan.render_metadata_block(
        plan.PLAN_HEADER_KEY, {"run_id": run_id, "created": "t"}, style="inline-code"
    )


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
