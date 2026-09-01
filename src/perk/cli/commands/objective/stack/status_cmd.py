"""``perk objective stack status`` — the ``Delivery.status`` worker (contracts.md §8.44).

Reads one immutable train projection from the canonical delivery façade and reports it —
read-only end to end, working from a fresh clone. Blockers are a successful *detection*
(exit 0, mirroring ``perk objective doctor``'s report-vs-abort split); exit 1 is reserved for
the typed reconstruction failures (no honest projection exists); exit 2 = not-a-repo.
Supervisor surface: ``--json`` → stdout, human text → stderr.
"""

from pathlib import Path

import click

from perk.boundary import OutputModel
from perk.cli import completions
from perk.cli.commands.objective.shared import (
    GateBlockerOut,
    PlanningGateOut,
    compose_planning_gate,
)
from perk.cli.commands.objective.stack.shared import resolve_objective_id
from perk.cli.context import require_config, require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.delivery import (
    DeliveryError,
    StatusRequest,
    StatusResult,
    continuation,
    recover,
    resolve_delivery,
    train,
)
from perk.substrate import git
from perk.substrate.output import user_output

# --- the ``--json`` envelope (OutputModel family; declaration order load-bearing) ---


class ObjectiveOut(OutputModel):
    """The resolved (ACTIVE) objective identity; ``redirected_from`` names the originally
    requested objective when a ``superseded_by`` chain redirected forward."""

    id: str
    url: str
    redirected_from: str | None


class FindingOut(OutputModel):
    code: str
    message: str
    node_id: str | None
    plan_id: str | None

    @classmethod
    def from_domain(cls, finding: train.TrainFinding) -> "FindingOut":
        return cls(
            code=finding.code,
            message=finding.message,
            node_id=finding.node_id,
            plan_id=finding.plan_id,
        )


class OperationOut(OutputModel):
    operation_id: str
    kind: str
    prepared_created: str


class LayerOut(OutputModel):
    node_id: str
    plan_id: str | None
    branch: str | None
    pr_number: int | None
    intent: str
    publication: str
    git: str
    pr: str
    membership: str
    writer: str
    finalization: str
    parent_checkpoint_sha: str | None
    published_head_sha: str | None
    observed_remote_head_sha: str | None
    observed_pr_base: str | None
    expected_pr_base: str | None
    # Declared last: the handoff axis is additive envelope growth (contracts.md §8.44).
    handoff: str

    @classmethod
    def from_domain(cls, layer: train.TrainLayer) -> "LayerOut":
        return cls(
            node_id=layer.node_id,
            plan_id=layer.plan_id,
            branch=layer.branch,
            pr_number=layer.pr_number,
            intent=layer.intent.value,
            publication=layer.publication.value,
            git=layer.git.value,
            pr=layer.pr.value,
            membership=layer.membership.value,
            writer=layer.writer.value,
            finalization=layer.finalization.value,
            parent_checkpoint_sha=layer.parent_checkpoint_sha,
            published_head_sha=layer.published_head_sha,
            observed_remote_head_sha=layer.observed_remote_head_sha,
            observed_pr_base=layer.observed_pr_base,
            expected_pr_base=layer.expected_pr_base,
            handoff=layer.handoff.value,
        )


class NextBuildReadyOut(OutputModel):
    """The derived build-readiness block (contracts.md §8.46): the readiness-derived next
    layer, the fail-closed verdict, and the exact veto when blocked."""

    node_id: str | None
    ready: bool
    reason: str | None

    @classmethod
    def from_domain(cls, readiness: train.BuildReadiness) -> "NextBuildReadyOut":
        return cls(node_id=readiness.next_node_id, ready=readiness.ready, reason=readiness.reason)


class TrainOut(OutputModel):
    delivery_lineage: str | None
    base: str
    published_prefix_len: int
    layers: tuple[LayerOut, ...]
    unresolved_operation: OperationOut | None
    blockers: tuple[FindingOut, ...]
    information: tuple[FindingOut, ...]
    # Declared last: the readiness block, the observed base head, the landed prefix, and the
    # planning gate are additive envelope growths (contracts.md §8.46 / §8.44 / §8.51).
    # ``next_build_ready`` stays byte-compatible and purely technical; ``planning_gate`` is
    # the technical-AND-handoff planning verdict (§8.46).
    next_build_ready: NextBuildReadyOut
    observed_base_head_sha: str | None
    landed_prefix_len: int = 0
    planning_gate: PlanningGateOut = PlanningGateOut(node_id=None, ready=False, blockers=())

    @classmethod
    def from_domain(cls, result: train.DeliveryTrain) -> "TrainOut":
        operation = result.unresolved_operation
        return cls(
            delivery_lineage=result.delivery_lineage,
            base=result.base,
            published_prefix_len=result.published_prefix_len,
            layers=tuple(LayerOut.from_domain(layer) for layer in result.layers),
            unresolved_operation=None
            if operation is None
            else OperationOut(
                operation_id=operation.operation_id,
                kind=operation.kind,
                prepared_created=operation.prepared_created,
            ),
            blockers=tuple(FindingOut.from_domain(f) for f in result.blockers),
            information=tuple(FindingOut.from_domain(f) for f in result.information),
            next_build_ready=NextBuildReadyOut.from_domain(result.build_readiness),
            observed_base_head_sha=result.observed_base_head_sha,
            landed_prefix_len=result.landed_prefix_len,
            planning_gate=compose_planning_gate(result, None),
        )


class ContinuationOut(OutputModel):
    """This lineage's pending sync-continuation manifest (contracts.md §8.44/§8.49) — a
    machine-local CLI-side observation. ``parseable: false`` rows carry nulls for every
    field the unreadable file cannot account for. ``targets_contained`` is additive trailing
    growth (§8.44/§8.51): whether the manifest's named targets pass the canonical
    ``continuation.validated_targets`` containment validation against the configured worktree
    root — the warm conflict dispatch requires it ``true`` (version skew fails closed: an
    older CLI omits the field and the warm side refuses to dispatch)."""

    operation_id: str | None
    conflict_node_id: str | None
    adopted_node: str | None
    created: str | None
    worktree_path: str | None
    manifest_path: str
    parseable: bool
    targets_contained: bool = False


class OrphanedResidueOut(OutputModel):
    """The machine-local orphaned-sync-residue observation (contracts.md §8.44/§8.51).
    ``observed: false`` + ``reason`` whenever the Config load or the classifier's git/fs
    reads fail — an unobserved state is never serialized as clean empty lists;
    ``observed: true`` with empty lists means genuinely clean."""

    observed: bool
    reason: str | None
    worktrees: tuple[str, ...]
    refs: tuple[str, ...]


class ObjectiveStackStatusOut(OutputModel):
    """The ``perk objective stack status --json`` envelope. ``delivery`` is
    ``incremental | stacked``; exactly one of ``train`` / ``no_train`` is set (``no_train``
    carries the successful no-train explanation for an incremental objective).
    ``operations`` / ``continuation`` / ``orphaned_residue`` are the §8.44 detailed-status
    additions (always-on, additive)."""

    success: bool
    error_type: str | None
    objective: ObjectiveOut
    delivery: str
    train: TrainOut | None
    no_train: str | None
    operations: tuple[OperationOut, ...]
    continuation: ContinuationOut | None
    orphaned_residue: OrphanedResidueOut

    @classmethod
    def from_domain(
        cls,
        result: StatusResult,
        *,
        continuation_out: ContinuationOut | None,
        orphaned_residue: OrphanedResidueOut,
    ) -> "ObjectiveStackStatusOut":
        objective_out = ObjectiveOut(
            id=result.objective_id,
            url=result.objective_url,
            redirected_from=result.redirected_from,
        )
        status = result.train
        if status is None:
            return cls(
                success=True,
                error_type=None,
                objective=objective_out,
                delivery="incremental",
                train=None,
                no_train=result.no_train_reason,
                operations=(),
                continuation=continuation_out,
                orphaned_residue=orphaned_residue,
            )
        return cls(
            success=True,
            error_type=None,
            objective=objective_out,
            delivery="stacked",
            train=TrainOut.from_domain(status),
            no_train=None,
            operations=tuple(
                OperationOut(
                    operation_id=facts.operation_id,
                    kind=facts.kind,
                    prepared_created=facts.prepared_created,
                )
                for facts in status.unresolved_operations
            ),
            continuation=continuation_out,
            orphaned_residue=orphaned_residue,
        )


# --- the machine-local CLI-side observations (§8.44 detailed status) ---


def _targets_contained(ctx: click.Context, manifest: continuation.ContinuationManifest) -> bool:
    """Whether the manifest's named targets pass the canonical containment validation
    (``continuation.validated_targets`` against the configured worktree root — the same seam
    continue/abort trust as deletion authority). Fail-closed and tolerant: a config read
    failure, a filesystem resolution failure, or any containment violation reports ``False``
    — status stays read-only and never raises on a local observation."""
    try:
        worktree_root = require_config(ctx).worktree_root
    except UserFacingCliError:
        return False
    try:
        continuation.validated_targets(manifest, worktree_root)
    except (continuation.ContainmentViolation, OSError):
        return False
    return True


def _observe_continuation(
    ctx: click.Context, repo_root: Path, result: StatusResult
) -> ContinuationOut | None:
    """This lineage's pending continuation manifest, read tolerantly (status stays read-only
    and never fails on a local observation)."""
    status = result.train
    if status is None or status.delivery_lineage is None:
        return None
    try:
        pending = continuation.pending_continuation(repo_root, status.delivery_lineage)
    except (OSError, ValueError):
        # A malformed (non-path-safe) lineage cannot name a manifest; the mutating
        # commands refuse it with the specific typed error — status just reports no pending
        # continuation.
        return None
    if pending is None:
        return None
    manifest = pending.manifest
    if manifest is None:
        return ContinuationOut(
            operation_id=None,
            conflict_node_id=None,
            adopted_node=None,
            created=None,
            worktree_path=None,
            manifest_path=str(pending.path),
            parseable=False,
            targets_contained=False,
        )
    return ContinuationOut(
        operation_id=manifest.operation_id,
        conflict_node_id=manifest.conflict_node_id,
        adopted_node=manifest.adopted_node,
        created=manifest.created,
        worktree_path=manifest.worktree_path,
        manifest_path=str(pending.path),
        parseable=True,
        targets_contained=_targets_contained(ctx, manifest),
    )


def _observe_orphans(ctx: click.Context, repo_root: Path) -> OrphanedResidueOut:
    """The orphan-residue observation through recover's shared classifier, fail-honest: a
    Config-load or git/fs read failure reports ``observed: false`` + the reason — never
    clean empty lists for a state that was not actually observed."""
    try:
        worktree_root = require_config(ctx).worktree_root
    except UserFacingCliError as exc:
        return OrphanedResidueOut(
            observed=False,
            reason=f"config unavailable: {exc.format_message()}",
            worktrees=(),
            refs=(),
        )
    try:
        scan = recover.observe_orphans(repo_root, worktree_root=worktree_root)
    except (git.GitError, OSError) as exc:
        return OrphanedResidueOut(
            observed=False,
            reason=f"residue observation failed: {exc}",
            worktrees=(),
            refs=(),
        )
    if scan.skipped is not None:
        return OrphanedResidueOut(observed=False, reason=scan.skipped, worktrees=(), refs=())
    return OrphanedResidueOut(
        observed=True,
        reason=None,
        # Stale worktree-admin entries (directory gone, inventory record left) count as
        # orphaned worktrees — they are would-be sweep targets like the on-disk ones.
        worktrees=tuple(str(path) for path in (*scan.worktrees, *scan.stale_admin)),
        refs=scan.refs,
    )


# --- rendering ---


def _gate_row_phrase(row: GateBlockerOut) -> str:
    """One handoff-gate blocker row's human phrase (fields-only — the §8.46 handoff rows
    carry no prose)."""
    if row.kind != "handoff":
        return f"[{row.code}] {row.message}; check: {row.remediation}"
    detail = f"{row.dependency_node_id} (plan #{row.plan}, PR #{row.pr}) — {row.handoff_state}"
    if (
        row.stamped_head is not None
        and row.current_head is not None
        and row.handoff_state == "stale"
    ):
        detail += f"; stamped {row.stamped_head[:12]} ≠ head {row.current_head[:12]}"
    return detail + f"; record the handoff: {row.remediation}"


def _layer_line(layer: train.TrainLayer) -> str:
    parts = [layer.node_id]
    parts.append(f"plan #{layer.plan_id}" if layer.plan_id is not None else "unplanned")
    parts.append(f"[{layer.publication.value}]")
    if layer.pr_number is not None:
        parts.append(f"pr #{layer.pr_number} ({layer.pr.value})")
    else:
        parts.append("no pr")
    if layer.membership is not train.LayerMembership.NOT_APPLICABLE:
        parts.append(f"stack {layer.membership.value}")
    if layer.writer is not train.LayerWriter.FREE:
        parts.append(f"writer {layer.writer.value}")
    if layer.handoff is not train.LayerHandoff.NOT_APPLICABLE:
        parts.append(f"handoff {layer.handoff.value}")
    return " ".join(parts)


def _render_human(result: StatusResult) -> None:
    if result.redirected_from is not None:
        user_output(click.style(f"redirected from #{result.redirected_from}", dim=True))
    status = result.train
    if status is None:
        user_output(f"Objective #{result.objective_id}: {result.no_train_reason}")
        return
    landed = f", landed {status.landed_prefix_len}" if status.landed_prefix_len else ""
    user_output(
        f"Objective #{status.objective_id}: stacked delivery train (base {status.base}, "
        f"published prefix {status.published_prefix_len}/{len(status.layers)}{landed})"
    )
    if status.delivery_lineage is not None:
        user_output(click.style(f"  lineage {status.delivery_lineage}", dim=True))
    for index, layer in enumerate(status.layers, start=1):
        user_output(f"  {index}. {_layer_line(layer)}")
    readiness = status.build_readiness
    if readiness.ready:
        user_output(f"  next build-ready: {readiness.next_node_id}")
    else:
        user_output(f"  build blocked: {readiness.reason}")
    if readiness.ready:
        gate = compose_planning_gate(status, None)
        if not gate.ready:
            for row in gate.blockers:
                user_output(f"  planning gated: {gate.node_id} waits on {_gate_row_phrase(row)}")
    for operation in status.unresolved_operations:
        user_output(
            f"  active operation: {operation.operation_id} ({operation.kind}, prepared "
            f"{operation.prepared_created})"
        )
    blockers, information = status.blockers, status.information
    if blockers:
        user_output("blockers:")
        for finding in blockers:
            user_output(f"  - [{finding.code}] {finding.message}")
    if information:
        user_output("information:")
        for finding in information:
            user_output(f"  - [{finding.code}] {finding.message}")
    if not blockers and not information:
        user_output(click.style("no findings", dim=True))


def _render_local_observations(
    continuation_out: ContinuationOut | None, orphans: OrphanedResidueOut
) -> None:
    if continuation_out is not None:
        if continuation_out.parseable:
            user_output(
                f"pending continuation: operation {continuation_out.operation_id} stopped "
                f"on node {continuation_out.conflict_node_id} (worktree "
                f"{continuation_out.worktree_path})"
            )
        else:
            user_output(
                f"pending continuation: UNPARSEABLE manifest at {continuation_out.manifest_path}"
            )
        user_output(
            "  resume with `perk objective stack sync --continue`, or discard with "
            "`perk objective stack sync --abort`"
        )
    if not orphans.observed:
        user_output(f"orphaned residue: not observed — {orphans.reason}")
    elif orphans.worktrees or orphans.refs:
        user_output(
            f"orphaned residue: {len(orphans.worktrees)} worktree(s), {len(orphans.refs)} "
            "ref(s) — run `perk objective stack recover` to sweep"
        )


@click.command("status")
@click.argument("objective", required=False, shell_complete=completions.complete_objective_id)
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def status_stack(ctx: click.Context, *, objective: str | None, as_json: bool) -> None:
    """Report an objective's delivery-train status (read-only; works from a fresh clone).

    Blockers found is a successful detection (exit 0); exit 1 is reserved for the typed
    reconstruction failures; 2 = not-a-repo. An incremental objective succeeds with the
    no-train explanation.
    """
    try:
        repo_root = require_repo(ctx)
        objective_id = resolve_objective_id(repo_root, objective)
        status = resolve_delivery(repo_root).status(StatusRequest(objective_id=objective_id))
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
    continuation_out = _observe_continuation(ctx, repo_root, status)
    orphaned_residue = _observe_orphans(ctx, repo_root)
    payload = ObjectiveStackStatusOut.from_domain(
        status, continuation_out=continuation_out, orphaned_residue=orphaned_residue
    ).model_dump(mode="json")

    def _render() -> None:
        _render_human(status)
        _render_local_observations(continuation_out, orphaned_residue)

    emit(as_json=as_json, payload=payload, render=_render)
