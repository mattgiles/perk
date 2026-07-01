"""`perk objective plan [NUMBER] [--node ID]`: the objective plan-factory cold door.

`objectives.get_objective` + `objectives.update_objective_node` + `launch.launch_stage` are
stubbed (no
GitHub, no `exec pi`), mirroring test_implement_cmd.py / test_objective_cmd.py.
"""

import json
import subprocess

from click.testing import CliRunner

from perk import github, objective
from perk.backends.github import objectives
from perk.cli.cli import cli
from perk.run import launch

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
    return objectives.ObjectiveState(
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
            sync_main=k.get("sync_main"),
        ),
    )


def test_sync_main_default_on_and_no_sync_opts_out(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(objectives, "get_objective", lambda **k: _state())
    monkeypatch.setattr(
        objectives,
        "update_objective_node",
        lambda **k: objectives.ObjectiveNodeUpdate(
            number=k["number"], node_id=k["node_id"], comment_updated=True, dry_run=False
        ),
    )
    runner = CliRunner()
    for args, expected in ((), True), (("--no-sync",), False):
        launched: dict = {}
        _stub_launch(monkeypatch, launched)
        with runner.isolated_filesystem() as d:
            _git_init(d)
            result = runner.invoke(cli, ["objective", "plan", "7", "--json", *args])
            assert result.exit_code == 0, result.output
        assert launched["sync_main"] is expected


def test_selects_next_node_marks_planning_and_launches(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(objectives, "get_objective", lambda **k: _state())
    marked: dict = {}
    monkeypatch.setattr(
        objectives,
        "update_objective_node",
        lambda **k: (
            marked.update(k)
            or objectives.ObjectiveNodeUpdate(
                number=k["number"], node_id=k["node_id"], comment_updated=True, dry_run=False
            )
        ),
    )
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "plan", "7", "--json"])
        assert result.exit_code == 0, result.output
        err = result.stderr
        assert "looking up objective #7" in err  # narrates the backend lookup wait
        assert "\u2713 found objective #7 \u2014 node 1.2" in err  # the lookup resolves on select
        # The real-run-only node-mark write and engagement read are narrated too (gap coverage).
        assert "marking node 1.2 planning" in err and "\u2713 marked node 1.2 planning" in err
        assert "reading node engagement" in err
    # The next actionable node (1.2) is selected + marked planning, then launched with the seed.
    assert marked["node_id"] == "1.2" and marked["status"] is N.PLANNING
    assert launched["stage"] == "objective-plan"
    assert "1.2" in (launched["prompt"] or "") and "objective_id" in (launched["prompt"] or "")
    # The objective link is also ferried through the handoff so plan-save recovers it even
    # when the model saves via the /plan-save command (which forwards only {plan, title}).
    assert launched["handoff_extra"] == {"objective_id": "7", "node_id": "1.2"}


def test_github_call_site_seeds_no_linear_fragments(monkeypatch):
    """The github call site forwards `store.backend_id`/`state.url` into `_seed_prompt`
    but the github arm is empty — the seed has no linear-read fragment (no churn)."""
    _authed(monkeypatch)
    monkeypatch.setattr(objectives, "get_objective", lambda **k: _state())
    monkeypatch.setattr(
        objectives,
        "update_objective_node",
        lambda **k: objectives.ObjectiveNodeUpdate(
            number=k["number"], node_id=k["node_id"], comment_updated=True, dry_run=False
        ),
    )
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "plan", "7", "--json"])
        assert result.exit_code == 0, result.output
    assert "Linear Project" not in (launched["prompt"] or "")
    assert "linear_get_issue" not in (launched["prompt"] or "")


def test_linear_call_site_forwards_backend_id_and_url(monkeypatch):
    """The call site forwards `store.backend_id` + `state.url` into `_seed_prompt`, so a
    project-backed (linear) objective seeds the backend-aware Project-URL/tools clause."""
    from perk.backends import resolve

    url = "https://linear.app/acme/project/objective-7"

    class _FakeLinearStore:
        backend_id = "linear"

        def get_objective(self, *, objective_id):
            return objectives.ObjectiveState(
                number=7, url=url, title="Ship it", header={"run_id": "01RID"}, nodes=_nodes()
            )

        def update_objective_node(self, **k):
            return objectives.ObjectiveNodeUpdate(
                number=7, node_id=k["node_id"], comment_updated=True, dry_run=False
            )

        def read_node_engagement(self, *, objective_id, node_id):
            from perk.backends.engagement import EMPTY_NODE_ENGAGEMENT

            return EMPTY_NODE_ENGAGEMENT

    _authed(monkeypatch)
    monkeypatch.setattr(resolve, "resolve_objective_store", lambda root: _FakeLinearStore())
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "plan", "7", "--json"])
        assert result.exit_code == 0, result.output
    prompt = launched["prompt"] or ""
    assert "This objective is a Linear Project" in prompt
    assert url in prompt
    assert "linear_get_issue" in prompt and "linear_list_comments" in prompt


# --- cold seed injects node-issue engagement (fail-soft) ----------------------------


def _engagement_store(monkeypatch, *, engagement_result, raises=None):
    """Install a fake project store whose `read_node_engagement` returns `engagement_result`
    (or raises `raises`). Returns the launch sink dict."""
    from perk.backends import resolve
    from perk.backends.objective_store import ObjectiveStoreError

    class _Store:
        backend_id = "linear"

        def get_objective(self, *, objective_id):
            return objectives.ObjectiveState(
                number=7, url="u/7", title="Ship it", header={"run_id": "01RID"}, nodes=_nodes()
            )

        def update_objective_node(self, **k):
            return objectives.ObjectiveNodeUpdate(
                number=7, node_id=k["node_id"], comment_updated=True, dry_run=False
            )

        def read_node_engagement(self, *, objective_id, node_id):
            if raises is not None:
                raise ObjectiveStoreError(raises)
            return engagement_result

    _authed(monkeypatch)
    monkeypatch.setattr(resolve, "resolve_objective_store", lambda root: _Store())
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    return launched


def test_cold_seed_injects_node_engagement_block(monkeypatch):
    from perk.backends import engagement

    ne = engagement.NodeEngagement(
        comments=(
            engagement.EngagementComment(
                id="c-1",
                body="please scope this down",
                created_at="2026-03-01",
                edited_at=None,
                author=engagement.EngagementAuthor(kind="human", display_name="Ada", id="u-1"),
            ),
        ),
        description_edits=(),
    )
    launched = _engagement_store(monkeypatch, engagement_result=ne)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "plan", "7", "--json"])
        assert result.exit_code == 0, result.output
    prompt = launched["prompt"] or ""
    assert "<untrusted_node_engagement>" in prompt
    assert "please scope this down" in prompt
    assert "pre-planning human engagement on the node-issue" in prompt


def test_cold_seed_omits_block_when_no_engagement(monkeypatch):
    from perk.backends import engagement

    launched = _engagement_store(monkeypatch, engagement_result=engagement.EMPTY_NODE_ENGAGEMENT)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "plan", "7", "--json"])
        assert result.exit_code == 0, result.output
    prompt = launched["prompt"] or ""
    assert "<untrusted_node_engagement>" not in prompt
    assert "pre-planning human engagement" not in prompt


def test_cold_seed_failsoft_when_read_raises(monkeypatch):
    # A Linear hiccup in read_node_engagement must never break the factory launch: the seed has
    # no engagement block but the launch still happens.
    launched = _engagement_store(monkeypatch, engagement_result=None, raises="linear boom")
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "plan", "7", "--json"])
        assert result.exit_code == 0, result.output
    assert launched["stage"] == "objective-plan"
    assert "<untrusted_node_engagement>" not in (launched["prompt"] or "")


def test_github_seed_byte_unchanged_vs_no_engagement_param(monkeypatch):
    # The github default store returns EMPTY_NODE_ENGAGEMENT → the seed equals _seed_prompt with no
    # node_engagement param (byte-unchanged; no churn).
    from perk.cli.commands.objective.plan_cmd import _seed_prompt

    _authed(monkeypatch)
    monkeypatch.setattr(objectives, "get_objective", lambda **k: _state())
    monkeypatch.setattr(
        objectives,
        "update_objective_node",
        lambda **k: objectives.ObjectiveNodeUpdate(
            number=k["number"], node_id=k["node_id"], comment_updated=True, dry_run=False
        ),
    )
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "plan", "7", "--json"])
        assert result.exit_code == 0, result.output
    node = next(n for n in _nodes() if n.id == "1.2")
    assert launched["prompt"] == _seed_prompt("7", node, "Ship it")


def test_explicit_node_selects_it(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(objectives, "get_objective", lambda **k: _state())
    marked: dict = {}
    monkeypatch.setattr(
        objectives,
        "update_objective_node",
        lambda **k: (
            marked.update(k)
            or objectives.ObjectiveNodeUpdate(
                number=k["number"], node_id=k["node_id"], comment_updated=False, dry_run=False
            )
        ),
    )
    _stub_launch(monkeypatch, {})
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "plan", "7", "--node", "1.3", "--json"])
        assert result.exit_code == 0, result.output
    assert marked["node_id"] == "1.3"


def test_dry_run_marks_nothing_launches_nothing(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(objectives, "get_objective", lambda **k: _state())

    def boom_update(**k):
        raise AssertionError("dry run must not mark")

    def boom_launch(**k):
        raise AssertionError("dry run must not launch")

    monkeypatch.setattr(objectives, "update_objective_node", boom_update)
    monkeypatch.setattr(launch, "launch_stage", boom_launch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "plan", "7", "--dry-run", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)  # stdout only: the lookup line is on stderr
        assert payload["success"] is True and payload["dry_run"] is True
        assert payload["node"] == "1.2" and payload["marked_status"] == "planning"
        assert payload["skipped_claims"] == []  # always present, empty when no claims exist
        # The lookup runs on the dry-run path too, so the wait IS narrated (to stderr).
        assert "looking up objective #7" in result.stderr
        # The node-mark write and engagement read do NOT run on a dry run — neither is narrated.
        assert "marking node" not in result.stderr
        assert "node engagement" not in result.stderr


def test_real_launch_banner_precedes_lookup(monkeypatch):
    """A real local launch heads stderr with the banner BEFORE the `looking up #X` narration."""
    _authed(monkeypatch)
    monkeypatch.setattr(objectives, "get_objective", lambda **k: _state())
    monkeypatch.setattr(
        objectives,
        "update_objective_node",
        lambda **k: objectives.ObjectiveNodeUpdate(
            number=k["number"], node_id=k["node_id"], comment_updated=True, dry_run=False
        ),
    )
    _stub_launch(monkeypatch, {})
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "plan", "7"])
        assert result.exit_code == 0, result.output
        err = result.stderr
        assert err.index("skills \u00b7") < err.index("looking up")


def test_dry_run_emits_no_banner(monkeypatch):
    """The banner is gated off on `--dry-run` (the preview path owns the output)."""
    _authed(monkeypatch)
    monkeypatch.setattr(objectives, "get_objective", lambda **k: _state())
    monkeypatch.setattr(launch, "launch_stage", lambda **k: None)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "plan", "7", "--dry-run", "--json"])
        assert result.exit_code == 0, result.output
        assert "skills \u00b7" not in result.stderr


def test_url_argument_peeled_to_objective_id(monkeypatch):
    # A pasted GitHub issue URL is peeled to its id before resolution; the dry-run payload
    # carries the extracted "7" (the parser is pure — the backend still authorities resolution).
    _authed(monkeypatch)
    monkeypatch.setattr(objectives, "get_objective", lambda **k: _state())
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(
            cli,
            ["objective", "plan", "https://github.com/o/r/issues/7", "--dry-run", "--json"],
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["objective"] == "7"  # stdout only (lookup line on stderr)


def test_objective_required_when_number_omitted(monkeypatch):
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "plan", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.stdout)["error_type"] == "objective_required"


def test_objective_not_found(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(objectives, "get_objective", lambda **k: None)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "plan", "99", "--json"])
        assert result.exit_code == 1
        # Parse stdout: the real-path `looking up #99` line is on stderr (combined .output).
        assert json.loads(result.stdout)["error_type"] == "objective_not_found"


def test_no_actionable_node(monkeypatch):
    _authed(monkeypatch)
    done_only = objectives.ObjectiveState(
        number=7,
        url="u/7",
        title="Done",
        header={},
        nodes=(objective.ObjectiveNode(id="1.1", description="A", status=N.DONE),),
    )
    monkeypatch.setattr(objectives, "get_objective", lambda **k: done_only)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        # next-node path
        result = runner.invoke(cli, ["objective", "plan", "7", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.stdout)["error_type"] == "no_actionable_node"
        # explicit non-actionable node path
        result2 = runner.invoke(cli, ["objective", "plan", "7", "--node", "1.1", "--json"])
        assert result2.exit_code == 1
        assert json.loads(result2.stdout)["error_type"] == "no_actionable_node"


def _parallel_state():
    # Node 1.1 carries a planning claim (possibly live in another terminal); 1.2 is an
    # INDEPENDENT unblocked pending node (explicit deps) -> pending-first selection takes 1.2.
    return objectives.ObjectiveState(
        number=7,
        url="u/7",
        title="Parallel",
        header={},
        nodes=(
            objective.ObjectiveNode(
                id="1.1", description="A", status=N.PLANNING, pr=None, depends_on=()
            ),
            objective.ObjectiveNode(id="1.2", description="B", status=N.PENDING, depends_on=()),
        ),
    )


def test_parallel_second_launch_selects_next_pending(monkeypatch):
    # The second parallel launch skips the (possibly live) claim, takes the pending node, and
    # notes the skipped claim on stderr.
    _authed(monkeypatch)
    monkeypatch.setattr(objectives, "get_objective", lambda **k: _parallel_state())
    marked: dict = {}
    monkeypatch.setattr(
        objectives,
        "update_objective_node",
        lambda **k: (
            marked.update(k)
            or objectives.ObjectiveNodeUpdate(
                number=k["number"], node_id=k["node_id"], comment_updated=True, dry_run=False
            )
        ),
    )
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "plan", "7", "--json"])
        assert result.exit_code == 0, result.output
        assert "node(s) 1.1 have unresumed planning claims" in result.stderr
        assert "--node <id>" in result.stderr
    assert marked["node_id"] == "1.2" and marked["status"] is N.PLANNING
    assert launched["stage"] == "objective-plan"


def test_dry_run_reports_skipped_claims(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(objectives, "get_objective", lambda **k: _parallel_state())

    def boom_update(**k):
        raise AssertionError("dry run must not mark")

    def boom_launch(**k):
        raise AssertionError("dry run must not launch")

    monkeypatch.setattr(objectives, "update_objective_node", boom_update)
    monkeypatch.setattr(launch, "launch_stage", boom_launch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "plan", "7", "--dry-run", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)  # stdout only: the lookup line is on stderr
        assert payload["node"] == "1.2"
        assert payload["skipped_claims"] == ["1.1"]


def test_resumes_orphaned_planning_claim(monkeypatch):
    # A `planning` head node with no pr (an abandoned claim) with 1.2 sequentially blocked
    # behind it is the ONLY plannable node -> the fallback re-selects + re-marks it planning.
    _authed(monkeypatch)
    orphaned = objectives.ObjectiveState(
        number=7,
        url="u/7",
        title="Resume",
        header={},
        nodes=(
            objective.ObjectiveNode(id="1.1", description="A", status=N.PLANNING, pr=None),
            objective.ObjectiveNode(id="1.2", description="B", status=N.PENDING),
        ),
    )
    monkeypatch.setattr(objectives, "get_objective", lambda **k: orphaned)
    marked: dict = {}
    monkeypatch.setattr(
        objectives,
        "update_objective_node",
        lambda **k: (
            marked.update(k)
            or objectives.ObjectiveNodeUpdate(
                number=k["number"], node_id=k["node_id"], comment_updated=True, dry_run=False
            )
        ),
    )
    launched: dict = {}
    _stub_launch(monkeypatch, launched)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "plan", "7", "--json"])
        assert result.exit_code == 0, result.output
    assert marked["node_id"] == "1.1" and marked["status"] is N.PLANNING
    assert launched["stage"] == "objective-plan"


def _in_flight_state():
    return objectives.ObjectiveState(
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
    monkeypatch.setattr(objectives, "get_objective", lambda **k: _in_flight_state())

    def boom_update(**k):
        raise AssertionError("must not mark when in flight")

    def boom_launch(**k):
        raise AssertionError("must not launch when in flight")

    monkeypatch.setattr(objectives, "update_objective_node", boom_update)
    monkeypatch.setattr(launch, "launch_stage", boom_launch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "plan", "7", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.stdout)["error_type"] == "objective_in_flight"


def test_complete_objective_reports_complete_message(monkeypatch):
    _authed(monkeypatch)
    done_only = objectives.ObjectiveState(
        number=7,
        url="u/7",
        title="Done",
        header={},
        nodes=(objective.ObjectiveNode(id="1.1", description="A", status=N.DONE),),
    )
    monkeypatch.setattr(objectives, "get_objective", lambda **k: done_only)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "plan", "7", "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["error_type"] == "no_actionable_node"
        assert "complete" in payload["message"]


def test_explicit_node_resumes_planning_claim(monkeypatch):
    _authed(monkeypatch)
    orphaned = objectives.ObjectiveState(
        number=7,
        url="u/7",
        title="Resume",
        header={},
        nodes=(
            objective.ObjectiveNode(id="1.1", description="A", status=N.PLANNING, pr=None),
            objective.ObjectiveNode(id="1.2", description="B", status=N.PENDING),
        ),
    )
    monkeypatch.setattr(objectives, "get_objective", lambda **k: orphaned)
    marked: dict = {}
    monkeypatch.setattr(
        objectives,
        "update_objective_node",
        lambda **k: (
            marked.update(k)
            or objectives.ObjectiveNodeUpdate(
                number=k["number"], node_id=k["node_id"], comment_updated=True, dry_run=False
            )
        ),
    )
    _stub_launch(monkeypatch, {})
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "plan", "7", "--node", "1.1", "--json"])
        assert result.exit_code == 0, result.output
    assert marked["node_id"] == "1.1"


def test_explicit_in_flight_node_rejected(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(objectives, "get_objective", lambda **k: _in_flight_state())
    monkeypatch.setattr(
        objectives, "update_objective_node", lambda **k: AssertionError("must not mark")
    )
    _stub_launch(monkeypatch, {})
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "plan", "7", "--node", "1.1", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.stdout)["error_type"] == "objective_in_flight"


def test_remote_blocked(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(objectives, "get_objective", lambda **k: _state())
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["objective", "plan", "7", "--remote", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.stdout)["error_type"] == "remote_blocked"


def test_not_a_repo_exit_2():
    runner = CliRunner()
    with runner.isolated_filesystem():  # no git init
        result = runner.invoke(cli, ["objective", "plan", "7", "--json"])
        assert result.exit_code == 2
        assert json.loads(result.stdout)["error_type"] == "not_a_repo"


# --- _seed_prompt model injection ----------------------------------------------------


def test_seed_prompt_injects_objective_explorer_model_when_configured():
    from perk.cli.commands.objective.plan_cmd import _seed_prompt

    node = objective.ObjectiveNode(id="1.2", description="B", status=N.PENDING, depends_on=())
    primed = _seed_prompt("7", node, "Ship it", "test/model")
    assert 'model: "test/model"' in primed
    assert "[subagents] objective-explorer model" in primed


def test_seed_prompt_omits_model_when_unset():
    from perk.cli.commands.objective.plan_cmd import _seed_prompt

    node = objective.ObjectiveNode(id="1.2", description="B", status=N.PENDING, depends_on=())
    assert "passing `model:" not in _seed_prompt("7", node, "Ship it")


def test_seed_prompt_instructs_the_file_first_loop():
    """The cold seed prompt mirrors the warm file-first loop (draft → review →
    approval-driven save), with the cold link carrier (handoff recovery, no planning mark)."""
    from perk.cli.commands.objective.plan_cmd import _seed_prompt

    node = objective.ObjectiveNode(id="1.2", description="B", status=N.PENDING, depends_on=())
    primed = _seed_prompt("7", node, "Ship it")
    # Draft + review steps are present; approval recovers the link from this run's handoff.
    assert "`plan_draft`" in primed
    assert "`plan_review`" in primed
    assert "from this run's handoff" in primed
    # No `objective_node` planning instruction — the cold door already marked the node.
    assert "objective_node" not in primed
    assert 'status: "planning"' not in primed
    # The old primary-save mandate is gone (the failsafe keeps a distinct phrasing).
    assert "Persist with `plan_save`" not in primed
    assert 'passing BOTH `objective_id: "' not in primed
    # The failsafe + never-implement mandate survive.
    assert "Manual failsafe: `/plan-save`" in primed
    assert "ALWAYS save, NEVER implement directly from this session" in primed
