"""Load and validate the shared skill-binding set (`shared/bindings.yaml`).

This is the Python plane's reader of the *second* parsed cross-plane contract (the first
being `shared/registry.yaml`). It maps a `trigger` (`"<kind>:<id>"`) to a `skill` plus a
per-binding delivery `mode` (`nudge`/`transclude`). The TS extension has an independent
reader (`extension/bindings.ts`) over the *same* bundled file.

Validation is **shape-only and registry-free**: the validator checks that each binding's
fields are well formed (and that no trigger repeats), but it does NOT cross-check that a
`stage:` target is a real registry stage or that a `command:` target is a real command —
that target-existence validation is `doctor`'s job (Node 3.1).

This node (1.1) locks the shape + ships the defaults with **no runtime behavior**: nothing
imports this module yet. The resolver (`shipped-defaults ⊕ user-bindings`) is Node 1.2.

The validator returns structured ``Issue`` records (it never raises for invalid *content*)
so callers decide how to surface them; ``BindingsError`` is reserved for structural load
failures. LBYL throughout (dignified-python): shapes are checked before use.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from perk._resources import shared_dir
from perk.registry import Issue, Severity

BINDINGS_FILENAME = "bindings.yaml"
SUPPORTED_SCHEMA_VERSION = 1

TRIGGER_KINDS: tuple[str, ...] = ("stage", "command")
MODES: tuple[str, ...] = ("nudge", "transclude")


@dataclass(frozen=True)
class Binding:
    """One trigger->skill delivery binding.

    ``kind``/``target_id`` are the parsed halves of ``trigger`` (split on the first ``:``);
    a trigger with no ``:`` parses to ``kind=""``, ``target_id=""`` so the validator can
    report it.
    """

    trigger: str
    kind: str
    target_id: str
    skill: str
    mode: str


@dataclass(frozen=True)
class BindingSet:
    schema_version: int
    bindings: list[Binding]
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


class BindingsError(Exception):
    """The bindings file is missing or not parseable as the expected top-level shape.

    Distinct from validation *issues*: this means we could not load a binding set at all
    (vs. loading one that fails consistency checks). Mirrors ``RegistryError``.
    """


# --------------------------------------------------------------------------- load


def load_bindings(path: Path | None = None) -> BindingSet:
    """Parse ``bindings.yaml`` from the bundled ``shared/`` dir (or an explicit path).

    Raises ``BindingsError`` only for *structural* failures (missing file, not a mapping,
    unsupported ``schema_version``) — content consistency is the validator's job.
    """
    bindings_path = path or (shared_dir() / BINDINGS_FILENAME)
    if not bindings_path.is_file():
        raise BindingsError(f"bindings not found at {bindings_path}")

    data = yaml.safe_load(bindings_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise BindingsError(f"{bindings_path}: top level must be a mapping")

    schema_version = data.get("schema_version")
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        raise BindingsError(
            f"{bindings_path}: unsupported schema_version {schema_version!r} "
            f"(this perk understands {SUPPORTED_SCHEMA_VERSION}). Run 'perk doctor'."
        )

    bindings = [_parse_binding(raw) for raw in _as_list(data.get("bindings"))]
    return BindingSet(schema_version=schema_version, bindings=bindings, raw=data)


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _parse_binding(raw: Any) -> Binding:
    """Coerce one raw binding mapping into a ``Binding``, tolerating absent fields.

    Missing/ill-typed fields become empty strings so the *validator* (not the parser)
    reports them — keeping all consistency findings in one place (matches
    ``registry._parse_stage``).
    """
    raw = raw if isinstance(raw, dict) else {}
    trigger = _str(raw.get("trigger"))
    kind, target_id = _split_trigger(trigger)
    return Binding(
        trigger=trigger,
        kind=kind,
        target_id=target_id,
        skill=_str(raw.get("skill")),
        mode=_str(raw.get("mode")),
    )


def _split_trigger(trigger: str) -> tuple[str, str]:
    """Split a ``"<kind>:<id>"`` trigger on the first ``:``. No colon -> ``("", "")``."""
    if ":" not in trigger:
        return "", ""
    kind, target_id = trigger.split(":", 1)
    return kind, target_id


def _str(value: Any) -> str:
    return value if isinstance(value, str) else ""


# ----------------------------------------------------------------------- validate


def validate(bindings: BindingSet) -> list[Issue]:
    """Return every shape issue (empty list == valid). Never raises for content.

    Shape-only and registry-free (Node 1.1): does not check that a ``stage:``/``command:``
    target actually exists — that cross-contract validation is ``doctor`` (Node 3.1).
    """
    issues: list[Issue] = []
    seen: set[str] = set()
    for binding in bindings.bindings:
        where = binding.trigger or "bindings"

        if not binding.skill:
            issues.append(Issue(Severity.ERROR, where, "missing `skill`"))
        if binding.mode not in MODES:
            issues.append(Issue(Severity.ERROR, where, f"`mode` must be one of {MODES}"))

        if not binding.trigger:
            issues.append(Issue(Severity.ERROR, "bindings", "a binding is missing its `trigger`"))
        elif ":" not in binding.trigger:
            issues.append(
                Issue(Severity.ERROR, where, "`trigger` must be of the form `<kind>:<id>`")
            )
        elif binding.kind not in TRIGGER_KINDS:
            issues.append(
                Issue(Severity.ERROR, where, f"`trigger` kind must be one of {TRIGGER_KINDS}")
            )
        elif not binding.target_id:
            issues.append(Issue(Severity.ERROR, where, "`trigger` has an empty `<id>`"))

        if binding.trigger:
            if binding.trigger in seen:
                issues.append(Issue(Severity.ERROR, where, "duplicate `trigger`"))
            seen.add(binding.trigger)

    return issues
