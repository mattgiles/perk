import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk import github, plan
from perk.backends.github import plans
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
from perk.delivery import LearnConsumeUpdate, ObjectiveLandUpdate
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


def _stub_land(
    monkeypatch,
    *,
    draft: bool,
    merged: bool = False,
    title: str = "My Feature",
    base_ref: str = "",
    header: dict | None = None,
) -> dict[str, object]:
    stamps: list[dict] = []
    calls: dict[str, object] = {
        "readied": False,
        "merged": False,
        "commit_message": None,
        "header_stamps": stamps,
    }
    state = "MERGED" if merged else "OPEN"
    monkeypatch.setattr(
        github,
        "find_pr_for_branch",
        lambda **k: github.PullRequest(
            number=42, url="u/pr/42", is_draft=draft, state=state, existed=True, base_ref=base_ref
        ),
    )
    monkeypatch.setattr(
        plans,
        "get_plan",
        lambda **k: plans.PlanState(number=7, url="u/7", title=title, header=header or {}, pr=None),
    )

    def _update_header(**k):
        stamps.append(k["fields"])
        return plans.PlanHeaderUpdate(fields_updated=tuple(k["fields"]), dry_run=False)

    monkeypatch.setattr(plans, "update_plan_header", _update_header)

    def _ready(**k):
        calls["readied"] = True

    def _merge(**k):
        calls["merged"] = True
        calls["commit_message"] = k.get("commit_message")
        return github.PullRequest(
            number=42, url="u/pr/42", is_draft=False, state="MERGED", existed=True
        )

    monkeypatch.setattr(github, "mark_pr_ready", _ready)
    monkeypatch.setattr(github, "merge_pr", _merge)
    return calls


def _run(args, *, write_ref=True):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        if write_ref:
            cache.write_plan_ref(Path(d), _ref())
        return runner.invoke(cli, args)


def test_dry_run_is_offline_and_sets_no_marker(unborn_git_repo_factory):
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


def test_real_land_draft_marks_ready_merges_and_sets_marker(monkeypatch, unborn_git_repo_factory):
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        cache.write_plan_ref(Path(d), _ref())
        calls = _stub_land(monkeypatch, draft=True)
        result = runner.invoke(cli, ["pr", "land", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["pr"]["state"] == "MERGED" and data["pending_learn"] is True
        assert calls["readied"] is True and calls["merged"] is True
        # The squash commit is plain `title + Closes #N` (no HTML leaks into git log).
        assert calls["commit_message"] == "My Feature\n\nCloses #7"
        assert cache.has_marker(Path(d), cache.PENDING_LEARN)


def test_real_land_empty_title_falls_back_to_closes(monkeypatch, unborn_git_repo_factory):
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        cache.write_plan_ref(Path(d), _ref())
        calls = _stub_land(monkeypatch, draft=False, title="")
        result = runner.invoke(cli, ["pr", "land", "--json"])
        assert result.exit_code == 0
        assert calls["commit_message"] == "Closes #7"


def test_real_land_ready_pr_skips_mark_ready(monkeypatch, unborn_git_repo_factory):
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        cache.write_plan_ref(Path(d), _ref())
        calls = _stub_land(monkeypatch, draft=False)
        result = runner.invoke(cli, ["pr", "land", "--json"])
        assert result.exit_code == 0
        assert calls["readied"] is False and calls["merged"] is True


def test_real_land_already_merged_is_idempotent(monkeypatch, unborn_git_repo_factory):
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        cache.write_plan_ref(Path(d), _ref())
        calls = _stub_land(monkeypatch, draft=False, merged=True)
        result = runner.invoke(cli, ["pr", "land", "--json"])
        assert result.exit_code == 0
        # already MERGED -> no mark-ready, no merge call, but the marker is still set
        assert calls["readied"] is False and calls["merged"] is False
        assert json.loads(result.output)["pending_learn"] is True
        assert cache.has_marker(Path(d), cache.PENDING_LEARN)


# --- the stacked-lineage refusal (fail-closed, before any mutation) ---------------------


def test_land_refuses_stacked_local_ref(monkeypatch, unborn_git_repo_factory):
    """A cached ref carrying delivery_lineage refuses before mark-ready/merge — stacked layers
    land only as one atomic train, never individually."""
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        cache.write_plan_ref(Path(d), _ref(delivery_lineage="dlv-1"))
        calls = _stub_land(monkeypatch, draft=True)
        result = runner.invoke(cli, ["pr", "land", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.output)["error_type"] == "stacked_plan"
        assert calls["readied"] is False and calls["merged"] is False
        assert not cache.has_marker(Path(d), cache.PENDING_LEARN)


def test_land_refuses_stacked_header_only(monkeypatch, unborn_git_repo_factory):
    """Header wins: a stale cached ref without the lineage still refuses once the plan header
    shows it — refused after the pre-merge read, before any mutation."""
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        cache.write_plan_ref(Path(d), _ref())
        calls = _stub_land(monkeypatch, draft=True, header={"delivery_lineage": "dlv-x"})
        result = runner.invoke(cli, ["pr", "land", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.output)["error_type"] == "stacked_plan"
        assert calls["readied"] is False and calls["merged"] is False
        assert not cache.has_marker(Path(d), cache.PENDING_LEARN)


def test_land_header_lineage_whitespace_not_stacked(monkeypatch, unborn_git_repo_factory):
    """The isinstance/strip guard: a whitespace-only header lineage is not stacked — lands."""
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        cache.write_plan_ref(Path(d), _ref())
        calls = _stub_land(monkeypatch, draft=False, header={"delivery_lineage": "  "})
        result = runner.invoke(cli, ["pr", "land", "--json"])
        assert result.exit_code == 0
        assert calls["merged"] is True


def test_land_plan_not_found_pre_merge(monkeypatch, unborn_git_repo_factory):
    """The hoisted pre-merge plan read is load-bearing: a vanished plan issue fails the land
    before any mutation (submit/ready's exact posture)."""
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        cache.write_plan_ref(Path(d), _ref())
        calls = _stub_land(monkeypatch, draft=True)
        monkeypatch.setattr(plans, "get_plan", lambda **k: None)
        result = runner.invoke(cli, ["pr", "land", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.output)["error_type"] == "plan_not_found"
        assert calls["readied"] is False and calls["merged"] is False


def test_dry_run_refuses_stacked_local_ref(unborn_git_repo_factory):
    """--dry-run refuses on the cached ref too (its would-merge preview would be a lie) while
    staying fully offline — no github stubs: anything network-bound would crash, not refuse."""
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        cache.write_plan_ref(Path(d), _ref(delivery_lineage="dlv-1"))
        result = runner.invoke(cli, ["pr", "land", "--dry-run", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.output)["error_type"] == "stacked_plan"


# --- explicit plan-issue close on a non-default-base github land -----------------------


def test_real_land_non_default_base_closes_plan_issue(monkeypatch, unborn_git_repo_factory):
    """A github PR merged into a non-default base never autocloses, so perk closes explicitly."""
    _authed(monkeypatch)
    monkeypatch.setattr(github, "default_branch", lambda repo_root: "main")
    closed: list[int] = []
    monkeypatch.setattr(plans, "close_issue", lambda **k: closed.append(k["number"]) or True)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        cache.write_plan_ref(Path(d), _ref())
        _stub_land(monkeypatch, draft=False, base_ref="release")
        result = runner.invoke(cli, ["pr", "land", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.output)["plan_issue_closed"] is True
        assert closed == [7]


def test_real_land_default_base_keeps_autoclose(monkeypatch, unborn_git_repo_factory):
    """A github PR merged into the default base relies on GitHub autoclose — no explicit close."""
    _authed(monkeypatch)
    monkeypatch.setattr(github, "default_branch", lambda repo_root: "main")

    def _boom(**k):
        raise AssertionError("close_issue must not be called on a default-base land")

    monkeypatch.setattr(plans, "close_issue", _boom)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        cache.write_plan_ref(Path(d), _ref())
        _stub_land(monkeypatch, draft=False, base_ref="main")
        result = runner.invoke(cli, ["pr", "land", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.output)["plan_issue_closed"] is False


def test_real_land_unknown_base_is_fail_open(monkeypatch, unborn_git_repo_factory):
    """An undeterminable base short-circuits WITHOUT calling default_branch (rely on autoclose)."""
    _authed(monkeypatch)

    def _no_default(repo_root):
        raise AssertionError("default_branch must not be called when the base is unknown")

    monkeypatch.setattr(github, "default_branch", _no_default)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        cache.write_plan_ref(Path(d), _ref())
        _stub_land(monkeypatch, draft=False, base_ref="")
        result = runner.invoke(cli, ["pr", "land", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.output)["plan_issue_closed"] is False


# --- the caller-owned Linear agent "landed" activity emission ---------------------------


def test_real_land_calls_linear_agent_landed(monkeypatch):
    """The land hook fires after the merge + learn consume, with the PR number and the
    objective-node summary (the emitter itself gates on the stamped provider + token)."""
    _authed(monkeypatch)
    _stub_land(monkeypatch, draft=True)
    emitted: list[dict] = []
    monkeypatch.setattr(
        land_cmd.linear_agent, "emit_landed", lambda _root, **kw: emitted.append(kw)
    )
    result = _run(["pr", "land", "--json"])
    assert result.exit_code == 0
    assert len(emitted) == 1
    assert emitted[0]["pr_number"] == 42
    assert emitted[0]["summary"] == ""  # no objective link on _REF


def test_dry_run_land_never_calls_linear_agent(monkeypatch):
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
    _stub_land(monkeypatch, draft=True)
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
    assert _landed_summary(ObjectiveLandUpdate(None, (), "no_objective_link")) == ""
    assert (
        _landed_summary(ObjectiveLandUpdate("9", ("2.1",), None))
        == "Objective #9: marked node(s) 2.1 done."
    )
    assert (
        _landed_summary(ObjectiveLandUpdate("9", ("2.1", "2.2"), None, closed=True))
        == "Objective #9: marked node(s) 2.1, 2.2 done. Objective complete — closed."
    )


def test_result_to_dict_carries_objective():
    result = PrLandResult(
        pr=github.PullRequest(number=42, url="u", is_draft=False, state="MERGED", existed=True),
        branch="plan-7",
        issue="7",
        pending_learn=True,
        dry_run=False,
        objective=ObjectiveLandUpdate("5", ("1.1",), None),
        learn=LearnConsumeUpdate(("45", "50"), None),
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


def _land_result(learn: LearnConsumeUpdate) -> PrLandResult:
    return PrLandResult(
        pr=github.PullRequest(number=42, url="u", is_draft=False, state="MERGED", existed=True),
        branch="plan-7",
        issue="7",
        pending_learn=True,
        dry_run=False,
        objective=ObjectiveLandUpdate(None, (), "no_objective_link"),
        learn=learn,
    )


def test_render_human_surfaces_non_benign_learn_skip(capsys):
    # A non-benign skip (a partial `failed: …`) is surfaced, not silent.
    _render_human(_land_result(LearnConsumeUpdate(("45",), "failed: #50")))
    out = capsys.readouterr().err
    assert "consolidated learn issue(s) #45" in out
    assert "learn consume incomplete: failed: #50" in out


def test_render_human_quiet_on_benign_learn_skip(capsys):
    # `no_consumed_learn` is the ordinary non-factory case — stay quiet.
    _render_human(_land_result(LearnConsumeUpdate((), "no_consumed_learn")))
    out = capsys.readouterr().err
    assert "learn consume incomplete" not in out


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


# --- the canonical learn_state stamp on land (§8.36) -----------------------------------------


def test_real_land_stamps_learn_state_pending(monkeypatch, unborn_git_repo_factory):
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        cache.write_plan_ref(Path(d), _ref())
        calls = _stub_land(monkeypatch, draft=False)
        result = runner.invoke(cli, ["pr", "land", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.output)["learn_state"] == "pending"
        assert calls["header_stamps"] == [{"learn_state": "pending"}]


def test_real_land_stamps_skipped_for_consumed_learn_plan(monkeypatch, unborn_git_repo_factory):
    # A learn-docs consolidation plan deliberately skips its learn pass — stamped `skipped`
    # at land so it never reads forever-pending. It is exempt from the land→learn cycle:
    # no pending-learn marker, and the envelope reports `pending_learn: false`.
    _authed(monkeypatch)
    monkeypatch.setattr(plans, "close_and_label_consolidated", lambda **k: True)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        cache.write_plan_ref(Path(d), _ref(consumed_learn=["45"]))
        calls = _stub_land(monkeypatch, draft=False)
        result = runner.invoke(cli, ["pr", "land", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["learn_state"] == "skipped"
        assert data["pending_learn"] is False
        assert not cache.has_marker(Path(d), cache.PENDING_LEARN)
        assert calls["header_stamps"] == [{"learn_state": "skipped"}]


def test_real_land_never_downgrades_captured(monkeypatch, unborn_git_repo_factory):
    # The never-downgrade guard: an idempotent re-land after /learn keeps `captured` (no write)
    # and the envelope reports the effective state.
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        cache.write_plan_ref(Path(d), _ref())
        calls = _stub_land(
            monkeypatch, draft=False, merged=True, header={"learn_state": "captured"}
        )
        result = runner.invoke(cli, ["pr", "land", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.output)["learn_state"] == "captured"
        assert calls["header_stamps"] == []  # no write on the guard arm


def test_real_land_stamp_failure_is_fail_open(monkeypatch, unborn_git_repo_factory):
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        cache.write_plan_ref(Path(d), _ref())
        _stub_land(monkeypatch, draft=False)

        def _boom(**k):
            raise github.GitHubError("gh exploded")

        monkeypatch.setattr(plans, "update_plan_header", _boom)
        result = runner.invoke(cli, ["pr", "land", "--json"])
        assert result.exit_code == 0  # the stamp never blocks landing
        assert json.loads(result.stdout)["learn_state"] is None
        assert "learn-state stamp skipped (non-fatal)" in result.stderr


def test_dry_run_stamps_no_learn_state(monkeypatch):
    def _boom(**k):
        raise AssertionError("dry run must not stamp the header")

    monkeypatch.setattr(plans, "update_plan_header", _boom)
    result = _run(["pr", "land", "--dry-run", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["learn_state"] is None


def test_real_land_no_pr_exits_1(monkeypatch, unborn_git_repo_factory):
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d, unborn_git_repo_factory)
        cache.write_plan_ref(Path(d), _ref())
        # The hoisted plan read now precedes PR discovery — stub it so the miss is the PR's.
        monkeypatch.setattr(
            plans,
            "get_plan",
            lambda **k: plans.PlanState(number=7, url="u/7", title="T", header={}, pr=None),
        )
        monkeypatch.setattr(github, "find_pr_for_branch", lambda **k: None)
        result = runner.invoke(cli, ["pr", "land", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.output)["error_type"] == "no_pr"
