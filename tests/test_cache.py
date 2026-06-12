from perk.state.cache import (
    clear_marker,
    ensure_layout,
    has_marker,
    list_run_ids,
    mark_handoff_consumed,
    plan_ref_path,
    read_handoff,
    read_plan_ref,
    read_scratch,
    read_session_data,
    run_scratch_dir,
    scratch_dir,
    session_data_dir,
    set_marker,
    workflow_dir,
    write_handoff,
    write_plan_ref,
    write_scratch,
    write_session_data,
)


def test_ensure_layout_idempotent(tmp_path):
    wd = ensure_layout(tmp_path)
    assert wd == workflow_dir(tmp_path) == tmp_path / ".pi" / "workflow"
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
    assert data["run_id"] == "RID"
    assert data["mode"] == "read-only"
    assert data["consumed"] is False

    mark_handoff_consumed(tmp_path, "RID", pi_session_id="sess1")
    consumed = read_handoff(tmp_path, "RID")
    assert consumed is not None
    assert consumed["consumed"] is True
    assert consumed["pi_session_id"] == "sess1"

    mark_handoff_consumed(tmp_path, "RID")  # idempotent
    again = read_handoff(tmp_path, "RID")
    assert again is not None and again["consumed"] is True


def test_write_handoff_run_id_is_authoritative(tmp_path):
    # A run_id in the data dict cannot override the keyed run_id.
    write_handoff(tmp_path, "RID", {"run_id": "BOGUS", "mode": "implement"})
    data = read_handoff(tmp_path, "RID")
    assert data is not None and data["run_id"] == "RID"


def test_read_and_consume_missing_handoff(tmp_path):
    assert read_handoff(tmp_path, "nope") is None
    mark_handoff_consumed(tmp_path, "nope")  # no error on absent handoff


def test_plan_ref_round_trip(tmp_path):
    assert read_plan_ref(tmp_path) is None  # absent -> None (branchable)
    ref = {
        "provider": "github",
        "pr_id": "42",
        "url": "https://github.com/o/r/issues/42",
        "labels": ["perk:plan"],
        "objective_id": None,
    }
    path = write_plan_ref(tmp_path, ref)
    assert path == plan_ref_path(tmp_path) == workflow_dir(tmp_path) / "plan-ref.json"
    assert read_plan_ref(tmp_path) == ref


def test_markers(tmp_path):
    assert not has_marker(tmp_path, "pending-learn")
    set_marker(tmp_path, "pending-learn")
    assert has_marker(tmp_path, "pending-learn")
    clear_marker(tmp_path, "pending-learn")
    assert not has_marker(tmp_path, "pending-learn")
    clear_marker(tmp_path, "pending-learn")  # idempotent
