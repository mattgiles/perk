"""Backend-shape coverage for the dream-report companion + artifact (contracts.md §8.64).

GitHub (the ``tests/test_github_journal.py`` harness pattern): the carrier is the normalized
objective issue itself, parts land there as HTML-marker comments, and the publisher arm is the
no-op. Linear (the ``tests/test_linear_journal.py`` pattern): the carrier is the Project
metadata sentinel, the stored bodies carry the TRANSCODED inline-code marker (the real
``to_linear_markdown``), and the artifact publisher (``fileUpload`` → signed PUT → Resources
link) is driven both over the stateful ``FakeLinearWorkspace`` and over the REAL
``LinearClient`` HTTP paths via ``httpx.MockTransport`` (header propagation + per-boundary
failure injection).
"""

import json
import subprocess
from pathlib import Path
from typing import cast

import httpx
import pytest
from _github_fakes import ROOT, _has, _Proc
from _linear_fakes import FakeLinearWorkspace

from perk import objective, plan
from perk.backends.github.backend import GitHubIssueBackend
from perk.backends.github.objective_store import GitHubObjectiveStore
from perk.backends.issue_backend import IssueBackendError
from perk.backends.linear import (
    LinearDreamArtifactPublisher,
    LinearIssueBackend,
    LinearProjectObjectiveStore,
)
from perk.backends.linear.client import LinearClient
from perk.backends.resolve import NoOpDreamArtifactPublisher
from perk.learn import dream_companion as dc

_RUN = "01RUNAAAAAAAAAAAAAAAAAAAAA"


# --- GitHub: the objective issue IS the carrier -----------------------------------------------


def _objective_body() -> str:
    return plan.render_metadata_block(
        objective.OBJECTIVE_HEADER_KEY, {"run_id": "01RUN", "created": "t", "status": "active"}
    )


def _issue_view(number: int = 252) -> _Proc:
    return _Proc(
        0,
        json.dumps(
            {"number": number, "title": "obj", "body": _objective_body(), "url": f"u{number}"}
        ),
    )


def _comment_node(cid: str, body: str, created_at: str) -> dict[str, object]:
    return {
        "id": cid,
        "body": body,
        "createdAt": created_at,
        "lastEditedAt": None,
        "author": {"login": "perk-bot", "__typename": "Bot", "databaseId": 1},
    }


def _comments_payload(nodes: list[dict[str, object]]) -> str:
    return json.dumps(
        {
            "data": {
                "repository": {
                    "issue": {
                        "comments": {
                            "nodes": nodes,
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                        }
                    }
                }
            }
        }
    )


def test_github_parts_land_on_the_normalized_objective_issue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posted: list[str] = []

    def dispatch(args: list[str], **_: object) -> _Proc:
        gh = args[1:]
        if _has("issue", "view", "252")(gh):
            return _issue_view()
        if _has("repo", "view", "nameWithOwner")(gh):
            return _Proc(0, "octo/repo\n")
        if _has("issues/252/comments", "POST")(gh):
            for tok in gh:
                if tok.startswith("body=@"):
                    posted.append(Path(tok[len("body=@") :]).read_text(encoding="utf-8"))
            return _Proc(0, "{}")
        nodes = [
            _comment_node(f"IC_{i}", body, f"2026-03-01T00:00:{i:02d}Z")
            for i, body in enumerate(posted, start=1)
        ]
        return _Proc(0, _comments_payload(nodes))

    monkeypatch.setattr(subprocess, "run", dispatch)
    # The carrier is the objective issue itself, NORMALIZED (a canonical `#252` spelling feeds
    # the numeric issue-tier comment ops).
    carrier = GitHubObjectiveStore(ROOT).journal_carrier_id(objective_id="#252")
    assert carrier == "252"
    issues = GitHubIssueBackend(ROOT)
    dc.persist_parts(issues, carrier_id=carrier, run_id=_RUN, parts=["part one", "part two"])
    assert posted == [
        f"<!-- perk:learn-dream-report:{_RUN}:1 -->\n\npart one",
        f"<!-- perk:learn-dream-report:{_RUN}:2 -->\n\npart two",
    ]
    # The converging re-run posts nothing (the read-back scan finds both parts byte-identical).
    dc.persist_parts(issues, carrier_id=carrier, run_id=_RUN, parts=["part one", "part two"])
    assert len(posted) == 2


def test_github_publisher_arm_is_the_noop() -> None:
    publisher = NoOpDreamArtifactPublisher()
    assert publisher.publish(objective_id="252", run_id=_RUN, parts=["p"]) is None


# --- Linear: the sentinel carrier + the transcoded round trip ----------------------------------


def _linear_setup() -> tuple[
    FakeLinearWorkspace, LinearProjectObjectiveStore, LinearIssueBackend, str
]:
    ws = FakeLinearWorkspace()
    store = LinearProjectObjectiveStore(ws, team_key="ENG", repo_root=Path("/repo"))
    issues = LinearIssueBackend(ws, team_key="ENG", repo_root=Path("/repo"))
    nodes = [
        objective.ObjectiveNode(id="1.1", description="One", status=objective.NodeStatus.PENDING)
    ]
    ref = store.create_objective(
        title="Obj", body="# Obj\n\nprose", run_id="01RUN", roadmap_nodes=nodes
    )
    return ws, store, issues, ref.id


def test_linear_carrier_routes_to_the_sentinel_and_stores_the_transcoded_form() -> None:
    ws, store, issues, obj_id = _linear_setup()
    carrier = store.journal_carrier_id(objective_id=obj_id)
    assert carrier == "ENG-1"  # the metadata sentinel's identifier
    dc.persist_parts(issues, carrier_id=carrier, run_id=_RUN, parts=["part one"])
    sentinel = ws.issue_by_identifier("ENG-1")
    [comment] = ws.comments_of(sentinel)
    # The outgoing body rode the real transcoder: the inline-code marker, nothing HTML-encoded.
    assert comment["body"] == f"`perk:learn-dream-report:{_RUN}:1`\n\npart one"
    # The transcoded byte-compare convergence: a re-run posts nothing.
    dc.persist_parts(issues, carrier_id=carrier, run_id=_RUN, parts=["part one"])
    assert len(ws.comments_of(sentinel)) == 1


# --- Linear: the artifact publisher over the stateful workspace fake ---------------------------


def test_linear_publisher_uploads_and_links(tmp_path: Path) -> None:
    ws, _store, _issues, obj_id = _linear_setup()
    publisher = LinearDreamArtifactPublisher(ws, team_key="ENG", repo_root=tmp_path)
    publisher.publish(objective_id=obj_id, run_id=_RUN, parts=["part one", "part two"])
    [reservation] = ws.uploads
    assert reservation["contentType"] == "text/markdown"
    assert reservation["filename"] == f"dream-report-{_RUN}.md"
    assert reservation["size"] == len(b"part one\n\npart two")
    [upload] = ws.uploaded_assets
    # The canonical parts joined verbatim — a file asset, never transcoded.
    assert upload["content"] == b"part one\n\npart two"
    assert upload["content_type"] == "text/markdown"
    assert upload["upload_url"] == reservation["uploadUrl"]
    project = ws.project_by_id(obj_id)
    links = cast("list[dict[str, object]]", project["external_links"])
    [dream_link] = [link for link in links if link["label"] == f"Dream report ({_RUN})"]
    assert dream_link["url"] == reservation["assetUrl"]


def test_linear_publisher_probe_skips_when_the_labeled_link_exists(tmp_path: Path) -> None:
    ws, _store, _issues, obj_id = _linear_setup()
    publisher = LinearDreamArtifactPublisher(ws, team_key="ENG", repo_root=tmp_path)
    publisher.publish(objective_id=obj_id, run_id=_RUN, parts=["part one"])
    first_asset = ws.uploads[0]["assetUrl"]
    publisher.publish(objective_id=obj_id, run_id=_RUN, parts=["part one"])
    assert len(ws.uploads) == 1  # no second reservation
    assert len(ws.uploaded_assets) == 1  # no second PUT
    project = ws.project_by_id(obj_id)
    links = cast("list[dict[str, object]]", project["external_links"])
    [dream_link] = [link for link in links if link["label"] == f"Dream report ({_RUN})"]
    # The retained link still points at the FIRST uploaded asset.
    assert dream_link["url"] == first_asset


# --- Linear: the REAL client HTTP paths (httpx.MockTransport) ----------------------------------


def _graphql(data: dict[str, object]) -> httpx.Response:
    return httpx.Response(200, json={"data": data})


def _empty_links() -> dict[str, object]:
    return {
        "project": {
            "externalLinks": {
                "nodes": [],
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            }
        }
    }


def _upload_file(n: int = 1) -> dict[str, object]:
    return {
        "fileUpload": {
            "success": True,
            "uploadFile": {
                "uploadUrl": f"https://uploads.linear.test/put/{n}",
                "assetUrl": f"https://uploads.linear.test/asset/{n}",
                "headers": [{"key": "x-linear-signature", "value": f"sig-{n}"}],
            },
        }
    }


class _HttpScript:
    """A stateful MockTransport handler: routes GraphQL by query substring (programmable
    per-arm failures) and records PUTs."""

    def __init__(
        self,
        *,
        file_upload_fails: bool = False,
        put_status: int = 200,
        link_failures: int = 0,
    ) -> None:
        self.puts: list[httpx.Request] = []
        self.links: list[dict[str, object]] = []
        self.upload_count = 0
        self._file_upload_fails = file_upload_fails
        self._put_status = put_status
        self._link_failures = link_failures

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            self.puts.append(request)
            return httpx.Response(self._put_status)
        body = json.loads(request.content)
        query = body["query"]
        if "externalLinks(" in query:
            nodes = list(self.links)
            return _graphql(
                {
                    "project": {
                        "externalLinks": {
                            "nodes": nodes,
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                        }
                    }
                }
            )
        if "fileUpload(" in query:
            if self._file_upload_fails:
                return _graphql({"fileUpload": {"success": False, "uploadFile": None}})
            self.upload_count += 1
            return _graphql(_upload_file(self.upload_count))
        if "entityExternalLinkCreate(" in query:
            if self._link_failures > 0:
                self._link_failures -= 1
                return _graphql({"entityExternalLinkCreate": {"success": False}})
            link_input = body["variables"]["input"]
            self.links.append({"label": link_input["label"], "url": link_input["url"]})
            return _graphql({"entityExternalLinkCreate": {"success": True}})
        raise AssertionError(f"unrouted GraphQL query: {query}")


def _publisher(script: _HttpScript, tmp_path: Path) -> LinearDreamArtifactPublisher:
    client = LinearClient("lin_api_test", transport=httpx.MockTransport(script))
    return LinearDreamArtifactPublisher(client, team_key="ENG", repo_root=tmp_path)


def test_real_client_put_propagates_reservation_headers(tmp_path: Path) -> None:
    script = _HttpScript()
    _publisher(script, tmp_path).publish(objective_id="proj-1", run_id=_RUN, parts=["part one"])
    [put] = script.puts
    assert str(put.url) == "https://uploads.linear.test/put/1"
    assert put.headers["x-linear-signature"] == "sig-1"  # the reservation header, propagated
    assert put.headers["content-type"] == "text/markdown"
    assert put.content == b"part one"
    [link] = script.links
    assert link == {
        "label": f"Dream report ({_RUN})",
        "url": "https://uploads.linear.test/asset/1",
    }


def test_real_client_file_upload_refusal_is_loud(tmp_path: Path) -> None:
    script = _HttpScript(file_upload_fails=True)
    with pytest.raises(IssueBackendError, match="fileUpload failed"):
        _publisher(script, tmp_path).publish(objective_id="proj-1", run_id=_RUN, parts=["p"])
    assert script.puts == [] and script.links == []  # nothing after the failed boundary


def test_real_client_put_failure_is_loud(tmp_path: Path) -> None:
    script = _HttpScript(put_status=403)
    with pytest.raises(IssueBackendError, match="HTTP 403"):
        _publisher(script, tmp_path).publish(objective_id="proj-1", run_id=_RUN, parts=["p"])
    assert script.links == []  # the link write never ran


def test_real_client_link_failure_is_loud_and_the_retry_uploads_fresh(tmp_path: Path) -> None:
    script = _HttpScript(link_failures=1)
    publisher = _publisher(script, tmp_path)
    with pytest.raises(IssueBackendError, match="external link"):
        publisher.publish(objective_id="proj-1", run_id=_RUN, parts=["p"])
    assert script.links == []
    # The accepted orphan-asset residual: the retry uploads a FRESH asset and links it (the
    # first uploaded asset stays behind, inert).
    publisher.publish(objective_id="proj-1", run_id=_RUN, parts=["p"])
    assert script.upload_count == 2
    [link] = script.links
    assert link["url"] == "https://uploads.linear.test/asset/2"
