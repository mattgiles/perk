"""`perk v2 start` — begin a new v2 execution over a repo ref."""

from pathlib import Path

import click

from perk.cli.commands.v2.shared import JSON_HELP, drive
from perk.cli.context import require_repo
from perk.cli.ensure import UserFacingCliError
from perk.v2.door import DEFAULT_REF


@click.command("start")
@click.option("--repo", default=None, help="The repo root to track (default: this checkout).")
@click.option("--ref", default=DEFAULT_REF, show_default=True, help="The ref to track.")
@click.option("--json", "as_json", is_flag=True, help=JSON_HELP)
@click.pass_context
def start_cmd(ctx: click.Context, *, repo: str | None, ref: str, as_json: bool) -> None:
    """Start a new execution: mint its id, observe REF in REPO, and run it to quiescence.

    A new execution id is minted on every call; continue an existing one with `perk v2 run`.
    """
    if repo is not None:
        tracked = str(Path(repo).resolve())
    else:
        try:
            tracked = str(require_repo(ctx))
        except UserFacingCliError:
            tracked = ""  # drive reports not_a_repo before the host runs
    drive(
        ctx,
        verb="start",
        execution_id=None,
        verb_options=(("repo", tracked), ("ref", ref)),
        as_json=as_json,
    )
