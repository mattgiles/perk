"""``perk run-worker`` — the runner-side CI worker entrypoint.

The managed ``perk-run.yml`` workflow checks out the plan branch, then invokes this command to
position the checkout and drive the dispatched stage headlessly via the Node worker. It
is a deterministic supervisor/CI surface (no agentic reasoning): it exits with the worker's exit
code so the workflow step's success reflects the drive outcome. See :mod:`perk.run.run_worker`.
"""

import os

import click

from perk.cli.context import require_github, require_repo
from perk.cli.plan_selection import parse_plan_id
from perk.run import run_worker
from perk.run.run_worker import DRIVABLE_DOOR
from perk.substrate.registry import load_registry

_DRIVABLE_STAGE_IDS = sorted(
    s.id for s in load_registry().stages if s.doors.get(DRIVABLE_DOOR) is True
)


@click.command("run-worker")
@click.option("--run-id", required=True, help="The perk run_id (ULID) for this drive.")
@click.option(
    "--stage",
    "stage_id",
    required=True,
    type=click.Choice(_DRIVABLE_STAGE_IDS),
    help="The stage to drive (implement | address).",
)
@click.option("--plan", required=True, help="The plan issue id (e.g. 42, #42, or ENG-123).")
@click.option("--base", help="The base branch the plan branch targets.")
@click.pass_context
def run_worker_cmd(
    ctx: click.Context,
    *,
    run_id: str,
    stage_id: str,
    plan: str,
    base: str | None,
) -> None:
    """Position the checkout and drive a stage headlessly (the CI runner entrypoint).

    \b
    Reconstructs the plan-ref from the plan's GitHub state, materializes the handoff/plan-ref/
    plan-body into the checkout's .perk/workflow/, then spawns the Node worker with PERK_RUN_ID set.
    Exits with the worker's exit code.
    """
    repo_root = require_repo(ctx)
    require_github(ctx)
    plan_id = parse_plan_id(plan)
    code = run_worker.run_worker(
        repo_root=repo_root,
        run_id=run_id,
        stage_id=stage_id,
        plan=plan_id,
        base=base,
        environ=dict(os.environ),
    )
    ctx.exit(code)
