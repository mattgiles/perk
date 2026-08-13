"""`perk objective run` — the capstone supervisor loop (§8.20).

A deterministic, no-agentic-reasoning scheduler: report cumulative budget, then advance the
objective's backlog ONE safe step (dispatch the next ready agentic stage remotely, or pause at a
draft-PR / awaiting-review / planning-required / completion boundary) and stop. The supervisor
NEVER lands — ready+merge stays the human/interactive ``/land``; nodes reach ``done`` only via that
path's reconcile, which this loop merely observes.
"""

import contextlib
import io
import json
import time
from pathlib import Path
from typing import Any

import click

from perk import github, objective
from perk.backends import issue_backend, resolve
from perk.backends.issue_backend import IssueBackendError
from perk.backends.objective_store import ObjectiveState, ObjectiveStoreError
from perk.cli.alias import alias
from perk.cli.commands.objective.shared import (
    classify_stacked_veto,
    parse_objective_id,
    stacked_lower_attention,
    stacked_selection,
)
from perk.cli.context import require_github, require_repo
from perk.cli.emit import fail
from perk.cli.ensure import Ensure, UserFacingCliError
from perk.cli.plan_selection import load_main_config, main_repo_root
from perk.github import GitHubError
from perk.run import discovery, launch, resume, run_report, runner
from perk.state import cache
from perk.substrate.config import Config
from perk.substrate.output import machine_output, user_output
from perk.substrate.registry import Stage, load_registry

# The `--wait` polling cadence. Local to this module by design (do not import from
# workflow_smoke) — same *values*, independent lifecycle. A timeout is inconclusive, not unhealthy.
POLL_INTERVAL_S = 15
POLL_TIMEOUT_S = 600


def _canon_objective(value: object) -> str:
    """Canonicalize an objective id (``"#137"``/``137`` → ``"137"``; ``None`` → ``""``)."""
    return str(value).lstrip("#") if value is not None else ""


def _fmt_tokens(tokens: int) -> str:
    return f"{tokens / 1000:.0f}k" if tokens >= 1000 else str(tokens)


def _fmt_elapsed(ms: int) -> str:
    seconds = ms // 1000
    return f"{seconds // 60}m" if seconds >= 60 else f"{seconds}s"


def _cumulative_budget(repo_root: Path, number: str) -> dict[str, int]:
    """Sum the budget across every dispatch record for this objective (report-only)."""
    target = number
    runs = turns = tokens = elapsed = 0
    for record in cache.list_dispatch_records(repo_root):
        oid = record.plan_ref.objective_id
        if _canon_objective(oid) != target:
            continue
        runs += 1
        outcome = run_report.read_outcome(repo_root, record.run_id)
        if not isinstance(outcome, dict):
            continue
        budget = outcome.get("budget")
        if not isinstance(budget, dict):
            continue
        turns += int(budget.get("turns") or 0)
        tokens += int(budget.get("tokens") or 0)
        elapsed += int(budget.get("elapsed_ms") or 0)
    return {"runs": runs, "turns": turns, "tokens": tokens, "elapsed_ms": elapsed}


def _node_plan_ids(state: ObjectiveState) -> set[str]:
    """The objective's ``#``-stripped node plan backlinks (``node.pr``) — the run→objective
    correlation keys (a dispatched node plan always has its backlink: dispatch happens after
    plan save)."""
    ids = {str(n.pr).lstrip("#").strip() for n in state.nodes if n.pr}
    ids.discard("")
    return ids


def _in_flight_record(
    repo_root: Path, number: str, plan_ids: set[str]
) -> tuple[str, runner.RunHandle, runner.Runner] | None:
    """The newest in-flight remote run for this objective, or ``None``.

    Discovery-first (contracts.md §8.20): one canonical GHA enumeration — so the gate works from
    a fresh clone — keeping ``queued``/``in_progress`` runs whose parsed plan id matches one of
    this objective's node backlinks. A discovery error degrades fail-soft (one stderr note) into
    the legacy local-record loop, preserving the offline behavior.
    """
    try:
        discovered = discovery.discover_runs(repo_root, limit=100)
    except (runner.RunnerError, GitHubError) as exc:
        user_output(f"note: run discovery unavailable: {exc}")
        return _in_flight_record_local(repo_root, number)
    for run in discovered:  # newest-first
        if run.status not in {"queued", "in_progress"}:
            continue
        if run.plan_id.lstrip("#") not in plan_ids:
            continue
        return run.run_id, run.handle, runner.select_runner(run.handle.runner)
    return None


def _in_flight_record_local(
    repo_root: Path, number: str
) -> tuple[str, runner.RunHandle, runner.Runner] | None:
    """The legacy local-record gate (the discovery-error fallback): the newest local dispatch
    record for this objective whose ``run_handle`` is present and whose live ``observe`` returns
    ``queued``/``in_progress``. Each observe is fail-soft — a runner/GitHub error treats that
    record as not-in-flight (noted to stderr), never raises.
    """
    target = number
    for record in cache.list_dispatch_records(repo_root):  # newest-first
        if _canon_objective(record.plan_ref.objective_id) != target:
            continue
        handle = record.run_handle
        if handle is None:
            continue
        runner_obj = runner.select_runner(record.runner)
        try:
            obs = runner_obj.observe(handle, repo_root=repo_root)
        except (runner.RunnerError, GitHubError) as exc:
            user_output(f"note: run state unavailable for {record.run_id}: {exc}")
            continue
        if obs.status in {"queued", "in_progress"}:
            return record.run_id, handle, runner_obj
    return None


def _poll_to_completion(
    handle: runner.RunHandle,
    runner_obj: runner.Runner,
    repo_root: Path,
    *,
    sleep: Any = None,
) -> runner.RunObservation | None:
    """Poll a run to completion. ``None`` on timeout (inconclusive) or a fail-soft observe."""
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


def _stage_by_id(stage_id: str) -> Stage:
    """The registry stage by id (``implement``/``address`` only here — guarded in the caller)."""
    for stage in load_registry().stages:
        if stage.id == stage_id:
            return stage
    raise UserFacingCliError(f"unknown stage '{stage_id}'", error_type="dispatch_failed")


def _parse_run_id(captured: str) -> str | None:
    """Extract the ``run_id`` from launch_stage's captured machine-output JSON."""
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
    node_plan_state: issue_backend.PlanState,
    remote: str,
    dry_run: bool,
) -> str | None:
    """Dispatch ``implement``/``address`` to the remote runner for an in-flight node.

    Reconstructs the node's plan-ref (preserving ``objective_id`` so the eventual human land
    reconciles the node) and passes it **directly** into ``launch_stage`` (the dispatch never
    re-reads the mutable selector), updating the **main-root** selector as a convenience —
    capturing the machine output so the supervisor surfaces a single unified ``--json``
    payload. Returns the minted ``run_id``. Under ``--dry-run`` this performs no write/trigger
    and returns ``None``.
    """
    stage = _stage_by_id(stage_id)
    Ensure.invariant(
        stage.doors.get("cold_remote") is True,
        f"stage '{stage_id}' is not remote-drivable (cold_remote:false)",
    )
    plan_ref = resume.reconstruct_plan_ref(
        node_plan_state, provider=resolve.resolve_issue_backend_id(repo_root)
    )
    if dry_run:
        return None
    # `repo_root` is already the main root (normalized once in `_run_impl`).
    cache.write_plan_ref(main_repo_root(repo_root), plan_ref)
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
            plan_ref=plan_ref,
        )
    return _parse_run_id(buf.getvalue())


def _resolve_in_flight_stage(
    payload: dict[str, Any],
    *,
    repo_root: Path,
    config: Config,
    number: str,
    node: objective.ObjectiveNode,
    remote: str,
    dry_run: bool,
) -> dict[str, Any]:
    """Resolve the action for an in-flight node via the shared classifier (contracts.md §8.37).

    Delegates classification to ``resume.resolve_next_action`` and maps the verdict onto the
    supervisor's ``action`` vocabulary: ``implement``/``address`` dispatch remotely;
    ``learn``/``done`` both surface as ``merged_pending_reconcile`` (learn is local-only — the
    learn-pending nuance rides on ``next_action`` + a ``perk plan resume`` remediation); the
    remaining gate verdicts pass through verbatim. A draft PR means implement is **complete** —
    never re-dispatch implement from a draft.
    """
    remediation = f"perk objective plan {number} --node {node.id}"
    # The node's `pr` backlink carries the PLAN id — an opaque string (GitHub "42", Linear
    # "ENG-123"; contracts §8.21): any non-empty value IS the plan id (the resolved backend is
    # the authority on whether it exists). Only the empty/missing case falls through to the
    # plan_required fallback below.
    plan_id = str(node.pr).lstrip("#").strip() if node.pr else ""
    backend = resolve.resolve_issue_backend(repo_root)
    plan_state = backend.get_plan(issue_id=plan_id) if plan_id else None
    if plan_state is None:  # defensive: an in-flight node should carry a resolvable plan
        payload.update(action="plan_required", node=node.id, remediation=remediation)
        return payload

    verdict = resume.resolve_next_action(
        plan_state,
        has_pending_learn=cache.has_marker(repo_root, cache.PENDING_LEARN),
        get_feedback=lambda n: github.get_pr_feedback(pr_number=n, repo_root=repo_root),
    )
    payload["next_action"] = verdict.value
    stage_id = verdict.stage_id
    if stage_id in ("implement", "address"):  # the cold_remote:true stages — dispatchable
        run_id_val = _dispatch_stage_remote(
            repo_root=repo_root,
            config=config,
            stage_id=stage_id,
            node_plan_state=plan_state,
            remote=remote,
            dry_run=dry_run,
        )
        payload.update(action="dispatched", node=node.id, stage=stage_id, run_id=run_id_val)
        return payload
    pr = Ensure.not_none(plan_state.pr, "non-implement verdict with no PR — this is a bug")
    if verdict in (resume.NextAction.LEARN, resume.NextAction.DONE):
        # The done transition is pending the human land's reconcile. Learn is local-only (never
        # remote-dispatched): name the pending learn + the local remediation, and stop.
        payload.update(action="merged_pending_reconcile", node=node.id, pr=pr.number)
        if verdict is resume.NextAction.LEARN:
            payload["remediation"] = f"perk plan resume {plan_id}"
        return payload
    # ready_for_review / awaiting_review / pr_closed: the verdict IS the supervisor action.
    payload.update(action=verdict.value, node=node.id, pr=pr.number)
    return payload


def _run_impl(
    ctx: click.Context, *, number: str, remote: str, wait: bool, dry_run: bool
) -> dict[str, Any]:
    """The deterministic single-pass control flow. Returns the structured payload to render;
    raises ``UserFacingCliError``/``IssueBackendError``/``GitHubError`` for the command's ``fail``
    boundary."""
    # Two-roots rule: the supervisor's config, canonical reads, dispatch records, and selector
    # writes all anchor to the MAIN checkout — invoking from inside a linked worktree must not
    # fork its state (objective run has no worktree-local fallback read).
    repo_root = main_repo_root(require_repo(ctx))
    config = load_main_config(repo_root)
    if not dry_run:
        require_github(ctx)
    store = resolve.resolve_objective_store(repo_root)
    state = store.get_objective(objective_id=number)
    if state is None:
        raise UserFacingCliError(f"Objective #{number} not found", error_type="objective_not_found")
    graph = objective.build_graph(list(state.nodes))
    payload: dict[str, Any] = {
        "success": True,
        "error_type": None,
        "objective": number,
        "budget": _cumulative_budget(repo_root, number),
        "action": None,
        "next_action": None,
        "node": None,
        "stage": None,
        "run_id": None,
        "remediation": None,
        "closed": False,
        "timed_out": False,
        "dry_run": dry_run,
    }

    # Active-run gate. Skipped under --dry-run to stay fully offline-safe.
    if not dry_run:
        in_flight = _in_flight_record(repo_root, number, _node_plan_ids(state))
        if in_flight is not None:
            run_id_val, handle, runner_obj = in_flight
            if not wait:
                payload.update(action="awaiting_run", run_id=run_id_val)
                return payload
            completed = _poll_to_completion(handle, runner_obj, repo_root)
            if completed is None:
                payload.update(action="awaiting_run", run_id=run_id_val, timed_out=True)
                return payload
            # Re-evaluate against FRESH state after the run settled: the just-completed run may have
            # advanced GitHub (a new PR, updated budget), so re-fetch the objective + rebuild the
            # graph rather than classifying on the pre-poll snapshot.
            payload["budget"] = _cumulative_budget(repo_root, number)
            state = store.get_objective(objective_id=number)
            if state is None:
                raise UserFacingCliError(
                    f"Objective #{number} not found", error_type="objective_not_found"
                )
            graph = objective.build_graph(list(state.nodes))

    # Stacked objectives consult the readiness-derived selection (contracts.md §8.46) instead
    # of the dep-terminal graph gating. Skipped under --dry-run (the dry run keeps the
    # offline graph classification; a live train reconstruction is a network read) — and the
    # dry-run payload SAYS so (stacked only) rather than pretending the check ran.
    if dry_run:
        try:
            policy = objective.delivery_policy(state.header)
        except ValueError as exc:
            raise UserFacingCliError(str(exc), error_type="invalid_delivery_policy") from exc
        if policy is objective.DeliveryPolicy.STACKED:
            payload["build_readiness"] = "unchecked (dry-run)"
    stacked = None if dry_run else stacked_selection(repo_root, state)
    if stacked is not None:
        veto = classify_stacked_veto(stacked, number)
        if veto is not None:
            payload.update(
                action=veto.action,
                reason=veto.reason,
                remediation=veto.remediation,
            )
            return payload
        if stacked.kind == "build_blocked":
            payload.update(
                action="build_blocked",
                reason=stacked.reason,
                remediation=f"perk objective stack status {number}",
            )
            return payload
        if stacked.train is not None:
            backend = resolve.resolve_issue_backend(repo_root)
            lower = stacked_lower_attention(
                repo_root,
                stacked.train,
                state,
                get_plan=lambda plan_id: backend.get_plan(issue_id=plan_id),
                get_feedback=lambda number: github.get_pr_feedback(
                    pr_number=number, repo_root=repo_root
                ),
                has_pending_learn=cache.has_marker(repo_root, cache.PENDING_LEARN),
            )
            if lower is not None:
                run_id_val = _dispatch_stage_remote(
                    repo_root=repo_root,
                    config=config,
                    stage_id="address",
                    node_plan_state=lower.plan,
                    remote=remote,
                    dry_run=dry_run,
                )
                payload.update(
                    action="dispatched",
                    node=lower.node.id,
                    stage="address",
                    next_action="address",
                    run_id=run_id_val,
                )
                return payload
        if stacked.kind == "plannable" and stacked.node is not None:
            node = stacked.node
            payload.update(
                action="plan_required",
                node=node.id,
                remediation=f"perk objective plan {number} --node {node.id}",
            )
            return payload
        if stacked.kind == "in_flight" and stacked.node is not None:
            return _resolve_in_flight_stage(
                payload,
                repo_root=repo_root,
                config=config,
                number=number,
                node=stacked.node,
                remote=remote,
                dry_run=dry_run,
            )
        # `no_candidate` (every layer published) falls through to the existing graph
        # classification — completion semantics unchanged.

    selection = graph.classify_for_planning()
    if selection.kind == "complete":
        # Close through the OBJECTIVE STORE (each backend retires its own entity: GitHub closes
        # the issue, Linear marks the Project complete) — not the issue tier (a Project is not an
        # issue).
        closed = store.close_objective(objective_id=number, dry_run=dry_run)
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
            remediation=f"perk objective plan {number} --node {node.id}",
        )
        return payload
    # in_flight
    in_flight_node = Ensure.not_none(selection.node, "in_flight selection must carry a node")
    return _resolve_in_flight_stage(
        payload,
        repo_root=repo_root,
        config=config,
        number=number,
        node=in_flight_node,
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
    elif action == "build_blocked":
        user_output(
            f"build blocked — {payload.get('reason')} (check: {payload.get('remediation')})"
        )
    elif action == "repair_required":
        user_output(
            f"repair required — {payload.get('reason')} (run: {payload.get('remediation')})"
        )
    elif action == "completed":
        for row in payload.get("audit", []):
            user_output(f"  {row['node']} → {row['status']} → {row['pr'] or '—'}")
        verb = "closed" if payload.get("closed") else "would close (dry-run)"
        user_output(click.style("✓ ", fg="green") + f"objective complete — {verb}")
    elif action == "merged_pending_reconcile":
        if payload.get("next_action") == "learn":
            user_output(
                f"node {node} (PR #{pr}): merged — learn pending "
                f"(run: {payload.get('remediation')}); node→done pending the land reconcile"
            )
        else:
            user_output(f"node {node} (PR #{pr}): merged — node→done pending the land reconcile")
    elif action == "pr_closed":
        user_output(f"node {node} (PR #{pr}): PR closed unmerged — needs human attention")
    if as_json:
        machine_output(json.dumps(payload))


@alias("r")
@click.command("run")
@click.argument("number")
@click.option(
    "--remote",
    default="",
    help="Runner ref for remote dispatches (default: the default runner).",
)
@click.option("--wait", is_flag=True, help="Poll an in-flight run to completion, then re-evaluate.")
@click.option(
    "--dry-run",
    is_flag=True,
    help="Resolve + report the decision only — mint/write/trigger/close nothing.",
)
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def run_objective(
    ctx: click.Context, *, number: str, remote: str, wait: bool, dry_run: bool, as_json: bool
) -> None:
    """Advance an objective's backlog one autonomously-safe step, then pause at the human gate."""
    try:
        payload = _run_impl(
            ctx, number=parse_objective_id(number), remote=remote, wait=wait, dry_run=dry_run
        )
    except (GitHubError, IssueBackendError, ObjectiveStoreError) as exc:
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
    _render_run(payload, as_json=as_json)
