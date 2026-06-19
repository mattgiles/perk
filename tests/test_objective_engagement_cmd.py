"""`perk objective engagement <NUMBER> [--json]` — the objective + node-issue engagement read
worker (Objective #682, Node 2.3). Stubs the resolved store (no network)."""

import json
import subprocess

from click.testing import CliRunner

from perk import github, objective
from perk.backends import engagement, objective_stores
from perk.backends.objective_store import ObjectiveStoreError
from perk.cli.cli import cli

N = objective.NodeStatus


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _nodes():
    return (
        objective.ObjectiveNode(id="1.1", description="A", status=N.DONE),
        objective.ObjectiveNode(id="2.1", description="B", status=N.PENDING),
    )


def _state():
    return github.ObjectiveState(
        number=7, url="u/7", title="Obj", header={"run_id": "01RID"}, nodes=_nodes()
    )


def _comment(body: str, *, cid: str = "c-1") -> engagement.EngagementComment:
    return engagement.EngagementComment(
        id=cid,
        body=body,
        created_at="2026-03-01",
        edited_at=None,
        author=engagement.EngagementAuthor(kind="human", display_name="Ada", id="u-1"),
    )


def _edit() -> engagement.DescriptionEdit:
    return engagement.DescriptionEdit(
        created_at="2026-03-02",
        author=engagement.EngagementAuthor(kind="human", display_name="Ada", id="u-1"),
        diff=None,
    )


def _install_store(
    monkeypatch,
    *,
    project_comments=(),
    project_edits=(),
    node_engagement=None,
    raises=None,
):
    class _Store:
        backend_id = "linear"

        def get_objective(self, *, objective_id):
            return _state()

        def read_comments(self, *, objective_id):
            if raises is not None:
                raise ObjectiveStoreError(raises)
            return project_comments

        def read_description_edits(self, *, objective_id):
            return project_edits

        def read_node_engagement(self, *, objective_id, node_id):
            if node_engagement is not None and node_id == "2.1":
                return node_engagement
            return engagement.EMPTY_NODE_ENGAGEMENT

    monkeypatch.setattr(objective_stores, "resolve_objective_store", lambda root: _Store())


def _invoke(args):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        return runner.invoke(cli, args)


def test_json_payload_shape(monkeypatch):
    _install_store(
        monkeypatch,
        project_comments=(_comment("project discussion", cid="p-1"),),
        node_engagement=engagement.NodeEngagement(
            comments=(_comment("node feedback", cid="n-1"),),
            description_edits=(_edit(),),
        ),
    )
    result = _invoke(["objective", "engagement", "7", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["objective"] == "7"
    assert [c["id"] for c in payload["project_comments"]] == ["p-1"]
    assert payload["project_description_edits"] == []
    assert [n["node"] for n in payload["nodes"]] == ["1.1", "2.1"]
    node_21 = next(n for n in payload["nodes"] if n["node"] == "2.1")
    assert [c["id"] for c in node_21["comments"]] == ["n-1"]
    assert len(node_21["description_edits"]) == 1


def test_human_renders_block(monkeypatch):
    _install_store(
        monkeypatch,
        project_comments=(_comment("project discussion"),),
        node_engagement=engagement.NodeEngagement(
            comments=(_comment("node feedback", cid="n-1"),), description_edits=()
        ),
    )
    result = _invoke(["objective", "engagement", "7"])
    assert result.exit_code == 0, result.output
    assert "<untrusted_objective_engagement>" in result.stderr
    assert "project discussion" in result.stderr
    assert "node 2.1:" in result.stderr
    assert "node feedback" in result.stderr


def test_human_no_engagement_note(monkeypatch):
    _install_store(monkeypatch)
    result = _invoke(["objective", "engagement", "7"])
    assert result.exit_code == 0, result.output
    assert "no human engagement on objective 7" in result.stderr


def test_json_empty_engagement(monkeypatch):
    _install_store(monkeypatch)
    result = _invoke(["objective", "engagement", "7", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["project_comments"] == []
    assert payload["project_description_edits"] == []
    assert all(n["comments"] == [] and n["description_edits"] == [] for n in payload["nodes"])


def test_objective_not_found(monkeypatch):
    class _Store:
        backend_id = "github"

        def get_objective(self, *, objective_id):
            return None

    monkeypatch.setattr(objective_stores, "resolve_objective_store", lambda root: _Store())
    result = _invoke(["objective", "engagement", "99", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "objective_not_found"


def test_store_error_maps_to_github_error(monkeypatch):
    _install_store(monkeypatch, raises="linear boom")
    result = _invoke(["objective", "engagement", "7", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "github_error"


def test_not_a_repo_exit_2():
    runner = CliRunner()
    with runner.isolated_filesystem():  # no git init -> not a repo
        result = runner.invoke(cli, ["objective", "engagement", "7", "--json"])
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error_type"] == "not_a_repo"
