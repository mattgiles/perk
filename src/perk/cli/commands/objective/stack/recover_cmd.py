"""``perk objective stack recover`` — the conclude-only recovery worker (contracts.md §8.51).

The cold surface over ``Delivery.recover``: classify every
unresolved stack operation, conclude the one selected target (automatic
SYNC/ADOPT/TRANSFER/LAND all-after roll-forward; confirmed ``--abandon`` with proof;
confirmed ``--accept-prefix`` recording an externally merged LAND prefix as a breach), run
the LAND finalization-convergence pass, then sweep orphaned machine-local sync residue.
Retry is never recover's verb — the report's detail routes to the owning command.
``--dry-run`` reports everything and mutates nothing. No ``--run-id``: conclude-only
recovery needs no run identity. Exit 0 = successful classification/report/no-op/actions
(including declined and ``selection_required``); 1 = typed refusals + infra failures; 2 =
not-a-repo.
"""

import click

from perk.boundary import OutputModel
from perk.cli.commands.objective.stack.land_cmd import ReconcileEvidenceOut
from perk.cli.commands.objective.stack.shared import resolve_objective_id
from perk.cli.commands.objective.stack.status_cmd import ObjectiveOut
from perk.cli.context import require_config, require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.delivery import DeliveryError, RecoverRequest, RecoverResult, resolve_delivery
from perk.substrate.output import user_output

# --- the ``--json`` envelope (OutputModel family; declaration order load-bearing) ---


class MergedPrefixOut(OutputModel):
    """One externally merged prefix layer (the ``external_prefix`` structured preview)."""

    node_id: str
    pr_number: int
    merge_commit_sha: str


class RemainderPrOut(OutputModel):
    """One remainder PR observed OPEN at its recorded head (the acceptance proof)."""

    pr_number: int
    state: str
    head_sha: str


class RecoverOperationOut(OutputModel):
    operation_id: str
    kind: str
    prepared_created: str
    classification: str  # all_before | all_after | external_prefix | in_flight | mixed
    # | unsupported
    action: str  # reported | rolled_forward | abandoned | accepted_prefix | declined
    detail: str
    # Declared last: the ``external_prefix`` structured preview — additive envelope growth
    # (contracts.md §8.51); empty on every other row.
    merged_layers: tuple[MergedPrefixOut, ...] = ()
    remainder: tuple[RemainderPrOut, ...] = ()

    @classmethod
    def from_domain(cls, row: RecoverResult.Operation) -> "RecoverOperationOut":
        return cls(
            operation_id=row.operation_id,
            kind=row.kind,
            prepared_created=row.prepared_created,
            classification=row.classification,
            action=row.action,
            detail=row.detail,
            merged_layers=tuple(
                MergedPrefixOut(
                    node_id=r.node_id, pr_number=r.pr_number, merge_commit_sha=r.merge_commit_sha
                )
                for r in row.merged_layers
            ),
            remainder=tuple(
                RemainderPrOut(pr_number=r.pr_number, state=r.state, head_sha=r.head_sha)
                for r in row.remainder
            ),
        )


class RecoverLandedLayerOut(OutputModel):
    """One landed layer this invocation acted on (a LAND conclusion's finalize or the
    convergence pass). ``finalized: null`` is a dry-run would-act row (not attempted)."""

    node_id: str
    plan_id: str
    pr_number: int
    merge_commit_sha: str
    base_sha: str
    head_sha: str
    finalized: bool | None

    @classmethod
    def from_domain(cls, row: RecoverResult.LandedLayer) -> "RecoverLandedLayerOut":
        return cls(
            node_id=row.node_id,
            plan_id=row.plan_id,
            pr_number=row.pr_number,
            merge_commit_sha=row.merge_commit_sha,
            base_sha=row.base_sha,
            head_sha=row.head_sha,
            finalized=row.finalized,
        )


class SweepFailureOut(OutputModel):
    target: str
    error: str


class ObjectiveStackRecoverOut(OutputModel):
    """The ``perk objective stack recover --json`` envelope (contracts.md §8.51). Under
    ``dry_run`` the swept lists carry the WOULD-BE sweep targets (nothing was deleted)."""

    success: bool
    objective: ObjectiveOut
    dry_run: bool
    selection_required: bool
    operations: tuple[RecoverOperationOut, ...]
    swept_worktrees: tuple[str, ...]
    swept_refs: tuple[str, ...]
    sweep_failures: tuple[SweepFailureOut, ...]
    sweep_skipped: str | None
    # Declared last: the LAND-arm fields — additive envelope growth (contracts.md §8.51).
    landed_layers: tuple[RecoverLandedLayerOut, ...] = ()
    objective_closed: bool = False
    reconcile_evidence: ReconcileEvidenceOut | None = None
    notes: tuple[str, ...] = ()

    @classmethod
    def from_domain(cls, result: RecoverResult.OperationConclusion) -> "ObjectiveStackRecoverOut":
        return cls(
            success=True,
            objective=ObjectiveOut(
                id=result.objective_id,
                url=result.objective_url,
                redirected_from=result.redirected_from,
            ),
            dry_run=result.dry_run,
            selection_required=result.selection_required,
            operations=tuple(RecoverOperationOut.from_domain(row) for row in result.operations),
            swept_worktrees=result.swept_worktrees,
            swept_refs=result.swept_refs,
            sweep_failures=tuple(
                SweepFailureOut(target=failure.target, error=failure.error)
                for failure in result.sweep_failures
            ),
            sweep_skipped=result.sweep_skipped,
            landed_layers=tuple(
                RecoverLandedLayerOut.from_domain(row) for row in result.landed_layers
            ),
            objective_closed=result.objective_closed,
            reconcile_evidence=None
            if result.reconcile_evidence is None
            else ReconcileEvidenceOut.from_domain(result.reconcile_evidence),
            notes=result.notes,
        )


# --- confirmation + rendering (stderr only; --json never contaminates stdout) ---


def _make_consent(*, yes: bool):
    """Render either conclusion preview with the existing confirmation discipline."""

    def consent(
        preview: RecoverResult.AbandonPreview | RecoverResult.AcceptPrefixPreview,
    ) -> bool:
        if isinstance(preview, RecoverResult.AbandonPreview):
            user_output(
                f"Abandon operation {preview.operation_id} ({preview.kind}, prepared "
                f"{preview.prepared_created})?"
            )
            user_output(f"  {preview.detail}")
            if yes:
                return True
            stdin = click.get_text_stream("stdin")
            if not stdin.isatty():
                raise UserFacingCliError(
                    "Abandoning an unresolved operation needs confirmation — rerun "
                    "interactively or pass --yes.",
                    error_type="confirmation_required",
                )
            return click.confirm("Abandon it?", err=True)

        user_output(
            f"Accept the externally merged prefix of operation {preview.operation_id} "
            f"(land, prepared {preview.prepared_created}) as a recorded degraded-atomicity "
            "breach?"
        )
        for row in preview.merged_layers:
            user_output(
                f"  merged: {row.node_id} pr #{row.pr_number} as {row.merge_commit_sha[:12]}"
            )
        for row in preview.remainder:
            user_output(f"  remainder: pr #{row.pr_number} {row.state} at {row.head_sha[:12]}")
        user_output(f"  {preview.detail}")
        if yes:
            return True
        stdin = click.get_text_stream("stdin")
        if not stdin.isatty():
            raise UserFacingCliError(
                "Accepting an externally merged prefix records a breach and needs "
                "confirmation — rerun interactively or pass --yes.",
                error_type="confirmation_required",
            )
        return click.confirm("Accept it?", err=True)

    return consent


def _require_operation_conclusion(
    result: RecoverResult,
) -> RecoverResult.OperationConclusion:
    """The one narrowing point: an operation_conclusion request always carries its detail
    (the strict wrapper's kind↔detail guard)."""
    conclusion = result.operation_conclusion
    if conclusion is None:
        raise AssertionError("operation_conclusion recover returned no operation detail")
    return conclusion


def _render_result(result: RecoverResult.OperationConclusion) -> None:
    if result.dry_run:
        user_output("dry run: nothing was concluded, journaled, or swept")
    if not result.operations:
        user_output("no unresolved operations")
    for row in result.operations:
        user_output(
            f"  {row.operation_id} ({row.kind}, prepared {row.prepared_created}): "
            f"{row.classification} → {row.action}"
        )
        user_output(f"    {row.detail}")
    if result.selection_required:
        user_output(
            "several operations are unresolved — rerun with `--operation ULID` to act on one"
        )
    for note in result.notes:
        user_output(click.style(f"note: {note}", dim=True))
    for row in result.landed_layers:
        if row.finalized is None:
            verdict = "would finalize"
        else:
            verdict = "finalized" if row.finalized else "FINALIZE FAILED (see notes)"
        user_output(
            f"  landed {row.node_id} plan #{row.plan_id} (pr #{row.pr_number}, merged as "
            f"{row.merge_commit_sha[:12]}): {verdict}"
        )
    if result.objective_closed:
        user_output(f"objective #{result.objective_id} complete — closed")
    evidence = result.reconcile_evidence
    if evidence is not None:
        partial = " (PARTIAL — see notes)" if evidence.partial else ""
        base = evidence.final_base_sha[:12] if evidence.final_base_sha is not None else "?"
        user_output(
            f"reconcile evidence: {len(evidence.layers)} layer(s), final base "
            f"{base}{partial} — reconcile objective #{result.objective_id} with "
            "/objective-reconcile"
        )
    if result.sweep_skipped is not None:
        user_output(f"sweep skipped: {result.sweep_skipped}")
    elif result.swept_worktrees or result.swept_refs:
        verb = "would sweep" if result.dry_run else "swept"
        user_output(
            f"{verb} {len(result.swept_worktrees)} orphaned worktree(s) and "
            f"{len(result.swept_refs)} orphaned ref(s)"
        )
    for failure in result.sweep_failures:
        user_output(f"  sweep failure: {failure.target} ({failure.error})")


@click.command("recover")
@click.argument("objective", required=False)
@click.option(
    "--dry-run",
    "dry_run",
    is_flag=True,
    help="Classify and report only — no roll-forward, no abandon, no sweep.",
)
@click.option(
    "--operation",
    "operation_id",
    default=None,
    metavar="ULID",
    help="The action target when several operations are unresolved.",
)
@click.option(
    "--abandon",
    "abandon",
    is_flag=True,
    help="Abandon the target operation with proof (requires an all-before classification).",
)
@click.option(
    "--accept-prefix",
    "accept_prefix",
    is_flag=True,
    help=(
        "Accept an externally merged LAND prefix as a recorded degraded-atomicity breach "
        "(requires an external_prefix classification)."
    ),
)
@click.option("--yes", "yes", is_flag=True, help="Approve the rendered action without asking.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def recover_stack(
    ctx: click.Context,
    *,
    objective: str | None,
    dry_run: bool,
    operation_id: str | None,
    abandon: bool,
    accept_prefix: bool,
    yes: bool,
    as_json: bool,
) -> None:
    """Conclude unresolved stack operations and sweep orphaned sync residue.

    Classifies every unresolved operation against fresh authority (SYNC/ADOPT through the
    sync-record core; PUBLISH through the publish proof; TRANSFER through the transfer
    manifest + run_id successor lookup; LAND through the recorded operation identity — the
    journaled merge-async handle or prepared mode — plus per-PR strict observation), rolls
    the target forward automatically when everything verified at the prepared after state,
    abandons a proven all-before target under --abandon (confirmed), records an externally
    merged LAND prefix as a breach under --accept-prefix (confirmed), converges LAND
    finalization idempotently, then sweeps orphaned sync worktrees/refs. Retries route to
    the owning command (`stack sync`, `/submit`, `stack land`).
    """
    if dry_run and (abandon or accept_prefix):
        fail(
            ctx,
            as_json=as_json,
            error_type="invalid_input",
            message="--dry-run previews only — drop it to act with --abandon/--accept-prefix.",
        )
        return
    if abandon and accept_prefix:
        fail(
            ctx,
            as_json=as_json,
            error_type="invalid_input",
            message="--abandon and --accept-prefix are mutually exclusive.",
        )
        return
    try:
        repo_root = require_repo(ctx)
        require_config(ctx)
        objective_id = resolve_objective_id(repo_root, objective)
        action = "accept_prefix" if accept_prefix else "abandon" if abandon else "report"
        request = RecoverRequest(
            kind="operation_conclusion",
            objective_id=objective_id,
            action=action,
            dry_run=dry_run,
            operation_id=operation_id,
        )
        result = _require_operation_conclusion(
            resolve_delivery(repo_root).recover(request, consent=_make_consent(yes=yes))
        )
    except DeliveryError as exc:
        fail(ctx, as_json=as_json, error_type=exc.error_type, message=str(exc))
        return
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return
    payload = ObjectiveStackRecoverOut.from_domain(result).model_dump(mode="json")
    emit(as_json=as_json, payload=payload, render=lambda: _render_result(result))
