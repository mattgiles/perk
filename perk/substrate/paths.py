"""perk-owned dot-directory path construction (contracts.md §8.1).

This is the **sole** construction site for the four perk-owned dot-path families — the perk dir,
the config files (`config.toml`/`local.toml`), and the repo-authored skills dir. The config family
now lives at `.perk/`; the legacy `.pi/perk.toml` / `.pi/perk.local.toml` paths are exposed only as
`legacy_*` helpers for the doctor migration (never read). The workflow family lives in the
established cache seam (``perk/state/cache.py::workflow_dir``); together these two modules own every
perk-owned dot-path. Objective #878 migrates each family to `.perk/` one phase at a time —
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


def legacy_config_file(root: Path) -> Path:
    """The legacy committed `.pi/perk.toml` (migration source only — never read)."""
    return root / ".pi" / LEGACY_CONFIG_FILENAME


def legacy_local_config_file(root: Path) -> Path:
    """The legacy gitignored `.pi/perk.local.toml` (migration source only — never read)."""
    return root / ".pi" / LEGACY_LOCAL_CONFIG_FILENAME


def repo_skills_dir(root: Path) -> Path:
    """The repo-authored skill source root."""
    return root / ".perk" / "skills"
