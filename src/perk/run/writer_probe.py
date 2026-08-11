"""Production remote-writer observation for delivery synchronization.

This seam lives with remote-run discovery rather than a Click command so every publication
caller can share the same fail-closed observation contract.
"""

from collections.abc import Sequence
from pathlib import Path

from perk.delivery import sync
from perk.github import GitHubError
from perk.run import discovery


class GhaRemoteWriterProbe:
    """The production :class:`~perk.delivery.sync.RemoteWriterProbe`.

    Active runs are listed with server-side status filters and matched through the managed
    run-name convention. Any listing failure becomes :class:`WriterObservationError`; an
    unreadable observation is never interpreted as no active writer.
    """

    def __init__(self, repo_root: Path, *, exclude_run_id: str | None = None) -> None:
        self._repo_root = repo_root
        self._exclude_run_id = exclude_run_id

    def active_plan_ids(self, plan_ids: Sequence[str]) -> frozenset[str]:
        try:
            return discovery.active_writer_plan_ids(
                self._repo_root,
                list(plan_ids),
                exclude_run_id=self._exclude_run_id,
            )
        except GitHubError as exc:
            raise sync.WriterObservationError(str(exc)) from exc
