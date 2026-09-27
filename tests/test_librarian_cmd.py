"""The ``perk librarian`` CLI surface: ``--json`` envelopes, exit codes, in-command option
parsing, and the no-traceback promise for injected filesystem failures (contracts.md §8.75)."""

import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from perk.cli.cli import cli
from perk.library import catalog as cat
from perk.library.layout import LibraryLayout

SOURCE = "https://pi.dev/docs"


def _run(args: list[str]):
    return CliRunner().invoke(cli, ["librarian", *args])


def _stage(repo: Path, name: str = "pi-01ARZ") -> Path:
    staging = LibraryLayout.for_repo(repo).staging / name
    staging.mkdir(parents=True)
    (staging / "index.md").write_text("# pi\n", encoding="utf-8")
    return staging


def _json(result) -> dict[str, Any]:
    assert result.stderr == "", result.stderr
    return json.loads(result.stdout)


@pytest.fixture
def repo(scaffolded_perk_repo, monkeypatch):
    monkeypatch.chdir(scaffolded_perk_repo)
    return scaffolded_perk_repo


def test_group_help_lists_the_three_verbs():
    result = _run(["--help"])
    assert result.exit_code == 0
    for verb in ("list", "record", "remove"):
        assert verb in result.output


def test_list_json_on_an_empty_library(repo):
    result = _run(["list", "--json"])
    assert result.exit_code == 0
    payload = _json(result)
    assert payload == {
        "success": True,
        "error_type": None,
        "message": None,
        "library_root": str(LibraryLayout.for_repo(repo).root),
        "catalog_present": False,
        "entries": [],
        "uncatalogued": [],
        "staging": [],
    }


def test_list_json_on_a_populated_library(repo):
    staging = _stage(repo)
    assert (
        _run(["record", "--publish", str(staging), "--slug", "pi", "--source", SOURCE]).exit_code
        == 0
    )
    layout = LibraryLayout.for_repo(repo)
    (layout.root / "hunk").mkdir()
    (layout.staging / "half").mkdir()
    result = _run(["list", "--json"])
    assert result.exit_code == 0
    payload = _json(result)
    assert payload["catalog_present"] is True
    [entry] = payload["entries"]
    assert list(entry) == [
        "kind",
        "slug",
        "source",
        "path",
        "present",
        "ref",
        "added_at",
        "checked_at",
        "checked_age_seconds",
        "stale_after",
        "evidence",
        "drifted",
        "status",
    ]
    assert entry["path"] == str(layout.docs_entry_dir("pi"))
    assert entry["status"] == "unknown"
    [orphan] = payload["uncatalogued"]
    assert orphan["name"] == "hunk"
    assert orphan["hint"].startswith("perk librarian record --adopt ")
    assert payload["staging"] == [{"name": "half", "path": str(layout.staging / "half")}]


def test_list_human_render(repo):
    staging = _stage(repo)
    _run(["record", "--publish", str(staging), "--slug", "pi", "--source", SOURCE])
    (LibraryLayout.for_repo(repo).root / "hunk").mkdir()
    result = _run(["list"])
    assert result.exit_code == 0
    assert result.stdout == ""
    assert "library: " in result.stderr
    assert "unknown" in result.stderr and "never checked" in result.stderr
    assert "uncatalogued:" in result.stderr
    assert "perk librarian record --adopt" in result.stderr


def test_list_human_render_of_an_absent_library(repo):
    result = _run(["list"])
    assert result.exit_code == 0
    assert "(absent)" in result.stderr


def test_record_publish_and_refusal_envelopes(repo):
    staging = _stage(repo)
    result = _run(
        [
            "record",
            "--publish",
            str(staging),
            "--slug",
            "pi",
            "--source",
            SOURCE,
            "--stale-after",
            "7d",
            "--json",
        ]
    )
    assert result.exit_code == 0
    payload = _json(result)
    assert payload["action"] == "publish"
    assert payload["replaced_previous"] is False
    assert payload["warnings"] == []
    assert payload["entry"]["stale_after"] == 604_800
    again = _stage(repo, "pi-02")
    result = _run(["record", "--publish", str(again), "--slug", "pi", "--source", SOURCE, "--json"])
    assert result.exit_code == 1
    refusal = _json(result)
    assert refusal["success"] is False
    assert refusal["error_type"] == "slug_exists"


def test_record_adopt_envelope_and_human_render(repo):
    layout = LibraryLayout.for_repo(repo)
    original = layout.root / "hunk"
    original.mkdir(parents=True)
    result = _run(["record", "--adopt", str(original), "--kind", "docs", "--source", SOURCE])
    assert result.exit_code == 0
    assert f"adopted hunk → {layout.docs_entry_dir('hunk')}" in result.stderr


@pytest.mark.parametrize(
    ("args", "error_type"),
    [
        (
            ["--publish", "x", "--slug", "pi", "--source", SOURCE, "--kind", "source"],
            "invalid_kind",
        ),
        (["--publish", "x", "--adopt", "y", "--source", SOURCE], "invalid_input"),
        (["--source", SOURCE], "invalid_input"),
        (["--publish", "x", "--source", SOURCE], "invalid_input"),
        (["--publish", "x", "--slug", "pi"], "invalid_input"),
        (["--adopt", "y", "--source", SOURCE, "--replace"], "invalid_input"),
        (["--adopt", "y", "--source", SOURCE, "--accept-failures"], "invalid_input"),
        (["--publish", "x", "--slug", "pi", "--source", "ftp://x"], "invalid_source"),
        (["--publish", "x", "--slug", "pi", "--source", "pi.dev/docs"], "invalid_source"),
        (["--publish", "x", "--slug", "pi", "--source", "https://[::1"], "invalid_source"),
        (
            ["--publish", "x", "--slug", "pi", "--source", SOURCE, "--stale-after", "7w"],
            "invalid_stale_after",
        ),
        (
            ["--publish", "x", "--slug", "pi", "--source", SOURCE, "--stale-after", "0d"],
            "invalid_stale_after",
        ),
        (["--publish", "x", "--slug", "Pi", "--source", SOURCE], "invalid_slug"),
    ],
)
def test_record_input_refusals(repo, args, error_type):
    result = _run(["record", *args, "--json"])
    assert result.exit_code == 1
    assert _json(result)["error_type"] == error_type


def test_record_not_a_repo_exits_2(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = _run(["record", "--publish", "x", "--slug", "pi", "--source", SOURCE, "--json"])
    assert result.exit_code == 2
    assert _json(result)["error_type"] == "not_a_repo"


def test_remove_ok_and_not_found(repo):
    staging = _stage(repo)
    _run(["record", "--publish", str(staging), "--slug", "pi", "--source", SOURCE])
    result = _run(["remove", "pi", "--json"])
    assert result.exit_code == 0
    payload = _json(result)
    assert payload == {
        "success": True,
        "error_type": None,
        "message": None,
        "slug": "pi",
        "kind": "docs",
        "path": str(LibraryLayout.for_repo(repo).docs_entry_dir("pi")),
        "content_removed": True,
    }
    result = _run(["remove", "pi", "--json"])
    assert result.exit_code == 1
    assert _json(result)["error_type"] == "entry_not_found"
    human = _run(["remove", "pi"])
    assert "Error:" in human.stderr


def test_remove_human_render(repo):
    staging = _stage(repo)
    _run(["record", "--publish", str(staging), "--slug", "pi", "--source", SOURCE])
    result = _run(["remove", "pi"])
    assert result.exit_code == 0
    assert "removed pi (docs)" in result.stderr


def _assert_io_error_envelope(result) -> None:
    assert result.exit_code == 1
    assert "Traceback" not in result.stderr
    payload = _json(result)
    assert payload["success"] is False
    assert payload["error_type"] == "io_error"


def test_injected_rename_failure_is_an_envelope(repo, monkeypatch):
    staging = _stage(repo)

    def fake_rename(src, dst, *args, **kwargs):
        raise PermissionError(13, "Permission denied (injected)", str(src))

    monkeypatch.setattr(os, "rename", fake_rename)
    result = _run(
        ["record", "--publish", str(staging), "--slug", "pi", "--source", SOURCE, "--json"]
    )
    _assert_io_error_envelope(result)


def test_injected_rmtree_failure_is_an_envelope(repo, monkeypatch):
    staging = _stage(repo)
    _run(["record", "--publish", str(staging), "--slug", "pi", "--source", SOURCE])

    def fake_rmtree(path, *args, **kwargs):
        raise PermissionError(13, "Permission denied (injected)", str(path))

    monkeypatch.setattr(shutil, "rmtree", fake_rmtree)
    _assert_io_error_envelope(_run(["remove", "pi", "--json"]))


def test_injected_lock_mkdir_failure_is_an_envelope(repo, monkeypatch):
    staging = _stage(repo)
    real_mkdir = Path.mkdir

    def fake_mkdir(self, *args, **kwargs):
        if self.name == "workflow":
            raise PermissionError(13, "Permission denied (injected)", str(self))
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fake_mkdir)
    result = _run(
        ["record", "--publish", str(staging), "--slug", "pi", "--source", SOURCE, "--json"]
    )
    _assert_io_error_envelope(result)
    assert "library lock" in _json(result)["message"]
    assert (staging / "index.md").is_file()
    assert cat.load_catalog(LibraryLayout.for_repo(repo)) == cat.Catalog()
