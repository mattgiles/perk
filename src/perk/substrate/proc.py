"""The one captured-subprocess primitive (dignified-convergence §1.9's wrapper discipline).

Every captured ``subprocess.run`` in production code routes through ``run_captured`` /
``run_checked`` — the domain facades (``git``, ``npm``, ``github._exec``, perk-dev's
``build``/``bump``, and the one-off probes) each stay a thin translation of the structured
``ProcFailure`` into their own error type, so error *types* remain per-boundary while the
spawn/timeout/env/kwargs mechanics live here exactly once. Child-env control is two
keyword-only params: ``env_overlay`` merges over ``os.environ`` (overlay wins) and
``env_remove`` DELETES inherited names first (removal is not expressible as an overlay — an
empty-string value is still a set variable); both ``None`` inherits untouched (``env=None``).
``tests/test_tooling.py``'s AST
guard pins this: ``run_captured`` holds the only sanctioned captured ``subprocess.run``
literal (the inherited-stdio streaming sites are a different idiom and keep their own).
``run_interactive`` is the one sanctioned **inherited-stdio interactive** primitive (the child
owns the terminal; nothing is captured) for gestures like init's offered ``gh auth login``.

``subprocess.run`` is resolved at call time on the shared module object, so tests that
monkeypatch the global ``subprocess.run`` keep working unchanged.

``which_absolute`` is the shared exec-launcher probe (resolve + absolutize a binary BEFORE any
``os.chdir``) — a pure-stdlib leaf both the pi launch and the hunk watch seam reach.
"""

import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal


def which_absolute(binary: str) -> str | None:
    """``shutil.which`` + absolutization — the shared exec-launcher probe.

    Exec-launcher safety contract: call this BEFORE any ``os.chdir`` and exec the returned
    absolute path (argv[0] conventionally stays the bare name). ``shutil.which`` can return a
    **relative** candidate when the matching ``PATH`` entry is itself relative (e.g. ``.``), and
    a relative path handed to a post-chdir exec is reinterpreted under the new cwd — the very
    directory the launcher just entered. The candidate is therefore absolutized against the
    CURRENT cwd via ``Path.absolute()`` (no symlink resolution — a version-manager shim path is
    exec'd as-is, not its target).

    Bounded trust: the probe trusts the *invocation* environment. With a relative ``PATH``
    entry, a launcher invoked from inside an untrusted tree still resolves within it — a
    shell-level pathology this probe cannot repair (the same recorded residual class as the
    shebang-interpreter ``PATH`` walk); it closes post-chdir re-resolution, nothing more.

    Returns ``None`` on a miss — miss policy stays with callers (each owns its typed refusal).
    """
    candidate = shutil.which(binary)
    if candidate is None:
        return None
    return str(Path(candidate).absolute())


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


def _child_env(
    env_overlay: Mapping[str, str] | None, env_remove: Sequence[str] | None
) -> dict[str, str] | None:
    """Compose the child env: ``os.environ`` minus ``env_remove``, then ``env_overlay`` wins.

    Both ``None`` → ``None`` (inherit untouched — byte-identical to passing no ``env``).
    Removal happens BEFORE the overlay, so an overlaid name always survives a same-name
    removal (overlay wins).
    """
    if env_overlay is None and env_remove is None:
        return None
    env = dict(os.environ)
    for name in env_remove or ():
        env.pop(name, None)
    env.update(env_overlay or {})
    return env


def run_captured(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout: int,
    env_overlay: Mapping[str, str] | None = None,
    env_remove: Sequence[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run ``argv`` capturing text output; spawn/timeout failures raise ``ProcFailure``.

    Returns the completed process **regardless of exit code** — non-zero policy stays with
    callers (gh's caller-owned returncode handling, best-effort batch git ops). ``timeout``
    is keyword-only with no default: each facade owns its domain timeout policy.
    ``env_overlay`` is merged **after** ``os.environ`` (overlay wins — perk-managed
    semantics); ``env_remove`` names are deleted from the inherited env FIRST (the
    deletion-capable arm — e.g. the documented ``PERK_RUN_ID``/``PI_SESSION_FILE`` env-leak
    guard for probes launched from inside a perk session; an overlay cannot remove). Both
    ``None`` passes ``env=None`` (inherit untouched).
    """
    env = _child_env(env_overlay, env_remove)
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


def run_interactive(argv: Sequence[str], *, timeout: int | None) -> int:
    """Run ``argv`` with **inherited stdio** (the child owns the terminal; no capture).

    The interactive twin of ``run_captured``: explicit ``check=False`` (exit-code policy stays
    with callers — the returned code), explicit ``timeout``; ``TimeoutExpired``/``OSError``
    raise ``ProcFailure`` exactly like ``run_captured``. ``timeout=None`` is allowed on purpose
    (an interactive child may legitimately wait on the human), but callers must pass it
    explicitly — no default.
    """
    try:
        return subprocess.run(list(argv), check=False, timeout=timeout).returncode
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
    env_remove: Sequence[str] | None = None,
) -> str:
    """``run_captured`` + a non-zero exit raises ``ProcFailure`` (kind ``"exit"``); returns stdout.

    Named for its *checked* semantics — it passes ``check=False`` internally and raises the
    domain-friendly ``ProcFailure`` instead of ``CalledProcessError``.
    """
    proc = run_captured(
        argv, cwd=cwd, timeout=timeout, env_overlay=env_overlay, env_remove=env_remove
    )
    if proc.returncode != 0:
        raise ProcFailure("exit", tuple(argv), returncode=proc.returncode, stderr=proc.stderr)
    return proc.stdout
