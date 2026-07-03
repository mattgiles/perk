"""``perk release-notes`` — show the bundled changelog's release notes.

An informational human command: output goes to stderr via ``user_output`` (guidelines §7.1),
there is no ``--json`` surface, and every expected miss (unknown version, unreadable changelog)
is a ``UserFacingCliError`` — never a traceback.
"""

import re

import click

from perk import __version__
from perk._resources import changelog_path
from perk.cli.ensure import UserFacingCliError
from perk.release_notes import (
    find_release,
    parse_release_notes,
    render_release,
    render_releases,
)
from perk.substrate.output import user_output

_VERSION_SHAPE_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _cli_version() -> str:
    """The running CLI's version (a named seam so tests can pin the default selection)."""
    return __version__


@click.command("release-notes")
@click.option("--all", "show_all", is_flag=True, help="Show every released version (newest first).")
@click.option("--version", "version", metavar="X.Y.Z", help="Show one specific release.")
def release_notes_cmd(*, show_all: bool, version: str | None) -> None:
    """Show perk's bundled release notes.

    By default shows the notes for the perk version you are running; --all shows every
    released version (newest first); --version X.Y.Z shows one specific release. Notes are
    read from the CHANGELOG.md bundled with the perk package (works outside a git repo);
    [Unreleased] entries are never shown.
    """
    if show_all and version is not None:
        raise UserFacingCliError("Pass either --all or --version X.Y.Z, not both.")
    if version is not None and _VERSION_SHAPE_RE.match(version) is None:
        raise UserFacingCliError(f"--version expects an X.Y.Z version, got {version!r}.")

    # The one EAFP boundary in the feature: the read itself is the authoritative test (no
    # cheap precise precondition for a permissions/race failure). OSError subsumes
    # FileNotFoundError, including changelog_path()'s both-locations-miss raise.
    try:
        text = changelog_path().read_text(encoding="utf-8")
    except OSError as exc:
        raise UserFacingCliError(f"Could not read perk's bundled changelog: {exc}") from exc

    releases = parse_release_notes(text)
    if show_all:
        if not releases:
            raise UserFacingCliError("No releases found in perk's bundled changelog.")
        user_output(render_releases(releases))
        return

    requested = version if version is not None else _cli_version()
    release = find_release(releases, requested)
    if release is None:
        available = ", ".join(r.version for r in releases)
        listing = f" Available: {available}." if available else ""
        raise UserFacingCliError(
            f"No release notes for perk {requested} in the bundled changelog."
            f"{listing} Use --all to see every release."
        )
    user_output(render_release(release))
