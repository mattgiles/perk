"""The ``perk`` CLI root group (the session *exterior*)."""

from pathlib import Path

import click

from perk import __version__
from perk.cli.alias import SectionedGroup, register_flat_alias, register_with_aliases
from perk.cli.commands.doctor import doctor_group
from perk.cli.commands.implement_cmd import implement
from perk.cli.commands.init_cmd import init_perk
from perk.cli.commands.learn import learn_group
from perk.cli.commands.objective import objective_group
from perk.cli.commands.plan import plan_group
from perk.cli.commands.pr import (
    pr_address_command,
    pr_group,
    pr_land_command,
    pr_submit_command,
)
from perk.cli.commands.pr.ready_cmd import ready_pr
from perk.cli.commands.registry import registry_group
from perk.cli.commands.run_worker_cmd import run_worker_cmd
from perk.cli.commands.skills import skills_group
from perk.cli.commands.state import state_group
from perk.cli.commands.workflow import workflow_group
from perk.cli.commands.worktree import worktree_group
from perk.cli.context import PerkContext
from perk.cli.stages import register_stage_commands
from perk.cli.version_check import maybe_warn_version_mismatch


@click.group(cls=SectionedGroup)
@click.version_option(__version__, prog_name="perk", message="%(prog)s %(version)s")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Plan-oriented engineering workflow for Pi."""
    # Cheap by design (no I/O): require_* resolves the repo/config lazily, so non-repo
    # commands work outside a git repo. Tests inject obj=PerkContext.for_test(...).
    if ctx.obj is None:
        ctx.obj = PerkContext(cwd=Path.cwd())
    # Report-only version warning. Its cheap gates (env/TTY/argv/subcommand) all short-circuit
    # before any I/O, so the no-I/O property still holds for tests, CI, pipes, and machine
    # consumers; only an interactive human invocation pays one `git rev-parse` + one file read.
    maybe_warn_version_mismatch(ctx.invoked_subcommand, ctx.obj.cwd)


cli.add_command(init_perk)
cli.add_command(plan_group)
# The `plan` group is hybrid: bare `perk plan` default-dispatches to the hidden
# plan-stage launcher, while `save` (merged launcher+worker under --json), `resume`, and `replan`
# are registered verbs. `plan` + `save` are in DEDICATED_STAGES, so register_stage_commands skips
# generating flat `perk plan` / `perk save` launchers.
cli.add_command(pr_group)
# Flat hot-path aliases: the SAME command objects registered at
# the root under a flat name, so `perk submit` resolves to the merged `pr submit`, etc. `ready` is
# worker-only (no `ready` registry stage) and gains only the flat alias. register_flat_alias
# records each in FLAT_ALIAS_ATTR so SectionedGroup routes their rows into the launcher section.
register_flat_alias(cli, pr_submit_command, "submit")
register_flat_alias(cli, pr_land_command, "land")
register_flat_alias(cli, pr_address_command, "address")
register_flat_alias(cli, ready_pr, "ready")
cli.add_command(learn_group)
# The `learn` group is hybrid: bare `perk learn` default-dispatches to the hidden
# stage launcher, while `capture` and `docs` are the cold workers. `docs` is a dedicated cold
# door but NOT a registry stage: it borrows the `plan` stage to launch.
register_with_aliases(cli, implement)
cli.add_command(doctor_group)
# implement is registered above; register_stage_commands skips it (DEDICATED_STAGES).
register_with_aliases(cli, registry_group)
register_with_aliases(cli, state_group)
register_with_aliases(cli, worktree_group)
register_with_aliases(cli, objective_group)
# The objective launchers (author/save/plan) now live inside the `objective` group beside its
# workers; register_stage_commands skips all three objective stages (DEDICATED_STAGES).
register_with_aliases(cli, workflow_group)
register_with_aliases(cli, skills_group)
cli.add_command(run_worker_cmd)
# `resume` and `replan` now live under the `plan` group. `replan` is still a dedicated
# cold door, not a registry stage: it borrows `plan` to re-launch with the target plan's original
# run_id (in-place upsert).
register_stage_commands(cli)


def main() -> None:
    cli()
