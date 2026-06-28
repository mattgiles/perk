"""Run-cache session-pointer record I/O + the cross-run resolver (contracts.md §8.35)."""

import subprocess
from pathlib import Path

from perk.backends import resolve
from perk.backends.issue_backend import PlanState
from perk.learn.sessions import resolve_plan_sessions
from perk.state import session_pointers
from perk.state.session_pointers import (
    SessionClassPointers,
    SessionPointer,
    SessionPointers,
    read_session_pointers,
    write_session_pointers,
)

_P_MAIN = SessionPointer(
    pi_session_id="sess-pm.jsonl",
    session_file="/abs/sess-pm.jsonl",
    at="2026-06-01T00:00:00Z",
    parent_pi_session_id=None,
)
_I_MAIN = SessionPointer(
    pi_session_id="sess-im.jsonl",
    session_file="/abs/sess-im.jsonl",
    at="2026-06-02T00:00:00Z",
    parent_pi_session_id="parent.jsonl",
)
_I_WORKER = SessionPointer(
    pi_session_id="sess-iw.jsonl",
    session_file="/abs/sess-iw.jsonl",
    at="2026-06-02T00:01:00Z",
    parent_pi_session_id=None,
)


# --- record I/O ------------------------------------------------------------------------------


def test_record_round_trip(tmp_path: Path):
    record = SessionPointers(
        run_id="01RUN_P",
        planning=SessionClassPointers(main=_P_MAIN, worker=None),
    )
    path = write_session_pointers(tmp_path, "01RUN_P", record)
    assert path == session_pointers.session_pointers_path(tmp_path, "01RUN_P")
    again = read_session_pointers(tmp_path, "01RUN_P")
    assert again is not None
    assert again.run_id == "01RUN_P"
    assert again.planning.main == _P_MAIN
    assert again.planning.worker is None
    assert again.implementation.main is None and again.implementation.worker is None


def test_read_absent_is_none(tmp_path: Path):
    assert read_session_pointers(tmp_path, "01NOPE") is None


def test_write_run_id_is_authoritative(tmp_path: Path):
    # `write_session_pointers` keys by the explicit run_id (the record's own is overridden).
    record = SessionPointers(run_id="stale")
    write_session_pointers(tmp_path, "01CANON", record)
    again = read_session_pointers(tmp_path, "01CANON")
    assert again is not None and again.run_id == "01CANON"


def test_lenient_parse_drops_unknown_keys(tmp_path: Path):
    path = session_pointers.session_pointers_path(tmp_path, "01RUN")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"run_id":"01RUN","planning":{"main":{"pi_session_id":"s","session_file":"f",'
        '"at":"t","parent_pi_session_id":null,"extra":"ignored"},"worker":null},'
        '"implementation":{"main":null,"worker":null},"future_field":1}\n',
        encoding="utf-8",
    )
    record = read_session_pointers(tmp_path, "01RUN")
    assert record is not None
    assert record.planning.main is not None
    assert record.planning.main.pi_session_id == "s"


# --- resolver --------------------------------------------------------------------------------


class _FakeBackend:
    def __init__(self, header: dict[str, object] | None):
        self._header = header

    def get_plan(self, *, issue_id: str) -> PlanState | None:
        if self._header is None:
            return None
        return PlanState(
            id=issue_id, url="u", title="t", header=self._header, pr=None, state="OPEN"
        )


def _stub_backend(monkeypatch, header: dict[str, object] | None) -> None:
    monkeypatch.setattr(resolve, "resolve_issue_backend", lambda root: _FakeBackend(header))


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def test_resolver_happy_path(monkeypatch, tmp_path: Path):
    _git_init(tmp_path)
    write_session_pointers(
        tmp_path,
        "01RUN_P",
        SessionPointers(run_id="01RUN_P", planning=SessionClassPointers(main=_P_MAIN)),
    )
    write_session_pointers(
        tmp_path,
        "01RUN_I",
        SessionPointers(
            run_id="01RUN_I",
            implementation=SessionClassPointers(main=_I_MAIN, worker=_I_WORKER),
        ),
    )
    _stub_backend(monkeypatch, {"run_id": "01RUN_P", "impl_run_ids": ["01RUN_I"]})

    resolved = resolve_plan_sessions(tmp_path, "7")
    assert resolved.plan_id == "7"
    assert resolved.planning_run_id == "01RUN_P"
    assert resolved.planning_main.status == "found"
    assert resolved.planning_main.pointer == _P_MAIN
    assert resolved.planning_worker.status == "missing"
    assert len(resolved.implementation) == 1
    impl = resolved.implementation[0]
    assert impl.run_id == "01RUN_I"
    assert impl.main.status == "found" and impl.main.pointer == _I_MAIN
    assert impl.worker.status == "found" and impl.worker.pointer == _I_WORKER


def test_resolver_from_linked_worktree(monkeypatch, tmp_path: Path):
    # The later-session path: records live under the MAIN checkout; the resolver runs from a
    # linked worktree cwd and finds them via main_worktree_root.
    main = tmp_path / "main"
    main.mkdir()
    _git_init(main)
    subprocess.run(["git", "commit", "--allow-empty", "-qm", "init"], cwd=main, check=True)
    wt = tmp_path / "wt"
    subprocess.run(["git", "worktree", "add", "-q", "-b", "feat", str(wt)], cwd=main, check=True)
    # Records written under the MAIN checkout only.
    write_session_pointers(
        main,
        "01RUN_P",
        SessionPointers(run_id="01RUN_P", planning=SessionClassPointers(main=_P_MAIN)),
    )
    _stub_backend(monkeypatch, {"run_id": "01RUN_P", "impl_run_ids": []})

    resolved = resolve_plan_sessions(wt, "7")
    assert resolved.planning_main.status == "found"
    assert resolved.planning_main.pointer == _P_MAIN
    assert resolved.implementation == ()


def test_resolver_degrades_to_missing(monkeypatch, tmp_path: Path):
    _git_init(tmp_path)

    # No plan at all.
    _stub_backend(monkeypatch, None)
    r = resolve_plan_sessions(tmp_path, "7")
    assert r.planning_run_id is None
    assert r.planning_main.status == "missing" and r.planning_main.pointer is None
    assert r.implementation == ()

    # Header lacks run_id and impl_run_ids.
    _stub_backend(monkeypatch, {})
    r = resolve_plan_sessions(tmp_path, "7")
    assert r.planning_run_id is None and r.planning_main.status == "missing"

    # run_id present but the record file is absent / GC'd.
    _stub_backend(monkeypatch, {"run_id": "01GONE", "impl_run_ids": ["01ALSO_GONE"]})
    r = resolve_plan_sessions(tmp_path, "7")
    assert r.planning_run_id == "01GONE"
    assert r.planning_main.status == "missing"
    assert len(r.implementation) == 1
    assert r.implementation[0].main.status == "missing"
    assert r.implementation[0].worker.status == "missing"


def test_resolver_null_slot_is_missing(monkeypatch, tmp_path: Path):
    _git_init(tmp_path)
    # The record exists but the planning.main slot is null → missing (not a guess).
    write_session_pointers(tmp_path, "01RUN_P", SessionPointers(run_id="01RUN_P"))
    _stub_backend(monkeypatch, {"run_id": "01RUN_P", "impl_run_ids": []})
    r = resolve_plan_sessions(tmp_path, "7")
    assert r.planning_run_id == "01RUN_P"
    assert r.planning_main.status == "missing"


def test_resolver_ignores_non_string_impl_run_ids(monkeypatch, tmp_path: Path):
    _git_init(tmp_path)
    _stub_backend(monkeypatch, {"run_id": "01RUN_P", "impl_run_ids": ["01OK", 7, "", None]})
    r = resolve_plan_sessions(tmp_path, "7")
    assert [run.run_id for run in r.implementation] == ["01OK"]
