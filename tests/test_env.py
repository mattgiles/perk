from perk.convergence import env
from perk.convergence.env import EnvCheck, check_environment, required_tools_ok


def test_check_environment_covers_required_tools():
    checks = check_environment()
    required = {c.name for c in checks if not c.optional}
    assert required == {"git", "gh", "node", "pi", "skills"}
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
        "Install Node.js >= 22: brew install node / mise use -g node@22 (https://nodejs.org)."
    )
    assert remediations["pi"] == (
        "Install Pi: npm install -g @earendil-works/pi-coding-agent (requires Node >= 22)."
    )
    assert remediations["skills"] == (
        "Install the skills CLI: curl -fsSL "
        "https://raw.githubusercontent.com/mattgiles/skills/main/scripts/install.sh | sh "
        "(macOS), or: go install github.com/mattgiles/skills/cmd/skills@latest"
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
