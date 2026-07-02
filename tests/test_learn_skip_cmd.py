import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk import github, plan
from perk.backends.github import plans
from perk.cli.cli import cli
from perk.state import cache

_REF = plan.PlanRef(
    provider="github",
    pr_id="7",
    url="https://gh/o/r/issues/7",
    labels=("perk:plan",),
    objective_id=None,
)


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _authed(monkeypatch) -> None:
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(True, "octocat", ("repo",), None)
    )


def _stub(monkeypatch, *, header: dict | None = None) -> dict[str, object]:
    stamps: list[dict] = []
    calls: dict[str, object] = {"header_stamps": stamps}
    monkeypatch.setattr(
        plans,
        "get_plan",
        lambda **k: plans.PlanState(
            number=7, url="u/7", title="My Feature", header=header or {}, pr=None
        ),
    )

    def _update_header(**k):
        # Record the canonical-first ordering (§8.36): the local pending-learn marker must
        # still be SET when the stamp runs (cleared only after the stamp succeeds).
        stamps.append(
            {
                "fields": k["fields"],
                "marker_set_at_stamp": cache.has_marker(Path.cwd(), cache.PENDING_LEARN),
            }
        )
        return plans.PlanHeaderUpdate(fields_updated=tuple(k["fields"]), dry_run=False)

    monkeypatch.setattr(plans, "update_plan_header", _update_header)
    return calls


def _run(extra_args, *, write_ref=True):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        if write_ref:
            cache.write_plan_ref(Path(d), _REF)
        cache.set_marker(Path(d), cache.PENDING_LEARN)
        result = runner.invoke(cli, ["learn", "skip", *extra_args])
        marker = cache.has_marker(Path(d), cache.PENDING_LEARN)
        return result, marker


def test_skip_stamps_skipped_and_clears_marker(monkeypatch):
    _authed(monkeypatch)
    calls = _stub(monkeypatch)
    result, marker = _run(["--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["success"] is True and data["learn_state"] == "skipped"
    assert data["plan_issue"] == "7" and data["pending_cleared"] is True
    assert calls["header_stamps"] == [
        {"fields": {"learn_state": "skipped"}, "marker_set_at_stamp": True}
    ]
    assert marker is False


def test_skip_never_downgrades_captured(monkeypatch):
    # Already-captured plan: no-op stamp, the marker is still cleared, the envelope reports the
    # kept `captured` state (never resurrected to skipped/pending).
    _authed(monkeypatch)
    calls = _stub(monkeypatch, header={"learn_state": "captured"})
    result, marker = _run(["--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["learn_state"] == "captured" and data["pending_cleared"] is True
    assert calls["header_stamps"] == []  # no write on the guard arm
    assert marker is False


def test_skip_stamp_failure_exits_1_and_keeps_marker(monkeypatch):
    # A failed canonical stamp propagates (strict) and leaves the marker set — the retry signal.
    _authed(monkeypatch)
    _stub(monkeypatch)

    def _boom(**k):
        raise github.GitHubError("gh exploded")

    monkeypatch.setattr(plans, "update_plan_header", _boom)
    result, marker = _run(["--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "github_error"
    assert marker is True


def test_skip_plan_not_found_exits_1(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(plans, "get_plan", lambda **k: None)
    result, marker = _run(["--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "plan_not_found"
    assert marker is True


def test_skip_no_plan_ref_exits_1():
    result, _ = _run(["--dry-run", "--json"], write_ref=False)
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "no_plan_ref"


def test_skip_dry_run_is_offline_and_inert():
    # No auth stub, no backend stubs: --dry-run composes only (no write, no marker change).
    result, marker = _run(["--dry-run", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data == {
        "success": True,
        "error_type": None,
        "message": None,
        "plan_issue": "7",
        "learn_state": "skipped",
        "pending_cleared": False,
        "dry_run": True,
    }
    assert marker is True  # dry run leaves the marker


def test_skip_not_a_repo_exits_2():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["learn", "skip", "--json"])
    assert result.exit_code == 2
    assert json.loads(result.output)["error_type"] == "not_a_repo"
