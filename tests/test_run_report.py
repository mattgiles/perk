"""`perk run_report` — runner-side run reporting back into GitHub (Node 2.3, contracts §8.15)."""

import json

import pytest

from perk import cache, github, run_report


def _outcome(
    *,
    status: str = "completed",
    terminal_signal: str = "natural_idle",
    pr: dict | None = None,
    error: dict | None = None,
) -> dict:
    return {
        "run_id": "RID",
        "stage": "implement",
        "status": status,
        "terminal_signal": terminal_signal,
        "pr": pr,
        "budget": {"turns": 3, "tokens": 1500, "elapsed_ms": 4200},
        "error": error,
    }


# ----------------------------------------------------------------- run_url_from_env


def test_run_url_from_env_all_present():
    url = run_report.run_url_from_env(
        {
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_REPOSITORY": "me/repo",
            "GITHUB_RUN_ID": "987",
        }
    )
    assert url == "https://github.com/me/repo/actions/runs/987"


@pytest.mark.parametrize(
    "environ",
    [
        {},
        {"GITHUB_SERVER_URL": "https://github.com"},
        {"GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "me/repo"},
        {"GITHUB_REPOSITORY": "me/repo", "GITHUB_RUN_ID": "1"},
    ],
)
def test_run_url_from_env_missing_returns_none(environ):
    assert run_report.run_url_from_env(environ) is None


# ----------------------------------------------------------------- read_outcome


def _write_events(tmp_path, run_id: str, *lines: str) -> None:
    cache.write_scratch(tmp_path, run_id, "events.ndjson", "\n".join(lines) + "\n")


def test_read_outcome_returns_last_run_finished(tmp_path):
    _write_events(
        tmp_path,
        "RID",
        json.dumps({"kind": "run_started", "seq": 0}),
        json.dumps({"kind": "tool_outcome", "seq": 1, "tool": "submit", "ok": True}),
        json.dumps({"kind": "run_finished", "seq": 2, "outcome": _outcome()}),
    )
    out = run_report.read_outcome(tmp_path, "RID")
    assert out is not None and out["status"] == "completed"


def test_read_outcome_missing_file_is_none(tmp_path):
    assert run_report.read_outcome(tmp_path, "NOPE") is None


def test_read_outcome_malformed_line_is_skipped(tmp_path):
    _write_events(
        tmp_path,
        "RID",
        "{ not json",
        json.dumps({"kind": "run_finished", "seq": 1, "outcome": _outcome(status="failed")}),
    )
    out = run_report.read_outcome(tmp_path, "RID")
    assert out is not None and out["status"] == "failed"


def test_read_outcome_no_run_finished_is_none(tmp_path):
    _write_events(tmp_path, "RID", json.dumps({"kind": "run_started", "seq": 0}))
    assert run_report.read_outcome(tmp_path, "RID") is None


# ----------------------------------------------------------------- format_started


def test_format_started_has_marker_and_no_github_prose():
    body = run_report.format_started(
        run_id="RID", stage="implement", plan=42, run_url="https://gh/runs/1"
    )
    assert body.startswith("<!-- perk:run-report:RID -->")
    assert "implement" in body and "plan #42" in body and "RID" in body
    assert "Run: https://gh/runs/1" in body


def test_format_started_without_run_url_omits_link():
    body = run_report.format_started(run_id="RID", stage="implement", plan=42, run_url=None)
    assert "Run:" not in body
    assert body.startswith("<!-- perk:run-report:RID -->")


# ----------------------------------------------------------------- format_outcome


def test_format_outcome_completed_with_pr():
    body = run_report.format_outcome(
        run_id="RID",
        stage="implement",
        plan=42,
        run_url="https://gh/runs/1",
        outcome=_outcome(pr={"number": 7, "url": "https://gh/pull/7"}),
        exit_code=0,
    )
    assert body.startswith("<!-- perk:run-report:RID -->")
    assert "Status: completed" in body
    assert "Opened PR #7 (https://gh/pull/7)" in body
    assert "turns=3" in body and "tokens=1500" in body and "elapsed_ms=4200" in body
    assert "Failure summary" not in body  # completed -> no failure section


def test_format_outcome_failed_carries_failure_summary():
    body = run_report.format_outcome(
        run_id="RID",
        stage="implement",
        plan=42,
        run_url=None,
        outcome=_outcome(status="failed", error={"summary": "boom: it broke"}),
        exit_code=1,
    )
    assert "Status: failed" in body
    assert "**Failure summary:**" in body and "boom: it broke" in body


def test_format_outcome_budget_exhausted_and_aborted_have_failure_section():
    for status in ("budget_exhausted", "aborted"):
        body = run_report.format_outcome(
            run_id="RID",
            stage="address",
            plan=5,
            run_url=None,
            outcome=_outcome(status=status, error={"summary": f"{status} detail"}),
            exit_code=1,
        )
        assert f"Status: {status}" in body
        assert f"{status} detail" in body


def test_format_outcome_address_with_null_pr_omits_pr_line():
    body = run_report.format_outcome(
        run_id="RID",
        stage="address",
        plan=5,
        run_url=None,
        outcome=_outcome(pr=None),
        exit_code=0,
    )
    assert "Opened PR" not in body


def test_format_outcome_degraded_when_outcome_none():
    ok = run_report.format_outcome(
        run_id="RID", stage="implement", plan=42, run_url=None, outcome=None, exit_code=0
    )
    bad = run_report.format_outcome(
        run_id="RID", stage="implement", plan=42, run_url=None, outcome=None, exit_code=2
    )
    assert "no structured outcome on disk" in ok and "completed" in ok
    assert "no structured outcome on disk" in bad and "failed" in bad
    assert ok.startswith("<!-- perk:run-report:RID -->")


# ----------------------------------------------------------------- format_step_summary


def test_format_step_summary_completed():
    summary = run_report.format_step_summary(
        stage="implement", plan=42, run_url="https://gh/runs/1", outcome=_outcome(), exit_code=0
    )
    assert summary.startswith("## perk remote implement")
    assert "Status: completed" in summary and "turns=3" in summary


def test_format_step_summary_failed_has_failure_summary():
    summary = run_report.format_step_summary(
        stage="implement",
        plan=42,
        run_url=None,
        outcome=_outcome(status="failed", error={"summary": "kaboom"}),
        exit_code=1,
    )
    assert "Status: failed" in summary and "kaboom" in summary


def test_format_step_summary_degraded_when_none():
    summary = run_report.format_step_summary(
        stage="implement", plan=42, run_url=None, outcome=None, exit_code=1
    )
    assert "no structured outcome on disk" in summary


# ----------------------------------------------------------------- orchestration


def test_report_started_upserts_marker_comment(tmp_path, monkeypatch):
    calls = {}

    def fake_upsert(*, issue, marker, body, repo_root, dry_run=False):
        calls.update(issue=issue, marker=marker, body=body)
        return github.CommentResult(posted=True)

    monkeypatch.setattr(github, "upsert_marked_comment", fake_upsert)
    run_report.report_started(tmp_path, run_id="RID", stage="implement", plan=42, environ={})
    assert calls["issue"] == 42
    assert calls["marker"] == "<!-- perk:run-report:RID -->"
    assert calls["marker"] in calls["body"]


def test_report_started_swallows_github_error(tmp_path, monkeypatch):
    def boom(**_):
        raise github.GitHubError("nope")

    monkeypatch.setattr(github, "upsert_marked_comment", boom)
    # Fail-soft: must not raise.
    run_report.report_started(tmp_path, run_id="RID", stage="implement", plan=42, environ={})


def test_report_terminal_upserts_and_appends_step_summary(tmp_path, monkeypatch):
    _write_events(
        tmp_path,
        "RID",
        json.dumps(
            {
                "kind": "run_finished",
                "seq": 0,
                "outcome": _outcome(status="failed", error={"summary": "broke"}),
            }
        ),
    )
    bodies = []
    monkeypatch.setattr(
        github,
        "upsert_marked_comment",
        lambda *, issue, marker, body, repo_root, dry_run=False: (
            bodies.append(body) or github.CommentResult(posted=True)
        ),
    )
    summary_file = tmp_path / "summary.md"
    run_report.report_terminal(
        tmp_path,
        run_id="RID",
        stage="implement",
        plan=42,
        exit_code=1,
        environ={"GITHUB_STEP_SUMMARY": str(summary_file)},
    )
    assert bodies and "Status: failed" in bodies[0] and "broke" in bodies[0]
    written = summary_file.read_text(encoding="utf-8")
    assert "## perk remote implement" in written and "broke" in written


def test_report_terminal_skips_summary_when_env_unset(tmp_path, monkeypatch):
    _write_events(
        tmp_path,
        "RID",
        json.dumps({"kind": "run_finished", "seq": 0, "outcome": _outcome()}),
    )
    monkeypatch.setattr(
        github,
        "upsert_marked_comment",
        lambda **_: github.CommentResult(posted=True),
    )
    # No GITHUB_STEP_SUMMARY -> no file write, no raise.
    run_report.report_terminal(
        tmp_path, run_id="RID", stage="implement", plan=42, exit_code=0, environ={}
    )


def test_report_terminal_swallows_github_error(tmp_path, monkeypatch):
    def boom(**_):
        raise github.GitHubError("nope")

    monkeypatch.setattr(github, "upsert_marked_comment", boom)
    run_report.report_terminal(
        tmp_path, run_id="RID", stage="implement", plan=42, exit_code=1, environ={}
    )
