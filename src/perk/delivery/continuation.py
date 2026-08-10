"""The sync continuation manifest — the durable record of a mid-conflict cascade stop.

Written in exactly ONE situation: a suffix-sync candidate rebase hit a conflict and the
conflicted worktree state was deliberately retained (contracts.md §8.48). The manifest is the
disposable, machine-local pointer to that residue — it names the operation, the affected
layers with every captured input (leases, parent edges, sources, temp refs), the conflicting
node, and the retained worktree. It is NOT a resumable transaction log: a resumed calculation
must revalidate every captured remote/checkpoint input before proceeding — the world may have
moved while the conflict sat.

Keyed by ``delivery_lineage`` and anchored at the MAIN checkout
(``.perk/workflow/sync-continuations/<lineage>.json``): sync residue is repo-common, so a
manifest written from a ``plan-<N>`` worktree must be visible from the main checkout and vice
versa. Lineage-keying means a conflict on lineage B can never overwrite lineage A's manifest.

The fresh-sync gate reads this lineage's file and fails closed: any present manifest — even an
unparseable one — refuses a new cascade until it is cleared (manual until the continue/abort
surface exists). Import discipline: this module stays below ``perk.state`` — it reaches the
atomic-write seam through ``perk.substrate.fs`` (never ``perk.state.cache``, which imports
``perk.delivery.layer`` at module scope and would close an import cycle through the package
``__init__``).
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from perk.boundary import LenientParseModel
from perk.substrate import git as git_mod
from perk.substrate.fs import atomic_write_text

_CONTINUATIONS_SUBDIR = Path(".perk/workflow/sync-continuations")


class ContinuationLayer(LenientParseModel):
    """One affected layer's captured inputs, bottom→top order preserved by the list.

    ``before_sha`` is the remote lease observed at preflight; ``old_parent_edge`` the stored
    ``parent_checkpoint_sha``; ``source_sha`` the candidate source (local head or verified
    published head); ``new_parent_edge`` the freshly computed parent (``None`` for layers the
    stop never reached); ``candidate_temp_ref``/``candidate_sha`` the minted temp ref and its
    computed candidate (``sha`` is ``None`` for the conflicting layer and everything above it).
    """

    node_id: str
    plan_id: str
    branch: str
    before_sha: str
    old_parent_edge: str
    source_sha: str
    new_parent_edge: str | None = None
    candidate_temp_ref: str
    candidate_sha: str | None = None


class ContinuationManifest(LenientParseModel):
    """The lineage-keyed conflict-stop record (schema pinned for the future continue/abort
    reader — bump ``schema_version`` on any shape change, never mutate in place)."""

    schema_version: Literal["1"] = "1"
    operation_id: str
    objective_id: str
    delivery_lineage: str
    run_id: str
    include_base: bool
    captured_base_head: str | None = None
    layers: tuple[ContinuationLayer, ...]
    conflict_node_id: str
    worktree_path: str
    created: str


@dataclass(frozen=True)
class PendingContinuation:
    """A present manifest file for a lineage — the fail-closed gate's finding.

    ``manifest`` is ``None`` when the file exists but cannot be parsed (unreadable bytes,
    invalid JSON, or a foreign shape): the gate treats that as pending all the same — never a
    fresh cascade over retained residue it cannot account for.
    """

    path: Path
    manifest: ContinuationManifest | None


def continuations_dir(repo_root: Path) -> Path:
    """The repo-common manifest directory, anchored at the MAIN checkout so residue written
    from any worktree is visible from every other (``main_worktree_root`` falls back to
    ``repo_root`` itself outside a linked worktree)."""
    main_root = git_mod.main_worktree_root(repo_root) or repo_root
    return main_root / _CONTINUATIONS_SUBDIR


def manifest_path(repo_root: Path, delivery_lineage: str) -> Path:
    """Where ``delivery_lineage``'s manifest lives (present or not)."""
    return continuations_dir(repo_root) / f"{delivery_lineage}.json"


def write_manifest(repo_root: Path, manifest: ContinuationManifest) -> Path:
    """Durably write ``manifest`` at its lineage-keyed path (atomic replace; parents created).

    Returns the written path — the refusal message names it, and the caller disarms its
    cleanup guard only after this returns (the write IS the retention decision).
    """
    path = manifest_path(repo_root, manifest.delivery_lineage)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(manifest.model_dump(mode="json"), indent=2) + "\n")
    return path


def pending_continuation(repo_root: Path, delivery_lineage: str) -> PendingContinuation | None:
    """The fresh-sync gate read: ``None`` when no manifest exists for this lineage, else the
    pending finding — with ``manifest=None`` on ANY read/parse failure (fail closed)."""
    path = manifest_path(repo_root, delivery_lineage)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        manifest = ContinuationManifest.model_validate(raw)
    except (OSError, ValueError, ValidationError):
        # ValueError covers json.JSONDecodeError; a present-but-unaccountable manifest still
        # gates (fail closed, never a fresh cascade over retained residue).
        return PendingContinuation(path=path, manifest=None)
    return PendingContinuation(path=path, manifest=manifest)
