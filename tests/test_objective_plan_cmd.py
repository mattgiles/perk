"""`perk objective plan [NUMBER] [--node ID]`: the objective plan-factory cold door.

`objectives.get_objective` + `objectives.update_objective_node` + `launch.launch_stage` are
stubbed (no
GitHub, no `exec pi`), mirroring test_implement_cmd.py / test_objective_cmd.py.
"""

import json

import pytest
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


def _git_init(path: str, factory) -> None:
    factory(path)


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


def test_blank_node_is_typed_invalid_input_before_authority_access(
    monkeypatch, unborn_git_repo_factory
):
    monkeypatch.setattr(
        objectives,
        "get_objective",
        lambda **_kwargs: pytest.fail("blank node must fail before objective lookup"),
    )
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "plan", "7", "--node", "  ", "--json"])

    assert result.exit_code == 1
    assert json.loads(result.stdout) == {
        "success": False,
        "error_type": "invalid_input",
        "message": "--node must not be blank.",
    }


def test_sync_main_default_on_and_no_sync_opts_out(monkeypatch, unborn_git_repo_factory):
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
            _git_init(d, unborn_git_repo_factory)
            result = runner.invoke(cli, ["objective", "plan", "7", "--json", *args])
            assert result.exit_code == 0, result.output
        assert launched["sync_main"] is expected


def test_selects_next_node_marks_planning_and_launches(monkeypatch, unborn_git_repo_factory):
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
        _git_init(d, unborn_git_repo_factory)
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


def test_github_call_site_seeds_no_linear_fragments(monkeypatch, unborn_git_repo_factory):
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
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "plan", "7", "--json"])
        assert result.exit_code == 0, result.output
    assert "Linear Project" not in (launched["prompt"] or "")
    assert "linear_get_issue" not in (launched["prompt"] or "")


def test_linear_call_site_forwards_backend_id_and_url(monkeypatch, unborn_git_repo_factory):
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
        _git_init(d, unborn_git_repo_factory)
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


def test_cold_seed_injects_node_engagement_block(monkeypatch, unborn_git_repo_factory):
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
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "plan", "7", "--json"])
        assert result.exit_code == 0, result.output
    prompt = launched["prompt"] or ""
    assert "<untrusted_node_engagement>" in prompt
    assert "please scope this down" in prompt
    assert "pre-planning human engagement on the node-issue" in prompt


def test_cold_seed_omits_block_when_no_engagement(monkeypatch, unborn_git_repo_factory):
    from perk.backends import engagement

    launched = _engagement_store(monkeypatch, engagement_result=engagement.EMPTY_NODE_ENGAGEMENT)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "plan", "7", "--json"])
        assert result.exit_code == 0, result.output
    prompt = launched["prompt"] or ""
    assert "<untrusted_node_engagement>" not in prompt
    assert "pre-planning human engagement" not in prompt


def test_cold_seed_failsoft_when_read_raises(monkeypatch, unborn_git_repo_factory):
    # A Linear hiccup in read_node_engagement must never break the factory launch: the seed has
    # no engagement block but the launch still happens.
    launched = _engagement_store(monkeypatch, engagement_result=None, raises="linear boom")
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "plan", "7", "--json"])
        assert result.exit_code == 0, result.output
    assert launched["stage"] == "objective-plan"
    assert "<untrusted_node_engagement>" not in (launched["prompt"] or "")


def test_github_seed_byte_unchanged_vs_no_engagement_param(monkeypatch, unborn_git_repo_factory):
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
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "plan", "7", "--json"])
        assert result.exit_code == 0, result.output
    node = next(n for n in _nodes() if n.id == "1.2")
    assert launched["prompt"] == _seed_prompt("7", node, "Ship it")


def test_explicit_node_selects_it(monkeypatch, unborn_git_repo_factory):
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
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "plan", "7", "--node", "1.3", "--json"])
        assert result.exit_code == 0, result.output
    assert marked["node_id"] == "1.3"


def test_dry_run_marks_nothing_launches_nothing(monkeypatch, unborn_git_repo_factory):
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
        _git_init(d, unborn_git_repo_factory)
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


def test_real_launch_banner_precedes_lookup(monkeypatch, unborn_git_repo_factory):
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
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "plan", "7"])
        assert result.exit_code == 0, result.output
        err = result.stderr
        assert err.index("skills \u00b7") < err.index("looking up")


def test_dry_run_emits_no_banner(monkeypatch, unborn_git_repo_factory):
    """The banner is gated off on `--dry-run` (the preview path owns the output)."""
    _authed(monkeypatch)
    monkeypatch.setattr(objectives, "get_objective", lambda **k: _state())
    monkeypatch.setattr(launch, "launch_stage", lambda **k: None)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "plan", "7", "--dry-run", "--json"])
        assert result.exit_code == 0, result.output
        assert "skills \u00b7" not in result.stderr


def test_url_argument_peeled_to_objective_id(monkeypatch, unborn_git_repo_factory):
    # A pasted GitHub issue URL is peeled to its id before resolution; the dry-run payload
    # carries the extracted "7" (the parser is pure — the backend still authorities resolution).
    _authed(monkeypatch)
    monkeypatch.setattr(objectives, "get_objective", lambda **k: _state())
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(
            cli,
            ["objective", "plan", "https://github.com/o/r/issues/7", "--dry-run", "--json"],
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["objective"] == "7"  # stdout only (lookup line on stderr)


def test_objective_required_when_number_omitted(monkeypatch, unborn_git_repo_factory):
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "plan", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.stdout)["error_type"] == "objective_required"


def test_objective_not_found(monkeypatch, unborn_git_repo_factory):
    _authed(monkeypatch)
    monkeypatch.setattr(objectives, "get_objective", lambda **k: None)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "plan", "99", "--json"])
        assert result.exit_code == 1
        # Parse stdout: the real-path `looking up #99` line is on stderr (combined .output).
        assert json.loads(result.stdout)["error_type"] == "objective_not_found"


def test_no_actionable_node(monkeypatch, unborn_git_repo_factory):
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
        _git_init(d, unborn_git_repo_factory)
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


def test_parallel_second_launch_selects_next_pending(monkeypatch, unborn_git_repo_factory):
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
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "plan", "7", "--json"])
        assert result.exit_code == 0, result.output
        assert "node(s) 1.1 have unresumed planning claims" in result.stderr
        assert "--node <id>" in result.stderr
    assert marked["node_id"] == "1.2" and marked["status"] is N.PLANNING
    assert launched["stage"] == "objective-plan"


def test_dry_run_reports_skipped_claims(monkeypatch, unborn_git_repo_factory):
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
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "plan", "7", "--dry-run", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)  # stdout only: the lookup line is on stderr
        assert payload["node"] == "1.2"
        assert payload["skipped_claims"] == ["1.1"]


def test_resumes_orphaned_planning_claim(monkeypatch, unborn_git_repo_factory):
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
        _git_init(d, unborn_git_repo_factory)
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


def test_in_flight_node_reports_objective_in_flight(monkeypatch, unborn_git_repo_factory):
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
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "plan", "7", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.stdout)["error_type"] == "objective_in_flight"


def test_complete_objective_reports_complete_message(monkeypatch, unborn_git_repo_factory):
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
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "plan", "7", "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["error_type"] == "no_actionable_node"
        assert "complete" in payload["message"]


def test_explicit_node_resumes_planning_claim(monkeypatch, unborn_git_repo_factory):
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
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "plan", "7", "--node", "1.1", "--json"])
        assert result.exit_code == 0, result.output
    assert marked["node_id"] == "1.1"


def test_explicit_in_flight_node_rejected(monkeypatch, unborn_git_repo_factory):
    _authed(monkeypatch)
    monkeypatch.setattr(objectives, "get_objective", lambda **k: _in_flight_state())
    monkeypatch.setattr(
        objectives, "update_objective_node", lambda **k: AssertionError("must not mark")
    )
    _stub_launch(monkeypatch, {})
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "plan", "7", "--node", "1.1", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.stdout)["error_type"] == "objective_in_flight"


def test_remote_blocked(monkeypatch, unborn_git_repo_factory):
    _authed(monkeypatch)
    monkeypatch.setattr(objectives, "get_objective", lambda **k: _state())
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "plan", "7", "--remote", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.stdout)["error_type"] == "remote_blocked"


def test_not_a_repo_exit_2():
    runner = CliRunner()
    with runner.isolated_filesystem():  # no git init
        result = runner.invoke(cli, ["objective", "plan", "7", "--json"])
        assert result.exit_code == 2
        assert json.loads(result.stdout)["error_type"] == "not_a_repo"


# --- _seed_prompt explore step ----------------------------------------------------


def test_seed_prompt_explores_via_the_tool_without_transcribed_mechanics():
    """The OPTIONAL explore step is ONE `explore_objective_node` call — the tool owns the wave
    mechanics and reads the explorer model at execute time, so nothing schema- or model-shaped
    rides the seed."""
    from perk.cli.commands.objective.plan_cmd import _seed_prompt

    node = objective.ObjectiveNode(id="1.2", description="B", status=N.PENDING, depends_on=())
    primed = _seed_prompt("7", node, "Ship it")
    assert "explore_objective_node" in primed
    assert "[models.subagents] objective-explorer" in primed
    assert "workflowScript" not in primed
    assert "outputSchema" not in primed
    assert "structuredOutput" not in primed
    assert "passing `model:" not in primed


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
    # No `objective_node` planning instruction — the cold door already marked the node (the
    # backtick-delimited pin keeps `explore_objective_node` from matching).
    assert "`objective_node`" not in primed
    assert 'status: "planning"' not in primed
    # The old primary-save mandate is gone (the failsafe keeps a distinct phrasing).
    assert "Persist with `plan_save`" not in primed
    assert 'passing BOTH `objective_id: "' not in primed
    # The failsafe + never-implement mandate survive.
    assert "Manual failsafe: `/plan-save`" in primed
    assert "ALWAYS save, NEVER implement directly from this session" in primed


# --- stacked selection (readiness-derived; contracts.md §8.46) -----------------------


def _stacked_state():
    return objectives.ObjectiveState(
        number=7,
        url="u/7",
        title="Ship it",
        header={
            "run_id": "01RID",
            "delivery": "stacked",
            "delivery_lineage": "01JB0000000000000000000000",
        },
        nodes=_nodes(),
    )


def _planning_node(node):
    from perk.delivery import PrepareResult

    return PrepareResult.PlanningNode(
        id=node.id, description=node.description, status=node.status, pr=node.pr
    )


def _decision(kind, node=None, *, reason=None, requested=None, context=None):
    from perk.delivery import PrepareResult

    return PrepareResult.PlanningDecision(
        kind=kind,
        objective_id="7",
        objective_title="Ship it from Prepare",
        objective_url="u/prepared-7",
        requested_node_id=requested,
        node=_planning_node(node) if node is not None else None,
        reason=reason,
        skipped_claim_ids=() if kind == "ready" else None,
        context=context,
    )


def _stub_planning_prepare(monkeypatch, decision):
    from perk.cli.commands.objective import plan_cmd
    from perk.delivery import DeliveryError, PrepareResult

    calls = []

    class FakeDelivery:
        def prepare(self, request):
            calls.append(request)
            if isinstance(decision, DeliveryError):
                raise decision
            return PrepareResult(kind="layer_start", mode="planning", planning=decision)

    monkeypatch.setattr(plan_cmd, "resolve_delivery", lambda _root: FakeDelivery())
    return calls


def test_stacked_auto_select_uses_planning_prepare_snapshot(monkeypatch, unborn_git_repo_factory):
    # Prepare's candidate (1.3) wins over the initial graph's pending-first choice (1.2), and
    # its captured title/description drive the mark, seed, and handoff.
    from perk import objective

    _authed(monkeypatch)
    monkeypatch.setattr(objectives, "get_objective", lambda **k: _stacked_state())
    candidate = objective.ObjectiveNode(
        id="1.3",
        description="Snapshot description",
        status=N.PENDING,
        depends_on=("1.1",),
    )
    calls = _stub_planning_prepare(monkeypatch, _decision("ready", candidate))
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
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "plan", "7", "--json"])
        assert result.exit_code == 0, result.output
    assert calls[0].objective_id == "7" and calls[0].node_id is None
    assert marked["node_id"] == "1.3"
    assert "Ship it from Prepare" in launched["prompt"]
    assert "Snapshot description" in launched["prompt"]
    assert launched["handoff_extra"] == {"objective_id": "7", "node_id": "1.3"}


def test_stacked_build_blocked_is_a_typed_refusal(monkeypatch, unborn_git_repo_factory):
    _authed(monkeypatch)
    monkeypatch.setattr(objectives, "get_objective", lambda **k: _stacked_state())
    _stub_planning_prepare(
        monkeypatch,
        _decision("build_blocked", reason="the train has blocker findings: [x] y"),
    )
    monkeypatch.setattr(
        objectives, "update_objective_node", lambda **k: pytest.fail("must not mark")
    )
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "plan", "7", "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
    assert payload["error_type"] == "node_not_build_ready"
    assert payload["message"] == (
        "Objective #7 is not build-ready: the train has blocker findings: [x] y\n"
        "Inspect the train: perk objective stack status 7"
    )


def test_stacked_explicit_node_must_match_the_ready_candidate(monkeypatch, unborn_git_repo_factory):
    _authed(monkeypatch)
    monkeypatch.setattr(objectives, "get_objective", lambda **k: _stacked_state())
    candidate = _nodes()[1]
    calls = _stub_planning_prepare(
        monkeypatch, _decision("wrong_candidate", candidate, requested="1.3")
    )
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "plan", "7", "--node", "1.3", "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
    assert calls[0].node_id == "1.3"
    assert payload["error_type"] == "node_not_build_ready"
    assert payload["message"] == (
        "Node 1.3 is not the build-ready layer — the next build-ready node is 1.2 "
        "(stacked planning follows the delivery order).\n"
        "Inspect the train: perk objective stack status 7"
    )


def test_stacked_in_flight_keeps_the_incremental_message_shape(
    monkeypatch, unborn_git_repo_factory
):
    from perk import objective

    _authed(monkeypatch)
    monkeypatch.setattr(objectives, "get_objective", lambda **k: _stacked_state())
    in_flight = objective.ObjectiveNode(
        id="1.2", description="B", status=N.IN_PROGRESS, pr="#55", depends_on=("1.1",)
    )
    _stub_planning_prepare(monkeypatch, _decision("in_flight", in_flight))
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "plan", "7", "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
    assert payload["error_type"] == "objective_in_flight"
    assert payload["message"] == (
        "No new node to plan: node 1.2 has a plan in flight (pr #55, status in_progress). "
        "Implement it (`perk implement #55` when set), or reset it to re-plan."
    )


@pytest.mark.parametrize(
    ("decision", "error_type", "message"),
    [
        (
            _decision("complete"),
            "no_actionable_node",
            "Objective #7 is complete — every node is done or skipped. Nothing to plan.",
        ),
        (
            _decision("node_not_found", requested="9.9"),
            "no_actionable_node",
            "Node '9.9' not found on objective #7.",
        ),
        (
            _decision(
                "terminal",
                objective.ObjectiveNode(id="1.1", description="Done", status=N.DONE, depends_on=()),
                requested="1.1",
            ),
            "no_actionable_node",
            "Node 1.1 is already done.",
        ),
        (
            _decision(
                "blocked",
                objective.ObjectiveNode(
                    id="1.2", description="Blocked", status=N.PENDING, depends_on=("1.1",)
                ),
                requested="1.2",
            ),
            "no_actionable_node",
            "Node 1.2 is blocked by an unfinished dependency.",
        ),
        (
            _decision("no_actionable"),
            "no_actionable_node",
            "No actionable node on objective #7: every remaining node is blocked by an "
            "unfinished dependency (or explicitly blocked).",
        ),
    ],
)
def test_planning_decision_refusal_mapping_is_exact(decision, error_type, message):
    from perk.cli.commands.objective.plan_cmd import _planning_node_choice
    from perk.cli.ensure import UserFacingCliError

    with pytest.raises(UserFacingCliError) as excinfo:
        _planning_node_choice(decision, "7")
    assert excinfo.value.error_type == error_type
    assert str(excinfo.value) == message


def test_stacked_dry_run_skips_prepare_and_reports_unchecked(monkeypatch, unborn_git_repo_factory):
    from perk.cli.commands.objective import plan_cmd

    _authed(monkeypatch)
    monkeypatch.setattr(objectives, "get_objective", lambda **k: _stacked_state())
    monkeypatch.setattr(
        plan_cmd, "resolve_delivery", lambda *_a: pytest.fail("dry run must not reconstruct")
    )
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "plan", "7", "--dry-run", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
    assert payload["build_readiness"] == "unchecked (dry-run)"
    assert payload["node"] == "1.2"


def test_incremental_dry_run_payload_has_no_build_readiness(monkeypatch, unborn_git_repo_factory):
    _authed(monkeypatch)
    monkeypatch.setattr(objectives, "get_objective", lambda **k: _state())
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        result = runner.invoke(cli, ["objective", "plan", "7", "--dry-run", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
    assert "build_readiness" not in payload


# --- the stacked-layer seed block ------------------------------------------------------


def _child_context():
    from perk.delivery import PrepareResult

    return PrepareResult.PlanningContext(
        position=2,
        layer_count=2,
        delivery_lineage="01JB0000000000000000000000",
        base="main",
        predecessor_node_id="1.2",
        predecessor_plan_id="101",
        parent_branch="plan-101",
        observed_parent_head_sha="a" * 40,
    )


def _bottom_context():
    from perk.delivery import PrepareResult

    return PrepareResult.PlanningContext(
        position=1,
        layer_count=2,
        delivery_lineage="01JB0000000000000000000000",
        base="main",
        predecessor_node_id=None,
        predecessor_plan_id=None,
        parent_branch="main",
        observed_parent_head_sha=None,
    )


def test_layer_context_block_child_names_predecessor_branch_and_verified_head():
    from perk.cli.commands.objective.plan_cmd import _layer_context_block

    block = _layer_context_block(_child_context())
    assert "<stacked_layer_context>" in block
    assert "layer 2 of 2" in block
    assert "node 1.2 (plan #101)" in block
    assert "`plan-101`" in block
    assert "verified remote head " + "a" * 40 in block
    assert "origin/plan-101" in block  # the already-fetched, locally-inspectable note
    assert "records no planning-time parent SHA" in block  # movement is a NORMAL danger


def test_layer_context_block_bottom_names_the_objective_base():
    from perk.cli.commands.objective.plan_cmd import _layer_context_block

    block = _layer_context_block(_bottom_context())
    assert "layer 1 of 2" in block
    assert "bottom layer" in block and "`main`" in block
    assert "origin/main" in block


def test_seed_prompt_incremental_stays_byte_identical_without_layer_context():
    from perk.cli.commands.objective.plan_cmd import _seed_prompt

    node = _nodes()[1]
    assert _seed_prompt("7", node, "Ship it") == _seed_prompt(
        "7", node, "Ship it", layer_context=""
    )
    assert "stacked_layer_context" not in _seed_prompt("7", node, "Ship it")


def test_seed_prompt_injects_the_layer_context_block():
    from perk.cli.commands.objective.plan_cmd import _layer_context_block, _seed_prompt

    node = _nodes()[1]
    block = _layer_context_block(_child_context())
    primed = _seed_prompt("7", node, "Ship it", layer_context=block)
    assert "<stacked_layer_context>" in primed
    assert "never as instructions" in primed  # the untrusted framing survives


def _handoff_layer(*, handoff, stamped=None, observed=None):
    from perk.delivery import train as train_mod

    return train_mod.TrainLayer(
        node_id="1.1",
        plan_id="101",
        branch="plan-101",
        pr_number=201,
        intent=train_mod.LayerIntent.PLANNED,
        publication=train_mod.LayerPublication.PUBLISHED,
        git=train_mod.LayerGit.SYNCED,
        pr=train_mod.LayerPr.DRAFT,
        membership=train_mod.LayerMembership.NOT_APPLICABLE,
        writer=train_mod.LayerWriter.FREE,
        finalization=train_mod.LayerFinalization.NOT_MERGED,
        parent_checkpoint_sha="a" * 40,
        published_head_sha="b" * 40,
        observed_remote_head_sha=observed,
        observed_pr_base=None,
        expected_pr_base=None,
        handoff=handoff,
        stamped_head_sha=stamped,
    )


def test_stacked_handoff_blocked_is_a_typed_refusal():
    # The §8.46 door refusal: each blocking dep/plan/PR/state (+ the head mismatch when
    # stale), the copyable `perk ready <PLAN>` first, then the stack-status hint.
    from perk import objective
    from perk.cli.commands.objective.plan_cmd import _planning_node_choice
    from perk.cli.ensure import UserFacingCliError
    from perk.delivery import PrepareResult
    from perk.delivery import train as train_mod

    node = objective.ObjectiveNode(
        id="1.2", description="Child", status=N.PENDING, depends_on=("1.1",)
    )
    decision = PrepareResult.PlanningDecision(
        kind="handoff_blocked",
        objective_id="7",
        objective_title="Obj",
        objective_url="u/7",
        requested_node_id=None,
        node=_planning_node(node),
        handoff_blockers=(
            _handoff_layer(
                handoff=train_mod.LayerHandoff.STALE, stamped="s" * 40, observed="h" * 40
            ),
        ),
    )
    with pytest.raises(UserFacingCliError) as excinfo:
        _planning_node_choice(decision, "7")
    assert excinfo.value.error_type == "node_not_handoff_ready"
    assert str(excinfo.value) == (
        "Node 1.2 is not handoff-ready: it waits on 1.1 (plan #101, PR #201) — stale; "
        f"stamped {'s' * 12} ≠ head {'h' * 12}; record the handoff: perk ready 101\n"
        "Inspect the train: perk objective stack status 7"
    )
