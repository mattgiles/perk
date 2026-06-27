"""`perk state show` — show a run's handoff + scratch, or list known runs."""

import json
from pathlib import Path

import click

from perk.cli.alias import alias
from perk.cli.ensure import UserFacingCliError
from perk.state import cache
from perk.substrate.output import user_output


@alias("s")
@click.command("show")
@click.option("--run-id", "rid", help="Show one run; omit to list all runs.")
def show_state(*, rid: str | None) -> None:
    """Show a run's handoff + scratch, or list known runs and markers."""
    root = Path.cwd()
    wd = cache.workflow_dir(root)
    if rid is None:
        runs = sorted(
            {p.stem for p in (wd / "handoff").glob("*.json")} | set(cache.list_run_ids(root))
        )
        user_output(f"{len(runs)} run(s):")
        for run in runs:
            user_output(f"  {run}")
        markers = sorted(p.name for p in (wd / "markers").glob("*") if p.is_file())
        user_output(f"markers: {', '.join(markers) or '—'}")
        return

    data = cache.read_handoff(root, rid)
    if data is None:
        raise UserFacingCliError(f"no handoff for run {rid}")
    user_output(f"run {rid}:")
    user_output(f"  handoff: {json.dumps(data.model_dump(mode='json'))}")
    scratch = cache.run_scratch_dir(root, rid)
    files = sorted(p.name for p in scratch.glob("*")) if scratch.is_dir() else []
    user_output(f"  scratch: {', '.join(files) or '—'}")
