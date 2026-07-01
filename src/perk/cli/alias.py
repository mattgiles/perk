"""Command aliases for the perk CLI.

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
  help (Stage Launchers / Command Groups / Setup & Health / Other / Hidden) while preserving
  the parenthetical alias display. Hidden-command visibility is gated by the ``PERK_SHOW_HIDDEN``
  environment variable.
"""

import os
from collections.abc import Callable
from typing import Literal, TypeVar

import click

F = TypeVar("F", bound=click.Command)

# Alias metadata is stashed on the Command object under this attribute.
ALIAS_ATTR = "_perk_aliases"

# Flat-alias bookkeeping is stashed on the root *group* object under this attribute (a set of the
# flat names registered via ``register_flat_alias``). Per-group state on the root object — NOT a
# module-level global — avoids cross-test leakage.
FLAT_ALIAS_ATTR = "_perk_flat_aliases"

# A per-command kind marker, stashed under this attribute and read by ``SectionedAliasGroup`` to
# partition a group's help into sections.
KIND_ATTR = "_perk_command_kind"

# The fixed kind vocabulary (compared with ``==`` in ``SectionedAliasGroup.format_commands``).
CommandKind = Literal["launcher", "worker"]


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


def register_flat_alias(
    root: click.Group, subcommand: click.Command, flat_name: str | None = None
) -> None:
    """Register a group's ``subcommand`` at ``root`` under a flat name (e.g. ``perk submit``).

    The same trick as ``register_with_aliases`` — the *same* ``Command`` object is added
    under another name — but across the group→root boundary, so ``perk submit`` can later resolve
    to ``perk pr submit``.

    The flat name is recorded on the ``root`` group itself (``FLAT_ALIAS_ATTR``) so
    ``SectionedGroup`` can route its row into the launcher section. Per-group state on the
    root object — not a module-level global — avoids cross-test leakage.
    """
    name = flat_name or subcommand.name
    if name is None:
        raise ValueError("register_flat_alias needs a flat_name when the subcommand is unnamed")
    root.add_command(subcommand, name=name)
    flat = getattr(root, FLAT_ALIAS_ATTR, None)
    if flat is None:
        flat = set()
        setattr(root, FLAT_ALIAS_ATTR, flat)
    flat.add(name)


def get_flat_aliases(group: click.Group) -> set[str]:
    """Return the flat-alias names registered on ``group`` (empty set when none)."""
    return getattr(group, FLAT_ALIAS_ATTR, set())


def mark_kind[C: click.Command](cmd: C, kind: CommandKind) -> C:
    """Mark ``cmd`` as a ``"launcher"`` or ``"worker"`` (read by ``SectionedAliasGroup``).

    Mirrors
    the ``alias``/``ALIAS_ATTR`` mechanism: a marker stashed on the ``Command`` object.
    """
    setattr(cmd, KIND_ATTR, kind)
    return cmd


def get_kind(cmd: click.Command) -> CommandKind | None:
    """Return the kind marker on ``cmd`` (``None`` when unmarked)."""
    return getattr(cmd, KIND_ATTR, None)


# Root-group section taxonomy (curated). Anything live but unlisted falls into
# the ``Other`` catch-all (e.g. the `run-worker` worker door); ``cmd.hidden``
# commands fall into ``Hidden`` (gated by env, see below).
STAGE_LAUNCHERS = [
    "plan",  # the hybrid plan group still reads as the stage launcher (save/resume/replan verbs)
    "implement",
    # submit/address/land are flat aliases (FLAT_ALIAS_ATTR), not generated launchers:
    # SectionedGroup routes flat aliases into the launcher bucket before consulting this list.
    "learn",  # the hybrid learn group still reads as the stage launcher
]
COMMAND_GROUPS = ["objective", "pr", "registry", "skills", "state", "worktree", "workflow"]
SETUP_HEALTH = ["init", "doctor"]


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

    Sections render in a fixed order — Stage Launchers, Command Groups, Setup & Health, Other,
    Hidden — and any section with no rows is omitted. Alias display and command resolution are
    inherited unchanged from ``AliasGroup``; the ``Hidden`` section is only rendered when
    ``PERK_SHOW_HIDDEN`` is set.
    """

    def format_commands(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        alias_names = _collect_alias_names(self, ctx)
        flat = get_flat_aliases(self)
        show_hidden = _show_hidden()

        launchers: list[tuple[str, click.Command]] = []
        groups: list[tuple[str, click.Command]] = []
        setup: list[tuple[str, click.Command]] = []
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
            if name in flat:
                # Flat top-level aliases feed the existing launcher bucket.
                launchers.append((name, cmd))
            elif name in COMMAND_GROUPS:
                groups.append((name, cmd))
            elif name in SETUP_HEALTH:
                setup.append((name, cmd))
            elif name in STAGE_LAUNCHERS:
                launchers.append((name, cmd))
            else:
                other.append((name, cmd))

        sections: list[tuple[str, list[tuple[str, click.Command]]]] = [
            ("Stage Launchers (each opens a primed pi session)", launchers),
            ("Command Groups", groups),
            ("Setup & Health", setup),
            ("Other", other),
            ("Hidden", hidden),
        ]
        for label, bucket in sections:
            if not bucket:
                continue
            with formatter.section(label):
                formatter.write_dl(_section_rows(bucket, formatter))


class SectionedAliasGroup(AliasGroup):
    """An ``AliasGroup`` that partitions its ``--help`` into Launchers / Workers / Commands.

    Commands marked via ``mark_kind`` render under their section: ``"launcher"``
    → **Launchers**, ``"worker"`` → **Workers**; unmarked commands fall into a catch-all
    **Commands** section (so an unmarked group renders exactly like ``AliasGroup``). Sections
    render in order Launchers, Workers, Commands; empty sections are omitted.
    """

    def format_commands(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        alias_names = _collect_alias_names(self, ctx)

        launchers: list[tuple[str, click.Command]] = []
        workers: list[tuple[str, click.Command]] = []
        commands: list[tuple[str, click.Command]] = []

        for name in self.list_commands(ctx):
            cmd = self.get_command(ctx, name)
            if cmd is None or cmd.hidden or name in alias_names:
                continue
            kind = get_kind(cmd)
            if kind == "launcher":
                launchers.append((name, cmd))
            elif kind == "worker":
                workers.append((name, cmd))
            else:
                commands.append((name, cmd))

        sections: list[tuple[str, list[tuple[str, click.Command]]]] = [
            ("Launchers", launchers),
            ("Workers", workers),
            ("Commands", commands),
        ]
        for label, bucket in sections:
            if not bucket:
                continue
            with formatter.section(label):
                formatter.write_dl(_section_rows(bucket, formatter))
