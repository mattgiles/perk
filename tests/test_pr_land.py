import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk import github, objective
from perk.backends.github import objectives, plans
from perk.backends.linear import agent as linear_agent
from perk.cli.cli import cli
from perk.cli.commands.pr import land_cmd
from perk.cli.commands.pr.land_cmd import (
    LearnConsumeUpdate,
    ObjectiveLandUpdate,
    PrLandResult,
    _consume_learn_on_land,
    _landed_summary,
    _reconcile_objective_on_land,
    _render_human,
    _result_to_dict,
)
from perk.state import cache

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
    monkeypatch, *, draft: bool, merged: bool = False, title: str = "My Feature", base_ref: str = ""
) -> dict[str, object]:
    calls: dict[str, object] = {"readied": False, "merged": False, "commit_message": None}
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
        lambda **k: plans.PlanState(number=7, url="u/7", title=title, header={}, pr=None),
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


# --- #691: explicit plan-issue close on a non-default-base github land -----------------------


def test_real_land_non_default_base_closes_plan_issue(monkeypatch):
    """A github PR merged into a non-default base never autocloses, so perk closes explicitly."""
    _authed(monkeypatch)
    monkeypatch.setattr(github, "default_branch", lambda repo_root: "main")
    closed: list[int] = []
    monkeypatch.setattr(plans, "close_issue", lambda **k: closed.append(k["number"]) or True)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), _REF)
        _stub_land(monkeypatch, draft=False, base_ref="release")
        result = runner.invoke(cli, ["pr", "land", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.output)["plan_issue_closed"] is True
        assert closed == [7]


def test_real_land_default_base_keeps_autoclose(monkeypatch):
    """A github PR merged into the default base relies on GitHub autoclose — no explicit close."""
    _authed(monkeypatch)
    monkeypatch.setattr(github, "default_branch", lambda repo_root: "main")

    def _boom(**k):
        raise AssertionError("close_issue must not be called on a default-base land")

    monkeypatch.setattr(plans, "close_issue", _boom)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), _REF)
        _stub_land(monkeypatch, draft=False, base_ref="main")
        result = runner.invoke(cli, ["pr", "land", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.output)["plan_issue_closed"] is False


def test_real_land_unknown_base_is_fail_open(monkeypatch):
    """An undeterminable base short-circuits WITHOUT calling default_branch (rely on autoclose)."""
    _authed(monkeypatch)

    def _no_default(repo_root):
        raise AssertionError("default_branch must not be called when the base is unknown")

    monkeypatch.setattr(github, "default_branch", _no_default)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), _REF)
        _stub_land(monkeypatch, draft=False, base_ref="")
        result = runner.invoke(cli, ["pr", "land", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.output)["plan_issue_closed"] is False


def test_close_plan_issue_non_default_base_failure_is_fail_open(monkeypatch, capsys):
    """A close failure on a non-default github base is fail-open: returns False, warns on stderr,
    never raises (so the land result is unchanged)."""
    from perk.backends.github import GitHubIssueBackend

    monkeypatch.setattr(github, "default_branch", lambda repo_root: "main")

    def _boom(**k):
        raise github.GitHubError("gh exploded")

    monkeypatch.setattr(plans, "close_issue", _boom)
    backend = GitHubIssueBackend(repo_root=Path())
    out = land_cmd._close_plan_issue_on_land(
        backend, issue="7", repo_root=Path(), pr_base="release"
    )
    assert out is False
    assert "plan issue close skipped (non-fatal)" in capsys.readouterr().err


# --- P2.T11a: mechanical auto-on-merge node-done --------------------------------------------


def _objective_state(nodes: list[objective.ObjectiveNode]) -> objectives.ObjectiveState:
    return objectives.ObjectiveState(
        number=5, url="u/5", title="Obj", header={}, nodes=tuple(nodes)
    )


def _node(node_id: str, *, pr: str | None, status=objective.NodeStatus.PENDING):
    return objective.ObjectiveNode(id=node_id, description=node_id, status=status, pr=pr)


def test_real_land_calls_linear_agent_landed(monkeypatch):
    """Node 5.1: the land hook fires after the merge + learn consume, with the PR number and the
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
    monkeypatch.setattr(cache, "read_agent_session", lambda _r: {"session_id": "sess-1"})

    def boom(_environ):
        raise RuntimeError("agent substrate down")

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


def test_reconcile_on_land_no_objective_link():
    out = _reconcile_objective_on_land(
        plan_ref={"objective_id": None, "pr_id": "7"}, repo_root=Path()
    )
    assert out == ObjectiveLandUpdate(None, (), "no_objective_link")


def test_reconcile_on_land_bad_objective_id():
    # Ids are opaque strings now — only an empty (post-`#`-strip) id is "bad".
    out = _reconcile_objective_on_land(
        plan_ref={"objective_id": "#", "pr_id": "7"}, repo_root=Path()
    )
    assert out == ObjectiveLandUpdate(None, (), "bad_objective_id")


def test_reconcile_on_land_objective_not_found(monkeypatch):
    monkeypatch.setattr(objectives, "get_objective", lambda **k: None)
    out = _reconcile_objective_on_land(
        plan_ref={"objective_id": "5", "pr_id": "7"}, repo_root=Path()
    )
    assert out == ObjectiveLandUpdate("5", (), "objective_not_found")


def test_reconcile_on_land_no_linked_node(monkeypatch):
    monkeypatch.setattr(
        objectives, "get_objective", lambda **k: _objective_state([_node("1.1", pr="#99")])
    )
    out = _reconcile_objective_on_land(
        plan_ref={"objective_id": "5", "pr_id": "7"}, repo_root=Path()
    )
    assert out == ObjectiveLandUpdate("5", (), "no_linked_node")


def test_reconcile_on_land_marks_backlinked_node_done(monkeypatch):
    marked: list[str] = []
    monkeypatch.setattr(
        objectives,
        "get_objective",
        lambda **k: _objective_state([_node("1.1", pr="#7"), _node("1.2", pr="#99")]),
    )

    def _update(**k):
        assert k["status"] == objective.NodeStatus.DONE
        marked.append(k["node_id"])
        return objectives.ObjectiveNodeUpdate(
            number=k["number"], node_id=k["node_id"], comment_updated=True, dry_run=False
        )

    monkeypatch.setattr(objectives, "update_objective_node", _update)
    closed: list[int] = []
    monkeypatch.setattr(plans, "close_issue", lambda **k: closed.append(k["number"]) or True)
    out = _reconcile_objective_on_land(
        plan_ref={"objective_id": "#5", "pr_id": "7"}, repo_root=Path()
    )
    # node 1.2 stays non-terminal → roadmap incomplete → no close.
    assert out == ObjectiveLandUpdate("5", ("1.1",), None)
    assert out.closed is False
    assert marked == ["1.1"]
    assert closed == []


def test_reconcile_on_land_skips_already_terminal_node(monkeypatch):
    # Re-land idempotency: the target is already done and the graph is complete — the close still
    # runs (idempotent convergence) even though zero nodes were marked.
    monkeypatch.setattr(
        objectives,
        "get_objective",
        lambda **k: _objective_state([_node("1.1", pr="#7", status=objective.NodeStatus.DONE)]),
    )
    closed: list[int] = []
    monkeypatch.setattr(plans, "close_issue", lambda **k: closed.append(k["number"]) or True)
    out = _reconcile_objective_on_land(
        plan_ref={"objective_id": "5", "pr_id": "7"}, repo_root=Path()
    )
    assert out == ObjectiveLandUpdate("5", (), None, closed=True)
    assert closed == [5]


def test_reconcile_on_land_closes_objective_when_final_node_completes(monkeypatch):
    # Landing the final non-terminal node → every node terminal → the objective issue is closed.
    monkeypatch.setattr(
        objectives,
        "get_objective",
        lambda **k: _objective_state(
            [
                _node("1.1", pr="#99", status=objective.NodeStatus.DONE),
                _node("1.2", pr="#98", status=objective.NodeStatus.SKIPPED),
                _node("1.3", pr="#7"),
            ]
        ),
    )
    monkeypatch.setattr(
        objectives,
        "update_objective_node",
        lambda **k: objectives.ObjectiveNodeUpdate(
            number=k["number"], node_id=k["node_id"], comment_updated=True, dry_run=False
        ),
    )
    closed: list[int] = []
    monkeypatch.setattr(plans, "close_issue", lambda **k: closed.append(k["number"]) or True)
    out = _reconcile_objective_on_land(
        plan_ref={"objective_id": "5", "pr_id": "7"}, repo_root=Path()
    )
    assert out == ObjectiveLandUpdate("5", ("1.3",), None, closed=True)
    assert closed == [5]


def test_reconcile_on_land_close_failure_is_isolated(monkeypatch, capsys):
    # A close failure must NOT discard the already-marked node ids (isolated fail-open) and must
    # never affect the land result.
    monkeypatch.setattr(
        objectives,
        "get_objective",
        lambda **k: _objective_state([_node("1.1", pr="#7")]),
    )
    monkeypatch.setattr(
        objectives,
        "update_objective_node",
        lambda **k: objectives.ObjectiveNodeUpdate(
            number=k["number"], node_id=k["node_id"], comment_updated=True, dry_run=False
        ),
    )

    def _boom(**k):
        raise github.GitHubError("gh exploded")

    monkeypatch.setattr(plans, "close_issue", _boom)
    out = _reconcile_objective_on_land(
        plan_ref={"objective_id": "5", "pr_id": "7"}, repo_root=Path()
    )
    assert out.nodes_marked == ("1.1",)
    assert out.closed is False
    assert out.skipped_reason is not None and out.skipped_reason.startswith("close_failed:")
    assert "objective close skipped (non-fatal)" in capsys.readouterr().err


def test_reconcile_on_land_completes_via_store_close_objective(monkeypatch):
    # Node 3.4: completion closes through the OBJECTIVE STORE (store.close_objective), not the issue
    # tier (backend.close_issue). Inject a fake store and assert it owns the close.
    from perk.backends import objective_store, resolve

    calls: dict[str, object] = {}
    marked: list[str] = []
    posts: list[dict] = []

    class _Store:
        backend_id = "linear"

        def get_objective(self, *, objective_id):
            return objective_store.ObjectiveState(
                id=objective_id,
                url="u",
                title="O",
                header={},
                nodes=(_node("1.1", pr="#ENG-7"),),
            )

        def update_objective_node(self, **k):
            marked.append(k["node_id"])
            return objective_store.ObjectiveNodeUpdate(
                objective_id=str(k["objective_id"]),
                node_id=k["node_id"],
                comment_updated=False,
                dry_run=False,
            )

        def close_objective(self, *, objective_id, dry_run=False):
            calls["closed"] = objective_id
            return True

        def post_status_update(self, *, objective_id, body, dry_run=False):
            posts.append({"objective_id": objective_id, "body": body})
            return True

    monkeypatch.setattr(resolve, "resolve_objective_store", lambda _root: _Store())
    # If the close reached the issue tier, this would fire — it must NOT.
    monkeypatch.setattr(
        plans, "close_issue", lambda **k: (_ for _ in ()).throw(AssertionError("issue-tier close"))
    )
    out = _reconcile_objective_on_land(
        plan_ref={"objective_id": "proj-1", "pr_id": "ENG-7"}, repo_root=Path()
    )
    assert out == ObjectiveLandUpdate("proj-1", ("1.1",), None, closed=True)
    assert calls["closed"] == "proj-1"
    # Node 4.3: a "plan landed" Project Update is posted once on completion (complete branch).
    assert len(posts) == 1
    assert posts[0]["objective_id"] == "proj-1"
    assert posts[0]["body"] == (
        "**Plan landed** — node(s) 1.1 (PR #ENG-7) marked done.\n\nObjective complete."
    )


def test_reconcile_on_land_posts_update_incomplete_and_fail_open(monkeypatch, capsys):
    # The incomplete branch posts a "plan landed" update (no "Objective complete."), and a post
    # failure is fail-open: the land result is byte-unchanged and a non-fatal line hits stderr.
    from perk.backends import objective_store, resolve

    class _Store:
        backend_id = "linear"

        def get_objective(self, *, objective_id):
            return objective_store.ObjectiveState(
                id=objective_id,
                url="u",
                title="O",
                header={},
                nodes=(_node("1.1", pr="#ENG-7"), _node("1.2", pr="#ENG-9")),
            )

        def update_objective_node(self, **k):
            return objective_store.ObjectiveNodeUpdate(
                objective_id=str(k["objective_id"]),
                node_id=k["node_id"],
                comment_updated=False,
                dry_run=False,
            )

        def post_status_update(self, *, objective_id, body, dry_run=False):
            raise objective_store.ObjectiveStoreError("linear update boom")

    monkeypatch.setattr(resolve, "resolve_objective_store", lambda _root: _Store())
    out = _reconcile_objective_on_land(
        plan_ref={"objective_id": "proj-1", "pr_id": "ENG-7"}, repo_root=Path()
    )
    # 1.2 stays non-terminal → incomplete → no close; the post failure never changes the result.
    assert out == ObjectiveLandUpdate("proj-1", ("1.1",), None)
    assert "project update skipped (non-fatal)" in capsys.readouterr().err


def test_reconcile_on_land_is_fail_open(monkeypatch):
    def _boom(**k):
        raise github.GitHubError("gh exploded")

    monkeypatch.setattr(objectives, "get_objective", _boom)
    out = _reconcile_objective_on_land(
        plan_ref={"objective_id": "5", "pr_id": "7"}, repo_root=Path()
    )
    assert out.objective == "5" and out.nodes_marked == ()
    assert out.skipped_reason is not None and out.skipped_reason.startswith("error:")


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
    # Opaque string ids at the machine boundary (contracts §8.21; Node 4.1).
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
    # #102: a non-benign skip (a partial `failed: …`) is surfaced, not silent.
    _render_human(_land_result(LearnConsumeUpdate(("45",), "failed: #50")))
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
    out = _consume_learn_on_land(plan_ref={"pr_id": "7"}, repo_root=Path())
    assert out.closed == () and out.skipped_reason == "no_consumed_learn"


def test_consume_learn_on_land_closes_listed_issues(monkeypatch):
    closed: list[int] = []
    monkeypatch.setattr(
        plans,
        "close_and_label_consolidated",
        lambda *, issue, repo_root, **k: closed.append(issue) or True,
    )
    out = _consume_learn_on_land(
        plan_ref={"consumed_learn": [45, 50], "pr_id": "7"}, repo_root=Path()
    )
    assert out.closed == ("45", "50") and out.skipped_reason is None
    assert closed == [45, 50]


def test_consume_learn_on_land_is_fail_open(monkeypatch):
    # #102: a fully-failing close is fail-open (never raises) and the failure is recorded per-issue.
    def _boom(**k):
        raise github.GitHubError("gh exploded")

    monkeypatch.setattr(plans, "close_and_label_consolidated", _boom)
    out = _consume_learn_on_land(plan_ref={"consumed_learn": [45], "pr_id": "7"}, repo_root=Path())
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

    monkeypatch.setattr(plans, "close_and_label_consolidated", _close)
    out = _consume_learn_on_land(
        plan_ref={"consumed_learn": [45, 50, 51], "pr_id": "7"}, repo_root=Path()
    )
    assert out.closed == ("45", "51")
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
            "id": None,
            "nodes_marked": [],
            "skipped_reason": "dry_run",
            "closed": False,
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
