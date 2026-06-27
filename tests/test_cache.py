import json

import pytest

from perk.state.cache import (
    AgentSessionCache,
    CacheError,
    PlanRefCache,
    clear_marker,
    dispatch_path,
    ensure_layout,
    has_marker,
    list_dispatch_records,
    list_run_ids,
    mark_handoff_consumed,
    plan_ref_path,
    read_agent_session,
    read_dispatch,
    read_handoff,
    read_plan_ref,
    read_scratch,
    read_session_data,
    run_scratch_dir,
    scratch_dir,
    session_data_dir,
    set_marker,
    workflow_dir,
    write_agent_session,
    write_dispatch,
    write_handoff,
    write_plan_ref,
    write_scratch,
    write_session_data,
)


def _dispatch(run_id: str = "01RID", **over: object) -> dict:
    base = {
        "stage": "implement",
        "plan_ref": {"provider": "github", "pr_id": "7"},
        "runner": "",
        "kind": "github-actions",
        "status": "dispatched",
        "dispatched_at": "2024-01-01T00:00:00Z",
    }
    return {**base, "run_id": run_id, **over}


def test_ensure_layout_idempotent(tmp_path):
    wd = ensure_layout(tmp_path)
    assert wd == workflow_dir(tmp_path) == tmp_path / ".perk" / "workflow"
    assert (wd / "scratch" / "runs").is_dir()
    assert (wd / "handoff").is_dir()
    assert (wd / "markers").is_dir()
    ensure_layout(tmp_path)  # second run is a no-op (no error)


def test_scratch_round_trip(tmp_path):
    write_scratch(tmp_path, "RID", "diff.txt", "hello")
    assert read_scratch(tmp_path, "RID", "diff.txt") == "hello"
    assert read_scratch(tmp_path, "RID", "missing.txt") is None


def test_scratch_and_session_data_path_shapes(tmp_path):
    assert scratch_dir(tmp_path) == workflow_dir(tmp_path) / "scratch"
    assert run_scratch_dir(tmp_path, "RID") == scratch_dir(tmp_path) / "runs" / "RID"
    assert session_data_dir(tmp_path, "RID") == run_scratch_dir(tmp_path, "RID") / "data"


def test_session_data_round_trip(tmp_path):
    path = write_session_data(tmp_path, "RID", "draft.md", "hello")
    assert path == session_data_dir(tmp_path, "RID") / "draft.md"
    assert path is not None and path.is_file()
    assert read_session_data(tmp_path, "RID", "draft.md") == "hello"


def test_session_data_absent_read_returns_none(tmp_path):
    assert read_session_data(tmp_path, "RID", "missing.md") is None


def test_session_data_write_failure_degrades(tmp_path, capsys):
    # Make the run dir a *file* so mkdir of data/ fails with OSError.
    run_dir = run_scratch_dir(tmp_path, "RID")
    run_dir.parent.mkdir(parents=True)
    run_dir.write_text("not a dir", encoding="utf-8")
    assert write_session_data(tmp_path, "RID", "draft.md", "x") is None
    assert "warning: could not write session data" in capsys.readouterr().err


def test_session_data_read_failure_degrades(tmp_path, capsys):
    write_session_data(tmp_path, "RID", "blob.bin", "placeholder")
    (session_data_dir(tmp_path, "RID") / "blob.bin").write_bytes(b"\xff\xfe\xff")
    assert read_session_data(tmp_path, "RID", "blob.bin") is None
    assert "warning: could not read session data" in capsys.readouterr().err


def test_list_run_ids(tmp_path):
    assert list_run_ids(tmp_path) == []
    runs = scratch_dir(tmp_path) / "runs"
    runs.mkdir(parents=True)
    (runs / "B").mkdir()
    (runs / "A").mkdir()
    (runs / "stray.txt").write_text("", encoding="utf-8")
    assert list_run_ids(tmp_path) == ["A", "B"]


def test_handoff_round_trip_and_consume(tmp_path):
    write_handoff(tmp_path, "RID", {"mode": "read-only"})
    data = read_handoff(tmp_path, "RID")
    assert data is not None
    assert data.run_id == "RID"
    assert data.mode == "read-only"
    assert data.consumed is False

    mark_handoff_consumed(tmp_path, "RID", pi_session_id="sess1")
    consumed = read_handoff(tmp_path, "RID")
    assert consumed is not None
    assert consumed.consumed is True
    assert consumed.pi_session_id == "sess1"

    mark_handoff_consumed(tmp_path, "RID")  # idempotent
    again = read_handoff(tmp_path, "RID")
    assert again is not None and again.consumed is True


def test_write_handoff_run_id_is_authoritative(tmp_path):
    # A run_id in the data dict cannot override the keyed run_id.
    write_handoff(tmp_path, "RID", {"run_id": "BOGUS", "mode": "implement"})
    data = read_handoff(tmp_path, "RID")
    assert data is not None and data.run_id == "RID"


def test_handoff_rejects_wrong_typed_consumed(tmp_path):
    # `consumed` is strict bool — a bool-as-int (1) is rejected (strict mode).
    path = write_handoff(tmp_path, "RID", {})
    path.write_text('{"run_id": "RID", "consumed": 1}\n', encoding="utf-8")
    with pytest.raises(CacheError) as exc:
        read_handoff(tmp_path, "RID")
    # Subclasses ValueError so fail-soft `except (OSError, ValueError)` cache guards keep working.
    assert isinstance(exc.value, ValueError)


def test_handoff_rejects_missing_run_id(tmp_path):
    path = write_handoff(tmp_path, "RID", {})
    path.write_text('{"consumed": false, "mode": "implement"}\n', encoding="utf-8")
    with pytest.raises(CacheError):
        read_handoff(tmp_path, "RID")


def test_handoff_arbitrary_extra_survives_round_trip(tmp_path):
    # `state new-run` may write an arbitrary object; extra keys round-trip (extra="allow").
    write_handoff(tmp_path, "RID", {"mode": "read-only", "custom_key": "custom_value"})
    data = read_handoff(tmp_path, "RID")
    assert data is not None
    assert data.model_dump(mode="json", exclude_unset=True)["custom_key"] == "custom_value"


def test_handoff_declared_extras_read_back_typed(tmp_path):
    write_handoff(
        tmp_path,
        "RID",
        {"stage": "plan", "objective_id": "137", "consumed_learn": ["45", "50"]},
    )
    data = read_handoff(tmp_path, "RID")
    assert data is not None
    assert data.objective_id == "137"
    assert data.consumed_learn == ("45", "50")


def test_read_and_consume_missing_handoff(tmp_path):
    assert read_handoff(tmp_path, "nope") is None
    mark_handoff_consumed(tmp_path, "nope")  # no error on absent handoff


def test_plan_ref_round_trip(tmp_path):
    assert read_plan_ref(tmp_path) is None  # absent -> None (branchable)
    # The former 5-key partial write: `exclude_unset` preserves the shape (no consumed_learn/base).
    ref = {
        "provider": "github",
        "pr_id": "42",
        "url": "https://github.com/o/r/issues/42",
        "labels": ["perk:plan"],
        "objective_id": None,
    }
    path = write_plan_ref(tmp_path, ref)
    assert path == plan_ref_path(tmp_path) == workflow_dir(tmp_path) / "plan-ref.json"
    got = read_plan_ref(tmp_path)
    assert got == PlanRefCache(
        provider="github",
        pr_id="42",
        url="https://github.com/o/r/issues/42",
        labels=("perk:plan",),
        objective_id=None,
    )
    # `objective_id: null` is preserved (explicitly set), and the shape stays 5 keys on disk.
    assert set(json.loads(path.read_text(encoding="utf-8"))) == {
        "provider",
        "pr_id",
        "url",
        "labels",
        "objective_id",
    }


def test_plan_ref_rejects_bad_types(tmp_path):
    with pytest.raises(CacheError):  # non-list labels
        write_plan_ref(tmp_path, {"provider": "g", "pr_id": "1", "url": "u", "labels": "x"})
    with pytest.raises(CacheError):  # non-str pr_id
        write_plan_ref(tmp_path, {"provider": "g", "pr_id": 1, "url": "u", "labels": ["x"]})


def test_dispatch_round_trip_and_required_fields(tmp_path):
    assert read_dispatch(tmp_path, "nope") is None  # absent -> None
    write_dispatch(tmp_path, "01RID", _dispatch(run_id="WRONG"))  # run_id is authoritative
    back = read_dispatch(tmp_path, "01RID")
    assert back is not None and back.run_id == "01RID" and back.run_handle is None
    # A record missing a required field is rejected.
    bad = dispatch_path(tmp_path, "01RID")
    bad.write_text('{"run_id": "01RID", "stage": "implement"}\n', encoding="utf-8")
    with pytest.raises(CacheError):
        read_dispatch(tmp_path, "01RID")


def test_list_dispatch_records_skips_invalid_loudly(tmp_path, capsys):
    write_dispatch(tmp_path, "01good", _dispatch(run_id="01good"))
    bad = run_scratch_dir(tmp_path, "01bad") / "dispatch.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text('{"run_id": "01bad"}\n', encoding="utf-8")  # missing required fields
    records = list_dispatch_records(tmp_path)
    assert [r.run_id for r in records] == ["01good"]
    assert "skipping unreadable dispatch record" in capsys.readouterr().err


def test_agent_session_round_trip_and_strictness(tmp_path):
    assert read_agent_session(tmp_path) is None  # absent -> None
    write_agent_session(tmp_path, {"session_id": "s", "issue": "ENG-1", "url": None})
    got = read_agent_session(tmp_path)
    assert got == AgentSessionCache(session_id="s", issue="ENG-1", url=None)
    # extra="forbid": an unknown key is rejected.
    with pytest.raises(CacheError):
        write_agent_session(tmp_path, {"session_id": "s", "issue": "x", "unknown": 1})


def test_markers(tmp_path):
    assert not has_marker(tmp_path, "pending-learn")
    set_marker(tmp_path, "pending-learn")
    assert has_marker(tmp_path, "pending-learn")
    clear_marker(tmp_path, "pending-learn")
    assert not has_marker(tmp_path, "pending-learn")
    clear_marker(tmp_path, "pending-learn")  # idempotent
