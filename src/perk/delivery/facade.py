"""The canonical repository-scoped delivery status façade.

``Delivery`` is the compact public interface for delivery-train status. It composes three
nominal aggregate authorities and delegates the pure projection to :mod:`perk.delivery.train`.
The pure core and production adapters remain internal seams while later operation families
migrate onto this façade.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from perk.backends.issue_backend import IssueBackendError, PlanState
from perk.backends.objective_store import ObjectiveState, ObjectiveStoreError
from perk.delivery import train
from perk.delivery.journal import JournalFold
from perk.delivery.persistence import TrainPersistenceError

_STATUS_ERROR_TYPES = frozenset(
    {
        "objective_not_found",
        "invalid_delivery_policy",
        "invalid_train",
        "git_error",
        "github_error",
        "supersession_corruption",
    }
)


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
    """A bounded delivery-status failure with a stable machine ``error_type``."""

    def __init__(self, message: str, *, error_type: str) -> None:
        if error_type not in _STATUS_ERROR_TYPES:
            allowed = ", ".join(sorted(_STATUS_ERROR_TYPES))
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
    """Aggregate status authority for repository Git observations."""

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
    """Aggregate status authority for GitHub PR and native-stack observations."""

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


class Delivery:
    """Repository-scoped delivery operations, beginning with the status vertical slice."""

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
            if exc.error_type not in _STATUS_ERROR_TYPES:
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
