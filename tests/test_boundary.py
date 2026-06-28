"""Tests for `perk/boundary.py` — the strict/lenient base models, the `StrTuple`
coercion allowlist, and the `ValidationError` → error-domain translation helpers.

Throwaway model fixtures are defined locally; the module under test is pure schema
+ helpers (no I/O). Inputs are fed through `model_validate(...)` (which takes the
untyped dict/list shape YAML/JSON actually produces) so the boundary coercion —
not python kwargs typing — is what's exercised.
"""

from dataclasses import FrozenInstanceError, dataclass

import pytest
from pydantic import Field

from perk.boundary import (
    LenientParseModel,
    OutputModel,
    StrictInputModel,
    StrTuple,
    ValidationError,
    format_validation_error,
    translate_validation_errors,
)


class _Strict(StrictInputModel):
    n: int


class _StrictTuple(StrictInputModel):
    items: tuple[str, ...]


class _StrTupleModel(StrictInputModel):
    items: StrTuple


class _Lenient(LenientParseModel):
    n: int


class _Aliased(LenientParseModel):
    field_name: str = Field(alias="camelCase")


def test_frozen_strict() -> None:
    model = _Strict.model_validate({"n": 5})
    with pytest.raises(ValidationError):
        model.n = 6


def test_frozen_lenient() -> None:
    model = _Lenient.model_validate({"n": 5})
    with pytest.raises(ValidationError):
        model.n = 6


def test_strict_forbids_extra() -> None:
    with pytest.raises(ValidationError):
        _Strict.model_validate({"n": 5, "unknown": "x"})


def test_lenient_ignores_extra() -> None:
    model = _Lenient.model_validate({"n": 5, "unknown": "x"})
    assert not hasattr(model, "unknown")


def test_strict_rejects_string_scalar() -> None:
    with pytest.raises(ValidationError):
        _Strict.model_validate({"n": "5"})


def test_strict_rejects_bool_as_int() -> None:
    with pytest.raises(ValidationError):
        _Strict.model_validate({"n": True})


def test_strict_accepts_int() -> None:
    assert _Strict.model_validate({"n": 5}).n == 5


def test_strict_tuple_rejects_list() -> None:
    # A field typed `tuple[str, ...]` directly stays fully strict: a list is rejected,
    # proving the list→tuple coercion is opt-in (only via StrTuple).
    with pytest.raises(ValidationError):
        _StrictTuple.model_validate({"items": ["a", "b"]})


def test_lenient_coerces_string_scalar() -> None:
    assert _Lenient.model_validate({"n": "5"}).n == 5


def test_strtuple_coerces_list() -> None:
    model = _StrTupleModel.model_validate({"items": ["a", "b"]})
    assert model.items == ("a", "b")
    assert isinstance(model.items, tuple)


def test_strtuple_accepts_tuple() -> None:
    model = _StrTupleModel.model_validate({"items": ("a", "b")})
    assert model.items == ("a", "b")


def test_strtuple_rejects_non_str_element() -> None:
    with pytest.raises(ValidationError):
        _StrTupleModel.model_validate({"items": [1]})


def test_strtuple_rejects_bare_str() -> None:
    # A bare str must not be spread into characters.
    with pytest.raises(ValidationError):
        _StrTupleModel.model_validate({"items": "ab"})


def test_populate_by_name() -> None:
    from_alias = _Aliased.model_validate({"camelCase": "x"})
    from_name = _Aliased.model_validate({"field_name": "x"})
    assert from_alias.field_name == "x"
    assert from_name.field_name == "x"


def test_format_validation_error_field_path() -> None:
    try:
        _Strict.model_validate({"n": "5"})
    except ValidationError as exc:
        message = format_validation_error(exc)
    assert "n:" in message


def test_format_validation_error_source_prefix() -> None:
    try:
        _Strict.model_validate({"n": "5"})
    except ValidationError as exc:
        message = format_validation_error(exc, source="registry")
    assert message.startswith("registry: ")


def test_translate_validation_errors_reraises() -> None:
    class _Boom(Exception):
        pass

    with (
        pytest.raises(_Boom) as caught,
        translate_validation_errors(_Boom, source="registry"),
    ):
        _Strict.model_validate({"n": "5"})
    assert isinstance(caught.value.__cause__, ValidationError)
    assert str(caught.value).startswith("registry: ")


def test_translate_validation_errors_clean_block() -> None:
    class _Boom(Exception):
        pass

    with translate_validation_errors(_Boom):
        _Strict.model_validate({"n": 5})


# --- OutputModel: trusted snapshot serialized via model_dump(mode="json") ---


class _Output(OutputModel):
    name: str
    count: int


def test_output_frozen() -> None:
    model = _Output.model_validate({"name": "x", "count": 1})
    with pytest.raises(ValidationError):
        model.count = 2


def test_output_forbids_extra() -> None:
    with pytest.raises(ValidationError):
        _Output.model_validate({"name": "x", "count": 1, "unknown": "y"})


def test_output_dump_json_round_trips() -> None:
    model = _Output.model_validate({"name": "x", "count": 1})
    assert model.model_dump(mode="json") == {"name": "x", "count": 1}


# --- Canonical pattern reference: lenient parse → frozen dataclass → validate ---
#
# Executable documentation of perk's boundary discipline. A messy external dict is
# parsed leniently (coercion + unknown-key drop), converted into a frozen dataclass
# domain object, then run through a separate content-finding pass. Content problems
# surface as returned findings — never as a parse-time raise.


class _RawTask(LenientParseModel):
    """The parse model: tolerant of the messy shape the boundary actually sees."""

    title: str
    priority: int


@dataclass(frozen=True)
class _Task:
    """The domain object: a frozen dataclass, immutable past construction."""

    title: str
    priority: int


def _to_task(raw: _RawTask) -> _Task:
    """Explicit conversion from the validated parse model to the domain object."""
    return _Task(title=raw.title, priority=raw.priority)


def _validate_task(task: _Task) -> list[str]:
    """The content pass: returns findings, never raises."""
    findings: list[str] = []
    if not task.title.strip():
        findings.append("title is empty")
    if task.priority < 0:
        findings.append("priority is negative")
    return findings


def test_canonical_pattern_lenient_parse_tolerates_messy_input() -> None:
    # "3" coerces to int; the unknown "legacy_field" is dropped — neither raises.
    raw = _RawTask.model_validate({"title": "ship it", "priority": "3", "legacy_field": "ignored"})
    assert raw.priority == 3
    assert not hasattr(raw, "legacy_field")


def test_canonical_pattern_domain_object_is_frozen() -> None:
    raw = _RawTask.model_validate({"title": "ship it", "priority": 3})
    task = _to_task(raw)
    with pytest.raises(FrozenInstanceError):
        task.priority = 4  # ty: ignore[invalid-assignment]


def test_canonical_pattern_content_findings_surface_via_validate() -> None:
    # A structurally-valid but content-poor task parses clean and converts clean;
    # the problems surface only as findings from the content pass.
    raw = _RawTask.model_validate({"title": "  ", "priority": -1})
    task = _to_task(raw)
    assert _validate_task(task) == ["title is empty", "priority is negative"]


def test_canonical_pattern_clean_task_has_no_findings() -> None:
    raw = _RawTask.model_validate({"title": "ship it", "priority": 3})
    assert _validate_task(_to_task(raw)) == []
