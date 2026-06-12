"""``perk run-worker`` — the runner-side CI worker entrypoint (Objective #137 Node 2.2).

The managed ``perk-run.yml`` workflow checks out the plan branch, then invokes this command to
position the checkout and drive the dispatched stage headlessly via the Node worker (Node 1.2). It
is a deterministic supervisor/CI surface (no agentic reasoning): it exits with the worker's exit
code so the workflow step's success reflects the drive outcome. See :mod:`perk.run_worker`.
"""

import os

import click

from perk import run_worker
from perk.cli.commands.resume_cmd import parse_plan_id
from perk.cli.context import require_github, require_repo
from perk.registry import load_registry
from perk.run_worker import DRIVABLE_DOOR

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
    plan-body into the checkout's .pi/workflow/, then spawns the Node worker with PERK_RUN_ID set.
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
