"""The offline-verifiable half of the docs-doors dogfood (contracts.md §8.75(k)).

The stitched gate: the real door (only the launch seam stubbed) renders the seed, then the
seeded flow is executed offline the way the session would — the crawl through the REAL crawl
script (imported by path from ``skills/librarian/scripts/`` and also planted at the delivery read
path; the fake site replaces the network) and every publish through **the seed's exact command**
(``shlex.split`` of the seeded string, handed to the real CLI). Component behaviour lives in
``test_library_docs_session.py`` / ``test_librarian_docs_door.py``; this asserts the handshakes
between them: door → seed → crawl → publish, a partial fetch, an interrupted curation and a
failed recording.
"""

import json
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from _librarian_site import SCRIPT_PATH, fake_site, http_error, load_script, page, run_script
from click.testing import CliRunner

from perk.cli.cli import cli
from perk.library import catalog as cat
from perk.library import docs_session
from perk.library.layout import LibraryLayout
from perk.run import launch

SCRIPT_REL = Path(".agents/skills/librarian/scripts/copy_docs_to_markdown.py")
SITE = "https://d.example"
SEED = f"{SITE}/docs/start"
COMMAND_RE = re.compile(r"by running exactly: `([^`]+)`")


@pytest.fixture(scope="module")
def script() -> ModuleType:
    return load_script()


@pytest.fixture
def launches(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    sink: list[dict[str, Any]] = []
    monkeypatch.setattr(launch, "launch_stage", lambda **kwargs: sink.append(kwargs))
    return sink


@pytest.fixture
def repo(scaffolded_perk_repo, monkeypatch, launches) -> Path:
    monkeypatch.chdir(scaffolded_perk_repo)
    monkeypatch.setattr(docs_session, "which", lambda tool: f"/usr/bin/{tool}")
    planted = scaffolded_perk_repo / SCRIPT_REL
    planted.parent.mkdir(parents=True)
    shutil.copyfile(SCRIPT_PATH, planted)
    return scaffolded_perk_repo


def _layout(repo: Path) -> LibraryLayout:
    return LibraryLayout.for_repo(repo)


def _status_outside_library(repo: Path) -> list[str]:
    out = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    ).stdout
    return [line for line in out.splitlines() if "docs/library/" not in line]


def _door(launches: list[dict[str, Any]], args: list[str]) -> tuple[str, str]:
    """Invoke one door; return the seed's (crawl, publish) commands."""
    before = len(launches)
    result = CliRunner().invoke(cli, ["librarian", *args])
    assert result.exit_code == 0, result.output
    assert len(launches) == before + 1  # exactly one launch per door invocation
    crawl, publish = COMMAND_RE.findall(launches[-1]["prompt_override"])
    return crawl, publish


def _crawl(repo: Path, script: ModuleType, command: str) -> tuple[int, Path]:
    """Run the seeded crawl command's script + arguments in-process; return (exit, staging)."""
    argv = shlex.split(command)
    assert argv[0] == sys.executable
    assert argv[1] == str(_layout(repo).main_root / SCRIPT_REL)
    return run_script(script, argv[2:]), Path(argv[3])


def _publish(command: str, *extra: str) -> tuple[int, dict[str, Any]]:
    argv = shlex.split(command)
    assert argv[:3] == ["perk", "librarian", "record"]
    result = CliRunner().invoke(cli, [*argv[1:], *extra])
    return result.exit_code, json.loads(result.stdout)


def _site(*, api: str | None = "API") -> dict[str, Any]:
    pages: dict[str, Any] = {
        SEED: page("Start", "/docs/guide", "/docs/api"),
        f"{SITE}/docs/guide": page("Guide"),
        f"{SITE}/docs/api": page(api) if api is not None else http_error(f"{SITE}/docs/api", 500),
    }
    return pages


def _list(repo: Path) -> dict[str, Any]:
    result = CliRunner().invoke(cli, ["librarian", "list", "--json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def _entry(repo: Path, slug: str) -> cat.Entry:
    entry = cat.load_catalog(_layout(repo)).get(slug)
    assert entry is not None
    return entry


def _page_urls(entry: cat.Entry) -> list[str]:
    assert isinstance(entry.upstream, cat.DocsUpstream)
    return [marker.url for marker in entry.upstream.pages]


def test_add_publish_refresh_interrupt_and_failed_recording(repo, script, launches, monkeypatch):
    layout = _layout(repo)
    status = _status_outside_library(repo)

    # 1. Add → publish.
    crawl, publish = _door(launches, ["add", "docs", SEED, "--slug", "d"])
    staging = layout.staging / "d"
    assert staging.is_dir() and list(staging.iterdir()) == []
    fake_site(monkeypatch, script, _site())
    code, crawled_into = _crawl(repo, script, crawl)
    assert code == 0  # an empty pre-existing staging directory is accepted
    assert crawled_into == staging
    code, payload = _publish(publish)
    assert code == 0, payload
    [entry] = _list(repo)["entries"]
    assert entry["slug"] == "d" and entry["present"] is True and entry["status"] == "unknown"
    assert entry["path"] == str(layout.docs_entry_dir("d"))
    first_index = (layout.docs_entry_dir("d") / "index.md").read_bytes()
    assert not staging.exists()
    assert _page_urls(_entry(repo, "d")) == [SEED, f"{SITE}/docs/guide", f"{SITE}/docs/api"]
    assert _status_outside_library(repo) == status

    # 3. Refresh → interrupted curation: the crawl lands, the publish never runs.
    crawl, publish = _door(launches, ["refresh", "d"])
    assert shlex.split(publish)[4] == str(staging)  # `.staging/d` is free again
    assert shlex.split(publish)[-2:] == ["--replace", "--json"]
    fake_site(monkeypatch, script, {**_site(), SEED: page("Start v2", "/docs/guide")})
    code, _ = _crawl(repo, script, crawl)
    assert code == 0
    catalog_bytes = layout.catalog_path.read_bytes()
    entry_before = _entry(repo, "d")
    assert (layout.docs_entry_dir("d") / "index.md").read_bytes() == first_index
    assert [item["name"] for item in _list(repo)["staging"]] == ["d"]
    _door(launches, ["refresh", "d"])  # a second door claims a sibling, never the leftover
    assert (layout.staging / "d-2").is_dir()
    assert (staging / "index.md").is_file()
    assert _entry(repo, "d") == entry_before
    assert _status_outside_library(repo) == status

    # 4. Failed recording: the seed's --replace publish with the catalog write failing.
    def fail_write(path: Path, text: str) -> None:
        raise OSError("disk full")

    with monkeypatch.context() as patch:
        patch.setattr(cat, "atomic_write_text", fail_write)
        code, payload = _publish(publish)
    assert code == 1
    assert payload["error_type"] == "io_error"
    assert (layout.docs_entry_dir("d") / "index.md").read_bytes() == first_index
    assert (staging / "index.md").is_file()
    assert layout.catalog_path.read_bytes() == catalog_bytes
    code, payload = _publish(publish)
    assert code == 0, payload
    assert payload["replaced_previous"] is True
    assert (layout.docs_entry_dir("d") / "index.md").read_bytes() != first_index
    assert _page_urls(_entry(repo, "d")) == [SEED, f"{SITE}/docs/guide"]
    assert not list(layout.documentation.glob(".d.previous-*"))
    assert _status_outside_library(repo) == status


def test_a_partial_fetch_publishes_only_with_accepted_failures(repo, script, launches, monkeypatch):
    layout = _layout(repo)
    status = _status_outside_library(repo)
    crawl, publish = _door(launches, ["add", "docs", SEED, "--slug", "e"])
    fake_site(monkeypatch, script, _site(api=None))
    code, staging = _crawl(repo, script, crawl)
    assert code == 1
    assert json.loads((staging / "failed-pages.json").read_text(encoding="utf-8"))
    code, payload = _publish(publish)
    assert code == 1
    assert payload["error_type"] == "staging_failed_pages"
    assert cat.load_catalog(layout).get("e") is None
    assert (staging / "index.md").is_file()
    code, payload = _publish(publish, "--accept-failures")
    assert code == 0, payload
    assert not (layout.docs_entry_dir("e") / "failed-pages.json").exists()
    assert _page_urls(_entry(repo, "e")) == [SEED, f"{SITE}/docs/guide"]
    assert _status_outside_library(repo) == status


def test_a_root_scope_round_trips_into_the_refresh(repo, script, launches, monkeypatch):
    layout = _layout(repo)
    deep = f"{SITE}/docs/guide/start"
    crawl, publish = _door(launches, ["add", "docs", deep, "--slug", "r", "--scope-prefix", "/"])
    assert shlex.split(crawl)[-2:] == ["--scope-prefix", "/"]
    fake_site(monkeypatch, script, {deep: page("Deep", "/blog/post"), f"{SITE}/blog/post": "x"})
    code, _ = _crawl(repo, script, crawl)
    assert code == 0
    assert _publish(publish)[0] == 0
    inventory = json.loads((layout.docs_entry_dir("r") / "sources.json").read_text("utf-8"))
    assert inventory["scope_prefix"] == "/"
    assert f"{SITE}/blog/post" in _page_urls(_entry(repo, "r"))
    crawl, _ = _door(launches, ["refresh", "r"])
    assert shlex.split(crawl)[-2:] == ["--scope-prefix", "/"]
