"""Hermetic fake-driven tests for the delivery publish operation (contracts.md §8.47).

Every effectful aggregate authority is backed by an in-memory world: a scriptable
mini remote (branch heads, PRs, one native stack), a recording persistence fake, and a
timeline that pins the load-bearing write ordering (prepared → push → … → identity →
checkpoint pair → completed). OFFLINE — no git / gh / network.
"""

import contextlib
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from perk.backends.issue_backend import PlanHeaderUpdate, PlanState
from perk.delivery import (
    Delivery,
    DeliveryError,
    DeliveryGit,
    DeliveryGitHub,
    DeliveryPersistence,
    PublishRequest,
    PublishResult,
    StatusRequest,
    StatusResult,
    SyncRequest,
    SyncResult,
    publish,
)
from perk.delivery import sync as sync_mod
from perk.delivery.journal import (
    EventRole,
    JournalEvent,
    JournalFold,
    OperationKind,
    OperationState,
    OutcomeRecord,
    PreparedRecord,
    ReadyStampEvent,
    ReadyStampRecord,
    canonical_payload,
    canonical_stamp_payload,
    mint_operation_id,
    stamp_key,
)
from perk.delivery.persistence import AppendResult, StampAppendResult, UnresolvedOperationError
from perk.delivery.train import (
    BuildReadiness,
    DeliveryTrain,
    FindingKind,
    LayerFinalization,
    LayerGit,
    LayerHandoff,
    LayerIntent,
    LayerMembership,
    LayerPr,
    LayerPublication,
    LayerWriter,
    TrainFinding,
    TrainLayer,
    TrainReconstructionError,
    UnresolvedOperationFacts,
)
from perk.github import GitHubError
from perk.github.prs import PullRequest
from perk.github.stacks import (
    PrDeliveryFacts,
    StackMutationOutcome,
    StackRestEntry,
    StackRestFacts,
)
from perk.objective import NodeStatus, ObjectiveNode
from perk.substrate import git

ROOT = Path("/repo")
OBJECTIVE = "500"
LINEAGE = "01LINEAGE"
MAIN = "m" * 40
P1 = "1" * 40  # layer-1 published head
P2 = "2" * 40  # layer-2 published head
C1 = "a" * 40  # layer-1 candidate
C2 = "b" * 40  # layer-2 candidate
C3 = "c" * 40  # a moved candidate


def _layer(
    node_id: str,
    plan_id: str,
    *,
    pr_number: int | None = None,
    published: bool = False,
    parent_checkpoint_sha: str | None = None,
    published_head_sha: str | None = None,
) -> TrainLayer:
    return TrainLayer(
        node_id=node_id,
        plan_id=plan_id,
        branch=f"plan-{plan_id}",
        pr_number=pr_number,
        intent=LayerIntent.PLANNED,
        publication=LayerPublication.PUBLISHED if published else LayerPublication.UNPUBLISHED,
        git=LayerGit.SYNCED if published else LayerGit.ABSENT,
        pr=LayerPr.DRAFT if pr_number is not None else LayerPr.ABSENT,
        membership=LayerMembership.NOT_APPLICABLE,
        writer=LayerWriter.FREE,
        finalization=LayerFinalization.NOT_MERGED,
        parent_checkpoint_sha=parent_checkpoint_sha,
        published_head_sha=published_head_sha,
        observed_remote_head_sha=None,
        observed_pr_base=None,
        expected_pr_base=None,
    )


class _WriterProbe:
    def active_plan_ids(self, plan_ids) -> frozenset[str]:
        return frozenset()


class _PrEntry:
    def __init__(self, number: int, branch: str, base: str, state: str = "OPEN") -> None:
        self.number = number
        self.branch = branch
        self.base = base
        self.state = state
        self.draft = True


class _FakePersistence:
    """In-memory journal: seeded unresolved records, recorded appends, and a live fold."""

    def __init__(self, world: "_World", unresolved: list[PreparedRecord]) -> None:
        self._world = world
        self.unresolved_records: dict[str, PreparedRecord] = {r.operation_id: r for r in unresolved}
        self.prepared: list[PreparedRecord] = []
        self.outcomes: list[OutcomeRecord] = []
        self.checkpoints: list[tuple[str, str, str]] = []
        self.stamps: list[ReadyStampEvent] = []
        # Fail-once process-death hook: raised BEFORE the outcome append lands (the P6
        # boundary — checkpoints written, `completed` not yet durable).
        self.outcome_boom: Exception | None = None

    def get_plan(self, *, issue_id: str) -> PlanState:
        return self._world.get_plan(issue_id=issue_id)

    def get_plan_body(self, *, issue_id: str) -> str | None:
        return None

    def update_plan_header(self, *, issue_id: str, fields: dict[str, object]) -> PlanHeaderUpdate:
        return self._world.update_plan_header(issue_id=issue_id, fields=fields)

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
            stamps=tuple(self.stamps),
        )

    def append_ready_stamp(self, objective_id: str, record: ReadyStampRecord) -> StampAppendResult:
        """Real key semantics: an already-held key is the idempotent no-write success; a fresh
        key stores a stamp event served back through the fold reconstruction reads."""
        key = stamp_key(record)
        existed = any(stamp.key == key for stamp in self.stamps)
        self._world.timeline.append(("ready_stamp", key, existed))
        if not existed:
            self.stamps.append(
                ReadyStampEvent(
                    record=record,
                    key=key,
                    canonical_payload=canonical_stamp_payload(record),
                    comment_id=f"stamp-{len(self.stamps)}",
                    created_at=f"s{len(self.stamps)}",
                )
            )
        return StampAppendResult(key=key, existed=existed)

    def append_prepared(self, objective_id: str, record: PreparedRecord) -> AppendResult:
        if self.unresolved_records:
            raise UnresolvedOperationError("an operation is already unresolved")
        self._world.timeline.append(("prepared", record.operation_id))
        self.prepared.append(record)
        self.unresolved_records[record.operation_id] = record
        return AppendResult(record.operation_id, EventRole.PREPARED, existed=False)

    def append_outcome(self, objective_id: str, record: OutcomeRecord) -> AppendResult:
        if self.outcome_boom is not None:
            boom, self.outcome_boom = self.outcome_boom, None
            raise boom
        self._world.timeline.append(("outcome", record.role.value, record.operation_id))
        self.outcomes.append(record)
        self.unresolved_records.pop(record.operation_id, None)
        return AppendResult(record.operation_id, record.role, existed=False)

    def write_checkpoints(
        self, plan_id: str, *, parent_checkpoint_sha: str, published_head_sha: str
    ) -> None:
        if self._world.checkpoints_boom is not None:
            boom, self._world.checkpoints_boom = self._world.checkpoints_boom, None
            raise boom
        self._world.timeline.append(("checkpoints", plan_id))
        self.checkpoints.append((plan_id, parent_checkpoint_sha, published_head_sha))
        # Stateful reconstruction (the crash/rerun tests): a checkpointed layer reads back
        # PUBLISHED, so a rerun's reconstruct sees the completed publication.
        for index, layer in enumerate(self._world.layers):
            if layer.plan_id == plan_id:
                self._world.layers[index] = replace(
                    layer,
                    publication=LayerPublication.PUBLISHED,
                    parent_checkpoint_sha=parent_checkpoint_sha,
                    published_head_sha=published_head_sha,
                )
                break


class _World:
    """The aggregate-backed mini remote + recorders for one Publish invocation."""

    def __init__(
        self,
        layers: list[TrainLayer],
        *,
        unresolved: list[PreparedRecord] | None = None,
        blockers: tuple[str, ...] = (),
        capability: bool = True,
    ) -> None:
        self.layers = layers
        self.base = "main"
        self.blockers = blockers
        self.capability = capability
        # Roadmap nodes carried on the reconstructed projection (empty for most scenarios;
        # the handoff-ungated regression sets them so a hypothetical gate would really bite).
        self.objective_nodes: tuple[ObjectiveNode, ...] = ()
        self.timeline: list[tuple] = []
        self.persistence = _FakePersistence(self, unresolved or [])
        # Git state.
        self.remote: dict[str, str | None] = {"main": MAIN}
        self.local: dict[str, str | None] = {}
        self.ancestry: set[tuple[str, str]] = set()
        self.push_reject = False
        self.fetch_script: list[Exception | None] = []
        self.remote_head_script: list[str | Exception | None] = []
        # GitHub state.
        self.pr_entries: dict[int, _PrEntry] = {}
        self.next_pr = 77
        self.validate_errors: tuple[str, ...] = ()
        self.header_boom: Exception | None = None
        self.checkpoints_boom: Exception | None = None
        # Fail-once process-death hooks at the remote-effect seams (the P-boundary matrix).
        # `push_boom` / `create_pr_boom` raise BEFORE the effect applies (death on the way
        # in); `after_effect_boom[seam]` raises immediately AFTER the effect applied (death
        # between the applied mutation and the next step). publish has no exception-path
        # cleanup that mutates durable state, so a raise IS a faithful death here (the
        # technique rule).
        self.push_boom: Exception | None = None
        self.create_pr_boom: Exception | None = None
        self.after_effect_boom: dict[str, Exception] = {}
        self.pr_facts_script: list[PrDeliveryFacts | Exception | None] = []
        self.stack_number: int | None = None
        self.stack_members: list[int] | None = None
        self.stack_read_script: list[StackRestFacts | Exception | None] = []
        self.mutation_script: list[tuple[StackMutationOutcome, bool]] = []
        # Recorders.
        self.capability_calls = 0
        self.reconstruct_calls = 0
        self.sleeps: list[float] = []
        self.pushes: list[tuple[str, str | None]] = []
        self.bodies: list[str] = []
        self.reconstruct_error: Exception | None = None
        self.writer_probe = _WriterProbe()
        self.sync_result: SyncResult | None = None
        self.sync_error: DeliveryError | None = None
        self.sync_checkpoint_updates: dict[str, tuple[str | None, str | None]] = {}
        self.sync_calls: list[dict[str, object]] = []
        self.use_bound_sync_dispatcher = False

    # ---------------------------------------------------------------- train + issues

    def _reconstruct(self, root: Path, objective_id: str) -> DeliveryTrain:
        self.reconstruct_calls += 1
        prefix = 0
        for layer in self.layers:
            if layer.publication is not LayerPublication.PUBLISHED:
                break
            prefix += 1
        next_node = next(
            (
                layer.node_id
                for layer in self.layers
                if layer.publication is not LayerPublication.PUBLISHED
            ),
            None,
        )
        findings = tuple(
            TrainFinding(kind=FindingKind.BLOCKER, code=code, message=f"boom {code}")
            for code in self.blockers
        )
        unresolved = None
        if self.persistence.unresolved_records:
            op_id = next(iter(self.persistence.unresolved_records))
            unresolved = UnresolvedOperationFacts(
                operation_id=op_id, kind="publish", prepared_created="t0"
            )
        ready = next_node is not None and not findings and unresolved is None
        return DeliveryTrain(
            objective_id=OBJECTIVE,
            objective_url="u",
            delivery_lineage=LINEAGE,
            base=self.base,
            redirected_from=None,
            layers=tuple(self.layers),
            published_prefix_len=prefix,
            unresolved_operation=unresolved,
            findings=findings,
            build_readiness=BuildReadiness(
                next_node_id=next_node, ready=ready, reason=None if ready else "veto"
            ),
            objective_nodes=self.objective_nodes,
        )

    def _issues(self) -> "_World":
        return self

    def get_plan(self, *, issue_id: str) -> PlanState:
        return PlanState(
            id=issue_id,
            url="u",
            title="T",
            header={"objective_id": OBJECTIVE},
            pr=None,
            state="OPEN",
        )

    def update_plan_header(
        self, *, issue_id: str, fields: dict[str, object], dry_run: bool = False
    ) -> PlanHeaderUpdate:
        if self.header_boom is not None:
            boom, self.header_boom = self.header_boom, None
            raise boom
        self.timeline.append(("header", issue_id, dict(fields)))
        # Stateful reconstruction: a written `pr` identity field shows up on the layer the
        # next reconstruct returns (the crash-window tests resume against updated state).
        pr_value = fields.get("pr")
        if isinstance(pr_value, str) and pr_value.isdigit():
            for i, layer in enumerate(self.layers):
                if layer.plan_id == issue_id:
                    self.layers[i] = replace(layer, pr_number=int(pr_value))
        return PlanHeaderUpdate(fields_updated=tuple(fields), dry_run=False)

    # ---------------------------------------------------------------- git seams

    def _fetch(self, root: Path, refspecs: list[str]) -> None:
        self.timeline.append(("fetch", tuple(refspecs)))
        if self.fetch_script:
            failure = self.fetch_script.pop(0)
            if failure is not None:
                raise failure

    def _remote_head(self, root: Path, branch: str) -> str | None:
        if self.remote_head_script:
            value = self.remote_head_script.pop(0)
            if isinstance(value, Exception):
                raise value
            return value
        return self.remote.get(branch)

    def _local_head(self, root: Path, ref: str) -> str | None:
        if ref in self.local:
            return self.local[ref]
        if ref in set(self.remote.values()):
            return ref  # a fetched remote object resolves locally
        return None

    def _is_ancestor(self, root: Path, ancestor: str, head: str) -> bool:
        return (ancestor, head) in self.ancestry

    def _push(self, cwd: Path, branch: str, *, expected_remote_sha: str | None) -> None:
        if self.push_boom is not None:
            boom, self.push_boom = self.push_boom, None
            raise boom  # died before the push moved the ref
        self.timeline.append(("push", branch, expected_remote_sha))
        self.pushes.append((branch, expected_remote_sha))
        if self.push_reject:
            raise git.PushRejectedError("stale info")
        self.remote[branch] = self.local[branch]

    # ---------------------------------------------------------------- github seams

    def _stack_probe(self, root: Path) -> bool:
        self.capability_calls += 1
        return self.capability

    def _pr_facts(self, *, number: int, repo_root: Path) -> PrDeliveryFacts | None:
        if self.pr_facts_script:
            value = self.pr_facts_script.pop(0)
            if isinstance(value, Exception):
                raise value
            return value
        entry = self.pr_entries.get(number)
        if entry is None:
            return None
        return PrDeliveryFacts(
            number=number,
            state=entry.state,
            is_draft=entry.draft,
            base_ref=entry.base,
            head_ref=entry.branch,
            head_sha=self.remote.get(entry.branch) or "",
        )

    def _stack_facts(self) -> StackRestFacts:
        members = self.stack_members or []
        entries = tuple(
            StackRestEntry(
                pr_number=n,
                state="open",
                draft=True,
                merged=False,
                head_ref=self.pr_entries[n].branch if n in self.pr_entries else f"pr-{n}",
                head_sha="",
            )
            for n in members
        )
        number = self.stack_number if self.stack_number is not None else 9
        return StackRestFacts(number=number, size=len(entries), entries=entries)

    def _stack_read(self, *, number: int, repo_root: Path) -> StackRestFacts | None:
        self.timeline.append(("stack_read", number))
        if self.stack_read_script:
            value = self.stack_read_script.pop(0)
            if isinstance(value, Exception):
                raise value
            return value
        if self.stack_members is not None and number in self.stack_members:
            return self._stack_facts()
        return None

    def _apply_members(self, members: list[int]) -> None:
        self.stack_members = list(members)
        if self.stack_number is None:
            self.stack_number = 9

    def _mutation(self, new_members: list[int]) -> StackMutationOutcome:
        if self.mutation_script:
            outcome, apply = self.mutation_script.pop(0)
            if apply:
                self._apply_members(new_members)
            return outcome
        self._apply_members(new_members)
        boom = self.after_effect_boom.pop("stack_mutation", None)
        if boom is not None:
            raise boom  # died right after the mutation applied, before the refetch
        return StackMutationOutcome(
            applied=True,
            status=201,
            retry_after_seconds=None,
            rate_limited=False,
            raw_detail="",
            stack=self._stack_facts(),
        )

    def _stack_create(self, *, pull_requests, repo_root) -> StackMutationOutcome:
        self.timeline.append(("stack_create", tuple(pull_requests)))
        return self._mutation(list(pull_requests))

    def _stack_append(self, *, stack_number, pull_requests, repo_root) -> StackMutationOutcome:
        self.timeline.append(("stack_append", stack_number, tuple(pull_requests)))
        return self._mutation([*(self.stack_members or []), *pull_requests])

    def _create_pr(self, *, head, base, title, body, repo_root, draft) -> PullRequest:
        if self.create_pr_boom is not None:
            boom, self.create_pr_boom = self.create_pr_boom, None
            raise boom  # died before any PR effect (the P2 boundary)
        self.bodies.append(body)
        existing = next((e for e in self.pr_entries.values() if e.branch == head), None)
        if existing is not None:
            return PullRequest(
                number=existing.number,
                url=f"u/pr/{existing.number}",
                is_draft=existing.draft,
                state=existing.state,
                existed=True,
                base_ref=existing.base,
                head_ref=existing.branch,
            )
        number = self.next_pr
        self.next_pr += 1
        self.pr_entries[number] = _PrEntry(number, head, base)
        self.timeline.append(("create_pr", number, head, base))
        boom = self.after_effect_boom.pop("create_pr", None)
        if boom is not None:
            raise boom  # died right after the fresh PR landed (the P3a boundary)
        return PullRequest(
            number=number,
            url=f"u/pr/{number}",
            is_draft=draft,
            state="OPEN",
            existed=False,
            base_ref=base,
            head_ref=head,
        )

    def _get_pr(self, *, number, repo_root) -> PullRequest | None:
        entry = self.pr_entries.get(number)
        if entry is None:
            return None
        return PullRequest(
            number=number,
            url=f"u/pr/{number}",
            is_draft=entry.draft,
            state=entry.state,
            existed=True,
            base_ref=entry.base,
            head_ref=entry.branch,
        )

    def _update_pr_body(self, *, number, body, repo_root):
        self.bodies.append(body)
        self.timeline.append(("update_pr_body", number))
        boom = self.after_effect_boom.pop("update_pr_body", None)
        if boom is not None:
            raise boom  # died right after the body update landed (the P3d boundary)
        from perk.github.prs import PrBodyUpdate

        return PrBodyUpdate(number=number, dry_run=False)

    def _update_pr_base(self, *, number, base, repo_root) -> None:
        self.timeline.append(("update_pr_base", number, base))
        self.pr_entries[number].base = base
        boom = self.after_effect_boom.pop("update_pr_base", None)
        if boom is not None:
            raise boom  # died right after the retarget landed (the P3c boundary)

    def _reopen_pr(self, *, number, repo_root) -> None:
        self.timeline.append(("reopen", number))
        self.pr_entries[number].state = "OPEN"
        boom = self.after_effect_boom.pop("reopen", None)
        if boom is not None:
            raise boom  # died right after the reopen landed (the P3b boundary)

    def _pr_for_branch(self, *, branch, repo_root) -> PullRequest | None:
        # The all-before PR-absence proof: an OPEN entry whose head is `branch`.
        self.timeline.append(("pr_for_branch", branch))
        for number, entry in self.pr_entries.items():
            if entry.branch == branch and entry.state == "OPEN":
                return self._get_pr(number=number, repo_root=repo_root)
        return None

    # ---------------------------------------------------------------- driving

    def _synchronize(self, request: SyncRequest, *, consent=None) -> SyncResult:
        self.sync_calls.append({"request": request, "consent": consent})
        if self.sync_error is not None:
            raise self.sync_error
        if self.sync_result is None:
            raise AssertionError("unexpected suffix synchronization")
        parent_after: str | None = None
        for affected in self.sync_result.affected:
            index = next(
                i for i, layer in enumerate(self.layers) if layer.node_id == affected.node_id
            )
            layer = self.layers[index]
            self.layers[index] = replace(
                layer,
                parent_checkpoint_sha=(
                    parent_after if parent_after is not None else layer.parent_checkpoint_sha
                ),
                published_head_sha=affected.after_sha,
            )
            parent_after = affected.after_sha
        for node_id, (parent_checkpoint, published_head) in self.sync_checkpoint_updates.items():
            index = next(i for i, layer in enumerate(self.layers) if layer.node_id == node_id)
            self.layers[index] = replace(
                self.layers[index],
                parent_checkpoint_sha=parent_checkpoint,
                published_head_sha=published_head,
            )
        return self.sync_result

    def _delivery(self) -> Delivery:
        """Bind one `Delivery` over this world's aggregate seams (publish and ready alike)."""
        world = self

        class _Git:
            @property
            def repo_root(self) -> Path:
                return ROOT

            def fetch_refs(self, refs: tuple[str, ...]) -> None:
                try:
                    world._fetch(ROOT, list(refs))
                except git.GitError as exc:
                    raise TrainReconstructionError(str(exc), error_type="git_error") from exc

            def remote_branch_sha(self, branch: str) -> str | None:
                try:
                    return world._remote_head(ROOT, branch)
                except git.GitError as exc:
                    raise TrainReconstructionError(str(exc), error_type="git_error") from exc

            def resolve_commit(self, ref: str, *, cwd: Path | None = None) -> str | None:
                try:
                    return world._local_head(cwd or ROOT, ref)
                except git.GitError as exc:
                    raise TrainReconstructionError(str(exc), error_type="git_error") from exc

            def is_ancestor(self, ancestor: str, head: str) -> bool:
                return world._is_ancestor(ROOT, ancestor, head)

            def push_with_exact_lease(
                self, branch: str, *, expected_remote_sha: str | None
            ) -> None:
                world._push(ROOT, branch, expected_remote_sha=expected_remote_sha)

        class _GitHub:
            def stack_capability(self) -> bool:
                return world._stack_probe(ROOT)

            def pr_facts(self, number: int) -> PrDeliveryFacts | None:
                try:
                    return world._pr_facts(number=number, repo_root=ROOT)
                except GitHubError as exc:
                    raise TrainReconstructionError(str(exc), error_type="github_error") from exc

            def strict_stack(self, number: int) -> StackRestFacts | None:
                try:
                    return world._stack_read(number=number, repo_root=ROOT)
                except GitHubError as exc:
                    raise TrainReconstructionError(str(exc), error_type="github_error") from exc

            def create_stack(self, pull_requests: tuple[int, ...]) -> StackMutationOutcome:
                return world._stack_create(pull_requests=pull_requests, repo_root=ROOT)

            def append_stack(
                self, stack_number: int, *, pull_requests: tuple[int, ...]
            ) -> StackMutationOutcome:
                return world._stack_append(
                    stack_number=stack_number,
                    pull_requests=pull_requests,
                    repo_root=ROOT,
                )

            def create_pr(
                self, *, head: str, base: str, title: str, body: str, draft: bool
            ) -> PullRequest:
                return world._create_pr(
                    head=head,
                    base=base,
                    title=title,
                    body=body,
                    repo_root=ROOT,
                    draft=draft,
                )

            def get_pr(self, number: int) -> PullRequest | None:
                return world._get_pr(number=number, repo_root=ROOT)

            def update_pr_body(self, number: int, *, body: str):
                return world._update_pr_body(number=number, body=body, repo_root=ROOT)

            def update_pr_base(self, number: int, *, base: str) -> None:
                world._update_pr_base(number=number, base=base, repo_root=ROOT)

            def reopen_pr(self, number: int) -> None:
                world._reopen_pr(number=number, repo_root=ROOT)

            def pr_for_branch(self, branch: str) -> PullRequest | None:
                return world._pr_for_branch(branch=branch, repo_root=ROOT)

            def mark_pr_ready(self, number: int) -> None:
                world.timeline.append(("mark_ready", number))
                world.pr_entries[number].draft = False

        class _Delivery(Delivery):
            def __init__(self) -> None:
                super().__init__(
                    persistence=cast("DeliveryPersistence", world.persistence),
                    git=cast("DeliveryGit", _Git()),
                    github=cast("DeliveryGitHub", _GitHub()),
                )

            def status(self, request: StatusRequest) -> StatusResult:
                if world.reconstruct_error is not None:
                    raise world.reconstruct_error
                train = world._reconstruct(ROOT, request.objective_id)
                return StatusResult(
                    train.objective_id,
                    train.objective_url,
                    train.redirected_from,
                    train,
                    None,
                )

            def sync(self, request: SyncRequest, *, consent=None) -> SyncResult:
                if world.use_bound_sync_dispatcher:
                    return super().sync(request, consent=consent)
                return world._synchronize(request, consent=consent)

        return _Delivery()

    def publish(
        self,
        plan_id: str,
        *,
        run_id: str = "01RUN",
        trigger_run_id: str | None = None,
    ) -> PublishResult.Layer:
        runtime = publish._PublishRuntime(
            mint_operation_id=mint_operation_id,
            now=lambda: "2026-01-01T00:00:00Z",
            sleep=self.sleeps.append,
            validate_pr_body=lambda body, *, pr_number: self.validate_errors,
        )
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(publish, "_DEFAULT_PUBLISH_RUNTIME", runtime)
            result = self._delivery().publish(
                PublishRequest(
                    kind="layer",
                    plan_id=plan_id,
                    run_id=run_id,
                    trigger_run_id=trigger_run_id,
                )
            )
        if result.layer is None:
            raise AssertionError("layer publish returned no layer detail")
        return result.layer

    def ready(self, plan_id: str, objective_id: str = OBJECTIVE) -> PublishResult.Ready:
        """Drive the stacked ready arm (mark-ready-if-draft, then the stamp append)."""
        result = self._delivery().publish(
            PublishRequest(
                kind="ready",
                plan_id=plan_id,
                delivery="stacked",
                objective_id=objective_id,
            )
        )
        if result.ready is None:
            raise AssertionError("ready publish returned no ready detail")
        return result.ready

    def events(self, kind: str) -> list[tuple]:
        return [t for t in self.timeline if t[0] == kind]

    def assert_nothing_persisted(self) -> None:
        """The fail-closed invariant: neither identity nor checkpoints land before every
        postcondition verified — and the operation (when prepared) stays unresolved."""
        assert self.events("header") == []
        assert self.persistence.checkpoints == []
        assert self.persistence.outcomes == []


def _bottom_world() -> _World:
    world = _World([_layer("1", "101"), _layer("2", "102")])
    world.local["plan-101"] = C1
    world.ancestry.add((MAIN, C1))
    return world


def _second_layer_world() -> _World:
    world = _World(
        [
            _layer(
                "1",
                "101",
                pr_number=55,
                published=True,
                parent_checkpoint_sha=MAIN,
                published_head_sha=P1,
            ),
            _layer("2", "102"),
        ]
    )
    world.remote["plan-101"] = P1
    world.local["plan-102"] = C2
    world.ancestry.add((P1, C2))
    world.pr_entries[55] = _PrEntry(55, "plan-101", "main")
    return world


# ----------------------------------------------------------------- fresh publish


def test_bottom_layer_fresh_publish_no_stack_work():
    world = _bottom_world()
    result = world.publish("101")
    assert result.converged_noop is False and result.resumed is False
    assert result.cascade is None
    assert result.pr.number == 77 and result.parent_branch == "main"
    assert result.stack_number is None and result.stack_size is None
    assert result.parent_checkpoint_sha == MAIN and result.published_head_sha == C1
    # No stack calls at all; capability NOT probed at the bottom.
    assert world.events("stack_read") == []
    assert world.events("stack_create") == [] and world.events("stack_append") == []
    assert world.capability_calls == 0
    # The prepared record: absence lease + the not_applicable stack.
    (record,) = world.persistence.prepared
    assert record.operation_kind is OperationKind.PUBLISH
    assert record.affected_plans == ("101",)
    assert record.before["branch"] == {"ref": "plan-101", "sha": None}
    assert record.after["stack"] == {"not_applicable": True}
    assert record.after["branch"] == {"ref": "plan-101", "sha": C1}
    assert world.pushes == [("plan-101", None)]
    # Identity → checkpoint pair → completed (the load-bearing ordering).
    kinds = [t[0] for t in world.timeline]
    assert kinds.index("prepared") < kinds.index("push")
    assert kinds.index("header") < kinds.index("checkpoints") < kinds.index("outcome")
    assert world.persistence.checkpoints == [("101", MAIN, C1)]
    (outcome,) = world.persistence.outcomes
    assert outcome.role is EventRole.COMPLETED
    assert outcome.observed == {"branch_sha": C1, "pr": 77, "stack": None}


def test_second_layer_create_registers_the_stack():
    world = _second_layer_world()
    result = world.publish("102")
    # Probed twice: early on the fresh route (before any effect) + at the mutation seam.
    assert world.capability_calls == 2
    assert world.events("stack_create") == [("stack_create", (55, 77))]
    assert world.events("stack_append") == []
    (record,) = world.persistence.prepared
    assert record.after["stack"] == {"members": [55, "self"]}
    assert record.before["stack"] == {"members": None}
    assert world.pushes == [("plan-102", None)]
    assert result.stack_number == 9 and result.stack_size == 2 and result.stack_position == 2
    assert result.pr.number == 77 and result.parent_branch == "plan-101"
    assert world.persistence.checkpoints == [("102", P1, C2)]
    (outcome,) = world.persistence.outcomes
    assert outcome.observed == {"branch_sha": C2, "pr": 77, "stack": [55, 77]}


@pytest.mark.parametrize(
    ("handoff", "stamped"),
    [(LayerHandoff.UNSTAMPED, None), (LayerHandoff.STALE, "e" * 40)],
)
def test_publication_never_reads_the_predecessor_handoff(
    handoff: LayerHandoff, stamped: str | None
) -> None:
    # The §8.46 publish-ungated regression at the REAL routing boundary: `_route` (the one
    # publication path both `/submit` and `/address`'s finalize_address reach through
    # `Delivery.publish(kind="layer")`) succeeds on a train whose predecessor is published
    # but unstamped/stale — the handoff gate belongs to planning + fresh execution starts
    # only, never to publication. The roadmap nodes ride the projection so a hypothetically
    # gated route would genuinely block here rather than pass vacuously.
    world = _second_layer_world()
    world.layers[0] = replace(world.layers[0], handoff=handoff, stamped_head_sha=stamped)
    world.objective_nodes = (
        ObjectiveNode(
            id="1", description="Bottom", status=NodeStatus.IN_PROGRESS, pr="#101", depends_on=()
        ),
        ObjectiveNode(
            id="2", description="Child", status=NodeStatus.PENDING, pr="#102", depends_on=("1",)
        ),
    )

    result = world.publish("102")

    assert result.pr.number == 77 and result.parent_branch == "plan-101"
    assert world.persistence.checkpoints == [("102", P1, C2)]
    (outcome,) = world.persistence.outcomes
    assert outcome.role is EventRole.COMPLETED


def test_kth_layer_appends_exactly_the_missing_suffix():
    world = _World(
        [
            _layer(
                "1",
                "101",
                pr_number=55,
                published=True,
                parent_checkpoint_sha=MAIN,
                published_head_sha=P1,
            ),
            _layer(
                "2",
                "102",
                pr_number=56,
                published=True,
                parent_checkpoint_sha=P1,
                published_head_sha=P2,
            ),
            _layer("3", "103"),
        ]
    )
    world.remote.update({"plan-101": P1, "plan-102": P2})
    world.local["plan-103"] = C3
    world.ancestry.add((P2, C3))
    world.pr_entries[55] = _PrEntry(55, "plan-101", "main")
    world.pr_entries[56] = _PrEntry(56, "plan-102", "plan-101")
    world.stack_number = 9
    world.stack_members = [55, 56]
    result = world.publish("103")
    assert world.events("stack_create") == []
    assert world.events("stack_append") == [("stack_append", 9, (77,))]
    assert result.stack_position == 3 and result.stack_size == 3
    (record,) = world.persistence.prepared
    assert record.after["stack"] == {"members": [55, 56, "self"]}
    assert record.before["stack"] == {"members": [55, 56]}


def test_already_exact_membership_skips_mutation_and_completes():
    # The layer already stages a PR and the stack already carries exactly the desired
    # composition — no mutation, still a full verified completion.
    world = _second_layer_world()
    world.layers[1] = _layer("2", "102", pr_number=56)
    world.pr_entries[56] = _PrEntry(56, "plan-102", "plan-101")
    world.stack_number = 9
    world.stack_members = [55, 56]
    result = world.publish("102")
    assert world.events("stack_create") == [] and world.events("stack_append") == []
    assert result.stack_number == 9 and result.stack_position == 2
    # An already-converged membership never probes the mutation seam (early check only).
    assert world.capability_calls == 1
    (record,) = world.persistence.prepared
    assert record.after["stack"] == {"members": [55, 56]}  # own PR known — no sentinel
    assert len(world.persistence.outcomes) == 1


def test_post_mutation_ambiguous_5xx_with_exact_after_succeeds():
    world = _second_layer_world()
    ambiguous = StackMutationOutcome(
        applied=False, status=502, retry_after_seconds=None, rate_limited=False, raw_detail="502"
    )
    # The mutation reply was ambiguous, but the server DID apply it — refetch classifies
    # exact-after → success, no second mutation.
    world.mutation_script = [(ambiguous, True)]
    result = world.publish("102")
    assert len(world.events("stack_create")) == 1
    assert result.stack_number == 9
    assert len(world.persistence.outcomes) == 1


def test_unchanged_before_retries_once_then_succeeds():
    world = _second_layer_world()
    ambiguous = StackMutationOutcome(
        applied=False, status=None, retry_after_seconds=None, rate_limited=False, raw_detail="x"
    )
    world.mutation_script = [(ambiguous, False)]  # first call: nothing happened
    result = world.publish("102")
    assert len(world.events("stack_create")) == 2  # the one bounded retry
    assert publish._SETTLE_SECONDS in world.sleeps
    assert result.stack_number == 9


def test_unchanged_before_retry_exhausted_is_registration_failed():
    world = _second_layer_world()
    ambiguous = StackMutationOutcome(
        applied=False, status=None, retry_after_seconds=None, rate_limited=False, raw_detail="x"
    )
    world.mutation_script = [(ambiguous, False), (ambiguous, False)]
    with pytest.raises(DeliveryError) as excinfo:
        world.publish("102")
    assert excinfo.value.error_type == "stack_registration_failed"
    assert len(world.events("stack_create")) == 2
    # The operation stays unresolved (recoverable); nothing durable landed.
    assert world.persistence.read_journal(OBJECTIVE).unresolved
    world.assert_nothing_persisted()


def test_rate_limited_sleeps_min_of_retry_after_and_cap():
    world = _second_layer_world()
    limited = StackMutationOutcome(
        applied=False, status=429, retry_after_seconds=120, rate_limited=True, raw_detail="429"
    )
    world.mutation_script = [(limited, True)]  # applied server-side despite the 429 reply
    result = world.publish("102")
    assert publish._RETRY_AFTER_CAP_SECONDS in world.sleeps  # min(120, 60) == 60
    assert result.stack_number == 9


def test_foreign_composition_is_registration_drift():
    world = _second_layer_world()
    world.stack_number = 9
    world.stack_members = [55, 99]  # a foreign member — neither desired nor the exact prefix
    with pytest.raises(DeliveryError) as excinfo:
        world.publish("102")
    assert excinfo.value.error_type == "stack_registration_drift"
    assert world.events("stack_create") == [] and world.events("stack_append") == []
    assert world.persistence.read_journal(OBJECTIVE).unresolved
    world.assert_nothing_persisted()


def test_own_pr_in_a_different_stack_is_registration_drift():
    world = _second_layer_world()
    # The bottom read sees nothing, but this PR already sits in some other stack.
    foreign = StackRestFacts(
        number=4,
        size=2,
        entries=(
            StackRestEntry(
                pr_number=77, state="open", draft=True, merged=False, head_ref="x", head_sha=""
            ),
            StackRestEntry(
                pr_number=99, state="open", draft=True, merged=False, head_ref="y", head_sha=""
            ),
        ),
    )
    world.stack_read_script = [None, foreign]  # bottom read → None; own read → foreign stack
    with pytest.raises(DeliveryError) as excinfo:
        world.publish("102")
    assert excinfo.value.error_type == "stack_registration_drift"


def test_absent_own_branch_fetch_wrapper_unwraps_and_remains_best_effort():
    world = _bottom_world()
    world.fetch_script = [git.GitError("remote branch is absent"), None]

    result = world.publish("101")

    assert result.pr.number == 77
    assert world.events("fetch")[:2] == [
        ("fetch", ("plan-101",)),
        ("fetch", ("main",)),
    ]


def test_parent_fetch_wrapper_unwraps_into_the_existing_domain_refusal():
    world = _bottom_world()
    world.fetch_script = [None, git.GitError("parent fetch offline")]

    with pytest.raises(DeliveryError) as excinfo:
        world.publish("101")

    assert (excinfo.value.error_type, excinfo.value.phase, excinfo.value.origin) == (
        "git_error",
        "layer",
        "domain",
    )
    assert "parent fetch offline" in str(excinfo.value)
    world.assert_nothing_persisted()


def test_pr_facts_wrapper_unwraps_for_postcondition_classification():
    world = _bottom_world()
    world.pr_facts_script = [GitHubError("PR refetch offline")]

    with pytest.raises(DeliveryError) as excinfo:
        world.publish("101")

    assert excinfo.value.error_type == "postcondition_unverified"
    assert "PR refetch offline" in str(excinfo.value)
    assert world.persistence.read_journal(OBJECTIVE).unresolved
    world.assert_nothing_persisted()


def test_verification_refetch_raising_is_postcondition_unverified():
    # A bottom-layer publish whose final branch re-observation fails: fail closed, the
    # operation stays unresolved for roll-forward.
    world = _bottom_world()
    world.remote_head_script = [
        None,  # the own-branch lease observation (absent — first push)
        MAIN,  # prepare_layer_start: the parent head
        git.GitError("offline"),  # the postcondition refetch
    ]
    with pytest.raises(DeliveryError) as excinfo:
        world.publish("101")
    assert excinfo.value.error_type == "postcondition_unverified"
    assert world.persistence.read_journal(OBJECTIVE).unresolved
    world.assert_nothing_persisted()


def _stack_rest(number: int, *members: int) -> StackRestFacts:
    return StackRestFacts(
        number=number,
        size=len(members),
        entries=tuple(
            StackRestEntry(
                pr_number=m,
                state="open",
                draft=True,
                merged=False,
                head_ref=f"pr-{m}",
                head_sha="",
            )
            for m in members
        ),
    )


def test_post_mutation_partial_composition_is_registration_drift():
    # The mutation reply is ambiguous and the refetch shows a composition that is neither
    # exact-after nor unchanged-before — drift, bounded to ONE mutation, nothing persisted.
    world = _second_layer_world()
    ambiguous = StackMutationOutcome(
        applied=False, status=502, retry_after_seconds=None, rate_limited=False, raw_detail="502"
    )
    world.mutation_script = [(ambiguous, False)]
    # stack_read order: the before-payload read, the classify bottom + own reads, then the
    # post-mutation refetch — which observes a foreign/partial composition.
    world.stack_read_script = [None, None, None, _stack_rest(9, 55, 99)]
    with pytest.raises(DeliveryError) as excinfo:
        world.publish("102")
    assert excinfo.value.error_type == "stack_registration_drift"
    assert len(world.events("stack_create")) == 1  # no second mutation after drift
    assert world.persistence.read_journal(OBJECTIVE).unresolved
    world.assert_nothing_persisted()


def test_post_mutation_unreadable_refetch_is_postcondition_unverified():
    world = _second_layer_world()
    ambiguous = StackMutationOutcome(
        applied=False, status=None, retry_after_seconds=None, rate_limited=False, raw_detail="x"
    )
    world.mutation_script = [(ambiguous, True)]
    world.stack_read_script = [None, None, None, GitHubError("boom")]
    with pytest.raises(DeliveryError) as excinfo:
        world.publish("102")
    assert excinfo.value.error_type == "postcondition_unverified"
    assert len(world.events("stack_create")) == 1  # an unverifiable outcome is never re-POSTed
    assert world.persistence.read_journal(OBJECTIVE).unresolved
    world.assert_nothing_persisted()


def test_body_validation_failure_is_postcondition_unverified_and_persists_nothing():
    world = _bottom_world()
    world.validate_errors = ("checkout footer missing",)
    with pytest.raises(DeliveryError) as excinfo:
        world.publish("101")
    assert excinfo.value.error_type == "postcondition_unverified"
    assert world.persistence.read_journal(OBJECTIVE).unresolved
    world.assert_nothing_persisted()


def test_remote_settling_timeout_when_pr_never_reflects_the_push():
    world = _second_layer_world()
    stale = PrDeliveryFacts(
        number=77,
        state="OPEN",
        is_draft=True,
        base_ref="plan-101",
        head_ref="plan-102",
        head_sha="0" * 40,
    )
    world.pr_facts_script = [stale] * publish._CONVERGE_ATTEMPTS
    with pytest.raises(DeliveryError) as excinfo:
        world.publish("102")
    assert excinfo.value.error_type == "remote_settling_timeout"
    assert world.sleeps == [publish._CONVERGE_DELAY_SECONDS] * publish._CONVERGE_ATTEMPTS
    assert world.persistence.read_journal(OBJECTIVE).unresolved
    world.assert_nothing_persisted()


def test_stale_parent_fails_before_any_journal_append():
    world = _bottom_world()
    world.ancestry.clear()  # the candidate does not contain the fresh parent head
    with pytest.raises(DeliveryError) as excinfo:
        world.publish("101")
    assert excinfo.value.error_type == "stale_parent"
    assert "rebase onto" in str(excinfo.value)
    assert world.persistence.prepared == []  # no prepared record written
    assert world.pushes == []


def test_lease_rejection_leaves_the_operation_unresolved():
    world = _bottom_world()
    world.push_reject = True
    with pytest.raises(DeliveryError) as excinfo:
        world.publish("101")
    assert excinfo.value.error_type == "push_rejected"
    # The prepared record exists and is unresolved — successor readiness blocks on it.
    assert len(world.persistence.prepared) == 1
    world.assert_nothing_persisted()
    fold = world.persistence.read_journal(OBJECTIVE)
    assert [op.kind for op in fold.unresolved] == [OperationKind.PUBLISH]


def test_crash_after_identity_write_resumes_without_duplicate_mutation():
    # Run 1 crashes at the identity write — push landed, PR created, stack registered. The
    # re-run rolls the SAME operation forward against the updated (stateful) train without a
    # second stack mutation, and the durable writes land exactly once.
    world = _second_layer_world()
    world.header_boom = GitHubError("boom at identity write")
    with pytest.raises(DeliveryError):
        world.publish("102")
    assert len(world.events("stack_create")) == 1
    assert world.events("header") == []
    assert world.persistence.checkpoints == [] and world.persistence.outcomes == []
    (record,) = world.persistence.prepared
    result = world.publish("102")
    assert result.resumed is True and result.operation_id == record.operation_id
    assert len(world.events("stack_create")) == 1  # no duplicate mutation across both runs
    assert len(world.events("header")) == 1
    assert world.persistence.checkpoints == [("102", P1, C2)]
    (outcome,) = world.persistence.outcomes
    assert outcome.role is EventRole.COMPLETED
    assert outcome.operation_id == record.operation_id
    assert result.pr.number == 77 and result.published_head_sha == C2


def test_crash_at_checkpoint_write_resumes_idempotently():
    # Run 1 crashes between the identity write and the checkpoint pair; the re-run
    # reconstructs from the updated state (the layer now carries the written PR number),
    # completes the same operation, and writes the pair exactly once.
    world = _second_layer_world()
    world.checkpoints_boom = GitHubError("boom at checkpoint write")
    with pytest.raises(DeliveryError):
        world.publish("102")
    assert len(world.events("header")) == 1  # identity landed before the crash
    assert world.persistence.checkpoints == [] and world.persistence.outcomes == []
    assert world.layers[1].pr_number == 77  # reconstruction now sees the written identity
    (record,) = world.persistence.prepared
    result = world.publish("102")
    assert result.resumed is True and result.operation_id == record.operation_id
    assert len(world.events("stack_create")) == 1
    assert world.persistence.checkpoints == [("102", P1, C2)]
    assert [o.role for o in world.persistence.outcomes] == [EventRole.COMPLETED]


# --- the process-death boundary matrix (the failure-hardening ledger's P rows) -----------
# Each cell: kill at the boundary (fail-once raise — faithful here: publish has no
# exception-path cleanup that mutates durable state), then rerun the owning command and
# assert convergence — exactly one prepared + one terminal record, converged identity/
# checkpoints, and no duplicate NON-idempotent remote effect. The PR create/discovery pass
# and `update_pr_body` are the resume contract's named idempotent re-upserts — they re-run
# on resume by design and are never asserted to zero.


def _kth_layer_world() -> _World:
    world = _World(
        [
            _layer(
                "1",
                "101",
                pr_number=55,
                published=True,
                parent_checkpoint_sha=MAIN,
                published_head_sha=P1,
            ),
            _layer(
                "2",
                "102",
                pr_number=56,
                published=True,
                parent_checkpoint_sha=P1,
                published_head_sha=P2,
            ),
            _layer("3", "103"),
        ]
    )
    world.remote.update({"plan-101": P1, "plan-102": P2})
    world.local["plan-103"] = C3
    world.ancestry.add((P2, C3))
    world.pr_entries[55] = _PrEntry(55, "plan-101", "main")
    world.pr_entries[56] = _PrEntry(56, "plan-102", "plan-101")
    world.stack_number = 9
    world.stack_members = [55, 56]
    return world


def test_crash_before_the_leased_push_retries_under_the_same_operation():
    # P1: died after `append_prepared`, before the leased push moved the ref. The recorded
    # before/after both survive; the local candidate is UNCHANGED, so the rerun retries
    # under the SAME operation from the push step (never a duplicate prepared).
    world = _second_layer_world()
    world.push_boom = GitHubError("process death before the push")
    with pytest.raises(DeliveryError):
        world.publish("102")
    (record,) = world.persistence.prepared
    assert world.pushes == []  # the ref never moved
    assert world.persistence.outcomes == []
    result = world.publish("102")
    assert result.resumed is True and result.operation_id == record.operation_id
    assert world.pushes == [("plan-102", None)]  # exactly one push ever (the absence lease)
    assert len(world.persistence.prepared) == 1  # same operation, no second prepared
    assert len(world.events("create_pr")) == 1 and len(world.events("stack_create")) == 1
    (outcome,) = world.persistence.outcomes
    assert outcome.role is EventRole.COMPLETED and outcome.operation_id == record.operation_id
    assert world.persistence.checkpoints == [("102", P1, C2)]


def test_crash_after_push_before_pr_effects_rolls_forward_the_same_operation():
    # P2: died after `_push_with_lease`, before ANY PR effect. The rerun observes the
    # branch at its after state and rolls the same operation forward — one PR create, one
    # stack mutation, no second push.
    world = _second_layer_world()
    world.create_pr_boom = GitHubError("process death before PR effects")
    with pytest.raises(DeliveryError):
        world.publish("102")
    (record,) = world.persistence.prepared
    assert world.pushes == [("plan-102", None)]  # the push landed (the absence lease)
    assert world.events("create_pr") == [] and world.events("stack_create") == []
    result = world.publish("102")
    assert result.resumed is True and result.operation_id == record.operation_id
    assert world.pushes == [("plan-102", None)]  # roll-forward never re-pushes
    assert len(world.events("create_pr")) == 1
    assert len(world.events("stack_create")) == 1
    (outcome,) = world.persistence.outcomes
    assert outcome.role is EventRole.COMPLETED


def test_crash_after_fresh_pr_create_resumes_via_idempotent_discovery():
    # P3a: died right after the fresh PR landed. The resume's create/discovery pass is the
    # named idempotent re-upsert: it REDISCOVERS the same PR by head (never a second PR)
    # and the single stack mutation happens on the rerun.
    world = _second_layer_world()
    world.after_effect_boom["create_pr"] = GitHubError("process death after PR create")
    with pytest.raises(DeliveryError):
        world.publish("102")
    assert len(world.events("create_pr")) == 1  # PR 77 exists
    assert world.events("stack_create") == []
    result = world.publish("102")
    assert result.resumed is True and result.pr.number == 77
    assert len(world.events("create_pr")) == 1  # rediscovered, never re-created
    assert len(world.events("stack_create")) == 1
    assert len(world.pr_entries) == 2  # PR 55 + PR 77 — no duplicate PR ever
    (outcome,) = world.persistence.outcomes
    assert outcome.role is EventRole.COMPLETED


def test_crash_after_reopen_never_repeats_the_reopen():
    # P3b: a reused CLOSED PR was reopened, then the process died. The rerun's discovery
    # sees the now-OPEN PR — the reopen is not repeated (state-guarded, not blindly re-run).
    world = _bottom_world()
    world.pr_entries[70] = _PrEntry(70, "plan-101", "main", state="CLOSED")
    world.after_effect_boom["reopen"] = GitHubError("process death after reopen")
    with pytest.raises(DeliveryError):
        world.publish("101")
    assert world.events("reopen") == [("reopen", 70)]
    result = world.publish("101")
    assert result.resumed is True and result.pr.number == 70
    assert world.events("reopen") == [("reopen", 70)]  # exactly once across both runs
    (outcome,) = world.persistence.outcomes
    assert outcome.role is EventRole.COMPLETED


def test_crash_after_base_retarget_never_repeats_the_retarget():
    # P3c: the reused PR's base retarget landed, then the process died. The rerun observes
    # the converged base — no second retarget call.
    world = _bottom_world()
    world.pr_entries[70] = _PrEntry(70, "plan-101", "develop", state="OPEN")
    world.after_effect_boom["update_pr_base"] = GitHubError("process death after retarget")
    with pytest.raises(DeliveryError):
        world.publish("101")
    assert world.events("update_pr_base") == [("update_pr_base", 70, "main")]
    result = world.publish("101")
    assert result.resumed is True and result.pr.number == 70
    assert world.events("update_pr_base") == [("update_pr_base", 70, "main")]  # exactly once
    (outcome,) = world.persistence.outcomes
    assert outcome.role is EventRole.COMPLETED


def test_crash_after_body_update_completes_stack_work_exactly_once():
    # P3d: died after `update_pr_body`, before the stack mutation. The body update is the
    # OTHER named idempotent re-upsert (it re-runs on resume — asserting zero repeats would
    # fight the convergent design); the stack mutation still happens exactly once.
    world = _second_layer_world()
    world.after_effect_boom["update_pr_body"] = GitHubError("process death after body update")
    with pytest.raises(DeliveryError):
        world.publish("102")
    assert len(world.events("update_pr_body")) == 1
    assert world.events("stack_create") == []
    result = world.publish("102")
    assert result.resumed is True
    assert len(world.events("update_pr_body")) == 2  # the allowed idempotent re-upsert
    assert len(world.events("stack_create")) == 1  # the non-idempotent effect: exactly once
    (outcome,) = world.persistence.outcomes
    assert outcome.role is EventRole.COMPLETED


def test_crash_after_stack_create_before_refetch_resumes_without_second_mutation():
    # P4a: layer 2's stack CREATE applied, then the process died before the postcondition
    # refetch. The rerun observes exact membership and skips the mutation entirely.
    world = _second_layer_world()
    world.after_effect_boom["stack_mutation"] = GitHubError("process death after stack create")
    with pytest.raises(DeliveryError):
        world.publish("102")
    assert len(world.events("stack_create")) == 1
    assert world.persistence.outcomes == []
    result = world.publish("102")
    assert result.resumed is True
    assert len(world.events("stack_create")) == 1  # never a second mutation
    assert len(world.events("stack_append")) == 0
    (outcome,) = world.persistence.outcomes
    assert outcome.role is EventRole.COMPLETED
    assert world.persistence.checkpoints == [("102", P1, C2)]


def test_crash_after_stack_append_before_refetch_resumes_without_second_append():
    # P4b: layer ≥3's stack APPEND applied, then the process died before the postcondition
    # refetch. The rerun observes the appended membership and never appends again.
    world = _kth_layer_world()
    world.after_effect_boom["stack_mutation"] = GitHubError("process death after stack append")
    with pytest.raises(DeliveryError):
        world.publish("103")
    assert world.events("stack_append") == [("stack_append", 9, (77,))]
    result = world.publish("103")
    assert result.resumed is True and result.stack_position == 3
    assert world.events("stack_append") == [("stack_append", 9, (77,))]  # exactly once
    assert world.events("stack_create") == []
    (outcome,) = world.persistence.outcomes
    assert outcome.role is EventRole.COMPLETED


def test_crash_before_the_completed_append_converges_on_rerun():
    # P6: checkpoints written, the `completed` append never landed. The rerun rolls the
    # same operation forward and the terminal record lands exactly once.
    world = _second_layer_world()
    world.persistence.outcome_boom = GitHubError("process death before the completed append")
    with pytest.raises(DeliveryError):
        world.publish("102")
    (record,) = world.persistence.prepared
    assert world.persistence.checkpoints == [("102", P1, C2)]  # landed before the death
    assert world.persistence.outcomes == []
    result = world.publish("102")
    assert result.resumed is True and result.operation_id == record.operation_id
    assert len(world.events("stack_create")) == 1  # no duplicate remote effect
    (outcome,) = world.persistence.outcomes
    assert outcome.role is EventRole.COMPLETED and outcome.operation_id == record.operation_id


def test_rerun_after_completed_is_a_converged_noop():
    # P7: the operation completed; a rerun takes the republish arm and converges without
    # writing anything new (no second prepared, no remote effect).
    world = _second_layer_world()
    first = world.publish("102")
    assert first.converged_noop is False
    prepared_before = len(world.persistence.prepared)
    outcomes_before = len(world.persistence.outcomes)
    result = world.publish("102")
    assert result.converged_noop is True
    assert len(world.persistence.prepared) == prepared_before  # nothing new journaled
    assert len(world.persistence.outcomes) == outcomes_before
    assert len(world.events("stack_create")) == 1 and world.pushes == [("plan-102", None)]


def test_merged_reused_pr_refuses():
    world = _bottom_world()
    world.pr_entries[70] = _PrEntry(70, "plan-101", "main", state="MERGED")
    with pytest.raises(DeliveryError) as excinfo:
        world.publish("101")
    assert excinfo.value.error_type == "pr_already_merged"


def test_closed_reused_pr_is_reopened_and_base_converged():
    world = _bottom_world()
    world.pr_entries[70] = _PrEntry(70, "plan-101", "develop", state="CLOSED")
    result = world.publish("101")
    assert result.pr.number == 70
    assert world.events("reopen") == [("reopen", 70)]
    assert world.events("update_pr_base") == [("update_pr_base", 70, "main")]


# ----------------------------------------------------------------- routing refusals


@pytest.mark.parametrize(
    ("kind", "plans"),
    [
        (OperationKind.PUBLISH, ("999",)),  # a PUBLISH for a DIFFERENT plan
        (OperationKind.SYNC, ("101",)),
        (OperationKind.ADOPT, ("101",)),
        (OperationKind.TRANSFER, ("101",)),
        (OperationKind.LAND, ("101",)),
    ],
)
def test_foreign_unresolved_operation_refuses(kind, plans):
    # One-unresolved-per-lineage, per kind: an unresolved record of every kind (or a
    # PUBLISH for another plan) blocks a fresh publish on the lineage.
    foreign = PreparedRecord(
        operation_id=mint_operation_id(),
        operation_kind=kind,
        delivery_lineage=LINEAGE,
        objective_id=OBJECTIVE,
        run_id="01RUN",
        created="t0",
        affected_plans=plans,
        before={},
        after={},
    )
    world = _bottom_world()
    world.persistence.unresolved_records[foreign.operation_id] = foreign
    with pytest.raises(DeliveryError) as excinfo:
        world.publish("101")
    assert excinfo.value.error_type == "unresolved_operation"


def test_capability_recheck_failure_at_position_two():
    world = _second_layer_world()
    world.capability = False
    with pytest.raises(DeliveryError) as excinfo:
        world.publish("102")
    assert excinfo.value.error_type == "stack_capability_lost"
    assert world.persistence.prepared == []  # refused before any journal append
    assert world.pushes == []


def test_missing_remote_parent_passes_through_the_layer_code():
    # The §8.46 layer-preparation codes join the publication vocabulary verbatim: an absent
    # remote parent surfaces as `parent_missing`, before any journal append.
    world = _bottom_world()
    world.remote["main"] = None
    with pytest.raises(DeliveryError) as excinfo:
        world.publish("101")
    assert excinfo.value.error_type == "parent_missing"
    assert world.persistence.prepared == [] and world.pushes == []


def _lower_published_world() -> _World:
    world = _World(
        [
            _layer(
                "1",
                "101",
                pr_number=55,
                published=True,
                parent_checkpoint_sha=MAIN,
                published_head_sha=P1,
            ),
            _layer(
                "2",
                "102",
                pr_number=56,
                published=True,
                parent_checkpoint_sha=P1,
                published_head_sha=P2,
            ),
            _layer("3", "103"),
        ]
    )
    world.pr_entries[55] = _PrEntry(55, "plan-101", "main")
    world.pr_entries[56] = _PrEntry(56, "plan-102", "plan-101")
    return world


def _sync_result(
    *,
    affected: tuple[SyncResult.Layer, ...],
    operation_id: str | None = "01SYNC",
    no_op: bool = False,
    resumed: bool = False,
    notes: tuple[str, ...] = (),
) -> SyncResult:
    return SyncResult(
        objective_id=OBJECTIVE,
        objective_url="u",
        redirected_from=None,
        operation_id=operation_id,
        abandoned_operation_id=None,
        no_op=no_op,
        declined=False,
        resumed=resumed,
        base_cascaded=False,
        base_advanced=False,
        affected=affected,
        notes=notes,
    )


def test_lower_claimed_layer_delegates_to_triggered_sync():
    world = _lower_published_world()
    affected = (
        SyncResult.Layer("1", "101", "plan-101", 55, P1, C1),
        SyncResult.Layer("2", "102", "plan-102", 56, P2, C2),
    )
    world.sync_result = _sync_result(affected=affected, notes=("residue",))

    result = world.publish("101", trigger_run_id="01RAW")

    (call,) = world.sync_calls
    assert call["request"] == SyncRequest(
        mode="cascade",
        objective_id=OBJECTIVE,
        run_id="01RUN",
        trigger_plan_id="101",
        trigger_run_id="01RAW",
    )
    assert call["consent"] is None
    assert result.operation_id == "01SYNC"
    assert result.parent_checkpoint_sha == MAIN and result.published_head_sha == C1
    assert (
        result.stack_number is None and result.stack_size is None and result.stack_position is None
    )
    assert result.cascade == world.sync_result


def test_lower_layer_publish_enters_the_bound_sync_lock_exactly_once(monkeypatch):
    world = _lower_published_world()
    affected = (SyncResult.Layer("1", "101", "plan-101", 55, P1, C1),)
    world.sync_result = _sync_result(affected=affected)
    world.sync_checkpoint_updates["1"] = (MAIN, C1)
    world.use_bound_sync_dispatcher = True
    events: list[tuple[str, Path]] = []
    active = False

    @contextlib.contextmanager
    def operation_lock(root: Path):
        nonlocal active
        if active:
            raise AssertionError("the non-reentrant stack lock was entered recursively")
        active = True
        events.append(("enter", root))
        try:
            yield
        finally:
            events.append(("exit", root))
            active = False

    runtime = replace(sync_mod._DEFAULT_SYNC_RUNTIME, operation_lock=operation_lock)

    def synchronize(context, request, *, consent):
        return world._synchronize(request, consent=consent)

    monkeypatch.setattr(sync_mod, "_DEFAULT_SYNC_RUNTIME", runtime)
    monkeypatch.setattr(sync_mod, "_synchronize", synchronize)

    result = world.publish("101", trigger_run_id="01RAW")

    assert result.cascade == world.sync_result
    assert events == [("enter", ROOT), ("exit", ROOT)]


def test_drifted_claimed_successor_still_routes_to_cascade():
    world = _lower_published_world()
    world.layers[2] = _layer(
        "3",
        "103",
        pr_number=57,
        published=False,
        parent_checkpoint_sha=P2,
        published_head_sha=C3,
    )
    world.pr_entries[57] = _PrEntry(57, "plan-103", "plan-102")
    affected = (SyncResult.Layer("2", "102", "plan-102", 56, P2, C2),)
    world.sync_result = _sync_result(affected=affected)

    result = world.publish("102")

    assert len(world.sync_calls) == 1
    request = cast(SyncRequest, world.sync_calls[0]["request"])
    assert request.trigger_plan_id == "102"
    assert result.published_head_sha == C2


def test_cascade_noop_uses_fresh_post_sync_checkpoints_and_typed_operation():
    world = _lower_published_world()
    world.sync_result = _sync_result(affected=(), operation_id=None, no_op=True)
    # Models trigger-resume/all-after: the old operation rolls its checkpoint forward, then the
    # fresh trigger pass is a no-op. Publish must not return its pre-sync train snapshot.
    world.sync_checkpoint_updates["1"] = (MAIN, C1)
    result = world.publish("101")
    assert result.converged_noop is True and result.operation_id is None
    assert result.parent_checkpoint_sha == MAIN and result.published_head_sha == C1
    assert result.cascade is not None and result.cascade.no_op is True
    assert world.reconstruct_calls == 2


def test_cascade_refuses_sync_result_missing_the_trigger():
    world = _lower_published_world()
    world.sync_result = _sync_result(
        affected=(SyncResult.Layer("2", "102", "plan-102", 56, P2, C2),)
    )
    with pytest.raises(DeliveryError) as excinfo:
        world.publish("101")
    assert excinfo.value.error_type == "publication_drift"
    assert "did not report plan #101" in str(excinfo.value)


def test_cascade_refuses_checkpoint_disagreement_after_sync():
    world = _lower_published_world()
    world.sync_result = _sync_result(
        affected=(SyncResult.Layer("1", "101", "plan-101", 55, P1, C1),)
    )
    world.sync_checkpoint_updates["1"] = (MAIN, C3)
    with pytest.raises(DeliveryError) as excinfo:
        world.publish("101")
    assert excinfo.value.error_type == "publication_drift"
    assert "fresh reconstruction carries" in str(excinfo.value)


def test_cascade_noop_refuses_incomplete_fresh_checkpoint_pair():
    world = _lower_published_world()
    world.sync_result = _sync_result(affected=(), operation_id=None, no_op=True)
    world.sync_checkpoint_updates["1"] = (None, None)
    with pytest.raises(DeliveryError) as excinfo:
        world.publish("101")
    assert excinfo.value.error_type == "publication_drift"
    assert "no complete checkpoint pair" in str(excinfo.value)


def test_cascade_contextualizes_the_bound_sync_error():
    world = _lower_published_world()
    world.sync_error = DeliveryError("branch drift", error_type="remote_drift")
    with pytest.raises(DeliveryError) as excinfo:
        world.publish("101")
    assert str(excinfo.value) == "branch drift"
    assert (excinfo.value.error_type, excinfo.value.phase, excinfo.value.origin) == (
        "remote_drift",
        "cascade",
        "delivery",
    )


def test_lower_publish_routes_sync_unresolved_through_cascade_before_fold():
    world = _lower_published_world()
    record = PreparedRecord(
        operation_id=mint_operation_id(),
        operation_kind=OperationKind.SYNC,
        delivery_lineage=LINEAGE,
        objective_id=OBJECTIVE,
        run_id="01RUN",
        created="t0",
        affected_plans=("101", "102"),
        before={},
        after={},
    )
    world.persistence.unresolved_records[record.operation_id] = record
    world.sync_result = _sync_result(affected=(), operation_id=None, no_op=True)
    assert world.publish("101").cascade is not None
    assert len(world.sync_calls) == 1


def test_readiness_veto_maps_to_node_not_build_ready():
    world = _bottom_world()
    world.blockers = ("checkpoint_drift",)
    with pytest.raises(DeliveryError) as excinfo:
        world.publish("101")
    assert excinfo.value.error_type == "node_not_build_ready"


def test_not_stacked_when_plan_is_not_a_layer():
    world = _bottom_world()
    with pytest.raises(DeliveryError) as excinfo:
        world.publish("404")
    assert excinfo.value.error_type == "not_stacked"


# ----------------------------------------------------------------- the republish arm


def _top_layer_world() -> _World:
    world = _World(
        [
            _layer(
                "1",
                "101",
                pr_number=55,
                published=True,
                parent_checkpoint_sha=MAIN,
                published_head_sha=P1,
            ),
            _layer(
                "2",
                "102",
                pr_number=56,
                published=True,
                parent_checkpoint_sha=P1,
                published_head_sha=P2,
            ),
        ]
    )
    world.remote.update({"plan-101": P1, "plan-102": P2})
    world.pr_entries[55] = _PrEntry(55, "plan-101", "main")
    world.pr_entries[56] = _PrEntry(56, "plan-102", "plan-101")
    world.stack_number = 9
    world.stack_members = [55, 56]
    return world


def test_top_layer_republish_moves_the_checkpoints():
    world = _top_layer_world()
    world.local["plan-102"] = C2  # an amended top layer
    world.ancestry.add((P1, C2))
    result = world.publish("102")
    assert result.converged_noop is False and result.cascade is None
    assert world.pushes == [("plan-102", P2)]  # the checkpoint-matching lease
    assert world.persistence.checkpoints == [("102", P1, C2)]
    assert world.events("stack_create") == [] and world.events("stack_append") == []
    (record,) = world.persistence.prepared
    assert record.before["branch"] == {"ref": "plan-102", "sha": P2}


def test_top_layer_pure_noop_converge_writes_nothing():
    world = _top_layer_world()
    world.local["plan-102"] = P2  # candidate == published head; everything already matches
    result = world.publish("102")
    assert result.converged_noop is True and result.operation_id is None
    assert result.cascade is None
    assert result.pr.number == 56
    assert result.stack_number == 9 and result.stack_position == 2
    assert result.parent_checkpoint_sha == P1 and result.published_head_sha == P2
    # NO journal event, no header write, no checkpoints, no push.
    assert world.persistence.prepared == [] and world.persistence.outcomes == []
    assert world.persistence.checkpoints == []
    assert world.events("header") == [] and world.pushes == []


def test_top_layer_remote_drift_refuses():
    world = _top_layer_world()
    world.remote["plan-102"] = C3  # out-of-band movement vs the checkpoint
    world.local["plan-102"] = C2
    with pytest.raises(DeliveryError) as excinfo:
        world.publish("102")
    assert excinfo.value.error_type == "remote_drift"


# ----------------------------------------------------------------- the resume path


def _resume_record(
    *,
    before_sha: str | None,
    after_sha: str,
    members=None,
    pr_base: str = "plan-101",
    lineage: str = LINEAGE,
) -> PreparedRecord:
    stack_after: dict[str, object] = (
        {"members": members} if members is not None else {"not_applicable": True}
    )
    return PreparedRecord(
        operation_id=mint_operation_id(),
        operation_kind=OperationKind.PUBLISH,
        delivery_lineage=lineage,
        objective_id=OBJECTIVE,
        run_id="01RUN",
        created="t0",
        affected_plans=("102",),
        before={
            "branch": {"ref": "plan-102", "sha": before_sha},
            "pr": {"number": None, "base": None, "head_sha": None, "state": None},
            "stack": {"members": None},
        },
        after={
            "branch": {"ref": "plan-102", "sha": after_sha},
            "pr": {"base": pr_base, "head_sha": after_sha},
            "stack": stack_after,
        },
    )


def test_resume_rolls_forward_from_the_after_state():
    record = _resume_record(before_sha=None, after_sha=C2, members=[55, "self"])
    world = _second_layer_world()
    world.persistence.unresolved_records[record.operation_id] = record
    world.remote["plan-102"] = C2  # the push landed; nothing else did
    result = world.publish("102")
    assert result.resumed is True
    assert result.operation_id == record.operation_id  # the SAME operation completes
    assert world.pushes == []  # roll-forward never re-pushes
    assert world.persistence.prepared == []  # no second prepared
    # The "self" member resolved through the PR discovered/created by head.
    assert world.events("stack_create") == [("stack_create", (55, 77))]
    (outcome,) = world.persistence.outcomes
    assert outcome.role is EventRole.COMPLETED and outcome.operation_id == record.operation_id
    assert world.persistence.checkpoints == [("102", P1, C2)]


def test_resume_retries_under_the_same_operation_when_candidate_unchanged():
    record = _resume_record(before_sha=None, after_sha=C2, members=[55, "self"])
    world = _second_layer_world()
    world.persistence.unresolved_records[record.operation_id] = record
    # Branch still absent remotely (the before state); the local candidate is unchanged.
    result = world.publish("102")
    assert result.resumed is True and result.operation_id == record.operation_id
    assert world.pushes == [("plan-102", None)]  # the retry re-pushes under the before lease
    assert world.persistence.prepared == []
    (outcome,) = world.persistence.outcomes
    assert outcome.operation_id == record.operation_id


def test_resume_abandons_with_proof_then_prepares_fresh():
    record = _resume_record(before_sha=None, after_sha=C2, members=[55, "self"])
    world = _second_layer_world()
    world.persistence.unresolved_records[record.operation_id] = record
    world.local["plan-102"] = C3  # the candidate moved
    world.ancestry.add((P1, C3))
    result = world.publish("102")
    assert result.resumed is False  # the completing operation is the FRESH one
    assert result.operation_id != record.operation_id
    abandoned, completed = world.persistence.outcomes
    assert abandoned.role is EventRole.ABANDONED
    assert abandoned.operation_id == record.operation_id
    # The proof: branch/PR/stack all observed at their before states.
    assert abandoned.observed["branch"] == {"ref": "plan-102", "sha": None}
    assert completed.role is EventRole.COMPLETED
    assert completed.operation_id == result.operation_id
    (fresh,) = world.persistence.prepared
    assert fresh.after["branch"] == {"ref": "plan-102", "sha": C3}
    assert world.reconstruct_calls == 2  # the fresh pass reconstructs again


def test_resume_refuses_a_drifted_parent_base():
    # The prepared record targeted a parent the reconstructed train no longer derives —
    # the recorded desired state wins: publication_drift, never a silent retarget.
    record = _resume_record(before_sha=None, after_sha=C2, members=[55, "self"], pr_base="plan-99")
    world = _second_layer_world()
    world.persistence.unresolved_records[record.operation_id] = record
    world.remote["plan-102"] = C2
    with pytest.raises(DeliveryError) as excinfo:
        world.publish("102")
    assert excinfo.value.error_type == "publication_drift"
    assert world.events("stack_create") == [] and world.pushes == []
    assert world.persistence.read_journal(OBJECTIVE).unresolved


def test_resume_refuses_a_drifted_stack_prefix():
    # The recorded desired members name a different prefix PR than the live train derives
    # (e.g. a prefix layer's PR identity changed while the operation was unresolved).
    record = _resume_record(before_sha=None, after_sha=C2, members=[66, "self"])
    world = _second_layer_world()
    world.persistence.unresolved_records[record.operation_id] = record
    world.remote["plan-102"] = C2
    with pytest.raises(DeliveryError) as excinfo:
        world.publish("102")
    assert excinfo.value.error_type == "publication_drift"
    assert world.events("stack_create") == []
    assert world.persistence.read_journal(OBJECTIVE).unresolved


def test_resume_refuses_a_drifted_lineage():
    record = _resume_record(before_sha=None, after_sha=C2, members=[55, "self"], lineage="01OTHER")
    world = _second_layer_world()
    world.persistence.unresolved_records[record.operation_id] = record
    world.remote["plan-102"] = C2
    with pytest.raises(DeliveryError) as excinfo:
        world.publish("102")
    assert excinfo.value.error_type == "publication_drift"


def test_resume_refuses_when_the_recorded_pr_pin_mismatches():
    # The record pinned a concrete own PR; the head selector discovers a different one —
    # mixed remote state, the recorded operation is never completed against it.
    record = _resume_record(before_sha=None, after_sha=C2, members=[55, 60])
    world = _second_layer_world()
    world.persistence.unresolved_records[record.operation_id] = record
    world.remote["plan-102"] = C2
    with pytest.raises(DeliveryError) as excinfo:
        world.publish("102")  # the head selector creates/discovers PR #77, not #60
    assert excinfo.value.error_type == "publication_drift"
    assert world.events("stack_create") == []
    assert world.persistence.read_journal(OBJECTIVE).unresolved


def test_resume_rechecks_capability_at_the_mutation_seam():
    # A resumed position-2 roll-forward that still needs the stack mutation re-probes at the
    # create/append seam and fails closed when the capability is gone.
    record = _resume_record(before_sha=None, after_sha=C2, members=[55, "self"])
    world = _second_layer_world()
    world.persistence.unresolved_records[record.operation_id] = record
    world.remote["plan-102"] = C2
    world.capability = False
    with pytest.raises(DeliveryError) as excinfo:
        world.publish("102")
    assert excinfo.value.error_type == "stack_capability_lost"
    assert world.events("stack_create") == [] and world.events("stack_append") == []
    assert world.persistence.read_journal(OBJECTIVE).unresolved


def test_resume_mixed_state_is_publication_drift():
    record = _resume_record(before_sha=None, after_sha=C2, members=[55, "self"])
    world = _second_layer_world()
    world.persistence.unresolved_records[record.operation_id] = record
    world.remote["plan-102"] = "f" * 40  # neither before nor after
    with pytest.raises(DeliveryError) as excinfo:
        world.publish("102")
    assert excinfo.value.error_type == "publication_drift"
    assert world.persistence.read_journal(OBJECTIVE).unresolved


def test_resume_pr_moved_off_its_before_state_is_publication_drift():
    record = _resume_record(before_sha=None, after_sha=C2, members=[55, "self"])
    # The before state recorded a PR observation; the live PR no longer matches it.
    object.__setattr__(
        record,
        "before",
        {
            "branch": {"ref": "plan-102", "sha": None},
            "pr": {"number": 56, "base": "plan-101", "head_sha": "0" * 40, "state": "OPEN"},
            "stack": {"members": None},
        },
    )
    world = _second_layer_world()
    world.pr_entries[56] = _PrEntry(56, "plan-102", "main")  # base moved off "plan-101"
    world.persistence.unresolved_records[record.operation_id] = record
    with pytest.raises(DeliveryError) as excinfo:
        world.publish("102")
    assert excinfo.value.error_type == "publication_drift"


# ----------------------------------------------------------------- the cross-command choreography


def test_choreography_submit_draft_review_address_stamp():
    """submit → draft review → address → stamp, pinned at the delivery level (contracts.md
    §8.43/§8.52): publish never touches draft state on an existing PR, review runs on drafts,
    and the stacked ready gesture orders mark-ready strictly before the head-exact stamp
    append — with the deterministic key making the re-run converge. Stamp read-back is
    asserted through the production fold accessor (`JournalFold.latest_ready_stamp`) over the
    persistence's own `read_journal` — the exact seam `_derive_handoff` consumes; the
    fold→handoff projection itself is pinned by `tests/test_delivery_train.py`."""

    def latest_stamp(world: _World):
        fold = world.persistence.read_journal(OBJECTIVE)
        return fold.latest_ready_stamp(objective_id=OBJECTIVE, plan_id="101")

    world = _bottom_world()
    # 1. Submit at head C1: a draft PR; no handoff yet — the fold serves back no stamp.
    first = world.publish("101")
    assert first.pr.number == 77 and first.published_head_sha == C1
    assert world.pr_entries[77].draft is True
    assert world.events("mark_ready") == [] and world.events("ready_stamp") == []
    assert latest_stamp(world) is None
    # 2. Draft review: no mechanics — the PR stays draft (review runs on drafts).
    assert world.pr_entries[77].draft is True
    # 3. Address: the branch advances to C3 and republishes (the same publication mechanic
    #    address finalization routes through) — the PR stays draft, still no stamp.
    world.local["plan-101"] = C3
    world.ancestry.add((MAIN, C3))
    second = world.publish("101")
    assert second.published_head_sha == C3
    assert world.pr_entries[77].draft is True
    assert world.events("ready_stamp") == []
    # 4. Stamp: mark-ready strictly before the append; the record binds the POST-address
    #    verified head (C3, never C1).
    ready = world.ready("101")
    key = f"{OBJECTIVE}:101:1:{C3}"
    assert world.events("mark_ready") == [("mark_ready", 77)]
    assert world.events("ready_stamp") == [("ready_stamp", key, False)]
    assert world.timeline.index(("mark_ready", 77)) < world.timeline.index(
        ("ready_stamp", key, False)
    )
    assert ready.was_draft is True
    assert ready.stamp is not None
    assert ready.stamp.existed is False and ready.stamp.record.head_sha == C3
    # The continuation fact rides the same verified projection as the record: the stamp
    # carries the layer's parent checkpoint so consumers can compose the pinned diff range.
    assert ready.stamp.parent_checkpoint_sha == MAIN
    # Read-back through the production fold accessor: the appended stamp is served back by
    # the journal read and names the post-address head.
    served = latest_stamp(world)
    assert served is not None and served.record == ready.stamp.record
    assert served.record.head_sha == C3
    # 5. Converging re-run: no second mark-ready; the deterministic key answers existed=True.
    again = world.ready("101")
    assert world.events("mark_ready") == [("mark_ready", 77)]
    assert world.events("ready_stamp") == [
        ("ready_stamp", key, False),
        ("ready_stamp", key, True),
    ]
    assert again.was_draft is False
    assert again.stamp is not None and again.stamp.existed is True
    assert again.stamp.parent_checkpoint_sha == MAIN
