import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk import cache, git, github
from perk.cli.cli import cli

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


def _stub_gh(
    monkeypatch, *, existed: bool = False, plan_body: str | None = None
) -> dict[str, object]:
    """Stub the whole submit gateway path; record what the worker did."""
    calls: dict[str, object] = {
        "pushed": False,
        "push_kwargs": None,
        "header": None,
        "pr_body": None,
    }
    monkeypatch.setattr(
        github,
        "get_plan",
        lambda **k: github.PlanState(number=7, url="u/7", title="My Feature", header={}, pr=None),
    )
    monkeypatch.setattr(github, "get_plan_body", lambda **k: plan_body)
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
        return github.PlanHeaderUpdate(fields_updated=tuple(k["fields"]), dry_run=False)

    def _update_body(**k):
        calls["pr_body"] = k["body"]
        return github.PrBodyUpdate(number=k["number"], dry_run=False)

    def _push(*a, **k):
        calls["pushed"] = True
        calls["push_kwargs"] = k

    monkeypatch.setattr(github, "update_plan_header", _update)
    monkeypatch.setattr(github, "update_pr_body", _update_body)
    monkeypatch.setattr(git, "push", _push)
    monkeypatch.setattr(git, "is_dirty", lambda root: False)
    return calls


def _run(monkeypatch, args, *, write_ref=True):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        if write_ref:
            cache.write_plan_ref(Path(d), _REF)
        return runner.invoke(cli, args)


def test_dry_run_is_offline_and_well_formed(monkeypatch):
    # No gh stubs at all — a dry run must not shell anything.
    result = _run(monkeypatch, ["pr-submit", "--dry-run", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["success"] is True and data["dry_run"] is True
    assert data["branch"] == "plan-7" and data["issue"] == 7
    assert data["pr"]["number"] == 0  # stub (no PR opened on a dry run)
    assert data["plan_header"]["fields_updated"] == ["branch", "pr", "lifecycle_stage"]


def test_no_plan_ref_exits_1(monkeypatch):
    result = _run(monkeypatch, ["pr-submit", "--dry-run", "--json"], write_ref=False)
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "no_plan_ref"


def test_not_a_repo_exits_2(monkeypatch):
    runner = CliRunner()
    with runner.isolated_filesystem():  # no git init
        result = runner.invoke(cli, ["pr-submit", "--dry-run", "--json"])
    assert result.exit_code == 2
    assert json.loads(result.output)["error_type"] == "not_a_repo"


def test_real_submit_opens_pr_and_updates_header(monkeypatch):
    _authed(monkeypatch)
    calls = _stub_gh(monkeypatch)
    result = _run(monkeypatch, ["pr-submit", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["pr"]["number"] == 42 and data["pr"]["existed"] is False
    assert calls["pushed"] is True
    assert calls["header"] == {"branch": "plan-7", "pr": "42", "lifecycle_stage": "impl"}
    # The footer carries the PR number (42), not the issue number (7) — the create-then-update fix.
    assert "`gh pr checkout 42`" in str(calls["pr_body"])
    assert "`gh pr checkout 7`" not in str(calls["pr_body"])
    assert data["pr_checked"] is True and data["plan_embedded"] is False


def test_real_submit_embeds_plan_when_available(monkeypatch):
    _authed(monkeypatch)
    calls = _stub_gh(monkeypatch, plan_body="# My Plan\n\nbody text")
    result = _run(monkeypatch, ["pr-submit", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["plan_embedded"] is True
    body = str(calls["pr_body"])
    assert "<details><summary>Plan #7</summary>" in body and "# My Plan" in body
    assert "`gh pr checkout 42`" in body  # footer stays plain even with the HTML embed


def test_real_submit_idempotent_existing_pr(monkeypatch):
    _authed(monkeypatch)
    _stub_gh(monkeypatch, existed=True)
    result = _run(monkeypatch, ["pr-submit", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["pr"]["existed"] is True


def test_real_submit_plan_not_found_exits_1(monkeypatch):
    _authed(monkeypatch)
    _stub_gh(monkeypatch)
    monkeypatch.setattr(github, "get_plan", lambda **k: None)
    result = _run(monkeypatch, ["pr-submit", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "plan_not_found"


def test_real_submit_force_pushes(monkeypatch):
    _authed(monkeypatch)
    calls = _stub_gh(monkeypatch)
    result = _run(monkeypatch, ["pr-submit", "--json"])
    assert result.exit_code == 0
    assert calls["pushed"] is True
    assert calls["push_kwargs"] == {"force": True}


def test_dirty_tree_refuses_before_push(monkeypatch):
    _authed(monkeypatch)
    calls = _stub_gh(monkeypatch)
    monkeypatch.setattr(git, "is_dirty", lambda root: True)
    result = _run(monkeypatch, ["pr-submit", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "dirty_tree"
    assert calls["pushed"] is False


def test_push_rejected_maps_to_stable_error(monkeypatch):
    _authed(monkeypatch)
    _stub_gh(monkeypatch)

    def _reject(*a, **k):
        raise git.PushRejectedError("! [rejected] plan-7 -> plan-7 (non-fast-forward)")

    monkeypatch.setattr(git, "push", _reject)
    result = _run(monkeypatch, ["pr-submit", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "push_rejected"
