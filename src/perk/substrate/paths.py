"""perk-owned dot-directory path construction (contracts.md §8.1).

This is the **sole** construction site for the perk-owned dot-path families — the perk dir,
the config files (`config.toml`/`local.toml`), the required-perk-version pin, the
committed managed-state file (`managed-state.toml`), the
repo-authored skills dir, and the user-level `~/.perk` family (the last-seen-version
store — the one perk-owned path outside the repo). The config family
now lives at `.perk/`; the legacy `.pi/perk.toml` / `.pi/perk.local.toml` paths are exposed only as
`legacy_*` helpers for the doctor migration (never read). The workflow family lives in the
established cache seam (``perk/state/cache.py::workflow_dir``); together these two modules own every
perk-owned dot-path. Remaining families migrate to `.perk/` one at a time —
redirecting a family is a single edit here (each family has its own redirection point; no shared
switch couples them). **Pi-native** `.pi/...` paths
(`.pi/settings.json`, `.pi/agents/`, `.pi/npm`, `.pi/APPEND_SYSTEM.md`, `~/.pi/agent`) are
intentionally *not* owned here — `.pi/` is not generally perk-owned, so those stay hand-built at
their Pi-native sites.

pathlib-only, no perk imports (a leaf so the guards can allowlist it cleanly).
"""

from pathlib import Path

CONFIG_FILENAME = "config.toml"
LOCAL_CONFIG_FILENAME = "local.toml"
REQUIRED_VERSION_FILENAME = "required-perk-version"
MANAGED_STATE_FILENAME = "managed-state.toml"
LAST_SEEN_VERSION_FILENAME = "last-seen-version"
# Legacy (pre-`.perk/`) config filenames — constructed only via the ``legacy_*`` helpers below for
# the doctor migration; never read by any config reader.
LEGACY_CONFIG_FILENAME = "perk.toml"
LEGACY_LOCAL_CONFIG_FILENAME = "perk.local.toml"
# Forward-slash relative string for display f-strings (kept byte-consistent with
# ``repo_skills_dir`` below — same `.perk/skills` literal text).
REPO_SKILLS_REL = ".perk/skills"


def perk_dir(root: Path) -> Path:
    """The perk-owned dot-dir root (shared with Pi today)."""
    return root / ".pi"


def config_dir(root: Path) -> Path:
    """The single config-family redirection point (the file helpers derive from it)."""
    return root / ".perk"


def config_file(root: Path) -> Path:
    """The committed `config.toml`."""
    return config_dir(root) / CONFIG_FILENAME


def local_config_file(root: Path) -> Path:
    """The gitignored `local.toml`."""
    return config_dir(root) / LOCAL_CONFIG_FILENAME


def required_version_file(root: Path) -> Path:
    """The committed required-perk-version pin (the repo's required perk CLI version)."""
    return config_dir(root) / REQUIRED_VERSION_FILENAME


def managed_state_file(root: Path) -> Path:
    """The committed `.perk/managed-state.toml` (managed-artifact version+hash state).

    Machine-written as a side effect of convergence (`perk init` / `perk doctor --fix`) and
    committed; deliberately **excluded from its own artifact/hash set** (no recursive churn).
    """
    return config_dir(root) / MANAGED_STATE_FILENAME


def legacy_config_file(root: Path) -> Path:
    """The legacy committed `.pi/perk.toml` (migration source only — never read)."""
    return root / ".pi" / LEGACY_CONFIG_FILENAME


def legacy_local_config_file(root: Path) -> Path:
    """The legacy gitignored `.pi/perk.local.toml` (migration source only — never read)."""
    return root / ".pi" / LEGACY_LOCAL_CONFIG_FILENAME


def repo_skills_dir(root: Path) -> Path:
    """The repo-authored skill source root."""
    return root / ".perk" / "skills"


def user_perk_dir() -> Path:
    """The user-level perk-owned dot-dir (machine-local, outside any repo).

    ``Path.home()`` can raise ``RuntimeError`` (no resolvable home) — the caller owns that
    guard, so this module stays pure construction.
    """
    return Path.home() / ".perk"


def last_seen_version_file() -> Path:
    """The user-level max-seen CLI version store (the post-upgrade-notice state)."""
    return user_perk_dir() / LAST_SEEN_VERSION_FILENAME
