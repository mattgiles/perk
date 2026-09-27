"""The `librarian` skill's crawl script (``skills/librarian/scripts/copy_docs_to_markdown.py``,
contracts.md §8.75(j)).

The script ships as a standalone stdlib file (never imported by perk), so it is loaded by path.
The network and the converter are faked at the script's own seams (``fetch_html`` /
``convert_html`` / ``which``); the filesystem is real, and failures are injected by patching
``os.replace`` / ``discard`` or by planting state from the conversion hook — which runs after the
output-directory check and ``mkdir``, just before the page's write.
"""

import json
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from _librarian_site import Redirect as _Redirect
from _librarian_site import SiteValue, load_script
from _librarian_site import fake_site as _fake_site
from _librarian_site import http_error as _http_error
from _librarian_site import page as _page
from _librarian_site import run_script as _run

from perk.library import ops
from perk.library.catalog import DocsUpstream, PageMarker
from perk.library.errors import LibraryError
from perk.library.layout import LibraryLayout

SITE = "https://d.example"
SEED = f"{SITE}/docs/start"
ARTIFACTS = ("failed-pages.json", "sources.json", "index.md")


@pytest.fixture(scope="module")
def script() -> ModuleType:
    return load_script()


def _three_page_site() -> dict[str, SiteValue]:
    return {
        SEED: _page("Start", "/docs/guide/intro", "/docs/api"),
        f"{SITE}/docs/guide/intro": _page("Intro"),
        f"{SITE}/docs/api": _page("API"),
    }


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _inventory_paths(out: Path) -> list[tuple[str, str]]:
    inventory = _read_json(out / "sources.json")
    return [(page["source_url"], page["path"]) for page in inventory["pages"]]


def _temp_files(root: Path) -> list[Path]:
    return [path for path in root.rglob("*") if path.name.endswith(".tmp")]


# --- URL → path mapping ----------------------------------------------------------------------


def test_empty_segments_collapse(script):
    assert script.normalize_segments("//guide//intro/") == ("guide", "intro")
    assert script.markdown_path_for_url(f"{SITE}/docs//guide//intro", "/docs/") == Path(
        "guide/intro.md"
    )


@pytest.mark.parametrize(
    "url_path", ["/docs/./x", "/docs/../x", "/docs/a/../../x", "/docs/a\x00b/x"]
)
def test_dot_and_nul_segments_are_unsafe(script, url_path):
    with pytest.raises(script.UnsafePath):
        script.normalize_segments(url_path)
    with pytest.raises(script.UnsafePath):
        script.markdown_path_for_url(f"{SITE}{url_path}", "/docs/")


@pytest.mark.parametrize(
    ("url_path", "expected"),
    [
        ("/docs/", "docs-home.md"),
        ("/docs/index.html", "docs-home.md"),
        ("/docs/index", "docs-home.md"),
        ("/docs/Index.html", "docs-home.md"),
        ("/docs/INDEX", "docs-home.md"),
        ("/docs/guide/index.html", "guide/index.md"),
        ("/docs/guide/", "guide.md"),
        ("/docs/%2e%2e/x", "%2e%2e/x.md"),
    ],
)
def test_markdown_path_for_url(script, url_path, expected):
    assert script.markdown_path_for_url(f"{SITE}{url_path}", "/docs/") == Path(expected)


def test_reserved_root_names_are_the_artifacts(script):
    assert frozenset(ARTIFACTS) == script.RESERVED_ROOT_NAMES


@pytest.mark.parametrize(
    "url_path",
    [
        "/docs/sources.json/topic",
        "/docs/failed-pages.json/x",
        "/docs/index.md/x",
        "/docs/Sources.JSON/x",
        "/docs/INDEX.MD/x",
    ],
)
def test_paths_beneath_a_reserved_name_are_unsafe(script, url_path):
    with pytest.raises(script.UnsafePath):
        script.markdown_path_for_url(f"{SITE}{url_path}", "/docs/")


def test_a_link_beneath_a_reserved_name_is_rejected(script, monkeypatch, tmp_path, capsys):
    blocked = f"{SITE}/docs/sources.json/topic"
    pages = {SEED: _page("Start", "/docs/sources.json/topic", "/docs/api"), blocked: "x"}
    pages[f"{SITE}/docs/api"] = _page("API")
    fetched = _fake_site(monkeypatch, script, pages)
    out = tmp_path / "out"

    assert _run(script, [SEED, str(out)]) == 0

    assert blocked not in fetched
    assert (out / "sources.json").is_file()
    assert _inventory_paths(out) == [(SEED, "start.md"), (f"{SITE}/docs/api", "api.md")]
    assert f"WARNING: rejected unsafe URL {blocked}" in capsys.readouterr().err


# --- argument and prerequisite refusals --------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        [f"{SITE}/docs/../etc/start"],
        [SEED, "--scope-prefix", "/docs/../"],
        ["ftp://d.example/docs/start"],
        ["/docs/start"],
        [SEED, "--max-pages", "0"],
    ],
)
def test_bad_arguments_exit_2_and_create_nothing(script, monkeypatch, tmp_path, argv):
    fetched = _fake_site(monkeypatch, script, _three_page_site())
    out = tmp_path / "out"
    assert _run(script, [argv[0], str(out), *argv[1:]]) == 2
    assert not out.exists()
    assert fetched == []


def test_missing_html2markdown_exits_2_with_the_install_hint(script, monkeypatch, tmp_path, capsys):
    fetched = _fake_site(monkeypatch, script, _three_page_site())
    monkeypatch.setattr(script, "which", lambda tool: None if tool == "html2markdown" else tool)
    out = tmp_path / "out"
    assert _run(script, [SEED, str(out)]) == 2
    assert "brew install html2markdown" in capsys.readouterr().err
    assert fetched == []
    assert not out.exists()


def test_dry_run_needs_only_curl(script, monkeypatch, tmp_path):
    _fake_site(monkeypatch, script, _three_page_site())
    monkeypatch.setattr(script, "which", lambda tool: None if tool == "html2markdown" else tool)
    assert _run(script, [SEED, str(tmp_path / "out"), "--dry-run"]) == 0

    monkeypatch.setattr(script, "which", lambda tool: None)
    assert _run(script, [SEED, str(tmp_path / "out"), "--dry-run"]) == 2


# --- traversal, reserved names, symlinks -------------------------------------------------------


def test_a_traversal_link_is_rejected_never_fetched(script, monkeypatch, tmp_path, capsys):
    evil = f"{SITE}/docs/guide/../../../etc/x"
    pages = {SEED: _page("Start", evil, "/docs/guide/intro"), f"{SITE}/docs/guide/intro": "x"}
    fetched = _fake_site(monkeypatch, script, pages)
    work = tmp_path / "work"
    out = work / "out"

    assert _run(script, [SEED, str(out)]) == 0

    assert evil not in fetched
    assert fetched == [SEED, f"{SITE}/docs/guide/intro"]
    assert evil not in [url for url, _path in _inventory_paths(out)]
    assert sorted(path.name for path in work.iterdir()) == ["out"]
    assert not any(part == "etc" for path in tmp_path.rglob("*") for part in path.parts)
    assert _read_json(out / "failed-pages.json") == []
    assert f"WARNING: rejected unsafe URL {evil}" in capsys.readouterr().err


def test_an_upstream_index_page_maps_to_docs_home(script, monkeypatch, tmp_path):
    pages = {
        SEED: _page("Start", "/docs/index.html"),
        f"{SITE}/docs/index.html": _page("Upstream home"),
    }
    _fake_site(monkeypatch, script, pages)
    out = tmp_path / "out"

    assert _run(script, [SEED, str(out)]) == 0

    assert _inventory_paths(out) == [
        (SEED, "start.md"),
        (f"{SITE}/docs/index.html", "docs-home.md"),
    ]
    assert (out / "docs-home.md").read_text(encoding="utf-8").startswith("# Upstream home")
    assert (out / "index.md").read_text(encoding="utf-8").startswith("# Documentation Index")


def test_the_scope_roots_index_page_is_a_collision_not_an_overwrite(
    script, monkeypatch, tmp_path, capsys
):
    seed = f"{SITE}/docs/"
    pages = {seed: _page("Home", "/docs/index.html"), f"{SITE}/docs/index.html": _page("Dup")}
    _fake_site(monkeypatch, script, pages)
    out = tmp_path / "out"

    assert _run(script, [seed, str(out), "--scope-prefix", "/docs/"]) == 0

    assert _inventory_paths(out) == [(seed, "docs-home.md")]
    assert (out / "docs-home.md").read_text(encoding="utf-8").startswith("# Home")
    assert (out / "index.md").read_text(encoding="utf-8").startswith("# Documentation Index")
    assert all(path not in ARTIFACTS for _url, path in _inventory_paths(out))
    assert f"WARNING: skipped {SITE}/docs/index.html: path collision with {seed}" in (
        capsys.readouterr().err
    )


def test_a_symlinked_output_dir_is_refused(script, monkeypatch, tmp_path):
    fetched = _fake_site(monkeypatch, script, _three_page_site())
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    out = tmp_path / "out"
    out.symlink_to(elsewhere, target_is_directory=True)

    assert _run(script, [SEED, str(out)]) == 2

    assert list(elsewhere.iterdir()) == []
    assert fetched == []


def test_write_contained_refuses_a_symlinked_component(script, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (out / "guide").symlink_to(elsewhere, target_is_directory=True)

    with pytest.raises(script.UnsafePath):
        script.write_contained(out, out.resolve(), Path("guide/intro.md"), "x")

    assert list(elsewhere.iterdir()) == []


def test_write_contained_refuses_a_symlinked_target(script, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    victim = tmp_path / "victim.md"
    victim.write_text("original\n", encoding="utf-8")
    (out / "page.md").symlink_to(victim)

    with pytest.raises(script.UnsafePath):
        script.write_contained(out, out.resolve(), Path("page.md"), "x")

    assert victim.read_text(encoding="utf-8") == "original\n"
    assert _temp_files(out) == []


def test_a_symlink_planted_mid_crawl_is_a_write_failure(script, monkeypatch, tmp_path):
    out = tmp_path / "out"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    def plant(index: int) -> None:
        if index == 1:  # converting guide/intro: the directory check and mkdir already ran
            (out / "guide").symlink_to(elsewhere, target_is_directory=True)

    _fake_site(monkeypatch, script, _three_page_site(), on_convert=plant)

    assert _run(script, [SEED, str(out)]) == 1

    report = _read_json(out / "failed-pages.json")
    assert [(item["url"], item["stage"]) for item in report] == [
        (f"{SITE}/docs/guide/intro", "write")
    ]
    assert list(elsewhere.iterdir()) == []
    assert _inventory_paths(out) == [(SEED, "start.md"), (f"{SITE}/docs/api", "api.md")]


# --- partial crawls ---------------------------------------------------------------------------


def test_a_failed_fetch_is_reported_and_the_rest_is_copied(script, monkeypatch, tmp_path):
    pages = _three_page_site()
    pages[f"{SITE}/docs/guide/intro"] = _http_error(f"{SITE}/docs/guide/intro", 500)
    _fake_site(monkeypatch, script, pages)
    out = tmp_path / "out"

    assert _run(script, [SEED, str(out)]) == 1

    assert _read_json(out / "failed-pages.json") == [
        {
            "url": f"{SITE}/docs/guide/intro",
            "stage": "fetch",
            "reason": "exit 22: curl: (22) The requested URL returned error: 500",
        }
    ]
    assert (out / "start.md").is_file()
    assert (out / "api.md").is_file()
    assert not (out / "guide").exists()
    assert _inventory_paths(out) == [(SEED, "start.md"), (f"{SITE}/docs/api", "api.md")]
    assert (out / "index.md").is_file()


def test_a_failed_conversion_is_a_convert_record(script, monkeypatch, tmp_path):
    def fail_second(index: int) -> None:
        if index == 1:
            raise subprocess.CalledProcessError(1, ["html2markdown"], stderr="parse error\n")

    _fake_site(monkeypatch, script, _three_page_site(), on_convert=fail_second)
    out = tmp_path / "out"

    assert _run(script, [SEED, str(out)]) == 1

    assert _read_json(out / "failed-pages.json") == [
        {"url": f"{SITE}/docs/guide/intro", "stage": "convert", "reason": "exit 1: parse error"}
    ]
    assert not (out / "guide" / "intro.md").exists()


def _failing_replace(monkeypatch, script, target_name: str) -> None:
    real_replace = script.os.replace

    def replace(src, dst):
        if Path(dst).name == target_name:
            raise OSError(28, "No space left on device")
        real_replace(src, dst)

    monkeypatch.setattr(script.os, "replace", replace)


def test_a_failed_write_leaves_no_partial_target(script, monkeypatch, tmp_path):
    _fake_site(monkeypatch, script, _three_page_site())
    _failing_replace(monkeypatch, script, "intro.md")
    out = tmp_path / "out"

    assert _run(script, [SEED, str(out)]) == 1

    assert _read_json(out / "failed-pages.json") == [
        {"url": f"{SITE}/docs/guide/intro", "stage": "write", "reason": "No space left on device"}
    ]
    assert not (out / "guide" / "intro.md").exists()
    assert _temp_files(out) == []
    assert (out / "start.md").is_file()
    assert (out / "api.md").is_file()
    assert _inventory_paths(out) == [(SEED, "start.md"), (f"{SITE}/docs/api", "api.md")]
    assert (out / "index.md").is_file()


def test_an_undiscardable_temp_file_aborts_with_exit_2(script, monkeypatch, tmp_path, capsys):
    _fake_site(monkeypatch, script, _three_page_site())
    _failing_replace(monkeypatch, script, "intro.md")

    def discard(path: Path) -> None:
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(script, "discard", discard)
    out = tmp_path / "out"

    assert _run(script, [SEED, str(out)]) == 2

    leftovers = _temp_files(out)
    assert len(leftovers) == 1
    err = capsys.readouterr().err
    assert "ERROR:" in err
    assert str(leftovers[0]) in err
    assert not (out / "index.md").exists()


class _Interrupted(BaseException):
    pass


@pytest.mark.parametrize(
    ("index_href", "written"),
    [
        (None, ["start.md"]),
        # On a case-insensitive filesystem `Index.md` would be the entrypoint itself.
        ("/docs/Index.html", ["docs-home.md", "start.md"]),
    ],
)
def test_an_interrupted_crawl_is_unpublishable(
    script, monkeypatch, scaffolded_perk_repo, index_href, written
):
    pages = _three_page_site()
    if index_href is not None:
        pages[SEED] = _page("Start", index_href, "/docs/guide/intro", "/docs/api")
        pages[f"{SITE}{index_href}"] = _page("Upstream home")

    def interrupt(index: int) -> None:
        if index == len(written):
            raise _Interrupted

    _fake_site(monkeypatch, script, pages, on_convert=interrupt)
    staging = LibraryLayout.for_repo(scaffolded_perk_repo).staging / "site"

    with pytest.raises(_Interrupted):
        script.main([SEED, str(staging)])

    assert sorted(path.name for path in staging.iterdir()) == written
    assert not any(path.name.casefold() == "index.md" for path in staging.iterdir())
    with pytest.raises(LibraryError) as excinfo:
        _publish(scaffolded_perk_repo, staging, accept_failures=True)
    assert excinfo.value.error_type == "staging_invalid"


@pytest.mark.parametrize("artifact", ARTIFACTS)
def test_a_failed_artifact_write_aborts_before_the_entrypoint(
    script, monkeypatch, scaffolded_perk_repo, capsys, artifact
):
    _fake_site(monkeypatch, script, _three_page_site())
    _failing_replace(monkeypatch, script, artifact)
    staging = LibraryLayout.for_repo(scaffolded_perk_repo).staging / "site"

    assert _run(script, [SEED, str(staging)]) == 2

    assert not (staging / "index.md").exists()
    assert not (staging / artifact).exists()
    assert _temp_files(staging) == []
    assert f"ERROR: could not write {staging / artifact}" in capsys.readouterr().err
    with pytest.raises(LibraryError) as excinfo:
        _publish(scaffolded_perk_repo, staging, accept_failures=True)
    assert excinfo.value.error_type == "staging_invalid"


# --- a clean crawl ----------------------------------------------------------------------------


def test_a_clean_crawl_writes_every_artifact_atomically_and_last(script, monkeypatch, tmp_path):
    _fake_site(monkeypatch, script, _three_page_site())
    written: list[str] = []
    real_write = script.write_contained

    def spy_write(output_dir, output_root, rel_path, text):
        written.append(rel_path.as_posix())
        real_write(output_dir, output_root, rel_path, text)

    replaced: list[tuple[str, str]] = []
    real_replace = script.os.replace

    def spy_replace(src, dst):
        replaced.append((Path(src).name, Path(dst).name))
        real_replace(src, dst)

    monkeypatch.setattr(script, "write_contained", spy_write)
    monkeypatch.setattr(script.os, "replace", spy_replace)
    out = tmp_path / "out"

    assert _run(script, [SEED, str(out)]) == 0

    assert written == ["start.md", "guide/intro.md", "api.md", *ARTIFACTS]
    index_replace = [src for src, dst in replaced if dst == "index.md"]
    assert len(index_replace) == 1
    assert index_replace[0].startswith(".index.md.")
    assert index_replace[0].endswith(".tmp")
    assert _read_json(out / "failed-pages.json") == []
    assert _read_json(out / "sources.json") == {
        "seed_url": SEED,
        "scope_prefix": "/docs/",
        "pages": [
            {"source_url": SEED, "path": "start.md"},
            {"source_url": f"{SITE}/docs/guide/intro", "path": "guide/intro.md"},
            {"source_url": f"{SITE}/docs/api", "path": "api.md"},
        ],
    }
    assert "[/docs/guide/intro](guide/intro.md)" in (out / "start.md").read_text(encoding="utf-8")
    assert "- [Intro](guide/intro.md)" in (out / "index.md").read_text(encoding="utf-8")
    assert _temp_files(out) == []


def test_dry_run_writes_nothing(script, monkeypatch, tmp_path, capsys):
    _fake_site(monkeypatch, script, _three_page_site())
    out = tmp_path / "out"

    assert _run(script, [SEED, str(out), "--dry-run"]) == 0

    assert not out.exists()
    assert f"{SITE}/docs/guide/intro -> guide/intro.md" in capsys.readouterr().out


def test_dry_run_exits_1_when_a_discovery_fetch_fails(script, monkeypatch, tmp_path):
    pages = _three_page_site()
    pages[f"{SITE}/docs/api"] = _http_error(f"{SITE}/docs/api")
    _fake_site(monkeypatch, script, pages)
    out = tmp_path / "out"

    assert _run(script, [SEED, str(out), "--dry-run"]) == 1

    assert not out.exists()


# --- the output directory ---------------------------------------------------------------------


@pytest.mark.parametrize("occupant", ["non-empty-dir", "file"])
def test_an_occupied_output_path_is_refused(script, monkeypatch, tmp_path, capsys, occupant):
    fetched = _fake_site(monkeypatch, script, _three_page_site())
    out = tmp_path / "out"
    if occupant == "file":
        out.write_text("x\n", encoding="utf-8")
    else:
        out.mkdir()
        (out / "old.md").write_text("old\n", encoding="utf-8")

    assert _run(script, [SEED, str(out)]) == 2

    assert "refusing to write into a non-empty directory" in capsys.readouterr().err
    assert fetched == []


def test_an_empty_output_dir_is_accepted(script, monkeypatch, tmp_path):
    _fake_site(monkeypatch, script, _three_page_site())
    out = tmp_path / "out"
    out.mkdir()

    assert _run(script, [SEED, str(out)]) == 0

    assert (out / "index.md").is_file()


# --- path collisions --------------------------------------------------------------------------


def test_two_urls_for_one_path_keep_the_first(script, monkeypatch, tmp_path, capsys):
    pages = {
        SEED: _page("Start", "/docs/a.html", "/docs/a"),
        f"{SITE}/docs/a.html": _page("A html"),
        f"{SITE}/docs/a": _page("A bare"),
    }
    _fake_site(monkeypatch, script, pages)
    out = tmp_path / "out"

    assert _run(script, [SEED, str(out)]) == 0

    assert _inventory_paths(out) == [(SEED, "start.md"), (f"{SITE}/docs/a.html", "a.md")]
    assert (out / "a.md").read_text(encoding="utf-8").startswith("# A html")
    assert f"WARNING: skipped {SITE}/docs/a: path collision with {SITE}/docs/a.html" in (
        capsys.readouterr().err
    )


def test_paths_differing_only_in_case_collide(script, monkeypatch, tmp_path, capsys):
    pages = {
        SEED: _page("Start", "/docs/API", "/docs/api.md/intro", "/docs/api"),
        f"{SITE}/docs/API": _page("API upper"),
        f"{SITE}/docs/api.md/intro": _page("Intro"),
        f"{SITE}/docs/api": _page("API lower"),
    }
    _fake_site(monkeypatch, script, pages)
    out = tmp_path / "out"

    assert _run(script, [SEED, str(out)]) == 0

    assert _inventory_paths(out) == [(SEED, "start.md"), (f"{SITE}/docs/API", "API.md")]
    err = capsys.readouterr().err
    assert f"WARNING: skipped {SITE}/docs/api: path collision with {SITE}/docs/API" in err
    assert f"WARNING: skipped {SITE}/docs/api.md/intro: path collision with {SITE}/docs/API" in err


@pytest.mark.parametrize(
    ("links", "kept", "skipped"),
    [
        (("/docs/a", "/docs/a.md/b"), ("/docs/a", "a.md"), "/docs/a.md/b"),
        (("/docs/a.md/b", "/docs/a"), ("/docs/a.md/b", "a.md/b.md"), "/docs/a"),
    ],
)
def test_a_file_directory_conflict_skips_the_later_page(
    script, monkeypatch, tmp_path, links, kept, skipped
):
    pages = {
        SEED: _page("Start", *links),
        f"{SITE}/docs/a": _page("A"),
        f"{SITE}/docs/a.md/b": _page("B"),
    }
    _fake_site(monkeypatch, script, pages)
    out = tmp_path / "out"

    assert _run(script, [SEED, str(out)]) == 0

    assert _inventory_paths(out) == [(SEED, "start.md"), (f"{SITE}{kept[0]}", kept[1])]
    assert f"{SITE}{skipped}" not in [url for url, _path in _inventory_paths(out)]
    assert (out / kept[1]).is_file()


# --- the fetch command ------------------------------------------------------------------------


def test_fetch_html_fails_on_http_errors_and_follows_bounded_redirects(script, monkeypatch):
    commands: list[list[str]] = []

    def run_text(command: list[str], stdin_text: str | None = None) -> str:
        commands.append(command)
        return "<html></html>"

    monkeypatch.setattr(script, "run_text", run_text)
    script.fetch_html(SEED)

    (argv,) = commands
    assert argv[0] == "curl"
    assert argv[-1] == SEED
    assert "--fail" in argv
    assert "--location" in argv
    assert argv[argv.index("--max-redirs") + 1] == "5"


def test_fetch_html_reports_the_effective_url(script, monkeypatch):
    effective = f"{SITE}/docs/guide/"

    def run_text(command: list[str], stdin_text: str | None = None) -> str:
        write_out = command[command.index("--write-out") + 1]
        assert "%{url_effective}" in write_out
        return "<html>body</html>" + write_out.replace("%{url_effective}", effective)

    monkeypatch.setattr(script, "run_text", run_text)

    fetched = script.fetch_html(f"{SITE}/docs/guide")

    assert (fetched.html, fetched.url) == ("<html>body</html>", effective)


def test_relative_links_resolve_against_the_redirect_destination(script, monkeypatch, tmp_path):
    pages: dict[str, SiteValue] = {
        SEED: _page("Start", "/docs/guide"),
        f"{SITE}/docs/guide": _Redirect(to=f"{SITE}/docs/guide/", html=_page("Guide", "intro")),
        f"{SITE}/docs/guide/intro": _page("Intro"),
        f"{SITE}/docs/intro": _page("Wrong page"),
    }
    fetched = _fake_site(monkeypatch, script, pages)
    out = tmp_path / "out"

    assert _run(script, [SEED, str(out)]) == 0

    assert f"{SITE}/docs/intro" not in fetched
    assert _inventory_paths(out) == [
        (SEED, "start.md"),
        (f"{SITE}/docs/guide", "guide.md"),
        (f"{SITE}/docs/guide/intro", "guide/intro.md"),
    ]


# --- the staging handshake round trip -----------------------------------------------------------


def _publish(repo: Path, staging: Path, *, accept_failures: bool) -> ops.RecordOutcome:
    return ops.publish(
        repo,
        staging=staging,
        slug="site",
        source=SEED,
        replace=False,
        accept_failures=accept_failures,
        stale_after=None,
    )


def test_the_handshakes_round_trip_through_record_publish(
    script, monkeypatch, scaffolded_perk_repo
):
    repo = scaffolded_perk_repo
    pages = _three_page_site()
    pages[f"{SITE}/docs/guide/intro"] = _http_error(f"{SITE}/docs/guide/intro")
    _fake_site(monkeypatch, script, pages)
    layout = LibraryLayout.for_repo(repo)
    staging = layout.staging / "site"

    assert _run(script, [SEED, str(staging)]) == 1

    with pytest.raises(LibraryError) as excinfo:
        _publish(repo, staging, accept_failures=False)
    assert excinfo.value.error_type == "staging_failed_pages"

    outcome = _publish(repo, staging, accept_failures=True)

    upstream = outcome.view.entry.upstream
    assert isinstance(upstream, DocsUpstream)
    assert upstream.pages == (PageMarker(url=SEED), PageMarker(url=f"{SITE}/docs/api"))
    published = layout.docs_entry_dir("site")
    assert not (published / "failed-pages.json").exists()
    assert (published / "sources.json").is_file()
    assert (published / "index.md").is_file()
    assert outcome.view.status == "unknown"
