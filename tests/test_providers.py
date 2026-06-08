"""Providers loader + validator + resolver tests (Node 2.1 selection substrate).

The real bundled `providers.yaml` must load + validate; the validator must *reject* each class of
authoring error (zero/double default per seam, duplicate/empty id, bad seam). The resolver mirrors
`resolve_bindings`: absent key → default silently; unknown id / seam mismatch → default + one issue.
Negative fixtures use a GOOD constant + per-test single-line mutation (mirroring test_bindings.py).
"""

import pytest

from perk.providers import (
    Provider,
    ProvidersError,
    ProviderSet,
    Severity,
    load_providers,
    resolve_providers,
    validate,
)

# A minimal-but-complete, valid supported set. Each negative test mutates one line.
GOOD = """\
schema_version: 1
providers:
  - id: perk-plan
    seam: plan
    package: null
    adapter: null
    default: true
  - id: perk-checkpoints
    seam: todo
    package: null
    adapter: null
    default: true
"""


def _write(tmp_path, text):
    path = tmp_path / "providers.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _messages(tmp_path, text):
    issues = validate(load_providers(_write(tmp_path, text)))
    assert all(i.severity is Severity.ERROR for i in issues), issues
    return " | ".join(i.message for i in issues)


# --- load (real bundled file) ---------------------------------------------------------------


def test_real_providers_load_the_four_entries():
    providers = load_providers()
    by_id = providers.by_id()
    assert set(by_id) == {"perk-plan", "perk-checkpoints", "tombell-plan", "juicesharp-todo"}
    plan = by_id["perk-plan"]
    assert (plan.seam, plan.package, plan.adapter, plan.default) == ("plan", None, None, True)
    tombell = by_id["tombell-plan"]
    assert tombell.seam == "plan"
    assert tombell.package == "npm:@tombell/pi-plan"
    assert tombell.adapter == "planAdapterTombell"
    assert tombell.default is False
    # Node 2.3: the real entry drops `package_filter` (the illustrative `extensions/*.ts` matched
    # nothing — `@tombell/pi-plan`'s sole extension is root `index.ts`; omitting it loads all).
    assert tombell.package_filter is None


def test_real_providers_are_valid():
    assert validate(load_providers()) == []


def test_default_for_returns_the_seam_default():
    providers = load_providers()
    plan = providers.default_for("plan")
    todo = providers.default_for("todo")
    assert plan is not None and plan.id == "perk-plan"
    assert todo is not None and todo.id == "perk-checkpoints"


def test_unsupported_schema_version_raises(tmp_path):
    with pytest.raises(ProvidersError):
        load_providers(_write(tmp_path, "schema_version: 2\nproviders: []\n"))


def test_missing_file_raises(tmp_path):
    with pytest.raises(ProvidersError):
        load_providers(tmp_path / "nope.yaml")


# --- validate (negative fixtures) -----------------------------------------------------------


def test_zero_default_per_seam_is_an_error(tmp_path):
    text = GOOD.replace(
        "    default: true\n  - id: perk-checkpoints",
        "    default: false\n  - id: perk-checkpoints",
    )
    assert "seam `plan` must have exactly one" in _messages(tmp_path, text)


def test_double_default_per_seam_is_an_error(tmp_path):
    text = GOOD + (
        "  - id: perk-plan-2\n    seam: plan\n"
        "    package: null\n    adapter: null\n    default: true\n"
    )
    assert "seam `plan` must have exactly one" in _messages(tmp_path, text)


def test_duplicate_id_is_an_error(tmp_path):
    text = GOOD.replace(
        "  - id: perk-checkpoints\n    seam: todo", "  - id: perk-plan\n    seam: todo"
    )
    assert "duplicate `id`" in _messages(tmp_path, text)


def test_empty_id_is_an_error(tmp_path):
    text = GOOD.replace("  - id: perk-plan\n", "  - id: \n")
    assert "missing its `id`" in _messages(tmp_path, text)


def test_bad_seam_is_an_error(tmp_path):
    text = GOOD.replace("    seam: plan\n", "    seam: nope\n")
    assert "`seam` must be one of" in _messages(tmp_path, text)


# --- resolve --------------------------------------------------------------------------------


def _set():
    return load_providers()


def test_resolve_absent_keys_fall_back_to_defaults_silently():
    resolved = resolve_providers({}, _set())
    assert resolved.plan.id == "perk-plan"
    assert resolved.todo.id == "perk-checkpoints"
    assert resolved.issues == []


def test_resolve_valid_selection_picks_the_named_provider():
    resolved = resolve_providers({"plan": "tombell-plan"}, _set())
    assert resolved.plan.id == "tombell-plan"
    assert resolved.todo.id == "perk-checkpoints"  # absent todo → default
    assert resolved.issues == []


def test_resolve_unknown_id_falls_back_with_one_issue():
    resolved = resolve_providers({"plan": "ghost"}, _set())
    assert resolved.plan.id == "perk-plan"
    assert len(resolved.issues) == 1
    assert "unknown provider `ghost`" in resolved.issues[0].message


def test_resolve_seam_mismatch_falls_back_with_one_issue():
    # juicesharp-todo is a `todo` provider; selecting it for `plan` is a seam mismatch.
    resolved = resolve_providers({"plan": "juicesharp-todo"}, _set())
    assert resolved.plan.id == "perk-plan"
    assert len(resolved.issues) == 1
    assert "is a `todo` provider, not `plan`" in resolved.issues[0].message


def test_resolve_loads_bundled_set_when_omitted():
    resolved = resolve_providers({})
    assert isinstance(resolved.plan, Provider)
    assert resolved.plan.id == "perk-plan"


def test_provider_set_is_constructible_directly():
    # by_id / default_for over a hand-built set (no file).
    ps = ProviderSet(
        schema_version=1,
        providers=[Provider("a", "plan", None, None, True, None)],
        raw={},
    )
    plan = ps.default_for("plan")
    assert plan is not None and plan.id == "a"
    assert ps.default_for("todo") is None
