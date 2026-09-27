"""``add source`` and ``refresh`` (``perk/library/source.py``, contracts.md §8.75(i)).

Offline: the ``upstream`` fixture's bare repository is reached through git's own env-config
``insteadOf`` rewriting of ``https://github.com/acme/widget.git``. Every successful op is also
checked against the cache-only promise: ``git status`` reports nothing under ``docs/``.
"""

import contextlib
import os
import shutil
import stat
import subprocess
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from _library_upstream import CLONE_URL, ENTRY_PATH, REPO_REF, Upstream, run_git, upstream

from perk.library import catalog as cat
from perk.library import source
from perk.library.errors import LibraryError
from perk.library.layout import LibraryLayout
from perk.substrate import git

__all__ = ["upstream"]  # the fixture, re-exported so pytest collects it here

NOW = datetime(2026, 9, 27, 12, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 9, 28, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def repo(scaffolded_perk_repo, monkeypatch):
    monkeypatch.chdir(scaffolded_perk_repo)
    return scaffolded_perk_repo


def _layout(repo: Path) -> LibraryLayout:
    return LibraryLayout.for_repo(repo)


def _checkout(repo: Path) -> Path:
    return _layout(repo).root / ENTRY_PATH


def _catalog(repo: Path) -> cat.Catalog:
    return cat.load_catalog(_layout(repo))


def _entry(repo: Path, slug: str = "widget") -> cat.Entry:
    entry = _catalog(repo).get(slug)
    assert entry is not None
    return entry


def _head_sha(entry: cat.Entry) -> str | None:
    assert isinstance(entry.upstream, cat.SourceUpstream)
    return entry.upstream.head_sha


def _detail(outcome: source.RefreshOutcome) -> str:
    assert outcome.detail is not None
    return outcome.detail


def _catalog_bytes(repo: Path) -> bytes | None:
    path = _layout(repo).catalog_path
    return path.read_bytes() if path.exists() else None


def _head(checkout: Path) -> str:
    return run_git(checkout, "rev-parse", "HEAD").strip()


def _assert_docs_clean(repo: Path) -> None:
    status = run_git(repo, "status", "--porcelain", "--untracked-files=all")
    assert [line for line in status.splitlines() if line[3:].startswith("docs/")] == []


def _refusal(fn: Callable[[], object]) -> LibraryError:
    with pytest.raises(LibraryError) as excinfo:
        fn()
    return excinfo.value


def _add(
    repo: Path,
    *,
    pin: str | None = None,
    slug: str | None = None,
    stale_after: int | None = None,
    repo_ref: str = REPO_REF,
    now: datetime = NOW,
) -> source.AddSourceOutcome:
    return source.add_source(
        repo, repo_ref=repo_ref, pin=pin, slug=slug, stale_after=stale_after, now=lambda: now
    )


def _refresh(repo: Path, slug: str = "widget", now: datetime = LATER) -> source.RefreshOutcome:
    return source.refresh_entry(repo, slug=slug, now=lambda: now)


def _set_entry(repo: Path, entry: cat.Entry) -> None:
    layout = _layout(repo)
    cat.write_catalog(layout, cat.load_catalog(layout).with_entry(entry))


def _commit(checkout: Path, name: str) -> str:
    (checkout / name).write_text(f"{name}\n", encoding="utf-8")
    run_git(checkout, "add", name)
    run_git(checkout, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", name)
    return _head(checkout)


# --- add source ------------------------------------------------------------------------------


def test_fresh_add_clones_a_blobless_checkout(repo, upstream: Upstream):
    outcome = _add(repo)
    assert outcome.action == "cloned"
    view = outcome.view
    entry = view.entry
    checkout = _checkout(repo)
    assert (entry.kind, entry.slug, entry.path, entry.source) == (
        "source",
        "widget",
        ENTRY_PATH,
        CLONE_URL,
    )
    assert entry.upstream == cat.SourceUpstream(branch="main", head_sha=upstream.sha("main"))
    assert _head(checkout) == upstream.sha("main")
    assert (entry.ref, entry.checked_at, entry.evidence, entry.drifted) == (
        None,
        None,
        "none",
        False,
    )
    assert entry.stale_after == cat.DEFAULT_STALE_AFTER["source"]
    assert (view.status, view.present, view.absolute_path) == ("unknown", True, checkout)
    assert run_git(checkout, "config", "remote.origin.partialclonefilter").strip() == "blob:none"
    assert _catalog(repo).entries == (entry,)
    _assert_docs_clean(repo)


def test_rerun_reuses_the_checkout_without_rewriting_the_catalog(repo, upstream):
    _add(repo)
    before = _catalog_bytes(repo)
    # The insteadOf environment is still active: the stored-URL comparison sees CLONE_URL.
    outcome = _add(repo, now=LATER)
    assert outcome.action == "reused"
    assert _catalog_bytes(repo) == before
    _assert_docs_clean(repo)


def test_rerun_with_stale_after_updates_only_the_window(repo, upstream):
    _add(repo)
    outcome = _add(repo, stale_after=3_600)
    assert outcome.action == "reused"
    assert outcome.view.entry.stale_after == 3_600
    assert _entry(repo).stale_after == 3_600


def test_pinned_clone_reuse_and_repin(repo, upstream):
    v1 = upstream.tag("v1", "HEAD~1")
    outcome = _add(repo, pin="v1")
    checkout = _checkout(repo)
    assert outcome.action == "cloned"
    assert outcome.view.entry.ref == "v1"
    assert outcome.view.status == "pinned"
    assert _head(checkout) == v1 == _head_sha(outcome.view.entry)
    assert git.current_branch(checkout) is None

    assert _add(repo, pin="v1").action == "reused"

    _set_entry(repo, replace(outcome.view.entry, checked_at="2026-09-27T00:00:00Z"))
    v2 = upstream.advance_origin()
    upstream.tag("v2", v2)
    repinned = _add(repo, pin="v2")
    assert repinned.action == "repinned"
    assert _head(checkout) == v2
    entry = repinned.view.entry
    assert (entry.ref, _head_sha(entry), entry.checked_at) == ("v2", v2, None)
    assert _entry(repo) == entry
    _assert_docs_clean(repo)


def test_unknown_pin_on_a_fresh_clone_removes_the_clone(repo, upstream):
    error = _refusal(lambda: _add(repo, pin="nope"))
    assert error.error_type == "ref_not_found"
    assert not _checkout(repo).exists()
    assert _catalog_bytes(repo) is None


def test_unknown_pin_on_an_existing_checkout_leaves_it_untouched(repo, upstream):
    _add(repo)
    before = (_head(_checkout(repo)), _catalog_bytes(repo))
    error = _refusal(lambda: _add(repo, pin="nope"))
    assert error.error_type == "ref_not_found"
    assert (_head(_checkout(repo)), _catalog_bytes(repo)) == before


def test_repin_refuses_a_dirty_checkout(repo, upstream):
    upstream.tag("v1", "HEAD~1")
    _add(repo)
    checkout = _checkout(repo)
    head = _head(checkout)
    (checkout / "scratch.txt").write_text("wip\n", encoding="utf-8")
    error = _refusal(lambda: _add(repo, pin="v1"))
    assert error.error_type == "checkout_dirty"
    assert _head(checkout) == head


@pytest.mark.parametrize("pin", ["", " v1", "v 1", "-v1", "--upload-pack=x"])
def test_invalid_pin_is_refused_before_anything(repo, upstream, pin):
    assert _refusal(lambda: _add(repo, pin=pin)).error_type == "invalid_input"
    assert not _checkout(repo).exists()


def test_uncatalogued_valid_checkout_is_adopted_at_its_head(repo, upstream):
    checkout = _checkout(repo)
    checkout.parent.mkdir(parents=True)
    run_git(checkout.parent, "clone", "-q", CLONE_URL, checkout.name)
    head = _head(checkout)
    upstream.advance_origin()
    run_git(checkout, "fetch", "-q", "origin")
    assert run_git(checkout, "rev-parse", "origin/main").strip() != head
    outcome = _add(repo)
    assert outcome.action == "reused"
    assert _head_sha(outcome.view.entry) == head
    assert _entry(repo) == outcome.view.entry
    _assert_docs_clean(repo)


def test_plain_directory_at_the_target_is_refused(repo, upstream):
    checkout = _checkout(repo)
    checkout.mkdir(parents=True)
    (checkout / "notes.txt").write_text("x\n", encoding="utf-8")
    assert _refusal(lambda: _add(repo)).error_type == "checkout_invalid"
    assert (checkout / "notes.txt").is_file()


def test_checkout_of_another_url_is_refused(repo, upstream):
    checkout = _checkout(repo)
    checkout.parent.mkdir(parents=True)
    run_git(checkout.parent, "clone", "-q", CLONE_URL, checkout.name)
    run_git(checkout, "remote", "set-url", "origin", "https://example.com/other.git")
    assert _refusal(lambda: _add(repo)).error_type == "checkout_invalid"


def test_linked_worktree_at_the_target_is_refused(repo, upstream):
    checkout = _checkout(repo)
    checkout.parent.mkdir(parents=True)
    # Same stored origin URL, so the gitfile `.git` is the only reason to refuse.
    run_git(upstream.seed, "remote", "set-url", "origin", CLONE_URL)
    run_git(upstream.seed, "worktree", "add", "-q", "--detach", str(checkout))
    assert (checkout / ".git").is_file()
    assert _refusal(lambda: _add(repo)).error_type == "checkout_invalid"


def test_missing_pinned_checkout_needs_an_explicit_ref(repo, upstream):
    v1 = upstream.tag("v1", "HEAD~1")
    _add(repo, pin="v1")
    shutil.rmtree(_checkout(repo))
    error = _refusal(lambda: _add(repo))
    assert error.error_type == "entry_pinned"
    assert "--ref v1" in str(error)
    restored = _add(repo, pin="v1")
    assert restored.action == "cloned"
    assert (_head(_checkout(repo)), restored.view.entry.ref) == (v1, "v1")


def test_missing_unpinned_checkout_is_recloned(repo, upstream):
    _add(repo)
    shutil.rmtree(_checkout(repo))
    outcome = _add(repo)
    assert outcome.action == "cloned"
    assert _head_sha(_entry(repo)) == _head(_checkout(repo))


def test_slug_taken_by_a_docs_entry_is_refused(repo, upstream):
    docs = cat.Entry(
        kind="docs",
        slug="widget",
        source="https://widget.dev/docs",
        path="documentation/widget",
        added_at="2026-09-01T00:00:00Z",
        stale_after=1_209_600,
        upstream=cat.DocsUpstream(),
    )
    _set_entry(repo, docs)
    assert _refusal(lambda: _add(repo)).error_type == "slug_exists"
    assert not _checkout(repo).exists()


def test_slug_disagreeing_with_the_catalogued_slug_is_refused(repo, upstream):
    _add(repo)
    error = _refusal(lambda: _add(repo, slug="gadget"))
    assert error.error_type == "invalid_input"
    assert "catalogued as widget" in str(error)


def test_a_concurrently_created_target_is_never_deleted(repo, upstream, monkeypatch):
    checkout = _checkout(repo)
    real_mkdir = Path.mkdir
    raced = []

    def racing_mkdir(self, *args, **kwargs):
        if self == checkout and not raced:
            raced.append(self)
            real_mkdir(self, parents=True)
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", racing_mkdir)
    error = _refusal(lambda: _add(repo))
    assert error.error_type == "checkout_invalid"
    assert "appeared meanwhile" in str(error)
    assert checkout.is_dir()


def test_a_clone_another_run_catalogued_meanwhile_is_never_deleted(repo, upstream, monkeypatch):
    # Interleaving: this run finishes its clone; before it takes the lock, another run adopts
    # the valid checkout under another slug. This run's eligibility re-check then refuses —
    # and its cleanup must leave the now-catalogued checkout alone.
    real_lock = source.library_lock
    adopted: list[cat.Entry] = []

    @contextlib.contextmanager
    def adopting_lock(root):
        if not adopted:
            entry = cat.Entry(
                kind="source",
                slug="gadget",
                source=CLONE_URL,
                path=ENTRY_PATH,
                added_at="2026-09-27T00:00:00Z",
                stale_after=86_400,
                upstream=cat.SourceUpstream(branch="main", head_sha=_head(_checkout(repo))),
            )
            _set_entry(repo, entry)
            adopted.append(entry)
        with real_lock(root):
            yield

    monkeypatch.setattr(source, "library_lock", adopting_lock)
    error = _refusal(lambda: _add(repo, slug="widget"))
    assert error.error_type == "checkout_invalid"
    assert "while this one cloned" in str(error)
    assert _checkout(repo).is_dir()
    assert _catalog(repo).entries == tuple(adopted)


def test_a_fresh_clone_never_records_its_pin_over_a_concurrent_repin(repo, upstream, monkeypatch):
    # Interleaving: this run clones and detaches at v1; before it takes the lock, another run
    # reuses the checkout, re-pins it to v2 and records that under the same slug. Recording v1
    # now would pair the ref with v2's HEAD.
    upstream.tag("v1", "HEAD~1")
    v2 = upstream.advance_origin()
    upstream.tag("v2", v2)
    real_lock = source.library_lock
    repinned: list[cat.Entry] = []

    @contextlib.contextmanager
    def repinning_lock(root):
        if not repinned:
            run_git(_checkout(repo), "checkout", "-q", "--detach", v2)
            entry = cat.Entry(
                kind="source",
                slug="widget",
                source=CLONE_URL,
                path=ENTRY_PATH,
                added_at="2026-09-27T00:00:00Z",
                stale_after=86_400,
                upstream=cat.SourceUpstream(branch="main", head_sha=v2),
                ref="v2",
            )
            _set_entry(repo, entry)
            repinned.append(entry)
        with real_lock(root):
            yield

    monkeypatch.setattr(source, "library_lock", repinning_lock)
    error = _refusal(lambda: _add(repo, pin="v1"))
    assert error.error_type == "checkout_invalid"
    assert _head(_checkout(repo)) == v2
    assert _catalog(repo).entries == tuple(repinned)


def test_clone_failure_leaves_nothing_behind(repo, upstream, monkeypatch):
    def failing_clone(url, dest, **_kwargs):
        (dest / "partial").write_text("x", encoding="utf-8")
        raise git.GitError("fatal: repository not found")

    monkeypatch.setattr(git, "clone_partial", failing_clone)
    error = _refusal(lambda: _add(repo))
    assert error.error_type == "clone_failed"
    assert "repository not found" in str(error)
    assert "git@/ssh://" in str(error)
    assert not _checkout(repo).exists()
    assert _catalog_bytes(repo) is None


def test_the_clone_never_executes_configured_hooks_or_filters(
    repo, upstream, tmp_path, monkeypatch
):
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    hook_canary = tmp_path / "canary-hook"
    filter_canary = tmp_path / "canary-filter"
    post_checkout = hooks / "post-checkout"
    post_checkout.write_text(f"#!/bin/sh\ntouch '{hook_canary}'\n", encoding="utf-8")
    post_checkout.chmod(post_checkout.stat().st_mode | stat.S_IXUSR)
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text(
        f"[core]\n\thooksPath = {hooks}\n"
        f"[filter \"canary\"]\n\tsmudge = touch '{filter_canary}' && cat\n\trequired = true\n",
        encoding="utf-8",
    )
    (upstream.seed / ".gitattributes").write_text("* filter=canary\n", encoding="utf-8")
    run_git(upstream.seed, "add", ".gitattributes")
    run_git(upstream.seed, "commit", "-qm", "attributes")
    run_git(upstream.seed, "push", "-q", "origin", "main")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))

    # Control: a bare `git clone` under the same environment fires both canaries.
    subprocess.run(
        ["git", "clone", "-q", CLONE_URL, str(tmp_path / "control")],
        check=True,
        capture_output=True,
        timeout=60,
    )
    assert hook_canary.exists() and filter_canary.exists()
    hook_canary.unlink()
    filter_canary.unlink()

    assert _add(repo).action == "cloned"
    assert (_checkout(repo) / ".gitattributes").is_file()
    assert not hook_canary.exists()
    assert not filter_canary.exists()


def _ran_in(canary: Path, checkout: Path) -> bool:
    """Whether a canary helper recorded running inside ``checkout`` (helpers log their cwd)."""
    if not canary.exists():
        return False
    lines = canary.read_text(encoding="utf-8").splitlines()
    return any(Path(line).resolve() == checkout.resolve() for line in lines)


def test_refresh_and_repin_never_execute_status_helpers(repo, upstream, tmp_path, monkeypatch):
    # The dirty check (`git status`) runs before any fetch: a globally configured fsmonitor
    # hook or an attributes-selected clean filter must not run inside a library checkout.
    upstream.tag("v1", "HEAD~1")
    (upstream.seed / ".gitattributes").write_text("* filter=canary\n", encoding="utf-8")
    run_git(upstream.seed, "add", ".gitattributes")
    run_git(upstream.seed, "commit", "-qm", "attributes")
    run_git(upstream.seed, "push", "-q", "origin", "main")
    _add(repo)
    checkout = _checkout(repo)
    fsmonitor_canary = tmp_path / "canary-fsmonitor"
    filter_canary = tmp_path / "canary-filter"
    fsmonitor = tmp_path / "fsmonitor-hook"
    fsmonitor.write_text(f"#!/bin/sh\npwd >> '{fsmonitor_canary}'\nexit 1\n", encoding="utf-8")
    fsmonitor.chmod(fsmonitor.stat().st_mode | stat.S_IXUSR)
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text(
        f"[core]\n\tfsmonitor = {fsmonitor}\n"
        f"[filter \"canary\"]\n\tclean = pwd >> '{filter_canary}' && cat\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    stamp = iter(range(1, 100))

    def force_recheck() -> None:
        # A new mtime makes `git status` re-hash the file through the clean filter.
        moment = (checkout / "f.txt").stat().st_mtime + 10 * next(stamp)
        os.utime(checkout / "f.txt", (moment, moment))

    # Control: a bare `git status` under the same environment fires both helpers.
    force_recheck()
    subprocess.run(
        ["git", "status", "--porcelain"], cwd=checkout, check=True, capture_output=True, timeout=60
    )
    assert _ran_in(fsmonitor_canary, checkout) and _ran_in(filter_canary, checkout)
    fsmonitor_canary.unlink()
    filter_canary.unlink()

    force_recheck()
    assert _refresh(repo).action == "up_to_date"
    force_recheck()
    assert _add(repo, pin="v1").action == "repinned"
    assert not _ran_in(fsmonitor_canary, checkout)
    assert not _ran_in(filter_canary, checkout)


def test_repin_catalog_write_failure_names_the_completing_rerun(repo, upstream, monkeypatch):
    upstream.tag("v1", "HEAD~1")
    _add(repo, pin="v1")
    v2 = upstream.advance_origin()
    upstream.tag("v2", v2)
    before = _catalog_bytes(repo)

    def failing_write(path, text):
        raise PermissionError(13, "Permission denied (injected)", str(path))

    with monkeypatch.context() as patch:
        patch.setattr(cat, "atomic_write_text", failing_write)
        error = _refusal(lambda: _add(repo, pin="v2"))
    assert error.error_type == "io_error"
    assert "completes the re-pin" in str(error)
    assert _head(_checkout(repo)) == v2
    assert _catalog_bytes(repo) == before
    outcome = _add(repo, pin="v2")
    assert outcome.action == "repinned"
    assert _entry(repo).ref == "v2"


def test_fresh_clone_catalog_write_failure_removes_the_clone(repo, upstream, monkeypatch):
    def failing_write(path, text):
        raise PermissionError(13, "Permission denied (injected)", str(path))

    monkeypatch.setattr(cat, "atomic_write_text", failing_write)
    error = _refusal(lambda: _add(repo))
    assert error.error_type == "io_error"
    assert "removed" in str(error)
    assert not _checkout(repo).exists()


def test_invalid_repo_ref_and_default_slug(repo):
    assert _refusal(lambda: _add(repo, repo_ref="click")).error_type == "invalid_repo_ref"
    long_ref = f"acme/{'w' * 65}"
    assert _refusal(lambda: _add(repo, repo_ref=long_ref)).error_type == "invalid_slug"


# --- refresh ---------------------------------------------------------------------------------


def test_refresh_up_to_date_records_strong_evidence(repo, upstream):
    _add(repo)
    outcome = _refresh(repo)
    assert outcome.action == "up_to_date"
    entry = outcome.view.entry
    assert (entry.evidence, entry.drifted, entry.checked_at) == (
        "strong",
        False,
        cat.format_ts(LATER),
    )
    assert outcome.previous_head == upstream.sha("main")
    assert outcome.view.status == "fresh"
    assert _entry(repo) == entry
    _assert_docs_clean(repo)


def test_refresh_fast_forwards(repo, upstream):
    _add(repo)
    old = upstream.sha("main")
    new = upstream.advance_origin()
    outcome = _refresh(repo)
    assert outcome.action == "fast_forwarded"
    assert (outcome.previous_head, _head_sha(outcome.view.entry)) == (old, new)
    assert _head(_checkout(repo)) == new
    assert git.current_branch(_checkout(repo)) == "main"
    _assert_docs_clean(repo)


def test_refresh_fast_forwards_to_the_classified_tip_despite_a_shadowing_tag(repo, upstream):
    # An upstream tag named `origin/main` outranks the remote-tracking ref in git's name
    # resolution; the merge must use the exact tip the ancestry check classified.
    _add(repo)
    old = upstream.sha("main")
    upstream.tag("origin/main", old)
    new = upstream.advance_origin()
    outcome = _refresh(repo)
    assert outcome.action == "fast_forwarded"
    assert _head(_checkout(repo)) == new
    assert _head_sha(outcome.view.entry) == new


def test_refresh_skips_a_dirty_checkout_without_writing(repo, upstream):
    _add(repo)
    (_checkout(repo) / "scratch.txt").write_text("wip\n", encoding="utf-8")
    outcome = _refresh(repo)
    assert outcome.action == "skipped_dirty"
    assert str(_checkout(repo)) in _detail(outcome)
    assert _entry(repo).checked_at is None


def test_refresh_reports_local_commits_ahead(repo, upstream):
    _add(repo)
    local = _commit(_checkout(repo), "local.txt")
    outcome = _refresh(repo)
    assert outcome.action == "skipped_non_ff"
    assert "local commits ahead of origin/main" in _detail(outcome)
    entry = outcome.view.entry
    assert (entry.drifted, _head_sha(entry), entry.evidence) == (True, local, "strong")
    assert _head(_checkout(repo)) == local


def test_refresh_reports_divergence(repo, upstream):
    _add(repo)
    local = _commit(_checkout(repo), "local.txt")
    upstream.advance_origin()
    outcome = _refresh(repo)
    assert outcome.action == "skipped_non_ff"
    assert "diverged from origin/main" in _detail(outcome)
    assert outcome.view.entry.drifted is True
    assert _head(_checkout(repo)) == local


def test_refresh_skips_a_detached_head_without_fetching(repo, upstream, monkeypatch):
    _add(repo)
    run_git(_checkout(repo), "checkout", "-q", "--detach")

    def no_fetch(*_args, **_kwargs):
        raise AssertionError("refresh fetched a detached checkout")

    monkeypatch.setattr(git, "fetch", no_fetch)
    outcome = _refresh(repo)
    assert outcome.action == "skipped_non_ff"
    assert "detached" in _detail(outcome)
    assert _entry(repo).checked_at is None


def test_refresh_refuses_pinned_docs_missing_and_unknown(repo, upstream):
    upstream.tag("v1", "HEAD~1")
    _add(repo, pin="v1")
    pinned = _refusal(lambda: _refresh(repo))
    assert pinned.error_type == "entry_pinned"
    assert f"perk librarian add source {CLONE_URL} --ref <new>" in str(pinned)

    _set_entry(
        repo,
        cat.Entry(
            kind="docs",
            slug="pi",
            source="https://pi.dev/docs",
            path="documentation/pi",
            added_at="2026-09-01T00:00:00Z",
            stale_after=1_209_600,
            upstream=cat.DocsUpstream(),
        ),
    )
    needs_session = _refusal(lambda: _refresh(repo, "pi"))
    assert needs_session.error_type == "needs_session"
    assert "record --publish" in str(needs_session)

    assert _refusal(lambda: _refresh(repo, "nope")).error_type == "entry_not_found"


def test_refresh_of_a_deleted_checkout_is_entry_missing(repo, upstream):
    _add(repo)
    shutil.rmtree(_checkout(repo))
    error = _refusal(lambda: _refresh(repo))
    assert error.error_type == "entry_missing"
    assert f"perk librarian add source {CLONE_URL}" in str(error)


def test_refresh_sees_a_deleted_upstream_branch(repo, upstream):
    # The fetch prunes: a stale `origin/main` tracking ref must not read as up to date.
    _add(repo)
    run_git(upstream.seed, "push", "-q", "origin", "HEAD~1:refs/heads/other")
    run_git(upstream.remote, "symbolic-ref", "HEAD", "refs/heads/other")
    run_git(upstream.remote, "branch", "-D", "main")
    outcome = _refresh(repo)
    assert outcome.action == "skipped_non_ff"
    assert _detail(outcome) == "origin/main is gone after fetch"
    entry = outcome.view.entry
    assert (entry.evidence, entry.drifted) == ("none", False)
    assert outcome.view.status == "unverifiable"


def test_refresh_fetch_failure_writes_nothing(repo, upstream, monkeypatch):
    _add(repo)

    def failing_fetch(*_args, **_kwargs):
        raise git.GitError("fatal: unable to access")

    monkeypatch.setattr(git, "fetch", failing_fetch)
    assert _refusal(lambda: _refresh(repo)).error_type == "fetch_failed"
    assert _entry(repo).checked_at is None


def test_refresh_write_failure_after_a_fast_forward_is_recorded_by_a_rerun(
    repo, upstream, monkeypatch
):
    _add(repo)
    new = upstream.advance_origin()

    def failing_write(path, text):
        raise PermissionError(13, "Permission denied (injected)", str(path))

    with monkeypatch.context() as patch:
        patch.setattr(cat, "atomic_write_text", failing_write)
        error = _refusal(lambda: _refresh(repo))
    assert error.error_type == "io_error"
    assert "rerunning `perk librarian refresh widget` records it" in str(error)
    assert _head(_checkout(repo)) == new
    outcome = _refresh(repo)
    assert outcome.action == "up_to_date"
    assert _head_sha(_entry(repo)) == new


def test_hooks_dir_is_removed_after_the_op(repo, upstream, monkeypatch):
    seen: list[Path] = []
    real = git.clone_partial

    def recording_clone(url, dest, *, pinned=None, **kwargs):
        assert pinned is not None and pinned.is_dir() and not any(pinned.iterdir())
        seen.append(pinned)
        real(url, dest, pinned=pinned, **kwargs)

    monkeypatch.setattr(git, "clone_partial", recording_clone)
    _add(repo)
    assert seen and not seen[0].exists()
