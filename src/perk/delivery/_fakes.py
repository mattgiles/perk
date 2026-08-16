"""Constructor-configured fakes for the delivery façade's aggregate authorities."""

from collections.abc import Mapping
from pathlib import Path

from perk.backends.issue_backend import PlanState
from perk.backends.objective_store import ObjectiveState
from perk.delivery.facade import DeliveryGit, DeliveryGitHub, DeliveryPersistence
from perk.delivery.journal import EventRole, JournalFold, OutcomeRecord, PreparedRecord, fold_events
from perk.delivery.persistence import AppendResult
from perk.delivery.train import (
    BaseHeadObservation,
    BranchPrView,
    PrFactsView,
    StackView,
    WorktreeFacts,
)
from perk.substrate import git as git_mod

type Call = tuple[object, ...]

_DEFAULT_MERGE_RULES = DeliveryGitHub.MergeRules(squash_allowed=True, merge_queue_required=False)


class _FailureMixin:
    def __init__(self, errors: Mapping[Call, Exception] | None) -> None:
        self._errors = dict(errors or {})

    def _raise_failure(self, call: Call) -> None:
        failure = self._errors.get(call)
        if failure is not None:
            raise failure


class FakeDeliveryPersistence(_FailureMixin, DeliveryPersistence):
    """Persistence authority fake for status, Prepare, and synchronization."""

    def __init__(
        self,
        *,
        objectives: Mapping[str, ObjectiveState] | None = None,
        plans: Mapping[str, PlanState] | None = None,
        journals: Mapping[str, JournalFold] | None = None,
        prepared_results: Mapping[str, AppendResult] | None = None,
        outcome_results: Mapping[str, AppendResult] | None = None,
        errors: Mapping[Call, Exception] | None = None,
    ) -> None:
        super().__init__(errors)
        self._objectives = dict(objectives or {})
        self._plans = dict(plans or {})
        self._journals = dict(journals or {})
        self._prepared_results = dict(prepared_results or {})
        self._outcome_results = dict(outcome_results or {})
        self.calls: list[Call] = []

    def get_objective(self, *, objective_id: str) -> ObjectiveState | None:
        call: Call = ("get_objective", objective_id)
        self.calls.append(call)
        self._raise_failure(call)
        return self._objectives.get(objective_id)

    def get_plan(self, *, issue_id: str) -> PlanState | None:
        call: Call = ("get_plan", issue_id)
        self.calls.append(call)
        self._raise_failure(call)
        return self._plans.get(issue_id)

    def read_journal(self, objective_id: str) -> JournalFold:
        call: Call = ("read_journal", objective_id)
        self.calls.append(call)
        self._raise_failure(call)
        seeded = self._journals.get(objective_id)
        if seeded is not None:
            return seeded
        state = self._objectives.get(objective_id)
        raw_lineage = state.header.get("delivery_lineage") if state is not None else None
        lineage = raw_lineage if isinstance(raw_lineage, str) else None
        return fold_events((), expected_lineage=lineage)

    def append_prepared(self, objective_id: str, record: PreparedRecord) -> AppendResult:
        call: Call = ("append_prepared", objective_id, record)
        self.calls.append(call)
        self._raise_failure(call)
        return self._prepared_results.get(
            record.operation_id,
            AppendResult(operation_id=record.operation_id, role=EventRole.PREPARED, existed=False),
        )

    def append_outcome(self, objective_id: str, record: OutcomeRecord) -> AppendResult:
        call: Call = ("append_outcome", objective_id, record)
        self.calls.append(call)
        self._raise_failure(call)
        return self._outcome_results.get(
            record.operation_id,
            AppendResult(operation_id=record.operation_id, role=record.role, existed=False),
        )

    def write_checkpoints(
        self,
        plan_id: str,
        *,
        parent_checkpoint_sha: str,
        published_head_sha: str,
    ) -> None:
        call: Call = (
            "write_checkpoints",
            plan_id,
            parent_checkpoint_sha,
            published_head_sha,
        )
        self.calls.append(call)
        self._raise_failure(call)


class FakeDeliveryGit(_FailureMixin, DeliveryGit):
    """Git authority fake for status, Prepare, and synchronization."""

    def __init__(
        self,
        *,
        repo_root: Path = Path("/repo"),
        trunk: str = "main",
        branches: Mapping[str, str] | None = None,
        resolutions: Mapping[str | tuple[Path, str], str] | None = None,
        push_urls: tuple[str, ...] = ("fake://origin",),
        push_urls_error: str | None = None,
        atomic_push_errors: Mapping[str, str] | None = None,
        ancestry: Mapping[tuple[str, str], bool | None] | None = None,
        worktrees: tuple[WorktreeFacts, ...] = (),
        base_heads: Mapping[str, BaseHeadObservation] | None = None,
        rebase_outcomes: Mapping[tuple[Path, str, str], git_mod.RebaseOutcome] | None = None,
        dirty_worktrees: frozenset[Path] = frozenset(),
        rebasing_worktrees: frozenset[Path] = frozenset(),
        refs: tuple[str, ...] = (),
        errors: Mapping[Call, Exception] | None = None,
    ) -> None:
        super().__init__(errors)
        self._repo_root = Path(repo_root)
        self._trunk = trunk
        self._branches = dict(branches or {})
        self._resolutions = dict(resolutions or {})
        self._push_urls = tuple(push_urls)
        self._push_urls_error = push_urls_error
        self._atomic_push_errors = dict(atomic_push_errors or {})
        self._ancestry = dict(ancestry or {})
        self._worktrees = tuple(worktrees)
        self._base_heads = dict(base_heads or {})
        self._rebase_outcomes = dict(rebase_outcomes or {})
        self._dirty_worktrees = frozenset(dirty_worktrees)
        self._rebasing_worktrees = frozenset(rebasing_worktrees)
        self._refs = tuple(refs)
        self.calls: list[Call] = []

    @property
    def repo_root(self) -> Path:
        return self._repo_root

    def trunk_branch(self) -> str:
        call: Call = ("trunk_branch",)
        self.calls.append(call)
        self._raise_failure(call)
        return self._trunk

    def fetch(self) -> None:
        call: Call = ("fetch",)
        self.calls.append(call)
        self._raise_failure(call)

    def fetch_refs(self, refs: tuple[str, ...]) -> None:
        call: Call = ("fetch_refs", *refs)
        self.calls.append(call)
        self._raise_failure(call)

    def resolve_commit(self, ref: str, *, cwd: Path | None = None) -> str | None:
        call: Call = ("resolve_commit", ref) if cwd is None else ("resolve_commit", ref, cwd)
        self.calls.append(call)
        self._raise_failure(call)
        if cwd is not None:
            resolved = self._resolutions.get((cwd, ref))
            if resolved is not None:
                return resolved
        return self._resolutions.get(ref)

    def remote_branch_sha(self, branch: str) -> str | None:
        call: Call = ("remote_branch_sha", branch)
        self.calls.append(call)
        self._raise_failure(call)
        return self._branches.get(branch)

    def push_urls(self) -> DeliveryGit.PushUrlsResult | DeliveryGit.ProbeError:
        call: Call = ("push_urls",)
        self.calls.append(call)
        if self._push_urls_error is not None:
            return DeliveryGit.ProbeError(message=self._push_urls_error)
        return DeliveryGit.PushUrlsResult(urls=self._push_urls)

    def probe_atomic_push(
        self,
        *,
        push_url: str,
        base_branch: str,
        base_sha: str,
    ) -> DeliveryGit.AtomicPushResult | DeliveryGit.ProbeError:
        call: Call = ("probe_atomic_push", push_url, base_branch, base_sha)
        self.calls.append(call)
        error = self._atomic_push_errors.get(push_url)
        if error is not None:
            return DeliveryGit.ProbeError(message=error)
        return DeliveryGit.AtomicPushResult()

    def is_ancestor(self, ancestor_sha: str, head_sha: str) -> bool | None:
        call: Call = ("is_ancestor", ancestor_sha, head_sha)
        self.calls.append(call)
        self._raise_failure(call)
        if ancestor_sha == head_sha:
            return True
        return self._ancestry.get((ancestor_sha, head_sha))

    def push_atomic(self, updates: tuple[git_mod.RefUpdate, ...]) -> None:
        call: Call = ("push_atomic", updates)
        self.calls.append(call)
        self._raise_failure(call)

    def update_ref(self, ref: str, sha: str) -> None:
        call: Call = ("update_ref", ref, sha)
        self.calls.append(call)
        self._raise_failure(call)

    def delete_ref(self, ref: str) -> None:
        call: Call = ("delete_ref", ref)
        self.calls.append(call)
        self._raise_failure(call)

    def list_refs(self, prefix: str) -> tuple[str, ...]:
        call: Call = ("list_refs", prefix)
        self.calls.append(call)
        self._raise_failure(call)
        return tuple(ref for ref in self._refs if ref.startswith(prefix))

    def add_detached_worktree(self, path: Path, commit: str) -> None:
        call: Call = ("add_detached_worktree", path, commit)
        self.calls.append(call)
        self._raise_failure(call)

    def remove_worktree(self, path: Path) -> None:
        call: Call = ("remove_worktree", path)
        self.calls.append(call)
        self._raise_failure(call)

    def prune_worktrees(self) -> None:
        call: Call = ("prune_worktrees",)
        self.calls.append(call)
        self._raise_failure(call)

    def checkout_detached(self, worktree: Path, sha: str) -> None:
        call: Call = ("checkout_detached", worktree, sha)
        self.calls.append(call)
        self._raise_failure(call)

    def rebase_onto(self, worktree: Path, *, onto: str, upstream: str) -> git_mod.RebaseOutcome:
        call: Call = ("rebase_onto", worktree, onto, upstream)
        self.calls.append(call)
        self._raise_failure(call)
        outcome = self._rebase_outcomes.get((worktree, onto, upstream))
        if outcome is None:
            raise AssertionError(f"no fake rebase outcome configured for {call!r}")
        return outcome

    def rebase_in_progress(self, worktree: Path) -> bool:
        call: Call = ("rebase_in_progress", worktree)
        self.calls.append(call)
        self._raise_failure(call)
        return worktree in self._rebasing_worktrees

    def worktree_dirty(self, worktree: Path) -> bool:
        call: Call = ("worktree_dirty", worktree)
        self.calls.append(call)
        self._raise_failure(call)
        return worktree in self._dirty_worktrees

    def worktree_branches(self) -> tuple[WorktreeFacts, ...]:
        call: Call = ("worktree_branches",)
        self.calls.append(call)
        self._raise_failure(call)
        return self._worktrees

    def base_head(self, branch: str) -> BaseHeadObservation:
        call: Call = ("base_head", branch)
        self.calls.append(call)
        self._raise_failure(call)
        return self._base_heads.get(branch, BaseHeadObservation(sha=None, failure=None))


class FakeDeliveryGitHub(_FailureMixin, DeliveryGitHub):
    """GitHub authority fake for status, Prepare, and synchronization."""

    def __init__(
        self,
        *,
        stack_capable: bool = True,
        merge_rules: DeliveryGitHub.MergeRules = _DEFAULT_MERGE_RULES,
        merge_rules_error: str | None = None,
        prs: Mapping[int, PrFactsView] | None = None,
        branch_prs: Mapping[str, BranchPrView] | None = None,
        stacks: Mapping[int, StackView] | None = None,
        strict_stacks: Mapping[int, tuple[int, ...] | None] | None = None,
        active_writers: frozenset[str] = frozenset(),
        errors: Mapping[Call, Exception] | None = None,
    ) -> None:
        super().__init__(errors)
        self._stack_capable = stack_capable
        self._merge_rules = merge_rules
        self._merge_rules_error = merge_rules_error
        self._prs = dict(prs or {})
        self._branch_prs = dict(branch_prs or {})
        self._stacks = dict(stacks or {})
        self._strict_stacks = dict(strict_stacks or {})
        self._active_writers = frozenset(active_writers)
        self.calls: list[Call] = []

    def stack_capability(self) -> bool:
        call: Call = ("stack_capability",)
        self.calls.append(call)
        return self._stack_capable

    def base_merge_rules(self, base: str) -> DeliveryGitHub.MergeRules | DeliveryGitHub.ProbeError:
        call: Call = ("base_merge_rules", base)
        self.calls.append(call)
        if self._merge_rules_error is not None:
            return DeliveryGitHub.ProbeError(message=self._merge_rules_error)
        return self._merge_rules

    def pr_facts(self, number: int) -> PrFactsView | None:
        call: Call = ("pr_facts", number)
        self.calls.append(call)
        self._raise_failure(call)
        return self._prs.get(number)

    def strict_stack_members(self, number: int) -> tuple[int, ...] | None:
        call: Call = ("strict_stack_members", number)
        self.calls.append(call)
        self._raise_failure(call)
        return self._strict_stacks.get(number)

    def active_writer_plan_ids(
        self,
        plan_ids: tuple[str, ...],
        *,
        trigger_plan_id: str | None,
        trigger_run_id: str | None,
    ) -> frozenset[str]:
        call: Call = (
            "active_writer_plan_ids",
            plan_ids,
            trigger_plan_id,
            trigger_run_id,
        )
        self.calls.append(call)
        self._raise_failure(call)
        return self._active_writers.intersection(plan_ids)

    def pr_for_branch(self, branch: str) -> BranchPrView | None:
        call: Call = ("pr_for_branch", branch)
        self.calls.append(call)
        self._raise_failure(call)
        return self._branch_prs.get(branch)

    def pr_stack(self, number: int) -> StackView:
        call: Call = ("pr_stack", number)
        self.calls.append(call)
        self._raise_failure(call)
        return self._stacks.get(number, StackView(available=True, stacked=False))
