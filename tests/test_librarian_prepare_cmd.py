"""``perk librarian prepare docs|refresh … --json`` through the real CLI — the ``run_librarian``
tool's worker (contracts.md §8.75(k)).

``CliRunner`` over a scaffolded consumer repo (the managed gitignore block) with the converter
probe faked at ``docs_session.which``, the crawl script planted at the skill's delivery read path
and the launch seam spied (the worker must never launch). Expected commands are rebuilt here from
the inputs, never read back from the worker's own plan object.
"""

import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from _library_upstream import REPO_REF, upstream
from click.testing import CliRunner

from perk.cli.cli import cli
from perk.library import docs_session
from perk.library.layout import LibraryLayout
from perk.run import launch

__all__ = ["upstream"]  # the fixture, re-exported so pytest collects it here

SCRIPT_REL = Path(".agents/skills/librarian/scripts/copy_docs_to_markdown.py")
URL = "https://d.example/docs/start"
PI_SOURCE = "https://pi.dev/docs"
ENVELOPE_KEYS = [
    "success",
    "error_type",
    "message",
    "action",
    "url",
    "slug",
    "scope_prefix",
    "staging_dir",
    "main_root",
    "current_dir",
    "replace",
    "crawl_command",
    "publish_command",
    "warnings",
]


def _run(args: list[str]):
    return CliRunner().invoke(cli, ["librarian", *args])


def _layout(repo: Path) -> LibraryLayout:
    return LibraryLayout.for_repo(repo)


def _staging_children(repo: Path) -> list[str]:
    staging = _layout(repo).staging
    return sorted(child.name for child in staging.iterdir()) if staging.exists() else []


@pytest.fixture
def converters(monkeypatch: pytest.MonkeyPatch) -> dict[str, str | None]:
    found: dict[str, str | None] = {"curl": "/usr/bin/curl", "html2markdown": "/usr/bin/h2m"}
    monkeypatch.setattr(docs_session, "which", lambda tool: found.get(tool))
    return found


@pytest.fixture
def launches(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    sink: list[dict[str, Any]] = []
    monkeypatch.setattr(launch, "launch_stage", lambda **kwargs: sink.append(kwargs))
    return sink


@pytest.fixture
def repo(scaffolded_perk_repo, monkeypatch, converters, launches) -> Path:
    monkeypatch.chdir(scaffolded_perk_repo)
    script = scaffolded_perk_repo / SCRIPT_REL
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("# the crawl script\n", encoding="utf-8")
    return scaffolded_perk_repo


def _publish_pi(repo: Path, *, scope_prefix: str | None = None) -> Path:
    staging = _layout(repo).staging / "pi-src"
    staging.mkdir(parents=True)
    (staging / "index.md").write_text("# pi\n", encoding="utf-8")
    if scope_prefix is not None:
        inventory = {"seed_url": PI_SOURCE, "scope_prefix": scope_prefix, "pages": []}
        (staging / "sources.json").write_text(json.dumps(inventory), encoding="utf-8")
    result = _run(["record", "--publish", str(staging), "--slug", "pi", "--source", PI_SOURCE])
    assert result.exit_code == 0, result.stderr
    return _layout(repo).docs_entry_dir("pi")


def _json(result) -> dict[str, Any]:
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


# --- prepare docs ----------------------------------------------------------------------------


def test_prepare_docs_claims_staging_and_emits_the_plan(repo, launches):
    payload = _json(_run(["prepare", "docs", URL, "--json"]))
    layout = _layout(repo)
    staging = layout.staging / "d"
    assert list(payload) == ENVELOPE_KEYS
    assert payload["success"] is True
    assert payload["error_type"] is None
    assert payload["action"] == "add-docs"
    assert payload["url"] == URL
    assert payload["slug"] == "d"
    assert payload["scope_prefix"] == ""
    assert payload["staging_dir"] == str(staging)
    assert staging.is_dir() and list(staging.iterdir()) == []
    assert payload["main_root"] == str(layout.main_root)
    assert payload["current_dir"] is None
    assert payload["replace"] is False
    crawl = shlex.split(payload["crawl_command"])
    assert crawl == [sys.executable, str(layout.main_root / SCRIPT_REL), URL, str(staging)]
    publish = shlex.split(payload["publish_command"])
    assert publish[-1] == "--json"
    assert "--replace" not in publish
    assert publish == [
        "perk",
        "librarian",
        "record",
        "--publish",
        str(staging),
        "--slug",
        "d",
        "--source",
        URL,
        "--json",
    ]
    assert payload["warnings"] == []
    assert launches == []


def test_prepare_docs_honors_slug_and_scope_prefix(repo):
    payload = _json(
        _run(["prepare", "docs", URL, "--slug", "dee", "--scope-prefix", "/", "--json"])
    )
    assert payload["slug"] == "dee"
    assert payload["scope_prefix"] == "/"
    crawl = shlex.split(payload["crawl_command"])
    assert crawl[-2:] == ["--scope-prefix", "/"]
    assert payload["staging_dir"] == str(_layout(repo).staging / "dee")


def test_prepare_docs_accepts_the_equals_form_of_scope_prefix(repo):
    payload = _json(_run(["prepare", "docs", URL, "--scope-prefix=/docs/", "--json"]))
    assert payload["scope_prefix"] == "/docs/"


def test_two_prepares_claim_distinct_staging_dirs(repo):
    first = _json(_run(["prepare", "docs", URL, "--json"]))
    second = _json(_run(["prepare", "docs", URL, "--json"]))
    assert Path(first["staging_dir"]).name == "d"
    assert Path(second["staging_dir"]).name == "d-2"
    assert _staging_children(repo) == ["d", "d-2"]


@pytest.mark.parametrize(
    ("args", "error_type"),
    [
        (["ftp://d.example/docs"], "invalid_source"),
        (["d.example/docs"], "invalid_source"),
        ([URL, "--slug", "Bad"], "invalid_slug"),
        (["https://-bad.example/docs"], "invalid_slug"),
        ([URL, "--scope-prefix", "../x"], "invalid_input"),
        ([URL, "--scope-prefix", " "], "invalid_input"),
    ],
)
def test_prepare_docs_input_refusals_claim_nothing(repo, launches, args, error_type):
    result = _run(["prepare", "docs", *args, "--json"])
    assert result.exit_code == 1, result.output
    assert json.loads(result.stdout)["error_type"] == error_type
    assert _staging_children(repo) == []
    assert launches == []


def test_prepare_docs_refuses_a_catalogued_slug(repo):
    _publish_pi(repo)
    before = _staging_children(repo)
    result = _run(["prepare", "docs", PI_SOURCE, "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "slug_exists"
    assert _staging_children(repo) == before


def test_prepare_docs_refuses_when_the_skill_is_missing(repo):
    (repo / SCRIPT_REL).unlink()
    result = _run(["prepare", "docs", URL, "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "skill_missing"
    assert _staging_children(repo) == []


def test_prepare_docs_refuses_a_missing_converter(repo, converters):
    converters["html2markdown"] = None
    result = _run(["prepare", "docs", URL, "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "missing_converter"
    assert _staging_children(repo) == []


def test_prepare_docs_refuses_when_the_library_is_not_ignored(repo):
    (repo / ".gitignore").write_text("", encoding="utf-8")
    result = _run(["prepare", "docs", URL, "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "library_not_ignored"
    assert _staging_children(repo) == []


def test_prepare_docs_outside_a_repo_exits_2(tmp_path, monkeypatch, converters, launches):
    monkeypatch.chdir(tmp_path)
    result = _run(["prepare", "docs", URL, "--json"])
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error_type"] == "not_a_repo"
    assert launches == []


def test_prepare_docs_from_a_linked_worktree_claims_under_the_main_checkout(
    repo, tmp_path, monkeypatch
):
    linked = tmp_path / "linked"
    subprocess.run(
        ["git", "worktree", "add", "-q", "-b", "wt", str(linked)],
        cwd=repo,
        check=True,
        capture_output=True,
        timeout=60,
    )
    monkeypatch.chdir(linked)
    payload = _json(_run(["prepare", "docs", URL, "--json"]))
    main = _layout(repo).main_root
    assert payload["main_root"] == str(main)
    staging = main / "docs" / "library" / ".staging" / "d"
    assert payload["staging_dir"] == str(staging)
    assert staging.is_dir()
    assert not (linked / "docs" / "library" / ".staging").exists()


def test_prepare_docs_human_render(repo, launches):
    result = _run(["prepare", "docs", URL])
    assert result.exit_code == 0, result.output
    assert result.stdout == ""
    lines = result.stderr.splitlines()
    assert "slug=d" in lines
    assert f"staging_dir={_layout(repo).staging / 'd'}" in lines
    assert "replace=false" in lines
    assert "current_dir=" in lines
    assert launches == []


# --- prepare refresh -------------------------------------------------------------------------


def test_prepare_refresh_emits_the_replace_plan_with_the_recorded_scope(repo, launches):
    current = _publish_pi(repo, scope_prefix="/docs/")
    payload = _json(_run(["prepare", "refresh", "pi", "--json"]))
    staging = _layout(repo).staging / "pi"
    assert list(payload) == ENVELOPE_KEYS
    assert payload["action"] == "refresh-docs"
    assert payload["url"] == PI_SOURCE
    assert payload["replace"] is True
    assert payload["current_dir"] == str(current)
    assert payload["scope_prefix"] == "/docs/"
    assert shlex.split(payload["crawl_command"])[-2:] == ["--scope-prefix", "/docs/"]
    assert shlex.split(payload["publish_command"])[-2:] == ["--replace", "--json"]
    assert payload["staging_dir"] == str(staging)
    assert staging.is_dir() and list(staging.iterdir()) == []
    assert payload["warnings"] == []
    assert launches == []


def test_prepare_refresh_warns_on_an_unusable_recorded_scope(repo):
    _publish_pi(repo, scope_prefix="../x")
    payload = _json(_run(["prepare", "refresh", "pi", "--json"]))
    assert payload["scope_prefix"] == ""
    assert "--scope-prefix" not in shlex.split(payload["crawl_command"])
    assert len(payload["warnings"]) == 1
    assert "recorded scope prefix '../x'" in payload["warnings"][0]
    human = _run(["prepare", "refresh", "pi"])
    assert (
        "warning: the prior crawl's recorded scope prefix '../x'" in human.stderr.splitlines()[-1]
    )


def test_prepare_refresh_of_an_unknown_slug_is_entry_not_found(repo):
    result = _run(["prepare", "refresh", "ghost", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "entry_not_found"
    assert _staging_children(repo) == []


def test_prepare_refresh_of_a_source_entry_is_entry_not_found(repo, launches, upstream):
    assert _run(["add", "source", REPO_REF]).exit_code == 0
    result = _run(["prepare", "refresh", "widget", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error_type"] == "entry_not_found"
    assert "not a documentation entry" in payload["message"]
    assert _staging_children(repo) == []
    assert launches == []
