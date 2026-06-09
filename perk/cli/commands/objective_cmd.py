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

import contextlib
import io
import json
import os
import time
from pathlib import Path
from typing import Any

import click

from perk import cache, github, launch, objective, plan, resume, run_id, run_report, runner
from perk.cli.alias import AliasGroup, alias, register_with_aliases
from perk.cli.context import require_config, require_github, require_repo
from perk.cli.ensure import Ensure, UserFacingCliError
from perk.config import Config
from perk.github import GitHubError
from perk.output import machine_output, user_output
from perk.registry import Stage, load_registry

_EXIT_FOR_TYPE = {"not_a_repo": 2}

# The `--wait` polling cadence (D4). Local to this module by design (do not import from
# workflow_smoke) — same *values*, independent lifecycle. A timeout is inconclusive, not unhealthy.
POLL_INTERVAL_S = 15
POLL_TIMEOUT_S = 600


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
        body_nodes: list[objective.ObjectiveNode] = []
        if roadmap_json is not None:
            try:
                raw = json.loads(roadmap_json)
            except json.JSONDecodeError as exc:
                raise UserFacingCliError(
                    f"Invalid --roadmap JSON: {exc}", error_type="invalid_roadmap"
                ) from exc
            roadmap_nodes, errors = objective.parse_structured_roadmap(raw)
        else:
            body_nodes, errors = objective.parse_roadmap_nodes(body_text)
        if errors:
            raise UserFacingCliError(
                "Invalid objective roadmap: " + "; ".join(errors), error_type="invalid_roadmap"
            )
        # Reject a roadmap-free objective before creating (also makes --dry-run reject early). The
        # parse/read layer stays lenient (existing node-less issues remain readable); creation does
        # not. `empty_roadmap` falls through _EXIT_FOR_TYPE to exit 1.
        effective_nodes = roadmap_nodes if roadmap_nodes is not None else body_nodes
        if not effective_nodes:
            raise UserFacingCliError(
                "An objective needs at least one roadmap node — author a roadmap (the "
                "objective_save tool's `roadmap`, or a `--roadmap` JSON array) before creating.",
                error_type="empty_roadmap",
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


# =====================================================================================
# `perk objective run` — the capstone supervisor loop (Node 3.4, §8.20)
#
# A deterministic, no-agentic-reasoning scheduler: report cumulative budget, then advance the
# objective's backlog ONE safe step (dispatch the next ready agentic stage remotely, or pause at a
# draft-PR / awaiting-review / planning-required / completion boundary) and stop. The supervisor
# NEVER lands — ready+merge stays the human/interactive `/land`; nodes reach `done` only via that
# path's reconcile, which this loop merely observes.
# =====================================================================================


def _canon_objective(value: object) -> str:
    """Canonicalize an objective id (``"#137"``/``137`` → ``"137"``; ``None`` → ``""``)."""
    return str(value).lstrip("#") if value is not None else ""


def _fmt_tokens(tokens: int) -> str:
    return f"{tokens / 1000:.0f}k" if tokens >= 1000 else str(tokens)


def _fmt_elapsed(ms: int) -> str:
    seconds = ms // 1000
    return f"{seconds // 60}m" if seconds >= 60 else f"{seconds}s"


def _cumulative_budget(repo_root: Path, number: int) -> dict[str, int]:
    """Sum the budget across every dispatch record for this objective (D3; report-only)."""
    target = str(number)
    runs = turns = tokens = elapsed = 0
    for record in cache.list_dispatch_records(repo_root):
        oid = (record.get("plan_ref") or {}).get("objective_id")
        if _canon_objective(oid) != target:
            continue
        runs += 1
        outcome = run_report.read_outcome(repo_root, str(record.get("run_id", "")))
        if not isinstance(outcome, dict):
            continue
        budget = outcome.get("budget")
        if not isinstance(budget, dict):
            continue
        turns += int(budget.get("turns") or 0)
        tokens += int(budget.get("tokens") or 0)
        elapsed += int(budget.get("elapsed_ms") or 0)
    return {"runs": runs, "turns": turns, "tokens": tokens, "elapsed_ms": elapsed}


def _in_flight_record(
    repo_root: Path, number: int
) -> tuple[dict[str, Any], runner.RunHandle, runner.Runner] | None:
    """The newest in-flight dispatch for this objective (D4), or ``None``.

    A record is in-flight when its ``run_handle`` is present and a live ``observe`` returns
    ``queued``/``in_progress``. Each observe is fail-soft — a runner/GitHub error treats that
    record as not-in-flight (noted to stderr), never raises.
    """
    target = str(number)
    for record in cache.list_dispatch_records(repo_root):  # newest-first
        if _canon_objective((record.get("plan_ref") or {}).get("objective_id")) != target:
            continue
        handle_data = record.get("run_handle")
        if not handle_data:
            continue
        handle = runner.RunHandle.from_data(handle_data)
        runner_obj = runner.select_runner(str(record.get("runner", "")))
        try:
            obs = runner_obj.observe(handle, repo_root=repo_root)
        except (runner.RunnerError, GitHubError) as exc:
            user_output(f"note: run state unavailable for {record.get('run_id', '?')}: {exc}")
            continue
        if obs.status in {"queued", "in_progress"}:
            return record, handle, runner_obj
    return None


def _poll_to_completion(
    handle: runner.RunHandle,
    runner_obj: runner.Runner,
    repo_root: Path,
    *,
    sleep: Any = None,
) -> runner.RunObservation | None:
    """Poll a run to completion (D4). ``None`` on timeout (inconclusive) or a fail-soft observe."""
    do_sleep = sleep or time.sleep
    elapsed = 0
    while elapsed < POLL_TIMEOUT_S:
        try:
            obs = runner_obj.observe(handle, repo_root=repo_root)
        except (runner.RunnerError, GitHubError) as exc:
            user_output(f"note: poll observe failed: {exc}")
            return None
        if obs.status == "completed":
            return obs
        do_sleep(POLL_INTERVAL_S)
        elapsed += POLL_INTERVAL_S
    return None


def needs_address(feedback: github.PrFeedback) -> bool:
    """True when an OPEN non-draft PR has actionable review feedback (D10; pure, offline-testable).

    True when either any review thread is unresolved, or the **latest review per author**
    (max ``submitted_at``, ISO-8601 string compare; ``None`` sorts oldest) is
    ``CHANGES_REQUESTED``. ``COMMENTED``/``APPROVED`` latest reviews and discussion comments are
    not address triggers (the latter are conversation, not change requests).
    """
    if any(not thread.is_resolved for thread in feedback.review_threads):
        return True
    latest: dict[str | None, github.Review] = {}
    for review in feedback.reviews:
        current = latest.get(review.author)
        if current is None or (review.submitted_at or "") >= (current.submitted_at or ""):
            latest[review.author] = review
    return any(review.state == "CHANGES_REQUESTED" for review in latest.values())


def _stage_by_id(stage_id: str) -> Stage:
    """The registry stage by id (``implement``/``address`` only here — guarded in the caller)."""
    for stage in load_registry().stages:
        if stage.id == stage_id:
            return stage
    raise UserFacingCliError(f"unknown stage '{stage_id}'", error_type="dispatch_failed")


def _parse_run_id(captured: str) -> str | None:
    """Extract the ``run_id`` from launch_stage's captured machine-output JSON (D9)."""
    for line in captured.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("run_id"):
            return str(data["run_id"])
    return None


def _dispatch_stage_remote(
    *,
    repo_root: Path,
    config: Config,
    stage_id: str,
    node_plan_state: github.PlanState,
    remote: str,
    dry_run: bool,
) -> str | None:
    """Dispatch ``implement``/``address`` to the remote runner for an in-flight node (D9).

    Reconstructs the node's plan-ref (preserving ``objective_id`` so the eventual human land
    reconciles the node), writes it to the repo-root ``cache.plan-ref`` (the seam
    ``_drive_remote_target`` reads), then drives ``launch_stage`` — capturing its machine output so
    the supervisor surfaces a single unified ``--json`` payload. Returns the minted ``run_id``.
    Under ``--dry-run`` this performs no write/trigger and returns ``None``.
    """
    stage = _stage_by_id(stage_id)
    Ensure.invariant(
        stage.doors.get("cold_remote") is True,
        f"stage '{stage_id}' is not remote-drivable (cold_remote:false)",
    )
    plan_ref = resume.reconstruct_plan_ref(node_plan_state)
    if dry_run:
        return None
    cache.write_plan_ref(repo_root, plan_ref)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        launch.launch_stage(
            repo_root=repo_root,
            config=config,
            stage=stage,
            worktree=None,
            dry_run=False,
            remote=remote,
            pi_args=[],
            prompt_override=None,
        )
    return _parse_run_id(buf.getvalue())


def _resolve_in_flight_stage(
    payload: dict[str, Any],
    *,
    repo_root: Path,
    config: Config,
    number: int,
    node: objective.ObjectiveNode,
    remote: str,
    dry_run: bool,
) -> dict[str, Any]:
    """Resolve the action for an in-flight node by inspecting its linked plan's PR state (D7)."""
    remediation = f"perk objective-plan {number} --node {node.id}"
    # Defensive parse: a malformed/non-numeric `node.pr` (e.g. "#abc") must not raise a raw
    # ValueError — it falls through to the plan_required fallback below like a missing pr.
    raw_pr = str(node.pr).lstrip("#").strip() if node.pr else ""
    pr_number = int(raw_pr) if raw_pr.isdigit() else None
    plan_state = (
        github.get_plan(number=pr_number, repo_root=repo_root) if pr_number is not None else None
    )
    if plan_state is None:  # defensive: an in-flight node should carry a resolvable plan
        payload.update(action="plan_required", node=node.id, remediation=remediation)
        return payload

    pr = plan_state.pr
    if pr is None:  # no PR opened yet → implement work is not done; dispatch it remotely
        run_id_val = _dispatch_stage_remote(
            repo_root=repo_root,
            config=config,
            stage_id="implement",
            node_plan_state=plan_state,
            remote=remote,
            dry_run=dry_run,
        )
        payload.update(action="dispatched", node=node.id, stage="implement", run_id=run_id_val)
        return payload
    if pr.state == "MERGED":  # done transition is pending the human land's reconcile
        payload.update(action="merged_pending_reconcile", node=node.id, pr=pr.number)
        return payload
    if pr.state == "CLOSED":  # closed unmerged — needs human attention
        payload.update(action="pr_closed", node=node.id, pr=pr.number)
        return payload
    if pr.is_draft:  # implement is complete; stop at the draft gate. NEVER re-dispatch implement.
        payload.update(action="ready_for_review", node=node.id, pr=pr.number)
        return payload
    # OPEN non-draft: address actionable feedback, else await the human review/land gate.
    feedback = github.get_pr_feedback(pr_number=pr.number, repo_root=repo_root)
    if needs_address(feedback):
        run_id_val = _dispatch_stage_remote(
            repo_root=repo_root,
            config=config,
            stage_id="address",
            node_plan_state=plan_state,
            remote=remote,
            dry_run=dry_run,
        )
        payload.update(action="dispatched", node=node.id, stage="address", run_id=run_id_val)
        return payload
    payload.update(action="awaiting_review", node=node.id, pr=pr.number)
    return payload


def _run_impl(
    ctx: click.Context, *, number: int, remote: str, wait: bool, dry_run: bool
) -> dict[str, Any]:
    """The deterministic single-pass control flow (D2). Returns the structured payload to render;
    raises ``UserFacingCliError``/``GitHubError`` for the command's ``_fail`` boundary."""
    repo_root = require_repo(ctx)
    config = require_config(ctx)
    if not dry_run:
        require_github(ctx)
    state = github.get_objective(number=number, repo_root=repo_root)
    if state is None:
        raise UserFacingCliError(f"Objective #{number} not found", error_type="objective_not_found")
    graph = objective.build_graph(list(state.nodes))
    payload: dict[str, Any] = {
        "success": True,
        "error_type": None,
        "objective": number,
        "budget": _cumulative_budget(repo_root, number),
        "action": None,
        "node": None,
        "stage": None,
        "run_id": None,
        "remediation": None,
        "closed": False,
        "timed_out": False,
        "dry_run": dry_run,
    }

    # Active-run gate (D4). Skipped under --dry-run to stay fully offline-safe (D11).
    if not dry_run:
        in_flight = _in_flight_record(repo_root, number)
        if in_flight is not None:
            record, handle, runner_obj = in_flight
            if not wait:
                payload.update(action="awaiting_run", run_id=record.get("run_id"))
                return payload
            completed = _poll_to_completion(handle, runner_obj, repo_root)
            if completed is None:
                payload.update(action="awaiting_run", run_id=record.get("run_id"), timed_out=True)
                return payload
            # Re-evaluate against FRESH state after the run settled: the just-completed run may have
            # advanced GitHub (a new PR, updated budget), so re-fetch the objective + rebuild the
            # graph rather than classifying on the pre-poll snapshot.
            payload["budget"] = _cumulative_budget(repo_root, number)
            state = github.get_objective(number=number, repo_root=repo_root)
            if state is None:
                raise UserFacingCliError(
                    f"Objective #{number} not found", error_type="objective_not_found"
                )
            graph = objective.build_graph(list(state.nodes))

    selection = graph.classify_for_planning()
    if selection.kind == "complete":
        closed = github.close_issue(number=number, repo_root=repo_root, dry_run=dry_run)
        payload.update(
            action="completed",
            closed=closed,
            audit=[{"node": n.id, "status": n.status.value, "pr": n.pr} for n in state.nodes],
        )
        return payload
    if selection.kind == "blocked":
        payload.update(action="blocked")
        return payload
    if selection.kind == "plannable" and selection.node is not None:
        node = selection.node
        payload.update(
            action="plan_required",
            node=node.id,
            remediation=f"perk objective-plan {number} --node {node.id}",
        )
        return payload
    # in_flight
    Ensure.invariant(selection.node is not None, "in_flight selection must carry a node")
    assert selection.node is not None
    return _resolve_in_flight_stage(
        payload,
        repo_root=repo_root,
        config=config,
        number=number,
        node=selection.node,
        remote=remote,
        dry_run=dry_run,
    )


def _render_run(payload: dict[str, Any], *, as_json: bool) -> None:
    """Render the supervisor result: budget + action line to stderr; payload to stdout on --json."""
    budget = payload["budget"]
    user_output(
        f"cumulative: {budget['runs']} runs · {_fmt_tokens(budget['tokens'])} tok · "
        f"{budget['turns']} turns · {_fmt_elapsed(budget['elapsed_ms'])}"
    )
    action = payload["action"]
    node = payload.get("node")
    pr = payload.get("pr")
    if action == "dispatched":
        user_output(
            click.style("→ ", fg="green")
            + f"dispatched {payload['stage']} for node {node} (run {payload.get('run_id')})"
        )
    elif action == "ready_for_review":
        user_output(f"PR #{pr} ready for review — mark it ready and /land when satisfied")
    elif action == "awaiting_review":
        user_output(f"node {node} (PR #{pr}): no actionable feedback — awaiting the human review")
    elif action == "awaiting_run":
        suffix = " (timed out — inconclusive)" if payload.get("timed_out") else ""
        user_output(f"run {payload.get('run_id')} still in flight{suffix}")
    elif action == "plan_required":
        user_output(f"node {node} needs a plan — run: {payload.get('remediation')}")
    elif action == "blocked":
        user_output("blocked — every remaining node depends on an unfinished node")
    elif action == "completed":
        for row in payload.get("audit", []):
            user_output(f"  {row['node']} → {row['status']} → {row['pr'] or '—'}")
        verb = "closed" if payload.get("closed") else "would close (dry-run)"
        user_output(click.style("✓ ", fg="green") + f"objective complete — {verb}")
    elif action == "merged_pending_reconcile":
        user_output(f"node {node} (PR #{pr}): merged — node→done pending the land reconcile")
    elif action == "pr_closed":
        user_output(f"node {node} (PR #{pr}): PR closed unmerged — needs human attention")
    if as_json:
        machine_output(json.dumps(payload))


@alias("r")
@click.command("run")
@click.argument("number", type=int)
@click.option(
    "--remote",
    "remote",
    default="",
    help="Runner ref for remote dispatches (default: the default runner).",
)
@click.option(
    "--wait", "wait", is_flag=True, help="Poll an in-flight run to completion, then re-evaluate."
)
@click.option(
    "--dry-run",
    "dry_run",
    is_flag=True,
    help="Resolve + report the decision only — mint/write/trigger/close nothing.",
)
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def objective_run(
    ctx: click.Context, *, number: int, remote: str, wait: bool, dry_run: bool, as_json: bool
) -> None:
    """Advance an objective's backlog one autonomously-safe step, then pause at the human gate."""
    try:
        payload = _run_impl(ctx, number=number, remote=remote, wait=wait, dry_run=dry_run)
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
    _render_run(payload, as_json=as_json)


register_with_aliases(objective_group, objective_create)
register_with_aliases(objective_group, objective_show)
register_with_aliases(objective_group, objective_node)
register_with_aliases(objective_group, objective_reconcile)
register_with_aliases(objective_group, objective_next)
register_with_aliases(objective_group, objective_run)
