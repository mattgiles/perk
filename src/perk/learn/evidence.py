"""The learn evidence-bundle gatherer (`contracts.md` §8.35).

Resolve a landed plan's session-grounded evidence — the saved plan, the merged PR's
metadata/diff, the planning + implementation session JSONLs (main + worker, labelled
distinctly), and a **basic** existing-docs inventory — materialize the artifacts into a worktree
scratch dir, and produce a **stable bundle manifest** with per-source ``found``/``missing``/
``ambiguous`` statuses.

Discipline (mirrors :mod:`perk.learn.export` / :mod:`perk.learn.sessions`):

- **Never fail on one missing source.** Each source gathers in its own try/except and degrades to
  ``missing`` (or ``ambiguous`` for a multi-candidate PR). The bundle is always returned.
- **Expected absence is silent; a genuine error is loud-but-non-fatal.** A ``None`` lookup / null
  slot / no impl runs → ``missing`` silently; an ``IssueBackendError`` / ``GitHubError`` /
  ``OSError`` → ``missing`` + a ``user_output("warning: …")`` to stderr.
- **A learn-docs consolidation plan returns a stable skip up front** (non-empty plan-header
  ``consumed_learn``), before any PR/session/docs gathering.

The serialize edge (the ``--json`` envelope) lives in the command file
(``perk/cli/commands/learn/evidence_cmd.py``); this module is the domain + typed impl + pure
helpers. A catastrophic environment failure (e.g. the bundle-dir ``mkdir`` raising) is **not** a
per-source miss — it bubbles to the CLI error boundary; only per-source failures degrade.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from perk import github, plan
from perk.backends import resolve
from perk.backends.issue_backend import IssueBackend, IssueBackendError, PlanState
from perk.github import GitHubError
from perk.learn.docs_scan import (
    DocEntry,
    DocFindings,
    _rel,
    scan_docs_richly,
    scan_existing_docs,
)
from perk.learn.export import export_session_jsonl
from perk.learn.normalize import sanitize_surrogates
from perk.learn.sessions import ImplementationRun, resolve_plan_sessions
from perk.run import launch
from perk.state import cache
from perk.state.session_pointers import SessionPointer
from perk.substrate.output import user_output

SourceStatus = Literal["found", "missing", "ambiguous"]

# `DocEntry`, the doc-scan helpers, and the rich `DocFindings` family live in the dependency-light
# leaf `perk.learn.docs_scan`; re-exported above so existing call sites import them from here
# unchanged. `scan_docs_richly` / the findings sub-types are re-exported for the same reason.


@dataclass(frozen=True)
class EvidenceSource:
    """One uniform manifest entry: a category/label slot with a resolved status + optional
    materialized artifact (relative to repo_root) + a human ``detail`` string."""

    category: str
    label: str
    status: SourceStatus
    artifact: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class EvidenceBundle:
    """The full gathered manifest. A skip yields ``skipped=True`` with empty source/doc tuples
    and an empty ``docs_findings``."""

    skipped: bool
    skip_reason: str | None
    plan_id: str | None
    bundle_dir: str | None
    sources: tuple[EvidenceSource, ...]
    existing_docs: tuple[DocEntry, ...]
    docs_findings: DocFindings


# ---------------------------------------------------------------------------
# Typed gather
# ---------------------------------------------------------------------------


def gather_evidence(repo_root: Path, plan_ref: plan.PlanRef) -> EvidenceBundle:
    """Gather the evidence bundle for the plan named by ``plan_ref`` (degrades per-source).

    The command owns the ``no_plan_ref`` precondition and passes the already-read ``plan_ref``.
    A non-empty plan-header ``consumed_learn`` returns a stable skip up front (no gathering).
    """
    plan_id = plan_ref.pr_id
    branch = launch.resolve_plan_worktree_name(plan_ref)

    backend = _try_resolve_backend(repo_root)
    plan_state = _try_get_plan(backend, plan_id)

    if plan_state is not None and _consumed_learn_nonempty(plan_state.header):
        return EvidenceBundle(
            skipped=True,
            skip_reason="learn-docs plan (consumed_learn non-empty)",
            plan_id=plan_id,
            bundle_dir=None,
            sources=(),
            existing_docs=(),
            docs_findings=DocFindings(),
        )

    bundle_dir = cache.scratch_dir(repo_root) / "learn-evidence"
    bundle_dir.mkdir(parents=True, exist_ok=True)

    docs = scan_existing_docs(repo_root)
    sources: list[EvidenceSource] = [
        _plan_source(repo_root, backend, plan_state, plan_id, bundle_dir),
        _gather_pr(repo_root, branch, bundle_dir),
        *_gather_sessions(repo_root, plan_id, bundle_dir),
        _existing_docs_source(docs),
    ]

    return EvidenceBundle(
        skipped=False,
        skip_reason=None,
        plan_id=plan_id,
        bundle_dir=_rel(repo_root, bundle_dir),
        sources=tuple(sources),
        existing_docs=docs,
        docs_findings=scan_docs_richly(repo_root),
    )


def _try_resolve_backend(repo_root: Path) -> IssueBackend | None:
    """Resolve the issue backend; ``None`` + a warning on any failure (never sinks the gather)."""
    try:
        return resolve.resolve_issue_backend(repo_root)
    except (IssueBackendError, GitHubError) as exc:
        user_output(f"warning: could not resolve issue backend: {exc}")
        return None


def _try_get_plan(backend: IssueBackend | None, plan_id: str) -> PlanState | None:
    """Fetch the plan once (doubles as the skip signal + the ``plan`` source).

    A genuine backend error warns (loud-but-non-fatal); a not-found returns ``None`` silently. A
    fetch failure is **never** a learn-docs signal — the caller proceeds to gather.
    """
    if backend is None:
        return None
    try:
        return backend.get_plan(issue_id=plan_id)
    except (IssueBackendError, GitHubError) as exc:
        user_output(f"warning: could not read plan #{plan_id}: {exc}")
        return None


def _consumed_learn_nonempty(header: dict[str, object]) -> bool:
    """A non-empty list ``consumed_learn`` marks a learn-docs consolidation plan (LBYL)."""
    value = header.get("consumed_learn")
    return isinstance(value, list) and bool(value)


def _plan_source(
    repo_root: Path,
    backend: IssueBackend | None,
    plan_state: PlanState | None,
    plan_id: str,
    bundle_dir: Path,
) -> EvidenceSource:
    """Materialize ``plan-body.md`` from the resolved plan; ``missing`` when unreadable."""
    if plan_state is None:
        return EvidenceSource(
            category="plan", label=plan_id, status="missing", detail="plan not found"
        )
    body = _try_get_plan_body(backend, plan_id)
    artifact: str | None = None
    if body:
        try:
            dest = bundle_dir / "plan-body.md"
            cache.atomic_write_text(dest, sanitize_surrogates(body))
            artifact = _rel(repo_root, dest)
        except OSError as exc:
            user_output(f"warning: could not write plan body for #{plan_id}: {exc}")
    return EvidenceSource(
        category="plan",
        label=plan_id,
        status="found",
        artifact=artifact,
        detail=f"{plan_state.title} ({plan_state.state})",
    )


def _try_get_plan_body(backend: IssueBackend | None, plan_id: str) -> str | None:
    if backend is None:
        return None
    try:
        return backend.get_plan_body(issue_id=plan_id)
    except (IssueBackendError, GitHubError) as exc:
        user_output(f"warning: could not read plan body for #{plan_id}: {exc}")
        return None


def _gather_pr(repo_root: Path, branch: str, bundle_dir: Path) -> EvidenceSource:
    """Resolve the PR for ``branch``; ``ambiguous`` on multi-candidate, else ``found``/``missing``.

    ``0`` matches → ``missing``; exactly one MERGED PR (even alongside closed/superseded PRs) →
    ``found``; exactly one match (any state) → ``found``; otherwise → ``ambiguous`` (no diff).
    """
    try:
        prs = github.list_prs_for_branch(branch=branch, repo_root=repo_root)
    except GitHubError as exc:
        user_output(f"warning: could not list PRs for {branch!r}: {exc}")
        return EvidenceSource(
            category="pr", label=branch, status="missing", detail="PR lookup failed"
        )

    if not prs:
        return EvidenceSource(
            category="pr", label=branch, status="missing", detail=f"no PR for branch {branch}"
        )

    merged = [pr for pr in prs if pr.state == "MERGED"]
    chosen = merged[0] if len(merged) == 1 else (prs[0] if len(prs) == 1 else None)
    if chosen is None:
        return EvidenceSource(
            category="pr",
            label=branch,
            status="ambiguous",
            detail=f"{len(prs)} PRs match branch {branch}; {len(merged)} merged",
        )

    artifact = _materialize_pr_diff(repo_root, branch, chosen, bundle_dir)
    return EvidenceSource(
        category="pr",
        label=branch,
        status="found",
        artifact=artifact,
        detail=f"#{chosen.number} {chosen.state} base={chosen.base_ref}",
    )


def _materialize_pr_diff(
    repo_root: Path, branch: str, pr: github.PullRequest, bundle_dir: Path
) -> str | None:
    """Best-effort ``pr.diff`` materialization — a diff-read failure leaves the PR ``found``."""
    try:
        context = github.get_pr_review_context(
            pr_number=pr.number, branch=branch, repo_root=repo_root, plan_body=None
        )
        dest = bundle_dir / "pr.diff"
        cache.atomic_write_text(dest, sanitize_surrogates(context.diff))
        return _rel(repo_root, dest)
    except (GitHubError, OSError) as exc:
        user_output(f"warning: could not materialize diff for PR #{pr.number}: {exc}")
        return None


def _gather_sessions(repo_root: Path, plan_id: str, bundle_dir: Path) -> list[EvidenceSource]:
    """Resolve + export the planning and implementation session JSONLs (main + worker each).

    Order: planning main/worker, then per ``ImplementationRun`` (header order) main/worker. When
    there are no implementation runs, a single ``(none)`` ``missing`` entry stands in.

    A resolution failure (the node-2.1 seam re-fetches the plan and may raise an
    ``IssueBackendError`` / ``GitHubError``) degrades every session slot to ``missing`` + a
    warning — never sinks the whole gather.
    """
    try:
        resolved = resolve_plan_sessions(repo_root, plan_id)
    except (IssueBackendError, GitHubError) as exc:
        user_output(f"warning: could not resolve sessions for #{plan_id}: {exc}")
        return [
            EvidenceSource(category="planning-session", label="main", status="missing"),
            EvidenceSource(category="planning-session", label="worker", status="missing"),
            EvidenceSource(
                category="implementation-session",
                label="(none)",
                status="missing",
                detail="session resolution failed",
            ),
        ]
    sources: list[EvidenceSource] = [
        _session_source(
            "planning-session",
            "main",
            resolved.planning_main.pointer,
            bundle_dir / "planning-main.jsonl",
            repo_root,
        ),
        _session_source(
            "planning-session",
            "worker",
            resolved.planning_worker.pointer,
            bundle_dir / "planning-worker.jsonl",
            repo_root,
        ),
    ]
    if not resolved.implementation:
        sources.append(
            EvidenceSource(
                category="implementation-session",
                label="(none)",
                status="missing",
                detail="no implementation runs",
            )
        )
        return sources
    for index, run in enumerate(resolved.implementation):
        sources.extend(_impl_run_sources(run, index, bundle_dir, repo_root))
    return sources


def _impl_run_sources(
    run: ImplementationRun, index: int, bundle_dir: Path, repo_root: Path
) -> list[EvidenceSource]:
    return [
        _session_source(
            "implementation-session",
            f"{run.run_id}/main",
            run.main.pointer,
            bundle_dir / f"implementation-{index}-main.jsonl",
            repo_root,
        ),
        _session_source(
            "implementation-session",
            f"{run.run_id}/worker",
            run.worker.pointer,
            bundle_dir / f"implementation-{index}-worker.jsonl",
            repo_root,
        ),
    ]


def _session_source(
    category: str, label: str, pointer: SessionPointer | None, dest: Path, repo_root: Path
) -> EvidenceSource:
    """Export one session slot; the export status (``found``/``missing``) is the source status."""
    export = export_session_jsonl(pointer, dest)
    if export.status == "found" and export.artifact is not None:
        return EvidenceSource(
            category=category,
            label=label,
            status="found",
            artifact=_rel(repo_root, export.artifact),
        )
    return EvidenceSource(category=category, label=label, status="missing")


def _existing_docs_source(docs: tuple[DocEntry, ...]) -> EvidenceSource:
    """A single roll-up entry: ``found`` when the inventory is non-empty, else ``missing``."""
    status: SourceStatus = "found" if docs else "missing"
    return EvidenceSource(
        category="existing-docs",
        label="inventory",
        status=status,
        detail=f"{len(docs)} doc(s)",
    )
