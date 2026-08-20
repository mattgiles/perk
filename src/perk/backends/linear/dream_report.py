"""The Linear dream-artifact publisher (contracts.md §8.64).

The Linear arm of the per-backend human-visibility strategy for a persisted dream report: the
marker-keyed companion parts live on the Project metadata sentinel (machine-readable, not a
human surface), so the RENDERED report is additionally uploaded as a workspace file asset
(``fileUpload`` → the signed PUT) and attached to the objective project's **Resources** via the
existing ``entityExternalLinkCreate`` op. GitHub needs no publisher — the parts on the objective
issue itself are the visible artifact (the no-op arm lives beside the backend resolver; this
module never imports the resolver — the import direction is resolver → backend, never back).

Fail-loud: every boundary failure raises ``IssueBackendError`` and fails the save (this is part
of the convergent companion sequence, never fail-open bookkeeping); the converging retry
re-publishes. The accepted **orphan-asset residual**: a crash after the upload but before the
link write leaves an uploaded asset with no discoverable run key — the retry uploads a fresh
asset and links it; unreferenced workspace assets are inert (documented in §8.64 beside the
pre-sentinel orphan window).
"""

from collections.abc import Sequence
from pathlib import Path

from perk.backends.linear.client import LinearClient
from perk.backends.linear.project_ops import _LinearProjectOps

_CONTENT_TYPE = "text/markdown"


def _artifact_label(run_id: str) -> str:
    """The Resources link label — the run-keyed identity the presence probe keys on."""
    return f"Dream report ({run_id})"


class LinearDreamArtifactPublisher:
    """``DreamArtifactPublisher`` over the Linear project store's objective model
    (``objective_id`` IS the project UUID). Presence probe first: a Resources link already
    labeled for this run skips the whole upload (retry idempotence for the LINK — the asset
    itself has no discoverable run key, hence the orphan residual above)."""

    def __init__(self, client: LinearClient, *, team_key: str, repo_root: Path) -> None:
        self._client = client
        self._projects = _LinearProjectOps(client, team_key=team_key, repo_root=repo_root)

    def publish(self, *, objective_id: str, run_id: str, parts: Sequence[str]) -> None:
        label = _artifact_label(run_id)
        links = self._projects.project_external_links(objective_id)
        if any(link.get("label") == label for link in links):
            return  # already published — converged
        # The uploaded bytes are the canonical parts joined verbatim — a file asset, not a
        # comment body, so the Linear comment transcoder never applies.
        content = "\n\n".join(parts).encode("utf-8")
        target = self._client.file_upload(
            content_type=_CONTENT_TYPE,
            filename=f"dream-report-{run_id}.md",
            size=len(content),
        )
        self._client.upload_asset(
            target.upload_url,
            headers=target.headers,
            content=content,
            content_type=_CONTENT_TYPE,
        )
        self._projects.create_entity_external_link(
            project_id=objective_id, label=label, url=target.asset_url
        )
