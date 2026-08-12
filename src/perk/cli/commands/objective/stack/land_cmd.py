"""``perk objective stack land`` — the landing-readiness dry-run worker (contracts.md §8.55).

Read-only end to end in this node: ``--dry-run`` reconstructs the train, composes the
:class:`~perk.delivery.land.LandReadiness` preflight projection from fresh GitHub
observations, and reports the complete dry-run land plan. Invoking ``land`` WITHOUT
``--dry-run`` is the typed refusal ``land_unimplemented`` — the atomic landing mutation is
deferred work that will replace the refusal on this same argv shape. Blockers are a
successful *detection* (exit 0, the ``stack status`` split); exit 1 is reserved for the
typed failures where no honest assessment exists; exit 2 = not-a-repo. Supervisor surface:
``--json`` → stdout, human text → stderr.
"""

import click

from perk.backends.issue_backend import IssueBackendError
from perk.backends.objective_store import ObjectiveStoreError
from perk.boundary import OutputModel
from perk.cli.commands.objective.stack.shared import resolve_objective_id
from perk.cli.commands.objective.stack.status_cmd import FindingOut, ObjectiveOut
from perk.cli.context import require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.delivery import land, observe, train
from perk.delivery.persistence import TrainPersistenceError
from perk.run.writer_probe import GhaRemoteWriterProbe
from perk.substrate.output import user_output

# --- the ``--json`` envelope (OutputModel family; declaration order load-bearing) ---


class RulesOut(OutputModel):
    squash_allowed: bool
    merge_queue_required: bool


class LandLayerOut(OutputModel):
    """One layer's readiness row — mirrors ``LandLayerReadiness`` field-for-field
    (unassessed rows serialize their ``None`` observations as-is)."""

    node_id: str
    plan_id: str | None
    pr_number: int | None
    branch: str | None
    expected_base_ref: str | None
    expected_head_sha: str | None
    base_sha: str | None
    assessed: bool
    observed_state: str | None
    observed_is_draft: bool | None
    observed_base_ref: str | None
    observed_head_ref: str | None
    observed_head_sha: str | None
    mergeable: str | None
    merge_state_status: str | None
    review_decision: str | None
    required_checks_failed: tuple[str, ...]
    required_checks_pending: tuple[str, ...]
    optional_checks_failed: tuple[str, ...]
    unresolved_thread_count: int | None

    @classmethod
    def from_domain(cls, row: land.LandLayerReadiness) -> "LandLayerOut":
        return cls(
            node_id=row.node_id,
            plan_id=row.plan_id,
            pr_number=row.pr_number,
            branch=row.branch,
            expected_base_ref=row.expected_base_ref,
            expected_head_sha=row.expected_head_sha,
            base_sha=row.base_sha,
            assessed=row.assessed,
            observed_state=row.observed_state,
            observed_is_draft=row.observed_is_draft,
            observed_base_ref=row.observed_base_ref,
            observed_head_ref=row.observed_head_ref,
            observed_head_sha=row.observed_head_sha,
            mergeable=row.mergeable,
            merge_state_status=row.merge_state_status,
            review_decision=row.review_decision,
            required_checks_failed=row.required_checks_failed,
            required_checks_pending=row.required_checks_pending,
            optional_checks_failed=row.optional_checks_failed,
            unresolved_thread_count=row.unresolved_thread_count,
        )


class LandPlanLayerOut(OutputModel):
    node_id: str
    plan_id: str
    pr_number: int
    base_sha: str
    head_sha: str


class LandPlanOut(OutputModel):
    mode: str
    merge_method: str
    top_pr_number: int
    top_head_sha: str
    layers: tuple[LandPlanLayerOut, ...]

    @classmethod
    def from_domain(cls, plan: land.LandPlan) -> "LandPlanOut":
        return cls(
            mode=plan.mode,
            merge_method=plan.merge_method,
            top_pr_number=plan.top_pr_number,
            top_head_sha=plan.top_head_sha,
            layers=tuple(
                LandPlanLayerOut(
                    node_id=layer.node_id,
                    plan_id=layer.plan_id,
                    pr_number=layer.pr_number,
                    base_sha=layer.base_sha,
                    head_sha=layer.head_sha,
                )
                for layer in plan.layers
            ),
        )


class ObjectiveStackLandOut(OutputModel):
    """The ``perk objective stack land --dry-run --json`` envelope (contracts.md §8.55)."""

    success: bool
    error_type: str | None
    objective: ObjectiveOut
    dry_run: bool
    disposition: str
    base: str
    delivery_lineage: str | None
    rules: RulesOut | None
    native_stack_capability: bool | None
    layers: tuple[LandLayerOut, ...]
    blockers: tuple[FindingOut, ...]
    information: tuple[FindingOut, ...]
    plan: LandPlanOut | None

    @classmethod
    def from_domain(
        cls, readiness: land.LandReadiness, *, redirected_from: str | None
    ) -> "ObjectiveStackLandOut":
        return cls(
            success=True,
            error_type=None,
            objective=ObjectiveOut(
                id=readiness.objective_id,
                url=readiness.objective_url,
                redirected_from=redirected_from,
            ),
            dry_run=True,
            disposition=readiness.disposition.value,
            base=readiness.base,
            delivery_lineage=readiness.delivery_lineage,
            rules=None
            if readiness.rules is None
            else RulesOut(
                squash_allowed=readiness.rules.squash_allowed,
                merge_queue_required=readiness.rules.merge_queue_required,
            ),
            native_stack_capability=readiness.native_stack_capability,
            layers=tuple(LandLayerOut.from_domain(row) for row in readiness.layers),
            blockers=tuple(FindingOut.from_domain(f) for f in readiness.blockers),
            information=tuple(FindingOut.from_domain(f) for f in readiness.information),
            plan=None if readiness.plan is None else LandPlanOut.from_domain(readiness.plan),
        )


# --- rendering (stderr; fed entirely from the LandReadiness value) ---


def _layer_line(row: land.LandLayerReadiness) -> str:
    parts = [row.node_id]
    parts.append(f"plan #{row.plan_id}" if row.plan_id is not None else "unplanned")
    parts.append(f"pr #{row.pr_number}" if row.pr_number is not None else "no pr")
    if not row.assessed:
        parts.append("not assessed")
        return " ".join(parts)
    parts.append(f"{row.observed_state} {'draft' if row.observed_is_draft else 'ready'}")
    if row.observed_base_ref == row.expected_base_ref:
        parts.append(f"base {row.observed_base_ref}")
    else:
        parts.append(f"base {row.observed_base_ref} (expected {row.expected_base_ref})")
    if row.observed_head_sha == row.expected_head_sha:
        parts.append(f"head {_short(row.observed_head_sha)}")
    else:
        parts.append(
            f"head {_short(row.observed_head_sha)} (expected {_short(row.expected_head_sha)})"
        )
    parts.append(f"{row.mergeable}/{row.merge_state_status}")
    if row.review_decision is not None:
        parts.append(f"review {row.review_decision}")
    if row.required_checks_failed:
        parts.append(f"required failed: {', '.join(row.required_checks_failed)}")
    if row.required_checks_pending:
        parts.append(f"required pending: {', '.join(row.required_checks_pending)}")
    if row.unresolved_thread_count:
        parts.append(f"{row.unresolved_thread_count} unresolved thread(s)")
    return " ".join(parts)


def _short(sha: str | None) -> str:
    return sha[:12] if sha is not None else "?"


def _render_human(readiness: land.LandReadiness) -> None:
    user_output(
        f"Objective #{readiness.objective_id}: landing readiness (dry run) — "
        f"{readiness.disposition.value.upper()}"
    )
    if readiness.rules is None:
        user_output(f"  base {readiness.base}: merge rules unobserved")
    else:
        squash = "allowed" if readiness.rules.squash_allowed else "FORBIDDEN"
        queue = "required" if readiness.rules.merge_queue_required else "not required"
        user_output(f"  base {readiness.base}: squash {squash}, merge queue {queue}")
    if readiness.native_stack_capability is not None:
        state = "present" if readiness.native_stack_capability else "UNAVAILABLE"
        user_output(f"  native stack API surface: {state} (host-schema evidence only)")
    for index, row in enumerate(readiness.layers, start=1):
        user_output(f"  {index}. {_layer_line(row)}")
    plan = readiness.plan
    if plan is not None:
        user_output(
            f"plan: {plan.mode} via {plan.merge_method} — top pr #{plan.top_pr_number} at "
            f"{_short(plan.top_head_sha)} ({len(plan.layers)} layer(s))"
        )
    blockers, information = readiness.blockers, readiness.information
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


@click.command("land")
@click.argument("objective", required=False)
@click.option(
    "--dry-run",
    "dry_run",
    is_flag=True,
    help="Assess landing readiness and render the complete dry-run land plan (read-only).",
)
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def land_stack(ctx: click.Context, *, objective: str | None, dry_run: bool, as_json: bool) -> None:
    """Assess an objective's landing readiness (--dry-run; read-only).

    Composes the typed readiness preflight from the reconstructed delivery train plus fresh
    GitHub observations (mergeability, review decision, required checks, merge rules, host
    stack capability) and renders the complete dry-run land plan. Blockers found is a
    successful detection (exit 0); exit 1 is reserved for the typed failures; 2 =
    not-a-repo. The atomic landing mutation is not implemented yet: without --dry-run this
    command refuses (land_unimplemented).
    """
    if not dry_run:
        fail(
            ctx,
            as_json=as_json,
            error_type="land_unimplemented",
            message=(
                "Atomic landing is not implemented yet — run "
                "`perk objective stack land --dry-run` for the readiness preview."
            ),
        )
        return
    try:
        repo_root = require_repo(ctx)
        objective_id = resolve_objective_id(repo_root, objective)
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
        # The backend-read translation matching `stack status` (an authority read failed).
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
    if isinstance(status, train.NoDeliveryTrain):
        fail(
            ctx,
            as_json=as_json,
            error_type="not_stacked",
            message=f"Objective #{status.objective_id}: {status.reason}",
        )
        return
    readiness = land.assess_land_readiness(
        status,
        observations=observe.GatewayLandObservations(repo_root, base=status.base),
        remote_writers=GhaRemoteWriterProbe(repo_root),
    )
    payload = ObjectiveStackLandOut.from_domain(
        readiness, redirected_from=status.redirected_from
    ).model_dump(mode="json")
    emit(as_json=as_json, payload=payload, render=lambda: _render_human(readiness))
