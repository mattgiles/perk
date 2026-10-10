"""The real-host proof of the host-SDK bridge (contracts §8.73).

The fixture matrix in ``extension/substrate/nativeSdkBridge.test.ts`` proves the mechanism against
a fixture "Pi"; this smoke drives the REAL ``pi`` bin over this checkout (its installed
``pi-subagents`` / ``pi-web-access`` under ``.pi/npm/node_modules/``) and reads
``/perk-selfcheck`` back: namespace capture, facade preparation and the consumers' actual
requested export names must all agree with the running bundle. A facade named-export mismatch
would surface as Pi's per-extension ``Failed to load extension`` line while perk kept running —
so the absence of that line, plus both consumers having registered tools, is the assertion. The
installed pi-subagents must also BE the managed pin: a stale install (an older release left in
``.pi/npm`` that the waves were never re-verified against) would still load and register tools,
so a version check on the artifact itself — not the configured source label — is what keeps this
proof about the pinned engine.

Hermetic like the rest of the suite: the agent dir is the throwaway ``PI_CODING_AGENT_DIR`` the
autouse fixture sets (resolved through :func:`launch_pi_agent_dir`, the precedence ``exec_pi``
uses), the project is trusted for this run with Pi's ``--approve`` (perk's own launcher posture —
no ``trust.json`` write), and a placeholder provider key satisfies print mode's upfront auth check
when the developer has none exported — the command never prompts a model (``PI_OFFLINE=1`` guards
the rest). Slow (a full Pi startup) and skip-guarded: no ``pi`` on PATH, or no installed consumers,
skips.

The PATH ``pi`` is also the host the extension admits (contracts §8.76(f)): the bridge proof needs
an admitted one, and a below-floor ``pi`` instead proves the refusal — Pi reports perk's thrown
refusal as a failed extension load and exits 1, so nothing of perk runs.
"""

import json
import os
import re
import shutil
from pathlib import Path

import pytest
from perk_dev.profile_startup.pty_session import PtyRun, PtySize, spawn_pty

from perk.convergence.init import SUBAGENTS_PACKAGE
from perk.substrate import git
from perk.substrate.config import launch_pi_agent_dir
from perk.substrate.pi_host import PiHost, probe_pi_host

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


# Inherited variables that would change the asserted outcome: perk run identity / the profiling
# handoff arm, the bridge opt-out (the assertion is `installed`), and pi-subagents' child-mode
# flags (a runner child registers no tools). Scrubbed so the smoke answers for THIS launch only.
_SCRUBBED_ENV = (
    "PERK_RUN_ID",
    "PERK_PROFILE_HANDOFF",
    "PERK_SELFCHECK",
    "PERK_DISABLE_NATIVE_SDK_BRIDGE",
    "PI_SUBAGENT_CHILD",
    "PI_SUBAGENT_CHILD_AGENT",
    "PI_SUBAGENT_EXTENSION_BINDINGS",
)


def _launch_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _SCRUBBED_ENV}
    env["PI_OFFLINE"] = "1"
    env["PERK_SKIP_VERSION_CHECK"] = "1"
    env.setdefault("TERM", "xterm-256color")
    env.setdefault("ANTHROPIC_API_KEY", "perk-live-smoke-placeholder-never-sent")
    main_root = git.main_worktree_root(REPO_ROOT) or REPO_ROOT
    resolution = launch_pi_agent_dir(main_root)
    if resolution is not None:
        env["PI_CODING_AGENT_DIR"] = str(resolution.path)
    return env


_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _path_pi() -> tuple[str, PiHost]:
    pi = shutil.which("pi")
    assert pi is not None
    return pi, probe_pi_host(pi)


def _selfcheck_run(pi: str) -> PtyRun:
    return spawn_pty(
        [pi, "--approve", "--mode", "json", "-p", "/perk-selfcheck"],
        cwd=REPO_ROOT,
        env=_launch_env(),
        size=PtySize(cols=120, rows=40),
        timeout_s=120.0,
        exit_grace_s=120.0,
        startup_marker=lambda _line: False,
    )


def test_the_installed_pi_subagents_is_the_managed_pin():
    pinned = SUBAGENTS_PACKAGE.rpartition("@")[2]
    manifest = CONSUMER_INSTALL_ROOT / "pi-subagents" / "package.json"
    installed = json.loads(manifest.read_text(encoding="utf-8"))["version"]
    assert installed == pinned, (
        f"{manifest} is pi-subagents {installed}, not the managed pin {SUBAGENTS_PACKAGE} — "
        "run `perk init` (or `pi install`) in the main checkout to converge the install"
    )


def test_real_pi_selfcheck_reports_the_bridge_installed_and_both_consumers_loaded():
    pi, host = _path_pi()
    if host.outcome != "admitted":
        pytest.skip(
            f"the PATH pi ({host.observed or host.detail}) is not admitted by the host floor "
            f"(>= {host.required}) — perk's extension refuses to load on it; upgrade it to run "
            "the bridge proof"
        )
    run = _selfcheck_run(pi)
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
        # A version-pinned source (`npm:pi-subagents@0.76.1`) carries its spec in the row.
        match = re.search(rf"npm:{re.escape(name)}(?:@[^=;\s]+)?=(\d+)", per_source)
        assert match is not None and int(match.group(1)) >= 1, (
            f"{name} registered no tools through the facades:\n{per_source}"
        )
    # The loaded source is the converged project pin, not a bare or user-scope spec.
    assert f"{SUBAGENTS_PACKAGE}=" in per_source, per_source

    assert "Failed to load extension" not in stderr, stderr


def test_a_below_floor_real_pi_refuses_to_load_perk():
    pi, host = _path_pi()
    if host.outcome != "unsupported":
        pytest.skip(f"needs a below-floor PATH pi (this one is {host.outcome})")
    run = _selfcheck_run(pi)
    stderr = _ANSI.sub("", run.stderr)
    assert not run.timed_out, f"pi did not exit within the timeout:\n{stderr}"
    assert run.exit_code == 1, f"pi exited {run.exit_code}:\n{stderr}"
    # Pi wraps perk's refusal twice: its loader's message, then the startup diagnostic.
    assert (
        "Failed to load extension: perk requires Pi >= "
        f"{host.required}; the Pi running this session is {host.observed} "
        "(@earendil-works/pi-coding-agent VERSION)."
    ) in stderr, stderr
    assert 'Hint: Start without extensions using "pi -ne".' in stderr, stderr
    assert "perk: selfcheck —" not in stderr, stderr
