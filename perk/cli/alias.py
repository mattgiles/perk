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
  Used by the subgroups (flat verb lists).
- ``SectionedGroup`` extends ``AliasGroup`` for the **root** group only: it renders sectioned
  help (Top-Level Commands / Command Groups / Initialization / Other / Hidden) while preserving
  the parenthetical alias display. Hidden-command visibility is gated by the ``PERK_SHOW_HIDDEN``
  environment variable.
"""

import os
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


# Root-group section taxonomy (curated, erk-faithful). Anything live but unlisted falls into
# the ``Other`` catch-all; ``cmd.hidden`` commands fall into ``Hidden`` (gated by env, see below).
TOP_LEVEL_COMMANDS = [
    "plan",
    "save",
    "submit",
    "address",
    "land",
    "learn",
    "implement",
    "resume",
    "replan",
    "plan-save",
    "learn-capture",
    "learn-docs",
    "objective-author",
    "objective-plan",
    "objective-save",
    "doctor",
]
COMMAND_GROUPS = ["objective", "pr", "registry", "state", "worktree", "workflow"]
INITIALIZATION = ["init"]


def _show_hidden() -> bool:
    """Whether hidden commands should be rendered (gated by ``PERK_SHOW_HIDDEN``)."""
    return os.environ.get("PERK_SHOW_HIDDEN") not in (None, "", "0")


def _collect_alias_names(group: click.Group, ctx: click.Context) -> set[str]:
    """Collect the set of alias names registered on ``group`` (skip them as standalone rows)."""
    alias_names: set[str] = set()
    for name in group.list_commands(ctx):
        cmd = group.get_command(ctx, name)
        if cmd is None:
            continue
        alias_names.update(get_aliases(cmd))
    return alias_names


def _section_rows(
    cmds: list[tuple[str, click.Command]], formatter: click.HelpFormatter
) -> list[tuple[str, str]]:
    """Build ``(display, short_help)`` rows with parenthetical alias display."""
    entries: list[tuple[str, str]] = []
    for name, cmd in cmds:
        aliases = get_aliases(cmd)
        display = f"{name} ({', '.join(aliases)})" if aliases else name
        entries.append((display, cmd.get_short_help_str(limit=formatter.width)))
    return entries


class AliasGroup(click.Group):
    """A ``click.Group`` that renders aliased commands once in ``--help``.

    Each command is shown as ``primary (alias, …)`` and the alias names are skipped as
    standalone rows. Resolution is unchanged from ``click.Group`` — aliases work because the
    same Command is registered under multiple names (see ``register_with_aliases``).
    """

    def format_commands(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        alias_names = _collect_alias_names(self, ctx)
        rows: list[tuple[str, click.Command]] = []
        for name in self.list_commands(ctx):
            cmd = self.get_command(ctx, name)
            if cmd is None or cmd.hidden or name in alias_names:
                continue
            rows.append((name, cmd))

        if not rows:
            return

        with formatter.section("Commands"):
            formatter.write_dl(_section_rows(rows, formatter))


class SectionedGroup(AliasGroup):
    """A root group that renders sectioned ``--help`` (curated name lists + ``Other`` catch-all).

    Sections render in a fixed order — Top-Level Commands, Command Groups, Initialization, Other,
    Hidden — and any section with no rows is omitted. Alias display and command resolution are
    inherited unchanged from ``AliasGroup``; the ``Hidden`` section is only rendered when
    ``PERK_SHOW_HIDDEN`` is set.
    """

    def format_commands(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        alias_names = _collect_alias_names(self, ctx)
        show_hidden = _show_hidden()

        top_level: list[tuple[str, click.Command]] = []
        groups: list[tuple[str, click.Command]] = []
        init: list[tuple[str, click.Command]] = []
        other: list[tuple[str, click.Command]] = []
        hidden: list[tuple[str, click.Command]] = []

        for name in self.list_commands(ctx):
            cmd = self.get_command(ctx, name)
            if cmd is None or name in alias_names:
                continue
            if cmd.hidden:
                if show_hidden:
                    hidden.append((name, cmd))
                continue
            if name in COMMAND_GROUPS:
                groups.append((name, cmd))
            elif name in INITIALIZATION:
                init.append((name, cmd))
            elif name in TOP_LEVEL_COMMANDS:
                top_level.append((name, cmd))
            else:
                other.append((name, cmd))

        sections: list[tuple[str, list[tuple[str, click.Command]]]] = [
            ("Top-Level Commands", top_level),
            ("Command Groups", groups),
            ("Initialization", init),
            ("Other", other),
            ("Hidden", hidden),
        ]
        for label, bucket in sections:
            if not bucket:
                continue
            with formatter.section(label):
                formatter.write_dl(_section_rows(bucket, formatter))
