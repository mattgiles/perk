"""Report-only runtime CLI-vs-repo version warning (contracts.md §8.6a).

Compares ``perk.__version__`` against the repo's committed ``.perk/required-perk-version`` pin
on interactive invocations and emits one soft stderr line on a mismatch — never fatal. The
pinned suppression ladder (all cheap LBYL gates run before any I/O, preserving the root
callback's cheap-by-design property for every non-interactive context):

1. ``PERK_SKIP_VERSION_CHECK`` non-empty (documented as ``=1``)
2. ``CI`` non-empty
3. non-TTY stderr (covers CliRunner, pipes, child processes)
4. ``--version`` / ``--help`` anywhere in argv (subcommand ``--help`` runs the group callback)
5. ``--json`` anywhere in argv (every machine-output command carries the house flag)
6. the ``run-worker`` worker door
7. outside a git repo
8. missing pin (presence/drift is the ``required-perk-version`` managed check's job)

An *unreadable* pin (``OSError`` after ``is_file()`` passed) is reported softly, never
swallowed — doctor's managed check owns the loud diagnosis; this line owns visibility.
"""

import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from perk import __version__
from perk.convergence.init.version_pin import read_version_pin
from perk.substrate import git
from perk.substrate.output import user_output

# The worker doors whose invocations are machine-driven even when argv/TTY gates miss them.
_SUPPRESSED_SUBCOMMANDS = frozenset({"run-worker"})


def version_mismatch_warning(
    *,
    argv: Sequence[str],
    subcommand: str | None,
    cwd: Path,
    env: Mapping[str, str],
    interactive: bool,
) -> str | None:
    """The one-line mismatch warning, or ``None`` when suppressed / matching.

    Pure over its inputs (no globals), so the suppression matrix tests without monkeypatching.
    """
    if env.get("PERK_SKIP_VERSION_CHECK"):
        return None
    if env.get("CI"):
        return None
    if not interactive:
        return None
    if "--version" in argv or "--help" in argv:
        return None
    if "--json" in argv:
        return None
    if subcommand in _SUPPRESSED_SUBCOMMANDS:
        return None
    root = git.repo_root(cwd)
    if root is None:
        return None
    try:
        pin = read_version_pin(root)
    except OSError as exc:
        # Reporting boundary (narrow class): the read itself is the authoritative test — no
        # cheap precise precondition exists for a permissions/race failure after `is_file()`.
        return f".perk/required-perk-version is unreadable ({exc}) — run `perk doctor` for details."
    if pin is None or pin == __version__:
        return None
    return (
        f"perk {__version__} != this repo's required perk version {pin} "
        "(.perk/required-perk-version) — upgrade perk, or re-run `perk init` if the pin is "
        "stale; set PERK_SKIP_VERSION_CHECK=1 to silence."
    )


def _interactive() -> bool:
    """Whether stderr is a TTY — the seam integration tests monkeypatch open."""
    return sys.stderr.isatty()


def maybe_warn_version_mismatch(subcommand: str | None, cwd: Path) -> None:
    """Production wrapper: build the real inputs and emit any warning to stderr."""
    message = version_mismatch_warning(
        argv=sys.argv[1:],
        subcommand=subcommand,
        cwd=cwd,
        env=os.environ,
        interactive=_interactive(),
    )
    if message is not None:
        user_output(f"\u26a0 {message}")
