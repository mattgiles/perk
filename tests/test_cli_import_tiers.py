"""The fresh-process import matrix behind the tiered-import rule (python-cli-guidelines §8.3,
contracts.md §8.72(j)).

Bare ``perk``, a lone ``--`` and the eager ``--version`` must import no command group, no exec
orchestrator, no GitHub/backends/convergence package and read no registry — the root registration
is deferred to Click's first subcommand lookup. Each row spawns a fresh interpreter under
``-X importtime`` (the same ``-m perk`` entry ``perk-dev profile-startup`` traces) on a controlling
PTY, so the bare rows pass the plain session's terminal check, and asserts the traced module set
from the piped stderr. ``--help`` is the positive control: it enumerates and loads the whole
surface, so every heavy prefix MUST appear there — the vacuity proof for the absence rows.

Reuses the perk-dev harness (``spawn_pty`` + ``parse_importtime``) rather than a second PTY
driver or importtime parser. Every row is ``slow``: a fresh interpreter tracing the full import
graph sits at the >= 1 s serial-median rule.
"""

import json
import os
import stat
import sys
from collections.abc import Iterable
from pathlib import Path

import pytest
from perk_dev.profile_startup.handoff import parse_importtime
from perk_dev.profile_startup.pty_session import PtySize, spawn_pty

pytestmark = pytest.mark.slow

# The packages bare `perk` / `--version` must never pay for. `perk.cli.stages` and
# `perk.cli.commands` are the only root-level registry readers, so their absence IS the
# "reads no registry" proof.
HEAVY = (
    "perk.github",
    "perk.backends",
    "perk.convergence.init",
    "perk.run.launch",
    "perk.plan",
    "perk.cli.commands",
    "perk.cli.stages",
)

# The parse floor: the root module always loads, so an empty module set means the importtime
# log was not captured (never a vacuous pass).
_ROOT_MODULE = "perk.cli.cli"

# The bare rows record the Pi handoff instead of exec'ing pi (the stop-before-exec arm), so the
# matrix proves the plain session reached the shared exec seam without ever launching pi.
_HANDOFF_ENV = "PERK_PROFILE_HANDOFF"
_PI_STUB = "#!/bin/sh\nexit 0\n"


def _loaded(modules: Iterable[str], prefix: str) -> set[str]:
    """The traced modules under ``prefix`` (the package itself or any submodule)."""
    return {m for m in modules if m == prefix or m.startswith(prefix + ".")}


@pytest.fixture
def tier_env(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, str]]:
    """A hermetic child environment: a `pi` stub on PATH, a scratch HOME, an env-arm agent dir,
    and the version surfaces suppressed. Returns ``(scratch_dir, env)``."""
    scratch = tmp_path_factory.mktemp("import-tiers")
    bin_dir = scratch / "bin"
    bin_dir.mkdir()
    pi_stub = bin_dir / "pi"
    pi_stub.write_text(_PI_STUB, encoding="utf-8")
    pi_stub.chmod(pi_stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    home = scratch / "home"
    home.mkdir()
    agent = scratch / "agent"
    agent.mkdir()
    env = {k: v for k, v in os.environ.items() if k not in ("PERK_RUN_ID", _HANDOFF_ENV)}
    env.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{env.get('PATH', '')}",
            "HOME": str(home),
            "PI_CODING_AGENT_DIR": str(agent),
            "PERK_SKIP_VERSION_CHECK": "1",
            "PYTHONUTF8": "1",
        }
    )
    return scratch, env


def _trace(args: list[str], *, cwd: Path, env: dict[str, str]) -> set[str]:
    """Run ``python -X importtime -m perk <args>`` on a PTY; return the traced module names."""
    run = spawn_pty(
        [sys.executable, "-X", "importtime", "-m", "perk", *args],
        cwd=cwd,
        env=env,
        size=PtySize(cols=120, rows=40),
        timeout_s=60,
        exit_grace_s=5,
        startup_marker=lambda _line: False,
    )
    assert run.exit_code == 0, f"perk {' '.join(args)} exited {run.exit_code}:\n{run.stderr}"
    modules = {row.name for row in parse_importtime(run.stderr)}
    assert _ROOT_MODULE in modules, f"importtime log not captured:\n{run.stderr}"
    return modules


def _assert_light(modules: set[str], label: str) -> None:
    offenders = {prefix: sorted(_loaded(modules, prefix)) for prefix in HEAVY}
    offenders = {prefix: loaded for prefix, loaded in offenders.items() if loaded}
    assert not offenders, f"{label} imported heavy packages: {json.dumps(offenders, indent=2)}"


def _assert_handoff_recorded(handoff: Path, *, cwd: Path) -> None:
    record = json.loads(handoff.read_text(encoding="utf-8"))
    assert record["argv"] == ["pi"]
    assert record["cwd"] == str(cwd)


def test_version_imports_no_heavy_package(tier_env):
    scratch, env = tier_env
    modules = _trace(["--version"], cwd=scratch, env=env)
    _assert_light(modules, "perk --version")


def test_bare_perk_imports_only_the_exec_seam(tier_env, git_repo):
    scratch, env = tier_env
    handoff = scratch / "handoff.json"
    modules = _trace([], cwd=git_repo, env={**env, _HANDOFF_ENV: str(handoff)})
    _assert_light(modules, "bare perk")
    assert "perk.run.pi_exec" in modules
    _assert_handoff_recorded(handoff, cwd=git_repo)


def test_lone_separator_takes_the_bare_arm(tier_env, git_repo):
    scratch, env = tier_env
    handoff = scratch / "handoff.json"
    modules = _trace(["--"], cwd=git_repo, env={**env, _HANDOFF_ENV: str(handoff)})
    _assert_light(modules, "perk --")
    assert "perk.run.pi_exec" in modules
    _assert_handoff_recorded(handoff, cwd=git_repo)


def test_help_loads_the_whole_surface(tier_env):
    # The positive control: `--help` lists every command, so the deferred registration runs and
    # every heavy prefix loads — proving the absence assertions above are not vacuous.
    scratch, env = tier_env
    modules = _trace(["--help"], cwd=scratch, env=env)
    missing = [prefix for prefix in HEAVY if not _loaded(modules, prefix)]
    assert not missing, f"perk --help did not load: {missing}"
