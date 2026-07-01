"""`perk workflow run cancel` — cancel an in-flight dispatched run."""

import json

import click

from perk.cli.commands.workflow.run.shared import action_payload, fail, resolve_target
from perk.run import runner
from perk.substrate.output import machine_output, user_output


@click.command("cancel")
@click.argument("run_id")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def cancel_run(ctx: click.Context, *, run_id: str, as_json: bool) -> None:
    """Cancel an in-flight (queued/in_progress) dispatched run by its perk run_id."""
    resolved = resolve_target(ctx, as_json=as_json, run_id=run_id, action="cancel")
    if resolved is None:
        return
    repo_root, _record, handle, runner_obj = resolved
    try:
        runner_obj.cancel(handle, repo_root=repo_root)
    except runner.RunnerError as exc:
        fail(ctx, as_json=as_json, error_type="cancel_failed", message=str(exc))
        return
    user_output(f"Cancelled run {run_id} ({handle.run_ref})")
    if as_json:
        machine_output(json.dumps(action_payload("cancel", run_id, handle)))
