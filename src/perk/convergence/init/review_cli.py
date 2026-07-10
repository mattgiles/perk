"""The best-effort hunk-CLI install/verify gesture (a review *surface*, unconditional).

The ``hunk`` CLI is an **external CLI** — a terminal TUI installed as a global npm binary
(``npm i -g hunkdiff``, binary ``hunk``), not a Pi package (so provider-package convergence adds
nothing). init/doctor converge it **unconditionally** — it is the review surface
``/pr-review-terminal`` drives, kept available regardless of config. ``ensure_review_cli`` is the
verify-gated gesture (init's nicety + doctor's ``--fix`` retry), and ``hunk_cli_present`` feeds
doctor's warn-level ``review-cli`` check. Best-effort throughout — an install failure degrades to
a warning carrying the manual hint, never fatal (the ``_reconcile_extension_install`` posture).
"""

import shutil
from pathlib import Path

from perk.substrate import npm

HUNK_BINARY = "hunk"
HUNK_NPM_SPEC = "hunkdiff"
HUNK_INSTALL_HINT = "npm i -g hunkdiff (or brew install hunk)"


def hunk_cli_present() -> bool:
    """True when the ``hunk`` binary is on PATH (a host probe — verify-gated by callers)."""
    return shutil.which(HUNK_BINARY) is not None


def ensure_review_cli(root: Path) -> tuple[list[str], list[str]]:
    """Install the ``hunk`` CLI when it is absent — unconditionally, no selection read.

    Returns ``(changes, warnings)``. Binary present → no-op; absent → attempt the global npm
    install — success yields one change line, ``NpmError`` degrades to one warning carrying the
    manual install hint. Never raises: a network/install failure must not block init or
    ``doctor --fix``. The ``root`` parameter is unused (the gesture reads no config) but retained
    as the patchable seam's signature — the conftest stub and both call sites pass it.
    """
    if hunk_cli_present():
        return ([], [])
    try:
        npm.install_global(HUNK_NPM_SPEC)
    except npm.NpmError as exc:
        return ([], [f"hunk CLI install failed ({exc}); install it manually: {HUNK_INSTALL_HINT}"])
    return ([f"hunk CLI: installed {HUNK_NPM_SPEC} (npm -g)"], [])
