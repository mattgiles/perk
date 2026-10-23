"""Write admission for perk's two convergence writers: ``perk init`` and ``perk doctor --fix``.

Both rewrite perk's managed files toward the **running** perk's desired state, so a perk that is
not the one this checkout expects converges them backward. The refusal runs before any repo write
(contracts.md §8.5 / §8.6 / §8.6a):

- **perk's own repo** (``self_repo``): the running perk's own checkout must **be** the converged
  checkout. ``perk/__init__.py`` lives at ``<checkout>/src/perk/__init__.py``, so an editable
  install resolves its checkout as ``parents[2]``; a site-packages install resolves to an
  unrelated directory. Equality, never containment — linked worktrees nest under
  ``<main>/.worktrees/``, so a containment test would admit a stale worktree converging main.
- **a consumer repo**: the running perk must not be older than ``.perk/required-perk-version``
  (semver precedence). Equal converges; a newer perk moves the pin forward. A missing, unreadable
  or unparseable pin never refuses — the ``required-perk-version`` managed check owns that
  diagnosis.

``perk.__file__`` / ``perk.__version__`` are read at call time (the test seams).
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import perk
from perk.convergence.version_pin import read_version_pin
from perk.substrate.semver import compare_semver, parse_semver

WriteRefusalType = Literal["foreign_perk", "perk_outdated"]


@dataclass(frozen=True)
class WriteRefusal:
    """Why the running perk may not converge this checkout (a typed exit-2 refusal)."""

    error_type: WriteRefusalType
    message: str


def running_checkout() -> Path:
    """The checkout the running perk was imported from (``<checkout>/src/perk/__init__.py``)."""
    return Path(perk.__file__).resolve().parents[2]


def write_refusal(root: Path, *, self_repo: bool) -> WriteRefusal | None:
    """The refusal for converging ``root`` with the running perk, or ``None`` when admitted."""
    version = perk.__version__
    if self_repo:
        checkout = running_checkout()
        target = root.resolve()
        if checkout == target:
            return None
        return WriteRefusal(
            "foreign_perk",
            f"perk {version} is running from {checkout}, not from this checkout ({target}). "
            "In perk's own repo, perk init and perk doctor --fix converge only from the "
            "checkout's own install: run them as `uv run perk …` here.",
        )
    try:
        pin = read_version_pin(root)
    except (OSError, UnicodeDecodeError):
        return None
    if pin is None:
        return None
    pinned = parse_semver(pin)
    running = parse_semver(version)
    if pinned is None or running is None or compare_semver(running, pinned) >= 0:
        return None
    return WriteRefusal(
        "perk_outdated",
        f"perk {version} is older than this repo's required perk version {pin} "
        "(.perk/required-perk-version) — upgrade perk before running init or doctor --fix; a "
        "newer perk converges the pin forward.",
    )
