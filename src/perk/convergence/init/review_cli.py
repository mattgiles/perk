"""The best-effort hunk-CLI install/verify gesture (a review *surface*, unconditional).

The ``hunk`` CLI is an **external CLI** — a terminal TUI installed as a global npm binary
(``npm i -g hunkdiff``, binary ``hunk``), not a Pi package (so provider-package convergence adds
nothing). init/doctor converge it **unconditionally** — it is the review surface
``/pr-review-terminal`` drives, kept available regardless of config. ``ensure_review_cli`` is the
verify-gated gesture (init's nicety + doctor's ``--fix`` retry), and ``hunk_cli_present`` feeds
doctor's warn-level ``review-cli`` check. Best-effort throughout — an install failure degrades to
a warning carrying the manual hint, never fatal (the ``_reconcile_extension_install`` posture).
"""

from pathlib import Path

from perk.substrate import npm
from perk.substrate.proc import which_absolute

HUNK_BINARY = "hunk"
HUNK_NPM_SPEC = "hunkdiff"
HUNK_INSTALL_HINT = "npm i -g hunkdiff (or brew install hunk)"


def hunk_cli_path() -> str | None:
    """Absolute path of the ``hunk`` binary on PATH, or ``None`` when absent (a host probe).

    The exec-carrying variant of :func:`hunk_cli_present`: a launcher that chdirs before
    exec'ing hunk must resolve the absolute path FIRST and exec that path — re-resolving the
    bare name after the chdir would let a relative ``PATH`` entry (e.g. ``.``) pick up an
    executable inside the target directory. Delegates to :func:`which_absolute` because
    ``shutil.which`` alone can return a *relative* candidate (when the matching ``PATH`` entry
    is itself relative) that a post-chdir exec would reinterpret under the worktree.
    """
    return which_absolute(HUNK_BINARY)


def hunk_cli_present() -> bool:
    """True when the ``hunk`` binary is on PATH (a host probe — verify-gated by callers)."""
    return hunk_cli_path() is not None


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
