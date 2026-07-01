"""``perk plan`` — the plan-stage launcher + the plan-revision verbs.

A **hybrid default-dispatch group** (mirroring ``LearnGroup``): bare ``perk plan`` launches the
read-only authoring stage (a primed pi session), while ``save``/``resume``/``replan``/``from`` are
registered verbs:

- ``save`` — the merged launcher+worker (``MergedCommand``): the ``save``-stage launcher by
  default, the deterministic worker (the GitHub plan-write) under ``--json``. The
  worker keeps the **full** flag set.
- ``resume PLAN`` — today's flat ``resume`` (launcher-only).
- ``replan PLAN`` — today's flat ``replan`` (launcher-only).

Any other invocation — ``perk plan --dry-run``, ``perk plan --worktree X`` — falls through to a
hidden launcher built from the generic registry-stage factory (``make_stage_launcher``), so the
bare surface stays byte-identical to the generated ``plan`` stage launcher.

Default-dispatch edge: launcher pi-args whose *first* token is literally ``save``/``resume``/
``replan`` would route to the verb instead of the launcher — accepted; in practice launcher
pi-args start with ``-``. The merged ``save``'s ``--json`` overload edge: ``--json`` anywhere in
``perk plan save``'s argv selects the deterministic worker (passing ``--json`` through to ``pi``
as a launcher pi-arg is unsupported via the merged command).

(A shared ``HybridDispatchGroup`` base with ``LearnGroup`` is a deliberate future-polish deferral
— bounded duplication here, per perk's "each group keeps its own copy" ethos.)
"""

import click

from perk.cli.alias import AliasGroup, register_with_aliases
from perk.cli.commands.plan.from_cmd import plan_from
from perk.cli.commands.plan.replan_cmd import replan
from perk.cli.commands.plan.resume_cmd import resume_cmd
from perk.cli.commands.plan.save_cmd import plan_save
from perk.cli.stages import make_merged_command, make_stage_launcher
from perk.substrate.registry import RegistryError, load_registry

_LAUNCHER_NAME = "launch"


class PlanGroup(AliasGroup):
    """A default-dispatch group: unknown first args fall through to the hidden stage launcher.

    ``perk plan --help`` still renders the *group* help (the ``--help`` option is parsed at the
    group level before dispatch); everything else that isn't a registered verb is handed — args
    intact — to the hidden ``launch`` command.
    """

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        # Bare `perk plan` launches the plan stage instead of printing group help.
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


plan_group = PlanGroup(
    "plan",
    help=(
        "Author + revise plans. Bare `perk plan` launches the read-only plan stage (a primed pi "
        "session); `save` is the merged save boundary (the cold plan-write under --json); "
        "`resume` and `replan` revise existing plans; `from` adopts a pre-existing issue in place."
    ),
    # Launcher options (--worktree/--dry-run/--remote/pi-args) must survive group-level parsing
    # so they reach resolve_command intact for the default-dispatch fall-through.
    context_settings={"ignore_unknown_options": True},
)

# resume/replan/from carry no aliases now (clean break), so each registers under its bare
# name. `from` is the in-place issue-adoption cold door and a valid Click command string.
register_with_aliases(plan_group, resume_cmd)
register_with_aliases(plan_group, replan)
register_with_aliases(plan_group, plan_from)

# The merged `save`: the `save`-stage launcher by default, the deterministic worker under `--json`.
# Defensive: a broken registry must not brick the CLI (mirrors register_stage_commands) — the
# other verbs still work; only the merged save's launcher half is missing.
try:
    _save_stage = next(s for s in load_registry().stages if s.id == "save")
except (RegistryError, FileNotFoundError, StopIteration):
    pass
else:
    plan_group.add_command(make_merged_command(_save_stage, plan_save, name="save"), name="save")

# The hidden bare-invocation launcher: the generic registry launcher for the `plan` stage.
# Defensive: a broken registry must not brick the CLI (mirrors register_stage_commands) — the
# verbs still work; only the bare-launch fall-through is missing.
try:
    _plan_stage = next(s for s in load_registry().stages if s.id == "plan")
except (RegistryError, FileNotFoundError, StopIteration):
    pass
else:
    _launcher = make_stage_launcher(_plan_stage)
    _launcher.hidden = True
    plan_group.add_command(_launcher, name=_LAUNCHER_NAME)
