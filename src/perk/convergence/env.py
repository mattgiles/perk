"""Environment verification for ``perk init`` (and, later, ``perk doctor``).

Presence checks for the tools perk's workflow needs, plus the one real version gate:
**node >= 22** (the extension relies on Node's native ``.ts`` type-stripping). Checks are
pure + side-effect-free; the caller decides fatality (init: missing required tool -> exit 2).
"""

import shutil
from dataclasses import dataclass

from perk.substrate.proc import ProcFailure, run_captured

_MIN_NODE_MAJOR = 22


@dataclass(frozen=True)
class EnvCheck:
    name: str
    ok: bool
    detail: str
    remediation: str
    optional: bool = False


def _node_version() -> str | None:
    """`node --version` -> e.g. ``v22.19.0`` (or ``None`` if node is absent/broken)."""
    if shutil.which("node") is None:
        return None
    try:
        proc = run_captured(["node", "--version"], timeout=10)
    except ProcFailure:
        # A defensive presence probe: any spawn/timeout failure just means "no usable node".
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
    path = shutil.which(name)
    if path is None:
        return EnvCheck(name, False, "not found", remediation)
    return EnvCheck(name, True, path, "")


def _check_optional_tool(name: str, remediation: str) -> EnvCheck:
    """Presence check for an *optional* tool — stamps ``optional=True`` either way.

    A missing optional tool is non-fatal: it never flips ``required_tools_ok`` and renders
    as a ``warn`` (doctor) / ``⚠️`` (init), never a ``missing_tool`` exit-2.
    """
    path = shutil.which(name)
    if path is None:
        return EnvCheck(name, False, "not found", remediation, optional=True)
    return EnvCheck(name, True, path, "", optional=True)


def check_environment() -> list[EnvCheck]:
    """All required-tooling checks (presence + node version)."""
    return [
        _check_tool("git", "Install git (https://git-scm.com)."),
        _check_tool("gh", "Install the GitHub CLI (https://cli.github.com)."),
        _check_node(),
        _check_tool("pi", "Install Pi (the coding agent perk drives)."),
        _check_tool("skills", "Install the skills CLI (https://github.com/mattgiles/skills)."),
        _check_optional_tool(
            "ast-grep",
            "Optional: install ast-grep for structural code search "
            "(brew install ast-grep / cargo install ast-grep / https://ast-grep.github.io).",
        ),
    ]


def required_tools_ok(checks: list[EnvCheck]) -> bool:
    """True iff every *required* tool is present (and node meets the version gate).

    Optional checks (e.g. ast-grep) are ignored — a missing optional tool is non-fatal.
    """
    return all(check.ok for check in checks if not check.optional)
