"""``perk pr ready [PLAN]`` (the worker) + ``perk ready [PLAN]`` (the continuation wrapper).

For an **incremental** plan the ready gesture is the review gate: perk deliberately does NOT
auto-publish on submit (the PR stays draft), and `/ready` is the explicit gesture that opens
the PR for review. For a **stacked** layer it is the deliberate post-review HUMAN handoff:
review happens on the draft layer PR, and after review + address the human runs ready to record
the handoff stamp at the exact verified published head — on draft AND non-draft PRs alike
(mark-ready mechanics first, then the journal append). It is never routine post-submit
choreography and never auto-run. The optional positional ``PLAN`` selects
the plan canonically (one backend read via ``perk.cli.plan_selection.select_plan``) — ready
needs no source files, so `perk pr ready 42` works from the repository root without requiring
or creating a worktree; the no-argument form keeps reading the invoking checkout's own
``cache.plan-ref`` (inside a plan worktree, that worktree's binding). The command derives only the
selected plan id, delivery mode, and stacked objective id; ``Delivery.publish`` owns incremental
and stacked ready mechanics. An already-ready stacked PR still validates the target but
skips mutation-only vetoes — and still stamps. A failed/ambiguous stamp append exits nonzero
with ``error_type: ready_stamp_failed`` while the envelope reports the truthful ``pr`` and
``was_draft``; the ambiguous/transient arms converge on an idempotent re-run (the deterministic
stamp key), deterministic failures name their own remediation.

Two spellings, one worker (contracts.md §8.66): ``perk pr ready`` is the deterministic,
non-launching **worker** — it never starts the ready-time reconcile pass; the envelope's
``reconcile_notice``/``reconcile_retry`` say so. ``perk ready`` is the **continuation wrapper**:
the exact worker mechanics first, then — on a successful stacked stamp in an interactive
terminal (stdin AND stdout TTYs; never on ``--json``/``--dry-run``) — it launches the seeded
ready-time reconcile session through the borrowed ``objective-save`` stage descriptor. A launch
failure after a successful stamp is the second reported outcome: loud stderr, exit 1, the stamp
stands, and re-running ``perk ready PLAN`` retries the pass.

Exit codes: 0 ready · 1 no saved plan / plan not found / no PR / op or launch failure ·
2 not-a-repo.
"""

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

import click

from perk import delivery, github
from perk.backends import resolve
from perk.backends.issue_backend import IssueBackendError
from perk.boundary import OutputModel
from perk.cli import completions
from perk.cli.commands.objective.shared import objective_read_instruction
from perk.cli.context import require_github, require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.cli.plan_selection import (
    SelectedPlan,
    load_main_config,
    main_repo_root,
    parse_plan_id,
    select_plan,
)
from perk.delivery import journal
from perk.github import GitHubError
from perk.prompts import render
from perk.run import launch
from perk.state import cache
from perk.substrate import registry
from perk.substrate.config import Config
from perk.substrate.output import user_output


@dataclass(frozen=True)
class PrReadyResult:
    """The thin command-level carrier around the façade's ready detail.

    ``stacked`` is the command's own routing decision (``None`` on the offline dry run, which
    classifies nothing); the continuation facts are derived from ``ready.stamp`` at the
    serialization boundary only.
    """

    ready: delivery.PublishResult.Ready
    plan_id: str
    stacked: bool | None
    dry_run: bool


@click.command("ready")
@click.argument("plan", required=False, shell_complete=completions.complete_plan_id)
@click.option(
    "--dry-run",
    is_flag=True,
    help=(
        "Offline selection-validation preview: PLAN is parse-checked and the no-argument form "
        "confirms a saved plan exists — no backend or GitHub read, no delivery classification, "
        "so it cannot predict which arm a real run would take. Nothing is resolved, marked, or "
        "stamped; a real run marks the draft PR ready (incremental) or records the post-review "
        "handoff stamp (stacked)."
    ),
)
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def ready_pr(ctx: click.Context, *, plan: str | None, dry_run: bool, as_json: bool) -> None:
    """Ready a plan's PR: the review gate (incremental) or the handoff stamp (stacked).

    \b
    Incremental plans: mark the draft PR ready for review — the deliberate review gate
    (submit keeps the PR draft on purpose). Stacked layers: the deliberate POST-review human
    handoff — review happens on the draft layer PR, and after review + address this gesture
    stamps the exact verified published head into the delivery journal (draft AND non-draft
    PRs; mark-ready first, then the append); the recorded stamp unblocks planning of the
    layer's direct dependents. Never routine post-submit choreography; never auto-run.
    A failed stamp exits 1 as ready_stamp_failed with the truthful pr/was_draft;
    an ambiguous/transient append converges on an idempotent re-run.

    \b
    PLAN is an optional plan issue id (e.g. 42, #42, ENG-123, or the pasted issue URL): pass it
    to select the plan canonically (works from the repository root — ready needs no worktree);
    omit it to read the invoking checkout's own cache.plan-ref (inside a plan worktree, that
    worktree's binding). Typed failures (no_plan_ref, plan_not_found, issue_kind_mismatch,
    no_pr, invalid_input) exit 1. Note: --dry-run performs no backend read, so the offline
    preview classifies nothing (kind included).
    """
    try:
        _repo_root, result = _execute_ready(ctx, plan=plan, dry_run=dry_run)
    except (delivery.DeliveryError, GitHubError, IssueBackendError, UserFacingCliError) as exc:
        _fail_ready(ctx, exc, as_json=as_json)
    # Emission ownership: the command emits itself, after its tail is decided — the worker's
    # tail is always the truthful not-launched notice.
    emit(
        as_json=as_json,
        payload=_result_to_dict(result),
        render=lambda: _render_human(result, reconcile_tail=_worker_tail(result.plan_id)),
    )


def _execute_ready(
    ctx: click.Context, *, plan: str | None, dry_run: bool
) -> tuple[Path, "PrReadyResult"]:
    """The shared selection/``require_github`` preamble + the pure execution seam.

    Returns ``(invocation_root, result)``; every failure propagates to the caller's
    :func:`_fail_ready` (which exits with the worker envelope).
    """
    repo_root = require_repo(ctx)
    selected: SelectedPlan | None = None
    explicit_plan_id: str | None = None
    if plan is not None:
        explicit_plan_id = parse_plan_id(plan)
    if not dry_run:
        require_github(ctx)
        if plan is not None:
            # One canonical read: the selection's fetched state replaces the command's own
            # plan re-read below (stacked train reconstruction keeps its per-layer reads).
            selected = select_plan(main_repo_root(repo_root), plan)
    result = _pr_ready_impl(
        repo_root=repo_root,
        dry_run=dry_run,
        selected=selected,
        explicit_plan_id=explicit_plan_id,
    )
    return repo_root, result


def _fail_ready(
    ctx: click.Context,
    exc: delivery.DeliveryError | GitHubError | IssueBackendError | UserFacingCliError,
    *,
    as_json: bool,
) -> NoReturn:
    """The one worker-envelope failure mapping both spellings share.

    Every arm delegates to :func:`fail`, which emits the envelope and calls ``ctx.exit`` —
    failure paths EXIT here, they never return (contracts.md §8.66).
    """
    if isinstance(exc, delivery.ReadyStampError):
        # The stamp-specific failure envelope: the gesture may already have flipped the PR, so
        # the truthful PR facts always ride along (contracts.md §8.43).
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type,
            message=str(exc),
            extra={
                "pr": {"number": exc.pr.number, "url": exc.pr.url},
                "was_draft": exc.was_draft,
                "dry_run": False,
            },
        )
    elif isinstance(exc, delivery.DeliveryError):
        message = str(exc) if exc.origin == "domain" else f"pr ready failed\n{exc}"
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type,
            message=message,
            extra={"dry_run": False},
        )
    elif isinstance(exc, GitHubError | IssueBackendError):
        fail(
            ctx,
            as_json=as_json,
            error_type="github_error",
            message=f"pr ready failed\n{exc}",
            extra={"dry_run": False},
        )
    else:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
            extra={"dry_run": False},
        )
    raise AssertionError("unreachable: fail() always exits")


def _no_plan_ref_error() -> UserFacingCliError:
    return UserFacingCliError(
        "No saved plan in this worktree\nRun /plan-save then perk implement first.",
        error_type="no_plan_ref",
    )


def _pr_ready_impl(
    *,
    repo_root: Path,
    dry_run: bool,
    selected: SelectedPlan | None = None,
    explicit_plan_id: str | None = None,
) -> PrReadyResult:
    """Select one plan in the CLI, then delegate ready mechanics to Delivery.publish."""
    stacked: bool | None = None
    if dry_run:
        plan_id = explicit_plan_id
        if plan_id is None:
            plan_ref = cache.read_plan_ref(repo_root)
            if plan_ref is None:
                raise _no_plan_ref_error()
            plan_id = plan_ref.pr_id
        published = delivery.resolve_delivery(repo_root).publish(
            delivery.PublishRequest(kind="ready", plan_id=plan_id, dry_run=True)
        )
    else:
        if selected is not None:
            plan_ref = selected.ref
            state = selected.state
        else:
            plan_ref = cache.read_plan_ref(repo_root)
            if plan_ref is None:
                raise _no_plan_ref_error()
            backend = resolve.resolve_issue_backend(repo_root)
            fetched = backend.get_plan(issue_id=plan_ref.pr_id)
            if fetched is None:
                raise UserFacingCliError(
                    f"Plan issue #{plan_ref.pr_id} not found", error_type="plan_not_found"
                )
            state = fetched
        header_lineage = state.header.get("delivery_lineage")
        stacked = plan_ref.delivery_lineage is not None or (
            isinstance(header_lineage, str) and bool(header_lineage.strip())
        )
        raw_objective = state.header.get("objective_id")
        objective_id = (
            raw_objective.strip()
            if stacked and isinstance(raw_objective, str) and raw_objective.strip()
            else None
        )
        published = delivery.resolve_delivery(repo_root).publish(
            delivery.PublishRequest(
                kind="ready",
                plan_id=plan_ref.pr_id,
                delivery="stacked" if stacked else "incremental",
                objective_id=objective_id,
            )
        )
    detail = published.ready
    if detail is None:
        raise ValueError("ready publish returned no ready detail")
    return PrReadyResult(
        ready=detail,
        plan_id=published.plan_id,
        stacked=stacked,
        dry_run=published.dry_run,
    )


class ReadyPrOut(OutputModel):
    """The serialization boundary of the picked :class:`github.PullRequest` subset
    (field order load-bearing)."""

    number: int
    url: str

    @classmethod
    def from_domain(cls, pr: github.PullRequest) -> "ReadyPrOut":
        return cls(number=pr.number, url=pr.url)


def _reconcile_notice() -> str:
    return (
        "the ready-time reconcile pass was not launched — perk pr ready is the deterministic, "
        "non-launching worker; run perk ready <plan> in an interactive terminal to launch it"
    )


def _reconcile_retry(plan_id: str) -> str:
    return f"perk ready {plan_id}"


def _worker_tail(plan_id: str) -> str:
    """The truthful not-launched human tail (rendered only when a stamp exists)."""
    return f"{_reconcile_notice()}; re-run: {_reconcile_retry(plan_id)}"


class PrReadyOut(OutputModel):
    """The ``--json`` serialization boundary of :class:`PrReadyResult` (order load-bearing —
    the nine continuation fields are tail-additive).

    Null semantics: dry-run → all nine continuation fields null; incremental →
    ``stacked=false``, rest null; stacked success → all populated (``reconcile_notice`` /
    ``reconcile_retry`` are CLI-composed presentation: the ready-time reconcile pass was not
    launched — the worker never launches — plus the copyable re-run gesture; ``plan`` /
    ``parent_checkpoint`` are the continuation evidence consumers compose the pinned diff
    range from, contracts.md §8.66).
    """

    success: bool
    error_type: str | None
    message: str | None
    pr: ReadyPrOut
    was_draft: bool
    dry_run: bool
    stacked: bool | None
    objective: str | None
    node: str | None
    stamped_head: str | None
    stamp_advanced: bool | None
    reconcile_notice: str | None
    reconcile_retry: str | None
    plan: str | None
    parent_checkpoint: str | None

    @classmethod
    def from_domain(cls, result: PrReadyResult) -> "PrReadyOut":
        stamp = result.ready.stamp
        return cls(
            success=True,
            error_type=None,
            message=None,
            pr=ReadyPrOut.from_domain(result.ready.pr),
            was_draft=result.ready.was_draft,
            dry_run=result.dry_run,
            stacked=result.stacked,
            objective=stamp.record.objective_id if stamp is not None else None,
            node=stamp.record.node_id if stamp is not None else None,
            stamped_head=stamp.record.head_sha if stamp is not None else None,
            stamp_advanced=(not stamp.existed) if stamp is not None else None,
            reconcile_notice=_reconcile_notice() if stamp is not None else None,
            reconcile_retry=_reconcile_retry(result.plan_id) if stamp is not None else None,
            plan=result.plan_id if stamp is not None else None,
            parent_checkpoint=stamp.parent_checkpoint_sha if stamp is not None else None,
        )


def _result_to_dict(result: PrReadyResult) -> dict[str, object]:
    return PrReadyOut.from_domain(result).model_dump(mode="json")


def _render_human(result: PrReadyResult, *, reconcile_tail: str | None) -> None:
    """The shared human render; ``reconcile_tail`` is the caller-decided continuation line
    (the worker's truthful not-launched notice, or the wrapper's launching line) — rendered
    only when a stamp exists."""
    if result.dry_run:
        user_output(click.style("pr ready --dry-run (no GitHub writes)", dim=True))
        # The offline preview validates selection only — it performs no delivery
        # classification, so it cannot claim which arm a real run would take.
        user_output("  validated the plan selection offline (nothing resolved or classified)")
        user_output(
            "  a real run would: mark the draft PR ready for review (incremental) or record "
            "the post-review handoff stamp (stacked)"
        )
        return
    verb = "Marked ready" if result.ready.was_draft else "Already ready"
    user_output(
        click.style("✓ ", fg="green")
        + f"{verb}: PR "
        + click.style(f"#{result.ready.pr.number}", fg="cyan")
        + " is open for review"
    )
    stamp = result.ready.stamp
    if stamp is None:
        return
    stamped = "Handoff stamped" if not stamp.existed else "Handoff already stamped"
    user_output(
        f"  {stamped}: objective #{stamp.record.objective_id} node {stamp.record.node_id} "
        f"at {stamp.record.head_sha}"
    )
    if reconcile_tail is not None:
        user_output(f"  {reconcile_tail}")


# ----------------------------------------------------------- the continuation wrapper (§8.66)


@dataclass(frozen=True)
class _ReadyLaunch:
    """Everything the reconcile launch needs, resolved BEFORE anything is emitted."""

    main_root: Path
    config: Config
    stage: registry.Stage
    seed: str


def _resolve_reconcile_launch(invocation_root: Path, result: PrReadyResult) -> _ReadyLaunch:
    """Resolve the pinned launch contract (contracts.md §8.66) for one stamped ready result.

    The continuation boundary's exact-SHA validation lives here: the stamp record's
    ``head_sha`` is already record-validated, but the stored ``parent_checkpoint_sha`` is
    presence-invariant only — BOTH range endpoints must be full 40-hex lowercase before they
    interpolate into the seed. Raises :class:`UserFacingCliError` on any refusal; resolution
    failures of any kind route to the caller's second-outcome degrade.
    """
    stamp = result.ready.stamp
    if stamp is None:
        raise UserFacingCliError("the launching arm requires a recorded stamp")
    record = stamp.record
    for what, value in (
        ("stamped head", record.head_sha),
        ("parent checkpoint", stamp.parent_checkpoint_sha),
    ):
        if not journal.is_full_head_sha(value):
            raise UserFacingCliError(
                f"the verified layer's {what} is not a full 40-hex lowercase object id: "
                f"{value!r} — the pinned diff range cannot be composed"
            )
    main_root = main_repo_root(invocation_root)
    config = load_main_config(main_root)
    # The borrowed write-capable launch descriptor (`mode: read-write`, `worktree: none` —
    # cwd = the invoking checkout; no plan worktree required or restored).
    stage = registry.stage_by_id("objective-save")
    read_clause = objective_read_instruction(
        resolve.resolve_issue_backend_id(main_root), record.objective_id, ""
    )
    seed = render(
        "stages/objective-reconcile-ready.md",
        {
            "objective": record.objective_id,
            "node": record.node_id,
            "plan": result.plan_id,
            "pr": str(result.ready.pr.number),
            "parent_checkpoint": stamp.parent_checkpoint_sha,
            "stamped_head": record.head_sha,
            "read_clause": read_clause,
        },
    )
    return _ReadyLaunch(main_root=main_root, config=config, stage=stage, seed=seed)


def _second_outcome_exit(ctx: click.Context, plan_id: str, exc: Exception) -> NoReturn:
    """The second reported outcome: the stamp stands; the launch did not — loud, exit 1."""
    user_output(
        click.style("Error: ", fg="red")
        + f"the ready-time reconcile session was not launched — {exc}\n"
        + "The handoff stamp already stands (nothing was rolled back); "
        + f"re-run to retry the pass: {_reconcile_retry(plan_id)}"
    )
    ctx.exit(1)
    raise AssertionError("unreachable: ctx.exit always raises")


@click.command("ready")
@click.argument("plan", required=False, shell_complete=completions.complete_plan_id)
@click.option(
    "--dry-run",
    is_flag=True,
    help=(
        "Offline selection-validation preview: PLAN is parse-checked and the no-argument form "
        "confirms a saved plan exists — no backend or GitHub read, no delivery classification, "
        "no launch. Nothing is resolved, marked, or stamped."
    ),
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Emit the worker's machine-readable report to stdout (never launches).",
)
@click.pass_context
def ready_continuation(
    ctx: click.Context, *, plan: str | None, dry_run: bool, as_json: bool
) -> None:
    """Ready a plan's PR, then continue into the ready-time reconcile pass.

    \b
    The continuation wrapper around the deterministic worker (`perk pr ready`): it runs the
    exact worker mechanics first — the review gate (incremental) or the post-review handoff
    stamp (stacked) — then, on a successful stacked stamp in an interactive terminal, launches
    the seeded ready-time reconcile session against the accepted layer's pinned diff range
    (re-stamps re-enter the pass). --json, --dry-run, and non-TTY invocations never launch:
    they emit exactly the worker's envelope/output (continuation facts, never a session).
    A launch failure after a successful stamp exits 1 — the stamp stands; re-run
    `perk ready PLAN` to retry the pass.

    \b
    PLAN is an optional plan issue id (e.g. 42, #42, ENG-123, or the pasted issue URL): pass it
    to select the plan canonically (works from the repository root — ready needs no worktree);
    omit it to read the invoking checkout's own cache.plan-ref (inside a plan worktree, that
    worktree's binding). Failure envelopes and exit codes match the worker exactly.
    """
    try:
        repo_root, result = _execute_ready(ctx, plan=plan, dry_run=dry_run)
    except (delivery.DeliveryError, GitHubError, IssueBackendError, UserFacingCliError) as exc:
        _fail_ready(ctx, exc, as_json=as_json)
    stamp = result.ready.stamp
    launching = (
        not as_json
        and not dry_run
        and result.stacked is True
        and stamp is not None
        # The launch execs the full-screen pi TUI — both ends must be terminals.
        and sys.stdin.isatty()
        and sys.stdout.isatty()
    )
    if not launching:
        # Continuation facts, never a session: byte-equal to the worker (envelope AND human
        # output, truthful not-launched tail included).
        emit(
            as_json=as_json,
            payload=_result_to_dict(result),
            render=lambda: _render_human(result, reconcile_tail=_worker_tail(result.plan_id)),
        )
        return
    # Launching arm — resolve BEFORE emitting: nothing prints until the launch is composable.
    try:
        prepared = _resolve_reconcile_launch(repo_root, result)
    except Exception as exc:  # the deliberate second-outcome degrade boundary: the stamp
        # already stands, so ANY resolution failure downgrades to the worker's truthful
        # output + a loud stderr line (BaseException/click's own exit exceptions pass through).
        emit(
            as_json=False,
            payload=_result_to_dict(result),
            render=lambda: _render_human(result, reconcile_tail=_worker_tail(result.plan_id)),
        )
        _second_outcome_exit(ctx, result.plan_id, exc)
    emit(
        as_json=False,
        payload=_result_to_dict(result),
        render=lambda: _render_human(
            result, reconcile_tail="launching the ready-time reconcile session…"
        ),
    )
    try:
        # Module-object call (the monkeypatch seam); on success the process execs pi.
        launch.launch_stage(
            repo_root=prepared.main_root,
            config=prepared.config,
            stage=prepared.stage,
            worktree=None,
            dry_run=False,
            remote=None,
            pi_args=[],
            prompt_override=prepared.seed,
            # The learn-docs override precedent: the borrowed stage must not fire
            # `stage:objective-save`; the pass's bindings ride the reconcile trigger.
            binding_trigger="command:objective-reconcile",
        )
    except Exception as exc:  # the deliberate second-outcome degrade boundary (see above):
        # the stamp already stands; BaseException/click's own exit exceptions pass through.
        _second_outcome_exit(ctx, result.plan_id, exc)
