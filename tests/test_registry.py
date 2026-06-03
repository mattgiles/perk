"""Registry loader + validator tests (T2 thin seam).

The real bundled registry must validate; the validator must *reject* each class of
authoring error. Negative fixtures are what exercise the shape/graph/vocabulary checks
while the real registry's reads/writes are still empty.
"""

import pytest

from perk.registry import RegistryError, Severity, load_registry, validate

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
    assert all(i.severity is Severity.ERROR for i in issues), issues
    return " | ".join(i.message for i in issues)


def test_real_registry_is_valid():
    # The bundled shared/registry.yaml: parses and has zero issues.
    registry = load_registry()
    assert [s.id for s in registry.stages] == [
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


def test_objective_plan_is_initial_before_plan():
    # P2.T10: objective-plan -> plan (the new single initial; learn stays the single terminal).
    registry = load_registry()
    by_id = {s.id: s for s in registry.stages}
    op = by_id["objective-plan"]
    assert op.predecessors == [] and op.successors == ["plan"]
    assert by_id["plan"].predecessors == ["objective-plan"]
    # Single initial, single terminal.
    initials = [s.id for s in registry.stages if not s.predecessors]
    terminals = [s.id for s in registry.stages if not s.successors]
    assert initials == ["objective-plan"]
    assert terminals == ["learn"]
    # Mode / worktree / doors / I/O as built.
    assert op.mode == "read-only" and op.worktree == "none"
    assert op.doors == {"warm": True, "cold_local": True, "cold_remote": False}
    assert op.requires == ["github.objective"]
    assert op.reads == ["github.objective"]
    assert op.writes == ["github.objective", "session.workflow-state"]


def test_address_is_linear_between_submit_and_land():
    # P2.T7: submit -> address -> land (single initial, single terminal, symmetric edges).
    registry = load_registry()
    by_id = {s.id: s for s in registry.stages}
    assert by_id["submit"].successors == ["address"]
    assert by_id["address"].predecessors == ["submit"]
    assert by_id["address"].successors == ["land"]
    assert by_id["land"].predecessors == ["address"]
    assert by_id["address"].mode == "read-write" and by_id["address"].worktree == "reuse"


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
    # warm must be `keep` (Q2).
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
