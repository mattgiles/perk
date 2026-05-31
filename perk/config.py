"""perk's TOML config (Q13): `.pi/perk.toml` (committed) overlaid by `.pi/perk.local.toml`
(gitignored). Read-only via stdlib ``tomllib``; ``perk init`` *writes* the files.

T4 needs only the worktree root; the ``Config`` dataclass grows as later turns add settings.
LBYL throughout (missing files -> defaults); a malformed file's ``TOMLDecodeError`` is
translated to a ``UserFacingCliError`` at the CLI boundary (``require_config``).
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONFIG_FILENAME = "perk.toml"
LOCAL_CONFIG_FILENAME = "perk.local.toml"
DEFAULT_WORKTREE_DIRNAME = ".worktrees"


@dataclass(frozen=True)
class Config:
    """Resolved perk config. ``worktree_root`` is absolute."""

    worktree_root: Path


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _overlay(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``over`` onto ``base`` (local wins; tables merge, leaves replace)."""
    merged = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _overlay(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(repo_root: Path) -> Config:
    """Load ``.pi/perk.toml`` overlaid by ``.pi/perk.local.toml`` from ``repo_root``."""
    pi_dir = repo_root / ".pi"
    merged: dict[str, Any] = {}
    for name in (CONFIG_FILENAME, LOCAL_CONFIG_FILENAME):
        merged = _overlay(merged, _read_toml(pi_dir / name))

    worktree = merged.get("worktree")
    root_value = worktree.get("root") if isinstance(worktree, dict) else None
    root = Path(root_value) if isinstance(root_value, str) else Path(DEFAULT_WORKTREE_DIRNAME)
    if not root.is_absolute():
        root = repo_root / root
    return Config(worktree_root=root)
