import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk import cache, github
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


def _stub(monkeypatch, *, run_id: str = "01RID") -> dict[str, object]:
    calls: dict[str, object] = {"created": None, "commented": False}
    monkeypatch.setattr(
        github,
        "get_plan",
        lambda **k: github.PlanState(
            number=7, url="u/7", title="My Feature", header={"run_id": run_id}, pr=None
        ),
    )

    def _create(**k):
        calls["created"] = {"run_id": k["run_id"], "plan_number": k["plan_number"]}
        return github.PlanIssue(number=99, url="u/99", existed=False)

    def _comment(**k):
        calls["commented"] = True
        return github.CommentResult(posted=True)

    monkeypatch.setattr(github, "create_learn_issue", _create)
    monkeypatch.setattr(github, "add_issue_comment", _comment)
    return calls


def _run(monkeypatch, extra_args, *, write_ref=True, body="## Learnings\n\nWe deviated."):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        if write_ref:
            cache.write_plan_ref(Path(d), _REF)
        cache.set_marker(Path(d), cache.PENDING_LEARN)
        body_file = Path(d) / "learnings.md"
        body_file.write_text(body, encoding="utf-8")
        result = runner.invoke(cli, ["learn", "capture", "--body", str(body_file), *extra_args])
        marker = cache.has_marker(Path(d), cache.PENDING_LEARN)
        return result, marker


def test_capture_creates_issue_and_clears_marker(monkeypatch):
    _authed(monkeypatch)
    calls = _stub(monkeypatch)
    result, marker = _run(monkeypatch, ["--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["success"] is True and data["learn_issue"]["number"] == 99
    assert data["pending_cleared"] is True
    assert calls["created"] == {"run_id": "01RID", "plan_number": 7}
    assert calls["commented"] is True
    assert marker is False  # pending-learn cleared


def test_capture_dry_run_writes_nothing(monkeypatch):
    result, marker = _run(monkeypatch, ["--dry-run", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["dry_run"] is True
    assert marker is True  # dry run leaves the marker


def test_capture_no_plan_ref_exits_1(monkeypatch):
    result, _ = _run(monkeypatch, ["--dry-run", "--json"], write_ref=False)
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "no_plan_ref"


def test_capture_empty_body_exits_1(monkeypatch):
    result, marker = _run(monkeypatch, ["--dry-run", "--json"], body="   \n")
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "empty_body"
    assert marker is True


def test_capture_not_a_repo_exits_2():
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        body_file = Path(d) / "l.md"
        body_file.write_text("x", encoding="utf-8")
        result = runner.invoke(cli, ["learn", "capture", "--body", str(body_file), "--json"])
    assert result.exit_code == 2
    assert json.loads(result.output)["error_type"] == "not_a_repo"
