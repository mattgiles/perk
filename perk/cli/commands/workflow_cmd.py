"""``perk workflow run`` — the supervisor read surface over dispatched runs (Node 3.1).

A dev/CI/supervisor surface (like ``perk objective`` / ``perk state``), **not** an agent
affordance: the model never shells ``perk workflow``. ``workflow run list`` enumerates the durable
dispatch records (the verified ``run_id → plan`` linkage from Node 2.1) and correlates each
``run_id ↔ plan ↔ PR``, overlaying live GitHub run state. Read-only: it mutates nothing.

``--json`` → a stable machine report on stdout; the human table → stderr. The live overlay is
**best-effort, fail-soft** — a GitHub read failure degrades that field to record-only state with a
one-line stderr note; it never raises and never changes the exit code.

``cancel``/``retry`` are the shipped control siblings of ``list`` (Node 3.2, contracts.md §8.18):
deterministic, mutating supervisor commands that resolve a perk ``run_id`` to its dispatch record
and act on the runner-native handle (cancel an in-flight run; re-run a completed/failed run, with
``--failed`` to re-run only the failed jobs). They require GitHub auth and surface gh's own error
verbatim; they mutate no ``.pi/workflow/`` state.
"""

import json
from datetime import UTC, datetime
from typing import Any

import click

from perk import cache, github, runner
from perk.cli.alias import AliasGroup, alias, register_with_aliases
from perk.cli.context import require_github, require_repo
from perk.cli.ensure import UserFacingCliError
from perk.output import machine_output, user_output

_EXIT_FOR_TYPE = {"not_a_repo": 2}

# Per-column display clamps for the human table (the full RUN_ID is never clamped).
_COL_CAP = 14


@alias("wf")
@click.group("workflow", cls=AliasGroup)
def workflow_group() -> None:
    """Supervisor surface over dispatched runs (dev/CI/supervisor surface, not an agent
    affordance)."""


@click.group("run", cls=AliasGroup)
def run_group() -> None:
    """Observe and (Node 3.2) control dispatched runs."""


def _fail(ctx: click.Context, *, as_json: bool, error_type: str, message: str) -> None:
    if as_json:
        machine_output(json.dumps({"success": False, "error_type": error_type, "message": message}))
    else:
        user_output(click.style("Error: ", fg="red") + message)
    ctx.exit(_EXIT_FOR_TYPE.get(error_type, 1))


def _format_age(dispatched_at: str) -> str:
    """A compact relative age from an ISO-8601 ``dispatched_at`` (``-`` when unparsable)."""
    if not dispatched_at:
        return "-"
    try:
        when = datetime.fromisoformat(dispatched_at)
    except ValueError:
        return "-"
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    seconds = (datetime.now(UTC) - when).total_seconds()
    if seconds < 0:
        seconds = 0
    if seconds < 60:
        return "<60s"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h"
    return f"{hours // 24}d"


def _row_to_dict(
    record: dict[str, Any],
    *,
    run_obs: runner.RunObservation | None,
    pr: github.PullRequest | None,
) -> dict[str, Any]:
    """Assemble one run's JSON dict from the record + the (possibly ``None``) overlays."""
    plan_ref = record.get("plan_ref") or {}
    pr_id = str(plan_ref.get("pr_id", "")).strip()
    handle = record.get("run_handle") or {}
    run_block: dict[str, Any] | None = None
    if run_obs is not None:
        run_block = {
            "run_ref": str(handle.get("run_ref", "")),
            "url": run_obs.url,
            "status": run_obs.status,
            "conclusion": run_obs.conclusion,
        }
    pr_block: dict[str, Any] | None = None
    if pr is not None:
        pr_block = {"number": pr.number, "url": pr.url, "state": pr.state}
    return {
        "run_id": str(record.get("run_id", "")),
        "stage": str(record.get("stage", "")),
        "runner": str(record.get("runner", "")),
        "kind": str(record.get("kind", "")),
        "dispatch_status": str(record.get("status", "")),
        "dispatched_at": str(record.get("dispatched_at", "")),
        "error": record.get("error"),
        "plan": {"pr_id": pr_id, "url": str(plan_ref.get("url", ""))},
        "pr": pr_block,
        "run": run_block,
    }


def _overlay(
    record: dict[str, Any],
    repo_root: Any,
    *,
    plan_cache: dict[int, github.PlanState | None],
) -> tuple[runner.RunObservation | None, github.PullRequest | None]:
    """Best-effort live overlay for one record: (run observation, correlated PR). Each read is
    fail-soft — a failure degrades to ``None`` with a one-line stderr note, never raises."""
    run_obs: runner.RunObservation | None = None
    handle_data = record.get("run_handle")
    if handle_data:
        try:
            handle = runner.RunHandle.from_data(handle_data)
            run_obs = runner.select_runner(str(record.get("runner", ""))).observe(
                handle, repo_root=repo_root
            )
        except runner.RunnerError as exc:
            user_output(f"note: run state unavailable for {record.get('run_id', '?')}: {exc}")
            run_obs = None

    pr: github.PullRequest | None = None
    pr_id = str((record.get("plan_ref") or {}).get("pr_id", "")).strip()
    if pr_id.isdigit() and int(pr_id) > 0:
        number = int(pr_id)
        if number in plan_cache:
            plan_state = plan_cache[number]
        else:
            try:
                plan_state = github.get_plan(number=number, repo_root=repo_root)
            except github.GitHubError as exc:
                user_output(f"note: plan #{number} unavailable: {exc}")
                plan_state = None
            plan_cache[number] = plan_state
        pr = plan_state.pr if plan_state is not None else None
    return run_obs, pr


def _clamp(value: str, width: int) -> str:
    return value if len(value) <= width else value[: width - 1] + "…"


def _render_table(rows: list[dict[str, Any]]) -> None:
    """Render the newest-first human table to stderr (plain, manually-aligned columns)."""
    if not rows:
        user_output("No dispatched runs found")
        return

    headers = ["RUN_ID", "STAGE", "DISPATCH", "RUN", "CONCLUSION", "PLAN", "PR", "AGE"]
    table: list[list[str]] = []
    for row in rows:
        run_block = row["run"]
        pr_block = row["pr"]
        table.append(
            [
                row["run_id"],
                _clamp(row["stage"], _COL_CAP),
                _clamp(row["dispatch_status"], _COL_CAP),
                _clamp(run_block["status"] if run_block else "-", _COL_CAP),
                _clamp((run_block["conclusion"] or "-") if run_block else "-", _COL_CAP),
                f"#{row['plan']['pr_id']}" if row["plan"]["pr_id"] else "-",
                f"#{pr_block['number']}({pr_block['state']})" if pr_block else "-",
                _format_age(row["dispatched_at"]),
            ]
        )

    widths = [len(h) for h in headers]
    for line in table:
        for i, cell in enumerate(line):
            widths[i] = max(widths[i], len(cell))

    def _fmt(cells: list[str]) -> str:
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells))

    user_output(_fmt(headers))
    for row, line in zip(rows, table, strict=True):
        user_output(_fmt(line))
        # Keep failed dispatches visible: surface the capped error on a continuation line.
        if row["dispatch_status"] == "failed" and row["error"]:
            user_output(f"    error: {row['error']}")


@alias("ls")
@click.command("list")
@click.option(
    "--no-refresh",
    "no_refresh",
    is_flag=True,
    help="Skip live GitHub reads; report only the durable dispatch-record state.",
)
@click.option(
    "--limit",
    "limit",
    type=int,
    default=50,
    show_default=True,
    help="Max runs to display (newest-first).",
)
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def workflow_run_list(ctx: click.Context, *, no_refresh: bool, limit: int, as_json: bool) -> None:
    """Enumerate dispatched runs, correlating run_id ↔ plan ↔ PR with a live GitHub overlay."""
    try:
        repo_root = require_repo(ctx)
    except UserFacingCliError as exc:
        _fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return

    records = cache.list_dispatch_records(repo_root)[:limit]
    refreshed = not no_refresh
    plan_cache: dict[int, github.PlanState | None] = {}
    rows: list[dict[str, Any]] = []
    for record in records:
        if refreshed:
            run_obs, pr = _overlay(record, repo_root, plan_cache=plan_cache)
        else:
            run_obs, pr = None, None
        rows.append(_row_to_dict(record, run_obs=run_obs, pr=pr))

    _render_table(rows)

    if as_json:
        machine_output(
            json.dumps(
                {
                    "success": True,
                    "error_type": None,
                    "refreshed": refreshed,
                    "count": len(rows),
                    "runs": rows,
                }
            )
        )


def _action_payload(
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


def _resolve_target(
    ctx: click.Context,
    *,
    as_json: bool,
    run_id: str,
    action: str,
) -> tuple[Any, dict[str, Any], runner.RunHandle, runner.Runner] | None:
    """Shared control-command prelude: require a repo + GitHub auth, resolve ``run_id`` to its
    dispatch record and a reconstructed runner handle. Routes every expected failure through
    ``_fail`` and returns ``None`` (the caller returns); on success returns
    ``(repo_root, record, handle, runner_obj)``."""
    try:
        repo_root = require_repo(ctx)
        require_github(ctx)
    except UserFacingCliError as exc:
        _fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return None
    record = cache.read_dispatch(repo_root, run_id)
    if record is None:
        _fail(
            ctx,
            as_json=as_json,
            error_type="run_not_found",
            message=f"no dispatched run with run_id {run_id!r}",
        )
        return None
    handle_data = record.get("run_handle")
    if not handle_data:
        _fail(
            ctx,
            as_json=as_json,
            error_type="run_not_dispatched",
            message=f"run {run_id!r} was never triggered (no run handle); nothing to {action}",
        )
        return None
    handle = runner.RunHandle.from_data(handle_data)
    runner_obj = runner.select_runner(str(record.get("runner", "")))
    return repo_root, record, handle, runner_obj


@click.command("cancel")
@click.argument("run_id")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def workflow_run_cancel(ctx: click.Context, *, run_id: str, as_json: bool) -> None:
    """Cancel an in-flight (queued/in_progress) dispatched run by its perk run_id."""
    resolved = _resolve_target(ctx, as_json=as_json, run_id=run_id, action="cancel")
    if resolved is None:
        return
    repo_root, _record, handle, runner_obj = resolved
    try:
        runner_obj.cancel(handle, repo_root=repo_root)
    except runner.RunnerError as exc:
        _fail(ctx, as_json=as_json, error_type="cancel_failed", message=str(exc))
        return
    user_output(f"Cancelled run {run_id} ({handle.run_ref})")
    if as_json:
        machine_output(json.dumps(_action_payload("cancel", run_id, handle)))


@click.command("retry")
@click.argument("run_id")
@click.option("--failed", "failed", is_flag=True, help="Re-run only the failed jobs.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def workflow_run_retry(ctx: click.Context, *, run_id: str, failed: bool, as_json: bool) -> None:
    """Re-run a completed/failed dispatched run by its perk run_id (``--failed`` = failed jobs)."""
    resolved = _resolve_target(ctx, as_json=as_json, run_id=run_id, action="retry")
    if resolved is None:
        return
    repo_root, _record, handle, runner_obj = resolved
    try:
        runner_obj.retry(handle, failed_only=failed, repo_root=repo_root)
    except runner.RunnerError as exc:
        _fail(ctx, as_json=as_json, error_type="retry_failed", message=str(exc))
        return
    user_output(f"Retried {'failed jobs of ' if failed else ''}run {run_id} ({handle.run_ref})")
    if as_json:
        machine_output(json.dumps(_action_payload("retry", run_id, handle, failed_only=failed)))


register_with_aliases(workflow_group, run_group)
register_with_aliases(run_group, workflow_run_list)
register_with_aliases(run_group, workflow_run_cancel)
register_with_aliases(run_group, workflow_run_retry)
