import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk import cache, github, objective
from perk.cli.cli import cli
from perk.cli.commands.pr.land_cmd import (
    LearnConsumeUpdate,
    ObjectiveLandUpdate,
    PrLandResult,
    _consume_learn_on_land,
    _reconcile_objective_on_land,
    _render_human,
    _result_to_dict,
)

_REF = {
    "provider": "github",
    "pr_id": "7",
    "url": "https://gh/o/r/issues/7",
    "labels": ["perk:plan"],
    "objective_id": None,
}


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _authed(monkeypatch) -> None:
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(True, "octocat", ("repo",), None)
    )


def _stub_land(
    monkeypatch, *, draft: bool, merged: bool = False, title: str = "My Feature"
) -> dict[str, object]:
    calls: dict[str, object] = {"readied": False, "merged": False, "commit_message": None}
    state = "MERGED" if merged else "OPEN"
    monkeypatch.setattr(
        github,
        "find_pr_for_branch",
        lambda **k: github.PullRequest(
            number=42, url="u/pr/42", is_draft=draft, state=state, existed=True
        ),
    )
    monkeypatch.setattr(
        github,
        "get_plan",
        lambda **k: github.PlanState(number=7, url="u/7", title=title, header={}, pr=None),
    )

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
        _git_init(d)
        if write_ref:
            cache.write_plan_ref(Path(d), _REF)
        return runner.invoke(cli, args)


def test_dry_run_is_offline_and_sets_no_marker():
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), _REF)
        result = runner.invoke(cli, ["pr", "land", "--dry-run", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["success"] is True and data["dry_run"] is True
        assert data["branch"] == "plan-7" and data["pending_learn"] is False
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


def test_real_land_draft_marks_ready_merges_and_sets_marker(monkeypatch):
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), _REF)
        calls = _stub_land(monkeypatch, draft=True)
        result = runner.invoke(cli, ["pr", "land", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["pr"]["state"] == "MERGED" and data["pending_learn"] is True
        assert calls["readied"] is True and calls["merged"] is True
        # P2.T8b: the squash commit is plain `title + Closes #N` (no HTML leaks into git log).
        assert calls["commit_message"] == "My Feature\n\nCloses #7"
        assert cache.has_marker(Path(d), cache.PENDING_LEARN)


def test_real_land_empty_title_falls_back_to_closes(monkeypatch):
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), _REF)
        calls = _stub_land(monkeypatch, draft=False, title="")
        result = runner.invoke(cli, ["pr", "land", "--json"])
        assert result.exit_code == 0
        assert calls["commit_message"] == "Closes #7"


def test_real_land_ready_pr_skips_mark_ready(monkeypatch):
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), _REF)
        calls = _stub_land(monkeypatch, draft=False)
        result = runner.invoke(cli, ["pr", "land", "--json"])
        assert result.exit_code == 0
        assert calls["readied"] is False and calls["merged"] is True


def test_real_land_already_merged_is_idempotent(monkeypatch):
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), _REF)
        calls = _stub_land(monkeypatch, draft=False, merged=True)
        result = runner.invoke(cli, ["pr", "land", "--json"])
        assert result.exit_code == 0
        # already MERGED -> no mark-ready, no merge call, but the marker is still set
        assert calls["readied"] is False and calls["merged"] is False
        assert json.loads(result.output)["pending_learn"] is True
        assert cache.has_marker(Path(d), cache.PENDING_LEARN)


# --- P2.T11a: mechanical auto-on-merge node-done --------------------------------------------


def _objective_state(nodes: list[objective.ObjectiveNode]) -> github.ObjectiveState:
    return github.ObjectiveState(number=5, url="u/5", title="Obj", header={}, nodes=tuple(nodes))


def _node(node_id: str, *, pr: str | None, status=objective.NodeStatus.PENDING):
    return objective.ObjectiveNode(id=node_id, description=node_id, status=status, pr=pr)


def test_reconcile_on_land_no_objective_link():
    out = _reconcile_objective_on_land(
        plan_ref={"objective_id": None, "pr_id": "7"}, repo_root=Path(".")
    )
    assert out == ObjectiveLandUpdate(None, (), "no_objective_link")


def test_reconcile_on_land_bad_objective_id():
    out = _reconcile_objective_on_land(
        plan_ref={"objective_id": "not-a-number", "pr_id": "7"}, repo_root=Path(".")
    )
    assert out == ObjectiveLandUpdate(None, (), "bad_objective_id")


def test_reconcile_on_land_objective_not_found(monkeypatch):
    monkeypatch.setattr(github, "get_objective", lambda **k: None)
    out = _reconcile_objective_on_land(
        plan_ref={"objective_id": "5", "pr_id": "7"}, repo_root=Path(".")
    )
    assert out == ObjectiveLandUpdate(5, (), "objective_not_found")


def test_reconcile_on_land_no_linked_node(monkeypatch):
    monkeypatch.setattr(
        github, "get_objective", lambda **k: _objective_state([_node("1.1", pr="#99")])
    )
    out = _reconcile_objective_on_land(
        plan_ref={"objective_id": "5", "pr_id": "7"}, repo_root=Path(".")
    )
    assert out == ObjectiveLandUpdate(5, (), "no_linked_node")


def test_reconcile_on_land_marks_backlinked_node_done(monkeypatch):
    marked: list[str] = []
    monkeypatch.setattr(
        github,
        "get_objective",
        lambda **k: _objective_state([_node("1.1", pr="#7"), _node("1.2", pr="#99")]),
    )

    def _update(**k):
        assert k["status"] == objective.NodeStatus.DONE
        marked.append(k["node_id"])
        return github.ObjectiveNodeUpdate(
            number=k["number"], node_id=k["node_id"], comment_updated=True, dry_run=False
        )

    monkeypatch.setattr(github, "update_objective_node", _update)
    out = _reconcile_objective_on_land(
        plan_ref={"objective_id": "#5", "pr_id": "7"}, repo_root=Path(".")
    )
    assert out == ObjectiveLandUpdate(5, ("1.1",), None)
    assert marked == ["1.1"]


def test_reconcile_on_land_skips_already_terminal_node(monkeypatch):
    monkeypatch.setattr(
        github,
        "get_objective",
        lambda **k: _objective_state([_node("1.1", pr="#7", status=objective.NodeStatus.DONE)]),
    )
    out = _reconcile_objective_on_land(
        plan_ref={"objective_id": "5", "pr_id": "7"}, repo_root=Path(".")
    )
    assert out == ObjectiveLandUpdate(5, (), None)


def test_reconcile_on_land_is_fail_open(monkeypatch):
    def _boom(**k):
        raise github.GitHubError("gh exploded")

    monkeypatch.setattr(github, "get_objective", _boom)
    out = _reconcile_objective_on_land(
        plan_ref={"objective_id": "5", "pr_id": "7"}, repo_root=Path(".")
    )
    assert out.objective == 5 and out.nodes_marked == ()
    assert out.skipped_reason is not None and out.skipped_reason.startswith("error:")


def test_result_to_dict_carries_objective():
    result = PrLandResult(
        pr=github.PullRequest(number=42, url="u", is_draft=False, state="MERGED", existed=True),
        branch="plan-7",
        issue=7,
        pending_learn=True,
        dry_run=False,
        objective=ObjectiveLandUpdate(5, ("1.1",), None),
        learn=LearnConsumeUpdate((45, 50), None),
    )
    data = _result_to_dict(result)
    assert data["objective"] == {"number": 5, "nodes_marked": ["1.1"], "skipped_reason": None}
    assert data["learn"] == {"closed": [45, 50], "skipped_reason": None}


def _land_result(learn: LearnConsumeUpdate) -> PrLandResult:
    return PrLandResult(
        pr=github.PullRequest(number=42, url="u", is_draft=False, state="MERGED", existed=True),
        branch="plan-7",
        issue=7,
        pending_learn=True,
        dry_run=False,
        objective=ObjectiveLandUpdate(None, (), "no_objective_link"),
        learn=learn,
    )


def test_render_human_surfaces_non_benign_learn_skip(capsys):
    # #102: a non-benign skip (a partial `failed: …`) is surfaced, not silent.
    _render_human(_land_result(LearnConsumeUpdate((45,), "failed: #50")))
    out = capsys.readouterr().err
    assert "consolidated learn issue(s) #45" in out
    assert "learn consume incomplete: failed: #50" in out


def test_render_human_quiet_on_benign_learn_skip(capsys):
    # #102: `no_consumed_learn` is the ordinary non-factory case — stay quiet.
    _render_human(_land_result(LearnConsumeUpdate((), "no_consumed_learn")))
    out = capsys.readouterr().err
    assert "learn consume incomplete" not in out


# --- learned-docs consume on land (hop-2) ----------------------------------------------------


def test_consume_learn_on_land_no_consumed():
    out = _consume_learn_on_land(plan_ref={"pr_id": "7"}, repo_root=Path("."))
    assert out.closed == () and out.skipped_reason == "no_consumed_learn"


def test_consume_learn_on_land_closes_listed_issues(monkeypatch):
    closed: list[int] = []
    monkeypatch.setattr(
        github,
        "close_and_label_consolidated",
        lambda *, issue, repo_root, **k: closed.append(issue) or True,
    )
    out = _consume_learn_on_land(
        plan_ref={"consumed_learn": [45, 50], "pr_id": "7"}, repo_root=Path(".")
    )
    assert out.closed == (45, 50) and out.skipped_reason is None
    assert closed == [45, 50]


def test_consume_learn_on_land_is_fail_open(monkeypatch):
    # #102: a fully-failing close is fail-open (never raises) and the failure is recorded per-issue.
    def _boom(**k):
        raise github.GitHubError("gh exploded")

    monkeypatch.setattr(github, "close_and_label_consolidated", _boom)
    out = _consume_learn_on_land(
        plan_ref={"consumed_learn": [45], "pr_id": "7"}, repo_root=Path(".")
    )
    assert out.closed == ()
    assert out.skipped_reason == "failed: #45"


def test_consume_learn_on_land_isolates_one_bad_issue(monkeypatch):
    # #102: one bad issue must not strand the rest — the good closes still land, the failure is
    # rolled into `failed: #N` while the result stays fail-open.
    closed: list[int] = []

    def _close(*, issue, repo_root, **k):
        if issue == 50:
            raise github.GitHubError("already deleted")
        closed.append(issue)
        return True

    monkeypatch.setattr(github, "close_and_label_consolidated", _close)
    out = _consume_learn_on_land(
        plan_ref={"consumed_learn": [45, 50, 51], "pr_id": "7"}, repo_root=Path(".")
    )
    assert out.closed == (45, 51)
    assert closed == [45, 51]
    assert out.skipped_reason == "failed: #50"


def test_dry_run_learn_is_inert():
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), {**_REF, "consumed_learn": [45]})
        result = runner.invoke(cli, ["pr", "land", "--dry-run", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["learn"] == {"closed": [], "skipped_reason": "dry_run"}


def test_dry_run_objective_is_inert():
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), {**_REF, "objective_id": "5"})
        result = runner.invoke(cli, ["pr", "land", "--dry-run", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["objective"] == {
            "number": None,
            "nodes_marked": [],
            "skipped_reason": "dry_run",
        }


def test_real_land_no_pr_exits_1(monkeypatch):
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), _REF)
        monkeypatch.setattr(github, "find_pr_for_branch", lambda **k: None)
        result = runner.invoke(cli, ["pr", "land", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.output)["error_type"] == "no_pr"
