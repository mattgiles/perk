"""`perk/cli/seed_file.py`: local-file seeding shared by the adoption cold doors (§8.33)."""

from pathlib import Path

import pytest

from perk.cli.ensure import UserFacingCliError
from perk.cli.seed_file import detect_seed_file, read_seed_file, render_seed_file_scratch


def test_detect_existing_file_returns_resolved_path(tmp_path: Path):
    f = tmp_path / "notes.md"
    f.write_text("hello", encoding="utf-8")
    detected = detect_seed_file(str(f))
    assert detected == f.resolve()


def test_detect_relative_path_against_cwd(tmp_path: Path, monkeypatch):
    f = tmp_path / "notes.md"
    f.write_text("hello", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert detect_seed_file("notes.md") == f.resolve()


def test_detect_missing_returns_none(tmp_path: Path):
    assert detect_seed_file(str(tmp_path / "nope.md")) is None
    assert detect_seed_file("123") is None
    assert detect_seed_file("path/to/missing.md") is None


def test_detect_directory_returns_none(tmp_path: Path):
    assert detect_seed_file(str(tmp_path)) is None


def test_read_seed_file_ok(tmp_path: Path):
    f = tmp_path / "notes.md"
    f.write_text("the work to plan", encoding="utf-8")
    assert read_seed_file(f) == "the work to plan"


def test_read_seed_file_non_utf8_errors(tmp_path: Path):
    f = tmp_path / "bin.md"
    f.write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(UserFacingCliError) as exc:
        read_seed_file(f)
    assert exc.value.error_type == "seed_file_error"


def test_read_seed_file_empty_errors(tmp_path: Path):
    f = tmp_path / "empty.md"
    f.write_text("   \n\t\n", encoding="utf-8")
    with pytest.raises(UserFacingCliError) as exc:
        read_seed_file(f)
    assert exc.value.error_type == "seed_file_error"


def test_read_seed_file_unreadable_errors(tmp_path: Path):
    missing = tmp_path / "gone.md"
    with pytest.raises(UserFacingCliError) as exc:
        read_seed_file(missing)
    assert exc.value.error_type == "seed_file_error"


def test_render_scratch_writes_wrapped_data(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    src = tmp_path / "notes.md"
    src.write_text("ignored", encoding="utf-8")
    scratch = render_seed_file_scratch(repo, src, "the seed content")
    assert scratch.name.startswith("seed-file-notes-")
    assert "/" not in scratch.name
    assert scratch.parent == repo / ".perk" / "workflow" / "scratch"
    text = scratch.read_text(encoding="utf-8")
    assert "<untrusted_seed_file>" in text and "</untrusted_seed_file>" in text
    assert "the seed content" in text


def test_render_scratch_same_stem_distinct_hashes(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    a = tmp_path / "a" / "notes.md"
    b = tmp_path / "b" / "notes.md"
    a.parent.mkdir()
    b.parent.mkdir()
    a.write_text("x", encoding="utf-8")
    b.write_text("y", encoding="utf-8")
    scratch_a = render_seed_file_scratch(repo, a, "x")
    scratch_b = render_seed_file_scratch(repo, b, "y")
    assert scratch_a.name != scratch_b.name


def test_render_scratch_sanitizes_stem(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    src = tmp_path / "my notes (draft).md"
    src.write_text("x", encoding="utf-8")
    scratch = render_seed_file_scratch(repo, src, "x")
    stem_part = scratch.name[len("seed-file-") :].rsplit("-", 1)[0]
    assert stem_part == "my_notes__draft_"
