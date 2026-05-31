"""Environment verification for ``perk init`` (and, later, ``perk doctor``).

Presence checks for the tools perk's workflow needs, plus the one real version gate:
**node >= 22** (the extension relies on Node's native ``.ts`` type-stripping). Checks are
pure + side-effect-free; the caller decides fatality (init: missing required tool -> exit 2).
"""

import shutil
import subprocess
from dataclasses import dataclass

_MIN_NODE_MAJOR = 22


@dataclass(frozen=True)
class EnvCheck:
    name: str
    ok: bool
    detail: str
    remediation: str


def _which(name: str) -> str | None:
    return shutil.which(name)


def _node_version() -> str | None:
    """`node --version` -> e.g. ``v22.19.0`` (or ``None`` if node is absent/broken)."""
    if _which("node") is None:
        return None
    try:
        proc = subprocess.run(
            ["node", "--version"], check=False, capture_output=True, text=True, timeout=10
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.strip() or None


def _node_major(version: str) -> int | None:
    """Parse the major from ``vMAJOR.MINOR.PATCH`` (defensive)."""
    try:
        return int(version.lstrip("v").split(".", 1)[0])
    except ValueError:
        return None


def _check_node() -> EnvCheck:
    version = _node_version()
    if version is None:
        return EnvCheck("node", False, "not found", "Install Node.js >= 22 (https://nodejs.org).")
    major = _node_major(version)
    if major is None or major < _MIN_NODE_MAJOR:
        return EnvCheck(
            "node", False, version, f"Upgrade Node.js to >= {_MIN_NODE_MAJOR} (found {version})."
        )
    return EnvCheck("node", True, version, "")


def _check_tool(name: str, remediation: str) -> EnvCheck:
    path = _which(name)
    if path is None:
        return EnvCheck(name, False, "not found", remediation)
    return EnvCheck(name, True, path, "")


def check_environment() -> list[EnvCheck]:
    """All required-tooling checks (presence + node version)."""
    return [
        _check_tool("git", "Install git (https://git-scm.com)."),
        _check_tool("gh", "Install the GitHub CLI (https://cli.github.com)."),
        _check_node(),
        _check_tool("pi", "Install Pi (the coding agent perk drives)."),
    ]


def required_tools_ok(checks: list[EnvCheck]) -> bool:
    """True iff every required tool is present (and node meets the version gate)."""
    return all(check.ok for check in checks)
