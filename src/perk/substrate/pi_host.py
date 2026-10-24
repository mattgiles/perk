"""The PATH ``pi`` host probe and its pure admission decision (contracts.md §8.76).

One home for both consumers of the Pi floor: the launch preflight in ``perk.run.pi_exec``
(refuses a non-admitted host before any exec-phase side effect) and the ``pi`` environment row in
``perk.convergence.env`` (reports the same requirement through ``perk init`` / ``perk doctor``).

The decision is split from the I/O so it is testable without a process:

- ``admit_pi_version`` is **pure** — the ``pi --version`` stdout against the floor →
  ``admitted`` / ``unsupported`` (parses, below the floor — a prerelease of the floor triple
  included) / ``unverifiable`` (not a version).
- ``admit_pi_companions`` is **pure** — the resolved companion versions against the adopted
  family → ``""`` (coherent) or a one-line offender detail.
- ``probe_pi_host`` is the I/O — one bounded ``pi --version`` spawn through ``run_captured``; a
  timeout, a spawn failure, a non-zero exit or undecodable output are ``unverifiable``. When the
  CLI answers the adopted version it also reads the installed package's companion graph through
  ``locate_pi_package`` / ``resolve_companions`` (filesystem reads only): a broken family is
  ``incoherent``, a ``pi`` that is not inside an installed package is ``unverifiable``. It never
  raises, never touches the network, never installs, never mutates the environment.

The version admission reads only the PATH CLI's own answer, and the companion read is anchored at
the resolved executable — never the repo's dev SDK install or a loaded SDK. Those are independent
observations, and equality between them is never required (a CLI ``1.4.0`` beside a ``1.4.1`` dev
SDK is admitted on the CLI's own reading). Only the adopted version's family is checked: perk
knows exactly one companion family, and a floor-satisfying Pi at another version is admitted on
its version alone (the environment row's advisory covers it).

This module also declares the **adopted Pi pin** (``PI_ADOPTED_VERSION``) and its **pinned install
set** (``PI_INSTALL_SPECS`` / ``PI_INSTALL_COMMAND``): the one exact spec of the Pi perk adopted,
whose own exact internal declarations place its companion packages at that same version. It
lives here, below ``perk.run``, so the
launch refusal, the environment rows, the guided install and the remote install pin all name the
same version and the same command. The floor admits any Pi at or above it; the adopted pin is what
every install-guidance string installs.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from perk.substrate.host_floor import load_host_floor, required_pi_version
from perk.substrate.proc import ProcFailure, run_captured
from perk.substrate.semver import Semver, parse_semver, satisfies_floor

PI_NPM_SPEC = "@earendil-works/pi-coding-agent"
# The adopted Pi pin: the exact published Pi perk adopted (the remote install pin carries this
# same value). It is distinct from the host floor (a minimum), the dev pins, the pi-subagents
# supplier pin and the guidance stamp; it moves on characterization + offline evidence (the live
# certification follows) and never below the floor.
#
# Since Pi 1.3.0 the package declares its `@earendil-works/*` companions at exact versions (no
# shrinkwrap — none needed), so a lockfile-free install of the one exact spec places the whole
# family at the adopted version, where Node's module resolvers and pi-subagents' peer-alias
# resolver reach it. The companion tuple remains the coherence family the probe verifies: exact
# declarations do not prove an INSTALLED family is intact (a dangling link, a stale nested copy).
# The tuple is pinned closed against the committed lockfile by test, and a separate test pins
# every family declaration exact there.
PI_ADOPTED_VERSION = "1.4.0"
PI_COMPANION_PACKAGES: tuple[str, ...] = (
    "@earendil-works/pi-agent-core",
    "@earendil-works/pi-ai",
    "@earendil-works/pi-codemode",
    "@earendil-works/pi-mcp",
    "@earendil-works/pi-telemetry",
    "@earendil-works/pi-tui",
)
PI_INSTALL_SPECS: tuple[str, ...] = (f"{PI_NPM_SPEC}@{PI_ADOPTED_VERSION}",)
PI_INSTALL_COMMAND = f"npm install -g {' '.join(PI_INSTALL_SPECS)}"
# `pi --version` answers before any extension/settings load (well under a second measured); the
# generous bound only catches a wedged binary, which reads as unverifiable.
PI_VERSION_PROBE_TIMEOUT = 20

_DETAIL_PREVIEW_CHARS = 80

PiHostOutcome = Literal["admitted", "unsupported", "unverifiable", "incoherent"]
PiRefusalErrorType = Literal[
    "pi_version_unsupported", "pi_version_unverifiable", "pi_companions_incoherent"
]


@dataclass(frozen=True)
class PiHost:
    """One admission decision about the PATH ``pi`` executable.

    ``observed`` is the parsed version's canonical text (``None`` when unverifiable);
    ``required`` is the floor's text; ``detail`` is the unverifiable reason or the incoherent
    companion offenders (``""`` otherwise).
    """

    executable: str
    outcome: PiHostOutcome
    observed: str | None
    required: str
    detail: str


def admit_pi_version(executable: str, stdout: str, floor: Semver) -> PiHost:
    """Decide admission from ``pi --version``'s stdout (pure)."""
    stripped = stdout.strip()
    observed = parse_semver(stripped)
    if observed is None:
        preview = stripped[:_DETAIL_PREVIEW_CHARS]
        return PiHost(
            executable=executable,
            outcome="unverifiable",
            observed=None,
            required=str(floor),
            detail=f"pi --version printed {preview!r} instead of a version",
        )
    return PiHost(
        executable=executable,
        outcome="admitted" if satisfies_floor(observed, floor) else "unsupported",
        observed=str(observed),
        required=str(floor),
        detail="",
    )


def _read_manifest(path: Path) -> dict[str, object] | None:
    """``path`` parsed as a JSON object, or ``None`` when absent, unreadable or not an object."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def locate_pi_package(executable: str) -> Path | None:
    """The installed ``@earendil-works/pi-coding-agent`` directory ``executable`` belongs to.

    Follows the global-bin symlink (``bin/pi`` → ``…/pi-coding-agent/dist/bundle/cli.js``), then
    returns the first ancestor whose ``package.json`` names the package; ``None`` when no
    ancestor qualifies. An unreadable or non-object ``package.json`` (a nested ``{"type": …}``
    marker included) is skipped, never fatal. Never raises.
    """
    try:
        resolved = Path(executable).resolve()
    except (OSError, RuntimeError):
        return None
    for parent in resolved.parents:
        manifest = _read_manifest(parent / "package.json")
        if manifest is not None and manifest.get("name") == PI_NPM_SPEC:
            return parent
    return None


def resolve_companions(entry_dir: Path) -> dict[str, str | None]:
    """Each companion's version as Node resolves it from ``entry_dir`` (the resolved ``pi``'s dir).

    Node's ESM package lookup walk: for each ancestor ``d`` of ``entry_dir`` (itself included) not
    itself named ``node_modules``, the candidate is the directory ``d/node_modules/<name>``; the
    first one that exists (symlinks followed) **wins**, whatever it holds. That finds a copy
    nested under the Pi package before the global-root sibling, reports a dangling symlink as
    unresolved, and never falls through past a winning directory — Node would load from it.
    The winner's version is its ``package.json`` ``version``; a missing or unreadable manifest
    or a non-string version there is unresolved (``None``). Never raises.
    """
    lookup_dirs = [d for d in (entry_dir, *entry_dir.parents) if d.name != "node_modules"]
    resolved: dict[str, str | None] = {}
    for name in PI_COMPANION_PACKAGES:
        resolved[name] = None
        for directory in lookup_dirs:
            package_dir = directory / "node_modules" / name
            try:
                exists = package_dir.is_dir()
            except OSError:
                exists = False
            if not exists:
                continue
            manifest = _read_manifest(package_dir / "package.json")
            version = None if manifest is None else manifest.get("version")
            resolved[name] = version if isinstance(version, str) else None
            break
    return resolved


def admit_pi_companions(resolved: Mapping[str, str | None]) -> str:
    """``""`` when every companion resolved at the adopted version, else the offender detail.

    Pure. Offenders are listed in ``PI_COMPANION_PACKAGES`` order, comma-separated:
    ``<name> resolves to <version>`` / ``<name> does not resolve``.
    """
    offenders: list[str] = []
    for name in PI_COMPANION_PACKAGES:
        version = resolved.get(name)
        if version is None:
            offenders.append(f"{name} does not resolve")
        elif version != PI_ADOPTED_VERSION:
            offenders.append(f"{name} resolves to {version}")
    return ", ".join(offenders)


def _verify_family(host: PiHost, floor: Semver) -> PiHost:
    """Family-check an adopted-version host: ``incoherent`` / ``unverifiable`` on a gap."""
    package = locate_pi_package(host.executable)
    if package is None:
        try:
            realpath = str(Path(host.executable).resolve())
        except (OSError, RuntimeError):
            realpath = host.executable
        return _unverifiable(
            host.executable,
            floor,
            f"pi at {host.executable} resolves to {realpath}, which is not inside an installed "
            f"{PI_NPM_SPEC} package",
        )
    entry_dir = Path(host.executable).resolve().parent
    offenders = admit_pi_companions(resolve_companions(entry_dir))
    if not offenders:
        return host
    return PiHost(
        executable=host.executable,
        outcome="incoherent",
        observed=host.observed,
        required=host.required,
        detail=offenders,
    )


def _unverifiable(executable: str, floor: Semver, detail: str) -> PiHost:
    return PiHost(
        executable=executable,
        outcome="unverifiable",
        observed=None,
        required=str(floor),
        detail=detail,
    )


def probe_pi_host(executable: str, floor: Semver | None = None) -> PiHost:
    """Run ``<executable> --version`` once (bounded) and decide admission. Never raises.

    An admitted host at exactly ``PI_ADOPTED_VERSION`` is then family-checked: its companions
    must resolve (from the resolved executable, Node's way) at the adopted version, else
    ``incoherent``; a ``pi`` not inside an installed Pi package is ``unverifiable``. Any other
    admitted version is not family-checked.

    ``floor`` defaults to the bundled host floor's Pi entry (a corrupt bundle raises
    ``HostFloorError`` from the accessor — that is a broken install, not a host verdict).
    """
    if floor is None:
        floor = required_pi_version(load_host_floor())
    try:
        result = run_captured([executable, "--version"], timeout=PI_VERSION_PROBE_TIMEOUT)
    except ProcFailure as exc:
        if exc.kind == "timeout":
            detail = f"pi --version timed out after {PI_VERSION_PROBE_TIMEOUT} s"
        else:
            detail = f"pi --version could not run: {exc.cause_text}"
        return _unverifiable(executable, floor, detail)
    except UnicodeDecodeError:
        # The capture wrapper decodes both streams strictly; a broken binary's undecodable output
        # is a host verdict, not a crash of the launch / init / doctor paths.
        return _unverifiable(executable, floor, "pi --version printed output that is not UTF-8")
    if result.returncode != 0:
        stderr_lines = [line for line in result.stderr.splitlines() if line.strip()]
        last = stderr_lines[-1].strip() if stderr_lines else "(no output)"
        return _unverifiable(executable, floor, f"pi --version exited {result.returncode}: {last}")
    host = admit_pi_version(executable, result.stdout, floor)
    if host.outcome == "admitted" and host.observed == PI_ADOPTED_VERSION:
        return _verify_family(host, floor)
    return host


def format_pi_refusal(host: PiHost) -> str:
    """The human refusal text for a non-admitted host (executable, version, floor, repair)."""
    if host.outcome == "unsupported":
        return (
            f"pi at {host.executable} is version {host.observed}; perk requires Pi >= "
            f"{host.required}. Upgrade it: {PI_INSTALL_COMMAND} — perk init and perk doctor "
            "report the same requirement."
        )
    if host.outcome == "incoherent":
        return (
            f"pi at {host.executable} is Pi {host.observed}, but its companion packages are not "
            f"the {host.observed} family: {host.detail}. perk requires the matching family — "
            f"run: perk doctor --fix (it runs: {PI_INSTALL_COMMAND})."
        )
    return (
        f"could not verify the Pi version of {host.executable} ({host.detail}); perk requires "
        f"Pi >= {host.required}. Reinstall it: {PI_INSTALL_COMMAND}."
    )


def pi_refusal_error_type(host: PiHost) -> PiRefusalErrorType:
    """The typed error code for a non-admitted host."""
    if host.outcome == "unsupported":
        return "pi_version_unsupported"
    if host.outcome == "incoherent":
        return "pi_companions_incoherent"
    return "pi_version_unverifiable"
