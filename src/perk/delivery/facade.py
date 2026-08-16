"""The canonical repository-scoped delivery status and authoring-Prepare façade.

``Delivery`` composes three nominal aggregate authorities. ``status`` delegates its pure
projection to :mod:`perk.delivery.train`; ``prepare(kind="authoring")`` owns the ordered live
capability observations while :mod:`perk.delivery.capability` owns their stable private rows.
Construction remains assignment-only, and deferred operation families stay on internal seams.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

from perk.backends.issue_backend import IssueBackendError, PlanState
from perk.backends.objective_store import ObjectiveState, ObjectiveStoreError
from perk.delivery import capability, train
from perk.delivery.journal import JournalFold
from perk.delivery.persistence import TrainPersistenceError
from perk.substrate import git as git_mod

_DELIVERY_ERROR_TYPES = frozenset(
    {
        "capability_unsupported",
        "objective_not_found",
        "invalid_delivery_policy",
        "invalid_train",
        "git_error",
        "github_error",
        "supersession_corruption",
    }
)


@dataclass(frozen=True)
class PrepareRequest:
    """Request the live preflight for one delivery operation family."""

    kind: Literal["authoring"]
    base: str | None

    def __post_init__(self) -> None:
        if self.kind != "authoring":
            raise ValueError(f"unknown prepare kind: {self.kind!r}")


@dataclass(frozen=True)
class PrepareResult:
    """The effective base successfully checked for authoring."""

    kind: Literal["authoring"]
    base: str

    def __post_init__(self) -> None:
        if self.kind != "authoring":
            raise ValueError(f"unknown prepare kind: {self.kind!r}")


@dataclass(frozen=True)
class StatusRequest:
    """Request one objective's current delivery status."""

    objective_id: str


@dataclass(frozen=True)
class StatusResult:
    """Exactly one explicit status branch: a train or the successful no-train reason."""

    objective_id: str
    objective_url: str
    redirected_from: str | None
    train: train.DeliveryTrain | None
    no_train_reason: str | None

    def __post_init__(self) -> None:
        if (self.train is None) == (self.no_train_reason is None):
            raise ValueError("exactly one of train and no_train_reason must be non-None")


class DeliveryError(Exception):
    """A bounded delivery-façade failure with a stable machine ``error_type``."""

    def __init__(self, message: str, *, error_type: str) -> None:
        if error_type not in _DELIVERY_ERROR_TYPES:
            allowed = ", ".join(sorted(_DELIVERY_ERROR_TYPES))
            raise ValueError(f"unknown delivery error type {error_type!r} (allowed: {allowed})")
        super().__init__(message)
        self.error_type = error_type


class DeliveryPersistence(ABC):
    """Aggregate status authority over objective, plan, and journal persistence."""

    @abstractmethod
    def get_objective(self, *, objective_id: str) -> ObjectiveState | None:
        """Read one objective by backend-owned id."""
        ...

    @abstractmethod
    def get_plan(self, *, issue_id: str) -> PlanState | None:
        """Read one plan by backend-owned id."""
        ...

    @abstractmethod
    def read_journal(self, objective_id: str) -> JournalFold:
        """Read the succession-folded delivery journal."""
        ...


class DeliveryGit(ABC):
    """Aggregate status and authoring-Prepare authority for repository Git observations."""

    @dataclass(frozen=True)
    class PushUrlsResult:
        urls: tuple[str, ...]

    @dataclass(frozen=True)
    class AtomicPushResult:
        pass

    @dataclass(frozen=True)
    class ProbeError:
        message: str

    @abstractmethod
    def trunk_branch(self) -> str:
        """Resolve the repository trunk when the objective does not pin a base."""
        ...

    @abstractmethod
    def fetch(self) -> None:
        """Fetch the delivery observation remote."""
        ...

    @abstractmethod
    def remote_branch_sha(self, branch: str) -> str | None:
        """Observe one remote branch head."""
        ...

    @abstractmethod
    def push_urls(self) -> PushUrlsResult | ProbeError:
        """Resolve every configured push URL or return the expected Git failure."""
        ...

    @abstractmethod
    def probe_atomic_push(
        self,
        *,
        push_url: str,
        base_branch: str,
        base_sha: str,
    ) -> AtomicPushResult | ProbeError:
        """Run one no-op atomic push probe or return the expected Git failure."""
        ...

    @abstractmethod
    def is_ancestor(self, ancestor_sha: str, head_sha: str) -> bool | None:
        """Classify ancestry, or return ``None`` when Git cannot answer."""
        ...

    @abstractmethod
    def worktree_branches(self) -> tuple[train.WorktreeFacts, ...]:
        """Observe branches occupied by local worktrees."""
        ...

    @abstractmethod
    def base_head(self, branch: str) -> train.BaseHeadObservation:
        """Observe the authoritative live base head tolerantly."""
        ...


class DeliveryGitHub(ABC):
    """Aggregate status and authoring-Prepare authority for GitHub observations."""

    @dataclass(frozen=True)
    class MergeRules:
        squash_allowed: bool
        merge_queue_required: bool

    @dataclass(frozen=True)
    class ProbeError:
        message: str

    @abstractmethod
    def stack_capability(self) -> bool:
        """Whether the host schema exposes native stacks, failing closed to ``False``."""
        ...

    @abstractmethod
    def base_merge_rules(self, base: str) -> MergeRules | ProbeError:
        """Read direct-merge rules for ``base`` or return the expected gateway failure."""
        ...

    @abstractmethod
    def pr_facts(self, number: int) -> train.PrFactsView | None:
        """Read stable delivery facts for one PR."""
        ...

    @abstractmethod
    def pr_stack(self, number: int) -> train.StackView:
        """Read tolerant native-stack membership for one PR."""
        ...

    @abstractmethod
    def pr_for_branch(self, branch: str) -> train.BranchPrView | None:
        """Read an all-state PR by head branch."""
        ...


def _raw_prepare_git_error(exc: git_mod.GitError | train.TrainReconstructionError) -> str:
    """Preserve the old authoring path's raw Git detail when status adapters are reused."""
    if isinstance(exc, train.TrainReconstructionError):
        cause = exc.__cause__
        if isinstance(cause, git_mod.GitError):
            return str(cause)
    return str(exc)


class Delivery:
    """Repository-scoped delivery status and authoring-Prepare operations."""

    def __init__(
        self,
        *,
        persistence: DeliveryPersistence,
        git: DeliveryGit,
        github: DeliveryGitHub,
    ) -> None:
        self._persistence = persistence
        self._git = git
        self._github = github

    def prepare(self, request: PrepareRequest) -> PrepareResult:
        """Check authoring capability and return the effective base or one bounded refusal."""
        effective_base = request.base
        if effective_base is None:
            try:
                effective_base = self._git.trunk_branch()
            except train.TrainReconstructionError as exc:
                if exc.error_type != "git_error":
                    raise
                raise DeliveryError(_raw_prepare_git_error(exc), error_type="git_error") from exc
            except git_mod.GitError as exc:
                raise DeliveryError(str(exc), error_type="git_error") from exc

        checks: list[capability._CapabilityCheck] = [
            capability._native_stack_check(self._github.stack_capability())
        ]

        rules = self._github.base_merge_rules(effective_base)
        if isinstance(rules, DeliveryGitHub.ProbeError):
            checks.append(capability._merge_rules_check(effective_base, error=rules.message))
        else:
            checks.append(
                capability._merge_rules_check(
                    effective_base,
                    squash_allowed=rules.squash_allowed,
                    merge_queue_required=rules.merge_queue_required,
                )
            )

        base_sha: str | None
        try:
            base_sha = self._git.remote_branch_sha(effective_base)
        except train.TrainReconstructionError as exc:
            if exc.error_type != "git_error":
                raise
            base_sha = None
            checks.append(
                capability._remote_base_check(effective_base, error=_raw_prepare_git_error(exc))
            )
        except git_mod.GitError as exc:
            base_sha = None
            checks.append(capability._remote_base_check(effective_base, error=str(exc)))
        else:
            checks.append(capability._remote_base_check(effective_base, sha=base_sha))

        if base_sha is not None:
            push_urls = self._git.push_urls()
            if isinstance(push_urls, DeliveryGit.ProbeError):
                checks.append(capability._push_urls_error_check(push_urls.message))
            elif not push_urls.urls:
                checks.append(capability._empty_push_urls_check())
            else:
                for push_url in push_urls.urls:
                    probe = self._git.probe_atomic_push(
                        push_url=push_url,
                        base_branch=effective_base,
                        base_sha=base_sha,
                    )
                    error = probe.message if isinstance(probe, DeliveryGit.ProbeError) else None
                    checks.append(capability._atomic_push_check(push_url, error=error))

        failures = tuple(check for check in checks if not check.ok)
        if failures:
            details = "\n".join(f"- {check.name}: {check.detail}" for check in failures)
            raise DeliveryError(
                f"This repository cannot take a stacked delivery train against base "
                f"{effective_base!r}:\n{details}",
                error_type="capability_unsupported",
            )
        return PrepareResult(kind="authoring", base=effective_base)

    def status(self, request: StatusRequest) -> StatusResult:
        """Reconstruct one delivery status and expose its train/no-train branches explicitly."""
        try:
            status = train.reconstruct_train(
                request.objective_id,
                store=self._persistence,
                issues=self._persistence,
                persistence=self._persistence,
                git=self._git,
                github=self._github,
            )
        except train.TrainReconstructionError as exc:
            if (
                exc.error_type == "capability_unsupported"
                or exc.error_type not in _DELIVERY_ERROR_TYPES
            ):
                raise
            raise DeliveryError(str(exc), error_type=exc.error_type) from exc
        except (IssueBackendError, ObjectiveStoreError, TrainPersistenceError) as exc:
            raise DeliveryError(str(exc), error_type="github_error") from exc

        if isinstance(status, train.DeliveryTrain):
            return StatusResult(
                objective_id=status.objective_id,
                objective_url=status.objective_url,
                redirected_from=status.redirected_from,
                train=status,
                no_train_reason=None,
            )
        return StatusResult(
            objective_id=status.objective_id,
            objective_url=status.objective_url,
            redirected_from=status.redirected_from,
            train=None,
            no_train_reason=status.reason,
        )
