"""Hermetic fake-driven tests for the delivery sync operation (contracts.md §8.49).

Every effectful aggregate authority used by ``Delivery.sync`` is backed by an in-memory
world: a scriptable mini remote (branch heads, PR facts, one native stack), a recording
persistence fake, in-memory temp refs / worktrees / continuation manifests, and a timeline
that pins the load-bearing ordering (candidates → approval → re-observation → prepared →
one atomic push → verify → checkpoints bottom→top → completed). OFFLINE — no git / gh / network.
"""

import contextlib
from collections.abc import Callable, Iterator
from dataclasses import replace as dataclasses_replace
from pathlib import Path
from typing import cast

import pytest

from perk.delivery import continuation, oplock, sync
from perk.delivery.facade import (
    Delivery,
    DeliveryError,
    DeliveryGit,
    DeliveryGitHub,
    DeliveryPersistence,
    StatusRequest,
    StatusResult,
    SyncRequest,
    SyncResult,
)
from perk.delivery.journal import (
    EventRole,
    JournalEvent,
    JournalFold,
    JournalRecordTooLarge,
    OperationKind,
    OperationState,
    OutcomeRecord,
    PreparedRecord,
    canonical_payload,
    mint_operation_id,
)
from perk.delivery.persistence import AppendResult, UnresolvedOperationError
from perk.delivery.train import (
    STRUCTURAL_BLOCKER_CODES,
    BuildReadiness,
    DeliveryTrain,
    FindingKind,
    LayerFinalization,
    LayerGit,
    LayerIntent,
    LayerMembership,
    LayerPr,
    LayerPublication,
    LayerWriter,
    NoDeliveryTrain,
    PrFactsView,
    TrainFinding,
    TrainLayer,
    TrainReconstructionError,
)
from perk.delivery.writers import WriterObservationError
from perk.github import GitHubError
from perk.github.stacks import PrDeliveryFacts, StackRestEntry, StackRestFacts
from perk.substrate import config as config_mod
from perk.substrate import git

ROOT = Path("/repo")
WT_ROOT = Path("/wt")
OBJECTIVE = "500"
LINEAGE = "01LINEAGE"
MAIN = "m" * 40  # the anchored objective base
NEWBASE = "n" * 40  # an advanced objective base head
P1 = "1" * 40  # layer-1 published head
P2 = "2" * 40  # layer-2 published head
P3 = "3" * 40  # layer-3 published head
C2 = "b" * 40  # layer-2 amended local head


def _reb(source: str, onto: str) -> str:
    """The fake rebase's deterministic transplant SHA."""
    return f"reb:{source[:4]}:onto:{onto[:4]}"


def _layer(
    node_id: str,
    plan_id: str | None,
    *,
    pr_number: int | None = None,
    parent_checkpoint_sha: str | None = None,
    published_head_sha: str | None = None,
    branch: str | None = "default",
    writer: LayerWriter = LayerWriter.FREE,
) -> TrainLayer:
    return TrainLayer(
        node_id=node_id,
        plan_id=plan_id,
        branch=(f"plan-{plan_id}" if branch == "default" else branch),
        pr_number=pr_number,
        intent=LayerIntent.PLANNED,
        publication=LayerPublication.UNPUBLISHED,  # deliberately untrusted by sync
        git=LayerGit.UNKNOWN,
        pr=LayerPr.ABSENT,
        membership=LayerMembership.NOT_APPLICABLE,
        writer=writer,
        finalization=LayerFinalization.NOT_MERGED,
        parent_checkpoint_sha=parent_checkpoint_sha,
        published_head_sha=published_head_sha,
        observed_remote_head_sha=None,
        observed_pr_base=None,
        expected_pr_base=None,
    )


class _WriterProbe:
    def __init__(self) -> None:
        self.active: frozenset[str] = frozenset()
        self.boom: Exception | None = None
        self.calls: list[tuple[str, ...]] = []

    def active_plan_ids(self, plan_ids) -> frozenset[str]:
        self.calls.append(tuple(plan_ids))
        if self.boom is not None:
            raise self.boom
        return self.active & frozenset(plan_ids)


class _FakePersistence:
    """In-memory journal: seeded unresolved records, recorded appends, and a live fold."""

    def __init__(self, world: "_World", unresolved: list[PreparedRecord]) -> None:
        self._world = world
        self.unresolved_records: dict[str, PreparedRecord] = {r.operation_id: r for r in unresolved}
        self.prepared: list[PreparedRecord] = []
        self.outcomes: list[OutcomeRecord] = []
        self.checkpoints: list[tuple[str, str, str]] = []
        # Fail-once process-death hooks for the completion-side boundary cells (S4/S4b):
        # `checkpoints_boom_at` raises BEFORE the n-th write_checkpoints call lands (1-based
        # — n-1 checkpoints are already durable); `completed_boom` raises BEFORE the
        # completed append lands. Faithful for the DURABLE axes (journal, remote refs,
        # checkpoint headers): sync's finally-cleanup touches only machine-local temp
        # refs/worktrees, whose post-death residue is S1's separately proven cell.
        self.prepared_boom: Exception | None = None
        self.checkpoints_boom_at: tuple[int, Exception] | None = None
        self.completed_boom: Exception | None = None
        self._checkpoint_calls = 0

    def read_journal(self, objective_id: str) -> JournalFold:
        ops = {}
        for op_id, record in self.unresolved_records.items():
            event = JournalEvent(
                record=record,
                role=EventRole.PREPARED,
                operation_id=op_id,
                canonical_payload=canonical_payload(record),
                comment_id="c1",
                created_at=record.created,
            )
            ops[op_id] = OperationState(
                operation_id=op_id,
                kind=record.operation_kind,
                prepared=event,
                accepted=None,
                outcome=None,
            )
        return JournalFold(
            events=(),
            operations=ops,
            unresolved=tuple(ops.values()),
            delivery_lineage=LINEAGE,
        )

    def append_prepared(self, objective_id: str, record: PreparedRecord) -> AppendResult:
        if self.prepared_boom is not None:
            raise self.prepared_boom
        if self.unresolved_records:
            raise UnresolvedOperationError("an operation is already unresolved")
        self._world.timeline.append(("prepared", record.operation_id))
        self.prepared.append(record)
        self.unresolved_records[record.operation_id] = record
        return AppendResult(record.operation_id, EventRole.PREPARED, existed=False)

    def append_outcome(self, objective_id: str, record: OutcomeRecord) -> AppendResult:
        if self.completed_boom is not None and record.role is EventRole.COMPLETED:
            boom, self.completed_boom = self.completed_boom, None
            raise boom
        self._world.timeline.append(("outcome", record.role.value, record.operation_id))
        self.outcomes.append(record)
        self.unresolved_records.pop(record.operation_id, None)
        return AppendResult(record.operation_id, record.role, existed=False)

    def write_checkpoints(
        self, plan_id: str, *, parent_checkpoint_sha: str, published_head_sha: str
    ) -> None:
        self._checkpoint_calls += 1
        if (
            self.checkpoints_boom_at is not None
            and self._checkpoint_calls == (self.checkpoints_boom_at[0])
        ):
            boom = self.checkpoints_boom_at[1]
            self.checkpoints_boom_at = None
            raise boom
        self._world.timeline.append(("checkpoints", plan_id))
        self.checkpoints.append((plan_id, parent_checkpoint_sha, published_head_sha))
        for index, layer in enumerate(self._world.layers):
            if layer.plan_id == plan_id:
                self._world.layers[index] = dataclasses_replace(
                    layer,
                    parent_checkpoint_sha=parent_checkpoint_sha,
                    published_head_sha=published_head_sha,
                )
                break


class _WorldGit:
    """Aggregate Git authority backed by the existing scriptable world."""

    def __init__(self, world: "_World") -> None:
        self._world = world

    @property
    def repo_root(self) -> Path:
        return ROOT

    def fetch_refs(self, refs: tuple[str, ...]) -> None:
        self._world._fetch(ROOT, list(refs))

    def remote_branch_sha(self, branch: str) -> str | None:
        return self._world._remote_head(ROOT, branch)

    def resolve_commit(self, ref: str, *, cwd: Path | None = None) -> str | None:
        return self._world._local_head(cwd or ROOT, ref)

    def is_ancestor(self, ancestor: str, descendant: str) -> bool | None:
        return self._world._is_ancestor(ROOT, ancestor, descendant)

    def push_urls(self) -> DeliveryGit.PushUrlsResult:
        return DeliveryGit.PushUrlsResult(urls=tuple(self._world._push_urls(ROOT)))

    def probe_atomic_push(
        self, *, push_url: str, base_branch: str, base_sha: str
    ) -> DeliveryGit.AtomicPushResult | DeliveryGit.ProbeError:
        try:
            self._world._atomic_probe(ROOT, push_url, base_branch, base_sha)
        except git.GitError as exc:
            return DeliveryGit.ProbeError(message=str(exc))
        return DeliveryGit.AtomicPushResult()

    def push_atomic(self, updates: tuple[git.RefUpdate, ...]) -> None:
        self._world._push_atomic(ROOT, list(updates))

    def update_ref(self, ref: str, sha: str) -> None:
        self._world._update_ref(ROOT, ref, sha)

    def delete_ref(self, ref: str) -> None:
        self._world._delete_ref(ROOT, ref)

    def list_refs(self, prefix: str) -> tuple[str, ...]:
        return tuple(self._world._list_refs(ROOT, prefix))

    def add_detached_worktree(self, path: Path, commit: str) -> None:
        self._world._worktree_add(ROOT, path, commit)

    def remove_worktree(self, path: Path) -> None:
        self._world._worktree_remove(ROOT, path)

    def prune_worktrees(self) -> None:
        self._world._worktree_prune(ROOT)

    def checkout_detached(self, worktree: Path, sha: str) -> None:
        self._world._checkout_detached(worktree, sha)

    def rebase_onto(self, worktree: Path, *, onto: str, upstream: str) -> git.RebaseOutcome:
        return self._world._rebase_onto(worktree, onto=onto, upstream=upstream)

    def rebase_in_progress(self, worktree: Path) -> bool:
        return self._world._rebase_in_progress(worktree)

    def worktree_dirty(self, worktree: Path) -> bool:
        return self._world._worktree_dirty(worktree)


class _WorldGitHub:
    """Aggregate GitHub authority backed by the existing scriptable world."""

    def __init__(self, world: "_World") -> None:
        self._world = world

    def pr_facts(self, number: int) -> PrFactsView | None:
        facts = self._world._pr_facts(number=number, repo_root=ROOT)
        if facts is None:
            return None
        return PrFactsView(
            number=facts.number,
            state=facts.state.upper(),
            is_draft=facts.is_draft,
            base_ref=facts.base_ref,
            head_ref=facts.head_ref,
            head_sha=facts.head_sha,
        )

    def strict_stack(self, number: int) -> StackRestFacts | None:
        return self._world._stack_read(number=number, repo_root=ROOT)

    def active_writer_plan_ids(
        self,
        plan_ids: tuple[str, ...],
        *,
        trigger_plan_id: str | None,
        trigger_run_id: str | None,
    ) -> frozenset[str]:
        del trigger_plan_id, trigger_run_id
        return self._world.writer_probe.active_plan_ids(plan_ids)


class _WorldDelivery(Delivery):
    """Use the world train projection while exercising the real sync façade dispatch."""

    def __init__(self, world: "_World") -> None:
        self._world = world
        super().__init__(
            persistence=cast("DeliveryPersistence", world.persistence),
            git=cast("DeliveryGit", _WorldGit(world)),
            github=cast("DeliveryGitHub", _WorldGitHub(world)),
        )

    def status(self, request: StatusRequest) -> StatusResult:
        self._world.status_calls.append(request)
        observed = self._world._reconstruct(ROOT, request.objective_id)
        if isinstance(observed, NoDeliveryTrain):
            return StatusResult(
                observed.objective_id,
                observed.objective_url,
                observed.redirected_from,
                None,
                observed.reason,
            )
        return StatusResult(
            observed.objective_id,
            observed.objective_url,
            observed.redirected_from,
            observed,
            None,
        )


class _World:
    """The injectable mini remote + recorders for one ``Delivery.sync`` invocation."""

    def __init__(
        self,
        layers: list[TrainLayer],
        *,
        unresolved: list[PreparedRecord] | None = None,
    ) -> None:
        self.layers = layers
        self.lineage: str | None = LINEAGE
        self.base_head: str | None = MAIN
        self.findings: tuple[TrainFinding, ...] = ()
        self.no_train = False
        self.timeline: list[tuple] = []
        self.status_calls: list[StatusRequest] = []
        self.persistence = _FakePersistence(self, unresolved or [])
        self.writer_probe = _WriterProbe()
        # Git state.
        self.remote: dict[str, str | None] = {"main": MAIN}
        self.local: dict[str, str | None] = {}
        self.ancestry: set[tuple[str, str]] = set()
        self.urls = ["https://gh/octo/repo.git"]
        self.atomic_probe_boom: Exception | None = None
        self.push_reject = False
        self.push_reject_leaves: dict[str, str] = {}
        self.on_push: Callable[[], None] | None = None
        self.fetch_boom: Exception | None = None
        self.remote_head_boom: Exception | None = None
        # GitHub state: PR number → (branch, base, state); head_sha reads live remote.
        self.pr_entries: dict[int, tuple[str, str, str]] = {}
        self.pr_facts_script: list[PrDeliveryFacts | Exception | None] = []
        self.stack_members: list[int] | None = None
        self.stack_read_boom: Exception | None = None
        # Residue state.
        self.refs: dict[str, str] = {}
        self.worktrees_added: list[tuple[Path, str]] = []
        self.worktrees_removed: list[Path] = []
        self.checkouts: list[str] = []
        self.rebase_conflicts: set[tuple[str, str]] = set()  # (source, onto) → conflict
        self.manifests: dict[str, continuation.ContinuationManifest] = {}
        self.manifest_write_override: (
            Callable[[Path, continuation.ContinuationManifest], Path] | None
        ) = None
        self.pending_unparseable = False
        self.sleeps: list[float] = []
        # The machine-local operation lock (injected; production is oplock's flock).
        self.lock_busy = False
        self.lock_events: list[str] = []
        # Continue/abort world state.
        self.pruned: list[Path] = []
        self.manifest_clear_boom: OSError | None = None
        self.delete_ref_boom: set[str] = set()
        self.worktree_remove_boom: Exception | None = None
        self.worktree_prune_boom: Exception | None = None
        self.cleared_manifests: list[str] = []
        self.existing_paths: set[str] = set()
        self.rebase_active = False
        self.worktree_is_dirty = False
        self.worktree_heads: dict[str, str] = {}

    # ---------------------------------------------------------------- the operation lock

    @contextlib.contextmanager
    def _lock(self, root: Path) -> Iterator[None]:
        if self.lock_busy:
            raise oplock.OperationLockBusy("another stack operation holds the lock")
        self.lock_events.append("acquired")
        try:
            yield
        finally:
            self.lock_events.append("released")

    # ---------------------------------------------------------------- train

    def _reconstruct(self, root: Path, objective_id: str):
        if self.no_train:
            return NoDeliveryTrain(
                objective_id=OBJECTIVE,
                objective_url="u",
                redirected_from=None,
                reason="objective is incremental",
            )
        return DeliveryTrain(
            objective_id=OBJECTIVE,
            objective_url="u",
            delivery_lineage=self.lineage,
            base="main",
            redirected_from=None,
            layers=tuple(self.layers),
            # Deliberately 0 even for fully-claimed worlds: sync's universe is the claimed
            # prefix, never the classifier's verified prefix.
            published_prefix_len=0,
            unresolved_operation=None,
            findings=self.findings,
            build_readiness=BuildReadiness(next_node_id=None, ready=False, reason="veto"),
            observed_base_head_sha=self.base_head,
        )

    # ---------------------------------------------------------------- git seams

    def _fetch(self, root: Path, refspecs: list[str]) -> None:
        if self.fetch_boom is not None:
            raise self.fetch_boom
        self.timeline.append(("fetch", tuple(refspecs)))

    def _remote_head(self, root: Path, branch: str) -> str | None:
        if self.remote_head_boom is not None:
            raise self.remote_head_boom
        return self.remote.get(branch)

    def _local_head(self, root: Path, ref: str) -> str | None:
        if root != ROOT:
            # A worktree-scoped read (the retained worktree's detached HEAD).
            return self.worktree_heads.get(str(root))
        if ref in self.refs:
            return self.refs[ref]  # temp-ref resolution rides the ref store
        return self.local.get(ref)

    def _is_ancestor(self, root: Path, ancestor: str, head: str) -> bool:
        # A fake rebase product (`reb:<src>:onto:<parent>`) contains its onto parent — the
        # continue path's resolved-candidate ancestry check relies on exactly that fact.
        if head.startswith("reb:") and head.endswith(f":onto:{ancestor[:4]}"):
            return True
        return ancestor == head or (ancestor, head) in self.ancestry

    def _push_urls(self, root: Path) -> list[str]:
        return list(self.urls)

    def _atomic_probe(self, root: Path, url: str, branch: str, sha: str) -> None:
        self.timeline.append(("atomic_probe", url, branch, sha))
        if self.atomic_probe_boom is not None:
            raise self.atomic_probe_boom

    def _push_atomic(self, root: Path, updates: list[git.RefUpdate]) -> None:
        self.timeline.append(
            ("push_atomic", tuple((u.branch, u.expected_remote_sha, u.new_sha) for u in updates))
        )
        if self.push_reject:
            self.remote.update(self.push_reject_leaves)
            if self.on_push is not None:
                self.on_push()
            raise git.PushRejectedError("a lease was stale")
        for update in updates:
            self.remote[update.branch] = update.new_sha
        if self.on_push is not None:
            self.on_push()

    def _update_ref(self, root: Path, ref: str, sha: str) -> None:
        self.timeline.append(("update_ref", ref, sha))
        self.refs[ref] = sha

    def _delete_ref(self, root: Path, ref: str) -> None:
        if "*" in self.delete_ref_boom or ref in self.delete_ref_boom:
            raise git.GitError("cannot delete")
        self.refs.pop(ref, None)

    def _list_refs(self, root: Path, prefix: str) -> list[str]:
        return sorted(ref for ref in self.refs if ref.startswith(prefix))

    def _worktree_add(self, root: Path, path: Path, commit: str) -> None:
        self.timeline.append(("worktree_add", str(path), commit))
        self.worktrees_added.append((path, commit))

    def _worktree_remove(self, root: Path, path: Path) -> None:
        if self.worktree_remove_boom is not None:
            raise self.worktree_remove_boom
        self.timeline.append(("worktree_remove", str(path)))
        self.worktrees_removed.append(path)

    def _worktree_prune(self, root: Path) -> None:
        if self.worktree_prune_boom is not None:
            raise self.worktree_prune_boom
        self.timeline.append(("worktree_prune",))
        self.pruned.append(root)

    def _path_exists(self, path: Path) -> bool:
        return str(path) in self.existing_paths

    def _rebase_in_progress(self, path: Path) -> bool:
        return self.rebase_active

    def _worktree_dirty(self, path: Path) -> bool:
        return self.worktree_is_dirty

    def _checkout_detached(self, worktree: Path, sha: str) -> None:
        self.checkouts.append(sha)

    def _rebase_onto(self, worktree: Path, *, onto: str, upstream: str) -> git.RebaseOutcome:
        source = self.checkouts[-1]
        self.timeline.append(("rebase", source, onto, upstream))
        if (source, onto) in self.rebase_conflicts:
            return git.RebaseConflict(detail="CONFLICT (content): parent.txt")
        return git.RebaseCompleted(head_sha=_reb(source, onto))

    # ---------------------------------------------------------------- github seams

    def _pr_facts(self, *, number: int, repo_root: Path) -> PrDeliveryFacts | None:
        if self.pr_facts_script:
            value = self.pr_facts_script.pop(0)
            if isinstance(value, Exception):
                raise value
            return value
        entry = self.pr_entries.get(number)
        if entry is None:
            return None
        branch, base, state = entry
        return PrDeliveryFacts(
            number=number,
            state=state,
            is_draft=True,
            base_ref=base,
            head_ref=branch,
            head_sha=self.remote.get(branch) or "",
        )

    def _stack_read(self, *, number: int, repo_root: Path) -> StackRestFacts | None:
        self.timeline.append(("stack_read", number))
        if self.stack_read_boom is not None:
            raise self.stack_read_boom
        if self.stack_members is None or number not in self.stack_members:
            return None
        entries = tuple(
            StackRestEntry(
                pr_number=n,
                state="open",
                draft=True,
                merged=False,
                head_ref=f"pr-{n}",
                head_sha="",
            )
            for n in self.stack_members
        )
        return StackRestFacts(number=9, size=len(entries), entries=entries)

    # ---------------------------------------------------------------- continuation seams

    def _pending_read(self, root: Path, lineage: str) -> continuation.PendingContinuation | None:
        path = Path(f"/main/.perk/workflow/sync-continuations/{lineage}.json")
        if self.pending_unparseable:
            return continuation.PendingContinuation(path=path, manifest=None)
        manifest = self.manifests.get(lineage)
        if manifest is None:
            return None
        return continuation.PendingContinuation(path=path, manifest=manifest)

    def _manifest_write(self, root: Path, manifest: continuation.ContinuationManifest) -> Path:
        if self.manifest_write_override is not None:
            return self.manifest_write_override(root, manifest)
        self.timeline.append(("manifest_write", manifest.delivery_lineage))
        self.manifests[manifest.delivery_lineage] = manifest
        return Path(f"/main/.perk/workflow/sync-continuations/{manifest.delivery_lineage}.json")

    def _manifest_clear(self, root: Path, lineage: str) -> None:
        if self.manifest_clear_boom is not None:
            raise self.manifest_clear_boom
        self.timeline.append(("manifest_clear", lineage))
        self.cleared_manifests.append(lineage)
        self.manifests.pop(lineage, None)
        self.pending_unparseable = False

    # ---------------------------------------------------------------- driving

    def _runtime(self) -> sync._SyncRuntime:
        return sync._SyncRuntime(
            worktree_root=lambda repo_root: WT_ROOT,
            operation_lock=self._lock,
            pending_continuation=self._pending_read,
            write_manifest=self._manifest_write,
            clear_manifest=self._manifest_clear,
            validate_targets=continuation.validated_targets,
            path_exists=self._path_exists,
            mint_operation_id=mint_operation_id,
            now=lambda: "2026-01-01T00:00:00Z",
            sleep=self.sleeps.append,
        )

    def _invoke(
        self,
        request: SyncRequest,
        consent: Callable[..., bool] | None,
    ) -> SyncResult:
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(sync, "_DEFAULT_SYNC_RUNTIME", self._runtime())
            return _WorldDelivery(self).sync(request, consent=consent)

    def sync(
        self,
        *,
        include_base: bool = False,
        dry_run: bool = False,
        adopt_node: str | None = None,
        trigger_plan_id: str | None = None,
        trigger_run_id: str | None = None,
        approve: Callable[[SyncResult.Cascade], bool] | None = None,
        run_id: str = "01RUN",
        objective_id: str = OBJECTIVE,
    ) -> SyncResult:
        # `objective_id` may be a request ALIAS: the fake reconstruction always resolves to
        # the OBJECTIVE projection id (modelling redirect resolution), so a divergent
        # request id proves message interpolation reads the train, never the request.
        return self._invoke(
            SyncRequest(
                mode="cascade",
                objective_id=objective_id,
                run_id=run_id,
                include_base=include_base,
                dry_run=dry_run,
                adopt_node=adopt_node,
                trigger_plan_id=trigger_plan_id,
                trigger_run_id=trigger_run_id,
            ),
            approve,
        )

    def continue_sync(
        self,
        *,
        approve: Callable[[SyncResult.Cascade], bool] | None = None,
        objective_id: str = OBJECTIVE,
    ) -> SyncResult:
        return self._invoke(
            SyncRequest(mode="continue", objective_id=objective_id),
            approve,
        )

    def abort_sync(
        self,
        *,
        approve: Callable[[SyncResult.AbortPreview], bool] | None = None,
    ) -> SyncResult:
        return self._invoke(
            SyncRequest(mode="abort", objective_id=OBJECTIVE),
            approve,
        )

    def events(self, kind: str) -> list[tuple]:
        return [t for t in self.timeline if t[0] == kind]

    def assert_guard_cleaned(self) -> None:
        """The centralized cleanup guard fired: no temp refs survive and every created
        isolated worktree was removed."""
        assert self.refs == {}
        if self.worktrees_added:
            assert self.worktrees_removed == [path for path, _ in self.worktrees_added]

    def assert_nothing_journaled(self) -> None:
        assert self.persistence.prepared == []
        assert self.persistence.outcomes == []
        assert self.persistence.checkpoints == []


def _three_layer_world() -> _World:
    """A fully claimed three-layer train, remote exactly at its checkpoints."""
    world = _World(
        [
            _layer("1.1", "101", pr_number=201, parent_checkpoint_sha=MAIN, published_head_sha=P1),
            _layer("1.2", "102", pr_number=202, parent_checkpoint_sha=P1, published_head_sha=P2),
            _layer("1.3", "103", pr_number=203, parent_checkpoint_sha=P2, published_head_sha=P3),
        ]
    )
    world.remote.update({"plan-101": P1, "plan-102": P2, "plan-103": P3})
    world.pr_entries = {
        201: ("plan-101", "main", "OPEN"),
        202: ("plan-102", "plan-101", "OPEN"),
        203: ("plan-103", "plan-102", "OPEN"),
    }
    world.stack_members = [201, 202, 203]
    # Healthy stored pairs: every published head contains its parent edge (the source
    # consistency the pre-candidate ancestry check requires).
    world.ancestry.update({(MAIN, P1), (P1, P2), (P2, P3)})
    return world


def _amended_middle_world() -> _World:
    """The default cascade scenario: layer 1.2's branch was amended locally (P2 → C2)."""
    world = _three_layer_world()
    world.local["plan-102"] = C2
    world.ancestry.add((P1, C2))  # C2 still contains its parent checkpoint
    return world


def _sync_error(world: _World, **kwargs) -> sync.SyncError:
    with pytest.raises(sync.SyncError) as excinfo:
        world.sync(**kwargs)
    return excinfo.value


def test_default_worktree_configuration_failure_is_a_public_invalid_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _amended_middle_world()
    runtime = dataclasses_replace(world._runtime(), worktree_root=sync._configured_worktree_root)

    def invalid_config(repo_root: Path) -> None:
        raise config_mod.ConfigError("bad worktree root")

    monkeypatch.setattr(config_mod, "load_config", invalid_config)
    monkeypatch.setattr(sync, "_DEFAULT_SYNC_RUNTIME", runtime)

    with pytest.raises(DeliveryError) as excinfo:
        _WorldDelivery(world).sync(
            SyncRequest(mode="cascade", objective_id=OBJECTIVE, run_id="01RUN"),
            consent=None,
        )

    assert excinfo.value.error_type == "invalid_config"
    assert "could not load worktree configuration: bad worktree root" in str(excinfo.value)
    world.assert_nothing_journaled()
    assert world.events("push_atomic") == []
    assert world.events("update_ref") == []
    assert world.worktrees_added == []
    assert world.manifests == {}


# ----------------------------------------------------------------- the fresh cascade


R3 = _reb(P3, C2)  # layer 1.3's transplant onto the amended C2


def test_local_change_cascades_the_published_suffix():
    world = _amended_middle_world()
    result = world.sync()
    assert result.no_op is False and result.declined is False and result.resumed is False
    assert result.base_cascaded is False
    assert result.operation_id is not None and result.abandoned_operation_id is None
    assert result.objective_id == OBJECTIVE and result.objective_url == "u"
    assert [
        (s.node_id, s.plan_id, s.branch, s.pr_number, s.before_sha, s.after_sha)
        for s in result.affected
    ] == [
        ("1.2", "102", "plan-102", 202, P2, C2),  # the changed layer: fast path, no rebase
        ("1.3", "103", "plan-103", 203, P3, R3),  # its successor: transplanted
    ]
    # The changed layer's candidate IS its local head (new parent edge unchanged → no
    # rebase); only the successor transplants.
    assert world.events("rebase") == [("rebase", P3, C2, P2)]
    # One atomic push, every affected ref under its exact lease.
    assert world.events("push_atomic") == [
        ("push_atomic", (("plan-102", P2, C2), ("plan-103", P3, R3)))
    ]
    assert world.remote["plan-102"] == C2 and world.remote["plan-103"] == R3
    # Checkpoints bottom→top with the NEW parent edges, then completed.
    assert world.persistence.checkpoints == [("102", P1, C2), ("103", C2, R3)]
    outcome = world.persistence.outcomes[-1]
    assert outcome.role is EventRole.COMPLETED
    assert outcome.observed == {
        "branches": [{"ref": "plan-102", "sha": C2}, {"ref": "plan-103", "sha": R3}],
        "prs": [{"number": 202, "head_sha": C2}, {"number": 203, "head_sha": R3}],
    }
    world.assert_guard_cleaned()


def test_ordering_prepared_push_verify_checkpoints_completed():
    world = _amended_middle_world()
    world.sync()
    kinds = [t[0] for t in world.timeline]
    assert kinds.index("prepared") < kinds.index("push_atomic")
    assert kinds.index("push_atomic") < kinds.index("checkpoints")
    assert kinds.index("checkpoints") < kinds.index("outcome")
    # The bottom-up checkpoint order.
    assert [t[1] for t in world.events("checkpoints")] == ["102", "103"]
    # Candidates are calculated (and approval passes) BEFORE the prepared record.
    assert kinds.index("update_ref") < kinds.index("prepared")


def test_prepared_record_payload_pins():
    world = _amended_middle_world()
    world.sync()
    record = world.persistence.prepared[0]
    assert record.operation_kind is OperationKind.SYNC
    assert record.delivery_lineage == LINEAGE and record.run_id == "01RUN"
    assert record.affected_plans == ("102", "103")
    assert record.before == {
        "base": None,
        "branches": [{"ref": "plan-102", "sha": P2}, {"ref": "plan-103", "sha": P3}],
        "prs": [
            {"number": 202, "head_sha": P2, "base": "plan-101"},
            {"number": 203, "head_sha": P3, "base": "plan-102"},
        ],
        "stack": {"members": [201, 202, 203]},
    }
    assert record.after == {
        "branches": [{"ref": "plan-102", "sha": C2}, {"ref": "plan-103", "sha": R3}],
        "prs": [
            {"number": 202, "head_sha": C2, "base": "plan-101"},
            {"number": 203, "head_sha": R3, "base": "plan-102"},
        ],
        "base_parent": None,
    }


def test_base_cascade_parent_edge_arithmetic():
    # --base with an advanced base: the bottom layer re-anchors onto the observed base head,
    # every successor transplants onto its predecessor's fresh candidate.
    world = _three_layer_world()
    world.base_head = NEWBASE
    world.remote["main"] = NEWBASE
    r1 = _reb(P1, NEWBASE)
    r2 = _reb(P2, r1)
    r3 = _reb(P3, r2)
    result = world.sync(include_base=True)
    assert result.base_cascaded is True
    assert [(s.before_sha, s.after_sha) for s in result.affected] == [
        (P1, r1),
        (P2, r2),
        (P3, r3),
    ]
    assert world.events("rebase") == [
        ("rebase", P1, NEWBASE, MAIN),
        ("rebase", P2, r1, P1),
        ("rebase", P3, r2, P2),
    ]
    assert world.persistence.checkpoints == [
        ("101", NEWBASE, r1),
        ("102", r1, r2),
        ("103", r2, r3),
    ]
    record = world.persistence.prepared[0]
    assert record.before["base"] == {"branch": "main", "sha": NEWBASE}
    assert record.after["base_parent"] == NEWBASE
    world.assert_guard_cleaned()


def test_base_dry_run_previews_movement_without_consent_or_mutation():
    world = _three_layer_world()
    world.base_head = NEWBASE
    world.remote["main"] = NEWBASE
    remote_before = dict(world.remote)
    approvals: list[SyncResult.Cascade] = []
    r1 = _reb(P1, NEWBASE)
    r2 = _reb(P2, r1)
    r3 = _reb(P3, r2)

    result = world.sync(
        include_base=True,
        dry_run=True,
        approve=lambda cascade: approvals.append(cascade) or True,
    )

    assert result.dry_run is True and result.base_cascaded is False
    assert [(layer.before_sha, layer.after_sha) for layer in result.affected] == [
        (P1, r1),
        (P2, r2),
        (P3, r3),
    ]
    assert approvals == []
    world.assert_nothing_journaled()
    assert world.remote == remote_before
    assert world.events("push_atomic") == []
    world.assert_guard_cleaned()


def test_the_cascade_is_offered_for_approval_with_base_facts():
    world = _three_layer_world()
    world.base_head = NEWBASE
    world.remote["main"] = NEWBASE
    seen: list[SyncResult.Cascade] = []

    def approve(cascade: SyncResult.Cascade) -> bool:
        seen.append(cascade)
        return True

    world.sync(include_base=True, approve=approve)
    (cascade,) = seen
    assert cascade.objective_id == OBJECTIVE
    assert cascade.include_base is True
    assert cascade.base_branch == "main"
    assert cascade.base_before == MAIN and cascade.base_after == NEWBASE
    assert [layer.pr_number for layer in cascade.layers] == [201, 202, 203]


# ----------------------------------------------------------------- the no-op + declined arms


def test_no_local_change_is_the_typed_no_op():
    world = _three_layer_world()
    result = world.sync()
    assert result.no_op is True and result.operation_id is None
    assert result.affected == () and result.base_cascaded is False
    assert result.base_advanced is False
    world.assert_nothing_journaled()
    assert world.worktrees_added == []  # no candidate work at all


def test_no_op_carries_the_base_advanced_notice():
    world = _three_layer_world()
    world.base_head = NEWBASE
    world.findings = (
        TrainFinding(kind=FindingKind.INFO, code="base_advanced", message="advanced"),
    )
    result = world.sync()  # no --base: the advance is a notice, never an implicit cascade
    assert result.no_op is True and result.base_advanced is True
    world.assert_nothing_journaled()


def test_stale_local_branch_is_never_a_revert_source():
    # The local branch resolves BEHIND the published head (an ancestor): information, never
    # a trigger — the cascade must not "sync" the remote back to the stale head.
    world = _three_layer_world()
    stale = "5" * 40
    world.local["plan-102"] = stale
    world.ancestry.add((stale, P2))
    result = world.sync()
    assert result.no_op is True
    world.assert_nothing_journaled()


def test_declined_cascade_journals_nothing_and_cleans_the_guard():
    world = _amended_middle_world()
    result = world.sync(approve=lambda cascade: False)
    assert result.declined is True and result.no_op is False
    assert result.operation_id is None and result.affected == ()
    world.assert_nothing_journaled()
    assert world.events("push_atomic") == []
    assert world.worktrees_added != []  # candidates were calculated…
    world.assert_guard_cleaned()  # …and the guard cleaned them up


# ----------------------------------------------------------------- claimed-prefix derivation


def test_half_checkpoint_pair_is_malformed():
    world = _three_layer_world()
    world.layers[1] = _layer(
        "1.2", "102", pr_number=202, parent_checkpoint_sha=P1, published_head_sha=None
    )
    error = _sync_error(world)
    assert error.error_type == "claimed_prefix_malformed"
    assert "half a checkpoint pair" in str(error)


def test_checkpointed_layer_missing_identity_is_malformed():
    world = _three_layer_world()
    world.layers[1] = _layer(
        "1.2", "102", pr_number=None, parent_checkpoint_sha=P1, published_head_sha=P2
    )
    error = _sync_error(world)
    assert error.error_type == "claimed_prefix_malformed"
    assert "identity" in str(error)


def test_claimed_layer_above_unclaimed_is_malformed():
    world = _three_layer_world()
    world.layers[1] = _layer("1.2", "102", pr_number=202)  # no checkpoints
    error = _sync_error(world)
    assert error.error_type == "claimed_prefix_malformed"
    assert "contiguous" in str(error)


def test_unclaimed_suffix_is_simply_outside_the_universe():
    # A trailing unpublished layer is fine — the claimed prefix just ends below it.
    world = _amended_middle_world()
    world.layers.append(_layer("1.4", "104"))
    result = world.sync()
    assert [s.plan_id for s in result.affected] == ["102", "103"]


def test_claimed_prefix_skips_the_landed_bottom_run():
    # A LANDED bottom layer is outside the claimed universe (§8.44/§8.49): the remainder
    # starts above it and claimed[0]'s expected base is the objective base (the retarget).
    world = _three_layer_world()
    world.layers[0] = dataclasses_replace(world.layers[0], publication=LayerPublication.LANDED)
    claimed = sync.derive_claimed_prefix(world._reconstruct(ROOT, OBJECTIVE))
    assert [(layer.node_id, layer.plan_id) for layer in claimed] == [
        ("1.2", "102"),
        ("1.3", "103"),
    ]
    assert sync._expected_pr_base(claimed, 0, "main") == "main"
    assert sync._expected_pr_base(claimed, 1, "main") == "plan-102"


def test_landed_above_a_non_landed_claimed_layer_is_malformed():
    world = _three_layer_world()
    world.layers[1] = dataclasses_replace(world.layers[1], publication=LayerPublication.LANDED)
    error = _sync_error(world)
    assert error.error_type == "claimed_prefix_malformed"
    assert "landed" in str(error)


def test_public_claimed_prefix_derivation_uses_checkpoint_claims():
    world = _three_layer_world()
    world.layers.append(_layer("1.4", "104"))
    claimed = sync.derive_claimed_prefix(world._reconstruct(ROOT, OBJECTIVE))
    assert isinstance(claimed, tuple)
    assert all(isinstance(layer, sync.ClaimedLayer) for layer in claimed)
    assert [(layer.node_id, layer.plan_id) for layer in claimed] == [
        ("1.1", "101"),
        ("1.2", "102"),
        ("1.3", "103"),
    ]


# ----------------------------------------------------------------- trigger-scoped cascade


def test_trigger_uses_only_its_local_head_and_published_successor_sources():
    world = _amended_middle_world()
    successor_local = "c" * 40
    world.local["plan-103"] = successor_local
    world.ancestry.add((P2, successor_local))
    result = world.sync(trigger_plan_id="#102")
    assert [(layer.plan_id, layer.after_sha) for layer in result.affected] == [
        ("102", C2),
        ("103", R3),
    ]
    assert world.events("rebase") == [("rebase", P3, C2, P2)]
    assert successor_local not in str(world.events("push_atomic"))


def test_trigger_without_a_resolvable_local_head_fails_closed():
    world = _three_layer_world()
    error = _sync_error(world, trigger_plan_id="102")
    assert error.error_type == "git_error"
    assert "does not resolve to a committed local head" in str(error)


def test_trigger_unchanged_or_stale_is_a_no_op():
    unchanged = _three_layer_world()
    unchanged.local["plan-102"] = P2
    assert unchanged.sync(trigger_plan_id="102").no_op is True

    stale = _three_layer_world()
    stale_head = "5" * 40
    stale.local["plan-102"] = stale_head
    stale.ancestry.add((stale_head, P2))
    assert stale.sync(trigger_plan_id="102").no_op is True


def test_trigger_must_name_a_claimed_layer():
    world = _three_layer_world()
    error = _sync_error(world, trigger_plan_id="#999")
    assert error.error_type == "claimed_prefix_malformed"
    assert "published classification and the checkpoint claims disagree" in str(error)


def test_trigger_refuses_base_and_adopt_composition():
    world = _three_layer_world()
    with pytest.raises(ValueError, match="trigger-scoped synchronization"):
        world.sync(trigger_plan_id="102", include_base=True)
    with pytest.raises(ValueError, match="trigger-scoped synchronization"):
        world.sync(trigger_plan_id="102", adopt_node="1.2")


# ----------------------------------------------------------------- drift reachability


def test_drifted_bottom_layer_is_remote_drift_never_a_false_no_op():
    # The classifier would truncate its verified prefix at the drifted bottom layer; sync's
    # claimed universe keeps the layer in scope so the drift refusal is REACHABLE.
    world = _three_layer_world()
    world.remote["plan-101"] = "9" * 40
    error = _sync_error(world)
    assert error.error_type == "remote_drift"
    assert "plan-101" in str(error)
    world.assert_nothing_journaled()


def test_drifted_upper_claimed_layer_blocks_a_lower_cascade():
    world = _amended_middle_world()  # the trigger is layer 1.2…
    world.remote["plan-103"] = "9" * 40  # …but the claimed layer ABOVE it drifted
    error = _sync_error(world)
    assert error.error_type == "remote_drift"
    assert "plan-103" in str(error)


# ----------------------------------------------------------------- the preflight refusal matrix


def test_not_stacked_when_no_train():
    world = _three_layer_world()
    world.no_train = True
    assert _sync_error(world).error_type == "not_stacked"


def test_missing_lineage_is_not_stacked():
    world = _three_layer_world()
    world.lineage = None
    assert _sync_error(world).error_type == "not_stacked"


@pytest.mark.parametrize(
    "kind", [OperationKind.PUBLISH, OperationKind.TRANSFER, OperationKind.LAND]
)
def test_foreign_unresolved_kind_refuses(kind):
    # One-unresolved-per-lineage, per kind: an unresolved record of EVERY foreign kind
    # blocks a fresh sync (an unresolved SYNC/ADOPT routes to its own resume instead).
    world = _amended_middle_world()
    record = _record(operation_kind=kind, affected_plans=("102",))
    world.persistence.unresolved_records[record.operation_id] = record
    assert _sync_error(world).error_type == "unresolved_operation"


def test_resume_deleted_branch_is_sync_drift_fail_closed():
    # The drifted-world corroboration arm (per-ref leases): a recorded ref whose branch was
    # DELETED since the crash matches neither its before nor after lease — sync_drift,
    # nothing journaled, nothing pushed.
    record = _record()
    world = _resume_world(record)
    world.remote["plan-103"] = None  # deleted since the crash; plan-102 still at before P2
    error = _sync_error(world)
    assert error.error_type == "sync_drift"
    assert world.events("push_atomic") == []
    assert world.persistence.prepared == [] and world.persistence.outcomes == []


def test_pr_drift_rows():
    for mutate in (
        lambda w: w.pr_entries.__setitem__(202, ("plan-102", "plan-101", "CLOSED")),
        lambda w: w.pr_entries.__setitem__(202, ("plan-102", "main", "OPEN")),  # wrong base
        lambda w: w.pr_entries.pop(202),  # absent
    ):
        world = _amended_middle_world()
        mutate(world)
        error = _sync_error(world)
        assert error.error_type == "pr_drift"
        world.assert_nothing_journaled()


def test_membership_drift():
    world = _amended_middle_world()
    world.stack_members = [201, 202]  # the claimed prefix is not exactly stacked
    assert _sync_error(world).error_type == "membership_drift"


def test_dirty_worktree_refuses():
    world = _amended_middle_world()
    world.layers[2] = _layer(
        "1.3",
        "103",
        pr_number=203,
        parent_checkpoint_sha=P2,
        published_head_sha=P3,
        writer=LayerWriter.DIRTY,
    )
    error = _sync_error(world)
    assert error.error_type == "dirty_worktree"
    assert "1.3" in str(error)


def test_clean_active_worktree_does_not_block():
    # A clean checked-out worktree is the normal state of the just-amended layer.
    world = _amended_middle_world()
    world.layers[1] = _layer(
        "1.2",
        "102",
        pr_number=202,
        parent_checkpoint_sha=P1,
        published_head_sha=P2,
        writer=LayerWriter.ACTIVE,
    )
    assert world.sync().no_op is False


def test_active_remote_writer_refuses():
    world = _amended_middle_world()
    world.writer_probe.active = frozenset({"103"})
    error = _sync_error(world)
    assert error.error_type == "active_writer"
    assert "103" in str(error)
    assert world.writer_probe.calls == [("101", "102", "103")]


def test_writer_probe_failure_fails_closed():
    world = _amended_middle_world()
    world.writer_probe.boom = WriterObservationError("gh api down")
    error = _sync_error(world)
    assert error.error_type == "writer_observation_unavailable"
    assert "gh api down" in str(error)


def test_include_base_with_unobserved_base_refuses():
    world = _three_layer_world()
    world.base_head = None
    error = _sync_error(world, include_base=True)
    assert error.error_type == "base_unobserved"


def test_stale_parent_refuses():
    world = _amended_middle_world()
    world.ancestry.discard((P1, C2))  # the amended head no longer contains its parent edge
    error = _sync_error(world)
    assert error.error_type == "stale_parent"
    assert "plan-102" in str(error)


def test_multiple_push_urls_refuses():
    world = _amended_middle_world()
    world.urls = ["https://gh/octo/repo.git", "/mirror.git"]
    error = _sync_error(world)
    assert error.error_type == "multiple_push_urls"


def test_atomic_push_unsupported():
    world = _amended_middle_world()
    world.atomic_probe_boom = git.GitError("atomic not supported")
    error = _sync_error(world)
    assert error.error_type == "atomic_push_unsupported"
    # The probe was pinned to the bottom AFFECTED layer's branch at its verified head.
    assert world.events("atomic_probe") == [
        ("atomic_probe", "https://gh/octo/repo.git", "plan-102", P2)
    ]


# ----------------------------------------------------------------- the conflict stop


def test_rebase_conflict_retains_residue_under_a_manifest():
    world = _amended_middle_world()
    world.rebase_conflicts.add((P3, C2))  # layer 1.3's transplant conflicts
    # The request carries an ALIAS id: the hint must interpolate the redirect-resolved
    # train id, never the raw request id.
    error = _sync_error(world, objective_id="REQUEST-ALIAS")
    assert error.error_type == "rebase_conflict"
    assert "1.3" in str(error)
    # The `for layer <node_id> ` token (trailing space) is load-bearing cross-plane (§8.49):
    # the warm drive's corroborateSyncConflict keys its freshness check on it — a message
    # rewrite that drops it silently disables the /objective-sync conflict drive.
    assert "for layer 1.3 " in str(error)
    assert "no remote ref and no journal record" in str(error)
    # Cross-plane lockstep: the appended warm-route sentence names the warm command id
    # registered in extension/pi/v1/delivery/stackSync.ts and the landed consent posture
    # ("on your approval") — with the TRAIN's projection id, not the request alias.
    assert "`/objective-sync 500`" in str(error)
    assert "REQUEST-ALIAS" not in str(error)
    # The guard DISARMED: temp refs + worktree retained, manifest written.
    manifest = world.manifests[LINEAGE]
    assert manifest.conflict_node_id == "1.3"
    assert manifest.include_base is False and manifest.captured_base_head is None
    assert [
        (layer.node_id, layer.new_parent_edge, layer.candidate_sha) for layer in manifest.layers
    ] == [
        ("1.2", P1, C2),  # the completed layer below the conflict
        ("1.3", C2, None),  # the conflicting layer: parent known, no candidate
    ]
    assert manifest.worktree_path == str(world.worktrees_added[0][0])
    assert world.worktrees_removed == []
    assert world.refs != {}  # the completed candidate's temp ref survives
    world.assert_nothing_journaled()
    assert world.events("push_atomic") == []
    # The write ordering: the manifest lands before the error propagates, never after
    # any journal/push event (there are none).
    kinds = [t[0] for t in world.timeline]
    assert "manifest_write" in kinds and "prepared" not in kinds


def test_continuation_gate_refuses_a_fresh_sync():
    world = _amended_middle_world()
    world.manifests[LINEAGE] = continuation.ContinuationManifest(
        operation_id=mint_operation_id(),
        objective_id=OBJECTIVE,
        delivery_lineage=LINEAGE,
        run_id="01RUN",
        include_base=False,
        captured_base_head=None,
        layers=(),
        conflict_node_id="1.3",
        worktree_path="/wt/sync-OP",
        created="2026-01-01T00:00:00Z",
    )
    # The request carries an ALIAS id: the hint must interpolate the redirect-resolved
    # train id, never the raw request id.
    error = _sync_error(world, objective_id="REQUEST-ALIAS")
    assert error.error_type == "sync_conflict_pending"
    assert "/wt/sync-OP" in str(error)  # names the retained worktree
    assert "sync-continuations" in str(error)  # …and the manifest path
    # Cross-plane lockstep: the appended warm-route sentence names the warm command id
    # registered in extension/pi/v1/delivery/stackSync.ts and the landed consent posture
    # ("on your approval") — with the TRAIN's projection id, not the request alias.
    assert "`/objective-sync 500`" in str(error)
    assert "REQUEST-ALIAS" not in str(error)
    world.assert_nothing_journaled()


def test_continuation_gate_hint_requires_manifest_train_identity():
    # A foreign/stale manifest (same lineage, different objective — e.g. a predecessor
    # objective's continuation surviving a transfer) still GATES identically, but the
    # warm-route hint is suppressed: the hinted route could only end in the downstream
    # mismatch refusal (`--continue` → continuation_invalid; warm corroboration →
    # report-only), so advertising it would be false.
    world = _amended_middle_world()
    world.manifests[LINEAGE] = continuation.ContinuationManifest(
        operation_id=mint_operation_id(),
        objective_id="777",
        delivery_lineage=LINEAGE,
        run_id="01RUN",
        include_base=False,
        captured_base_head=None,
        layers=(),
        conflict_node_id="1.3",
        worktree_path="/wt/sync-OP",
        created="2026-01-01T00:00:00Z",
    )
    error = _sync_error(world)
    assert error.error_type == "sync_conflict_pending"
    assert "/wt/sync-OP" in str(error) and "sync-continuations" in str(error)
    assert "/objective-sync" not in str(error)
    world.assert_nothing_journaled()


def test_unparseable_manifest_still_gates():
    world = _amended_middle_world()
    world.pending_unparseable = True
    error = _sync_error(world)
    assert error.error_type == "sync_conflict_pending"
    assert "could not be parsed" in str(error)
    # Deliberately abort-only: automated resolution cannot corroborate an unparseable
    # manifest, so this arm never advertises it.
    assert "/objective-sync" not in str(error)


def test_warm_route_hint_confines_the_objective_id():
    # The full sentence is contract: the copyable command, the read-write qualification,
    # the approval-dependent dispatch, and the publication handback — pinned exactly so a
    # wording drift that overclaims (e.g. unconditional dispatch) fails here.
    assert sync._warm_route_hint("500") == (
        "Automated resolution is available from a read-write perk session: run "
        "`/objective-sync 500` — on your approval it dispatches the conflict "
        "resolver into the retained worktree and hands publication back to you."
    )
    # Conforming ids interpolate into the copyable command (numeric GitHub ids, Linear
    # keys, the 64-char boundary of the cap).
    for good in ("500", "ENG-7", "a" * 64):
        hint = sync._warm_route_hint(good)
        assert hint is not None
        assert f"`/objective-sync {good}`" in hint
    # Non-conforming ids fail closed to omission — never an id-less command, and the raw
    # input never reaches any returned text: option-shaped tokens, dot segments, over the
    # 64-char cap, the empty string, and whitespace/metacharacter ids.
    for bad in ("--json", ".", "..", "a" * 65, "", "7; rm -rf"):
        assert sync._warm_route_hint(bad) is None


def test_cross_lineage_manifest_does_not_gate():
    world = _amended_middle_world()
    world.manifests["01OTHERLINEAGE"] = continuation.ContinuationManifest(
        operation_id=mint_operation_id(),
        objective_id="777",
        delivery_lineage="01OTHERLINEAGE",
        run_id="01RUN",
        include_base=False,
        captured_base_head=None,
        layers=(),
        conflict_node_id="9.9",
        worktree_path="/wt/sync-X",
        created="2026-01-01T00:00:00Z",
    )
    assert world.sync().no_op is False  # this lineage cascades untouched


# ----------------------------------------------------------------- the approval race


def test_remote_mutation_during_approval_is_remote_drift_with_no_record():
    world = _amended_middle_world()

    def approve(cascade: SyncResult.Cascade) -> bool:
        world.remote["plan-103"] = "9" * 40  # a foreign writer moves a lease mid-approval
        return True

    error = _sync_error(world, approve=approve)
    assert error.error_type == "remote_drift"
    assert "re-observed after approval" in str(error)
    world.assert_nothing_journaled()  # NO prepared record was written
    world.assert_guard_cleaned()


def test_base_mutation_during_approval_is_remote_drift():
    world = _three_layer_world()
    world.base_head = NEWBASE
    world.remote["main"] = NEWBASE

    def approve(cascade: SyncResult.Cascade) -> bool:
        world.remote["main"] = "9" * 40
        return True

    error = _sync_error(world, include_base=True, approve=approve)
    assert error.error_type == "remote_drift"
    world.assert_nothing_journaled()


# ----------------------------------------------------------------- push rejection


def test_push_rejected_all_before_abandons_with_proof():
    world = _amended_middle_world()
    world.push_reject = True
    error = _sync_error(world)
    assert error.error_type == "push_rejected"
    # Abandoned-with-proof: the one outcome is ABANDONED carrying the all-before observation.
    (outcome,) = world.persistence.outcomes
    assert outcome.role is EventRole.ABANDONED
    assert outcome.observed == {
        "branches": [{"ref": "plan-102", "sha": P2}, {"ref": "plan-103", "sha": P3}]
    }
    assert world.persistence.checkpoints == []
    world.assert_guard_cleaned()


def test_push_rejected_mixed_observation_is_sync_drift_unresolved():
    world = _amended_middle_world()
    world.push_reject = True
    world.push_reject_leaves = {"plan-103": "9" * 40}  # neither before nor after
    error = _sync_error(world)
    assert error.error_type == "sync_drift"
    assert world.persistence.outcomes == []  # unresolved — no abandon without proof
    assert world.persistence.unresolved_records  # the prepared record stays open
    world.assert_guard_cleaned()


def test_push_rejected_unreadable_refetch_is_postcondition_unverified():
    world = _amended_middle_world()
    world.push_reject = True
    world.on_push = lambda: setattr(world, "remote_head_boom", git.GitError("net down"))
    error = _sync_error(world)
    assert error.error_type == "postcondition_unverified"
    assert world.persistence.outcomes == []


# ----------------------------------------------------------------- postcondition verification


def test_foreign_writer_after_push_is_sync_drift_unresolved():
    world = _amended_middle_world()
    world.on_push = lambda: world.remote.__setitem__("plan-103", "9" * 40)
    error = _sync_error(world)
    assert error.error_type == "sync_drift"
    assert world.persistence.checkpoints == []
    assert world.persistence.unresolved_records


def test_unreadable_branch_refetch_is_postcondition_unverified():
    world = _amended_middle_world()
    world.on_push = lambda: setattr(world, "fetch_boom", git.GitError("net down"))
    error = _sync_error(world)
    assert error.error_type == "postcondition_unverified"


def test_adapter_wrapped_branch_refetch_is_postcondition_unverified():
    world = _amended_middle_world()
    wrapped = TrainReconstructionError("net down", error_type="git_error")
    world.on_push = lambda: setattr(world, "fetch_boom", wrapped)

    error = _sync_error(world)

    assert error.error_type == "postcondition_unverified"
    assert world.persistence.checkpoints == []
    assert world.persistence.unresolved_records


def test_pr_settle_poll_converges_on_a_stale_then_current_read():
    world = _amended_middle_world()
    stale = PrDeliveryFacts(
        number=202,
        state="OPEN",
        is_draft=True,
        base_ref="plan-101",
        head_ref="plan-102",
        head_sha=P2,  # the pre-push head: GitHub has not propagated yet
    )
    world.on_push = lambda: world.pr_facts_script.append(stale)
    result = world.sync()
    assert result.operation_id is not None
    assert world.sleeps == [2.0]  # exactly one settle wait before the converged read


def test_pr_still_stale_after_the_poll_is_pr_drift():
    world = _amended_middle_world()
    stale = PrDeliveryFacts(
        number=202,
        state="OPEN",
        is_draft=True,
        base_ref="plan-101",
        head_ref="plan-102",
        head_sha=P2,
    )
    world.on_push = lambda: world.pr_facts_script.extend([stale] * 5)
    error = _sync_error(world)
    assert error.error_type == "pr_drift"
    assert len(world.sleeps) == 4  # the full bounded poll
    assert world.persistence.checkpoints == []


def test_unreadable_pr_read_is_postcondition_unverified():
    world = _amended_middle_world()
    world.on_push = lambda: world.pr_facts_script.append(GitHubError("boom"))
    error = _sync_error(world)
    assert error.error_type == "postcondition_unverified"


def test_adapter_wrapped_pr_read_is_postcondition_unverified():
    world = _amended_middle_world()
    wrapped = TrainReconstructionError("API down", error_type="github_error")
    world.on_push = lambda: world.pr_facts_script.append(wrapped)

    error = _sync_error(world)

    assert error.error_type == "postcondition_unverified"
    assert world.persistence.checkpoints == []
    assert world.persistence.unresolved_records


def test_membership_no_longer_exact_after_push_is_membership_drift():
    world = _amended_middle_world()
    world.on_push = lambda: setattr(world, "stack_members", [201, 202])
    error = _sync_error(world)
    assert error.error_type == "membership_drift"
    assert world.persistence.checkpoints == []


def test_adapter_wrapped_membership_read_is_postcondition_unverified():
    world = _amended_middle_world()
    wrapped = TrainReconstructionError("API down", error_type="github_error")
    world.on_push = lambda: setattr(world, "stack_read_boom", wrapped)

    error = _sync_error(world)

    assert error.error_type == "postcondition_unverified"
    assert world.persistence.checkpoints == []
    assert world.persistence.unresolved_records


# ----------------------------------------------------------------- the resume matrix


def _record(
    *,
    operation_kind: OperationKind = OperationKind.SYNC,
    affected_plans: tuple[str, ...] = ("102", "103"),
    before: dict | None = None,
    after: dict | None = None,
    lineage: str = LINEAGE,
) -> PreparedRecord:
    return PreparedRecord(
        operation_id=mint_operation_id(),
        operation_kind=operation_kind,
        delivery_lineage=lineage,
        objective_id=OBJECTIVE,
        run_id="01RUN",
        created="2026-01-01T00:00:00Z",
        affected_plans=affected_plans,
        before=before
        if before is not None
        else {
            "base": None,
            "branches": [{"ref": "plan-102", "sha": P2}, {"ref": "plan-103", "sha": P3}],
            "prs": [
                {"number": 202, "head_sha": P2, "base": "plan-101"},
                {"number": 203, "head_sha": P3, "base": "plan-102"},
            ],
            "stack": {"members": [201, 202, 203]},
        },
        after=after
        if after is not None
        else {
            "branches": [{"ref": "plan-102", "sha": C2}, {"ref": "plan-103", "sha": R3}],
            "prs": [
                {"number": 202, "head_sha": C2, "base": "plan-101"},
                {"number": 203, "head_sha": R3, "base": "plan-102"},
            ],
            "base_parent": None,
        },
    )


def _resume_world(record: PreparedRecord) -> _World:
    world = _amended_middle_world()
    world.persistence.unresolved_records[record.operation_id] = record
    return world


def test_resume_all_after_rolls_forward_under_the_same_operation():
    record = _record()
    world = _resume_world(record)
    world.remote.update({"plan-102": C2, "plan-103": R3})  # the push landed; nothing else did
    result = world.sync()
    assert result.resumed is True
    assert result.operation_id == record.operation_id
    assert result.abandoned_operation_id is None
    assert [(s.before_sha, s.after_sha) for s in result.affected] == [(P2, C2), (P3, R3)]
    # Steps 13-14 only: no fresh candidates, no push — verify then persist.
    assert world.events("push_atomic") == [] and world.worktrees_added == []
    assert world.persistence.checkpoints == [("102", P1, C2), ("103", C2, R3)]
    assert world.persistence.outcomes[-1].role is EventRole.COMPLETED


def test_trigger_resume_all_after_rolls_forward_then_cascades_fresh_head():
    record = _record()
    world = _resume_world(record)
    world.remote.update({"plan-102": C2, "plan-103": R3})
    newer = "d" * 40
    world.local["plan-102"] = newer
    world.ancestry.add((P1, newer))

    result = world.sync(trigger_plan_id="102")

    assert result.resumed is False
    assert result.operation_id is not None and result.operation_id != record.operation_id
    assert result.abandoned_operation_id is None
    assert result.notes[0] == (
        f"concluded unresolved operation {record.operation_id} (roll-forward) before cascading"
    )
    assert result.affected[0].before_sha == C2
    assert result.affected[0].after_sha == newer
    assert [outcome.role for outcome in world.persistence.outcomes] == [
        EventRole.COMPLETED,
        EventRole.COMPLETED,
    ]
    assert len(world.persistence.prepared) == 1
    assert world.status_calls == [StatusRequest(OBJECTIVE), StatusRequest(OBJECTIVE)]


def test_trigger_resume_all_after_then_fresh_noop_when_head_already_published():
    record = _record()
    world = _resume_world(record)
    world.remote.update({"plan-102": C2, "plan-103": R3})

    result = world.sync(trigger_plan_id="102")

    assert result.no_op is True
    assert result.resumed is False and result.operation_id is None
    assert result.notes == (
        f"concluded unresolved operation {record.operation_id} (roll-forward) before cascading",
    )
    assert world.persistence.prepared == []
    assert [outcome.role for outcome in world.persistence.outcomes] == [EventRole.COMPLETED]


def test_trigger_resume_all_after_keeps_completion_when_fresh_preflight_refuses():
    record = _record()
    world = _resume_world(record)
    world.remote.update({"plan-102": C2, "plan-103": R3})
    world.local["plan-102"] = "d" * 40
    world.writer_probe.active = frozenset({"102"})

    error = _sync_error(world, trigger_plan_id="102")

    assert error.error_type == "active_writer"
    assert [outcome.role for outcome in world.persistence.outcomes] == [EventRole.COMPLETED]
    assert record.operation_id not in world.persistence.unresolved_records
    assert world.persistence.prepared == []
    assert world.events("push_atomic") == []


def test_oversized_prepared_record_is_typed_before_any_remote_effect() -> None:
    world = _amended_middle_world()
    world.persistence.prepared_boom = JournalRecordTooLarge("prepared record exceeds 10000 chars")

    with pytest.raises(DeliveryError) as excinfo:
        world.sync()

    assert excinfo.value.error_type == "journal_record_too_large"
    assert "10000" in str(excinfo.value)
    assert world.persistence.prepared == [] and world.events("push_atomic") == []
    assert world.remote["plan-102"] == P2 and world.remote["plan-103"] == P3


def test_oversized_completed_record_leaves_the_prepared_operation_unresolved() -> None:
    world = _amended_middle_world()
    world.persistence.completed_boom = JournalRecordTooLarge("completed record exceeds 10000 chars")

    with pytest.raises(DeliveryError) as excinfo:
        world.sync()

    assert excinfo.value.error_type == "journal_record_too_large"
    (prepared,) = world.persistence.prepared
    assert prepared.operation_id in world.persistence.unresolved_records
    assert world.remote["plan-102"] == C2 and world.remote["plan-103"] == R3
    assert world.persistence.outcomes == []


# --- the process-death completion-side cells (the failure-hardening ledger's S4/S4b/S5) --
# Genuine kill-at-the-boundary + rerun: the crash run dies inside `_persist_completion`
# (fail-once raise — faithful for the durable axes: sync's finally-cleanup touches only
# machine-local residue, which is S1's separately proven cell), then the SAME public
# surface reruns and converges — exactly one prepared + one completed, checkpoints
# converged, and no second atomic push.


def test_crash_mid_checkpoint_writes_rolls_forward_on_rerun():
    # S4: died after SOME but not all per-layer checkpoint writes. The rerun classifies
    # all_after from the recorded refs and rolls forward under the same operation — the
    # checkpoint re-writes are idempotent merge-writes (allowed); completed lands once.
    world = _amended_middle_world()
    world.persistence.checkpoints_boom_at = (2, GitHubError("process death mid checkpoints"))
    with pytest.raises(DeliveryError) as excinfo:
        world.sync()
    assert excinfo.value.error_type == "github_error"
    (record,) = world.persistence.prepared
    assert [c[0] for c in world.persistence.checkpoints] == ["102"]  # 103's never landed
    assert world.persistence.outcomes == []
    assert world.remote["plan-102"] == C2 and world.remote["plan-103"] == R3  # push applied
    pushes = len(world.events("push_atomic"))

    result = world.sync()
    assert result.resumed is True and result.operation_id == record.operation_id
    assert len(world.persistence.prepared) == 1  # never a second prepared
    assert len(world.events("push_atomic")) == pushes  # roll-forward never re-pushes
    # Both layers' checkpoints converge on the recorded after states.
    assert world.persistence.checkpoints[-2:] == [("102", P1, C2), ("103", C2, R3)]
    (outcome,) = world.persistence.outcomes
    assert outcome.role is EventRole.COMPLETED and outcome.operation_id == record.operation_id


def test_crash_after_all_checkpoints_before_completed_converges_on_rerun():
    # S4b: every checkpoint landed; the completed append never did. The rerun rolls the
    # same operation forward — the terminal record lands exactly once.
    world = _amended_middle_world()
    world.persistence.completed_boom = GitHubError("process death before the completed append")
    with pytest.raises(DeliveryError) as excinfo:
        world.sync()
    assert excinfo.value.error_type == "github_error"
    (record,) = world.persistence.prepared
    assert [c[0] for c in world.persistence.checkpoints] == ["102", "103"]
    assert world.persistence.outcomes == []

    result = world.sync()
    assert result.resumed is True and result.operation_id == record.operation_id
    assert len(world.persistence.prepared) == 1
    (outcome,) = world.persistence.outcomes
    assert outcome.role is EventRole.COMPLETED and outcome.operation_id == record.operation_id


def test_rerun_after_completed_is_the_typed_noop():
    # S5: the operation completed; a rerun finds no local change and takes the typed no-op
    # arm — nothing journaled, nothing pushed.
    world = _amended_middle_world()
    first = world.sync()
    assert first.no_op is False
    prepared_before = len(world.persistence.prepared)
    pushes_before = len(world.events("push_atomic"))
    result = world.sync()
    assert result.no_op is True
    assert len(world.persistence.prepared) == prepared_before
    assert len(world.events("push_atomic")) == pushes_before


def test_resume_all_before_abandons_with_proof_and_prepares_fresh():
    record = _record()
    world = _resume_world(record)  # remote still at P2/P3; the local amend still stands
    result = world.sync()
    assert result.resumed is False
    assert result.abandoned_operation_id == record.operation_id
    assert result.operation_id is not None and result.operation_id != record.operation_id
    # The abandon-with-proof came first, then the fresh prepared record.
    roles = [outcome.role for outcome in world.persistence.outcomes]
    assert roles == [EventRole.ABANDONED, EventRole.COMPLETED]
    assert world.persistence.outcomes[0].observed == {
        "branches": [{"ref": "plan-102", "sha": P2}, {"ref": "plan-103", "sha": P3}]
    }
    assert world.persistence.prepared[0].operation_id == result.operation_id
    assert world.remote["plan-102"] == C2  # the fresh cascade pushed


def test_trigger_resume_all_before_abandons_then_runs_fresh_trigger():
    record = _record()
    world = _resume_world(record)
    result = world.sync(trigger_plan_id="102")
    assert result.resumed is False
    assert result.abandoned_operation_id == record.operation_id
    assert result.operation_id is not None and result.operation_id != record.operation_id
    assert world.remote["plan-102"] == C2


def test_resume_mixed_state_is_sync_drift_unresolved():
    record = _record()
    world = _resume_world(record)
    world.remote["plan-102"] = C2  # one ref applied, the other still at before
    error = _sync_error(world)
    assert error.error_type == "sync_drift"
    assert world.persistence.outcomes == []  # unresolved, fail closed
    assert world.persistence.unresolved_records


def test_trigger_resume_mixed_state_stays_sync_drift():
    record = _record()
    world = _resume_world(record)
    world.remote["plan-102"] = C2
    assert _sync_error(world, trigger_plan_id="102").error_type == "sync_drift"


def test_resume_corroboration_drift_rows():
    # The fresh reconstruction must still agree with the record: a foreign lineage, a
    # missing plan, a renamed branch, and a re-staged PR are each sync_drift.
    rows: list[Callable[[_World], None]] = [
        lambda w: w.layers.__setitem__(
            1,
            _layer("1.2", "999", pr_number=202, parent_checkpoint_sha=P1, published_head_sha=P2),
        ),
        lambda w: w.layers.__setitem__(
            1,
            _layer(
                "1.2",
                "102",
                pr_number=202,
                parent_checkpoint_sha=P1,
                published_head_sha=P2,
                branch="plan-renamed",
            ),
        ),
        lambda w: w.layers.__setitem__(
            1,
            _layer("1.2", "102", pr_number=999, parent_checkpoint_sha=P1, published_head_sha=P2),
        ),
    ]
    for mutate in rows:
        record = _record()
        world = _resume_world(record)
        mutate(world)
        assert _sync_error(world).error_type == "sync_drift"


def test_resume_foreign_lineage_record_is_sync_drift():
    record = _record(lineage="01FOREIGN")
    world = _resume_world(record)
    assert _sync_error(world).error_type == "sync_drift"


def test_resume_base_cascade_restores_recorded_parent_edges():
    r1 = _reb(P1, NEWBASE)
    record = _record(
        affected_plans=("101", "102", "103"),
        before={
            "base": {"branch": "main", "sha": NEWBASE},
            "branches": [
                {"ref": "plan-101", "sha": P1},
                {"ref": "plan-102", "sha": P2},
                {"ref": "plan-103", "sha": P3},
            ],
            "prs": [
                {"number": 201, "head_sha": P1, "base": "main"},
                {"number": 202, "head_sha": P2, "base": "plan-101"},
                {"number": 203, "head_sha": P3, "base": "plan-102"},
            ],
            "stack": {"members": [201, 202, 203]},
        },
        after={
            "branches": [
                {"ref": "plan-101", "sha": r1},
                {"ref": "plan-102", "sha": _reb(P2, r1)},
                {"ref": "plan-103", "sha": _reb(P3, _reb(P2, r1))},
            ],
            "prs": [
                {"number": 201, "head_sha": r1, "base": "main"},
                {"number": 202, "head_sha": _reb(P2, r1), "base": "plan-101"},
                {"number": 203, "head_sha": _reb(P3, _reb(P2, r1)), "base": "plan-102"},
            ],
            "base_parent": NEWBASE,
        },
    )
    world = _three_layer_world()
    world.persistence.unresolved_records[record.operation_id] = record
    world.remote.update(
        {"plan-101": r1, "plan-102": _reb(P2, r1), "plan-103": _reb(P3, _reb(P2, r1))}
    )
    # Resume must not consult the live base head — a legitimately advanced base never
    # blocks concluding an already-effected cascade.
    assert world.base_head != NEWBASE
    result = world.sync()
    assert result.resumed is True and result.base_cascaded is True
    assert world.persistence.checkpoints == [
        ("101", NEWBASE, r1),
        ("102", r1, _reb(P2, r1)),
        ("103", _reb(P2, r1), _reb(P3, _reb(P2, r1))),
    ]


# ----------------------------------------------------------------- the cleanup guard


def _race_approve(world: _World) -> Callable[[SyncResult.Cascade], bool]:
    def race(cascade: SyncResult.Cascade) -> bool:
        world.remote["plan-103"] = "9" * 40
        return True

    return race


def test_guard_cleans_on_every_non_conflict_exit_arm():
    arms: list[tuple[str, Callable[[_World], None], Callable[[_World], dict]]] = [
        ("success", lambda w: None, lambda w: {}),
        ("declined", lambda w: None, lambda w: {"approve": lambda c: False}),
        ("push_rejected", lambda w: setattr(w, "push_reject", True), lambda w: {}),
        (
            "postcondition_unverified",
            lambda w: setattr(w, "on_push", lambda: setattr(w, "fetch_boom", git.GitError("x"))),
            lambda w: {},
        ),
        ("remote_drift (approval race)", lambda w: None, lambda w: {"approve": _race_approve(w)}),
    ]
    for name, mutate, make_kwargs in arms:
        world = _amended_middle_world()
        mutate(world)
        with contextlib.suppress(sync.SyncError):
            world.sync(**make_kwargs(world))
        assert world.refs == {}, name
        assert world.worktrees_removed == [p for p, _ in world.worktrees_added], name


# ----------------------------------------------------------------- structural blockers + lineage


def test_structural_blockers_refuse_before_any_route():
    # A structurally mis-linked plan (owned by a foreign objective) must never be pushed or
    # checkpointed, even when the live branch/PR observations all look consistent.
    world = _amended_middle_world()
    world.findings = (
        TrainFinding(
            kind=FindingKind.BLOCKER,
            code="wrong_owner",
            message="plan #102 is owned by objective #999",
        ),
    )
    error = _sync_error(world)
    assert error.error_type == "claimed_prefix_malformed"
    assert "wrong_owner" in str(error)
    world.assert_nothing_journaled()
    assert world.worktrees_added == []  # refused before any candidate work


def test_operational_drift_blockers_pass_through_to_syncs_own_preflight():
    # The operational axes (checkpoint/PR/stack drift) stay sync's own fresh observation —
    # a stale projection blocker must not veto a world sync re-verifies itself.
    world = _amended_middle_world()
    world.findings = (
        TrainFinding(kind=FindingKind.BLOCKER, code="checkpoint_drift", message="stale"),
    )
    result = world.sync()
    assert result.no_op is False and result.operation_id is not None


def test_malformed_lineage_is_invalid_input():
    world = _amended_middle_world()
    world.lineage = "../../evil"
    error = _sync_error(world)
    assert error.error_type == "invalid_input"
    assert "path-safe" in str(error)
    world.assert_nothing_journaled()


# ----------------------------------------------------------------- more approval-race axes


def test_pr_mutation_during_approval_is_remote_drift_with_no_record():
    world = _amended_middle_world()

    def approve(cascade: SyncResult.Cascade) -> bool:
        world.pr_entries[203] = ("plan-103", "plan-102", "CLOSED")  # a PR flips mid-approval
        return True

    error = _sync_error(world, approve=approve)
    assert error.error_type == "remote_drift"
    world.assert_nothing_journaled()
    world.assert_guard_cleaned()


def test_membership_mutation_during_approval_is_remote_drift_with_no_record():
    world = _amended_middle_world()

    def approve(cascade: SyncResult.Cascade) -> bool:
        world.stack_members = [201, 202]  # the native stack is edited mid-approval
        return True

    error = _sync_error(world, approve=approve)
    assert error.error_type == "remote_drift"
    world.assert_nothing_journaled()
    world.assert_guard_cleaned()


# ----------------------------------------------------------------- the one-layer train


C1 = "a" * 40  # layer 1.1's amended local head (single-layer scenario)


def _one_layer_world() -> _World:
    world = _World(
        [_layer("1.1", "101", pr_number=201, parent_checkpoint_sha=MAIN, published_head_sha=P1)]
    )
    world.remote.update({"plan-101": P1})
    world.pr_entries = {201: ("plan-101", "main", "OPEN")}
    world.stack_members = None  # below two PRs there is no native stack at all
    world.local["plan-101"] = C1
    world.ancestry.add((MAIN, C1))
    return world


def test_single_layer_train_cascades_without_stack_work():
    world = _one_layer_world()
    result = world.sync()
    assert [(s.before_sha, s.after_sha) for s in result.affected] == [(P1, C1)]
    assert world.events("stack_read") == []  # membership is not_applicable: never read
    record = world.persistence.prepared[0]
    assert record.before["stack"] is None  # …and serialized as the null observation
    assert record.affected_plans == ("101",)
    assert world.events("push_atomic") == [("push_atomic", (("plan-101", P1, C1),))]
    assert world.remote["plan-101"] == C1
    assert world.persistence.checkpoints == [("101", MAIN, C1)]
    assert world.persistence.outcomes[-1].role is EventRole.COMPLETED
    world.assert_guard_cleaned()


# ----------------------------------------------------------------- resume fail-closed rows


def test_resume_malformed_payload_rows_fail_closed():
    # Structurally incomplete/corrupt prepared payloads are sync_drift — never resumed, never
    # completed, no checkpoints; the operation stays unresolved.
    good = _record()
    rows: list[dict] = [
        # A truncated after.branches array (parallel-array break).
        {
            "after": {
                "branches": [{"ref": "plan-102", "sha": C2}],
                "prs": dict(good.after)["prs"],
                "base_parent": None,
            }
        },
        # A non-list branches payload.
        {"before": {**dict(good.before), "branches": "junk"}},
        # A branch entry whose after ref disagrees with its before ref.
        {
            "after": {
                "branches": [
                    {"ref": "plan-999", "sha": C2},
                    {"ref": "plan-103", "sha": R3},
                ],
                "prs": dict(good.after)["prs"],
                "base_parent": None,
            }
        },
    ]
    for overrides in rows:
        record = _record(**overrides)
        world = _resume_world(record)
        error = _sync_error(world)
        assert error.error_type == "sync_drift", overrides
        assert world.persistence.outcomes == [] and world.persistence.checkpoints == []
        assert world.persistence.unresolved_records  # fail closed: still unresolved


def test_resume_stale_recorded_pr_base_is_sync_drift():
    # The record captured plan-102's PR onto 'main', but the fresh train derives 'plan-101' —
    # the base topology moved while the operation was unresolved.
    record = _record(
        after={
            "branches": [{"ref": "plan-102", "sha": C2}, {"ref": "plan-103", "sha": R3}],
            "prs": [
                {"number": 202, "head_sha": C2, "base": "main"},  # stale
                {"number": 203, "head_sha": R3, "base": "plan-102"},
            ],
            "base_parent": None,
        }
    )
    world = _resume_world(record)
    world.remote.update({"plan-102": C2, "plan-103": R3})  # even a landed push cannot resume
    error = _sync_error(world)
    assert error.error_type == "sync_drift"
    assert "PR base" in str(error)
    assert world.persistence.outcomes == [] and world.persistence.checkpoints == []


def test_resume_missing_stored_checkpoints_is_sync_drift():
    record = _record()
    world = _resume_world(record)
    world.layers[1] = _layer("1.2", "102", pr_number=202)  # checkpoints vanished from store
    error = _sync_error(world)
    assert error.error_type == "sync_drift"
    assert "checkpoints" in str(error)
    assert world.persistence.outcomes == [] and world.persistence.checkpoints == []


def test_resume_non_contiguous_affected_order_is_sync_drift():
    # The record names plans 102+103 but the fresh roadmap inserted a layer between them.
    record = _record()
    world = _resume_world(record)
    world.layers.insert(
        2,
        _layer("1.2b", "150", pr_number=250, parent_checkpoint_sha=P2, published_head_sha=P3),
    )
    error = _sync_error(world)
    assert error.error_type == "sync_drift"
    assert "affected order" in str(error)


def test_resume_roll_forward_verifies_recorded_membership():
    record = _record()
    world = _resume_world(record)
    world.remote.update({"plan-102": C2, "plan-103": R3})  # all-after…
    world.stack_members = [201, 202]  # …but the recorded membership no longer holds
    error = _sync_error(world)
    assert error.error_type == "membership_drift"
    assert world.persistence.checkpoints == []
    assert world.persistence.unresolved_records


def test_resume_all_before_then_declined_keeps_the_abandoned_id():
    # The all-before abandon re-runs the FULL fresh protocol; a declined fresh cascade keeps
    # the declined shape (operation_id null) while carrying the abandoned id — the abandon
    # was journaled as an OUTCOME under the old id, never a prepared record.
    record = _record()
    world = _resume_world(record)
    result = world.sync(approve=lambda cascade: False)
    assert result.declined is True and result.operation_id is None
    assert result.abandoned_operation_id == record.operation_id
    assert [o.role for o in world.persistence.outcomes] == [EventRole.ABANDONED]
    assert world.persistence.prepared == []
    world.assert_guard_cleaned()


# ----------------------------------------------------------------- source-pair consistency


def test_corrupt_unchanged_stored_pair_refuses_before_candidates():
    # An UNCHANGED claimed layer whose published head does not contain its stored parent edge
    # is broken stored state — the edge would become the rebase upstream unchecked.
    world = _amended_middle_world()
    world.ancestry.discard((P2, P3))  # layer 1.3's stored pair is internally inconsistent
    error = _sync_error(world)
    assert error.error_type == "claimed_prefix_malformed"
    assert "1.3" in str(error) and "parent checkpoint" in str(error)
    world.assert_nothing_journaled()
    assert world.worktrees_added == []  # refused before any candidate work


# ----------------------------------------------------------------- the full structural set


def test_every_structural_blocker_code_refuses():
    # The hand-maintained allowlist is pinned code-by-code: an omission/typo in any entry
    # would let mutation proceed against structurally untrusted train state.
    contracted = {
        "missing_plan",
        "duplicate_plan_link",
        "wrong_owner",
        "node_link_mismatch",
        "wrong_lineage",
        "lineage_checkpoint_conflict",
        "malformed_plan_header",
        "predecessor_mismatch",
        "journal_corruption",
        # The §8.54 cancellation/checkpoint-topology/journal-history growth — structural
        # because each contradicts stored identity or append-only history perk cannot
        # repair. The two PENDING codes (`publish_outcome_pending`,
        # `canceled_publication_pending`) are deliberately NOT here: a live unresolved
        # PUBLISH concludes via recover / the owning /submit.
        "canceled_status_conflict",
        "canceled_plan_unresolved",
        "canceled_published_layer",
        "canceled_remote_work",
        "cancellation_evidence_unavailable",
        "checkpoint_pair_incomplete",
        "checkpoint_prefix_gap",
        "checkpoint_parent_mismatch",
        "missing_publish_outcome",
        "checkpoint_after_abandoned_publish",
    }
    assert contracted | {"missing_lineage"} == STRUCTURAL_BLOCKER_CODES
    assert "publish_outcome_pending" not in STRUCTURAL_BLOCKER_CODES
    assert "canceled_publication_pending" not in STRUCTURAL_BLOCKER_CODES
    for code in sorted(contracted):
        world = _amended_middle_world()
        world.findings = (
            TrainFinding(kind=FindingKind.BLOCKER, code=code, message=f"boom {code}"),
        )
        error = _sync_error(world)
        assert error.error_type == "claimed_prefix_malformed", code
        assert code in str(error)
        world.assert_nothing_journaled()
        assert world.worktrees_added == [], code


# ----------------------------------------------------------------- resume payload strictness


def test_resume_inconsistent_base_payload_rows_fail_closed():
    # before.base and after.base_parent must be mutually consistent — an unvalidated
    # base_parent would be persisted verbatim as the bottom layer's parent checkpoint —
    # and a shape-valid capture must still BIND to the fresh train's base branch (a
    # stale/crafted capture under an unrelated branch name never supplies the checkpoint).
    good = _record()
    rows: list[dict] = [
        # A stray base_parent with no captured base.
        {"after": {**dict(good.after), "base_parent": "z" * 40}},
        # A captured base whose sha disagrees with base_parent.
        {
            "before": {**dict(good.before), "base": {"branch": "main", "sha": "y" * 40}},
            "after": {**dict(good.after), "base_parent": "z" * 40},
        },
        # A captured base with base_parent missing/null.
        {"before": {**dict(good.before), "base": {"branch": "main", "sha": NEWBASE}}},
        # A malformed base capture (no sha).
        {
            "before": {**dict(good.before), "base": {"branch": "main"}},
            "after": {**dict(good.after), "base_parent": NEWBASE},
        },
        # A shape-valid capture under the wrong branch — the train's base is "main".
        {
            "before": {**dict(good.before), "base": {"branch": "not-main", "sha": NEWBASE}},
            "after": {**dict(good.after), "base_parent": NEWBASE},
        },
    ]
    for overrides in rows:
        record = _record(**overrides)
        world = _resume_world(record)
        world.remote.update({"plan-102": C2, "plan-103": R3})  # even a landed push: no resume
        error = _sync_error(world)
        assert error.error_type == "sync_drift", overrides
        assert "base payload" in str(error)
        assert world.persistence.outcomes == [] and world.persistence.checkpoints == []
        assert world.persistence.unresolved_records


def test_resume_malformed_stack_payload_rows_fail_closed():
    # The recorded membership drives roll-forward verification: a silently-degraded shape
    # would skip the native-stack check entirely.
    good = _record()
    rows: list[object] = [
        {"members": "junk"},  # non-list members
        {"members": [201, "x", 203]},  # non-int member
        {"members": []},  # empty members
        {},  # mapping without members
        "junk",  # non-mapping stack
    ]
    for stack in rows:
        record = _record(before={**dict(good.before), "stack": stack})
        world = _resume_world(record)
        error = _sync_error(world)
        assert error.error_type == "sync_drift", stack
        assert "stack payload" in str(error)
        assert world.persistence.outcomes == [] and world.persistence.checkpoints == []


def test_resume_null_stack_for_a_multi_layer_cascade_is_sync_drift():
    good = _record()
    record = _record(before={**dict(good.before), "stack": None})
    world = _resume_world(record)
    error = _sync_error(world)
    assert error.error_type == "sync_drift"
    assert "multi-layer cascade" in str(error)


def test_resume_membership_not_ending_with_the_affected_run_is_sync_drift():
    # A recorded membership unrelated to the affected suffix would verify a stack that has
    # nothing to do with what roll-forward is about to checkpoint.
    good = _record()
    record = _record(before={**dict(good.before), "stack": {"members": [202, 203, 999]}})
    world = _resume_world(record)
    error = _sync_error(world)
    assert error.error_type == "sync_drift"
    assert "recorded membership" in str(error)


# ----------------------------------------------------------------- manifest-write failure


def test_conflict_with_failed_manifest_write_stays_typed_and_cleans():
    # The conflict arm's retention WRITE fails (disk/permissions): the guard stays armed —
    # residue cleaned — and the failure stays inside the typed boundary; nothing journaled.
    world = _amended_middle_world()
    world.rebase_conflicts.add((P3, C2))

    def boom(root: Path, manifest: continuation.ContinuationManifest) -> Path:
        raise OSError("read-only filesystem")

    world.manifest_write_override = boom
    error = _sync_error(world)
    assert error.error_type == "rebase_conflict"
    # The load-bearing §8.49 freshness token (see corroborateSyncConflict): every
    # rebase_conflict arm names the layer whose rebase actually stopped.
    assert "for layer 1.3 " in str(error)
    assert "could not be written" in str(error) and "NOT retained" in str(error)
    # Deliberately no warm-route hint: retention failed, so there is nothing for automated
    # resolution to resolve — the remedy is the filesystem.
    assert "/objective-sync" not in str(error)
    assert world.manifests == {}
    world.assert_nothing_journaled()
    world.assert_guard_cleaned()  # guard NOT disarmed: temp refs + worktree removed


# ----------------------------------------------------------------- the operation lock


def test_busy_lock_is_operation_in_progress_for_every_mutating_entry():
    for drive in ("sync", "continue", "abort"):
        world = _amended_middle_world()
        world.lock_busy = True
        with pytest.raises(sync.SyncError) as excinfo:
            if drive == "sync":
                world.sync()
            elif drive == "continue":
                world.continue_sync()
            else:
                world.abort_sync()
        assert excinfo.value.error_type == "operation_in_progress", drive
        world.assert_nothing_journaled()
        assert world.timeline == []  # refused before ANY observation or mutation


def test_lock_is_held_for_the_full_operation_and_released():
    world = _amended_middle_world()
    world.sync()
    assert world.lock_events == ["acquired", "released"]


# ----------------------------------------------------------------- cleanup prune ordering


def test_cleanup_prunes_after_worktree_remove_on_every_arm():
    arms: list[tuple[str, Callable[[_World], dict]]] = [
        ("success", lambda w: {}),
        ("declined", lambda w: {"approve": lambda c: False}),
        ("dry_run", lambda w: {"dry_run": True}),
    ]
    for name, make_kwargs in arms:
        world = _amended_middle_world()
        world.sync(**make_kwargs(world))
        kinds = [t[0] for t in world.timeline]
        assert "worktree_prune" in kinds, name
        assert kinds.index("worktree_remove") < kinds.index("worktree_prune"), name


# ----------------------------------------------------------------- --dry-run


def test_dry_run_stops_at_the_approval_boundary():
    world = _amended_middle_world()
    approvals: list[SyncResult.Cascade] = []
    result = world.sync(dry_run=True, approve=lambda c: approvals.append(c) or True)
    assert result.dry_run is True and result.no_op is False
    assert result.operation_id is None and result.declined is False
    # The full cascade was computed and reported…
    assert [(s.node_id, s.before_sha, s.after_sha) for s in result.affected] == [
        ("1.2", P2, C2),
        ("1.3", P3, R3),
    ]
    # …but nothing effectful followed: no approval, no journal record, no push.
    assert approvals == []
    world.assert_nothing_journaled()
    assert world.events("push_atomic") == []
    assert world.remote["plan-102"] == P2 and world.remote["plan-103"] == P3
    world.assert_guard_cleaned()
    assert result.notes == ()


def test_dry_run_composes_with_the_no_op_arm():
    world = _three_layer_world()
    result = world.sync(dry_run=True)
    assert result.no_op is True and result.dry_run is True
    world.assert_nothing_journaled()


def test_dry_run_conflict_retains_nothing():
    world = _amended_middle_world()
    world.rebase_conflicts.add((P3, C2))
    error = _sync_error(world, dry_run=True)
    assert error.error_type == "rebase_conflict"
    assert "dry-run preview" in str(error) and "nothing was retained" in str(error)
    # Deliberately no warm-route hint: nothing is retained, so automated resolution
    # cannot fire here.
    assert "/objective-sync" not in str(error)
    assert world.manifests == {}  # NO manifest write
    world.assert_nothing_journaled()
    world.assert_guard_cleaned()  # the guard stayed armed


def test_dry_run_never_resumes_and_names_the_kind_aware_hint():
    resumable = _record()
    world = _resume_world(resumable)
    error = _sync_error(world, dry_run=True)
    assert error.error_type == "unresolved_operation"
    assert "a real sync would resume it" in str(error)
    world.assert_nothing_journaled()

    foreign = _record(operation_kind=OperationKind.TRANSFER)
    world = _resume_world(foreign)
    error = _sync_error(world, dry_run=True)
    assert error.error_type == "unresolved_operation"
    assert "perk objective stack recover" in str(error)


def test_dry_run_still_gates_on_a_pending_manifest():
    world = _amended_middle_world()
    world.pending_unparseable = True
    error = _sync_error(world, dry_run=True)
    assert error.error_type == "sync_conflict_pending"


# ----------------------------------------------------------------- --adopt


A2 = "e" * 40  # layer 1.2's out-of-band remote edit
A3 = "f" * 40  # layer 1.3's out-of-band remote edit
R3A = _reb(P3, A2)  # layer 1.3's transplant onto the adopted A2


def _adopt_middle_world() -> _World:
    """Layer 1.2's branch was edited out-of-band on the remote (P2 → A2); nothing local."""
    world = _three_layer_world()
    world.remote["plan-102"] = A2
    world.ancestry.add((P1, A2))  # the adopted head still contains the stored parent edge
    return world


def test_adopt_middle_layer_cascades_with_the_remote_head_as_source():
    world = _adopt_middle_world()
    result = world.sync(adopt_node="1.2")
    assert result.adopted_node == "1.2" and result.no_op is False
    assert [(s.node_id, s.before_sha, s.after_sha) for s in result.affected] == [
        ("1.2", A2, A2),  # the adopted layer: before IS the observed head (its lease)
        ("1.3", P3, R3A),
    ]
    # Decision 16: the adopted no-op ref (candidate == observed before) is EXCLUDED from
    # the atomic push argv; the moved successor is pushed under its exact lease.
    assert world.events("push_atomic") == [("push_atomic", (("plan-103", P3, R3A),))]
    # Its checkpoint pair is still written: published_head_sha = the adopted head.
    assert world.persistence.checkpoints == [("102", P1, A2), ("103", A2, R3A)]
    record = world.persistence.prepared[0]
    assert record.operation_kind is OperationKind.ADOPT
    assert record.after["adopted"] == {"node_id": "1.2", "plan_id": "102", "remote_head": A2}
    # The record documents the FULL affected set, including the unpushed adopted ref.
    assert record.before["branches"] == [
        {"ref": "plan-102", "sha": A2},
        {"ref": "plan-103", "sha": P3},
    ]
    assert record.after["branches"] == [
        {"ref": "plan-102", "sha": A2},
        {"ref": "plan-103", "sha": R3A},
    ]
    world.assert_guard_cleaned()


def test_adopt_record_round_trips_the_strict_journal_envelope():
    world = _adopt_middle_world()
    world.sync(adopt_node="1.2")
    record = world.persistence.prepared[0]
    # The kind-owned `after.adopted` mapping rides INSIDE the opaque payload: the strict v1
    # envelope (extra="forbid" at the top level) accepts it unchanged.
    import yaml

    from perk.delivery.journal import PreparedRecordModel

    raw = yaml.safe_load(canonical_payload(record))
    round_tripped = PreparedRecordModel.model_validate(raw).to_domain()
    assert round_tripped == record


def test_top_layer_adoption_is_checkpoint_only_with_an_empty_push_set():
    world = _three_layer_world()
    world.remote["plan-103"] = A3
    world.ancestry.add((P2, A3))
    result = world.sync(adopt_node="1.3")
    assert result.adopted_node == "1.3"
    assert [(s.node_id, s.before_sha, s.after_sha) for s in result.affected] == [("1.3", A3, A3)]
    assert world.events("push_atomic") == []  # nothing to push: a pure reconciliation…
    assert world.persistence.checkpoints == [("103", P2, A3)]  # …that still checkpoints
    record = world.persistence.prepared[0]  # …and journals the accepted head durably
    assert record.operation_kind is OperationKind.ADOPT
    assert world.persistence.outcomes[-1].role is EventRole.COMPLETED


def test_declined_adoption_still_echoes_the_adopted_node():
    # The declined arm carries adopted_node like every other returning arm — a consumer can
    # tell WHAT was declined without re-deriving it from the request.
    world = _adopt_middle_world()
    result = world.sync(adopt_node="1.2", approve=lambda cascade: False)
    assert result.declined is True and result.adopted_node == "1.2"
    world.assert_nothing_journaled()


def test_adopt_unclaimed_node_is_invalid_input_naming_the_claimed_ids():
    world = _adopt_middle_world()
    error = _sync_error(world, adopt_node="9.9")
    assert error.error_type == "invalid_input"
    assert "1.1, 1.2, 1.3" in str(error)


def test_adopt_blocked_reasons():
    # (i) nothing to adopt: the branch sits exactly at its checkpoint.
    world = _three_layer_world()
    error = _sync_error(world, adopt_node="1.2")
    assert error.error_type == "adopt_blocked" and "nothing to adopt" in str(error)

    # (ii) no remote head at all.
    world = _three_layer_world()
    world.remote["plan-102"] = None
    error = _sync_error(world, adopt_node="1.2")
    assert error.error_type == "adopt_blocked" and "no remote head" in str(error)

    # (iii) the adopted layer is ALSO locally changed — an ambiguous source.
    world = _adopt_middle_world()
    world.local["plan-102"] = C2
    world.ancestry.add((P1, C2))
    error = _sync_error(world, adopt_node="1.2")
    assert error.error_type == "adopt_blocked" and "ambiguous source" in str(error)

    # (iv) the remote edit rewrote ancestry: the head no longer contains the parent edge.
    world = _three_layer_world()
    world.remote["plan-102"] = A2  # no (P1, A2) ancestry seeded
    error = _sync_error(world, adopt_node="1.2")
    assert error.error_type == "adopt_blocked" and "rewrote the layer's ancestry" in str(error)


def test_adopt_with_another_drifted_layer_is_still_remote_drift():
    world = _adopt_middle_world()
    world.remote["plan-103"] = "9" * 40  # a non-adopted layer drifted too
    error = _sync_error(world, adopt_node="1.2")
    assert error.error_type == "remote_drift"
    assert "plan-103" in str(error)
    world.assert_nothing_journaled()


def test_adopt_with_base_is_refused_at_the_request_boundary():
    world = _adopt_middle_world()
    with pytest.raises(ValueError, match="mutually exclusive"):
        world.sync(adopt_node="1.2", include_base=True)
    assert world.timeline == []  # refused before the lock/observations


def test_adopt_composes_with_dry_run():
    world = _adopt_middle_world()
    result = world.sync(adopt_node="1.2", dry_run=True)
    assert result.dry_run is True and result.adopted_node == "1.2"
    assert [(s.before_sha, s.after_sha) for s in result.affected] == [(A2, A2), (P3, R3A)]
    world.assert_nothing_journaled()
    assert world.events("push_atomic") == []
    world.assert_guard_cleaned()


def _adopt_record() -> PreparedRecord:
    return _record(
        operation_kind=OperationKind.ADOPT,
        before={
            "base": None,
            "branches": [{"ref": "plan-102", "sha": A2}, {"ref": "plan-103", "sha": P3}],
            "prs": [
                {"number": 202, "head_sha": A2, "base": "plan-101"},
                {"number": 203, "head_sha": P3, "base": "plan-102"},
            ],
            "stack": {"members": [201, 202, 203]},
        },
        after={
            "branches": [{"ref": "plan-102", "sha": A2}, {"ref": "plan-103", "sha": R3A}],
            "prs": [
                {"number": 202, "head_sha": A2, "base": "plan-101"},
                {"number": 203, "head_sha": R3A, "base": "plan-102"},
            ],
            "base_parent": None,
            "adopted": {"node_id": "1.2", "plan_id": "102", "remote_head": A2},
        },
    )


def test_resume_adopt_all_after_rolls_forward_record_driven():
    record = _adopt_record()
    world = _three_layer_world()
    world.persistence.unresolved_records[record.operation_id] = record
    world.remote.update({"plan-102": A2, "plan-103": R3A})
    result = world.sync()  # a PLAIN sync resumes an unresolved ADOPT identically
    assert result.resumed is True and result.operation_id == record.operation_id
    assert result.adopted_node == "1.2"  # record-driven, not flag-driven
    assert world.persistence.checkpoints == [("102", P1, A2), ("103", A2, R3A)]
    assert world.persistence.outcomes[-1].role is EventRole.COMPLETED


def test_resume_adopt_all_before_abandons_then_fresh_takes_the_invocation_flags():
    record = _adopt_record()
    world = _adopt_middle_world()  # remote back at the before set (A2 / P3)
    world.persistence.unresolved_records[record.operation_id] = record
    result = world.sync(adopt_node="1.2")
    assert result.abandoned_operation_id == record.operation_id
    assert result.operation_id is not None and result.operation_id != record.operation_id
    assert result.adopted_node == "1.2"  # the FRESH preparation carried the adopt flag
    roles = [outcome.role for outcome in world.persistence.outcomes]
    assert roles == [EventRole.ABANDONED, EventRole.COMPLETED]
    assert world.persistence.prepared[0].operation_kind is OperationKind.ADOPT


def test_adopt_flag_routing_is_flag_independent_for_an_unresolved_sync():
    record = _record()  # a plain SYNC record
    world = _resume_world(record)
    world.remote.update({"plan-102": C2, "plan-103": R3})  # all-after
    result = world.sync(adopt_node="1.2")  # the adopt invocation still resumes normally
    assert result.resumed is True and result.operation_id == record.operation_id
    assert result.adopted_node is None  # record-driven: the SYNC record adopted nothing


def test_resume_adopt_record_with_malformed_adopted_payload_is_sync_drift():
    good = _adopt_record()
    record = _record(
        operation_kind=OperationKind.ADOPT,
        before=dict(good.before),
        after={**dict(good.after), "adopted": {"node_id": "1.2"}},  # missing fields
    )
    world = _three_layer_world()
    world.persistence.unresolved_records[record.operation_id] = record
    world.remote.update({"plan-102": A2, "plan-103": R3A})
    error = _sync_error(world)
    assert error.error_type == "sync_drift"
    assert "adopted" in str(error)


# ----------------------------------------------------------------- --continue


OP = mint_operation_id()  # a canonical ULID: the retained operation's identity
WT = str((WT_ROOT / f"sync-{OP}").resolve())
MRUN = "01MANIFESTRUN"


def _retained_manifest(**overrides) -> continuation.ContinuationManifest:
    """The manifest a conflicted `_amended_middle_world` cascade retains: 1.2's candidate
    (the fast-path C2) completed, 1.3's transplant onto it conflicted."""
    base = continuation.ContinuationManifest(
        operation_id=OP,
        objective_id=OBJECTIVE,
        delivery_lineage=LINEAGE,
        run_id=MRUN,
        include_base=False,
        captured_base_head=None,
        layers=(
            continuation.ContinuationLayer(
                node_id="1.2",
                plan_id="102",
                branch="plan-102",
                before_sha=P2,
                old_parent_edge=P1,
                source_sha=C2,
                new_parent_edge=P1,
                candidate_temp_ref=f"refs/perk/sync/{OP}/plan-102",
                candidate_sha=C2,
            ),
            continuation.ContinuationLayer(
                node_id="1.3",
                plan_id="103",
                branch="plan-103",
                before_sha=P3,
                old_parent_edge=P2,
                source_sha=P3,
                new_parent_edge=C2,
                candidate_temp_ref=f"refs/perk/sync/{OP}/plan-103",
                candidate_sha=None,
            ),
        ),
        conflict_node_id="1.3",
        worktree_path=WT,
        created="2026-01-01T00:00:00Z",
        adopted_node=None,
    )
    return dataclasses_replace(base, **overrides)


def _retained_world(manifest: continuation.ContinuationManifest | None = None) -> _World:
    """The world a continue re-enters: the manifest present, the completed candidate's temp
    ref live, the retained worktree existing with the human-resolved rebase at its HEAD."""
    world = _amended_middle_world()
    manifest = manifest if manifest is not None else _retained_manifest()
    world.manifests[manifest.delivery_lineage] = manifest
    world.refs[f"refs/perk/sync/{OP}/plan-102"] = C2
    world.existing_paths.add(WT)
    world.worktree_heads[WT] = R3  # the human finished the rebase: HEAD is 1.3's candidate
    return world


def _continue_error(world: _World, **kwargs) -> sync.SyncError:
    with pytest.raises(sync.SyncError) as excinfo:
        world.continue_sync(**kwargs)
    return excinfo.value


def test_continue_completes_under_the_manifest_identity():
    world = _retained_world()
    result = world.continue_sync()
    assert result.continued is True and result.declined is False
    assert result.operation_id == OP  # the MANIFEST's operation, not a fresh mint
    assert [(s.node_id, s.before_sha, s.after_sha) for s in result.affected] == [
        ("1.2", P2, C2),
        ("1.3", P3, R3),
    ]
    record = world.persistence.prepared[0]
    assert record.operation_id == OP and record.run_id == MRUN  # the manifest's identity
    assert record.operation_kind is OperationKind.SYNC
    assert world.remote["plan-102"] == C2 and world.remote["plan-103"] == R3
    assert world.persistence.checkpoints == [("102", P1, C2), ("103", C2, R3)]
    assert world.persistence.outcomes[-1].role is EventRole.COMPLETED
    # The manifest retired at prepared-append: after `prepared`, before the push.
    kinds = [t[0] for t in world.timeline]
    assert kinds.index("prepared") < kinds.index("manifest_clear") < kinds.index("push_atomic")
    assert world.manifests == {} and world.cleared_manifests == [LINEAGE]
    # The retained residue is cleaned on exit (the journal owns the operation now).
    assert world.refs == {} and WT in {str(p) for p in world.worktrees_removed}


def test_continue_missing_manifest_is_no_continuation():
    world = _amended_middle_world()
    error = _continue_error(world)
    assert error.error_type == "no_continuation"
    assert "nothing to continue" in str(error)


def test_continue_unparseable_manifest_directs_to_abort():
    world = _retained_world()
    world.pending_unparseable = True
    error = _continue_error(world)
    assert error.error_type == "continuation_invalid"
    assert "--abort" in str(error)
    world.assert_nothing_journaled()


def test_continue_hostile_manifest_fields_are_continuation_invalid_and_non_destructive():
    hostile: list[continuation.ContinuationManifest] = [
        _retained_manifest(operation_id="not-a-ulid"),
        _retained_manifest(worktree_path="/etc/passwd"),
        _retained_manifest(worktree_path=f"/wt/../etc/sync-{OP}"),
        _retained_manifest(
            layers=(
                continuation.ContinuationLayer(
                    node_id="1.2",
                    plan_id="102",
                    branch="plan-102",
                    before_sha=P2,
                    old_parent_edge=P1,
                    source_sha=C2,
                    new_parent_edge=P1,
                    candidate_temp_ref="refs/heads/main",  # outside the operation namespace
                    candidate_sha=C2,
                ),
            )
        ),
    ]
    for manifest in hostile:
        world = _retained_world(manifest)
        error = _continue_error(world)
        assert error.error_type == "continuation_invalid"
        assert "nothing was deleted" in str(error)
        assert world.worktrees_removed == [] and world.cleared_manifests == []
        assert world.manifests[LINEAGE] is manifest  # retained untouched
        world.assert_nothing_journaled()


def test_continue_identity_mismatch_is_continuation_invalid():
    world = _retained_world(_retained_manifest(objective_id="777"))
    error = _continue_error(world)
    assert error.error_type == "continuation_invalid"
    assert "777" in str(error)
    world.assert_nothing_journaled()


def test_continue_refuses_while_the_rebase_is_still_in_progress():
    world = _retained_world()
    world.rebase_active = True
    error = _continue_error(world)
    assert error.error_type == "rebase_in_progress"
    assert f"git -C {WT} rebase --continue" in str(error)
    # Everything retained: the manifest, the worktree, the temp refs.
    assert world.manifests[LINEAGE] is not None and world.refs != {}
    assert world.worktrees_removed == []
    world.assert_nothing_journaled()


def test_continue_stale_arms_retain_everything():
    def missing_worktree(world: _World) -> None:
        world.existing_paths.clear()

    def missing_temp_ref(world: _World) -> None:
        world.refs.clear()

    def dirty_after_rebase(world: _World) -> None:
        world.worktree_is_dirty = True

    def moved_remote(world: _World) -> None:
        world.remote["plan-103"] = "9" * 40

    def unresolvable_head(world: _World) -> None:
        world.worktree_heads.clear()

    for name, mutate in [
        ("missing worktree", missing_worktree),
        ("missing temp ref", missing_temp_ref),
        ("dirty after rebase", dirty_after_rebase),
        ("moved remote", moved_remote),
        ("unresolvable HEAD", unresolvable_head),
    ]:
        world = _retained_world()
        mutate(world)
        error = _continue_error(world)
        assert error.error_type == "continuation_stale", name
        assert "--abort" in str(error), name
        assert world.manifests.get(LINEAGE) is not None, name  # manifest retained
        assert world.worktrees_removed == [], name
        world.assert_nothing_journaled()


def test_continue_captured_before_disagreeing_with_the_checkpoint_is_stale():
    manifest = _retained_manifest()
    bad = dataclasses_replace(
        manifest,
        layers=(
            dataclasses_replace(manifest.layers[0], before_sha="9" * 40),
            manifest.layers[1],
        ),
    )
    world = _retained_world(bad)
    error = _continue_error(world)
    assert error.error_type == "continuation_stale"
    world.assert_nothing_journaled()


def test_continue_manifest_layer_no_longer_claimed_is_stale():
    manifest = _retained_manifest(
        layers=(
            dataclasses_replace(_retained_manifest().layers[0], node_id="8.8"),
            _retained_manifest().layers[1],
        )
    )
    world = _retained_world(manifest)
    error = _continue_error(world)
    assert error.error_type == "continuation_stale"
    assert "8.8" in str(error)


def test_continue_manifest_not_the_top_suffix_is_stale():
    # Only the bottom claimed layer: the affected set must be the contiguous TOP suffix.
    manifest = _retained_manifest(
        layers=(
            continuation.ContinuationLayer(
                node_id="1.1",
                plan_id="101",
                branch="plan-101",
                before_sha=P1,
                old_parent_edge=MAIN,
                source_sha=P1,
                new_parent_edge=MAIN,
                candidate_temp_ref=f"refs/perk/sync/{OP}/plan-101",
                candidate_sha=P1,
            ),
        ),
        conflict_node_id="1.1",
    )
    world = _retained_world(manifest)
    world.refs[f"refs/perk/sync/{OP}/plan-101"] = P1
    error = _continue_error(world)
    assert error.error_type == "continuation_stale"
    assert "top suffix" in str(error)


def test_continue_declined_retains_a_fully_computed_manifest_then_reenters():
    world = _retained_world()
    declined = world.continue_sync(approve=lambda c: False)
    assert declined.continued is True and declined.declined is True
    assert declined.operation_id is None
    world.assert_nothing_journaled()
    # The manifest now carries EVERY candidate (the durable approval-ready state)…
    manifest = world.manifests[LINEAGE]
    assert [layer.candidate_sha for layer in manifest.layers] == [C2, R3]
    # …and the residue is retained.
    assert world.worktrees_removed == [] and world.refs != {}

    # Re-entry lands at the approval gate: no rebase work, straight to completion.
    seen: list[SyncResult.Cascade] = []
    result = world.continue_sync(approve=lambda c: seen.append(c) or True)
    assert result.operation_id == OP
    (cascade,) = seen
    assert [(s.before_sha, s.after_sha) for s in cascade.layers] == [(P2, C2), (P3, R3)]
    assert world.events("rebase") == []  # never recomputed
    assert world.persistence.outcomes[-1].role is EventRole.COMPLETED


def test_continue_rewrites_the_manifest_after_every_candidate():
    # A base-cascade stop at 1.2 with 1.3 unreached: continue must capture 1.2's candidate,
    # rewrite, then compute 1.3's and rewrite again.
    r1 = _reb(P1, NEWBASE)
    x2 = "x" * 40  # the human-resolved candidate for 1.2 (the retained worktree's HEAD)
    manifest = _retained_manifest(
        include_base=True,
        captured_base_head=NEWBASE,
        conflict_node_id="1.2",
        layers=(
            continuation.ContinuationLayer(
                node_id="1.1",
                plan_id="101",
                branch="plan-101",
                before_sha=P1,
                old_parent_edge=MAIN,
                source_sha=P1,
                new_parent_edge=NEWBASE,
                candidate_temp_ref=f"refs/perk/sync/{OP}/plan-101",
                candidate_sha=r1,
            ),
            continuation.ContinuationLayer(
                node_id="1.2",
                plan_id="102",
                branch="plan-102",
                before_sha=P2,
                old_parent_edge=P1,
                source_sha=P2,
                new_parent_edge=r1,
                candidate_temp_ref=f"refs/perk/sync/{OP}/plan-102",
                candidate_sha=None,
            ),
            continuation.ContinuationLayer(
                node_id="1.3",
                plan_id="103",
                branch="plan-103",
                before_sha=P3,
                old_parent_edge=P2,
                source_sha=P3,
                new_parent_edge=None,
                candidate_temp_ref=f"refs/perk/sync/{OP}/plan-103",
                candidate_sha=None,
            ),
        ),
    )
    world = _three_layer_world()
    world.base_head = NEWBASE
    world.remote["main"] = NEWBASE
    world.manifests[LINEAGE] = manifest
    world.refs[f"refs/perk/sync/{OP}/plan-101"] = r1
    world.existing_paths.add(WT)
    world.worktree_heads[WT] = x2
    world.ancestry.add((r1, x2))  # the resolved HEAD contains the recorded new parent
    r3x = _reb(P3, x2)
    result = world.continue_sync()
    assert result.operation_id == OP and result.base_cascaded is True
    assert [(s.before_sha, s.after_sha) for s in result.affected] == [
        (P1, r1),
        (P2, x2),
        (P3, r3x),
    ]
    # Exactly one rebase remained (1.3's transplant onto the resolved x2).
    assert world.events("rebase") == [("rebase", P3, x2, P2)]
    # The manifest was rewritten after EACH captured candidate: once for the pending layer,
    # once for the freshly computed 1.3 — then retired.
    assert world.events("manifest_write") == [
        ("manifest_write", LINEAGE),
        ("manifest_write", LINEAGE),
    ]
    assert world.manifests == {}
    # Checkpoints restore the record-derived parent edges (base cascade arithmetic).
    assert world.persistence.checkpoints == [
        ("101", NEWBASE, r1),
        ("102", r1, x2),
        ("103", x2, r3x),
    ]


def test_continue_base_capture_disagreeing_with_fresh_base_is_stale():
    manifest = _retained_manifest(include_base=True, captured_base_head=NEWBASE)
    world = _retained_world(manifest)  # world.base_head is still MAIN
    error = _continue_error(world)
    assert error.error_type == "continuation_stale"
    assert NEWBASE in str(error)


def test_continue_new_higher_conflict_rewrites_the_manifest_same_operation():
    r1 = _reb(P1, NEWBASE)
    x2 = "x" * 40
    manifest = _retained_manifest(
        include_base=True,
        captured_base_head=NEWBASE,
        conflict_node_id="1.2",
        layers=(
            continuation.ContinuationLayer(
                node_id="1.1",
                plan_id="101",
                branch="plan-101",
                before_sha=P1,
                old_parent_edge=MAIN,
                source_sha=P1,
                new_parent_edge=NEWBASE,
                candidate_temp_ref=f"refs/perk/sync/{OP}/plan-101",
                candidate_sha=r1,
            ),
            continuation.ContinuationLayer(
                node_id="1.2",
                plan_id="102",
                branch="plan-102",
                before_sha=P2,
                old_parent_edge=P1,
                source_sha=P2,
                new_parent_edge=r1,
                candidate_temp_ref=f"refs/perk/sync/{OP}/plan-102",
                candidate_sha=None,
            ),
            continuation.ContinuationLayer(
                node_id="1.3",
                plan_id="103",
                branch="plan-103",
                before_sha=P3,
                old_parent_edge=P2,
                source_sha=P3,
                new_parent_edge=None,
                candidate_temp_ref=f"refs/perk/sync/{OP}/plan-103",
                candidate_sha=None,
            ),
        ),
    )
    world = _three_layer_world()
    world.base_head = NEWBASE
    world.remote["main"] = NEWBASE
    world.manifests[LINEAGE] = manifest
    world.refs[f"refs/perk/sync/{OP}/plan-101"] = r1
    world.existing_paths.add(WT)
    world.worktree_heads[WT] = x2
    world.ancestry.add((r1, x2))  # the resolved HEAD contains the recorded new parent
    world.rebase_conflicts.add((P3, x2))  # the NEXT layer's transplant now conflicts
    # The request carries an ALIAS id: the hint must interpolate the redirect-resolved
    # train id, never the raw request id.
    error = _continue_error(world, objective_id="REQUEST-ALIAS")
    assert error.error_type == "rebase_conflict"
    assert "1.3" in str(error) and OP in str(error)
    # The load-bearing §8.49 freshness token (see corroborateSyncConflict): the rewritten
    # manifest and the message agree on the NEW conflict layer here.
    assert "for layer 1.3 " in str(error)
    # Cross-plane lockstep: the appended warm-route sentence names the warm command id
    # registered in extension/pi/v1/delivery/stackSync.ts and the landed consent posture
    # ("on your approval") — with the TRAIN's projection id, not the request alias.
    assert "`/objective-sync 500`" in str(error)
    assert "REQUEST-ALIAS" not in str(error)
    rewritten = world.manifests[LINEAGE]
    assert rewritten.operation_id == OP  # same operation, progress retained
    assert rewritten.conflict_node_id == "1.3"
    assert [layer.candidate_sha for layer in rewritten.layers] == [r1, x2, None]
    assert rewritten.layers[2].new_parent_edge == x2
    # Residue retained for the next continue.
    assert world.worktrees_removed == []
    world.assert_nothing_journaled()


def test_continue_post_prepare_failure_leaves_the_operation_unresolved_without_a_manifest():
    world = _retained_world()
    world.push_reject = True
    world.push_reject_leaves = {"plan-103": "9" * 40}  # a mixed observation: fail closed
    error = _continue_error(world)
    assert error.error_type == "sync_drift"
    # The prepared record stays unresolved; the manifest was already retired.
    assert world.persistence.unresolved_records and world.manifests == {}
    # A second --continue finds no manifest: recovery routes through sync/recover.
    error = _continue_error(world)
    assert error.error_type == "no_continuation"


def test_continue_reobservation_drift_retains_the_manifest():
    world = _retained_world()

    def approve(cascade: SyncResult.Cascade) -> bool:
        world.remote["plan-103"] = "9" * 40  # the world moves during the approval pause
        return True

    error = _continue_error(world, approve=approve)
    assert error.error_type == "remote_drift"
    # Pre-journal: nothing appended, manifest + residue retained (still continuable).
    world.assert_nothing_journaled()
    assert world.manifests.get(LINEAGE) is not None
    assert world.worktrees_removed == []


def test_continue_manifest_retirement_failure_is_a_loud_note_never_a_refusal():
    world = _retained_world()
    world.manifest_clear_boom = OSError("EACCES")
    result = world.continue_sync()
    assert result.operation_id == OP
    assert any("could not retire the continuation manifest" in note for note in result.notes)
    assert world.persistence.outcomes[-1].role is EventRole.COMPLETED


def test_continue_adopt_manifest_journals_adopt_with_the_captured_head():
    # An ADOPT cascade's conflict stop: the adopted layer 1.2's before IS the observed head.
    manifest = _retained_manifest(
        adopted_node="1.2",
        layers=(
            dataclasses_replace(
                _retained_manifest().layers[0], before_sha=A2, source_sha=A2, candidate_sha=A2
            ),
            dataclasses_replace(_retained_manifest().layers[1], new_parent_edge=A2),
        ),
    )
    world = _three_layer_world()
    world.remote["plan-102"] = A2  # the out-of-band head still stands
    world.manifests[LINEAGE] = manifest
    world.refs[f"refs/perk/sync/{OP}/plan-102"] = A2
    world.existing_paths.add(WT)
    world.worktree_heads[WT] = R3A
    result = world.continue_sync()
    assert result.operation_id == OP and result.adopted_node == "1.2"
    record = world.persistence.prepared[0]
    assert record.operation_kind is OperationKind.ADOPT
    assert record.after["adopted"] == {"node_id": "1.2", "plan_id": "102", "remote_head": A2}
    # Push-set rule: the adopted no-op ref is excluded; the successor pushes.
    assert world.events("push_atomic") == [("push_atomic", (("plan-103", P3, R3A),))]
    assert world.persistence.checkpoints == [("102", P1, A2), ("103", A2, R3A)]


# ----------------------------------------------------------------- --abort


def _abort_error(world: _World, **kwargs) -> sync.SyncError:
    with pytest.raises(sync.SyncError) as excinfo:
        world.abort_sync(**kwargs)
    return excinfo.value


def test_abort_valid_manifest_discards_the_full_residue():
    world = _retained_world()
    world.refs["refs/perk/sync/01OTHEROP/plan-999"] = "z" * 40  # a foreign op's ref survives
    previews: list[SyncResult.AbortPreview] = []
    result = world.abort_sync(approve=lambda p: previews.append(p) or True)
    assert result.aborted is True and result.declined is False
    assert result.operation_id is None  # nothing journaled by an abort
    (preview,) = previews
    assert preview.parseable is True and preview.contained is True
    assert preview.operation_id == OP and preview.conflict_node_id == "1.3"
    assert preview.worktree_path == WT
    assert [str(p) for p in world.worktrees_removed] == [WT]
    assert world.pruned != []
    assert world.refs == {"refs/perk/sync/01OTHEROP/plan-999": "z" * 40}
    assert world.manifests == {} and world.cleared_manifests == [LINEAGE]
    world.assert_nothing_journaled()


def test_abort_worktree_remove_failure_is_a_loud_residue_note():
    world = _retained_world()
    world.worktree_remove_boom = git.GitError("worktree busy")
    result = world.abort_sync(approve=lambda p: True)
    assert result.aborted is True and world.manifests == {}
    assert any("could not remove the isolated worktree" in note for note in result.notes)
    assert any("manifest retired despite incomplete cleanup" in note for note in result.notes)
    assert any("perk objective stack recover" in note for note in result.notes)
    world.assert_nothing_journaled()


def test_abort_ref_delete_failure_is_a_loud_residue_note():
    world = _retained_world()
    surviving = f"refs/perk/sync/{OP}/plan-102"
    world.delete_ref_boom.add(surviving)
    result = world.abort_sync(approve=lambda p: True)
    assert result.aborted is True and world.manifests == {}
    assert surviving in world.refs
    assert any(surviving in note and "could not delete" in note for note in result.notes)
    assert any("perk objective stack recover" in note for note in result.notes)
    world.assert_nothing_journaled()


def test_abort_prune_failure_is_a_loud_residue_note():
    world = _retained_world()
    world.worktree_prune_boom = OSError("EACCES")
    result = world.abort_sync(approve=lambda p: True)
    assert result.aborted is True and world.manifests == {}
    assert any("could not prune the worktree records" in note for note in result.notes)
    assert any("perk objective stack recover" in note for note in result.notes)
    world.assert_nothing_journaled()


def test_abort_manifest_clear_failure_is_typed_and_keeps_the_manifest_authoritative():
    world = _retained_world()
    world.manifest_clear_boom = OSError("EACCES")
    error = _abort_error(world, approve=lambda p: True)
    assert error.error_type == "git_error"
    assert "manifest remains authoritative" in str(error)
    assert "Cleanup report" in str(error)
    assert world.manifests.get(LINEAGE) is not None
    world.assert_nothing_journaled()


def test_abort_declined_deletes_nothing():
    world = _retained_world()
    result = world.abort_sync(approve=lambda p: False)
    assert result.aborted is False and result.declined is True
    assert world.manifests.get(LINEAGE) is not None
    assert world.worktrees_removed == [] and world.refs != {}
    assert world.cleared_manifests == []
    world.assert_nothing_journaled()


def test_abort_invalid_manifest_deletes_only_the_manifest_file():
    world = _retained_world(_retained_manifest(operation_id="not-a-ulid"))
    world.refs.clear()
    world.refs["refs/perk/sync/evil/plan-102"] = C2
    previews: list[SyncResult.AbortPreview] = []
    result = world.abort_sync(approve=lambda p: previews.append(p) or True)
    assert result.aborted is True
    assert previews[0].contained is False
    assert any("containment" in note for note in result.notes)
    assert any("recover" in note for note in result.notes)
    assert world.worktrees_removed == []  # never a deletion from an unvalidated manifest
    assert world.refs != {}
    assert world.manifests == {}  # only the manifest file went


def test_abort_unparseable_manifest_deletes_only_the_manifest_file():
    world = _retained_world()
    world.pending_unparseable = True
    previews: list[SyncResult.AbortPreview] = []
    result = world.abort_sync(approve=lambda p: previews.append(p) or True)
    assert result.aborted is True
    assert previews[0].parseable is False and previews[0].operation_id is None
    assert any("unparseable" in note for note in result.notes)
    assert world.worktrees_removed == []
    assert world.cleared_manifests == [LINEAGE]


def test_abort_missing_manifest_is_no_continuation():
    world = _amended_middle_world()
    error = _abort_error(world)
    assert error.error_type == "no_continuation"
    assert "nothing to abort" in str(error)


def test_abort_foreign_identity_manifest_deletes_only_the_manifest_file():
    # Contained shapes but a different objective: never this train's residue to delete.
    world = _retained_world(_retained_manifest(objective_id="777"))
    result = world.abort_sync(approve=lambda p: True)
    assert result.aborted is True
    assert world.worktrees_removed == []
    assert world.manifests == {}


# ----------------------------------------------------------------- cleanup notes (loud residue)


def test_success_cleanup_failures_surface_as_loud_notes():
    world = _amended_middle_world()
    world.worktree_prune_boom = git.GitError("prune refused")
    result = world.sync()
    assert result.operation_id is not None  # the cascade itself succeeded
    assert any("could not prune the worktree records" in note for note in result.notes)
    assert any("perk objective stack recover" in note for note in result.notes)


def test_clean_success_carries_no_notes():
    assert _amended_middle_world().sync().notes == ()


def test_dry_run_cleanup_failures_surface_as_loud_notes():
    world = _amended_middle_world()
    world.worktree_remove_boom = git.GitError("busy")
    world.worktree_prune_boom = OSError("EACCES")
    result = world.sync(dry_run=True)
    assert result.dry_run is True
    assert any("could not remove the isolated worktree" in note for note in result.notes)
    assert any("could not prune the worktree records" in note for note in result.notes)
    assert any("perk objective stack recover" in note for note in result.notes)


def test_dry_run_per_ref_cleanup_failure_is_a_note():
    assert _amended_middle_world().sync(dry_run=True).notes == ()  # clean baseline
    world = _amended_middle_world()
    world.delete_ref_boom = {"*"}  # every temp-ref deletion fails
    result = world.sync(dry_run=True)
    ref_notes = [note for note in result.notes if "could not delete the temp ref" in note]
    assert len(ref_notes) == 2  # one note per affected layer's temp ref
    assert any("perk objective stack recover" in note for note in result.notes)


def test_continue_success_cleanup_failure_is_a_loud_note():
    world = _retained_world()
    world.worktree_prune_boom = git.GitError("prune refused")
    result = world.continue_sync()
    assert result.continued is True and result.operation_id == OP
    assert any("could not prune the worktree records" in note for note in result.notes)


# ----------------------------------------------------------------- continue hardening


def test_continue_aborted_rebase_head_is_stale():
    # `git rebase --abort` leaves a CLEAN worktree at the ORIGINAL source — the resolved
    # HEAD does not contain the recorded new parent, so continue must refuse (stale), not
    # checkpoint a candidate that does not contain its parent.
    world = _retained_world()
    world.worktree_heads[WT] = P3  # the original source, not a continuation of C2
    error = _continue_error(world)
    assert error.error_type == "continuation_stale"
    assert "does not contain the recorded new parent" in str(error)
    assert LINEAGE in world.manifests  # everything stays retained
    assert world.worktrees_removed == []
    world.assert_nothing_journaled()


def test_continue_captured_parent_edge_mismatch_is_stale():
    # The captured old parent edge must corroborate against the FRESH stored checkpoint
    # pair — a tampered/stale capture must never become a rebase upstream.
    manifest = _retained_manifest()
    tampered = dataclasses_replace(
        manifest,
        layers=(
            dataclasses_replace(manifest.layers[0], old_parent_edge="f" * 40),
            manifest.layers[1],
        ),
    )
    world = _retained_world(tampered)
    error = _continue_error(world)
    assert error.error_type == "continuation_stale"
    assert "old parent edge" in str(error)
    assert LINEAGE in world.manifests
    world.assert_nothing_journaled()


def test_continue_progress_rewrite_failure_is_typed_and_preserves_the_snapshot():
    world = _retained_world()

    def failing_write(root: Path, manifest: continuation.ContinuationManifest) -> Path:
        raise OSError("read-only filesystem")

    world.manifest_write_override = failing_write
    with pytest.raises(DeliveryError) as excinfo:
        world.continue_sync()
    assert excinfo.value.error_type == "git_error"
    assert "could not rewrite the continuation manifest" in str(excinfo.value)
    assert "--continue" in str(excinfo.value)
    # The previous durable snapshot is untouched and everything stays retained.
    assert world.manifests[LINEAGE] == _retained_manifest()
    assert world.worktrees_removed == []
    world.assert_nothing_journaled()


def test_continue_new_conflict_rewrite_failure_stays_typed():
    # The three-layer resume: 1.2's pending candidate adopts (rewrite #1 succeeds), then
    # 1.3's transplant hits a NEW conflict whose progress rewrite fails.
    r1 = _reb(P1, NEWBASE)
    x2 = "x" * 40
    manifest = _retained_manifest(
        include_base=True,
        captured_base_head=NEWBASE,
        conflict_node_id="1.2",
        layers=(
            continuation.ContinuationLayer(
                node_id="1.1",
                plan_id="101",
                branch="plan-101",
                before_sha=P1,
                old_parent_edge=MAIN,
                source_sha=P1,
                new_parent_edge=NEWBASE,
                candidate_temp_ref=f"refs/perk/sync/{OP}/plan-101",
                candidate_sha=r1,
            ),
            continuation.ContinuationLayer(
                node_id="1.2",
                plan_id="102",
                branch="plan-102",
                before_sha=P2,
                old_parent_edge=P1,
                source_sha=P2,
                new_parent_edge=r1,
                candidate_temp_ref=f"refs/perk/sync/{OP}/plan-102",
                candidate_sha=None,
            ),
            continuation.ContinuationLayer(
                node_id="1.3",
                plan_id="103",
                branch="plan-103",
                before_sha=P3,
                old_parent_edge=P2,
                source_sha=P3,
                new_parent_edge=None,
                candidate_temp_ref=f"refs/perk/sync/{OP}/plan-103",
                candidate_sha=None,
            ),
        ),
    )
    world = _three_layer_world()
    world.base_head = NEWBASE
    world.remote["main"] = NEWBASE
    world.manifests[LINEAGE] = manifest
    world.refs[f"refs/perk/sync/{OP}/plan-101"] = r1
    world.existing_paths.add(WT)
    world.worktree_heads[WT] = x2
    world.ancestry.add((r1, x2))
    world.rebase_conflicts.add((P3, x2))
    writes = {"n": 0}
    default_write = world._manifest_write

    def flaky_write(root: Path, m: continuation.ContinuationManifest) -> Path:
        writes["n"] += 1
        if writes["n"] == 2:  # the NEW-conflict progress rewrite
            raise OSError("disk full")
        world.manifest_write_override = None
        try:
            return default_write(root, m)
        finally:
            world.manifest_write_override = flaky_write

    world.manifest_write_override = flaky_write
    error = _continue_error(world)
    assert error.error_type == "rebase_conflict"
    assert "could not be rewritten" in str(error)
    assert "previous snapshot stays retained" in str(error)
    # Deliberately no warm-route hint: the durable manifest still names the OLD conflict
    # layer, so the warm drive stays report-only on this arm — the remedy is the filesystem.
    assert "/objective-sync" not in str(error)
    # The load-bearing §8.49 freshness token (see corroborateSyncConflict): the message names
    # the NEW layer while the PRESERVED manifest still names the old one — that mismatch is
    # exactly what keeps the warm drive report-only on this arm.
    assert "for layer 1.3 " in str(error)
    # The last durable snapshot is rewrite #1 (1.2's candidate captured, 1.3 still pending).
    assert [layer.candidate_sha for layer in world.manifests[LINEAGE].layers] == [r1, x2, None]
    world.assert_nothing_journaled()


# ----------------------------------------------------------------- continue authority gates


def _retained_is_untouched(world: _World) -> None:
    assert LINEAGE in world.manifests
    assert world.worktrees_removed == []
    assert f"refs/perk/sync/{OP}/plan-102" in world.refs
    world.assert_nothing_journaled()


def test_continue_pr_drift_refuses_and_retains():
    world = _retained_world()
    world.pr_entries[202] = ("plan-102", "main", "OPEN")  # base retargeted out-of-band
    error = _continue_error(world)
    assert error.error_type == "pr_drift"
    _retained_is_untouched(world)


def test_continue_membership_drift_refuses_and_retains():
    world = _retained_world()
    world.stack_members = [201, 202]  # 203 fell out of the native stack
    error = _continue_error(world)
    assert error.error_type == "membership_drift"
    _retained_is_untouched(world)


def test_continue_dirty_claimed_worktree_refuses_and_retains():
    world = _retained_world()
    world.layers[0] = _layer(
        "1.1",
        "101",
        pr_number=201,
        parent_checkpoint_sha=MAIN,
        published_head_sha=P1,
        writer=LayerWriter.DIRTY,
    )
    error = _continue_error(world)
    assert error.error_type == "dirty_worktree"
    _retained_is_untouched(world)


def test_continue_active_remote_writer_refuses_and_retains():
    world = _retained_world()
    world.writer_probe.active = frozenset({"103"})
    error = _continue_error(world)
    assert error.error_type == "active_writer"
    _retained_is_untouched(world)


def test_continue_writer_probe_failure_fails_closed_and_retains():
    world = _retained_world()
    world.writer_probe.boom = WriterObservationError("gh api down")
    error = _continue_error(world)
    assert error.error_type == "writer_observation_unavailable"
    _retained_is_untouched(world)


def test_continue_capability_failure_refuses_and_retains():
    world = _retained_world()
    world.atomic_probe_boom = git.GitError("atomic refused")
    error = _continue_error(world)
    assert error.error_type == "atomic_push_unsupported"
    _retained_is_untouched(world)
