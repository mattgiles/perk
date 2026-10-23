"""Isolated staging of an npm install root: a copy-on-write clone, else hardlinks + own metadata.

A worktree's ``.pi/npm`` is staged from the main checkout's so Pi installs nothing at startup,
without paying a full byte copy (hundreds of MB per worktree). What each tier isolates:

- **clonefile** (macOS): ``clonefile(2)`` on the directory clones the whole hierarchy in one call —
  independent inodes everywhere, data blocks shared until a byte diverges. Fully isolated.
- **hardlink** (every platform): per-file hardlinks, then :func:`detach_shared_files`. Only the
  install root's own metadata files (``package.json``, the lockfiles,
  ``node_modules/.package-lock.json`` …) get their own inodes — the package manager and Pi rewrite
  those **in place**, so a shared inode there leaks every install across trees. Package files
  stay **shared**: every package manager Pi supports replaces a package by removing and
  re-extracting its directory, which breaks the links, but a tool that patches an installed
  package's files in place writes through to every tree that shares them.

There is deliberately no byte-copy tier. ``shutil.copy2`` is not a clone on macOS (CPython's fast
path is ``fcopyfile(COPYFILE_DATA)``, a byte copy), and ``copyfile(3)``'s best-effort clone flag
silently degrades to one — the exact cost this module exists to avoid.
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Literal

CloneMethod = Literal["clonefile", "hardlink"]


def _detach(path: Path) -> None:
    """Give ``path`` its own inode with identical bytes and mode (copy beside, then replace)."""
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".perk-detach", dir=path.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        shutil.copy2(path, tmp)
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def detach_shared_files(root: Path) -> int:
    """Give every shared regular file at depth <= 1 of the install root ``root`` its own inode.

    Depth <= 1 is the entries directly under ``root`` and directly under ``root/node_modules`` —
    whatever the package manager writes there (``package.json``, ``package-lock.json``,
    ``yarn.lock``, ``pnpm-lock.yaml``, ``bun.lock``, ``.gitignore``,
    ``node_modules/.package-lock.json``, ``node_modules/.modules.yaml`` …). Only regular,
    non-symlink files with ``st_nlink > 1`` are touched; package directories never are. Returns
    the number of files detached — idempotent (a second call returns ``0``). A missing
    ``node_modules`` is skipped; any other ``OSError`` propagates.
    """
    detached = 0
    for directory in (root, root / "node_modules"):
        if directory != root and not directory.is_dir():
            continue
        with os.scandir(directory) as entries:
            shared = [
                Path(entry.path)
                for entry in entries
                if entry.is_file(follow_symlinks=False)
                and entry.stat(follow_symlinks=False).st_nlink > 1
            ]
        for path in sorted(shared):
            _detach(path)
            detached += 1
    return detached


def _clonefile(src: Path, dst: Path) -> bool:
    """One ``clonefile(2)`` of the hierarchy ``src`` → ``dst``; ``False`` when unavailable/failed.

    A failure removes whatever partial hierarchy the call left, so the next tier starts clean.
    """
    # Tiered import: the Pi exec pipeline imports this module for the detach rule on every launch
    # (the bare-`perk` path), and only the clone tier needs ctypes.
    import ctypes  # noqa: PLC0415 — tiered import

    try:
        clonefile = ctypes.CDLL(None, use_errno=True).clonefile
    except (OSError, AttributeError):
        return False
    clonefile.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32)
    clonefile.restype = ctypes.c_int
    if clonefile(os.fsencode(src), os.fsencode(dst), 0) == 0:
        return True
    shutil.rmtree(dst, ignore_errors=True)
    return False


def clone_tree(src: Path, dst: Path) -> CloneMethod:
    """Stage the directory ``src`` at the absent path ``dst``; return the tier used.

    ``clonefile`` on macOS (fully independent); otherwise (or when it fails — another volume, a
    filesystem without clones) per-file hardlinks with symlinks recreated as symlinks (what
    ``clonefile`` does), then :func:`detach_shared_files` — private metadata, shared package
    files. Raises ``FileExistsError`` when ``dst`` exists and ``OSError``
    when neither tier works — after removing the partial tree, which holds only links, never
    byte copies.
    """
    if os.path.lexists(dst):
        raise FileExistsError(f"clone destination already exists: {dst}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "darwin" and _clonefile(src, dst):
        return "clonefile"
    try:
        shutil.copytree(src, dst, symlinks=True, copy_function=os.link)
        detach_shared_files(dst)
    except OSError:
        shutil.rmtree(dst, ignore_errors=True)
        raise
    return "hardlink"
