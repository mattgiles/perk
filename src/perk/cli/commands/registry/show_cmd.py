"""`perk registry show` — print the stages and their transitions."""

import click

from perk.cli.alias import alias
from perk.cli.commands.registry.shared import load_or_die
from perk.substrate.output import user_output


@alias("s")
@click.command("show")
def show_registry() -> None:
    """Print the stages and their transitions (a dev/doctor convenience)."""
    reg = load_or_die()
    user_output(f"schema_version: {reg.schema_version}   ({len(reg.stages)} stages)")
    user_output("")
    for stage in reg.stages:
        doors = ",".join(d for d in ("warm", "cold_local", "cold_remote") if stage.doors.get(d))
        succ = ", ".join(stage.successors) or "—"
        user_output(
            f"  {stage.id:<10} mode={stage.mode:<10} worktree={stage.worktree:<7} "
            f"doors=[{doors}]  -> {succ}"
        )
