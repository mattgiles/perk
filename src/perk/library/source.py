"""The source-checkout verbs: ``add source`` and ``refresh`` (contracts.md §8.75(i)).

Posture — simple and legible. ``add source`` clones lock-free into a directory THIS run claimed
(an atomic ``mkdir``), then records the entry under the library lock; the lock is never held
across a clone. A re-pin, and ``refresh``'s fetch + fast-forward, touch an already catalogued
checkout and run under the lock. Nothing is deleted that this run did not create. There are no
rollback ladders: a catalog write failing after a git mutation is an ``io_error`` whose message
names the checkout's state and the rerun that completes the operation.

Every executing git operation runs config-pinned (``pinned=`` an empty temporary hooks
directory — :data:`perk.substrate.git.LIBRARY_GIT_ENV`), so nothing the cloned tree or the
user's global config selects can execute; env config and the checkout's repo-local config stay
trusted (an adopted pre-existing checkout brings its creator's). ``upstream.head_sha`` is
always the checkout's HEAD — the revision the local mirror holds; only a clone, a re-pin or a
fast-forward changes it.
"""

import contextlib
import shutil
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from perk.library.catalog import (
    DEFAULT_STALE_AFTER,
    Catalog,
    Clock,
    Entry,
    SourceUpstream,
    format_ts,
    load_catalog,
    utc_now,
    write_catalog,
)
from perk.library.errors import LibraryError, translating_io
from perk.library.guard import (
    probe_paths_for,
    require_ignored,
    require_no_tracked_content,
    require_real_roots,
    require_unlinked_components,
)
from perk.library.layout import LibraryLayout, validate_slug
from perk.library.lock import library_lock
from perk.library.ops import EntryView, entry_view
from perk.library.repo_ref import RepoRef, parse_repo_ref
from perk.substrate import git

type AddAction = Literal["cloned", "reused", "repinned"]
type RefreshAction = Literal["fast_forwarded", "up_to_date", "skipped_dirty", "skipped_non_ff"]


@dataclass(frozen=True)
class AddSourceOutcome:
    action: AddAction
    view: EntryView


@dataclass(frozen=True)
class RefreshOutcome:
    action: RefreshAction
    detail: str | None
    previous_head: str | None
    view: EntryView


@contextlib.contextmanager
def hooks_dir() -> Iterator[Path]:
    """An empty temporary directory to pin ``core.hooksPath`` at for the op's duration."""
    with tempfile.TemporaryDirectory(prefix="perk-library-hooks-") as name:
        yield Path(name)


def add_source(
    repo_root: Path,
    *,
    repo_ref: str,
    pin: str | None,
    slug: str | None,
    stale_after: int | None,
    now: Clock | None = None,
) -> AddSourceOutcome:
    """Clone (or reuse) a source checkout at ``source-code/<host>/<org>/<repo>`` and record it.

    Idempotent: a rerun over a valid checkout is ``reused`` (a valid uncatalogued checkout — a
    killed run's — is catalogued). ``pin`` detaches the checkout at a tag/branch/commit and
    records it as the entry's ``ref``; a different ``pin`` on an existing checkout re-pins it.
    """
    with translating_io("add source"):
        layout = LibraryLayout.for_repo(repo_root)
        ref = parse_repo_ref(repo_ref)
        if pin is not None:
            _validate_pin(pin)
        requested = validate_slug(slug) if slug is not None else None
        target = layout.source_entry_dir(ref.host, ref.org, ref.repo)
        rel = layout.relative(target)
        require_real_roots(layout)
        require_no_tracked_content(layout)
        # Before the ignore probe: git refuses to evaluate a path beyond a symlink.
        require_unlinked_components(layout, rel)
        require_ignored(layout, probe_paths_for(layout, dirs=[target]))
        fresh = not (target.exists() or target.is_symlink())
        snapshot, _chosen = _eligibility(
            load_catalog(layout), ref=ref, rel=rel, requested=requested, pin=pin, fresh=fresh
        )
        with hooks_dir() as hooks:
            if fresh:
                _clone_fresh(target, ref, pin, hooks)
            else:
                _require_checkout(target, ref.clone_url)
            committed = False
            try:
                outcome = _record_source(
                    repo_root,
                    layout,
                    ref=ref,
                    rel=rel,
                    target=target,
                    requested=requested,
                    pin=pin,
                    fresh=fresh,
                    snapshot=snapshot,
                    stale_after=stale_after,
                    hooks=hooks,
                    now=now,
                )
                committed = True
            finally:
                if fresh and not committed and not _catalogued_meanwhile(layout, rel, snapshot):
                    shutil.rmtree(target, ignore_errors=True)
        return outcome


def _catalogued_meanwhile(layout: LibraryLayout, rel: str, snapshot: Entry | None) -> bool:
    """Whether another operation catalogued (or changed) the entry owning ``rel`` since the
    pre-clone snapshot — a checkout another run has published is no longer this run's to
    delete. An unreadable catalog counts as yes: when in doubt, keep the directory."""
    try:
        return load_catalog(layout).owner_of(rel) != snapshot
    except LibraryError:
        return True


def _validate_pin(pin: str) -> None:
    if not pin or any(char.isspace() for char in pin) or pin.startswith("-"):
        raise LibraryError(
            "invalid_input",
            f"invalid --ref {pin!r}: name a tag, branch or commit (no whitespace, no leading '-')",
        )


def _eligibility(
    catalog: Catalog,
    *,
    ref: RepoRef,
    rel: str,
    requested: str | None,
    pin: str | None,
    fresh: bool,
) -> tuple[Entry | None, str]:
    """The entry already owning ``rel`` (``None`` when uncatalogued) and the slug to record —
    or a typed refusal. Run lock-free before the clone, then again under the lock."""
    existing = catalog.owner_of(rel)
    if existing is None:
        chosen = requested if requested is not None else ref.default_slug
        taken = catalog.get(chosen)
        if taken is not None:
            raise LibraryError(
                "slug_exists",
                f"slug {chosen} is already catalogued ({taken.kind} entry at {taken.path}) — "
                "pick another --slug",
            )
        return None, chosen
    if requested is not None and requested != existing.slug:
        raise LibraryError(
            "invalid_input",
            f"{rel} is catalogued as {existing.slug}; omit --slug (or pass --slug {existing.slug})",
        )
    if existing.source != ref.clone_url:
        raise LibraryError(
            "invalid_input",
            f"{rel} is catalogued as {existing.slug} from {existing.source} — pass that "
            f"repo-ref, or `perk librarian remove {existing.slug}` first to switch URLs",
        )
    if existing.ref is not None and fresh and pin is None:
        raise LibraryError(
            "entry_pinned",
            f"the checkout for {existing.slug} is missing; it is pinned at {existing.ref} — "
            f"rerun with --ref {existing.ref} to restore it, another --ref to re-pin, or "
            f"`perk librarian remove {existing.slug}` then `perk librarian add source "
            f"{existing.source}` to track the default branch",
        )
    return existing, existing.slug


def _clone_fresh(target: Path, ref: RepoRef, pin: str | None, hooks: Path) -> None:
    """Claim ``target`` (an atomic ``mkdir``), clone into it and detach at ``pin``; a failure
    removes the directory this run created — and only that."""
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.mkdir()
    except FileExistsError as exc:
        raise LibraryError(
            "checkout_invalid",
            f"{target} appeared meanwhile — another `perk librarian add source` may be running; "
            "rerun, or delete it if it persists",
        ) from exc
    cloned = False
    try:
        try:
            git.clone_partial(ref.clone_url, target, pinned=hooks)
        except git.GitError as exc:
            hint = (
                " (private repositories need the git@/ssh:// form)"
                if ref.clone_url.startswith("https://")
                else ""
            )
            raise LibraryError(
                "clone_failed", f"cloning {ref.clone_url} failed: {exc}{hint}"
            ) from exc
        if pin is not None:
            _detach_at_pin(target, pin, hooks)
        cloned = True
    finally:
        if not cloned:
            shutil.rmtree(target, ignore_errors=True)


def _detach_at_pin(checkout: Path, pin: str, hooks: Path) -> None:
    sha = _resolve_pin(checkout, pin)
    if sha is None:
        raise LibraryError(
            "ref_not_found",
            f"--ref {pin} does not resolve in {checkout} (tried the tag, the origin branch and "
            "a commit)",
        )
    git.checkout_detached(checkout, sha, pinned=hooks)


def _resolve_pin(checkout: Path, pin: str) -> str | None:
    """The commit ``pin`` names — a tag first, then an origin branch, then any revision."""
    for candidate in (f"refs/tags/{pin}", f"refs/remotes/origin/{pin}", pin):
        sha = git.resolve_commit(checkout, candidate)
        if sha is not None:
            return sha
    return None


def _require_checkout(target: Path, clone_url: str) -> None:
    """``target`` must be a checkout of ``clone_url``: its own real ``.git`` directory (a
    gitfile — a linked worktree — or a symlink is refused), ``remote.origin.url`` stored as
    ``clone_url`` (the stored URL, comparable even under ``insteadOf`` rewrites) and a HEAD that
    resolves."""
    dot_git = target / ".git"
    valid = (
        target.is_dir()
        and not target.is_symlink()
        and dot_git.is_dir()
        and not dot_git.is_symlink()
    )
    if valid:
        # The toplevel check stops an invalid `.git` directory from letting git discover an
        # enclosing repository (the consumer repo itself).
        toplevel = git.repo_root(target)
        valid = (
            toplevel is not None
            and toplevel.resolve() == target.resolve()
            and git.config_get(target, "remote.origin.url") == clone_url
            and git.head_commit(target) is not None
        )
    if not valid:
        raise LibraryError(
            "checkout_invalid",
            f"{target} exists but is not a checkout of {clone_url} (a concurrent `perk librarian "
            "add source` may still be running) — rerun later, or delete it and rerun",
        )


def _upstream_of(checkout: Path) -> SourceUpstream:
    return SourceUpstream(
        branch=git.detect_trunk_branch(checkout), head_sha=git.head_commit(checkout)
    )


def _record_source(
    repo_root: Path,
    layout: LibraryLayout,
    *,
    ref: RepoRef,
    rel: str,
    target: Path,
    requested: str | None,
    pin: str | None,
    fresh: bool,
    snapshot: Entry | None,
    stale_after: int | None,
    hooks: Path,
    now: Clock | None,
) -> AddSourceOutcome:
    """The lock phase of ``add source``: re-check eligibility, re-pin, write the entry.

    A fresh clone was made outside the lock, so its recording is fenced on the catalog still
    holding the pre-clone ``snapshot`` for the path: another run that adopted (or re-pinned)
    the checkout meanwhile owns it now, and recording this run's pin over it would pair a
    ``ref`` with another revision's HEAD.
    """
    with library_lock(repo_root):
        catalog = load_catalog(layout)
        if fresh and catalog.owner_of(rel) != snapshot:
            raise LibraryError(
                "checkout_invalid",
                f"{rel} was catalogued or changed by another `perk librarian add source` while "
                "this one cloned — the checkout is left as that run recorded it; rerun to "
                "reconcile",
            )
        existing, chosen = _eligibility(
            catalog, ref=ref, rel=rel, requested=requested, pin=pin, fresh=fresh
        )
        repinned = False
        if not fresh and pin is not None and pin != (existing.ref if existing else None):
            _repin(target, pin, hooks)
            repinned = True
        moment = (now or utc_now)()
        if existing is None:
            entry = Entry(
                kind="source",
                slug=chosen,
                source=ref.clone_url,
                path=rel,
                added_at=format_ts(moment),
                stale_after=stale_after
                if stale_after is not None
                else DEFAULT_STALE_AFTER["source"],
                upstream=_upstream_of(target),
                ref=pin,
            )
        elif fresh or repinned:
            # A revision change: the markers describe the new checkout, never-checked.
            entry = replace(
                existing,
                ref=pin,
                upstream=_upstream_of(target),
                stale_after=stale_after if stale_after is not None else existing.stale_after,
                checked_at=None,
                evidence="none",
                drifted=False,
            )
        else:
            entry = (
                replace(existing, stale_after=stale_after) if stale_after is not None else existing
            )
        if entry != existing:
            try:
                write_catalog(layout, catalog.with_entry(entry))
            except OSError as exc:
                raise _write_failed(
                    exc, target=target, pin=pin, fresh=fresh, repinned=repinned
                ) from exc
        action: AddAction = "cloned" if fresh else "repinned" if repinned else "reused"
        return AddSourceOutcome(action=action, view=entry_view(layout, entry, moment))


def _repin(checkout: Path, pin: str, hooks: Path) -> None:
    if git.is_dirty(checkout, pinned=hooks):
        raise LibraryError(
            "checkout_dirty",
            f"{checkout} has uncommitted changes — commit, stash or discard them before "
            f"re-pinning to {pin}",
        )
    try:
        git.fetch(checkout, pinned=hooks)
    except git.GitError as exc:
        raise LibraryError("fetch_failed", f"fetching into {checkout} failed: {exc}") from exc
    _detach_at_pin(checkout, pin, hooks)


def _write_failed(
    exc: OSError, *, target: Path, pin: str | None, fresh: bool, repinned: bool
) -> LibraryError:
    if fresh:
        state = f"the fresh checkout at {target} is removed and nothing was catalogued — rerun"
    elif repinned:
        state = (
            f"the checkout at {target} is already detached at {pin}; rerunning the same "
            "`perk librarian add source … --ref` completes the re-pin"
        )
    else:
        state = "the catalog is unchanged — rerun"
    return LibraryError("io_error", f"add source: writing the catalog failed ({exc}); {state}")


def refresh_entry(repo_root: Path, *, slug: str, now: Clock | None = None) -> RefreshOutcome:
    """Fetch an unpinned source entry's checkout and fast-forward it to its default branch.

    A dirty tree or a HEAD off the default branch is skipped before any fetch (no write);
    after the fetch the outcome is classified by ancestry — never by the merge's exit code —
    and recorded (``checked_at``, ``evidence``, ``drifted``, ``head_sha`` = the checkout's HEAD).
    """
    with translating_io("refresh"):
        layout = LibraryLayout.for_repo(repo_root)
        require_real_roots(layout)
        require_no_tracked_content(layout)
        require_ignored(layout, [])
        entry = _refreshable(load_catalog(layout).get(slug), slug)
        with hooks_dir() as hooks, library_lock(repo_root):
            catalog = load_catalog(layout)
            current = catalog.get(slug)
            if current is None or current.path != entry.path:
                raise LibraryError(
                    "entry_removed_meanwhile",
                    f"entry {slug} was removed or replaced meanwhile — rerun",
                )
            current = _refreshable(current, slug)
            checkout = require_unlinked_components(layout, current.path)
            require_ignored(layout, probe_paths_for(layout, dirs=[checkout]))
            if not (checkout.exists() or checkout.is_symlink()):
                raise LibraryError(
                    "entry_missing",
                    f"the checkout for {slug} is missing at {checkout} — `perk librarian add "
                    f"source {current.source}` re-clones it",
                )
            _require_checkout(checkout, current.source)
            return _refresh_checkout(layout, catalog, current, checkout, hooks, now)


def _refreshable(entry: Entry | None, slug: str) -> Entry:
    if entry is None:
        raise LibraryError("entry_not_found", f"no library entry named {slug}")
    if entry.kind == "docs":
        raise LibraryError(
            "needs_session",
            f"refreshing docs entry {slug} is judgment work — `perk librarian refresh {slug}` "
            "(without --json) launches the refresh session from a terminal; or re-crawl into "
            "docs/library/.staging/<dir>, curate, then `perk librarian record --publish <dir> "
            f"--slug {slug} --source {entry.source} --replace`",
        )
    if entry.ref is not None:
        raise LibraryError(
            "entry_pinned",
            f"{slug} is pinned at {entry.ref} — re-pin with `perk librarian add source "
            f"{entry.source} --ref <new>`, or `perk librarian remove {slug}` then `perk "
            f"librarian add source {entry.source}` to track the default branch again",
        )
    return entry


def _refresh_checkout(
    layout: LibraryLayout,
    catalog: Catalog,
    entry: Entry,
    checkout: Path,
    hooks: Path,
    now: Clock | None,
) -> RefreshOutcome:
    recorded = entry.upstream
    branch = (
        recorded.branch
        if isinstance(recorded, SourceUpstream) and recorded.branch
        else git.detect_trunk_branch(checkout)
    )
    moment = (now or utc_now)()
    if git.is_dirty(checkout, pinned=hooks):
        return RefreshOutcome(
            action="skipped_dirty",
            detail=f"{checkout} has uncommitted changes",
            previous_head=None,
            view=entry_view(layout, entry, moment),
        )
    on = git.current_branch(checkout)
    if on != branch:
        where = "detached" if on is None else f"on {on}"
        return RefreshOutcome(
            action="skipped_non_ff",
            detail=f"HEAD is {where}, not {branch}",
            previous_head=None,
            view=entry_view(layout, entry, moment),
        )
    previous = git.head_commit(checkout)
    if previous is None:  # _require_checkout saw a resolvable HEAD a moment ago
        raise LibraryError("io_error", f"refresh: HEAD of {checkout} no longer resolves")
    try:
        # Pruned: a stale tracking ref of a branch deleted upstream must not read as its tip.
        git.fetch(checkout, prune=True, pinned=hooks)
    except git.GitError as exc:
        raise LibraryError("fetch_failed", f"fetching into {checkout} failed: {exc}") from exc
    tracking = f"origin/{branch}"
    remote_tip = git.resolve_commit(checkout, f"refs/remotes/{tracking}")
    action: RefreshAction
    detail: str | None = None
    evidence: Literal["strong", "none"] = "strong"
    drifted = entry.drifted
    if remote_tip is None:
        action, detail, evidence = "skipped_non_ff", f"{tracking} is gone after fetch", "none"
    elif remote_tip == previous:
        action, drifted = "up_to_date", False
    else:
        ahead = _ancestry(checkout, previous, remote_tip)
        if ahead:
            # The exact classified SHA — a name like `origin/main` could resolve to a tag.
            if not git.merge_ff_only(checkout, remote_tip, pinned=hooks):
                raise LibraryError(
                    "io_error",
                    f"refresh: fast-forwarding {checkout} to {tracking} failed — inspect the "
                    "checkout and rerun",
                )
            action, drifted = "fast_forwarded", False
        else:
            behind = _ancestry(checkout, remote_tip, previous)
            detail = f"local commits ahead of {tracking}" if behind else f"diverged from {tracking}"
            action, drifted = "skipped_non_ff", True
    updated = replace(
        entry,
        upstream=SourceUpstream(branch=branch, head_sha=git.head_commit(checkout)),
        checked_at=format_ts(moment),
        evidence=evidence,
        drifted=drifted,
    )
    try:
        write_catalog(layout, catalog.with_entry(updated))
    except OSError as exc:
        state = (
            f"the checkout is already fast-forwarded; rerunning `perk librarian refresh "
            f"{entry.slug}` records it"
            if action == "fast_forwarded"
            else "the catalog is unchanged — rerun"
        )
        raise LibraryError(
            "io_error", f"refresh: writing the catalog failed ({exc}); {state}"
        ) from exc
    return RefreshOutcome(
        action=action,
        detail=detail,
        previous_head=previous,
        view=entry_view(layout, updated, moment),
    )


def _ancestry(checkout: Path, ancestor: str, head: str) -> bool:
    """Whether ``ancestor`` is reachable from ``head``; an unanswerable probe is ``io_error``."""
    verdict = git.is_ancestor(checkout, ancestor, head)
    if verdict is None:
        raise LibraryError(
            "io_error",
            f"refresh: could not determine the ancestry of {ancestor} and {head} in {checkout}",
        )
    return verdict
