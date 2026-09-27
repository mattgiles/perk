"""The cache-only preflight (contracts.md §8.75(d)) — the read-only-invariant carve-out, made
operational.

The library is a gitignored cache, not repository content, so the workers may run in read-only
perk sessions — but only because these checks refuse any operation that would create, modify
or delete a non-ignored or tracked path. Pure git reads + ``lstat``; no writes. The mutating
workers call them BEFORE ``library_lock`` is taken, so a refused repository sees zero
filesystem effects (not even the lock file).

The ignore probes are representative coverage by path class, not a proof: a ``.gitignore``
edit racing a worker between preflight and mutation is outside the threat model.
"""

from collections.abc import Iterable
from pathlib import Path, PurePosixPath

from perk.library.errors import LibraryError
from perk.library.layout import ENTRYPOINT_FILENAME, README_FILENAME, LibraryLayout
from perk.library.lock import lock_rel
from perk.substrate import git, paths

_TRACKED_SHOWN = 5


def require_real_roots(layout: LibraryLayout) -> None:
    """The library root must resolve to ``<main>/docs/library`` and every existing root
    (library, ``documentation/``, ``source-code/``, ``.staging/``) must be a real directory.

    The fence is established on the canonical roots — never by trusting a potentially
    redirected parent — so a symlinked ``docs/`` or ``docs/library`` fails too.
    """
    expected = paths.library_dir(layout.main_root.resolve())
    if layout.root.resolve() != expected:
        raise _root_invalid(layout, layout.root)
    for root in (layout.root, layout.documentation, layout.source_code, layout.staging):
        if root.is_symlink() or (root.exists() and not root.is_dir()):
            raise _root_invalid(layout, root)


def _root_invalid(layout: LibraryLayout, path: Path) -> LibraryError:
    return LibraryError(
        "library_root_invalid",
        f"{path} is a symlink or resolves outside {paths.library_dir(layout.main_root)} — "
        "refusing to mutate the library through a redirected root",
    )


def require_no_tracked_content(layout: LibraryLayout) -> None:
    """Nothing under ``docs/library/`` may be tracked except the committed README."""
    readme = f"{paths.LIBRARY_REL}/{README_FILENAME}"
    tracked = git.tracked_paths(layout.main_root, [f":(literal){paths.LIBRARY_REL}"])
    offenders = [path for path in tracked if path != readme]
    if not offenders:
        return
    shown = ", ".join(offenders[:_TRACKED_SHOWN])
    more = f", +{len(offenders) - _TRACKED_SHOWN}" if len(offenders) > _TRACKED_SHOWN else ""
    raise LibraryError(
        "library_tracked_content",
        f"{paths.LIBRARY_REL}/ carries committed content ({shown}{more}) — the library is a "
        "gitignored cache; untrack it (git rm --cached) before using perk librarian",
    )


def require_ignored(layout: LibraryLayout, mutation_paths: Iterable[str]) -> None:
    """Every probe must be gitignored: the fixed base set (the catalog, a representative
    atomic-write temp sibling, the lock file) plus the operation's ``mutation_paths``."""
    catalog = layout.relative_to_main(layout.catalog_path)
    base = [catalog, f"{catalog}.probe.tmp", lock_rel()]
    probes = list(dict.fromkeys([*base, *mutation_paths]))
    ignored = git.ignored_subset(layout.main_root, probes)
    missing = [probe for probe in probes if probe not in ignored]
    if missing:
        raise LibraryError(
            "library_not_ignored",
            "these library paths are not gitignored in this checkout: "
            f"{', '.join(missing)} — run `perk init` (or `perk doctor --fix`) to reconverge the "
            "managed .gitignore block, then rerun",
        )


def probe_paths_for(layout: LibraryLayout, *, dirs: Iterable[Path]) -> list[str]:
    """Each mutated directory as a nested nonexistent file (``<dir>/index.md``, relative to the
    main checkout) — a rule must cover the directory's descendants, and a negation for one
    specific entry is caught."""
    return [f"{layout.relative_to_main(directory)}/{ENTRYPOINT_FILENAME}" for directory in dirs]


def require_unlinked_components(layout: LibraryLayout, rel_path: str) -> Path:
    """Walk ``rel_path`` from the library root, refusing (``entry_path_invalid``) when any
    component is a symlink; return the absolute path."""
    current = layout.root
    for part in PurePosixPath(rel_path).parts:
        current = current / part
        if current.is_symlink():
            raise LibraryError(
                "entry_path_invalid",
                f"{current} is a symlink — refusing to touch a library entry through a "
                "redirected path",
            )
    return current
