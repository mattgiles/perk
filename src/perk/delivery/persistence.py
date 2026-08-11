"""``TrainPersistence`` — the backend-aligned train-persistence adapter (contracts.md §8.43).

The one coherent persistence view over a delivery train's durable logical state: the operation
journal (read via succession folding, written via the gated read-back append) plus the typed
writers for the rest of the stored train state (the checkpoint pair, plan ownership, layer
identity, the objective lineage stamp). Composes the selected :class:`ObjectiveStore` and
:class:`IssueBackend` — one committed ``[issues]`` selection drives both, so the journal carrier
and the comment ops are always backend-aligned.

Import direction: ``perk.delivery`` imports the ``perk.backends.*`` contracts one-directionally
and calls only Protocol surfaces (never the ``perk.github`` gateway directly); nothing in
``perk/backends/`` imports ``perk.delivery``.

Append disciplines (the architecture's cross-machine recovery contract):

- **Read back every append before crossing its boundary** — an append succeeds only once a
  rescan finds the deterministic event key with a byte-identical canonical payload.
- **Retries never substitute for read convergence** — on an ambiguous POST (the backend raised;
  the write may have landed) the carrier is rescanned FIRST; only a proven-absent event earns
  the one bounded retry, and a still-ambiguous append raises :class:`JournalAppendAmbiguous`.
- **One unresolved remote-mutating operation per lineage** — ``append_prepared`` refuses while
  any operation lacks a terminal outcome (recovery appends outcomes, never a second prepared).
"""

import contextlib
from dataclasses import dataclass, replace
from pathlib import Path

from perk.backends.issue_backend import IssueBackend, IssueBackendError
from perk.backends.objective_store import ObjectiveState, ObjectiveStore
from perk.backends.resolve import resolve_issue_backend, resolve_objective_store
from perk.delivery.journal import (
    EventRole,
    JournalCorruptionError,
    JournalEvent,
    JournalFold,
    OperationKind,
    OutcomeRecord,
    PreparedRecord,
    canonical_payload,
    ensure_event_size,
    fold_events,
    parse_journal_comment,
    render_event,
)

# The supersession-chain walk's depth cap (active objective + predecessors); a breach is
# corruption — no legitimate lineage supersedes itself 50 times.
_CHAIN_DEPTH_CAP = 50


class TrainPersistenceError(Exception):
    """A train-persistence operation failed (caller bug / stored-state mismatch)."""


class UnresolvedOperationError(TrainPersistenceError):
    """``append_prepared`` refused: the lineage already carries an unresolved operation (the
    one-unresolved-remote-mutation-per-lineage gate). Recovery appends outcomes, never a second
    prepared."""


class JournalAppendAmbiguous(TrainPersistenceError):
    """An append remained ambiguous after read convergence and the one bounded retry: the event
    could not be proven present OR absent. The remote effect the event guards must not proceed
    until a rescan finds the deterministic event key."""


@dataclass(frozen=True)
class AppendResult:
    """The result of one journal append. ``existed=True`` means the byte-identical event was
    already on the carrier (an idempotent re-append; nothing was written)."""

    operation_id: str
    role: EventRole
    existed: bool


def resolve_train_persistence(repo_root: Path) -> "TrainPersistence":
    """Compose the repo's train persistence from the committed ``[issues]`` selection — the
    backend-aligned guarantee: one selection drives both the objective store (the carrier
    resolver) and the issue backend (the comment ops)."""
    return TrainPersistence(resolve_objective_store(repo_root), resolve_issue_backend(repo_root))


def _header_str(header: dict[str, object], key: str, *, objective_id: str) -> str | None:
    """A nullable string header field, fail-closed on junk (a non-string value is tampering /
    corruption territory, never silently coerced)."""
    value = header.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        return value
    raise TrainPersistenceError(
        f"objective {objective_id}: header field {key!r} is not a string ({value!r})"
    )


class TrainPersistence:
    """The train-persistence adapter over one ``(ObjectiveStore, IssueBackend)`` pair."""

    def __init__(self, store: ObjectiveStore, issues: IssueBackend) -> None:
        self._store = store
        self._issues = issues

    # ------------------------------------------------------------------ journal reads

    def read_journal(self, objective_id: str) -> JournalFold:
        """The succession-folding journal read: walk the ``supersedes`` chain from the active
        objective, read every chain member's carrier, parse the perk-marked events, and fold
        them against the active objective's ``delivery_lineage``.

        Raises :class:`TrainPersistenceError` when the objective is absent (a journal read
        against a missing objective is a caller bug, never an empty journal);
        :class:`JournalCorruptionError` on a supersession cycle / depth breach or any corrupt
        event.
        """
        chain, lineage = self._supersession_chain(objective_id)
        events: list[JournalEvent] = []
        for member_id in chain:
            events.extend(self._carrier_events(member_id))
        return fold_events(events, expected_lineage=lineage)

    def _supersession_chain(self, objective_id: str) -> tuple[list[str], str | None]:
        """The active objective's id + every predecessor id (via ``supersedes``), plus the
        active header's ``delivery_lineage``. Cycle guard + depth cap breach → corruption."""
        state = self._require_objective(objective_id)
        lineage = _header_str(state.header, "delivery_lineage", objective_id=objective_id)
        chain = [objective_id]
        seen = {objective_id}
        current = state
        current_id = objective_id
        while True:
            predecessor_id = _header_str(current.header, "supersedes", objective_id=current_id)
            if predecessor_id is None:
                return chain, lineage
            if predecessor_id in seen:
                raise JournalCorruptionError(
                    f"supersession cycle at objective {predecessor_id} "
                    f"(walking the chain from {objective_id})"
                )
            if len(chain) >= _CHAIN_DEPTH_CAP:
                raise JournalCorruptionError(
                    f"supersession chain from objective {objective_id} exceeds the depth cap "
                    f"({_CHAIN_DEPTH_CAP})"
                )
            predecessor = self._store.get_objective(objective_id=predecessor_id)
            if predecessor is None:
                raise TrainPersistenceError(
                    f"objective {current_id} supersedes {predecessor_id}, which does not exist — "
                    "the journal chain is unreadable"
                )
            seen.add(predecessor_id)
            chain.append(predecessor_id)
            current = predecessor
            current_id = predecessor_id

    def _carrier_events(self, member_objective_id: str) -> list[JournalEvent]:
        """One chain member's parsed journal events, stamped with the member as their carrier
        objective. Unmarked comments are dropped (unrelated DATA); corruption propagates."""
        carrier = self._carrier_id(member_objective_id)
        events: list[JournalEvent] = []
        for comment in self._issues.read_comments(issue_id=carrier):
            event = parse_journal_comment(
                comment.body,
                comment_id=comment.id,
                created_at=comment.created_at,
                edited_at=comment.edited_at,
                carrier=carrier,
            )
            if event is not None:
                events.append(replace(event, carrier_objective_id=member_objective_id))
        return events

    def _require_objective(self, objective_id: str) -> ObjectiveState:
        state = self._store.get_objective(objective_id=objective_id)
        if state is None:
            raise TrainPersistenceError(f"objective {objective_id} not found")
        return state

    def _carrier_id(self, objective_id: str) -> str:
        carrier = self._store.journal_carrier_id(objective_id=objective_id)
        if carrier is None:
            raise TrainPersistenceError(
                f"objective {objective_id} has no journal carrier (objective absent)"
            )
        return carrier

    # ------------------------------------------------------------------ journal appends

    def append_prepared(self, objective_id: str, record: PreparedRecord) -> AppendResult:
        """The gated, read-back ``prepared`` append onto the ACTIVE objective's carrier.

        Gates (in order): the record's ``objective_id`` must name the active objective (a
        lineage is shared across supersession, so identity is checked separately — a stale
        record must never persist a wrong objective-at-preparation claim); the active
        objective's stored ``delivery_lineage`` must equal the record's (fail closed); an
        existing byte-identical prepared for this ``operation_id`` is an idempotent success
        (``existed=True``) while a differing one is corruption; any OTHER unresolved operation
        refuses the append (:class:`UnresolvedOperationError` — the one-unresolved-per-lineage
        rule). The write follows the size-cap + ambiguity + read-back discipline (module
        docstring).
        """
        if record.objective_id != objective_id:
            raise TrainPersistenceError(
                f"prepared record claims objective {record.objective_id!r} but is being appended "
                f"to objective {objective_id!r} — refusing to append"
            )
        state = self._require_objective(objective_id)
        stored_lineage = _header_str(state.header, "delivery_lineage", objective_id=objective_id)
        if stored_lineage != record.delivery_lineage:
            raise TrainPersistenceError(
                f"objective {objective_id} stores delivery_lineage {stored_lineage!r} but the "
                f"prepared record carries {record.delivery_lineage!r} — refusing to append"
            )
        fold = self.read_journal(objective_id)
        canonical = canonical_payload(record)
        existing = fold.operations.get(record.operation_id)
        if existing is not None:
            if existing.prepared.canonical_payload == canonical:
                return AppendResult(
                    operation_id=record.operation_id, role=EventRole.PREPARED, existed=True
                )
            raise JournalCorruptionError(
                f"operation {record.operation_id} already has a prepared event with a differing "
                "payload (conflicting duplicate)"
            )
        if fold.unresolved:
            blocking = fold.unresolved[0]
            raise UnresolvedOperationError(
                f"lineage {fold.delivery_lineage} already has an unresolved operation "
                f"{blocking.operation_id} ({blocking.kind.value}) — recover or abandon it before "
                "preparing another"
            )
        self._append(
            member_objective_id=objective_id,
            record=record,
            canonical=canonical,
        )
        return AppendResult(
            operation_id=record.operation_id, role=EventRole.PREPARED, existed=False
        )

    def append_outcome(self, objective_id: str, record: OutcomeRecord) -> AppendResult:
        """The gated, read-back outcome append — routed to the carrier **holding the operation's
        prepared event** (not necessarily the active objective: the transfer protocol prepares
        on the predecessor and keeps that operation's later events there).

        An outcome whose operation has no prepared event anywhere in the fold is corruption
        (orphan). ``accepted`` on a non-``land`` operation refuses before any write. Fold-level
        conflict rules apply: an already-recorded byte-identical outcome is ``existed=True``; a
        differing one is corruption.
        """
        fold = self.read_journal(objective_id)
        operation = fold.operations.get(record.operation_id)
        if operation is None:
            raise JournalCorruptionError(
                f"outcome for operation {record.operation_id} has no prepared event anywhere in "
                "the fold — likely out-of-band deletion of the prepared record (authorized "
                "deletion is corruption)"
            )
        if record.role is EventRole.ACCEPTED and operation.kind is not OperationKind.LAND:
            raise TrainPersistenceError(
                f"operation {record.operation_id} ({operation.kind.value}) cannot record an "
                "accepted event — accepted is gated to land (the async-merge handle)"
            )
        canonical = canonical_payload(record)
        if record.role is EventRole.ACCEPTED:
            if operation.accepted is not None:
                if operation.accepted.canonical_payload == canonical:
                    return AppendResult(
                        operation_id=record.operation_id, role=record.role, existed=True
                    )
                raise JournalCorruptionError(
                    f"operation {record.operation_id} already has an accepted event with a "
                    "differing payload (conflicting duplicate)"
                )
        elif operation.outcome is not None:
            if (
                operation.outcome.role is record.role
                and operation.outcome.canonical_payload == canonical
            ):
                return AppendResult(
                    operation_id=record.operation_id, role=record.role, existed=True
                )
            raise JournalCorruptionError(
                f"operation {record.operation_id} is already terminal "
                f"({operation.outcome.role.value}) — a differing {record.role.value} outcome is "
                "corruption"
            )
        self._append(
            member_objective_id=operation.prepared.carrier_objective_id,
            record=record,
            canonical=canonical,
        )
        return AppendResult(operation_id=record.operation_id, role=record.role, existed=False)

    def _append(
        self,
        *,
        member_objective_id: str,
        record: PreparedRecord | OutcomeRecord,
        canonical: str,
    ) -> None:
        """Render, size-validate, POST with the rescan-one-retry ambiguity policy, and read
        back. At most TWO POST attempts ever; a still-unproven event raises
        :class:`JournalAppendAmbiguous`."""
        body = render_event(record)
        ensure_event_size(body)
        carrier = self._carrier_id(member_objective_id)
        role = EventRole.PREPARED if isinstance(record, PreparedRecord) else record.role
        for _attempt in range(2):
            # A raised POST is AMBIGUOUS (the write may have landed) — read convergence
            # decides, never a blind retry.
            with contextlib.suppress(IssueBackendError):
                self._issues.add_issue_comment(issue_id=carrier, body=body)
            try:
                landed = self._event_landed(
                    carrier=carrier,
                    operation_id=record.operation_id,
                    role=role,
                    canonical=canonical,
                )
            except IssueBackendError as exc:
                # A failed rescan proves NOTHING (neither present nor absent): the event is
                # ambiguous and another POST is forbidden — only a rescan that proved absence
                # earns the retry.
                raise JournalAppendAmbiguous(
                    f"append of {record.operation_id}:{role.value} to carrier {carrier} is "
                    f"unverifiable — the read-back rescan failed ({exc}); rescan the carrier "
                    "before any remote effect"
                ) from exc
            if landed:
                return
            # Proven absent on this rescan — the one bounded retry loops.
        raise JournalAppendAmbiguous(
            f"append of {record.operation_id}:{role.value} to carrier {carrier} could not be "
            "verified after one retry — rescan the carrier before any remote effect"
        )

    def _event_landed(
        self, *, carrier: str, operation_id: str, role: EventRole, canonical: str
    ) -> bool:
        """Rescan the carrier for the deterministic event key — the COMPLETE scan, never a
        first-match return: ANY differing payload under the key (e.g. a concurrent writer's
        conflicting duplicate) → corruption before the append boundary is crossed; a
        byte-identical match with no conflicts → landed; absent → False (proven absent)."""
        found = False
        for comment in self._issues.read_comments(issue_id=carrier):
            event = parse_journal_comment(
                comment.body,
                comment_id=comment.id,
                created_at=comment.created_at,
                edited_at=comment.edited_at,
                carrier=carrier,
            )
            if event is None or (event.operation_id, event.role) != (operation_id, role):
                continue
            if event.canonical_payload != canonical:
                raise JournalCorruptionError(
                    f"read-back of {operation_id}:{role.value} on carrier {carrier} found the "
                    "event key with a DIFFERENT payload (conflicting duplicate)"
                )
            found = True
        return found

    # ------------------------------------------------------------------ typed writers
    # Thin compositions over the merge-write header seams — the adapter is the one coherent
    # persistence view, and the write-together rules are enforced structurally (there is no
    # single-field surface).

    def write_checkpoints(
        self, plan_id: str, *, parent_checkpoint_sha: str, published_head_sha: str
    ) -> None:
        """Write the verified checkpoint pair in ONE ``update_plan_header`` write (§8.42: the
        pair is updated together only after publication verification)."""
        self._issues.update_plan_header(
            issue_id=plan_id,
            fields={
                "parent_checkpoint_sha": parent_checkpoint_sha,
                "published_head_sha": published_head_sha,
            },
        )

    def transfer_plan_ownership(
        self, plan_id: str, *, objective_id: str, objective_node_id: str
    ) -> None:
        """Transfer a plan's objective/node ownership in one write (the replan-transfer
        write)."""
        self._issues.update_plan_header(
            issue_id=plan_id,
            fields={"objective_id": objective_id, "objective_node_id": objective_node_id},
        )

    def stamp_layer_identity(
        self, plan_id: str, *, delivery_lineage: str, predecessor_plan_id: str | None
    ) -> None:
        """Stamp a layer's train identity in one write. An explicit ``None`` predecessor is
        contract-legal for the bottom layer (absent ≡ null at the read boundary)."""
        self._issues.update_plan_header(
            issue_id=plan_id,
            fields={
                "delivery_lineage": delivery_lineage,
                "predecessor_plan_id": predecessor_plan_id,
            },
        )

    def clear_delivery_metadata(self, plan_id: str) -> None:
        """Clear a plan's four stacked delivery fields in ONE ``update_plan_header`` write —
        the stacked→incremental replan-transfer write (contracts.md §8.53). Present-key-with-
        ``None`` is an explicit null on both backends, and absent ≡ null at the read boundary
        (§8.42), so writing ``None`` IS clearing. ``objective_node_id`` deliberately stays with
        :meth:`transfer_plan_ownership` (ownership is transferred, never cleared)."""
        self._issues.update_plan_header(
            issue_id=plan_id,
            fields={
                "delivery_lineage": None,
                "predecessor_plan_id": None,
                "parent_checkpoint_sha": None,
                "published_head_sha": None,
            },
        )

    def write_delivery_lineage(self, objective_id: str, delivery_lineage: str) -> None:
        """Stamp the objective's ``delivery_lineage`` (the storage primitive only — lineage
        minting is the authoring node's concern)."""
        self._store.update_objective_header(
            objective_id=objective_id, fields={"delivery_lineage": delivery_lineage}
        )
