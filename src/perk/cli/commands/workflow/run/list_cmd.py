"""`perk workflow run list` — enumerate runs from the canonical GHA discovery, merged with the
local dispatch-record cache (contracts.md §8.17).

GitHub's run enumeration (via the parseable run-name) is the existence source; the local
``dispatch.json`` records enrich it (plan url, objective correlation, precise dispatch time) and
keep failed/never-triggered dispatches — plus runs older than the newest discovery page —
visible. ``--no-refresh`` is the zero-network cache-only view.
"""

import json
from datetime import UTC, datetime
from typing import Any

import click

from perk import github
from perk.backends import issue_backend, resolve
from perk.cli.alias import alias
from perk.cli.context import require_repo
from perk.cli.emit import fail
from perk.cli.ensure import UserFacingCliError
from perk.run import discovery, runner
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
    source: str,
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
        "source": source,
    }


def _merged_row(
    record: cache.Dispatch,
    run: runner.DiscoveredRun,
    *,
    pr: github.PullRequest | None,
) -> dict[str, Any]:
    """A ``source: "both"`` row: record fields (plan url, objective correlation, precise
    dispatch time, error) enriched with the discovery's live run block — one enumeration
    replaces a per-record ``observe``."""
    row = _row_to_dict(record, run_obs=None, pr=pr, source="both")
    row["run"] = {
        "run_ref": run.handle.run_ref,
        "url": run.handle.url,
        "status": run.status,
        "conclusion": run.conclusion,
    }
    return row


def _discovered_row(run: runner.DiscoveredRun, *, pr: github.PullRequest | None) -> dict[str, Any]:
    """A ``source: "discovered"`` row reconstructed purely from the parsed run-name + the run's
    live state — the run exists on GitHub, so the dispatch evidently succeeded."""
    pr_block: dict[str, Any] | None = None
    if pr is not None:
        pr_block = {"number": pr.number, "url": pr.url, "state": pr.state}
    return {
        "run_id": run.run_id,
        "stage": run.stage,
        "runner": "",
        "kind": run.handle.kind,
        "dispatch_status": "dispatched",
        "dispatched_at": run.dispatched_at,
        "error": None,
        "plan": {"pr_id": run.plan_id, "url": ""},
        "pr": pr_block,
        "run": {
            "run_ref": run.handle.run_ref,
            "url": run.handle.url,
            "status": run.status,
            "conclusion": run.conclusion,
        },
        "source": "discovered",
    }


def _lookup_pr(
    pr_id: str,
    repo_root: Any,
    *,
    plan_cache: dict[str, issue_backend.PlanState | None],
) -> github.PullRequest | None:
    """Best-effort memoized plan→PR correlation (fail-soft: a backend error degrades to ``None``
    with a one-line stderr note). Plan ids are opaque strings (contracts §8.21)."""
    pr_id = pr_id.strip()
    if not pr_id:
        return None
    if pr_id not in plan_cache:
        try:
            backend = resolve.resolve_issue_backend(repo_root)
            plan_cache[pr_id] = backend.get_plan(issue_id=pr_id)
        except issue_backend.IssueBackendError as exc:
            user_output(f"note: plan #{pr_id} unavailable: {exc}")
            plan_cache[pr_id] = None
    plan_state = plan_cache[pr_id]
    return plan_state.pr if plan_state is not None else None


def _sort_key(row: dict[str, Any]) -> tuple[int, float]:
    """Newest-first merge ordering: parseable ISO ``dispatched_at`` first (descending), then
    unparseable/blank timestamps last."""
    raw = str(row["dispatched_at"] or "")
    try:
        when = datetime.fromisoformat(raw)
    except ValueError:
        return (1, 0.0)
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return (0, -when.timestamp())


def _overlay(
    record: cache.Dispatch,
    repo_root: Any,
    *,
    plan_cache: dict[str, issue_backend.PlanState | None],
) -> tuple[runner.RunObservation | None, github.PullRequest | None]:
    """Best-effort live overlay for one local-only record: (run observation, correlated PR).
    Each read is fail-soft — a failure degrades to ``None`` with a one-line stderr note, never
    raises."""
    run_obs: runner.RunObservation | None = None
    handle = record.run_handle
    if handle is not None:
        try:
            run_obs = runner.select_runner(record.runner).observe(handle, repo_root=repo_root)
        except runner.RunnerError as exc:
            user_output(f"note: run state unavailable for {record.run_id}: {exc}")
            run_obs = None
    pr = _lookup_pr(record.plan_ref.pr_id, repo_root, plan_cache=plan_cache)
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

    records = cache.list_dispatch_records(repo_root)
    refreshed = not no_refresh
    plan_cache: dict[str, issue_backend.PlanState | None] = {}

    # Canonical discovery (one enumeration), fail-soft: on a runner error, degrade to the
    # local-cache view with a one-line note — exactly today's offline behavior.
    discovered: list[runner.DiscoveredRun] = []
    if refreshed:
        try:
            discovered = discovery.discover_runs(repo_root, limit=limit)
        except runner.RunnerError as exc:
            user_output(f"note: run discovery unavailable: {exc}")

    by_run_id = {run.run_id: run for run in discovered}
    rows: list[dict[str, Any]] = []
    for record in records:
        run = by_run_id.pop(record.run_id, None)
        if run is not None:
            pr = _lookup_pr(record.plan_ref.pr_id, repo_root, plan_cache=plan_cache)
            rows.append(_merged_row(record, run, pr=pr))
            continue
        # Local-only: failed/`dispatching` records, or runs older than the discovery page.
        if refreshed:
            run_obs, pr = _overlay(record, repo_root, plan_cache=plan_cache)
        else:
            run_obs, pr = None, None
        rows.append(_row_to_dict(record, run_obs=run_obs, pr=pr, source="local"))
    for run in by_run_id.values():  # discovered-only: runs this clone never dispatched
        rows.append(
            _discovered_row(run, pr=_lookup_pr(run.plan_id, repo_root, plan_cache=plan_cache))
        )

    rows.sort(key=_sort_key)
    rows = rows[:limit]
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
