"""Environment verification for ``perk init`` and ``perk doctor``.

Presence checks for the tools perk's workflow needs (``cloc`` counts every submitted PR's change
stats), plus the two version gates read from the shared host floor (``shared/host-floor.yaml``,
contracts.md §8.76) and compared with semver precedence: **pi** against its single minimum, and
**node** by supported-line admission — its major must be one of the floor's supported release
lines and the version at or above that line's floor. An installed-but-outdated, unsupported-line
or unverifiable Node/Pi is ``ok=False`` exactly like an absent one. Checks
are side-effect-free probes; the caller decides fatality (init: missing/outdated required tool
-> exit 2; doctor: ``fail``). The launch admission in ``perk.run.pi_exec`` shares the Pi probe
(``perk.substrate.pi_host``) but never gates these checks.

The adopted Pi whose companion packages do not resolve as the adopted family (contracts.md
§8.76(c), ``incoherent``) is ``ok=False`` with the offenders in the detail, repaired by
``perk doctor --fix``.

A Pi admitted at a version other than the adopted Pi pin stays ``ok`` (the floor is a minimum) but
carries an **advisory** naming the pinned install command — a successful init renders it as a
warning, doctor as a ``warn`` check. The ``pi`` row reads the PATH ``pi`` only: the Pi a session
actually runs may be a different install (contracts.md §8.76(f)), which is why the extension's
SDK-boundary refusal names the public requirements reference rather than this row.

``repair_pi`` is the one Pi repair gesture (``perk doctor --fix``): gap-driven over the ``pi``
row, it runs the pinned eight-spec install as an argument list, then re-probes — the only
function here with a side effect, and never called by a check.
"""

import shutil
from dataclasses import dataclass

from perk.substrate import cloc, npm
from perk.substrate.host_floor import (
    describe_node_lines,
    load_host_floor,
    node_line_floor,
    supported_node_lines,
)
from perk.substrate.output import io_step
from perk.substrate.pi_host import (
    PI_ADOPTED_VERSION,
    PI_INSTALL_COMMAND,
    PI_INSTALL_SPECS,
    probe_pi_host,
)
from perk.substrate.proc import ProcFailure, run_captured, which_absolute
from perk.substrate.semver import parse_semver, satisfies_floor

# The pinned install downloads eight packages over the network.
_PI_INSTALL_TIMEOUT = 600
_PI_FIX_REMEDIATION = f"Run `perk doctor --fix` (it runs: {PI_INSTALL_COMMAND})."


@dataclass(frozen=True)
class EnvCheck:
    """One environment probe result.

    ``advisory`` is a non-blocking caution on an ``ok`` row — rendered as a warning by a
    successful init and as a ``warn`` check by doctor; it is always empty on a not-ok row (whose
    ``remediation`` carries the repair).
    """

    name: str
    ok: bool
    detail: str
    remediation: str
    optional: bool = False
    advisory: str = ""


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
    """Supported-line admission: a supported major at or above its line floor.

    An unparsable version counts as outdated; a major outside the closed table is an
    unsupported release line.
    """
    lines = supported_node_lines(load_host_floor())
    described = describe_node_lines(lines)
    version = _node_version()
    if version is None:
        return EnvCheck(
            "node",
            False,
            "not found",
            f"Install Node.js on a supported release line ({described}): brew install node / "
            f"mise use -g node@{lines[0].major} (https://nodejs.org).",
        )
    observed = parse_semver(version)
    if observed is None:
        return EnvCheck(
            "node",
            False,
            version,
            f"Upgrade Node.js to a supported release line ({described}) (found {version}): "
            f"brew upgrade node / mise use -g node@{lines[0].major} (https://nodejs.org).",
        )
    line_floor = node_line_floor(lines, observed)
    if line_floor is None:
        return EnvCheck(
            "node",
            False,
            f"{version} (unsupported release line)",
            f"Node.js {observed.major}.x is not a supported release line; install one of "
            f"{described}: brew install node / mise use -g node@{lines[-1].major} "
            "(https://nodejs.org).",
        )
    if not satisfies_floor(observed, line_floor):
        return EnvCheck(
            "node",
            False,
            version,
            f"Upgrade Node.js to >= {line_floor} (found {version}): "
            f"brew upgrade node / mise use -g node@{line_floor} (https://nodejs.org).",
        )
    return EnvCheck("node", True, version, "")


def _check_pi() -> EnvCheck:
    """Presence + the Pi floor, through the same probe the launch admission uses.

    Reads ``which_absolute`` / ``probe_pi_host`` as this module's globals (the test seams).
    """
    lines = supported_node_lines(load_host_floor())
    path = which_absolute("pi")
    if path is None:
        return EnvCheck(
            "pi",
            False,
            "not found",
            f"Install Pi: {PI_INSTALL_COMMAND} (requires Node.js on a supported release line: "
            f"{describe_node_lines(lines)}).",
        )
    host = probe_pi_host(path)
    if host.outcome == "admitted":
        detail = f"{host.observed} (floor >= {host.required})"
        if host.observed == PI_ADOPTED_VERSION:
            return EnvCheck("pi", True, detail, "")
        return EnvCheck(
            "pi",
            True,
            detail,
            "",
            advisory=(
                f"Pi {host.observed} is admitted (floor >= {host.required}) but is not the "
                f"adopted Pi {PI_ADOPTED_VERSION}: perk's subagent waves are characterized only "
                "on the adopted Pi with its pinned companions and can be refused on another. "
                f"Install the adopted set: {PI_INSTALL_COMMAND}."
            ),
        )
    if host.outcome == "unsupported":
        return EnvCheck(
            "pi",
            False,
            f"{host.observed} (floor >= {host.required})",
            f"Upgrade Pi to >= {host.required} (found {host.observed}): {PI_INSTALL_COMMAND}.",
        )
    if host.outcome == "incoherent":
        return EnvCheck(
            "pi",
            False,
            f"{host.observed} (floor >= {host.required}) — companions: {host.detail}",
            _PI_FIX_REMEDIATION,
        )
    return EnvCheck(
        "pi",
        False,
        f"version unverifiable ({host.detail})",
        _PI_FIX_REMEDIATION,
    )


def pi_needs_node_warning() -> str:
    """The one "install Node first" sentence (the guided install pass emits the same text)."""
    node_lines = describe_node_lines(supported_node_lines(load_host_floor()))
    return (
        f"pi: install Node.js on a supported release line ({node_lines}) first, "
        f"then: {PI_INSTALL_COMMAND}"
    )


def repair_pi(checks: list[EnvCheck]) -> tuple[list[str], list[str]]:
    """The ``perk doctor --fix`` Pi repair gesture — gap-driven, never raises.

    A no-op ``([], [])`` unless the ``pi`` row is not ok (absent / unsupported / unverifiable /
    incoherent) or carries the advisory (admitted, not the adopted Pi). A failing ``node`` row
    stops it with the install-Node-first warning (nothing installed). Otherwise one
    ``npm install -g`` of the pinned eight-spec set (an argument list), then a re-probe: green →
    one fixed line; an ``NpmError`` → the manual-command error; still not green → the PATH-order
    error (the ``pi`` PATH finds is not the install npm wrote). Reads ``_check_pi`` /
    ``which_absolute`` / ``npm`` as module globals (the test seams).
    """
    pi = next((c for c in checks if c.name == "pi"), None)
    if pi is None or (pi.ok and not pi.advisory):
        return ([], [])
    if not any(c.name == "node" and c.ok for c in checks):
        return ([], [pi_needs_node_warning()])
    try:
        with io_step("installing the adopted Pi set"):
            npm.install_global(*PI_INSTALL_SPECS, timeout=_PI_INSTALL_TIMEOUT)
    except npm.NpmError as exc:
        return ([], [f"pi: adopted-set install failed ({exc}); run manually: {PI_INSTALL_COMMAND}"])
    after = _check_pi()
    if after.ok and not after.advisory:
        return (
            [
                f"pi: installed the adopted Pi {PI_ADOPTED_VERSION} set "
                f"(npm -g, {len(PI_INSTALL_SPECS)} packages)"
            ],
            [],
        )
    on_path = which_absolute("pi") or "not on PATH"
    return (
        [],
        [
            f"pi: still {after.detail} after installing the adopted set — the pi on PATH "
            f"({on_path}) is not the install npm wrote; fix PATH order or remove the other pi"
        ],
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
