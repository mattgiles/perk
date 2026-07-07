"""The one captured-subprocess primitive (dignified-convergence §1.9's wrapper discipline).

Every captured ``subprocess.run`` in production code routes through ``run_captured`` /
``run_checked`` — the domain facades (``git``, ``npm``, ``github._exec``, perk-dev's
``build``/``bump``, and the one-off probes) each stay a thin translation of the structured
``ProcFailure`` into their own error type, so error *types* remain per-boundary while the
spawn/timeout/env/kwargs mechanics live here exactly once. ``tests/test_tooling.py``'s AST
guard pins this: ``run_captured`` holds the only sanctioned captured ``subprocess.run``
literal (the inherited-stdio streaming sites are a different idiom and keep their own).

``subprocess.run`` is resolved at call time on the shared module object, so tests that
monkeypatch the global ``subprocess.run`` keep working unchanged.
"""

import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal


class ProcFailure(Exception):
    """A structured spawn/timeout/exit failure from ``run_captured``/``run_checked``.

    ``str(exc)`` renders the canonical default message shapes (the git/npm majority):
    timeout → ``"{cmd} timed out"``; spawn → ``"{cmd} could not run: {cause_text}"``;
    exit → ``stderr.strip() or "{cmd} failed"``. Facades needing a different shape format
    from the structured fields instead. ``__cause__`` carries the original ``OSError`` /
    ``TimeoutExpired`` for facades that discriminate (e.g. gh's ``FileNotFoundError`` arm).
    """

    def __init__(
        self,
        kind: Literal["spawn", "timeout", "exit"],
        argv: tuple[str, ...],
        *,
        returncode: int | None = None,
        stderr: str = "",
        cause_text: str = "",
    ) -> None:
        super().__init__()
        self.kind = kind
        self.argv = argv
        self.returncode = returncode  # exit kind only
        self.stderr = stderr  # exit kind only
        self.cause_text = cause_text  # spawn kind only — str(OSError)

    @property
    def cmd(self) -> str:
        """The command as a display string — ``" ".join(argv)``."""
        return " ".join(self.argv)

    def __str__(self) -> str:
        if self.kind == "timeout":
            return f"{self.cmd} timed out"
        if self.kind == "spawn":
            return f"{self.cmd} could not run: {self.cause_text}"
        return self.stderr.strip() or f"{self.cmd} failed"


def run_captured(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout: int,
    env_overlay: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run ``argv`` capturing text output; spawn/timeout failures raise ``ProcFailure``.

    Returns the completed process **regardless of exit code** — non-zero policy stays with
    callers (gh's caller-owned returncode handling, best-effort batch git ops). ``timeout``
    is keyword-only with no default: each facade owns its domain timeout policy.
    ``env_overlay`` is merged **after** ``os.environ`` (overlay wins — perk-managed
    semantics); ``None`` passes ``env=None`` (inherit untouched).
    """
    env = None if env_overlay is None else {**os.environ, **env_overlay}
    try:
        return subprocess.run(
            list(argv),
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProcFailure("timeout", tuple(argv)) from exc
    except OSError as exc:
        raise ProcFailure("spawn", tuple(argv), cause_text=str(exc)) from exc


def run_checked(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout: int,
    env_overlay: Mapping[str, str] | None = None,
) -> str:
    """``run_captured`` + a non-zero exit raises ``ProcFailure`` (kind ``"exit"``); returns stdout.

    Named for its *checked* semantics — it passes ``check=False`` internally and raises the
    domain-friendly ``ProcFailure`` instead of ``CalledProcessError``.
    """
    proc = run_captured(argv, cwd=cwd, timeout=timeout, env_overlay=env_overlay)
    if proc.returncode != 0:
        raise ProcFailure("exit", tuple(argv), returncode=proc.returncode, stderr=proc.stderr)
    return proc.stdout
