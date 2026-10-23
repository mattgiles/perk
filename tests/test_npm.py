"""The ``npm`` gateway (`perk.substrate.npm`): what actually reaches the npm process.

The init/review callers' tests stub ``install_global`` itself; these exercise the real gateway down
to the subprocess boundary, so a wiring regression (e.g. forwarding only the first of several
specs, which would install Pi over floating companions) fails here.
"""

import os
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from perk.substrate import npm
from perk.substrate import proc as proc_mod
from perk.substrate.pi_host import PI_INSTALL_SPECS

Call = tuple[list[str], int, dict[str, str]]


def _record_spawns(monkeypatch: pytest.MonkeyPatch, returncode: int = 0) -> list[Call]:
    """Stub the subprocess boundary under ``run_captured``; record argv, timeout and env."""
    calls: list[Call] = []

    def fake_run(
        argv: Sequence[str], *, timeout: int, env: dict[str, str] | None, **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        assert env is not None  # the gateway always layers its quiet overlay
        calls.append((list(argv), timeout, env))
        return subprocess.CompletedProcess(list(argv), returncode, "", "boom" if returncode else "")

    monkeypatch.setattr(proc_mod.subprocess, "run", fake_run)
    return calls


def test_install_global_forwards_the_pinned_set_in_one_npm_invocation(monkeypatch):
    calls = _record_spawns(monkeypatch)
    npm.install_global(*PI_INSTALL_SPECS, timeout=600)
    assert [(argv, timeout) for argv, timeout, _ in calls] == [
        (["npm", "install", "-g", *PI_INSTALL_SPECS], 600)
    ]
    assert len(PI_INSTALL_SPECS) == 8
    (_, _, env) = calls[0]
    assert env["npm_config_loglevel"] == "error"  # the quiet overlay rides every install


def test_install_global_single_spec_callers_keep_their_shape(monkeypatch):
    calls = _record_spawns(monkeypatch)
    npm.install_global("hunkdiff")
    npm.install_global("cloc", timeout=600)
    assert [(argv, timeout) for argv, timeout, _ in calls] == [
        (["npm", "install", "-g", "hunkdiff"], 300),
        (["npm", "install", "-g", "cloc"], 600),
    ]


def test_install_global_non_zero_exit_raises_npm_error(monkeypatch):
    _record_spawns(monkeypatch, returncode=1)
    with pytest.raises(npm.NpmError):
        npm.install_global(*PI_INSTALL_SPECS, timeout=600)


def test_install_global_real_spawn_receives_every_spec(monkeypatch, tmp_path: Path):
    # A real process boundary: a fake `npm` first on PATH logs its argv, one invocation per block.
    log = tmp_path / "npm-argv.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "npm"
    fake.write_text(
        '#!/bin/sh\nfor a in "$@"; do printf "%s\\n" "$a" >> "$FAKE_NPM_LOG"; done\n'
        'echo "--" >> "$FAKE_NPM_LOG"\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_NPM_LOG", str(log))
    npm.install_global(*PI_INSTALL_SPECS, timeout=30)
    argv_blocks = log.read_text(encoding="utf-8").splitlines()
    assert argv_blocks == ["install", "-g", *PI_INSTALL_SPECS, "--"]  # one invocation, all eight
