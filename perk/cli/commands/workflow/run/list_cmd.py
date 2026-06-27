"""`perk workflow run list` — enumerate dispatched runs with a live GitHub overlay."""

import json
from datetime import UTC, datetime
from typing import Any

import click

from perk import github
from perk.backends import issue_backend, resolve
from perk.cli.alias import alias
from perk.cli.commands.workflow.run.shared import fail
from perk.cli.context import require_repo
from perk.cli.ensure import UserFacingCliError
from perk.run import runner
from perk.state import cache
from perk.substrate.output import machine_output, user_output

# Per-column display clamps for the human table (the full RUN_ID is never clamped).
_COL_CAP = 14


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
    record: cache.Dispatch,
    *,
    run_obs: runner.RunObservation | None,
    pr: github.PullRequest | None,
) -> dict[str, Any]:
    """Assemble one run's JSON dict from the record + the (possibly ``None``) overlays."""
    plan_ref = record.plan_ref
    pr_id = plan_ref.pr_id.strip()
    run_block: dict[str, Any] | None = None
    if run_obs is not None:
        run_block = {
            "run_ref": record.run_handle.run_ref if record.run_handle else "",
            "url": run_obs.url,
            "status": run_obs.status,
            "conclusion": run_obs.conclusion,
        }
    pr_block: dict[str, Any] | None = None
    if pr is not None:
        pr_block = {"number": pr.number, "url": pr.url, "state": pr.state}
    return {
        "run_id": record.run_id,
        "stage": record.stage,
        "runner": record.runner,
        "kind": record.kind,
        "dispatch_status": record.status,
        "dispatched_at": record.dispatched_at,
        "error": record.error,
        "plan": {"pr_id": pr_id, "url": plan_ref.url},
        "pr": pr_block,
        "run": run_block,
    }


def _overlay(
    record: cache.Dispatch,
    repo_root: Any,
    *,
    plan_cache: dict[str, issue_backend.PlanState | None],
) -> tuple[runner.RunObservation | None, github.PullRequest | None]:
    """Best-effort live overlay for one record: (run observation, correlated PR). Each read is
    fail-soft — a failure degrades to ``None`` with a one-line stderr note, never raises."""
    run_obs: runner.RunObservation | None = None
    handle = record.run_handle
    if handle is not None:
        try:
            run_obs = runner.select_runner(record.runner).observe(handle, repo_root=repo_root)
        except runner.RunnerError as exc:
            user_output(f"note: run state unavailable for {record.run_id}: {exc}")
            run_obs = None

    pr: github.PullRequest | None = None
    # Plan ids are opaque strings (contracts §8.21): any non-empty id resolves via the backend.
    pr_id = record.plan_ref.pr_id.strip()
    if pr_id:
        if pr_id in plan_cache:
            plan_state = plan_cache[pr_id]
        else:
            try:
                backend = resolve.resolve_issue_backend(repo_root)
                plan_state = backend.get_plan(issue_id=pr_id)
            except issue_backend.IssueBackendError as exc:
                user_output(f"note: plan #{pr_id} unavailable: {exc}")
                plan_state = None
            plan_cache[pr_id] = plan_state
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
    is_flag=True,
    help="Skip live GitHub reads; report only the durable dispatch-record state.",
)
@click.option(
    "--limit",
    type=click.IntRange(min=1),
    default=50,
    show_default=True,
    help="Max runs to display (newest-first).",
)
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def list_runs(ctx: click.Context, *, no_refresh: bool, limit: int, as_json: bool) -> None:
    """Enumerate dispatched runs, correlating run_id ↔ plan ↔ PR with a live GitHub overlay."""
    try:
        repo_root = require_repo(ctx)
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return

    records = cache.list_dispatch_records(repo_root)[:limit]
    refreshed = not no_refresh
    plan_cache: dict[str, issue_backend.PlanState | None] = {}
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
