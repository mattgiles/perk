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
- **LAND** — never decoded or observed: classification ``unsupported``, report-only
  rows; ``--abandon`` on it is a typed refusal.

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

import contextlib
import re
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path

from perk import plan
from perk.delivery import continuation, observe, oplock, publish
from perk.delivery import sync as sync_mod
from perk.delivery import transfer as transfer_mod
from perk.delivery.journal import (
    EventRole,
    JournalCorruptionError,
    OperationKind,
    OperationState,
    OutcomeRecord,
    PreparedRecord,
)
from perk.delivery.persistence import resolve_train_persistence
from perk.delivery.train import DeliveryTrain, NoDeliveryTrain, TrainStatus
from perk.github import prs, stacks
from perk.substrate import git as git_mod


class RecoverError(Exception):
    """A recovery failed or refused. ``error_type`` is the stable machine code the CLI
    boundary maps onto its failure envelope."""

    def __init__(
        self,
        message: str,
        *,
        error_type: str,  # not_stacked | invalid_input | operation_not_found
        # | operation_ambiguous | abandon_blocked | unsupported_operation_kind
        # | operation_in_progress | git_error | github_error (contracts.md §8.51;
        # git_error/github_error are the CLI's mapping of raw infra raises, and the
        # roll-forward tail's SyncError arms pass through under the §8.49 vocabulary)
    ) -> None:
        super().__init__(message)
        self.error_type = error_type


# ----------------------------------------------------------------- result shapes


@dataclass(frozen=True)
class OperationRow:
    """One unresolved operation's classification + what this invocation did about it."""

    operation_id: str
    kind: str  # publish | sync | adopt | transfer | land
    prepared_created: str
    classification: str  # all_before | all_after | mixed | unsupported
    action: str  # reported | rolled_forward | abandoned | declined
    detail: str


@dataclass(frozen=True)
class SweepFailure:
    """One sweep target that could not be removed — recorded loudly, never a failure."""

    target: str
    error: str


@dataclass(frozen=True)
class AbandonPreview:
    """What the abandon confirmation renders: the target's identity and the all-before
    proof the affirmative answer will journal against."""

    operation_id: str
    kind: str
    prepared_created: str
    detail: str


@dataclass(frozen=True)
class RecoverResult:
    """The outcome of one recover invocation (the §8.51 envelope). Under ``dry_run`` the
    swept lists carry the WOULD-BE sweep targets (nothing was deleted) and every row's
    action stays ``reported``."""

    objective_id: str
    objective_url: str
    redirected_from: str | None
    dry_run: bool
    selection_required: bool
    operations: tuple[OperationRow, ...]
    swept_worktrees: tuple[str, ...]
    swept_refs: tuple[str, ...]
    sweep_failures: tuple[SweepFailure, ...]
    sweep_skipped: str | None


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


# ----------------------------------------------------------------- the bundle + entry


def _default_fetch(repo: Path, refspecs: list[str]) -> None:
    git_mod.fetch_refspecs(repo, refspecs)


def _default_worktree_remove(repo: Path, path: Path) -> None:
    git_mod.worktree_remove(repo, path, force=True)


@dataclass(frozen=True)
class _Recover:
    """The per-invocation bundle. Structurally satisfies :class:`sync.SyncRecordSeams`
    (the SYNC/ADOPT recovery core) and :class:`publish.PublishProofSeams` (the PUBLISH
    proof), and composes transfer's roll-forward seams for the fold-first TRANSFER arm. The
    kind-specific decoders consume only their owned observation seams."""

    repo_root: Path
    dry_run: bool
    abandon: bool
    operation_id: str | None
    approve: Callable[[AbandonPreview], bool] | None
    worktree_root: Path
    persistence: sync_mod.SyncPersistence
    transfer_seams_factory: Callable[[Path], transfer_mod.TransferSeams]
    reconstruct: Callable[[Path, str], TrainStatus]
    pr_facts: Callable[..., object]
    stack_read: Callable[..., object]
    pr_for_branch: Callable[..., object]
    fetch: Callable[[Path, list[str]], None]
    remote_head: Callable[[Path, str], str | None]
    list_refs: Callable[[Path, str], list[str]]
    delete_ref: Callable[[Path, str], None]
    worktree_remove: Callable[[Path, Path], None]
    worktree_prune: Callable[[Path], None]
    iter_manifests: Callable[[Path], continuation.ManifestScan]
    worktree_dirs: Callable[[Path], list[Path]]
    worktree_admin_dirs: Callable[[Path], list[Path]]
    sleep: Callable[[float], None]
    now: Callable[[], str]


def recover_operations(
    repo_root: Path,
    *,
    objective_id: str,
    worktree_root: Path,
    dry_run: bool = False,
    abandon: bool = False,
    operation_id: str | None = None,
    approve: Callable[[AbandonPreview], bool] | None = None,
    reconstruct: Callable[[Path, str], TrainStatus] = observe.reconstruct_repo_train,
    persistence_factory: Callable[[Path], sync_mod.SyncPersistence] = resolve_train_persistence,
    transfer_seams_factory: Callable[
        [Path], transfer_mod.TransferSeams
    ] = transfer_mod.resolve_transfer_seams,
    pr_facts: Callable[..., object] = stacks.pr_delivery_facts,
    stack_read: Callable[..., object] = stacks.stack_for_pr,
    pr_for_branch: Callable[..., object] = prs.find_pr_for_branch,
    fetch: Callable[[Path, list[str]], None] = _default_fetch,
    remote_head: Callable[[Path, str], str | None] = git_mod.remote_branch_head,
    list_refs: Callable[[Path, str], list[str]] = git_mod.list_refs,
    delete_ref: Callable[[Path, str], None] = git_mod.delete_ref,
    worktree_remove: Callable[[Path, Path], None] = _default_worktree_remove,
    worktree_prune: Callable[[Path], None] = git_mod.worktree_prune,
    iter_manifests: Callable[[Path], continuation.ManifestScan] = continuation.iter_manifests,
    worktree_dirs: Callable[[Path], list[Path]] = _default_worktree_dirs,
    worktree_admin_dirs: Callable[[Path], list[Path]] = _default_worktree_admin_dirs,
    lock: Callable[[Path], AbstractContextManager[None]] = oplock.stack_operation_lock,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], str] = plan.now_iso,
) -> RecoverResult:
    """Classify every unresolved operation, conclude the one selected target (automatic
    all-after roll-forward for SYNC/ADOPT/TRANSFER, confirmed abandon-with-proof under
    ``--abandon``), then sweep the orphaned residue. ``--dry-run`` reports everything and
    mutates nothing. No ``run_id``: conclude-only recovery needs no new run identity."""
    if dry_run and abandon:
        # Flag validation lives at the CLI boundary; this is the defensive assert-guard.
        raise RecoverError(
            "--dry-run and --abandon are mutually exclusive — preview first, then abandon",
            error_type="invalid_input",
        )
    rec = _Recover(
        repo_root=repo_root,
        dry_run=dry_run,
        abandon=abandon,
        operation_id=operation_id,
        approve=approve,
        worktree_root=worktree_root,
        persistence=persistence_factory(repo_root),
        transfer_seams_factory=transfer_seams_factory,
        reconstruct=reconstruct,
        pr_facts=pr_facts,
        stack_read=stack_read,
        pr_for_branch=pr_for_branch,
        fetch=fetch,
        remote_head=remote_head,
        list_refs=list_refs,
        delete_ref=delete_ref,
        worktree_remove=worktree_remove,
        worktree_prune=worktree_prune,
        iter_manifests=iter_manifests,
        worktree_dirs=worktree_dirs,
        worktree_admin_dirs=worktree_admin_dirs,
        sleep=sleep,
        now=now,
    )
    with _held_lock(lock, repo_root):
        return _recover(rec, objective_id)


@contextlib.contextmanager
def _held_lock(
    lock: Callable[[Path], AbstractContextManager[None]], repo_root: Path
) -> Iterator[None]:
    try:
        with lock(repo_root):
            yield
    except oplock.OperationLockBusy as exc:
        raise RecoverError(str(exc), error_type="operation_in_progress") from exc


# ----------------------------------------------------------------- classification


@dataclass(frozen=True)
class _Classified:
    """One operation's classification with the kind-specific evidence the action phase
    reuses (sync facts/observation, publish proof, or the decoded transfer record)."""

    op: OperationState
    classification: str
    detail: str
    sync_facts: sync_mod.SyncRecordFacts | None = None
    sync_observed: tuple[str | None, ...] | None = None
    publish_proof: publish.PublishRecordProof | None = None
    transfer_record: PreparedRecord | None = None


def _classify(rec: _Recover, train: DeliveryTrain, op: OperationState) -> _Classified:
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
        observed = sync_mod.observe_sync_record(rec, facts)
        classification = sync_mod.classify_sync_observation(facts, observed)
        pairs = [(entry.branch, sha) for sha, entry in zip(observed, facts.recorded, strict=True)]
        detail = {
            "all_after": "every recorded ref verified at its prepared after state",
            "all_before": "every recorded ref verified at its prepared before state",
            "mixed": f"the recorded refs verified in a MIXED state ({pairs})",
        }[classification]
        return _Classified(op, classification, detail, sync_facts=facts, sync_observed=observed)
    if op.kind is OperationKind.PUBLISH:
        proof = publish.classify_publish_record(rec, train, record)
        return _Classified(op, proof.classification, proof.detail, publish_proof=proof)
    # LAND — plus the impossible-by-construction fallback for a TRANSFER sharing a fold
    # with other unresolved operations (a sole-unresolved TRANSFER dispatched to the
    # transfer arm before any train gate).
    return _Classified(
        op,
        "unsupported",
        f"{op.kind.value} recovery is report-only — conclude it via the owning surface",
    )


# ----------------------------------------------------------------- the protocol


def _recover(rec: _Recover, objective_id: str) -> RecoverResult:
    # §8.51 fold-first: read the REQUESTED objective's succession journal before any train
    # gate. An unresolved TRANSFER must dispatch before the `not_stacked` rejection and the
    # structural-blocker gate — a mid-transfer predecessor necessarily shows intentional
    # `wrong_owner`/`node_link_mismatch` blockers, and a finalized-but-uncompleted
    # stacked→incremental transfer has no train at all. Both gates stay in force for
    # PUBLISH/SYNC/ADOPT (the reconstruction below re-folds for those).
    fold = rec.persistence.read_journal(objective_id)
    if len(fold.unresolved) == 1 and fold.unresolved[0].kind is OperationKind.TRANSFER:
        # The one-unresolved-per-lineage fold gate makes an unresolved TRANSFER the sole
        # unresolved operation; a fold that violates that (multiple unresolved) is an
        # impossible-by-construction state that falls through to the report-only flow.
        return _recover_transfer(rec, objective_id, fold.unresolved[0])
    # §8.54 fold-first sole-PUBLISH routing: a REAL unresolved PUBLISH can itself produce
    # structural cancellation/remote/checkpoint findings (`publish_outcome_pending` rides with
    # `canceled_remote_work`/`checkpoint_prefix_gap`/…), so the generic structural gate would
    # dead-end exactly the operation recover exists to conclude. When the requested fold's
    # SOLE unresolved operation is PUBLISH, the existing PUBLISH classifier/conclusion
    # machinery runs WITHOUT the generic gate — `classify_publish_record`'s
    # `_validate_resume_context` plus the exact before/after branch/PR/stack proof stays the
    # safety gate, so the bypass never authorizes checkpoint/identity mutation. Other kinds
    # and multi-unresolved states keep today's gates.
    sole_publish = len(fold.unresolved) == 1 and fold.unresolved[0].kind is OperationKind.PUBLISH
    train = rec.reconstruct(rec.repo_root, objective_id)
    if isinstance(train, NoDeliveryTrain):
        raise RecoverError(
            f"objective {train.objective_id} has no delivery train ({train.reason})",
            error_type="not_stacked",
        )
    if not sole_publish:
        # Sync's fail-closed structural gate (§8.49 step 4) applies here too: a mis-linked
        # layer (wrong_owner / wrong_lineage / node_link_mismatch …) can still corroborate on
        # branch/checkpoint fields, and a roll-forward would checkpoint into the wrong plan.
        # The typed SyncError (claimed_prefix_malformed) passes through the CLI verbatim.
        sync_mod.refuse_structural_blockers(train)
    fold = rec.persistence.read_journal(train.objective_id)

    # Phase 2: classify EVERY unresolved operation (display never mutates).
    classified = [_classify(rec, train, op) for op in fold.unresolved]

    # Phase 3: target selection (decision 19) — any action applies to exactly one target.
    ids = [entry.op.operation_id for entry in classified]
    target_id: str | None = None
    selection_required = False
    if rec.operation_id is not None:
        if rec.operation_id not in ids:
            listed = ", ".join(ids) or "<none>"
            raise RecoverError(
                f"operation {rec.operation_id} is not unresolved on this train — "
                f"unresolved: {listed}",
                error_type="operation_not_found",
            )
        target_id = rec.operation_id
    elif len(classified) == 1:
        target_id = ids[0]
    elif len(classified) > 1:
        if rec.abandon:
            raise RecoverError(
                f"several operations are unresolved ({', '.join(ids)}) — name the abandon "
                "target with --operation",
                error_type="operation_ambiguous",
            )
        selection_required = True
    elif rec.abandon:
        raise RecoverError(
            "no unresolved operation exists — nothing to abandon",
            error_type="operation_not_found",
        )

    # Phase 4: the action phase (rows are built either way; dry-run never acts).
    rows = [
        _conclude(rec, train, entry, is_target=entry.op.operation_id == target_id)
        for entry in classified
    ]

    # Phase 5: the orphan sweep — reached only on a success path (every refusal raised).
    swept_worktrees, swept_refs, failures, skipped = _sweep(rec)

    return RecoverResult(
        objective_id=train.objective_id,
        objective_url=train.objective_url,
        redirected_from=train.redirected_from,
        dry_run=rec.dry_run,
        selection_required=selection_required,
        operations=tuple(rows),
        swept_worktrees=swept_worktrees,
        swept_refs=swept_refs,
        sweep_failures=failures,
        sweep_skipped=skipped,
    )


# ----------------------------------------------------------------- the TRANSFER arm (§8.53)


def _recover_transfer(rec: _Recover, objective_id: str, op: OperationState) -> RecoverResult:
    """Conclude the sole unresolved TRANSFER: classify against fresh authority (manifest
    decode + run_id successor lookup + corroboration), then roll forward / confirmed-abandon
    / report — all under the already-held operation lock. The orphan sweep still runs last."""
    if rec.operation_id is not None and rec.operation_id != op.operation_id:
        raise RecoverError(
            f"operation {rec.operation_id} is not unresolved on this objective — unresolved: "
            f"{op.operation_id}",
            error_type="operation_not_found",
        )
    seams = rec.transfer_seams_factory(rec.repo_root)
    entry = _classify_transfer(seams, op)
    row = _conclude_transfer(rec, seams, objective_id, entry)
    swept_worktrees, swept_refs, failures, skipped = _sweep(rec)
    state = seams.store.get_objective(objective_id=objective_id)
    return RecoverResult(
        objective_id=objective_id,
        objective_url=state.url if state is not None else "",
        redirected_from=None,
        dry_run=rec.dry_run,
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
    rec: _Recover, seams: transfer_mod.TransferSeams, objective_id: str, entry: _Classified
) -> OperationRow:
    """The TRANSFER action phase: automatic all-after roll-forward through transfer's
    lock-assumed core, the confirmed abandon arm under ``--abandon``, else a reported row
    with the routing hint."""
    op = entry.op
    action = "reported"
    detail = entry.detail
    if rec.abandon:
        action, outcome = _abandon_transfer(rec, seams, objective_id, entry)
        detail = f"{entry.detail} — {outcome}"
    elif (
        entry.classification == "all_after"
        and entry.transfer_record is not None
        and not rec.dry_run
    ):
        successor = transfer_mod.roll_forward_transfer(seams, record=entry.transfer_record)
        action = "rolled_forward"
        detail = (
            f"{entry.detail} — rolled forward to completion (successor {successor.id}: "
            "ownership stamped, projection verified, predecessor finalized, completion "
            "journaled)"
        )
    else:
        detail = f"{entry.detail} — {_transfer_hint(rec, entry)}"
    return OperationRow(
        operation_id=op.operation_id,
        kind=op.kind.value,
        prepared_created=op.prepared.record.created,
        classification=entry.classification,
        action=action,
        detail=detail,
    )


def _transfer_hint(rec: _Recover, entry: _Classified) -> str:
    """The reported TRANSFER row's routing hint (hints name the predecessor id — the
    documented recovery entry for an interrupted transfer)."""
    predecessor = entry.transfer_record.objective_id if entry.transfer_record is not None else "?"
    if entry.classification == "all_after":
        if rec.dry_run:
            return "a real recover would roll this forward automatically"
        return f"rerun `perk objective stack recover {predecessor}` to roll it forward"
    if entry.classification == "all_before":
        return (
            "abandon with `--abandon`, or re-save the replan (the save abandons-with-proof "
            "and re-prepares in the same invocation)"
        )
    return "corrupt/mixed state — refusing to guess; investigate the manifest and the successor"


def _abandon_transfer(
    rec: _Recover, seams: transfer_mod.TransferSeams, objective_id: str, entry: _Classified
) -> tuple[str, str]:
    """The confirmed TRANSFER abandon arm: an all-before classification gate, the approve
    callback, then the from-scratch RE-classification (the approval pause is a race boundary)
    whose post-confirmation observation is the journaled proof."""
    op = entry.op
    if entry.classification != "all_before":
        raise RecoverError(
            f"--abandon requires every recorded effect verified at its before state — "
            f"operation {op.operation_id} classified {entry.classification}; nothing was "
            "journaled",
            error_type="abandon_blocked",
        )
    preview = AbandonPreview(
        operation_id=op.operation_id,
        kind=op.kind.value,
        prepared_created=op.prepared.record.created,
        detail=entry.detail,
    )
    if rec.approve is not None and not rec.approve(preview):
        return ("declined", "the abandon confirmation was declined; the journal is untouched")
    fresh = _classify_transfer(seams, op)
    if fresh.classification != "all_before":
        raise RecoverError(
            f"the world moved while the confirmation was pending: operation "
            f"{op.operation_id} re-classified {fresh.classification} — nothing was "
            "journaled; rerun recover",
            error_type="abandon_blocked",
        )
    record = fresh.transfer_record
    assert record is not None  # guaranteed: an all_before classification decoded it
    rec.persistence.append_outcome(
        objective_id,
        OutcomeRecord(
            operation_id=op.operation_id,
            role=EventRole.ABANDONED,
            created=rec.now(),
            observed=transfer_mod.transfer_abandon_observation(record),
        ),
    )
    return ("abandoned", "abandoned with the post-confirmation all-before observation as proof")


def _conclude(
    rec: _Recover, train: DeliveryTrain, entry: _Classified, *, is_target: bool
) -> OperationRow:
    """One train-backed row's action: confirmed/re-classified abandon or automatic
    record-driven all-after roll-forward for the target; everything else is reported with a
    routing hint. A sole TRANSFER takes the earlier fold-first arm."""
    op = entry.op
    resumable = op.kind in (OperationKind.SYNC, OperationKind.ADOPT)
    action = "reported"
    detail = entry.detail
    if rec.abandon and is_target:
        action, outcome = _abandon(rec, train, entry)
        detail = f"{entry.detail} — {outcome}"
    elif (
        is_target
        and resumable
        and entry.classification == "all_after"
        and entry.sync_facts is not None
        and not rec.dry_run
    ):
        record = op.prepared.record
        assert isinstance(record, PreparedRecord)  # guaranteed by the classification
        layers = sync_mod.roll_forward_sync_record(rec, train, record, entry.sync_facts)
        action = "rolled_forward"
        moved = ", ".join(f"{layer.branch}@{layer.after_sha}" for layer in layers)
        detail = (
            f"{entry.detail} — rolled forward under the same operation "
            f"(checkpoints + completion journaled; {moved})"
        )
    else:
        detail = f"{entry.detail} — {_hint(rec, entry, is_target=is_target)}"
    return OperationRow(
        operation_id=op.operation_id,
        kind=op.kind.value,
        prepared_created=op.prepared.record.created,
        classification=entry.classification,
        action=action,
        detail=detail,
    )


def _hint(rec: _Recover, entry: _Classified, *, is_target: bool) -> str:
    """The reported row's routing hint — retry is never recover's verb, so every hint names
    the owning surface."""
    op = entry.op
    if op.kind in (OperationKind.SYNC, OperationKind.ADOPT):
        if entry.classification == "all_after":
            if is_target and rec.dry_run:
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
    return "LAND recovery is report-only here"


def _prepared(op: OperationState) -> PreparedRecord | None:
    record = op.prepared.record
    return record if isinstance(record, PreparedRecord) else None


def _abandon(rec: _Recover, train: DeliveryTrain, entry: _Classified) -> tuple[str, str]:
    """The confirmed abandon arm: kind + classification gates, the approve callback, then
    the from-scratch RE-classification (decision 18 — the approval pause is a race
    boundary) whose post-confirmation observation is the journaled proof."""
    op = entry.op
    if op.kind in (OperationKind.TRANSFER, OperationKind.LAND):
        raise RecoverError(
            f"operation {op.operation_id} is {op.kind.value} — abandoning it is not "
            "supported here (report-only); conclude it via the owning surface",
            error_type="unsupported_operation_kind",
        )
    if entry.classification != "all_before":
        raise RecoverError(
            f"--abandon requires every recorded effect verified at its before state — "
            f"operation {op.operation_id} classified {entry.classification}; nothing was "
            "journaled",
            error_type="abandon_blocked",
        )
    preview = AbandonPreview(
        operation_id=op.operation_id,
        kind=op.kind.value,
        prepared_created=op.prepared.record.created,
        detail=entry.detail,
    )
    if rec.approve is not None and not rec.approve(preview):
        return ("declined", "the abandon confirmation was declined; the journal is untouched")
    fresh = _classify(rec, train, op)
    if fresh.classification != "all_before":
        raise RecoverError(
            f"the world moved while the confirmation was pending: operation "
            f"{op.operation_id} re-classified {fresh.classification} — nothing was "
            "journaled; rerun recover",
            error_type="abandon_blocked",
        )
    record = _prepared(op)
    assert record is not None  # guaranteed: an all_before classification decoded it
    if op.kind is OperationKind.PUBLISH:
        assert fresh.publish_proof is not None
        rec.persistence.append_outcome(
            train.objective_id,
            OutcomeRecord(
                operation_id=op.operation_id,
                role=EventRole.ABANDONED,
                created=rec.now(),
                observed=publish.publish_abandon_observation(record, fresh.publish_proof),
            ),
        )
    else:
        assert fresh.sync_facts is not None and fresh.sync_observed is not None
        sync_mod.abandon_sync_record(
            rec, train.objective_id, record, fresh.sync_facts, fresh.sync_observed
        )
    return ("abandoned", "abandoned with the post-confirmation all-before observation as proof")


# ----------------------------------------------------------------- the orphan sweep


def _sweep(
    rec: _Recover,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[SweepFailure, ...], str | None]:
    """Phase 5 (decision 7): classify, then — unless dry-run or the unparseable-manifest
    fail-safe fired — attempt every target (refs, then worktrees, then ONE prune), with
    per-item failures recorded loudly. Under dry-run the classified targets ride the result
    as the would-be sweep (nothing deleted)."""
    scan = observe_orphans(
        rec.repo_root,
        worktree_root=rec.worktree_root,
        iter_manifests=rec.iter_manifests,
        list_refs=rec.list_refs,
        worktree_dirs=rec.worktree_dirs,
        worktree_admin_dirs=rec.worktree_admin_dirs,
    )
    if scan.skipped is not None:
        return ((), (), (), scan.skipped)
    if rec.dry_run:
        return (
            tuple(str(path) for path in (*scan.worktrees, *scan.stale_admin)),
            scan.refs,
            (),
            None,
        )
    swept_refs: list[str] = []
    swept_worktrees: list[str] = []
    failures: list[SweepFailure] = []
    for ref in scan.refs:
        try:
            rec.delete_ref(rec.repo_root, ref)
            swept_refs.append(ref)
        except (git_mod.GitError, OSError) as exc:
            failures.append(SweepFailure(target=ref, error=str(exc)))
    for path in scan.worktrees:
        try:
            rec.worktree_remove(rec.repo_root, path)
            swept_worktrees.append(str(path))
        except (git_mod.GitError, OSError) as exc:
            failures.append(SweepFailure(target=str(path), error=str(exc)))
    try:
        # One unconditional prune: clears the stale worktree-admin entries (directories
        # already gone) the scan classified, plus any admin records the removals left.
        rec.worktree_prune(rec.repo_root)
        swept_worktrees.extend(str(path) for path in scan.stale_admin)
    except (git_mod.GitError, OSError) as exc:
        failures.append(SweepFailure(target="worktree-prune", error=str(exc)))
        failures.extend(
            SweepFailure(target=str(path), error="the worktree-admin prune failed")
            for path in scan.stale_admin
        )
    return (tuple(swept_worktrees), tuple(swept_refs), tuple(failures), None)
