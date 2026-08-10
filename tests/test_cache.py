import dataclasses
import json
import threading

import pytest

from perk import plan
from perk.boundary import ValidationError
from perk.cli.ensure import UserFacingCliError
from perk.run.runner import RunHandle
from perk.state import cache
from perk.state.cache import (
    AgentSession,
    CacheError,
    Dispatch,
    atomic_write_text,
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


def _dispatch(
    run_id: str = "01RID", *, run_handle: RunHandle | None = None, **over: object
) -> Dispatch:
    ref = plan.PlanRef(provider="github", pr_id="7", url="u/7", labels=("perk:plan",))
    base = Dispatch(
        run_id=run_id,
        stage="implement",
        plan_ref=ref,
        runner="",
        kind="github-actions",
        status="dispatched",
        dispatched_at="2024-01-01T00:00:00Z",
        run_handle=run_handle,
    )
    return dataclasses.replace(base, **over) if over else base


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


def test_handoff_gist_scope_declared_round_trip(tmp_path):
    # The declared gist_scope key (stashed by `perk gist author --scope`, recovered by
    # `perk gist create`) round-trips with typed attribute access; absent → None.
    write_handoff(tmp_path, "RID", {"stage": "gist-author", "gist_scope": "objective"})
    data = read_handoff(tmp_path, "RID")
    assert data is not None and data.gist_scope == "objective"

    write_handoff(tmp_path, "RID2", {"stage": "gist-author"})
    bare = read_handoff(tmp_path, "RID2")
    assert bare is not None and bare.gist_scope is None


def test_handoff_on_disk_shape_is_minimal(tmp_path):
    # The on-disk blob stays minimal — only the caller's keys + the authoritative run_id/consumed
    # (byte-identical to the pre-Pydantic passthrough; no synthesized null fields).
    path = write_handoff(tmp_path, "RID", {"stage": "plan", "mode": "read-only"})
    assert set(json.loads(path.read_text(encoding="utf-8"))) == {
        "stage",
        "mode",
        "run_id",
        "consumed",
    }


def test_write_handoff_run_id_is_authoritative(tmp_path):
    # A run_id in the data dict cannot override the keyed run_id.
    write_handoff(tmp_path, "RID", {"run_id": "BOGUS", "mode": "implement"})
    data = read_handoff(tmp_path, "RID")
    assert data is not None and data.run_id == "RID"


def test_handoff_coerces_int_consumed(tmp_path):
    # The read boundary is now a LenientParseModel: a bool-as-int (1) coerces to True instead of
    # raising (the pre-Pydantic v1.0.1 behavior never validated `consumed` — truthy int). The
    # intended lenient-edge behavior for the durable cache.
    path = write_handoff(tmp_path, "RID", {})
    path.write_text('{"run_id": "RID", "consumed": 1}\n', encoding="utf-8")
    data = read_handoff(tmp_path, "RID")
    assert data is not None and data.consumed is True


def test_handoff_rejects_missing_run_id(tmp_path):
    path = write_handoff(tmp_path, "RID", {})
    path.write_text('{"consumed": false, "mode": "implement"}\n', encoding="utf-8")
    with pytest.raises(CacheError):
        read_handoff(tmp_path, "RID")


def test_handoff_arbitrary_extra_survives_round_trip(tmp_path):
    # `state new-run` may write an arbitrary object; extra keys round-trip (extra="allow")
    # and land in the domain object's `extra` mapping.
    write_handoff(tmp_path, "RID", {"mode": "read-only", "custom_key": "custom_value"})
    data = read_handoff(tmp_path, "RID")
    assert data is not None
    assert data.extra["custom_key"] == "custom_value"


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
    # `write_plan_ref` now takes a typed `plan.PlanRef` (always full), so the on-disk shape is
    # the full 8-key shape (= byte-identical to the production write path).
    ref = plan.PlanRef(
        provider="github",
        pr_id="42",
        url="https://github.com/o/r/issues/42",
        labels=("perk:plan",),
    )
    path = write_plan_ref(tmp_path, ref)
    assert path == plan_ref_path(tmp_path) == workflow_dir(tmp_path) / "plan-ref.json"
    got = read_plan_ref(tmp_path)
    assert got == ref
    assert set(json.loads(path.read_text(encoding="utf-8"))) == {
        "provider",
        "pr_id",
        "url",
        "labels",
        "objective_id",
        "consumed_learn",
        "base",
        "delivery_lineage",
    }


def test_plan_ref_rejects_bad_types_on_read(tmp_path):
    # `write_plan_ref` takes a typed dataclass, so bad-type rejection lives at the read boundary:
    # a malformed `plan-ref.json` raises CacheError when read.
    path = plan_ref_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"provider": "g", "pr_id": "1", "url": "u", "labels": "x"}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(CacheError):  # non-list labels (a bare str is not spread)
        read_plan_ref(tmp_path)
    path.write_text(
        json.dumps({"provider": "g", "url": "u", "labels": ["x"]}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(CacheError):  # missing required pr_id
        read_plan_ref(tmp_path)


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


def test_dispatch_nested_round_trip_is_typed(tmp_path):
    """The nested plan_ref/run_handle are validated + read back as typed domain objects."""
    write_dispatch(
        tmp_path,
        "01RID",
        _dispatch(
            run_id="01RID",
            run_handle=RunHandle(runner="ci", kind="github-actions", run_ref="7", url="u"),
        ),
    )
    back = read_dispatch(tmp_path, "01RID")
    assert back is not None
    assert isinstance(back.plan_ref, plan.PlanRef) and back.plan_ref.pr_id == "7"
    assert isinstance(back.run_handle, RunHandle) and back.run_handle.run_ref == "7"


def test_dispatch_rejects_malformed_nested_plan_ref(tmp_path):
    """A nested plan_ref missing required url/labels on disk -> CacheError from read_dispatch."""
    bad = dispatch_path(tmp_path, "01bad")
    bad.parent.mkdir(parents=True, exist_ok=True)
    # model_validate (the boundary) raises a raw ValidationError; the cache reader translates it.
    with pytest.raises(ValidationError):
        cache.DispatchModel.model_validate(
            {
                "run_id": "01bad",
                "stage": "implement",
                "plan_ref": {"provider": "github", "pr_id": "7"},
                "runner": "",
                "kind": "github-actions",
                "status": "dispatched",
                "dispatched_at": "2024-01-01T00:00:00Z",
            }
        )
    bad.write_text(
        json.dumps(
            {
                "run_id": "01bad",
                "stage": "implement",
                "plan_ref": {"provider": "github", "pr_id": "7"},
                "runner": "",
                "kind": "github-actions",
                "status": "dispatched",
                "dispatched_at": "2024-01-01T00:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(CacheError):
        read_dispatch(tmp_path, "01bad")


def test_list_dispatch_records_skips_malformed_nested(tmp_path, capsys):
    write_dispatch(tmp_path, "01good", _dispatch(run_id="01good"))
    bad = run_scratch_dir(tmp_path, "01bad") / "dispatch.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    # A nested run_handle missing required keys -> skipped loudly, not fatal.
    bad.write_text(
        json.dumps(
            {
                "run_id": "01bad",
                "stage": "implement",
                "plan_ref": {"provider": "github", "pr_id": "7", "url": "u", "labels": []},
                "runner": "",
                "kind": "github-actions",
                "status": "dispatched",
                "dispatched_at": "2024-01-01T00:00:00Z",
                "run_handle": {"run_ref": "7"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    records = list_dispatch_records(tmp_path)
    assert [r.run_id for r in records] == ["01good"]
    assert "skipping unreadable dispatch record" in capsys.readouterr().err


def test_list_dispatch_records_skips_invalid_loudly(tmp_path, capsys):
    write_dispatch(tmp_path, "01good", _dispatch(run_id="01good"))
    bad = run_scratch_dir(tmp_path, "01bad") / "dispatch.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text('{"run_id": "01bad"}\n', encoding="utf-8")  # missing required fields
    records = list_dispatch_records(tmp_path)
    assert [r.run_id for r in records] == ["01good"]
    assert "skipping unreadable dispatch record" in capsys.readouterr().err


def test_agent_session_round_trip(tmp_path):
    assert read_agent_session(tmp_path) is None  # absent -> None
    write_agent_session(tmp_path, AgentSession(session_id="s", issue="ENG-1", url=None))
    got = read_agent_session(tmp_path)
    assert got == AgentSession(session_id="s", issue="ENG-1", url=None)
    # A malformed file missing a required field raises CacheError on read.
    cache.agent_session_path(tmp_path).write_text('{"session_id": "s"}\n', encoding="utf-8")
    with pytest.raises(CacheError):
        read_agent_session(tmp_path)


def test_markers(tmp_path):
    assert not has_marker(tmp_path, "pending-learn")
    set_marker(tmp_path, "pending-learn")
    assert has_marker(tmp_path, "pending-learn")
    clear_marker(tmp_path, "pending-learn")
    assert not has_marker(tmp_path, "pending-learn")
    clear_marker(tmp_path, "pending-learn")  # idempotent


# --- atomic_write_text: the exterior atomic-write seam -----------------------------------


def test_atomic_write_text_writes_content(tmp_path):
    path = tmp_path / "out.json"
    atomic_write_text(path, '{"a": 1}\n')
    assert path.read_text(encoding="utf-8") == '{"a": 1}\n'


def test_atomic_write_text_short_over_long_leaves_no_residue(tmp_path):
    # The production tear shape: a shorter payload over a longer one must fully replace it
    # (a bare open-truncate-write interrupted mid-way leaves trailing stray bytes).
    path = tmp_path / "out.json"
    atomic_write_text(path, json.dumps({"key": "a much longer payload value here"}) + "\n")
    atomic_write_text(path, '{"k": 1}\n')
    assert path.read_text(encoding="utf-8") == '{"k": 1}\n'


def test_atomic_write_text_leaves_no_tmp_residue(tmp_path):
    path = tmp_path / "out.json"
    atomic_write_text(path, "content\n")
    assert [p.name for p in tmp_path.iterdir()] == ["out.json"]


def test_atomic_write_text_encoding_failure_cleans_tmp_and_raises(tmp_path):
    # A caller-supplied encoding can fail after mkstemp (UnicodeEncodeError / LookupError);
    # cleanup must cover those too, and the original exception must propagate unchanged.
    path = tmp_path / "out.txt"
    with pytest.raises(UnicodeEncodeError):
        atomic_write_text(path, "caf\u00e9", encoding="ascii")
    with pytest.raises(LookupError):
        atomic_write_text(path, "content", encoding="no-such-codec")
    assert list(tmp_path.iterdir()) == []  # temp files cleaned up, nothing landed


def test_atomic_write_text_failure_cleans_tmp_and_raises_oserror(tmp_path, monkeypatch):
    def boom(self, target):
        raise OSError("replace failed")

    monkeypatch.setattr(cache.Path, "replace", boom)
    path = tmp_path / "out.json"
    with pytest.raises(OSError, match="replace failed"):
        atomic_write_text(path, "content\n")
    assert list(tmp_path.iterdir()) == []  # temp file cleaned up, nothing landed


def test_atomic_write_text_concurrent_writers_never_tear(tmp_path):
    """Interleaving smoke test: two writers race different-length JSON payloads onto one path
    while a reader loop parses every observation — a torn (part-old part-new) file would fail
    ``json.loads``."""
    path = tmp_path / "contested.json"
    short = json.dumps({"n": 1}) + "\n"
    long = json.dumps({"n": 2, "padding": "x" * 512}) + "\n"
    atomic_write_text(path, short)
    errors: list[Exception] = []

    def writer(payload: str) -> None:
        for _ in range(200):
            atomic_write_text(path, payload)

    threads = [threading.Thread(target=writer, args=(p,)) for p in (short, long)]
    for t in threads:
        t.start()
    while any(t.is_alive() for t in threads):
        try:
            assert json.loads(path.read_text(encoding="utf-8")) in ({"n": 1}, json.loads(long))
        except Exception as exc:  # collected and asserted below
            errors.append(exc)
    for t in threads:
        t.join()
    assert not errors, f"reader observed a torn/unreadable file: {errors[:3]}"


# --- corruption posture: malformed JSON -> CacheError (fail-closed readers) --------------


def _assert_corruption_error(excinfo: pytest.ExceptionInfo, path) -> None:
    exc = excinfo.value
    assert isinstance(exc, ValueError)
    assert isinstance(exc, UserFacingCliError)
    assert exc.error_type == "cache_invalid"
    assert str(path) in str(exc)
    assert "move the file aside" in str(exc)


@pytest.mark.parametrize("garbage", ['{"run_id": "01RID", "cons', "not json at all"])
def test_read_handoff_corrupt_raises_cache_error(tmp_path, garbage):
    path = cache.handoff_path(tmp_path, "01RID")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(garbage, encoding="utf-8")
    with pytest.raises(CacheError) as excinfo:
        read_handoff(tmp_path, "01RID")
    _assert_corruption_error(excinfo, path)


def test_mark_handoff_consumed_corrupt_raises_cache_error(tmp_path):
    path = cache.handoff_path(tmp_path, "01RID")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"run_id": "01RID", "cons', encoding="utf-8")
    with pytest.raises(CacheError) as excinfo:
        mark_handoff_consumed(tmp_path, "01RID")
    _assert_corruption_error(excinfo, path)


def test_read_dispatch_corrupt_raises_cache_error(tmp_path):
    path = dispatch_path(tmp_path, "01RID")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"run_id": "01RID", "sta', encoding="utf-8")
    with pytest.raises(CacheError) as excinfo:
        read_dispatch(tmp_path, "01RID")
    _assert_corruption_error(excinfo, path)


def test_read_plan_ref_corrupt_raises_cache_error(tmp_path):
    path = plan_ref_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # The production tear shape: a valid payload followed by trailing stray bytes.
    path.write_text('{"provider": "github"}\n"perk:plan"]}\n', encoding="utf-8")
    with pytest.raises(CacheError) as excinfo:
        read_plan_ref(tmp_path)
    _assert_corruption_error(excinfo, path)
    assert "plan-ref.json" in str(excinfo.value)  # the remediation names the rewrite path


def test_read_plan_ref_invalid_utf8_raises_cache_error(tmp_path):
    # A torn write can end mid-multibyte-sequence → UnicodeDecodeError before JSON parsing;
    # it must translate to the same CacheError posture as malformed JSON.
    path = plan_ref_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'{"provider": "github\xc3')  # truncated 2-byte UTF-8 sequence
    with pytest.raises(CacheError) as excinfo:
        read_plan_ref(tmp_path)
    _assert_corruption_error(excinfo, path)


def test_read_agent_session_corrupt_raises_cache_error(tmp_path):
    path = cache.agent_session_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"session_id": "s", "iss', encoding="utf-8")
    with pytest.raises(CacheError) as excinfo:
        read_agent_session(tmp_path)
    _assert_corruption_error(excinfo, path)


@pytest.mark.parametrize(
    "garbage",
    [b'{"run_id": "01bad", "trunc', b'{"run_id": "01bad\xc3'],
    ids=["truncated-json", "invalid-utf8"],
)
def test_list_dispatch_records_skips_corrupt_records_loudly(tmp_path, capsys, garbage):
    write_dispatch(tmp_path, "01good", _dispatch(run_id="01good"))
    bad = run_scratch_dir(tmp_path, "01bad") / "dispatch.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_bytes(garbage)
    records = list_dispatch_records(tmp_path)
    assert [r.run_id for r in records] == ["01good"]  # corrupt record skipped, never raises
    assert "skipping unreadable dispatch record" in capsys.readouterr().err
