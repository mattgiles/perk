import pytest

from perk.convergence import env
from perk.convergence.env import EnvCheck, check_environment, required_tools_ok
from perk.substrate import npm
from perk.substrate.pi_host import (
    PI_ADOPTED_VERSION,
    PI_INSTALL_COMMAND,
    PI_INSTALL_SPECS,
    PiHost,
)

LINES = "22.x >= 22.23.4, 24.x >= 24.22.1, 26.x >= 26.12.1"
PI_FIX_REMEDIATION = f"Run `perk doctor --fix` (it runs: {PI_INSTALL_COMMAND})."
PI_ABSENT_REMEDIATION = (
    f"Install Pi: {PI_INSTALL_COMMAND} (requires Node.js on a supported release line: {LINES})."
)


def test_check_environment_covers_required_tools():
    checks = check_environment()
    required = {c.name for c in checks if not c.optional}
    assert required == {"git", "gh", "node", "pi", "skills", "cloc"}
    ast_grep = next(c for c in checks if c.name == "ast-grep")
    assert ast_grep.optional is True


def test_required_remediations_carry_the_exact_install_command(monkeypatch):
    """The rewritten remediation values (a deliberate value change in ALL modes, --json
    included): each required tool's remediation carries a runnable command."""
    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setattr(env, "_node_version", lambda: None)
    remediations = {c.name: c.remediation for c in check_environment() if not c.optional}
    assert remediations["git"] == (
        "Install git: brew install git / xcode-select --install (macOS), "
        "or your distro package manager (https://git-scm.com)."
    )
    assert remediations["gh"] == (
        "Install the GitHub CLI: brew install gh (or see https://cli.github.com)."
    )
    assert remediations["node"] == (
        f"Install Node.js on a supported release line ({LINES}): brew install node / "
        "mise use -g node@22 (https://nodejs.org)."
    )
    assert remediations["pi"] == PI_ABSENT_REMEDIATION
    assert remediations["skills"] == (
        "Install the skills CLI: curl -fsSL "
        "https://raw.githubusercontent.com/mattgiles/skills/main/scripts/install.sh | sh "
        "(macOS), or: go install github.com/mattgiles/skills/cmd/skills@latest"
    )
    assert remediations["cloc"] == (
        "Install cloc: brew install cloc (macOS), npm install -g cloc, or your distro package "
        "(https://github.com/AlDanial/cloc)."
    )


def test_outdated_node_remediation_also_carries_commands(monkeypatch):
    """The installed-but-outdated arm carries actionable commands too, not just absent-node."""
    monkeypatch.setattr(env, "_node_version", lambda: "v26.3.0")
    node = next(c for c in env.check_environment() if c.name == "node")
    assert not node.ok
    # The remediation names the observed line's own floor, not the lowest line's.
    assert node.remediation == (
        "Upgrade Node.js to >= 26.12.1 (found v26.3.0): "
        "brew upgrade node / mise use -g node@26.12.1 (https://nodejs.org)."
    )


def test_optional_tool_non_fatal():
    # An optional check that is not ok does not flip required_tools_ok.
    assert required_tools_ok(
        [EnvCheck("git", True, "", ""), EnvCheck("ast-grep", False, "not found", "", optional=True)]
    )
    # A required check that is not ok still fails.
    assert not required_tools_ok(
        [
            EnvCheck("git", False, "not found", ""),
            EnvCheck("ast-grep", True, "/x", "", optional=True),
        ]
    )


def test_required_tools_ok():
    assert required_tools_ok([EnvCheck("git", True, "", ""), EnvCheck("node", True, "v22", "")])
    assert not required_tools_ok([EnvCheck("node", False, "v18", "upgrade")])


def test_node_version_gate(monkeypatch):
    monkeypatch.setattr(env, "_node_version", lambda: "v22.19.0")
    node = next(c for c in env.check_environment() if c.name == "node")
    assert not node.ok and "Upgrade" in node.remediation

    monkeypatch.setattr(env, "_node_version", lambda: "v22.23.4")
    node = next(c for c in env.check_environment() if c.name == "node")
    assert node.ok and node.detail == "v22.23.4"


def test_node_absent(monkeypatch):
    monkeypatch.setattr(env, "_node_version", lambda: None)
    node = next(c for c in env.check_environment() if c.name == "node")
    assert not node.ok and node.detail == "not found"


@pytest.mark.parametrize(
    ("version", "line_floor"),
    [
        ("v22.23.3", "22.23.4"),
        ("v24.22.0", "24.22.1"),
        ("v26.3.0", "26.12.1"),
        # A prerelease of the floor triple is below it.
        ("v26.12.1-rc.1", "26.12.1"),
    ],
)
def test_node_below_its_line_floor_is_outdated(monkeypatch, version, line_floor):
    monkeypatch.setattr(env, "_node_version", lambda: version)
    node = env._check_node()
    assert not node.ok
    assert node.detail == version
    assert node.remediation == (
        f"Upgrade Node.js to >= {line_floor} (found {version}): "
        f"brew upgrade node / mise use -g node@{line_floor} (https://nodejs.org)."
    )


@pytest.mark.parametrize("version", ["garbage", "v22"])
def test_unparsable_node_is_outdated(monkeypatch, version):
    monkeypatch.setattr(env, "_node_version", lambda: version)
    node = env._check_node()
    assert not node.ok
    assert node.detail == version
    assert node.remediation == (
        f"Upgrade Node.js to a supported release line ({LINES}) (found {version}): "
        "brew upgrade node / mise use -g node@22 (https://nodejs.org)."
    )


@pytest.mark.parametrize("version", ["v20.19.0", "v23.11.0", "v25.9.0", "v27.0.0-alpha.0"])
def test_node_on_an_unsupported_line_is_not_ok(monkeypatch, version):
    monkeypatch.setattr(env, "_node_version", lambda: version)
    node = env._check_node()
    assert not node.ok
    assert node.detail == f"{version} (unsupported release line)"
    major = version.removeprefix("v").split(".")[0]
    assert node.remediation == (
        f"Node.js {major}.x is not a supported release line; install one of {LINES}: "
        "brew install node / mise use -g node@26 (https://nodejs.org)."
    )


# A prerelease of a LATER triple is above the floor (semver precedence compares the triple first).
@pytest.mark.parametrize(
    "version", ["v22.23.4", "v22.30.0", "v24.22.1", "v26.12.1", "v26.13.0", "v26.13.0-rc.1"]
)
def test_node_at_or_above_its_line_floor_is_ok(monkeypatch, version):
    monkeypatch.setattr(env, "_node_version", lambda: version)
    node = env._check_node()
    assert node.ok and node.detail == version and node.remediation == ""


# --- the pi row: presence + the Pi floor -----------------------------------------------------


def _pi_host(outcome, observed, detail=""):
    return PiHost("/opt/bin/pi", outcome, observed, "1.0.0", detail)


def test_pi_absent(monkeypatch):
    monkeypatch.setattr(env, "which_absolute", lambda name: None)
    monkeypatch.setattr(env, "probe_pi_host", _unreachable_probe)
    pi = env._check_pi()
    assert (pi.ok, pi.detail) == (False, "not found")
    assert pi.remediation == PI_ABSENT_REMEDIATION


def test_pi_admitted(monkeypatch):
    probed: list[str] = []
    monkeypatch.setattr(env, "which_absolute", lambda name: "/opt/bin/pi")
    monkeypatch.setattr(
        env, "probe_pi_host", lambda path: probed.append(path) or _pi_host("admitted", "1.0.3")
    )
    pi = env._check_pi()
    assert probed == ["/opt/bin/pi"]
    assert (pi.ok, pi.detail, pi.remediation) == (True, "1.0.3 (floor >= 1.0.0)", "")
    assert pi.advisory  # admitted, but not the adopted pin


def test_pi_admitted_at_the_adopted_pin_carries_no_advisory(monkeypatch):
    monkeypatch.setattr(env, "which_absolute", lambda name: "/opt/bin/pi")
    monkeypatch.setattr(env, "probe_pi_host", lambda path: _pi_host("admitted", PI_ADOPTED_VERSION))
    pi = env._check_pi()
    assert (pi.ok, pi.remediation, pi.advisory) == (True, "", "")
    assert pi.detail == f"{PI_ADOPTED_VERSION} (floor >= 1.0.0)"


def test_pi_admitted_at_another_version_carries_the_advisory(monkeypatch):
    monkeypatch.setattr(env, "which_absolute", lambda name: "/opt/bin/pi")
    monkeypatch.setattr(
        env, "probe_pi_host", lambda path: PiHost("/opt/bin/pi", "admitted", "1.4.0", "1.1.0", "")
    )
    pi = env._check_pi()
    assert (pi.ok, pi.detail, pi.remediation) == (True, "1.4.0 (floor >= 1.1.0)", "")
    assert pi.advisory == (
        "Pi 1.4.0 is admitted (floor >= 1.1.0) but is not the adopted Pi 1.1.0: perk's subagent "
        "waves are characterized only on the adopted Pi with its pinned companions and can be "
        f"refused on another. Install the adopted set: {PI_INSTALL_COMMAND}."
    )
    assert required_tools_ok([pi])  # a caution, never a gate


def test_pi_outdated_is_not_ok(monkeypatch):
    monkeypatch.setattr(env, "which_absolute", lambda name: "/opt/bin/pi")
    monkeypatch.setattr(env, "probe_pi_host", lambda path: _pi_host("unsupported", "0.99.2"))
    pi = env._check_pi()
    assert not pi.ok
    assert pi.detail == "0.99.2 (floor >= 1.0.0)"
    assert pi.remediation == f"Upgrade Pi to >= 1.0.0 (found 0.99.2): {PI_INSTALL_COMMAND}."
    assert pi.advisory == ""
    assert not required_tools_ok([pi])


def test_pi_unverifiable_is_not_ok(monkeypatch):
    monkeypatch.setattr(env, "which_absolute", lambda name: "/opt/bin/pi")
    monkeypatch.setattr(
        env,
        "probe_pi_host",
        lambda path: _pi_host("unverifiable", None, "pi --version timed out after 20 s"),
    )
    pi = env._check_pi()
    assert not pi.ok
    assert pi.detail == "version unverifiable (pi --version timed out after 20 s)"
    assert pi.remediation == PI_FIX_REMEDIATION
    assert pi.advisory == ""


def test_pi_with_undecodable_output_is_an_unverifiable_row_not_a_crash(monkeypatch, tmp_path):
    script = tmp_path / "pi"
    script.write_text('#!/bin/sh\nprintf "\\377\\n"\n', encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setattr(env, "which_absolute", lambda name: str(script))
    pi = env._check_pi()  # the REAL probe, against the shipped floor
    assert not pi.ok
    assert pi.detail == "version unverifiable (pi --version printed output that is not UTF-8)"
    assert pi.remediation == PI_FIX_REMEDIATION


def test_check_environment_carries_the_pi_row_in_place(monkeypatch):
    monkeypatch.setattr(env, "which_absolute", lambda name: "/opt/bin/pi")
    monkeypatch.setattr(env, "probe_pi_host", lambda path: _pi_host("unsupported", "0.99.2"))
    names = [c.name for c in check_environment()]
    assert names.index("node") + 1 == names.index("pi")
    pi = next(c for c in check_environment() if c.name == "pi")
    assert not pi.ok and pi.detail == "0.99.2 (floor >= 1.0.0)"


def _unreachable_probe(path):
    raise AssertionError(f"probe ran for an absent pi: {path}")


def test_pi_incoherent_is_not_ok(monkeypatch):
    detail = (
        "@earendil-works/pi-codemode does not resolve, @earendil-works/pi-mcp resolves to 1.4.0"
    )
    monkeypatch.setattr(env, "which_absolute", lambda name: "/opt/bin/pi")
    monkeypatch.setattr(env, "probe_pi_host", lambda path: _pi_host("incoherent", "1.1.0", detail))
    pi = env._check_pi()
    assert not pi.ok
    assert pi.detail == f"1.1.0 (floor >= 1.0.0) — companions: {detail}"
    assert pi.remediation == PI_FIX_REMEDIATION
    assert "perk doctor --fix" in pi.remediation
    assert pi.advisory == ""
    assert not required_tools_ok([pi])


# --- repair_pi: the `perk doctor --fix` gesture ----------------------------------------------

_NODE_OK = EnvCheck("node", True, "v26.12.1", "")
_PI_GREEN = EnvCheck("pi", True, "1.1.0 (floor >= 1.1.0)", "")
_PI_ADVISORY = EnvCheck("pi", True, "1.4.0 (floor >= 1.1.0)", "", advisory="caution")
_PI_INCOHERENT = EnvCheck("pi", False, "1.1.0 (floor >= 1.1.0) — companions: x", PI_FIX_REMEDIATION)
_PI_ABSENT = EnvCheck("pi", False, "not found", PI_ABSENT_REMEDIATION)


@pytest.fixture
def install_recorder(monkeypatch):
    calls: list[tuple[tuple[str, ...], int]] = []

    def fake_install(*specs: str, timeout: int) -> None:
        calls.append((specs, timeout))

    monkeypatch.setattr(npm, "install_global", fake_install)
    return calls


def test_repair_pi_is_a_noop_on_a_green_row(monkeypatch, install_recorder):
    monkeypatch.setattr(env, "_check_pi", lambda: pytest.fail("no re-probe on a green row"))
    assert env.repair_pi([_NODE_OK, _PI_GREEN]) == ([], [])
    assert env.repair_pi([_NODE_OK]) == ([], [])
    assert install_recorder == []


@pytest.mark.parametrize("row", [_PI_ADVISORY, _PI_INCOHERENT, _PI_ABSENT])
def test_repair_pi_installs_the_set_and_reports_the_green_reprobe(
    monkeypatch, install_recorder, row
):
    monkeypatch.setattr(env, "_check_pi", lambda: _PI_GREEN)
    fixed, errors = env.repair_pi([_NODE_OK, row])
    assert install_recorder == [(PI_INSTALL_SPECS, 600)]
    assert fixed == [f"pi: installed the adopted Pi {PI_ADOPTED_VERSION} set (npm -g, 8 packages)"]
    assert errors == []


def test_repair_pi_install_failure_names_the_manual_command(monkeypatch):
    def failing(*specs: str, timeout: int) -> None:
        raise npm.NpmError("npm exited 1")

    monkeypatch.setattr(npm, "install_global", failing)
    monkeypatch.setattr(env, "_check_pi", lambda: pytest.fail("no re-probe after a failed install"))
    assert env.repair_pi([_NODE_OK, _PI_INCOHERENT]) == (
        [],
        [f"pi: adopted-set install failed (npm exited 1); run manually: {PI_INSTALL_COMMAND}"],
    )


@pytest.mark.parametrize(
    "after", [_PI_ADVISORY, EnvCheck("pi", False, "1.1.0 (floor >= 1.1.0) — companions: y", "")]
)
def test_repair_pi_still_not_green_names_the_path_order(monkeypatch, install_recorder, after):
    monkeypatch.setattr(env, "_check_pi", lambda: after)
    monkeypatch.setattr(env, "which_absolute", lambda name: "/opt/other/bin/pi")
    fixed, errors = env.repair_pi([_NODE_OK, _PI_INCOHERENT])
    assert install_recorder == [(PI_INSTALL_SPECS, 600)]
    assert fixed == []
    assert errors == [
        f"pi: still {after.detail} after installing the adopted set — the pi on PATH "
        "(/opt/other/bin/pi) is not the install npm wrote; fix PATH order or remove the other pi"
    ]


def test_repair_pi_under_a_failing_node_installs_nothing(install_recorder):
    node_bad = EnvCheck("node", False, "not found", "install node")
    fixed, errors = env.repair_pi([node_bad, _PI_ABSENT])
    assert install_recorder == []
    assert fixed == []
    assert errors == [
        f"pi: install Node.js on a supported release line ({LINES}) first, then: "
        f"{PI_INSTALL_COMMAND}"
    ]
    assert errors == [env.pi_needs_node_warning()]
