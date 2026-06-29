"""`perk learn evidence --json` — gather a landed plan's session-grounded evidence bundle.

The first consumer of the cross-run session resolver (`perk/learn/sessions.py`) + the session-export
seam (`perk/learn/export.py`). Reads the local `cache.plan-ref` (no positional arg, mirroring
`perk learn capture` / `perk pr review-context`), resolves the plan + PR + planning/implementation
session JSONLs + a basic existing-docs inventory, materializes the artifacts into a worktree scratch
dir, and emits a stable bundle manifest. A learn-docs consolidation plan (non-empty plan-header
`consumed_learn`) returns a stable skip up front.

Each source degrades independently — one missing/ambiguous source never fails the command. Exit
codes: 0 ok (skip OR gathered manifest) · 1 no plan-ref / invalid · 2 not-a-repo.
"""

import json

import click

from perk.boundary import OutputModel
from perk.cli.commands.learn.shared import fail
from perk.cli.context import require_repo
from perk.cli.ensure import UserFacingCliError
from perk.learn.evidence import DocEntry, EvidenceBundle, EvidenceSource, gather_evidence
from perk.state import cache
from perk.substrate.output import machine_output, user_output


@click.command("evidence")
@click.option("--json", "as_json", is_flag=True, help="Emit a machine-readable manifest to stdout.")
@click.pass_context
def evidence_learn(ctx: click.Context, *, as_json: bool) -> None:
    """Gather a landed plan's session-grounded evidence bundle (read-only; the /learn cold door).

    \b
    Run from inside the plan's worktree (it reads the local cache.plan-ref).
    """
    try:
        repo_root = require_repo(ctx)
        plan_ref = cache.read_plan_ref(repo_root)
        if plan_ref is None:
            raise UserFacingCliError(
                "No saved plan in this worktree\nRun /plan-save then perk implement first.",
                error_type="no_plan_ref",
            )
        bundle = gather_evidence(repo_root, plan_ref)
    except UserFacingCliError as exc:
        fail(
            ctx,
            as_json=as_json,
            error_type=exc.error_type or "invalid_input",
            message=exc.format_message(),
        )
        return

    if as_json:
        machine_output(json.dumps(EvidenceBundleOut.from_domain(bundle).model_dump(mode="json")))
    else:
        _render_human(bundle)


class EvidenceSourceOut(OutputModel):
    """The ``--json`` serialization boundary of :class:`EvidenceSource` (order load-bearing)."""

    category: str
    label: str
    status: str
    artifact: str | None
    detail: str | None

    @classmethod
    def from_domain(cls, source: EvidenceSource) -> "EvidenceSourceOut":
        return cls(
            category=source.category,
            label=source.label,
            status=source.status,
            artifact=source.artifact,
            detail=source.detail,
        )


class DocEntryOut(OutputModel):
    """The ``--json`` serialization boundary of :class:`DocEntry` (order load-bearing)."""

    kind: str
    path: str
    title: str | None
    snippet: str | None

    @classmethod
    def from_domain(cls, entry: DocEntry) -> "DocEntryOut":
        return cls(kind=entry.kind, path=entry.path, title=entry.title, snippet=entry.snippet)


class EvidenceBundleOut(OutputModel):
    """The ``--json`` serialization boundary of :class:`EvidenceBundle` (order load-bearing).

    Always serializes the full shape (no ``exclude_unset``) so a machine consumer sees stable keys
    (absent values render ``null``) — matching the ``LearnCaptureOut`` full-dump convention.
    """

    success: bool
    error_type: str | None
    message: str | None
    skipped: bool
    skip_reason: str | None
    plan_id: str | None
    bundle_dir: str | None
    sources: tuple[EvidenceSourceOut, ...]
    existing_docs: tuple[DocEntryOut, ...]

    @classmethod
    def from_domain(cls, bundle: EvidenceBundle) -> "EvidenceBundleOut":
        return cls(
            success=True,
            error_type=None,
            message=None,
            skipped=bundle.skipped,
            skip_reason=bundle.skip_reason,
            plan_id=bundle.plan_id,
            bundle_dir=bundle.bundle_dir,
            sources=tuple(EvidenceSourceOut.from_domain(s) for s in bundle.sources),
            existing_docs=tuple(DocEntryOut.from_domain(d) for d in bundle.existing_docs),
        )


def _render_human(bundle: EvidenceBundle) -> None:
    if bundle.skipped:
        user_output(click.style("learn evidence skipped", dim=True) + f" — {bundle.skip_reason}")
        return
    by_category: dict[str, list[EvidenceSource]] = {}
    for source in bundle.sources:
        by_category.setdefault(source.category, []).append(source)
    plan_status = _first_status(by_category, "plan")
    pr_status = _first_status(by_category, "pr")
    planning = by_category.get("planning-session", [])
    planning_summary = "/".join(s.status for s in planning) or "missing"
    impl_runs = len(
        {
            s.label.split("/")[0]
            for s in by_category.get("implementation-session", [])
            if s.label != "(none)"
        }
    )
    docs = len(bundle.existing_docs)
    user_output(
        f"plan {plan_status}, pr {pr_status}, planning {planning_summary}, "
        f"{impl_runs} impl run(s), docs: {docs}"
    )


def _first_status(by_category: dict[str, list[EvidenceSource]], category: str) -> str:
    entries = by_category.get(category, [])
    return entries[0].status if entries else "missing"
