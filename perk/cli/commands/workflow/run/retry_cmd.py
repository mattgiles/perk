"""`perk workflow run retry` — re-run a completed/failed dispatched run."""

import json

import click

from perk.cli.commands.workflow.run.shared import action_payload, fail, resolve_target
from perk.run import runner
from perk.substrate.output import machine_output, user_output


@click.command("retry")
@click.argument("run_id")
@click.option("--failed", is_flag=True, help="Re-run only the failed jobs.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def retry_run(ctx: click.Context, *, run_id: str, failed: bool, as_json: bool) -> None:
    """Re-run a completed/failed dispatched run by its perk run_id (``--failed`` = failed jobs)."""
    resolved = resolve_target(ctx, as_json=as_json, run_id=run_id, action="retry")
    if resolved is None:
        return
    repo_root, _record, handle, runner_obj = resolved
    try:
        runner_obj.retry(handle, failed_only=failed, repo_root=repo_root)
    except runner.RunnerError as exc:
        fail(ctx, as_json=as_json, error_type="retry_failed", message=str(exc))
        return
    user_output(f"Retried {'failed jobs of ' if failed else ''}run {run_id} ({handle.run_ref})")
    if as_json:
        machine_output(json.dumps(action_payload("retry", run_id, handle, failed_only=failed)))
