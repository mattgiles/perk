"""The ONE PTY spawn of the profiler: a child on a real controlling terminal, stderr on a pipe.

Pi requires only stdin/stdout to be TTYs (``resolveAppMode(parsed, stdin.isTTY, stdout.isTTY)``
in Pi's ``dist/main.js``), so the child's stdout/stdin are a PTY slave — sized via
``TIOCSWINSZ`` and made the child's controlling terminal via ``TIOCSCTTY`` after ``setsid`` (the
pexpect posture) — while **stderr is a plain pipe**: Pi's timing report (``console.error`` in
``dist/core/timings.js``) arrives clean, separate from the TUI bytes, which are drained from
the master and only counted.

Lifecycle: before the startup marker, ``timeout_s`` from spawn → ``SIGKILL`` the process group,
``timed_out``. After the marker, the child may run ``exit_grace_s`` more; then ``SIGTERM`` the
group, wait :data:`TERM_GRACE_S`, ``SIGKILL``, ``lingered`` (the tracer's exit-on-SIGTERM handler
uses that window to flush the census and let Node write its CPU profile). Master EOF / ``EIO`` =
the child closed the terminal. ``exit_ms`` is spawn → natural exit; ``None`` whenever the
harness terminated the child. Whatever the outcome, the owned process group is swept with
``SIGKILL`` on the way out, so a grandchild the leader left behind never survives into the next
sample.

This module holds the profiler's only ``subprocess.Popen`` literal (sanctioned in
``tests/test_tooling.py``); explicit ``cwd=`` and ``start_new_session=`` are the killable
process-group discipline.
"""

import codecs
import contextlib
import errno
import fcntl
import os
import pty
import selectors
import signal
import struct
import subprocess
import termios
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

# SIGTERM → SIGKILL window for a child that outlives its exit grace (the census flush window).
TERM_GRACE_S = 2.0
# How long to keep draining the fds after the child is gone (a grandchild may hold the slave).
_POST_EXIT_DRAIN_S = 0.2
_SELECT_TICK_S = 0.05
_READ_CHUNK = 65536


@dataclass(frozen=True)
class PtySize:
    """The terminal geometry handed to the child (``TIOCSWINSZ``)."""

    cols: int
    rows: int


@dataclass(frozen=True)
class PtyRun:
    """One completed PTY spawn.

    ``exit_code`` is the process return code (negative for a signal). Both durations start at
    ``spawn_monotonic_ns``, stamped immediately BEFORE the ``Popen`` call, so they include process
    creation/exec and the parent's read latency: ``elapsed_ms`` ends when the harness observes the
    first stderr line the startup marker accepts (``None`` when it never fired); ``exit_ms`` ends
    at the natural exit (``None`` when the harness terminated the child). ``stderr`` is the whole
    decoded stderr text; ``stdout_bytes`` counts the TUI bytes drained from the master.
    """

    exit_code: int | None
    elapsed_ms: float | None
    exit_ms: float | None
    timed_out: bool
    lingered: bool
    stderr: str
    stdout_bytes: int
    spawn_monotonic_ns: int


class SpawnFn(Protocol):
    """The :func:`spawn_pty` signature — the harness's injectable spawn seam (tests pass a fake)."""

    def __call__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        size: PtySize,
        timeout_s: float,
        exit_grace_s: float,
        startup_marker: Callable[[str], bool],
    ) -> PtyRun: ...


def _acquire_controlling_tty() -> None:
    """Make the slave (already dup'd onto fd 0) the child's controlling terminal.

    Runs in the child after ``setsid`` (``start_new_session=True``): a fresh session leader may
    acquire a controlling terminal; without this Pi's TUI sees a tty that is nobody's terminal.
    """
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


def _signal_group(pid: int, sig: signal.Signals) -> None:
    with contextlib.suppress(ProcessLookupError):  # the group is already gone
        os.killpg(pid, sig)


class _StderrLines:
    """Incremental UTF-8 decoding of the stderr pipe into complete lines."""

    def __init__(self) -> None:
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._pending = ""
        self._chunks: list[str] = []
        self.flushed = False

    def feed(self, data: bytes) -> list[str]:
        text = self._decoder.decode(data, False)
        self._chunks.append(text)
        self._pending += text
        parts = self._pending.split("\n")
        self._pending = parts.pop()
        return parts

    def flush(self) -> list[str]:
        if self.flushed:
            return []
        self.flushed = True
        text = self._decoder.decode(b"", True)
        self._chunks.append(text)
        self._pending += text
        tail, self._pending = self._pending, ""
        return [tail] if tail else []

    @property
    def text(self) -> str:
        return "".join(self._chunks)


class _Drive:
    """The per-spawn mutable state the selector loop and the fd reader share."""

    def __init__(
        self,
        *,
        master: int,
        stderr_fd: int,
        spawn_ns: int,
        timeout_s: float,
        exit_grace_s: float,
        startup_marker: Callable[[str], bool],
    ) -> None:
        self.master = master
        self.stderr_fd = stderr_fd
        self.spawn_ns = spawn_ns
        self.exit_grace_ns = int(exit_grace_s * 1e9)
        self.deadline_ns = spawn_ns + int(timeout_s * 1e9)
        self.startup_marker = startup_marker
        self.lines = _StderrLines()
        self.stdout_bytes = 0
        self.elapsed_ms: float | None = None
        self.accept_marker = True
        self.selector = selectors.DefaultSelector()
        self.selector.register(master, selectors.EVENT_READ)
        self.selector.register(stderr_fd, selectors.EVENT_READ)
        self.open_fds = {master, stderr_fd}

    def _feed_marker(self, lines: list[str]) -> None:
        for line in lines:
            if self.accept_marker and self.elapsed_ms is None and self.startup_marker(line):
                now_ns = time.monotonic_ns()
                self.elapsed_ms = (now_ns - self.spawn_ns) / 1e6
                self.deadline_ns = now_ns + self.exit_grace_ns

    def read(self, fd: int) -> None:
        try:
            data = os.read(fd, _READ_CHUNK)
        except OSError as exc:
            # The one expected error: Linux reports a PTY master whose slave side closed as
            # EIO (macOS returns 0 bytes). Anything else — on either fd — is a harness defect
            # and must surface, not masquerade as a clean EOF that later reads as a timeout.
            if fd != self.master or exc.errno != errno.EIO:
                raise
            data = b""
        if not data:
            self.selector.unregister(fd)
            self.open_fds.discard(fd)
            if fd == self.stderr_fd:
                self._feed_marker(self.lines.flush())
            return
        if fd == self.master:
            self.stdout_bytes += len(data)
            return
        self._feed_marker(self.lines.feed(data))

    def pump(self, timeout_s: float) -> bool:
        """One selector tick; ``False`` when nothing was ready."""
        ready = self.selector.select(timeout=timeout_s)
        for key, _ in ready:
            self.read(key.fd)
        return bool(ready)

    def drain_after_exit(self) -> None:
        """Bounded drain once the child is gone: stop at EOF on both fds, at quiet, or at the
        cap (a grandchild holding the slave must not pin the harness)."""
        drain_until = time.monotonic_ns() + int(_POST_EXIT_DRAIN_S * 1e9)
        while self.open_fds and time.monotonic_ns() < drain_until:
            if not self.pump(_SELECT_TICK_S):
                break

    def close(self) -> None:
        self.selector.close()
        self._feed_marker(self.lines.flush())


def spawn_pty(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    size: PtySize,
    timeout_s: float,
    exit_grace_s: float,
    startup_marker: Callable[[str], bool],
) -> PtyRun:
    """Spawn ``argv`` on a controlling PTY and drive it to completion (see the module doc).

    ``startup_marker`` receives every complete stderr line (without its newline); the first
    ``True`` stamps ``elapsed_ms`` and starts the ``exit_grace_s`` window.
    """
    master, slave = pty.openpty()
    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", size.rows, size.cols, 0, 0))
    spawn_monotonic_ns = time.monotonic_ns()
    try:
        proc = subprocess.Popen(
            list(argv),
            cwd=cwd,
            env=dict(env),
            stdin=slave,
            stdout=slave,
            stderr=subprocess.PIPE,
            start_new_session=True,
            preexec_fn=_acquire_controlling_tty,
            close_fds=True,
        )
    except OSError:
        os.close(master)
        raise
    finally:
        os.close(slave)
    stderr_pipe = proc.stderr
    if stderr_pipe is None:  # pragma: no cover — Popen(stderr=PIPE) always provides it
        raise RuntimeError("stderr pipe missing")

    drive = _Drive(
        master=master,
        stderr_fd=stderr_pipe.fileno(),
        spawn_ns=spawn_monotonic_ns,
        timeout_s=timeout_s,
        exit_grace_s=exit_grace_s,
        startup_marker=startup_marker,
    )
    exit_ms: float | None = None
    timed_out = False
    lingered = False
    try:
        while True:
            now_ns = time.monotonic_ns()
            if now_ns >= drive.deadline_ns:
                drive.accept_marker = False  # a late marker never rewrites a decided outcome
                if drive.elapsed_ms is None:
                    timed_out = True
                    _signal_group(proc.pid, signal.SIGKILL)
                else:
                    lingered = True
                    _signal_group(proc.pid, signal.SIGTERM)
                    try:
                        proc.wait(timeout=TERM_GRACE_S)
                    except subprocess.TimeoutExpired:
                        _signal_group(proc.pid, signal.SIGKILL)
                proc.wait()
                drive.drain_after_exit()
                break
            remaining_s = max(0.0, (drive.deadline_ns - now_ns) / 1e9)
            tick = min(remaining_s, _SELECT_TICK_S)
            if drive.open_fds:
                drive.pump(tick)
                if proc.poll() is not None:
                    # Exited while a grandchild still holds an fd: drain what is left, bounded.
                    exit_ms = (time.monotonic_ns() - spawn_monotonic_ns) / 1e6
                    drive.drain_after_exit()
                    break
                continue
            # Both fds hit EOF — the ordinary end of a child that closed its stdio at exit — or
            # the child detached from its stdio and lives on: wait on the process itself.
            try:
                proc.wait(timeout=tick)
            except subprocess.TimeoutExpired:
                continue
            exit_ms = (time.monotonic_ns() - spawn_monotonic_ns) / 1e6
            break
    finally:
        drive.close()
        os.close(master)
        stderr_pipe.close()
        if proc.poll() is None:  # never leave a child behind, whatever exited the loop
            _signal_group(proc.pid, signal.SIGKILL)
            proc.wait()
        # Sweep the owned process group even after a natural exit: a grandchild the leader left
        # behind in its session would otherwise outlive this run and skew the samples that
        # follow. The pgid is the (now-reaped) leader's pid and stays reserved while any member
        # lives, so this reaches exactly the stragglers; an empty group is ESRCH, suppressed.
        # Timing classification is untouched — `exit_ms` was taken when the leader exited.
        _signal_group(proc.pid, signal.SIGKILL)

    return PtyRun(
        exit_code=proc.returncode,
        elapsed_ms=drive.elapsed_ms,
        exit_ms=None if (timed_out or lingered) else exit_ms,
        timed_out=timed_out,
        lingered=lingered,
        stderr=drive.lines.text,
        stdout_bytes=drive.stdout_bytes,
        spawn_monotonic_ns=spawn_monotonic_ns,
    )
