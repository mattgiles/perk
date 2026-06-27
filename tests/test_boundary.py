"""Tests for `perk/boundary.py` — the strict/lenient base models, the `StrTuple`
coercion allowlist, and the `ValidationError` → error-domain translation helpers.

Throwaway model fixtures are defined locally; the module under test is pure schema
+ helpers (no I/O). Inputs are fed through `model_validate(...)` (which takes the
untyped dict/list shape YAML/JSON actually produces) so the boundary coercion —
not python kwargs typing — is what's exercised.
"""

import pytest
from pydantic import Field

from perk.boundary import (
    LenientApiModel,
    StrictBoundaryModel,
    StrTuple,
    ValidationError,
    format_validation_error,
    translate_validation_errors,
)


class _Strict(StrictBoundaryModel):
    n: int


class _StrictTuple(StrictBoundaryModel):
    items: tuple[str, ...]


class _StrTupleModel(StrictBoundaryModel):
    items: StrTuple


class _Lenient(LenientApiModel):
    n: int


class _Aliased(LenientApiModel):
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
