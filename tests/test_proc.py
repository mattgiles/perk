"""Tests for ``perk.substrate.proc`` — the one captured-subprocess primitive.

Each test patches the **global** ``subprocess.run`` (the same surface the facade suites
use), pinning the kwargs contract, the env-overlay layering, and the three ``ProcFailure``
arms with their canonical message shapes.
"""

import shutil
import subprocess

import pytest

from perk.substrate import proc


def test_run_captured_env_overlay_merged_after_environ(monkeypatch):
    """The overlay is layered AFTER os.environ: ambient vars inherited, overlay wins."""
    monkeypatch.setenv("PERK_TEST_AMBIENT", "ambient")
    monkeypatch.setenv("PERK_TEST_OVERRIDDEN", "loses")
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)
        return subprocess.CompletedProcess(args, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = proc.run_captured(
        ["tool", "arg"], timeout=5, env_overlay={"PERK_TEST_OVERRIDDEN": "wins"}
    )
    assert result.stdout == "ok\n"
    assert captured["args"] == ["tool", "arg"]
    assert captured["check"] is False
    assert captured["capture_output"] is True
    assert captured["text"] is True
    assert captured["timeout"] == 5
    env = captured["env"]
    assert env["PERK_TEST_AMBIENT"] == "ambient"
    assert env["PERK_TEST_OVERRIDDEN"] == "wins"


def test_run_captured_no_overlay_passes_env_none(monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    proc.run_captured(["tool"], timeout=5)
    assert captured["env"] is None


def test_run_captured_returns_nonzero_without_raising(monkeypatch):
    """Non-zero exit policy stays with callers — run_captured never raises on it."""

    def fake_run(args, **_):
        return subprocess.CompletedProcess(args, 3, stdout="out", stderr="err")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = proc.run_captured(["tool"], timeout=5)
    assert result.returncode == 3


def test_run_captured_timeout_arm(monkeypatch):
    def fake_run(args, **_):
        raise subprocess.TimeoutExpired(cmd=args, timeout=5)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(proc.ProcFailure) as excinfo:
        proc.run_captured(["tool", "arg"], timeout=5)
    failure = excinfo.value
    assert failure.kind == "timeout"
    assert failure.argv == ("tool", "arg")
    assert str(failure) == "tool arg timed out"
    assert isinstance(failure.__cause__, subprocess.TimeoutExpired)


def test_run_captured_spawn_arm(monkeypatch):
    original = FileNotFoundError(2, "No such file or directory")

    def fake_run(args, **_):
        raise original

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(proc.ProcFailure) as excinfo:
        proc.run_captured(["tool", "arg"], timeout=5)
    failure = excinfo.value
    assert failure.kind == "spawn"
    assert failure.cause_text == str(original)
    assert str(failure) == f"tool arg could not run: {original}"
    assert failure.__cause__ is original  # facades discriminate FileNotFoundError via __cause__


def test_run_interactive_inherits_stdio_and_returns_exit_code(monkeypatch):
    """No capture kwargs: the child inherits the terminal; the exit code passes through."""
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)
        return subprocess.CompletedProcess(args, 7)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert proc.run_interactive(["gh", "auth", "login"], timeout=900) == 7
    assert captured["args"] == ["gh", "auth", "login"]
    assert captured["check"] is False
    assert captured["timeout"] == 900
    for forbidden in ("capture_output", "stdout", "stderr", "stdin", "text"):
        assert forbidden not in captured


def test_run_interactive_zero_exit(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda args, **_: subprocess.CompletedProcess(args, 0))
    assert proc.run_interactive(["tool"], timeout=None) == 0


def test_run_interactive_timeout_arm(monkeypatch):
    def fake_run(args, **_):
        raise subprocess.TimeoutExpired(cmd=args, timeout=5)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(proc.ProcFailure) as excinfo:
        proc.run_interactive(["tool", "arg"], timeout=5)
    assert excinfo.value.kind == "timeout"
    assert str(excinfo.value) == "tool arg timed out"


def test_run_interactive_spawn_arm(monkeypatch):
    original = FileNotFoundError(2, "No such file or directory")

    def fake_run(args, **_):
        raise original

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(proc.ProcFailure) as excinfo:
        proc.run_interactive(["tool"], timeout=5)
    assert excinfo.value.kind == "spawn"
    assert excinfo.value.__cause__ is original


def test_run_checked_returns_stdout_on_success(monkeypatch):
    def fake_run(args, **_):
        return subprocess.CompletedProcess(args, 0, stdout="payload\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert proc.run_checked(["tool"], timeout=5) == "payload\n"


def test_run_checked_exit_arm_prefers_stderr(monkeypatch):
    def fake_run(args, **_):
        return subprocess.CompletedProcess(args, 2, stdout="", stderr="  boom  \n")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(proc.ProcFailure) as excinfo:
        proc.run_checked(["tool", "arg"], timeout=5)
    failure = excinfo.value
    assert failure.kind == "exit"
    assert failure.returncode == 2
    assert failure.stderr == "  boom  \n"
    assert str(failure) == "boom"


def test_run_checked_exit_arm_falls_back_to_cmd_failed(monkeypatch):
    def fake_run(args, **_):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="   ")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(proc.ProcFailure) as excinfo:
        proc.run_checked(["tool", "arg"], timeout=5)
    assert str(excinfo.value) == "tool arg failed"


# --- which_absolute (the shared exec-launcher probe) --------------------------------------------


def test_which_absolute_absolutizes_a_relative_which_result(tmp_path, monkeypatch):
    """A relative PATH entry makes shutil.which return a relative candidate — the probe
    absolutizes it against the cwd AT CALL TIME, so a later chdir cannot reinterpret it."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(shutil, "which", lambda binary: "bin/pi")
    assert proc.which_absolute("pi") == str(tmp_path / "bin" / "pi")


def test_which_absolute_miss_returns_none(monkeypatch):
    """A PATH miss is None — miss policy (the typed refusal) stays with each caller."""
    monkeypatch.setattr(shutil, "which", lambda binary: None)
    assert proc.which_absolute("pi") is None


def test_which_absolute_preserves_a_symlink_candidate(tmp_path, monkeypatch):
    """Path.absolute(), not resolve(): a version-manager shim (a symlink) is returned as the
    symlink pathname, never chased to its target — an implementation that resolved symlinks
    would exec the target instead of the shim."""
    target = tmp_path / "real-pi"
    target.write_text("", encoding="utf-8")
    shim = tmp_path / "shim-pi"
    shim.symlink_to(target)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(shutil, "which", lambda binary: "shim-pi")
    assert proc.which_absolute("pi") == str(tmp_path / "shim-pi")
