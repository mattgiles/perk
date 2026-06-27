"""Registry loader + validator tests (the thin seam).

The real bundled registry must validate; the validator must *reject* each class of
authoring error. Negative fixtures are what exercise the shape/graph/vocabulary checks
while the real registry's reads/writes are still empty.
"""

import pytest

from perk.boundary import ValidationError
from perk.substrate.registry import FindingSeverity, RegistryError, load_registry, validate

# A minimal-but-complete, valid 2-stage registry. Each negative test mutates one line.
GOOD = """\
schema_version: 1
state_keys:
  github: [plan]
  cache: [plan-ref]
  session: [workflow-state]
stages:
  - id: plan
    summary: draft
    mode: read-only
    worktree: none
    doors: { warm: true, cold_local: true, cold_remote: false }
    run_id: { warm: keep, cold_local: mint, cold_remote: mint }
    command: plan
    requires: []
    reads: []
    writes: []
    predecessors: []
    successors: [save]
  - id: save
    summary: persist
    mode: read-write
    worktree: none
    doors: { warm: true, cold_local: true, cold_remote: false }
    run_id: { warm: keep, cold_local: mint, cold_remote: mint }
    command: save
    requires: []
    reads: []
    writes: []
    predecessors: [plan]
    successors: []
"""


def _write(tmp_path, text):
    path = tmp_path / "registry.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _messages(tmp_path, text):
    issues = validate(load_registry(_write(tmp_path, text)))
    assert all(i.severity is FindingSeverity.ERROR for i in issues), issues
    return " | ".join(i.message for i in issues)


def test_real_registry_is_valid():
    # The bundled shared/registry.yaml: parses and has zero issues.
    registry = load_registry()
    assert [s.id for s in registry.stages] == [
        "objective-author",
        "objective-save",
        "objective-plan",
        "plan",
        "save",
        "implement",
        "submit",
        "address",
        "land",
        "learn",
    ]
    assert validate(registry) == []


def test_objective_author_is_the_single_initial():
    # objective-author -> objective-save -> objective-plan -> plan (the new single initial;
    # learn stays the single terminal).
    registry = load_registry()
    by_id = {s.id: s for s in registry.stages}
    auth = by_id["objective-author"]
    save = by_id["objective-save"]
    assert auth.predecessors == [] and auth.successors == ["objective-save"]
    assert save.predecessors == ["objective-author"] and save.successors == ["objective-plan"]
    assert by_id["objective-plan"].predecessors == ["objective-save"]
    # Single initial, single terminal.
    initials = [s.id for s in registry.stages if not s.predecessors]
    terminals = [s.id for s in registry.stages if not s.successors]
    assert initials == ["objective-author"]
    assert terminals == ["learn"]
    # Mode / worktree / doors / I/O as built.
    assert auth.mode == "read-only" and auth.worktree == "none"
    assert auth.doors == {"warm": True, "cold_local": True, "cold_remote": False}
    assert auth.requires == [] and auth.reads == []
    # objective_draft adds cache.session-data to the authoring stage's writes.
    assert auth.writes == ["session.workflow-state", "cache.session-data"]
    assert save.mode == "read-write" and save.worktree == "none"
    assert save.writes == ["github.objective", "session.workflow-state"]


def test_address_is_linear_between_submit_and_land():
    # submit -> address -> land (single initial, single terminal, symmetric edges).
    registry = load_registry()
    by_id = {s.id: s for s in registry.stages}
    assert by_id["submit"].successors == ["address"]
    assert by_id["address"].predecessors == ["submit"]
    assert by_id["address"].successors == ["land"]
    assert by_id["land"].predecessors == ["address"]
    assert by_id["address"].mode == "read-write" and by_id["address"].worktree == "reuse"


def test_land_io_includes_github_objective():
    # The mechanical auto-on-merge node-done reads + writes github.objective.
    registry = load_registry()
    land = {s.id: s for s in registry.stages}["land"]
    assert "github.objective" in land.reads
    assert "github.objective" in land.writes


def test_stage_io_contract():
    # Locks the per-stage state I/O the retired scripts/verify-*.sh gates guarded.
    # Anchored on stage ids + field names (never line numbers) so it tracks
    # shared/registry.yaml as the cross-plane contract.
    registry = load_registry()
    by_id = {s.id: s for s in registry.stages}

    assert by_id["save"].writes == [
        "github.plan",
        "cache.plan-ref",
        "session.workflow-state",
    ]

    implement = by_id["implement"]
    assert implement.requires == ["cache.plan-ref"]
    assert implement.reads == ["cache.plan-ref"]
    assert implement.writes == ["session.workflow-state"]
    assert implement.doors["warm"] is False

    submit = by_id["submit"]
    assert "cache.plan-ref" in submit.requires
    assert {"github.pr", "github.plan"} <= set(submit.writes)

    learn = by_id["learn"]
    assert {"github.learn", "github.comments"} <= set(learn.writes)
    assert "cache.plan-ref" in learn.reads
    assert "cache.markers" in learn.requires and "cache.markers" in learn.writes

    assert {"github.pr", "cache.markers"} <= set(by_id["land"].writes)

    cold_remote = {sid for sid, s in by_id.items() if s.doors.get("cold_remote") is True}
    assert cold_remote == {"implement", "address"}

    assert "github.learn" in registry.state_keys
    # The session-data vocabulary key, declared in writes by both authoring stages.
    assert "cache.session-data" in registry.state_keys
    assert "cache.session-data" in by_id["plan"].writes
    assert "cache.session-data" in by_id["objective-plan"].writes
    # objective_draft writes the objective-draft artifact during objective-author.
    assert "cache.session-data" in by_id["objective-author"].writes


def test_good_fixture_is_valid(tmp_path):
    assert validate(load_registry(_write(tmp_path, GOOD))) == []


def test_rejects_dangling_successor(tmp_path):
    bad = GOOD.replace("successors: [save]", "successors: [ghost]")
    assert "ghost" in _messages(tmp_path, bad)


def test_rejects_asymmetric_edge(tmp_path):
    # plan -> save, but save no longer lists plan as a predecessor.
    bad = GOOD.replace("    predecessors: [plan]", "    predecessors: []")
    assert "asymmetric" in _messages(tmp_path, bad)


def test_rejects_unknown_state_key(tmp_path):
    bad = GOOD.replace(
        "    reads: []\n    writes: []\n    predecessors: [plan]",
        "    reads: [github.bogus]\n    writes: []\n    predecessors: [plan]",
    )
    assert "github.bogus" in _messages(tmp_path, bad)


def test_rejects_bad_mode_enum(tmp_path):
    bad = GOOD.replace("    mode: read-only", "    mode: read")
    assert "mode" in _messages(tmp_path, bad)


def test_rejects_bad_run_id_invariant(tmp_path):
    # warm must be `keep`.
    bad = GOOD.replace(
        "run_id: { warm: keep, cold_local: mint, cold_remote: mint }",
        "run_id: { warm: mint, cold_local: mint, cold_remote: mint }",
        1,
    )
    assert "run_id.warm" in _messages(tmp_path, bad)


def test_unsupported_schema_version_raises(tmp_path):
    bad = GOOD.replace("schema_version: 1", "schema_version: 99")
    with pytest.raises(RegistryError):
        load_registry(_write(tmp_path, bad))


def test_wrong_typed_field_raises_registry_error(tmp_path):
    # A wrong-typed field is now structural (was: silently defaulted, then a content Issue).
    bad = GOOD.replace("    mode: read-only", "    mode: 5")
    with pytest.raises(RegistryError):
        load_registry(_write(tmp_path, bad))


def test_unknown_stage_key_raises_registry_error(tmp_path):
    # `extra="forbid"` on the strict model: an unknown stage key is structural.
    bad = GOOD.replace("    command: plan", "    command: plan\n    bogus: x")
    with pytest.raises(RegistryError):
        load_registry(_write(tmp_path, bad))


def test_missing_field_is_still_a_content_issue(tmp_path):
    # An absent field stays content (defaulted to ""), reported by validate() — not structural.
    bad = GOOD.replace("    summary: draft\n", "")
    assert "summary" in _messages(tmp_path, bad)


def test_models_are_frozen(tmp_path):
    # The frozen contract carries over from the old frozen dataclasses.
    registry = load_registry(_write(tmp_path, GOOD))
    with pytest.raises(ValidationError):
        registry.stages[0].id = "mutated"
    with pytest.raises(ValidationError):
        registry.schema_version = 99
