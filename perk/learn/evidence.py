"""The learn evidence-bundle gatherer (`contracts.md` §8.35, node 3.1).

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

import yaml

from perk import github, plan
from perk.backends import resolve
from perk.backends.issue_backend import IssueBackend, IssueBackendError, PlanState
from perk.boundary import LenientParseModel
from perk.github import GitHubError
from perk.learn.export import export_session_jsonl
from perk.learn.sessions import ImplementationRun, resolve_plan_sessions
from perk.run import launch
from perk.state import cache
from perk.state.session_pointers import SessionPointer
from perk.substrate.output import user_output

SourceStatus = Literal["found", "missing", "ambiguous"]

_SNIPPET_LEN = 240

# The three conventional existing-docs roots scanned by `scan_existing_docs`. Top-level `skills/`
# is deliberately excluded — it is perk's own codebase, not the workflow-managed skill surface;
# `.perk/skills/` is the repo-authored skill surface.
_LEARNED_GLOB = ("docs/learned", "**/*.md")
_USER_DOCS_GLOB = ("docs/user-docs", "**/*.md")
_SKILLS_GLOB = (".perk/skills", "*/SKILL.md")


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
class DocEntry:
    """One inventoried existing doc: its kind, repo-relative path, and (best-effort) metadata."""

    kind: str  # "learned" | "user-doc" | "skill"
    path: str
    title: str | None
    snippet: str | None


@dataclass(frozen=True)
class EvidenceBundle:
    """The full gathered manifest. A skip yields ``skipped=True`` with empty source/doc tuples."""

    skipped: bool
    skip_reason: str | None
    plan_id: str | None
    bundle_dir: str | None
    sources: tuple[EvidenceSource, ...]
    existing_docs: tuple[DocEntry, ...]


class _DocFrontmatter(LenientParseModel):
    """The untrusted read edge for any inventoried doc's YAML frontmatter.

    Serves a learned doc (``title``/``read_when``) and a skill (``name``/``description``); the
    lenient base (``extra="ignore"``) drops every other frontmatter key a doc may carry.
    """

    title: str | None = None
    read_when: str | None = None
    name: str | None = None
    description: str | None = None


# ---------------------------------------------------------------------------
# Pure existing-docs inventory
# ---------------------------------------------------------------------------


def scan_existing_docs(repo_root: Path) -> tuple[DocEntry, ...]:
    """Inventory the three conventional docs roots; deterministic (sorted by path), never raises.

    ``docs/learned/**/*.md`` (frontmatter ``title``/``read_when``), ``docs/user-docs/**/*.md``
    (first ``# `` heading + first paragraph), ``.perk/skills/*/SKILL.md`` (frontmatter
    ``name``/``description``). Non-existent roots yield nothing.
    """
    entries: list[DocEntry] = []
    entries.extend(_scan_root(repo_root, "learned", _LEARNED_GLOB))
    entries.extend(_scan_root(repo_root, "user-doc", _USER_DOCS_GLOB))
    entries.extend(_scan_root(repo_root, "skill", _SKILLS_GLOB))
    return tuple(sorted(entries, key=lambda e: e.path))


def _scan_root(repo_root: Path, kind: str, glob: tuple[str, str]) -> list[DocEntry]:
    root = repo_root / glob[0]
    if not root.is_dir():
        return []
    out: list[DocEntry] = []
    for path in root.glob(glob[1]):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        title, snippet = _doc_metadata(kind, text)
        out.append(DocEntry(kind=kind, path=_rel(repo_root, path), title=title, snippet=snippet))
    return out


def _doc_metadata(kind: str, text: str) -> tuple[str | None, str | None]:
    """Best-effort ``(title, snippet)`` for a doc; never raises (malformed → ``(None, None)``)."""
    if kind in ("learned", "skill"):
        front = _frontmatter_dict(text)
        if not front:
            return None, None
        try:
            meta = _DocFrontmatter.model_validate(front)
        except ValueError:
            return None, None
        if kind == "skill":
            return meta.name, _truncate(meta.description)
        return meta.title, _truncate(meta.read_when)
    return _user_doc_metadata(text)


def _user_doc_metadata(text: str) -> tuple[str | None, str | None]:
    """A user-doc has no frontmatter: title = first ``# `` heading, snippet = first paragraph."""
    title: str | None = None
    snippet: str | None = None
    paragraph: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if title is None and line.startswith("# "):
            title = line[2:].strip()
            continue
        if title is not None:
            if line:
                paragraph.append(line)
            elif paragraph:
                break
    if paragraph:
        snippet = _truncate(" ".join(paragraph))
    return title, snippet


def _frontmatter_dict(text: str) -> dict[str, object]:
    """Parse a doc's leading ``---``-delimited YAML frontmatter mapping; ``{}`` when absent or
    malformed (mirrors the ``repo_skills.py`` splitter — never raises)."""
    if not text.startswith("---\n"):
        return {}
    lines = text.split("\n")
    end = next((i for i in range(1, len(lines)) if lines[i] == "---"), None)
    if end is None:
        return {}
    try:
        parsed = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _rel(repo_root: Path, path: Path) -> str:
    """``path`` relative to ``repo_root`` (POSIX-stable), else the absolute string."""
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return str(path)


def _truncate(value: str | None) -> str | None:
    """A bounded single-line snippet (``≈240`` chars), or ``None`` for an empty/absent value."""
    if not value:
        return None
    flat = " ".join(value.split())
    if not flat:
        return None
    if len(flat) <= _SNIPPET_LEN:
        return flat
    return flat[: _SNIPPET_LEN - 1].rstrip() + "…"


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
            dest.write_text(body, encoding="utf-8")
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
        dest.write_text(context.diff, encoding="utf-8")
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
