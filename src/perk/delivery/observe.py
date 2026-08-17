"""Production adapters for the delivery façade and deferred internal readers.

:func:`resolve_delivery` is the sole public production constructor for the canonical
:class:`perk.delivery.facade.Delivery` status, Prepare, Transfer, Publish, sync, and Recover
variants.
Construction is assignment-only and does no configuration, credential, Git, subprocess, or
network work; the nominal adapters resolve or observe their authorities only when an operation
needs them.

The compatibility ``TrainReads`` / ``resolve_train_reads`` / ``reconstruct_repo_train`` seams
remain internal while the deferred delivery operation families migrate. Landing observations also
remain here. Stable Git/GitHub failures become typed pure-core errors, while the preview stack
read and landing-readiness enrichment retain their documented tolerant/fail-closed postures.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from perk import objective
from perk.backends.issue_backend import IssueBackend, PlanHeaderUpdate, PlanState
from perk.backends.objective_store import ObjectiveRef, ObjectiveState, ObjectiveStore
from perk.backends.resolve import (
    GITHUB_BACKEND_ID,
    resolve_issue_backend,
    resolve_objective_store,
)
from perk.delivery import diagnostics, land, writers
from perk.delivery.facade import Delivery, DeliveryGit, DeliveryGitHub, DeliveryPersistence
from perk.delivery.journal import JournalFold, OutcomeRecord, PreparedRecord
from perk.delivery.persistence import AppendResult, TrainPersistence, TrainPersistenceError
from perk.delivery.train import (
    BaseHeadObservation,
    PrFactsView,
    StackEntryView,
    StackView,
    TrainReconstructionError,
    TrainStatus,
    WorktreeFacts,
    reconstruct_train,
)
from perk.github import GitHubError, prs, stacks
from perk.substrate import git as git_mod


class RepoDeliveryGit(DeliveryGit):
    """The production aggregate Git authority over one repository.

    Status failures raise typed ``git_error`` values. Prepare's continuable push observations
    instead return frozen success/error discriminants; only expected ``GitError`` values are
    converted.
    """

    def __init__(self, repo_root: Path, *, remote: str = "origin") -> None:
        self._repo_root = repo_root
        self._remote = remote

    @property
    def repo_root(self) -> Path:
        return self._repo_root

    def trunk_branch(self) -> str:
        try:
            return git_mod.detect_trunk_branch(self._repo_root)
        except git_mod.GitError as exc:
            raise TrainReconstructionError(
                f"git trunk detection failed: {exc}", error_type="git_error"
            ) from exc

    def fetch(self) -> None:
        try:
            git_mod.fetch(self._repo_root, remote=self._remote)
        except git_mod.GitError as exc:
            raise TrainReconstructionError(
                f"git fetch failed: {exc}", error_type="git_error"
            ) from exc

    def fetch_refs(self, refs: tuple[str, ...]) -> None:
        try:
            git_mod.fetch_refspecs(self._repo_root, list(refs), remote=self._remote)
        except git_mod.GitError as exc:
            raise TrainReconstructionError(
                f"git fetch failed for refs {refs!r}: {exc}", error_type="git_error"
            ) from exc

    def resolve_commit(self, ref: str, *, cwd: Path | None = None) -> str | None:
        try:
            return git_mod.resolve_commit(cwd or self._repo_root, ref)
        except git_mod.GitError as exc:
            raise TrainReconstructionError(
                f"git resolve failed for ref {ref!r}: {exc}", error_type="git_error"
            ) from exc

    def remote_branch_sha(self, branch: str) -> str | None:
        try:
            return git_mod.remote_branch_head(self._repo_root, branch, remote=self._remote)
        except git_mod.GitError as exc:
            raise TrainReconstructionError(
                f"git ls-remote failed for branch {branch!r}: {exc}", error_type="git_error"
            ) from exc

    def push_with_exact_lease(self, branch: str, *, expected_remote_sha: str | None) -> None:
        git_mod.push_with_exact_lease(
            self._repo_root, branch, expected_remote_sha=expected_remote_sha
        )

    def push_urls(self) -> DeliveryGit.PushUrlsResult | DeliveryGit.ProbeError:
        try:
            urls = git_mod.push_urls(self._repo_root, remote=self._remote)
        except git_mod.GitError as exc:
            return DeliveryGit.ProbeError(message=str(exc))
        return DeliveryGit.PushUrlsResult(urls=tuple(urls))

    def probe_atomic_push(
        self,
        *,
        push_url: str,
        base_branch: str,
        base_sha: str,
    ) -> DeliveryGit.AtomicPushResult | DeliveryGit.ProbeError:
        try:
            git_mod.probe_atomic_push(
                self._repo_root,
                push_url=push_url,
                base_branch=base_branch,
                base_sha=base_sha,
            )
        except git_mod.GitError as exc:
            return DeliveryGit.ProbeError(message=str(exc))
        return DeliveryGit.AtomicPushResult()

    def is_ancestor(self, ancestor_sha: str, head_sha: str) -> bool | None:
        """Ancestry over fetched objects; ``None`` when Git cannot answer honestly."""
        return git_mod.is_ancestor(self._repo_root, ancestor_sha, head_sha)

    def base_head(self, branch: str) -> BaseHeadObservation:
        """The authoritative live base-head read: ``ls-remote`` (never the fetched
        remote-tracking ref — a plain fetch has no ``--prune``, so a deleted remote base
        leaves a stale tracking ref that still resolves). Tolerant per the seam contract:
        a ``GitError`` degrades into the observation's ``failure`` arm."""
        try:
            sha = git_mod.remote_branch_head(self._repo_root, branch, remote=self._remote)
        except git_mod.GitError as exc:
            return BaseHeadObservation(sha=None, failure=str(exc))
        return BaseHeadObservation(sha=sha, failure=None)

    def push_atomic(self, updates: tuple[git_mod.RefUpdate, ...]) -> None:
        git_mod.push_atomic_with_leases(self._repo_root, list(updates))

    def update_ref(self, ref: str, sha: str) -> None:
        git_mod.update_ref(self._repo_root, ref, sha)

    def delete_ref(self, ref: str) -> None:
        git_mod.delete_ref(self._repo_root, ref)

    def list_refs(self, prefix: str) -> tuple[str, ...]:
        return tuple(git_mod.list_refs(self._repo_root, prefix))

    def add_detached_worktree(self, path: Path, commit: str) -> None:
        git_mod.worktree_add_detached(self._repo_root, path, commit)

    def remove_worktree(self, path: Path) -> None:
        git_mod.worktree_remove(self._repo_root, path, force=True)

    def prune_worktrees(self) -> None:
        git_mod.worktree_prune(self._repo_root)

    def checkout_detached(self, worktree: Path, sha: str) -> None:
        git_mod.checkout_detached(worktree, sha)

    def rebase_onto(self, worktree: Path, *, onto: str, upstream: str) -> git_mod.RebaseOutcome:
        return git_mod.rebase_onto(worktree, onto=onto, upstream=upstream)

    def rebase_in_progress(self, worktree: Path) -> bool:
        return git_mod.rebase_in_progress(worktree)

    def worktree_dirty(self, worktree: Path) -> bool:
        return git_mod.is_dirty(worktree)

    def worktree_admin_paths(self) -> tuple[Path, ...]:
        return tuple(worktree.path for worktree in git_mod.worktree_list(self._repo_root))

    def worktree_branches(self) -> tuple[WorktreeFacts, ...]:
        try:
            worktrees = git_mod.worktree_list(self._repo_root)
        except git_mod.GitError as exc:
            raise TrainReconstructionError(
                f"git worktree list failed: {exc}", error_type="git_error"
            ) from exc
        facts: list[WorktreeFacts] = []
        for worktree in worktrees:
            if worktree.branch is None:
                continue
            try:
                dirty = git_mod.is_dirty(worktree.path)
            except git_mod.GitError:
                # An unreadable/broken worktree still occupies the branch — conservatively
                # not FREE (the read-only writer axis never blocks anything by itself).
                dirty = True
            facts.append(
                WorktreeFacts(path=str(worktree.path), branch=worktree.branch, dirty=dirty)
            )
        return tuple(facts)


def _corroborated_remote_run_id(
    repo_root: Path,
    plan_id: str,
    requested_run_id: str | None,
    *,
    environ: Mapping[str, str] = os.environ,
) -> str | None:
    """Return an invoking remote run only when local run authority proves the exact pair."""
    if requested_run_id is None or environ.get("PERK_RUN_ID") != requested_run_id:
        return None
    from perk.state import cache  # noqa: PLC0415 — preserve delivery import ordering

    try:
        handoff = cache.read_handoff(repo_root, requested_run_id)
        plan_ref = cache.read_plan_ref(repo_root)
    except (OSError, ValueError):
        return None
    if (
        handoff is None
        or handoff.consumed is not True
        or handoff.stage not in {"implement", "address"}
        or plan_ref is None
        or plan_ref.pr_id.removeprefix("#") != plan_id.removeprefix("#")
    ):
        return None
    return requested_run_id


class RepoDeliveryGitHub(DeliveryGitHub):
    """The production aggregate GitHub authority over ``perk.github.stacks``.

    Stable status reads hard-fail as ``github_error`` and preview stack reads tolerate gateway
    failures. Prepare receives the gateway's fail-closed stack bool and a frozen merge-rule
    success/error discriminant so it can continue independent observations.
    """

    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root

    def stack_capability(self) -> bool:
        return stacks.stack_capability(self._repo_root)

    def base_merge_rules(self, base: str) -> DeliveryGitHub.MergeRules | DeliveryGitHub.ProbeError:
        try:
            rules = stacks.base_merge_rules(self._repo_root, base)
        except GitHubError as exc:
            return DeliveryGitHub.ProbeError(message=str(exc))
        return DeliveryGitHub.MergeRules(
            squash_allowed=rules.squash_allowed,
            merge_queue_required=rules.merge_queue_required,
        )

    def pr_facts(self, number: int) -> PrFactsView | None:
        try:
            facts = stacks.pr_delivery_facts(number=number, repo_root=self._repo_root)
        except GitHubError as exc:
            raise TrainReconstructionError(str(exc), error_type="github_error") from exc
        if facts is None:
            return None
        return PrFactsView(
            number=facts.number,
            state=facts.state,
            is_draft=facts.is_draft,
            base_ref=facts.base_ref,
            head_ref=facts.head_ref,
            head_sha=facts.head_sha,
        )

    def strict_stack(self, number: int) -> stacks.StackRestFacts | None:
        try:
            return stacks.stack_for_pr(number=number, repo_root=self._repo_root)
        except GitHubError as exc:
            raise TrainReconstructionError(str(exc), error_type="github_error") from exc

    def merge_async_probe(self, number: int, *, uuid: str) -> stacks.MergeAsyncProbe:
        return stacks.merge_async_probe(number=number, uuid=uuid, repo_root=self._repo_root)

    def merged_evidence(self, number: int) -> stacks.PrMergedEvidence | None:
        return stacks.pr_merged_evidence(number=number, repo_root=self._repo_root)

    def active_writer_plan_ids(
        self,
        plan_ids: tuple[str, ...],
        *,
        trigger_plan_id: str | None,
        trigger_run_id: str | None,
    ) -> frozenset[str]:
        from perk.run import discovery  # noqa: PLC0415 — preserve delivery import ordering

        excluded_run_id: str | None = None
        excluded_plan_id: str | None = None
        if trigger_plan_id is not None and trigger_run_id is not None:
            excluded_run_id = _corroborated_remote_run_id(
                self._repo_root, trigger_plan_id, trigger_run_id
            )
            if excluded_run_id is not None:
                excluded_plan_id = trigger_plan_id
        try:
            return discovery.active_writer_plan_ids(
                self._repo_root,
                list(plan_ids),
                exclude_run_id=excluded_run_id,
                exclude_plan_id=excluded_plan_id,
            )
        except GitHubError as exc:
            raise writers.WriterObservationError(str(exc)) from exc

    def pr_for_branch(self, branch: str) -> prs.PullRequest | None:
        """Read the all-state branch-owned PR through the stable status posture.

        Failures raise the typed ``github_error``; publication bridges unwrap only its raw
        GitHub cause where the mutation protocol requires the original gateway classification.
        """
        try:
            pr = prs.find_pr_for_branch(branch=branch, repo_root=self._repo_root)
        except GitHubError as exc:
            raise TrainReconstructionError(str(exc), error_type="github_error") from exc
        return pr

    def get_pr(self, number: int) -> prs.PullRequest | None:
        return prs.get_pr(number=number, repo_root=self._repo_root)

    def create_pr(
        self, *, head: str, base: str, title: str, body: str, draft: bool
    ) -> prs.PullRequest:
        return prs.create_pr(
            head=head,
            base=base,
            title=title,
            body=body,
            repo_root=self._repo_root,
            draft=draft,
        )

    def update_pr_body(self, number: int, *, body: str) -> prs.PrBodyUpdate:
        return prs.update_pr_body(number=number, body=body, repo_root=self._repo_root)

    def update_pr_base(self, number: int, *, base: str) -> None:
        prs.update_pr_base(number=number, base=base, repo_root=self._repo_root)

    def reopen_pr(self, number: int) -> None:
        prs.reopen_pr(number=number, repo_root=self._repo_root)

    def mark_pr_ready(self, number: int) -> None:
        prs.mark_pr_ready(number=number, repo_root=self._repo_root)

    def create_stack(self, pull_requests: tuple[int, ...]) -> stacks.StackMutationOutcome:
        return stacks.create_stack(pull_requests=pull_requests, repo_root=self._repo_root)

    def append_stack(
        self, stack_number: int, *, pull_requests: tuple[int, ...]
    ) -> stacks.StackMutationOutcome:
        return stacks.append_to_stack(
            stack_number=stack_number,
            pull_requests=pull_requests,
            repo_root=self._repo_root,
        )

    def pr_stack(self, number: int) -> StackView:
        try:
            observation = stacks.pr_stack(number=number, repo_root=self._repo_root)
        except GitHubError:
            return StackView(available=False)
        if not observation.available:
            return StackView(available=False)
        if observation.stack is None:
            return StackView(available=True, stacked=False)
        return StackView(
            available=True,
            stacked=True,
            entries=tuple(
                StackEntryView(position=entry.position, pr_number=entry.pr_number)
                for entry in observation.stack.entries
            ),
            truncated=observation.stack.truncated,
        )


class GatewayLandObservations:
    """The production :class:`~perk.delivery.land.LandObservations` over
    ``perk.github.stacks``: the strict readiness/rules reads wrap every ``GitHubError`` into
    the typed :class:`~perk.delivery.land.LandObservationError` (the assessment converts it
    into the read-specific fail-closed blocker); ``stack_capability`` passes the gateway's
    fail-closed bool through — the §8.55 declared boolean arm."""

    def __init__(self, repo_root: Path, *, base: str) -> None:
        self._repo_root = repo_root
        self._base = base

    def pr_readiness(self, number: int) -> land.PrLandView | None:
        try:
            facts = stacks.pr_land_facts(number=number, repo_root=self._repo_root)
        except GitHubError as exc:
            raise land.LandObservationError(str(exc)) from exc
        if facts is None:
            return None
        return land.PrLandView(
            number=facts.number,
            state=facts.state,
            is_draft=facts.is_draft,
            base_ref=facts.base_ref,
            head_ref=facts.head_ref,
            head_sha=facts.head_sha,
            mergeable=facts.mergeable,
            merge_state_status=facts.merge_state_status,
            review_decision=facts.review_decision,
            checks=tuple(
                land.CheckView(
                    name=check.name, is_required=check.is_required, outcome=check.outcome
                )
                for check in facts.checks
            ),
            unresolved_thread_count=facts.unresolved_thread_count,
        )

    def base_merge_rules(self) -> land.MergeRulesView:
        try:
            rules = stacks.base_merge_rules(self._repo_root, self._base)
        except GitHubError as exc:
            raise land.LandObservationError(str(exc)) from exc
        return land.MergeRulesView(
            squash_allowed=rules.squash_allowed,
            merge_queue_required=rules.merge_queue_required,
        )

    def stack_capability(self) -> bool:
        return stacks.stack_capability(self._repo_root)


class RepoDeliveryPersistence(DeliveryPersistence):
    """The lazily resolved, backend-aligned aggregate persistence authority.

    The objective store, issue backend, and ``TrainPersistence`` are cached only after both
    resolvers succeed and their backend identities agree. A failed attempt leaves no partial
    selection for a later call to reuse.
    """

    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root
        self._resolved: tuple[ObjectiveStore, IssueBackend, TrainPersistence] | None = None

    def _resolve(self) -> tuple[ObjectiveStore, IssueBackend, TrainPersistence]:
        if self._resolved is not None:
            return self._resolved
        store = resolve_objective_store(self._repo_root)
        issues = resolve_issue_backend(self._repo_root)
        if store.backend_id != issues.backend_id:
            raise TrainPersistenceError(
                "delivery backend mismatch: objective store is "
                f"{store.backend_id!r}, issue backend is {issues.backend_id!r}"
            )
        resolved = (store, issues, TrainPersistence(store, issues))
        self._resolved = resolved
        return resolved

    def get_objective(self, *, objective_id: str) -> ObjectiveState | None:
        store, _issues, _persistence = self._resolve()
        return store.get_objective(objective_id=objective_id)

    def close_objective(self, *, objective_id: str, dry_run: bool = False) -> bool:
        store, _issues, _persistence = self._resolve()
        return store.close_objective(objective_id=objective_id, dry_run=dry_run)

    def get_plan(self, *, issue_id: str) -> PlanState | None:
        _store, issues, _persistence = self._resolve()
        return issues.get_plan(issue_id=issue_id)

    def get_plan_body(self, *, issue_id: str) -> str | None:
        _store, issues, _persistence = self._resolve()
        return issues.get_plan_body(issue_id=issue_id)

    def update_plan_header(self, *, issue_id: str, fields: dict[str, object]) -> PlanHeaderUpdate:
        _store, issues, _persistence = self._resolve()
        return issues.update_plan_header(issue_id=issue_id, fields=fields)

    def normalize_transfer_carry_map(
        self, carry_map: tuple[tuple[str, str], ...]
    ) -> dict[str, str]:
        store, _issues, _persistence = self._resolve()
        if store.backend_id == GITHUB_BACKEND_ID:
            return {}
        return dict(carry_map)

    def find_objective(self, *, run_id: str) -> ObjectiveRef | None:
        store, _issues, _persistence = self._resolve()
        return store.find_objective(run_id=run_id)

    def supersede_objective(
        self,
        *,
        old_objective_id: str,
        title: str,
        prose: str,
        run_id: str,
        status: str = "active",
        base: str | None = None,
        roadmap_nodes: list[objective.ObjectiveNode],
        carry_map: dict[str, str],
        delivery: objective.DeliveryPolicy | None = None,
        delivery_lineage: str | None = None,
        close_predecessor: bool = True,
        dry_run: bool = False,
    ) -> ObjectiveRef | None:
        store, _issues, _persistence = self._resolve()
        return store.supersede_objective(
            old_objective_id=old_objective_id,
            title=title,
            prose=prose,
            run_id=run_id,
            status=status,
            base=base,
            roadmap_nodes=roadmap_nodes,
            carry_map=carry_map,
            delivery=delivery,
            delivery_lineage=delivery_lineage,
            close_predecessor=close_predecessor,
            dry_run=dry_run,
        )

    def finalize_supersession(self, *, old_objective_id: str, new_objective_id: str) -> bool:
        store, _issues, _persistence = self._resolve()
        return store.finalize_supersession(
            old_objective_id=old_objective_id,
            new_objective_id=new_objective_id,
        )

    def read_journal(self, objective_id: str) -> JournalFold:
        _store, _issues, persistence = self._resolve()
        return persistence.read_journal(objective_id)

    def append_prepared(self, objective_id: str, record: PreparedRecord) -> AppendResult:
        _store, _issues, persistence = self._resolve()
        return persistence.append_prepared(objective_id, record)

    def append_outcome(self, objective_id: str, record: OutcomeRecord) -> AppendResult:
        _store, _issues, persistence = self._resolve()
        return persistence.append_outcome(objective_id, record)

    def write_checkpoints(
        self,
        plan_id: str,
        *,
        parent_checkpoint_sha: str,
        published_head_sha: str,
    ) -> None:
        _store, _issues, persistence = self._resolve()
        persistence.write_checkpoints(
            plan_id,
            parent_checkpoint_sha=parent_checkpoint_sha,
            published_head_sha=published_head_sha,
        )

    def native_cancellation_metadata_writer(
        self,
    ) -> diagnostics.NativeCancellationMetadataWriter | None:
        """Return the resolved objective store only when it structurally offers the §8.54
        conditional cancellation writer (the runtime-checkable Protocol); ``None``
        otherwise. One lazy aligned resolution — no extra objective read, and a failed
        resolution stays uncached like every other persistence operation."""
        store, _issues, _persistence = self._resolve()
        if isinstance(store, diagnostics.NativeCancellationMetadataWriter):
            return store
        return None


def resolve_delivery(repo_root: Path) -> Delivery:
    """Construct the repository-scoped delivery façade without performing I/O."""
    return Delivery(
        persistence=RepoDeliveryPersistence(repo_root),
        git=RepoDeliveryGit(repo_root),
        github=RepoDeliveryGitHub(repo_root),
    )


@dataclass(frozen=True)
class TrainReads:
    """Internal compatibility composition for delivery operations not yet on the façade."""

    store: RepoDeliveryPersistence
    issues: RepoDeliveryPersistence
    persistence: RepoDeliveryPersistence
    git: RepoDeliveryGit
    github: RepoDeliveryGitHub


def resolve_train_reads(repo_root: Path) -> TrainReads:
    """Compose deferred internal train readers without eagerly resolving any authority."""
    persistence = RepoDeliveryPersistence(repo_root)
    return TrainReads(
        store=persistence,
        issues=persistence,
        persistence=persistence,
        git=RepoDeliveryGit(repo_root),
        github=RepoDeliveryGitHub(repo_root),
    )


def reconstruct_repo_train(repo_root: Path, objective_id: str) -> TrainStatus:
    """Internal compatibility reconstruction for deferred delivery operation families."""
    reads = resolve_train_reads(repo_root)
    return reconstruct_train(
        objective_id,
        store=reads.store,
        issues=reads.issues,
        persistence=reads.persistence,
        git=reads.git,
        github=reads.github,
    )
