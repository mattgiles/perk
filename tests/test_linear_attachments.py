"""Unit coverage for the Linear attachment-metadata vocabulary (contracts.md §8.21): the URL
builders, the envelope encode/decode round-trip, foreign-attachment tolerance, and the
`_LinearIssueOps` attachment read/find/write extensions against the scripted fake."""

import json
from pathlib import Path
from typing import cast

import pytest
from _linear_fakes import _FakeLinear

from perk.backends.issue_backend import IssueBackendError
from perk.backends.linear import attachments
from perk.backends.linear.issue_ops import _LinearIssueOps

# --------------------------------------------------------------------------- URL builders


def test_url_builders() -> None:
    assert attachments.plan_header_url("01RUN") == "https://perk.invalid/plan/01RUN"
    assert attachments.learn_header_url("01RUN") == "https://perk.invalid/learn/01RUN"
    assert attachments.node_url("ENG-7") == "https://perk.invalid/node/ENG-7"
    assert attachments.objective_header_url("01OBJ") == "https://perk.invalid/objective/01OBJ"
    assert attachments.objective_manifest_url("01OBJ") == "https://perk.invalid/manifest/01OBJ"


def test_url_builders_accept_identifier_fallback_key() -> None:
    # a run-id-less plan keys its URL on the issue identifier (unique; never queried by finds)
    assert attachments.plan_header_url("ENG-3") == "https://perk.invalid/plan/ENG-3"


# --------------------------------------------------------------------------- encode


def test_encode_plan_header_card_and_envelope() -> None:
    fields: dict[str, object] = {
        "run_id": "01RUN",
        "created": "2026-07-12T00:00:00Z",
        "lifecycle_stage": "impl",
        "consumed_learn": ["ENG-2"],
        "pr": None,
    }
    card = attachments.encode(attachments.PLAN_HEADER_KIND, fields)
    assert card.title == "Perk plan"
    assert card.subtitle == "impl · created {created__since}"
    assert card.metadata["source"] == "perk"
    assert card.metadata["schema_version"] == 1
    assert card.metadata["kind"] == "plan-header"
    assert card.metadata["created"] == "2026-07-12T00:00:00Z"
    # payload_json round-trips the EXACT fields dict — lists and nulls verbatim
    assert json.loads(str(card.metadata["payload_json"])) == fields
    # attributes: non-null scalars only (the list + null are excluded), stringified
    attributes = card.metadata["attributes"]
    assert attributes == [
        {"name": "run_id", "value": "01RUN"},
        {"name": "created", "value": "2026-07-12T00:00:00Z"},
        {"name": "lifecycle_stage", "value": "impl"},
    ]


def test_encode_per_kind_cards() -> None:
    node = attachments.encode(attachments.OBJECTIVE_NODE_KIND, {"id": "1.2", "status": "pending"})
    assert node.title == "Perk node 1.2" and node.subtitle == "pending"
    learn = attachments.encode(attachments.LEARN_HEADER_KIND, {"run_id": "01L", "created": "t"})
    assert learn.title == "Perk learn" and learn.subtitle == "created {created__since}"
    obj = attachments.encode(
        attachments.OBJECTIVE_HEADER_KIND, {"run_id": "01O", "status": "active", "created": "t"}
    )
    assert obj.title == "Perk objective"
    assert obj.subtitle == "active · created {created__since}"
    manifest = attachments.encode(
        attachments.OBJECTIVE_MANIFEST_KIND, {"nodes": [{"id": "1.1"}], "phases": {"1": "Phase 1"}}
    )
    assert manifest.title == "Perk objective manifest" and manifest.subtitle == "1 node(s)"


def test_encode_unknown_kind_raises() -> None:
    with pytest.raises(IssueBackendError, match="unknown perk attachment kind"):
        attachments.encode("mystery", {})


def test_encode_omits_absent_optional_projections() -> None:
    card = attachments.encode(attachments.PLAN_HEADER_KIND, {"run_id": "01R"})
    assert card.subtitle is None
    assert "created" not in card.metadata


# --------------------------------------------------------------------------- decode


def _node(
    kind: str, fields: dict[str, object], *, url: str = "https://perk.invalid/x/1"
) -> dict[str, object]:
    return {"id": f"att-{kind}", "url": url, "metadata": attachments.encode(kind, fields).metadata}


def test_find_perk_attachment_round_trips_lists_and_nulls() -> None:
    fields: dict[str, object] = {
        "run_id": "01R",
        "pr": None,
        "consumed_learn": ["ENG-1", "ENG-2"],
        "nested": {"deep": [1, None]},
    }
    found = attachments.find_perk_attachment(
        [_node(attachments.PLAN_HEADER_KIND, fields)], kind=attachments.PLAN_HEADER_KIND
    )
    assert found is not None
    assert found.id == "att-plan-header"
    assert found.url == "https://perk.invalid/x/1"
    assert found.payload == fields


def test_find_perk_attachment_skips_foreign_and_other_kinds() -> None:
    nodes: list[dict[str, object]] = [
        {"id": "a1", "url": "https://github.com/x/pull/1", "metadata": {}},  # the PR card
        {"id": "a2", "url": "u2", "metadata": {"source": "sentry", "kind": "plan-header"}},
        {"id": "a3", "url": "u3"},  # no metadata at all
        _node(attachments.OBJECTIVE_NODE_KIND, {"id": "1.1", "status": "pending"}),
    ]
    assert attachments.find_perk_attachment(nodes, kind=attachments.PLAN_HEADER_KIND) is None
    node = attachments.find_perk_attachment(nodes, kind=attachments.OBJECTIVE_NODE_KIND)
    assert node is not None and node.payload["id"] == "1.1"


def test_find_perk_attachment_two_envelope_coexistence() -> None:
    # a unified node-issue carries BOTH a node and a plan envelope — `kind` disambiguates
    nodes = [
        _node(attachments.OBJECTIVE_NODE_KIND, {"id": "1.1", "status": "in_progress"}),
        _node(attachments.PLAN_HEADER_KIND, {"run_id": "01R"}),
    ]
    plan_att = attachments.find_perk_attachment(nodes, kind=attachments.PLAN_HEADER_KIND)
    node_att = attachments.find_perk_attachment(nodes, kind=attachments.OBJECTIVE_NODE_KIND)
    assert plan_att is not None and plan_att.payload == {"run_id": "01R"}
    assert node_att is not None and node_att.payload["status"] == "in_progress"


def test_find_perk_attachment_malformed_payload_fails_loud() -> None:
    bad: dict[str, object] = {
        "id": "a1",
        "url": "u1",
        "metadata": {"source": "perk", "kind": "plan-header", "payload_json": "{not json"},
    }
    with pytest.raises(IssueBackendError, match="invalid payload_json"):
        attachments.find_perk_attachment([bad], kind=attachments.PLAN_HEADER_KIND)
    missing: dict[str, object] = {
        "id": "a1",
        "url": "u1",
        "metadata": {"source": "perk", "kind": "plan-header"},
    }
    with pytest.raises(IssueBackendError, match="payload_json is not a string"):
        attachments.find_perk_attachment([missing], kind=attachments.PLAN_HEADER_KIND)
    non_object: dict[str, object] = {
        "id": "a1",
        "url": "u1",
        "metadata": {"source": "perk", "kind": "plan-header", "payload_json": "[1, 2]"},
    }
    with pytest.raises(IssueBackendError, match="payload is not an object"):
        attachments.find_perk_attachment([non_object], kind=attachments.PLAN_HEADER_KIND)


# --------------------------------------------------------------------------- ops extensions


def _ops(responses: dict[str, list[object]]) -> tuple[_LinearIssueOps, _FakeLinear]:
    fake = _FakeLinear(responses)
    return _LinearIssueOps(fake, team_key="ENG", repo_root=Path("/repo")), fake


def test_issue_attachments_reads_raw_nodes() -> None:
    ops, fake = _ops(
        {
            "issue(id": [
                {
                    "issue": {
                        "id": "iss-1",
                        "attachments": {
                            "nodes": [{"id": "att-1", "url": "u1", "metadata": {"k": "v"}}]
                        },
                    }
                }
            ]
        }
    )
    nodes = ops.issue_attachments("ENG-1")
    assert nodes == [{"id": "att-1", "url": "u1", "metadata": {"k": "v"}}]
    (query, variables) = fake.requests[0]
    assert "attachments(first: 50)" in query and variables == {"id": "ENG-1"}


def test_find_issue_by_attachment_url_hit_and_miss() -> None:
    issue = {
        "identifier": "ENG-9",
        "url": "https://linear.app/t/issue/ENG-9",
        "state": {"type": "started"},
        "project": None,
    }
    ops, fake = _ops(
        {
            "attachmentsForURL(": [
                {"attachmentsForURL": {"nodes": [{"issue": issue}]}},
                {"attachmentsForURL": {"nodes": []}},
            ]
        }
    )
    found = ops.find_issue_by_attachment_url("https://perk.invalid/plan/01R")
    assert found == issue
    assert ops.find_issue_by_attachment_url("https://perk.invalid/plan/other") is None
    assert fake.requests[0][1] == {"url": "https://perk.invalid/plan/01R"}


def test_create_attachment_metadata_is_conditional() -> None:
    ops, fake = _ops({"attachmentCreate(": [{"attachmentCreate": {"success": True}}]})
    # without metadata: input byte-identical to the PR-card call (no `metadata` key at all)
    ops.create_attachment("ENG-1", url="https://github.com/x/pull/1", title="PR")
    payload = fake.requests[0][1]["input"]
    assert isinstance(payload, dict) and "metadata" not in payload
    # with metadata: the envelope rides the input
    card = attachments.encode(attachments.PLAN_HEADER_KIND, {"run_id": "01R"})
    ops.create_attachment(
        "ENG-1",
        url=attachments.plan_header_url("01R"),
        title=card.title,
        subtitle=card.subtitle,
        metadata=card.metadata,
    )
    payload = fake.requests[1][1]["input"]
    assert isinstance(payload, dict)
    assert cast("dict[str, object]", payload)["metadata"] == card.metadata
