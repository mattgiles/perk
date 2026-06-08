"""perk's TOML config (Q13): `.pi/perk.toml` (committed) overlaid by `.pi/perk.local.toml`
(gitignored). Read-only via stdlib ``tomllib``; ``perk init`` *writes* the files.

T4 needs only the worktree root; the ``Config`` dataclass grows as later turns add settings.
LBYL throughout (missing files -> defaults); a malformed file's ``TOMLDecodeError`` is
translated to a ``UserFacingCliError`` at the CLI boundary (``require_config``).
"""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from perk.bindings import Binding, parse_user_bindings

CONFIG_FILENAME = "perk.toml"
LOCAL_CONFIG_FILENAME = "perk.local.toml"
DEFAULT_WORKTREE_DIRNAME = ".worktrees"


@dataclass(frozen=True)
class Config:
    """Resolved perk config. ``worktree_root`` is absolute."""

    worktree_root: Path
    user_bindings: list[Binding] = field(default_factory=list)
    # The `[pr-review] model` selection (#175) — the configurable `/pr-review` reviewer model, or
    # None when unset (the `perk.pr-reviewer` agent's frontmatter model is then the default). Read
    # for forward parity; today only the TS warm path consumes it (no cold `/pr-review` door yet).
    pr_review_model: str | None = None
    # The raw `[providers]` per-seam selection (provider-id strings or None when absent). Exposed
    # raw — resolution against the supported set happens in `init`/`providers` (mirroring how
    # `user_bindings` is raw and `resolve_bindings` resolves it).
    providers: dict[str, str | None] = field(default_factory=dict)


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
    return Config(
        worktree_root=root,
        user_bindings=parse_user_bindings(merged.get("bindings")),
        providers=_parse_providers_selection(merged.get("providers")),
        pr_review_model=_parse_pr_review_model(merged.get("pr-review")),
    )


def _parse_pr_review_model(raw: Any) -> str | None:
    """Read `[pr-review] model` (a string) from the merged config; ``None`` if absent/ill-typed."""
    if isinstance(raw, dict) and isinstance(model := raw.get("model"), str) and model.strip():
        return model
    return None


def _parse_providers_selection(raw: Any) -> dict[str, str | None]:
    """Read the flat `[providers]` table into a `{plan, todo}` selection (string values only).

    A non-dict table (absent) yields ``{}``; only `plan`/`todo` keys with **string** values are
    kept (an absent/ill-typed key is simply omitted, so the resolver falls back to the seam
    default silently for it).
    """
    table = raw if isinstance(raw, dict) else {}
    return {seam: value for seam in ("plan", "todo") if isinstance(value := table.get(seam), str)}
