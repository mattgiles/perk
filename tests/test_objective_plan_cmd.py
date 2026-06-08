"""P2.T10 — `perk objective-plan [NUMBER] [--node ID]`: the objective plan-factory cold door.

`github.get_objective` + `github.update_objective_node` + `launch.launch_stage` are stubbed (no
GitHub, no `exec pi`), mirroring test_implement_cmd.py / test_objective_cmd.py.
"""

import json
import subprocess

from click.testing import CliRunner

from perk import github, launch, objective
from perk.cli.cli import cli

N = objective.NodeStatus


def _nodes():
    # Explicit deps so 1.2 AND 1.3 are unblocked-pending (both depend only on the done 1.1);
    # next_node() returns 1.2 by position, and an explicit --node 1.3 is also actionable.
    return (
        objective.ObjectiveNode(id="1.1", description="A", status=N.DONE, depends_on=()),
        objective.ObjectiveNode(id="1.2", description="B", status=N.PENDING, depends_on=("1.1",)),
        objective.ObjectiveNode(id="1.3", description="C", status=N.PENDING, depends_on=("1.1",)),
    )


def _state():
    return github.ObjectiveState(
        number=7, url="u/7", title="Ship it", header={"run_id": "01RID"}, nodes=_nodes()
    )


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _authed(monkeypatch) -> None:
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(True, "octocat", ("repo",), None)
    )


def _stub_launch(monkeypatch, sink: dict) -> None:
    monkeypatch.setattr(
        launch,
        "launch_stage",
        lambda **k: sink.update(
            stage=k["stage"].id,
            prompt=k.get("prompt_override"),
            handoff_extra=k.get("handoff_extra"),
        ),
    )


def test_selects_next_node_marks_planning_and_launches(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(github, "get_objective", lambda **k: _state())
    marked: dict = {}
    monkeypatch.setattr(
        github,
        "update_objective_node",
        lambda **k: (
            marked.update(k)
            or github.ObjectiveNodeUpdate(
                number=k["number"], node_id=k["node_id"], comment_updated=True, dry_run=False
            )
        ),
    )
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective-plan", "7", "--json"])
        assert result.exit_code == 0, result.output
    # The next actionable node (1.2) is selected + marked planning, then launched with the seed.
    assert marked["node_id"] == "1.2" and marked["status"] is N.PLANNING
    assert launched["stage"] == "objective-plan"
    assert "1.2" in (launched["prompt"] or "") and "objective_id" in (launched["prompt"] or "")
    # #78: the objective link is also ferried through the handoff so plan-save recovers it even
    # when the model saves via the /plan-save command (which forwards only {plan, title}).
    assert launched["handoff_extra"] == {"objective_id": "7", "node_id": "1.2"}


def test_explicit_node_selects_it(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(github, "get_objective", lambda **k: _state())
    marked: dict = {}
    monkeypatch.setattr(
        github,
        "update_objective_node",
        lambda **k: (
            marked.update(k)
            or github.ObjectiveNodeUpdate(
                number=k["number"], node_id=k["node_id"], comment_updated=False, dry_run=False
            )
        ),
    )
    _stub_launch(monkeypatch, {})
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective-plan", "7", "--node", "1.3", "--json"])
        assert result.exit_code == 0, result.output
    assert marked["node_id"] == "1.3"


def test_dry_run_marks_nothing_launches_nothing(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(github, "get_objective", lambda **k: _state())

    def boom_update(**k):
        raise AssertionError("dry run must not mark")

    def boom_launch(**k):
        raise AssertionError("dry run must not launch")

    monkeypatch.setattr(github, "update_objective_node", boom_update)
    monkeypatch.setattr(launch, "launch_stage", boom_launch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective-plan", "7", "--dry-run", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["success"] is True and payload["dry_run"] is True
        assert payload["node"] == "1.2" and payload["marked_status"] == "planning"


def test_objective_required_when_number_omitted(monkeypatch):
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective-plan", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.output)["error_type"] == "objective_required"


def test_objective_not_found(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(github, "get_objective", lambda **k: None)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective-plan", "99", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.output)["error_type"] == "objective_not_found"


def test_no_actionable_node(monkeypatch):
    _authed(monkeypatch)
    done_only = github.ObjectiveState(
        number=7,
        url="u/7",
        title="Done",
        header={},
        nodes=(objective.ObjectiveNode(id="1.1", description="A", status=N.DONE),),
    )
    monkeypatch.setattr(github, "get_objective", lambda **k: done_only)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        # next-node path
        result = runner.invoke(cli, ["objective-plan", "7", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.output)["error_type"] == "no_actionable_node"
        # explicit non-actionable node path
        result2 = runner.invoke(cli, ["objective-plan", "7", "--node", "1.1", "--json"])
        assert result2.exit_code == 1
        assert json.loads(result2.output)["error_type"] == "no_actionable_node"


def test_resumes_orphaned_planning_claim(monkeypatch):
    # A `planning` head node with no pr (an abandoned claim) is re-selected and re-marked planning.
    _authed(monkeypatch)
    orphaned = github.ObjectiveState(
        number=7,
        url="u/7",
        title="Resume",
        header={},
        nodes=(
            objective.ObjectiveNode(id="1.1", description="A", status=N.PLANNING, pr=None),
            objective.ObjectiveNode(id="1.2", description="B", status=N.PENDING),
        ),
    )
    monkeypatch.setattr(github, "get_objective", lambda **k: orphaned)
    marked: dict = {}
    monkeypatch.setattr(
        github,
        "update_objective_node",
        lambda **k: (
            marked.update(k)
            or github.ObjectiveNodeUpdate(
                number=k["number"], node_id=k["node_id"], comment_updated=True, dry_run=False
            )
        ),
    )
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective-plan", "7", "--json"])
        assert result.exit_code == 0, result.output
    assert marked["node_id"] == "1.1" and marked["status"] is N.PLANNING
    assert launched["stage"] == "objective-plan"


def _in_flight_state():
    return github.ObjectiveState(
        number=7,
        url="u/7",
        title="In flight",
        header={},
        nodes=(
            objective.ObjectiveNode(id="1.1", description="A", status=N.IN_PROGRESS, pr="#9"),
            objective.ObjectiveNode(id="1.2", description="B", status=N.PENDING),
        ),
    )


def test_in_flight_node_reports_objective_in_flight(monkeypatch):
    # A head in_progress node blocks the rest: no plannable node -> objective_in_flight, no launch.
    _authed(monkeypatch)
    monkeypatch.setattr(github, "get_objective", lambda **k: _in_flight_state())

    def boom_update(**k):
        raise AssertionError("must not mark when in flight")

    def boom_launch(**k):
        raise AssertionError("must not launch when in flight")

    monkeypatch.setattr(github, "update_objective_node", boom_update)
    monkeypatch.setattr(launch, "launch_stage", boom_launch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective-plan", "7", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.output)["error_type"] == "objective_in_flight"


def test_complete_objective_reports_complete_message(monkeypatch):
    _authed(monkeypatch)
    done_only = github.ObjectiveState(
        number=7,
        url="u/7",
        title="Done",
        header={},
        nodes=(objective.ObjectiveNode(id="1.1", description="A", status=N.DONE),),
    )
    monkeypatch.setattr(github, "get_objective", lambda **k: done_only)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective-plan", "7", "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["error_type"] == "no_actionable_node"
        assert "complete" in payload["message"]


def test_explicit_node_resumes_planning_claim(monkeypatch):
    _authed(monkeypatch)
    orphaned = github.ObjectiveState(
        number=7,
        url="u/7",
        title="Resume",
        header={},
        nodes=(
            objective.ObjectiveNode(id="1.1", description="A", status=N.PLANNING, pr=None),
            objective.ObjectiveNode(id="1.2", description="B", status=N.PENDING),
        ),
    )
    monkeypatch.setattr(github, "get_objective", lambda **k: orphaned)
    marked: dict = {}
    monkeypatch.setattr(
        github,
        "update_objective_node",
        lambda **k: (
            marked.update(k)
            or github.ObjectiveNodeUpdate(
                number=k["number"], node_id=k["node_id"], comment_updated=True, dry_run=False
            )
        ),
    )
    _stub_launch(monkeypatch, {})
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective-plan", "7", "--node", "1.1", "--json"])
        assert result.exit_code == 0, result.output
    assert marked["node_id"] == "1.1"


def test_explicit_in_flight_node_rejected(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(github, "get_objective", lambda **k: _in_flight_state())
    monkeypatch.setattr(
        github, "update_objective_node", lambda **k: AssertionError("must not mark")
    )
    _stub_launch(monkeypatch, {})
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective-plan", "7", "--node", "1.1", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.output)["error_type"] == "objective_in_flight"


def test_remote_blocked(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(github, "get_objective", lambda **k: _state())
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective-plan", "7", "--remote", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.output)["error_type"] == "remote_blocked"


def test_not_a_repo_exit_2():
    runner = CliRunner()
    with runner.isolated_filesystem():  # no git init
        result = runner.invoke(cli, ["objective-plan", "7", "--json"])
        assert result.exit_code == 2
        assert json.loads(result.output)["error_type"] == "not_a_repo"


# --- _seed_prompt model injection (#196) ----------------------------------------------------


def test_seed_prompt_injects_objective_explorer_model_when_configured():
    from perk.cli.commands.objective_plan_cmd import _seed_prompt

    node = objective.ObjectiveNode(id="1.2", description="B", status=N.PENDING, depends_on=())
    primed = _seed_prompt(7, node, "Ship it", "test/model")
    assert 'model: "test/model"' in primed
    assert "[subagents] objective-explorer model" in primed


def test_seed_prompt_omits_model_when_unset():
    from perk.cli.commands.objective_plan_cmd import _seed_prompt

    node = objective.ObjectiveNode(id="1.2", description="B", status=N.PENDING, depends_on=())
    assert "passing `model:" not in _seed_prompt(7, node, "Ship it")
