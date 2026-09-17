"""Run-cache session-pointer record I/O + the cross-run resolver (contracts.md §8.35)."""

import subprocess
from pathlib import Path

import pytest

from perk.backends import resolve
from perk.backends.issue_backend import PlanState
from perk.learn.sessions import resolve_plan_sessions
from perk.state import session_pointers
from perk.state.session_pointers import (
    RunSessionEntry,
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

# The cross-plane byte-pin fixtures — the SAME literals live in
# extension/substrate/sessionPointers.test.ts (ASCII content; the schema/order contract).
_RID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
_SA = RunSessionEntry(
    pi_session_id="a.jsonl",
    session_file="/abs/a.jsonl",
    cwd="/abs/wt-a",
    at="2026-06-01T00:00:00.000Z",
)
_SB = RunSessionEntry(
    pi_session_id="b.jsonl",
    session_file="/abs/b.jsonl",
    cwd="/abs/wt-b",
    at="2026-06-02T00:00:00.000Z",
)
_EMPTY_RECORD_BYTES = "\n".join(
    [
        "{",
        '  "run_id": "01RID",',
        '  "planning": {',
        '    "main": {',
        '      "pi_session_id": "pm.jsonl",',
        '      "session_file": "/abs/pm.jsonl",',
        '      "parent_pi_session_id": null,',
        '      "at": "2026-06-01T00:00:00Z"',
        "    },",
        '    "worker": null',
        "  },",
        '  "implementation": {',
        '    "main": null,',
        '    "worker": null',
        "  },",
        '  "sessions": []',
        "}",
        "",
    ]
)
_TWO_SESSIONS_BYTES = "\n".join(
    [
        "{",
        f'  "run_id": "{_RID}",',
        '  "planning": {',
        '    "main": null,',
        '    "worker": null',
        "  },",
        '  "implementation": {',
        '    "main": null,',
        '    "worker": null',
        "  },",
        '  "sessions": [',
        "    {",
        '      "pi_session_id": "a.jsonl",',
        '      "session_file": "/abs/a.jsonl",',
        '      "cwd": "/abs/wt-a",',
        '      "at": "2026-06-01T00:00:00.000Z"',
        "    },",
        "    {",
        '      "pi_session_id": "b.jsonl",',
        '      "session_file": "/abs/b.jsonl",',
        '      "cwd": "/abs/wt-b",',
        '      "at": "2026-06-02T00:00:00.000Z"',
        "    }",
        "  ]",
        "}",
        "",
    ]
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


def test_read_corrupt_record_degrades_to_none(tmp_path: Path):
    # A corrupt/unreadable record never raises (the resolver contract) — it degrades to None.
    path = session_pointers.session_pointers_path(tmp_path, "01BAD")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json at all", encoding="utf-8")
    assert read_session_pointers(tmp_path, "01BAD") is None
    # A schema-mismatched (valid JSON, missing run_id) record also degrades to None.
    path.write_text('{"planning": {}}', encoding="utf-8")
    assert read_session_pointers(tmp_path, "01BAD") is None


def test_write_run_id_is_authoritative(tmp_path: Path):
    # `write_session_pointers` keys by the explicit run_id (the record's own is overridden).
    record = SessionPointers(run_id="stale")
    write_session_pointers(tmp_path, "01CANON", record)
    again = read_session_pointers(tmp_path, "01CANON")
    assert again is not None and again.run_id == "01CANON"


# --- the `sessions` list -------------------------------------------------------------------


def test_sessions_round_trip_beside_the_class_slots(tmp_path: Path):
    record = SessionPointers(
        run_id=_RID,
        planning=SessionClassPointers(main=_P_MAIN),
        implementation=SessionClassPointers(main=_I_MAIN, worker=_I_WORKER),
        sessions=(_SA, _SB),
    )
    write_session_pointers(tmp_path, _RID, record)
    again = read_session_pointers(tmp_path, _RID)
    assert again is not None
    assert again.sessions == (_SA, _SB)
    assert again.planning.main == _P_MAIN
    assert again.implementation.main == _I_MAIN
    assert again.implementation.worker == _I_WORKER


def test_legacy_record_without_sessions_reads_as_empty(tmp_path: Path):
    path = session_pointers.session_pointers_path(tmp_path, _RID)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'{{"run_id":"{_RID}","planning":{{"main":null,"worker":null}},'
        '"implementation":{"main":null,"worker":null}}\n',
        encoding="utf-8",
    )
    record = read_session_pointers(tmp_path, _RID)
    assert record is not None
    assert record.sessions == ()


def test_written_bytes_match_the_ts_pins(tmp_path: Path):
    # The Python writer and the TS `serialize` emit the SAME bytes for ASCII content: key order,
    # 2-space indent, trailing newline, `"sessions": []` for an empty list.
    pm = SessionPointer(
        pi_session_id="pm.jsonl",
        session_file="/abs/pm.jsonl",
        at="2026-06-01T00:00:00Z",
        parent_pi_session_id=None,
    )
    empty = write_session_pointers(
        tmp_path,
        "01RID",
        SessionPointers(run_id="01RID", planning=SessionClassPointers(main=pm)),
    )
    assert empty.read_text(encoding="utf-8") == _EMPTY_RECORD_BYTES
    two = write_session_pointers(tmp_path, _RID, SessionPointers(run_id=_RID, sessions=(_SA, _SB)))
    assert two.read_text(encoding="utf-8") == _TWO_SESSIONS_BYTES


def test_sessions_entry_extra_key_is_dropped_leniently(tmp_path: Path):
    path = session_pointers.session_pointers_path(tmp_path, _RID)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'{{"run_id":"{_RID}","sessions":[{{"pi_session_id":"a.jsonl",'
        '"session_file":"/abs/a.jsonl","cwd":"/abs/wt-a","at":"2026-06-01T00:00:00.000Z",'
        '"future":true}]}\n',
        encoding="utf-8",
    )
    record = read_session_pointers(tmp_path, _RID)
    assert record is not None
    assert record.sessions == (_SA,)


@pytest.mark.parametrize(
    "entry",
    [
        # Missing `cwd`.
        '{"pi_session_id":"a.jsonl","session_file":"/abs/a.jsonl","at":"2026-06-01T00:00:00.000Z"}',
        # `at` without milliseconds — not the toISOString() form.
        '{"pi_session_id":"a.jsonl","session_file":"/abs/a.jsonl","cwd":"/w","at":"2026-06-01T00:00:00Z"}',
        '{"pi_session_id":"a.jsonl","session_file":"/abs/a.jsonl","cwd":"/w","at":"yesterday"}',
    ],
)
def test_malformed_sessions_entry_degrades_the_record_to_none(tmp_path: Path, capsys, entry: str):
    path = session_pointers.session_pointers_path(tmp_path, _RID)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'{{"run_id":"{_RID}","sessions":[{entry}]}}\n', encoding="utf-8")
    assert read_session_pointers(tmp_path, _RID) is None
    err = capsys.readouterr().err
    assert "skipping unreadable session-pointers record" in err and str(path) in err


def test_invalid_utf8_record_degrades_to_none_without_raising(tmp_path: Path, capsys):
    # The DECODE stage: invalid bytes raise UnicodeDecodeError (a ValueError that is NOT a
    # JSONDecodeError) — the reader's boundary must cover it, or "never raises" is false.
    path = session_pointers.session_pointers_path(tmp_path, _RID)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'\xff\xfe{"run_id":')
    assert read_session_pointers(tmp_path, _RID) is None
    err = capsys.readouterr().err
    assert "skipping unreadable session-pointers record" in err and str(path) in err


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
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "perk tests"], cwd=path, check=True)


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

    # A corrupt record file degrades to missing too (the resolver never crashes).
    corrupt = session_pointers.session_pointers_path(tmp_path, "01CORRUPT")
    corrupt.parent.mkdir(parents=True, exist_ok=True)
    corrupt.write_text("{not json", encoding="utf-8")
    _stub_backend(monkeypatch, {"run_id": "01CORRUPT", "impl_run_ids": []})
    r = resolve_plan_sessions(tmp_path, "7")
    assert r.planning_run_id == "01CORRUPT"
    assert r.planning_main.status == "missing"


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
