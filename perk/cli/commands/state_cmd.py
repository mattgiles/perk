"""``perk state`` — inspect the local workflow cache and mint run ids.

A developer / CI / `doctor` surface (like `perk registry`), **not** an agent affordance:
the agent reads and writes workflow state through the extension, never by shelling `perk`.
T4's launch primitive reuses ``run_id.mint`` + ``cache.write_handoff``; this group exercises
them now so the T3 gate can drive the shell → ``PERK_RUN_ID`` → claim round-trip before the
real launcher exists.
"""

import json
from pathlib import Path
from typing import Any

import click

from perk import cache, run_id
from perk.cli.ensure import UserFacingCliError
from perk.output import machine_output, user_output


@click.group("state")
def state() -> None:
    """Inspect the local workflow cache and mint run ids (dev/CI/doctor surface)."""


def _read_handoff_arg(value: str) -> dict[str, Any]:
    """Parse a ``--handoff`` argument: a JSON object literal or ``@path`` to one."""
    if value.startswith("@"):
        path = Path(value[1:])
        if not path.is_file():
            raise UserFacingCliError(f"--handoff file not found: {path}")
        raw = path.read_text(encoding="utf-8")
    else:
        raw = value
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UserFacingCliError(f"--handoff is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise UserFacingCliError("--handoff must be a JSON object.")
    return parsed


@state.command("new-run")
@click.option(
    "--handoff",
    "handoff_arg",
    default=None,
    help="Handoff JSON object (or @file) to write for the extension to claim.",
)
def new_run(handoff_arg: str | None) -> None:
    """Mint a run_id, write its handoff blob, and print the id on stdout.

    \b
    Examples:
      RID=$(perk state new-run)
      RID=$(perk state new-run --handoff '{"mode": "read-only"}')
    """
    data = _read_handoff_arg(handoff_arg) if handoff_arg is not None else {}
    root = Path.cwd()
    rid = run_id.mint()
    cache.ensure_layout(root)
    cache.write_handoff(root, rid, data)
    user_output(f"minted run_id {rid}; wrote handoff {cache.handoff_path(root, rid)}")
    machine_output(rid)


@state.command("show")
@click.option("--run-id", "rid", default=None, help="Show one run; omit to list all runs.")
def show(rid: str | None) -> None:
    """Show a run's handoff + scratch, or list known runs and markers."""
    root = Path.cwd()
    wd = cache.workflow_dir(root)
    if rid is None:
        runs = sorted(
            {p.stem for p in (wd / "handoff").glob("*.json")}
            | {p.name for p in (wd / "scratch" / "runs").glob("*") if p.is_dir()}
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
    user_output(f"  handoff: {json.dumps(data)}")
    scratch = cache.run_scratch_dir(root, rid)
    files = sorted(p.name for p in scratch.glob("*")) if scratch.is_dir() else []
    user_output(f"  scratch: {', '.join(files) or '—'}")
