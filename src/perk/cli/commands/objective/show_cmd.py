"""`perk objective show` — header + roadmap + summary + next-node."""

import json

import click

from perk import objective
from perk.backends import resolve
from perk.backends.objective_store import ObjectiveStoreError
from perk.cli import completions
from perk.cli.alias import alias
from perk.cli.commands.objective.shared import (
    StackedSelection,
    node_to_dict,
    parse_objective_id,
    selection_gate_blockers,
    stacked_selection,
)
from perk.cli.context import require_repo
from perk.cli.emit import fail
from perk.cli.ensure import UserFacingCliError
from perk.substrate.output import machine_output, user_output


@alias("s")
@click.command("show")
@click.argument("number", shell_complete=completions.complete_objective_id)
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def show_objective(ctx: click.Context, *, number: str, as_json: bool) -> None:
    """Show an objective's header, roadmap, summary, and next actionable node."""
    try:
        repo_root = require_repo(ctx)
        number = parse_objective_id(number)
        state = resolve.resolve_objective_store(repo_root).get_objective(objective_id=number)
        if state is None:
            raise UserFacingCliError(
                f"Objective #{number} not found", error_type="objective_not_found"
            )
    except ObjectiveStoreError as exc:
        fail(ctx, as_json=as_json, error_type="github_error", message=str(exc))
        return
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return

    nodes = list(state.nodes)
    graph = objective.build_graph(nodes)
    graph_next = graph.next_plannable()
    selection = graph.classify_for_planning()
    claims = graph.resumable_claims()

    # Stacked objectives gain the LIVE readiness block (contracts.md §8.46) with a tolerant
    # degrade — incremental payloads stay byte-identical. `selection_kind`, `resumable_claims`,
    # `summary`, and `nodes` stay graph-derived observational facts (offline vocabulary and
    # source) whether or not the live read succeeded; the live truth rides exclusively in
    # `stacked_readiness` plus the `next_node` override.
    live: StackedSelection | None = None
    live_error: str | None = None
    stacked = False
    try:
        stacked = objective.delivery_policy(state.header) is objective.DeliveryPolicy.STACKED
    except ValueError:
        stacked = False
    if stacked:
        try:
            live = stacked_selection(repo_root, state)
        except UserFacingCliError as exc:
            live_error = exc.format_message()
        if live is None and live_error is None:  # defensive: the policy read said stacked
            live_error = "no delivery train"

    next_node = (
        (live.node if live.kind == "plannable" else None) if live is not None else graph_next
    )
    payload: dict[str, object] = {
        "success": True,
        "error_type": None,
        "objective": {
            # Opaque string id at every machine boundary (contracts §8.21).
            "id": state.id,
            "url": state.url,
            "title": state.title,
            "header": state.header,
        },
        "summary": objective.summary(nodes),
        "nodes": [node_to_dict(n) for n in nodes],
        "next_node": node_to_dict(next_node) if next_node else None,
        "resumable_claims": [node_to_dict(n) for n in claims],
        "selection_kind": selection.kind,
        "all_complete": graph.is_complete(),
    }
    if stacked:
        if live is not None:
            payload["stacked_readiness"] = {
                "checked": True,
                "ready": live.ready,
                "reason": live.reason,
                "blockers": [row.model_dump(mode="json") for row in selection_gate_blockers(live)],
            }
        else:
            payload["stacked_readiness"] = {
                "checked": False,
                "ready": None,
                "reason": live_error,
                "blockers": [],
            }
    if as_json:
        machine_output(json.dumps(payload))
        return
    user_output(f"Objective #{state.id}: {state.title}")
    user_output(f"  summary: {objective.summary(nodes)}")
    if live is not None and live.kind == "plannable" and live.node is not None:
        user_output(f"  next: {live.node.id}")
    elif live is not None and live.kind == "handoff_blocked":
        user_output(f"  next: — (handoff blocked: {live.reason})")
    elif live is not None and live.kind == "build_blocked":
        user_output(f"  next: — (build blocked: {live.reason})")
    elif live is not None and live.kind == "in_flight" and live.node is not None:
        user_output(f"  next: — (in flight: node {live.node.id} pr {live.node.pr or 'pending'})")
    elif graph_next is not None and (live is None or live.kind == "no_candidate"):
        user_output(f"  next: {graph_next.id}")
    elif selection.kind == "complete":
        user_output("  next: — (complete)")
    elif selection.kind == "in_flight" and selection.node is not None:
        user_output(
            f"  next: — (in flight: node {selection.node.id} pr {selection.node.pr or 'pending'})"
        )
    else:
        user_output("  next: — (blocked)")
    if stacked and live is None:
        user_output(
            click.style(
                f"  readiness unchecked ({live_error}) — check: perk objective next {state.id}",
                dim=True,
            )
        )
    unresumed = [n.id for n in claims if next_node is None or n.id != next_node.id]
    if unresumed:
        user_output(
            click.style(
                f"  claims: {', '.join(unresumed)} (planning, unresumed — resume with --node)",
                dim=True,
            )
        )
