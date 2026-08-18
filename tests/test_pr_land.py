"""CLI-layer tests for the migrated `perk pr land` thin mapper over ``Delivery.land``.

The merge/ready/refusal-ordering matrix lives at the façade/engine layer
(`tests/test_delivery_facade.py`); the finalization bookkeeping matrix stays in
`tests/test_delivery_finalize.py`. This file pins the mapper: the exact reconstructed
``LandRequest``, the caller-owned marker + Linear emission, the byte-stable envelopes, and the
``DeliveryError`` → exit-1 mapping.
"""

import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk import delivery, github, plan
from perk.backends.issue_backend import IssueBackendError
from perk.backends.linear import agent as linear_agent
from perk.cli.cli import cli
from perk.cli.commands.pr import land_cmd
from perk.cli.commands.pr.land_cmd import (
    PrLandResult,
    _landed_summary,
    _render_human,
    _result_to_dict,
)
from perk.delivery._fakes import FakeDeliveryGit, FakeDeliveryGitHub, FakeDeliveryPersistence
from perk.state import cache

_REF = {
    "provider": "github",
    "pr_id": "7",
    "url": "https://gh/o/r/issues/7",
    "labels": ["perk:plan"],
    "objective_id": None,
}


def _ref(**over: object) -> plan.PlanRef:
    """Build a plan.PlanRef from the canonical _REF defaults plus overrides."""
    return plan.PlanRefModel.model_validate({**_REF, **over}).to_domain()


def _git_init(path, factory) -> None:
    factory(path)


def _authed(monkeypatch) -> None:
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(True, "octocat", ("repo",), None)
    )


def _merged_detail(**over: object) -> delivery.LandResult.Plan:
    fields: dict[str, object] = {
        "dry_run": False,
        "pr": delivery.LandResult.MergedPr(number=42, state="MERGED"),
        "objective": delivery.LandResult.ObjectiveUpdate(None, (), "no_objective_link"),
        "learn": delivery.LandResult.LearnUpdate((), "no_consumed_learn"),
        "plan_issue_closed": False,
        "learn_state": "pending",
    }
    fields.update(over)
    return delivery.LandResult.Plan(**fields)  # type: ignore[arg-type]


def _dry_run_detail() -> delivery.LandResult.Plan:
    return delivery.LandResult.Plan(
        dry_run=True,
        pr=delivery.LandResult.MergedPr(number=0, state="OPEN"),
        objective=delivery.LandResult.ObjectiveUpdate(None, (), "dry_run"),
        learn=delivery.LandResult.LearnUpdate((), "dry_run"),
    )


def _bind_land_delivery(
    monkeypatch,
    *,
    detail: delivery.LandResult.Plan | None = None,
    error: Exception | None = None,
) -> list[delivery.LandRequest]:
    """Bind a scripted Delivery subclass (the migrated-command convention)."""
    requests: list[delivery.LandRequest] = []

    class _LandDelivery(delivery.Delivery):
        def land(self, request: delivery.LandRequest) -> delivery.LandResult:
            requests.append(request)
            if error is not None:
                raise error
            scripted = detail
            if scripted is None:
                scripted = _dry_run_detail() if request.dry_run else _merged_detail()
            return delivery.LandResult(kind="plan", plan=scripted)

    service = _LandDelivery(
        persistence=FakeDeliveryPersistence(),
        git=FakeDeliveryGit(),
        github=FakeDeliveryGitHub(),
    )
    monkeypatch.setattr(delivery, "resolve_delivery", lambda _root: service)
    return requests


def _run(args, *, write_ref=True):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        if write_ref:
            cache.write_plan_ref(Path(d), _ref())
        return runner.invoke(cli, args)


def test_dry_run_is_offline_and_sets_no_marker(unborn_git_repo_factory):
    # Deliberately UNSTUBBED: the real resolve_delivery + façade dry-run early return must be
    # fully offline (no gh, no backend/config/credential reads) — anything network-bound would
    # crash here, not pass.
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        cache.write_plan_ref(Path(d), _ref())
        result = runner.invoke(cli, ["pr", "land", "--dry-run", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["success"] is True and data["dry_run"] is True
        assert data["branch"] == "plan-7" and data["pending_learn"] is False
        assert data["issue"] == "7"  # opaque string id (contracts §8.21)
        assert not cache.has_marker(Path(d), cache.PENDING_LEARN)


def test_dry_run_request_rides_the_scripted_service(monkeypatch):
    requests = _bind_land_delivery(monkeypatch)
    result = _run(["pr", "land", "--dry-run", "--json"])
    assert result.exit_code == 0
    assert requests == [
        delivery.LandRequest(kind="plan", plan_id="7", branch="plan-7", dry_run=True)
    ]


def test_no_plan_ref_exits_1():
    result = _run(["pr", "land", "--dry-run", "--json"], write_ref=False)
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "no_plan_ref"


def test_not_a_repo_exits_2():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["pr", "land", "--dry-run", "--json"])
    assert result.exit_code == 2
    assert json.loads(result.output)["error_type"] == "not_a_repo"


def test_real_land_builds_the_exact_request_and_sets_marker(monkeypatch, unborn_git_repo_factory):
    _authed(monkeypatch)
    requests = _bind_land_delivery(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        cache.write_plan_ref(Path(d), _ref(objective_id="5", base="develop", delivery_lineage=None))
        result = runner.invoke(cli, ["pr", "land", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["pr"] == {"number": 42, "state": "MERGED"}
        assert data["pending_learn"] is True
        assert cache.has_marker(Path(d), cache.PENDING_LEARN)
    assert requests == [
        delivery.LandRequest(
            kind="plan",
            plan_id="7",
            branch="plan-7",
            objective_id="5",
            consumed_learn=(),
            delivery_lineage=None,
            dry_run=False,
        )
    ]


def test_learn_docs_plan_is_exempt_from_the_marker(monkeypatch, unborn_git_repo_factory):
    # A learn-docs consolidation plan (non-empty consumed_learn) is exempt from the land→learn
    # cycle: no marker, `pending_learn: false` in the envelope.
    _authed(monkeypatch)
    requests = _bind_land_delivery(
        monkeypatch,
        detail=_merged_detail(
            learn=delivery.LandResult.LearnUpdate(("45",), None), learn_state="skipped"
        ),
    )
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        cache.write_plan_ref(Path(d), _ref(consumed_learn=["45"]))
        result = runner.invoke(cli, ["pr", "land", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["pending_learn"] is False
        assert data["learn_state"] == "skipped"
        assert data["learn"] == {"closed": ["45"], "skipped_reason": None}
        assert not cache.has_marker(Path(d), cache.PENDING_LEARN)
    assert requests[0].consumed_learn == ("45",)


def test_real_land_carries_the_cached_lineage_verbatim(monkeypatch, unborn_git_repo_factory):
    # The mapper never interprets the lineage — the façade owns the refusal; the request
    # carries the cached ref's value verbatim.
    _authed(monkeypatch)
    refusal = delivery.DeliveryError(
        "plan #7 carries stacked delivery lineage — stacked layers land only as one "
        "atomic train, never individually\n"
        "Landing one layer merges into its parent branch and tears the train. "
        "Inspect the train with: perk objective stack status",
        error_type="stacked_plan",
        phase="land",
        origin="domain",
    )
    requests = _bind_land_delivery(monkeypatch, error=refusal)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        cache.write_plan_ref(Path(d), _ref(delivery_lineage="dlv-1"))
        result = runner.invoke(cli, ["pr", "land", "--json"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["error_type"] == "stacked_plan"
        # Domain refusals render bare — byte-identical to the pre-migration refusal.
        assert data["message"] == str(refusal)
        assert not cache.has_marker(Path(d), cache.PENDING_LEARN)
    assert requests[0].delivery_lineage == "dlv-1"


def test_domain_refusals_render_bare(monkeypatch, unborn_git_repo_factory):
    _authed(monkeypatch)
    for error_type, message in (
        ("plan_not_found", "Plan issue #7 not found"),
        ("no_pr", "No PR found for branch 'plan-7'\nRun /submit first."),
    ):
        _bind_land_delivery(
            monkeypatch,
            error=delivery.DeliveryError(
                message, error_type=error_type, phase="land", origin="domain"
            ),
        )
        runner = CliRunner()
        with runner.isolated_filesystem() as d:
            _git_init(d, unborn_git_repo_factory)
            cache.write_plan_ref(Path(d), _ref())
            result = runner.invoke(cli, ["pr", "land", "--json"])
            assert result.exit_code == 1
            data = json.loads(result.output)
            assert data["error_type"] == error_type
            assert data["message"] == message
            assert data["dry_run"] is False


def test_infra_failure_keeps_the_pr_land_failed_prefix(monkeypatch, unborn_git_repo_factory):
    _authed(monkeypatch)
    _bind_land_delivery(
        monkeypatch,
        error=delivery.DeliveryError(
            "gh exploded", error_type="github_error", phase="land", origin="github"
        ),
    )
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        cache.write_plan_ref(Path(d), _ref())
        result = runner.invoke(cli, ["pr", "land", "--json"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["error_type"] == "github_error"
        assert data["message"] == "PR land failed\ngh exploded"
        assert not cache.has_marker(Path(d), cache.PENDING_LEARN)


def test_json_envelope_passes_the_facade_detail_through(monkeypatch, unborn_git_repo_factory):
    _authed(monkeypatch)
    _bind_land_delivery(
        monkeypatch,
        detail=_merged_detail(
            objective=delivery.LandResult.ObjectiveUpdate("5", ("1.1",), None, closed=False),
            plan_issue_closed=True,
        ),
    )
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        cache.write_plan_ref(Path(d), _ref(objective_id="5"))
        result = runner.invoke(cli, ["pr", "land", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["objective"] == {
            "id": "5",
            "nodes_marked": ["1.1"],
            "skipped_reason": None,
            "closed": False,
        }
        assert data["plan_issue_closed"] is True
        assert data["learn_state"] == "pending"


# --- the caller-owned Linear agent "landed" activity emission ---------------------------


def test_real_land_calls_linear_agent_landed(monkeypatch):
    """The land hook fires after the façade call, with the PR number and the objective-node
    summary (the emitter itself gates on the stamped provider + token)."""
    _authed(monkeypatch)
    _bind_land_delivery(
        monkeypatch,
        detail=_merged_detail(objective=delivery.LandResult.ObjectiveUpdate("5", ("1.1",), None)),
    )
    emitted: list[dict] = []
    monkeypatch.setattr(
        land_cmd.linear_agent, "emit_landed", lambda _root, **kw: emitted.append(kw)
    )
    result = _run(["pr", "land", "--json"])
    assert result.exit_code == 0
    assert len(emitted) == 1
    assert emitted[0]["pr_number"] == 42
    assert emitted[0]["summary"] == "Objective #5: marked node(s) 1.1 done."


def test_dry_run_land_never_calls_linear_agent(monkeypatch):
    _bind_land_delivery(monkeypatch)
    emitted: list[dict] = []
    monkeypatch.setattr(
        land_cmd.linear_agent, "emit_landed", lambda _root, **kw: emitted.append(kw)
    )
    result = _run(["pr", "land", "--dry-run", "--json"])
    assert result.exit_code == 0
    assert emitted == []


def test_linear_agent_failure_leaves_land_payload_byte_identical(monkeypatch):
    """Fail-soft: a broken emitter substrate (gate forced open) never changes the --json payload
    or exit code."""
    _authed(monkeypatch)
    _bind_land_delivery(monkeypatch)
    baseline = _run(["pr", "land", "--json"])
    assert baseline.exit_code == 0

    monkeypatch.setattr(linear_agent, "emission_enabled", lambda *_a, **_k: True)
    monkeypatch.setattr(
        cache,
        "read_agent_session",
        lambda _r: cache.AgentSession(session_id="sess-1", issue="7"),
    )

    def boom(_environ):
        raise IssueBackendError("agent substrate down")

    monkeypatch.setattr(linear_agent, "agent_client_from_env", boom)
    result = _run(["pr", "land", "--json"])
    assert result.exit_code == 0
    assert result.stdout == baseline.stdout  # the --json payload is byte-identical
    assert "landed emission skipped (non-fatal)" in result.stderr


def test_landed_summary_lines():
    assert _landed_summary(delivery.LandResult.ObjectiveUpdate(None, (), "no_objective_link")) == ""
    assert (
        _landed_summary(delivery.LandResult.ObjectiveUpdate("9", ("2.1",), None))
        == "Objective #9: marked node(s) 2.1 done."
    )
    assert (
        _landed_summary(delivery.LandResult.ObjectiveUpdate("9", ("2.1", "2.2"), None, closed=True))
        == "Objective #9: marked node(s) 2.1, 2.2 done. Objective complete — closed."
    )


def test_result_to_dict_carries_objective():
    result = PrLandResult(
        pr=delivery.LandResult.MergedPr(number=42, state="MERGED"),
        branch="plan-7",
        issue="7",
        pending_learn=True,
        dry_run=False,
        objective=delivery.LandResult.ObjectiveUpdate("5", ("1.1",), None),
        learn=delivery.LandResult.LearnUpdate(("45", "50"), None),
    )
    data = _result_to_dict(result)
    # Opaque string ids at the machine boundary (contracts §8.21).
    assert data["issue"] == "7"
    assert data["plan_issue_closed"] is False
    assert data["objective"] == {
        "id": "5",
        "nodes_marked": ["1.1"],
        "skipped_reason": None,
        "closed": False,
    }
    assert data["learn"] == {"closed": ["45", "50"], "skipped_reason": None}


def _land_result(
    learn: delivery.LandResult.LearnUpdate, *, learn_state: str | None = "pending"
) -> PrLandResult:
    return PrLandResult(
        pr=delivery.LandResult.MergedPr(number=42, state="MERGED"),
        branch="plan-7",
        issue="7",
        pending_learn=True,
        dry_run=False,
        objective=delivery.LandResult.ObjectiveUpdate(None, (), "no_objective_link"),
        learn=learn,
        learn_state=learn_state,
    )


def test_render_human_surfaces_non_benign_learn_skip(capsys):
    # A non-benign skip (a partial `failed: …`) is surfaced, not silent.
    _render_human(_land_result(delivery.LandResult.LearnUpdate(("45",), "failed: #50")))
    out = capsys.readouterr().err
    assert "consolidated learn issue(s) #45" in out
    assert "learn consume incomplete: failed: #50" in out


def test_render_human_quiet_on_benign_learn_skip(capsys):
    # `no_consumed_learn` is the ordinary non-factory case — stay quiet.
    _render_human(_land_result(delivery.LandResult.LearnUpdate((), "no_consumed_learn")))
    out = capsys.readouterr().err
    assert "learn consume incomplete" not in out


def test_render_human_warns_on_a_failed_learn_state_stamp(capsys):
    _render_human(
        _land_result(delivery.LandResult.LearnUpdate((), "no_consumed_learn"), learn_state=None)
    )
    out = capsys.readouterr().err
    assert "learn-state stamp failed" in out


def test_render_human_reports_close_and_objective_lines(capsys):
    result = PrLandResult(
        pr=delivery.LandResult.MergedPr(number=42, state="MERGED"),
        branch="plan-7",
        issue="7",
        pending_learn=True,
        dry_run=False,
        objective=delivery.LandResult.ObjectiveUpdate("5", ("1.1", "1.2"), None, closed=True),
        learn=delivery.LandResult.LearnUpdate((), "no_consumed_learn"),
        plan_issue_closed=True,
        learn_state="pending",
    )
    _render_human(result)
    out = capsys.readouterr().err
    assert "plan issue closed explicitly" in out
    assert "objective #5: marked node(s) 1.1, 1.2 done" in out
    assert "objective #5 complete — closed" in out
    assert "learn_state=pending" in out


def test_dry_run_learn_is_inert(unborn_git_repo_factory):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        cache.write_plan_ref(Path(d), _ref(consumed_learn=["45"]))
        result = runner.invoke(cli, ["pr", "land", "--dry-run", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["learn"] == {"closed": [], "skipped_reason": "dry_run"}


def test_dry_run_objective_is_inert(unborn_git_repo_factory):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        cache.write_plan_ref(Path(d), _ref(objective_id="5"))
        result = runner.invoke(cli, ["pr", "land", "--dry-run", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["objective"] == {
            "id": None,
            "nodes_marked": [],
            "skipped_reason": "dry_run",
            "closed": False,
        }
