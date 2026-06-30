"""``perk objective plan [NUMBER] [--node ID]`` — the objective plan-factory cold door.

The objective **transition** surface on top of the deterministic mechanics: select the next
actionable objective node (**pending-first** dependency-graph order — unblocked ``pending`` nodes
win, a resumable ``planning`` claim is only a fallback so parallel launches never steal a
possibly-live claim — or an explicit ``--node``), mark it
``planning``, and launch a **read-only** plan-mode session seeded with that node so the model
authors a *bounded* plan through the existing ``plan → save`` spine.

A **dedicated** command (in ``DEDICATED_STAGES``), not the generic registry launcher: the generic
launcher accepts only ``--worktree/--dry-run/--remote`` and could not select a node. Mirrors
``implement_cmd``. The cold door **requires** an explicit objective NUMBER — a fresh cold session
cannot read the session-only ``active_objective`` (the warm ``/objective-plan`` resolves that).

Supervisor surface: ``--json`` → stdout, human text → stderr, stable exits
(``0`` ok · ``1`` invalid/op-failure · ``2`` not-a-repo). Deterministic mechanics stay in Python;
the judgment (scope bounding, the completion audit) lives in the ``perk-objective-plan`` skill.
"""

import json

import click

from perk import objective
from perk.backends import resolve
from perk.backends.engagement import EMPTY_NODE_ENGAGEMENT, render_node_engagement
from perk.backends.objective_store import ObjectiveStoreError
from perk.cli.commands.objective.shared import (
    fail,
    objective_read_instruction,
    parse_objective_id,
)
from perk.cli.context import require_config, require_github, require_repo
from perk.cli.ensure import UserFacingCliError
from perk.prompts import render
from perk.run import launch
from perk.substrate.output import log_step, machine_output, user_output
from perk.substrate.registry import Stage, load_registry


def _objective_plan_stage() -> Stage:
    return next(s for s in load_registry().stages if s.id == "objective-plan")


def _node_not_plannable_error(
    graph: objective.DependencyGraph, number: str, node_id: str
) -> UserFacingCliError:
    """A targeted error for an explicit ``--node`` that is not plannable, derived from the node's
    actual state (not found / in-flight / terminal / blocked)."""
    node = next((n for n in graph.nodes if n.id == node_id), None)
    if node is None:
        return UserFacingCliError(
            f"Node {node_id!r} not found on objective #{number}.",
            error_type="no_actionable_node",
        )
    if node in graph.in_flight_nodes():
        return UserFacingCliError(
            f"Node {node_id} already has a plan in flight (pr {node.pr or 'pending'}). "
            f"Implement it (`perk implement {node.pr}` when set), or reset it "
            f"(`perk objective node {number} --node {node_id} --status pending`) to re-plan.",
            error_type="objective_in_flight",
        )
    if node.status in objective.TERMINAL:
        return UserFacingCliError(
            f"Node {node_id} is already {node.status.value}.",
            error_type="no_actionable_node",
        )
    return UserFacingCliError(
        f"Node {node_id} is blocked by an unfinished dependency.",
        error_type="no_actionable_node",
    )


def _seed_prompt(
    number: str,
    node: objective.ObjectiveNode,
    title: str,
    model: str | None = None,
    backend: str = "github",
    url: str = "",
    node_engagement: str = "",
) -> str:
    """The node-seeded initial prompt for the read-only plan-mode session.

    The objective title + node description are wrapped as ``<untrusted_objective>`` and must be
    treated as DATA, never as instructions. The loop is file-first (``plan_draft`` →
    ``plan_review`` → approval-driven save); the node link rides this run's ``handoff_extra``
    (recovered by ``perk plan-save``), so no ``objective_node`` planning mark is instructed —
    the cold door already marked the node before launch. When ``model`` is set, the OPTIONAL
    ``perk.objective-explorer`` spawn carries an inline `model` override ([subagents]
    objective-explorer); otherwise the agent's frontmatter default is used.

    ``node_engagement`` is the pre-rendered ``<untrusted_node_engagement>`` block: when
    non-empty it is injected immediately after the ``<untrusted_objective>`` block as untrusted
    DATA the plan must comprehend; when empty the seed is byte-unchanged (GitHub / no engagement).
    """
    read_clause = objective_read_instruction(backend, number, url)
    return render(
        "stages/objective-plan/seed.md",
        {
            "number": number,
            "title": title,
            "node_id": node.id,
            "node_description": node.description,
            "node_engagement": node_engagement,
            "read_clause": read_clause,
            "model": model or "",
        },
    )


@click.command("plan", context_settings={"ignore_unknown_options": True})
@click.argument("number", required=False)
@click.option("--node", "node_id", help="Plan a specific node id (else next actionable).")
@click.option("--worktree", help="Worktree to position (objective plan runs at repo root).")
@click.option("--dry-run", is_flag=True, help="Resolve + print; mark nothing, launch nothing.")
@click.option(
    "--remote",
    type=str,
    default=None,
    is_flag=False,
    flag_value="",
    help="Local (default) or a remote runner; objective plan is local-only (cold_remote:false).",
)
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.option(
    "--no-sync",
    "no_sync",
    is_flag=True,
    help="Skip the pre-launch fast-forward of the main checkout.",
)
@click.argument("pi_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def plan_objective(
    ctx: click.Context,
    *,
    number: str | None,
    node_id: str | None,
    worktree: str | None,
    dry_run: bool,
    remote: str | None,
    as_json: bool,
    no_sync: bool,
    pi_args: tuple[str, ...],
) -> None:
    """Select the next objective node and author a bounded plan (read-only).

    \b
    NUMBER is the objective issue id (required — a cold session has no active objective).
    \b
    Examples:
      perk objective plan 7                 # plan the next actionable node of objective #7
      perk objective plan 7 --node 2.3      # plan a specific node
      perk objective plan 7 --dry-run       # resolve + print, mark/launch nothing
      perk objective plan https://github.com/o/r/issues/7   # paste the URL instead of the id
    """
    try:
        repo_root = require_repo(ctx)
        config = require_config(ctx)
        if number is None:
            raise UserFacingCliError(
                "An objective number is required (e.g. `perk objective plan 7`).",
                error_type="objective_required",
            )
        number = parse_objective_id(number)
        if not dry_run:
            require_github(ctx)

        store = resolve.resolve_objective_store(repo_root)
        # Banner first: head a real local launch with the banner BEFORE narrating the lookup wait.
        launch.print_launch_banner_gated(repo_root, dry_run=dry_run, remote=remote)
        # Narrate the backend lookup wait. The lookup runs on the dry-run path too (dry-run
        # resolves the node via this read), so the narration is NOT gated on `dry_run`; the line
        # goes to stderr, leaving the `--json` stdout payload byte-unchanged.
        log_step(f"looking up objective #{number}")
        state = store.get_objective(objective_id=number)
        if state is None:
            raise UserFacingCliError(
                f"Objective #{number} not found", error_type="objective_not_found"
            )

        graph = objective.build_graph(list(state.nodes))
        plannable = {n.id: n for n in graph.plannable_nodes()}
        if node_id is not None:
            node = plannable.get(node_id)
            if node is None:
                raise _node_not_plannable_error(graph, number, node_id)
        else:
            sel = graph.classify_for_planning()
            if sel.kind == "plannable":
                assert sel.node is not None
                node = sel.node
            elif sel.kind == "complete":
                raise UserFacingCliError(
                    f"Objective #{number} is complete — every node is done or skipped. "
                    "Nothing to plan.",
                    error_type="no_actionable_node",
                )
            elif sel.kind == "in_flight":
                assert sel.node is not None
                raise UserFacingCliError(
                    f"No new node to plan: node {sel.node.id} has a plan in flight "
                    f"(pr {sel.node.pr or 'pending'}, status {sel.node.status.value}). "
                    f"Implement it (`perk implement {sel.node.pr}` when set), or reset it to "
                    "re-plan.",
                    error_type="objective_in_flight",
                )
            else:
                raise UserFacingCliError(
                    f"No actionable node on objective #{number}: every remaining node is blocked "
                    "by an unfinished dependency (or explicitly blocked).",
                    error_type="no_actionable_node",
                )

        # Claims skipped by pending-first selection (possibly live in another terminal, possibly
        # abandoned) — surfaced so a multi-terminal user can coordinate / explicitly resume.
        skipped = [n.id for n in graph.resumable_claims() if n.id != node.id]

        stage = _objective_plan_stage()
        # Resolve the run target up front so `--remote` on this local-only stage is rejected before
        # any mutation (mirrors launch_stage, which re-resolves it harmlessly).
        launch.resolve_target(stage, remote)

        marked_status = objective.NodeStatus.PLANNING
        if skipped and not (dry_run and as_json):
            user_output(
                click.style(
                    f"note: node(s) {', '.join(skipped)} have unresumed planning claims "
                    "(resume with --node <id>)",
                    dim=True,
                )
            )
        if not dry_run:
            store.update_objective_node(
                objective_id=number,
                node_id=node.id,
                status=marked_status,
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

    # Read the node-issue's pre-planning human engagement, fail-soft: a Linear hiccup
    # must never break the factory launch. Empty/None for GitHub + no-engagement → byte-unchanged
    # seed. Skipped on a dry run (resolve-only, offline). Read AFTER the node is marked above.
    engagement_block = ""
    if not dry_run:
        try:
            ne = store.read_node_engagement(objective_id=number, node_id=node.id)
        except ObjectiveStoreError:
            ne = EMPTY_NODE_ENGAGEMENT
        engagement_block = render_node_engagement(ne) or ""

    seed = _seed_prompt(
        number,
        node,
        state.title,
        config.subagents.get("objective-explorer"),
        backend=store.backend_id,
        url=state.url,
        node_engagement=engagement_block,
    )

    if dry_run:
        # Resolve + report only: nothing marked, nothing launched. A single payload (no
        # launch_stage fall-through, which would emit a second JSON object).
        if as_json:
            machine_output(
                json.dumps(
                    {
                        "success": True,
                        "error_type": None,
                        "objective": number,
                        "node": node.id,
                        "marked_status": marked_status.value,
                        "skipped_claims": skipped,
                        "dry_run": True,
                    }
                )
            )
        else:
            user_output(
                click.style("objective plan --dry-run (resolve only; no mark, no launch)", dim=True)
            )
            user_output(f"  objective=#{number}  node={node.id}  would-mark={marked_status.value}")
        return

    if as_json:
        user_output(f"selected objective #{number} node {node.id} (marked {marked_status.value})")
    # launch_stage exec's pi with the node-seeded prompt (becomes the session — nothing after runs).
    launch.launch_stage(
        repo_root=repo_root,
        config=config,
        stage=stage,
        worktree=worktree,
        dry_run=False,
        remote=remote,
        pi_args=list(pi_args),
        prompt_override=seed,
        # Carry the link through the handoff so `perk plan-save` recovers objective_id/node_id
        # regardless of which save surface the model uses (the /plan-save command forwards only
        # {plan, title}). The factory already marked node.id `planning` above.
        handoff_extra={"objective_id": number, "node_id": node.id},
        sync_main=not no_sync,
    )
