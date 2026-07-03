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


def _stub(monkeypatch, *, run_id: str = "01RID") -> dict[str, object]:
    stamps: list[dict] = []
    calls: dict[str, object] = {"created": None, "commented": False, "header_stamps": stamps}
    monkeypatch.setattr(
        plans,
        "get_plan",
        lambda **k: plans.PlanState(
            number=7, url="u/7", title="My Feature", header={"run_id": run_id}, pr=None
        ),
    )

    def _create(**k):
        calls["created"] = {"run_id": k["run_id"], "plan_number": k["plan_number"]}
        calls["decision"] = k.get("decision")
        calls["target"] = k.get("target")
        return plans.PlanIssue(number=99, url="u/99", existed=False)

    def _comment(**k):
        calls["commented"] = True
        return plans.CommentResult(posted=True)

    monkeypatch.setattr(plans, "create_learn_issue", _create)
    monkeypatch.setattr(plans, "add_issue_comment", _comment)

    def _update_header(**k):
        # Record the canonical-first ordering (§8.36): the local pending-learn marker must
        # still be SET when the stamp runs (cleared only after canonical state is terminal).
        stamps.append(
            {
                "fields": k["fields"],
                "marker_set_at_stamp": cache.has_marker(Path.cwd(), cache.PENDING_LEARN),
            }
        )
        return plans.PlanHeaderUpdate(fields_updated=tuple(k["fields"]), dry_run=False)

    monkeypatch.setattr(plans, "update_plan_header", _update_header)
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
    assert data["success"] is True and data["learn_issue"]["id"] == "99"
    assert data["pending_cleared"] is True
    assert calls["created"] == {"run_id": "01RID", "plan_number": 7}
    assert calls["commented"] is True
    assert marker is False  # pending-learn cleared


def test_capture_threads_decision_and_target(monkeypatch):
    _authed(monkeypatch)
    calls = _stub(monkeypatch)
    result, _ = _run(
        monkeypatch,
        ["--json", "--decision", "UPDATE_EXISTING_DOC", "--target", "docs/learned/x.md"],
    )
    assert result.exit_code == 0
    assert calls["decision"] == "UPDATE_EXISTING_DOC"
    assert calls["target"] == "docs/learned/x.md"
    # The --json envelope is unchanged (the classification lives on the issue header, not here).
    data = json.loads(result.output)
    assert "decision" not in data and "target" not in data


def test_capture_rejects_out_of_set_decision(monkeypatch):
    _authed(monkeypatch)
    _stub(monkeypatch)
    result, marker = _run(monkeypatch, ["--json", "--decision", "NONSENSE"])
    assert result.exit_code != 0  # click.Choice rejects it before any work
    assert marker is True  # nothing cleared


def test_capture_stamps_captured_before_marker_clear(monkeypatch):
    _authed(monkeypatch)
    calls = _stub(monkeypatch)
    result, marker = _run(monkeypatch, ["--json"])
    assert result.exit_code == 0
    assert calls["header_stamps"] == [
        {"fields": {"learn_state": "captured"}, "marker_set_at_stamp": True}
    ]
    assert marker is False  # cleared only after the canonical stamp


def test_capture_stamp_failure_exits_1_and_keeps_marker(monkeypatch):
    # A failed canonical stamp propagates (strict) and leaves the local marker set — the retry
    # signal; a re-run converges (capture is idempotent via the run_id finder).
    _authed(monkeypatch)
    _stub(monkeypatch)

    def _boom(**k):
        raise github.GitHubError("gh exploded")

    monkeypatch.setattr(plans, "update_plan_header", _boom)
    result, marker = _run(monkeypatch, ["--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "github_error"
    assert marker is True  # the marker survives a failed stamp


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
