"""The real-host proof of the host-SDK bridge (contracts §8.73).

The fixture matrix in ``extension/substrate/nativeSdkBridge.test.ts`` proves the mechanism against
a fixture "Pi"; this smoke drives the REAL ``pi`` bin over this checkout (its installed
``pi-subagents`` / ``pi-web-access`` under ``.pi/npm/node_modules/``) and reads
``/perk-selfcheck`` back: namespace capture, facade preparation and the consumers' actual
requested export names must all agree with the running bundle. A facade named-export mismatch
would surface as Pi's per-extension ``Failed to load extension`` line while perk kept running —
so the absence of that line, plus both consumers having registered tools, is the assertion.

Hermetic like the rest of the suite: the agent dir is the throwaway ``PI_CODING_AGENT_DIR`` the
autouse fixture sets (resolved through :func:`launch_pi_agent_dir`, the precedence ``exec_pi``
uses), the project is trusted for this run with Pi's ``--approve`` (perk's own launcher posture —
no ``trust.json`` write), and a placeholder provider key satisfies print mode's upfront auth check
when the developer has none exported — the command never prompts a model (``PI_OFFLINE=1`` guards
the rest). Slow (a full Pi startup) and skip-guarded: no ``pi`` on PATH, or no installed consumers,
skips.
"""

import os
import re
import shutil
from pathlib import Path

import pytest
from perk_dev.profile_startup.pty_session import PtySize, spawn_pty

from perk.substrate import git
from perk.substrate.config import launch_pi_agent_dir

REPO_ROOT = Path(__file__).resolve().parents[1]
CONSUMER_INSTALL_ROOT = REPO_ROOT / ".pi" / "npm" / "node_modules"
CONSUMERS = ("pi-subagents", "pi-web-access")

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(shutil.which("pi") is None, reason="no `pi` on PATH"),
    pytest.mark.skipif(
        not all((CONSUMER_INSTALL_ROOT / name / "package.json").is_file() for name in CONSUMERS),
        reason="the native consumers are not installed under this checkout's .pi/npm",
    ),
]


def _launch_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in ("PERK_RUN_ID", "PERK_PROFILE_HANDOFF")}
    env["PI_OFFLINE"] = "1"
    env["PERK_SKIP_VERSION_CHECK"] = "1"
    env.setdefault("TERM", "xterm-256color")
    env.setdefault("ANTHROPIC_API_KEY", "perk-live-smoke-placeholder-never-sent")
    main_root = git.main_worktree_root(REPO_ROOT) or REPO_ROOT
    resolution = launch_pi_agent_dir(main_root)
    if resolution is not None:
        env["PI_CODING_AGENT_DIR"] = str(resolution.path)
    return env


def test_real_pi_selfcheck_reports_the_bridge_installed_and_both_consumers_loaded():
    pi = shutil.which("pi")
    assert pi is not None
    run = spawn_pty(
        [pi, "--approve", "--mode", "json", "-p", "/perk-selfcheck"],
        cwd=REPO_ROOT,
        env=_launch_env(),
        size=PtySize(cols=120, rows=40),
        timeout_s=120.0,
        exit_grace_s=120.0,
        startup_marker=lambda _line: False,
    )
    stderr = run.stderr
    assert not run.timed_out, f"pi did not exit within the timeout:\n{stderr}"
    assert run.exit_code == 0, f"pi exited {run.exit_code}:\n{stderr}"

    summary = next((line for line in stderr.splitlines() if "perk: selfcheck —" in line), None)
    assert summary is not None, f"no selfcheck summary line:\n{stderr}"
    assert "bridge=installed" in summary, summary

    for name in CONSUMERS:
        root = (CONSUMER_INSTALL_ROOT / name).resolve()
        assert str(root) in stderr, f"census block does not name the {name} root:\n{stderr}"

    per_source = next((line for line in stderr.splitlines() if "per source:" in line), None)
    assert per_source is not None, f"no per-source tool row:\n{stderr}"
    for name in CONSUMERS:
        match = re.search(rf"npm:{re.escape(name)}=(\d+)", per_source)
        assert match is not None and int(match.group(1)) >= 1, (
            f"{name} registered no tools through the facades:\n{per_source}"
        )

    assert "Failed to load extension" not in stderr, stderr
