"""The best-effort hunk-CLI install/verify gesture for the review seam.

The review seam's default provider (``hunk``) is an **external CLI** — a terminal TUI installed
as a global npm binary (``npm i -g hunkdiff``, binary ``hunk``), not a Pi package
(``package: null``, so provider-package convergence adds nothing). init/doctor own its
install/verify: ``ensure_review_cli`` is the verify-gated gesture (init's nicety + doctor's
``--fix`` retry), and ``hunk_cli_present`` / ``resolved_review_provider_id`` feed doctor's
warn-level ``review-cli`` check. Best-effort throughout — an install failure degrades to a
warning carrying the manual hint, never fatal (the ``_reconcile_extension_install`` posture).
"""

import shutil
import tomllib
from pathlib import Path

from perk.substrate import npm
from perk.substrate.config import ConfigError, load_config
from perk.substrate.providers import ProvidersError, resolve_providers

HUNK_BINARY = "hunk"
HUNK_NPM_SPEC = "hunkdiff"
HUNK_INSTALL_HINT = "npm i -g hunkdiff (or brew install hunk)"


def hunk_cli_present() -> bool:
    """True when the ``hunk`` binary is on PATH (a host probe — verify-gated by callers)."""
    return shutil.which(HUNK_BINARY) is not None


def resolved_review_provider_id(root: Path) -> str | None:
    """The resolved review-seam provider id for ``root``, or ``None`` on any load failure.

    **Fail toward no mutation**: a malformed/ill-typed config.toml (the selection cannot be
    trusted — it could hide a non-``hunk`` pick) and a corrupt bundled providers file both return
    ``None`` — the config/providers checks own surfacing those failures; the callers here must
    never install onto uncertain state.
    """
    try:
        selection = load_config(root).providers
    except (tomllib.TOMLDecodeError, ConfigError):
        return None
    try:
        return resolve_providers(selection).review.id
    except ProvidersError:
        return None


def ensure_review_cli(root: Path) -> tuple[list[str], list[str]]:
    """Install the ``hunk`` CLI when the review selection needs it and it is absent.

    Returns ``(changes, warnings)``. No-op unless the resolved review provider is ``hunk`` and
    the binary is missing; then attempts the global npm install — success yields one change line,
    ``NpmError`` degrades to one warning carrying the manual install hint. Never raises: a
    network/install failure must not block init or ``doctor --fix``.
    """
    # The provider id ("hunk", the catalog row) happens to share the binary's name; the id is
    # what the selection resolves to.
    if resolved_review_provider_id(root) != "hunk":
        return ([], [])
    if hunk_cli_present():
        return ([], [])
    try:
        npm.install_global(HUNK_NPM_SPEC)
    except npm.NpmError as exc:
        return ([], [f"hunk CLI install failed ({exc}); install it manually: {HUNK_INSTALL_HINT}"])
    return ([f"hunk CLI: installed {HUNK_NPM_SPEC} (npm -g)"], [])
