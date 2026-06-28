"""The session JSONL export seam (contracts.md §8.35)."""

import shutil
import subprocess
from pathlib import Path

from perk.backends import resolve
from perk.backends.issue_backend import PlanState
from perk.learn.export import export_session_jsonl
from perk.learn.sessions import resolve_plan_sessions
from perk.state.session_pointers import (
    SessionClassPointers,
    SessionPointer,
    SessionPointers,
    write_session_pointers,
)

# A realistic small session JSONL: a `session` header line + a couple of `message` entries.
_FIXTURE_JSONL = (
    '{"type":"session","version":3,"id":"sess-pm","cwd":"/some/worktree"}\n'
    '{"type":"message","role":"user","content":"hello"}\n'
    '{"type":"message","role":"assistant","content":"hi"}\n'
)


def _pointer(session_file: str) -> SessionPointer:
    return SessionPointer(
        pi_session_id="sess-pm.jsonl",
        session_file=session_file,
        at="2026-06-01T00:00:00Z",
        parent_pi_session_id=None,
    )


def test_found_faithful_copy(tmp_path: Path):
    src = tmp_path / "home" / "sess-pm.jsonl"
    src.parent.mkdir(parents=True)
    src.write_text(_FIXTURE_JSONL, encoding="utf-8")
    dest = tmp_path / "out" / "planning-main.jsonl"

    result = export_session_jsonl(_pointer(str(src)), dest)

    assert result.status == "found"
    assert result.artifact == dest
    assert result.source == str(src)
    assert dest.read_bytes() == src.read_bytes()


def test_missing_pointer(tmp_path: Path):
    dest = tmp_path / "out" / "planning-main.jsonl"
    result = export_session_jsonl(None, dest)
    assert result.status == "missing"
    assert result.source is None and result.artifact is None
    assert not dest.exists()


def test_missing_source_file(tmp_path: Path):
    dest = tmp_path / "out" / "planning-main.jsonl"
    result = export_session_jsonl(_pointer(str(tmp_path / "gone.jsonl")), dest)
    assert result.status == "missing"
    assert not dest.exists()


def test_empty_session_file(tmp_path: Path):
    dest = tmp_path / "out" / "planning-main.jsonl"
    result = export_session_jsonl(_pointer(""), dest)
    assert result.status == "missing"
    assert not dest.exists()


def test_os_error_never_raises(tmp_path: Path, monkeypatch, capsys):
    src = tmp_path / "sess-pm.jsonl"
    src.write_text(_FIXTURE_JSONL, encoding="utf-8")
    dest = tmp_path / "out" / "planning-main.jsonl"

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(shutil, "copyfile", _boom)

    result = export_session_jsonl(_pointer(str(src)), dest)

    assert result.status == "missing"
    assert "warning" in capsys.readouterr().err
    assert not dest.exists()


def test_dest_parent_auto_created(tmp_path: Path):
    src = tmp_path / "sess-pm.jsonl"
    src.write_text(_FIXTURE_JSONL, encoding="utf-8")
    dest = tmp_path / "deep" / "nested" / "subdir" / "planning-main.jsonl"

    result = export_session_jsonl(_pointer(str(src)), dest)

    assert result.status == "found"
    assert dest.parent.is_dir()
    assert dest.read_bytes() == src.read_bytes()


# --- composition (resolve → export, end-to-end) ----------------------------------------------


class _FakeBackend:
    def __init__(self, header: dict[str, object]):
        self._header = header

    def get_plan(self, *, issue_id: str) -> PlanState:
        return PlanState(
            id=issue_id, url="u", title="t", header=self._header, pr=None, state="OPEN"
        )


def test_resolve_then_export_end_to_end(tmp_path: Path, monkeypatch):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    # A real on-disk JSONL fixture serves as the captured planning-main session file.
    src = tmp_path / "home" / "sess-pm.jsonl"
    src.parent.mkdir(parents=True)
    src.write_text(_FIXTURE_JSONL, encoding="utf-8")

    write_session_pointers(
        tmp_path,
        "01RUN_P",
        SessionPointers(
            run_id="01RUN_P",
            planning=SessionClassPointers(main=_pointer(str(src))),
        ),
    )
    monkeypatch.setattr(
        resolve,
        "resolve_issue_backend",
        lambda root: _FakeBackend({"run_id": "01RUN_P", "impl_run_ids": []}),
    )

    resolved = resolve_plan_sessions(tmp_path, "7")
    assert resolved.planning_main.status == "found"

    dest = tmp_path / "bundle" / "planning-main.jsonl"
    result = export_session_jsonl(resolved.planning_main.pointer, dest)

    assert result.status == "found"
    assert result.artifact == dest
    assert dest.read_bytes() == src.read_bytes()
