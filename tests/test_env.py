import pytest

from perk.convergence import env
from perk.convergence.env import EnvCheck, check_environment, required_tools_ok
from perk.substrate.pi_host import PiHost


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
        "Install Node.js >= 22.19.0: brew install node / mise use -g node@22 (https://nodejs.org)."
    )
    assert remediations["pi"] == (
        "Install Pi: npm install -g @earendil-works/pi-coding-agent (requires Node >= 22.19.0)."
    )
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
    monkeypatch.setattr(env, "_node_version", lambda: "v20.11.0")
    node = next(c for c in env.check_environment() if c.name == "node")
    assert not node.ok
    assert node.remediation == (
        "Upgrade Node.js to >= 22.19.0 (found v20.11.0): "
        "brew upgrade node / mise use -g node@22 (https://nodejs.org)."
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
    monkeypatch.setattr(env, "_node_version", lambda: "v18.20.0")
    node = next(c for c in env.check_environment() if c.name == "node")
    assert not node.ok and "Upgrade" in node.remediation

    monkeypatch.setattr(env, "_node_version", lambda: "v22.19.0")
    node = next(c for c in env.check_environment() if c.name == "node")
    assert node.ok and node.detail == "v22.19.0"


def test_node_absent(monkeypatch):
    monkeypatch.setattr(env, "_node_version", lambda: None)
    node = next(c for c in env.check_environment() if c.name == "node")
    assert not node.ok and node.detail == "not found"


@pytest.mark.parametrize(
    "version",
    ["v22.18.0", "v22.19.0-nightly20250101", "v22", "garbage", "v21.99.99"],
)
def test_node_below_the_full_floor_or_unparsable_is_outdated(monkeypatch, version):
    monkeypatch.setattr(env, "_node_version", lambda: version)
    node = env._check_node()
    assert not node.ok
    assert node.detail == version
    assert node.remediation.startswith(f"Upgrade Node.js to >= 22.19.0 (found {version}): ")


# A prerelease of a LATER triple is above the floor (semver precedence compares the triple first).
@pytest.mark.parametrize(
    "version", ["v22.19.0", "v22.20.1", "v23.0.0-nightly20250101abc", "v24.0.0", "v26.3.0"]
)
def test_node_at_or_above_the_full_floor_is_ok(monkeypatch, version):
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
    assert pi.remediation == (
        "Install Pi: npm install -g @earendil-works/pi-coding-agent (requires Node >= 22.19.0)."
    )


def test_pi_admitted(monkeypatch):
    probed: list[str] = []
    monkeypatch.setattr(env, "which_absolute", lambda name: "/opt/bin/pi")
    monkeypatch.setattr(
        env, "probe_pi_host", lambda path: probed.append(path) or _pi_host("admitted", "1.0.3")
    )
    pi = env._check_pi()
    assert probed == ["/opt/bin/pi"]
    assert (pi.ok, pi.detail, pi.remediation) == (True, "1.0.3 (floor >= 1.0.0)", "")


def test_pi_outdated_is_not_ok(monkeypatch):
    monkeypatch.setattr(env, "which_absolute", lambda name: "/opt/bin/pi")
    monkeypatch.setattr(env, "probe_pi_host", lambda path: _pi_host("unsupported", "0.99.2"))
    pi = env._check_pi()
    assert not pi.ok
    assert pi.detail == "0.99.2 (floor >= 1.0.0)"
    assert pi.remediation == (
        "Upgrade Pi to >= 1.0.0 (found 0.99.2): npm install -g @earendil-works/pi-coding-agent."
    )
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
    assert pi.remediation == (
        "Reinstall Pi (>= 1.0.0 required): npm install -g @earendil-works/pi-coding-agent."
    )


def test_pi_with_undecodable_output_is_an_unverifiable_row_not_a_crash(monkeypatch, tmp_path):
    script = tmp_path / "pi"
    script.write_text('#!/bin/sh\nprintf "\\377\\n"\n', encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setattr(env, "which_absolute", lambda name: str(script))
    pi = env._check_pi()  # the REAL probe
    assert not pi.ok
    assert pi.detail == "version unverifiable (pi --version printed output that is not UTF-8)"
    assert pi.remediation.startswith("Reinstall Pi (>= 1.0.0 required): ")


def test_check_environment_carries_the_pi_row_in_place(monkeypatch):
    monkeypatch.setattr(env, "which_absolute", lambda name: "/opt/bin/pi")
    monkeypatch.setattr(env, "probe_pi_host", lambda path: _pi_host("unsupported", "0.99.2"))
    names = [c.name for c in check_environment()]
    assert names.index("node") + 1 == names.index("pi")
    pi = next(c for c in check_environment() if c.name == "pi")
    assert not pi.ok and pi.detail == "0.99.2 (floor >= 1.0.0)"


def _unreachable_probe(path):
    raise AssertionError(f"probe ran for an absent pi: {path}")
