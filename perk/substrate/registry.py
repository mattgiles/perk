"""Load and validate the shared stage registry (`shared/registry.yaml`).

This is the Python plane's view of the language-neutral contract both planes read
(`Q4`/`Q6`). T4 generates `perk <stage>` subcommands from it; T6 `doctor` folds the
validator below into its checks. The TS extension has an independent reader
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

from perk._resources import shared_dir

REGISTRY_FILENAME = "registry.yaml"
SUPPORTED_SCHEMA_VERSION = 1

DOORS: tuple[str, ...] = ("warm", "cold_local", "cold_remote")
MODES: tuple[str, ...] = ("read-only", "read-write")
WORKTREES: tuple[str, ...] = ("none", "reuse", "create")
RUN_ID_POLICIES: tuple[str, ...] = ("keep", "mint")


class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class Issue:
    """A single validation finding, addressed to a stage (or the registry as a whole)."""

    severity: Severity
    where: str  # stage id, or "registry" for whole-file issues
    message: str

    def __str__(self) -> str:
        return f"[{self.severity.value}] {self.where}: {self.message}"


@dataclass(frozen=True)
class Stage:
    id: str
    summary: str
    mode: str
    worktree: str
    # doors/run_id values are parsed leniently and checked by the validator, so they are
    # typed Any here (the parser never trusts them; `validate()` reports bad shapes).
    doors: dict[str, Any]
    run_id: dict[str, Any]
    command: str
    requires: list[str]
    reads: list[str]
    writes: list[str]
    predecessors: list[str]
    successors: list[str]


@dataclass(frozen=True)
class Registry:
    schema_version: int
    state_keys: set[str]  # flattened "<tier>.<key>" vocabulary
    stages: list[Stage]
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

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

    state_keys = _flatten_state_keys(data.get("state_keys"))
    stages = [_parse_stage(raw) for raw in _as_list(data.get("stages"))]
    return Registry(schema_version=schema_version, state_keys=state_keys, stages=stages, raw=data)


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _flatten_state_keys(raw: Any) -> set[str]:
    """``{github: [plan, ...], cache: [...]}`` -> ``{"github.plan", ...}``."""
    if not isinstance(raw, dict):
        return set()
    keys: set[str] = set()
    for tier, names in raw.items():
        if isinstance(tier, str) and isinstance(names, list):
            keys.update(f"{tier}.{name}" for name in names if isinstance(name, str))
    return keys


def _parse_stage(raw: Any) -> Stage:
    """Coerce one raw stage mapping into a ``Stage``, tolerating absent fields.

    Missing/ill-typed fields become empty defaults so the *validator* (not the parser)
    reports them — that keeps all consistency findings in one place.
    """
    raw = raw if isinstance(raw, dict) else {}
    return Stage(
        id=_str(raw.get("id")),
        summary=_str(raw.get("summary")),
        mode=_str(raw.get("mode")),
        worktree=_str(raw.get("worktree")),
        doors=_map(raw.get("doors")),
        run_id=_map(raw.get("run_id")),
        command=_str(raw.get("command")),
        requires=_str_list(raw.get("requires")),
        reads=_str_list(raw.get("reads")),
        writes=_str_list(raw.get("writes")),
        predecessors=_str_list(raw.get("predecessors")),
        successors=_str_list(raw.get("successors")),
    )


def _str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _map(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _str_list(value: Any) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


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
    return Issue(Severity.ERROR, where, msg)


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
        # Q2 invariant: warm keeps, cold mints.
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
        if len(initials) != 1:
            issues.append(_err("registry", f"expected exactly one initial stage, got {initials}"))
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
