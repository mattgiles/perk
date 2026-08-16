"""Constructor-configured fakes for the delivery façade's aggregate authorities."""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from perk.backends.issue_backend import PlanHeaderUpdate, PlanState
from perk.backends.objective_store import ObjectiveState
from perk.delivery.facade import DeliveryGit, DeliveryGitHub, DeliveryPersistence
from perk.delivery.journal import EventRole, JournalFold, OutcomeRecord, PreparedRecord, fold_events
from perk.delivery.persistence import AppendResult
from perk.delivery.train import (
    BaseHeadObservation,
    PrFactsView,
    StackView,
    WorktreeFacts,
)
from perk.github import prs, stacks
from perk.substrate import git as git_mod

type Call = tuple[object, ...]

_DEFAULT_MERGE_RULES = DeliveryGitHub.MergeRules(squash_allowed=True, merge_queue_required=False)


def _call_value(value: object) -> object:
    """Freeze JSON-like mutation inputs so call records remain deterministic mapping keys."""
    if isinstance(value, dict):
        return tuple((key, _call_value(item)) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return tuple(_call_value(item) for item in value)
    return value


class _FailureMixin:
    def __init__(self, errors: Mapping[Call, Exception] | None) -> None:
        self._errors = dict(errors or {})

    def _raise_failure(self, call: Call) -> None:
        try:
            failure = self._errors.get(call)
        except TypeError:
            failure = next(
                (candidate for key, candidate in self._errors.items() if key == call),
                None,
            )
        if failure is not None:
            raise failure


class FakeDeliveryPersistence(_FailureMixin, DeliveryPersistence):
    """Persistence authority fake for status, Prepare, and synchronization."""

    def __init__(
        self,
        *,
        objectives: Mapping[str, ObjectiveState] | None = None,
        plans: Mapping[str, PlanState] | None = None,
        plan_bodies: Mapping[str, str | None] | None = None,
        journals: Mapping[str, JournalFold] | None = None,
        prepared_results: Mapping[str, AppendResult] | None = None,
        outcome_results: Mapping[str, AppendResult] | None = None,
        header_results: Mapping[str, PlanHeaderUpdate] | None = None,
        errors: Mapping[Call, Exception] | None = None,
    ) -> None:
        super().__init__(errors)
        self._objectives = {
            key: replace(value, header=deepcopy(value.header))
            for key, value in (objectives or {}).items()
        }
        self._plans = {
            key: replace(value, header=deepcopy(value.header))
            for key, value in (plans or {}).items()
        }
        self._plan_bodies = dict(plan_bodies or {})
        self._journals = dict(journals or {})
        self._prepared_results = dict(prepared_results or {})
        self._outcome_results = dict(outcome_results or {})
        self._header_results = dict(header_results or {})
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

    def get_plan_body(self, *, issue_id: str) -> str | None:
        call: Call = ("get_plan_body", issue_id)
        self.calls.append(call)
        self._raise_failure(call)
        return self._plan_bodies.get(issue_id)

    def update_plan_header(self, *, issue_id: str, fields: dict[str, object]) -> PlanHeaderUpdate:
        copied = deepcopy(fields)
        call: Call = (
            "update_plan_header",
            issue_id,
            tuple((key, _call_value(value)) for key, value in copied.items()),
        )
        self.calls.append(call)
        self._raise_failure(call)
        state = self._plans.get(issue_id)
        if state is not None:
            merged = deepcopy(state.header)
            merged.update(copied)
            self._plans[issue_id] = replace(state, header=merged)
        return self._header_results.get(
            issue_id,
            PlanHeaderUpdate(fields_updated=tuple(copied), dry_run=False),
        )

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

    def push_with_exact_lease(self, branch: str, *, expected_remote_sha: str | None) -> None:
        call: Call = ("push_with_exact_lease", branch, expected_remote_sha)
        self.calls.append(call)
        self._raise_failure(call)
        local = self._resolutions.get(branch)
        if local is not None:
            self._branches[branch] = local

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
        pull_requests: Mapping[int, prs.PullRequest] | None = None,
        branch_prs: Mapping[str, prs.PullRequest] | None = None,
        stacks: Mapping[int, StackView] | None = None,
        strict_stacks: Mapping[int, stacks.StackRestFacts | None] | None = None,
        body_updates: Mapping[int, prs.PrBodyUpdate] | None = None,
        create_stack_results: Mapping[tuple[int, ...], stacks.StackMutationOutcome] | None = None,
        append_stack_results: Mapping[tuple[int, tuple[int, ...]], stacks.StackMutationOutcome]
        | None = None,
        active_writers: frozenset[str] = frozenset(),
        errors: Mapping[Call, Exception] | None = None,
    ) -> None:
        super().__init__(errors)
        self._stack_capable = stack_capable
        self._merge_rules = merge_rules
        self._merge_rules_error = merge_rules_error
        self._prs = dict(prs or {})
        self._pull_requests = dict(pull_requests or {})
        self._branch_prs = dict(branch_prs or {})
        self._stacks = dict(stacks or {})
        self._strict_stacks = dict(strict_stacks or {})
        self._body_updates = dict(body_updates or {})
        self._create_stack_results = dict(create_stack_results or {})
        self._append_stack_results = dict(append_stack_results or {})
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

    def strict_stack(self, number: int) -> stacks.StackRestFacts | None:
        call: Call = ("strict_stack", number)
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

    def pr_for_branch(self, branch: str) -> prs.PullRequest | None:
        call: Call = ("pr_for_branch", branch)
        self.calls.append(call)
        self._raise_failure(call)
        return self._branch_prs.get(branch)

    def get_pr(self, number: int) -> prs.PullRequest | None:
        call: Call = ("get_pr", number)
        self.calls.append(call)
        self._raise_failure(call)
        return self._pull_requests.get(number)

    def create_pr(
        self, *, head: str, base: str, title: str, body: str, draft: bool
    ) -> prs.PullRequest:
        call: Call = ("create_pr", head, base, title, body, draft)
        self.calls.append(call)
        self._raise_failure(call)
        result = self._branch_prs.get(head)
        if result is None:
            raise AssertionError(f"no fake PR configured for branch {head!r}")
        self._pull_requests[result.number] = result
        return result

    def update_pr_body(self, number: int, *, body: str) -> prs.PrBodyUpdate:
        call: Call = ("update_pr_body", number, body)
        self.calls.append(call)
        self._raise_failure(call)
        return self._body_updates.get(number, prs.PrBodyUpdate(number=number, dry_run=False))

    def update_pr_base(self, number: int, *, base: str) -> None:
        call: Call = ("update_pr_base", number, base)
        self.calls.append(call)
        self._raise_failure(call)

    def reopen_pr(self, number: int) -> None:
        call: Call = ("reopen_pr", number)
        self.calls.append(call)
        self._raise_failure(call)

    def mark_pr_ready(self, number: int) -> None:
        call: Call = ("mark_pr_ready", number)
        self.calls.append(call)
        self._raise_failure(call)

    def create_stack(self, pull_requests: tuple[int, ...]) -> stacks.StackMutationOutcome:
        call: Call = ("create_stack", pull_requests)
        self.calls.append(call)
        self._raise_failure(call)
        result = self._create_stack_results.get(pull_requests)
        if result is None:
            raise AssertionError(f"no fake create-stack result configured for {pull_requests!r}")
        return result

    def append_stack(
        self, stack_number: int, *, pull_requests: tuple[int, ...]
    ) -> stacks.StackMutationOutcome:
        call: Call = ("append_stack", stack_number, pull_requests)
        self.calls.append(call)
        self._raise_failure(call)
        result = self._append_stack_results.get((stack_number, pull_requests))
        if result is None:
            raise AssertionError(
                f"no fake append-stack result configured for {(stack_number, pull_requests)!r}"
            )
        return result

    def pr_stack(self, number: int) -> StackView:
        call: Call = ("pr_stack", number)
        self.calls.append(call)
        self._raise_failure(call)
        return self._stacks.get(number, StackView(available=True, stacked=False))
