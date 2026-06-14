"""Providers loader + validator + resolver tests (Node 2.1 selection substrate).

The real bundled `providers.yaml` must load + validate; the validator must *reject* each class of
authoring error (zero/double default per seam, duplicate/empty id, bad seam). The resolver mirrors
`resolve_bindings`: absent key → default silently; unknown id / seam mismatch → default + one issue.
Negative fixtures use a GOOD constant + per-test single-line mutation (mirroring test_bindings.py).
"""

import pytest

from perk.substrate.providers import (
    SEAMS,
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
  - id: perk-ask-user
    seam: askuser
    package: null
    adapter: null
    default: true
  - id: perk-footer
    seam: footer
    package: null
    adapter: null
    default: true
  - id: pi-web-access
    seam: web
    package: "npm:pi-web-access"
    adapter: null
    default: true
"""


def test_seams_tuple_includes_askuser_footer_and_web():
    assert SEAMS == ("plan", "todo", "askuser", "footer", "web")


def _write(tmp_path, text):
    path = tmp_path / "providers.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _messages(tmp_path, text):
    issues = validate(load_providers(_write(tmp_path, text)))
    assert all(i.severity is Severity.ERROR for i in issues), issues
    return " | ".join(i.message for i in issues)


# --- load (real bundled file) ---------------------------------------------------------------


def test_real_providers_load_the_entries():
    providers = load_providers()
    by_id = providers.by_id()
    assert set(by_id) == {
        "perk-plan",
        "perk-checkpoints",
        "perk-ask-user",
        "perk-footer",
        "tombell-plan",
        "plannotator-plan",
        "juicesharp-todo",
        "juicesharp-ask-user",
        "powerline-footer",
        "pi-bar-footer",
        "pi-web-access",
        "ollama-web-search",
        "juicesharp-web-tools",
    }
    # web DEFAULT reference: the FOREIGN `pi-web-access` (the novelty — a non-null-package default).
    web = by_id["pi-web-access"]
    assert web.seam == "web"
    assert web.package == "npm:pi-web-access"
    assert web.adapter is None
    assert web.default is True
    assert web.package_filter is None
    # ollama-web-search / juicesharp-web-tools: VACATE-ONLY interface seam (null adapter).
    ollama = by_id["ollama-web-search"]
    assert ollama.seam == "web"
    assert ollama.package == "npm:@ollama/pi-web-search"
    assert ollama.adapter is None
    assert ollama.default is False
    assert ollama.package_filter is None
    rpiv_web = by_id["juicesharp-web-tools"]
    assert rpiv_web.seam == "web"
    assert rpiv_web.package == "npm:@juicesharp/rpiv-web-tools"
    assert rpiv_web.adapter is None
    assert rpiv_web.default is False
    assert rpiv_web.package_filter is None
    # footer reference: perk's own footer (behavior-preserving default, no package/adapter).
    foot = by_id["perk-footer"]
    assert (foot.seam, foot.package, foot.adapter, foot.default) == ("footer", None, None, True)
    # powerline-footer / pi-bar-footer: VACATE-ONLY interface seam (adapter null, no filter).
    powerline = by_id["powerline-footer"]
    assert powerline.seam == "footer"
    assert powerline.package == "npm:pi-powerline-footer"
    assert powerline.adapter is None
    assert powerline.default is False
    assert powerline.package_filter is None
    pi_bar = by_id["pi-bar-footer"]
    assert pi_bar.seam == "footer"
    assert pi_bar.package == "npm:pi-bar"
    assert pi_bar.adapter is None
    assert pi_bar.default is False
    assert pi_bar.package_filter is None
    # askuser reference: perk's own tool (behavior-preserving default, no package/adapter).
    ask = by_id["perk-ask-user"]
    assert (ask.seam, ask.package, ask.adapter, ask.default) == ("askuser", None, None, True)
    # juicesharp-ask-user: VACATE-ONLY interface seam (adapter null, no package_filter).
    juice_ask = by_id["juicesharp-ask-user"]
    assert juice_ask.seam == "askuser"
    assert juice_ask.package == "npm:@juicesharp/rpiv-ask-user-question"
    assert juice_ask.adapter is None
    assert juice_ask.default is False
    assert juice_ask.package_filter is None
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
    # plannotator-plan: a REAL plan provider with the AUGMENT posture (planAdapterPlannotator
    # bridges its browser review via the plan_review tool; perk's plan surface + gate stay).
    plannotator = by_id["plannotator-plan"]
    assert plannotator.seam == "plan"
    assert plannotator.package == "npm:@plannotator/pi-extension"
    assert plannotator.adapter == "planAdapterPlannotator"
    assert plannotator.default is False
    # No `package_filter` (`pi.extensions: ["./"]` — the sole extension is the package root).
    assert plannotator.package_filter is None
    # Node 3.2: `juicesharp-todo` is now a REAL todo provider (todoAdapterJuicesharp bridges it).
    juicesharp = by_id["juicesharp-todo"]
    assert juicesharp.seam == "todo"
    assert juicesharp.package == "npm:@juicesharp/rpiv-todo"
    assert juicesharp.adapter == "todoAdapterJuicesharp"
    assert juicesharp.default is False
    # No `package_filter` (single-concern checklist overlay) — mirrors the tombell case.
    assert juicesharp.package_filter is None


def test_real_providers_are_valid():
    assert validate(load_providers()) == []


def test_default_for_returns_the_seam_default():
    providers = load_providers()
    plan = providers.default_for("plan")
    todo = providers.default_for("todo")
    askuser = providers.default_for("askuser")
    footer = providers.default_for("footer")
    web = providers.default_for("web")
    assert plan is not None and plan.id == "perk-plan"
    assert todo is not None and todo.id == "perk-checkpoints"
    assert askuser is not None and askuser.id == "perk-ask-user"
    assert footer is not None and footer.id == "perk-footer"
    assert web is not None and web.id == "pi-web-access"


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
    assert resolved.askuser.id == "perk-ask-user"
    assert resolved.footer.id == "perk-footer"
    assert resolved.web.id == "pi-web-access"
    assert resolved.issues == []


def test_resolve_web_selection():
    # default → pi-web-access silently; foreign selected → resolves; wrong-seam → fallback + issue.
    assert resolve_providers({"web": "ollama-web-search"}, _set()).web.id == "ollama-web-search"
    assert resolve_providers({"web": "juicesharp-web-tools"}, _set()).web.id == (
        "juicesharp-web-tools"
    )
    mismatch = resolve_providers({"web": "perk-plan"}, _set())
    assert mismatch.web.id == "pi-web-access"
    assert len(mismatch.issues) == 1
    assert "is a `plan` provider, not `web`" in mismatch.issues[0].message
    unknown = resolve_providers({"web": "ghost"}, _set())
    assert unknown.web.id == "pi-web-access"
    assert len(unknown.issues) == 1


def test_resolve_footer_selection():
    # default → perk-footer silently; foreign selected → resolves; wrong-seam → fallback + issue.
    assert resolve_providers({"footer": "pi-bar-footer"}, _set()).footer.id == "pi-bar-footer"
    assert resolve_providers({"footer": "powerline-footer"}, _set()).footer.id == (
        "powerline-footer"
    )
    mismatch = resolve_providers({"footer": "perk-plan"}, _set())
    assert mismatch.footer.id == "perk-footer"
    assert len(mismatch.issues) == 1
    assert "is a `plan` provider, not `footer`" in mismatch.issues[0].message
    unknown = resolve_providers({"footer": "ghost"}, _set())
    assert unknown.footer.id == "perk-footer"
    assert len(unknown.issues) == 1


def test_resolve_askuser_selection():
    # default → perk-ask-user silently; foreign selected → resolves; wrong-seam → fallback + issue.
    assert resolve_providers({"askuser": "juicesharp-ask-user"}, _set()).askuser.id == (
        "juicesharp-ask-user"
    )
    mismatch = resolve_providers({"askuser": "perk-plan"}, _set())
    assert mismatch.askuser.id == "perk-ask-user"
    assert len(mismatch.issues) == 1
    assert "is a `plan` provider, not `askuser`" in mismatch.issues[0].message
    unknown = resolve_providers({"askuser": "ghost"}, _set())
    assert unknown.askuser.id == "perk-ask-user"
    assert len(unknown.issues) == 1


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
