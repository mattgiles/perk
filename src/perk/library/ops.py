"""The librarian worker cores: ``list`` (lock-free) and the mutating ``publish`` / ``adopt`` /
``remove`` (contracts.md §8.75(e)).

Each mutating op runs, in order: (1) argument/staging validation, (2) the cache-only preflight
(``perk.library.guard`` — before the lock, so a refused repository sees no write), (3)
``library_lock``, (4) a transactional core with a rollback ladder, (5) post-commit best-effort
steps that only ever produce warnings. Every op's body runs inside ``translating_io``, so an
unexpected filesystem or git failure is the typed ``io_error``, never a traceback.

Both ends of every rename live under ``docs/library/`` on preflight-verified real roots, so each
rename is atomic. The catalog is replaced atomically and always points at whichever revision
sits at the entry path; an interrupted swap leaves at worst an uncatalogued directory that
``list`` reports for the human to adopt or delete (no automatic repair).
"""

import json
import os
import secrets
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, NoReturn

from perk.library.catalog import (
    DEFAULT_STALE_AFTER,
    Catalog,
    Clock,
    DocsUpstream,
    Entry,
    Status,
    derive_status,
    format_ts,
    load_catalog,
    parse_ts,
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
from perk.library.inventory import read_inventory
from perk.library.layout import (
    ENTRYPOINT_FILENAME,
    FAILED_PAGES_FILENAME,
    RESERVED_TOP_LEVEL,
    SLUG_GRAMMAR,
    Kind,
    LibraryLayout,
    validate_slug,
)
from perk.library.lock import library_lock

_FAILED_PAGES_SHOWN = 5


@dataclass(frozen=True)
class EntryView:
    """A catalogued entry as the workers report it (absolute path + derived status)."""

    entry: Entry
    absolute_path: Path
    present: bool
    status: Status
    checked_age_seconds: int | None


@dataclass(frozen=True)
class ListReport:
    root: Path
    catalog_present: bool
    entries: tuple[EntryView, ...]
    uncatalogued: tuple[Path, ...]
    staging: tuple[Path, ...]


@dataclass(frozen=True)
class RecordOutcome:
    action: Literal["publish", "adopt"]
    view: EntryView
    replaced_previous: bool
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class RemoveOutcome:
    slug: str
    kind: Kind
    absolute_path: Path
    content_removed: bool


def list_library(repo_root: Path, *, now: Clock | None = None) -> ListReport:
    """The library report — offline and lock-free.

    Paths are absolute under the main checkout's library root (as git reports it; never
    ``resolve()``d). A malformed catalog propagates ``catalog_malformed`` (no silent pass).
    """
    with translating_io("list"):
        layout = LibraryLayout.for_repo(repo_root)
        if not layout.root.is_dir():
            return ListReport(
                root=layout.root, catalog_present=False, entries=(), uncatalogued=(), staging=()
            )
        catalog = load_catalog(layout)
        moment = (now or utc_now)()
        entries = tuple(
            _view(layout, entry, moment) for entry in sorted(catalog.entries, key=lambda e: e.slug)
        )
        return ListReport(
            root=layout.root,
            catalog_present=layout.catalog_path.is_file(),
            entries=entries,
            uncatalogued=_uncatalogued(layout, catalog),
            staging=_child_dirs(layout.staging),
        )


def _child_dirs(directory: Path) -> tuple[Path, ...]:
    if not directory.is_dir():
        return ()
    return tuple(sorted((child for child in directory.iterdir() if child.is_dir()), key=_name))


def _name(path: Path) -> str:
    return path.name


def _uncatalogued(layout: LibraryLayout, catalog: Catalog) -> tuple[Path, ...]:
    """Top-level directories outside the reserved names, plus every directory under
    ``documentation/`` no entry owns (orphaned mirrors — e.g. a displaced prior revision or a
    half-rolled-back swap)."""
    top = [child for child in _child_dirs(layout.root) if child.name not in RESERVED_TOP_LEVEL]
    orphans = [
        child
        for child in _child_dirs(layout.documentation)
        if catalog.owner_of(layout.relative(child)) is None
    ]
    return (*top, *orphans)


def _view(layout: LibraryLayout, entry: Entry, now: datetime) -> EntryView:
    absolute = layout.root / entry.path
    age = None
    if entry.checked_at is not None:
        age = max(0, int((now - parse_ts(entry.checked_at)).total_seconds()))
    return EntryView(
        entry=entry,
        absolute_path=absolute,
        present=absolute.is_dir(),
        status=derive_status(entry, now=now),
        checked_age_seconds=age,
    )


def publish(
    repo_root: Path,
    *,
    staging: Path,
    slug: str,
    source: str,
    replace: bool,
    accept_failures: bool,
    stale_after: int | None,
    now: Clock | None = None,
) -> RecordOutcome:
    """Publish a staged mirror to ``documentation/<slug>/`` and record it — the only way a
    mirror reaches ``documentation/``. Create-only unless ``replace``; every refusal leaves the
    staging directory intact."""
    with translating_io("publish"):
        layout = LibraryLayout.for_repo(repo_root)
        validate_slug(slug)
        staged = _validate_staging(layout, staging)
        _check_failed_pages(staged, accept_failures=accept_failures)
        target = layout.docs_entry_dir(slug)
        displaced_probe = layout.documentation / f".{slug}.previous-probe"
        require_real_roots(layout)
        require_no_tracked_content(layout)
        # Before the ignore probe: git refuses to evaluate a path beyond a symlink.
        require_unlinked_components(layout, layout.relative(target))
        require_ignored(layout, probe_paths_for(layout, dirs=[target, displaced_probe, staged]))
        with library_lock(repo_root):
            catalog = load_catalog(layout)
            existing = _publish_eligibility(layout, catalog, slug=slug, replace=replace)
            markers, inventory_warning = read_inventory(staged)
            moment = (now or utc_now)()
            entry = Entry(
                kind="docs",
                slug=slug,
                source=source,
                path=layout.relative(target),
                added_at=existing.added_at if existing is not None else format_ts(moment),
                stale_after=_stale_after(stale_after, existing),
                upstream=DocsUpstream(pages=markers),
            )
            previous = _commit_publish(layout, staged, target, slug, catalog.with_entry(entry))
            warnings = [inventory_warning] if inventory_warning is not None else []
            warnings.extend(_post_publish(target, previous))
            view = _view(layout, entry, moment)
        return RecordOutcome(
            action="publish",
            view=view,
            replaced_previous=previous is not None,
            warnings=tuple(warnings),
        )


def _stale_after(requested: int | None, existing: Entry | None) -> int:
    if requested is not None:
        return requested
    if existing is not None:
        return existing.stale_after
    return DEFAULT_STALE_AFTER["docs"]


def _validate_staging(layout: LibraryLayout, staging: Path) -> Path:
    """The staging directory's canonical path (``<library>/.staging/<name>``) once it is a real,
    symlink-free direct child of ``.staging/`` with an ``index.md`` entrypoint."""
    candidate = staging.absolute()
    if not candidate.exists() and not candidate.is_symlink():
        raise LibraryError("staging_not_found", f"staging directory {candidate} does not exist")
    if candidate.is_symlink() or not candidate.is_dir():
        raise LibraryError(
            "staging_invalid", f"{candidate} is not a real directory (a symlink or a file)"
        )
    resolved = candidate.resolve()
    if resolved.parent != layout.staging.resolve():
        raise LibraryError(
            "staging_outside_library",
            f"{candidate} is not a direct child of {layout.staging} — crawl into the library's "
            ".staging/ directory, then publish from there",
        )
    staged = layout.staging / resolved.name
    _refuse_symlinks(staged, error_type="staging_invalid")
    entrypoint = staged / ENTRYPOINT_FILENAME
    if entrypoint.is_symlink() or not entrypoint.is_file():
        raise LibraryError(
            "staging_invalid", f"{staged} has no {ENTRYPOINT_FILENAME} entrypoint file"
        )
    return staged


def _refuse_symlinks(root: Path, *, error_type: str) -> None:
    """Refuse (``error_type``) when ``root`` or anything beneath it is a symlink."""
    if root.is_symlink():
        raise LibraryError(error_type, f"{root} is a symlink")
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False, onerror=_reraise):
        for name in (*dirnames, *filenames):
            path = Path(dirpath) / name
            if path.is_symlink():
                raise LibraryError(
                    error_type, f"{path} is a symlink — library content must be real files"
                )


def _reraise(exc: OSError) -> NoReturn:
    raise exc


def _check_failed_pages(staged: Path, *, accept_failures: bool) -> None:
    """Honor the crawl-report handshake: ``failed-pages.json`` (a JSON list) must be empty
    unless ``accept_failures``."""
    report = staged / FAILED_PAGES_FILENAME
    if not report.exists():
        return
    if not report.is_file():
        raise LibraryError("staging_invalid", f"{report} is not a file")
    try:
        failures = json.loads(report.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise LibraryError("staging_invalid", f"{report} is not valid JSON ({exc})") from exc
    if not isinstance(failures, list):
        raise LibraryError("staging_invalid", f"{report} must be a JSON list of failed pages")
    if failures and not accept_failures:
        shown = ", ".join(json.dumps(item) for item in failures[:_FAILED_PAGES_SHOWN])
        more = (
            f", +{len(failures) - _FAILED_PAGES_SHOWN}"
            if len(failures) > _FAILED_PAGES_SHOWN
            else ""
        )
        raise LibraryError(
            "staging_failed_pages",
            f"the crawl reported {len(failures)} failed page(s) ({shown}{more}) — re-crawl, or "
            "pass --accept-failures to publish the partial mirror",
        )


def _publish_eligibility(
    layout: LibraryLayout, catalog: Catalog, *, slug: str, replace: bool
) -> Entry | None:
    """The existing entry being replaced (``None`` for a fresh publish), or a typed refusal."""
    target = layout.docs_entry_dir(slug)
    existing = catalog.get(slug)
    target_present = target.exists() or target.is_symlink()
    if not replace:
        if existing is not None:
            raise LibraryError(
                "slug_exists",
                f"slug {slug} is already catalogued ({existing.kind} entry at {existing.path}) — "
                "pass --replace to refresh it, or pick another --slug",
            )
        if target_present:
            raise LibraryError(
                "slug_exists",
                f"{target} already exists but is not catalogued — adopt it (perk librarian "
                "record --adopt) or delete it, or pick another --slug",
            )
        return None
    if existing is None:
        raise LibraryError(
            "entry_removed_meanwhile",
            f"--replace names slug {slug}, but no such entry is catalogued (removed meanwhile?) "
            "— rerun without --replace to publish it fresh",
        )
    if existing.kind != "docs" or existing.path != layout.relative(target):
        raise LibraryError(
            "kind_mismatch",
            f"slug {slug} is a {existing.kind} entry at {existing.path}; docs cannot replace it "
            f"— `perk librarian remove {slug}` first or choose another slug",
        )
    if target_present:
        require_unlinked_components(layout, layout.relative(target))
        if not target.is_dir():
            raise LibraryError("entry_path_invalid", f"{target} is not a directory")
    return existing


def _commit_publish(
    layout: LibraryLayout, staged: Path, target: Path, slug: str, catalog: Catalog
) -> Path | None:
    """Displace → swap → catalog write; on any failure roll back and raise ``io_error``.

    Returns the displaced prior revision's path (``None`` when there was none).
    """
    layout.documentation.mkdir(parents=True, exist_ok=True)
    previous: Path | None = None
    if target.exists():
        displaced = layout.documentation / f".{slug}.previous-{secrets.token_hex(6)}"
        try:
            target.rename(displaced)
        except OSError as exc:
            _rolled_back("displacing the prior revision", exc, [], intact=("staging", staged))
        previous = displaced
    restore_previous = [(previous, target)] if previous is not None else []
    try:
        staged.rename(target)
    except OSError as exc:
        _rolled_back(
            "moving the staged mirror into place", exc, restore_previous, intact=("staging", staged)
        )
    try:
        write_catalog(layout, catalog)
    except OSError as exc:
        _rolled_back(
            "writing the catalog",
            exc,
            [(target, staged), *restore_previous],
            intact=("staging", staged),
        )
    return previous


def _rolled_back(
    step: str, exc: OSError, moves: list[tuple[Path, Path]], *, intact: tuple[str, Path]
) -> NoReturn:
    """Undo ``moves`` in order, then raise ``io_error`` naming what was restored — or, when a
    rollback rename itself fails, every path the human must inspect."""
    label, intact_path = intact
    for source, destination in moves:
        try:
            source.rename(destination)
        except OSError as rollback_exc:
            involved = dict.fromkeys(path for move in moves for path in move)
            residue = ", ".join(
                f"{path} ({'present' if path.exists() else 'absent'})" for path in involved
            )
            raise LibraryError(
                "io_error",
                f"{step}: {exc}; rollback failed ({rollback_exc}) — residue: {residue}; "
                "inspect these paths (perk librarian list reports uncatalogued leftovers)",
            ) from exc
    raise LibraryError(
        "io_error", f"{step}: {exc}; the library was restored ({label} intact at {intact_path})"
    ) from exc


def _post_publish(target: Path, previous: Path | None) -> list[str]:
    """Best-effort cleanup after the commit — each failure is a warning, never a failure."""
    warnings: list[str] = []
    report = target / FAILED_PAGES_FILENAME
    if report.exists():
        try:
            report.unlink()
        except OSError as exc:
            warnings.append(f"crawl report left at {report} ({exc})")
    if previous is not None:
        try:
            shutil.rmtree(previous)
        except OSError as exc:
            warnings.append(f"prior revision left at {previous}; remove it by hand ({exc})")
    return warnings


def adopt(
    repo_root: Path,
    *,
    directory: Path,
    slug: str | None,
    source: str,
    stale_after: int | None,
    now: Clock | None = None,
) -> RecordOutcome:
    """Catalog a pre-existing uncatalogued directory as a docs entry, moving it to
    ``documentation/<slug>/`` when it lives elsewhere. Orphan-only: a directory a live entry
    owns is refused (never a rename)."""
    with translating_io("adopt"):
        layout = LibraryLayout.for_repo(repo_root)
        original = _validate_adoptee(layout, directory)
        chosen = _adopt_slug(original, slug)
        target = layout.docs_entry_dir(chosen)
        require_real_roots(layout)
        require_no_tracked_content(layout)
        require_unlinked_components(layout, layout.relative(target))
        require_ignored(layout, probe_paths_for(layout, dirs=[target, original]))
        with library_lock(repo_root):
            catalog = load_catalog(layout)
            owner = catalog.owner_of(layout.relative(original))
            if owner is not None:
                raise LibraryError(
                    "directory_catalogued",
                    f"{original} is already catalogued as {owner.slug}; `perk librarian remove "
                    f"{owner.slug}` first, or refresh it with `record --publish … --replace`",
                )
            if catalog.get(chosen) is not None or (
                (target.exists() or target.is_symlink()) and target != original
            ):
                raise LibraryError(
                    "slug_exists",
                    f"slug {chosen} is already taken in the library — pick another --slug",
                )
            markers, inventory_warning = read_inventory(original)
            moment = (now or utc_now)()
            entry = Entry(
                kind="docs",
                slug=chosen,
                source=source,
                path=layout.relative(target),
                added_at=format_ts(moment),
                stale_after=_stale_after(stale_after, None),
                upstream=DocsUpstream(pages=markers),
            )
            _commit_adopt(layout, original, target, catalog.with_entry(entry))
            view = _view(layout, entry, moment)
        warnings = (inventory_warning,) if inventory_warning is not None else ()
        return RecordOutcome(action="adopt", view=view, replaced_previous=False, warnings=warnings)


def _validate_adoptee(layout: LibraryLayout, directory: Path) -> Path:
    """The adoptee's canonical path: a real, symlink-free directory directly under the library
    root (not a reserved name) or directly under ``documentation/``."""
    candidate = directory.absolute()
    if not candidate.exists() and not candidate.is_symlink():
        raise LibraryError("adopt_not_found", f"{candidate} does not exist")
    if candidate.is_symlink() or not candidate.is_dir():
        raise LibraryError(
            "adopt_invalid", f"{candidate} is not a real directory (a symlink or a file)"
        )
    resolved = candidate.resolve()
    if resolved.parent == layout.root.resolve():
        if resolved.name in RESERVED_TOP_LEVEL:
            raise LibraryError(
                "adopt_invalid", f"{candidate} is a reserved library directory, not an entry"
            )
        original = layout.root / resolved.name
    elif resolved.parent == layout.documentation.resolve():
        original = layout.documentation / resolved.name
    else:
        raise LibraryError(
            "adopt_invalid",
            f"{candidate} must sit directly under {layout.root} or {layout.documentation}",
        )
    _refuse_symlinks(original, error_type="adopt_invalid")
    return original


def _adopt_slug(original: Path, slug: str | None) -> str:
    if slug is not None:
        return validate_slug(slug)
    try:
        return validate_slug(original.name)
    except LibraryError as exc:
        raise LibraryError(
            "invalid_slug",
            f"the directory name {original.name!r} is not a valid slug ({SLUG_GRAMMAR}) — pass "
            "--slug",
        ) from exc


def _commit_adopt(layout: LibraryLayout, original: Path, target: Path, catalog: Catalog) -> None:
    layout.documentation.mkdir(parents=True, exist_ok=True)
    moves: list[tuple[Path, Path]] = []
    if original != target:
        try:
            original.rename(target)
        except OSError as exc:
            _rolled_back(f"moving {original} to {target}", exc, [], intact=("directory", original))
        moves.append((target, original))
    try:
        write_catalog(layout, catalog)
    except OSError as exc:
        _rolled_back("writing the catalog", exc, moves, intact=("directory", original))


def remove(repo_root: Path, *, slug: str) -> RemoveOutcome:
    """Drop an entry from the catalog, then delete exactly its leaf entry directory.

    Catalog first: a failed deletion leaves an adoptable orphan ``list`` reports, never a
    dangling entry.
    """
    with translating_io("remove"):
        layout = LibraryLayout.for_repo(repo_root)
        require_real_roots(layout)
        require_no_tracked_content(layout)
        require_ignored(layout, [])
        with library_lock(repo_root):
            catalog = load_catalog(layout)
            entry = catalog.get(slug)
            if entry is None:
                raise LibraryError("entry_not_found", f"no library entry named {slug}")
            # The symlink walk first (git refuses to probe a path beyond a symlink), then the
            # ignore probe: deleting non-ignored content would change the untracked set.
            content = require_unlinked_components(layout, entry.path)
            require_ignored(layout, probe_paths_for(layout, dirs=[content]))
            write_catalog(layout, catalog.without(slug))
            removed = False
            if content.exists():
                try:
                    shutil.rmtree(content)
                except OSError as exc:
                    raise LibraryError(
                        "io_error",
                        f"entry {slug} removed from the catalog; content left at {content} "
                        f"({exc}) — adopt it again or delete it by hand",
                    ) from exc
                removed = True
        return RemoveOutcome(
            slug=slug, kind=entry.kind, absolute_path=content, content_removed=removed
        )
