import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk import github, plan
from perk.backends.github import plans
from perk.backends.linear import agent as linear_agent
from perk.cli.cli import cli
from perk.cli.commands.pr import submit_cmd
from perk.state import cache
from perk.substrate import git

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


_CLEAN_PROBE = git.MergeProbe(determined=True, mergeable=True, conflicts=())


def _stub_gh(
    monkeypatch,
    *,
    existed: bool = False,
    plan_body: str | None = None,
    probe: git.MergeProbe | None = _CLEAN_PROBE,
) -> dict[str, object]:
    """Stub the whole submit gateway path; record what the worker did.

    ``probe`` stubs the local merge-conflict probe: a ``MergeProbe`` is returned verbatim;
    ``None`` makes the probe raise ``GitError`` (the fail-open path). The probe call is recorded.
    """
    calls: dict[str, object] = {
        "pushed": False,
        "push_kwargs": None,
        "header": None,
        "pr_body": None,
        "probed": False,
    }
    monkeypatch.setattr(
        plans,
        "get_plan",
        lambda **k: plans.PlanState(number=7, url="u/7", title="My Feature", header={}, pr=None),
    )
    monkeypatch.setattr(plans, "get_plan_body", lambda **k: plan_body)
    monkeypatch.setattr(github, "default_branch", lambda root: "main")
    monkeypatch.setattr(
        github,
        "create_pr",
        lambda **k: github.PullRequest(
            number=42, url="u/pr/42", is_draft=True, state="OPEN", existed=existed
        ),
    )

    def _update(**k):
        calls["header"] = k["fields"]
        return plans.PlanHeaderUpdate(fields_updated=tuple(k["fields"]), dry_run=False)

    def _update_body(**k):
        calls["pr_body"] = k["body"]
        return github.PrBodyUpdate(number=k["number"], dry_run=False)

    def _push(*a, **k):
        calls["pushed"] = True
        calls["push_kwargs"] = k

    def _probe(*_a, **_k):
        calls["probed"] = True
        if probe is None:
            raise git.GitError("probe boom")
        return probe

    monkeypatch.setattr(plans, "update_plan_header", _update)
    monkeypatch.setattr(github, "update_pr_body", _update_body)
    monkeypatch.setattr(git, "push", _push)
    monkeypatch.setattr(git, "is_dirty", lambda root: False)
    monkeypatch.setattr(git, "detect_merge_conflicts", _probe)
    return calls


def _run(monkeypatch, args, *, write_ref=True):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        if write_ref:
            cache.write_plan_ref(Path(d), plan.PlanRefModel.model_validate(_REF).to_domain())
        return runner.invoke(cli, args)


def test_dry_run_is_offline_and_well_formed(monkeypatch):
    # No gh stubs at all — a dry run must not shell anything.
    result = _run(monkeypatch, ["pr", "submit", "--dry-run", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["success"] is True and data["dry_run"] is True
    assert data["branch"] == "plan-7" and data["issue"] == "7"
    assert data["pr"]["number"] == 0  # stub (no PR opened on a dry run)
    assert data["plan_header"]["fields_updated"] == ["branch", "pr", "lifecycle_stage"]
    # Dry run stays fully offline: no probe, mergeability unknown.
    assert data["base"] == "" and data["mergeable"] is None and data["conflicts"] == []


def test_no_plan_ref_exits_1(monkeypatch):
    result = _run(monkeypatch, ["pr", "submit", "--dry-run", "--json"], write_ref=False)
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "no_plan_ref"


def test_not_a_repo_exits_2(monkeypatch):
    runner = CliRunner()
    with runner.isolated_filesystem():  # no git init
        result = runner.invoke(cli, ["pr", "submit", "--dry-run", "--json"])
    assert result.exit_code == 2
    assert json.loads(result.output)["error_type"] == "not_a_repo"


def test_real_submit_opens_pr_and_updates_header(monkeypatch):
    _authed(monkeypatch)
    calls = _stub_gh(monkeypatch)
    result = _run(monkeypatch, ["pr", "submit", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["pr"]["number"] == 42 and data["pr"]["existed"] is False
    assert calls["pushed"] is True
    assert calls["header"] == {"branch": "plan-7", "pr": "42", "lifecycle_stage": "impl"}
    # The footer carries the PR number (42), not the issue number (7) — the create-then-update fix.
    assert "`gh pr checkout 42`" in str(calls["pr_body"])
    assert "`gh pr checkout 7`" not in str(calls["pr_body"])
    assert data["pr_checked"] is True and data["plan_embedded"] is False
    # Mergeability surfaced: clean probe -> base/mergeable/conflicts present.
    assert data["base"] == "main"
    assert data["mergeable"] is True and data["conflicts"] == []
    assert calls["probed"] is True


def test_submit_targets_pinned_base_from_plan_ref(monkeypatch):
    # A plan-ref carrying `base` retargets create_pr + the mergeability probe (over the
    # GitHub default branch).
    _authed(monkeypatch)
    captured: dict[str, object] = {}
    _stub_gh(monkeypatch)
    monkeypatch.setattr(
        github,
        "create_pr",
        lambda **k: (
            captured.update(create_base=k["base"])
            or github.PullRequest(
                number=42, url="u/pr/42", is_draft=True, state="OPEN", existed=False
            )
        ),
    )

    def _probe(_root, *, base, branch_ref):
        captured["probe_base"] = base
        return _CLEAN_PROBE

    monkeypatch.setattr(git, "detect_merge_conflicts", _probe)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(
            Path(d), plan.PlanRefModel.model_validate({**_REF, "base": "develop"}).to_domain()
        )
        result = runner.invoke(cli, ["pr", "submit", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["base"] == "develop"
    assert captured["create_base"] == "develop"
    assert captured["probe_base"] == "develop"


def test_submit_falls_back_to_header_then_default_base(monkeypatch):
    # With no plan-ref base, submit resolves base from the plan-header, else default_branch.
    _authed(monkeypatch)
    captured: dict[str, object] = {}
    _stub_gh(monkeypatch)
    monkeypatch.setattr(
        plans,
        "get_plan",
        lambda **k: plans.PlanState(
            number=7, url="u/7", title="My Feature", header={"base": "release"}, pr=None
        ),
    )
    monkeypatch.setattr(
        github,
        "create_pr",
        lambda **k: (
            captured.update(create_base=k["base"])
            or github.PullRequest(
                number=42, url="u/pr/42", is_draft=True, state="OPEN", existed=False
            )
        ),
    )
    result = _run(monkeypatch, ["pr", "submit", "--json"])  # _REF has no base
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["base"] == "release"
    assert captured["create_base"] == "release"


def test_submit_surfaces_conflicts_but_succeeds(monkeypatch):
    _authed(monkeypatch)
    _stub_gh(
        monkeypatch,
        probe=git.MergeProbe(determined=True, mergeable=False, conflicts=("a.py", "b.py")),
    )
    result = _run(monkeypatch, ["pr", "submit", "--json"])
    # The submit succeeded MECHANICALLY (exit 0); mergeability is reported separately.
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["success"] is True
    assert data["mergeable"] is False and data["conflicts"] == ["a.py", "b.py"]
    assert data["base"] == "main"


def test_submit_probe_failure_is_fail_open(monkeypatch):
    _authed(monkeypatch)
    _stub_gh(monkeypatch, probe=None)  # probe raises -> fail-open
    result = _run(monkeypatch, ["pr", "submit", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["mergeable"] is None and data["conflicts"] == []


def test_submit_undetermined_probe_is_null(monkeypatch):
    _authed(monkeypatch)
    _stub_gh(monkeypatch, probe=git.MergeProbe(determined=False, mergeable=False, conflicts=()))
    result = _run(monkeypatch, ["pr", "submit", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["mergeable"] is None


def test_real_submit_embeds_plan_when_available(monkeypatch):
    _authed(monkeypatch)
    calls = _stub_gh(monkeypatch, plan_body="# My Plan\n\nbody text")
    result = _run(monkeypatch, ["pr", "submit", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["plan_embedded"] is True
    body = str(calls["pr_body"])
    assert "<details><summary>Plan #7</summary>" in body and "# My Plan" in body
    assert "`gh pr checkout 42`" in body  # footer stays plain even with the HTML embed


def test_real_submit_idempotent_existing_pr(monkeypatch):
    _authed(monkeypatch)
    _stub_gh(monkeypatch, existed=True)
    result = _run(monkeypatch, ["pr", "submit", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["pr"]["existed"] is True


def test_real_submit_plan_not_found_exits_1(monkeypatch):
    _authed(monkeypatch)
    _stub_gh(monkeypatch)
    monkeypatch.setattr(plans, "get_plan", lambda **k: None)
    result = _run(monkeypatch, ["pr", "submit", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "plan_not_found"


def test_real_submit_calls_linear_agent_pr_opened(monkeypatch):
    """The submit hook fires after the header update with the PR fields (the emitter
    itself gates on the stamped provider + LINEAR_AGENT_TOKEN)."""
    _authed(monkeypatch)
    _stub_gh(monkeypatch)
    emitted: list[dict] = []
    monkeypatch.setattr(
        submit_cmd.linear_agent, "emit_pr_opened", lambda _root, **kw: emitted.append(kw)
    )
    result = _run(monkeypatch, ["pr", "submit", "--json"])
    assert result.exit_code == 0
    assert len(emitted) == 1
    kw = emitted[0]
    assert kw["pr_number"] == 42
    assert kw["pr_url"] == "u/pr/42"
    assert kw["branch"] == "plan-7"


def test_dry_run_submit_never_calls_linear_agent(monkeypatch):
    emitted: list[dict] = []
    monkeypatch.setattr(
        submit_cmd.linear_agent, "emit_pr_opened", lambda _root, **kw: emitted.append(kw)
    )
    result = _run(monkeypatch, ["pr", "submit", "--dry-run", "--json"])
    assert result.exit_code == 0
    assert emitted == []


def test_linear_agent_failure_leaves_submit_payload_byte_identical(monkeypatch):
    """Fail-soft: a broken emitter substrate (gate forced open) never changes the --json payload
    or exit code."""
    _authed(monkeypatch)
    _stub_gh(monkeypatch)
    baseline = _run(monkeypatch, ["pr", "submit", "--json"])
    assert baseline.exit_code == 0

    monkeypatch.setattr(linear_agent, "emission_enabled", lambda *_a, **_k: True)
    monkeypatch.setattr(
        cache,
        "read_agent_session",
        lambda _r: cache.AgentSession(session_id="sess-1", issue="7"),
    )

    def boom(_environ):
        raise RuntimeError("agent substrate down")

    monkeypatch.setattr(linear_agent, "agent_client_from_env", boom)
    result = _run(monkeypatch, ["pr", "submit", "--json"])
    assert result.exit_code == 0
    assert result.stdout == baseline.stdout  # the --json payload is byte-identical
    assert "pr-opened emission skipped (non-fatal)" in result.stderr


def test_real_submit_force_pushes(monkeypatch):
    _authed(monkeypatch)
    calls = _stub_gh(monkeypatch)
    result = _run(monkeypatch, ["pr", "submit", "--json"])
    assert result.exit_code == 0
    assert calls["pushed"] is True
    assert calls["push_kwargs"] == {"force": True}


def test_dirty_tree_refuses_before_push(monkeypatch):
    _authed(monkeypatch)
    calls = _stub_gh(monkeypatch)
    monkeypatch.setattr(git, "is_dirty", lambda root: True)
    result = _run(monkeypatch, ["pr", "submit", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "dirty_tree"
    assert calls["pushed"] is False


def test_push_rejected_maps_to_stable_error(monkeypatch):
    _authed(monkeypatch)
    _stub_gh(monkeypatch)

    def _reject(*a, **k):
        raise git.PushRejectedError("! [rejected] plan-7 -> plan-7 (non-fast-forward)")

    monkeypatch.setattr(git, "push", _reject)
    result = _run(monkeypatch, ["pr", "submit", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "push_rejected"
