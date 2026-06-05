"""Bindings loader + validator tests (Node 1.1 thin seam).

The real bundled bindings must validate; the validator must *reject* each class of
authoring error. Negative fixtures (a GOOD constant + per-test single-line mutation,
mirroring test_registry.py) exercise the shape checks. A test also asserts the shipped
`stage:` triggers are real registry stages, to catch a typo in the shipped file — while
the loader itself stays registry-free (target-existence is doctor's job, Node 3.1).
"""

import pytest

from perk.bindings import BindingsError, Severity, load_bindings, validate
from perk.registry import load_registry

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
    ("stage:objective-author", "perk-objective-author", "nudge"),
    ("stage:objective-plan", "perk-objective-plan", "nudge"),
    ("stage:implement", "perk-implement", "nudge"),
    ("stage:address", "perk-address", "nudge"),
    ("stage:learn", "perk-learn", "nudge"),
    ("command:objective-reconcile", "perk-objective-reconcile", "nudge"),
    ("command:learn-docs", "perk-learn-docs", "nudge"),
]


def _write(tmp_path, text):
    path = tmp_path / "bindings.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _messages(tmp_path, text):
    issues = validate(load_bindings(_write(tmp_path, text)))
    assert all(i.severity is Severity.ERROR for i in issues), issues
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
