"""The ``perk`` CLI root group (the session *exterior*).

T1 ships ``--version`` and a minimal, idempotent ``init``. Stage subcommands are
generated from the stage registry (foundational #3) in a later turn; worktrees,
launch, and ``doctor`` follow. See docs/phase-0-plan.md.
"""

from pathlib import Path

import click

from perk import __version__
from perk.cli.alias import AliasGroup, register_with_aliases
from perk.cli.commands.doctor_cmd import doctor
from perk.cli.commands.implement_cmd import implement
from perk.cli.commands.init_cmd import init_perk
from perk.cli.commands.learn_capture_cmd import learn_capture
from perk.cli.commands.objective_cmd import objective_group
from perk.cli.commands.objective_plan_cmd import objective_plan
from perk.cli.commands.plan_save_cmd import plan_save
from perk.cli.commands.pr_check_cmd import pr_check
from perk.cli.commands.pr_feedback_cmd import pr_feedback
from perk.cli.commands.pr_land_cmd import pr_land
from perk.cli.commands.pr_ready_cmd import pr_ready
from perk.cli.commands.pr_resolve_threads_cmd import pr_resolve_threads
from perk.cli.commands.pr_submit_cmd import pr_submit
from perk.cli.commands.registry_cmd import registry
from perk.cli.commands.resume_cmd import resume_cmd
from perk.cli.commands.state_cmd import state
from perk.cli.commands.worktree_cmd import worktree
from perk.cli.context import PerkContext
from perk.cli.stages import register_stage_commands


@click.group(cls=AliasGroup)
@click.version_option(__version__, prog_name="perk", message="%(prog)s %(version)s")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Plan-oriented engineering workflow for Pi."""
    # Cheap by design (no I/O): require_* resolves the repo/config lazily, so non-repo
    # commands work outside a git repo. Tests inject obj=PerkContext.for_test(...).
    if ctx.obj is None:
        ctx.obj = PerkContext(cwd=Path.cwd())


cli.add_command(init_perk)
register_with_aliases(cli, plan_save)
cli.add_command(pr_submit)
cli.add_command(pr_check)
cli.add_command(pr_ready)
cli.add_command(pr_land)
register_with_aliases(cli, learn_capture)
cli.add_command(pr_feedback)
cli.add_command(pr_resolve_threads)
register_with_aliases(cli, resume_cmd)
register_with_aliases(cli, implement)
cli.add_command(doctor)
# implement is registered above; register_stage_commands skips it (DEDICATED_STAGES).
register_with_aliases(cli, registry)
register_with_aliases(cli, state)
register_with_aliases(cli, worktree)
register_with_aliases(cli, objective_group)
register_with_aliases(cli, objective_plan)
# objective-plan is registered above; register_stage_commands skips it (DEDICATED_STAGES).
register_stage_commands(cli)


def main() -> None:
    cli()
