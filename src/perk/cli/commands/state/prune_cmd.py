"""`perk state prune` (alias `gc`) — prune stale `.perk/workflow/` run state.

Executes the GC policy in ``perk/state/gc.py``: terminal-stage prune + age-based prune (default
14d).
``require_repo`` anchors at the checkout root and refuses outside a repo — pruning is
destructive, so cwd-anchoring (like ``new-run``) is not acceptable here. Deletion lives
*exclusively* in this command; the ``cache-gc`` doctor check only reports (no ``--fix`` arm).
"""

import json
from typing import Any

import click

from perk.cli.alias import alias
from perk.cli.context import require_repo
from perk.cli.ensure import UserFacingCliError
from perk.state import gc
from perk.substrate.output import machine_output, user_output

_EXIT_FOR_TYPE = {"not_a_repo": 2}


def _fail(ctx: click.Context, *, as_json: bool, error_type: str, message: str) -> None:
    """Mirror ``workflow run``'s ``shared.fail`` (kept local to avoid a cross-group import)."""
    if as_json:
        machine_output(json.dumps({"success": False, "error_type": error_type, "message": message}))
    else:
        user_output(click.style("Error: ", fg="red") + message)
    ctx.exit(_EXIT_FOR_TYPE.get(error_type, 1))


def _candidate_dict(candidate: gc.PruneCandidate) -> dict[str, Any]:
    return {
        "run_id": candidate.run_id,
        "reason": candidate.reason,
        "run_dir": str(candidate.run_dir) if candidate.run_dir is not None else None,
        "handoff": str(candidate.handoff) if candidate.handoff is not None else None,
    }


@alias("gc")
@click.command("prune")
@click.option(
    "--max-age-days",
    type=click.IntRange(min=0),
    default=gc.DEFAULT_MAX_AGE_DAYS,
    show_default=True,
    help="Age threshold (days) for the age-based prune rule.",
)
@click.option("--dry-run", is_flag=True, help="Preview removals without deleting anything.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable payload on stdout.")
@click.pass_context
def prune_run_state(ctx: click.Context, *, max_age_days: int, dry_run: bool, as_json: bool) -> None:
    """Prune stale `.perk/workflow/` run dirs + handoff blobs (terminal-stage + age rules)."""
    try:
        root = require_repo(ctx)
    except UserFacingCliError as exc:
        _fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return

    plan = gc.plan_prune(root, max_age_days=max_age_days)
    errors = [] if dry_run else gc.execute_prune(plan)

    for candidate in plan.eligible:
        verb = "would prune" if dry_run else "pruned"
        user_output(f"{verb} {candidate.run_id}  ({candidate.reason})")
    for err in errors:
        user_output(click.style("error: ", fg="red") + err)
    verb = "would prune" if dry_run else "pruned"
    user_output(f"{verb} {len(plan.eligible)}; kept {plan.kept}")

    if as_json:
        machine_output(
            json.dumps(
                {
                    "success": not errors,
                    "error_type": None,
                    "dry_run": dry_run,
                    "max_age_days": max_age_days,
                    "pruned": [_candidate_dict(c) for c in plan.eligible],
                    "kept": plan.kept,
                    "errors": errors,
                }
            )
        )
    if errors:
        ctx.exit(1)
