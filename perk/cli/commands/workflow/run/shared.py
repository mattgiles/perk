"""Cross-verb helpers for the ``perk workflow run`` group."""

import json
from typing import Any

import click

from perk import runner
from perk.cli.context import require_github, require_repo
from perk.cli.ensure import UserFacingCliError
from perk.state import cache
from perk.substrate.output import machine_output, user_output

EXIT_FOR_TYPE = {"not_a_repo": 2}


def fail(ctx: click.Context, *, as_json: bool, error_type: str, message: str) -> None:
    if as_json:
        machine_output(json.dumps({"success": False, "error_type": error_type, "message": message}))
    else:
        user_output(click.style("Error: ", fg="red") + message)
    ctx.exit(EXIT_FOR_TYPE.get(error_type, 1))


def action_payload(
    action: str,
    run_id: str,
    handle: runner.RunHandle,
    *,
    failed_only: bool | None = None,
) -> dict[str, Any]:
    """The stable ``--json`` success payload for a control action (stdout)."""
    payload: dict[str, Any] = {
        "success": True,
        "error_type": None,
        "action": action,
        "run_id": run_id,
        "run_ref": handle.run_ref,
        "runner": handle.runner,
        "kind": handle.kind,
        "url": handle.url,
    }
    if failed_only is not None:
        payload["failed_only"] = failed_only
    return payload


def resolve_target(
    ctx: click.Context,
    *,
    as_json: bool,
    run_id: str,
    action: str,
) -> tuple[Any, dict[str, Any], runner.RunHandle, runner.Runner] | None:
    """Shared control-command prelude: require a repo + GitHub auth, resolve ``run_id`` to its
    dispatch record and a reconstructed runner handle. Routes every expected failure through
    ``fail`` and returns ``None`` (the caller returns); on success returns
    ``(repo_root, record, handle, runner_obj)``."""
    try:
        repo_root = require_repo(ctx)
        require_github(ctx)
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return None
    record = cache.read_dispatch(repo_root, run_id)
    if record is None:
        fail(
            ctx,
            as_json=as_json,
            error_type="run_not_found",
            message=f"no dispatched run with run_id {run_id!r}",
        )
        return None
    handle_data = record.get("run_handle")
    if not handle_data:
        fail(
            ctx,
            as_json=as_json,
            error_type="run_not_dispatched",
            message=f"run {run_id!r} was never triggered (no run handle); nothing to {action}",
        )
        return None
    handle = runner.RunHandle.from_data(handle_data)
    runner_obj = runner.select_runner(str(record.get("runner", "")))
    return repo_root, record, handle, runner_obj
