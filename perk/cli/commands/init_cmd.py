"""`perk init` — thin Click adapter over the convergent init operation (perk/init.py)."""

import click

from perk.init import run_init


@click.command("init")
def init_perk() -> None:
    """Scaffold/converge this repo for perk (idempotent; safe to re-run).

    Wires `.pi/settings.json` (perk's extension + the borrowed default set), creates the
    `.pi/workflow/` cache dir, manages `.gitignore`, and writes the perk-managed `AGENTS.md`
    block. Re-running on an already-converged repo is a no-op.

    \b
    Examples:
      # converge the current repo
      perk init
    """
    run_init()
