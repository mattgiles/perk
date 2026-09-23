"""The ONE Pi exec pipeline (contracts.md §8.71(b), §8.72(b)(i)), shared by the plain session
(bare ``perk``), the staged launch (through ``launch._exec_pi``) and the session-resume engine.

The preserved order of :func:`exec_pi`: absolute ``pi`` resolution pre-``chdir``
(``pi_cli_missing``) → the ``LINEAR_API_KEY`` seed from the main checkout, only when the operator
env lacks a non-blank value → :func:`_build_exec_env` (merge order ``_NPM_QUIET_ENV`` < operator
env < perk stamps; ``run_id=None`` removes an inherited ``PERK_RUN_ID``; a blank
``PI_CODING_AGENT_DIR`` is scrubbed) → the stale-lock sweep → the ``PERK_PROFILE_HANDOFF`` arm →
``chdir`` + ``execvpe`` inside the ``launch_failed`` ``OSError`` arm.

**The test seam.** ``exec_pi`` reads :func:`_resolve_pi_executable` / :func:`_build_exec_env` /
:func:`_sweep_stale_pi_agent_locks` / :func:`_record_profile_handoff` and ``os.chdir`` /
``os.execvpe`` as THIS module's globals, so tests patch ``pi_exec.<name>`` / ``pi_exec.os`` —
never a re-export on another module (a patch there would be a silent no-op against this
pipeline).

**Import tier.** This module sits on the bare-``perk`` path (python-cli-guidelines §8.3): it
imports neither the launch facade (the stage orchestrator and everything it drags in) nor any
``perk.cli`` module other than ``perk.cli.ensure``, so the plain session pays for the config
boundary and nothing above it.
"""

import json
import os
import time
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from perk import __version__
from perk.cli.ensure import UserFacingCliError
from perk.substrate.config import (
    ConfigError,
    PiAgentDir,
    default_pi_agent_dir,
    launch_pi_agent_dir,
    load_local_linear_api_key,
)
from perk.substrate.output import log_warn, user_output
from perk.substrate.proc import which_absolute

# pi locks its agent-dir JSON via proper-lockfile, which holds a lock as a *directory*
# (atomic mkdir). A stale regular *file* at one of these paths makes pi's startup rmdir fail
# with ENOTDIR and print a "(startup session lookup, global settings)" warning on every launch.
_PI_AGENT_LOCK_FILES = ("settings.json.lock", "auth.json.lock")

# Quiet the npm installs pi runs at startup when a fresh worktree's gitignored
# .pi/npm/ is empty (funding nags, audit advisories, allow-scripts warnings).
# loglevel=error keeps real install failures visible on pi's inherited stdio.
# Setdefault semantics: a user's own npm_config_* env vars win (see launch_stage).
_NPM_QUIET_ENV = {
    "npm_config_loglevel": "error",
    "npm_config_fund": "false",
    "npm_config_audit": "false",
}

# The maintainer-only stop-before-exec seam (contracts.md §8.72(i)): when this variable names a
# file, `exec_pi` records the exact Python→Pi handoff instant there and exits 0 instead of
# exec'ing pi. The plain path ends in `os.execvpe`, so no in-process profiler (cProfile,
# `-X importtime`) survives it — this arm is the only exact handoff mark a profiler can wrap.
# Inert unless set; timing samples never set it. `perk-dev profile-startup` imports the spelling.
PROFILE_HANDOFF_ENV = "PERK_PROFILE_HANDOFF"


@dataclass(frozen=True)
class LaunchAgentDir:
    """The agent-dir half of a Pi launch environment, shared by stage launches and session
    reopens.

    ``resolution`` is the full launch-precedence resolution (env → main-checkout `[pi]
    agent_dir` → pi's default) the stale-lock sweep targets — ``None`` when no directory is
    resolvable (the sweep is skipped). ``injected`` is the value handed to the child's
    ``PI_CODING_AGENT_DIR`` — set only when the ``config`` arm chose the dir (an operator env
    value is inherited as-is; the default store needs no injection).
    """

    resolution: PiAgentDir | None
    injected: Path | None


def resolve_launch_agent_dir(repo_root: Path) -> LaunchAgentDir:
    """Resolve the agent dir a cold-local Pi exec hands pi, through the shared launch-precedence
    resolver — resolved once for preview/exec parity.

    Inherited redirects count as operator choices, including the value injected by a parent
    session into a nested cold launch. A broken main-checkout config warns and falls back to
    pi's default store (no injection) — the same fallback the resolver's ``default`` arm yields.
    Only the ``config`` arm injects: a missing configured dir warns (pi creates it on demand);
    an existing non-directory refuses ``pi_agent_dir_invalid`` (pi cannot build its sessions
    tree there). Reads ``launch_pi_agent_dir`` / ``default_pi_agent_dir`` / ``log_warn`` as
    this module's globals.
    """
    try:
        resolution = launch_pi_agent_dir(repo_root)
    except (ConfigError, tomllib.TOMLDecodeError) as exc:
        log_warn(
            "could not read [pi] agent_dir from the main checkout config — "
            f"launching without the redirect ({exc})"
        )
        resolution = default_pi_agent_dir()
    injected = None
    if resolution is not None and resolution.source == "config":
        injected = resolution.path
        if not injected.exists():
            log_warn(
                f"pi agent dir {injected} is missing — pi creates an empty agent dir "
                "on demand; sessions launch with no auth.json/models.json"
            )
        elif not injected.is_dir():
            raise UserFacingCliError(
                f"pi agent dir {injected} is not a directory — pi cannot create its "
                "sessions tree under a non-directory. Set [pi] agent_dir to a directory.",
                error_type="pi_agent_dir_invalid",
            )
    return LaunchAgentDir(resolution=resolution, injected=injected)


def _sweep_stale_pi_agent_locks(agent_dir: Path) -> None:
    """Remove stale pi agent-dir lockfiles before exec'ing pi.

    Only removes a lock path when it is **not a directory**: a directory is a *live*
    ``proper-lockfile`` lock (held via atomic ``mkdir``), so a non-directory at that path can
    only be a stale artifact and can never clobber a held lock. Best-effort and non-fatal — a
    sweep failure must never block a launch; if a stale lock survives, pi surfaces its own
    startup diagnostic (the status-quo warning), so this is a report-not-swallow boundary.

    Project-scope locks (``<worktree>/.pi/settings.json.lock``) are out of scope: launched
    worktrees get a fresh ``.pi/`` and the observed bug is on pi's global agent dir.
    """
    for name in _PI_AGENT_LOCK_FILES:
        lock = agent_dir / name
        try:
            if not lock.is_dir():
                lock.unlink(missing_ok=True)
        except OSError:
            pass  # best-effort; a stale lock is surfaced by pi's own startup diagnostic


def _build_exec_env(
    *,
    run_id: str | None,
    environ: Mapping[str, str],
    fallback_linear_api_key: str | None,
    pi_agent_dir: Path | None,
) -> dict[str, str]:
    """Build the environment passed to pi without mutating the operator environment.

    Operator npm choices override perk's defaults. The run identity and CLI version are
    authoritative launch metadata, so they override conflicting inherited values. A ``None``
    ``run_id`` (a session reopen, which mints nothing) REMOVES an inherited ``PERK_RUN_ID``
    rather than forwarding it — a reopened session that already carries its identity keeps it
    and never claims or adopts a foreign run. A non-blank operator ``LINEAR_API_KEY`` wins over
    the gitignored local-config fallback. Agent-dir precedence is already settled by the caller
    (:func:`resolve_launch_agent_dir`); a supplied path is assigned verbatim.
    """
    env = {**_NPM_QUIET_ENV, **environ, "PERK_CLI_VERSION": __version__}
    if run_id is None:
        env.pop("PERK_RUN_ID", None)
    else:
        env["PERK_RUN_ID"] = run_id
    if not env.get("LINEAR_API_KEY", "").strip() and fallback_linear_api_key is not None:
        env["LINEAR_API_KEY"] = fallback_linear_api_key
    if pi_agent_dir is not None:
        env["PI_CODING_AGENT_DIR"] = str(pi_agent_dir)
    elif not env.get("PI_CODING_AGENT_DIR", "").strip():
        # Pi treats whitespace as a path, but launch precedence treats it as unset.
        env.pop("PI_CODING_AGENT_DIR", None)
    return env


def _resolve_pi_executable() -> str:
    """Resolve the absolute path of the ``pi`` binary — typed refusal on a PATH miss.

    Module-level on purpose: ``exec_pi`` reads it as this module's global, so
    ``monkeypatch.setattr(pi_exec, "_resolve_pi_executable", …)`` rebinds the name it calls.
    No bare-name fallback — a miss is a ``pi_cli_missing`` refusal, never a raw
    ``FileNotFoundError`` traceback from ``execvpe``'s exhausted PATH walk.
    """
    candidate = which_absolute("pi")
    if candidate is None:
        raise UserFacingCliError(
            "pi CLI not found on PATH — install it: "
            "npm install -g @earendil-works/pi-coding-agent (requires Node >= 22).",
            error_type="pi_cli_missing",
        )
    return candidate


def _record_profile_handoff(
    target: Path,
    *,
    pi_path: str,
    argv: tuple[str, ...],
    checkout: Path,
    env: Mapping[str, str],
) -> None:
    """Write the stop-before-exec handoff record — the instant that stands for the exec.

    The monotonic stamp is taken FIRST (before any file I/O) so it marks the moment the plain
    path would have called ``os.execvpe``; ``CLOCK_MONOTONIC`` is system-wide, so a harness that
    stamped the spawn with the same clock can subtract across processes. ``env_keys`` carries
    key NAMES only — the child env holds secrets (``LINEAR_API_KEY``), and a profiling record
    must never leak a value. Exactly these keys, nothing else: the consumer's parser mirrors
    the set.
    """
    handoff_monotonic_ns = time.monotonic_ns()
    record = {
        "schema": 1,
        "handoff_monotonic_ns": handoff_monotonic_ns,
        "pid": os.getpid(),
        "pi_path": pi_path,
        "argv": list(argv),
        "cwd": str(checkout),
        "env_keys": sorted(env),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def exec_pi(
    *,
    main_root: Path,
    checkout: Path,
    argv: tuple[str, ...],
    run_id: str | None,
    agent_dir: LaunchAgentDir,
) -> None:
    """The ONE Pi exec pipeline: build the child env, sweep stale pi agent locks, chdir into
    ``checkout``, and ``exec pi`` — the CLI *becomes* pi, so nothing after this runs.

    **The stop-before-exec arm.** When ``PERK_PROFILE_HANDOFF`` (:data:`PROFILE_HANDOFF_ENV`)
    holds a non-blank file path, the pipeline runs every pre-exec phase as usual (env build,
    lock sweep), then :func:`_record_profile_handoff` writes the handoff record to that file,
    ONE stderr line names it, and the process exits ``0`` via ``SystemExit`` — no ``chdir``, no
    exec, no env mutation. Why: the plain path ends in ``os.execvpe``, so no in-process profiler
    survives into pi; this arm is the only exact handoff mark, and it lets cProfile / ``-X
    importtime`` wrap a real launch (cProfile's runner swallows ``SystemExit`` and still dumps
    its stats). Blank/whitespace values take the ordinary exec path. Every cold-local launch
    (plain, staged, resumed) routes through here, so the arm applies to all of them.

    Shared verbatim by the stage launch (through the ``launch._exec_pi`` adapter) and the
    session-reopen engine (``run_id=None`` — nothing minted, an inherited ``PERK_RUN_ID``
    dropped), so the two paths cannot drift.

    The pi executable is resolved to an ABSOLUTE path pre-chdir via
    :func:`_resolve_pi_executable` (FIRST, before any exec-phase side effect): re-resolving the
    bare name after the chdir would let a relative ``PATH`` entry (e.g. ``.``) pick up a ``pi``
    inside the very checkout being launched into. Bounded protection: this closes pi-name
    substitution from the checkout, not the ``#!/usr/bin/env node`` shebang-interpreter lookup
    (pi's bin script's ``env`` still walks the unchanged ``PATH`` post-chdir — a recorded
    residual; sanitizing the operator's ``PATH`` is out of scope).

    ``LINEAR_API_KEY`` is seeded from the MAIN checkout's gitignored ``.perk/local.toml``
    `[linear] api_key` (read from ``main_root`` BEFORE the chdir) so the borrowed in-session
    ``linear_*`` tools and any ``perk <stage> --json`` cold-door worker the session spawns (they
    inherit this env) can authenticate. Env wins: only filled when the environment does not
    already provide a non-blank key. Best-effort (fail-soft reader). ``PERK_CLI_VERSION``
    carries the running CLI's version into the session so the extension's ``session_start``
    handler can surface a soft drift warning when the live loaded ``@mgiles/perk`` extension
    differs from the CLI that launched it (a stale lazy-installed npm: package) — informational
    only (not run-control data, unlike ``PERK_RUN_ID``); set at this single local-launch seam.

    Reads ``_resolve_pi_executable`` / ``_build_exec_env`` / ``_sweep_stale_pi_agent_locks`` as
    this module's globals, and ``os.chdir`` / ``os.execvpe`` off the shared ``os`` module object
    the exec recorders patch.

    Annotated ``-> None`` (not ``NoReturn``): tests stub ``os.execvpe`` and control returns.
    """
    pi_path = _resolve_pi_executable()  # pre-chdir: aborts the exec phase before any side effect
    local_linear_key = None
    if not os.environ.get("LINEAR_API_KEY", "").strip():
        local_linear_key = load_local_linear_api_key(main_root)
    env = _build_exec_env(
        run_id=run_id,
        environ=os.environ,
        fallback_linear_api_key=local_linear_key,
        pi_agent_dir=agent_dir.injected,
    )
    if agent_dir.resolution is not None:
        _sweep_stale_pi_agent_locks(agent_dir.resolution.path)
    handoff_target = os.environ.get(PROFILE_HANDOFF_ENV, "").strip()
    if handoff_target:
        _record_profile_handoff(
            Path(handoff_target), pi_path=pi_path, argv=argv, checkout=checkout, env=env
        )
        user_output(
            f"{PROFILE_HANDOFF_ENV} set — recorded the Pi handoff to {handoff_target}; "
            "exiting without launching pi"
        )
        raise SystemExit(0)
    # The presence probe does not eliminate the exec race — a failed chdir/exec is an ordinary
    # OSError arm, not a crash (the watch-seam shape).
    try:
        os.chdir(checkout)  # pi's ctx.cwd becomes the checkout; the extension claims there
        # absolute pi path: no bare-name PATH re-resolution after the chdir; argv[0] stays "pi"
        os.execvpe(pi_path, list(argv), env)  # the CLI *becomes* pi — nothing after this runs
    except OSError as exc:
        raise UserFacingCliError(
            f"could not launch pi in {checkout}: {exc}",
            error_type="launch_failed",
        ) from exc
