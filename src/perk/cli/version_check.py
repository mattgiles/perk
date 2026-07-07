"""The two report-only startup version surfaces (contracts.md §8.6a).

**Mismatch warning**: compares ``perk.__version__`` against the repo's committed
``.perk/required-perk-version`` pin on interactive invocations and emits one soft stderr line
on a mismatch — never fatal. The pinned suppression ladder (all cheap LBYL gates run before
any I/O, preserving the root callback's cheap-by-design property for every non-interactive
context):

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

**Post-upgrade notice**: a one-line pointer at ``perk release-notes`` on the first interactive
run after an upgrade, backed by the user-level ``~/.perk/last-seen-version`` max-seen store.
Its ladder is gates 1-6 above (the shared ``_suppressed`` helper — same rules by construction)
with **no repo gate**: it fires outside a git repo too, like ``perk release-notes`` itself.
Semantics: record-then-notice (the notice shows only after the record succeeds); first run and
garbage stored content record silently; equal stored version is a no-op with no write;
downgrades never lower the max seen; suppressed invocations perform **no store I/O** (so a
machine run never consumes the notice). Every store failure degrades silently.
"""

import os
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from perk import __version__
from perk.convergence.init.version_pin import read_version_pin
from perk.substrate import git, paths
from perk.substrate.output import user_output

# The worker doors whose invocations are machine-driven even when argv/TTY gates miss them.
_SUPPRESSED_SUBCOMMANDS = frozenset({"run-worker"})


def _suppressed(
    *,
    argv: Sequence[str],
    subcommand: str | None,
    env: Mapping[str, str],
    interactive: bool,
) -> bool:
    """The six shared suppression gates, pinned order — all cheap LBYL, no I/O.

    Shared by both startup surfaces (mismatch warning + upgrade notice), so "same suppression
    rules" is structural, not aspirational.
    """
    if env.get("PERK_SKIP_VERSION_CHECK"):
        return True
    if env.get("CI"):
        return True
    if not interactive:
        return True
    if "--version" in argv or "--help" in argv:
        return True
    if "--json" in argv:
        return True
    return subcommand in _SUPPRESSED_SUBCOMMANDS


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
    if _suppressed(argv=argv, subcommand=subcommand, env=env, interactive=interactive):
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


_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _parse_version(text: str) -> tuple[int, int, int] | None:
    """A strict ``X.Y.Z`` parse to an int 3-tuple — perk versions carry no pre-release forms."""
    match = _VERSION_RE.match(text)
    if match is None:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _decide_last_seen(stored: str | None, current: str) -> tuple[str | None, bool]:
    """The pure decision: ``(version_to_record_or_None, show_notice)``.

    - no/garbage stored value → record silently (first run, or self-heal — can't know it was
      an upgrade);
    - equal → no-op, no write;
    - upgrade → record + notice;
    - downgrade → no-op (the max seen is never lowered);
    - unparseable ``current`` → no-op (defensive; perk versions are plain ``X.Y.Z``).
    """
    current_parsed = _parse_version(current)
    if current_parsed is None:
        return (None, False)
    stored_parsed = _parse_version(stored) if stored is not None else None
    if stored_parsed is None:
        return (current, False)
    if stored_parsed == current_parsed:
        return (None, False)
    if stored_parsed < current_parsed:
        return (current, True)
    return (None, False)


def _record_last_seen(store: Path, version: str) -> bool:
    """Write the max-seen version; ``False`` on failure."""
    # Silent-degrade boundary (deviation from the report-never-silent norm, deliberate): the
    # store is a pure UX nicety with no remediation surface — no doctor check owns it — and a
    # soft report here would itself become permanent per-invocation noise.
    try:
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(f"{version}\n", encoding="utf-8")
    except OSError:
        return False
    return True


def upgrade_notice(
    *,
    argv: Sequence[str],
    subcommand: str | None,
    env: Mapping[str, str],
    interactive: bool,
    store: Path,
) -> str | None:
    """The one-line post-upgrade notice, or ``None`` when suppressed / not an upgrade.

    Pure over its inputs like its sibling. Suppressed invocations return before **any** store
    I/O (no read, no record) — keeps the root callback cheap for machine/CI/piped paths, and
    means a machine run never consumes the notice: it shows on the first *interactive* run
    after an upgrade. Record-then-notice: an unrecordable upgrade shows nothing (showing it
    would repeat every run, violating "once").
    """
    if _suppressed(argv=argv, subcommand=subcommand, env=env, interactive=interactive):
        return None
    try:
        stored = store.read_text(encoding="utf-8").strip()
    except OSError:
        # Missing file (first run) and an unreadable store degrade identically: treat as
        # never-seen and self-heal via the record below.
        stored = None
    record, show_notice = _decide_last_seen(stored, __version__)
    if record is not None and not _record_last_seen(store, record):
        return None
    if not show_notice:
        return None
    return f"perk updated to {__version__}; run `perk release-notes` for what's new."


def maybe_notice_upgrade(subcommand: str | None) -> None:
    """Production wrapper: build the real inputs and emit any notice to stderr."""
    try:
        store = paths.last_seen_version_file()
    except RuntimeError:
        # `Path.home()` found no resolvable home — the same silent-degrade posture as every
        # other store failure.
        return
    message = upgrade_notice(
        argv=sys.argv[1:],
        subcommand=subcommand,
        env=os.environ,
        interactive=_interactive(),
        store=store,
    )
    if message is not None:
        user_output(message)
