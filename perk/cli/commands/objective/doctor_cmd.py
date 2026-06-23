"""`perk objective doctor` — detect (and optionally repair) objective drift.

Detect mode (default) builds the observed snapshot, diffs it against the persisted
``objective-manifest`` baseline, and reports every drift condition. ``--fix`` additionally applies
the **safe, unambiguous** (repairable) repairs in a deterministic order, stopping at the first
failed Linear write (fail-loud). ``--dry-run`` plans the repairs (the would-apply set) without any
write. GitHub objectives (and the issue-backed Linear store) have no divergence surface, so the
report is trivially empty — the worker is a Linear-Project-objective surface.

Supervisor surface: ``--json`` → stdout, human → stderr; exit ``0`` ran / ``1``
op-failure or an aborted repair / ``2`` not-a-repo.
"""

import json

import click

from perk.backends import resolve
from perk.backends.objective_store import (
    DriftCondition,
    ObjectiveStoreError,
    RepairAction,
    RepairResult,
)
from perk.cli.alias import alias
from perk.cli.commands.objective.shared import fail, parse_objective_id
from perk.cli.context import require_github, require_repo
from perk.cli.ensure import UserFacingCliError
from perk.substrate.output import machine_output, user_output


def _condition_to_dict(cond: DriftCondition) -> dict[str, object]:
    return {
        "code": cond.code.value,
        "severity": cond.severity.value,
        "node_id": cond.node_id,
        "target": cond.target,
        "message": cond.message,
        "repairable": cond.repairable,
    }


def _action_to_dict(action: RepairAction) -> dict[str, object]:
    payload: dict[str, object] = {"code": action.code.value, "node_id": action.node_id}
    if action.error is not None:
        payload["error"] = action.error
    return payload


def _fix_to_dict(result: RepairResult) -> dict[str, object]:
    return {
        "applied": [_action_to_dict(a) for a in result.applied],
        "failed": _action_to_dict(result.failed) if result.failed is not None else None,
        "remaining": [_condition_to_dict(c) for c in result.remaining],
        "aborted": result.aborted,
        "dry_run": result.dry_run,
    }


@alias("doc")
@click.command("doctor")
@click.argument("number")
@click.option("--fix", is_flag=True, help="Apply the safe, unambiguous repairs (else report only).")
@click.option("--dry-run", is_flag=True, help="With --fix: plan the repairs without writing.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def doctor_objective(
    ctx: click.Context, *, number: str, fix: bool, dry_run: bool, as_json: bool
) -> None:
    """Detect (and with ``--fix`` repair) drift between an objective's manifest and live state."""
    try:
        repo_root = require_repo(ctx)
        number = parse_objective_id(number)
        store = resolve.resolve_objective_store(repo_root)
        report = store.detect_objective_drift(objective_id=number)
        fix_result: RepairResult | None = None
        if fix:
            if not dry_run:
                require_github(ctx)
            fix_result = store.repair_objective_drift(objective_id=number, dry_run=dry_run)
    except ObjectiveStoreError as exc:
        message = str(exc)
        error_type = "objective_missing" if "not found" in message else "github_error"
        fail(ctx, as_json=as_json, error_type=error_type, message=message)
        return
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return

    payload: dict[str, object] = {
        "success": True,
        "error_type": None,
        "objective": number,
        "drift": [_condition_to_dict(c) for c in report.conditions],
        "fix": _fix_to_dict(fix_result) if fix_result is not None else None,
    }
    if as_json:
        machine_output(json.dumps(payload))
    else:
        _render_human(number, report.conditions, fix_result)

    # A repairable write that failed (aborted) is an op-failure — exit 1 (fail-loud). Report-only
    # drift (including ERRORs perk has no authority to auto-repair) is a clean report → exit 0.
    if fix_result is not None and fix_result.aborted:
        ctx.exit(1)


def _render_human(
    number: str, conditions: tuple[DriftCondition, ...], fix_result: RepairResult | None
) -> None:
    if not conditions:
        user_output(click.style("✓ ", fg="green") + f"Objective #{number}: no drift detected")
        return
    user_output(f"Objective #{number}: {len(conditions)} drift condition(s)")
    for cond in conditions:
        colour = {"error": "red", "warning": "yellow", "info": "cyan"}.get(
            cond.severity.value, "white"
        )
        tag = click.style(cond.severity.value.upper(), fg=colour)
        where = f" [{cond.node_id}]" if cond.node_id else ""
        user_output(f"  {tag} {cond.code.value}{where}: {cond.message}")
    if fix_result is not None:
        verb = "would apply" if fix_result.dry_run else "applied"
        user_output(f"  fix: {verb} {len(fix_result.applied)} repair(s)")
        if fix_result.failed is not None:
            user_output(
                click.style("  fix aborted: ", fg="red")
                + f"{fix_result.failed.code.value}: {fix_result.failed.error}"
            )
