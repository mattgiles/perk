"""The Linear dream-artifact publish flow (contracts.md §8.64).

The Linear arm of the per-backend human-visibility step for a persisted dream report: the
marker-keyed companion parts live on the Project metadata sentinel (machine-readable, not a
human surface), so the RENDERED report is additionally uploaded as a workspace file asset
(``LinearClient.upload_file``) and attached to the objective project's **Resources** via the
existing ``entityExternalLinkCreate`` op. GitHub needs no publish step — the parts on the
objective issue itself are the visible artifact (the immediate-return arm lives beside the
backend resolver; this module never imports the resolver — the import direction is resolver →
backend, never back).

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


def publish_dream_artifact(
    client: LinearClient,
    *,
    team_key: str,
    repo_root: Path,
    objective_id: str,
    run_id: str,
    parts: Sequence[str],
) -> None:
    """Publish the rendered report on the objective project (``objective_id`` IS the project
    UUID). Presence probe first: a Resources link already labeled for this run skips the whole
    upload (retry idempotence for the LINK — the asset itself has no discoverable run key, hence
    the orphan residual above)."""
    ops = _LinearProjectOps(client, team_key=team_key, repo_root=repo_root)
    label = _artifact_label(run_id)
    links = ops.project_external_links(objective_id)
    if any(link.get("label") == label for link in links):
        return  # already published — converged
    # The uploaded bytes are the canonical parts joined verbatim — a file asset, not a comment
    # body, so the Linear comment transcoder never applies.
    content = "\n\n".join(parts).encode("utf-8")
    asset_url = client.upload_file(
        filename=f"dream-report-{run_id}.md", content_type=_CONTENT_TYPE, content=content
    )
    ops.create_entity_external_link(project_id=objective_id, label=label, url=asset_url)
