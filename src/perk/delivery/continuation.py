"""The sync continuation manifest — the durable record of a mid-conflict cascade stop.

Written in exactly ONE situation: a suffix-sync candidate rebase hit a conflict and the
conflicted worktree state was deliberately retained (contracts.md §8.49). The manifest is the
disposable, machine-local pointer to that residue — it names the operation, the affected
layers with every captured input (leases, parent edges, sources, temp refs), the conflicting
node, and the retained worktree. It is NOT a resumable transaction log: a resumed calculation
must revalidate every captured remote/checkpoint input before proceeding — the world may have
moved while the conflict sat.

Keyed by ``delivery_lineage`` and anchored at the MAIN checkout
(``.perk/workflow/sync-continuations/<lineage>.json``): sync residue is repo-common, so a
manifest written from a ``plan-<N>`` worktree must be visible from the main checkout and vice
versa. Lineage-keying means a conflict on lineage B can never overwrite lineage A's manifest.
The lineage is stored objective metadata (an arbitrary string at the trust boundary), so it is
validated as a path-safe token BEFORE any path is derived — a hostile value (``../…``, an
absolute path) raises ``ValueError`` here and is refused as typed ``invalid_input`` by sync;
it can never escape the continuation directory.

The fresh-sync gate reads this lineage's file and fails closed: any present manifest — even an
unparseable one — refuses a new cascade until it is cleared (manual until the continue/abort
surface exists). Boundary discipline: the durable JSON is parsed through private lenient
models and converted to the frozen dataclasses below (the domain objects the delivery plane
passes around); serialization is an explicit render, never a domain-object dump. Import
discipline: this module stays below ``perk.state`` — it reaches the atomic-write seam through
``perk.substrate.fs`` (never ``perk.state.cache``, which imports ``perk.delivery.layer`` at
module scope and would close an import cycle through the package ``__init__``).
"""

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from perk.boundary import LenientParseModel
from perk.substrate import git as git_mod
from perk.substrate.fs import atomic_write_text

_CONTINUATIONS_SUBDIR = Path(".perk/workflow/sync-continuations")
_SCHEMA_VERSION = "1"
# The path-safe lineage vocabulary: an alphanumeric-led token (ULIDs in practice) — no dots,
# no separators, bounded length — so `<lineage>.json` can never traverse out of the directory.
_SAFE_LINEAGE_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z_-]{0,63}")


def is_safe_lineage(delivery_lineage: str) -> bool:
    """Whether ``delivery_lineage`` is a path-safe token (the precondition every path-deriving
    function below enforces; sync refuses a violating lineage as typed ``invalid_input``)."""
    return _SAFE_LINEAGE_RE.fullmatch(delivery_lineage) is not None


def _require_safe_lineage(delivery_lineage: str) -> str:
    if not is_safe_lineage(delivery_lineage):
        raise ValueError(
            f"delivery_lineage {delivery_lineage!r} is not a path-safe token — refusing to "
            "derive a continuation-manifest path from it"
        )
    return delivery_lineage


@dataclass(frozen=True)
class ContinuationLayer:
    """One affected layer's captured inputs, bottom→top order preserved by the container.

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
    candidate_temp_ref: str
    new_parent_edge: str | None = None
    candidate_sha: str | None = None


@dataclass(frozen=True)
class ContinuationManifest:
    """The lineage-keyed conflict-stop record (the frozen domain object; the durable JSON
    shape is schema-pinned for the future continue/abort reader — bump the serialized
    ``schema_version`` on any shape change, never mutate in place)."""

    operation_id: str
    objective_id: str
    delivery_lineage: str
    run_id: str
    include_base: bool
    captured_base_head: str | None
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


class _ContinuationLayerModel(LenientParseModel):
    """The lenient parse shape of one stored layer entry (boundary only, never the domain)."""

    node_id: str
    plan_id: str
    branch: str
    before_sha: str
    old_parent_edge: str
    source_sha: str
    candidate_temp_ref: str
    new_parent_edge: str | None = None
    candidate_sha: str | None = None

    def to_domain(self) -> ContinuationLayer:
        return ContinuationLayer(
            node_id=self.node_id,
            plan_id=self.plan_id,
            branch=self.branch,
            before_sha=self.before_sha,
            old_parent_edge=self.old_parent_edge,
            source_sha=self.source_sha,
            candidate_temp_ref=self.candidate_temp_ref,
            new_parent_edge=self.new_parent_edge,
            candidate_sha=self.candidate_sha,
        )


class _ContinuationManifestModel(LenientParseModel):
    """The lenient parse shape of the stored manifest (``schema_version`` pinned for the
    future continue/abort reader)."""

    schema_version: Literal["1"]
    operation_id: str
    objective_id: str
    delivery_lineage: str
    run_id: str
    include_base: bool
    captured_base_head: str | None = None
    layers: tuple[_ContinuationLayerModel, ...]
    conflict_node_id: str
    worktree_path: str
    created: str

    def to_domain(self) -> ContinuationManifest:
        return ContinuationManifest(
            operation_id=self.operation_id,
            objective_id=self.objective_id,
            delivery_lineage=self.delivery_lineage,
            run_id=self.run_id,
            include_base=self.include_base,
            captured_base_head=self.captured_base_head,
            layers=tuple(layer.to_domain() for layer in self.layers),
            conflict_node_id=self.conflict_node_id,
            worktree_path=self.worktree_path,
            created=self.created,
        )


def continuations_dir(repo_root: Path) -> Path:
    """The repo-common manifest directory, anchored at the MAIN checkout so residue written
    from any worktree is visible from every other (``main_worktree_root`` falls back to
    ``repo_root`` itself outside a linked worktree)."""
    main_root = git_mod.main_worktree_root(repo_root) or repo_root
    return main_root / _CONTINUATIONS_SUBDIR


def manifest_path(repo_root: Path, delivery_lineage: str) -> Path:
    """Where ``delivery_lineage``'s manifest lives (present or not). Raises ``ValueError`` on
    a lineage that is not a path-safe token (containment: the path always stays inside the
    continuation directory)."""
    return continuations_dir(repo_root) / f"{_require_safe_lineage(delivery_lineage)}.json"


def _render(manifest: ContinuationManifest) -> dict[str, object]:
    """The explicit serialization of the domain object (the writer stamps the schema pin —
    the domain never dumps itself)."""
    return {"schema_version": _SCHEMA_VERSION, **asdict(manifest)}


def write_manifest(repo_root: Path, manifest: ContinuationManifest) -> Path:
    """Durably write ``manifest`` at its lineage-keyed path (atomic replace; parents created).

    Returns the written path — the refusal message names it, and the caller disarms its
    cleanup guard only after this returns (the write IS the retention decision).
    """
    path = manifest_path(repo_root, manifest.delivery_lineage)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(_render(manifest), indent=2) + "\n")
    return path


def pending_continuation(repo_root: Path, delivery_lineage: str) -> PendingContinuation | None:
    """The fresh-sync gate read: ``None`` when no manifest exists for this lineage, else the
    pending finding — with ``manifest=None`` on ANY read/parse failure (fail closed)."""
    path = manifest_path(repo_root, delivery_lineage)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        manifest = _ContinuationManifestModel.model_validate(raw).to_domain()
    except (OSError, ValueError, ValidationError):
        # ValueError covers json.JSONDecodeError; a present-but-unaccountable manifest still
        # gates (fail closed, never a fresh cascade over retained residue).
        return PendingContinuation(path=path, manifest=None)
    return PendingContinuation(path=path, manifest=manifest)
