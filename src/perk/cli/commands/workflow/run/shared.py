"""Cross-verb helpers for the ``perk workflow run`` group."""

from typing import Any

import click

from perk.cli.context import require_github, require_repo
from perk.cli.emit import fail
from perk.cli.ensure import UserFacingCliError
from perk.run import discovery, runner
from perk.state import cache
from perk.substrate.output import user_output


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
) -> tuple[Any, cache.Dispatch | None, runner.RunHandle, runner.Runner] | None:
    """Shared control-command prelude: require a repo + GitHub auth, then resolve ``run_id`` to a
    runner handle via a two-rung ladder (contracts.md §8.18) — the local dispatch record first
    (the cache accelerator), the canonical run discovery second (so any machine can control a run
    it never dispatched, and a record whose finalize write-back never landed a handle recovers).
    Routes every expected failure through ``fail`` and returns ``None`` (the caller returns); on
    success returns ``(repo_root, record, handle, runner_obj)`` — ``record`` is ``None`` for a
    discovered-only run."""
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
    if record is not None and record.run_handle is not None:
        return repo_root, record, record.run_handle, runner.select_runner(record.runner)

    # No local record, or a handle-less one — fall back to the canonical discovery. A discovery
    # failure degrades fail-soft into the miss arms below (the strict vocabulary is unchanged).
    discovered: runner.DiscoveredRun | None = None
    try:
        discovered = discovery.find_discovered_run(repo_root, run_id)
    except runner.RunnerError as exc:
        user_output(f"note: run discovery unavailable: {exc}")
    if discovered is not None:
        handle = discovered.handle
        ref = record.runner if record is not None else handle.runner
        return repo_root, record, handle, runner.select_runner(ref)

    if record is None:
        fail(
            ctx,
            as_json=as_json,
            error_type="run_not_found",
            message=(
                f"no dispatched run with run_id {run_id!r} — no local dispatch record, and not "
                f"among the newest discovered perk-run.yml runs"
            ),
        )
        return None
    fail(
        ctx,
        as_json=as_json,
        error_type="run_not_dispatched",
        message=f"run {run_id!r} was never triggered (no run handle); nothing to {action}",
    )
    return None
