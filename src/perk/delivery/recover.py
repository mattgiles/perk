"""The delivery **recover** operation — conclude-only recovery (contracts.md §8.51).

`perk objective stack recover` concludes unresolved stack operations and sweeps orphaned
machine-local sync residue; it NEVER retries — retry always routes to the owning command
(a SYNC/ADOPT recompute is `stack sync`; a PUBLISH roll-forward is `/submit`'s own resume,
which needs submit-owned title/body context). Per kind:

- **SYNC/ADOPT** — classified through the shared sync-record recovery core
  (:func:`perk.delivery.sync.validate_sync_record` + observation): ``all_after`` rolls
  forward automatically (record-driven steps 13-14 under the same operation);
  ``all_before`` may be abandoned with proof under ``--abandon``; anything else is
  ``mixed`` — reported, never concluded (fail closed).
- **PUBLISH** — classified through the publish-owned proof helper
  (:func:`perk.delivery.publish.classify_publish_record`: branch + PR facts + native-stack
  membership). Report-only for roll-forward; ``--abandon`` allowed on a proven
  ``all_before``. A **sole** unresolved PUBLISH is routed fold-first PAST the generic
  structural-blocker gate (§8.54): its own crash window legitimately produces structural
  cancellation/remote/checkpoint findings, and the publish proof
  (``_validate_resume_context`` + exact before/after branch/PR/stack observation) is the
  real safety gate — the bypass never authorizes checkpoint/identity mutation.
- **TRANSFER** — routed FIRST, before any train gate (fold-first): a mid-transfer
  predecessor necessarily shows intentional ``wrong_owner``/``node_link_mismatch``
  blockers, and a finalized-but-uncompleted stacked→incremental transfer has no train at
  all. Classified via the transfer manifest + the run_id successor lookup (§8.53):
  successor found + corroborated → ``all_after`` rolls forward automatically through
  :func:`perk.delivery.transfer.roll_forward_transfer` (create-convergent → stamp →
  verify → finalize → complete, under the same held lock); successor absent →
  ``all_before`` may be abandoned with proof under ``--abandon``; an undecodable manifest
  is a report-only corruption row (fail closed).
- **LAND** — classified through the landing-owned proof
  (:func:`perk.delivery.landing.classify_land_record`: strict payload decode +
  fresh-train exact-set corroboration + at most ONE total handle probe per classification
  pass + one strict PR observation per recorded layer, folded through the complete
  handle-evidence x observation-shape table). ``all_after`` rolls forward automatically
  (:func:`perk.delivery.landing.roll_forward_land`: the §8.56 ``completed`` append →
  per-layer finalize → the state-aware close); ``all_before`` may be abandoned with proof
  under ``--abandon`` (reason ``recovered_before_state``); ``external_prefix`` — a
  bottom-contiguous externally merged prefix with the remainder OPEN at its recorded
  heads — may be ACCEPTED as a recorded degraded-atomicity breach under
  ``--accept-prefix`` (preview → confirm → from-scratch re-classification →
  :func:`perk.delivery.landing.accept_external_prefix`; the remainder then rides
  ``stack sync --base`` → ``land``); ``in_flight`` / ``mixed`` only ever report (a
  live/unexcludable merge request is never contradicted by action).

After the conclude phase, the train-backed path runs the **finalization-convergence
pass** (even with zero unresolved operations): re-read the journal fold fresh, re-run the
idempotent per-layer finalizer for every journal-covered, freshly corroborated merged
layer (never a completeness proxy), then the state-aware close — closing the objective
once every node is terminal and attaching the fresh-fold ``reconcile_evidence``. An
already-closed, journal-complete objective re-emits that evidence with a loud note (the
death-after-close repair — at-least-once; the reconcile pass is idempotent).

The sole service entry is :meth:`perk.delivery.facade.Delivery.recover`. Its private immutable
context binds the three aggregate authorities plus the façade's train reconstruction bridge; its
private runtime carries only config/path enumeration, the lock, the temporarily retained
per-layer finalizer, sleep, and clock. No backend resolver, dependency factory, or low-level
recovery entrypoint is public.

Any ACTION (roll-forward or abandon) applies to exactly ONE target — the sole unresolved
operation, else ``--operation``; non-target rows stay reported. The abandon confirmation is
a race boundary: after an affirmative answer the target is RE-classified from scratch and
the post-confirmation observation is the journaled proof. The orphan sweep runs last, only
on a success path, protected by every parseable continuation manifest (foreign lineages
included) and skipped entirely while any unparseable manifest exists. The same machine-local
advisory lock as sync (:mod:`perk.delivery.oplock`) serializes recover with the mutating
sync entries; a busy lock is the typed refusal ``operation_in_progress``. Cross-machine
quiescence is an operator responsibility when abandoning: a still-live remote owner's
residual push is detected as drift by the next preflight, never prevented here.
"""

import re
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from perk import objective, plan
from perk.backends.objective_store import ObjectiveStoreError
from perk.delivery import continuation, land_records, landing, oplock, publish
from perk.delivery import sync as sync_mod
from perk.delivery import transfer as transfer_mod
from perk.delivery.facade import (
    DeliveryError,
    DeliveryGit,
    DeliveryGitHub,
    DeliveryPersistence,
    RecoverRequest,
    RecoverResult,
)
from perk.delivery.finalize import finalize_landed_plan
from perk.delivery.journal import (
    EventRole,
    JournalCorruptionError,
    JournalFold,
    OperationKind,
    OperationState,
    OutcomeRecord,
    PreparedRecord,
)
from perk.delivery.train import (
    DeliveryTrain,
    NoDeliveryTrain,
    PlanReader,
    TrainLayer,
    TrainStatus,
)
from perk.github import GitHubError
from perk.substrate import git as git_mod

# ----------------------------------------------------------------- orphan classification

# The perk-minted machine-local sync residue shapes (§8.49): `sync-<26-char Crockford
# ULID>` worktrees and `refs/perk/sync/<ulid>/<branch>` temp refs. Anything else under
# these roots is not perk-minted and is never touched.
_ULID_RE = re.compile(r"[0-9A-HJKMNP-TV-Z]{26}")
_SYNC_DIR_RE = re.compile(r"sync-([0-9A-HJKMNP-TV-Z]{26})\Z")
_SYNC_REF_PREFIX = "refs/perk/sync/"


@dataclass(frozen=True)
class OrphanScan:
    """The machine-local orphaned sync residue (read-only; shared by recover's sweep and
    detailed status). ``worktrees`` are on-disk directories; ``stale_admin`` are entries
    still in git's worktree-admin inventory whose directory is GONE (prunable — swept by
    the sweep's one prune). ``skipped`` is non-``None`` when the unparseable-manifest
    fail-safe fired — an unaccountable manifest cannot protect its residue, so nothing
    classifies."""

    worktrees: tuple[Path, ...]
    refs: tuple[str, ...]
    skipped: str | None
    stale_admin: tuple[Path, ...] = ()


def _default_worktree_dirs(worktree_root: Path) -> list[Path]:
    if not worktree_root.is_dir():
        return []
    return sorted(path for path in worktree_root.iterdir() if path.is_dir())


def _default_worktree_admin_dirs(repo_root: Path) -> list[Path]:
    """Every worktree path git's admin inventory records — including entries whose
    directory is gone (the prunable stale entries a killed sync can leave)."""
    return [entry.path for entry in git_mod.worktree_list(repo_root)]


def _same_dir(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def observe_orphans(
    repo_root: Path,
    *,
    worktree_root: Path,
    iter_manifests: Callable[[Path], continuation.ManifestScan] = continuation.iter_manifests,
    list_refs: Callable[[Path, str], list[str]] = git_mod.list_refs,
    worktree_dirs: Callable[[Path], list[Path]] = _default_worktree_dirs,
    worktree_admin_dirs: Callable[[Path], list[Path]] = _default_worktree_admin_dirs,
) -> OrphanScan:
    """Classify orphaned sync residue: perk-minted `sync-<ulid>` worktrees (on disk, plus
    stale worktree-admin entries whose directory is already gone) and
    `refs/perk/sync/<ulid>/` refs whose operation id is NOT protected by any parseable
    continuation manifest (manifests are lineage-keyed and may belong to other objectives —
    all of them protect their residue). Live in-flight residue is protected by the
    operation LOCK, not by this exclusion. Read failures propagate to the caller."""
    scan = iter_manifests(repo_root)
    if scan.unparseable:
        names = ", ".join(str(path) for path in scan.unparseable)
        return OrphanScan(
            worktrees=(),
            refs=(),
            skipped=(
                f"unparseable continuation manifest(s) present ({names}) — an unaccountable "
                "manifest cannot protect its residue; discard it with "
                "`perk objective stack sync --abort` and rerun"
            ),
        )
    protected = {manifest.operation_id for manifest in scan.manifests}
    on_disk = worktree_dirs(worktree_root)
    worktrees = tuple(
        path
        for path in on_disk
        if (match := _SYNC_DIR_RE.fullmatch(path.name)) is not None
        and match.group(1) not in protected
    )
    disk_names = {path.name for path in on_disk}
    stale_admin = tuple(
        path
        for path in worktree_admin_dirs(repo_root)
        if (match := _SYNC_DIR_RE.fullmatch(path.name)) is not None
        and match.group(1) not in protected
        and path.name not in disk_names
        and (path.parent == worktree_root or _same_dir(path.parent, worktree_root))
    )
    refs = tuple(
        ref
        for ref in list_refs(repo_root, _SYNC_REF_PREFIX)
        if (op := _ref_operation_id(ref)) is not None and op not in protected
    )
    return OrphanScan(worktrees=worktrees, refs=refs, skipped=None, stale_admin=stale_admin)


def _ref_operation_id(ref: str) -> str | None:
    if not ref.startswith(_SYNC_REF_PREFIX):
        return None
    segment = ref[len(_SYNC_REF_PREFIX) :].split("/", 1)[0]
    return segment if _ULID_RE.fullmatch(segment) else None


# ----------------------------------------------------------------- façade binding + runtime


@dataclass(frozen=True)
class _RecoverRuntime:
    """Private immutable helpers that are not delivery authorities."""

    worktree_root: Callable[[Path], Path]
    operation_lock: Callable[[Path], AbstractContextManager[None]]
    iter_manifests: Callable[[Path], continuation.ManifestScan]
    worktree_dirs: Callable[[Path], list[Path]]
    finalize: landing._Finalize
    sleep: Callable[[float], None]
    now: Callable[[], str]


_DEFAULT_RECOVER_RUNTIME = _RecoverRuntime(
    worktree_root=sync_mod._configured_worktree_root,
    operation_lock=oplock.stack_operation_lock,
    iter_manifests=continuation.iter_manifests,
    worktree_dirs=_default_worktree_dirs,
    finalize=finalize_landed_plan,
    sleep=time.sleep,
    now=plan.now_iso,
)


@dataclass(frozen=True)
class _RecoverContext:
    """One façade-bound operation-conclusion context."""

    repo_root: Path
    persistence: DeliveryPersistence
    git: DeliveryGit
    github: DeliveryGitHub
    reconstruct: Callable[[Path, str], TrainStatus]
    runtime: _RecoverRuntime


@dataclass(frozen=True)
class _RecoverRecordSeams:
    """Adapt aggregate authorities to the existing kind-specific record protocols."""

    context: _RecoverContext

    @property
    def repo_root(self) -> Path:
        return self.context.repo_root

    @property
    def persistence(self) -> DeliveryPersistence:
        return self.context.persistence

    @property
    def issues(self) -> PlanReader:
        return self.context.persistence

    @property
    def store(self) -> landing.LandObjectiveStore:
        return self.context.persistence

    def _pr_facts(self, *, number: int, repo_root: Path) -> object:
        del repo_root
        return self.context.github.pr_facts(number)

    @property
    def pr_facts(self) -> sync_mod._PrFactsRead:
        return cast("sync_mod._PrFactsRead", self._pr_facts)

    def _stack_read(self, *, number: int, repo_root: Path) -> object:
        del repo_root
        return self.context.github.strict_stack(number)

    @property
    def stack_read(self) -> sync_mod._StackRead:
        return cast("sync_mod._StackRead", self._stack_read)

    def _pr_for_branch(self, *, branch: str, repo_root: Path) -> object:
        del repo_root
        return self.context.github.pr_for_branch(branch)

    @property
    def pr_for_branch(self) -> publish._FindPrForBranch:
        return cast("publish._FindPrForBranch", self._pr_for_branch)

    def _merge_probe(self, *, number: int, uuid: str, repo_root: Path) -> object:
        del repo_root
        return self.context.github.merge_async_probe(number, uuid=uuid)

    @property
    def merge_probe(self) -> landing._ProbeAsync:
        return cast("landing._ProbeAsync", self._merge_probe)

    def _merged_evidence(self, *, number: int, repo_root: Path) -> object:
        del repo_root
        return self.context.github.merged_evidence(number)

    @property
    def merged_evidence(self) -> landing._MergedEvidence:
        return cast("landing._MergedEvidence", self._merged_evidence)

    def _fetch(self, repo_root: Path, refs: list[str]) -> None:
        del repo_root
        self.context.git.fetch_refs(tuple(refs))

    @property
    def fetch(self) -> Callable[[Path, list[str]], None]:
        return self._fetch

    def _remote_head(self, repo_root: Path, branch: str) -> str | None:
        del repo_root
        return self.context.git.remote_branch_sha(branch)

    @property
    def remote_head(self) -> Callable[[Path, str], str | None]:
        return self._remote_head

    @property
    def finalize(self) -> landing._Finalize:
        return self.context.runtime.finalize

    @property
    def sleep(self) -> Callable[[float], None]:
        return self.context.runtime.sleep

    @property
    def now(self) -> Callable[[], str]:
        return self.context.runtime.now


type _Consent = Callable[[RecoverResult.AbandonPreview | RecoverResult.AcceptPrefixPreview], bool]


def _dispatch(
    context: _RecoverContext,
    request: RecoverRequest,
    *,
    consent: _Consent | None,
) -> RecoverResult:
    """Resolve local configuration, then hold the one operation lock through the sweep."""
    worktree_root = context.runtime.worktree_root(context.repo_root)
    entered = False
    try:
        with context.runtime.operation_lock(context.repo_root):
            entered = True
            return _recover(
                context,
                _RecoverRecordSeams(context),
                request,
                worktree_root=worktree_root,
                consent=consent,
            )
    except oplock.OperationLockBusy as exc:
        if entered:
            raise
        raise DeliveryError(str(exc), error_type="operation_in_progress") from exc


# ----------------------------------------------------------------- classification


@dataclass(frozen=True)
class _Classified:
    """One operation's classification with the kind-specific evidence the action phase
    reuses (sync facts/observation, publish proof, the decoded transfer record, or the
    LAND record proof)."""

    op: OperationState
    classification: str
    detail: str
    sync_facts: sync_mod.SyncRecordFacts | None = None
    sync_observed: tuple[str | None, ...] | None = None
    publish_proof: publish.PublishRecordProof | None = None
    transfer_record: PreparedRecord | None = None
    land_proof: landing.LandRecordProof | None = None


@dataclass
class _LandEffects:
    """The invocation-level LAND effects accumulator (conclusions + the convergence pass):
    landed rows, the real close transition, the fresh reconcile evidence, loud notes."""

    landed_layers: list[RecoverResult.LandedLayer] = field(default_factory=list)
    objective_closed: bool = False
    reconcile_evidence: landing.LandEvidence | None = None
    notes: list[str] = field(default_factory=list)

    def merge_conclusion(self, conclusion: landing.LandConclusion) -> None:
        self.landed_layers.extend(_landed_row(layer) for layer in conclusion.landed_layers)
        self.objective_closed = self.objective_closed or conclusion.objective_closed
        if self.reconcile_evidence is None:
            self.reconcile_evidence = conclusion.reconcile_evidence
        self.notes.extend(conclusion.notes)


def _landed_row(layer: landing.LandedLayer) -> RecoverResult.LandedLayer:
    return RecoverResult.LandedLayer(
        node_id=layer.node_id,
        plan_id=layer.plan_id,
        pr_number=layer.pr_number,
        merge_commit_sha=layer.merge_commit_sha,
        base_sha=layer.base_sha,
        head_sha=layer.head_sha,
        finalized=layer.finalization is not None,
    )


def _classify(seams: _RecoverRecordSeams, train: DeliveryTrain, op: OperationState) -> _Classified:
    """Phase 2, per kind (decision: no unified record decoder). A SYNC/ADOPT corroboration
    failure classifies ``mixed`` (fail closed, reported); infra read failures propagate —
    recover fails whole rather than mis-classifying."""
    record = op.prepared.record
    if not isinstance(record, PreparedRecord):
        return _Classified(op, "mixed", "the prepared event carries no readable record")
    if op.kind in (OperationKind.SYNC, OperationKind.ADOPT):
        try:
            facts = sync_mod.validate_sync_record(train, record)
        except sync_mod.SyncError as exc:
            return _Classified(op, "mixed", f"corroboration against fresh authority failed: {exc}")
        observed = sync_mod.observe_sync_record(seams, facts)
        classification = sync_mod.classify_sync_observation(facts, observed)
        pairs = [(entry.branch, sha) for sha, entry in zip(observed, facts.recorded, strict=True)]
        detail = {
            "all_after": "every recorded ref verified at its prepared after state",
            "all_before": "every recorded ref verified at its prepared before state",
            "mixed": f"the recorded refs verified in a MIXED state ({pairs})",
        }[classification]
        return _Classified(op, classification, detail, sync_facts=facts, sync_observed=observed)
    if op.kind is OperationKind.PUBLISH:
        proof = publish.classify_publish_record(seams, train, record)
        return _Classified(op, proof.classification, proof.detail, publish_proof=proof)
    if op.kind is OperationKind.LAND:
        land_proof = landing.classify_land_record(seams, train, op)
        return _Classified(op, land_proof.classification, land_proof.detail, land_proof=land_proof)
    # The impossible-by-construction fallback for a TRANSFER sharing a fold with other
    # unresolved operations (a sole-unresolved TRANSFER dispatched to the transfer arm
    # before any train gate).
    return _Classified(
        op,
        "unsupported",
        f"{op.kind.value} recovery is report-only — conclude it via the owning surface",
    )


# ----------------------------------------------------------------- the protocol


def _recover(
    context: _RecoverContext,
    seams: _RecoverRecordSeams,
    request: RecoverRequest,
    *,
    worktree_root: Path,
    consent: _Consent | None,
) -> RecoverResult:
    # Fold the requested objective before any train gate: an unresolved TRANSFER owns a
    # deliberately inconsistent predecessor projection and must route first.
    fold = context.persistence.read_journal(request.objective_id)
    if len(fold.unresolved) == 1 and fold.unresolved[0].kind is OperationKind.TRANSFER:
        return _recover_transfer(
            context,
            request,
            request.objective_id,
            fold.unresolved[0],
            worktree_root=worktree_root,
            consent=consent,
        )
    status = context.reconstruct(context.repo_root, request.objective_id)
    if isinstance(status, NoDeliveryTrain):
        raise DeliveryError(
            f"objective {status.objective_id} has no delivery train ({status.reason})",
            error_type="not_stacked",
        )

    fold = context.persistence.read_journal(status.objective_id)
    sole_publish = len(fold.unresolved) == 1 and fold.unresolved[0].kind is OperationKind.PUBLISH
    if not sole_publish:
        sync_mod.refuse_structural_blockers(status)

    classified = [_classify(seams, status, op) for op in fold.unresolved]
    ids = [entry.op.operation_id for entry in classified]
    target_id: str | None = None
    selection_required = False
    acting = request.action != "report"
    if request.operation_id is not None:
        if request.operation_id not in ids:
            listed = ", ".join(ids) or "<none>"
            raise DeliveryError(
                f"operation {request.operation_id} is not unresolved on this train — "
                f"unresolved: {listed}",
                error_type="operation_not_found",
            )
        target_id = request.operation_id
    elif len(classified) == 1:
        target_id = ids[0]
    elif len(classified) > 1:
        if acting:
            raise DeliveryError(
                f"several operations are unresolved ({', '.join(ids)}) — name the action "
                "target with --operation",
                error_type="operation_ambiguous",
            )
        selection_required = True
    elif acting:
        raise DeliveryError(
            "no unresolved operation exists — nothing to conclude",
            error_type="operation_not_found",
        )

    effects = _LandEffects()
    rows = [
        _conclude(
            seams,
            request,
            status,
            entry,
            is_target=entry.op.operation_id == target_id,
            effects=effects,
            consent=consent,
        )
        for entry in classified
    ]
    _converge_finalization(seams, request, status, effects)

    swept_worktrees, swept_refs, failures, skipped = _sweep(
        context, request, worktree_root=worktree_root
    )
    return RecoverResult(
        kind=request.kind,
        objective_id=status.objective_id,
        objective_url=status.objective_url,
        redirected_from=status.redirected_from,
        dry_run=request.dry_run,
        selection_required=selection_required,
        operations=tuple(rows),
        swept_worktrees=swept_worktrees,
        swept_refs=swept_refs,
        sweep_failures=failures,
        sweep_skipped=skipped,
        landed_layers=tuple(effects.landed_layers),
        objective_closed=effects.objective_closed,
        reconcile_evidence=effects.reconcile_evidence,
        notes=tuple(effects.notes),
    )


# ----------------------------------------------------------------- the TRANSFER arm (§8.53)


def _recover_transfer(
    context: _RecoverContext,
    request: RecoverRequest,
    objective_id: str,
    op: OperationState,
    *,
    worktree_root: Path,
    consent: _Consent | None,
) -> RecoverResult:
    """Conclude the fold-first TRANSFER while keeping the orphan sweep last."""
    if request.operation_id is not None and request.operation_id != op.operation_id:
        raise DeliveryError(
            f"operation {request.operation_id} is not unresolved on this objective — unresolved: "
            f"{op.operation_id}",
            error_type="operation_not_found",
        )
    if request.action == "accept_prefix":
        raise DeliveryError(
            f"--accept-prefix requires an external_prefix LAND classification — operation "
            f"{op.operation_id} is transfer; nothing was journaled",
            error_type="accept_blocked",
        )
    seams = transfer_mod.TransferSeams(
        repo_root=context.repo_root,
        store=context.persistence,
        issues=context.persistence,
        persistence=context.persistence,
        reconstruct=context.reconstruct,
        now=context.runtime.now,
    )
    entry = _classify_transfer(seams, op)
    row = _conclude_transfer(
        context,
        request,
        seams,
        objective_id,
        entry,
        consent=consent,
    )
    state = context.persistence.get_objective(objective_id=objective_id)
    objective_url = state.url if state is not None else ""
    swept_worktrees, swept_refs, failures, skipped = _sweep(
        context, request, worktree_root=worktree_root
    )
    return RecoverResult(
        kind=request.kind,
        objective_id=objective_id,
        objective_url=objective_url,
        redirected_from=None,
        dry_run=request.dry_run,
        selection_required=False,
        operations=(row,),
        swept_worktrees=swept_worktrees,
        swept_refs=swept_refs,
        sweep_failures=failures,
        sweep_skipped=skipped,
    )


def _classify_transfer(seams: transfer_mod.TransferSeams, op: OperationState) -> _Classified:
    """The TRANSFER classification (D11): decode the recorded manifest (undecodable → a
    report-only corruption row, fail closed), then the run_id successor lookup — found +
    corroborated → ``all_after``; absent → provably ``all_before`` (creation is the first
    post-prepare effect); a corroboration mismatch → ``mixed`` (reported, never concluded)."""
    record = op.prepared.record
    if not isinstance(record, PreparedRecord):
        return _Classified(op, "mixed", "the prepared event carries no readable record")
    try:
        manifest = transfer_mod.decode_transfer_record(record)
    except JournalCorruptionError as exc:
        return _Classified(
            op, "mixed", f"the transfer manifest is undecodable — corruption, report-only: {exc}"
        )
    found = seams.store.find_objective(run_id=record.run_id)
    if found is None:
        return _Classified(
            op,
            "all_before",
            f"no successor exists for run {record.run_id} — creation is the first "
            "post-prepare effect, so nothing after the prepared record happened",
            transfer_record=record,
        )
    try:
        transfer_mod.corroborate_successor(seams.store, found, manifest, record)
    except transfer_mod.TransferError as exc:
        return _Classified(op, "mixed", f"corroboration against fresh authority failed: {exc}")
    return _Classified(
        op,
        "all_after",
        f"successor {found.id} exists for run {record.run_id} (supersedes + lineage corroborated)",
        transfer_record=record,
    )


def _conclude_transfer(
    context: _RecoverContext,
    request: RecoverRequest,
    seams: transfer_mod.TransferSeams,
    objective_id: str,
    entry: _Classified,
    *,
    consent: _Consent | None,
) -> RecoverResult.Operation:
    """Apply the selected TRANSFER conclusion through the lock-assumed core."""
    op = entry.op
    action = "reported"
    detail = entry.detail
    if request.action == "abandon":
        action, outcome = _abandon_transfer(context, seams, objective_id, entry, consent=consent)
        detail = f"{entry.detail} — {outcome}"
    elif (
        entry.classification == "all_after"
        and entry.transfer_record is not None
        and not request.dry_run
    ):
        successor = transfer_mod.roll_forward_transfer(seams, record=entry.transfer_record)
        action = "rolled_forward"
        detail = (
            f"{entry.detail} — rolled forward to completion (successor {successor.id}: "
            "ownership stamped, projection verified, predecessor finalized, completion "
            "journaled)"
        )
    else:
        detail = f"{entry.detail} — {_transfer_hint(request, entry)}"
    return RecoverResult.Operation(
        operation_id=op.operation_id,
        kind=op.kind.value,
        prepared_created=op.prepared.record.created,
        classification=entry.classification,
        action=action,
        detail=detail,
    )


def _transfer_hint(request: RecoverRequest, entry: _Classified) -> str:
    predecessor = entry.transfer_record.objective_id if entry.transfer_record is not None else "?"
    if entry.classification == "all_after":
        if request.dry_run:
            return "a real recover would roll this forward automatically"
        return f"rerun `perk objective stack recover {predecessor}` to roll it forward"
    if entry.classification == "all_before":
        return (
            "abandon with `--abandon`, or re-save the replan (the save abandons-with-proof "
            "and re-prepares in the same invocation)"
        )
    return "corrupt/mixed state — refusing to guess; investigate the manifest and the successor"


def _abandon_transfer(
    context: _RecoverContext,
    seams: transfer_mod.TransferSeams,
    objective_id: str,
    entry: _Classified,
    *,
    consent: _Consent | None,
) -> tuple[str, str]:
    op = entry.op
    if entry.classification != "all_before":
        raise DeliveryError(
            f"--abandon requires every recorded effect verified at its before state — "
            f"operation {op.operation_id} classified {entry.classification}; nothing was "
            "journaled",
            error_type="abandon_blocked",
        )
    preview = RecoverResult.AbandonPreview(
        operation_id=op.operation_id,
        kind=op.kind.value,
        prepared_created=op.prepared.record.created,
        detail=entry.detail,
    )
    if consent is not None and not consent(preview):
        return ("declined", "the abandon confirmation was declined; the journal is untouched")
    fresh = _classify_transfer(seams, op)
    if fresh.classification != "all_before":
        raise DeliveryError(
            f"the world moved while the confirmation was pending: operation "
            f"{op.operation_id} re-classified {fresh.classification} — nothing was "
            "journaled; rerun recover",
            error_type="abandon_blocked",
        )
    record = fresh.transfer_record
    assert record is not None
    context.persistence.append_outcome(
        objective_id,
        OutcomeRecord(
            operation_id=op.operation_id,
            role=EventRole.ABANDONED,
            created=context.runtime.now(),
            observed=transfer_mod.transfer_abandon_observation(record),
        ),
    )
    return ("abandoned", "abandoned with the post-confirmation all-before observation as proof")


def _conclude(
    seams: _RecoverRecordSeams,
    request: RecoverRequest,
    train: DeliveryTrain,
    entry: _Classified,
    *,
    is_target: bool,
    effects: _LandEffects,
    consent: _Consent | None,
) -> RecoverResult.Operation:
    """Apply one train-backed conclusion or return its report row."""
    op = entry.op
    resumable = op.kind in (OperationKind.SYNC, OperationKind.ADOPT)
    action = "reported"
    detail = entry.detail
    if request.action == "accept_prefix" and is_target:
        action, outcome = _accept_prefix(seams, train, entry, effects, consent=consent)
        detail = f"{entry.detail} — {outcome}"
    elif request.action == "abandon" and is_target:
        action, outcome = _abandon(seams, train, entry, consent=consent)
        detail = f"{entry.detail} — {outcome}"
    elif (
        is_target
        and resumable
        and entry.classification == "all_after"
        and entry.sync_facts is not None
        and not request.dry_run
    ):
        record = op.prepared.record
        assert isinstance(record, PreparedRecord)
        layers = sync_mod.roll_forward_sync_record(seams, train, record, entry.sync_facts)
        action = "rolled_forward"
        moved = ", ".join(f"{layer.branch}@{layer.after_sha}" for layer in layers)
        detail = (
            f"{entry.detail} — rolled forward under the same operation "
            f"(checkpoints + completion journaled; {moved})"
        )
    elif (
        is_target
        and op.kind is OperationKind.LAND
        and entry.classification == "all_after"
        and entry.land_proof is not None
        and not request.dry_run
    ):
        conclusion = landing.roll_forward_land(seams, train, op, entry.land_proof)
        effects.merge_conclusion(conclusion)
        action = "rolled_forward"
        detail = (
            f"{entry.detail} — rolled forward under the same operation (completed "
            f"journaled; {len(conclusion.landed_layers)} layer(s) finalized bottom→top)"
        )
    else:
        detail = f"{entry.detail} — {_hint(request, entry, is_target=is_target)}"
    merged_rows, remainder_rows = _prefix_preview_rows(entry)
    return RecoverResult.Operation(
        operation_id=op.operation_id,
        kind=op.kind.value,
        prepared_created=op.prepared.record.created,
        classification=entry.classification,
        action=action,
        detail=detail,
        merged_layers=merged_rows,
        remainder=remainder_rows,
    )


def _prefix_preview_rows(
    entry: _Classified,
) -> tuple[
    tuple[RecoverResult.MergedPrefix, ...],
    tuple[RecoverResult.RemainderPr, ...],
]:
    """The ``external_prefix`` rows' structured preview fields (dry-run included — the warm
    flow previews via ``dry_run: true``, presents, then confirms); empty on every other
    row."""
    if entry.classification != "external_prefix" or entry.land_proof is None:
        return ((), ())
    return (
        tuple(
            RecoverResult.MergedPrefix(
                node_id=row.node_id,
                pr_number=row.pr_number,
                merge_commit_sha=row.merge_commit_sha,
            )
            for row in entry.land_proof.merged_prefix
        ),
        tuple(
            RecoverResult.RemainderPr(
                pr_number=row.pr_number, state=row.state, head_sha=row.head_sha
            )
            for row in entry.land_proof.remainder
        ),
    )


def _accept_prefix(
    seams: _RecoverRecordSeams,
    train: DeliveryTrain,
    entry: _Classified,
    effects: _LandEffects,
    *,
    consent: _Consent | None,
) -> tuple[str, str]:
    """Confirm, then reclassify and record one external LAND prefix."""
    op = entry.op
    if (
        op.kind is not OperationKind.LAND
        or entry.classification != "external_prefix"
        or entry.land_proof is None
    ):
        raise DeliveryError(
            f"--accept-prefix requires an external_prefix LAND classification — operation "
            f"{op.operation_id} is {op.kind.value} and classified {entry.classification}; "
            "nothing was journaled",
            error_type="accept_blocked",
        )
    merged_rows, remainder_rows = _prefix_preview_rows(entry)
    preview = RecoverResult.AcceptPrefixPreview(
        operation_id=op.operation_id,
        prepared_created=op.prepared.record.created,
        merged_layers=merged_rows,
        remainder=remainder_rows,
        detail=entry.detail,
    )
    if consent is not None and not consent(preview):
        return ("declined", "the accept-prefix confirmation was declined; the journal is untouched")
    fresh = _classify(seams, train, op)
    if fresh.classification != "external_prefix" or fresh.land_proof is None:
        raise DeliveryError(
            f"the world moved while the confirmation was pending: operation "
            f"{op.operation_id} re-classified {fresh.classification} — nothing was "
            "journaled; rerun recover",
            error_type="accept_blocked",
        )
    confirmed = {row.pr_number for row in entry.land_proof.merged_prefix}
    reobserved = {row.pr_number for row in fresh.land_proof.merged_prefix}
    if confirmed != reobserved:
        raise DeliveryError(
            f"the merged-prefix membership changed while the confirmation was pending "
            f"(confirmed PRs {sorted(confirmed)}, re-observed {sorted(reobserved)}) — "
            "nothing was journaled; rerun recover",
            error_type="accept_blocked",
        )
    conclusion = landing.accept_external_prefix(seams, train, op, fresh.land_proof)
    effects.merge_conclusion(conclusion)
    return (
        "accepted_prefix",
        f"accepted the externally merged prefix as a recorded breach "
        f"({len(conclusion.landed_layers)} layer(s) finalized); cascade the remainder with "
        "`perk objective stack sync --base`, then `perk objective stack land` (if the "
        "merged prefix's branch still exists, the remainder PR may still target it — sync "
        "reports that as pr_drift until the merged branch is deleted or the PR retargeted)",
    )


def _hint(request: RecoverRequest, entry: _Classified, *, is_target: bool) -> str:
    """The reported row's routing hint — retry is never recover's verb, so every hint names
    the owning surface."""
    op = entry.op
    if op.kind in (OperationKind.SYNC, OperationKind.ADOPT):
        if entry.classification == "all_after":
            if is_target and request.dry_run:
                return "a real recover would roll this forward automatically"
            return f"rerun with `--operation {op.operation_id}` to roll it forward"
        if entry.classification == "all_before":
            return (
                "abandon with `--abandon`, or rerun `perk objective stack sync` "
                "(a real sync abandons-with-proof and recomputes)"
            )
        return "mixed state — refusing to guess; reconcile the drifted refs and rerun"
    if op.kind is OperationKind.PUBLISH:
        plan_id = record.affected_plans[0] if (record := _prepared(op)) is not None else "?"
        if entry.classification == "all_after":
            return (
                "the push landed — publish's own resume rolls it forward: rerun `/submit` "
                f"for plan #{plan_id}"
            )
        if entry.classification == "all_before":
            return f"abandon with `--abandon`, or rerun `/submit` for plan #{plan_id} to retry"
        return "mixed state — refusing to guess; reconcile the branch/PR/stack and rerun"
    if op.kind is OperationKind.LAND:
        if entry.classification == "all_after":
            if is_target and request.dry_run:
                return "a real recover would roll this forward automatically"
            return f"rerun with `--operation {op.operation_id}` to roll it forward"
        if entry.classification == "all_before":
            return (
                "abandon with `--abandon` (journals reason recovered_before_state with the "
                "reobserved proof), then land again"
            )
        if entry.classification == "external_prefix":
            return (
                "accept the externally merged prefix with `--accept-prefix`; then cascade "
                "the remainder with `perk objective stack sync --base` and land it with "
                "`perk objective stack land` (an undeleted merged-prefix branch can leave "
                "the remainder PR targeting it — sync reports pr_drift until the branch is "
                "deleted or the PR retargeted)"
            )
        if entry.classification == "in_flight":
            return (
                "report-only — a live/unexcludable merge request is never contradicted by "
                "action; rerun recover to converge"
            )
        return "mixed state — refusing to guess; investigate the PRs and the journal"
    return "recovery for this kind is report-only here"


def _prepared(op: OperationState) -> PreparedRecord | None:
    record = op.prepared.record
    return record if isinstance(record, PreparedRecord) else None


def _abandon(
    seams: _RecoverRecordSeams,
    train: DeliveryTrain,
    entry: _Classified,
    *,
    consent: _Consent | None,
) -> tuple[str, str]:
    """Confirm, then reclassify and abandon one all-before operation."""
    op = entry.op
    if op.kind is OperationKind.TRANSFER:
        raise DeliveryError(
            f"operation {op.operation_id} is {op.kind.value} — abandoning it is not "
            "supported here (report-only); conclude it via the owning surface",
            error_type="unsupported_operation_kind",
        )
    if entry.classification != "all_before":
        raise DeliveryError(
            f"--abandon requires every recorded effect verified at its before state — "
            f"operation {op.operation_id} classified {entry.classification}; nothing was "
            "journaled",
            error_type="abandon_blocked",
        )
    preview = RecoverResult.AbandonPreview(
        operation_id=op.operation_id,
        kind=op.kind.value,
        prepared_created=op.prepared.record.created,
        detail=entry.detail,
    )
    if consent is not None and not consent(preview):
        return ("declined", "the abandon confirmation was declined; the journal is untouched")
    fresh = _classify(seams, train, op)
    if fresh.classification != "all_before":
        raise DeliveryError(
            f"the world moved while the confirmation was pending: operation "
            f"{op.operation_id} re-classified {fresh.classification} — nothing was "
            "journaled; rerun recover",
            error_type="abandon_blocked",
        )
    record = _prepared(op)
    assert record is not None
    if op.kind is OperationKind.PUBLISH:
        assert fresh.publish_proof is not None
        seams.persistence.append_outcome(
            train.objective_id,
            OutcomeRecord(
                operation_id=op.operation_id,
                role=EventRole.ABANDONED,
                created=seams.now(),
                observed=publish.publish_abandon_observation(record, fresh.publish_proof),
            ),
        )
    elif op.kind is OperationKind.LAND:
        assert fresh.land_proof is not None
        seams.persistence.append_outcome(
            train.objective_id,
            OutcomeRecord(
                operation_id=op.operation_id,
                role=EventRole.ABANDONED,
                created=seams.now(),
                observed=landing.land_abandon_observation(fresh.land_proof, detail=fresh.detail),
            ),
        )
    else:
        assert fresh.sync_facts is not None and fresh.sync_observed is not None
        sync_mod.abandon_sync_record(
            seams, train.objective_id, record, fresh.sync_facts, fresh.sync_observed
        )
    return ("abandoned", "abandoned with the post-confirmation all-before observation as proof")


# ----------------------------------------------------------------- the convergence pass (§8.51)


def _converge_finalization(
    seams: _RecoverRecordSeams,
    request: RecoverRequest,
    train: DeliveryTrain,
    effects: _LandEffects,
) -> None:
    """The finalization-convergence pass (contracts.md §8.51): GitHub merge completion and
    backend finalization are distinct axes, so recovery re-runs the idempotent
    ``finalize_landed_plan`` for EVERY journal-covered, freshly corroborated merged layer —
    no completeness proxy (plan-close + node-terminal cannot observe the learn-stamp/consume
    effects) — then runs the state-aware close.

    Snapshot semantics: the journal fold is re-read FRESH (a completed/breach record
    appended by this invocation's conclude phase is visible); the objective is re-fetched by
    the close helper; the earlier train snapshot supplies only structural identity
    (branches, checkpoints, layer↔node joins). Layers already finalized by this
    invocation's conclude phase are excluded by ``plan_id`` (no duplicate rows; a
    conclude-phase finalize failure is deliberately NOT retried within the same invocation
    — the next run converges it). Corroboration (the read-only PR check) runs on EVERY
    path, dry-run included: a would-act row with ``finalized: None`` is emitted only for a
    proof-backed layer — a layer that fails to corroborate is a loud skip note on both
    paths, so the preview never promises an action the real run would refuse. Under
    ``--dry-run`` nothing mutates. Merged PRs with no journal coverage are never touched
    (the scope guard). The close waits for a CONVERGED journal: while any
    LAND operation is still unresolved in the fresh fold (e.g. a deferred completed append),
    closing would assemble incomplete reconcile evidence and permanently suppress the
    drive — the close is skipped with a loud note and the next run converges it.

    Evidence rides MORE than the real close transition: an already-closed, journal-complete
    objective (the death-after-close crash signature — both the landing close and the
    NOTHING_TO_LAND arm) re-emits the fresh-fold reconcile evidence with a loud note, so a
    drive suppressed by process death between the close and the evidence step stays
    recoverable here (at-least-once by design; the reconcile pass is idempotent)."""
    try:
        fold = seams.persistence.read_journal(train.objective_id)
    except JournalCorruptionError as exc:
        effects.notes.append(
            f"finalization convergence skipped: the journal fold is unreadable ({exc})"
        )
        return
    covered = _journal_covered_layers(train, fold, effects.notes)
    concluded = {row.plan_id for row in effects.landed_layers}
    for layer, recorded_head, recorded_merge in covered:
        plan_id = layer.plan_id
        if plan_id is None or plan_id in concluded or layer.pr_number is None:
            continue
        proof = _corroborate_covered_layer(
            seams, train, layer, recorded_head, recorded_merge, effects.notes
        )
        if proof is None:
            continue
        if request.dry_run:
            effects.landed_layers.append(
                RecoverResult.LandedLayer(
                    node_id=layer.node_id,
                    plan_id=plan_id,
                    pr_number=layer.pr_number,
                    merge_commit_sha=recorded_merge,
                    base_sha=layer.parent_checkpoint_sha or "",
                    head_sha=recorded_head,
                    finalized=None,  # not attempted — a proof-backed dry-run would-act row
                )
            )
            continue
        landed = landing.finalize_proof_layers(seams, train.objective_id, (proof,), effects.notes)
        effects.landed_layers.extend(_landed_row(row) for row in landed)
    if request.dry_run:
        return
    unresolved_land = [op for op in fold.unresolved if op.kind is OperationKind.LAND]
    if unresolved_land:
        effects.notes.append(
            "convergence close deferred: LAND operation(s) "
            + ", ".join(op.operation_id for op in unresolved_land)
            + " are still unresolved — conclude them first so the close carries complete "
            "reconcile evidence"
        )
        return
    closed = landing.state_aware_close(seams.store, train.objective_id, effects.notes)
    if closed:
        effects.objective_closed = True
    elif not _closed_and_complete(seams, train.objective_id, effects.notes):
        return
    if effects.reconcile_evidence is None:
        evidence = landing.assemble_land_evidence(fold)
        effects.notes.extend(evidence.notes)
        effects.reconcile_evidence = evidence
        if not closed:
            # The close-then-evidence crash repair: process death between the aggregate
            # close and the evidence/drive step would otherwise suppress the reconcile
            # drive PERMANENTLY (a rerun sees "already closed" and never re-assembles).
            # Recover therefore re-emits the fresh-fold evidence for an already-closed,
            # journal-complete objective on EVERY invocation — deliberately at-least-once
            # (the reconcile pass is idempotent; recover is operator-invoked).
            effects.notes.append(
                "objective already closed — re-emitting reconcile evidence (at-least-once; "
                "the reconcile pass is idempotent)"
            )


def _closed_and_complete(seams: _RecoverRecordSeams, objective_id: str, notes: list[str]) -> bool:
    """Whether the objective reads CLOSED with every node terminal — the death-after-close
    crash signature the evidence re-emission repairs. The fresh fetch corroborates the
    CURRENT state, never this invocation's earlier reads. An OPEN/partial state answers
    ``False`` silently (the close arms already reported their own loud notes); a FAILED
    fresh read answers ``False`` loudly — a transient backend error must never silently
    defeat the crash repair (the operator reruns recover instead of trusting a clean
    no-evidence exit)."""
    try:
        state = seams.store.get_objective(objective_id=objective_id)
    except ObjectiveStoreError as exc:
        notes.append(
            "reconcile-evidence re-emission skipped: the fresh objective corroboration "
            f"read failed ({exc}) — rerun recover to retry"
        )
        return False
    if state is None:
        notes.append(
            f"reconcile-evidence re-emission skipped: objective #{objective_id} was not "
            "found on the fresh corroboration read — rerun recover to retry"
        )
        return False
    if state.state == "open":
        return False
    return all(node.status in objective.TERMINAL for node in state.nodes)


def _journal_covered_layers(
    train: DeliveryTrain, fold: JournalFold, notes: list[str]
) -> list[tuple[TrainLayer, str, str]]:
    """The convergence universe: train layers covered by a completed LAND record in the
    fresh fold — the shared prepared⋈completed join (node_id, plan_id, pr_number equal AND
    the recorded head == the layer's ``published_head_sha`` checkpoint). An
    undecodable/unjoinable operation skips with a loud note (fail closed)."""
    coverage: dict[tuple[str, str, int], tuple[str, str]] = {}
    joins, failures = land_records.join_completed_land_operations(fold)
    for join in joins:
        for row in join.layers:
            coverage[(row.node_id, row.plan_id, row.pr_number)] = (
                row.head_sha,
                row.merge_commit_sha,
            )
    notes.extend(
        f"finalization convergence skipped LAND operation {failure.operation_id}: its "
        f"payload is undecodable ({failure.error})"
        for failure in failures
    )
    covered: list[tuple[TrainLayer, str, str]] = []
    for layer in train.layers:
        if layer.plan_id is None or layer.pr_number is None:
            continue
        hit = coverage.get((layer.node_id, layer.plan_id, layer.pr_number))
        if hit is None:
            continue
        recorded_head, recorded_merge = hit
        if layer.published_head_sha != recorded_head:
            # A replanned/republished layer — the recorded head no longer matches the
            # checkpoint; never adopted (the coverage identity rule).
            continue
        covered.append((layer, recorded_head, recorded_merge))
    return covered


def _corroborate_covered_layer(
    seams: _RecoverRecordSeams,
    train: DeliveryTrain,
    layer: TrainLayer,
    recorded_head: str,
    recorded_merge: str,
    notes: list[str],
) -> landing.MergedLayerProof | None:
    """One covered layer's FRESH merged corroboration for the convergence pass: MERGED with
    the recorded merge commit, at the recorded head, on the layer branch, onto a legitimate
    base. Any mismatch or read failure is a loud note + skip (never a guess)."""
    assert layer.plan_id is not None and layer.pr_number is not None  # caller-filtered
    try:
        evidence = seams.merged_evidence(number=layer.pr_number, repo_root=seams.repo_root)
    except GitHubError as exc:
        notes.append(
            f"finalization convergence skipped layer {layer.node_id}: could not read "
            f"PR #{layer.pr_number} ({exc})"
        )
        return None
    if (
        evidence is None
        or evidence.state != "MERGED"
        or evidence.merge_commit_sha != recorded_merge
        or evidence.head_sha != recorded_head
        or evidence.head_ref != layer.branch
        or evidence.base_ref not in (layer.expected_pr_base, train.base)
    ):
        observed = (
            f"state={evidence.state} base={evidence.base_ref!r} "
            f"head-ref={evidence.head_ref!r} head={evidence.head_sha} "
            f"merge_commit={evidence.merge_commit_sha}"
            if evidence is not None
            else "absent"
        )
        notes.append(
            f"finalization convergence skipped layer {layer.node_id}: PR "
            f"#{layer.pr_number} did not corroborate the recorded merge (observed "
            f"{observed}; expected MERGED as {recorded_merge[:12]} at {recorded_head[:12]})"
        )
        return None
    return landing.MergedLayerProof(
        node_id=layer.node_id,
        plan_id=layer.plan_id,
        pr_number=layer.pr_number,
        base_sha=layer.parent_checkpoint_sha or "",
        head_sha=recorded_head,
        merge_commit_sha=recorded_merge,
        expected_base_ref=layer.expected_pr_base,
    )


# ----------------------------------------------------------------- the orphan sweep


def _sweep(
    context: _RecoverContext,
    request: RecoverRequest,
    *,
    worktree_root: Path,
) -> tuple[
    tuple[str, ...],
    tuple[str, ...],
    tuple[RecoverResult.SweepFailure, ...],
    str | None,
]:
    """Classify residue, then delete refs, worktrees, and finally prune once."""

    def list_refs(repo_root: Path, prefix: str) -> list[str]:
        del repo_root
        return list(context.git.list_refs(prefix))

    def worktree_admin_dirs(repo_root: Path) -> list[Path]:
        del repo_root
        return list(context.git.worktree_admin_paths())

    scan = observe_orphans(
        context.repo_root,
        worktree_root=worktree_root,
        iter_manifests=context.runtime.iter_manifests,
        list_refs=list_refs,
        worktree_dirs=context.runtime.worktree_dirs,
        worktree_admin_dirs=worktree_admin_dirs,
    )
    if scan.skipped is not None:
        return ((), (), (), scan.skipped)
    if request.dry_run:
        return (
            tuple(str(path) for path in (*scan.worktrees, *scan.stale_admin)),
            scan.refs,
            (),
            None,
        )
    swept_refs: list[str] = []
    swept_worktrees: list[str] = []
    failures: list[RecoverResult.SweepFailure] = []
    for ref in scan.refs:
        try:
            context.git.delete_ref(ref)
            swept_refs.append(ref)
        except (git_mod.GitError, OSError) as exc:
            failures.append(RecoverResult.SweepFailure(target=ref, error=str(exc)))
    for path in scan.worktrees:
        try:
            context.git.remove_worktree(path)
            swept_worktrees.append(str(path))
        except (git_mod.GitError, OSError) as exc:
            failures.append(RecoverResult.SweepFailure(target=str(path), error=str(exc)))
    try:
        context.git.prune_worktrees()
        swept_worktrees.extend(str(path) for path in scan.stale_admin)
    except (git_mod.GitError, OSError) as exc:
        failures.append(RecoverResult.SweepFailure(target="worktree-prune", error=str(exc)))
        failures.extend(
            RecoverResult.SweepFailure(target=str(path), error="the worktree-admin prune failed")
            for path in scan.stale_admin
        )
    return (tuple(swept_worktrees), tuple(swept_refs), tuple(failures), None)
