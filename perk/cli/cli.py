"""The ``perk`` CLI root group (the session *exterior*).

T1 ships ``--version`` and a minimal, idempotent ``init``. Stage subcommands are
generated from the stage registry (foundational #3) in a later turn; worktrees,
launch, and ``doctor`` follow. See docs/phase-0-plan.md.
"""

from pathlib import Path

import click

from perk import __version__
from perk.cli.alias import SectionedGroup, register_with_aliases
from perk.cli.commands.doctor import doctor_group
from perk.cli.commands.implement_cmd import implement
from perk.cli.commands.init_cmd import init_perk
from perk.cli.commands.learn import learn_group
from perk.cli.commands.objective import objective_group
from perk.cli.commands.objective_author_cmd import objective_author
from perk.cli.commands.objective_plan_cmd import objective_plan
from perk.cli.commands.plan_save_cmd import plan_save
from perk.cli.commands.pr import pr_group
from perk.cli.commands.registry import registry_group
from perk.cli.commands.replan_cmd import replan
from perk.cli.commands.resume_cmd import resume_cmd
from perk.cli.commands.run_worker_cmd import run_worker_cmd
from perk.cli.commands.state import state_group
from perk.cli.commands.workflow import workflow_group
from perk.cli.commands.worktree import worktree_group
from perk.cli.context import PerkContext
from perk.cli.stages import register_stage_commands


@click.group(cls=SectionedGroup)
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
cli.add_command(pr_group)
cli.add_command(learn_group)
# The `learn` group is hybrid (Node 2.2): bare `perk learn` default-dispatches to the hidden
# stage launcher, while `capture` and `docs` are the cold workers. `docs` is a dedicated cold
# door but NOT a registry stage (hop-2): it borrows the `plan` stage to launch.
register_with_aliases(cli, resume_cmd)
register_with_aliases(cli, implement)
cli.add_command(doctor_group)
# implement is registered above; register_stage_commands skips it (DEDICATED_STAGES).
register_with_aliases(cli, registry_group)
register_with_aliases(cli, state_group)
register_with_aliases(cli, worktree_group)
register_with_aliases(cli, objective_group)
register_with_aliases(cli, objective_author)
register_with_aliases(cli, objective_plan)
# objective-author + objective-plan are registered above; register_stage_commands skips them
# (DEDICATED_STAGES).
register_with_aliases(cli, replan)
register_with_aliases(cli, workflow_group)
cli.add_command(run_worker_cmd)
# replan is likewise a dedicated cold door, not a registry stage: it borrows `plan` to re-launch
# with the target plan's original run_id (in-place upsert), so DEDICATED_STAGES is unchanged.
register_stage_commands(cli)


def main() -> None:
    cli()
