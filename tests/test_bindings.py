"""Bindings loader + validator tests (the thin seam).

The real bundled bindings must validate; the validator must *reject* each class of
authoring error. Negative fixtures (a GOOD constant + per-test single-line mutation,
mirroring test_registry.py) exercise the shape checks. A test also asserts the shipped
`stage:` triggers are real registry stages, to catch a typo in the shipped file — while
the loader itself stays registry-free (target-existence is doctor's job).
"""

from dataclasses import FrozenInstanceError

import pytest

from perk.substrate.bindings import (
    DELIVERABLE_COMMAND_TARGETS,
    Binding,
    BindingsError,
    FindingSeverity,
    is_skill_installed,
    load_bindings,
    parse_user_bindings,
    resolve_bindings,
    validate,
)
from perk.substrate.registry import load_registry

# A minimal-but-complete, valid binding set. Each negative test mutates one line.
GOOD = """\
schema_version: 1
bindings:
  - trigger: "stage:plan"
    skill: perk-plan
    mode: nudge
  - trigger: "command:learn-docs"
    skill: perk-learn-docs
    mode: nudge
"""

EXPECTED_DEFAULTS = [
    ("stage:plan", "perk-plan", "nudge"),
    ("stage:gist-author", "perk-gist-author", "nudge"),
    ("stage:objective-author", "perk-objective-author", "nudge"),
    ("stage:objective-plan", "perk-objective-plan", "nudge"),
    ("stage:implement", "perk-implement", "nudge"),
    ("stage:address", "perk-address", "nudge"),
    ("stage:learn", "perk-learn", "nudge"),
    ("command:objective-reconcile", "perk-objective-reconcile", "nudge"),
    ("command:objective-replan", "perk-objective-replan", "nudge"),
    ("command:learn-docs", "perk-learn-docs", "nudge"),
    ("command:learn-code", "perk-learn-code", "nudge"),
    ("command:pr-review", "perk-pr-review", "nudge"),
    ("command:pr-review-terminal", "perk-pr-review-terminal", "nudge"),
    ("command:pr-review-browser", "perk-pr-review-browser", "nudge"),
    ("command:skills-create", "perk-skill-author", "nudge"),
    ("command:skills-refine", "perk-skill-author", "nudge"),
]


def _write(tmp_path, text):
    path = tmp_path / "bindings.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _messages(tmp_path, text):
    issues = validate(load_bindings(_write(tmp_path, text)))
    assert all(i.severity is FindingSeverity.ERROR for i in issues), issues
    return " | ".join(i.message for i in issues)


def test_real_bindings_are_valid():
    # The bundled shared/bindings.yaml: parses and has zero issues.
    assert validate(load_bindings()) == []


def test_default_bindings_match_shipped_set():
    bindings = load_bindings().bindings
    assert [(b.trigger, b.skill, b.mode) for b in bindings] == EXPECTED_DEFAULTS


def test_default_stage_triggers_are_real_stages():
    stage_ids = load_registry().stage_ids()
    for binding in load_bindings().bindings:
        if binding.kind == "stage":
            assert binding.target_id in stage_ids, binding.trigger


def test_good_fixture_is_valid(tmp_path):
    assert validate(load_bindings(_write(tmp_path, GOOD))) == []


def test_rejects_bad_mode(tmp_path):
    bad = GOOD.replace(
        "    skill: perk-plan\n    mode: nudge", "    skill: perk-plan\n    mode: shout"
    )
    assert "mode" in _messages(tmp_path, bad)


def test_rejects_empty_skill(tmp_path):
    bad = GOOD.replace("    skill: perk-plan\n", '    skill: ""\n')
    assert "skill" in _messages(tmp_path, bad)


def test_rejects_malformed_trigger_no_colon(tmp_path):
    bad = GOOD.replace('trigger: "stage:plan"', 'trigger: "stageplan"')
    assert "<kind>:<id>" in _messages(tmp_path, bad)


def test_rejects_unknown_kind(tmp_path):
    bad = GOOD.replace('trigger: "stage:plan"', 'trigger: "phase:plan"')
    assert "kind" in _messages(tmp_path, bad)


def test_rejects_empty_target_id(tmp_path):
    bad = GOOD.replace('trigger: "stage:plan"', 'trigger: "stage:"')
    assert "empty" in _messages(tmp_path, bad)


def test_rejects_duplicate_trigger(tmp_path):
    bad = GOOD.replace('trigger: "command:learn-docs"', 'trigger: "stage:plan"')
    assert "duplicate" in _messages(tmp_path, bad)


def test_unsupported_schema_version_raises(tmp_path):
    bad = GOOD.replace("schema_version: 1", "schema_version: 99")
    with pytest.raises(BindingsError):
        load_bindings(_write(tmp_path, bad))


# --------------------------------------------------------------------- malformed input (model)


def test_non_string_scalar_in_stored_file_raises(tmp_path):
    # A non-string scalar in the stored file is a genuine type error: the lenient parse model
    # cannot coerce int->str, so it raises (translated to BindingsError at the load boundary).
    bad = GOOD.replace('trigger: "stage:plan"', "trigger: 5")
    with pytest.raises(BindingsError):
        load_bindings(_write(tmp_path, bad))


def test_absent_field_stays_a_content_finding(tmp_path):
    # An *absent* field defaults to "" and surfaces through validate() (structural/content split
    # preserved) — it never raises at the load boundary.
    missing_mode = GOOD.replace("    skill: perk-plan\n    mode: nudge\n", "    skill: perk-plan\n")
    issues = validate(load_bindings(_write(tmp_path, missing_mode)))
    assert "mode" in " | ".join(i.message for i in issues)


def test_user_overlay_ill_typed_scalar_is_loud_but_non_fatal():
    # U3: an ill-typed user [[bindings]] scalar coerces to "" (never crashes config-load) and the
    # resolver records the resulting shape Issue (never silently drops).
    user = parse_user_bindings([{"trigger": 5, "skill": "x", "mode": "nudge"}])
    assert user[0].trigger == ""
    resolved = resolve_bindings(user, defaults=DEFAULTS)
    assert resolved.bindings == DEFAULTS  # the invalid user binding is dropped
    assert resolved.issues  # ...and reported


def test_unknown_key_is_dropped_not_forbidden(tmp_path):
    # A stray key on a stored binding is dropped (extra="ignore"): the file loads clean and the
    # resulting Binding exposes only trigger/skill/mode.
    with_stray = GOOD.replace(
        "    skill: perk-plan\n    mode: nudge",
        "    skill: perk-plan\n    mode: nudge\n    bogus: y",
    )
    bindings = load_bindings(_write(tmp_path, with_stray))
    assert validate(bindings) == []
    first = bindings.bindings[0]
    assert (first.trigger, first.skill, first.mode) == ("stage:plan", "perk-plan", "nudge")
    assert not hasattr(first, "bogus")


def test_binding_is_frozen():
    binding = Binding(trigger="stage:plan", skill="x", mode="nudge")
    with pytest.raises(FrozenInstanceError):
        binding.skill = "y"  # ty: ignore[invalid-assignment]


def test_kind_and_target_id_derive_from_trigger():
    binding = Binding(trigger="stage:plan", skill="x", mode="nudge")
    assert (binding.kind, binding.target_id) == ("stage", "plan")
    no_colon = Binding(trigger="noColon", skill="x", mode="nudge")
    assert (no_colon.kind, no_colon.target_id) == ("", "")


# --------------------------------------------------------------------------- resolver

DEFAULTS = [
    Binding(trigger="stage:plan", skill="perk-plan", mode="nudge"),
    Binding(trigger="stage:implement", skill="perk-implement", mode="nudge"),
]


def _b(trigger, skill, mode):
    return Binding(trigger=trigger, skill=skill, mode=mode)


def test_resolve_empty_user_returns_defaults_unchanged():
    resolved = resolve_bindings([], defaults=DEFAULTS)
    assert resolved.bindings == DEFAULTS
    assert resolved.issues == []


def test_resolve_override_mode_in_place_preserves_position_and_count():
    resolved = resolve_bindings([_b("stage:plan", "perk-plan", "transclude")], defaults=DEFAULTS)
    assert resolved.issues == []
    assert [(b.trigger, b.skill, b.mode) for b in resolved.bindings] == [
        ("stage:plan", "perk-plan", "transclude"),
        ("stage:implement", "perk-implement", "nudge"),
    ]


def test_resolve_replace_skill_at_existing_trigger():
    resolved = resolve_bindings([_b("stage:plan", "house-style", "nudge")], defaults=DEFAULTS)
    assert resolved.bindings[0] == _b("stage:plan", "house-style", "nudge")


def test_resolve_new_trigger_is_appended():
    resolved = resolve_bindings([_b("stage:address", "house-style", "nudge")], defaults=DEFAULTS)
    assert resolved.issues == []
    assert [b.trigger for b in resolved.bindings] == [
        "stage:plan",
        "stage:implement",
        "stage:address",
    ]


def test_resolve_drops_invalid_bindings_and_reports_each_class():
    invalid = [
        _b("stage:plan", "", "nudge"),  # missing skill
        _b("stage:implement", "s", "shout"),  # bad mode
        _b("noColon", "s", "nudge"),  # malformed trigger
        _b("phase:x", "s", "nudge"),  # unknown kind
        _b("stage:", "s", "nudge"),  # empty target id
    ]
    resolved = resolve_bindings(invalid, defaults=DEFAULTS)
    # Defaults untouched (every user binding dropped).
    assert resolved.bindings == DEFAULTS
    messages = " | ".join(i.message for i in resolved.issues)
    assert all(i.severity is FindingSeverity.ERROR for i in resolved.issues)
    for fragment in ("skill", "mode", "<kind>:<id>", "kind", "empty"):
        assert fragment in messages


def test_resolve_duplicate_user_trigger_applies_first_reports_second():
    resolved = resolve_bindings(
        [
            _b("stage:plan", "first", "nudge"),
            _b("stage:plan", "second", "nudge"),
        ],
        defaults=DEFAULTS,
    )
    assert resolved.bindings[0].skill == "first"
    assert [i.message for i in resolved.issues] == ["duplicate `trigger`"]
    # Unique triggers by construction.
    triggers = [b.trigger for b in resolved.bindings]
    assert len(triggers) == len(set(triggers))


def test_resolve_defaults_to_shipped_when_omitted():
    resolved = resolve_bindings([])
    assert [(b.trigger, b.skill, b.mode) for b in resolved.bindings] == EXPECTED_DEFAULTS
    assert resolved.issues == []


# --- target-existence primitives (doctor) -----------------------------------------


def test_deliverable_command_targets_are_the_two_mechanism_b_triggers():
    # The only command triggers perk's delivery layer fires; stage-named commands bind via stage:.
    assert (
        frozenset(
            {
                "objective-reconcile",
                "objective-replan",
                "learn-docs",
                "learn-code",
                "pr-review",
                "pr-review-terminal",
                "pr-review-browser",
                "skills-create",
                "skills-refine",
            }
        )
        == DELIVERABLE_COMMAND_TARGETS
    )


def _plant_skill(root, subdir, name):
    path = root / subdir / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# skill\n", encoding="utf-8")


def test_is_skill_installed_absent(tmp_path):
    assert is_skill_installed(tmp_path, "ghost") is False


def test_is_skill_installed_under_agents_skills(tmp_path):
    _plant_skill(tmp_path, ".agents/skills", "my-skill")
    assert is_skill_installed(tmp_path, "my-skill") is True


def test_is_skill_installed_ignores_committed_self_repo_layout(tmp_path):
    # perk's own committed skills/<name>/ layout is NOT the delivery read path — warm injection
    # reads only .agents/skills/, so a committed-but-unsynced skill must read as not installed.
    _plant_skill(tmp_path, "skills", "perk-plan")
    assert is_skill_installed(tmp_path, "perk-plan") is False
