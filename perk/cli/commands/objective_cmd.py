"""``perk objective`` — the deterministic objective mechanics (cold-door workers, P2.T9).

A developer / CI / T10 surface (like ``perk state`` / ``perk registry``), **not** an agent
affordance: the model drives objectives through the extension's bounded transition tools (T10),
never by shelling ``perk objective``. Each subcommand is a supervisor surface (cli-vs-pi §3.2):
``--json`` → stdout, human text → stderr, stable exit codes (``0`` ok · ``1`` invalid/op-failure ·
``2`` not-a-repo), ``UserFacingCliError`` with a stable ``error_type``.

Subcommands: ``create`` (two-step issue create from authored markdown), ``show`` (header + roadmap
+ summary + next-node), ``node`` (explicit-status node update), ``next`` (dependency-graph
selection — what T10's ``/objective-plan`` consumes).
"""

import json
import os
from pathlib import Path

import click

from perk import github, objective, plan, run_id
from perk.cli.alias import AliasGroup, alias, register_with_aliases
from perk.cli.context import require_github, require_repo
from perk.cli.ensure import UserFacingCliError
from perk.github import GitHubError
from perk.output import machine_output, user_output

_EXIT_FOR_TYPE = {"not_a_repo": 2}


@alias("obj")
@click.group("objective", cls=AliasGroup)
def objective_group() -> None:
    """Deterministic objective storage + mechanics (dev/CI/T10 surface, not an agent affordance)."""


def _fail(ctx: click.Context, *, as_json: bool, error_type: str, message: str) -> None:
    if as_json:
        machine_output(json.dumps({"success": False, "error_type": error_type, "message": message}))
    else:
        user_output(click.style("Error: ", fg="red") + message)
    ctx.exit(_EXIT_FOR_TYPE.get(error_type, 1))


def _node_to_dict(node: objective.ObjectiveNode) -> dict[str, object]:
    return {
        "id": node.id,
        "description": node.description,
        "status": node.status.value,
        "pr": node.pr,
        "phase": objective.phase_label(objective.derive_phase(node.id)),
    }


@alias("new")
@click.command("create")
@click.option(
    "--body",
    "body_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="Path to the authored objective markdown (may embed a roadmap).",
)
@click.option("--title", "title", default=None, help="Objective title (else derived from body).")
@click.option(
    "--roadmap",
    "roadmap_json",
    default=None,
    help="Structured roadmap as a JSON array of nodes (preferred over embedding YAML in --body).",
)
@click.option(
    "--run-id", "run_id_arg", default=None, help="Correlation run id (defaults to $PERK_RUN_ID)."
)
@click.option("--dry-run", "dry_run", is_flag=True, help="Compose without creating an issue.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def objective_create(
    ctx: click.Context,
    *,
    body_path: Path,
    title: str | None,
    roadmap_json: str | None,
    run_id_arg: str | None,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Mint a run_id and create the perk:objective issue from authored markdown."""
    try:
        repo_root = require_repo(ctx)
        if not dry_run:
            require_github(ctx)
        body_text = body_path.read_text(encoding="utf-8").strip()
        if not body_text:
            raise UserFacingCliError("Objective body is empty", error_type="empty_body")
        # Resolve the roadmap: a structured --roadmap JSON wins (the agent path, never hand-written
        # YAML); otherwise validate any roadmap embedded in the body (the legacy cold-CLI path).
        roadmap_nodes: list[objective.ObjectiveNode] | None = None
        if roadmap_json is not None:
            try:
                raw = json.loads(roadmap_json)
            except json.JSONDecodeError as exc:
                raise UserFacingCliError(
                    f"Invalid --roadmap JSON: {exc}", error_type="invalid_roadmap"
                ) from exc
            roadmap_nodes, errors = objective.parse_structured_roadmap(raw)
        else:
            _nodes, errors = objective.parse_roadmap_nodes(body_text)
        if errors:
            raise UserFacingCliError(
                "Invalid objective roadmap: " + "; ".join(errors), error_type="invalid_roadmap"
            )
        resolved_title = title or plan.derive_title(body_text, fallback="perk objective")
        resolved_run_id = run_id_arg or os.environ.get("PERK_RUN_ID") or run_id.mint()
        issue = github.create_objective_issue(
            title=resolved_title,
            body=body_text,
            repo_root=repo_root,
            run_id=resolved_run_id,
            roadmap_nodes=roadmap_nodes,
            dry_run=dry_run,
        )
    except GitHubError as exc:
        _fail(
            ctx,
            as_json=as_json,
            error_type="github_error",
            message=f"objective create failed\n{exc}",
        )
        return
    except UserFacingCliError as exc:
        _fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return

    payload = {
        "success": True,
        "error_type": None,
        "objective": {"number": issue.number, "url": issue.url, "existed": issue.existed},
        "dry_run": dry_run,
    }
    if as_json:
        machine_output(json.dumps(payload))
    else:
        verb = "Found existing" if issue.existed else "Created"
        user_output(click.style("✓ ", fg="green") + f"{verb} objective #{issue.number} {issue.url}")


@alias("s")
@click.command("show")
@click.argument("number", type=int)
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def objective_show(ctx: click.Context, *, number: int, as_json: bool) -> None:
    """Show an objective's header, roadmap, summary, and next actionable node."""
    try:
        repo_root = require_repo(ctx)
        state = github.get_objective(number=number, repo_root=repo_root)
        if state is None:
            raise UserFacingCliError(
                f"Objective #{number} not found", error_type="objective_not_found"
            )
    except GitHubError as exc:
        _fail(ctx, as_json=as_json, error_type="github_error", message=str(exc))
        return
    except UserFacingCliError as exc:
        _fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return

    nodes = list(state.nodes)
    graph = objective.build_graph(nodes)
    next_node = graph.next_node()
    selection = graph.classify_for_planning()
    payload = {
        "success": True,
        "error_type": None,
        "objective": {
            "number": state.number,
            "url": state.url,
            "title": state.title,
            "header": state.header,
        },
        "summary": objective.summary(nodes),
        "nodes": [_node_to_dict(n) for n in nodes],
        "next_node": _node_to_dict(next_node) if next_node else None,
        "selection_kind": selection.kind,
        "all_complete": graph.is_complete(),
    }
    if as_json:
        machine_output(json.dumps(payload))
    else:
        user_output(f"Objective #{state.number}: {state.title}")
        user_output(f"  summary: {objective.summary(nodes)}")
        if next_node is not None:
            user_output(f"  next: {next_node.id}")
        elif selection.kind == "complete":
            user_output("  next: — (complete)")
        elif selection.kind == "in_flight" and selection.node is not None:
            user_output(
                f"  next: — (in flight: node {selection.node.id} pr "
                f"{selection.node.pr or 'pending'})"
            )
        else:
            user_output("  next: — (blocked)")


@click.command("node")
@click.argument("number", type=int)
@click.option("--node", "node_id", required=True, help="The roadmap node id (e.g. 1.2).")
@click.option(
    "--status",
    "status",
    type=click.Choice([s.value for s in objective.NodeStatus]),
    default=None,
    help="Set the node's status (explicit-only; never inferred from --pr).",
)
@click.option("--pr", "pr", default=None, help='Set/clear the PR ("#N" sets, "" clears).')
@click.option("--description", "description", default=None, help="Update the node description.")
@click.option("--dry-run", "dry_run", is_flag=True, help="Validate without writing.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def objective_node(
    ctx: click.Context,
    *,
    number: int,
    node_id: str,
    status: str | None,
    pr: str | None,
    description: str | None,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Update one roadmap node (explicit-status-only; open #3)."""
    try:
        repo_root = require_repo(ctx)
        if not dry_run:
            require_github(ctx)
        result = github.update_objective_node(
            number=number,
            node_id=node_id,
            status=objective.NodeStatus(status) if status else None,
            pr=pr,
            description=description,
            repo_root=repo_root,
            dry_run=dry_run,
        )
    except GitHubError as exc:
        # A not-found node is a user error, not infra — map it to invalid_input.
        error_type = "node_not_found" if "not found" in str(exc) else "github_error"
        _fail(ctx, as_json=as_json, error_type=error_type, message=str(exc))
        return
    except UserFacingCliError as exc:
        _fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return

    payload = {
        "success": True,
        "error_type": None,
        "objective": number,
        "node": result.node_id,
        "comment_updated": result.comment_updated,
        "dry_run": result.dry_run,
    }
    if as_json:
        machine_output(json.dumps(payload))
    else:
        user_output(click.style("✓ ", fg="green") + f"Updated node {result.node_id} on #{number}")


@alias("rec")
@click.command("reconcile")
@click.argument("number", type=int)
@click.option(
    "--body",
    "body_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="Path to the reconciled Reconcilable-prose markdown (stdin-less worker pattern).",
)
@click.option("--dry-run", "dry_run", is_flag=True, help="Compose without writing.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def objective_reconcile(
    ctx: click.Context, *, number: int, body_path: Path, dry_run: bool, as_json: bool
) -> None:
    """Reconcile an objective's Reconcilable prose region against the merged diff (P2.T11b).

    Rewrites ONLY the marker-bounded Reconcilable region of the objective-body comment — the
    Mechanical roadmap table and any Immutable notes are never touched. Node-description
    reconciliation reuses ``perk objective node --description`` (no new flag here).
    """
    try:
        repo_root = require_repo(ctx)
        if not dry_run:
            require_github(ctx)
        prose = body_path.read_text(encoding="utf-8")
        result = github.update_objective_body(
            number=number, prose=prose, repo_root=repo_root, dry_run=dry_run
        )
    except GitHubError as exc:
        message = str(exc)
        error_type = (
            "reconcile_target_missing"
            if ("no body comment" in message or "no reconcilable region" in message)
            else "github_error"
        )
        _fail(ctx, as_json=as_json, error_type=error_type, message=message)
        return
    except UserFacingCliError as exc:
        _fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return

    payload = {
        "success": True,
        "error_type": None,
        "objective": result.number,
        "comment_id": result.comment_id,
        "updated": result.updated,
        "dry_run": result.dry_run,
    }
    if as_json:
        machine_output(json.dumps(payload))
    else:
        user_output(click.style("✓ ", fg="green") + f"Reconciled objective #{number} prose region")


@alias("n")
@click.command("next")
@click.argument("number", type=int)
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def objective_next(ctx: click.Context, *, number: int, as_json: bool) -> None:
    """Print the next plannable node (pending, or a resumable ``planning`` claim)."""
    try:
        repo_root = require_repo(ctx)
        state = github.get_objective(number=number, repo_root=repo_root)
        if state is None:
            raise UserFacingCliError(
                f"Objective #{number} not found", error_type="objective_not_found"
            )
    except GitHubError as exc:
        _fail(ctx, as_json=as_json, error_type="github_error", message=str(exc))
        return
    except UserFacingCliError as exc:
        _fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return

    next_node = objective.build_graph(list(state.nodes)).next_node()
    payload = {
        "success": True,
        "error_type": None,
        "next_node": _node_to_dict(next_node) if next_node else None,
    }
    if as_json:
        machine_output(json.dumps(payload))
    else:
        user_output(f"next: {next_node.id if next_node else '—'}")


register_with_aliases(objective_group, objective_create)
register_with_aliases(objective_group, objective_show)
register_with_aliases(objective_group, objective_node)
register_with_aliases(objective_group, objective_reconcile)
register_with_aliases(objective_group, objective_next)
