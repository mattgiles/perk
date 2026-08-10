"""Expectation-catalog loader + validator tests (perk_dev.audit.expectations).

Fixture-driven, mirroring test_bindings.py: a GOOD inline YAML string + per-test
targeted mutations written to tmp_path exercise each validation rule; structural
failures raise ExpectationsError while content problems stay Issue findings. The
committed catalog gets self-checks (parses + validates clean, non-empty, spans all
four kinds, `stage:` triggers are real registry stages, `source` paths exist).
"""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from perk_dev.audit.expectations import (
    KINDS,
    SUPPORTED_SCHEMA_VERSION,
    TIERS,
    Expectation,
    ExpectationsError,
    FindingSeverity,
    load_catalog,
    source_path_part,
    validate,
)

from perk.substrate.registry import load_registry

REPO_ROOT = Path(__file__).parents[1]

# A minimal-but-complete, valid catalog. Each negative test mutates one line.
GOOD = """\
schema_version: 1
expectations:
  - id: plan.review-before-save
    kind: workflow-shape
    surface: plan-stage review loop
    source: "prompts/stages/plan.md"
    applies_to:
      - "stage:plan"
    vintage_floor: "2.3.0"
    evidence: >-
      The transcript shows a review pass before /plan-save fires.
    violation: >-
      /plan-save fires with no review pass anywhere in the transcript.
    tier: deterministic
    enforcement: prose-only
  - id: learn-capture
    kind: prompt-adherence
    surface: learn capture
    source: "shared/contracts.md §8.4"
    applies_to:
      - "stage:learn"
      - "command:learn-docs"
    vintage_floor: "2.0.0"
    evidence: >-
      A learn summary is captured or the skip is recorded.
    violation: >-
      The session ends with neither a capture nor a recorded skip.
    tier: judgment
    enforcement: structural
"""


def _write(tmp_path, text):
    path = tmp_path / "expectations.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _messages(tmp_path, text):
    issues = validate(load_catalog(_write(tmp_path, text)))
    assert all(i.severity is FindingSeverity.ERROR for i in issues), issues
    return " | ".join(i.message for i in issues)


# --------------------------------------------------------------------- structural


def test_missing_file_raises(tmp_path):
    with pytest.raises(ExpectationsError, match="not found"):
        load_catalog(tmp_path / "expectations.yaml")


def test_top_level_not_a_mapping_raises(tmp_path):
    with pytest.raises(ExpectationsError, match="mapping"):
        load_catalog(_write(tmp_path, "- just\n- a\n- list\n"))


def test_unsupported_schema_version_raises(tmp_path):
    bad = GOOD.replace("schema_version: 1", "schema_version: 99")
    with pytest.raises(ExpectationsError, match="schema_version"):
        load_catalog(_write(tmp_path, bad))


def test_absent_schema_version_raises(tmp_path):
    bad = GOOD.replace("schema_version: 1\n", "")
    with pytest.raises(ExpectationsError, match="schema_version"):
        load_catalog(_write(tmp_path, bad))


def test_boolean_schema_version_raises(tmp_path):
    # bool is an int subclass and True == 1 in Python — the version gate must
    # still reject it (the catalog's schema_version is an integer by contract).
    bad = GOOD.replace("schema_version: 1", "schema_version: true")
    with pytest.raises(ExpectationsError, match="schema_version"):
        load_catalog(_write(tmp_path, bad))


def test_float_schema_version_raises(tmp_path):
    bad = GOOD.replace("schema_version: 1", "schema_version: 1.0")
    with pytest.raises(ExpectationsError, match="schema_version"):
        load_catalog(_write(tmp_path, bad))


def test_malformed_yaml_raises(tmp_path):
    # A YAML scanner/parser failure is a structural load failure: translated to
    # ExpectationsError (with the catalog path), never a leaked yaml.YAMLError.
    with pytest.raises(ExpectationsError, match=r"expectations\.yaml.*not parseable as YAML"):
        load_catalog(_write(tmp_path, "expectations: [unclosed\n"))


def test_non_string_scalar_raises_with_path(tmp_path):
    # A present bad-typed scalar is a genuine type error: the lenient parse model
    # cannot coerce int->str, so it raises (translated to ExpectationsError at the
    # load boundary) with the file path in the message.
    bad = GOOD.replace("id: plan.review-before-save", "id: 3")
    with pytest.raises(ExpectationsError, match=r"expectations\.yaml"):
        load_catalog(_write(tmp_path, bad))


# --------------------------------------------------------------- content findings


def test_good_fixture_is_valid(tmp_path):
    assert validate(load_catalog(_write(tmp_path, GOOD))) == []


def test_rejects_missing_id(tmp_path):
    bad = GOOD.replace("  - id: plan.review-before-save\n    kind:", "  - kind:")
    assert "missing its `id`" in _messages(tmp_path, bad)


def test_rejects_malformed_id_uppercase(tmp_path):
    bad = GOOD.replace("id: plan.review-before-save", "id: Plan.Review-Before-Save")
    assert "`id` must be" in _messages(tmp_path, bad)


def test_rejects_malformed_id_space(tmp_path):
    bad = GOOD.replace("id: plan.review-before-save", 'id: "plan review"')
    assert "`id` must be" in _messages(tmp_path, bad)


def test_rejects_duplicate_id(tmp_path):
    bad = GOOD.replace("id: learn-capture", "id: plan.review-before-save")
    assert "duplicate `id`" in _messages(tmp_path, bad)


def test_rejects_unknown_kind(tmp_path):
    bad = GOOD.replace("kind: workflow-shape", "kind: vibes")
    assert "`kind` must be one of" in _messages(tmp_path, bad)


def test_rejects_empty_surface(tmp_path):
    bad = GOOD.replace("surface: plan-stage review loop", 'surface: ""')
    assert "missing `surface`" in _messages(tmp_path, bad)


def test_rejects_empty_source(tmp_path):
    bad = GOOD.replace('source: "prompts/stages/plan.md"', 'source: ""')
    assert "missing `source`" in _messages(tmp_path, bad)


def test_rejects_empty_source_path_part(tmp_path):
    bad = GOOD.replace('source: "prompts/stages/plan.md"', 'source: " §8.4"')
    assert "empty path part" in _messages(tmp_path, bad)


def test_rejects_absolute_source(tmp_path):
    bad = GOOD.replace('source: "prompts/stages/plan.md"', 'source: "/etc/prompts/plan.md"')
    assert "repo-relative" in _messages(tmp_path, bad)


def test_rejects_backslash_source(tmp_path):
    bad = GOOD.replace('source: "prompts/stages/plan.md"', r"source: 'prompts\stages\plan.md'")
    assert "backslash" in _messages(tmp_path, bad)


def test_rejects_empty_applies_to(tmp_path):
    bad = GOOD.replace('applies_to:\n      - "stage:plan"', "applies_to: []")
    assert "at least one trigger" in _messages(tmp_path, bad)


def test_rejects_trigger_without_colon(tmp_path):
    bad = GOOD.replace('- "stage:plan"', '- "stageplan"')
    assert "<kind>:<id>" in _messages(tmp_path, bad)


def test_rejects_trigger_unknown_kind(tmp_path):
    bad = GOOD.replace('- "stage:plan"', '- "phase:plan"')
    assert "kind must be one of" in _messages(tmp_path, bad)


def test_rejects_trigger_empty_id(tmp_path):
    bad = GOOD.replace('- "stage:plan"', '- "stage:"')
    assert "empty `<id>`" in _messages(tmp_path, bad)


def test_rejects_duplicate_trigger_within_entry(tmp_path):
    bad = GOOD.replace('- "command:learn-docs"', '- "stage:learn"')
    assert "duplicate `applies_to` trigger" in _messages(tmp_path, bad)


def test_rejects_absent_vintage_floor(tmp_path):
    bad = GOOD.replace('    vintage_floor: "2.3.0"\n', "")
    assert "missing `vintage_floor`" in _messages(tmp_path, bad)


def test_rejects_malformed_vintage_floor_two_part(tmp_path):
    bad = GOOD.replace('vintage_floor: "2.3.0"', 'vintage_floor: "2.3"')
    assert "`vintage_floor` must be" in _messages(tmp_path, bad)


def test_rejects_malformed_vintage_floor_v_prefix(tmp_path):
    bad = GOOD.replace('vintage_floor: "2.3.0"', 'vintage_floor: "v2.3.0"')
    assert "`vintage_floor` must be" in _messages(tmp_path, bad)


def test_rejects_empty_evidence(tmp_path):
    bad = GOOD.replace(
        "evidence: >-\n      The transcript shows a review pass before /plan-save fires.",
        'evidence: ""',
    )
    assert "missing `evidence`" in _messages(tmp_path, bad)


def test_rejects_empty_violation(tmp_path):
    bad = GOOD.replace(
        "violation: >-\n      /plan-save fires with no review pass anywhere in the transcript.",
        'violation: ""',
    )
    assert "missing `violation`" in _messages(tmp_path, bad)


def test_rejects_unknown_tier(tmp_path):
    bad = GOOD.replace("tier: deterministic", "tier: hunch")
    assert "`tier` must be one of" in _messages(tmp_path, bad)


def test_rejects_unknown_enforcement(tmp_path):
    bad = GOOD.replace("enforcement: prose-only", "enforcement: gentle")
    assert "`enforcement` must be one of" in _messages(tmp_path, bad)


def test_multi_defect_catalog_reports_each_issue_at_its_location(tmp_path):
    # validate() accumulates every independent finding and addresses each to the
    # right location: the generic "expectations" for a missing id, the entry's own
    # id otherwise.
    multi_defect = """\
schema_version: 1
expectations:
  - kind: workflow-shape
    surface: s
    source: "docs/index.md"
    applies_to:
      - "stage:plan"
    vintage_floor: "2.3.0"
    evidence: e
    violation: v
    tier: deterministic
    enforcement: prose-only
  - id: second-entry
    kind: workflow-shape
    surface: ""
    source: "docs/index.md"
    applies_to:
      - "stage:plan"
    vintage_floor: "2.3.0"
    evidence: e
    violation: v
    tier: hunch
    enforcement: prose-only
"""
    issues = validate(load_catalog(_write(tmp_path, multi_defect)))
    assert [(i.severity, i.where, i.message) for i in issues] == [
        (FindingSeverity.ERROR, "expectations", "an expectation is missing its `id`"),
        (FindingSeverity.ERROR, "second-entry", "missing `surface`"),
        (FindingSeverity.ERROR, "second-entry", f"`tier` must be one of {TIERS}"),
    ]


# ----------------------------------------------------------- lenient boundary


def test_unknown_key_is_dropped_not_forbidden(tmp_path):
    # A stray key on a stored entry is dropped (extra="ignore"): the file loads
    # clean, validates clean, and the domain object exposes no such attribute.
    with_stray = GOOD.replace("    tier: deterministic", "    bogus: y\n    tier: deterministic")
    catalog = load_catalog(_write(tmp_path, with_stray))
    assert validate(catalog) == []
    assert not hasattr(catalog.expectations[0], "bogus")


def test_absent_field_stays_a_content_finding(tmp_path):
    # An *absent* field defaults and surfaces through validate() (structural/content
    # split preserved) — it never raises at the load boundary.
    missing_tier = GOOD.replace("    tier: judgment\n", "")
    issues = validate(load_catalog(_write(tmp_path, missing_tier)))
    assert "`tier` must be one of" in " | ".join(i.message for i in issues)


# ------------------------------------------------------------------ domain shape


def test_expectation_is_frozen():
    entry = Expectation(
        id="x",
        kind="workflow-shape",
        surface="s",
        source="docs/index.md",
        applies_to=("stage:plan",),
        vintage_floor="2.3.0",
        evidence="e",
        violation="v",
        tier="deterministic",
        enforcement="prose-only",
    )
    with pytest.raises(FrozenInstanceError):
        entry.kind = "skill-uptake"  # ty: ignore[invalid-assignment]


def test_loads_full_expectation_field_for_field(tmp_path):
    # The loader's core conversion contract: every YAML field lands on its own
    # Expectation field (no swapped/miswired assignments), and the parsed
    # schema_version is pinned on the catalog.
    catalog = load_catalog(_write(tmp_path, GOOD))
    assert catalog.schema_version == SUPPORTED_SCHEMA_VERSION
    assert catalog.expectations[0] == Expectation(
        id="plan.review-before-save",
        kind="workflow-shape",
        surface="plan-stage review loop",
        source="prompts/stages/plan.md",
        applies_to=("stage:plan",),
        vintage_floor="2.3.0",
        evidence="The transcript shows a review pass before /plan-save fires.",
        violation="/plan-save fires with no review pass anywhere in the transcript.",
        tier="deterministic",
        enforcement="prose-only",
    )


def test_applies_to_round_trips_to_tuple(tmp_path):
    catalog = load_catalog(_write(tmp_path, GOOD))
    assert catalog.expectations[1].applies_to == ("stage:learn", "command:learn-docs")


def test_source_path_part_splits_anchor():
    assert source_path_part("shared/contracts.md §8.4") == "shared/contracts.md"
    assert source_path_part("prompts/stages/plan.md") == "prompts/stages/plan.md"


# --------------------------------------------------- committed-catalog self-checks


def test_committed_catalog_is_valid():
    # The committed YAML always parses + validates clean.
    assert validate(load_catalog()) == []


def test_committed_catalog_is_not_empty():
    # The empty-catalog era is over: an accidental truncation must fail CI.
    assert load_catalog().expectations


def test_committed_catalog_spans_all_four_kinds():
    # The catalog must keep covering all four expectation kinds.
    assert {e.kind for e in load_catalog().expectations} == set(KINDS)


def test_committed_catalog_schema_version():
    assert load_catalog().schema_version == SUPPORTED_SCHEMA_VERSION


def test_committed_stage_triggers_are_real_stages():
    stage_ids = load_registry().stage_ids()
    for entry in load_catalog().expectations:
        for trigger in entry.applies_to:
            kind, _, target_id = trigger.partition(":")
            if kind == "stage":
                assert target_id in stage_ids, trigger


def test_committed_source_paths_exist():
    for entry in load_catalog().expectations:
        path_part = source_path_part(entry.source)
        assert (REPO_ROOT / path_part).exists(), entry.source
