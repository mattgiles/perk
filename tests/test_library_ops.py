"""The librarian worker cores (``perk/library/ops.py``, contracts.md §8.75(e)).

Real filesystem + real git over a scaffolded consumer repo (it carries the managed gitignore
block); failures are injected by monkeypatching ``os.rename`` / the catalog's
``atomic_write_text`` / ``shutil.rmtree`` at a chosen step. Every successful op is also checked
against the cache-only promise: ``git status`` reports nothing under ``docs/``.
"""

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from perk.library import catalog as cat
from perk.library import ops
from perk.library.errors import LibraryError
from perk.library.layout import LibraryLayout

NOW = datetime(2026, 9, 27, 12, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 9, 28, 12, 0, 0, tzinfo=UTC)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, timeout=60
    ).stdout


def _layout(repo: Path) -> LibraryLayout:
    return LibraryLayout.for_repo(repo)


def _stage(repo: Path, name: str = "pi-01ARZ", *, body: str = "# pi\n") -> Path:
    staging = _layout(repo).staging / name
    staging.mkdir(parents=True)
    (staging / "index.md").write_text(body, encoding="utf-8")
    (staging / "guide").mkdir()
    (staging / "guide" / "start.md").write_text("start\n", encoding="utf-8")
    return staging


def _publish(
    repo: Path,
    staging: Path,
    slug: str = "pi",
    *,
    replace: bool = False,
    accept_failures: bool = False,
    stale_after: int | None = None,
    now: datetime = NOW,
) -> ops.RecordOutcome:
    return ops.publish(
        repo,
        staging=staging,
        slug=slug,
        source="https://pi.dev/docs",
        replace=replace,
        accept_failures=accept_failures,
        stale_after=stale_after,
        now=lambda: now,
    )


def _adopt(repo: Path, directory: Path, slug: str | None = None) -> ops.RecordOutcome:
    return ops.adopt(
        repo,
        directory=directory,
        slug=slug,
        source="https://example.com/docs",
        stale_after=None,
        now=lambda: NOW,
    )


def _catalog(repo: Path) -> cat.Catalog:
    return cat.load_catalog(_layout(repo))


def _catalog_bytes(repo: Path) -> bytes | None:
    path = _layout(repo).catalog_path
    return path.read_bytes() if path.exists() else None


def _assert_docs_clean(repo: Path) -> None:
    status = _git(repo, "status", "--porcelain", "--untracked-files=all")
    assert [line for line in status.splitlines() if line[3:].startswith("docs/")] == []


def _refusal(fn: Callable[[], object]) -> LibraryError:
    with pytest.raises(LibraryError) as excinfo:
        fn()
    return excinfo.value


def _source_entry(slug: str = "click") -> cat.Entry:
    return cat.Entry(
        kind="source",
        slug=slug,
        source="https://github.com/org/click",
        path=f"source-code/github.com/org/{slug}",
        added_at="2026-09-01T00:00:00Z",
        stale_after=86_400,
        upstream=cat.SourceUpstream(branch="main", head_sha="abc"),
        ref="v1",
    )


def _seed_source(repo: Path, slug: str = "click") -> Path:
    layout = _layout(repo)
    entry = _source_entry(slug)
    checkout = layout.root / entry.path
    checkout.mkdir(parents=True)
    (checkout / "README").write_text("src\n", encoding="utf-8")
    cat.write_catalog(layout, cat.Catalog(entries=(entry,)))
    return checkout


# --- publish ---------------------------------------------------------------------------------


def test_publish_fresh(scaffolded_perk_repo):
    repo = scaffolded_perk_repo
    staging = _stage(repo)
    outcome = _publish(repo, staging)
    target = _layout(repo).docs_entry_dir("pi")
    assert not staging.exists()
    assert (target / "index.md").read_text(encoding="utf-8") == "# pi\n"
    assert (target / "guide" / "start.md").is_file()
    entry = _catalog(repo).get("pi")
    assert entry is not None
    assert entry.path == "documentation/pi"
    assert entry.kind == "docs"
    assert entry.added_at == "2026-09-27T12:00:00Z"
    assert entry.stale_after == cat.DEFAULT_STALE_AFTER["docs"]
    assert entry.upstream == cat.DocsUpstream(pages=())
    assert (entry.checked_at, entry.evidence, entry.drifted, entry.ref) == (
        None,
        "none",
        False,
        None,
    )
    assert outcome.action == "publish"
    assert outcome.replaced_previous is False
    assert outcome.warnings == ()
    assert outcome.view.status == "unknown"
    assert outcome.view.present is True
    assert outcome.view.absolute_path == target
    _assert_docs_clean(repo)


def test_publish_replace_keeps_added_at_and_drops_the_prior_revision(scaffolded_perk_repo):
    repo = scaffolded_perk_repo
    _publish(repo, _stage(repo), stale_after=3_600)
    staging = _stage(repo, "pi-02", body="# pi v2\n")
    outcome = _publish(repo, staging, replace=True, now=LATER)
    layout = _layout(repo)
    target = layout.docs_entry_dir("pi")
    assert (target / "index.md").read_text(encoding="utf-8") == "# pi v2\n"
    assert not staging.exists()
    assert [p.name for p in layout.documentation.iterdir()] == ["pi"]
    entry = _catalog(repo).get("pi")
    assert entry is not None
    assert entry.added_at == "2026-09-27T12:00:00Z"
    assert entry.stale_after == 3_600  # preserved when not re-specified
    assert outcome.replaced_previous is True
    _assert_docs_clean(repo)


def test_publish_slug_exists_for_a_docs_entry(scaffolded_perk_repo):
    repo = scaffolded_perk_repo
    _publish(repo, _stage(repo))
    staging = _stage(repo, "pi-02")
    error = _refusal(lambda: _publish(repo, staging))
    assert error.error_type == "slug_exists"
    assert "--replace" in str(error)
    assert (staging / "index.md").is_file()


def test_publish_slug_exists_for_a_source_entry(scaffolded_perk_repo):
    repo = scaffolded_perk_repo
    _seed_source(repo, "pi")
    staging = _stage(repo)
    error = _refusal(lambda: _publish(repo, staging))
    assert error.error_type == "slug_exists"
    assert staging.is_dir()


def test_publish_slug_exists_for_an_uncatalogued_target(scaffolded_perk_repo):
    repo = scaffolded_perk_repo
    (_layout(repo).docs_entry_dir("pi")).mkdir(parents=True)
    staging = _stage(repo)
    error = _refusal(lambda: _publish(repo, staging))
    assert error.error_type == "slug_exists"
    assert "not catalogued" in str(error)
    assert staging.is_dir()


def test_publish_replace_without_an_entry(scaffolded_perk_repo):
    repo = scaffolded_perk_repo
    staging = _stage(repo)
    error = _refusal(lambda: _publish(repo, staging, replace=True))
    assert error.error_type == "entry_removed_meanwhile"
    assert staging.is_dir()
    assert _catalog_bytes(repo) is None


def test_publish_replace_refuses_a_cross_kind_collision(scaffolded_perk_repo):
    repo = scaffolded_perk_repo
    checkout = _seed_source(repo, "pi")
    before = _catalog_bytes(repo)
    staging = _stage(repo)
    error = _refusal(lambda: _publish(repo, staging, replace=True))
    assert error.error_type == "kind_mismatch"
    assert "perk librarian remove pi" in str(error)
    assert _catalog_bytes(repo) == before
    assert (checkout / "README").is_file()
    assert staging.is_dir()


def test_publish_replace_refuses_a_symlinked_target(scaffolded_perk_repo, tmp_path_factory):
    repo = scaffolded_perk_repo
    _publish(repo, _stage(repo))
    target = _layout(repo).docs_entry_dir("pi")
    shutil.rmtree(target)
    elsewhere = tmp_path_factory.mktemp("precious")
    (elsewhere / "keep.md").write_text("keep\n", encoding="utf-8")
    target.symlink_to(elsewhere, target_is_directory=True)
    staging = _stage(repo, "pi-02")
    error = _refusal(lambda: _publish(repo, staging, replace=True))
    assert error.error_type == "entry_path_invalid"
    assert staging.is_dir()
    assert (elsewhere / "keep.md").is_file()
    assert target.is_symlink()


def test_publish_staging_not_found(scaffolded_perk_repo):
    repo = scaffolded_perk_repo
    error = _refusal(lambda: _publish(repo, _layout(repo).staging / "nope"))
    assert error.error_type == "staging_not_found"


def test_publish_staging_outside_library(scaffolded_perk_repo, tmp_path_factory):
    repo = scaffolded_perk_repo
    inside_docs = _layout(repo).documentation / "sneaky"
    inside_docs.mkdir(parents=True)
    (inside_docs / "index.md").write_text("x\n", encoding="utf-8")
    elsewhere = tmp_path_factory.mktemp("crawl")
    (elsewhere / "index.md").write_text("x\n", encoding="utf-8")
    for candidate in (inside_docs, elsewhere):
        error = _refusal(lambda candidate=candidate: _publish(repo, candidate))
        assert error.error_type == "staging_outside_library"
        assert (candidate / "index.md").is_file()


def test_publish_staging_invalid_shapes(scaffolded_perk_repo, tmp_path_factory):
    repo = scaffolded_perk_repo
    staging_root = _layout(repo).staging
    outside = tmp_path_factory.mktemp("outside")
    (outside / "secret.md").write_text("s\n", encoding="utf-8")

    linked_file = _stage(repo, "linked-file")
    (linked_file / "secret.md").symlink_to(outside / "secret.md")

    staging_root.mkdir(parents=True, exist_ok=True)
    linked_dir = staging_root / "linked-dir"
    linked_dir.symlink_to(outside, target_is_directory=True)

    no_index = staging_root / "no-index"
    no_index.mkdir()
    (no_index / "page.md").write_text("p\n", encoding="utf-8")

    bad_report = _stage(repo, "bad-report")
    (bad_report / "failed-pages.json").write_text("{not json", encoding="utf-8")

    object_report = _stage(repo, "object-report")
    (object_report / "failed-pages.json").write_text('{"a": 1}', encoding="utf-8")

    for candidate in (linked_file, linked_dir, no_index, bad_report, object_report):
        error = _refusal(lambda candidate=candidate: _publish(repo, candidate))
        assert error.error_type == "staging_invalid", candidate
    assert _catalog_bytes(repo) is None


def test_publish_failed_pages_gate(scaffolded_perk_repo):
    repo = scaffolded_perk_repo
    staging = _stage(repo)
    failures = [{"url": f"https://pi.dev/docs/p{i}", "error": "404"} for i in range(7)]
    (staging / "failed-pages.json").write_text(json.dumps(failures), encoding="utf-8")
    error = _refusal(lambda: _publish(repo, staging))
    assert error.error_type == "staging_failed_pages"
    assert "7 failed page(s)" in str(error)
    assert "+2" in str(error)
    assert staging.is_dir()
    outcome = _publish(repo, staging, accept_failures=True)
    assert not (outcome.view.absolute_path / "failed-pages.json").exists()
    assert outcome.warnings == ()


def test_publish_accepts_an_empty_failed_pages_report(scaffolded_perk_repo):
    repo = scaffolded_perk_repo
    staging = _stage(repo)
    (staging / "failed-pages.json").write_text("[]", encoding="utf-8")
    outcome = _publish(repo, staging)
    assert not (outcome.view.absolute_path / "failed-pages.json").exists()


def test_publish_seeds_page_markers_from_the_inventory(scaffolded_perk_repo):
    repo = scaffolded_perk_repo
    staging = _stage(repo)
    inventory = {
        "seed_url": "https://pi.dev/docs",
        "pages": [
            {"path": "index.md", "source_url": "https://pi.dev/docs"},
            {"path": "guide/start.md", "source_url": "https://pi.dev/docs/start"},
            {"path": "dup.md", "source_url": "https://pi.dev/docs"},
            {"path": "nourl.md"},
        ],
    }
    (staging / "sources.json").write_text(json.dumps(inventory), encoding="utf-8")
    _publish(repo, staging)
    entry = _catalog(repo).get("pi")
    assert entry is not None
    assert entry.upstream == cat.DocsUpstream(
        pages=(
            cat.PageMarker(url="https://pi.dev/docs"),
            cat.PageMarker(url="https://pi.dev/docs/start"),
        )
    )


def test_publish_warns_on_a_malformed_inventory(scaffolded_perk_repo):
    repo = scaffolded_perk_repo
    staging = _stage(repo)
    (staging / "sources.json").write_text("[1, 2", encoding="utf-8")
    outcome = _publish(repo, staging)
    assert len(outcome.warnings) == 1
    assert "sources.json" in outcome.warnings[0]
    assert "recorded with no per-page inventory" in outcome.warnings[0]
    entry = _catalog(repo).get("pi")
    assert entry is not None and entry.upstream == cat.DocsUpstream(pages=())


# --- the rollback ladder ---------------------------------------------------------------------


def _failing_rename(monkeypatch, predicate: Callable[[Path, Path], bool]) -> None:
    real = os.rename

    def fake(src, dst, *args, **kwargs):
        if predicate(Path(src), Path(dst)):
            raise PermissionError(13, "Permission denied (injected)", str(src))
        return real(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "rename", fake)


def _failing_catalog_write(monkeypatch) -> None:
    def fake(path, content, **_kwargs):
        raise PermissionError(13, "Permission denied (injected)", str(path))

    monkeypatch.setattr(cat, "atomic_write_text", fake)


def test_step_b_failure_on_replace_restores_the_prior_revision(scaffolded_perk_repo, monkeypatch):
    repo = scaffolded_perk_repo
    _publish(repo, _stage(repo, body="# v1\n"))
    before = _catalog_bytes(repo)
    staging = _stage(repo, "pi-02", body="# v2\n")
    with monkeypatch.context() as mp:
        _failing_rename(mp, lambda src, _dst: src == staging)
        error = _refusal(lambda: _publish(repo, staging, replace=True))
    assert error.error_type == "io_error"
    assert "the library was restored" in str(error)
    assert str(staging) in str(error)
    target = _layout(repo).docs_entry_dir("pi")
    assert (target / "index.md").read_text(encoding="utf-8") == "# v1\n"
    assert (staging / "index.md").read_text(encoding="utf-8") == "# v2\n"
    assert _catalog_bytes(repo) == before
    assert [p.name for p in _layout(repo).documentation.iterdir()] == ["pi"]
    # Retryable once the injection is lifted.
    _publish(repo, staging, replace=True)
    assert (target / "index.md").read_text(encoding="utf-8") == "# v2\n"


def test_step_c_failure_on_fresh_publish_restores_staging(scaffolded_perk_repo, monkeypatch):
    repo = scaffolded_perk_repo
    staging = _stage(repo)
    with monkeypatch.context() as mp:
        _failing_catalog_write(mp)
        error = _refusal(lambda: _publish(repo, staging))
    assert error.error_type == "io_error"
    assert "writing the catalog" in str(error)
    assert "the library was restored" in str(error)
    assert (staging / "index.md").is_file()
    assert not _layout(repo).docs_entry_dir("pi").exists()
    assert _catalog_bytes(repo) is None
    _publish(repo, staging)
    assert _catalog(repo).get("pi") is not None


def test_step_c_failure_on_replace_restores_both(scaffolded_perk_repo, monkeypatch):
    repo = scaffolded_perk_repo
    _publish(repo, _stage(repo, body="# v1\n"))
    before = _catalog_bytes(repo)
    staging = _stage(repo, "pi-02", body="# v2\n")
    with monkeypatch.context() as mp:
        _failing_catalog_write(mp)
        error = _refusal(lambda: _publish(repo, staging, replace=True, now=LATER))
    assert error.error_type == "io_error"
    target = _layout(repo).docs_entry_dir("pi")
    assert (target / "index.md").read_text(encoding="utf-8") == "# v1\n"
    assert (staging / "index.md").read_text(encoding="utf-8") == "# v2\n"
    assert _catalog_bytes(repo) == before
    assert [p.name for p in _layout(repo).documentation.iterdir()] == ["pi"]
    _publish(repo, staging, replace=True)
    assert (target / "index.md").read_text(encoding="utf-8") == "# v2\n"


def test_step_c_failure_on_adopt_restores_the_directory(scaffolded_perk_repo, monkeypatch):
    repo = scaffolded_perk_repo
    original = _layout(repo).root / "hunk"
    original.mkdir(parents=True)
    (original / "index.md").write_text("# hunk\n", encoding="utf-8")
    with monkeypatch.context() as mp:
        _failing_catalog_write(mp)
        error = _refusal(lambda: _adopt(repo, original))
    assert error.error_type == "io_error"
    assert "directory intact" in str(error)
    assert (original / "index.md").is_file()
    assert not _layout(repo).docs_entry_dir("hunk").exists()
    assert _catalog_bytes(repo) is None
    _adopt(repo, original)
    assert _catalog(repo).get("hunk") is not None


def test_a_failed_rollback_names_the_residue(scaffolded_perk_repo, monkeypatch):
    repo = scaffolded_perk_repo
    _publish(repo, _stage(repo, body="# v1\n"))
    staging = _stage(repo, "pi-02", body="# v2\n")
    with monkeypatch.context() as mp:
        _failing_catalog_write(mp)
        _failing_rename(mp, lambda src, _dst: src.name.startswith(".pi.previous-"))
        error = _refusal(lambda: _publish(repo, staging, replace=True))
    message = str(error)
    assert error.error_type == "io_error"
    assert "rollback failed" in message
    assert "residue" in message
    layout = _layout(repo)
    displaced = [p for p in layout.documentation.iterdir() if p.name.startswith(".pi.previous-")]
    assert len(displaced) == 1
    assert str(displaced[0]) in message
    assert str(staging) in message
    report = ops.list_library(repo, now=lambda: NOW)
    assert displaced[0] in report.uncatalogued


# --- post-commit best-effort warnings --------------------------------------------------------


def test_prior_revision_cleanup_failure_is_a_warning(scaffolded_perk_repo, monkeypatch):
    repo = scaffolded_perk_repo
    _publish(repo, _stage(repo))
    real_rmtree = shutil.rmtree

    def fake_rmtree(path, *args, **kwargs):
        if Path(path).name.startswith(".pi.previous-"):
            raise PermissionError(13, "Permission denied (injected)", str(path))
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(ops.shutil, "rmtree", fake_rmtree)
    outcome = _publish(repo, _stage(repo, "pi-02"), replace=True)
    assert outcome.replaced_previous is True
    assert len(outcome.warnings) == 1
    assert "prior revision left at" in outcome.warnings[0]
    leftover = [
        p for p in _layout(repo).documentation.iterdir() if p.name.startswith(".pi.previous-")
    ]
    assert len(leftover) == 1
    assert leftover[0] in ops.list_library(repo, now=lambda: NOW).uncatalogued


def test_crawl_report_deletion_failure_is_a_warning(scaffolded_perk_repo, monkeypatch):
    repo = scaffolded_perk_repo
    staging = _stage(repo)
    (staging / "failed-pages.json").write_text('["https://pi.dev/x"]', encoding="utf-8")
    real_unlink = Path.unlink

    def fake_unlink(self, *args, **kwargs):
        if self.name == "failed-pages.json":
            raise PermissionError(13, "Permission denied (injected)", str(self))
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fake_unlink)
    outcome = _publish(repo, staging, accept_failures=True)
    assert len(outcome.warnings) == 1
    assert "crawl report left at" in outcome.warnings[0]


# --- adopt -----------------------------------------------------------------------------------


def test_adopt_a_top_level_directory_with_the_default_slug(scaffolded_perk_repo):
    repo = scaffolded_perk_repo
    layout = _layout(repo)
    original = layout.root / "dbt-duckdb"
    original.mkdir(parents=True)
    (original / "index.md").write_text("# dbt\n", encoding="utf-8")
    outcome = _adopt(repo, original)
    assert outcome.action == "adopt"
    assert not original.exists()
    assert (layout.docs_entry_dir("dbt-duckdb") / "index.md").is_file()
    entry = _catalog(repo).get("dbt-duckdb")
    assert entry is not None
    assert entry.path == "documentation/dbt-duckdb"
    assert entry.source == "https://example.com/docs"
    assert entry.added_at == "2026-09-27T12:00:00Z"
    _assert_docs_clean(repo)


def test_adopt_an_orphan_under_documentation_without_moving(scaffolded_perk_repo):
    repo = scaffolded_perk_repo
    layout = _layout(repo)
    orphan = layout.docs_entry_dir("hunk")
    orphan.mkdir(parents=True)
    (orphan / "index.md").write_text("# hunk\n", encoding="utf-8")
    outcome = _adopt(repo, orphan)
    assert outcome.view.absolute_path == orphan
    assert (orphan / "index.md").is_file()
    assert _catalog(repo).get("hunk") is not None


def test_adopt_under_an_explicit_slug(scaffolded_perk_repo):
    repo = scaffolded_perk_repo
    original = _layout(repo).root / "Divio_Docs"
    original.mkdir(parents=True)
    error = _refusal(lambda: _adopt(repo, original))
    assert error.error_type == "invalid_slug"
    assert "--slug" in str(error)
    _adopt(repo, original, slug="divio")
    assert _catalog(repo).get("divio") is not None


def test_adopt_invalid_shapes(scaffolded_perk_repo, tmp_path_factory):
    repo = scaffolded_perk_repo
    layout = _layout(repo)
    layout.staging.mkdir(parents=True)
    linked = layout.root / "linked"
    linked.symlink_to(tmp_path_factory.mktemp("elsewhere"), target_is_directory=True)
    nested = layout.root / "a" / "b"
    nested.mkdir(parents=True)
    inner_link = layout.root / "inner"
    inner_link.mkdir()
    (inner_link / "x.md").symlink_to(tmp_path_factory.mktemp("x") / "x.md")
    for candidate in (layout.staging, linked, nested, inner_link, tmp_path_factory.mktemp("out")):
        error = _refusal(lambda candidate=candidate: _adopt(repo, candidate))
        assert error.error_type == "adopt_invalid", candidate
    error = _refusal(lambda: _adopt(repo, layout.root / "missing"))
    assert error.error_type == "adopt_not_found"


def test_adopt_slug_exists(scaffolded_perk_repo):
    repo = scaffolded_perk_repo
    _publish(repo, _stage(repo))
    original = _layout(repo).root / "pi-copy"
    original.mkdir()
    error = _refusal(lambda: _adopt(repo, original, slug="pi"))
    assert error.error_type == "slug_exists"
    assert original.is_dir()


def test_adopt_refuses_a_live_entry_directory(scaffolded_perk_repo):
    repo = scaffolded_perk_repo
    _publish(repo, _stage(repo))
    before_catalog = _catalog_bytes(repo)
    target = _layout(repo).docs_entry_dir("pi")
    before_listing = sorted(str(p) for p in target.rglob("*"))
    error = _refusal(lambda: _adopt(repo, target, slug="pi2"))
    assert error.error_type == "directory_catalogued"
    assert "perk librarian remove pi" in str(error)
    assert _catalog_bytes(repo) == before_catalog
    assert sorted(str(p) for p in target.rglob("*")) == before_listing


# --- remove ----------------------------------------------------------------------------------


def test_remove_drops_the_entry_then_the_content(scaffolded_perk_repo):
    repo = scaffolded_perk_repo
    _publish(repo, _stage(repo))
    outcome = ops.remove(repo, slug="pi")
    assert outcome.slug == "pi"
    assert outcome.kind == "docs"
    assert outcome.content_removed is True
    assert outcome.absolute_path == _layout(repo).docs_entry_dir("pi")
    assert not outcome.absolute_path.exists()
    assert _catalog(repo).get("pi") is None
    _assert_docs_clean(repo)


def test_remove_a_source_entry_deletes_only_its_leaf(scaffolded_perk_repo):
    repo = scaffolded_perk_repo
    checkout = _seed_source(repo, "click")
    sibling = checkout.parent / "other"
    sibling.mkdir()
    outcome = ops.remove(repo, slug="click")
    assert outcome.kind == "source"
    assert not checkout.exists()
    assert sibling.is_dir()


def test_remove_unknown_entry(scaffolded_perk_repo):
    error = _refusal(lambda: ops.remove(scaffolded_perk_repo, slug="nope"))
    assert error.error_type == "entry_not_found"


def test_remove_refuses_a_symlinked_entry_directory(scaffolded_perk_repo, tmp_path_factory):
    repo = scaffolded_perk_repo
    _publish(repo, _stage(repo))
    target = _layout(repo).docs_entry_dir("pi")
    shutil.rmtree(target)
    elsewhere = tmp_path_factory.mktemp("precious")
    (elsewhere / "keep.md").write_text("keep\n", encoding="utf-8")
    target.symlink_to(elsewhere, target_is_directory=True)
    before = _catalog_bytes(repo)
    error = _refusal(lambda: ops.remove(repo, slug="pi"))
    assert error.error_type == "entry_path_invalid"
    assert _catalog_bytes(repo) == before
    assert (elsewhere / "keep.md").is_file()


@pytest.mark.parametrize("bad_path", ["documentation", "documentation/pi/nested"])
def test_remove_refuses_a_hand_edited_catalog_path(scaffolded_perk_repo, bad_path):
    repo = scaffolded_perk_repo
    _publish(repo, _stage(repo))
    layout = _layout(repo)
    raw = json.loads(layout.catalog_path.read_text(encoding="utf-8"))
    raw["entries"][0]["path"] = bad_path
    layout.catalog_path.write_text(json.dumps(raw), encoding="utf-8")
    error = _refusal(lambda: ops.remove(repo, slug="pi"))
    assert error.error_type == "catalog_malformed"
    assert (layout.docs_entry_dir("pi") / "index.md").is_file()


def test_remove_rmtree_failure_leaves_an_adoptable_orphan(scaffolded_perk_repo, monkeypatch):
    repo = scaffolded_perk_repo
    _publish(repo, _stage(repo))

    def fake_rmtree(path, *args, **kwargs):
        raise PermissionError(13, "Permission denied (injected)", str(path))

    monkeypatch.setattr(ops.shutil, "rmtree", fake_rmtree)
    error = _refusal(lambda: ops.remove(repo, slug="pi"))
    assert error.error_type == "io_error"
    assert "removed from the catalog; content left at" in str(error)
    assert _catalog(repo).get("pi") is None
    target = _layout(repo).docs_entry_dir("pi")
    assert target in ops.list_library(repo, now=lambda: NOW).uncatalogued


# --- list ------------------------------------------------------------------------------------


def test_list_an_absent_library(scaffolded_perk_repo):
    report = ops.list_library(scaffolded_perk_repo, now=lambda: NOW)
    assert report.catalog_present is False
    assert (report.entries, report.uncatalogued, report.staging) == ((), (), ())
    assert report.root == _layout(scaffolded_perk_repo).root


def test_list_reports_entries_uncatalogued_and_staging(scaffolded_perk_repo):
    repo = scaffolded_perk_repo
    layout = _layout(repo)
    _publish(repo, _stage(repo))
    _seed_source_into_catalog = _source_entry("click")
    cat.write_catalog(layout, _catalog(repo).with_entry(_seed_source_into_catalog))
    (layout.root / "hunk").mkdir()
    (layout.root / "linear").mkdir()
    (layout.root / "stray.txt").write_text("x\n", encoding="utf-8")
    (layout.documentation / ".pi.previous-abc").mkdir()
    (layout.staging / "half-crawl").mkdir(parents=True)
    report = ops.list_library(repo, now=lambda: NOW)
    assert report.catalog_present is True
    assert [view.entry.slug for view in report.entries] == ["click", "pi"]
    click_view, pi_view = report.entries
    assert click_view.status == "pinned"
    assert click_view.present is False
    assert pi_view.present is True
    assert pi_view.absolute_path == layout.docs_entry_dir("pi")
    assert report.uncatalogued == (
        layout.root / "hunk",
        layout.root / "linear",
        layout.documentation / ".pi.previous-abc",
    )
    assert report.staging == (layout.staging / "half-crawl",)
    assert all(path.is_absolute() for path in report.uncatalogued)


def test_list_from_a_linked_worktree_reports_the_main_checkout(scaffolded_perk_repo):
    repo = scaffolded_perk_repo
    _publish(repo, _stage(repo))
    linked = repo / ".worktrees" / "wt"
    _git(repo, "worktree", "add", "-q", "-b", "wt", str(linked))
    report = ops.list_library(linked, now=lambda: NOW)
    assert report.root.resolve() == _layout(repo).root.resolve()
    assert report.entries[0].absolute_path.resolve() == _layout(repo).docs_entry_dir("pi").resolve()
    assert report.entries[0].absolute_path.is_absolute()


def test_list_propagates_a_malformed_catalog(scaffolded_perk_repo):
    layout = _layout(scaffolded_perk_repo)
    layout.root.mkdir(parents=True)
    layout.catalog_path.write_text("nope", encoding="utf-8")
    error = _refusal(lambda: ops.list_library(scaffolded_perk_repo, now=lambda: NOW))
    assert error.error_type == "catalog_malformed"


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_list_enumeration_failure_is_io_error(scaffolded_perk_repo):
    layout = _layout(scaffolded_perk_repo)
    layout.documentation.mkdir(parents=True)
    layout.documentation.chmod(0o000)
    try:
        error = _refusal(lambda: ops.list_library(scaffolded_perk_repo, now=lambda: NOW))
    finally:
        layout.documentation.chmod(0o700)
    assert error.error_type == "io_error"
    assert str(error).startswith("list:")
