"""`perk-dev profile-startup` — the Click verb: every option-domain refusal, the output-directory
arms, `tool_missing`, and the supervisor contract over a monkeypatched `run_profile` (`--json`
bytes on stdout equal to `summary.json`, the human summary on stderr, exit 0 with failed
samples plus the `warning:` line)."""

import json
import stat
from pathlib import Path

import pytest
from click.testing import CliRunner
from perk_dev.cli import cli
from perk_dev.profile_startup import cli as cli_mod
from perk_dev.profile_startup import summary as summary_mod
from perk_dev.profile_startup.pty_session import PtyRun, PtySize
from perk_dev.profile_startup.subjects import SubjectStamp

_STDERR_OK = (
    "--- Startup Timings: main ---\n  imports: 100ms\n  TOTAL: 600ms\n"
    "-----------------------------\n"
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _prepare_subject(root: Path) -> Path:
    bin_dir = root / ".venv" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name in ("perk", "python"):
        tool = bin_dir / name
        tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
    (root / ".pi" / "npm" / "node_modules").mkdir(parents=True, exist_ok=True)
    _write_json(root / ".pi" / "npm" / "package.json", {"dependencies": {}})
    return root


@pytest.fixture
def subject_dir(tmp_path) -> Path:
    return _prepare_subject(tmp_path / "subject")


@pytest.fixture
def tools_on_path(monkeypatch):
    monkeypatch.setattr(
        cli_mod, "which_absolute", lambda name: {"pi": "/opt/bin/pi", "node": "/opt/bin/node"}[name]
    )


def _invoke(args: list[str]):
    return CliRunner().invoke(cli, ["profile-startup", *args])


def _payload(result) -> dict:
    return json.loads(result.stdout)


def _base_args(tmp_path: Path, subject_dir: Path, *extra: str) -> list[str]:
    return ["--output", str(tmp_path / "out"), "--subject", f"s={subject_dir}", *extra]


# --- option domains -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("extra", "needle"),
    [
        (["--runs", "0"], "--runs"),
        (["--timeout", "0"], "--timeout"),
        (["--timeout", "inf"], "--timeout"),
        (["--exit-grace", "-1"], "--exit-grace"),
        (["--exit-grace", "nan"], "--exit-grace"),
        (["--pty-size", "10x10"], "--pty-size"),
        (["--pty-size", "500x40"], "--pty-size"),
        (["--pty-size", "120x300"], "--pty-size"),
        (["--pty-size", "wide"], "--pty-size"),
    ],
)
def test_option_domain_violations_are_bad_arguments(
    tmp_path, subject_dir, tools_on_path, extra, needle
):
    result = _invoke([*_base_args(tmp_path, subject_dir), *extra, "--json"])
    assert result.exit_code == 1
    payload = _payload(result)
    assert payload["success"] is False and payload["error_type"] == "bad_arguments"
    assert needle in payload["message"]
    assert not (tmp_path / "out").exists()  # decided before the output dir is created


def test_missing_output_and_missing_subject_are_bad_arguments(tmp_path, subject_dir, tools_on_path):
    result = _invoke(["--subject", f"s={subject_dir}", "--json"])
    assert result.exit_code == 1 and _payload(result)["error_type"] == "bad_arguments"
    assert "--output" in _payload(result)["message"]
    result = _invoke(["--output", str(tmp_path / "out"), "--json"])
    assert result.exit_code == 1 and _payload(result)["error_type"] == "bad_arguments"
    assert "--subject" in _payload(result)["message"]


def test_bad_subject_label_is_bad_arguments_on_the_human_surface(
    tmp_path, subject_dir, tools_on_path
):
    result = _invoke(["--output", str(tmp_path / "out"), "--subject", f"bad label={subject_dir}"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Error:" in result.stderr and "bad label" in result.stderr
    assert "bad_arguments" not in result.stderr  # the human surface never renders the code


def test_output_with_a_double_quote_is_refused(tmp_path, subject_dir, tools_on_path):
    result = _invoke(
        ["--output", str(tmp_path / 'we"ird'), "--subject", f"s={subject_dir}", "--json"]
    )
    assert result.exit_code == 1
    assert _payload(result)["error_type"] == "bad_arguments"
    assert "NODE_OPTIONS" in _payload(result)["message"]


def test_output_that_is_a_file_is_refused(tmp_path, subject_dir, tools_on_path):
    (tmp_path / "file").write_text("x", encoding="utf-8")
    result = _invoke(
        ["--output", str(tmp_path / "file"), "--subject", f"s={subject_dir}", "--json"]
    )
    assert result.exit_code == 1 and _payload(result)["error_type"] == "bad_arguments"


def test_non_empty_output_is_output_not_empty(tmp_path, subject_dir, tools_on_path):
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "stale").write_text("x", encoding="utf-8")
    result = _invoke([*_base_args(tmp_path, subject_dir), "--json"])
    assert result.exit_code == 1 and _payload(result)["error_type"] == "output_not_empty"


def test_subject_refusals_surface_their_error_type(tmp_path, tools_on_path):
    result = _invoke(
        ["--output", str(tmp_path / "out"), "--subject", f"s={tmp_path / 'nope'}", "--json"]
    )
    assert result.exit_code == 1 and _payload(result)["error_type"] == "subject_missing"
    root = _prepare_subject(tmp_path / "unconverged")
    (root / ".pi" / "npm" / "package.json").unlink()
    result = _invoke(["--output", str(tmp_path / "out"), "--subject", f"s={root}", "--json"])
    assert result.exit_code == 1 and _payload(result)["error_type"] == "subject_not_converged"


def test_missing_pi_or_node_is_tool_missing(tmp_path, subject_dir, monkeypatch):
    monkeypatch.setattr(cli_mod, "which_absolute", lambda name: None)
    result = _invoke([*_base_args(tmp_path, subject_dir), "--json"])
    assert result.exit_code == 1
    assert _payload(result)["error_type"] == "tool_missing"
    assert "`pi`" in _payload(result)["message"]


# --- the supervisor contract over a canned run --------------------------------------------------


def _stamp() -> SubjectStamp:
    return SubjectStamp(
        head="a" * 40,
        dirty=False,
        perk_version="perk 3.6.0",
        pi_version="0.87.0",
        pi_path="/opt/pi/dist/bundle/cli.js",
        node_version="v26.3.0",
        packages={},
        sdk_copies=(),
        agent_dir="/agent",
        agent_dir_source="env",
        trusted_by="trusted_by=defaultProjectTrust",
    )


def _canned_summary(options, *, failed_only: bool) -> summary_mod.Summary:
    ok = summary_mod.classify_sample(
        PtyRun(0, 900.0, 1200.0, False, False, _STDERR_OK, 10, 1),
        index=1,
    )
    bad = summary_mod.classify_sample(
        PtyRun(-9, None, None, True, False, "", 0, 1),
        index=2,
    )
    subjects = [
        summary_mod.SubjectSummary(
            label=s.label,
            checkout=str(s.checkout),
            stamp=_stamp(),
            first_run=ok,
            samples=(bad,) if failed_only else (ok, bad),
            handoff=None,
            census=None,
        )
        for s in options.subjects
    ]
    return summary_mod.build_summary(
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:01:00+00:00",
        tool=summary_mod.ToolInfo(perk_version="3.6.0", perk_dev_head=None),
        host=summary_mod.HostInfo(platform="test", machine="arm64", cpu_count=8),
        options=summary_mod.RunOptions(
            runs=options.runs,
            timeout_s=options.timeout_s,
            exit_grace_s=options.exit_grace_s,
            pty_size=options.pty_size,
            profiles=options.profiles,
        ),
        env=summary_mod.EnvInfo(injected={}, removed=(), operator_node_options=None),
        subjects=subjects,
    )


@pytest.fixture
def canned_run(monkeypatch):
    """Replace `run_profile` with a fake that writes `summary.json` the way the harness does and
    records the options it received."""
    seen: dict = {}

    def fake_run_profile(options, *, report, failed_only=False):
        seen["options"] = options
        summary = _canned_summary(options, failed_only=seen.get("failed_only", False))
        report("stamping s")
        (options.output / "summary.json").write_text(
            summary_mod.summary_json_text(summary), encoding="utf-8"
        )
        return summary

    monkeypatch.setattr(cli_mod, "run_profile", fake_run_profile)
    return seen


def test_json_payload_is_byte_identical_to_summary_json(
    tmp_path, subject_dir, tools_on_path, canned_run
):
    result = _invoke(
        [*_base_args(tmp_path, subject_dir), "--runs", "2", "--pty-size", "80x24", "--json"]
    )
    assert result.exit_code == 0, result.output
    written = (tmp_path / "out" / "summary.json").read_text(encoding="utf-8")
    assert result.stdout == written
    payload = json.loads(result.stdout)
    assert payload["schema"] == 1
    assert payload["subjects"][0]["samples"] == {
        "count": 2,
        "failed": 1,
        "elapsed_ms": {"median": 900.0, "min": 900.0, "max": 900.0, "count": 1},
        "pi_main_total_ms": {"median": 600.0, "min": 600.0, "max": 600.0, "count": 1},
        "pre_pi_remainder_ms": {"median": 300.0, "min": 300.0, "max": 300.0, "count": 1},
    }
    options = canned_run["options"]
    assert options.runs == 2 and options.pty_size == PtySize(cols=80, rows=24)
    assert options.profiles is True
    assert options.output == (tmp_path / "out").resolve()
    assert options.pi_path == "/opt/bin/pi" and options.node_path == "/opt/bin/node"
    assert [s.label for s in options.subjects] == ["s"]
    # Progress narration stays on stderr under --json; no warning: one sample succeeded.
    assert "stamping s" in result.stderr
    assert "warning:" not in result.stderr


def test_human_summary_goes_to_stderr_and_exit_is_zero_with_failed_samples(
    tmp_path, subject_dir, tools_on_path, canned_run
):
    result = _invoke([*_base_args(tmp_path, subject_dir), "--no-profiles"])
    assert result.exit_code == 0, result.output
    assert result.stdout == ""
    assert "# perk startup profile" in result.stderr
    assert "derived estimate" in result.stderr
    assert canned_run["options"].profiles is False
    assert "warning:" not in result.stderr


def test_warning_line_for_a_subject_with_zero_successful_samples(
    tmp_path, subject_dir, tools_on_path, canned_run
):
    canned_run["failed_only"] = True
    result = _invoke([*_base_args(tmp_path, subject_dir), "--json"])
    assert result.exit_code == 0, result.output  # a completed run reports, never fails
    assert json.loads(result.stdout)["subjects"][0]["samples"]["failed"] == 1
    assert (
        "warning:" in result.stderr and "subject s produced no successful sample" in result.stderr
    )


def test_io_error_from_the_run_names_the_partial_directory(
    tmp_path, subject_dir, tools_on_path, monkeypatch
):
    def failing_run_profile(options, *, report):
        (options.output / "meta.json").write_text("{}", encoding="utf-8")
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(cli_mod, "run_profile", failing_run_profile)
    result = _invoke([*_base_args(tmp_path, subject_dir), "--json"])
    assert result.exit_code == 1
    payload = _payload(result)
    assert payload["error_type"] == "io_error"
    assert str((tmp_path / "out").resolve()) in payload["message"]
    assert (tmp_path / "out" / "meta.json").exists()  # the partial run directory is left in place


def test_subject_refusal_inside_the_run_is_typed(tmp_path, subject_dir, tools_on_path, monkeypatch):
    from perk.cli.ensure import UserFacingCliError

    def refusing_run_profile(options, *, report):
        raise UserFacingCliError("subject s: not trusted", error_type="subject_untrusted")

    monkeypatch.setattr(cli_mod, "run_profile", refusing_run_profile)
    result = _invoke([*_base_args(tmp_path, subject_dir), "--json"])
    assert result.exit_code == 1 and _payload(result)["error_type"] == "subject_untrusted"


def test_profile_startup_is_registered():
    assert "profile-startup" in cli.commands


# --- the developer how-to -----------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_profiling_how_to_is_indexed_and_states_its_kind():
    how_to = REPO_ROOT / "docs/developers/profiling-startup.md"
    text = how_to.read_text(encoding="utf-8")
    assert text.startswith("# Profiling perk's startup\n\nThis page is a **how-to guide**")
    index = (REPO_ROOT / "docs/developers/index.md").read_text(encoding="utf-8")
    assert "(./profiling-startup.md) | How-to |" in index, (
        "docs/developers/index.md must link the profiling how-to as a How-to row"
    )
    # The how-to names the seam variable, the injected env, and every option once.
    assert "PERK_PROFILE_HANDOFF" in text
    for name in ("PI_STARTUP_BENCHMARK=1", "PI_TIMING=1", "PI_OFFLINE=1"):
        assert name in text
    for option in (
        "--runs",
        "--output",
        "--subject",
        "--timeout",
        "--exit-grace",
        "--pty-size",
        "--no-profiles",
        "--json",
    ):
        assert f"`{option}" in text, option
    assert "derived estimate" in text
    assert "§8.72(i)" in text
