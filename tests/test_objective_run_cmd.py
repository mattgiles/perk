"""`perk objective run`: the deterministic capstone supervisor loop (§8.20).

`objectives.get_objective`/`get_plan`/`get_pr_feedback`/`close_issue`,
`cache.list_dispatch_records`,
`run_report.read_outcome`, `runner.select_runner`, and `launch.launch_stage` are all stubbed (no
GitHub, no `exec pi`, no real runner) — the supervisor's control flow is exercised purely.
"""

import json
import subprocess

import pytest
from click.testing import CliRunner

from perk import github, objective
from perk.backends.github import objectives, plans
from perk.cli.cli import cli
from perk.cli.commands.objective import run_cmd
from perk.delivery import train as train_mod
from perk.run import discovery, launch, run_report, runner
from perk.state import cache

N = objective.NodeStatus


# --------------------------------------------------------------------------- harness


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


@pytest.fixture(autouse=True)
def _offline_discovery(monkeypatch):
    """The gate's canonical discovery shells `gh api`; default every test to a discovery error so
    the gate exercises the legacy local-record fallback (today's offline behavior). The
    discovery-first tests override ``discovery.discover_runs`` themselves."""

    def _offline(root, *, limit=100):
        raise runner.RunnerError("offline test default")

    monkeypatch.setattr(discovery, "discover_runs", _offline)


def _authed(monkeypatch) -> None:
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(True, "octocat", ("repo",), None)
    )


def _state(nodes):
    return objectives.ObjectiveState(
        number=137, url="u/137", title="Ship it", header={"run_id": "01RID"}, nodes=tuple(nodes)
    )


def _plan_state(pr, *, header=None):
    return plans.PlanState(number=7, url="u/7", title="Plan", header=header or {}, pr=pr)


def _pr(*, state="OPEN", is_draft=False, number=99):
    return github.PullRequest(
        number=number, url="u/pr", is_draft=is_draft, state=state, existed=True
    )


def _feedback(*, threads=(), reviews=(), comments=()):
    return github.PrFeedback(
        pr_number=99,
        review_threads=tuple(threads),
        discussion_comments=tuple(comments),
        reviews=tuple(reviews),
    )


def _thread(resolved):
    return github.ReviewThread(
        thread_id="T", is_resolved=resolved, is_outdated=False, path=None, line=None, comments=()
    )


def _review(author, state, submitted_at):
    return github.Review(
        review_id="R", author=author, body="", state=state, submitted_at=submitted_at
    )


def _invoke(monkeypatch, args, *, objective_state, stub_no_records=True):
    monkeypatch.setattr(objectives, "get_objective", lambda **k: objective_state)
    if stub_no_records:
        monkeypatch.setattr(cache, "list_dispatch_records", lambda root: [])
    cli_runner = CliRunner()
    with cli_runner.isolated_filesystem() as d:
        _git_init(d)
        return cli_runner.invoke(cli, ["objective", "run", *args])


def _payload(result):
    # CliRunner mixes stderr (human lines) + stdout (the JSON) into `output`; the JSON is the
    # final non-empty line.
    line = [ln for ln in result.output.splitlines() if ln.strip()][-1]
    return json.loads(line)


# --------------------------------------------------------------------------- selection


def test_plannable_emits_plan_required_and_dispatches_nothing(monkeypatch):
    _authed(monkeypatch)
    launched: dict = {}
    monkeypatch.setattr(launch, "launch_stage", lambda **k: launched.update(called=True))
    nodes = [objective.ObjectiveNode(id="1.1", description="A", status=N.PENDING)]
    result = _invoke(monkeypatch, ["137", "--json"], objective_state=_state(nodes))
    assert result.exit_code == 0
    payload = _payload(result)
    assert payload["action"] == "plan_required"
    assert payload["node"] == "1.1"
    assert payload["remediation"] == "perk objective plan 137 --node 1.1"
    assert "called" not in launched


def test_objective_not_found(monkeypatch):
    _authed(monkeypatch)
    result = _invoke(monkeypatch, ["137", "--json"], objective_state=None)
    assert result.exit_code == 1
    payload = _payload(result)
    assert payload["success"] is False and payload["error_type"] == "objective_not_found"


# --------------------------------------------------------------------------- in-flight dispatch


def _in_flight_nodes():
    return [
        objective.ObjectiveNode(id="1.1", description="A", status=N.DONE, depends_on=()),
        objective.ObjectiveNode(
            id="1.2", description="B", status=N.IN_PROGRESS, pr="#7", depends_on=("1.1",)
        ),
    ]


def _stub_launch(monkeypatch, sink):
    def _fake(**k):
        sink["called"] = True
        sink["stage"] = k["stage"].id
        sink["remote"] = k["remote"]
        sink["worktree"] = k["worktree"]
        print(json.dumps({"success": True, "run_id": "01DISPATCH", "stage": k["stage"].id}))

    monkeypatch.setattr(launch, "launch_stage", _fake)


def test_in_flight_no_pr_dispatches_implement_remotely(monkeypatch):
    _authed(monkeypatch)
    sink: dict = {}
    _stub_launch(monkeypatch, sink)
    monkeypatch.setattr(plans, "get_plan", lambda **k: _plan_state(None))
    result = _invoke(monkeypatch, ["137", "--json"], objective_state=_state(_in_flight_nodes()))
    assert result.exit_code == 0
    payload = _payload(result)
    assert payload["action"] == "dispatched" and payload["stage"] == "implement"
    assert payload["next_action"] == "implement"
    assert payload["run_id"] == "01DISPATCH"
    assert sink["stage"] == "implement" and sink["remote"] == "" and sink["worktree"] is None


def test_in_flight_draft_pr_is_ready_for_review_not_redispatch(monkeypatch):
    _authed(monkeypatch)
    sink: dict = {}
    _stub_launch(monkeypatch, sink)
    monkeypatch.setattr(plans, "get_plan", lambda **k: _plan_state(_pr(is_draft=True)))
    result = _invoke(monkeypatch, ["137", "--json"], objective_state=_state(_in_flight_nodes()))
    assert result.exit_code == 0
    payload = _payload(result)
    assert payload["action"] == "ready_for_review" and payload["next_action"] == "ready_for_review"
    assert "called" not in sink  # the draft→re-implement regression guard


def test_in_flight_open_pr_unresolved_thread_dispatches_address(monkeypatch):
    _authed(monkeypatch)
    sink: dict = {}
    _stub_launch(monkeypatch, sink)
    monkeypatch.setattr(plans, "get_plan", lambda **k: _plan_state(_pr()))
    monkeypatch.setattr(github, "get_pr_feedback", lambda **k: _feedback(threads=(_thread(False),)))
    result = _invoke(monkeypatch, ["137", "--json"], objective_state=_state(_in_flight_nodes()))
    assert result.exit_code == 0
    payload = _payload(result)
    assert payload["action"] == "dispatched" and payload["stage"] == "address"
    assert payload["next_action"] == "address"
    assert sink["stage"] == "address"


def test_in_flight_open_pr_only_approved_awaits_review(monkeypatch):
    _authed(monkeypatch)
    sink: dict = {}
    _stub_launch(monkeypatch, sink)
    monkeypatch.setattr(plans, "get_plan", lambda **k: _plan_state(_pr()))
    monkeypatch.setattr(
        github,
        "get_pr_feedback",
        lambda **k: _feedback(reviews=(_review("alice", "APPROVED", "2024-01-01"),)),
    )
    result = _invoke(monkeypatch, ["137", "--json"], objective_state=_state(_in_flight_nodes()))
    assert result.exit_code == 0
    payload = _payload(result)
    assert payload["action"] == "awaiting_review" and payload["next_action"] == "awaiting_review"
    assert "called" not in sink


def test_in_flight_merged_pr_is_pending_reconcile(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(launch, "launch_stage", lambda **k: None)
    monkeypatch.setattr(plans, "get_plan", lambda **k: _plan_state(_pr(state="MERGED")))
    result = _invoke(monkeypatch, ["137", "--json"], objective_state=_state(_in_flight_nodes()))
    payload = _payload(result)
    # No `learn_state` header and no local marker → the merged plan reads as done.
    assert payload["action"] == "merged_pending_reconcile" and payload["next_action"] == "done"
    assert payload["remediation"] is None


def test_in_flight_merged_pr_learn_pending_names_the_local_remediation(monkeypatch):
    """A merged PR with `learn_state: pending` stays merged_pending_reconcile (learn is
    local-only — never dispatched) but surfaces `next_action: learn` + the resume remediation."""
    _authed(monkeypatch)
    sink: dict = {}
    _stub_launch(monkeypatch, sink)
    monkeypatch.setattr(
        plans,
        "get_plan",
        lambda **k: _plan_state(_pr(state="MERGED"), header={"learn_state": "pending"}),
    )
    result = _invoke(monkeypatch, ["137", "--json"], objective_state=_state(_in_flight_nodes()))
    assert result.exit_code == 0
    payload = _payload(result)
    assert payload["action"] == "merged_pending_reconcile" and payload["next_action"] == "learn"
    assert payload["remediation"] == "perk plan resume 7"
    assert "called" not in sink  # learn is never remote-dispatched
    assert "learn pending (run: perk plan resume 7)" in result.output


# --------------------------------------------------------------------------- completion


def _complete_nodes():
    return [
        objective.ObjectiveNode(id="1.1", description="A", status=N.DONE, pr="#7"),
        objective.ObjectiveNode(id="1.2", description="B", status=N.SKIPPED),
    ]


def test_complete_audits_and_closes(monkeypatch):
    _authed(monkeypatch)
    closed: dict = {}
    monkeypatch.setattr(plans, "close_issue", lambda **k: closed.update(k) or True)
    result = _invoke(monkeypatch, ["137", "--json"], objective_state=_state(_complete_nodes()))
    assert result.exit_code == 0
    payload = _payload(result)
    assert payload["action"] == "completed" and payload["closed"] is True
    assert closed["number"] == 137 and closed["dry_run"] is False
    assert payload["audit"] == [
        {"node": "1.1", "status": "done", "pr": "#7"},
        {"node": "1.2", "status": "skipped", "pr": None},
    ]


def test_complete_dry_run_does_not_close(monkeypatch):
    called: dict = {}

    def _close(**k):
        called.update(k)
        # Faithful to the real helper's dry-run contract: return False without shelling.
        return not k["dry_run"]

    monkeypatch.setattr(plans, "close_issue", _close)
    result = _invoke(
        monkeypatch, ["137", "--dry-run", "--json"], objective_state=_state(_complete_nodes())
    )
    assert result.exit_code == 0
    payload = _payload(result)
    assert payload["action"] == "completed" and payload["closed"] is False
    assert payload["dry_run"] is True
    # close_issue is invoked but with dry_run=True (the no-shell path).
    assert called.get("dry_run") is True


# --------------------------------------------------------------------------- active-run gate


class _FakeRunner:
    def __init__(self, statuses):
        self._statuses = list(statuses)
        self.kind = "fake"

    def observe(self, handle, *, repo_root):
        status = self._statuses.pop(0) if len(self._statuses) > 1 else self._statuses[0]
        return runner.RunObservation(status=status, conclusion=None, url="u")


def _record(*, objective_id="137", run_id="01RUN", with_handle=True):
    return cache.DispatchModel.model_validate(
        {
            "run_id": run_id,
            "stage": "implement",
            "plan_ref": {
                "provider": "github",
                "pr_id": "7",
                "url": "u/7",
                "labels": ["perk:plan"],
                "objective_id": objective_id,
            },
            "runner": "",
            "kind": "github-actions",
            "status": "dispatched",
            "dispatched_at": "2024-01-01T00:00:00+00:00",
            "run_handle": {"runner": "", "kind": "github-actions", "run_ref": "555", "url": "u"}
            if with_handle
            else None,
            "error": None,
        }
    ).to_domain()


def test_active_run_without_wait_is_awaiting_run(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(cache, "list_dispatch_records", lambda root: [_record()])
    monkeypatch.setattr(runner, "select_runner", lambda ref: _FakeRunner(["in_progress"]))
    monkeypatch.setattr(run_report, "read_outcome", lambda root, rid: None)
    launched: dict = {}
    monkeypatch.setattr(launch, "launch_stage", lambda **k: launched.update(called=True))
    result = _invoke(
        monkeypatch,
        ["137", "--json"],
        objective_state=_state(_in_flight_nodes()),
        stub_no_records=False,
    )
    assert result.exit_code == 0
    payload = _payload(result)
    assert payload["action"] == "awaiting_run" and payload["run_id"] == "01RUN"
    assert "called" not in launched


def test_active_run_with_wait_polls_then_reevaluates(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(cache, "list_dispatch_records", lambda root: [_record()])
    # in_progress, in_progress, then completed → the poll loop proceeds to re-evaluate selection.
    statuses = ["in_progress", "in_progress", "completed"]
    monkeypatch.setattr(runner, "select_runner", lambda ref: _FakeRunner(statuses))
    monkeypatch.setattr(run_report, "read_outcome", lambda root, rid: None)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    # After the run completes, the node still resolves (pr None → dispatch implement).
    monkeypatch.setattr(plans, "get_plan", lambda **k: _plan_state(None))
    sink: dict = {}
    _stub_launch(monkeypatch, sink)
    result = _invoke(
        monkeypatch,
        ["137", "--wait", "--json"],
        objective_state=_state(_in_flight_nodes()),
        stub_no_records=False,
    )
    assert result.exit_code == 0
    assert _payload(result)["action"] == "dispatched"


def test_active_run_with_wait_refetches_objective_state(monkeypatch):
    """After polling completes, selection must re-evaluate against FRESH objective state."""
    _authed(monkeypatch)
    monkeypatch.setattr(cache, "list_dispatch_records", lambda root: [_record()])
    # in_progress (active-run gate detects in-flight) → completed (poll loop settles).
    statuses = ["in_progress", "completed"]
    monkeypatch.setattr(runner, "select_runner", lambda ref: _FakeRunner(statuses))
    monkeypatch.setattr(run_report, "read_outcome", lambda root, rid: None)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    # First get_objective returns the in-flight snapshot; the post-poll re-fetch returns a state
    # whose node has advanced to a terminal roll-up (complete) — proving a re-fetch happened.
    states = iter([_state(_in_flight_nodes()), _state(_complete_nodes())])
    monkeypatch.setattr(objectives, "get_objective", lambda **k: next(states))
    monkeypatch.setattr(cache, "list_dispatch_records", lambda root: [_record()])
    monkeypatch.setattr(plans, "close_issue", lambda **k: True)
    cli_runner = CliRunner()
    with cli_runner.isolated_filesystem() as d:
        _git_init(d)
        result = cli_runner.invoke(cli, ["objective", "run", "137", "--wait", "--json"])
    assert result.exit_code == 0
    # Re-fetched state was complete → the supervisor audits + closes (not the stale in-flight path).
    assert _payload(result)["action"] == "completed"


def test_in_flight_missing_pr_id_falls_back_to_plan_required(monkeypatch):
    """An in-flight node with no `pr` backlink degrades to plan_required (D7 fallback)."""
    _authed(monkeypatch)
    monkeypatch.setattr(launch, "launch_stage", lambda **k: None)
    nodes = [
        objective.ObjectiveNode(id="1.1", description="A", status=N.DONE, depends_on=()),
        objective.ObjectiveNode(
            id="1.2", description="B", status=N.IN_PROGRESS, pr=None, depends_on=("1.1",)
        ),
    ]
    result = _invoke(monkeypatch, ["137", "--json"], objective_state=_state(nodes))
    assert result.exit_code == 0
    payload = _payload(result)
    assert payload["action"] == "plan_required" and payload["node"] == "1.2"


def test_in_flight_opaque_pr_id_is_passed_to_the_backend(monkeypatch):
    """Any non-empty `pr` backlink IS the plan id — passed to the backend verbatim
    (the Linear `#ENG-N` shape resolves; the backend is the authority on junk ids)."""
    _authed(monkeypatch)
    monkeypatch.setattr(launch, "launch_stage", lambda **k: None)
    seen: list[int] = []

    def _get_plan(**k):
        seen.append(k["number"])
        return _plan_state(pr=_pr(state="MERGED"))

    monkeypatch.setattr(plans, "get_plan", _get_plan)
    nodes = [
        objective.ObjectiveNode(
            id="1.1", description="A", status=N.IN_PROGRESS, pr="#7", depends_on=()
        ),
    ]
    result = _invoke(monkeypatch, ["137", "--json"], objective_state=_state(nodes))
    assert result.exit_code == 0
    assert seen == [7]
    payload = _payload(result)
    assert payload["action"] == "merged_pending_reconcile" and payload["node"] == "1.1"


def test_active_run_with_wait_timeout_is_inconclusive(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(cache, "list_dispatch_records", lambda root: [_record()])
    monkeypatch.setattr(runner, "select_runner", lambda ref: _FakeRunner(["in_progress"]))
    monkeypatch.setattr(run_report, "read_outcome", lambda root, rid: None)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    monkeypatch.setattr(run_cmd, "POLL_TIMEOUT_S", 30)
    result = _invoke(
        monkeypatch,
        ["137", "--wait", "--json"],
        objective_state=_state(_in_flight_nodes()),
        stub_no_records=False,
    )
    assert result.exit_code == 0
    payload = _payload(result)
    assert payload["action"] == "awaiting_run" and payload["timed_out"] is True


# --------------------------------------------------------------------------- cumulative budget


def test_cumulative_budget_sums_this_objective_only(monkeypatch):
    _authed(monkeypatch)
    records = [
        _record(run_id="01A"),
        _record(run_id="01B"),
        _record(run_id="01C", objective_id="999"),  # a different objective — excluded
    ]
    monkeypatch.setattr(cache, "list_dispatch_records", lambda root: records)
    monkeypatch.setattr(runner, "select_runner", lambda ref: _FakeRunner(["completed"]))

    def _outcome(root, rid):
        return {"budget": {"turns": 3, "tokens": 1000, "elapsed_ms": 60000}}

    monkeypatch.setattr(run_report, "read_outcome", _outcome)
    monkeypatch.setattr(plans, "get_plan", lambda **k: _plan_state(None))
    sink: dict = {}
    _stub_launch(monkeypatch, sink)
    result = _invoke(
        monkeypatch,
        ["137", "--json"],
        objective_state=_state(_in_flight_nodes()),
        stub_no_records=False,
    )
    assert result.exit_code == 0
    budget = _payload(result)["budget"]
    assert budget == {"runs": 2, "turns": 6, "tokens": 2000, "elapsed_ms": 120000}


# --------------------------------------------------------------------------- dry-run


def test_dry_run_dispatch_writes_nothing_and_skips_launch(monkeypatch):
    sink: dict = {}
    _stub_launch(monkeypatch, sink)
    monkeypatch.setattr(plans, "get_plan", lambda **k: _plan_state(None))
    result = _invoke(
        monkeypatch, ["137", "--dry-run", "--json"], objective_state=_state(_in_flight_nodes())
    )
    assert result.exit_code == 0
    payload = _payload(result)
    assert payload["action"] == "dispatched" and payload["stage"] == "implement"
    assert payload["run_id"] is None and payload["dry_run"] is True
    assert "called" not in sink  # no launch_stage, no mint/write under --dry-run


# --------------------------------------------------------------- discovery-first gate (§8.20)

_ULID = "01HZXW8T2M3N4P5Q6R7S8T9V0W"


def _discovered_run(*, plan_id="7", status="in_progress", run_id=_ULID):
    return runner.DiscoveredRun(
        run_id=run_id,
        stage="implement",
        plan_id=plan_id,
        dispatched_at="2026-06-07T12:00:00Z",
        status=status,
        conclusion=None,
        handle=runner.RunHandle(runner="", kind="github-actions", run_ref="999", url="u/999"),
    )


def test_gate_works_from_a_fresh_clone_via_discovery(monkeypatch):
    """Zero local records + a discovered in-flight run matching a node backlink ⇒ awaiting_run
    (the fresh-clone acceptance: the gate never double-dispatches)."""
    _authed(monkeypatch)
    monkeypatch.setattr(discovery, "discover_runs", lambda root, *, limit=100: [_discovered_run()])
    launched: dict = {}
    monkeypatch.setattr(launch, "launch_stage", lambda **k: launched.update(called=True))
    result = _invoke(monkeypatch, ["137", "--json"], objective_state=_state(_in_flight_nodes()))
    assert result.exit_code == 0
    payload = _payload(result)
    assert payload["action"] == "awaiting_run" and payload["run_id"] == _ULID
    assert "called" not in launched


def test_gate_ignores_runs_for_other_plans(monkeypatch):
    """A discovered in-flight run whose plan id matches no node backlink does not gate."""
    _authed(monkeypatch)
    monkeypatch.setattr(
        discovery, "discover_runs", lambda root, *, limit=100: [_discovered_run(plan_id="888")]
    )
    monkeypatch.setattr(plans, "get_plan", lambda **k: _plan_state(None))
    sink: dict = {}
    _stub_launch(monkeypatch, sink)
    result = _invoke(monkeypatch, ["137", "--json"], objective_state=_state(_in_flight_nodes()))
    assert result.exit_code == 0
    assert _payload(result)["action"] == "dispatched"


def test_gate_ignores_completed_discovered_runs(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(
        discovery,
        "discover_runs",
        lambda root, *, limit=100: [_discovered_run(status="completed")],
    )
    monkeypatch.setattr(plans, "get_plan", lambda **k: _plan_state(None))
    sink: dict = {}
    _stub_launch(monkeypatch, sink)
    result = _invoke(monkeypatch, ["137", "--json"], objective_state=_state(_in_flight_nodes()))
    assert result.exit_code == 0
    assert _payload(result)["action"] == "dispatched"


def test_gate_discovery_error_falls_back_to_local_records(monkeypatch):
    """The autouse offline default raises — the gate degrades to the legacy local loop."""
    _authed(monkeypatch)
    monkeypatch.setattr(cache, "list_dispatch_records", lambda root: [_record()])
    monkeypatch.setattr(runner, "select_runner", lambda ref: _FakeRunner(["in_progress"]))
    monkeypatch.setattr(run_report, "read_outcome", lambda root, rid: None)
    result = _invoke(
        monkeypatch,
        ["137", "--json"],
        objective_state=_state(_in_flight_nodes()),
        stub_no_records=False,
    )
    assert result.exit_code == 0
    payload = _payload(result)
    assert payload["action"] == "awaiting_run" and payload["run_id"] == "01RUN"
    assert "run discovery unavailable" in result.output


def test_gate_wait_polls_the_reconstructed_handle(monkeypatch):
    """--wait polls the discovery-reconstructed handle to completion, then re-evaluates."""
    _authed(monkeypatch)
    monkeypatch.setattr(discovery, "discover_runs", lambda root, *, limit=100: [_discovered_run()])
    polled: list[str] = []

    class _PollRunner:
        kind = "fake"

        def observe(self, handle, *, repo_root):
            polled.append(handle.run_ref)
            return runner.RunObservation(status="completed", conclusion="success", url="u")

    monkeypatch.setattr(runner, "select_runner", lambda ref: _PollRunner())
    monkeypatch.setattr("time.sleep", lambda _s: None)
    monkeypatch.setattr(plans, "get_plan", lambda **k: _plan_state(None))
    sink: dict = {}
    _stub_launch(monkeypatch, sink)
    result = _invoke(
        monkeypatch, ["137", "--wait", "--json"], objective_state=_state(_in_flight_nodes())
    )
    assert result.exit_code == 0
    assert _payload(result)["action"] == "dispatched"
    assert polled == ["999"]  # the handle came from discovery, not a local record


# --------------------------------------------------------------------------- stacked selection


def _stacked_state(nodes):
    return objectives.ObjectiveState(
        number=137,
        url="u/137",
        title="Ship it",
        header={
            "run_id": "01RID",
            "delivery": "stacked",
            "delivery_lineage": "01JB0000000000000000000000",
        },
        nodes=tuple(nodes),
    )


def _stacked_selection(kind, node=None, *, reason=None):
    from perk.cli.commands.objective.shared import StackedSelection

    return StackedSelection(
        kind=kind,
        node=node,
        ready=kind in ("plannable", "in_flight"),
        reason=reason,
        train=None,
    )


def test_stacked_build_blocked_is_an_honest_report_arm(monkeypatch):
    # A readiness veto surfaces as action=build_blocked (exit 0, a report arm like `blocked`)
    # with the exact reason + the stack-status remediation — never a dispatch.
    _authed(monkeypatch)
    monkeypatch.setattr(
        run_cmd,
        "stacked_selection",
        lambda *_a: _stacked_selection("build_blocked", reason="[checkpoint_drift] x"),
    )
    launched: dict = {}
    monkeypatch.setattr(launch, "launch_stage", lambda **k: launched.update(called=True))
    nodes = [objective.ObjectiveNode(id="1.1", description="A", status=N.PENDING)]
    result = _invoke(monkeypatch, ["137", "--json"], objective_state=_stacked_state(nodes))
    assert result.exit_code == 0
    payload = _payload(result)
    assert payload["action"] == "build_blocked"
    assert payload["reason"] == "[checkpoint_drift] x"
    assert payload["remediation"] == "perk objective stack status 137"
    assert "called" not in launched
    assert "build blocked" in result.output  # the human render arm


def _train_layer(
    node_id: str,
    plan_id: str,
    pr_number: int | None,
    *,
    published: bool,
) -> train_mod.TrainLayer:
    return train_mod.TrainLayer(
        node_id=node_id,
        plan_id=plan_id,
        branch=f"plan-{plan_id}",
        pr_number=pr_number,
        intent=train_mod.LayerIntent.PLANNED,
        publication=(
            train_mod.LayerPublication.PUBLISHED
            if published
            else train_mod.LayerPublication.UNPUBLISHED
        ),
        git=train_mod.LayerGit.SYNCED if published else train_mod.LayerGit.ABSENT,
        pr=train_mod.LayerPr.DRAFT if pr_number is not None else train_mod.LayerPr.ABSENT,
        membership=train_mod.LayerMembership.EXACT,
        writer=train_mod.LayerWriter.FREE,
        finalization=train_mod.LayerFinalization.NOT_MERGED,
        parent_checkpoint_sha="p" * 40 if published else None,
        published_head_sha="h" * 40 if published else None,
        observed_remote_head_sha="h" * 40 if published else None,
        observed_pr_base="main" if published else None,
        expected_pr_base="main",
    )


def _supervisor_train(
    layers: tuple[train_mod.TrainLayer, ...],
    *,
    findings: tuple[train_mod.TrainFinding, ...] = (),
    unresolved: tuple[train_mod.UnresolvedOperationFacts, ...] = (),
) -> train_mod.DeliveryTrain:
    next_node = next(
        (
            layer.node_id
            for layer in layers
            if layer.publication is not train_mod.LayerPublication.PUBLISHED
        ),
        None,
    )
    return train_mod.DeliveryTrain(
        objective_id="137",
        objective_url="u/137",
        delivery_lineage="01JB0000000000000000000000",
        base="main",
        redirected_from=None,
        layers=layers,
        published_prefix_len=sum(
            layer.publication is train_mod.LayerPublication.PUBLISHED for layer in layers
        ),
        unresolved_operation=unresolved[0] if unresolved else None,
        findings=findings,
        build_readiness=train_mod.BuildReadiness(
            next_node_id=next_node,
            ready=next_node is not None and not findings and not unresolved,
            reason="all layers published" if next_node is None else None,
        ),
        unresolved_operations=unresolved,
    )


@pytest.mark.parametrize(
    ("selection_kind", "upper_status", "upper_plan"),
    [("plannable", N.PENDING, None), ("in_flight", N.IN_PROGRESS, "#7")],
)
def test_lower_layer_address_outranks_upper_work(
    monkeypatch, selection_kind, upper_status, upper_plan
):
    _authed(monkeypatch)
    lower = objective.ObjectiveNode(id="1.1", description="A", status=N.IN_PROGRESS, pr="#6")
    upper = objective.ObjectiveNode(id="1.2", description="B", status=upper_status, pr=upper_plan)
    train = _supervisor_train(
        (
            _train_layer("1.1", "6", 41, published=True),
            _train_layer("1.2", "7", None, published=False),
        )
    )
    selection = _stacked_selection(selection_kind, upper)
    selection = selection.__class__(**{**selection.__dict__, "train": train})
    monkeypatch.setattr(run_cmd, "stacked_selection", lambda *_a: selection)
    monkeypatch.setattr(
        plans,
        "get_plan",
        lambda **kwargs: plans.PlanState(
            number=6,
            url="u/6",
            title="Lower",
            header={"objective_id": "137"},
            pr=_pr(number=41),
        ),
    )
    monkeypatch.setattr(
        github, "get_pr_feedback", lambda **kwargs: _feedback(threads=(_thread(False),))
    )
    sink: dict = {}
    _stub_launch(monkeypatch, sink)
    result = _invoke(
        monkeypatch,
        ["137", "--json"],
        objective_state=_stacked_state((lower, upper)),
    )
    payload = _payload(result)
    assert payload["action"] == "dispatched"
    assert payload["stage"] == "address" and payload["node"] == "1.1"
    assert payload["next_action"] == "address"
    assert sink["stage"] == "address"


def test_lower_review_waits_fall_through_to_upper_work(monkeypatch):
    _authed(monkeypatch)
    draft = objective.ObjectiveNode(id="1.1", description="A", status=N.IN_PROGRESS, pr="#6")
    awaiting = objective.ObjectiveNode(id="1.2", description="B", status=N.IN_PROGRESS, pr="#7")
    upper = objective.ObjectiveNode(id="1.3", description="C", status=N.PENDING)
    train = _supervisor_train(
        (
            _train_layer("1.1", "6", 41, published=True),
            _train_layer("1.2", "7", 42, published=True),
            _train_layer("1.3", "8", None, published=False),
        )
    )
    selection = _stacked_selection("plannable", upper)
    selection = selection.__class__(**{**selection.__dict__, "train": train})
    monkeypatch.setattr(run_cmd, "stacked_selection", lambda *_a: selection)

    def get_plan(**kwargs):
        number = kwargs["number"]
        return plans.PlanState(
            number=number,
            url=f"u/{number}",
            title="Lower",
            header={},
            pr=_pr(number=40 + number, is_draft=number == 6),
        )

    monkeypatch.setattr(plans, "get_plan", get_plan)
    feedback_calls: list[int] = []

    def feedback(**kwargs):
        feedback_calls.append(kwargs["pr_number"])
        return _feedback()

    monkeypatch.setattr(github, "get_pr_feedback", feedback)
    result = _invoke(
        monkeypatch,
        ["137", "--json"],
        objective_state=_stacked_state((draft, awaiting, upper)),
    )
    payload = _payload(result)
    assert payload["action"] == "plan_required" and payload["node"] == "1.3"
    assert feedback_calls == [47]  # draft plan #6 never fetched; plan #7 awaited review


def test_all_published_unresolved_operation_is_repair_required(monkeypatch):
    _authed(monkeypatch)
    node = objective.ObjectiveNode(id="1.1", description="A", status=N.IN_PROGRESS, pr="#7")
    operation = train_mod.UnresolvedOperationFacts("01OP", "sync", "t0")
    train = _supervisor_train(
        (_train_layer("1.1", "7", 42, published=True),), unresolved=(operation,)
    )
    selection = _stacked_selection("no_candidate")
    selection = selection.__class__(**{**selection.__dict__, "train": train})
    monkeypatch.setattr(run_cmd, "stacked_selection", lambda *_a: selection)
    result = _invoke(monkeypatch, ["137", "--json"], objective_state=_stacked_state((node,)))
    payload = _payload(result)
    assert payload["action"] == "repair_required"
    assert payload["reason"] == "operation 01OP (sync, prepared t0)"
    assert payload["remediation"] == "perk objective stack recover 137"
    assert "repair required" in result.output


def test_train_veto_precedes_lower_reads_and_upper_dispatch(monkeypatch):
    _authed(monkeypatch)
    lower = objective.ObjectiveNode(id="1.1", description="A", status=N.IN_PROGRESS, pr="#6")
    upper = objective.ObjectiveNode(id="1.2", description="B", status=N.IN_PROGRESS, pr="#7")
    operation = train_mod.UnresolvedOperationFacts("01OP", "sync", "t0")
    train = _supervisor_train(
        (
            _train_layer("1.1", "6", 41, published=True),
            _train_layer("1.2", "7", None, published=False),
        ),
        unresolved=(operation,),
    )
    selection = _stacked_selection("in_flight", upper)
    selection = selection.__class__(**{**selection.__dict__, "train": train})
    monkeypatch.setattr(run_cmd, "stacked_selection", lambda *_a: selection)
    monkeypatch.setattr(
        plans,
        "get_plan",
        lambda **kwargs: pytest.fail("veto must precede lower plan reads"),
    )
    monkeypatch.setattr(
        github,
        "get_pr_feedback",
        lambda **kwargs: pytest.fail("veto must precede feedback reads"),
    )
    monkeypatch.setattr(
        run_cmd,
        "_dispatch_stage_remote",
        lambda **kwargs: pytest.fail("veto must precede upper dispatch"),
    )

    result = _invoke(
        monkeypatch,
        ["137", "--json"],
        objective_state=_stacked_state((lower, upper)),
    )
    payload = _payload(result)
    assert payload["action"] == "repair_required"
    assert payload["remediation"] == "perk objective stack recover 137"


def test_stacked_plannable_uses_the_helper_candidate(monkeypatch):
    _authed(monkeypatch)
    candidate = objective.ObjectiveNode(id="2.2", description="B", status=N.PENDING)
    monkeypatch.setattr(
        run_cmd, "stacked_selection", lambda *_a: _stacked_selection("plannable", candidate)
    )
    nodes = [
        objective.ObjectiveNode(id="1.1", description="A", status=N.PENDING),
        candidate,
    ]
    result = _invoke(monkeypatch, ["137", "--json"], objective_state=_stacked_state(nodes))
    assert result.exit_code == 0
    payload = _payload(result)
    assert payload["action"] == "plan_required"
    assert payload["node"] == "2.2"  # the readiness-derived candidate, not the graph's 1.1
    assert payload["remediation"] == "perk objective plan 137 --node 2.2"


def test_stacked_dry_run_keeps_the_offline_graph_classification(monkeypatch):
    # --dry-run never reconstructs the train — the helper must not be consulted — and the
    # payload SAYS the readiness check was skipped rather than pretending it ran.
    _authed(monkeypatch)
    monkeypatch.setattr(
        run_cmd,
        "stacked_selection",
        lambda *_a: pytest.fail("dry run must not reconstruct the train"),
    )
    nodes = [objective.ObjectiveNode(id="1.1", description="A", status=N.PENDING)]
    result = _invoke(
        monkeypatch, ["137", "--dry-run", "--json"], objective_state=_stacked_state(nodes)
    )
    assert result.exit_code == 0
    payload = _payload(result)
    assert payload["action"] == "plan_required" and payload["node"] == "1.1"
    assert payload["build_readiness"] == "unchecked (dry-run)"


def test_incremental_dry_run_payload_has_no_build_readiness(monkeypatch):
    _authed(monkeypatch)
    nodes = [objective.ObjectiveNode(id="1.1", description="A", status=N.PENDING)]
    result = _invoke(monkeypatch, ["137", "--dry-run", "--json"], objective_state=_state(nodes))
    assert result.exit_code == 0
    assert "build_readiness" not in _payload(result)
