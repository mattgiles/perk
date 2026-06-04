"""Command aliases for the perk CLI (adapted from erk's ``cli_alias``/``cli_group``).

perk has no shared CLI package, so the whole (small) mechanism lives here:

- ``@alias(...)`` annotates a ``click.Command`` with extra invocation names. It must be
  listed **above** ``@click.command``/``@<group>.command`` in the decorator stack: decorators
  apply bottom-up, so ``@click.command`` builds the ``Command`` first and ``@alias`` then
  annotates the resulting object.
- ``register_with_aliases`` adds the *same* ``Command`` object to a group under its primary
  name and under every alias, so Click's resolver finds it for free (no ``get_command``
  override needed).
- ``AliasGroup`` is a ``click.Group`` whose only customization is help display: each command
  is listed once as ``primary (alias, …)`` and alias names are not rendered as separate rows.
"""

from collections.abc import Callable
from typing import TypeVar

import click

F = TypeVar("F", bound=click.Command)

# Alias metadata is stashed on the Command object under this attribute.
ALIAS_ATTR = "_perk_aliases"


def alias(*names: str) -> Callable[[F], F]:
    """Declare one or more aliases for a Click command.

    Must be applied BEFORE ``@click.command`` (i.e. listed above it in the decorator stack),
    because decorators apply bottom-to-top: ``@alias`` runs after ``@click.command`` has built
    the ``Command`` object.

    Usage::

        @alias("ls")
        @click.command("list")
        def list_cmd(...):
            ...
    """

    def decorator(cmd: F) -> F:
        existing = getattr(cmd, ALIAS_ATTR, [])
        setattr(cmd, ALIAS_ATTR, existing + list(names))
        return cmd

    return decorator


def get_aliases(cmd: click.Command) -> list[str]:
    """Return the aliases declared on a command (``[]`` when none)."""
    return getattr(cmd, ALIAS_ATTR, [])


def register_with_aliases(group: click.Group, cmd: click.Command, name: str | None = None) -> None:
    """Register ``cmd`` with ``group`` under its primary name and every declared alias."""
    cmd_name = name or cmd.name
    group.add_command(cmd, name=cmd_name)
    for alias_name in get_aliases(cmd):
        group.add_command(cmd, name=alias_name)


class AliasGroup(click.Group):
    """A ``click.Group`` that renders aliased commands once in ``--help``.

    Each command is shown as ``primary (alias, …)`` and the alias names are skipped as
    standalone rows. Resolution is unchanged from ``click.Group`` — aliases work because the
    same Command is registered under multiple names (see ``register_with_aliases``).
    """

    def format_commands(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        # Collect alias names so they are not rendered as standalone rows.
        alias_names: set[str] = set()
        rows: list[tuple[str, click.Command]] = []
        for name in self.list_commands(ctx):
            cmd = self.get_command(ctx, name)
            if cmd is None:
                continue
            alias_names.update(get_aliases(cmd))

        for name in self.list_commands(ctx):
            cmd = self.get_command(ctx, name)
            if cmd is None or cmd.hidden or name in alias_names:
                continue
            rows.append((name, cmd))

        if not rows:
            return

        entries: list[tuple[str, str]] = []
        for name, cmd in rows:
            aliases = get_aliases(cmd)
            display = f"{name} ({', '.join(aliases)})" if aliases else name
            entries.append((display, cmd.get_short_help_str(limit=formatter.width)))

        with formatter.section("Commands"):
            formatter.write_dl(entries)
