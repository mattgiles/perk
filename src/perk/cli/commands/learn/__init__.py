"""``perk learn`` — the learn-stage launcher + the learn workers (cold doors).

A **hybrid default-dispatch group**: ``capture``/``skip`` (the ``/learn`` knowledge-capture and
skip-recording workers), ``docs`` (the hop-2 learned-docs plan-factory cold door), and
``pending`` (the closed-plans-awaiting-/learn backlog view) are
registered verbs, while any other invocation — bare ``perk learn``, ``perk learn --dry-run``,
``perk learn --worktree X`` — falls through to a hidden launcher built from the generic
registry-stage factory (``make_stage_launcher``), so the bare surface stays byte-identical to
the generated ``learn`` stage launcher.

Default-dispatch edge: launcher pi-args whose *first* token is literally a registered verb
(``capture``, ``skip``, ``docs``, …) would route to the verb instead of the launcher —
accepted; in practice launcher pi-args start with ``-``. Launcher-vs-group presentation: the
root ``Stage Launchers`` section header plus the generated launcher help sentence
(``make_stage_launcher``) carry the disambiguation; the hidden ``launch`` verb intentionally
stays out of subgroup help.
"""

import click

from perk.cli.alias import AliasGroup
from perk.cli.commands.learn.capture_cmd import capture_learn
from perk.cli.commands.learn.code_cmd import code_learn
from perk.cli.commands.learn.docs_check_cmd import docs_check_learn
from perk.cli.commands.learn.docs_cmd import docs_learn
from perk.cli.commands.learn.docs_sync_cmd import docs_sync_learn
from perk.cli.commands.learn.evidence_cmd import evidence_learn
from perk.cli.commands.learn.harvest_cmd import harvest_learn
from perk.cli.commands.learn.pending_cmd import pending_learn
from perk.cli.commands.learn.skip_cmd import skip_learn
from perk.cli.stages import make_stage_launcher
from perk.substrate.registry import RegistryError, stage_by_id

_LAUNCHER_NAME = "launch"


class LearnGroup(AliasGroup):
    """A default-dispatch group: unknown first args fall through to the hidden stage launcher.

    ``perk learn --help`` still renders the *group* help (the ``--help`` option is parsed at the
    group level before dispatch); everything else that isn't a registered verb is handed — args
    intact — to the hidden ``launch`` command.
    """

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        # Bare `perk learn` launches the learn stage instead of printing group help.
        if not args and not ctx.resilient_parsing and _LAUNCHER_NAME in self.commands:
            args = [_LAUNCHER_NAME]
        return super().parse_args(ctx, args)

    def resolve_command(
        self, ctx: click.Context, args: list[str]
    ) -> tuple[str | None, click.Command | None, list[str]]:
        head = args[0] if args else ""
        if head in self.commands or head in ("--help", "-h"):
            return super().resolve_command(ctx, args)
        if _LAUNCHER_NAME in self.commands:
            # Not a verb: divert to the hidden launcher with ALL original args preserved.
            return _LAUNCHER_NAME, self.commands[_LAUNCHER_NAME], args
        return super().resolve_command(ctx, args)


learn_group = LearnGroup(
    "learn",
    help=(
        "Capture + consolidate learnings. Bare `perk learn` launches the learn stage (a primed "
        "pi session); `capture`, `skip`, `code`, `docs`, `docs-check`, `docs-sync`, and "
        "`evidence` are the cold workers the warm doors delegate to; `harvest` is the cold-only "
        "objective factory that mines docs/learned (no warm door); `pending` lists closed "
        "plans still awaiting /learn."
    ),
    # Launcher options (--worktree/--dry-run/--remote/pi-args) must survive group-level parsing
    # so they reach resolve_command intact for the default-dispatch fall-through.
    context_settings={"ignore_unknown_options": True},
)

learn_group.add_command(capture_learn)
learn_group.add_command(code_learn)
learn_group.add_command(docs_learn)
learn_group.add_command(docs_check_learn)
learn_group.add_command(docs_sync_learn)
learn_group.add_command(evidence_learn)
learn_group.add_command(harvest_learn)
learn_group.add_command(pending_learn)
learn_group.add_command(skip_learn)

# The hidden bare-invocation launcher: the generic registry launcher for the `learn` stage.
# Defensive: a broken registry must not brick the CLI (mirrors register_stage_commands) — the
# verbs still work; only the bare-launch fall-through is missing.
try:
    _learn_stage = stage_by_id("learn")
except (RegistryError, FileNotFoundError):
    pass
else:
    _launcher = make_stage_launcher(_learn_stage)
    _launcher.hidden = True
    learn_group.add_command(_launcher, name=_LAUNCHER_NAME)
