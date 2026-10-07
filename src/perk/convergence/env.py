"""Environment verification for ``perk init`` and ``perk doctor``.

Presence checks for the tools perk's workflow needs (``cloc`` counts every submitted PR's change
stats), plus the two version gates — **node** and **pi** — read from the shared host floor
(``shared/host-floor.yaml``, contracts.md §8.76) and compared with semver precedence. An
installed-but-outdated or unverifiable Node/Pi is ``ok=False`` exactly like an absent one. Checks
are side-effect-free probes; the caller decides fatality (init: missing/outdated required tool
-> exit 2; doctor: ``fail``). The launch admission in ``perk.run.pi_exec`` shares the Pi probe
(``perk.substrate.pi_host``) but never gates these checks.
"""

import shutil
from dataclasses import dataclass

from perk.substrate import cloc
from perk.substrate.host_floor import load_host_floor, required_node_version
from perk.substrate.pi_host import PI_INSTALL_COMMAND, probe_pi_host
from perk.substrate.proc import ProcFailure, run_captured, which_absolute
from perk.substrate.semver import parse_semver, satisfies_floor


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


def _check_node() -> EnvCheck:
    """The full Node floor (not just the major): an unparsable version counts as outdated."""
    floor = required_node_version(load_host_floor())
    version = _node_version()
    if version is None:
        return EnvCheck(
            "node",
            False,
            "not found",
            f"Install Node.js >= {floor}: brew install node / mise use -g node@{floor.major} "
            "(https://nodejs.org).",
        )
    observed = parse_semver(version)
    if observed is None or not satisfies_floor(observed, floor):
        return EnvCheck(
            "node",
            False,
            version,
            f"Upgrade Node.js to >= {floor} (found {version}): "
            f"brew upgrade node / mise use -g node@{floor.major} (https://nodejs.org).",
        )
    return EnvCheck("node", True, version, "")


def _check_pi() -> EnvCheck:
    """Presence + the Pi floor, through the same probe the launch admission uses.

    Reads ``which_absolute`` / ``probe_pi_host`` as this module's globals (the test seams).
    """
    floor = load_host_floor()
    path = which_absolute("pi")
    if path is None:
        return EnvCheck(
            "pi",
            False,
            "not found",
            f"Install Pi: {PI_INSTALL_COMMAND} (requires Node >= {floor.node_min_version}).",
        )
    host = probe_pi_host(path)
    if host.outcome == "admitted":
        return EnvCheck("pi", True, f"{host.observed} (floor >= {host.required})", "")
    if host.outcome == "unsupported":
        return EnvCheck(
            "pi",
            False,
            f"{host.observed} (floor >= {host.required})",
            f"Upgrade Pi to >= {host.required} (found {host.observed}): {PI_INSTALL_COMMAND}.",
        )
    return EnvCheck(
        "pi",
        False,
        f"version unverifiable ({host.detail})",
        f"Reinstall Pi (>= {host.required} required): {PI_INSTALL_COMMAND}.",
    )


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
    """All required-tooling checks (presence + the node and pi version floors).

    The required-tool remediations carry the exact install command — rendered by init's
    failure path, doctor, AND the interactive guided-install pass (which offers to run the
    supported ones; the ``git``/``node`` strings are guide-only, OS-owned).
    """
    return [
        _check_tool(
            "git",
            "Install git: brew install git / xcode-select --install (macOS), "
            "or your distro package manager (https://git-scm.com).",
        ),
        _check_tool(
            "gh", "Install the GitHub CLI: brew install gh (or see https://cli.github.com)."
        ),
        _check_node(),
        _check_pi(),
        _check_tool(
            "skills",
            "Install the skills CLI: curl -fsSL "
            "https://raw.githubusercontent.com/mattgiles/skills/main/scripts/install.sh | sh "
            "(macOS), or: go install github.com/mattgiles/skills/cmd/skills@latest",
        ),
        _check_tool("cloc", cloc.INSTALL_HINT),
        _check_optional_tool(
            "ast-grep",
            "Optional: install ast-grep for structural code search "
            "(brew install ast-grep / cargo install ast-grep / https://ast-grep.github.io).",
        ),
    ]


def required_tools_ok(checks: list[EnvCheck]) -> bool:
    """True iff every *required* tool is present (and node/pi meet the host floor).

    Optional checks (e.g. ast-grep) are ignored — a missing optional tool is non-fatal.
    """
    return all(check.ok for check in checks if not check.optional)
