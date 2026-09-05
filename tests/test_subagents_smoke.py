"""`perk-dev subagents-smoke` — the opt-in live pi-subagents smoke's OFFLINE surfaces.

Everything here is pure or monkeypatched: the event-stream evaluator over canned NDJSON, the
baseline gathering from planted package.json files, the preflight fail arms, and the spawn
contract (the env-leak guard asserted through a monkeypatched `run_captured`). No live spawn
ever happens in tests — the live run is implementation evidence bound to a committed SHA, not
a CI check.
"""

import json
import subprocess

import pytest
from perk_dev import subagents_smoke
from perk_dev.cli import cli

from perk.cli.ensure import UserFacingCliError
from perk.substrate import proc

# --- the event-stream evaluator (pure) -------------------------------------------------------


def _end_event(*, tool=subagents_smoke.SMOKE_TOOL, ok=True, is_error=False, report=True):
    details = {"ok": ok}
    if report:
        details["report"] = {"node": "1.1", "relevant_files": []}
    return {
        "type": "tool_execution_end",
        "toolCallId": "call-1",
        "toolName": tool,
        "result": {"content": [{"type": "text", "text": "…"}], "details": details},
        "isError": is_error,
    }


def _stream(*events) -> str:
    return "\n".join(json.dumps(e) for e in events) + "\n"


def test_evaluator_success_arm():
    stdout = _stream(
        {"type": "agent_start"},
        {"type": "tool_execution_start", "toolName": subagents_smoke.SMOKE_TOOL},
        _end_event(),
        {"type": "agent_end"},
    )
    evaluation = subagents_smoke.evaluate_event_stream(stdout)
    assert evaluation.passed is True
    assert evaluation.reason is None
    assert evaluation.tool_executions == 1


def test_evaluator_tolerates_non_json_lines():
    stdout = "some banner text\n" + _stream(_end_event()) + "trailing noise\n"
    evaluation = subagents_smoke.evaluate_event_stream(stdout)
    assert evaluation.passed is True


def test_evaluator_no_tool_call_arm():
    stdout = _stream({"type": "agent_start"}, {"type": "agent_end"})
    evaluation = subagents_smoke.evaluate_event_stream(stdout)
    assert evaluation.passed is False
    assert (
        evaluation.reason is not None and "no explore_objective_node tool call" in evaluation.reason
    )


def test_evaluator_ignores_other_tools():
    stdout = _stream(_end_event(tool="read"), {"type": "agent_end"})
    evaluation = subagents_smoke.evaluate_event_stream(stdout)
    assert evaluation.passed is False
    assert evaluation.tool_executions == 0


def test_evaluator_tool_error_arm():
    # The explore tool never throws — a failure is a soft result with details.ok false.
    stdout = _stream(_end_event(ok=False, report=False))
    evaluation = subagents_smoke.evaluate_event_stream(stdout)
    assert evaluation.passed is False
    assert (
        evaluation.reason is not None and "did not return a successful report" in evaluation.reason
    )
    assert evaluation.tool_executions == 1


def test_evaluator_is_error_arm():
    stdout = _stream(_end_event(is_error=True))
    assert subagents_smoke.evaluate_event_stream(stdout).passed is False


def test_evaluator_ok_without_report_fails():
    stdout = _stream(_end_event(report=False))
    assert subagents_smoke.evaluate_event_stream(stdout).passed is False


def test_evaluator_multiple_executions_arm():
    stdout = _stream(_end_event(), _end_event())
    evaluation = subagents_smoke.evaluate_event_stream(stdout)
    assert evaluation.passed is False
    assert evaluation.reason is not None and "exactly one" in evaluation.reason
    assert evaluation.tool_executions == 2


def test_evaluator_unparseable_stream_arm():
    evaluation = subagents_smoke.evaluate_event_stream("no json here\nat all\n")
    assert evaluation.passed is False
    assert evaluation.reason is not None and "stream unparseable" in evaluation.reason


# --- baseline gathering ----------------------------------------------------------------------


def _plant_versions(root, *, pi="0.84.1", subagents="0.65.1"):
    pi_pkg = root / "node_modules" / "@earendil-works" / "pi-coding-agent"
    pi_pkg.mkdir(parents=True, exist_ok=True)
    (pi_pkg / "package.json").write_text(json.dumps({"version": pi}), encoding="utf-8")
    sub_pkg = root / ".pi" / "npm" / "node_modules" / "pi-subagents"
    sub_pkg.mkdir(parents=True, exist_ok=True)
    (sub_pkg / "package.json").write_text(json.dumps({"version": subagents}), encoding="utf-8")


def test_gather_baseline_reads_planted_versions(git_repo):
    _plant_versions(git_repo, pi="0.84.1", subagents="0.65.1")
    baseline = subagents_smoke.gather_baseline(git_repo)
    assert baseline.pi_version == "0.84.1"
    assert baseline.subagents_version == "0.65.1"
    assert baseline.repo_commit is not None and len(baseline.repo_commit) == 40


def test_gather_baseline_dirty_flag_and_missing_versions(git_repo):
    clean = subagents_smoke.gather_baseline(git_repo)
    assert clean.dirty is False  # the fixture repo is clean at HEAD
    assert clean.pi_version is None  # nothing planted → best-effort None, never a raise
    assert clean.subagents_version is None
    (git_repo / "scratch.txt").write_text("dirt\n", encoding="utf-8")
    assert subagents_smoke.gather_baseline(git_repo).dirty is True


# --- preflight fail arms ---------------------------------------------------------------------


def test_preflight_pi_binary_missing(git_repo):
    with pytest.raises(UserFacingCliError) as excinfo:
        subagents_smoke.preflight(git_repo)
    assert excinfo.value.error_type == "pi_missing"
    assert "just install" in str(excinfo.value)


def test_preflight_subagents_missing(git_repo):
    pi_bin = git_repo / "node_modules" / ".bin" / "pi"
    pi_bin.parent.mkdir(parents=True, exist_ok=True)
    pi_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    with pytest.raises(UserFacingCliError) as excinfo:
        subagents_smoke.preflight(git_repo)
    assert excinfo.value.error_type == "subagents_missing"
    assert "lazy-installs" in str(excinfo.value)


def test_cli_not_a_repo_arm(tmp_path, monkeypatch):
    from click.testing import CliRunner

    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["subagents-smoke", "--json"])
    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    assert payload["success"] is False
    assert payload["error_type"] == "not_a_repo"


# --- the spawn contract (no live spawn — a recorded fake) ------------------------------------


def _ready_repo(git_repo):
    """A repo passing preflight with planted version files."""
    pi_bin = git_repo / "node_modules" / ".bin" / "pi"
    pi_bin.parent.mkdir(parents=True, exist_ok=True)
    pi_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    _plant_versions(git_repo)
    return git_repo


def _fake_pi_spawn(monkeypatch, recorded, *, stdout, returncode=0):
    """Monkeypatch run_captured to fake ONLY the pi spawn — git traffic (the baseline
    gathering routes through the same proc primitive) passes through to the real thing."""
    real = proc.run_captured

    def fake_run_captured(argv, **kwargs):
        if not argv[0].endswith("pi"):
            return real(argv, **kwargs)
        recorded["argv"] = list(argv)
        recorded.update(kwargs)
        return subprocess.CompletedProcess(list(argv), returncode, stdout=stdout, stderr="")

    monkeypatch.setattr(subagents_smoke.proc, "run_captured", fake_run_captured)


def test_run_smoke_spawn_contract(git_repo, monkeypatch):
    """The spawn rides run_captured with the env-leak guard and the headless argv shape."""
    root = _ready_repo(git_repo)
    recorded = {}
    _fake_pi_spawn(monkeypatch, recorded, stdout=_stream(_end_event()))
    result = subagents_smoke.run_smoke(root)
    assert result.evaluation.passed is True
    assert recorded["env_remove"] == ("PERK_RUN_ID", "PI_SESSION_FILE")
    assert recorded["cwd"] == root
    assert recorded["timeout"] == subagents_smoke.SMOKE_TIMEOUT_SECONDS
    assert recorded["argv"][0].endswith("node_modules/.bin/pi")
    assert recorded["argv"][1:4] == ["--mode", "json", "-p"]
    assert recorded["argv"][4] == subagents_smoke.SMOKE_PROMPT
    assert result.baseline.pi_version == "0.84.1"
    assert result.baseline.subagents_version == "0.65.1"


def test_run_smoke_nonzero_exit_contradicts_a_passing_stream(git_repo, monkeypatch):
    root = _ready_repo(git_repo)
    _fake_pi_spawn(monkeypatch, {}, stdout=_stream(_end_event()), returncode=3)
    result = subagents_smoke.run_smoke(root)
    assert result.evaluation.passed is False
    assert result.evaluation.reason is not None and "pi exited 3" in result.evaluation.reason


def test_run_smoke_spawn_failure_is_user_facing(git_repo, monkeypatch):
    root = _ready_repo(git_repo)
    real = proc.run_captured

    def fake_run_captured(argv, **kwargs):
        if not argv[0].endswith("pi"):
            return real(argv, **kwargs)
        raise proc.ProcFailure("timeout", tuple(argv))

    monkeypatch.setattr(subagents_smoke.proc, "run_captured", fake_run_captured)
    with pytest.raises(UserFacingCliError) as excinfo:
        subagents_smoke.run_smoke(root)
    assert excinfo.value.error_type == "spawn_failed"


# --- the report envelope + human summary -----------------------------------------------------


def _fake_result(*, passed=True, reason=None):
    return subagents_smoke.SmokeResult(
        baseline=subagents_smoke.SmokeBaseline(
            perk_version="9.9.9",
            repo_commit="a" * 40,
            dirty=False,
            pi_version="0.84.1",
            subagents_version="0.65.1",
        ),
        evaluation=subagents_smoke.SmokeEvaluation(
            passed=passed, reason=reason, tool_executions=1 if passed else 0
        ),
        exit_code=0,
    )


def test_json_envelope_shape():
    out = subagents_smoke.SubagentsSmokeOut.from_domain(_fake_result())
    payload = out.model_dump(mode="json")
    assert payload == {
        "success": True,
        "error_type": None,
        "passed": True,
        "reason": None,
        "tool_executions": 1,
        "exit_code": 0,
        "perk_version": "9.9.9",
        "repo_commit": "a" * 40,
        "dirty": False,
        "pi_version": "0.84.1",
        "subagents_version": "0.65.1",
    }


def test_summary_lines_pass_and_fail():
    passing = subagents_smoke.summary_lines(_fake_result())
    assert passing[0] == "subagents-smoke: PASS"
    assert any("pi 0.84.1" in line and "pi-subagents 0.65.1" in line for line in passing)
    assert not any("failure:" in line for line in passing)

    failing = subagents_smoke.summary_lines(
        _fake_result(passed=False, reason="no explore_objective_node tool call observed")
    )
    assert failing[0] == "subagents-smoke: FAIL"
    assert any("failure: no explore_objective_node" in line for line in failing)


def test_cli_fail_verdict_exits_nonzero(git_repo, monkeypatch):
    root = _ready_repo(git_repo)
    _fake_pi_spawn(monkeypatch, {}, stdout="not json\n")
    monkeypatch.chdir(root)
    from click.testing import CliRunner

    result = CliRunner().invoke(cli, ["subagents-smoke", "--json"])
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["success"] is True
    assert payload["passed"] is False
    assert "stream unparseable" in payload["reason"]
