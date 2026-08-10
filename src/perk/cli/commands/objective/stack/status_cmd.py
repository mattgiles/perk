"""``perk objective stack status`` — the DeliveryTrain read-path worker (contracts.md §8.44).

Reconstructs one immutable train projection from the durable authorities and reports it —
read-only end to end, working from a fresh clone. Blockers are a successful *detection*
(exit 0, mirroring ``perk objective doctor``'s report-vs-abort split); exit 1 is reserved for
the typed reconstruction failures (no honest projection exists); exit 2 = not-a-repo.
Supervisor surface: ``--json`` → stdout, human text → stderr.
"""

from pathlib import Path

import click

from perk.backends.issue_backend import IssueBackendError
from perk.backends.objective_store import ObjectiveStoreError
from perk.boundary import OutputModel
from perk.cli.commands.objective.shared import parse_objective_id
from perk.cli.context import require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.delivery import observe, train
from perk.delivery.persistence import TrainPersistenceError
from perk.state import cache
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
    # Declared last: the readiness block is an additive envelope growth (contracts.md §8.46).
    next_build_ready: NextBuildReadyOut

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
        )


class ObjectiveStackStatusOut(OutputModel):
    """The ``perk objective stack status --json`` envelope. ``delivery`` is
    ``incremental | stacked``; exactly one of ``train`` / ``no_train`` is set (``no_train``
    carries the successful no-train explanation for an incremental objective)."""

    success: bool
    error_type: str | None
    objective: ObjectiveOut
    delivery: str
    train: TrainOut | None
    no_train: str | None

    @classmethod
    def from_domain(cls, status: train.TrainStatus) -> "ObjectiveStackStatusOut":
        objective_out = ObjectiveOut(
            id=status.objective_id,
            url=status.objective_url,
            redirected_from=status.redirected_from,
        )
        if isinstance(status, train.NoDeliveryTrain):
            return cls(
                success=True,
                error_type=None,
                objective=objective_out,
                delivery="incremental",
                train=None,
                no_train=status.reason,
            )
        return cls(
            success=True,
            error_type=None,
            objective=objective_out,
            delivery="stacked",
            train=TrainOut.from_domain(status),
            no_train=None,
        )


# --- rendering ---


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
    return " ".join(parts)


def _render_human(status: train.TrainStatus) -> None:
    if status.redirected_from is not None:
        user_output(click.style(f"redirected from #{status.redirected_from}", dim=True))
    if isinstance(status, train.NoDeliveryTrain):
        user_output(f"Objective #{status.objective_id}: {status.reason}")
        return
    user_output(
        f"Objective #{status.objective_id}: stacked delivery train (base {status.base}, "
        f"published prefix {status.published_prefix_len}/{len(status.layers)})"
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
    operation = status.unresolved_operation
    if operation is not None:
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


def _resolve_objective_id(repo_root: Path, explicit: str | None) -> str:
    """Explicit argument wins; else the worktree plan-ref's linked objective; neither is a
    typed refusal (a cold session must name its objective)."""
    if explicit is not None:
        return parse_objective_id(explicit)
    ref = cache.read_plan_ref(repo_root)
    if ref is not None and ref.objective_id is not None:
        return ref.objective_id
    raise UserFacingCliError(
        "No objective given — pass OBJECTIVE or run from a plan worktree linked to one.",
        error_type="no_objective",
    )


@click.command("status")
@click.argument("objective", required=False)
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
        objective_id = _resolve_objective_id(repo_root, objective)
        reads = observe.resolve_train_reads(repo_root)
        status = train.reconstruct_train(
            objective_id,
            store=reads.store,
            issues=reads.issues,
            persistence=reads.persistence,
            git=reads.git,
            github=reads.github,
            trunk=reads.trunk,
        )
    except train.TrainReconstructionError as exc:
        fail(ctx, as_json=as_json, error_type=exc.error_type, message=str(exc))
        return
    except (IssueBackendError, ObjectiveStoreError, TrainPersistenceError) as exc:
        # The backend-read translation matching `objective show` (an authority read failed).
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
    payload = ObjectiveStackStatusOut.from_domain(status).model_dump(mode="json")
    emit(as_json=as_json, payload=payload, render=lambda: _render_human(status))
