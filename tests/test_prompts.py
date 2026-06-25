from collections.abc import Mapping
from typing import cast

import jinja2
import pytest
import yaml

from perk._resources import prompts_dir
from perk.prompts import render


def _load_cases() -> list[dict[str, object]]:
    cases_path = prompts_dir() / "_fixtures" / "cases.yaml"
    return yaml.safe_load(cases_path.read_text())


_CASES = _load_cases()


@pytest.mark.parametrize("case", _CASES, ids=[str(c["template"]) for c in _CASES])
def test_golden_parity(case: dict[str, object]) -> None:
    raw_vars = case["vars"]
    assert isinstance(raw_vars, dict)
    variables = cast(Mapping[str, object], raw_vars)
    golden = (prompts_dir() / str(case["golden"])).read_text()
    assert render(str(case["template"]), variables) == golden


def test_strict_undefined_raises() -> None:
    # hello.md requires `name`; rendering it with no vars must fail loudly.
    with pytest.raises(jinja2.UndefinedError):
        render("_fixtures/templates/hello.md", {})


@pytest.mark.parametrize("bad", [True, 42, None, ["x"], {"k": "v"}])
def test_string_only_contract_rejects_non_string_vars(bad: object) -> None:
    # The render contract is string-only (contracts.md §8.31), enforced on both planes. A
    # non-string var value must raise rather than silently coerce via str(value).
    with pytest.raises(TypeError, match="string-only"):
        render("_fixtures/templates/hello.md", {"name": bad})
