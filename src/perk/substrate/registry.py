"""Load and validate the shared stage registry (`shared/registry.yaml`).

This is the Python plane's view of the language-neutral contract both planes read.
It generates `perk <stage>` subcommands from it; `doctor` folds the validator below
into its checks. The TS extension has an independent reader
(`extension/substrate/registry.ts`) over the *same* bundled file.

The validator returns structured ``Issue`` records (it never raises for invalid
*content*) so callers — the CLI and, later, ``doctor`` — decide how to surface them.
LBYL throughout (dignified-python): shapes are checked before use.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field

from perk._resources import shared_dir
from perk.boundary import LenientParseModel, translate_validation_errors

REGISTRY_FILENAME = "registry.yaml"
SUPPORTED_SCHEMA_VERSION = 1

DOORS: tuple[str, ...] = ("warm", "cold_local", "cold_remote")
MODES: tuple[str, ...] = ("read-only", "read-write")
WORKTREES: tuple[str, ...] = ("none", "reuse", "create")
RUN_ID_POLICIES: tuple[str, ...] = ("keep", "mint")


class FindingSeverity(Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class Issue:
    """A single validation finding, addressed to a stage (or the registry as a whole)."""

    severity: FindingSeverity
    where: str  # stage id, or "registry" for whole-file issues
    message: str

    def __str__(self) -> str:
        return f"[{self.severity.value}] {self.where}: {self.message}"


class StageEntry(LenientParseModel):
    """The lenient per-stage parse model at the file boundary.

    Same fields/defaults as the ``Stage`` domain dataclass; tolerant parsing
    (drop unknown keys, coerce ordinary scalars) per the lenient base.
    """

    id: str = ""
    summary: str = ""
    mode: str = ""
    worktree: str = ""
    # doors/run_id values are parsed leniently and checked by the validator, so they are
    # typed Any here (the parser never trusts them; `validate()` reports bad shapes).
    doors: dict[str, Any] = Field(default_factory=dict)
    run_id: dict[str, Any] = Field(default_factory=dict)
    command: str = ""
    requires: list[str] = Field(default_factory=list)
    reads: list[str] = Field(default_factory=list)
    writes: list[str] = Field(default_factory=list)
    predecessors: list[str] = Field(default_factory=list)
    successors: list[str] = Field(default_factory=list)

    def to_domain(self) -> "Stage":
        """Explicit field-for-field conversion into the frozen domain object."""
        return Stage(
            id=self.id,
            summary=self.summary,
            mode=self.mode,
            worktree=self.worktree,
            doors=self.doors,
            run_id=self.run_id,
            command=self.command,
            requires=self.requires,
            reads=self.reads,
            writes=self.writes,
            predecessors=self.predecessors,
            successors=self.successors,
        )


class RegistryFile(LenientParseModel):
    """The lenient whole-file parse model.

    ``schema_version`` is deliberately NOT a field: it stays a structural
    pre-check in ``load_registry`` (it must run before generic validation and
    raise its own message). ``extra="ignore"`` drops it (and any other top-level
    key) from this model.
    """

    state_keys: dict[str, Any] = Field(default_factory=dict)
    stages: list[StageEntry] = Field(default_factory=list)

    def to_domain(self, schema_version: int) -> "Registry":
        """Convert the whole validated file into the frozen ``Registry`` domain object."""
        return Registry(
            schema_version=schema_version,
            state_keys=frozenset(_flatten_state_keys(self.state_keys)),
            stages=tuple(s.to_domain() for s in self.stages),
        )


@dataclass(frozen=True)
class Stage:
    """A single stage in the registry (frozen domain object)."""

    id: str = ""
    summary: str = ""
    mode: str = ""
    worktree: str = ""
    doors: dict[str, Any] = field(default_factory=dict)
    run_id: dict[str, Any] = field(default_factory=dict)
    command: str = ""
    requires: list[str] = field(default_factory=list)
    reads: list[str] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)
    predecessors: list[str] = field(default_factory=list)
    successors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Registry:
    """The loaded registry (frozen domain object)."""

    schema_version: int
    state_keys: frozenset[str] = frozenset()  # flattened "<tier>.<key>" vocabulary
    stages: tuple[Stage, ...] = ()

    def stage_ids(self) -> set[str]:
        return {s.id for s in self.stages}


class RegistryError(Exception):
    """The registry file is missing or not parseable as the expected top-level shape.

    Distinct from validation *issues*: this means we could not load a registry object at
    all (vs. loading one that fails consistency checks).
    """


# --------------------------------------------------------------------------- load


def load_registry(path: Path | None = None) -> Registry:
    """Parse ``registry.yaml`` from the bundled ``shared/`` dir (or an explicit path).

    Raises ``RegistryError`` only for *structural* failures (missing file, not a mapping,
    missing/garbled top-level keys) — content consistency is the validator's job.
    """
    registry_path = path or (shared_dir() / REGISTRY_FILENAME)
    if not registry_path.is_file():
        raise RegistryError(f"registry not found at {registry_path}")

    data = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RegistryError(f"{registry_path}: top level must be a mapping")

    schema_version = data.get("schema_version")
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        raise RegistryError(
            f"{registry_path}: unsupported schema_version {schema_version!r} "
            f"(this perk understands {SUPPORTED_SCHEMA_VERSION}). Run 'perk doctor'."
        )

    with translate_validation_errors(RegistryError, source=str(registry_path)):
        # proven == SUPPORTED_SCHEMA_VERSION above; the literal satisfies strict int + ty.
        return RegistryFile.model_validate(data).to_domain(SUPPORTED_SCHEMA_VERSION)


def stage_by_id(stage_id: str) -> Stage:
    """The registry stage with ``stage_id`` (raises ``RegistryError`` on an unknown id).

    The one shared lookup for every command that borrows a stage descriptor for launch. A miss
    raises ``RegistryError`` (not ``StopIteration``) so the defensive registration sites can catch
    it alongside the other structural load failures.
    """
    for stage in load_registry().stages:
        if stage.id == stage_id:
            return stage
    raise RegistryError(f"unknown stage id: {stage_id!r}")


def _flatten_state_keys(raw: object) -> set[str]:
    """``{github: [plan, ...], cache: [...]}`` -> ``{"github.plan", ...}``."""
    if not isinstance(raw, dict):
        return set()
    keys: set[str] = set()
    for tier, names in raw.items():
        if isinstance(tier, str) and isinstance(names, list):
            keys.update(f"{tier}.{name}" for name in names if isinstance(name, str))
    return keys


# ----------------------------------------------------------------------- validate


def validate(registry: Registry) -> list[Issue]:
    """Return every consistency issue (empty list == valid). Never raises for content."""
    issues: list[Issue] = []
    issues.extend(_check_shapes(registry))
    issues.extend(_check_graph(registry))
    issues.extend(_check_vocabulary(registry))
    return issues


def _err(where: str, msg: str) -> Issue:
    """Shorthand for the validators' uniform ERROR-severity issues."""
    return Issue(FindingSeverity.ERROR, where, msg)


def _check_shapes(registry: Registry) -> list[Issue]:
    issues: list[Issue] = []
    seen: set[str] = set()
    for stage in registry.stages:
        where = stage.id or "<stage with no id>"
        if not stage.id:
            issues.append(_err("registry", "a stage is missing its `id`"))
        elif stage.id in seen:
            issues.append(_err(where, "duplicate stage id"))
        seen.add(stage.id)

        if not stage.summary:
            issues.append(_err(where, "missing `summary`"))
        if not stage.command:
            issues.append(_err(where, "missing `command`"))
        if stage.mode not in MODES:
            issues.append(_err(where, f"`mode` must be one of {MODES}"))
        if stage.worktree not in WORKTREES:
            issues.append(_err(where, f"`worktree` must be one of {WORKTREES}"))

        issues.extend(_check_doors_and_run_id(stage, where))
    return issues


def _check_doors_and_run_id(stage: Stage, where: str) -> list[Issue]:
    issues: list[Issue] = []
    if set(stage.doors) != set(DOORS):
        issues.append(_err(where, f"`doors` keys must be exactly {DOORS}"))
    if any(not isinstance(v, bool) for v in stage.doors.values()):
        issues.append(_err(where, "`doors` values must be booleans"))
    if set(stage.run_id) != set(DOORS):
        issues.append(_err(where, f"`run_id` keys must be exactly {DOORS}"))

    for door in DOORS:
        policy = stage.run_id.get(door)
        if policy not in RUN_ID_POLICIES:
            issues.append(_err(where, f"`run_id.{door}` must be one of {RUN_ID_POLICIES}"))
            continue
        # invariant: warm keeps, cold mints.
        if door == "warm" and policy != "keep":
            issues.append(_err(where, "`run_id.warm` must be `keep` (Q2)"))
        if door != "warm" and policy != "mint":
            issues.append(_err(where, f"`run_id.{door}` must be `mint` (Q2)"))
    return issues


def _check_graph(registry: Registry) -> list[Issue]:
    issues: list[Issue] = []
    ids = registry.stage_ids()
    by_id = {s.id: s for s in registry.stages}

    for stage in registry.stages:
        for succ in stage.successors:
            if succ not in ids:
                issues.append(_err(stage.id, f"successor `{succ}` is not a stage"))
            elif stage.id not in by_id[succ].predecessors:
                issues.append(
                    _err(
                        stage.id,
                        f"asymmetric edge: `{succ}` does not list `{stage.id}` as a predecessor",
                    )
                )
        for pred in stage.predecessors:
            if pred not in ids:
                issues.append(_err(stage.id, f"predecessor `{pred}` is not a stage"))
            elif stage.id not in by_id[pred].successors:
                issues.append(
                    _err(
                        stage.id,
                        f"asymmetric edge: `{pred}` does not list `{stage.id}` as a successor",
                    )
                )

    if registry.stages:
        initials = [s.id for s in registry.stages if not s.predecessors]
        terminals = [s.id for s in registry.stages if not s.successors]
        if not initials:
            issues.append(_err("registry", "no initial stage (none has empty predecessors)"))
        if not terminals:
            issues.append(_err("registry", "no terminal stage (none has empty successors)"))
    return issues


def _check_vocabulary(registry: Registry) -> list[Issue]:
    issues: list[Issue] = []
    for stage in registry.stages:
        for field_name, keys in (
            ("requires", stage.requires),
            ("reads", stage.reads),
            ("writes", stage.writes),
        ):
            for key in keys:
                if key not in registry.state_keys:
                    issues.append(
                        _err(
                            stage.id,
                            f"`{field_name}` key `{key}` is not in the state-key vocabulary",
                        )
                    )
    return issues
