"""`perk objective node-add` — insert a new roadmap node (auto-assigned `<phase>.<n>`)."""

import json

import click

from perk import objective
from perk.backends import resolve
from perk.backends.objective_store import ObjectiveStore, ObjectiveStoreError
from perk.cli.commands.objective.shared import parse_objective_id
from perk.cli.context import require_github, require_repo
from perk.cli.emit import fail
from perk.cli.ensure import UserFacingCliError
from perk.substrate.output import machine_output, user_output


@click.command("node-add")
@click.argument("number")
@click.option("--phase", type=int, required=True, help="The phase number to insert the node into.")
@click.option("--description", required=True, help="The new node's description.")
@click.option(
    "--status",
    type=click.Choice([s.value for s in objective.NodeStatus]),
    default=objective.NodeStatus.PENDING.value,
    help="The new node's status (default: pending).",
)
@click.option("--slug", help="The node slug (auto-derived from the description if omitted).")
@click.option(
    "--depends-on",
    "depends_on_ids",
    multiple=True,
    help="A node id this node depends on (repeatable).",
)
@click.option("--comment", help="An optional note attached to the node.")
@click.option("--dry-run", is_flag=True, help="Validate without writing.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def node_add_objective(
    ctx: click.Context,
    *,
    number: str,
    phase: int,
    description: str,
    status: str,
    slug: str | None,
    depends_on_ids: tuple[str, ...],
    comment: str | None,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Insert a new node into a phase (auto-assigned `<phase>.<n>`; appended after that phase's
    last node). Use sparingly — only when a genuinely new unit of work emerged (a deferred
    follow-up, an uncovered defect or gap, a missing prerequisite for a later node, or
    human-requested work)."""
    try:
        repo_root = require_repo(ctx)
        number = parse_objective_id(number)
        if not dry_run:
            require_github(ctx)
        store = resolve.resolve_objective_store(repo_root)
        result = store.add_objective_node(
            objective_id=number,
            phase=phase,
            description=description,
            status=objective.NodeStatus(status),
            slug=slug,
            depends_on=tuple(depends_on_ids) or None,
            comment=comment,
            dry_run=dry_run,
        )
    except ObjectiveStoreError as exc:
        error_type = "invalid_input" if "collision" in str(exc) else "github_error"
        fail(ctx, as_json=as_json, error_type=error_type, message=str(exc))
        return
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return

    # Reopen-on-incomplete: a successful non-dry-run add of a NON-terminal node makes the
    # roadmap incomplete again, so a closed objective must converge back to open (the mirror of
    # land's close-on-complete). Terminal adds short-circuit before any read.
    reopened = False
    reopen_error: str | None = None
    if not dry_run and objective.NodeStatus(status) not in objective.TERMINAL:
        reopened, reopen_error = _reopen_on_incomplete(store, number)

    payload = {
        "success": True,
        "error_type": None,
        "objective": number,
        "node": result.node_id,
        "comment_updated": result.comment_updated,
        "reopened": reopened,
        "reopen_error": reopen_error,
        "dry_run": result.dry_run,
    }
    if as_json:
        machine_output(json.dumps(payload))
    else:
        user_output(click.style("✓ ", fg="green") + f"Added node {result.node_id} on #{number}")
        if reopened:
            user_output(
                click.style("✓ ", fg="green") + f"Reopened #{number} (roadmap incomplete again)"
            )


def _reopen_on_incomplete(store: ObjectiveStore, number: str) -> tuple[bool, str | None]:
    """Converge the objective open after a non-terminal node insertion (the reopen-on-incomplete
    invariant — "roadmap incomplete ⇒ open", the mirror of land's close-on-complete).

    Inserting live work into a closed objective expresses intent that it is live again — even an
    objective a human closed early (incomplete, not superseded) reopens. The ONE exemption is
    superseded lineage, guarded backend-neutrally here at the door (never in a store):
    ``objective replan`` closed that objective deliberately and stamped ``superseded_by`` — a
    perk-schema header field, not a backend-owned opaque value — so resurrecting it would fork
    the live objective; the skip is policy, not an error (``reopen_error`` stays ``None``).

    Isolated fail-open, the exact posture of land's close: an ``ObjectiveStoreError`` anywhere in
    the gesture is reported on stderr and returned as ``reopen_error``, never discarding the
    already-applied add result. Returns ``(reopened, reopen_error)``.
    """
    try:
        state = store.get_objective(objective_id=number)
        superseded = None if state is None else state.header.get("superseded_by")
        if superseded:
            user_output(
                f"perk objective node-add: objective #{number} superseded by {superseded}; "
                "not reopening"
            )
            return False, None
        return store.reopen_objective(objective_id=number), None
    except ObjectiveStoreError as exc:
        user_output(f"perk objective node-add: objective reopen skipped (non-fatal): {exc}")
        return False, str(exc)
