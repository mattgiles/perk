"""The delivery module's production wiring leaf (contracts.md §8.44).

The one place the delivery module touches the Git substrate and the GitHub gateway:
:class:`RepoGitProbe` and :class:`GatewayGitHubProbe` satisfy the narrow Protocols
:mod:`perk.delivery.train` declares (converting substrate/gateway types into the pure core's
view vocabulary), :class:`GatewayLandObservations` satisfies
:class:`perk.delivery.land.LandObservations` the same way (contracts.md §8.55), and
:func:`resolve_train_reads` composes every read authority
``perk objective stack status`` needs from the committed ``[issues]`` selection.

Import direction stays legal: this leaf imports ``perk.substrate.git`` + ``perk.github.stacks``
one-directionally; nothing in ``perk/backends/`` or ``perk/github/`` imports the delivery
module. Substrate/gateway failures are translated at this boundary into the typed
:class:`~perk.delivery.train.TrainReconstructionError` (``git_error`` / ``github_error``) —
except the tolerant preview stack read, which degrades to ``StackView(available=False)``
(the §8.44 failure-posture split).
"""

from dataclasses import dataclass
from pathlib import Path

from perk.backends.issue_backend import IssueBackend
from perk.backends.objective_store import ObjectiveStore
from perk.backends.resolve import resolve_issue_backend, resolve_objective_store
from perk.delivery import land
from perk.delivery.persistence import TrainPersistence, resolve_train_persistence
from perk.delivery.train import (
    BaseHeadObservation,
    BranchPrView,
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


class RepoGitProbe:
    """The production :class:`~perk.delivery.train.GitProbe`: read-only Git observation over
    one repo. Failures raise the typed ``git_error`` — except local-observation gaps
    (unavailable objects, an unreadable worktree), which degrade honestly per the seam's
    contract."""

    def __init__(self, repo_root: Path, *, remote: str = "origin") -> None:
        self._repo_root = repo_root
        self._remote = remote

    def fetch(self) -> None:
        try:
            git_mod.fetch(self._repo_root, remote=self._remote)
        except git_mod.GitError as exc:
            raise TrainReconstructionError(
                f"git fetch failed: {exc}", error_type="git_error"
            ) from exc

    def remote_branch_sha(self, branch: str) -> str | None:
        try:
            return git_mod.remote_branch_head(self._repo_root, branch, remote=self._remote)
        except git_mod.GitError as exc:
            raise TrainReconstructionError(
                f"git ls-remote failed for branch {branch!r}: {exc}", error_type="git_error"
            ) from exc

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


class GatewayGitHubProbe:
    """The production :class:`~perk.delivery.train.GitHubProbe` over ``perk.github.stacks``:
    the stable PR read hard-fails as ``github_error``; the preview stack read tolerates every
    ``GitHubError`` to ``StackView(available=False)`` (Decision: preview instability is
    information, never a command failure)."""

    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root

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

    def pr_for_branch(self, branch: str) -> BranchPrView | None:
        """The all-state branch-owned PR read (§8.54's cancellation proof) — a stable read:
        failures raise the typed ``github_error`` (an unobservable authority fails the
        cancellation proof closed, never silently reads as absent)."""
        try:
            pr = prs.find_pr_for_branch(branch=branch, repo_root=self._repo_root)
        except GitHubError as exc:
            raise TrainReconstructionError(str(exc), error_type="github_error") from exc
        if pr is None:
            return None
        return BranchPrView(number=pr.number, state=pr.state)

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
            rollup_state=facts.rollup_state,
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


@dataclass(frozen=True)
class TrainReads:
    """Every read authority :func:`~perk.delivery.train.reconstruct_train` needs, composed
    from one committed ``[issues]`` selection (the backend-aligned guarantee)."""

    store: ObjectiveStore
    issues: IssueBackend
    persistence: TrainPersistence
    git: RepoGitProbe
    github: GatewayGitHubProbe
    trunk: str


def resolve_train_reads(repo_root: Path) -> TrainReads:
    """Compose the repo's train-read authorities: the objective store + issue backend (the
    ``[issues]`` selection), the succession-folding persistence, the two probes, and the
    detected trunk branch (the base fallback when the objective header pins none)."""
    return TrainReads(
        store=resolve_objective_store(repo_root),
        issues=resolve_issue_backend(repo_root),
        persistence=resolve_train_persistence(repo_root),
        git=RepoGitProbe(repo_root),
        github=GatewayGitHubProbe(repo_root),
        trunk=git_mod.detect_trunk_branch(repo_root),
    )


def reconstruct_repo_train(repo_root: Path, objective_id: str) -> TrainStatus:
    """Reconstruct one train projection from the repo's live read authorities — the composed
    convenience every execution-path consumer shares (``resolve_train_reads`` +
    ``reconstruct_train``); tests monkeypatch this seam on the module."""
    reads = resolve_train_reads(repo_root)
    return reconstruct_train(
        objective_id,
        store=reads.store,
        issues=reads.issues,
        persistence=reads.persistence,
        git=reads.git,
        github=reads.github,
        trunk=reads.trunk,
    )
