"""The ``perk-dev`` CLI root group (dev-only maintainer tooling; never published).

The bare group + one ``smoke`` verb prove the cross-package dependency on ``perk``
resolves and that both reuse seams — perk's version-reading and its git/LBYL helpers —
are importable. Later nodes hang real ``changelog-*`` / ``release-*`` verbs off this group.
"""

from pathlib import Path

import click

from perk import __version__ as _perk_version
from perk.substrate.git import repo_root


@click.group()
@click.version_option(_perk_version, prog_name="perk-dev", message="%(prog)s %(version)s")
def cli() -> None:
    """perk's internal maintainer/release tooling (dev-only; never published)."""


@cli.command("smoke")
def smoke() -> None:
    """Smoke-check that perk-dev can reach perk's reused version + git helpers."""
    root = repo_root(Path.cwd())
    where = str(root) if root is not None else "(not a git repo)"
    click.echo(f"perk-dev smoke: perk {_perk_version} @ {where}")


def main() -> None:
    cli()
