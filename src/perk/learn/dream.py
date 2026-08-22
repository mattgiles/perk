"""The gather core for the ``perk learn dream`` factory (`contracts.md` §8.59).

Whole-corpus enumeration over ``docs/learned/`` + the two-source cluster partition (the committed
registry joined with per-doc ``cluster`` frontmatter) + the versioned dream-manifest render/write.
Dependency-light on purpose (stdlib + ``perk.learn.harvest`` + ``perk.learn.docs_scan`` +
``perk.learn.docs_sync`` + ``perk.boundary`` + ``perk.state.cache`` + ``perk.cli.ensure``) and
**pure**: ``commit_sha`` and ``run_id`` are parameters — the door owns HEAD capture, sync, and
the clean-tree/origin preflight. No public command registers here; the manifest is the contract
the TypeScript analyst wave strictly decodes.

Dream is a **complete-corpus audit**, so its posture diverges from harvest's deliberately: where
harvest silently *filters* an escaping doc out of the eligible corpus, dream *refuses* — a
completed gather's doc set is exactly the ``read_learned_docs`` enumeration, never a silently
narrowed subset.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from perk.boundary import OutputModel
from perk.cli.ensure import UserFacingCliError
from perk.learn.docs_scan import (
    BrokenDocPath,
    DuplicateGroup,
    LearnedDoc,
    StalePointer,
    read_learned_docs,
)
from perk.learn.docs_sync import (
    ClusterRegistry,
    CueHazard,
    DistillationIssue,
    InvalidClusterRegistry,
    OverlongCue,
    SourceCodeBlock,
    check_docs,
    load_cluster_registry,
)
from perk.learn.harvest import MAX_LANE_DOCS, eligible_learned_docs, partition_lanes
from perk.state import cache

# The dream-manifest contract version — dream's own version line (a string, the harvest
# precedent), independent of harvest's `MANIFEST_SCHEMA_VERSION`; the TS decoder pins the same
# string.
DREAM_MANIFEST_SCHEMA_VERSION = "1"

# The run-scoped scratch filename the dream manifest is written under.
DREAM_MANIFEST_FILENAME = "dream-manifest.json"


@dataclass(frozen=True)
class DreamLane:
    """One dream analyst lane: a stable ``"<cluster>-<n>"`` id (1-based per cluster), the
    cluster's registry rollup cue (``None`` in category fallback, where the id is harvest's
    ``"<category>-<n>"`` shape), and its docs."""

    id: str
    rollup: str | None
    docs: tuple[LearnedDoc, ...]


@dataclass(frozen=True)
class DreamFindings:
    """The bounded, curated docs-check subset the manifest carries (`contracts.md` §8.59).

    Every family is filtered by its **owner-doc field only** against the manifest path set (the
    field vocabularies are ``docs_sync``/``docs_scan``'s — reused, never widened). Structural =
    verifiable breakage (stale pointers, broken doc references, duplicate ``read_when`` cues,
    missing frontmatter); advisory = quality/read-cost signals (distillation issues, copied-source
    blocks, overlong cues, cue hazards, empty registry clusters).
    """

    stale_pointers: tuple[StalePointer, ...]
    broken_doc_paths: tuple[BrokenDocPath, ...]
    duplicate_cues: tuple[DuplicateGroup, ...]
    missing_frontmatter: tuple[str, ...]
    distillation_issues: tuple[DistillationIssue, ...]
    source_code_blocks: tuple[SourceCodeBlock, ...]
    overlong_cues: tuple[OverlongCue, ...]
    cue_hazards: tuple[CueHazard, ...]
    empty_clusters: tuple[str, ...]


@dataclass(frozen=True)
class DreamGather:
    """A completed dream gather: the full corpus, its lanes, the partition mode, per-doc raw
    byte sizes (keyed by ``LearnedDoc.path``), and the curated findings."""

    docs: tuple[LearnedDoc, ...]
    lanes: tuple[DreamLane, ...]
    registry_mode: Literal["clusters", "categories"]
    sizes: Mapping[str, int]
    findings: DreamFindings

    @property
    def doc_count(self) -> int:
        """The gathered corpus size (== the ``read_learned_docs`` enumeration, by refusal)."""
        return len(self.docs)

    @property
    def total_bytes(self) -> int:
        """The summed raw byte size of every gathered doc."""
        return sum(self.sizes.values())


def resolve_dream_docs(repo_root: Path) -> tuple[tuple[LearnedDoc, Path], ...]:
    """Resolve the FULL learned corpus as ``(doc, resolved_path)`` pairs, in corpus order.

    Two dream-specific refusals on top of :func:`eligible_learned_docs` (which itself refuses a
    symlinked corpus root as ``invalid_input``):

    - **Escaped-symlink refusal**: any enumerated doc missing from the eligible set (a symlink
      resolving outside ``docs/learned/``) → ``invalid_input`` naming every escaping doc. Dream
      refuses where harvest filters — a complete-corpus audit must never silently narrow the
      corpus, so a completed gather's doc set is exactly the ``read_learned_docs`` enumeration.
    - **Empty corpus** → ``no_learned_docs``.
    """
    pairs = eligible_learned_docs(repo_root)
    eligible_paths = {doc.path for doc, _resolved in pairs}
    escaping = [doc.path for doc in read_learned_docs(repo_root) if doc.path not in eligible_paths]
    if escaping:
        raise UserFacingCliError(
            "learned doc(s) resolve outside docs/learned/ (escaping symlinks) — a dream gather "
            "audits the complete corpus and refuses to narrow it: " + ", ".join(escaping),
            error_type="invalid_input",
        )
    if not pairs:
        raise UserFacingCliError(
            "No learned docs found — nothing to dream over (the generated "
            "docs/learned/index.md is never included).",
            error_type="no_learned_docs",
        )
    return pairs


def partition_dream_lanes(
    docs: Sequence[LearnedDoc], registry: ClusterRegistry | None
) -> tuple[DreamLane, ...]:
    """The two-source join: registry clusters joined with per-doc ``cluster`` frontmatter. Pure and
    deterministic; resolved paths are never partition input.

    **Registry mode**: lanes in **registry file order** (the presentation SSOT, matching the
    ``docs_sync`` rendering); per cluster, members = the docs whose ``cluster`` matches, sorted
    by ``path``, chunked sequentially at :data:`MAX_LANE_DOCS`; lane ids ``"<cluster>-<n>"``,
    1-based per cluster; every chunk lane of a cluster carries that cluster's ``rollup``. An
    empty cluster emits no lane. Any doc whose ``cluster`` is ``None`` or names no registry id →
    ``incomplete_registry`` listing every offending doc (the docs-sync posture — never a silent
    fallback).

    **Category fallback** (``registry=None`` — the file is truly absent): delegate to
    :func:`partition_lanes` — ``"<category>-<n>"`` ids in sorted-group order, ``rollup=None``.
    """
    if registry is None:
        return tuple(
            DreamLane(id=lane.id, rollup=None, docs=lane.docs) for lane in partition_lanes(docs)
        )
    known = {cluster.id for cluster in registry.clusters}
    offending = [doc.path for doc in docs if doc.cluster is None or doc.cluster not in known]
    if offending:
        raise UserFacingCliError(
            "learned doc(s) missing a declared registry cluster (`cluster` frontmatter absent "
            "or naming no docs/learned/clusters.yaml id) — declare them before dreaming: "
            + ", ".join(offending),
            error_type="incomplete_registry",
        )
    lanes: list[DreamLane] = []
    for cluster in registry.clusters:
        members = sorted((doc for doc in docs if doc.cluster == cluster.id), key=lambda d: d.path)
        for n, start in enumerate(range(0, len(members), MAX_LANE_DOCS), start=1):
            lanes.append(
                DreamLane(
                    id=f"{cluster.id}-{n}",
                    rollup=cluster.rollup,
                    docs=tuple(members[start : start + MAX_LANE_DOCS]),
                )
            )
    return tuple(lanes)


def gather_dream(repo_root: Path) -> DreamGather:
    """The composition seam the door calls: resolve (refuses empty/escaping) → load the registry
    (refuses invalid) → measure sizes (refuses unreadable) → partition (refuses incomplete) →
    collect findings.

    Sizes are measured from the pairs' **resolved paths** (consumed here and nowhere else);
    an ``OSError`` on a doc's byte read → ``invalid_input`` naming the doc — snapshot honesty,
    never a silent 0. Measurement runs BEFORE the partition on purpose: an unreadable doc's
    frontmatter (its ``cluster`` included) degrades to ``None`` in the never-raising scan, so
    partitioning first would misname the failure ``incomplete_registry`` — readability precedes
    membership.
    """
    pairs = resolve_dream_docs(repo_root)
    docs = tuple(doc for doc, _resolved in pairs)
    registry = load_cluster_registry(repo_root)
    if isinstance(registry, InvalidClusterRegistry):
        raise UserFacingCliError(
            f"the cluster registry is invalid — {registry.reason}",
            error_type="invalid_registry",
        )
    sizes: dict[str, int] = {}
    for doc, resolved in pairs:
        try:
            sizes[doc.path] = len(resolved.read_bytes())
        except OSError as exc:
            raise UserFacingCliError(
                f"cannot read {doc.path} for the dream snapshot ({exc}) — every gathered doc's "
                "raw bytes must be measurable.",
                error_type="invalid_input",
            ) from exc
    return DreamGather(
        docs=docs,
        lanes=partition_dream_lanes(docs, registry),
        registry_mode="clusters" if registry is not None else "categories",
        sizes=sizes,
        findings=_collect_findings(repo_root, docs, registry_present=registry is not None),
    )


def _collect_findings(
    repo_root: Path, docs: Sequence[LearnedDoc], *, registry_present: bool
) -> DreamFindings:
    """One ``check_docs`` call mapped into the pinned closed manifest shape.

    Every family is filtered by its **owner-doc field only** against the manifest path set —
    which equals the ``read_learned_docs`` enumeration (the escaped-symlink refusal guarantees
    it), so the learned-doc-owned families pass through whole while user-doc/skill-owned rows
    drop. A ``broken_doc_paths`` row's ``target`` never participates in filtering (a broken
    target is by definition not a corpus member — it IS the finding); a ``stale_pointers``
    row's ``pointer`` likewise. ``duplicate_cues`` (from ``duplicate_read_when``,
    learned-docs-only by construction) keeps groups whose ``docs`` all sit in the path set —
    degenerate post-refusal, pinned for determinism. ``empty_clusters`` passes through
    untouched in registry mode and is ``()`` in category fallback.
    """
    report = check_docs(repo_root)
    member = {doc.path for doc in docs}
    return DreamFindings(
        stale_pointers=tuple(p for p in report.stale_pointers if p.doc in member),
        broken_doc_paths=tuple(b for b in report.broken_doc_paths if b.doc in member),
        duplicate_cues=tuple(
            g for g in report.duplicate_read_when if all(d in member for d in g.docs)
        ),
        missing_frontmatter=tuple(p for p in report.missing_frontmatter if p in member),
        distillation_issues=tuple(i for i in report.distillation_issues if i.doc in member),
        source_code_blocks=tuple(s for s in report.source_code_blocks if s.doc in member),
        overlong_cues=tuple(c for c in report.overlong_cues if c.doc in member),
        cue_hazards=tuple(h for h in report.cue_hazards if h.doc in member),
        empty_clusters=report.empty_clusters if registry_present else (),
    )


class _DreamDocOut(OutputModel):
    path: str
    title: str | None
    read_when: str | None
    cluster: str | None
    bytes: int


class _DreamLaneOut(OutputModel):
    id: str
    rollup: str | None
    docs: tuple[_DreamDocOut, ...]


class _StalePointerOut(OutputModel):
    doc: str
    pointer: str
    reason: str


class _BrokenDocPathOut(OutputModel):
    doc: str
    target: str


class _DuplicateCueOut(OutputModel):
    key: str
    docs: tuple[str, ...]


class _StructuralFindingsOut(OutputModel):
    stale_pointers: tuple[_StalePointerOut, ...]
    broken_doc_paths: tuple[_BrokenDocPathOut, ...]
    duplicate_cues: tuple[_DuplicateCueOut, ...]
    missing_frontmatter: tuple[str, ...]


class _DistillationIssueOut(OutputModel):
    doc: str
    problem: str


class _SourceCodeBlockOut(OutputModel):
    doc: str
    language: str
    lines: int


class _OverlongCueOut(OutputModel):
    doc: str
    length: int


class _CueHazardOut(OutputModel):
    doc: str
    hazard: str


class _AdvisoryFindingsOut(OutputModel):
    distillation_issues: tuple[_DistillationIssueOut, ...]
    source_code_blocks: tuple[_SourceCodeBlockOut, ...]
    overlong_cues: tuple[_OverlongCueOut, ...]
    cue_hazards: tuple[_CueHazardOut, ...]
    empty_clusters: tuple[str, ...]


class _DreamFindingsOut(OutputModel):
    structural: _StructuralFindingsOut
    advisory: _AdvisoryFindingsOut


class _DreamManifestOut(OutputModel):
    schema_version: str
    commit_sha: str
    registry_mode: str
    doc_count: int
    total_bytes: int
    findings: _DreamFindingsOut
    lanes: tuple[_DreamLaneOut, ...]


def render_manifest(gather: DreamGather, *, commit_sha: str) -> str:
    """Render the versioned dream manifest as JSON (the cross-plane contract the TS decoder
    consumes). ``None`` title/cue/cluster/rollup values are carried as JSON ``null``, never
    dropped. ``commit_sha`` is a parameter — capturing HEAD is the door's job, never this
    module's.
    """
    manifest = _DreamManifestOut(
        schema_version=DREAM_MANIFEST_SCHEMA_VERSION,
        commit_sha=commit_sha,
        registry_mode=gather.registry_mode,
        doc_count=gather.doc_count,
        total_bytes=gather.total_bytes,
        findings=_DreamFindingsOut(
            structural=_StructuralFindingsOut(
                stale_pointers=tuple(
                    _StalePointerOut(doc=p.doc, pointer=p.pointer, reason=p.reason)
                    for p in gather.findings.stale_pointers
                ),
                broken_doc_paths=tuple(
                    _BrokenDocPathOut(doc=b.doc, target=b.target)
                    for b in gather.findings.broken_doc_paths
                ),
                duplicate_cues=tuple(
                    _DuplicateCueOut(key=g.key, docs=g.docs) for g in gather.findings.duplicate_cues
                ),
                missing_frontmatter=gather.findings.missing_frontmatter,
            ),
            advisory=_AdvisoryFindingsOut(
                distillation_issues=tuple(
                    _DistillationIssueOut(doc=i.doc, problem=i.problem)
                    for i in gather.findings.distillation_issues
                ),
                source_code_blocks=tuple(
                    _SourceCodeBlockOut(doc=s.doc, language=s.language, lines=s.lines)
                    for s in gather.findings.source_code_blocks
                ),
                overlong_cues=tuple(
                    _OverlongCueOut(doc=c.doc, length=c.length)
                    for c in gather.findings.overlong_cues
                ),
                cue_hazards=tuple(
                    _CueHazardOut(doc=h.doc, hazard=h.hazard) for h in gather.findings.cue_hazards
                ),
                empty_clusters=gather.findings.empty_clusters,
            ),
        ),
        lanes=tuple(
            _DreamLaneOut(
                id=lane.id,
                rollup=lane.rollup,
                docs=tuple(
                    _DreamDocOut(
                        path=doc.path,
                        title=doc.title,
                        read_when=doc.read_when,
                        cluster=doc.cluster,
                        bytes=gather.sizes[doc.path],
                    )
                    for doc in lane.docs
                ),
            )
            for lane in gather.lanes
        ),
    )
    return json.dumps(manifest.model_dump(mode="json"), indent=2) + "\n"


def write_manifest(repo_root: Path, run_id: str, gather: DreamGather, *, commit_sha: str) -> Path:
    """Write the rendered dream manifest to the run-scoped scratch dir; return its path."""
    return cache.write_scratch(
        repo_root, run_id, DREAM_MANIFEST_FILENAME, render_manifest(gather, commit_sha=commit_sha)
    )
