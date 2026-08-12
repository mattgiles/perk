"""``perk objective stack land`` — the objective landing worker (contracts.md §8.55/§8.56).

``--dry-run`` is the read-only readiness preview (§8.55; behavior unchanged — the envelope
preserves the §8.55 field prefix/order, with the §8.56 mutation fields appended as trailing
nulls/empties): reconstruct the train, compose the
:class:`~perk.delivery.land.LandReadiness` projection from fresh GitHub observations, and
report the complete dry-run land plan — blockers are a
successful *detection* (exit 0, the ``stack status`` split). Bare ``land`` is the journaled
atomic landing mutation (§8.56) over ``perk.delivery.landing.land_train``: consent
(``--yes`` auto-approves; non-interactive without it is the typed ``confirmation_required``
refusal), the re-observe/journal-first protocol, and the honest outcome envelope.

Exit codes: 0 = an honest success envelope (every ``--dry-run`` assessment, and the
mutation outcomes ``merged``, ``pending``, ``unexpected_enqueued``,
``completed_without_merge``, ``declined`` — a pending/enqueued landing is unresolved, never
a failure); 1 = the typed failures (``land_blocked``, ``land_failed``,
``merge_async_unavailable``, ``merge_request_conflict``, ``land_drift``,
``confirmation_required``, ``operation_in_progress``, ``plan_not_found``, ``not_stacked``,
``no_objective``, reconstruction/backend failures); 2 = not-a-repo. Supervisor surface:
``--json`` → stdout, human text → stderr.
"""

import click

from perk.backends.issue_backend import IssueBackendError
from perk.backends.objective_store import ObjectiveStoreError
from perk.boundary import OutputModel
from perk.cli.commands.objective.stack.shared import resolve_objective_id, resolve_run_id
from perk.cli.commands.objective.stack.status_cmd import FindingOut, ObjectiveOut
from perk.cli.context import require_github, require_repo
from perk.cli.emit import emit, fail
from perk.cli.ensure import UserFacingCliError
from perk.delivery import land, landing, observe, train
from perk.delivery.journal import JournalCorruptionError
from perk.delivery.persistence import TrainPersistenceError
from perk.github import GitHubError
from perk.run.writer_probe import GhaRemoteWriterProbe
from perk.substrate import git
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
    # Declared last: additive envelope growth (contracts.md §8.51) — a LANDED layer's row
    # carries ``landed: true`` with unassessed nulls.
    landed: bool = False

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
            landed=row.landed,
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


class LandedLayerOut(OutputModel):
    """One verified-merged layer's envelope row (§8.56). The finalize facts flatten here —
    ``finalized: false`` means the per-layer finalize failed (its failure text rides
    ``notes``) and the finalize-derived fields carry their honest defaults."""

    node_id: str
    plan_id: str
    pr_number: int
    merge_commit_sha: str
    learn_state: str | None
    plan_issue_closed: bool
    nodes_marked: tuple[str, ...]
    finalized: bool
    # Declared last: the recorded incremental diff bounds — additive envelope growth
    # (contracts.md §8.56, the reconcile-evidence identity).
    base_sha: str = ""
    head_sha: str = ""

    @classmethod
    def from_domain(cls, layer: landing.LandedLayer) -> "LandedLayerOut":
        fin = layer.finalization
        return cls(
            node_id=layer.node_id,
            plan_id=layer.plan_id,
            pr_number=layer.pr_number,
            merge_commit_sha=layer.merge_commit_sha,
            learn_state=None if fin is None else fin.learn_state,
            plan_issue_closed=False if fin is None else fin.plan_issue_closed,
            nodes_marked=() if fin is None else fin.objective.nodes_marked,
            finalized=fin is not None,
            base_sha=layer.base_sha,
            head_sha=layer.head_sha,
        )


class EvidenceLayerOut(OutputModel):
    node_id: str
    plan_id: str
    pr_number: int
    base_sha: str
    head_sha: str
    merge_commit_sha: str


class ReconcileEvidenceOut(OutputModel):
    """The ordered reconcile evidence riding a close transition (contracts.md §8.56):
    assembled fresh from ALL completed LAND records in fold order — diff identities only,
    never patches. ``partial: true`` marks an undecodable record (its note rides
    ``notes``)."""

    layers: tuple[EvidenceLayerOut, ...]
    final_base_sha: str | None
    partial: bool
    notes: tuple[str, ...]

    @classmethod
    def from_domain(cls, evidence: landing.LandEvidence) -> "ReconcileEvidenceOut":
        return cls(
            layers=tuple(
                EvidenceLayerOut(
                    node_id=row.node_id,
                    plan_id=row.plan_id,
                    pr_number=row.pr_number,
                    base_sha=row.base_sha,
                    head_sha=row.head_sha,
                    merge_commit_sha=row.merge_commit_sha,
                )
                for row in evidence.layers
            ),
            final_base_sha=evidence.final_base_sha,
            partial=evidence.partial,
            notes=evidence.notes,
        )


class ObjectiveStackLandOut(OutputModel):
    """The ``perk objective stack land --json`` envelope (contracts.md §8.55/§8.56).

    The mutation fields are declared LAST so the §8.55 dry-run envelope's field
    prefix/order is preserved (they serialize as trailing nulls/empties there)."""

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
    outcome: str | None = None
    operation_id: str | None = None
    merge_async_uuid: str | None = None
    landed_layers: tuple[LandedLayerOut, ...] = ()
    objective_closed: bool = False
    notes: tuple[str, ...] = ()
    reconcile_evidence: ReconcileEvidenceOut | None = None

    @classmethod
    def from_domain(
        cls, readiness: land.LandReadiness, *, redirected_from: str | None, dry_run: bool = True
    ) -> "ObjectiveStackLandOut":
        return cls(
            success=True,
            error_type=None,
            objective=ObjectiveOut(
                id=readiness.objective_id,
                url=readiness.objective_url,
                redirected_from=redirected_from,
            ),
            dry_run=dry_run,
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

    @classmethod
    def from_outcome(
        cls, result: landing.LandOutcome, *, redirected_from: str | None = None
    ) -> "ObjectiveStackLandOut":
        base = cls.from_domain(result.readiness, redirected_from=redirected_from, dry_run=False)
        return base.model_copy(
            update={
                "outcome": result.outcome,
                "operation_id": result.operation_id,
                "merge_async_uuid": result.merge_async_uuid,
                "landed_layers": tuple(
                    LandedLayerOut.from_domain(layer) for layer in result.landed_layers
                ),
                "objective_closed": result.objective_closed,
                "notes": result.notes,
                "reconcile_evidence": None
                if result.reconcile_evidence is None
                else ReconcileEvidenceOut.from_domain(result.reconcile_evidence),
            }
        )


# --- rendering (stderr; fed entirely from the LandReadiness value) ---


def _layer_line(row: land.LandLayerReadiness) -> str:
    parts = [row.node_id]
    parts.append(f"plan #{row.plan_id}" if row.plan_id is not None else "unplanned")
    parts.append(f"pr #{row.pr_number}" if row.pr_number is not None else "no pr")
    if row.landed:
        parts.append("LANDED")
        return " ".join(parts)
    if not row.assessed:
        parts.append("not assessed")
        return " ".join(parts)
    parts.append(f"{row.observed_state} {'draft' if row.observed_is_draft else 'ready'}")
    if row.observed_base_ref == row.expected_base_ref:
        parts.append(f"base {row.observed_base_ref}")
    else:
        parts.append(f"base {row.observed_base_ref} (expected {row.expected_base_ref})")
    if row.observed_head_ref == row.branch:
        parts.append(f"head-ref {row.observed_head_ref}")
    else:
        parts.append(f"head-ref {row.observed_head_ref} (expected {row.branch})")
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


def _render_human(readiness: land.LandReadiness, *, heading: str) -> None:
    user_output(
        f"Objective #{readiness.objective_id}: {heading} — {readiness.disposition.value.upper()}"
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


# --- consent + the mutation render (stderr only; --json never contaminates stdout) ---


def _render_land_plan(readiness: land.LandReadiness) -> None:
    """Render exactly what an affirmative answer lands (or completes) — the approval gate's
    preview, fed entirely from the readiness value."""
    plan = readiness.plan
    if plan is None:
        # The NOTHING_TO_LAND completion preview: nothing to merge; close the objective.
        user_output(
            f"Objective #{readiness.objective_id}: nothing to merge — every layer is "
            f"skipped or already landed; close objective #{readiness.objective_id} as complete"
        )
        return
    user_output(
        f"Objective #{readiness.objective_id}: land {len(plan.layers)} layer(s) atomically "
        f"({plan.mode} via {plan.merge_method}, base {readiness.base})"
    )
    for layer in plan.layers:
        user_output(
            f"  {layer.node_id} plan #{layer.plan_id} (pr #{layer.pr_number}): "
            f"{layer.base_sha} → {layer.head_sha}"
        )
    user_output(f"  top pin: pr #{plan.top_pr_number} at {plan.top_head_sha}")


def _make_approve(*, yes: bool):
    """The approval callback (sync's ``_make_approve`` discipline): render the land plan (or
    the NOTHING_TO_LAND completion preview) to stderr, then confirm (also on stderr).
    ``--yes`` auto-approves (still rendering what it approved); a non-interactive session
    without ``--yes`` raises the typed ``confirmation_required`` refusal BEFORE any prompt —
    never a hang, never a silent merge."""

    def approve(readiness: land.LandReadiness) -> bool:
        _render_land_plan(readiness)
        if yes:
            return True
        stdin = click.get_text_stream("stdin")
        if not stdin.isatty():
            raise UserFacingCliError(
                "Landing merges the remaining train atomically and needs confirmation — "
                "rerun interactively or pass --yes.",
                error_type="confirmation_required",
            )
        return click.confirm("Proceed?", err=True)

    return approve


# The standing unresolved-operation guidance (the pending / unexpected_enqueued arms).
_UNRESOLVED_GUIDANCE = (
    "the LAND operation is unresolved — landing is blocked until it concludes; "
    "once the merge settles (or expires), `perk objective stack recover` classifies it "
    "against fresh authority and concludes it (all-after rolls forward automatically)"
)


def _render_outcome(result: landing.LandOutcome) -> None:
    for note in result.notes:
        user_output(click.style(f"note: {note}", dim=True))
    if result.outcome == "declined":
        user_output("landing declined; nothing merged or journaled")
        return
    if result.outcome == "completed_without_merge":
        user_output(
            f"nothing to merge — objective #{result.readiness.objective_id} closed as complete"
        )
        return
    if result.outcome in ("pending", "unexpected_enqueued"):
        headline = (
            "the merge request was ENQUEUED (a merge queue owns the outcome)"
            if result.outcome == "unexpected_enqueued"
            else "the landing did not conclude"
        )
        user_output(f"{headline} (operation {result.operation_id})")
        user_output(click.style(f"  ⚠ {_UNRESOLVED_GUIDANCE}", fg="yellow"))
        return
    user_output(
        f"landed {len(result.landed_layers)} layer(s) atomically (operation {result.operation_id})"
    )
    for layer in result.landed_layers:
        line = (
            f"  {layer.node_id} plan #{layer.plan_id} (pr #{layer.pr_number}): merged as "
            f"{layer.merge_commit_sha[:12]}"
        )
        if layer.finalization is None:
            line += " — FINALIZE FAILED (see notes)"
        user_output(line)
    if result.objective_closed:
        user_output(f"objective #{result.readiness.objective_id} complete — closed")
    evidence = result.reconcile_evidence
    if evidence is not None:
        partial = " (PARTIAL — see notes)" if evidence.partial else ""
        user_output(
            f"reconcile evidence: {len(evidence.layers)} layer(s), final base "
            f"{_short(evidence.final_base_sha)}{partial} — reconcile with /objective-reconcile"
        )


# --- the command ---


@click.command("land")
@click.argument("objective", required=False)
@click.option(
    "--dry-run",
    "dry_run",
    is_flag=True,
    help="Assess landing readiness and render the complete dry-run land plan (read-only).",
)
@click.option("--run-id", "run_id", default=None, help="This operation's perk run id.")
@click.option("--yes", "yes", is_flag=True, help="Approve the rendered land plan without asking.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def land_stack(
    ctx: click.Context,
    *,
    objective: str | None,
    dry_run: bool,
    run_id: str | None,
    yes: bool,
    as_json: bool,
) -> None:
    """Land an objective's delivery train atomically (or preview with --dry-run).

    --dry-run composes the typed readiness preflight from the reconstructed delivery train
    plus fresh GitHub observations and renders the complete dry-run land plan (read-only;
    blockers found is a successful detection). Bare land runs the journaled atomic landing
    mutation: the rendered land plan is confirmed on stderr (--yes auto-approves;
    non-interactive without it refuses), every layer PR is re-observed, the operation is
    journaled first, then merged (merge-async for a multi-layer train; a SHA-pinned direct
    squash for the dynamic singleton), verified per PR, finalized per layer, and the
    objective closed once every node is terminal. Exit 0 = an honest outcome envelope
    (merged, pending, unexpected_enqueued, completed_without_merge, declined — a pending/
    enqueued landing is unresolved, not failed); 1 = typed failures; 2 = not-a-repo.
    """
    if dry_run:
        _land_dry_run(ctx, objective=objective, as_json=as_json)
        return
    _land_mutation(ctx, objective=objective, run_id=run_id, yes=yes, as_json=as_json)


def _land_dry_run(ctx: click.Context, *, objective: str | None, as_json: bool) -> None:
    """The §8.55 read-only readiness preview — same reads, the §8.55 envelope field
    prefix/order preserved (the §8.56 mutation fields serialize as trailing nulls/empties),
    no consent."""
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
    except JournalCorruptionError as exc:
        fail(ctx, as_json=as_json, error_type="journal_corruption", message=str(exc))
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
    emit(
        as_json=as_json,
        payload=payload,
        render=lambda: _render_human(readiness, heading="landing readiness (dry run)"),
    )


def _land_mutation(
    ctx: click.Context, *, objective: str | None, run_id: str | None, yes: bool, as_json: bool
) -> None:
    """The §8.56 mutating path (the error ladder mirrors ``sync_cmd``'s)."""
    objective_id: str | None = None
    try:
        repo_root = require_repo(ctx)
        require_github(ctx)
        objective_id = resolve_objective_id(repo_root, objective)
        resolved_run_id = resolve_run_id(repo_root, objective_id, run_id)
        result = landing.land_train(
            repo_root,
            objective_id=objective_id,
            run_id=resolved_run_id,
            approve=_make_approve(yes=yes),
            remote_writers=GhaRemoteWriterProbe(repo_root),
        )
    except landing.LandError as exc:
        extra: dict[str, object] | None = None
        if exc.error_type == "land_blocked" and exc.readiness is not None:
            # The full readiness report: rendered to stderr for humans, attached to the
            # JSON fail envelope as the dry-run-shaped `readiness` payload.
            if not as_json:
                _render_human(exc.readiness, heading="landing readiness")
            extra = {
                "readiness": ObjectiveStackLandOut.from_domain(
                    exc.readiness,
                    redirected_from=_redirected_from(objective_id, exc.readiness),
                    dry_run=False,
                ).model_dump(mode="json")
            }
        fail(ctx, as_json=as_json, error_type=exc.error_type, message=str(exc), extra=extra)
        return
    except train.TrainReconstructionError as exc:
        fail(ctx, as_json=as_json, error_type=exc.error_type, message=str(exc))
        return
    except JournalCorruptionError as exc:
        fail(ctx, as_json=as_json, error_type="journal_corruption", message=str(exc))
        return
    except git.GitError as exc:
        fail(ctx, as_json=as_json, error_type="git_error", message=str(exc))
        return
    except (IssueBackendError, ObjectiveStoreError, TrainPersistenceError, GitHubError) as exc:
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
    payload = ObjectiveStackLandOut.from_outcome(
        result, redirected_from=_redirected_from(objective_id, result.readiness)
    ).model_dump(mode="json")
    emit(as_json=as_json, payload=payload, render=lambda: _render_outcome(result))


def _redirected_from(requested: str | None, readiness: land.LandReadiness) -> str | None:
    """The supersession-redirect fact for the mutation envelopes: the reconstruction follows
    ``superseded_by`` forward, so a requested id differing from the readiness's ACTIVE
    objective id was redirected (the dry-run path's ``redirected_from`` semantics)."""
    if requested is None:
        return None
    if requested.removeprefix("#") == readiness.objective_id.removeprefix("#"):
        return None
    return requested
