"""The hermetic cross-machine continuation lane (the failure-hardening ledger's 6.1 cell).

Two genuinely separate "machines" over the two REAL shared durable authorities: one bare
git origin (the ref authority — pushes, leases, fetches and ls-remote run real git) and one
shared stateful fake backend world (the journal + plan/PR/objective authority — hermetic;
live wire parity is node 6.2's dogfood). Machine A is clone A; machine B is a **separately
created fresh clone** with **separately constructed** seams. Zero shared local state: no
copied ``.perk/``, no shared worktrees, and every git seam on a machine asserts it only
ever receives that machine's own clone root — B structurally cannot read A's tree.

Machine A's "death" is post-crash durable-state construction (the technique rule): A's
surviving effects are applied for real (real pushes from clone A, journal records in the
shared world), then machine B's PUBLIC surfaces (``recover_operations``, ``Delivery.publish``)
conclude the operation from the durable authorities alone — the same posture as the remote
runner's fresh checkout. Arms: SYNC all-after roll-forward, SYNC all-before
abandon-with-proof, PUBLISH bottom-layer all-after (report + submit-resume completion),
PUBLISH non-bottom mixed (honest report + submit-resume stack convergence), LAND
accepted-handle conclusion, and the TRANSFER manifest roll-forward. ADOPT is deliberately
not a separate arm: it shares SYNC's record-recovery core (``sync.py``'s §8.51 region) and
its classification/roll-forward arms are pinned in ``tests/test_delivery_recover.py`` /
``tests/test_delivery_sync.py`` — the ledger maps ADOPT onto that evidence.
"""

import contextlib
import subprocess
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from perk import objective
from perk.backends.issue_backend import PlanHeaderUpdate, PlanState
from perk.backends.objective_store import ObjectiveRef, ObjectiveState
from perk.delivery import (
    Delivery,
    DeliveryGit,
    DeliveryGitHub,
    DeliveryPersistence,
    PublishRequest,
    PublishResult,
    StatusRequest,
    StatusResult,
    continuation,
    publish,
    recover,
)
from perk.delivery import transfer as transfer_mod
from perk.delivery.finalize import (
    LandFinalization,
    LearnConsumeUpdate,
    ObjectiveLandUpdate,
)
from perk.delivery.journal import (
    EventRole,
    JournalEvent,
    JournalFold,
    OperationKind,
    OperationState,
    OutcomeRecord,
    PreparedRecord,
    canonical_payload,
    mint_operation_id,
)
from perk.delivery.persistence import AppendResult, UnresolvedOperationError
from perk.delivery.train import (
    BuildReadiness,
    DeliveryTrain,
    LayerFinalization,
    LayerGit,
    LayerIntent,
    LayerMembership,
    LayerPr,
    LayerPublication,
    LayerWriter,
    TrainLayer,
    UnresolvedOperationFacts,
)
from perk.github.prs import PullRequest
from perk.github.stacks import (
    MergeAsyncProbe,
    PrDeliveryFacts,
    PrMergedEvidence,
    StackMutationOutcome,
    StackRestEntry,
    StackRestFacts,
)
from perk.substrate import git as git_mod

OBJECTIVE = "500"
LINEAGE = "01LINEAGE"
NOW = "2026-02-02T00:00:00Z"
M1 = "d" * 40  # fabricated merge commits (the merge facts ride the stateful fake)
M2 = "e" * 40


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def _commit(repo: Path, name: str) -> str:
    (repo / f"{name}.txt").write_text(f"{name}\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", name)
    return _git(repo, "rev-parse", "HEAD").strip()


# ----------------------------------------------------------------- the shared authorities


class _SharedPersistence:
    """The shared durable journal (the backend authority both machines' seams compose)."""

    def __init__(self) -> None:
        self.unresolved_records: dict[str, PreparedRecord] = {}
        self.accepted_records: dict[str, OutcomeRecord] = {}
        self.completed: list[tuple[PreparedRecord, OutcomeRecord]] = []
        self.prepared: list[PreparedRecord] = []
        self.outcomes: list[OutcomeRecord] = []
        self.checkpoints: list[tuple[str, str, str]] = []
        self.world: _SharedWorld | None = None

    def _event(self, record, role: EventRole, comment_id: str) -> JournalEvent:
        return JournalEvent(
            record=record,
            role=role,
            operation_id=record.operation_id,
            canonical_payload=canonical_payload(record),
            comment_id=comment_id,
            created_at=record.created,
        )

    def read_journal(self, objective_id: str) -> JournalFold:
        ops: dict[str, OperationState] = {}
        for record, outcome in self.completed:
            ops[record.operation_id] = OperationState(
                operation_id=record.operation_id,
                kind=record.operation_kind,
                prepared=self._event(record, EventRole.PREPARED, "c1"),
                accepted=None,
                outcome=self._event(outcome, outcome.role, "c3"),
            )
        for op_id, record in self.unresolved_records.items():
            accepted = self.accepted_records.get(op_id)
            ops[op_id] = OperationState(
                operation_id=op_id,
                kind=record.operation_kind,
                prepared=self._event(record, EventRole.PREPARED, "c1"),
                accepted=None
                if accepted is None
                else self._event(accepted, EventRole.ACCEPTED, "c2"),
                outcome=None,
            )
        return JournalFold(
            events=(),
            operations=ops,
            unresolved=tuple(op for op in ops.values() if not op.resolved),
            delivery_lineage=LINEAGE,
        )

    def append_prepared(self, objective_id: str, record: PreparedRecord) -> AppendResult:
        if self.unresolved_records:
            raise UnresolvedOperationError("an operation is already unresolved")
        self.prepared.append(record)
        self.unresolved_records[record.operation_id] = record
        return AppendResult(record.operation_id, EventRole.PREPARED, existed=False)

    def append_outcome(self, objective_id: str, record: OutcomeRecord) -> AppendResult:
        self.outcomes.append(record)
        moved = self.unresolved_records.pop(record.operation_id, None)
        if moved is not None and record.role in (EventRole.COMPLETED, EventRole.ABANDONED):
            self.completed.append((moved, record))
        elif moved is not None:
            self.unresolved_records[record.operation_id] = moved
            self.accepted_records[record.operation_id] = record
        return AppendResult(record.operation_id, record.role, existed=False)

    def write_checkpoints(
        self, plan_id: str, *, parent_checkpoint_sha: str, published_head_sha: str
    ) -> None:
        self.checkpoints.append((plan_id, parent_checkpoint_sha, published_head_sha))
        assert self.world is not None
        self.world.checkpoint_state[plan_id] = (parent_checkpoint_sha, published_head_sha)


class _SharedWorld:
    """The shared stateful backend world: plan headers, PRs, one native stack, objectives —
    everything that is durable OUTSIDE any machine's filesystem."""

    def __init__(self) -> None:
        self.persistence = _SharedPersistence()
        self.persistence.world = self
        # (node_id, plan_id, pr_number|None, expected_pr_base|None) bottom→top.
        self.layer_specs: list[dict[str, object]] = []
        self.checkpoint_state: dict[str, tuple[str, str]] = {}
        self.pr_entries: dict[int, tuple[str, str, str]] = {}  # number -> (branch, base, state)
        self.next_pr = 77
        self.stack_members: list[int] | None = None
        self.stack_number: int | None = None
        self.stack_creates: list[tuple[int, ...]] = []
        self.stack_appends: list[tuple[int, tuple[int, ...]]] = []
        self.header_writes: list[tuple[str, dict[str, object]]] = []
        self.pr_creates: list[int] = []
        self.main_sha = ""
        # LAND state.
        self.probe_results: list[MergeAsyncProbe] = []
        self.pr_merged: dict[int, PrMergedEvidence] = {}
        self.finalize_calls: list[tuple[str, str]] = []
        self.objectives: dict[str, ObjectiveState] = {}
        self.closed_objectives: list[str] = []
        # TRANSFER state.
        self.objectives_by_run: dict[str, ObjectiveRef] = {}
        self.ownership: list[tuple[str, str, str]] = []
        self.identity: list[tuple[str, str, str | None]] = []
        self.cleared: list[str] = []
        self.finalized: list[tuple[str, str]] = []
        self.supersede_calls: list[str] = []
        self.plans: dict[str, PlanState] = {}
        self.backend_id = "github"

    # ------------------------------------------------------------- issues (both operations)

    def get_plan(self, *, issue_id: str) -> PlanState | None:
        found = self.plans.get(issue_id)
        if found is not None:
            return found
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
        self.header_writes.append((issue_id, dict(fields)))
        if set(fields) == {"objective_id", "objective_node_id"}:
            self.ownership.append(
                (issue_id, str(fields["objective_id"]), str(fields["objective_node_id"]))
            )
        elif set(fields) == {"delivery_lineage", "predecessor_plan_id"}:
            predecessor = fields["predecessor_plan_id"]
            self.identity.append(
                (
                    issue_id,
                    str(fields["delivery_lineage"]),
                    str(predecessor) if predecessor is not None else None,
                )
            )
        elif set(fields) == {
            "delivery_lineage",
            "predecessor_plan_id",
            "parent_checkpoint_sha",
            "published_head_sha",
        }:
            self.cleared.append(issue_id)
        state = self.plans.get(issue_id)
        if state is not None:
            header = dict(state.header)
            header.update(fields)
            self.plans[issue_id] = replace(state, header=header)
        pr_value = fields.get("pr")
        if isinstance(pr_value, str) and pr_value.isdigit():
            for spec in self.layer_specs:
                if spec["plan_id"] == issue_id:
                    spec["pr_number"] = int(pr_value)
        return PlanHeaderUpdate(fields_updated=tuple(fields), dry_run=False)

    # ------------------------------------------------------------- objectives (LAND/TRANSFER)

    def get_objective(self, *, objective_id: str) -> ObjectiveState | None:
        return self.objectives.get(objective_id)

    def close_objective(self, *, objective_id: str, dry_run: bool = False) -> bool:
        self.closed_objectives.append(objective_id)
        state = self.objectives.get(objective_id)
        if state is not None:
            self.objectives[objective_id] = ObjectiveState(
                id=state.id,
                url=state.url,
                title=state.title,
                header=state.header,
                nodes=state.nodes,
                state="closed",
            )
        return True

    def find_objective(self, *, run_id: str) -> ObjectiveRef | None:
        return self.objectives_by_run.get(run_id)

    def supersede_objective(self, **kwargs) -> ObjectiveRef | None:
        self.supersede_calls.append(str(kwargs["run_id"]))
        return self.objectives_by_run.get(str(kwargs["run_id"]))

    def finalize_supersession(self, *, old_objective_id: str, new_objective_id: str) -> bool:
        self.finalized.append((old_objective_id, new_objective_id))
        old = self.objectives.get(old_objective_id)
        if old is not None:
            self.objectives[old_objective_id] = ObjectiveState(
                id=old.id,
                url=old.url,
                title=old.title,
                header={**old.header, "superseded_by": new_objective_id},
                nodes=old.nodes,
                state=old.state,
            )
        return True


# ----------------------------------------------------------------- one machine


class _Machine:
    """One machine: its own clone + separately constructed seams over the shared world.

    Every git seam asserts it received THIS machine's clone root — the other machine's
    tree is unreachable by construction (`seen_roots` additionally records every root any
    seam saw, so a test can assert B's phase never touched A's path)."""

    def __init__(self, name: str, root: Path, shared: _SharedWorld) -> None:
        self.name = name
        self.root = root
        self.shared = shared
        self.seen_roots: set[Path] = set()

    def _own(self, repo: Path) -> Path:
        self.seen_roots.add(repo)
        assert repo == self.root, (
            f"machine {self.name} seam received a foreign root {repo} (own: {self.root})"
        )
        return repo

    # ------------------------------------------------------------- REAL git seams

    def _fetch(self, repo: Path, refspecs: list[str]) -> None:
        git_mod.fetch_refspecs(self._own(repo), refspecs)

    def _remote_head(self, repo: Path, branch: str) -> str | None:
        return git_mod.remote_branch_head(self._own(repo), branch)

    def _local_head(self, repo: Path, ref: str) -> str | None:
        return git_mod.resolve_commit(self._own(repo), ref)

    def _is_ancestor(self, repo: Path, ancestor: str, head: str) -> bool:
        self._own(repo)
        return (
            subprocess.run(
                ["git", "merge-base", "--is-ancestor", ancestor, head],
                cwd=repo,
                check=False,
                capture_output=True,
            ).returncode
            == 0
        )

    def _push(self, cwd: Path, branch: str, *, expected_remote_sha: str | None) -> None:
        git_mod.push_with_exact_lease(
            self._own(cwd), branch, expected_remote_sha=expected_remote_sha
        )

    # ------------------------------------------------------------- shared-world seams

    def _reconstruct(self, root: Path, objective_id: str) -> DeliveryTrain:
        self.seen_roots.add(root)
        layers: list[TrainLayer] = []
        for spec in self.shared.layer_specs:
            plan_id = str(spec["plan_id"])
            cp = self.shared.checkpoint_state.get(plan_id)
            pr_number = spec.get("pr_number")
            layers.append(
                TrainLayer(
                    node_id=str(spec["node_id"]),
                    plan_id=plan_id,
                    branch=f"plan-{plan_id}",
                    pr_number=pr_number if isinstance(pr_number, int) else None,
                    intent=LayerIntent.PLANNED,
                    publication=(
                        LayerPublication.PUBLISHED if cp else LayerPublication.UNPUBLISHED
                    ),
                    git=LayerGit.SYNCED if cp else LayerGit.ABSENT,
                    pr=LayerPr.DRAFT if isinstance(pr_number, int) else LayerPr.ABSENT,
                    membership=LayerMembership.NOT_APPLICABLE,
                    writer=LayerWriter.FREE,
                    finalization=LayerFinalization.NOT_MERGED,
                    parent_checkpoint_sha=cp[0] if cp else None,
                    published_head_sha=cp[1] if cp else None,
                    observed_remote_head_sha=None,
                    observed_pr_base=None,
                    expected_pr_base=(
                        str(spec["expected_pr_base"])
                        if spec.get("expected_pr_base") is not None
                        else None
                    ),
                )
            )
        prefix = 0
        for layer in layers:
            if layer.publication is not LayerPublication.PUBLISHED:
                break
            prefix += 1
        unresolved = None
        if self.shared.persistence.unresolved_records:
            op_id = next(iter(self.shared.persistence.unresolved_records))
            record = self.shared.persistence.unresolved_records[op_id]
            unresolved = UnresolvedOperationFacts(
                operation_id=op_id, kind=record.operation_kind.value, prepared_created="t0"
            )
        next_node = layers[prefix].node_id if prefix < len(layers) else None
        ready = next_node is not None and unresolved is None
        return DeliveryTrain(
            objective_id=OBJECTIVE,
            objective_url="u",
            delivery_lineage=LINEAGE,
            base="main",
            redirected_from=None,
            layers=tuple(layers),
            published_prefix_len=prefix,
            unresolved_operation=unresolved,
            findings=(),
            build_readiness=BuildReadiness(
                next_node_id=next_node, ready=ready, reason=None if ready else "veto"
            ),
            observed_base_head_sha=self.shared.main_sha,
        )

    def _pr_facts(self, *, number: int, repo_root: Path) -> PrDeliveryFacts | None:
        entry = self.shared.pr_entries.get(number)
        if entry is None:
            return None
        branch, base, state = entry
        # The PR head mirrors the branch's REAL origin head (observed via THIS clone).
        head = git_mod.remote_branch_head(self._own(repo_root), branch)
        return PrDeliveryFacts(
            number=number,
            state=state,
            is_draft=True,
            base_ref=base,
            head_ref=branch,
            head_sha=head or "",
        )

    def _stack_facts(self) -> StackRestFacts | None:
        members = self.shared.stack_members
        if members is None:
            return None
        entries = tuple(
            StackRestEntry(
                pr_number=n, state="open", draft=True, merged=False, head_ref="", head_sha=""
            )
            for n in members
        )
        number = self.shared.stack_number if self.shared.stack_number is not None else 9
        return StackRestFacts(number=number, size=len(entries), entries=entries)

    def _stack_read(self, *, number: int, repo_root: Path) -> StackRestFacts | None:
        self.seen_roots.add(repo_root)
        members = self.shared.stack_members
        if members is None or number not in members:
            return None
        return self._stack_facts()

    def _stack_mutation(self, members: list[int]) -> StackMutationOutcome:
        self.shared.stack_members = list(members)
        if self.shared.stack_number is None:
            self.shared.stack_number = 9
        facts = self._stack_facts()
        assert facts is not None
        return StackMutationOutcome(
            applied=True,
            status=201,
            retry_after_seconds=None,
            rate_limited=False,
            raw_detail="",
            stack=facts,
        )

    def _stack_create(self, *, pull_requests, repo_root) -> StackMutationOutcome:
        self.shared.stack_creates.append(tuple(pull_requests))
        return self._stack_mutation(list(pull_requests))

    def _stack_append(self, *, stack_number, pull_requests, repo_root) -> StackMutationOutcome:
        self.shared.stack_appends.append((stack_number, tuple(pull_requests)))
        return self._stack_mutation([*(self.shared.stack_members or []), *pull_requests])

    def _create_pr(self, *, head, base, title, body, repo_root, draft) -> PullRequest:
        existing = next(
            (n for n, (branch, _b, _s) in self.shared.pr_entries.items() if branch == head),
            None,
        )
        if existing is not None:
            branch, pr_base, state = self.shared.pr_entries[existing]
            return PullRequest(
                number=existing,
                url=f"u/pr/{existing}",
                is_draft=True,
                state=state,
                existed=True,
                base_ref=pr_base,
                head_ref=branch,
            )
        number = self.shared.next_pr
        self.shared.next_pr += 1
        self.shared.pr_entries[number] = (head, base, "OPEN")
        self.shared.pr_creates.append(number)
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
        entry = self.shared.pr_entries.get(number)
        if entry is None:
            return None
        branch, base, state = entry
        return PullRequest(
            number=number,
            url=f"u/pr/{number}",
            is_draft=True,
            state=state,
            existed=True,
            base_ref=base,
            head_ref=branch,
        )

    def _pr_for_branch(self, *, branch, repo_root) -> PullRequest | None:
        for number, (head, _base, state) in self.shared.pr_entries.items():
            if head == branch and state == "OPEN":
                return self._get_pr(number=number, repo_root=repo_root)
        return None

    # ------------------------------------------------------------- LAND seams

    def _merge_probe(self, *, number: int, uuid: str, repo_root: Path) -> MergeAsyncProbe:
        if not self.shared.probe_results:
            return MergeAsyncProbe(state="unreadable", sha=None, message="unscripted")
        return self.shared.probe_results.pop(0)

    def _merged_evidence(self, *, number: int, repo_root: Path) -> PrMergedEvidence | None:
        return self.shared.pr_merged.get(number)

    def _finalize(self, repo_root: Path, *, landed, pr_base: str, close_objective_on_complete=True):
        assert close_objective_on_complete is False
        self.shared.finalize_calls.append((landed.plan_id, pr_base))
        return LandFinalization(
            learn_state="pending",
            plan_issue_closed=True,
            objective=ObjectiveLandUpdate(OBJECTIVE, (), None),
            learn=LearnConsumeUpdate((), "no_consumed_learn"),
        )

    # ------------------------------------------------------------- drivers

    @contextlib.contextmanager
    def _lock(self, root: Path) -> Iterator[None]:
        yield

    def _transfer_seams(self, root: Path) -> transfer_mod.TransferSeams:
        return transfer_mod.TransferSeams(
            repo_root=root,
            store=self.shared,
            issues=self.shared,
            persistence=self.shared.persistence,
            reconstruct=self._reconstruct,
            now=lambda: NOW,
        )

    def recover(
        self,
        *,
        abandon: bool = False,
        approve: Callable[[recover.AbandonPreview], bool] | None = None,
    ) -> recover.RecoverResult:
        return recover.recover_operations(
            self.root,
            objective_id=OBJECTIVE,
            worktree_root=self.root / ".wt",
            abandon=abandon,
            approve=approve,
            reconstruct=self._reconstruct,
            persistence_factory=lambda root: self.shared.persistence,
            transfer_seams_factory=self._transfer_seams,
            pr_facts=self._pr_facts,
            stack_read=self._stack_read,
            pr_for_branch=self._pr_for_branch,
            merge_probe=self._merge_probe,
            merged_evidence=self._merged_evidence,
            finalize=self._finalize,
            issues_factory=lambda root: self.shared,
            store_factory=lambda root: self.shared,
            fetch=self._fetch,
            remote_head=self._remote_head,
            list_refs=lambda root, prefix: [],
            worktree_remove=lambda root, path: None,
            worktree_prune=lambda root: None,
            iter_manifests=lambda root: continuation.ManifestScan(manifests=(), unparseable=()),
            worktree_dirs=lambda root: [],
            worktree_admin_dirs=lambda root: [],
            lock=self._lock,
            sleep=lambda s: None,
            now=lambda: NOW,
        )

    def publish(self, plan_id: str, *, run_id: str = "01RUNB") -> PublishResult.Layer:
        machine = self

        class _Persistence:
            def get_plan(self, *, issue_id: str) -> PlanState | None:
                return machine.shared.get_plan(issue_id=issue_id)

            def get_plan_body(self, *, issue_id: str) -> str | None:
                del issue_id
                return None

            def update_plan_header(
                self, *, issue_id: str, fields: dict[str, object]
            ) -> PlanHeaderUpdate:
                return machine.shared.update_plan_header(issue_id=issue_id, fields=fields)

            def read_journal(self, objective_id: str) -> JournalFold:
                return machine.shared.persistence.read_journal(objective_id)

            def append_prepared(self, objective_id: str, record: PreparedRecord) -> AppendResult:
                return machine.shared.persistence.append_prepared(objective_id, record)

            def append_outcome(self, objective_id: str, record: OutcomeRecord) -> AppendResult:
                return machine.shared.persistence.append_outcome(objective_id, record)

            def write_checkpoints(
                self,
                plan_id: str,
                *,
                parent_checkpoint_sha: str,
                published_head_sha: str,
            ) -> None:
                machine.shared.persistence.write_checkpoints(
                    plan_id,
                    parent_checkpoint_sha=parent_checkpoint_sha,
                    published_head_sha=published_head_sha,
                )

        class _Git:
            @property
            def repo_root(self) -> Path:
                return machine.root

            def fetch_refs(self, refs: tuple[str, ...]) -> None:
                machine._fetch(machine.root, list(refs))

            def remote_branch_sha(self, branch: str) -> str | None:
                return machine._remote_head(machine.root, branch)

            def resolve_commit(self, ref: str, *, cwd: Path | None = None) -> str | None:
                return machine._local_head(cwd or machine.root, ref)

            def is_ancestor(self, ancestor_sha: str, head_sha: str) -> bool:
                return machine._is_ancestor(machine.root, ancestor_sha, head_sha)

            def push_with_exact_lease(
                self, branch: str, *, expected_remote_sha: str | None
            ) -> None:
                machine._push(machine.root, branch, expected_remote_sha=expected_remote_sha)

        class _GitHub:
            def stack_capability(self) -> bool:
                return True

            def pr_facts(self, number: int) -> PrDeliveryFacts | None:
                return machine._pr_facts(number=number, repo_root=machine.root)

            def strict_stack(self, number: int) -> StackRestFacts | None:
                return machine._stack_read(number=number, repo_root=machine.root)

            def create_stack(self, pull_requests: tuple[int, ...]) -> StackMutationOutcome:
                return machine._stack_create(pull_requests=pull_requests, repo_root=machine.root)

            def append_stack(
                self, stack_number: int, *, pull_requests: tuple[int, ...]
            ) -> StackMutationOutcome:
                return machine._stack_append(
                    stack_number=stack_number,
                    pull_requests=pull_requests,
                    repo_root=machine.root,
                )

            def create_pr(
                self, *, head: str, base: str, title: str, body: str, draft: bool
            ) -> PullRequest:
                return machine._create_pr(
                    head=head,
                    base=base,
                    title=title,
                    body=body,
                    repo_root=machine.root,
                    draft=draft,
                )

            def get_pr(self, number: int) -> PullRequest | None:
                return machine._get_pr(number=number, repo_root=machine.root)

            def update_pr_body(self, number: int, *, body: str):
                return machine._update_pr_body(number=number, body=body, repo_root=machine.root)

            def update_pr_base(self, number: int, *, base: str) -> None:
                machine._update_pr_base(number=number, base=base, repo_root=machine.root)

            def reopen_pr(self, number: int) -> None:
                machine._reopen_pr(number=number, repo_root=machine.root)

            def pr_for_branch(self, branch: str) -> PullRequest | None:
                return machine._pr_for_branch(branch=branch, repo_root=machine.root)

        class _Delivery(Delivery):
            def __init__(self) -> None:
                super().__init__(
                    persistence=cast("DeliveryPersistence", _Persistence()),
                    git=cast("DeliveryGit", _Git()),
                    github=cast("DeliveryGitHub", _GitHub()),
                )

            def status(self, request: StatusRequest) -> StatusResult:
                train = machine._reconstruct(machine.root, request.objective_id)
                return StatusResult(
                    train.objective_id,
                    train.objective_url,
                    train.redirected_from,
                    train,
                    None,
                )

        runtime = publish._PublishRuntime(
            mint_operation_id=mint_operation_id,
            now=lambda: NOW,
            sleep=lambda _seconds: None,
            validate_pr_body=lambda body, *, pr_number: (),
        )
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(publish, "_DEFAULT_PUBLISH_RUNTIME", runtime)
            result = _Delivery().publish(
                PublishRequest(kind="layer", plan_id=plan_id, run_id=run_id)
            )
        if result.layer is None:
            raise AssertionError("layer publish returned no layer detail")
        return result.layer

    def _update_pr_body(self, *, number, body, repo_root):
        from perk.github.prs import PrBodyUpdate

        return PrBodyUpdate(number=number, dry_run=False)

    def _update_pr_base(self, *, number, base, repo_root) -> None:
        branch, _old, state = self.shared.pr_entries[number]
        self.shared.pr_entries[number] = (branch, base, state)

    def _reopen_pr(self, *, number, repo_root) -> None:
        branch, base, _state = self.shared.pr_entries[number]
        self.shared.pr_entries[number] = (branch, base, "OPEN")


# ----------------------------------------------------------------- fixture builders


def _two_machines(tmp_path: Path) -> tuple[Path, _Machine, _Machine, _SharedWorld, dict[str, str]]:
    """One bare origin; machine A builds and pushes the three-layer train; machine B is a
    separately created FRESH clone (its own objects, its own config, nothing copied)."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    a_root = tmp_path / "machine-a"
    a_root.mkdir()
    _git(a_root, "init", "-q")
    _git(a_root, "config", "user.email", "a@example.com")
    _git(a_root, "config", "user.name", "machine a")
    _git(a_root, "remote", "add", "origin", str(origin))
    _git(a_root, "checkout", "-q", "-b", "main")
    shas: dict[str, str] = {}
    shas["main"] = _commit(a_root, "base")
    _git(a_root, "checkout", "-q", "-b", "plan-101")
    shas["p1"] = _commit(a_root, "one")
    _git(a_root, "checkout", "-q", "-b", "plan-102")
    shas["p2"] = _commit(a_root, "two")
    _git(a_root, "checkout", "-q", "-b", "plan-103")
    shas["p3"] = _commit(a_root, "three")
    _git(a_root, "push", "-q", "origin", "main", "plan-101", "plan-102", "plan-103")
    b_root = tmp_path / "machine-b"
    _git(tmp_path, "clone", "-q", str(origin), str(b_root))
    shared = _SharedWorld()
    shared.main_sha = shas["main"]
    machine_a = _Machine("a", a_root, shared)
    machine_b = _Machine("b", b_root, shared)
    return origin, machine_a, machine_b, shared, shas


def _seed_sync_world(shared: _SharedWorld, shas: dict[str, str]) -> None:
    shared.layer_specs = [
        {"node_id": "1.1", "plan_id": "101", "pr_number": 201, "expected_pr_base": "main"},
        {"node_id": "1.2", "plan_id": "102", "pr_number": 202, "expected_pr_base": "plan-101"},
        {"node_id": "1.3", "plan_id": "103", "pr_number": 203, "expected_pr_base": "plan-102"},
    ]
    shared.checkpoint_state = {
        "101": (shas["main"], shas["p1"]),
        "102": (shas["p1"], shas["p2"]),
        "103": (shas["p2"], shas["p3"]),
    }
    shared.pr_entries = {
        201: ("plan-101", "main", "OPEN"),
        202: ("plan-102", "plan-101", "OPEN"),
        203: ("plan-103", "plan-102", "OPEN"),
    }
    shared.stack_members = [201, 202, 203]
    shared.stack_number = 9


def _sync_record(shas: dict[str, str], *, c2: str, r3: str) -> PreparedRecord:
    return PreparedRecord(
        operation_id=mint_operation_id(),
        operation_kind=OperationKind.SYNC,
        delivery_lineage=LINEAGE,
        objective_id=OBJECTIVE,
        run_id="01RUNA",
        created="2026-01-01T00:00:00Z",
        affected_plans=("102", "103"),
        before={
            "base": None,
            "branches": [
                {"ref": "plan-102", "sha": shas["p2"]},
                {"ref": "plan-103", "sha": shas["p3"]},
            ],
            "prs": [
                {"number": 202, "head_sha": shas["p2"], "base": "plan-101"},
                {"number": 203, "head_sha": shas["p3"], "base": "plan-102"},
            ],
            "stack": {"members": [201, 202, 203]},
        },
        after={
            "branches": [{"ref": "plan-102", "sha": c2}, {"ref": "plan-103", "sha": r3}],
            "prs": [
                {"number": 202, "head_sha": c2, "base": "plan-101"},
                {"number": 203, "head_sha": r3, "base": "plan-102"},
            ],
            "base_parent": None,
        },
    )


def _amend_and_transplant(machine_a: _Machine, shas: dict[str, str]) -> tuple[str, str]:
    """Machine A's recomputed cascade candidates: layer 102 amended onto P1, layer 103
    transplanted onto the amended head (real commits in clone A)."""
    a = machine_a.root
    _git(a, "checkout", "-q", "-B", "plan-102", shas["p1"])
    c2 = _commit(a, "two-amended")
    _git(a, "checkout", "-q", "-B", "plan-103", c2)
    r3 = _commit(a, "three-transplanted")
    return c2, r3


def _assert_converged_journal(shared: _SharedWorld, operation_id: str, role: EventRole) -> None:
    assert shared.persistence.unresolved_records == {}
    outcomes = [o for o in shared.persistence.outcomes if o.operation_id == operation_id]
    assert [o.role for o in outcomes] == [role]


def _assert_b_never_saw_a(machine_a: _Machine, machine_b: _Machine) -> None:
    assert machine_a.root not in machine_b.seen_roots
    assert all(machine_a.root not in path.parents for path in machine_b.seen_roots)


# ----------------------------------------------------------------- SYNC arms


def test_sync_all_after_concludes_from_a_fresh_clone(tmp_path):
    # Machine A died after the REAL atomic push (both refs moved on the origin), before
    # verification. Machine B — a separately initialized clone with separately constructed
    # seams — rolls the recorded operation forward from the durable authorities alone:
    # checkpoints + completed written from B; the origin refs stay exactly where A left them.
    origin, machine_a, machine_b, shared, shas = _two_machines(tmp_path)
    _seed_sync_world(shared, shas)
    c2, r3 = _amend_and_transplant(machine_a, shas)
    git_mod.push_atomic_with_leases(
        machine_a.root,
        [
            git_mod.RefUpdate(branch="plan-102", expected_remote_sha=shas["p2"], new_sha=c2),
            git_mod.RefUpdate(branch="plan-103", expected_remote_sha=shas["p3"], new_sha=r3),
        ],
    )
    record = _sync_record(shas, c2=c2, r3=r3)
    shared.persistence.unresolved_records[record.operation_id] = record

    result = machine_b.recover()

    (row,) = result.operations
    assert row.kind == "sync"
    assert row.classification == "all_after" and row.action == "rolled_forward"
    _assert_converged_journal(shared, record.operation_id, EventRole.COMPLETED)
    assert shared.persistence.checkpoints == [
        ("102", shas["p1"], c2),
        ("103", c2, r3),
    ]
    # The origin refs are already correct and UNTOUCHED by B's conclusion.
    assert _git(origin, "rev-parse", "plan-102").strip() == c2
    assert _git(origin, "rev-parse", "plan-103").strip() == r3
    _assert_b_never_saw_a(machine_a, machine_b)


def test_sync_all_before_abandons_with_proof_from_a_fresh_clone(tmp_path):
    # Machine A died after `append_prepared` — the atomic push never ran (the origin still
    # holds the before refs). Machine B's recover proves all-before against the REAL origin
    # and abandons with the post-confirmation observation as proof; nothing moves.
    origin, machine_a, machine_b, shared, shas = _two_machines(tmp_path)
    _seed_sync_world(shared, shas)
    c2, r3 = _amend_and_transplant(machine_a, shas)  # candidates existed only in A's tree
    record = _sync_record(shas, c2=c2, r3=r3)
    shared.persistence.unresolved_records[record.operation_id] = record

    previews: list[recover.AbandonPreview] = []

    def approve(preview: recover.AbandonPreview) -> bool:
        previews.append(preview)
        return True

    result = machine_b.recover(abandon=True, approve=approve)

    (row,) = result.operations
    assert row.classification == "all_before" and row.action == "abandoned"
    assert len(previews) == 1
    _assert_converged_journal(shared, record.operation_id, EventRole.ABANDONED)
    (abandoned,) = shared.persistence.outcomes
    assert abandoned.observed == {
        "branches": [
            {"ref": "plan-102", "sha": shas["p2"]},
            {"ref": "plan-103", "sha": shas["p3"]},
        ]
    }
    # The origin never moved.
    assert _git(origin, "rev-parse", "plan-102").strip() == shas["p2"]
    assert _git(origin, "rev-parse", "plan-103").strip() == shas["p3"]
    _assert_b_never_saw_a(machine_a, machine_b)


# ----------------------------------------------------------------- PUBLISH arms


def _publish_record(
    *,
    plan_id: str,
    branch: str,
    before_sha: str | None,
    after_sha: str,
    parent_branch: str,
    stack_after: dict[str, object],
    stack_before: dict[str, object],
    pr_before: dict[str, object] | None = None,
) -> PreparedRecord:
    return PreparedRecord(
        operation_id=mint_operation_id(),
        operation_kind=OperationKind.PUBLISH,
        delivery_lineage=LINEAGE,
        objective_id=OBJECTIVE,
        run_id="01RUNA",
        created="2026-01-01T00:00:00Z",
        affected_plans=(plan_id,),
        before={
            "branch": {"ref": branch, "sha": before_sha},
            "pr": pr_before or {"number": None, "base": None, "head_sha": None, "state": None},
            "stack": stack_before,
        },
        after={
            "branch": {"ref": branch, "sha": after_sha},
            "pr": {"base": parent_branch, "head_sha": after_sha},
            "stack": stack_after,
        },
    )


def test_publish_bottom_layer_all_after_reports_then_submit_resume_completes(tmp_path):
    # Machine A died after the branch push + PR create on a BOTTOM layer (its `after` has
    # no stack membership — a true all-after). Machine B's recover REPORTS the owning
    # /submit resume (conclude-only posture, never a roll-forward); `Delivery.publish` with
    # resume from B then completes the RECORDED operation: identity + checkpoints +
    # completed from B, no duplicate non-idempotent effect (no second PR, no push).
    origin, machine_a, machine_b, shared, shas = _two_machines(tmp_path)
    shared.layer_specs = [
        {"node_id": "1", "plan_id": "101", "pr_number": None, "expected_pr_base": "main"},
        {"node_id": "2", "plan_id": "102", "pr_number": None, "expected_pr_base": None},
    ]
    # This arm's world has NO published layers: the seeded plan branches leave the origin
    # (the fixture pushed them for the train-shaped arms), so the fresh publish's absence
    # lease is real.
    a = machine_a.root
    _git(a, "push", "-q", "origin", "--delete", "plan-101", "plan-102", "plan-103")
    # A's death-constructed effects: the REAL push of plan-101 (built on main) + the PR.
    _git(a, "checkout", "-q", "-B", "plan-101", shas["main"])
    c1 = _commit(a, "layer-one-candidate")
    git_mod.push_with_exact_lease(a, "plan-101", expected_remote_sha=None)
    shared.pr_entries[77] = ("plan-101", "main", "OPEN")
    shared.next_pr = 78
    record = _publish_record(
        plan_id="101",
        branch="plan-101",
        before_sha=None,
        after_sha=c1,
        parent_branch="main",
        stack_before={"members": None},
        stack_after={"not_applicable": True},
    )
    shared.persistence.unresolved_records[record.operation_id] = record

    report = machine_b.recover()
    (row,) = report.operations
    assert row.kind == "publish"
    assert row.classification == "all_after" and row.action == "reported"
    assert "rerun `/submit` for plan #101" in row.detail
    assert record.operation_id in shared.persistence.unresolved_records  # conclude-only

    # `/submit` runs from a checkout that HAS the plan branch (the remote runner's fresh
    # checkout fetches it) — localize the branch objects in B the same way before resuming.
    _git(machine_b.root, "fetch", "-q", "origin", "plan-101")
    result = machine_b.publish("101")
    assert result.resumed is True and result.operation_id == record.operation_id
    assert result.pr.number == 77
    _assert_converged_journal(shared, record.operation_id, EventRole.COMPLETED)
    assert shared.pr_creates == []  # the discovery re-entry never minted a second PR
    assert shared.persistence.checkpoints == [("101", shas["main"], c1)]
    identity = [w for w in shared.header_writes if w[0] == "101"]
    assert len(identity) == 1 and identity[0][1]["pr"] == "77"
    assert _git(origin, "rev-parse", "plan-101").strip() == c1  # B never re-pushed
    _assert_b_never_saw_a(machine_a, machine_b)


def test_publish_non_bottom_partial_reports_mixed_then_submit_resume_converges(tmp_path):
    # Machine A died after the second layer's PR create but BEFORE the stack mutation. The
    # classification is layer-position-dependent: a non-bottom `after` includes stack
    # membership, so machine B's recover honestly reports MIXED (report-only, fail closed).
    # `Delivery.publish`'s own resume from B then rolls forward under the recorded operation
    # and completes the stack convergence — the cross-machine stack registration.
    origin, machine_a, machine_b, shared, shas = _two_machines(tmp_path)
    shared.layer_specs = [
        {"node_id": "1", "plan_id": "101", "pr_number": 55, "expected_pr_base": "main"},
        {"node_id": "2", "plan_id": "102", "pr_number": None, "expected_pr_base": None},
    ]
    shared.checkpoint_state = {"101": (shas["main"], shas["p1"])}
    shared.pr_entries[55] = ("plan-101", "main", "OPEN")
    # Only the published layer-1 branch exists on the origin; the layer-2 candidate's
    # absence lease is real.
    a = machine_a.root
    _git(a, "push", "-q", "origin", "--delete", "plan-102", "plan-103")
    # A's death-constructed effects: the REAL push of the layer-2 candidate + its PR.
    _git(a, "checkout", "-q", "-B", "plan-102", shas["p1"])
    c2 = _commit(a, "layer-two-candidate")
    git_mod.push_with_exact_lease(a, "plan-102", expected_remote_sha=None)
    shared.pr_entries[78] = ("plan-102", "plan-101", "OPEN")
    shared.next_pr = 79
    record = _publish_record(
        plan_id="102",
        branch="plan-102",
        before_sha=None,
        after_sha=c2,
        parent_branch="plan-101",
        stack_before={"members": None},
        stack_after={"members": [55, "self"]},
    )
    shared.persistence.unresolved_records[record.operation_id] = record

    report = machine_b.recover()
    (row,) = report.operations
    assert row.classification == "mixed" and row.action == "reported"  # the honest report
    assert record.operation_id in shared.persistence.unresolved_records

    # `/submit` runs from a checkout that HAS the plan branch (the remote runner's fresh
    # checkout fetches it) — localize the branch objects in B the same way before resuming.
    _git(machine_b.root, "fetch", "-q", "origin", "plan-102")
    result = machine_b.publish("102")
    assert result.resumed is True and result.operation_id == record.operation_id
    assert result.pr.number == 78
    _assert_converged_journal(shared, record.operation_id, EventRole.COMPLETED)
    assert shared.stack_creates == [(55, 78)]  # the stack converged exactly once, from B
    assert shared.pr_creates == []  # no duplicate PR
    assert shared.persistence.checkpoints == [("102", shas["p1"], c2)]
    assert _git(origin, "rev-parse", "plan-102").strip() == c2  # B never re-pushed
    _assert_b_never_saw_a(machine_a, machine_b)


# ----------------------------------------------------------------- the LAND arm


def test_land_accepted_handle_concludes_from_a_fresh_clone(tmp_path):
    # Machine A died after the `accepted` append (the journaled merge-request handle).
    # Machine B probes the recorded UUID (merged), corroborates each layer PR, journals
    # `completed`, finalizes bottom→top, and runs the state-aware close — all from B.
    _origin, machine_a, machine_b, shared, shas = _two_machines(tmp_path)
    shared.layer_specs = [
        {"node_id": "1.1", "plan_id": "101", "pr_number": 201, "expected_pr_base": "main"},
        {"node_id": "1.2", "plan_id": "102", "pr_number": 202, "expected_pr_base": "plan-101"},
    ]
    shared.checkpoint_state = {
        "101": (shas["main"], shas["p1"]),
        "102": (shas["p1"], shas["p2"]),
    }
    done = objective.NodeStatus.DONE
    shared.objectives[OBJECTIVE] = ObjectiveState(
        id=OBJECTIVE,
        url="u",
        title="t",
        header={},
        nodes=(
            objective.ObjectiveNode(id="1.1", description="a", status=done, pr="#101"),
            objective.ObjectiveNode(id="1.2", description="b", status=done, pr="#102"),
        ),
    )
    record = PreparedRecord(
        operation_id=mint_operation_id(),
        operation_kind=OperationKind.LAND,
        delivery_lineage=LINEAGE,
        objective_id=OBJECTIVE,
        run_id="01RUNA",
        created="2026-01-01T00:00:00Z",
        affected_plans=("101", "102"),
        before={
            "mode": "stack_merge_async",
            "merge_method": "squash",
            "base": "main",
            "top_pr_number": 202,
            "top_head_sha": shas["p2"],
            "layers": [
                {
                    "node_id": "1.1",
                    "plan_id": "101",
                    "pr_number": 201,
                    "base_sha": shas["main"],
                    "head_sha": shas["p1"],
                },
                {
                    "node_id": "1.2",
                    "plan_id": "102",
                    "pr_number": 202,
                    "base_sha": shas["p1"],
                    "head_sha": shas["p2"],
                },
            ],
        },
        after={"merged_pr_numbers": [201, 202], "base": "main"},
    )
    shared.persistence.unresolved_records[record.operation_id] = record
    shared.persistence.accepted_records[record.operation_id] = OutcomeRecord(
        operation_id=record.operation_id,
        role=EventRole.ACCEPTED,
        created="2026-01-01T00:00:01Z",
        observed={
            "uuid": "u-1",
            "merge_method": "squash",
            "merge_action": "direct_merge",
            "expected_head_sha": shas["p2"],
            "http_status": 202,
        },
    )
    shared.probe_results = [MergeAsyncProbe(state="merged", sha=M2, message="")]
    shared.pr_merged = {
        201: PrMergedEvidence(
            number=201,
            state="MERGED",
            merge_commit_sha=M1,
            head_sha=shas["p1"],
            head_ref="plan-101",
            base_ref="main",
        ),
        202: PrMergedEvidence(
            number=202,
            state="MERGED",
            merge_commit_sha=M2,
            head_sha=shas["p2"],
            head_ref="plan-102",
            base_ref="main",  # retargeted onto the base at merge — a legitimate landing
        ),
    }

    result = machine_b.recover()

    (row,) = result.operations
    assert row.kind == "land"
    assert row.classification == "all_after" and row.action == "rolled_forward"
    _assert_converged_journal(shared, record.operation_id, EventRole.COMPLETED)
    assert shared.finalize_calls == [("101", "main"), ("102", "plan-101")]
    assert result.objective_closed is True
    assert shared.closed_objectives == [OBJECTIVE]
    assert result.reconcile_evidence is not None
    assert [r.pr_number for r in result.reconcile_evidence.layers] == [201, 202]
    _assert_b_never_saw_a(machine_a, machine_b)


# ----------------------------------------------------------------- the TRANSFER arm


def test_transfer_manifest_rolls_forward_on_fresh_seams(tmp_path):
    # Machine A died mid-transfer: the successor exists (found by run_id + corroborated)
    # but ownership/finalize/completion never ran. Machine B constructs FRESH TransferSeams
    # (backend-only — the manifest is the durable authority; no git observation is needed)
    # and recover rolls the transfer forward: ownership stamped, projection verified, the
    # predecessor finalized, completion journaled — each effect exactly once.
    _origin, machine_a, machine_b, shared, _shas = _two_machines(tmp_path)
    del machine_a  # the transfer conclusion is backend-only; A contributed only the journal
    shared.layer_specs = [
        {"node_id": "9.1", "plan_id": "101", "pr_number": None, "expected_pr_base": None},
    ]
    record = PreparedRecord(
        operation_id=mint_operation_id(),
        operation_kind=OperationKind.TRANSFER,
        delivery_lineage=LINEAGE,
        objective_id=OBJECTIVE,
        run_id="01RUNTRANSFER",
        created="2026-01-01T00:00:00Z",
        affected_plans=("101",),
        before={
            "predecessor_objective_id": OBJECTIVE,
            "base": "main",
            "delivery": "stacked",
            "delivery_lineage": LINEAGE,
            "claimed_prefix": [],
            "carried_unpublished": [{"node_id": "1.1", "plan_id": "101"}],
        },
        after={
            "title": "Successor",
            "prose": "p",
            "base": "main",
            "delivery": "stacked",
            "delivery_lineage": LINEAGE,
            "roadmap_nodes": [
                {
                    "id": "9.1",
                    "slug": None,
                    "description": "carried work",
                    "status": "pending",
                    "pr": "#101",
                    "depends_on": None,
                    "adopt_issue": None,
                    "comment": None,
                }
            ],
            "carry_map": {},
        },
    )
    shared.persistence.unresolved_records[record.operation_id] = record
    shared.objectives[OBJECTIVE] = ObjectiveState(
        id=OBJECTIVE,
        url="u/500",
        title="Old",
        header={"delivery": "stacked", "delivery_lineage": LINEAGE},
        nodes=(),
    )
    shared.objectives_by_run["01RUNTRANSFER"] = ObjectiveRef(id="600", url="u/600", existed=True)
    shared.objectives["600"] = ObjectiveState(
        id="600",
        url="u/600",
        title="Successor",
        header={"supersedes": OBJECTIVE, "delivery_lineage": LINEAGE, "delivery": "stacked"},
        nodes=(
            objective.ObjectiveNode(
                id="9.1",
                description="carried work",
                status=objective.NodeStatus.PENDING,
                pr="#101",
            ),
        ),
    )
    shared.plans["101"] = PlanState(
        id="101",
        url="u/p",
        title="plan",
        header={"objective_id": OBJECTIVE, "objective_node_id": "1.1"},
        pr=None,
        state="OPEN",
    )

    result = machine_b.recover()

    (row,) = result.operations
    assert row.kind == "transfer"
    assert row.classification == "all_after" and row.action == "rolled_forward"
    _assert_converged_journal(shared, record.operation_id, EventRole.COMPLETED)
    # Each effect exactly once, driven from B's fresh seams.
    assert shared.supersede_calls == ["01RUNTRANSFER"]  # the found-arm converge
    assert shared.ownership == [("101", "600", "9.1")]
    assert shared.identity == [("101", LINEAGE, None)]
    assert shared.finalized == [(OBJECTIVE, "600")]
    completed = [o for o in shared.persistence.outcomes if o.role is EventRole.COMPLETED]
    assert len(completed) == 1
    assert completed[0].observed == {
        "successor_objective_id": "600",
        "run_id": "01RUNTRANSFER",
    }


def test_machines_share_no_local_state(tmp_path):
    # The zero-shared-local-state pin, by construction: separate clone paths, separate git
    # object stores, no copied metadata — only the origin and the backend world are shared.
    _origin, machine_a, machine_b, _shared, _shas = _two_machines(tmp_path)
    assert machine_a.root != machine_b.root
    assert (machine_a.root / ".git").is_dir() and (machine_b.root / ".git").is_dir()
    assert machine_b.root not in machine_a.root.parents
    assert machine_a.root not in machine_b.root.parents
    with pytest.raises(AssertionError, match="foreign root"):
        machine_b._own(machine_a.root)
