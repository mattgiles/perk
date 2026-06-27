"""The boundary-validation layer for perk's inputs and outputs.

Pydantic lives at the edges; the domain is frozen dataclasses. Three role-named
base classes name the three boundary roles:

- ``LenientParseModel`` — perk's stored files AND external API responses (GitHub /
  Linear), whose schemas grow additively. Tolerant: drop unknown keys, coerce
  ordinary scalars.
- ``StrictInputModel`` — machine-authored CLI batch inputs where a typo must fail
  loudly: unknown keys raise, no implicit scalar coercion.
- ``OutputModel`` — ``--json`` serialization snapshots, built from trusted internal
  domain values and dumped via ``model_dump(mode="json")``.

The canonical pattern: parse untrusted input through a ``LenientParseModel`` via
``model_validate(raw)``, convert the validated result into a
``@dataclass(frozen=True)`` domain object, then run a separate
``validate(domain) -> [findings]`` content pass (content problems are findings, not
parse raises). All three share one ``ValidationError`` → error-domain translation
seam so every consumer keeps surfacing its own domain error (RegistryError /
BindingsError / ProvidersError / GitHubError / IssueBackendError /
UserFacingCliError) rather than a raw pydantic error.

No I/O: this is pure schema + helpers, a leaf importing only ``pydantic`` and
stdlib ``contextlib``.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    ValidationError,
)

__all__ = [
    "LenientParseModel",
    "OutputModel",
    "StrTuple",
    "StrictBoundaryModel",
    "StrictInputModel",
    "ValidationError",
    "format_validation_error",
    "translate_validation_errors",
]


class LenientParseModel(BaseModel):
    """Base for tolerant parsing of perk's stored files AND external API responses.

    Covers perk's own stored YAML/JSON files and external API responses (GitHub /
    Linear) whose schemas grow additively. ``frozen`` → immutable;
    ``extra="ignore"`` → additive/unknown fields are silently dropped;
    ``strict=False`` → ordinary coercion for reliable JSON scalar shapes;
    ``populate_by_name`` → a model may be built from either a ``Field(alias=...)``
    or its python field name (foundation for camelCase response mapping).

    The canonical first step of the parse→dataclass→validate pattern: parse the
    untrusted dict via ``model_validate(raw)``, then convert into a frozen
    dataclass domain object.
    """

    model_config = ConfigDict(frozen=True, extra="ignore", strict=False, populate_by_name=True)


class StrictInputModel(BaseModel):
    """Base for machine-authored CLI batch inputs where a typo must fail loudly.

    ``frozen`` → immutable + hashable; ``extra="forbid"`` → unknown keys raise;
    ``strict`` → no implicit scalar coercion (``"5"``/``True``/``1.0`` are all
    rejected for an ``int`` field). Intentional coercions are opt-in only, via
    named annotated types like ``StrTuple``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class OutputModel(BaseModel):
    """Base for ``--json`` serialization snapshots, built from trusted domain values.

    Coercion is irrelevant — the fields are filled from trusted internal domain
    values, never untrusted input. ``extra="forbid"`` because perk authors the
    ``--json`` schema; ``frozen`` → an immutable snapshot. Serialized via
    ``model_dump(mode="json")``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class StrictBoundaryModel(BaseModel):
    """Legacy/transitional base — use the role-named bases instead.

    Config-identical to ``StrictInputModel`` (``frozen``, ``extra="forbid"``,
    ``strict``). Still backs the per-model domain shapes (registry / bindings /
    providers / plan / objective / cache / runner) during the Phase-1 migration
    onto the role-named bases (``LenientParseModel`` / ``StrictInputModel`` /
    ``OutputModel``); to be removed once every consumer has moved off it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


def _coerce_sequence_to_tuple(value: object) -> object:
    """Allowlisted list→tuple normalization (the ONLY implicit container coercion
    under strict). Non-sequences pass through unchanged so the strict tuple
    validator still rejects them (e.g. a bare ``str`` is NOT spread into
    characters)."""
    return tuple(value) if isinstance(value, list) else value


StrTuple = Annotated[tuple[str, ...], BeforeValidator(_coerce_sequence_to_tuple)]
"""The named coercion allowlist for list→tuple under strict mode.

A field typed ``tuple[str, ...]`` directly stays fully strict (rejects a list); a
field typed ``StrTuple`` accepts a list and normalizes to a tuple while still
strictly validating each element as ``str`` (the ``BeforeValidator`` runs before
the strict per-element check). Serves ``consumed_learn`` / ``labels`` (plan
models) and ``depends_on`` (objective models)."""


def format_validation_error(exc: ValidationError, *, source: str | None = None) -> str:
    """Render a ``ValidationError`` as one compact, deterministic message.

    Each error becomes ``"<loc>: <msg>"`` (``loc`` dotted, ``"<root>"`` when
    empty), joined by ``"; "``, optionally prefixed ``"source: "``. Field order is
    preserved (pydantic reports in field order).
    """
    parts = [
        (".".join(str(p) for p in err["loc"]) or "<root>") + ": " + err["msg"]
        for err in exc.errors()
    ]
    message = "; ".join(parts)
    return f"{source}: {message}" if source is not None else message


@contextmanager
def translate_validation_errors(
    error_cls: type[Exception], *, source: str | None = None
) -> Iterator[None]:
    """Bridge ``ValidationError`` into a target domain error.

    Run a validation block; on ``ValidationError`` raise
    ``error_cls(format_validation_error(...))`` chained ``from`` the original.
    The target error class is a parameter (decoupled from any specific domain), so
    the same helper routes RegistryError / BindingsError / ProvidersError /
    GitHubError / IssueBackendError and ``click.ClickException`` subclasses alike.
    """
    try:
        yield
    except ValidationError as exc:
        raise error_cls(format_validation_error(exc, source=source)) from exc
