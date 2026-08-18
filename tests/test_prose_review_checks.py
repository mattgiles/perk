"""The Prose Review CheckRunner: the pinned allowlist and the streaming process seam."""

import dataclasses
import os
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from perk_dev.prose_review import checks as checks_module
from perk_dev.prose_review.checks import (
    CHECK_COMMANDS,
    OUTPUT_CAP_CHARS,
    RUN_HISTORY_LIMIT,
    CheckCommand,
    CheckRunner,
    CheckRunSnapshot,
)

DEADLINE_SECONDS = 30.0


def _wait_for[T](
    condition: Callable[[], T | None],
    *,
    message: str,
    deadline: float = DEADLINE_SECONDS,
) -> T:
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        value = condition()
        if value is not None:
            return value
        time.sleep(0.02)
    pytest.fail(message)


def _wait_terminal(runner: CheckRunner, run_id: str) -> CheckRunSnapshot:
    def terminal() -> CheckRunSnapshot | None:
        snapshot = runner.get(run_id)
        assert snapshot is not None
        return snapshot if snapshot.status != "running" else None

    return _wait_for(terminal, message=f"run {run_id} never went terminal")


def _fake(script: str, *, timeout_seconds: int = 30) -> CheckCommand:
    return CheckCommand(
        label="Fake check",
        argv=(sys.executable, "-c", script),
        timeout_seconds=timeout_seconds,
    )


# Prints its own pid (so tests can prove the process group died), then a marker line,
# then blocks until killed.
_PID_THEN_BLOCK = (
    "import os, sys, time\n"
    "print(os.getpid(), flush=True)\n"
    "print('STARTED', flush=True)\n"
    "time.sleep(600)\n"
)

# A same-group descendant that ignores SIGTERM and holds the inherited stdout pipe;
# CHILD-UP is printed only after the handler is installed, so a test that waited for
# it genuinely exercises the resistant arm.
_RESISTANT_CHILD_SOURCE = (
    "import signal, time\n"
    "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
    "print('CHILD-UP', flush=True)\n"
    "while True:\n"
    "    time.sleep(0.2)\n"
)
# The leader spawns the resistant child (inheriting the process group and stdout),
# reports both pids, then blocks; the leader itself dies on SIGTERM.
_RESISTANT_FAMILY_SCRIPT = (
    "import os, subprocess, sys, time\n"
    f"child = subprocess.Popen([sys.executable, '-c', {_RESISTANT_CHILD_SOURCE!r}])\n"
    "print(os.getpid(), flush=True)\n"
    "print(child.pid, flush=True)\n"
    "print('STARTED', flush=True)\n"
    "time.sleep(600)\n"
)


def _started_pid(runner: CheckRunner, run_id: str) -> int:
    def pid() -> int | None:
        snapshot = runner.get(run_id)
        assert snapshot is not None
        lines = snapshot.output.splitlines()
        return int(lines[0]) if "STARTED" in lines else None

    return _wait_for(pid, message=f"run {run_id} never printed its pid")


def _assert_group_dead(pid: int) -> None:
    def dead() -> bool | None:
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            return True
        return None

    _wait_for(dead, message=f"process group {pid} still alive")


def _assert_threads_settle(baseline: set[threading.Thread]) -> None:
    """Reader and timer threads must finish once their run is terminal."""

    def settled() -> bool | None:
        return True if set(threading.enumerate()) <= baseline else None

    _wait_for(settled, message=f"lingering threads: {set(threading.enumerate()) - baseline}")


# ── The allowlist pin ─────────────────────────────────────────────────────────


def test_check_commands_table_is_exactly_the_reviewed_allowlist() -> None:
    # Any change to a check id, argv, or timeout is a reviewed diff of this pin.
    expected: dict[str, tuple[str, tuple[str, ...], int]] = {
        "prose-map": (
            "Prose map check",
            ("uv", "run", "--no-sync", "perk-dev", "prose-map", "check"),
            120,
        ),
        "learned-docs": (
            "Learned docs check",
            ("uv", "run", "--no-sync", "perk", "learn", "docs-check"),
            120,
        ),
        "prompt-parity": (
            "Prompt render parity (pytest)",
            (
                "uv",
                "run",
                "--no-sync",
                "pytest",
                "tests/test_prompt_parity.py",
                "tests/test_binding_render_parity.py",
                "-q",
            ),
            900,
        ),
        "worker-prompt-pins": (
            "Worker prompt pins (pytest)",
            ("uv", "run", "--no-sync", "pytest", "tests/test_worker_prompt_parity.py", "-q"),
            300,
        ),
        "worker-test-pins": (
            "Worker prompt pins (node:test)",
            ("node", "--test", "extension/worker/worker.test.ts"),
            300,
        ),
        "ruff": (
            "Ruff lint (check-only)",
            (
                "uv",
                "run",
                "--no-sync",
                "ruff",
                "check",
                "src/perk",
                "packages/perk-dev/src",
                "tests",
            ),
            120,
        ),
        "ty": ("ty typecheck", ("uv", "run", "--no-sync", "ty", "check"), 300),
        "biome": (
            "Biome lint (check-only)",
            ("npx", "--no-install", "biome", "check", "extension", "tools"),
            120,
        ),
        "tsc": ("TypeScript typecheck", ("npx", "--no-install", "tsc", "--noEmit"), 300),
    }
    assert {
        check_id: (command.label, command.argv, command.timeout_seconds)
        for check_id, command in CHECK_COMMANDS.items()
    } == expected


def test_check_commands_structural_invariants_pin_the_never_list() -> None:
    for check_id, command in CHECK_COMMANDS.items():
        assert command.argv[0] in ("uv", "npx", "node"), check_id
        if command.argv[0] == "uv":
            assert command.argv[:3] == ("uv", "run", "--no-sync"), check_id
        if command.argv[0] == "npx":
            assert command.argv[:2] == ("npx", "--no-install"), check_id
        for element in command.argv:
            # Check-only, never mutating; the full gates stay run_ci territory.
            assert "--fix" not in element, check_id
            assert "--write" not in element, check_id
            assert "--unsafe-fixes" not in element, check_id
            assert "format" not in element, check_id
            assert element != "just", check_id
            assert "run_ci" not in element, check_id
        assert command.command == " ".join(command.argv), check_id
        assert command.timeout_seconds > 0, check_id


# ── The streaming/cancellable runner ──────────────────────────────────────────


def test_incremental_capture_is_observable_before_completion(tmp_path: Path) -> None:
    gate = tmp_path / "gate"
    script = (
        "import pathlib, time\n"
        "print('first', flush=True)\n"
        f"while not pathlib.Path({str(gate)!r}).exists():\n"
        "    time.sleep(0.01)\n"
        "print('second')\n"
    )
    runner = CheckRunner(tmp_path, commands={"ruff": _fake(script)})
    started = runner.start("ruff")
    assert started is not None
    assert started.status == "running"

    def first_line() -> CheckRunSnapshot | None:
        snapshot = runner.get(started.run_id)
        assert snapshot is not None
        return snapshot if "first" in snapshot.output else None

    mid_run = _wait_for(first_line, message="first line never captured")
    assert mid_run.status == "running"
    assert "second" not in mid_run.output
    gate.touch()
    final = _wait_terminal(runner, started.run_id)
    assert final.status == "passed"
    assert final.exit_code == 0
    assert final.output == "first\nsecond\n"
    # Snapshots are frozen copies: the mid-run snapshot never grew.
    assert mid_run.output == "first\n"
    with pytest.raises(dataclasses.FrozenInstanceError):
        mid_run.status = "failed"  # ty: ignore[invalid-assignment]


def test_exit_codes_map_to_passed_and_failed(tmp_path: Path) -> None:
    runner = CheckRunner(
        tmp_path,
        commands={
            "ruff": _fake("print('ok')"),
            "ty": _fake("import sys\nprint('bad')\nsys.exit(3)"),
        },
    )
    passed_start = runner.start("ruff")
    assert passed_start is not None
    passed = _wait_terminal(runner, passed_start.run_id)
    assert (passed.status, passed.exit_code) == ("passed", 0)
    failed_start = runner.start("ty")
    assert failed_start is not None
    failed = _wait_terminal(runner, failed_start.run_id)
    assert (failed.status, failed.exit_code) == ("failed", 3)
    assert "bad" in failed.output


def test_cancel_kills_the_process_group_and_records_cancelled(tmp_path: Path) -> None:
    baseline = set(threading.enumerate())
    runner = CheckRunner(tmp_path, commands={"ruff": _fake(_PID_THEN_BLOCK)})
    started = runner.start("ruff")
    assert started is not None
    child_pid = _started_pid(runner, started.run_id)
    assert runner.cancel(started.run_id) is True
    final = _wait_terminal(runner, started.run_id)
    assert final.status == "cancelled"
    assert final.exit_code is None
    _assert_group_dead(child_pid)
    # The reader finalizer cancelled the timeout timer: no reader or timer thread lingers.
    _assert_threads_settle(baseline)


def test_cancel_after_terminal_is_idempotent(tmp_path: Path) -> None:
    runner = CheckRunner(tmp_path, commands={"ruff": _fake("print('done')")})
    started = runner.start("ruff")
    assert started is not None
    final = _wait_terminal(runner, started.run_id)
    assert final.status == "passed"
    # Idempotent success acknowledgment; the terminal record stays untouched.
    assert runner.cancel(started.run_id) is True
    assert runner.get(started.run_id) == final
    assert runner.cancel("absent-run") is False


def test_cancel_kills_a_sigterm_resistant_descendant_with_the_whole_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The regression arm: the leader dies on SIGTERM while its same-group child
    # ignores it and holds the merged pipe; only the group-wide probe + SIGKILL
    # escalation removes it (a leader-only poll would wedge the reader and the slot).
    monkeypatch.setattr(checks_module, "KILL_GRACE_SECONDS", 0.5)
    runner = CheckRunner(tmp_path, commands={"ruff": _fake(_RESISTANT_FAMILY_SCRIPT)})
    started = runner.start("ruff")
    assert started is not None

    def family_up() -> tuple[int, int] | None:
        snapshot = runner.get(started.run_id)
        assert snapshot is not None
        lines = snapshot.output.splitlines()
        if "STARTED" not in lines or "CHILD-UP" not in lines:
            return None
        pids = [int(line) for line in lines if line.isdigit()]
        return (pids[0], pids[1])

    leader_pid, child_pid = _wait_for(family_up, message="the resistant family never came up")
    assert runner.cancel(started.run_id) is True
    final = _wait_terminal(runner, started.run_id)
    assert final.status == "cancelled"
    _assert_group_dead(leader_pid)

    def child_gone() -> bool | None:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            return True
        return None

    _wait_for(child_gone, message=f"SIGTERM-resistant child {child_pid} still alive")


def test_timeout_fires_and_records_timeout(tmp_path: Path) -> None:
    runner = CheckRunner(
        tmp_path,
        commands={"ruff": _fake(_PID_THEN_BLOCK, timeout_seconds=1)},
    )
    started = runner.start("ruff")
    assert started is not None
    child_pid = _started_pid(runner, started.run_id)
    final = _wait_terminal(runner, started.run_id)
    assert final.status == "timeout"
    assert final.exit_code is None
    _assert_group_dead(child_pid)


def test_spawn_failure_records_terminal_run_without_threads(tmp_path: Path) -> None:
    baseline = set(threading.enumerate())
    missing = tmp_path / "does-not-exist"
    runner = CheckRunner(
        tmp_path,
        commands={
            "ruff": CheckCommand(label="Missing", argv=(str(missing),), timeout_seconds=30),
            "ty": _fake("print('ok')"),
        },
    )
    failed = runner.start("ruff")
    assert failed is not None
    assert failed.status == "spawn-failed"
    assert failed.exit_code is None
    assert failed.output != ""
    assert set(threading.enumerate()) == baseline
    latest = runner.latest()
    assert latest is not None and latest.run_id == failed.run_id
    # The slot was never occupied: another check starts immediately.
    next_run = runner.start("ty")
    assert next_run is not None
    assert _wait_terminal(runner, next_run.run_id).status == "passed"


def test_output_cap_truncates_and_keeps_draining(tmp_path: Path) -> None:
    # Writes past the cap (2,000,000 chars) and still runs to completion: the reader
    # drains without storing, so the pipe never blocks the child.
    script = (
        "import sys\n"
        "chunk = 'x' * 8191 + '\\n'\n"
        f"for _ in range({OUTPUT_CAP_CHARS // 8192 + 40}):\n"
        "    sys.stdout.write(chunk)\n"
        "print('END')\n"
    )
    runner = CheckRunner(tmp_path, commands={"ruff": _fake(script, timeout_seconds=120)})
    started = runner.start("ruff")
    assert started is not None
    final = _wait_terminal(runner, started.run_id)
    assert final.status == "passed"
    assert final.truncated is True
    assert len(final.output) == OUTPUT_CAP_CHARS
    assert "END" not in final.output


def test_single_slot_reports_busy_until_terminal(tmp_path: Path) -> None:
    gate = tmp_path / "gate"
    script = (
        "import pathlib, time\n"
        "print('STARTED', flush=True)\n"
        f"while not pathlib.Path({str(gate)!r}).exists():\n"
        "    time.sleep(0.01)\n"
    )
    runner = CheckRunner(tmp_path, commands={"ruff": _fake(script), "ty": _fake("print('ok')")})
    started = runner.start("ruff")
    assert started is not None
    assert runner.start("ty") is None
    gate.touch()
    _wait_terminal(runner, started.run_id)
    second = runner.start("ty")
    assert second is not None
    assert _wait_terminal(runner, second.run_id).status == "passed"


def test_ring_retains_only_the_most_recent_records(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    command = CheckCommand(label="Missing", argv=(str(missing),), timeout_seconds=30)
    runner = CheckRunner(tmp_path, commands={"ruff": command})
    run_ids: list[str] = []
    for _ in range(RUN_HISTORY_LIMIT + 5):
        snapshot = runner.start("ruff")
        assert snapshot is not None
        run_ids.append(snapshot.run_id)
    for evicted in run_ids[:-RUN_HISTORY_LIMIT]:
        assert runner.get(evicted) is None
    for retained in run_ids[-RUN_HISTORY_LIMIT:]:
        assert runner.get(retained) is not None
    latest = runner.latest()
    assert latest is not None and latest.run_id == run_ids[-1]


def test_latest_serves_running_and_none_before_any_run(tmp_path: Path) -> None:
    runner = CheckRunner(tmp_path, commands={"ruff": _fake(_PID_THEN_BLOCK)})
    assert runner.latest() is None
    started = runner.start("ruff")
    assert started is not None
    latest = runner.latest()
    assert latest is not None
    assert (latest.run_id, latest.status) == (started.run_id, "running")
    runner.cancel(started.run_id)
    _wait_terminal(runner, started.run_id)


def test_checks_run_with_the_repo_root_as_working_directory(tmp_path: Path) -> None:
    # The allowlist's real commands are relative-path invocations (pytest paths,
    # ruff/biome roots, node test files): the spawn must anchor them at the supplied
    # repository root, proven here by an actual relative read.
    (tmp_path / "marker.txt").write_text("relative-read-proof", encoding="utf-8")
    script = (
        "import os, pathlib\n"
        "print(os.getcwd(), flush=True)\n"
        "print(pathlib.Path('marker.txt').read_text(encoding='utf-8'), flush=True)\n"
    )
    runner = CheckRunner(tmp_path, commands={"ruff": _fake(script)})
    started = runner.start("ruff")
    assert started is not None
    final = _wait_terminal(runner, started.run_id)
    assert final.status == "passed"
    reported_cwd, marker = final.output.splitlines()[:2]
    assert Path(reported_cwd).resolve() == tmp_path.resolve()
    assert marker == "relative-read-proof"


def test_shutdown_kills_the_active_run_and_leaves_no_threads(tmp_path: Path) -> None:
    baseline = set(threading.enumerate())
    runner = CheckRunner(tmp_path, commands={"ruff": _fake(_PID_THEN_BLOCK)})
    started = runner.start("ruff")
    assert started is not None
    child_pid = _started_pid(runner, started.run_id)
    runner.shutdown()
    _assert_group_dead(child_pid)
    final = runner.get(started.run_id)
    assert final is not None
    assert final.status == "cancelled"
    _assert_threads_settle(baseline)
    # Idempotent with no active run.
    runner.shutdown()
