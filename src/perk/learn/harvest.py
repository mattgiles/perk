"""The shared learned-corpus gather core both learn factories build on.

Corpus/``--from`` resolution over ``docs/learned/`` for the ``perk learn harvest`` factory + the
pure lane partition + the versioned manifest render/write; :func:`eligible_learned_docs` (the
guarded eligible-corpus enumeration) and :func:`partition_lanes`/:data:`MAX_LANE_DOCS` are the
shared primitives ``perk.learn.dream`` builds on. Dependency-light on purpose (stdlib +
``perk.learn.docs_scan`` + ``perk.boundary`` + ``perk.state.cache`` + ``perk.cli.ensure``): the
cold door supplies
``run_id``/``commit_sha`` and owns every CLI concern (flags, ``--json``). Single- vs multi-lane
**routing** (direct in-session analysis vs the analyst wave) is the fallback state table's first
split, decided by the lane count (``len(partition_lanes(docs))``, the per-group lane contract —
never a total-doc-count check) and enforced by ``run_harvest_wave``'s single-lane refusal
(``extension/pi/v1/learning/harvest.ts``).
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from perk.boundary import OutputModel
from perk.cli.ensure import UserFacingCliError
from perk.learn.docs_scan import LearnedDoc, read_learned_docs
from perk.state import cache

# The lane cap: docs per lane within a group (a tunable default pinned by tests).
MAX_LANE_DOCS = 8

# The manifest contract version — a string, matching the roadmap-YAML `schema_version: '1'`
# precedent; the TS validator pins the same string.
MANIFEST_SCHEMA_VERSION = "1"

# The run-scoped scratch filename the manifest is written under.
MANIFEST_FILENAME = "harvest-manifest.json"


@dataclass(frozen=True)
class HarvestLane:
    """One analyst lane: a stable ``"<category>-<n>"`` id (1-based) and its docs."""

    id: str
    docs: tuple[LearnedDoc, ...]


def eligible_learned_docs(repo_root: Path) -> tuple[tuple[LearnedDoc, Path], ...]:
    """The eligible learned corpus: ``(doc, resolved_path)`` pairs in corpus order.

    The corpus is ``read_learned_docs(repo_root)`` — the sole enumerator (``index.md``
    exclusion, ``(category, slug)`` order, and ``None``-cue tolerance all inherited) — filtered
    once to the docs whose resolved path stays inside ``docs/learned/`` (an escaped-symlink
    entry is silently **filtered**; a caller wanting the refuse posture compares this set
    against the raw enumeration itself).

    Raises ``UserFacingCliError`` ``invalid_input`` when ``docs/learned`` itself resolves
    outside the repository (a symlinked corpus root — refused before any scan, or the outside
    target would become the trusted containment root).
    """
    learned_root = (repo_root / "docs" / "learned").resolve()
    # Path-traversal guard: the per-doc containment below is relative to learned_root, so a
    # docs/learned that is itself a symlink out of the repository would launder outside-tree
    # files into a manifest (and the launched session would be told to read them). Refuse
    # before reading anything. The message names no single factory — both learn factories
    # share this guard.
    if not learned_root.is_relative_to(repo_root.resolve()):
        raise UserFacingCliError(
            "docs/learned resolves outside the repository (a symlinked corpus root) — "
            "refusing to read outside-tree content.",
            error_type="invalid_input",
        )
    eligible: list[tuple[LearnedDoc, Path]] = []
    for doc in read_learned_docs(repo_root):
        resolved = (repo_root / doc.path).resolve()
        if resolved.is_relative_to(learned_root):
            eligible.append((doc, resolved))
    return tuple(eligible)


def resolve_harvest_docs(repo_root: Path, from_targets: Sequence[str]) -> tuple[LearnedDoc, ...]:
    """Resolve the harvest selection over the eligible learned corpus.

    The corpus is :func:`eligible_learned_docs` (an escaped-symlink entry is excluded from
    every arm, so the default and ``--from docs/learned`` stay equivalent by construction and
    harvest never selects outside-tree content). Empty ``from_targets`` → the full eligible
    corpus; otherwise the deduped union of per-target selections, in corpus order.

    Raises ``UserFacingCliError``: ``invalid_input`` when ``docs/learned`` itself resolves
    outside the repository (a symlinked corpus root — refused before any scan, or the outside
    target would become the trusted containment root); ``invalid_from`` for a target that
    resolves outside ``docs/learned/`` or does not exist; ``no_harvest_docs`` when the selection
    is empty.
    """
    eligible = eligible_learned_docs(repo_root)
    learned_root = (repo_root / "docs" / "learned").resolve()

    if not from_targets:
        selected = tuple(doc for doc, _resolved in eligible)
    else:
        selected_paths: set[str] = set()
        for target in from_targets:
            candidate = Path(target) if Path(target).is_absolute() else repo_root / target
            resolved_target = candidate.resolve()
            # is_relative_to covers equality, so `--from docs/learned` itself passes containment.
            if not resolved_target.is_relative_to(learned_root):
                raise UserFacingCliError(
                    f"--from target {target!r} resolves outside docs/learned/ — pass a file or "
                    "directory inside docs/learned/ (repo-root-relative or absolute).",
                    error_type="invalid_from",
                )
            if not resolved_target.exists():
                raise UserFacingCliError(
                    f"--from target {target!r} does not exist.",
                    error_type="invalid_from",
                )
            for doc, resolved in eligible:
                # A file target matches by equality; a directory target by containment —
                # is_relative_to serves both (equality included).
                if resolved.is_relative_to(resolved_target):
                    selected_paths.add(doc.path)
        selected = tuple(doc for doc, _resolved in eligible if doc.path in selected_paths)

    if not selected:
        raise UserFacingCliError(
            "No learned docs selected — nothing to harvest (the generated "
            "docs/learned/index.md is never included).",
            error_type="no_harvest_docs",
        )
    return selected


def _lane_category(doc: LearnedDoc) -> str:
    """The lane group key: the first path component of ``doc.category`` under ``docs/learned/``.

    The top-level edge (``category == "."``) maps to the literal ``"root"`` — and a real
    ``docs/learned/root/`` category co-groups with it **intentionally**: lanes are a batching
    boundary for analyst context, not a semantic namespace, so there is no reservation or
    escaping rule.
    """
    if doc.category == ".":
        return "root"
    return doc.category.split("/", 1)[0]


def partition_lanes(docs: Sequence[LearnedDoc]) -> tuple[HarvestLane, ...]:
    """Partition docs into lanes by the fixed rule. Pure and deterministic; ``()`` in → ``()`` out.

    Groups (keyed by :func:`_lane_category`) are emitted in sorted key order; within a group docs
    are sorted by ``path`` and chunked sequentially at :data:`MAX_LANE_DOCS`; lane ids are
    ``"<group>-<n>"``, 1-based per group.
    """
    groups: dict[str, list[LearnedDoc]] = {}
    for doc in docs:
        groups.setdefault(_lane_category(doc), []).append(doc)
    lanes: list[HarvestLane] = []
    for group in sorted(groups):
        members = sorted(groups[group], key=lambda d: d.path)
        for n, start in enumerate(range(0, len(members), MAX_LANE_DOCS), start=1):
            lanes.append(
                HarvestLane(id=f"{group}-{n}", docs=tuple(members[start : start + MAX_LANE_DOCS]))
            )
    return tuple(lanes)


class _HarvestDocOut(OutputModel):
    path: str
    title: str | None
    read_when: str | None


class _HarvestLaneOut(OutputModel):
    id: str
    docs: tuple[_HarvestDocOut, ...]


class _HarvestManifestOut(OutputModel):
    schema_version: str
    commit_sha: str
    lanes: tuple[_HarvestLaneOut, ...]


def render_manifest(lanes: Sequence[HarvestLane], *, commit_sha: str) -> str:
    """Render the versioned harvest manifest as JSON (the cross-plane contract the TS validator
    consumes). ``None`` title/read_when cues are carried as JSON ``null``, never dropped.

    ``commit_sha`` is a parameter — capturing HEAD is the door's job (its one-revision
    boundary), never this module's.
    """
    manifest = _HarvestManifestOut(
        schema_version=MANIFEST_SCHEMA_VERSION,
        commit_sha=commit_sha,
        lanes=tuple(
            _HarvestLaneOut(
                id=lane.id,
                docs=tuple(
                    _HarvestDocOut(path=doc.path, title=doc.title, read_when=doc.read_when)
                    for doc in lane.docs
                ),
            )
            for lane in lanes
        ),
    )
    return json.dumps(manifest.model_dump(mode="json"), indent=2) + "\n"


def write_manifest(
    repo_root: Path, run_id: str, lanes: Sequence[HarvestLane], *, commit_sha: str
) -> Path:
    """Write the rendered manifest to the run-scoped scratch dir; return its path."""
    return cache.write_scratch(
        repo_root, run_id, MANIFEST_FILENAME, render_manifest(lanes, commit_sha=commit_sha)
    )
