"""`perk objective doctor` — detect (and optionally repair) objective drift, in two parts.

**Part 1 (manifest drift)**: build the observed snapshot, diff it against the persisted
``objective-manifest`` baseline, and report every drift condition (the Linear-Project surface;
GitHub objectives have no divergence surface, so this part is trivially empty). **Part 2 (train
diagnosis, §8.54)**: read the exact ``DeliveryTrain`` projection through ``Delivery.status``
on every backend and
report its findings annotated with the deterministic diagnosis policy
(:mod:`perk.delivery.diagnostics` — severity / repairability / remediation). A third,
**report-only** check rides along: the both-headers kind-corruption signature over the
objective's issue-tier carrier (§8.43 ``journal_carrier_id`` + a presence-only ``read_issue``)
— detected findings ride the ``corruption`` field, never any repair batch, and keep exit 0.

Both parts target ONE active objective: the requested id resolves forward through
``train.resolve_active_objective`` (``objective`` reports the active id; ``redirected_from``
preserves the requested id); a predecessor is never mutated by ``doctor OLD --fix``.

``--fix`` applies the safe manifest repairs first (existing behavior), then exactly ONE narrow
train repair — persisting a safely-projected native cancellation into the node attachment via
the conditional ``NativeCancellationMetadataWriter`` (fresh proof immediately before each
compare-and-write, post-write verification, compensation on drift). It never repairs plan
identity, checkpoints, journal history, branches, PRs, or native stack membership. ``--dry-run``
plans both repair batches without any write.

Supervisor surface: ``--json`` → stdout, human → stderr; exit ``0`` clean report / ``1``
op-failure, an aborted repair, or an unavailable train / ``2`` not-a-repo. An assembled report
keeps top-level ``success`` true — the exit code conveys unavailability/aborted repair.
"""

import json
from pathlib import Path

import click
from pydantic import SerializerFunctionWrapHandler, model_serializer

from perk.backends import resolve
from perk.backends.issue_backend import IssueBackendError
from perk.backends.objective_store import (
    DriftCondition,
    ObjectiveStore,
    ObjectiveStoreError,
    RepairAction,
    RepairResult,
)
from perk.boundary import OutputModel
from perk.cli.alias import alias
from perk.cli.commands.objective.shared import parse_objective_id
from perk.cli.context import require_github, require_repo
from perk.cli.emit import fail
from perk.cli.ensure import UserFacingCliError
from perk.delivery import (
    Delivery,
    DeliveryError,
    StatusRequest,
    diagnostics,
    observe,
    resolve_delivery,
)
from perk.delivery import train as train_mod
from perk.delivery.persistence import TrainPersistenceError
from perk.delivery.train import TrainReconstructionError, TrainStatus
from perk.substrate.output import machine_output, user_output

# ----------------------------------------------------------------- output models
# Private OutputModels: field declaration order is load-bearing (the machine surface's key
# order) — do not reorder.


class _TrainFindingOut(OutputModel):
    code: str
    severity: str
    node_id: str | None
    plan_id: str | None
    message: str
    repairable: bool
    remediation: str | None


class _TrainDiagnosisOut(OutputModel):
    state: str  # stacked | incremental | unavailable
    objective_id: str
    redirected_from: str | None
    error_type: str | None
    message: str | None
    blockers: tuple[_TrainFindingOut, ...]
    information: tuple[_TrainFindingOut, ...]


class _TrainRepairActionOut(OutputModel):
    code: str
    node_id: str
    outcome: str  # applied | would_apply | skipped | failed
    error: str | None


class _TrainFixOut(OutputModel):
    state: str  # completed | aborted | skipped_manifest_abort | unavailable
    applied: tuple[_TrainRepairActionOut, ...]
    skipped: tuple[_TrainRepairActionOut, ...]
    failed: _TrainRepairActionOut | None
    remaining: tuple[_TrainFindingOut, ...]
    aborted: bool
    dry_run: bool


def _finding_out(
    finding: train_mod.TrainFinding, *, objective_id: str, repairable_nodes: frozenset[str]
) -> _TrainFindingOut:
    policy = diagnostics.classify_finding(
        finding, objective_id=objective_id, repairable_nodes=repairable_nodes
    )
    return _TrainFindingOut(
        code=finding.code,
        severity=policy.severity,
        node_id=finding.node_id,
        plan_id=finding.plan_id,
        message=finding.message,
        repairable=policy.repairable,
        remediation=policy.remediation,
    )


def _reconstruct_normalized(repo_root: Path, active_id: str) -> TrainStatus:
    """One reconstruction with every EXPECTED authority-read failure normalized onto the
    typed ``TrainReconstructionError`` (the same backend-read translation the stack-status
    boundary applies) — a routine plan/journal/store outage becomes the modeled
    ``unavailable`` diagnosis (or the repair pass's unavailable arm), never an escape."""
    try:
        return observe.reconstruct_repo_train(repo_root, active_id)
    except (IssueBackendError, ObjectiveStoreError, TrainPersistenceError) as exc:
        raise TrainReconstructionError(str(exc), error_type="github_error") from exc


def _diagnose_train(
    delivery: Delivery, active_id: str, *, redirected_from: str | None
) -> _TrainDiagnosisOut:
    """One façade-backed diagnosis: stacked carries policy-annotated findings; incremental
    carries the no-train message; a typed status failure is the ``unavailable`` report arm."""
    try:
        result = delivery.status(StatusRequest(objective_id=active_id))
    except DeliveryError as exc:
        return _TrainDiagnosisOut(
            state="unavailable",
            objective_id=active_id,
            redirected_from=redirected_from,
            error_type=exc.error_type,
            message=str(exc),
            blockers=(),
            information=(),
        )
    status = result.train
    if status is None:
        return _TrainDiagnosisOut(
            state="incremental",
            objective_id=result.objective_id,
            redirected_from=redirected_from,
            error_type=None,
            message=result.no_train_reason,
            blockers=(),
            information=(),
        )
    repairable = frozenset(fact.node_id for fact in status.repairable_canceled_nodes)
    return _TrainDiagnosisOut(
        state="stacked",
        objective_id=status.objective_id,
        redirected_from=redirected_from,
        error_type=None,
        message=None,
        blockers=tuple(
            _finding_out(f, objective_id=active_id, repairable_nodes=repairable)
            for f in status.blockers
        ),
        information=tuple(
            _finding_out(f, objective_id=active_id, repairable_nodes=repairable)
            for f in status.information
        ),
    )


def _action_out(action: diagnostics.CancellationRepairAction) -> _TrainRepairActionOut:
    return _TrainRepairActionOut(
        code=action.code, node_id=action.node_id, outcome=action.outcome, error=action.error
    )


def _run_train_fix(
    repo_root: Path,
    active_id: str,
    store: ObjectiveStore,
    delivery: Delivery,
    *,
    current: _TrainDiagnosisOut,
    redirected_from: str | None,
    dry_run: bool,
) -> _TrainFixOut:
    """The train side of ``--fix``: the per-candidate conditional cancellation repair (only a
    store satisfying the writer seam can carry candidates), then the FINAL diagnosis in
    ``remaining``."""
    if current.state == "unavailable":
        return _TrainFixOut(
            state="unavailable",
            applied=(),
            skipped=(),
            failed=None,
            remaining=(),
            aborted=True,
            dry_run=dry_run,
        )
    if current.state == "incremental":
        # No train, no candidates, nothing failed — a completed empty pass.
        return _TrainFixOut(
            state="completed",
            applied=(),
            skipped=(),
            failed=None,
            remaining=(),
            aborted=False,
            dry_run=dry_run,
        )
    if isinstance(store, diagnostics.NativeCancellationMetadataWriter):
        result = diagnostics.repair_projected_cancellations(
            active_id,
            writer=store,
            reconstruct=lambda: _reconstruct_normalized(repo_root, active_id),
            dry_run=dry_run,
        )
    else:
        # Only the Linear project store observes native cancellations, so a non-writer store
        # can never carry a repairable candidate — an empty completed pass.
        result = diagnostics.CancellationRepairResult(
            actions=(), failed=None, aborted=False, dry_run=dry_run
        )
    final = _diagnose_train(delivery, active_id, redirected_from=redirected_from)
    remaining = final.blockers + final.information
    applied = tuple(
        _action_out(a) for a in result.actions if a.outcome in ("applied", "would_apply")
    )
    skipped = tuple(_action_out(a) for a in result.actions if a.outcome == "skipped")
    failed = _action_out(result.failed) if result.failed is not None else None
    if result.unavailable is not None or final.state == "unavailable":
        state = "unavailable"
        aborted = True
    elif result.aborted:
        state = "aborted"
        aborted = True
    else:
        state = "completed"
        aborted = False
    return _TrainFixOut(
        state=state,
        applied=applied,
        skipped=skipped,
        failed=failed,
        remaining=remaining,
        aborted=aborted,
        dry_run=dry_run,
    )


# ----------------------------------------------------------------- manifest serialization


class _DriftConditionOut(OutputModel):
    code: str
    severity: str
    node_id: str | None
    target: str | None
    message: str
    repairable: bool


class _RepairActionOut(OutputModel):
    """One manifest repair action. ``error`` carries the write-failure message on the
    **failed** action only — the key is omitted entirely when ``None`` (contracts.md
    §8.54's documented conditionality; the emission is byte-identical to the historical
    hand-built payload)."""

    code: str
    node_id: str | None
    error: str | None = None

    @model_serializer(mode="wrap")
    def _omit_null_error(self, handler: SerializerFunctionWrapHandler):
        # §8.54 documents `error` as present on the failed action only; preserve that
        # conditional omission byte-for-byte. Deliberately no return annotation: an
        # annotated wrap serializer collapses the serialization JSON schema to a bare
        # object, while unannotated keeps the per-field detail. Caveat (recorded in the
        # failure-hardening ledger): the snapshotted schema still declares `error` as a
        # nullable property — it cannot express the conditional omission, so the snapshot
        # is a drift tripwire, not an instance validator.
        payload = handler(self)
        if self.error is None:
            del payload["error"]
        return payload


class _RepairResultOut(OutputModel):
    applied: tuple[_RepairActionOut, ...]
    failed: _RepairActionOut | None
    remaining: tuple[_DriftConditionOut, ...]
    aborted: bool
    dry_run: bool


class _CorruptionFindingOut(OutputModel):
    """One kind-corruption finding over the objective's issue-tier carrier (report-only —
    ``--fix`` never touches it; no repair code path exists)."""

    code: str  # "both_headers"
    carrier: str  # the resolved issue-tier carrier id that was checked
    message: str
    remediation: str


class ObjectiveDoctorOut(OutputModel):
    """The ``perk objective doctor --json`` report envelope (contracts.md §8.54). Field
    declaration order is load-bearing (the machine surface's exact key order) — do not
    reorder. The failure envelope stays the shared ``fail(...)`` path."""

    success: bool
    error_type: str | None
    objective: str
    drift: tuple[_DriftConditionOut, ...]
    fix: _RepairResultOut | None
    redirected_from: str | None
    train: _TrainDiagnosisOut
    train_fix: _TrainFixOut | None
    corruption: tuple[_CorruptionFindingOut, ...]


def _detect_kind_corruption(
    store: ObjectiveStore, repo_root: Path, active_id: str
) -> tuple[_CorruptionFindingOut, ...]:
    """The both-headers corruption-signature check (report-only): resolve the objective's
    issue-tier carrier via ``journal_carrier_id`` (§8.43 — GitHub → the objective issue,
    Linear project store → the metadata sentinel issue's identifier) and read it
    **presence-only** (``read_issue`` — never ``get_plan``, whose header-``pr`` chase could
    abort the whole report on a PR-lookup infra failure). A carrier bearing BOTH
    objective-header and plan-header is the kind-corruption signature — exactly one finding;
    a healthy or unresolvable carrier yields ``()``. Direction-neutral: the signature cannot
    prove which header is the stray one. Cost: up to two bounded reads per report."""
    carrier = store.journal_carrier_id(objective_id=active_id)
    if carrier is None:
        return ()
    read = resolve.resolve_issue_backend(repo_root).read_issue(issue_id=carrier)
    if read is None or not (read.already_plan and read.already_objective):
        return ()
    return (
        _CorruptionFindingOut(
            code="both_headers",
            carrier=carrier,
            message=(
                f"issue-tier carrier #{carrier} bears BOTH objective-header and plan-header — "
                "one header was stamped onto the wrong kind of carrier (the kind-corruption "
                "signature; the stray side is not provable from the carrier alone)"
            ),
            remediation=(
                "report-only, no automatic repair: inspect provenance (issue history; each "
                "header's run_id) to identify the stray header and remove it manually — or, "
                "when the objective side is the live one, retire the carrier by superseding "
                f"it (perk objective replan {active_id})"
            ),
        ),
    )


def _condition_out(cond: DriftCondition) -> _DriftConditionOut:
    return _DriftConditionOut(
        code=cond.code.value,
        severity=cond.severity.value,
        node_id=cond.node_id,
        target=cond.target,
        message=cond.message,
        repairable=cond.repairable,
    )


def _repair_action_out(action: RepairAction) -> _RepairActionOut:
    return _RepairActionOut(code=action.code.value, node_id=action.node_id, error=action.error)


def _repair_result_out(result: RepairResult) -> _RepairResultOut:
    return _RepairResultOut(
        applied=tuple(_repair_action_out(a) for a in result.applied),
        failed=_repair_action_out(result.failed) if result.failed is not None else None,
        remaining=tuple(_condition_out(c) for c in result.remaining),
        aborted=result.aborted,
        dry_run=result.dry_run,
    )


# ----------------------------------------------------------------- the command


@alias("doc")
@click.command("doctor")
@click.argument("number")
@click.option("--fix", is_flag=True, help="Apply the safe, unambiguous repairs (else report only).")
@click.option("--dry-run", is_flag=True, help="With --fix: plan the repairs without writing.")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable report to stdout.")
@click.pass_context
def doctor_objective(
    ctx: click.Context, *, number: str, fix: bool, dry_run: bool, as_json: bool
) -> None:
    """Detect (and with ``--fix`` repair) manifest drift AND delivery-train findings."""
    try:
        repo_root = require_repo(ctx)
        number = parse_objective_id(number)
        store = resolve.resolve_objective_store(repo_root)
        delivery = resolve_delivery(repo_root)
        # ONE active-objective resolution for both report parts (a superseded id redirects
        # forward; the predecessor is never targeted, read or written).
        state, redirected_from = train_mod.resolve_active_objective(store, number)
        active_id = state.id
        report = store.detect_objective_drift(objective_id=active_id)
        corruption = _detect_kind_corruption(store, repo_root, active_id)
    except IssueBackendError as exc:
        fail(ctx, as_json=as_json, error_type="github_error", message=str(exc))
        return
    except TrainReconstructionError as exc:
        fail(ctx, as_json=as_json, error_type=exc.error_type, message=str(exc))
        return
    except ObjectiveStoreError as exc:
        message = str(exc)
        error_type = "objective_missing" if "not found" in message else "github_error"
        fail(ctx, as_json=as_json, error_type=error_type, message=message)
        return
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return

    train_diag = _diagnose_train(delivery, active_id, redirected_from=redirected_from)

    fix_result: RepairResult | None = None
    train_fix: _TrainFixOut | None = None
    if fix:
        try:
            if not dry_run:
                require_github(ctx)
            fix_result = store.repair_objective_drift(objective_id=active_id, dry_run=dry_run)
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
        if fix_result.aborted:
            # The manifest repair aborted first: no train action runs; the initial train
            # diagnosis remains the report.
            train_fix = _TrainFixOut(
                state="skipped_manifest_abort",
                applied=(),
                skipped=(),
                failed=None,
                remaining=train_diag.blockers + train_diag.information,
                aborted=True,
                dry_run=dry_run,
            )
        else:
            current = train_diag
            if fix_result.applied and not dry_run:
                # The manifest changed — re-diagnose before any train action.
                current = _diagnose_train(delivery, active_id, redirected_from=redirected_from)
            train_fix = _run_train_fix(
                repo_root,
                active_id,
                store,
                delivery,
                current=current,
                redirected_from=redirected_from,
                dry_run=dry_run,
            )

    out = ObjectiveDoctorOut(
        success=True,
        error_type=None,
        objective=active_id,
        drift=tuple(_condition_out(c) for c in report.conditions),
        fix=_repair_result_out(fix_result) if fix_result is not None else None,
        redirected_from=redirected_from,
        train=train_diag,
        train_fix=train_fix,
        corruption=corruption,
    )
    if as_json:
        machine_output(json.dumps(out.model_dump(mode="json")))
    else:
        _render_human(active_id, report.conditions, fix_result, train_diag, train_fix, corruption)

    # The exit code conveys unavailability / an aborted repair (the assembled report stays
    # success=true): a failed repairable write, an aborted train repair, or an unavailable
    # train exits 1; report-only drift/findings are a clean report → exit 0.
    if (
        train_diag.state == "unavailable"
        or (fix_result is not None and fix_result.aborted)
        or (train_fix is not None and train_fix.aborted)
    ):
        ctx.exit(1)


def _render_human(
    number: str,
    conditions: tuple[DriftCondition, ...],
    fix_result: RepairResult | None,
    train_diag: _TrainDiagnosisOut,
    train_fix: _TrainFixOut | None,
    corruption: tuple[_CorruptionFindingOut, ...],
) -> None:
    if train_diag.redirected_from is not None:
        user_output(f"Objective #{train_diag.redirected_from} → active objective #{number}")
    # --- part 1: manifest drift ---
    if not conditions:
        user_output(click.style("✓ ", fg="green") + f"Objective #{number}: no manifest drift")
    else:
        user_output(f"Objective #{number}: {len(conditions)} manifest drift condition(s)")
        for cond in conditions:
            colour = {"error": "red", "warning": "yellow", "info": "cyan"}.get(
                cond.severity.value, "white"
            )
            tag = click.style(cond.severity.value.upper(), fg=colour)
            where = f" [{cond.node_id}]" if cond.node_id else ""
            user_output(f"  {tag} {cond.code.value}{where}: {cond.message}")
    if fix_result is not None:
        verb = "would apply" if fix_result.dry_run else "applied"
        user_output(f"  fix: {verb} {len(fix_result.applied)} repair(s)")
        if fix_result.failed is not None:
            user_output(
                click.style("  fix aborted: ", fg="red")
                + f"{fix_result.failed.code.value}: {fix_result.failed.error}"
            )
    # --- the both-headers corruption signature (printed ONLY when detected — clean runs'
    # output stays byte-unchanged; report-only findings keep the report clean: exit 0) ---
    if corruption:
        user_output(f"Corruption: {len(corruption)} finding(s)")
        for finding in corruption:
            tag = click.style("ERROR", fg="red")
            user_output(f"  {tag} {finding.code} [#{finding.carrier}]: {finding.message}")
            user_output(f"    remediation: {finding.remediation}")
    # --- part 2: the delivery train ---
    if train_diag.state == "incremental":
        user_output(click.style("✓ ", fg="green") + f"Train: {train_diag.message}")
    elif train_diag.state == "unavailable":
        user_output(
            click.style("Train unavailable: ", fg="red")
            + f"[{train_diag.error_type}] {train_diag.message}"
        )
    else:
        findings = [*train_diag.blockers, *train_diag.information]
        if not findings:
            user_output(click.style("✓ ", fg="green") + "Train: no findings")
        else:
            user_output(f"Train: {len(findings)} finding(s)")
            for finding in findings:
                colour = {"error": "red", "warning": "yellow", "info": "cyan"}.get(
                    finding.severity, "white"
                )
                tag = click.style(finding.severity.upper(), fg=colour)
                where = f" [{finding.node_id}]" if finding.node_id else ""
                user_output(f"  {tag} {finding.code}{where}: {finding.message}")
                if finding.remediation is not None:
                    user_output(f"    remediation: {finding.remediation}")
    if train_fix is not None:
        verb = "would apply" if train_fix.dry_run else "applied"
        user_output(
            f"  train fix ({train_fix.state}): {verb} {len(train_fix.applied)} repair(s), "
            f"{len(train_fix.skipped)} skipped"
        )
        if train_fix.failed is not None:
            user_output(
                click.style("  train fix failed: ", fg="red")
                + f"{train_fix.failed.node_id}: {train_fix.failed.error}"
            )
