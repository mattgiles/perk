"""The cache-only preflight (``perk/library/guard.py``, contracts.md §8.75(d)).

Each guard over a real scaffolded consumer repo (it carries the managed gitignore block), plus
the end-to-end promise that a refused publish — and a refused network worker (``add source``,
``check``, ``refresh``, §8.75(i)) — sees zero filesystem effects: the tree is byte-identical
before/after, no lock file was created (the preflight runs before the lock), and no network
call was made.
"""

import hashlib
import os
import subprocess
from pathlib import Path

import httpx
import pytest

from perk.library import catalog as cat
from perk.library import check, guard, lock, ops, source
from perk.library.errors import LibraryError
from perk.library.layout import LibraryLayout
from perk.substrate import git


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, timeout=60
    ).stdout


def _snapshot(root: Path) -> dict[str, str]:
    """Every path under ``root`` (outside ``.git``) → a content hash / kind marker."""
    shot: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name != ".git"]
        for name in dirnames:
            shot[str(Path(dirpath, name).relative_to(root))] = "dir"
        for name in filenames:
            path = Path(dirpath, name)
            rel = str(path.relative_to(root))
            if path.is_symlink():
                shot[rel] = f"link:{path.readlink()}"
            else:
                shot[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return shot


def _staged(repo: Path, name: str = "pi-01ARZ") -> Path:
    staging = repo / "docs" / "library" / ".staging" / name
    staging.mkdir(parents=True)
    (staging / "index.md").write_text("# pi\n", encoding="utf-8")
    return staging


def _assert_refused_without_effects(repo: Path, error_type: str) -> LibraryError:
    lock.lock_path(repo).unlink(missing_ok=True)
    before_status = _git(repo, "status", "--porcelain", "--ignored")
    before = _snapshot(repo)
    with pytest.raises(LibraryError) as excinfo:
        ops.publish(
            repo,
            staging=repo / "docs" / "library" / ".staging" / "pi-01ARZ",
            slug="pi",
            source="https://pi.dev/docs",
            replace=False,
            accept_failures=False,
            stale_after=None,
        )
    assert excinfo.value.error_type == error_type
    assert _snapshot(repo) == before
    assert _git(repo, "status", "--porcelain", "--ignored") == before_status
    assert not lock.lock_path(repo).exists()
    return excinfo.value


def test_require_real_roots_accepts_real_directories(scaffolded_perk_repo):
    layout = LibraryLayout.for_repo(scaffolded_perk_repo)
    guard.require_real_roots(layout)  # nothing exists yet
    for root in (layout.documentation, layout.source_code, layout.staging):
        root.mkdir(parents=True)
    guard.require_real_roots(layout)


@pytest.mark.parametrize("name", ["documentation", "source-code", ".staging"])
def test_require_real_roots_refuses_a_symlinked_content_root(
    scaffolded_perk_repo, tmp_path_factory, name
):
    layout = LibraryLayout.for_repo(scaffolded_perk_repo)
    layout.root.mkdir(parents=True)
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    (layout.root / name).symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(LibraryError) as excinfo:
        guard.require_real_roots(layout)
    assert excinfo.value.error_type == "library_root_invalid"
    assert name in str(excinfo.value)


def test_require_real_roots_refuses_a_symlinked_library(scaffolded_perk_repo, tmp_path_factory):
    layout = LibraryLayout.for_repo(scaffolded_perk_repo)
    (scaffolded_perk_repo / "docs").mkdir()
    layout.root.symlink_to(tmp_path_factory.mktemp("lib"), target_is_directory=True)
    with pytest.raises(LibraryError) as excinfo:
        guard.require_real_roots(layout)
    assert excinfo.value.error_type == "library_root_invalid"


def test_require_real_roots_refuses_a_symlinked_docs_dir(scaffolded_perk_repo, tmp_path_factory):
    layout = LibraryLayout.for_repo(scaffolded_perk_repo)
    target = tmp_path_factory.mktemp("docs-elsewhere")
    (target / "library").mkdir()
    (scaffolded_perk_repo / "docs").symlink_to(target, target_is_directory=True)
    with pytest.raises(LibraryError) as excinfo:
        guard.require_real_roots(layout)
    assert excinfo.value.error_type == "library_root_invalid"


def test_require_no_tracked_content(scaffolded_perk_repo):
    repo = scaffolded_perk_repo
    layout = LibraryLayout.for_repo(repo)
    layout.root.mkdir(parents=True)
    (layout.root / "README.md").write_text("# lib\n", encoding="utf-8")
    _git(repo, "add", "docs/library/README.md")
    guard.require_no_tracked_content(layout)  # the README alone is allowed
    mirror = layout.root / "pi" / "index.md"
    mirror.parent.mkdir()
    mirror.write_text("# pi\n", encoding="utf-8")
    _git(repo, "add", "-f", "docs/library/pi/index.md")
    # The ignore probe alone would pass: the tracked file IS pattern-ignored.
    guard.require_ignored(layout, guard.probe_paths_for(layout, dirs=[mirror.parent]))
    with pytest.raises(LibraryError) as excinfo:
        guard.require_no_tracked_content(layout)
    assert excinfo.value.error_type == "library_tracked_content"
    assert "docs/library/pi/index.md" in str(excinfo.value)
    assert "docs/library/README.md" not in str(excinfo.value)


def test_require_ignored_passes_with_the_managed_block(scaffolded_perk_repo):
    layout = LibraryLayout.for_repo(scaffolded_perk_repo)
    probes = guard.probe_paths_for(
        layout,
        dirs=[layout.docs_entry_dir("pi"), layout.staging / "x", layout.documentation / ".pi.p"],
    )
    assert probes[0] == "docs/library/documentation/pi/index.md"
    guard.require_ignored(layout, probes)


def test_require_ignored_names_every_missing_probe(scaffolded_perk_repo):
    repo = scaffolded_perk_repo
    (repo / ".gitignore").write_text("/docs/library/catalog.json\n", encoding="utf-8")
    layout = LibraryLayout.for_repo(repo)
    with pytest.raises(LibraryError) as excinfo:
        guard.require_ignored(
            layout, guard.probe_paths_for(layout, dirs=[layout.docs_entry_dir("pi")])
        )
    message = str(excinfo.value)
    assert excinfo.value.error_type == "library_not_ignored"
    assert "docs/library/catalog.json.probe.tmp" in message
    assert ".perk/workflow/library.lock" in message
    assert "docs/library/documentation/pi/index.md" in message
    assert "docs/library/catalog.json," not in message  # the catalog itself IS ignored
    assert "perk init" in message


def test_require_ignored_catches_a_slug_negation(scaffolded_perk_repo):
    repo = scaffolded_perk_repo
    # A single `!…/pi/` line cannot re-include anything under the managed `/docs/library/**`
    # (the excluded parent wins); re-including pi's files takes every ancestor negated.
    with (repo / ".gitignore").open("a", encoding="utf-8") as handle:
        handle.write(
            "!/docs/library/documentation/\n"
            "!/docs/library/documentation/pi/\n"
            "!/docs/library/documentation/pi/**\n"
        )
    layout = LibraryLayout.for_repo(repo)
    dirs = [layout.docs_entry_dir("pi"), layout.docs_entry_dir("qq")]
    with pytest.raises(LibraryError) as excinfo:
        guard.require_ignored(layout, guard.probe_paths_for(layout, dirs=dirs))
    message = str(excinfo.value)
    assert "docs/library/documentation/pi/index.md" in message
    assert "documentation/qq" not in message
    assert "catalog.json" not in message


def test_require_ignored_refuses_without_the_managed_block(git_repo):
    layout = LibraryLayout.for_repo(git_repo)
    with pytest.raises(LibraryError) as excinfo:
        guard.require_ignored(layout, [])
    assert excinfo.value.error_type == "library_not_ignored"


def test_require_unlinked_components(scaffolded_perk_repo, tmp_path_factory):
    layout = LibraryLayout.for_repo(scaffolded_perk_repo)
    layout.documentation.mkdir(parents=True)
    assert (
        guard.require_unlinked_components(layout, "documentation/pi") == layout.documentation / "pi"
    )
    (layout.documentation / "pi").symlink_to(
        tmp_path_factory.mktemp("pi"), target_is_directory=True
    )
    with pytest.raises(LibraryError) as excinfo:
        guard.require_unlinked_components(layout, "documentation/pi")
    assert excinfo.value.error_type == "entry_path_invalid"


# --- a refused publish has zero filesystem effects -------------------------------------------


def test_refused_publish_not_ignored_leaves_no_trace(scaffolded_perk_repo):
    repo = scaffolded_perk_repo
    (repo / ".gitignore").write_text(
        "/docs/library/.staging/\n/docs/library/catalog.json\n", encoding="utf-8"
    )
    _staged(repo)
    _assert_refused_without_effects(repo, "library_not_ignored")


def test_refused_publish_tracked_content_leaves_no_trace(scaffolded_perk_repo):
    repo = scaffolded_perk_repo
    _staged(repo)
    tracked = repo / "docs" / "library" / "hunk" / "index.md"
    tracked.parent.mkdir(parents=True)
    tracked.write_text("# hunk\n", encoding="utf-8")
    _git(repo, "add", "-f", "docs/library/hunk/index.md")
    _assert_refused_without_effects(repo, "library_tracked_content")


def test_refused_publish_symlinked_root_leaves_no_trace(scaffolded_perk_repo, tmp_path_factory):
    repo = scaffolded_perk_repo
    _staged(repo)
    (repo / "docs" / "library" / "documentation").symlink_to(
        tmp_path_factory.mktemp("redirect"), target_is_directory=True
    )
    _assert_refused_without_effects(repo, "library_root_invalid")


# --- the network workers run the same preflight, before any network or write ----------------


def _seed_catalog(repo: Path) -> None:
    layout = LibraryLayout.for_repo(repo)
    mirror = layout.docs_entry_dir("pi")
    mirror.mkdir(parents=True)
    (mirror / "index.md").write_text("# pi\n", encoding="utf-8")
    checkout = layout.root / "source-code" / "github.com" / "acme" / "widget"
    checkout.mkdir(parents=True)
    added_at = "2026-09-01T00:00:00Z"
    cat.write_catalog(
        layout,
        cat.Catalog(
            entries=(
                cat.Entry(
                    kind="docs",
                    slug="pi",
                    source="https://pi.dev/docs",
                    path="documentation/pi",
                    stale_after=1_209_600,
                    upstream=cat.DocsUpstream(),
                    added_at=added_at,
                ),
                cat.Entry(
                    kind="source",
                    slug="widget",
                    source="https://github.com/acme/widget.git",
                    path="source-code/github.com/acme/widget",
                    stale_after=86_400,
                    upstream=cat.SourceUpstream(branch="main", head_sha="0" * 40),
                    added_at=added_at,
                ),
            )
        ),
    )


def _unignore(repo: Path, _tmp: Path) -> str:
    (repo / ".gitignore").write_text("", encoding="utf-8")
    return "library_not_ignored"


def _track(repo: Path, _tmp: Path) -> str:
    tracked = repo / "docs" / "library" / "hunk" / "index.md"
    tracked.parent.mkdir(parents=True)
    tracked.write_text("# hunk\n", encoding="utf-8")
    _git(repo, "add", "-f", "docs/library/hunk/index.md")
    return "library_tracked_content"


def _redirect(repo: Path, tmp: Path) -> str:
    (repo / "docs" / "library" / ".staging").symlink_to(tmp, target_is_directory=True)
    return "library_root_invalid"


def _no_network(*_args, **_kwargs):
    raise AssertionError("a refused worker reached the network")


@pytest.mark.parametrize("breakage", [_unignore, _track, _redirect], ids=lambda f: f.__name__)
@pytest.mark.parametrize("worker", ["add source", "check", "refresh"])
def test_network_workers_refuse_before_any_network_or_write(
    scaffolded_perk_repo, tmp_path_factory, monkeypatch, worker, breakage
):
    repo = scaffolded_perk_repo
    monkeypatch.chdir(repo)
    _seed_catalog(repo)
    error_type = breakage(repo, tmp_path_factory.mktemp("redirect"))
    for name in ("clone_partial", "fetch", "remote_branch_head"):
        monkeypatch.setattr(git, name, _no_network)
    transport = httpx.MockTransport(_no_network)
    run = {
        "add source": lambda: source.add_source(
            repo, repo_ref="acme/gadget", pin=None, slug=None, stale_after=None
        ),
        "check": lambda: check.check_entries(repo, slugs=(), force=True, transport=transport),
        "refresh": lambda: source.refresh_entry(repo, slug="widget"),
    }[worker]
    lock.lock_path(repo).unlink(missing_ok=True)
    before_status = _git(repo, "status", "--porcelain", "--ignored")
    before = _snapshot(repo)
    with pytest.raises(LibraryError) as excinfo:
        run()
    assert excinfo.value.error_type == error_type
    assert _snapshot(repo) == before
    assert _git(repo, "status", "--porcelain", "--ignored") == before_status
    assert not lock.lock_path(repo).exists()
