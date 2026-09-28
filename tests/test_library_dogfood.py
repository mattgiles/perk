"""The stitched perk-library dogfood gate — the offline-verifiable half of Part A of
``docs/design/archive/perk-library-dogfood.md``.

Component behaviour lives in ``test_library_ops.py`` / ``test_librarian_cmd.py`` /
``test_library_check.py`` / ``test_doctor.py`` / ``test_init_library_readme.py``; this file
asserts the *sequences* the live run follows, one fixture each: adopting perk's own flat,
uncatalogued mirrors by the printed hints; the source half of the ``check`` matrix (pin,
throttle, drift, refresh); and first use from a consumer's main checkout and a linked worktree.

The network is the offline bare upstream of ``_library_upstream.py`` (git ``insteadOf``), and
every story commits the scaffold's init output first: that untracked baseline is a fixture fact,
not a library observation. Every clean-tree assertion uses ``--untracked-files=all`` — default
porcelain collapses a new directory to its first untracked ancestor.
"""

import json
import shlex
from pathlib import Path
from typing import Any

import pytest
from _library_upstream import ENTRY_PATH, REPO_REF, run_git, upstream
from click.testing import CliRunner

from perk.cli.cli import cli
from perk.convergence.doctor import _library_check, run_doctor
from perk.convergence.init import LIBRARY_README
from perk.library.catalog import DocsUpstream, SourceUpstream, load_catalog
from perk.library.layout import LibraryLayout

__all__ = ["upstream"]  # the fixture, re-exported so pytest collects it here

PLANNOTATOR_PAGES = (
    "https://docs.plannotator.ai/open-source",
    "https://docs.plannotator.ai/open-source/start/installation",
)


def _run(args: list[str]):
    return CliRunner().invoke(cli, ["librarian", *args])


def _json(args: list[str]) -> dict[str, Any]:
    result = _run(args)
    assert result.exit_code == 0, result.output
    assert result.stderr == "", result.stderr
    return json.loads(result.stdout)


def _status(repo: Path) -> str:
    return run_git(repo, "status", "--porcelain", "--untracked-files=all")


def _commit_scaffold(repo: Path) -> None:
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-qm", "perk init wiring")
    assert _status(repo) == ""


def _check_named(report, name: str):
    return next(check for check in report.checks if check.name == name)


def _only_result(payload: dict[str, Any]) -> dict[str, Any]:
    [result] = payload["results"]
    return result


@pytest.fixture
def repo(scaffolded_perk_repo, monkeypatch):
    monkeypatch.chdir(scaffolded_perk_repo)
    return scaffolded_perk_repo


def _seed_flat_mirrors(layout: LibraryLayout) -> None:
    """perk's own main-checkout shape: flat mirrors from before the catalog existed."""
    (layout.root / "pi").mkdir(parents=True)
    (layout.root / "pi" / "index.md").write_text("# pi\n", encoding="utf-8")
    plannotator = layout.root / "plannotator"
    plannotator.mkdir()
    (plannotator / "index.md").write_text("# plannotator\n", encoding="utf-8")
    inventory = {
        "copied_on": "2026-09-07",
        "seed_url": PLANNOTATOR_PAGES[0],
        "scope_prefix": "/open-source/",
        "pages": [
            {
                "path": "docs-home.md",
                "source_url": PLANNOTATOR_PAGES[0],
                "markdown_url": f"{PLANNOTATOR_PAGES[0]}/index.md",
                "title": "Plannotator OSS Documentation",
            },
            {
                "path": "start/installation.md",
                "source_url": PLANNOTATOR_PAGES[1],
                "markdown_url": f"{PLANNOTATOR_PAGES[1]}.md",
                "title": "Install Plannotator",
            },
        ],
    }
    (plannotator / "sources.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    (layout.root / "dbt-duckdb").mkdir()
    (layout.root / "dbt-duckdb" / "README.md").write_text("# dbt-duckdb\n", encoding="utf-8")
    (layout.staging / "half").mkdir(parents=True)


@pytest.mark.slow
def test_flat_mirrors_adopt_by_the_printed_hints(repo):
    _commit_scaffold(repo)
    layout = LibraryLayout.for_repo(repo)
    layout.root.mkdir(parents=True)
    layout.readme_path.write_text(LIBRARY_README, encoding="utf-8")
    run_git(repo, "add", "docs/library/README.md")
    run_git(repo, "commit", "-qm", "library README")
    _seed_flat_mirrors(layout)
    before = _status(repo)
    assert before == ""

    health = _library_check(repo)
    assert health.status == "info"
    for name in ("pi", "plannotator", "dbt-duckdb", "half"):
        assert name in health.detail

    listed = _json(["list", "--json"])
    assert listed["catalog_present"] is False
    names = sorted(item["name"] for item in listed["uncatalogued"])
    assert names == ["dbt-duckdb", "pi", "plannotator"]
    for item in listed["uncatalogued"]:
        assert item["hint"] == (
            f"perk librarian record --adopt {item['path']} --kind docs --source <url>"
        )

    # Each hint is executable as printed, plus the trailing --json a read-only session appends.
    for item in listed["uncatalogued"]:
        argv = shlex.split(item["hint"])
        assert argv[:2] == ["perk", "librarian"]
        url = f"https://example.test/{item['name']}"
        adopted = _json([*(url if arg == "<url>" else arg for arg in argv[2:]), "--json"])
        assert adopted["action"] == "adopt"
        assert adopted["entry"]["status"] == "unknown"

    after = _json(["list", "--json"])
    assert [entry["slug"] for entry in after["entries"]] == ["dbt-duckdb", "pi", "plannotator"]
    for entry in after["entries"]:
        assert entry["present"] is True
        assert entry["path"] == str(layout.docs_entry_dir(entry["slug"]))
    assert after["uncatalogued"] == []
    assert [staged["name"] for staged in after["staging"]] == ["half"]
    for name in names:
        assert not (layout.root / name).exists()
    # Adoption accepts a mirror with no index.md (publish would refuse one).
    assert (layout.docs_entry_dir("dbt-duckdb") / "README.md").is_file()

    catalog = load_catalog(layout)
    pages: dict[str, tuple[str, ...]] = {}
    for slug in names:
        entry = catalog.get(slug)
        assert entry is not None and isinstance(entry.upstream, DocsUpstream)
        pages[slug] = tuple(page.url for page in entry.upstream.pages)
    assert pages == {"dbt-duckdb": (), "pi": (), "plannotator": PLANNOTATOR_PAGES}

    health = _library_check(repo)
    assert health.status == "info"
    assert health.detail == "staging: half"
    assert _status(repo) == before


def _source_head(layout: LibraryLayout) -> str | None:
    entry = load_catalog(layout).get("widget")
    assert entry is not None and isinstance(entry.upstream, SourceUpstream)
    return entry.upstream.head_sha


@pytest.mark.slow
def test_source_pin_throttle_drift_and_refresh_sequence(repo, upstream):
    _commit_scaffold(repo)
    layout = LibraryLayout.for_repo(repo)
    upstream.tag("v1", "HEAD~1")

    pinned = _json(["add", "source", REPO_REF, "--ref", "v1", "--json"])
    assert pinned["action"] == "cloned"
    assert (pinned["entry"]["ref"], pinned["entry"]["status"]) == ("v1", "pinned")
    never = _only_result(_json(["check", "--json"]))
    assert never["action"] == "pinned"
    assert "never probed" in never["detail"]
    # A rerun without --ref never unpins.
    rerun = _json(["add", "source", REPO_REF, "--json"])
    assert rerun["action"] == "reused"
    assert (rerun["entry"]["ref"], rerun["entry"]["status"]) == ("v1", "pinned")

    # Unpinning is remove + add source. Removal deletes only the leaf.
    _json(["remove", "widget", "--json"])
    assert not (layout.root / ENTRY_PATH).exists()
    assert load_catalog(layout).get("widget") is None
    tracking = _json(["add", "source", REPO_REF, "--json"])
    assert tracking["action"] == "cloned"
    assert (tracking["entry"]["ref"], tracking["entry"]["status"]) == (None, "unknown")

    first = _only_result(_json(["check", "--json"]))
    assert first["action"] == "probed"
    assert first["entry"]["status"] == "fresh"
    assert first["entry"]["checked_at"] is not None
    throttled = _only_result(_json(["check", "--json"]))
    assert throttled["action"] == "recent"
    assert "pass --force" in throttled["detail"]

    advanced = upstream.advance_origin()
    # The throttle window hides upstream drift until it lapses or --force is passed.
    assert _only_result(_json(["check", "--json"]))["action"] == "recent"
    forced = _only_result(_json(["check", "--force", "--json"]))
    assert (forced["action"], forced["entry"]["status"]) == ("probed", "drifted")

    refreshed = _json(["refresh", "widget", "--json"])
    assert refreshed["action"] == "fast_forwarded"
    assert _source_head(layout) == advanced
    settled = _only_result(_json(["check", "--force", "--json"]))
    assert (settled["action"], settled["entry"]["status"]) == ("probed", "fresh")
    assert _status(repo) == ""


@pytest.mark.slow
def test_first_use_from_a_consumer_main_checkout_and_linked_worktree(repo, upstream, monkeypatch):
    _commit_scaffold(repo)
    layout = LibraryLayout.for_repo(repo)
    report = run_doctor(repo, verify=False)
    assert _check_named(report, "library-readme").status == "ok"
    library = _check_named(report, "library")
    assert library.status == "ok"
    assert "absent" in library.message

    upstream.tag("v1", "HEAD~1")
    added = _json(["add", "source", REPO_REF, "--ref", "v1", "--json"])
    assert added["action"] == "cloned"
    assert layout.root.is_dir()
    assert _status(repo) == ""
    readme = _check_named(run_doctor(repo, verify=False), "library-readme")
    assert readme.status == "fail"
    assert readme.remediation == "perk doctor --fix"

    run_doctor(repo, verify=False, fix=True)
    assert layout.readme_path.read_text(encoding="utf-8") == LIBRARY_README
    assert _status(repo) == "?? docs/library/README.md\n"
    uncommitted = _library_check(repo)
    assert (uncommitted.status, uncommitted.message) == (
        "warn",
        "docs/library/README.md is not committed",
    )
    run_git(repo, "add", "docs/library/README.md")
    run_git(repo, "commit", "-qm", "library README")
    committed = _library_check(repo)
    assert (committed.status, committed.message) == ("ok", "library catalogued (1 entries)")

    run_git(repo, "worktree", "add", "-q", "-b", "wt", ".worktrees/wt")
    worktree = repo / ".worktrees" / "wt"
    try:
        # A linked worktree carries only the committed README — its road to the main library.
        checkout_library = worktree / "docs" / "library"
        assert sorted(child.name for child in checkout_library.iterdir()) == ["README.md"]
        assert (checkout_library / "README.md").read_text(encoding="utf-8") == LIBRARY_README

        monkeypatch.chdir(worktree)
        listed = _json(["list", "--json"])
        assert listed["library_root"] == str(layout.root)
        [entry] = listed["entries"]
        assert entry["path"] == added["entry"]["path"] == str(layout.root / ENTRY_PATH)
        assert entry["present"] is True
        assert (Path(entry["path"]) / "f.txt").read_text(encoding="utf-8") == "hi\n"
        again = _json(["add", "source", REPO_REF, "--ref", "v1", "--json"])
        assert again["action"] == "reused"
        assert again["entry"]["path"] == entry["path"]
    finally:
        monkeypatch.chdir(repo)
        run_git(repo, "worktree", "remove", "--force", ".worktrees/wt")
