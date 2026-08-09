"""Load and validate the session-audit expectation catalog (``expectations.yaml``).

The catalog is a versioned, machine-enumerable committed YAML of behavioral
expectations: "in a session where stage/door X ran, we expect evidence Y; a violation
looks like Z". Each entry names an intent surface with a durable repo pointer,
selects applicable sessions via the shared trigger vocabulary (``"<kind>:<id>"``,
the same grammar as ``shared/bindings.yaml``), and carries a ``vintage_floor``
(the earliest perk version the expectation applies to).

Mirrors ``perk/substrate/bindings.py`` symbol-for-symbol: a lenient parse model
(``ExpectationEntry``/``ExpectationsFile``) → explicit ``to_domain()`` → frozen
dataclasses (``Expectation``/``ExpectationCatalog``). ``ExpectationsError`` is
reserved for *structural* load failures (missing file, top level not a mapping,
unsupported ``schema_version``, genuine type errors); content problems are
``Issue`` findings from ``validate()``, which never raises.

``validate`` is shape-only and pure (no I/O, no registry cross-check):
target-existence (``stage:`` ids) and source-path-existence checks live in the
committed-catalog self-check tests.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import Field

from perk.boundary import LenientParseModel, translate_validation_errors
from perk.substrate.registry import FindingSeverity, Issue

EXPECTATIONS_FILENAME = "expectations.yaml"
SUPPORTED_SCHEMA_VERSION = 1

# The objective's four expectation kinds: tool/door usage mechanics, prompt/instruction
# adherence, workflow-shape integrity, skill-binding delivery & uptake.
KINDS: tuple[str, ...] = ("tool-mechanics", "prompt-adherence", "workflow-shape", "skill-uptake")
TIERS: tuple[str, ...] = ("deterministic", "judgment")
ENFORCEMENT_CLASSES: tuple[str, ...] = ("prose-only", "structural")
# The shared trigger vocabulary (`"<kind>:<id>"`) — one selector grammar across the repo,
# matching `shared/bindings.yaml`'s TRIGGER_KINDS.
APPLIES_TO_KINDS: tuple[str, ...] = ("stage", "command")

# Stable slug ids: lowercase alnum runs joined by single dots or hyphens.
ID_PATTERN = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")
# A perk version, never a date (release history maps versions to dates downstream).
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")

# A `source` pointer is "<path>" or "<path> §<anchor>" — split on the first " §".
SOURCE_ANCHOR_SEPARATOR = " §"


class ExpectationEntry(LenientParseModel):
    """Tolerant parse shape for one stored catalog entry.

    Lenient base: unknown keys dropped (``extra="ignore"``); absent keys default
    (``""`` / ``[]``) so ``validate()`` reports them as content findings. A present
    bad-typed scalar is a genuine type error and raises (translated to
    ``ExpectationsError`` at the load boundary).
    """

    id: str = ""
    kind: str = ""
    surface: str = ""
    source: str = ""
    applies_to: list[str] = Field(default_factory=list)
    vintage_floor: str = ""
    evidence: str = ""
    violation: str = ""
    tier: str = ""
    enforcement: str = ""

    def to_domain(self) -> "Expectation":
        """Explicit field-for-field conversion into the frozen domain object."""
        return Expectation(
            id=self.id,
            kind=self.kind,
            surface=self.surface,
            source=self.source,
            applies_to=tuple(self.applies_to),
            vintage_floor=self.vintage_floor,
            evidence=self.evidence,
            violation=self.violation,
            tier=self.tier,
            enforcement=self.enforcement,
        )


class ExpectationsFile(LenientParseModel):
    """Whole-file parse shape.

    ``schema_version`` stays OUT of the model (the structural pre-check in
    ``load_catalog`` owns it; ``extra="ignore"`` drops the key here). A non-list
    ``expectations:`` raises.
    """

    expectations: list[ExpectationEntry] = Field(default_factory=list)

    def to_domain(self, schema_version: int) -> "ExpectationCatalog":
        """Convert the whole validated file into the frozen catalog domain object."""
        return ExpectationCatalog(
            schema_version=schema_version,
            expectations=tuple(e.to_domain() for e in self.expectations),
        )


@dataclass(frozen=True)
class Expectation:
    """One behavioral expectation (frozen domain object)."""

    id: str
    kind: str
    surface: str
    source: str
    applies_to: tuple[str, ...]
    vintage_floor: str
    evidence: str
    violation: str
    tier: str
    enforcement: str


@dataclass(frozen=True)
class ExpectationCatalog:
    schema_version: int
    expectations: tuple[Expectation, ...]


class ExpectationsError(Exception):
    """The catalog file is missing or not parseable as the expected top-level shape.

    Distinct from validation *issues*: this means we could not load a catalog at all
    (vs. loading one that fails consistency checks). Mirrors ``BindingsError``.
    """


# --------------------------------------------------------------------------- load


def load_catalog(path: Path | None = None) -> ExpectationCatalog:
    """Parse the committed catalog beside this module (or an explicit path).

    perk-dev is dev-only and always editable-installed, so the default path is a
    plain sibling lookup (no ``_resources``-style dual-mode resolution needed).
    Raises ``ExpectationsError`` only for *structural* failures — content
    consistency is the validator's job.
    """
    catalog_path = path or Path(__file__).with_name(EXPECTATIONS_FILENAME)
    if not catalog_path.is_file():
        raise ExpectationsError(f"expectation catalog not found at {catalog_path}")

    data = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ExpectationsError(f"{catalog_path}: top level must be a mapping")

    schema_version = data.get("schema_version")
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        raise ExpectationsError(
            f"{catalog_path}: unsupported schema_version {schema_version!r} "
            f"(this perk-dev understands {SUPPORTED_SCHEMA_VERSION})."
        )

    with translate_validation_errors(ExpectationsError, source=str(catalog_path)):
        parsed = ExpectationsFile.model_validate(data)
    return parsed.to_domain(schema_version)


def source_path_part(source: str) -> str:
    """The path half of a ``source`` pointer (before an optional ``" §<anchor>"`` suffix)."""
    return source.split(SOURCE_ANCHOR_SEPARATOR, 1)[0]


# ----------------------------------------------------------------------- validate


def _id_issues(entry: Expectation) -> list[Issue]:
    if not entry.id:
        return [Issue(FindingSeverity.ERROR, "expectations", "an expectation is missing its `id`")]
    if not ID_PATTERN.fullmatch(entry.id):
        return [
            Issue(
                FindingSeverity.ERROR,
                entry.id,
                "`id` must be a lowercase dot/kebab slug "
                "(lowercase alnum runs joined by `.` or `-`)",
            )
        ]
    return []


def _source_issues(entry: Expectation, where: str) -> list[Issue]:
    if not entry.source:
        return [Issue(FindingSeverity.ERROR, where, "missing `source`")]
    issues: list[Issue] = []
    path_part = source_path_part(entry.source)
    if not path_part:
        issues.append(Issue(FindingSeverity.ERROR, where, "`source` has an empty path part"))
    else:
        if path_part.startswith("/"):
            issues.append(
                Issue(
                    FindingSeverity.ERROR,
                    where,
                    "`source` path must be repo-relative (not absolute)",
                )
            )
        if "\\" in path_part:
            issues.append(
                Issue(FindingSeverity.ERROR, where, "`source` path must not contain backslashes")
            )
    return issues


def _applies_to_issues(entry: Expectation, where: str) -> list[Issue]:
    if not entry.applies_to:
        return [Issue(FindingSeverity.ERROR, where, "`applies_to` must list at least one trigger")]
    issues: list[Issue] = []
    seen: set[str] = set()
    for trigger in entry.applies_to:
        if ":" not in trigger:
            issues.append(
                Issue(
                    FindingSeverity.ERROR,
                    where,
                    f"`applies_to` trigger {trigger!r} must be of the form `<kind>:<id>`",
                )
            )
        else:
            kind, target_id = trigger.split(":", 1)
            if kind not in APPLIES_TO_KINDS:
                issues.append(
                    Issue(
                        FindingSeverity.ERROR,
                        where,
                        f"`applies_to` trigger {trigger!r} kind must be one of {APPLIES_TO_KINDS}",
                    )
                )
            elif not target_id:
                issues.append(
                    Issue(
                        FindingSeverity.ERROR,
                        where,
                        f"`applies_to` trigger {trigger!r} has an empty `<id>`",
                    )
                )
        if trigger in seen:
            issues.append(
                Issue(FindingSeverity.ERROR, where, f"duplicate `applies_to` trigger {trigger!r}")
            )
        seen.add(trigger)
    return issues


def _entry_issues(entry: Expectation) -> list[Issue]:
    """Return the shape issues for a *single* expectation.

    Shape-only and registry-free: does not check that a ``stage:`` target is a real
    registry stage or that the ``source`` path exists — those cross-checks live in
    the committed-catalog self-check tests. Duplicate-``id`` detection is a
    *set*-level concern owned by ``validate``.
    """
    where = entry.id or "expectations"
    issues = _id_issues(entry)

    if entry.kind not in KINDS:
        issues.append(Issue(FindingSeverity.ERROR, where, f"`kind` must be one of {KINDS}"))
    if not entry.surface:
        issues.append(Issue(FindingSeverity.ERROR, where, "missing `surface`"))

    issues.extend(_source_issues(entry, where))
    issues.extend(_applies_to_issues(entry, where))

    if not entry.vintage_floor:
        issues.append(Issue(FindingSeverity.ERROR, where, "missing `vintage_floor`"))
    elif not VERSION_PATTERN.fullmatch(entry.vintage_floor):
        issues.append(
            Issue(
                FindingSeverity.ERROR,
                where,
                f"`vintage_floor` must be an `X.Y.Z` perk version, got {entry.vintage_floor!r}",
            )
        )

    if not entry.evidence:
        issues.append(Issue(FindingSeverity.ERROR, where, "missing `evidence`"))
    if not entry.violation:
        issues.append(Issue(FindingSeverity.ERROR, where, "missing `violation`"))

    if entry.tier not in TIERS:
        issues.append(Issue(FindingSeverity.ERROR, where, f"`tier` must be one of {TIERS}"))
    if entry.enforcement not in ENFORCEMENT_CLASSES:
        issues.append(
            Issue(
                FindingSeverity.ERROR,
                where,
                f"`enforcement` must be one of {ENFORCEMENT_CLASSES}",
            )
        )

    return issues


def validate(catalog: ExpectationCatalog) -> list[Issue]:
    """Return every shape issue (empty list == valid). Never raises for content.

    Shape-only and pure (no I/O, no registry cross-check) — target-existence and
    source-path-existence live in the self-check tests.
    """
    issues: list[Issue] = []
    seen: set[str] = set()
    for entry in catalog.expectations:
        issues.extend(_entry_issues(entry))
        if entry.id:
            if entry.id in seen:
                issues.append(Issue(FindingSeverity.ERROR, entry.id, "duplicate `id`"))
            seen.add(entry.id)
    return issues
