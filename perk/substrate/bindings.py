"""Load and validate the shared skill-binding set (`shared/bindings.yaml`).

This is the Python plane's reader of the *second* parsed cross-plane contract (the first
being `shared/registry.yaml`). It maps a `trigger` (`"<kind>:<id>"`) to a `skill` plus a
per-binding delivery `mode` (`nudge`/`transclude`). The TS extension has an independent
reader (`extension/substrate/bindings.ts`) over the *same* bundled file.

Validation is **shape-only and registry-free**: the validator checks that each binding's
fields are well formed (and that no trigger repeats), but it does NOT cross-check that a
`stage:` target is a real registry stage or that a `command:` target is a real command —
that target-existence validation is `doctor`'s job.

The shape + defaults are locked **and consumed**: the resolver (`resolve_bindings`,
`shipped-defaults ⊕ user-bindings`) and cold-door delivery (`perk/substrate/binding_delivery.py`)
are live.

The validator returns structured ``Issue`` records (it never raises for invalid *content*)
so callers decide how to surface them; ``BindingsError`` is reserved for structural load
failures. LBYL throughout (dignified-python): shapes are checked before use.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, model_validator

from perk._resources import shared_dir
from perk.boundary import StrictBoundaryModel, translate_validation_errors
from perk.substrate.registry import FindingSeverity, Issue

BINDINGS_FILENAME = "bindings.yaml"
SUPPORTED_SCHEMA_VERSION = 1

TRIGGER_KINDS: tuple[str, ...] = ("stage", "command")
MODES: tuple[str, ...] = ("nudge", "transclude")

# The `command:<id>` targets that perk's binding-delivery layer actually fires (D5).
# A `command:<id>` outside this set has no delivery surface, so the binding can never fire — the
# only deliverable command triggers are the Mechanism-B call sites (`bindingSuffix` in
# extension/factories/objectivePlan.ts + extension/doors/learnDocs.ts +
# extension/doors/prReview.ts) plus the cold `binding_trigger=` overrides in perk/cli/commands/:
# `command:learn-docs` (learn/docs_cmd.py), `command:skills-create` (skills/create_cmd.py), and
# `command:skills-refine` (skills/refine_cmd.py).
# Commands that ARE registry stages bind via `stage:<id>` (the kind-selection rule, §8.9) and are
# deliberately excluded here.
DELIVERABLE_COMMAND_TARGETS: frozenset[str] = frozenset(
    {
        "objective-reconcile",
        "objective-replan",
        "learn-docs",
        "pr-review",
        "skills-create",
        "skills-refine",
    }
)

# Where an installed skill body lives. The `skills` CLI delivers every `perk-*` skill into
# `.agents/skills/<name>/` in both self-repo and consumer trees (the Pi package no longer declares
# `pi.skills`, so Pi discovers them only through these symlinks). perk's own self-repo also keeps
# the skill bodies committed at `skills/<name>/`; doctor accepts that as a pre-sync fallback under
# `self_repo` (a best-effort safety net before `skills update --sync` has run).
SKILLS_DIR = Path(".agents/skills")
_SELF_REPO_SKILLS_DIR = Path("skills")
SKILL_FILENAME = "SKILL.md"


class Binding(StrictBoundaryModel):
    """One trigger->skill delivery binding.

    The model itself is the tolerant parser: a ``model_validator(mode="before")`` collapses
    any raw input down to exactly the three declared keys, each run through ``_str`` (absent
    or non-str -> ``""``). So a mistyped scalar is a sentinel-collapse, not a hard failure —
    every content finding still surfaces through ``validate()`` (the validator owns content).
    Unknown keys are dropped before ``extra="forbid"`` is reached.

    ``kind``/``target_id`` are read-only properties: the parsed halves of ``trigger`` (split
    on the first ``:``); a trigger with no ``:`` yields ``kind=""``, ``target_id=""`` so the
    validator can report it.
    """

    trigger: str
    skill: str
    mode: str

    @model_validator(mode="before")
    @classmethod
    def _tolerate(cls, raw: object) -> dict[str, str]:
        d: dict[Any, Any] = raw if isinstance(raw, dict) else {}
        return {key: _str(d.get(key)) for key in ("trigger", "skill", "mode")}

    @property
    def kind(self) -> str:
        return _split_trigger(self.trigger)[0]

    @property
    def target_id(self) -> str:
        return _split_trigger(self.trigger)[1]


class BindingSet(StrictBoundaryModel):
    schema_version: int
    bindings: list[Binding]
    raw: dict[str, Any] = Field(default_factory=dict, repr=False)


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

    with translate_validation_errors(BindingsError, source=str(bindings_path)):
        bindings = [Binding.model_validate(raw) for raw in _as_list(data.get("bindings"))]
        return BindingSet(schema_version=schema_version, bindings=bindings, raw=data)


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _split_trigger(trigger: str) -> tuple[str, str]:
    """Split a ``"<kind>:<id>"`` trigger on the first ``:``. No colon -> ``("", "")``."""
    if ":" not in trigger:
        return "", ""
    kind, target_id = trigger.split(":", 1)
    return kind, target_id


def _str(value: Any) -> str:
    return value if isinstance(value, str) else ""


# ----------------------------------------------------------------------- validate


def _binding_issues(binding: Binding) -> list[Issue]:
    """Return the shape issues for a *single* binding (skill/mode/trigger well-formedness).

    Shape-only and registry-free (§8.9): does not check that a ``stage:``/``command:``
    target actually exists — that cross-contract validation is ``doctor``.
    Duplicate-trigger detection is a *set*-level concern owned by the caller (``validate``
    over a committed set; ``resolve_bindings`` over the user overlay).
    """
    issues: list[Issue] = []
    where = binding.trigger or "bindings"

    if not binding.skill:
        issues.append(Issue(FindingSeverity.ERROR, where, "missing `skill`"))
    if binding.mode not in MODES:
        issues.append(Issue(FindingSeverity.ERROR, where, f"`mode` must be one of {MODES}"))

    if not binding.trigger:
        issues.append(
            Issue(FindingSeverity.ERROR, "bindings", "a binding is missing its `trigger`")
        )
    elif ":" not in binding.trigger:
        issues.append(
            Issue(FindingSeverity.ERROR, where, "`trigger` must be of the form `<kind>:<id>`")
        )
    elif binding.kind not in TRIGGER_KINDS:
        issues.append(
            Issue(FindingSeverity.ERROR, where, f"`trigger` kind must be one of {TRIGGER_KINDS}")
        )
    elif not binding.target_id:
        issues.append(Issue(FindingSeverity.ERROR, where, "`trigger` has an empty `<id>`"))

    return issues


def validate(bindings: BindingSet) -> list[Issue]:
    """Return every shape issue (empty list == valid). Never raises for content.

    Shape-only and registry-free: does not check that a ``stage:``/``command:``
    target actually exists — that cross-contract validation is ``doctor``.
    """
    issues: list[Issue] = []
    seen: set[str] = set()
    for binding in bindings.bindings:
        issues.extend(_binding_issues(binding))
        if binding.trigger:
            if binding.trigger in seen:
                issues.append(Issue(FindingSeverity.ERROR, binding.trigger, "duplicate `trigger`"))
            seen.add(binding.trigger)

    return issues


# ------------------------------------------------------------------------ resolve


@dataclass(frozen=True)
class ResolvedBindings:
    """The effective binding set after overlaying user bindings onto shipped defaults.

    ``bindings`` has **unique triggers by construction**; ``issues`` collects every dropped
    user binding's shape/duplicate finding for later loud-but-non-fatal surfacing.
    """

    bindings: list[Binding]
    issues: list[Issue]


def parse_user_bindings(raw: Any) -> list[Binding]:
    """Parse a ``.perk/config.toml`` ``[[bindings]]`` array-of-tables into ``Binding``s.

    Tolerant like ``Binding._tolerate``: absent/ill-typed fields become empty strings so the
    *resolver* reports them. A non-list ``raw`` (absent table) yields ``[]``.
    """
    return [Binding.model_validate(item) for item in _as_list(raw)]


def resolve_bindings(
    user_bindings: list[Binding], defaults: list[Binding] | None = None
) -> ResolvedBindings:
    """Overlay user bindings onto shipped defaults (trigger-keyed; pure).

    Defaults are trusted (not re-validated). Each user binding is applied iff it is
    shape-valid AND its trigger was not already applied by an earlier user binding;
    otherwise it is dropped and its issue recorded. An applied binding **replaces in place**
    the default with the same trigger, or **appends** at a new trigger — so the resolved set
    has unique triggers by construction. Target-existence stays ``doctor``.
    """
    if defaults is None:
        defaults = load_bindings().bindings
    resolved = list(defaults)
    index = {binding.trigger: i for i, binding in enumerate(resolved)}
    issues: list[Issue] = []
    applied: set[str] = set()
    for binding in user_bindings:
        binding_issues = _binding_issues(binding)
        if binding_issues:
            issues.extend(binding_issues)
            continue
        if binding.trigger in applied:
            issues.append(Issue(FindingSeverity.ERROR, binding.trigger, "duplicate `trigger`"))
            continue
        applied.add(binding.trigger)
        at = index.get(binding.trigger)
        if at is not None:
            resolved[at] = binding
        else:
            index[binding.trigger] = len(resolved)
            resolved.append(binding)
    return ResolvedBindings(bindings=resolved, issues=issues)


# ----------------------------------------------------------------- target-existence (doctor, 3.1)


def is_skill_installed(root: Path, skill: str, *, self_repo: bool = False) -> bool:
    """True iff ``skill``'s ``SKILL.md`` is installed under ``root`` (the delivery read path).

    Checks ``.agents/skills/<skill>/SKILL.md`` — byte-identical to the cold/warm delivery readers
    (``binding_delivery._read_skill_body`` / ``bindingDelivery.readSkillBody``). When ``self_repo``
    is set, also accepts perk's own committed ``skills/<skill>/SKILL.md`` layout as a pre-sync
    fallback (a best-effort safety net before the ``skills`` CLI has materialized
    ``.agents/skills/``). The self-repo fallback is doctor-only; injection always uses the default
    ``self_repo=False``.
    """
    if (root / SKILLS_DIR / skill / SKILL_FILENAME).is_file():
        return True
    return self_repo and (root / _SELF_REPO_SKILLS_DIR / skill / SKILL_FILENAME).is_file()
