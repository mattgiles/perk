"""The ``perk librarian`` CLI surface: ``--json`` envelopes, exit codes, in-command option
parsing, and the no-traceback promise for injected filesystem failures (contracts.md §8.75)."""

import json
import os
import shutil
from pathlib import Path
from typing import Any

import httpx
import pytest
from _library_upstream import CLONE_URL, ENTRY_PATH, REPO_REF, upstream
from click.testing import CliRunner

from perk.cli.cli import cli
from perk.cli.commands.librarian import check_cmd
from perk.library import catalog as cat
from perk.library.layout import LibraryLayout

__all__ = ["upstream"]  # the fixture, re-exported so pytest collects it here

SOURCE = "https://pi.dev/docs"
ENTRY_KEYS = [
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


def test_group_help_lists_the_six_verbs():
    result = _run(["--help"])
    assert result.exit_code == 0
    for verb in ("add", "check", "list", "record", "refresh", "remove"):
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
    assert list(entry) == ENTRY_KEYS
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


# --- add source / check / refresh -------------------------------------------------------------


def _publish_pi(repo: Path) -> None:
    staging = _stage(repo)
    result = _run(["record", "--publish", str(staging), "--slug", "pi", "--source", SOURCE])
    assert result.exit_code == 0, result.stderr


def test_add_source_json_envelope_and_rerun(repo, upstream):
    result = _run(["add", "source", REPO_REF, "--json"])
    assert result.exit_code == 0, result.stderr
    payload = _json(result)
    assert list(payload) == ["success", "error_type", "message", "action", "entry"]
    assert payload["action"] == "cloned"
    assert list(payload["entry"]) == ENTRY_KEYS
    assert payload["entry"]["source"] == CLONE_URL
    assert payload["entry"]["path"] == str(LibraryLayout.for_repo(repo).root / ENTRY_PATH)
    assert payload["entry"]["status"] == "unknown"
    assert _json(_run(["add", "source", REPO_REF, "--json"]))["action"] == "reused"


def test_add_source_human_render(repo, upstream):
    upstream.tag("v1", "HEAD~1")
    result = _run(["add", "source", REPO_REF, "--ref", "v1"])
    assert result.exit_code == 0, result.stderr
    assert result.stdout == ""
    checkout = LibraryLayout.for_repo(repo).root / ENTRY_PATH
    assert f"cloned widget at v1 → {checkout}" in result.stderr


@pytest.mark.parametrize(
    ("args", "error_type"),
    [
        (["click"], "invalid_repo_ref"),
        ([REPO_REF, "--stale-after", "7w"], "invalid_stale_after"),
        ([REPO_REF, "--slug", "Widget"], "invalid_slug"),
        ([REPO_REF, "--ref", "v 1"], "invalid_input"),
    ],
)
def test_add_source_input_refusals(repo, args, error_type):
    result = _run(["add", "source", *args, "--json"])
    assert result.exit_code == 1
    assert _json(result)["error_type"] == error_type
    assert not (LibraryLayout.for_repo(repo).root / ENTRY_PATH).exists()


@pytest.mark.parametrize("args", [["add", "source", REPO_REF], ["check"], ["refresh", "widget"]])
def test_network_verbs_outside_a_repo_exit_2(tmp_path, monkeypatch, args):
    monkeypatch.chdir(tmp_path)
    result = _run([*args, "--json"])
    assert result.exit_code == 2
    assert _json(result)["error_type"] == "not_a_repo"


def _failing_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused (injected)", request=request)

    return httpx.MockTransport(handler)


def test_check_json_envelope_exits_0_with_a_failed_result(repo, monkeypatch):
    _publish_pi(repo)
    monkeypatch.setattr(check_cmd, "http_transport", _failing_transport)
    result = _run(["check", "--json"])
    assert result.exit_code == 0, result.stderr
    payload = _json(result)
    assert list(payload) == ["success", "error_type", "message", "results", "warnings"]
    [entry_result] = payload["results"]
    assert list(entry_result) == ["action", "detail", "notes", "entry"]
    assert entry_result["action"] == "failed"
    assert "ConnectError" in entry_result["detail"]
    assert list(entry_result["entry"]) == ENTRY_KEYS
    assert payload["warnings"] == []


# The docs probe's inventory requests (sitemap, its index fallback, llms.txt) at the site root.
INVENTORY_URLS = frozenset(
    f"https://pi.dev/{name}" for name in ("sitemap.xml", "sitemap-index.xml", "llms.txt")
)


@pytest.mark.parametrize(
    ("seed_headers", "evidence", "status"),
    [
        pytest.param({"ETag": '"v1"'}, "strong", "fresh", id="etag-is-strong"),
        pytest.param({}, "none", "unverifiable", id="no-validators-is-unverifiable"),
    ],
)
def test_check_probes_over_the_transport_seam(repo, monkeypatch, seed_headers, evidence, status):
    _publish_pi(repo)
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if str(request.url) == SOURCE:
            return httpx.Response(200, headers=seed_headers)
        return httpx.Response(404)

    monkeypatch.setattr(check_cmd, "http_transport", lambda: httpx.MockTransport(handler))
    result = _run(["check"])
    assert result.exit_code == 0, result.stderr
    [line] = result.stderr.splitlines()
    assert line.split() == ["probed", status, "docs", "pi"]
    assert set(requested) == {SOURCE, *INVENTORY_URLS}
    entry = cat.load_catalog(LibraryLayout.for_repo(repo)).get("pi")
    assert entry is not None and entry.evidence == evidence


def test_check_human_render_lists_notes_and_details(repo, monkeypatch):
    _publish_pi(repo)
    monkeypatch.setattr(check_cmd, "http_transport", _failing_transport)
    result = _run(["check"])
    assert result.exit_code == 0
    lines = result.stderr.splitlines()
    assert lines[0].startswith("failed   unknown      docs   pi")
    assert any(line.startswith("  note: ") for line in lines[1:])


def test_check_unknown_slug_exits_1(repo):
    _publish_pi(repo)
    result = _run(["check", "pi", "nope", "--json"])
    assert result.exit_code == 1
    assert _json(result)["error_type"] == "entry_not_found"


def test_refresh_json_envelope(repo, upstream):
    assert _run(["add", "source", REPO_REF]).exit_code == 0
    result = _run(["refresh", "widget", "--json"])
    assert result.exit_code == 0, result.stderr
    payload = _json(result)
    assert list(payload) == [
        "success",
        "error_type",
        "message",
        "action",
        "detail",
        "previous_head",
        "entry",
    ]
    assert payload["action"] == "up_to_date"
    assert payload["entry"]["status"] == "fresh"
    new = upstream.advance_origin()
    human = _run(["refresh", "widget"])
    assert human.exit_code == 0
    assert f"fast-forwarded widget {payload['previous_head'][:7]}..{new[:7]}" in human.stderr


def test_refresh_docs_entry_needs_a_session(repo):
    # The human form of a docs entry is the refresh door (test_librarian_docs_door.py).
    _publish_pi(repo)
    result = _run(["refresh", "pi", "--json"])
    assert result.exit_code == 1
    payload = _json(result)
    assert payload["error_type"] == "needs_session"
    assert "`perk librarian refresh pi` (without --json)" in payload["message"]


def test_refresh_pinned_entry_is_refused(repo, upstream):
    upstream.tag("v1", "HEAD~1")
    assert _run(["add", "source", REPO_REF, "--ref", "v1"]).exit_code == 0
    result = _run(["refresh", "widget", "--json"])
    assert result.exit_code == 1
    payload = _json(result)
    assert payload["error_type"] == "entry_pinned"
    assert "--ref <new>" in payload["message"]
