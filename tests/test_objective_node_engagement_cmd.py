"""`perk objective node-engagement <NUMBER> --node ID [--json]` — the node-issue engagement read
worker. Stubs the resolved store (no network)."""

import json
import subprocess

from click.testing import CliRunner

from perk import objective
from perk.backends import engagement, resolve
from perk.backends.github import objectives
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
    return objectives.ObjectiveState(
        number=7, url="u/7", title="Obj", header={"run_id": "01RID"}, nodes=_nodes()
    )


def _install_store(monkeypatch, *, engagement_result=None, raises=None):
    class _Store:
        backend_id = "linear"

        def get_objective(self, *, objective_id):
            return _state()

        def read_node_engagement(self, *, objective_id, node_id):
            if raises is not None:
                raise ObjectiveStoreError(raises)
            return (
                engagement_result
                if engagement_result is not None
                else (engagement.EMPTY_NODE_ENGAGEMENT)
            )

    monkeypatch.setattr(resolve, "resolve_objective_store", lambda root: _Store())


def _invoke(args):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        return runner.invoke(cli, args)


def _sample_engagement():
    return engagement.NodeEngagement(
        comments=(
            engagement.EngagementComment(
                id="c-1",
                body="please scope this down",
                created_at="2026-03-01",
                edited_at=None,
                author=engagement.EngagementAuthor(kind="human", display_name="Ada", id="u-1"),
            ),
        ),
        description_edits=(
            engagement.DescriptionEdit(
                created_at="2026-03-02",
                author=engagement.EngagementAuthor(kind="human", display_name="Ada", id="u-1"),
                diff=None,
            ),
        ),
    )


def test_json_payload_shape(monkeypatch):
    _install_store(monkeypatch, engagement_result=_sample_engagement())
    result = _invoke(["objective", "node-engagement", "7", "--node", "2.1", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["objective"] == "7"
    assert payload["node"] == "2.1"
    assert [c["id"] for c in payload["comments"]] == ["c-1"]
    assert payload["comments"][0]["author"]["kind"] == "human"
    assert payload["comments"][0]["body"] == "please scope this down"
    assert len(payload["description_edits"]) == 1
    assert payload["description_edits"][0]["diff"] is None


def test_human_renders_block(monkeypatch):
    _install_store(monkeypatch, engagement_result=_sample_engagement())
    result = _invoke(["objective", "node-engagement", "7", "--node", "2.1"])
    assert result.exit_code == 0, result.output
    assert "<untrusted_node_engagement>" in result.stderr
    assert "please scope this down" in result.stderr


def test_human_no_engagement_note(monkeypatch):
    _install_store(monkeypatch, engagement_result=engagement.EMPTY_NODE_ENGAGEMENT)
    result = _invoke(["objective", "node-engagement", "7", "--node", "2.1"])
    assert result.exit_code == 0, result.output
    assert "no pre-planning engagement on node 2.1" in result.stderr


def test_json_empty_engagement(monkeypatch):
    _install_store(monkeypatch, engagement_result=engagement.EMPTY_NODE_ENGAGEMENT)
    result = _invoke(["objective", "node-engagement", "7", "--node", "2.1", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["comments"] == []
    assert payload["description_edits"] == []


def test_objective_not_found(monkeypatch):
    class _Store:
        backend_id = "github"

        def get_objective(self, *, objective_id):
            return None

        def read_node_engagement(self, *, objective_id, node_id):
            return engagement.EMPTY_NODE_ENGAGEMENT

    monkeypatch.setattr(resolve, "resolve_objective_store", lambda root: _Store())
    result = _invoke(["objective", "node-engagement", "99", "--node", "2.1", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "objective_not_found"


def test_store_error_maps_to_github_error(monkeypatch):
    _install_store(monkeypatch, raises="linear boom")
    result = _invoke(["objective", "node-engagement", "7", "--node", "2.1", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "github_error"


def test_not_a_repo_exit_2():
    runner = CliRunner()
    with runner.isolated_filesystem():  # no git init -> not a repo
        result = runner.invoke(
            cli, ["objective", "node-engagement", "7", "--node", "2.1", "--json"]
        )
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error_type"] == "not_a_repo"


def test_node_option_required():
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "node-engagement", "7"])
    assert result.exit_code != 0  # Click usage error: --node is required
