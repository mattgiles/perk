"""The delivery **landing** operation — the journaled atomic merge (contracts.md §8.56).

``land_train`` is a thin consumer of the §8.55 readiness projection
(:func:`perk.delivery.land.assess_land_readiness`, consumed as-is — never re-derived) plus the
§8.43 journal (:mod:`perk.delivery.journal` / :mod:`perk.delivery.persistence`), the
per-layer finalize seam (:func:`perk.delivery.finalize.finalize_landed_plan`), and the
machine-local operation lock (:mod:`perk.delivery.oplock`). A multi-layer train lands through
GitHub's atomic async stack merge (submit → verified ``accepted`` handle → bounded poll); the
dynamic singleton lands through an ordinary SHA-pinned direct squash merge (never in a native
stack; merge-async preview enrollment must not be required — and no ``accepted`` event ever:
the journal's ``accepted`` stays async-UUID-only).

Journal-first discipline (§8.56): ``prepared`` (read back) → submit → ``accepted`` only after
the returned options verify against the prepared request → a terminal outcome only for a
verified terminal observation. ``abandoned`` only with proof (every layer PR re-observed OPEN
at its exact expected head); an unprovable state stays unresolved (``outcome: pending`` —
``perk objective stack recover`` classifies and concludes it, §8.51). Invariant 20: once
per-PR merge verification succeeds, a
failed/ambiguous ``completed`` append or a finalize failure degrades to loud ``notes`` on an
``outcome: "merged"`` result — never an error exit.

Injection shape mirrors :mod:`perk.delivery.sync`: one public entry with keyword-injectable
seams defaulting to production wiring; Protocol-sized fakes in tests.
"""

import time
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from perk import objective, plan
from perk.backends import resolve
from perk.backends.issue_backend import IssueBackendError, PlanState
from perk.backends.objective_store import ObjectiveState, ObjectiveStoreError
from perk.delivery import land, land_records, observe, oplock
from perk.delivery.finalize import LandedPlan, LandFinalization, finalize_landed_plan
from perk.delivery.journal import (
    EventRole,
    JournalCorruptionError,
    JournalFold,
    OperationKind,
    OutcomeRecord,
    PreparedRecord,
    mint_operation_id,
)
from perk.delivery.persistence import (
    AppendResult,
    TrainPersistenceError,
    resolve_train_persistence,
)
from perk.delivery.train import DeliveryTrain, NoDeliveryTrain, TrainStatus
from perk.delivery.writers import RemoteWriterProbe
from perk.github import GitHubError, stacks

# The bounded async-merge poll: up to 60 ticks, one injected second apart — a stack merge
# normally concludes well inside a minute; exhaustion is the honest `pending` arm (the
# operation stays unresolved; `perk objective stack recover` concludes it).
_POLL_TICKS = 60
_POLL_DELAY_SECONDS = 1.0

# Bound the failure text carried in an `abandoned` event's observed payload (message
# material inside a journal event, never a payload the fold classifies from).
_ABANDON_DETAIL_CAP = 500

# The strict LAND payload read models live in the pure leaf `land_records` (train's coverage
# join must decode them too, and train cannot import this module) — re-exported here because
# the payload vocabulary is landing-owned (contracts.md §8.56).
LandPrepared = land_records.LandPrepared
LandPreparedBefore = land_records.LandPreparedBefore
LandPreparedAfter = land_records.LandPreparedAfter
LandPreparedLayer = land_records.LandPreparedLayer
LandAcceptedObserved = land_records.LandAcceptedObserved
LandCompletedObserved = land_records.LandCompletedObserved
LandCompletedLayer = land_records.LandCompletedLayer
LandRemainderPr = land_records.LandRemainderPr
LandAbandonedObserved = land_records.LandAbandonedObserved
decode_land_prepared = land_records.decode_land_prepared
decode_land_accepted = land_records.decode_land_accepted
decode_land_completed = land_records.decode_land_completed
decode_land_abandoned = land_records.decode_land_abandoned

type LandOutcomeKind = Literal[
    "merged", "pending", "unexpected_enqueued", "completed_without_merge", "declined"
]


class LandError(Exception):
    """A landing refused or failed with a typed cause. ``error_type`` is the stable machine
    code the CLI boundary maps onto its failure envelope; ``readiness`` rides along on
    ``land_blocked`` so the CLI can render the full report and attach it to the fail
    envelope."""

    def __init__(
        self,
        message: str,
        *,
        error_type: str,  # not_stacked | land_blocked | land_drift | land_failed
        # | merge_async_unavailable | merge_request_conflict | plan_not_found
        # | operation_in_progress | confirmation_required (contracts.md §8.56;
        # reconstruction/persistence/backend errors keep their existing typed passthrough
        # at the CLI boundary, mirroring sync_cmd)
        readiness: land.LandReadiness | None = None,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.readiness = readiness


@dataclass(frozen=True)
class LandedLayer:
    """One verified-merged layer. ``finalization`` is ``None`` when the per-layer finalize
    failed (the failure text goes to the outcome's ``notes`` — invariant 20).
    ``base_sha``/``head_sha`` are the layer's recorded incremental diff bounds (from the
    land-plan layer) — the reconcile-evidence identity."""

    node_id: str
    plan_id: str
    pr_number: int
    merge_commit_sha: str
    finalization: LandFinalization | None
    base_sha: str
    head_sha: str


@dataclass(frozen=True)
class LandEvidenceLayer:
    """One reconcile-evidence layer row: PR identity, the incremental base/head SHAs, and
    the observed merge commit — everything the reconcile pass needs to recover the exact
    diff later (PR APIs / Git objects / pull refs; patches are never stored)."""

    node_id: str
    plan_id: str
    pr_number: int
    base_sha: str
    head_sha: str
    merge_commit_sha: str


@dataclass(frozen=True)
class LandEvidence:
    """The ordered reconcile evidence (contracts.md §8.56), assembled FRESH from all
    completed LAND records in fold order on every close transition — never from an
    invocation's action rows (close-only retries and multi-operation breach flows must
    carry the full history). ``partial`` marks an undecodable record (loud, never a crash
    at close time); ``final_base_sha`` is the LAST completed record's value."""

    layers: tuple[LandEvidenceLayer, ...]
    final_base_sha: str | None
    partial: bool
    notes: tuple[str, ...]


def assemble_land_evidence(fold: JournalFold) -> LandEvidence:
    """Walk ALL completed LAND records in fold order (delivery order by construction —
    breach prefix records first, remainder records after), join each completed layer to its
    operation's strict prepared layer by ``pr_number``, and yield the ordered evidence.
    Pure; undecodable records mark the evidence ``partial`` with a loud note."""
    layers: list[LandEvidenceLayer] = []
    notes: list[str] = []
    partial = False
    final_base_sha: str | None = None
    for op in fold.operations.values():
        if op.kind is not OperationKind.LAND or op.terminal_role is not EventRole.COMPLETED:
            continue
        prepared_record = op.prepared.record
        outcome = op.outcome.record if op.outcome is not None else None
        try:
            if not isinstance(prepared_record, PreparedRecord) or not isinstance(
                outcome, OutcomeRecord
            ):  # unreachable by fold construction; fail closed
                raise JournalCorruptionError(
                    f"operation {op.operation_id} folds without prepared/outcome records"
                )
            prepared = land_records.decode_land_prepared(prepared_record)
            completed = land_records.decode_land_completed(
                outcome.observed, operation_id=op.operation_id
            )
        except JournalCorruptionError as exc:
            partial = True
            notes.append(
                f"reconcile evidence is PARTIAL: LAND operation {op.operation_id} is "
                f"undecodable ({exc})"
            )
            continue
        prepared_by_pr = {layer.pr_number: layer for layer in prepared.before.layers}
        for row in completed.layers:
            joined = prepared_by_pr.get(row.pr_number)
            if joined is None:
                partial = True
                notes.append(
                    f"reconcile evidence is PARTIAL: LAND operation {op.operation_id} "
                    f"completed PR #{row.pr_number} joins no prepared layer"
                )
                continue
            layers.append(
                LandEvidenceLayer(
                    node_id=joined.node_id,
                    plan_id=joined.plan_id,
                    pr_number=joined.pr_number,
                    base_sha=joined.base_sha,
                    head_sha=joined.head_sha,
                    merge_commit_sha=row.merge_commit_sha,
                )
            )
        final_base_sha = completed.final_base_sha
    return LandEvidence(
        layers=tuple(layers), final_base_sha=final_base_sha, partial=partial, notes=tuple(notes)
    )


@dataclass(frozen=True)
class LandOutcome:
    """The honest result of one landing invocation (every arm is exit 0 at the CLI).

    ``pending`` / ``unexpected_enqueued`` mean the LAND operation stays **unresolved** —
    never success, never failure (``perk objective stack recover`` concludes it).
    ``merged`` is only reported after per-PR verification (invariant 20). ``notes`` are
    loud human-facing detail lines, never failures. ``objective_closed`` reports a REAL
    close transition (state-aware — a rerun on a closed objective reads ``False``);
    ``reconcile_evidence`` rides every close transition, assembled fresh from the journal
    (``None`` when nothing closed or the fold was unreadable).
    """

    outcome: LandOutcomeKind
    readiness: land.LandReadiness
    operation_id: str | None
    merge_async_uuid: str | None
    landed_layers: tuple[LandedLayer, ...]
    objective_closed: bool
    notes: tuple[str, ...]
    reconcile_evidence: LandEvidence | None = None


def squash_commit_message(*, issue: str, url: str, backend_id: str, title: str) -> str:
    """The deepened squash commit message: plain ``"<plan title>\\n\\n<footer>"``.

    The footer branches per backend: GitHub keeps ``Closes #N`` (the autoclose target —
    byte-identical to the pre-Linear shape); non-github backends get a plain
    ``Plan: <id> — <url>`` reference line — NO commit magic words (Linear's commit-linking
    needs a non-assumable extra webhook; perk closes the plan issue explicitly at land
    instead). Plain text only, so no HTML leaks into ``git log``; an empty title falls back
    to the bare footer. Shared by the incremental ``perk pr land`` and the stacked
    singleton's direct squash (one implementation, no drift).
    """
    footer = f"Closes #{issue}" if backend_id == "github" else f"Plan: {issue} — {url}"
    cleaned = title.strip()
    return f"{cleaned}\n\n{footer}" if cleaned else footer


# ----------------------------------------------------------------- injected-seam protocols


class LandPersistence(Protocol):
    """The narrow journal surface landing needs (structurally satisfied by
    :func:`resolve_train_persistence`'s adapter). ``read_journal`` feeds the fresh
    reconcile-evidence assembly on a close transition."""

    def append_prepared(self, objective_id: str, record: PreparedRecord) -> AppendResult: ...

    def append_outcome(self, objective_id: str, record: OutcomeRecord) -> AppendResult: ...

    def read_journal(self, objective_id: str) -> JournalFold: ...


class LandIssueReads(Protocol):
    """The narrow issue-backend surface landing needs (structurally satisfied by every
    :class:`~perk.backends.issue_backend.IssueBackend`): the load-bearing pre-merge plan
    read plus the backend identity the squash footer branches on."""

    backend_id: str

    def get_plan(self, *, issue_id: str) -> PlanState | None: ...


class LandObjectiveStore(Protocol):
    """The narrow objective-store surface landing needs (structurally satisfied by every
    :class:`~perk.backends.objective_store.ObjectiveStore`): the aggregate-close re-fetch
    and the close itself."""

    def get_objective(self, *, objective_id: str) -> ObjectiveState | None: ...

    def close_objective(self, *, objective_id: str, dry_run: bool = False) -> bool: ...


class _PrFactsRead(Protocol):
    def __call__(self, *, number: int, repo_root: Path) -> stacks.PrDeliveryFacts | None: ...


class _SubmitAsync(Protocol):
    def __call__(
        self, *, number: int, sha: str, repo_root: Path
    ) -> stacks.MergeAsyncSubmitOutcome: ...


class _PollAsync(Protocol):
    def __call__(self, *, number: int, uuid: str, repo_root: Path) -> stacks.MergeAsyncResult: ...


class _MergeDirect(Protocol):
    def __call__(
        self, *, number: int, sha: str, commit_message: str | None, repo_root: Path
    ) -> stacks.DirectMergeOutcome: ...


class _MergedEvidence(Protocol):
    def __call__(self, *, number: int, repo_root: Path) -> stacks.PrMergedEvidence | None: ...


class _Assess(Protocol):
    def __call__(
        self,
        train_projection: DeliveryTrain,
        *,
        observations: land.LandObservations,
        remote_writers: RemoteWriterProbe,
    ) -> land.LandReadiness: ...


class _Finalize(Protocol):
    def __call__(
        self,
        repo_root: Path,
        *,
        landed: LandedPlan,
        pr_base: str,
        close_objective_on_complete: bool = True,
    ) -> LandFinalization: ...


def _default_observations(repo_root: Path, base: str) -> land.LandObservations:
    return observe.GatewayLandObservations(repo_root, base=base)


@dataclass(frozen=True)
class _Landing:
    """The per-invocation bundle: repo, call parameters, and every injected seam."""

    repo_root: Path
    run_id: str
    approve: Callable[[land.LandReadiness], bool] | None
    remote_writers: RemoteWriterProbe
    reconstruct: Callable[[Path, str], TrainStatus]
    observations_factory: Callable[[Path, str], land.LandObservations]
    assess: _Assess
    persistence: LandPersistence
    issues: LandIssueReads
    store: LandObjectiveStore
    pr_facts: _PrFactsRead
    submit_async: _SubmitAsync
    poll_async: _PollAsync
    merge_direct: _MergeDirect
    merged_evidence: _MergedEvidence
    finalize: _Finalize
    sleep: Callable[[float], None]
    now: Callable[[], str]


def land_train(
    repo_root: Path,
    *,
    objective_id: str,
    run_id: str,
    remote_writers: RemoteWriterProbe,
    approve: Callable[[land.LandReadiness], bool] | None = None,
    reconstruct: Callable[[Path, str], TrainStatus] = observe.reconstruct_repo_train,
    observations_factory: Callable[[Path, str], land.LandObservations] = _default_observations,
    assess: _Assess = land.assess_land_readiness,
    persistence_factory: Callable[[Path], LandPersistence] = resolve_train_persistence,
    issues_factory: Callable[[Path], LandIssueReads] = resolve.resolve_issue_backend,
    store_factory: Callable[[Path], LandObjectiveStore] = resolve.resolve_objective_store,
    pr_facts: _PrFactsRead = stacks.pr_delivery_facts,
    submit_async: _SubmitAsync = stacks.submit_merge_async,
    poll_async: _PollAsync = stacks.merge_async_result,
    merge_direct: _MergeDirect = stacks.merge_pr_direct,
    merged_evidence: _MergedEvidence = stacks.pr_merged_evidence,
    finalize: _Finalize = finalize_landed_plan,
    lock: Callable[[Path], AbstractContextManager[None]] = oplock.stack_operation_lock,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], str] = plan.now_iso,
) -> LandOutcome:
    """Land ``objective_id``'s remaining delivery train atomically (the §8.56 operation).

    ``approve`` is the consent gate over the composed :class:`~perk.delivery.land.LandReadiness`
    (``None`` = auto-approve) — it fires for both the READY land plan and the NOTHING_TO_LAND
    completion preview; ``remote_writers`` is the required fail-closed writer preflight
    (consumed by the readiness assessment — there is deliberately no default). Raises
    :class:`LandError` on every typed refusal; reconstruction/persistence/backend errors
    propagate for the CLI boundary's existing arms, always leaving any prepared operation
    unresolved (recoverable).
    """
    landing = _Landing(
        repo_root=repo_root,
        run_id=run_id,
        approve=approve,
        remote_writers=remote_writers,
        reconstruct=reconstruct,
        observations_factory=observations_factory,
        assess=assess,
        persistence=persistence_factory(repo_root),
        issues=issues_factory(repo_root),
        store=store_factory(repo_root),
        pr_facts=pr_facts,
        submit_async=submit_async,
        poll_async=poll_async,
        merge_direct=merge_direct,
        merged_evidence=merged_evidence,
        finalize=finalize,
        sleep=sleep,
        now=now,
    )
    try:
        with lock(repo_root):
            return _land(landing, objective_id)
    except oplock.OperationLockBusy as exc:
        raise LandError(str(exc), error_type="operation_in_progress") from exc


# ----------------------------------------------------------------- the protocol


def _land(b: _Landing, objective_id: str) -> LandOutcome:
    # 1./2. Reconstruct + require a journalable lineage.
    status = b.reconstruct(b.repo_root, objective_id)
    if isinstance(status, NoDeliveryTrain):
        raise LandError(
            f"objective {status.objective_id} has no delivery train ({status.reason})",
            error_type="not_stacked",
        )
    if status.delivery_lineage is None:
        raise LandError(
            f"objective {status.objective_id} carries no delivery_lineage — landing cannot "
            "be journaled",
            error_type="not_stacked",
        )
    lineage = status.delivery_lineage

    # 3. Assess — the §8.55 projection, consumed as-is.
    readiness = b.assess(
        status,
        observations=b.observations_factory(b.repo_root, status.base),
        remote_writers=b.remote_writers,
    )

    # 4. NOTHING_TO_LAND: the confirmed completion-without-merge (no journal — no remote
    # train mutation to guard; the close is idempotent/convergent).
    if readiness.disposition is land.LandDisposition.NOTHING_TO_LAND:
        if b.approve is not None and not b.approve(readiness):
            return _outcome(readiness, "declined")
        # The close is this arm's PRIMARY effect — a failure here is a typed store error
        # propagating to the CLI ladder, never fail-open. State-aware (§8.44's lifecycle
        # read): only an OPEN objective transitions; a rerun on a closed one honestly
        # reports objective_closed: false.
        notes: list[str] = []
        state = b.store.get_objective(objective_id=readiness.objective_id)
        closed = False
        if state is None:
            notes.append(
                f"objective #{readiness.objective_id} could not be re-fetched for the close "
                "— nothing was closed"
            )
        elif state.state == "open":
            b.store.close_objective(objective_id=readiness.objective_id)
            closed = True
        else:
            notes.append(f"objective #{readiness.objective_id} is already closed")
        evidence = _read_evidence(b, readiness.objective_id, notes) if closed else None
        return _outcome(
            readiness,
            "completed_without_merge",
            objective_closed=closed,
            notes=tuple(notes),
            reconcile_evidence=evidence,
        )

    # 5. BLOCKED: the typed refusal carrying the full readiness report.
    if readiness.disposition is land.LandDisposition.BLOCKED or readiness.plan is None:
        blockers = "; ".join(f"[{f.code}] {f.message}" for f in readiness.blockers)
        raise LandError(
            f"objective {readiness.objective_id} is not ready to land: {blockers or 'blocked'}",
            error_type="land_blocked",
            readiness=readiness,
        )
    land_plan = readiness.plan

    # 6. READY. The singleton's load-bearing pre-merge plan read (squash title/url +
    # consumed_learn) happens BEFORE consent so a missing plan refuses cleanly.
    singleton_message: str | None = None
    singleton_consumed: tuple[str, ...] | None = None
    if land_plan.mode == "singleton_squash":
        sole = land_plan.layers[0]
        state = b.issues.get_plan(issue_id=sole.plan_id)
        if state is None:
            raise LandError(
                f"plan issue #{sole.plan_id} not found — cannot compose the squash message",
                error_type="plan_not_found",
            )
        singleton_message = squash_commit_message(
            issue=sole.plan_id,
            url=state.url,
            backend_id=b.issues.backend_id,
            title=state.title,
        )
        singleton_consumed = _consumed_learn(state.header)
    if b.approve is not None and not b.approve(readiness):
        return _outcome(readiness, "declined")

    # 7. Re-observe every layer PR after the arbitrary approval pause — any mismatch
    # or read failure is `land_drift` with nothing journaled.
    rows = {row.node_id: row for row in readiness.layers}
    _reobserve(b, land_plan, rows)

    # 8. The prepared record, journal-first (§8.43's read-back discipline; its gates and
    # ambiguity propagate to the CLI ladder).
    operation_id = mint_operation_id()
    b.persistence.append_prepared(
        readiness.objective_id,
        PreparedRecord(
            operation_id=operation_id,
            operation_kind=OperationKind.LAND,
            delivery_lineage=lineage,
            objective_id=readiness.objective_id,
            run_id=b.run_id,
            created=b.now(),
            affected_plans=tuple(layer.plan_id for layer in land_plan.layers),
            before=_before_payload(land_plan, base=readiness.base),
            after=_after_payload(land_plan, base=readiness.base),
        ),
    )

    # 9./10. Submit (+ the async poll).
    if land_plan.mode == "stack_merge_async":
        return _land_async(b, readiness, land_plan, rows, operation_id, consumed=None)
    return _land_singleton(
        b,
        readiness,
        land_plan,
        rows,
        operation_id,
        commit_message=singleton_message,
        consumed=singleton_consumed,
    )


def _land_async(
    b: _Landing,
    readiness: land.LandReadiness,
    land_plan: land.LandPlan,
    rows: Mapping[str, land.LandLayerReadiness],
    operation_id: str,
    *,
    consumed: tuple[str, ...] | None,
) -> LandOutcome:
    """The multi-layer arm: submit the SHA-pinned async merge, verify the returned options,
    record the ``accepted`` handle, poll to a verified terminal observation."""
    submitted = b.submit_async(
        number=land_plan.top_pr_number, sha=land_plan.top_head_sha, repo_root=b.repo_root
    )
    first_ambiguous = _classify_async_submit(submitted) == "ambiguous"
    if first_ambiguous:
        # ONE identical SHA-pinned retry: a 409-pending-with-matching-options recovers the
        # handle (the architecture's ambiguity rule).
        submitted = b.submit_async(
            number=land_plan.top_pr_number, sha=land_plan.top_head_sha, repo_root=b.repo_root
        )
    if first_ambiguous and _classify_async_submit(submitted) not in ("pending", "merged"):
        # The first request may already have created an async job (the PRs can re-observe
        # OPEN while it is still scheduled), so a retry-side 404/422/failed reply proves
        # nothing about the FIRST attempt — only a live matching handle or a merged reply
        # conclusively recovers it. Never abandon here; the operation stays unresolved.
        return _outcome(
            readiness,
            "pending",
            operation_id=operation_id,
            notes=(
                "the async merge submission stayed unproven: the first attempt was "
                "ambiguous and the retry did not conclusively recover it "
                f"(HTTP {submitted.status}, detail: {submitted.raw_detail or 'none'}) — "
                f"the LAND operation {operation_id} is unresolved; landing is blocked "
                "until it concludes",
            ),
        )
    match _classify_async_submit(submitted):
        case "pending":
            if (
                submitted.uuid is None
                or submitted.merge_method != "squash"
                or submitted.merge_action != "direct_merge"
                or submitted.expected_head_sha != land_plan.top_head_sha
            ):
                # The foreign-409 arm (or a mismatching 202 — fail closed either way): an
                # EXISTING merge request whose options differ from ours. No accepted append;
                # the prepared operation stays unresolved — a foreign merge may be in flight.
                raise LandError(
                    f"an existing merge request for PR #{land_plan.top_pr_number} does not "
                    f"match this land plan (uuid={submitted.uuid!r}, "
                    f"merge_method={submitted.merge_method!r}, "
                    f"merge_action={submitted.merge_action!r}, "
                    f"expected_head_sha={submitted.expected_head_sha!r}; expected squash/"
                    f"direct_merge at {land_plan.top_head_sha}) — the LAND operation "
                    f"{operation_id} stays unresolved; investigate before retrying",
                    error_type="merge_request_conflict",
                )
            b.persistence.append_outcome(
                readiness.objective_id,
                OutcomeRecord(
                    operation_id=operation_id,
                    role=EventRole.ACCEPTED,
                    created=b.now(),
                    observed={
                        "uuid": submitted.uuid,
                        "merge_method": submitted.merge_method,
                        "merge_action": submitted.merge_action,
                        "expected_head_sha": submitted.expected_head_sha,
                        "http_status": submitted.status,
                    },
                ),
            )
            return _poll(b, readiness, land_plan, rows, operation_id, submitted.uuid, consumed)
        case "merged":
            # A 200 "already merged" — skip the poll, go straight to verification.
            return _verify_and_finalize(
                b,
                readiness,
                land_plan,
                rows,
                operation_id,
                uuid=None,
                reported_sha=None,
                consumed=consumed,
            )
        case "unavailable":
            return _terminal_non_application(
                b,
                readiness,
                land_plan,
                operation_id,
                uuid=None,
                reason="submit_404",
                detail=submitted.raw_detail,
                error_type="merge_async_unavailable",
                message=(
                    "the async stack-merge endpoint is unavailable for this repository "
                    f"(HTTP 404 on submit for PR #{land_plan.top_pr_number}) — per-repo "
                    "preview enrollment / endpoint availability is observable only at "
                    f"mutation time: {submitted.raw_detail}"
                ),
            )
        case "failed":
            reason = "submit_rejected" if submitted.status == 422 else "submit_failed"
            return _terminal_non_application(
                b,
                readiness,
                land_plan,
                operation_id,
                uuid=None,
                reason=reason,
                detail=submitted.raw_detail,
                error_type="land_failed",
                message=(
                    f"GitHub rejected the async stack merge for PR "
                    f"#{land_plan.top_pr_number} (HTTP {submitted.status}): "
                    f"{submitted.raw_detail}"
                ),
            )
        case _:  # unreachable without a first-attempt ambiguity (guarded above); fail safe
            return _outcome(
                readiness,
                "pending",
                operation_id=operation_id,
                notes=(
                    "the async merge submission stayed ambiguous "
                    f"(HTTP {submitted.status}, detail: {submitted.raw_detail or 'none'}) — "
                    f"the LAND operation {operation_id} is unresolved; landing is blocked "
                    "until it concludes",
                ),
            )


def _classify_async_submit(outcome: stacks.MergeAsyncSubmitOutcome) -> str:
    """The submit-reply classification (§8.56). Only the EXACT protocol status/state pairs
    classify — 202/409 + ``pending``, 200 + ``merged``, 404 (unavailable), 400 + ``failed``
    or a bare 422 (rejected). Every discordant combination — a 5xx carrying any parseable
    state, a body contradicting its status, an unparseable 2xx/409 body, no status at all —
    is ``ambiguous`` (fail closed: a 5xx never proves the merge was or was not scheduled,
    so it must never reach a terminal abandon)."""
    if outcome.state == "pending" and outcome.status in (202, 409):
        return "pending"
    if outcome.state == "merged" and outcome.status == 200:
        return "merged"
    if outcome.status == 404:
        return "unavailable"
    if (outcome.state == "failed" and outcome.status == 400) or outcome.status == 422:
        return "failed"
    return "ambiguous"


def _poll(
    b: _Landing,
    readiness: land.LandReadiness,
    land_plan: land.LandPlan,
    rows: Mapping[str, land.LandLayerReadiness],
    operation_id: str,
    uuid: str,
    consumed: tuple[str, ...] | None,
) -> LandOutcome:
    """The bounded handle poll: pending continues, merged verifies, failed abandons with
    proof, enqueued stops immediately (terminal for the REQUEST, not the train — unresolved),
    per-tick read failures are tolerated within the budget."""
    for tick in range(_POLL_TICKS):
        if tick > 0:
            b.sleep(_POLL_DELAY_SECONDS)
        try:
            result = b.poll_async(number=land_plan.top_pr_number, uuid=uuid, repo_root=b.repo_root)
        except GitHubError:
            continue  # tolerated; counts against the budget
        if result.state == "pending":
            continue
        if result.state == "merged":
            return _verify_and_finalize(
                b,
                readiness,
                land_plan,
                rows,
                operation_id,
                uuid=uuid,
                reported_sha=result.sha,
                consumed=consumed,
            )
        if result.state == "failed":
            return _terminal_non_application(
                b,
                readiness,
                land_plan,
                operation_id,
                uuid=uuid,
                reason="poll_failed",
                detail=result.message,
                error_type="land_failed",
                message=(
                    f"the async stack merge {uuid} for PR #{land_plan.top_pr_number} "
                    f"reported failed: {result.message or 'no detail'}"
                ),
            )
        # enqueued: terminal for the request but NOT for the train — the queue owns the
        # outcome, which contradicts the direct-merge plan; unresolved (`stack recover`
        # concludes it).
        return _outcome(
            readiness,
            "unexpected_enqueued",
            operation_id=operation_id,
            merge_async_uuid=uuid,
            notes=(
                f"the merge request {uuid} was ENQUEUED — a merge queue now owns the "
                f"outcome; the LAND operation {operation_id} is unresolved and landing is "
                "blocked until it concludes (never re-submit; conclude it with "
                "`perk objective stack recover`)",
            ),
        )
    return _outcome(
        readiness,
        "pending",
        operation_id=operation_id,
        merge_async_uuid=uuid,
        notes=(
            f"the async merge {uuid} was still pending after {_POLL_TICKS} poll ticks — "
            f"the LAND operation {operation_id} is unresolved; landing is blocked until it "
            "concludes (conclude it with `perk objective stack recover`)",
        ),
    )


def _land_singleton(
    b: _Landing,
    readiness: land.LandReadiness,
    land_plan: land.LandPlan,
    rows: Mapping[str, land.LandLayerReadiness],
    operation_id: str,
    *,
    commit_message: str | None,
    consumed: tuple[str, ...] | None,
) -> LandOutcome:
    """The dynamic-singleton arm: one ordinary SHA-pinned direct squash merge. No
    ``accepted`` event ever — there is no handle."""
    sole = land_plan.layers[0]
    merged = b.merge_direct(
        number=sole.pr_number,
        sha=sole.head_sha,
        commit_message=commit_message,
        repo_root=b.repo_root,
    )
    first_ambiguous = _classify_direct_merge(merged) == "ambiguous"
    if first_ambiguous:
        # ONE identical retry: the SHA pin + the already-merged idempotent arm make it safe.
        merged = b.merge_direct(
            number=sole.pr_number,
            sha=sole.head_sha,
            commit_message=commit_message,
            repo_root=b.repo_root,
        )
    if first_ambiguous and _classify_direct_merge(merged) != "merged":
        # The first request may already have applied (an applied-but-unconfirmed merge
        # surfaces on the retry as the already-merged arm) — a retry-side rejection proves
        # nothing about the FIRST attempt. Never abandon here; the operation stays
        # unresolved.
        return _outcome(
            readiness,
            "pending",
            operation_id=operation_id,
            notes=(
                "the direct squash merge stayed unproven: the first attempt was ambiguous "
                "and the retry did not conclusively recover it "
                f"(HTTP {merged.status}, detail: {merged.raw_detail or 'none'}) — the LAND "
                f"operation {operation_id} is unresolved; landing is blocked until it "
                "concludes",
            ),
        )
    match _classify_direct_merge(merged):
        case "merged":
            return _verify_and_finalize(
                b,
                readiness,
                land_plan,
                rows,
                operation_id,
                uuid=None,
                reported_sha=merged.sha,
                consumed=consumed,
            )
        case "rejected":
            # Every 4xx is a terminal non-application — the 404 arm too: the legacy merge
            # endpoint exists everywhere, so a missing PR is drift, not availability.
            return _terminal_non_application(
                b,
                readiness,
                land_plan,
                operation_id,
                uuid=None,
                reason="submit_failed",
                detail=merged.raw_detail,
                error_type="land_failed",
                message=(
                    f"GitHub rejected the direct squash merge for PR #{sole.pr_number} "
                    f"(HTTP {merged.status}): {merged.raw_detail}"
                ),
            )
        case _:  # unreachable without a first-attempt ambiguity (guarded above); fail safe
            return _outcome(
                readiness,
                "pending",
                operation_id=operation_id,
                notes=(
                    "the direct squash merge stayed ambiguous "
                    f"(HTTP {merged.status}, detail: {merged.raw_detail or 'none'}) — the "
                    f"LAND operation {operation_id} is unresolved; landing is blocked until "
                    "it concludes",
                ),
            )


def _classify_direct_merge(outcome: stacks.DirectMergeOutcome) -> str:
    """The direct-merge classification: a 4xx is proven non-application; no status / 5xx /
    a 2xx whose body did not parse is ambiguous (the retry's already-merged arm recovers
    an applied-but-unconfirmed first attempt)."""
    if outcome.merged:
        return "merged"
    if outcome.status is not None and 400 <= outcome.status < 500:
        return "rejected"
    return "ambiguous"


# ----------------------------------------------------------------- verification + bookkeeping


def _reobserve(
    b: _Landing, land_plan: land.LandPlan, rows: Mapping[str, land.LandLayerReadiness]
) -> None:
    """The post-approval re-observation: every layer PR OPEN, at its exact expected
    head, onto its expected base ref, on its expected branch — any mismatch or read failure
    is ``land_drift`` with nothing journaled."""
    for layer in land_plan.layers:
        row = rows.get(layer.node_id)
        expected_base = row.expected_base_ref if row is not None else None
        expected_branch = row.branch if row is not None else None
        try:
            facts = b.pr_facts(number=layer.pr_number, repo_root=b.repo_root)
        except GitHubError as exc:
            raise LandError(
                f"could not re-observe PR #{layer.pr_number} (layer {layer.node_id}) after "
                f"approval: {exc} — nothing was journaled; rerun land",
                error_type="land_drift",
            ) from exc
        if (
            facts is None
            or facts.state != "OPEN"
            or facts.head_sha != layer.head_sha
            or expected_base is None
            or facts.base_ref != expected_base
            or expected_branch is None
            or facts.head_ref != expected_branch
        ):
            observed = (
                f"state={facts.state} base={facts.base_ref!r} head-ref={facts.head_ref!r} "
                f"head={facts.head_sha}"
                if facts is not None
                else "absent"
            )
            raise LandError(
                f"PR #{layer.pr_number} (layer {layer.node_id}) drifted after approval: "
                f"observed {observed}, expected OPEN onto {expected_base!r} as "
                f"{expected_branch!r} at {layer.head_sha} — nothing was journaled; rerun "
                "land after reconciling",
                error_type="land_drift",
            )


def _terminal_non_application(
    b: _Landing,
    readiness: land.LandReadiness,
    land_plan: land.LandPlan,
    operation_id: str,
    *,
    uuid: str | None,
    reason: str,
    detail: str,
    error_type: str,
    message: str,
) -> LandOutcome:
    """The abandon-with-proof path (§8.56): a terminal non-application may be journaled
    ``abandoned`` only when every layer PR re-observes OPEN at its exact expected head —
    then the typed failure propagates (retry is legal: the operation is resolved). Any
    contradiction or read failure appends NO outcome and stays the honest ``pending``."""
    reobserved: list[dict[str, object]] = []
    proven = True
    for layer in land_plan.layers:
        try:
            facts = b.pr_facts(number=layer.pr_number, repo_root=b.repo_root)
        except GitHubError:
            proven = False
            break
        if facts is None or facts.state != "OPEN" or facts.head_sha != layer.head_sha:
            proven = False
            break
        reobserved.append(
            {"pr_number": layer.pr_number, "state": facts.state, "head_sha": facts.head_sha}
        )
    if not proven:
        return _outcome(
            readiness,
            "pending",
            operation_id=operation_id,
            merge_async_uuid=uuid,
            notes=(
                f"{message}; the before-state could not be proven (a layer PR did not "
                f"re-observe OPEN at its expected head), so the LAND operation "
                f"{operation_id} stays unresolved — landing is blocked until it concludes",
            ),
        )
    b.persistence.append_outcome(
        readiness.objective_id,
        OutcomeRecord(
            operation_id=operation_id,
            role=EventRole.ABANDONED,
            created=b.now(),
            observed={
                "reason": reason,
                "detail": detail[:_ABANDON_DETAIL_CAP],
                "reobserved": reobserved,
            },
        ),
    )
    raise LandError(message, error_type=error_type)


def _verify_and_finalize(
    b: _Landing,
    readiness: land.LandReadiness,
    land_plan: land.LandPlan,
    rows: Mapping[str, land.LandLayerReadiness],
    operation_id: str,
    *,
    uuid: str | None,
    reported_sha: str | None,
    consumed: tuple[str, ...] | None,
) -> LandOutcome:
    """Per-PR merge verification, the ``completed`` append, per-layer finalization
    bottom→top, and the aggregate objective close. Once verification succeeds the result is
    ``merged`` — every later bookkeeping failure degrades to a loud note (invariant 20).

    Verification corroborates each layer's IDENTITY, not just its MERGED state: the head
    commit must be the approved published head (the re-observe→submit window is not
    zero — a force-pushed lower layer could otherwise merge unnoticed under the top-only
    SHA pin), the head ref must be the published branch, and the merge target must be the
    layer's expected base ref — or the objective base (GitHub retargets a dependent PR onto
    the base when its parent branch is deleted at merge, so both targets are legitimate
    landings of the approved train; any other base fails)."""
    notes: list[str] = []
    verified: list[tuple[land.LandPlanLayer, str]] = []
    for layer in land_plan.layers:
        row = rows.get(layer.node_id)
        expected_base = row.expected_base_ref if row is not None else None
        expected_branch = row.branch if row is not None else None
        try:
            evidence = b.merged_evidence(number=layer.pr_number, repo_root=b.repo_root)
        except GitHubError as exc:
            evidence = None
            notes.append(f"could not read merged evidence for PR #{layer.pr_number}: {exc}")
        if (
            evidence is None
            or evidence.state != "MERGED"
            or evidence.merge_commit_sha is None
            or evidence.head_sha != layer.head_sha
            or expected_branch is None
            or evidence.head_ref != expected_branch
            or expected_base is None
            or evidence.base_ref not in (expected_base, readiness.base)
        ):
            observed = (
                f"state={evidence.state} base={evidence.base_ref!r} "
                f"head-ref={evidence.head_ref!r} head={evidence.head_sha} "
                f"merge_commit={evidence.merge_commit_sha}"
                if evidence is not None
                else "unreadable"
            )
            notes.append(
                "GitHub reported the merge but per-PR verification failed "
                f"(PR #{layer.pr_number}: {observed}; expected MERGED as "
                f"{expected_branch!r} at {layer.head_sha} onto {expected_base!r} or "
                f"{readiness.base!r}) — no completed outcome was journaled; the LAND "
                f"operation {operation_id} is unresolved (conclude it with "
                "`perk objective stack recover`)"
            )
            return _outcome(
                readiness,
                "pending",
                operation_id=operation_id,
                merge_async_uuid=uuid,
                notes=tuple(notes),
            )
        verified.append((layer, evidence.merge_commit_sha))
    # The final objective-base SHA is the TOP layer's merge commit: a direct stack
    # merge lands the train as base commits; the singleton likewise.
    final_base_sha = verified[-1][1]
    try:
        b.persistence.append_outcome(
            readiness.objective_id,
            OutcomeRecord(
                operation_id=operation_id,
                role=EventRole.COMPLETED,
                created=b.now(),
                observed={
                    "layers": [
                        {"pr_number": layer.pr_number, "merge_commit_sha": sha}
                        for layer, sha in verified
                    ],
                    "reported_sha": reported_sha,
                    "final_base_sha": final_base_sha,
                },
            ),
        )
    except (
        TrainPersistenceError,
        JournalCorruptionError,
        IssueBackendError,
        ObjectiveStoreError,
    ) as exc:
        # Invariant 20: the merge is verified — a failed/ambiguous completed append (the
        # adapter's carrier read can also raise the store's expected failures) degrades to
        # a loud note, never an error exit; finalization and the aggregate close still run.
        notes.append(
            f"completed outcome could not be journaled after verification (non-fatal; the "
            f"LAND operation {operation_id} reads unresolved until it is concluded): {exc}"
        )
    landed = _finalize_layers(b, readiness, rows, verified, notes, consumed=consumed)
    closed = state_aware_close(b.store, readiness.objective_id, notes)
    evidence = _read_evidence(b, readiness.objective_id, notes) if closed else None
    return _outcome(
        readiness,
        "merged",
        operation_id=operation_id,
        merge_async_uuid=uuid,
        landed_layers=tuple(landed),
        objective_closed=closed,
        notes=tuple(notes),
        reconcile_evidence=evidence,
    )


def _finalize_layers(
    b: _Landing,
    readiness: land.LandReadiness,
    rows: Mapping[str, land.LandLayerReadiness],
    verified: list[tuple[land.LandPlanLayer, str]],
    notes: list[str],
    *,
    consumed: tuple[str, ...] | None,
) -> list[LandedLayer]:
    """Per-layer finalization bottom→top. ``consumed`` short-circuits the plan re-read for
    the singleton (its step-6 load-bearing read already carried ``consumed_learn``); every
    failure is a note, never a result change (the merge is already verified)."""
    landed: list[LandedLayer] = []
    for layer, sha in verified:
        layer_consumed = consumed
        if layer_consumed is None:
            try:
                state = b.issues.get_plan(issue_id=layer.plan_id)
            except IssueBackendError as exc:
                state = None
                notes.append(
                    f"could not read plan #{layer.plan_id} for consumed_learn (non-fatal; "
                    f"finalizing without it): {exc}"
                )
            else:
                if state is None:
                    notes.append(
                        f"plan #{layer.plan_id} not found for consumed_learn (non-fatal; "
                        "finalizing without it)"
                    )
            layer_consumed = () if state is None else _consumed_learn(state.header)
        row = rows.get(layer.node_id)
        pr_base = (
            row.expected_base_ref if row is not None and row.expected_base_ref is not None else ""
        )
        try:
            fin: LandFinalization | None = b.finalize(
                b.repo_root,
                landed=LandedPlan(
                    plan_id=layer.plan_id,
                    objective_id=readiness.objective_id,
                    consumed_learn=layer_consumed,
                ),
                pr_base=pr_base,
                close_objective_on_complete=False,
            )
        except Exception as exc:
            # Deliberately broad (invariant 20): a verified merge is never reported failed
            # because bookkeeping raised; the layer's finalization is honestly None and the
            # remaining layers still finalize.
            fin = None
            notes.append(f"finalize failed for plan #{layer.plan_id} (non-fatal): {exc}")
        landed.append(
            LandedLayer(
                node_id=layer.node_id,
                plan_id=layer.plan_id,
                pr_number=layer.pr_number,
                merge_commit_sha=sha,
                finalization=fin,
                base_sha=layer.base_sha,
                head_sha=layer.head_sha,
            )
        )
    return landed


def state_aware_close(store: LandObjectiveStore, objective_id: str, notes: list[str]) -> bool:
    """The shared state-aware aggregate objective close (§8.56; also recover's convergence
    close): re-fetch the objective; OPEN (the lifecycle read) + every node terminal ⇒ close
    (isolated fail-open, mirroring finalize's close posture) ⇒ ``True`` — a REAL transition.
    A rerun on a closed objective reports ``False`` (convergent, never an idempotent-write
    guess). Cross-machine duplicate closes remain possible (idempotent close, machine-local
    lock) — the drive contract is at-least-once."""
    try:
        state = store.get_objective(objective_id=objective_id)
    except ObjectiveStoreError as exc:
        notes.append(f"aggregate objective close skipped (non-fatal): {exc}")
        return False
    if state is None:
        notes.append(f"aggregate objective close skipped: objective #{objective_id} not found")
        return False
    remaining = [node.id for node in state.nodes if node.status not in objective.TERMINAL]
    if remaining:
        notes.append(
            f"objective #{objective_id} not closed — non-terminal node(s): " + ", ".join(remaining)
        )
        return False
    if state.state != "open":
        notes.append(f"objective #{objective_id} is already closed")
        return False
    try:
        store.close_objective(objective_id=objective_id)
    except ObjectiveStoreError as exc:
        notes.append(f"objective close failed (non-fatal — every node is terminal): {exc}")
        return False
    return True


def _read_evidence(b: _Landing, objective_id: str, notes: list[str]) -> LandEvidence | None:
    """The fresh-fold reconcile-evidence read for a close transition — fail-open loud (the
    close already happened; the evidence is reconcile bookkeeping)."""
    try:
        fold = b.persistence.read_journal(objective_id)
    except (
        TrainPersistenceError,
        JournalCorruptionError,
        IssueBackendError,
        ObjectiveStoreError,
    ) as exc:
        notes.append(f"reconcile evidence could not be assembled (non-fatal): {exc}")
        return None
    evidence = assemble_land_evidence(fold)
    notes.extend(evidence.notes)
    return evidence


# ----------------------------------------------------------------- payloads + small helpers


def _before_payload(land_plan: land.LandPlan, *, base: str) -> dict[str, object]:
    """The prepared ``before``: exactly the ``LandPlan`` evidence plus the base branch."""
    return {
        "mode": land_plan.mode,
        "merge_method": land_plan.merge_method,
        "base": base,
        "top_pr_number": land_plan.top_pr_number,
        "top_head_sha": land_plan.top_head_sha,
        "layers": [
            {
                "node_id": layer.node_id,
                "plan_id": layer.plan_id,
                "pr_number": layer.pr_number,
                "base_sha": layer.base_sha,
                "head_sha": layer.head_sha,
            }
            for layer in land_plan.layers
        ],
    }


def _after_payload(land_plan: land.LandPlan, *, base: str) -> dict[str, object]:
    return {
        "merged_pr_numbers": [layer.pr_number for layer in land_plan.layers],
        "base": base,
    }


def _consumed_learn(header: Mapping[str, object]) -> tuple[str, ...]:
    """The plan header's ``consumed_learn``, parsed tolerantly (bookkeeping input — junk
    reads as empty, never raises)."""
    raw = header.get("consumed_learn")
    if isinstance(raw, list | tuple):
        return tuple(str(item).strip() for item in raw if str(item).strip())
    return ()


def _outcome(
    readiness: land.LandReadiness,
    outcome: LandOutcomeKind,
    *,
    operation_id: str | None = None,
    merge_async_uuid: str | None = None,
    landed_layers: tuple[LandedLayer, ...] = (),
    objective_closed: bool = False,
    notes: tuple[str, ...] = (),
    reconcile_evidence: LandEvidence | None = None,
) -> LandOutcome:
    return LandOutcome(
        outcome=outcome,
        readiness=readiness,
        operation_id=operation_id,
        merge_async_uuid=merge_async_uuid,
        landed_layers=landed_layers,
        objective_closed=objective_closed,
        notes=notes,
        reconcile_evidence=reconcile_evidence,
    )
