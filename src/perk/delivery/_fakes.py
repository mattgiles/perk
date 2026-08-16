"""Constructor-configured fakes for the delivery façade's aggregate authorities."""

from collections.abc import Mapping

from perk.backends.issue_backend import PlanState
from perk.backends.objective_store import ObjectiveState
from perk.delivery.facade import DeliveryGit, DeliveryGitHub, DeliveryPersistence
from perk.delivery.journal import JournalFold, fold_events
from perk.delivery.train import (
    BaseHeadObservation,
    BranchPrView,
    PrFactsView,
    StackView,
    WorktreeFacts,
)

type Call = tuple[str | int, ...]

_DEFAULT_MERGE_RULES = DeliveryGitHub.MergeRules(squash_allowed=True, merge_queue_required=False)


class _FailureMixin:
    def __init__(self, errors: Mapping[Call, Exception] | None) -> None:
        self._errors = dict(errors or {})

    def _raise_failure(self, call: Call) -> None:
        failure = self._errors.get(call)
        if failure is not None:
            raise failure


class FakeDeliveryPersistence(_FailureMixin, DeliveryPersistence):
    """Minimum status fake for objective, plan, and journal reads."""

    def __init__(
        self,
        *,
        objectives: Mapping[str, ObjectiveState] | None = None,
        plans: Mapping[str, PlanState] | None = None,
        journals: Mapping[str, JournalFold] | None = None,
        errors: Mapping[Call, Exception] | None = None,
    ) -> None:
        super().__init__(errors)
        self._objectives = dict(objectives or {})
        self._plans = dict(plans or {})
        self._journals = dict(journals or {})
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


class FakeDeliveryGit(_FailureMixin, DeliveryGit):
    """Minimum status/Prepare fake for trunk and Git observations."""

    def __init__(
        self,
        *,
        trunk: str = "main",
        branches: Mapping[str, str] | None = None,
        push_urls: tuple[str, ...] = ("fake://origin",),
        push_urls_error: str | None = None,
        atomic_push_errors: Mapping[str, str] | None = None,
        ancestry: Mapping[tuple[str, str], bool | None] | None = None,
        worktrees: tuple[WorktreeFacts, ...] = (),
        base_heads: Mapping[str, BaseHeadObservation] | None = None,
        errors: Mapping[Call, Exception] | None = None,
    ) -> None:
        super().__init__(errors)
        self._trunk = trunk
        self._branches = dict(branches or {})
        self._push_urls = tuple(push_urls)
        self._push_urls_error = push_urls_error
        self._atomic_push_errors = dict(atomic_push_errors or {})
        self._ancestry = dict(ancestry or {})
        self._worktrees = tuple(worktrees)
        self._base_heads = dict(base_heads or {})
        self.calls: list[Call] = []

    def trunk_branch(self) -> str:
        call: Call = ("trunk_branch",)
        self.calls.append(call)
        self._raise_failure(call)
        return self._trunk

    def fetch(self) -> None:
        call: Call = ("fetch",)
        self.calls.append(call)
        self._raise_failure(call)

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
    """Minimum status/Prepare fake for GitHub observations."""

    def __init__(
        self,
        *,
        stack_capable: bool = True,
        merge_rules: DeliveryGitHub.MergeRules = _DEFAULT_MERGE_RULES,
        merge_rules_error: str | None = None,
        prs: Mapping[int, PrFactsView] | None = None,
        branch_prs: Mapping[str, BranchPrView] | None = None,
        stacks: Mapping[int, StackView] | None = None,
        errors: Mapping[Call, Exception] | None = None,
    ) -> None:
        super().__init__(errors)
        self._stack_capable = stack_capable
        self._merge_rules = merge_rules
        self._merge_rules_error = merge_rules_error
        self._prs = dict(prs or {})
        self._branch_prs = dict(branch_prs or {})
        self._stacks = dict(stacks or {})
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
