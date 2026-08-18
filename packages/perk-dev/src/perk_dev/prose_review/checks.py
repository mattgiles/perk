"""The Prose Review Workbench CheckRunner: allowlisted targeted checks, streamed.

The single source of truth for check identity, display command, and execution.
Every entry in :data:`CHECK_COMMANDS` is a complete fixed executable command — no
``just`` recipes, no ``npm run`` script indirection (a ``package.json`` script edit
can never change what the runner executes) — and the client only ever sends a check
id, so zero argv content is request-derived. Every entry is check-only: nothing here
formats, fixes, syncs environments, or fetches from the network (``uv run --no-sync``
and ``npx --no-install`` pin those side effects out).

The streaming/cancellable process seam is deliberately app-owned:
``perk.substrate.proc`` stays a blocking-and-capture primitive and is not reused.
Concurrency follows the single-finalizer rule — the reader thread is the only path
that assigns a terminal status, clears the active slot, and cancels the timer
(spawn failure aside, which happens synchronously in ``start()`` before either
exists). The timeout timer and ``cancel()`` only set their flag under the lock and
run the process-group kill escalation outside it; the reader owns the one
``proc.wait()``.
"""

import os
import secrets
import signal
import subprocess
import threading
import time
from collections import deque
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

type CheckId = Literal[
    "prose-map",
    "learned-docs",
    "prompt-parity",
    "worker-prompt-pins",
    "worker-test-pins",
    "ruff",
    "ty",
    "biome",
    "tsc",
]
type CheckRunStatus = Literal[
    "running",
    "passed",
    "failed",
    "cancelled",
    "timeout",
    "spawn-failed",
]

# Captured output is capped in Python str code points; beyond it the reader keeps
# draining the pipe without storing (the child never blocks on a full pipe), and the
# run record reports `truncated`. Offsets over the captured text are therefore stable
# monotone append-only indexes.
OUTPUT_CAP_CHARS = 2_000_000
# The bounded record ring: polling and `latest()` reconciliation stay served for the
# most recent runs; older records evict to the fixed unknown-run 404.
RUN_HISTORY_LIMIT = 20
# SIGTERM → poll → SIGKILL escalation grace, in seconds.
KILL_GRACE_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class CheckCommand:
    """One allowlisted non-mutating command; the CHECK_COMMANDS key is its identity."""

    label: str
    argv: tuple[str, ...]
    timeout_seconds: int

    @property
    def command(self) -> str:
        """The display string — exactly the executed argv, never a paraphrase."""
        return " ".join(self.argv)


CHECK_COMMANDS: dict[CheckId, CheckCommand] = {
    "prose-map": CheckCommand(
        label="Prose map check",
        argv=("uv", "run", "--no-sync", "perk-dev", "prose-map", "check"),
        timeout_seconds=120,
    ),
    "learned-docs": CheckCommand(
        label="Learned docs check",
        argv=("uv", "run", "--no-sync", "perk", "learn", "docs-check"),
        timeout_seconds=120,
    ),
    "prompt-parity": CheckCommand(
        label="Prompt render parity (pytest)",
        argv=(
            "uv",
            "run",
            "--no-sync",
            "pytest",
            "tests/test_prompt_parity.py",
            "tests/test_binding_render_parity.py",
            "-q",
        ),
        timeout_seconds=900,
    ),
    "worker-prompt-pins": CheckCommand(
        label="Worker prompt pins (pytest)",
        argv=("uv", "run", "--no-sync", "pytest", "tests/test_worker_prompt_parity.py", "-q"),
        timeout_seconds=300,
    ),
    "worker-test-pins": CheckCommand(
        label="Worker prompt pins (node:test)",
        argv=("node", "--test", "extension/worker/worker.test.ts"),
        timeout_seconds=300,
    ),
    "ruff": CheckCommand(
        label="Ruff lint (check-only)",
        argv=(
            "uv",
            "run",
            "--no-sync",
            "ruff",
            "check",
            "src/perk",
            "packages/perk-dev/src",
            "tests",
        ),
        timeout_seconds=120,
    ),
    "ty": CheckCommand(
        label="ty typecheck",
        argv=("uv", "run", "--no-sync", "ty", "check"),
        timeout_seconds=300,
    ),
    "biome": CheckCommand(
        label="Biome lint (check-only)",
        argv=("npx", "--no-install", "biome", "check", "extension", "tools"),
        timeout_seconds=120,
    ),
    "tsc": CheckCommand(
        label="TypeScript typecheck",
        argv=("npx", "--no-install", "tsc", "--noEmit"),
        timeout_seconds=300,
    ),
}


class UnknownCheckError(Exception):
    """A check id absent from the runner's (possibly injected) command mapping."""


@dataclass(frozen=True, slots=True)
class CheckRunSnapshot:
    """One immutable copy of a run record — never the live mutable record."""

    run_id: str
    check: CheckId
    label: str
    command: str
    status: CheckRunStatus
    exit_code: int | None
    output: str
    truncated: bool


class _CheckRun:
    """The live mutable run record; every field mutation happens under the runner lock."""

    __slots__ = (
        "cancel_requested",
        "check",
        "chunks",
        "command",
        "exit_code",
        "length",
        "proc",
        "reader",
        "run_id",
        "status",
        "timeout_fired",
        "timer",
        "truncated",
    )

    def __init__(self, run_id: str, check: CheckId, command: CheckCommand) -> None:
        self.run_id = run_id
        self.check = check
        self.command = command
        self.status: CheckRunStatus = "running"
        self.exit_code: int | None = None
        self.chunks: list[str] = []
        self.length = 0
        self.truncated = False
        self.cancel_requested = False
        self.timeout_fired = False
        self.proc: subprocess.Popen[str] | None = None
        self.reader: threading.Thread | None = None
        self.timer: threading.Timer | None = None


class CheckRunner:
    """App-lifetime executor of allowlisted checks: one active slot, bounded record ring.

    ``commands`` is the test seam — the mapping is used as-is, wholesale (production
    default :data:`CHECK_COMMANDS`); a request naming an id absent from a partial
    injected mapping raises :class:`UnknownCheckError`. Thread-safe via the one lock:
    sync-def endpoints run in uvicorn's threadpool, and the reader/timer threads
    contend for the same records.
    """

    def __init__(
        self,
        repo_root: Path,
        commands: Mapping[CheckId, CheckCommand] | None = None,
    ) -> None:
        self._repo_root = repo_root
        self._commands = CHECK_COMMANDS if commands is None else commands
        self._lock = threading.Lock()
        self._active: _CheckRun | None = None
        self._runs: deque[_CheckRun] = deque(maxlen=RUN_HISTORY_LIMIT)

    def start(self, check_id: CheckId) -> CheckRunSnapshot | None:
        """Start one allowlisted check; ``None`` means the single app-wide slot is busy."""
        with self._lock:
            command = self._commands.get(check_id)
            if command is None:
                raise UnknownCheckError(check_id)
            if self._active is not None:
                return None
            record = _CheckRun(secrets.token_urlsafe(8), check_id, command)
            try:
                proc = self._spawn(command.argv)
            except OSError as exc:
                # Terminal before a reader thread or timer ever exists: the OS error
                # text is the whole captured output.
                record.status = "spawn-failed"
                record.chunks.append(str(exc))
                record.length = len(str(exc))
                self._runs.append(record)
                return _snapshot(record)
            record.proc = proc
            self._active = record
            self._runs.append(record)
            reader = threading.Thread(
                target=self._read,
                args=(record, proc),
                name=f"check-run-{record.run_id}",
                daemon=True,
            )
            record.reader = reader
            timer = threading.Timer(command.timeout_seconds, self._on_timeout, args=(record,))
            timer.daemon = True
            record.timer = timer
            reader.start()
            timer.start()
            return _snapshot(record)

    def get(self, run_id: str) -> CheckRunSnapshot | None:
        with self._lock:
            record = self._find(run_id)
            return None if record is None else _snapshot(record)

    def latest(self) -> CheckRunSnapshot | None:
        """The most recent run, running or terminal — the reconciliation read."""
        with self._lock:
            if not self._runs:
                return None
            return _snapshot(self._runs[-1])

    def cancel(self, run_id: str) -> CheckRunSnapshot | None:
        """Request cancellation; idempotent — a terminal run returns its snapshot untouched."""
        with self._lock:
            record = self._find(run_id)
            if record is None:
                return None
            if record.status != "running":
                return _snapshot(record)
            record.cancel_requested = True
            proc = record.proc
        if proc is not None:
            _kill_group(proc)
        with self._lock:
            return _snapshot(record)

    def shutdown(self) -> None:
        """Flag the active run cancelled, kill its process group, and join the reader.

        App-scoped (wired into the FastAPI lifespan, no ``atexit``): repeated app/test
        construction leaks nothing process-global.
        """
        with self._lock:
            record = self._active
            if record is None:
                return
            record.cancel_requested = True
            proc = record.proc
            reader = record.reader
        if proc is not None:
            _kill_group(proc)
        if reader is not None:
            reader.join(timeout=KILL_GRACE_SECONDS + 5.0)

    def _spawn(self, argv: tuple[str, ...]) -> subprocess.Popen[str]:
        # The one Popen call site (sanctioned in tests/test_tooling.py): list argv, no
        # shell anywhere; one merged ordered text stream with stdlib incremental
        # decoding; start_new_session makes the whole child tree one killable group.
        return subprocess.Popen(
            list(argv),
            cwd=self._repo_root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=True,
            env={**os.environ, "NO_COLOR": "1", "FORCE_COLOR": "0", "PYTHONUNBUFFERED": "1"},
        )

    def _read(self, record: _CheckRun, proc: subprocess.Popen[str]) -> None:
        """The reader thread: sole capture writer and the single finalizer/reaper."""
        stream = proc.stdout
        if stream is not None:
            for line in stream:
                with self._lock:
                    remaining = OUTPUT_CAP_CHARS - record.length
                    if remaining <= 0:
                        # Past the cap: keep draining without storing so the pipe
                        # never blocks the child.
                        record.truncated = True
                        continue
                    if len(line) > remaining:
                        record.chunks.append(line[:remaining])
                        record.length = OUTPUT_CAP_CHARS
                        record.truncated = True
                    else:
                        record.chunks.append(line)
                        record.length += len(line)
        exit_code = proc.wait()
        with self._lock:
            # Flag precedence: cancelled > timeout > exit-code-derived; exit_code is
            # non-null only for the exit-code-derived statuses.
            if record.cancel_requested:
                record.status = "cancelled"
            elif record.timeout_fired:
                record.status = "timeout"
            elif exit_code == 0:
                record.status = "passed"
                record.exit_code = 0
            else:
                record.status = "failed"
                record.exit_code = exit_code
            if self._active is record:
                self._active = None
            if record.timer is not None:
                record.timer.cancel()

    def _on_timeout(self, record: _CheckRun) -> None:
        with self._lock:
            if record.status != "running":
                return
            record.timeout_fired = True
            proc = record.proc
        if proc is not None:
            _kill_group(proc)

    def _find(self, run_id: str) -> _CheckRun | None:
        for record in self._runs:
            if record.run_id == run_id:
                return record
        return None


def _snapshot(record: _CheckRun) -> CheckRunSnapshot:
    """Copy one record into a frozen snapshot; callers hold the runner lock."""
    return CheckRunSnapshot(
        run_id=record.run_id,
        check=record.check,
        label=record.command.label,
        command=record.command.command,
        status=record.status,
        exit_code=record.exit_code,
        output="".join(record.chunks),
        truncated=record.truncated,
    )


def _kill_group(proc: subprocess.Popen[str]) -> None:
    """SIGTERM the process group, poll for grace, then SIGKILL — never ``wait()``.

    The reader owns the one ``proc.wait()`` (the single reaper); this escalation only
    signals and polls. ``start_new_session=True`` makes the child's pid its pgid. A
    group already gone (or unsignalable mid-teardown) is success, not an error.
    """
    with suppress(OSError):
        os.killpg(proc.pid, signal.SIGTERM)
    deadline = time.monotonic() + KILL_GRACE_SECONDS
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.05)
    with suppress(OSError):
        os.killpg(proc.pid, signal.SIGKILL)
