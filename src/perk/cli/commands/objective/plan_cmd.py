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

from pathlib import Path

import click

from perk import objective
from perk.backends import resolve
from perk.backends.engagement import EMPTY_NODE_ENGAGEMENT, render_node_engagement
from perk.backends.objective_store import ObjectiveStoreError
from perk.cli.commands.objective.shared import (
    objective_read_instruction,
    parse_objective_id,
)
from perk.cli.commands.seeded_door import SeededLaunch, run_seeded_door, seeded_door_options
from perk.cli.context import require_github
from perk.cli.ensure import Ensure, UserFacingCliError
from perk.prompts import render
from perk.run import launch
from perk.substrate.config import Config
from perk.substrate.output import io_step, user_output
from perk.substrate.registry import Stage


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
    ``perk.objective-explorer`` workflowScript call carries a workflow-level `model` default
    ([models.subagents] objective-explorer); otherwise the agent's frontmatter default is used.

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
@seeded_door_options(
    worktree_help="Worktree to position (objective plan runs at repo root).",
    dry_run_help="Resolve + print; mark nothing, launch nothing.",
    remote_subject="objective plan",
)
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

    def gather(repo_root: Path, config: Config, stage: Stage) -> SeededLaunch:
        nonlocal number
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
        # goes to stderr, leaving the `--json` stdout payload byte-unchanged. The refusal raises
        # escape the step (dangling + the error text below).
        with io_step(f"looking up objective #{number}") as s:
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
                    node = Ensure.not_none(sel.node, "plannable selection must carry a node")
                elif sel.kind == "complete":
                    raise UserFacingCliError(
                        f"Objective #{number} is complete — every node is done or skipped. "
                        "Nothing to plan.",
                        error_type="no_actionable_node",
                    )
                elif sel.kind == "in_flight":
                    in_flight = Ensure.not_none(sel.node, "in_flight selection must carry a node")
                    raise UserFacingCliError(
                        f"No new node to plan: node {in_flight.id} has a plan in flight "
                        f"(pr {in_flight.pr or 'pending'}, status {in_flight.status.value}). "
                        f"Implement it (`perk implement {in_flight.pr}` when set), or reset it to "
                        "re-plan.",
                        error_type="objective_in_flight",
                    )
                else:
                    raise UserFacingCliError(
                        f"No actionable node on objective #{number}: every remaining node is "
                        "blocked by an unfinished dependency (or explicitly blocked).",
                        error_type="no_actionable_node",
                    )
            s.done(f"found objective #{number} — node {node.id}")

        # Claims skipped by pending-first selection (possibly live in another terminal, possibly
        # abandoned) — surfaced so a multi-terminal user can coordinate / explicitly resume.
        skipped = [n.id for n in graph.resumable_claims() if n.id != node.id]

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
        # Narrate the node-mark write (narration follows the I/O: this write genuinely does not
        # run on --dry-run, so the step is real-run-only).
        if not dry_run:
            with io_step(f"marking node {node.id} planning") as mark:
                store.update_objective_node(
                    objective_id=number,
                    node_id=node.id,
                    status=marked_status,
                )
                mark.done(f"marked node {node.id} planning")

        # Read the node-issue's pre-planning human engagement, fail-soft: a Linear hiccup
        # must never break the factory launch. Empty/None for GitHub + no-engagement →
        # byte-unchanged seed. Skipped on a dry run (resolve-only, offline). Read AFTER the node
        # is marked above.
        engagement_block = ""
        if not dry_run:
            with io_step("reading node engagement") as eng:
                try:
                    ne = store.read_node_engagement(objective_id=number, node_id=node.id)
                except ObjectiveStoreError:
                    ne = EMPTY_NODE_ENGAGEMENT
                    eng.warn("node engagement unavailable — continuing without it")
                else:
                    eng.done("read node engagement")
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
        return SeededLaunch(
            seed=seed,
            launch_note=(
                f"selected objective #{number} node {node.id} (marked {marked_status.value})"
            ),
            dry_run_label="objective plan --dry-run (resolve only; no mark, no launch)",
            dry_run_fields=(
                f"  objective=#{number}  node={node.id}  would-mark={marked_status.value}",
            ),
            dry_run_payload={
                "success": True,
                "error_type": None,
                "objective": number,
                "node": node.id,
                "marked_status": marked_status.value,
                "skipped_claims": skipped,
                "dry_run": True,
            },
            # This door's human dry-run prints no seed section (resolve-only report).
            dry_run_shows_seed=False,
            # Carry the link through the handoff so `perk plan-save` recovers objective_id/node_id
            # regardless of which save surface the model uses (the /plan-save command forwards
            # only {plan, title}). The factory already marked node.id `planning` above.
            handoff_extra={"objective_id": number, "node_id": node.id},
        )

    run_seeded_door(
        ctx,
        stage_id="objective-plan",
        worktree=worktree,
        dry_run=dry_run,
        remote=remote,
        as_json=as_json,
        no_sync=no_sync,
        pi_args=pi_args,
        backend_errors=(ObjectiveStoreError,),
        gather=gather,
    )
