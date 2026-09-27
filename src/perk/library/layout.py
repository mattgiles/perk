"""The perk library's on-disk layout, resolved to the MAIN checkout from any worktree.

``docs/library/`` holds ``documentation/<slug>/`` mirrors, ``source-code/<host>/<org>/<repo>/``
checkouts, ``.staging/<dir>/`` in-progress crawls, the machine-owned ``catalog.json`` and the
committed ``README.md`` (contracts.md §8.74(a)). ``paths.library_dir`` is the one construction
site; :func:`library_root` / :meth:`LibraryLayout.for_repo` add the main-checkout resolution so a
linked worktree and the main checkout address one library.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from perk.library.errors import LibraryError
from perk.substrate import git, paths

type Kind = Literal["docs", "source"]

DOCUMENTATION_DIRNAME = "documentation"
SOURCE_CODE_DIRNAME = "source-code"
STAGING_DIRNAME = ".staging"
RESERVED_TOP_LEVEL = frozenset({DOCUMENTATION_DIRNAME, SOURCE_CODE_DIRNAME, STAGING_DIRNAME})
CATALOG_FILENAME = "catalog.json"
README_FILENAME = "README.md"
INVENTORY_FILENAME = "sources.json"
FAILED_PAGES_FILENAME = "failed-pages.json"
ENTRYPOINT_FILENAME = "index.md"

SLUG_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
SLUG_GRAMMAR = (
    "lowercase letters, digits, '.', '_' or '-', starting with a letter or digit, at most 64 "
    "characters, no '..'"
)
# One segment of a source-code entry path (`<host>`, `<org>`, `<repo>`).
_SOURCE_SEGMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def library_root(repo_root: Path) -> Path:
    """The library root of the MAIN checkout containing ``repo_root``."""
    return paths.library_dir(git.main_worktree_root(repo_root) or repo_root)


@dataclass(frozen=True)
class LibraryLayout:
    """The library's paths, anchored at the main checkout (``root`` is absolute)."""

    main_root: Path
    root: Path

    @classmethod
    def for_repo(cls, repo_root: Path) -> "LibraryLayout":
        main_root = git.main_worktree_root(repo_root) or repo_root
        return cls(main_root=main_root, root=paths.library_dir(main_root))

    @property
    def documentation(self) -> Path:
        return self.root / DOCUMENTATION_DIRNAME

    @property
    def source_code(self) -> Path:
        return self.root / SOURCE_CODE_DIRNAME

    @property
    def staging(self) -> Path:
        return self.root / STAGING_DIRNAME

    @property
    def catalog_path(self) -> Path:
        return self.root / CATALOG_FILENAME

    @property
    def readme_path(self) -> Path:
        return self.root / README_FILENAME

    @property
    def content_roots(self) -> tuple[Path, Path]:
        return (self.documentation, self.source_code)

    def docs_entry_dir(self, slug: str) -> Path:
        return self.documentation / slug

    def relative(self, path: Path) -> str:
        """``path`` relative to the library root, POSIX — the catalog ``path`` form.

        Lexical: ``path`` must already be spelled under ``root``.
        """
        return path.relative_to(self.root).as_posix()

    def relative_to_main(self, path: Path) -> str:
        """``path`` relative to the main checkout, POSIX — the git pathspec form (lexical)."""
        return path.relative_to(self.main_root).as_posix()


def validate_slug(slug: str) -> str:
    """Return ``slug`` when it matches the slug grammar; else ``invalid_slug``."""
    if SLUG_RE.fullmatch(slug) is None or ".." in slug:
        raise LibraryError("invalid_slug", f"invalid slug {slug!r}: use {SLUG_GRAMMAR}")
    return slug


def entry_path_shape(kind: Kind, path: str) -> bool:
    """Whether ``path`` is a well-formed catalog entry path for ``kind``.

    A relative POSIX path with no empty/``.``/``..`` segments and no backslash; ``docs`` is
    exactly ``documentation/<slug>``, ``source`` exactly ``source-code/<host>/<org>/<repo>``.
    Every catalogued path is therefore a leaf entry directory — never a content root, a shared
    ancestor, or another entry's directory.
    """
    if not path or "\\" in path or path.startswith("/"):
        return False
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return False
    if kind == "docs":
        return (
            len(parts) == 2
            and parts[0] == DOCUMENTATION_DIRNAME
            and SLUG_RE.fullmatch(parts[1]) is not None
            and ".." not in parts[1]
        )
    return (
        len(parts) == 4
        and parts[0] == SOURCE_CODE_DIRNAME
        and all(_SOURCE_SEGMENT_RE.fullmatch(part) is not None for part in parts[1:])
    )
