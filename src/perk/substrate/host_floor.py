"""Load and validate the shared host floor (`shared/host-floor.yaml`, contracts.md §8.76).

This is the Python plane's reader of the *fourth* parsed cross-plane contract (after
`shared/registry.yaml`, `shared/bindings.yaml` and `shared/providers.yaml`). The declaration names
the minimum supported host versions — Pi and Node — once, as semver floors (``>=``). The TS plane
has an independent structural reader (`extension/substrate/hostFloor.ts`) over the same bundled
file; this reader is the authoritative content validator.

A floor is a **minimum**, never a pin: it is distinct from the development pins
(``package.json`` devDependencies), the pi-subagents supplier pin, the doctor guidance stamp and the
remote install pin (``perk.run.workflow_artifacts.REMOTE_PI_VERSION``). Consumers compare each host
observation independently against it (``perk.substrate.pi_host`` for the PATH ``pi`` CLI,
``perk.convergence.env`` for ``node``).

The boundary follows the canonical lenient-parse → frozen-dataclass → ``validate()`` pattern:
``HostFloorFile`` parses the untrusted file, ``HostFloor`` is the frozen domain object, and
``validate(HostFloor) -> [Issue]`` runs the content checks (non-empty, parseable semver, a release
— no prerelease or build metadata). ``HostFloorError`` is reserved for structural load failures
(missing file, YAML error, not a mapping, unsupported ``schema_version``, a wrong-typed present
field) and for a consumer accessor meeting a corrupt bundle.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import Field

from perk._resources import shared_dir
from perk.boundary import LenientParseModel, translate_validation_errors
from perk.substrate.registry import FindingSeverity, Issue
from perk.substrate.semver import Semver, parse_semver

HOST_FLOOR_FILENAME = "host-floor.yaml"
SUPPORTED_SCHEMA_VERSION = 1


class _FloorEntry(LenientParseModel):
    """One host's floor entry. ``str | None`` so an explicit YAML ``null`` reads as missing."""

    min_version: str | None = None


class HostFloorFile(LenientParseModel):
    """The lenient whole-file parse model.

    ``schema_version`` is deliberately NOT a field: it stays a structural pre-check in
    ``load_host_floor`` (it must run before generic validation and raise its own message).
    """

    pi: _FloorEntry = Field(default_factory=_FloorEntry)
    node: _FloorEntry = Field(default_factory=_FloorEntry)

    def to_domain(self, schema_version: int) -> "HostFloor":
        """Convert into the frozen domain object, normalizing a missing version to ``""``."""
        return HostFloor(
            schema_version=schema_version,
            pi_min_version=self.pi.min_version or "",
            node_min_version=self.node.min_version or "",
        )


@dataclass(frozen=True)
class HostFloor:
    """The loaded host floor (frozen domain object); versions are the declared text."""

    schema_version: int
    pi_min_version: str
    node_min_version: str


class HostFloorError(Exception):
    """The host floor could not be loaded (structural), or a consumer met a corrupt bundle."""


# --------------------------------------------------------------------------- load


def load_host_floor(path: Path | None = None) -> HostFloor:
    """Parse ``host-floor.yaml`` from the bundled ``shared/`` dir (or an explicit path).

    Raises ``HostFloorError`` only for structural failures — content is the validator's job.
    """
    floor_path = path or (shared_dir() / HOST_FLOOR_FILENAME)
    if not floor_path.is_file():
        raise HostFloorError(f"host floor not found at {floor_path}")

    try:
        data = yaml.safe_load(floor_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise HostFloorError(f"{floor_path}: not parseable as YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise HostFloorError(f"{floor_path}: top level must be a mapping")

    schema_version = data.get("schema_version")
    # bool is an int subclass and True == 1; require a genuine int.
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version != SUPPORTED_SCHEMA_VERSION
    ):
        raise HostFloorError(
            f"{floor_path}: unsupported schema_version {schema_version!r} "
            f"(this perk understands {SUPPORTED_SCHEMA_VERSION}). Run 'perk doctor'."
        )

    with translate_validation_errors(HostFloorError, source=str(floor_path)):
        return HostFloorFile.model_validate(data).to_domain(SUPPORTED_SCHEMA_VERSION)


# ----------------------------------------------------------------------- validate


def _version_problem(text: str) -> str | None:
    """Why ``text`` is not a usable floor (``None`` when it is a plain release version)."""
    if not text:
        return "is missing"
    parsed = parse_semver(text)
    if parsed is None:
        return f"{text!r} is not a semver version"
    # The canonical rendering drops build metadata, a leading `v` and whitespace, so inequality
    # catches all three; the floor text is rendered verbatim elsewhere (e.g. `node-version`).
    if parsed.prerelease or text != str(parsed):
        return f"{text!r} must be a plain release version (MAJOR.MINOR.PATCH)"
    return None


def validate(floor: HostFloor) -> list[Issue]:
    """Return every content issue (empty list == valid). Never raises for content."""
    issues: list[Issue] = []
    for host, text in (("pi", floor.pi_min_version), ("node", floor.node_min_version)):
        problem = _version_problem(text)
        if problem is not None:
            issues.append(
                Issue(FindingSeverity.ERROR, "host-floor", f"`{host}.min_version` {problem}")
            )
    return issues


# ---------------------------------------------------------------------- accessors


def _require_release(host: str, text: str) -> Semver:
    """Parse a floor entry for a consumer, or raise — a healthy bundle never reaches the raise."""
    problem = _version_problem(text)
    parsed = parse_semver(text)
    if problem is not None or parsed is None:
        raise HostFloorError(
            f"`{host}.min_version` {problem or 'is unreadable'} — corrupt bundled host floor — "
            "reinstall perk"
        )
    return parsed


def required_pi_version(floor: HostFloor) -> Semver:
    """The Pi floor as a ``Semver`` (raises ``HostFloorError`` on a corrupt bundle)."""
    return _require_release("pi", floor.pi_min_version)


def required_node_version(floor: HostFloor) -> Semver:
    """The Node floor as a ``Semver`` (raises ``HostFloorError`` on a corrupt bundle)."""
    return _require_release("node", floor.node_min_version)
