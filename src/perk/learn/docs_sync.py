"""Generate + check the learned-docs navigation (`contracts.md` §8.35).

A pure, deterministic leaf (imports only ``docs_scan`` + ``yaml`` + ``perk.boundary`` — no
``github``/``backends``) that derives two navigation artifacts from each learned doc's ``title`` +
``read_when`` + ``cluster`` frontmatter (the single source of truth), optionally grouped by the
committed cluster registry ``docs/learned/clusters.yaml``:

- **The ambient routing block** (→ ``.pi/APPEND_SYSTEM.md``) — with the registry, one line per
  **cluster** (id + rollup cue + every member doc's ``category/slug``); without it (the legacy
  fallback), one line per doc. Loaded ambiently into every session's system prompt.
- **The per-doc catalog table** (→ ``docs/learned/index.md``) — one row per doc, the tier that
  keeps the full per-doc ``read_when`` cues; with the registry it gains a Cluster column.

Both wrap their generated region in ``BEGIN``/``END`` markers so a hand-editable preamble survives
re-generation. Generation is byte-for-byte deterministic (registry file order for cluster lines,
``(category, slug)`` for docs, fixed formatting, single trailing newline, no wall-clock/random), so
re-running ``docs-sync`` on a converged tree is a no-op. An **invalid** registry is never rendered:
``sync_docs`` returns the precise :class:`InvalidClusterRegistry` refusal and writes nothing.

The checker (:func:`check_docs`) splits **gating** findings — freshness (the generated region
matches a fresh render), the per-cue budget (each ``read_when`` ≤ :data:`READ_WHEN_MAX_CHARS`
chars and free of the plain-scalar hazards that silently corrupt the rendered cue), the
cluster gates (a valid registry, every doc's ``cluster`` declared + known, no empty clusters,
each rollup ≤ :data:`CLUSTER_ROLLUP_MAX_CHARS` chars), and the distillation gate (every doc
strictly over :data:`DISTILLATION_THRESHOLD_BYTES` raw bytes opens with a conformant
``## Distillation`` header — :func:`scan_distillation`) — from **advisory hygiene** (missing
frontmatter, copied-source-looking code blocks, the over-threshold raw-size rows, plus the
reused ``docs_scan`` dup-``read_when``/stale-pointer/broken-link facts — reported, never
gating).
"""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from perk.boundary import LenientParseModel, ValidationError, format_validation_error
from perk.learn.docs_scan import (
    BrokenDocPath,
    DuplicateGroup,
    LearnedDoc,
    StalePointer,
    read_learned_docs,
    scan_docs_richly,
)

# The two generated artifacts (repo-relative posix). `.pi/APPEND_SYSTEM.md` is Pi-native (not owned
# by `perk/substrate/paths.py`); both path guards permit constructing it directly.
_APPEND_REL = ".pi/APPEND_SYSTEM.md"
_INDEX_REL = "docs/learned/index.md"

# The generated-region fence. A hand-editable preamble lives OUTSIDE these markers; everything
# between them is owned by `perk learn docs-sync`.
BEGIN_MARKER = "<!-- BEGIN perk docs-sync (generated — do not edit between these markers) -->"
END_MARKER = "<!-- END perk docs-sync -->"

# The catalog table header (a fixed two-row preamble inside the generated region). The clustered
# variant (registry mode) adds the Cluster column; the legacy variant stays byte-identical.
_CATALOG_HEADER = "| Category | Doc | When to read |"
_CATALOG_SEP = "|----------|-----|-------------|"
_CATALOG_HEADER_CLUSTERED = "| Category | Doc | Cluster | When to read |"
_CATALOG_SEP_CLUSTERED = "|----------|-----|---------|-------------|"

# The D4 source-code-block heuristic: an info-string in this set AND a body of >= this many
# non-blank lines flags a fenced block as copied-source-looking (advisory). Data-format/CLI fences
# (json/yaml/toml/text/console/sh/bash/diff/ini) and untagged fences are always allowed; the
# threshold leaves every existing short illustrative snippet (<=3 lines) clean.
_SOURCE_FENCE_LANGS = frozenset(
    {"py", "python", "ts", "typescript", "js", "javascript", "tsx", "jsx", "rust", "rs", "go"}
)
_MAX_SOURCE_BLOCK_LINES = 10

# The per-cue routing budget: the max length of a parsed `read_when` value — byte-for-byte what
# `generate_routing_block`/`generate_catalog` emit into the ambient artifacts. Gates `docs-check`
# and the live-corpus pytest.
READ_WHEN_MAX_CHARS = 200

# The committed cluster registry (repo-relative posix). Absent ⇒ legacy per-doc rendering; present
# ⇒ the two-tier ambient index (§8.35).
_CLUSTERS_REL = "docs/learned/clusters.yaml"

# The per-cluster rollup ceiling: the max length of a parsed `rollup` value — byte-for-byte what
# `generate_routing_block` emits into the ambient cluster line (the §8.35 two-tier contract).
# Overlong is a GATING `docs-check` finding, but sync still writes (parity with the overlong-cue
# posture on `read_when`).
CLUSTER_ROLLUP_MAX_CHARS = 160

# A registry id must be kebab-case (it renders verbatim into the ambient grammar).
_CLUSTER_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# The distillation-first contract for big learned docs (the curation playbook is
# `docs/design/learned-curation-map.md`): a doc strictly over this raw byte size must open with
# its `## Distillation` header (gate #4); the raw size itself stays an advisory note.
DISTILLATION_THRESHOLD_BYTES = 12_288

# The header extent's line ceiling — heading line included, interior blank lines included,
# trailing blank separator lines excluded (see `docs/design/learned-curation-map.md`).
DISTILLATION_MAX_LINES = 30

# The containment window: the extent's last 1-indexed WHOLE-FILE line number (frontmatter
# included — exactly what `read` sees) must be within it, so `read` with `limit: 80` always
# captures the full header (see `docs/design/learned-curation-map.md`).
DISTILLATION_WINDOW_LINES = 80

# The exact heading: a line's content after stripping trailing whitespace. When (malformed)
# duplicates exist, the earliest such line governs (see `docs/design/learned-curation-map.md`).
DISTILLATION_HEADING = "## Distillation"

# The distillation section's terminator: the next H1/H2 line (`###`+ subsections count as
# section content — they extend the extent).
_DISTILLATION_SECTION_END_RE = re.compile(r"^#{1,2} ")

# The hand-editable preambles baked for a bootstrap (absent markers) write — one pair per
# rendering mode, so a legacy (no-registry) repo never gets self-documentation describing a
# registry it doesn't have. On a converged file the real preamble outside the markers is
# preserved verbatim and these constants are never consulted.
_APPEND_PREAMBLE = """\
<!--
  This file is appended to every perk session's system prompt (Pi's project-scoped
  .pi/APPEND_SYSTEM.md). It holds the COMPRESSED, ambient routing index into docs/learned/ —
  the realization of the "compressed index must be ambient" finding (a retrieval-tier index is
  too brittle to rely on). Keep it SMALL: one terse routing line per durable doc, pointing into
  the full catalog at docs/learned/index.md (read on demand).

  The routing block below is GENERATED from each doc's title + read_when frontmatter by
  `perk learn docs-sync` — edit the docs' frontmatter, not this block. `perk learn docs-check`
  reports drift on demand.
-->

## Durable learnings (docs/learned)

Cross-cutting reasoning captured for future agents lives in `docs/learned/`. The full catalog is
`docs/learned/index.md`; read a specific doc when its routing cue matches your task.

"""

_APPEND_PREAMBLE_CLUSTERED = """\
<!--
  This file is appended to every perk session's system prompt (Pi's project-scoped
  .pi/APPEND_SYSTEM.md). It holds the COMPRESSED, ambient routing index into docs/learned/ —
  the realization of the "compressed index must be ambient" finding (a retrieval-tier index is
  too brittle to rely on). Keep it SMALL: one line per cluster — id + rollup cue + member
  doc slugs; the full per-doc cues live in the catalog at docs/learned/index.md (read on
  demand).

  The routing block below is GENERATED from docs/learned/clusters.yaml + each doc's frontmatter
  by `perk learn docs-sync` — edit the registry / the docs' frontmatter, not this block.
  `perk learn docs-check` reports drift on demand.
-->

## Durable learnings (docs/learned)

Cross-cutting reasoning captured for future agents lives in `docs/learned/`. The full catalog is
`docs/learned/index.md`; read a specific doc when its cluster's rollup cue matches your task.

"""

_INDEX_PREAMBLE = """\
# Learned Index

This is the per-doc **catalog** of `docs/learned/` — one row per doc, linking the doc and giving a
single-line *when to read* cue. The compressed, ambient form of this routing (one terse line per
doc, loaded into every session's system prompt) lives in `.pi/APPEND_SYSTEM.md`.

The table below is GENERATED from each doc's `title` + `read_when` frontmatter by
`perk learn docs-sync` — edit the docs' frontmatter, not this table.

"""

_INDEX_PREAMBLE_CLUSTERED = """\
# Learned Index

This is the per-doc **catalog** of `docs/learned/` — one row per doc, linking the doc and giving a
single-line *when to read* cue. This table is the tier that keeps the full per-doc cues; the
compressed, ambient form of the routing (one line per cluster — id + rollup cue + member doc
slugs, loaded into every session's system prompt) lives in `.pi/APPEND_SYSTEM.md`.

The table below is GENERATED from each doc's frontmatter (and the cluster registry
`docs/learned/clusters.yaml`) by `perk learn docs-sync` — edit the docs' frontmatter, not this
table.

"""


# ---------------------------------------------------------------------------
# The cluster registry (the two-tier boundary)
# ---------------------------------------------------------------------------


class _ClusterEntryModel(LenientParseModel):
    """One ``clusters.yaml`` entry (``{id, rollup}``, extra ignored)."""

    id: str | None = None
    rollup: str | None = None


class _ClustersFileModel(LenientParseModel):
    """The untrusted read edge for the WHOLE registry-file shape (``clusters: [{id, rollup}]``,
    extra ignored) — the lenient-parse half of the boundary recipe; the content rules (kebab
    ids, one-line rollups, …) run as the separate :func:`_to_registry` pass."""

    clusters: tuple[_ClusterEntryModel, ...] | None = None


@dataclass(frozen=True)
class ClusterDef:
    """One cluster definition: its kebab-case id + one-line rollup cue (≤ 160 chars to pass
    ``docs-check``)."""

    id: str
    rollup: str


@dataclass(frozen=True)
class ClusterRegistry:
    """The parsed ``docs/learned/clusters.yaml``, in **file order** (the presentation SSOT —
    cluster lines render in this order). Members are derived from doc frontmatter, never listed
    here."""

    clusters: tuple[ClusterDef, ...]


@dataclass(frozen=True)
class InvalidClusterRegistry:
    """A present-but-invalid registry: ``sync_docs`` refuses (writes nothing) and ``docs-check``
    gates, both carrying this precise human-facing reason — a broken registry can never silently
    regress the committed block to per-doc grain."""

    reason: str


def load_cluster_registry(repo_root: Path) -> ClusterRegistry | InvalidClusterRegistry | None:
    """Load the cluster registry: ``None`` = the file is truly absent (legacy per-doc mode); any
    present-but-broken entry — a directory or dangling symlink at the path, an unreadable file, a
    YAML error, a wrong shape, empty/duplicate/non-kebab ids, missing/blank/multiline rollups —
    degrades to :class:`InvalidClusterRegistry` (never legacy mode: a broken registry must refuse,
    not silently regress the block to per-doc grain). Never raises.

    The boundary recipe (``perk/boundary.py``): the whole file shape parses through the lenient
    :class:`_ClustersFileModel`, then :func:`_to_registry` runs the content pass + the explicit
    conversion into the frozen domain dataclasses.
    """
    path = repo_root / _CLUSTERS_REL
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        # A dangling symlink ALSO raises FileNotFoundError on read, but it is a present (broken)
        # directory entry — only true absence selects legacy mode.
        if path.is_symlink():
            return InvalidClusterRegistry(
                reason=f"{_CLUSTERS_REL}: dangling symlink (not a readable file)"
            )
        return None
    except (OSError, UnicodeDecodeError) as exc:
        # Covers a directory at the path (IsADirectoryError), permission errors, and non-UTF-8.
        return InvalidClusterRegistry(reason=f"{_CLUSTERS_REL}: unreadable ({_flat(exc)})")
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return InvalidClusterRegistry(reason=f"{_CLUSTERS_REL}: YAML parse error ({_flat(exc)})")
    if not isinstance(parsed, dict):
        return InvalidClusterRegistry(reason=f"{_CLUSTERS_REL}: root is not a mapping")
    try:
        model = _ClustersFileModel.model_validate(parsed)
    except ValidationError as exc:
        return InvalidClusterRegistry(reason=f"{_CLUSTERS_REL}: {format_validation_error(exc)}")
    return _to_registry(model)


def _to_registry(model: _ClustersFileModel) -> ClusterRegistry | InvalidClusterRegistry:
    """The content pass + explicit conversion into the frozen domain registry (file order
    preserved): non-empty ``clusters``, kebab-case unique ids (full-string — a trailing newline
    from a block scalar is rejected), and rollups with non-whitespace content on exactly one line
    (``splitlines`` — ``\\r`` and the other line separators count, not just ``\\n``)."""
    if model.clusters is None:
        return InvalidClusterRegistry(reason=f"{_CLUSTERS_REL}: `clusters` is missing")
    if not model.clusters:
        return InvalidClusterRegistry(reason=f"{_CLUSTERS_REL}: `clusters` is empty")
    defs: list[ClusterDef] = []
    seen: set[str] = set()
    for i, entry in enumerate(model.clusters):
        label = f"clusters[{i}]"
        if not entry.id:
            return InvalidClusterRegistry(reason=f"{_CLUSTERS_REL}: {label} is missing an id")
        if _CLUSTER_ID_RE.fullmatch(entry.id) is None:
            return InvalidClusterRegistry(
                reason=f"{_CLUSTERS_REL}: {label} id {entry.id!r} is not kebab-case"
            )
        if entry.id in seen:
            return InvalidClusterRegistry(
                reason=f"{_CLUSTERS_REL}: duplicate cluster id {entry.id!r}"
            )
        seen.add(entry.id)
        if entry.rollup is None or not entry.rollup.strip():
            return InvalidClusterRegistry(
                reason=f"{_CLUSTERS_REL}: {label} ({entry.id!r}) is missing a rollup"
            )
        if len(entry.rollup.splitlines()) > 1:
            return InvalidClusterRegistry(
                reason=f"{_CLUSTERS_REL}: {label} ({entry.id!r}) rollup spans multiple lines"
            )
        defs.append(ClusterDef(id=entry.id, rollup=entry.rollup))
    return ClusterRegistry(clusters=tuple(defs))


def _flat(exc: BaseException) -> str:
    """One-line rendering of an exception message (YAML errors span lines)."""
    return " ".join(str(exc).split())


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def generate_routing_block(
    docs: tuple[LearnedDoc, ...], registry: ClusterRegistry | None = None
) -> str:
    """The ambient routing block, at cluster grain with a registry, per-doc grain without.

    Legacy (``registry=None``): one ``- **<category>/<slug>** — <read_when>`` line per doc —
    byte-identical to the pre-registry rendering. Full (untruncated) ``read_when``; a doc missing
    it renders an empty cue. No table → no escaping.

    Registry mode: one ``- **<id>** — <rollup> (<category/slug>, …)`` line per cluster in
    **registry order** (members = the docs whose ``cluster`` matches, sorted ``(category, slug)``;
    an empty cluster renders without parens), then a trailing legacy per-doc line for every doc
    whose ``cluster`` is missing or unknown (corpus order) — an unassigned doc never drops from
    the ambient tier (``docs-check`` gates it red meanwhile).
    """
    if registry is None:
        lines = [
            f"- **{doc.category}/{doc.slug}** — {doc.read_when or ''}".rstrip() for doc in docs
        ]
        return "\n".join(lines)
    lines = []
    for cluster in registry.clusters:
        members = sorted((d.category, d.slug) for d in docs if d.cluster == cluster.id)
        line = f"- **{cluster.id}** — {cluster.rollup}"
        if members:
            line += f" ({', '.join(f'{category}/{slug}' for category, slug in members)})"
        lines.append(line)
    known = {cluster.id for cluster in registry.clusters}
    lines.extend(
        f"- **{doc.category}/{doc.slug}** — {doc.read_when or ''}".rstrip()
        for doc in docs
        if doc.cluster is None or doc.cluster not in known
    )
    return "\n".join(lines)


def generate_catalog(docs: tuple[LearnedDoc, ...], registry: ClusterRegistry | None = None) -> str:
    """The per-doc catalog table: a fixed header + one ``| cat | [slug.md](…) | read_when |`` row
    (legacy), or 4 columns with the declared ``cluster`` value in registry mode.

    Links use the doc's real ``<category>/<slug>.md`` filename; ``read_when`` (and, in registry
    mode, the declared ``cluster`` — rendered verbatim, empty when undeclared) has its ``|``
    escaped (a table cell) — see ``biome.md`` / ``in-place-adoption.md`` which carry a literal
    ``|`` in the cue.
    """
    if registry is None:
        rows = [_CATALOG_HEADER, _CATALOG_SEP]
        for doc in docs:
            cue = (doc.read_when or "").replace("|", "\\|")
            link = f"[{doc.slug}.md]({doc.category}/{doc.slug}.md)"
            rows.append(f"| {doc.category} | {link} | {cue} |")
        return "\n".join(rows)
    rows = [_CATALOG_HEADER_CLUSTERED, _CATALOG_SEP_CLUSTERED]
    for doc in docs:
        cue = (doc.read_when or "").replace("|", "\\|")
        cluster = (doc.cluster or "").replace("|", "\\|")
        link = f"[{doc.slug}.md]({doc.category}/{doc.slug}.md)"
        rows.append(f"| {doc.category} | {link} | {cluster} | {cue} |")
    return "\n".join(rows)


def render_with_markers(existing: str, region: str, default_preamble: str) -> str:
    """Splice ``region`` between the ``BEGIN``/``END`` markers, preserving everything outside.

    If ``existing`` already carries both markers → replace strictly between them (idempotent; the
    preamble stays hand-editable). Otherwise (bootstrap / absent file) → write
    ``default_preamble + BEGIN + region + END`` with a single trailing newline.
    """
    block = f"{BEGIN_MARKER}\n{region}\n{END_MARKER}"
    if BEGIN_MARKER in existing and END_MARKER in existing:
        before = existing.split(BEGIN_MARKER, 1)[0]
        after = existing.split(END_MARKER, 1)[1]
        return f"{before}{block}{after}"
    return f"{default_preamble}{block}\n"


@dataclass(frozen=True)
class SyncResult:
    """The outcome of a :func:`sync_docs` pass: which artifacts changed vs. were already current."""

    written: tuple[str, ...]
    unchanged: tuple[str, ...]


def sync_docs(repo_root: Path, *, dry_run: bool) -> SyncResult | InvalidClusterRegistry:
    """Regenerate both artifacts; write only those whose content changed (``dry_run`` writes none).

    Deterministic + idempotent: on a converged tree every artifact lands in ``unchanged``. The
    cluster registry is loaded FIRST: an invalid one is returned as the refusal — no artifact
    reads, no writes (a broken registry never regresses the committed block to per-doc grain).
    """
    registry = load_cluster_registry(repo_root)
    if isinstance(registry, InvalidClusterRegistry):
        return registry
    docs = read_learned_docs(repo_root)
    routing = generate_routing_block(docs, registry)
    catalog = generate_catalog(docs, registry)
    clustered = registry is not None
    written: list[str] = []
    unchanged: list[str] = []
    for rel, region, preamble in (
        (_APPEND_REL, routing, _APPEND_PREAMBLE_CLUSTERED if clustered else _APPEND_PREAMBLE),
        (_INDEX_REL, catalog, _INDEX_PREAMBLE_CLUSTERED if clustered else _INDEX_PREAMBLE),
    ):
        path = repo_root / rel
        existing = path.read_text(encoding="utf-8") if path.is_file() else ""
        new = render_with_markers(existing, region, preamble)
        if new == existing:
            unchanged.append(rel)
            continue
        written.append(rel)
        if not dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(new, encoding="utf-8")
    return SyncResult(written=tuple(sorted(written)), unchanged=tuple(sorted(unchanged)))


# ---------------------------------------------------------------------------
# Checking
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceCodeBlock:
    """A fenced block whose info-string is a source language and whose body is suspiciously long."""

    doc: str
    language: str
    lines: int


@dataclass(frozen=True)
class OverlongCue:
    """A parsed ``read_when`` cue longer than :data:`READ_WHEN_MAX_CHARS`."""

    doc: str
    length: int


@dataclass(frozen=True)
class CueHazard:
    """A ``read_when`` scalar shape that silently corrupts the rendered cue.

    ``hazard`` is a closed set (mirroring ``StalePointer.reason``):
    "space-hash" (a `` #`` in the raw plain scalar — YAML comment start, silent truncation) |
    "colon-space" (a ``: `` in the raw plain scalar — the whole frontmatter parse fails) |
    "multiline" (the parsed value spans lines — breaks the one-line routing grammar).
    """

    doc: str
    hazard: str


@dataclass(frozen=True)
class CueFindings:
    """The per-cue budget/hazard scan result; both gate the ``docs-check`` exit."""

    overlong: tuple[OverlongCue, ...]
    hazards: tuple[CueHazard, ...]


@dataclass(frozen=True)
class DistillationIssue:
    """An over-threshold learned doc whose ``## Distillation`` header is absent or
    non-conformant (gating — gate #4).

    ``problem`` is a closed set (mirroring ``CueHazard.hazard``):
    "undecodable" (not valid UTF-8 — the header cannot be verified; exclusive) |
    "missing" (no ``## Distillation`` heading; exclusive) |
    "not-first" (another ``## `` body section precedes it) |
    "too-long" (the extent exceeds :data:`DISTILLATION_MAX_LINES` lines) |
    "not-contained" (the extent ends after whole-file line :data:`DISTILLATION_WINDOW_LINES`).
    """

    doc: str
    problem: str


@dataclass(frozen=True)
class OversizeDoc:
    """An over-threshold learned doc's raw size (advisory — reported, never gating)."""

    doc: str
    bytes: int


@dataclass(frozen=True)
class DistillationFindings:
    """The distillation scan result: the gating header issues + the advisory oversize rows."""

    issues: tuple[DistillationIssue, ...]
    oversize: tuple[OversizeDoc, ...]


@dataclass(frozen=True)
class ClusterIssue:
    """A doc whose ``cluster`` frontmatter is undeclared or names no registry id (gating,
    registry-valid mode only — the doc renders as a trailing per-doc line meanwhile).

    ``problem`` is a closed set: "missing" (no ``cluster`` declared — ``cluster`` is ``None``) |
    "unknown" (declared but not a registry id).
    """

    doc: str
    cluster: str | None
    problem: str


@dataclass(frozen=True)
class OverlongRollup:
    """A registry rollup cue longer than :data:`CLUSTER_ROLLUP_MAX_CHARS` (gating)."""

    cluster: str
    length: int


@dataclass(frozen=True)
class DocsCheckReport:
    """The on-demand check result: gating findings (freshness, the per-cue budget/hazards, and —
    in registry mode — registry validity + the cluster gates) + advisory hygiene findings.

    Field semantics under an invalid registry: the routing/catalog freshness comparison is
    SKIPPED (there is no valid render to compare against), so ``fresh``/``stale_files`` carry the
    non-compared defaults (``True``/``()``) — they mean "not compared", never "verified
    current"; ``registry_error`` is the authoritative gating signal (and the human render says
    UNCHECKED, not fresh).
    """

    fresh: bool
    stale_files: tuple[str, ...]
    missing_frontmatter: tuple[str, ...]
    source_code_blocks: tuple[SourceCodeBlock, ...]
    duplicate_read_when: tuple[DuplicateGroup, ...]
    stale_pointers: tuple[StalePointer, ...]
    broken_doc_paths: tuple[BrokenDocPath, ...]
    overlong_cues: tuple[OverlongCue, ...]
    cue_hazards: tuple[CueHazard, ...]
    registry_error: str | None = None  # the InvalidClusterRegistry.reason; None = absent-or-valid
    cluster_issues: tuple[ClusterIssue, ...] = ()  # registry-valid mode only
    empty_clusters: tuple[str, ...] = ()  # registry ids with zero member docs
    overlong_rollups: tuple[OverlongRollup, ...] = ()  # parsed rollup length > the ceiling
    distillation_issues: tuple[DistillationIssue, ...] = ()  # gate #4 (gating)
    oversize_docs: tuple[OversizeDoc, ...] = ()  # the raw-size rows (advisory, never gating)


def check_docs(repo_root: Path) -> DocsCheckReport:
    """Verify the generated artifacts are current + scan the cues + collect advisory hygiene.

    Freshness compares each artifact's live marked region to a fresh (registry-aware) render
    (absent markers or a mismatch ⇒ stale); the per-cue budget/hazard scan (:func:`scan_cues`)
    joins it as the second gating category, the cluster gates (registry validity, every doc's
    ``cluster`` declared + known, no empty clusters, each rollup within the ceiling) as the
    third, and the distillation gate (:func:`scan_distillation` — every doc strictly over
    :data:`DISTILLATION_THRESHOLD_BYTES` raw bytes opens with a conformant ``## Distillation``
    header) as the fourth. An invalid registry reports its precise reason and **skips** the
    routing/catalog freshness comparison — ``fresh``/``stale_files`` then carry the non-compared
    defaults and the ``registry_error`` gate covers the exit (deterministic, never raises); the
    cue and distillation scans still run. Hygiene
    reuses the never-raising ``docs_scan.scan_docs_richly`` facts plus two learned-doc-only passes
    (missing frontmatter, the D4 source-block heuristic), joined by the advisory over-threshold
    raw-size rows. Pure + deterministic; never raises on the scan paths.
    """
    docs = read_learned_docs(repo_root)
    registry = load_cluster_registry(repo_root)
    if isinstance(registry, InvalidClusterRegistry):
        registry_error: str | None = registry.reason
        stale: tuple[str, ...] = ()
        cluster_issues: tuple[ClusterIssue, ...] = ()
        empty_clusters: tuple[str, ...] = ()
        overlong_rollups: tuple[OverlongRollup, ...] = ()
    else:
        registry_error = None
        stale = _stale_files(repo_root, docs, registry)
        cluster_issues, empty_clusters, overlong_rollups = _cluster_findings(docs, registry)
    missing = tuple(doc.path for doc in docs if doc.title is None or doc.read_when is None)
    findings = scan_docs_richly(repo_root)
    cues = scan_cues(repo_root, docs)
    distillation = scan_distillation(repo_root, docs)
    return DocsCheckReport(
        fresh=not stale,
        stale_files=stale,
        missing_frontmatter=missing,
        source_code_blocks=_source_code_blocks(repo_root),
        duplicate_read_when=tuple(g for g in findings.duplicate_groups if g.basis == "read_when"),
        stale_pointers=findings.stale_pointers,
        broken_doc_paths=findings.broken_doc_paths,
        overlong_cues=cues.overlong,
        cue_hazards=cues.hazards,
        registry_error=registry_error,
        cluster_issues=cluster_issues,
        empty_clusters=empty_clusters,
        overlong_rollups=overlong_rollups,
        distillation_issues=distillation.issues,
        oversize_docs=distillation.oversize,
    )


def _cluster_findings(
    docs: tuple[LearnedDoc, ...], registry: ClusterRegistry | None
) -> tuple[tuple[ClusterIssue, ...], tuple[str, ...], tuple[OverlongRollup, ...]]:
    """The registry-mode cluster gates (all empty in legacy mode): per-doc missing/unknown
    ``cluster`` declarations, member-less registry ids, and over-ceiling rollups."""
    if registry is None:
        return (), (), ()
    known = {cluster.id for cluster in registry.clusters}
    issues: list[ClusterIssue] = []
    for doc in docs:
        if doc.cluster is None:
            issues.append(ClusterIssue(doc=doc.path, cluster=None, problem="missing"))
        elif doc.cluster not in known:
            issues.append(ClusterIssue(doc=doc.path, cluster=doc.cluster, problem="unknown"))
    declared = {doc.cluster for doc in docs}
    empty = tuple(cluster.id for cluster in registry.clusters if cluster.id not in declared)
    overlong = tuple(
        OverlongRollup(cluster=cluster.id, length=len(cluster.rollup))
        for cluster in registry.clusters
        if len(cluster.rollup) > CLUSTER_ROLLUP_MAX_CHARS
    )
    return tuple(issues), empty, overlong


def scan_cues(repo_root: Path, docs: tuple[LearnedDoc, ...]) -> CueFindings:
    """The per-cue budget + hazard scan (gates the ``docs-check`` exit; also the CI pytest's core).

    The **ceiling** measures the *parsed* ``read_when`` (what the generators emit verbatim); the
    **hazard** scan covers the raw≠parsed divergence cases the parsed value can't reveal: a `` #``
    silently truncates a plain scalar, a ``: `` fails the whole frontmatter parse (the cue renders
    empty), and a multi-line value breaks the one-line routing grammar. A value written as a
    quoted scalar is the sanctioned YAML escape — its lexical checks are skipped. Pure +
    deterministic (findings preserve the sorted ``docs`` order); never raises.
    """
    overlong: list[OverlongCue] = []
    hazards: list[CueHazard] = []
    for doc in docs:
        if doc.read_when is not None:
            if len(doc.read_when) > READ_WHEN_MAX_CHARS:
                overlong.append(OverlongCue(doc=doc.path, length=len(doc.read_when)))
            if "\n" in doc.read_when:
                hazards.append(CueHazard(doc=doc.path, hazard="multiline"))
        hazards.extend(_raw_line_hazards(repo_root, doc))
    return CueFindings(overlong=tuple(overlong), hazards=tuple(hazards))


def _raw_line_hazards(repo_root: Path, doc: LearnedDoc) -> list[CueHazard]:
    """The lexical plain-scalar hazards on a doc's raw ``read_when:`` frontmatter line.

    Quoted values (``"``/``'`` — the sanctioned escape) and block-scalar indicators (``|``/``>`` —
    the parsed-side multiline check covers them) are skipped. Never raises (unreadable → no
    findings, matching the module's never-raise idiom).
    """
    try:
        text = (repo_root / doc.path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    remainder = _raw_read_when_remainder(text)
    if remainder is None:
        return []
    if remainder.strip().startswith(('"', "'", "|", ">")):
        return []
    out: list[CueHazard] = []
    if " #" in remainder:
        out.append(CueHazard(doc=doc.path, hazard="space-hash"))
    if ": " in remainder:
        out.append(CueHazard(doc=doc.path, hazard="colon-space"))
    return out


def _raw_read_when_remainder(text: str) -> str | None:
    """The raw text after ``read_when:`` on the first such frontmatter line, or ``None``.

    Extracts the frontmatter block with the same ``---`` splitter semantics as the ``docs_scan``
    frontmatter parse, so the lexical scan sees exactly the lines YAML would.
    """
    if not text.startswith("---\n"):
        return None
    lines = text.split("\n")
    end = next((i for i in range(1, len(lines)) if lines[i] == "---"), None)
    if end is None:
        return None
    for line in lines[1:end]:
        if line.startswith("read_when:"):
            return line[len("read_when:") :]
    return None


def scan_distillation(repo_root: Path, docs: tuple[LearnedDoc, ...]) -> DistillationFindings:
    """The gate-#4 distillation scan over the big learned docs (+ the advisory raw-size rows).

    A doc whose raw file size (the byte length of its content, read once as bytes) is strictly
    over :data:`DISTILLATION_THRESHOLD_BYTES` must open with a conformant ``## Distillation``
    header: the first ``## `` body section (frontmatter, the ``# `` H1, and intro prose may
    precede it; a duplicate heading later is ordinary body content — the earliest governs), an
    extent of ≤ :data:`DISTILLATION_MAX_LINES` lines (heading included, interior blanks
    included, trailing blank separator lines excluded), ending within the file's first
    :data:`DISTILLATION_WINDOW_LINES` whole-file lines — so ``read`` with ``limit: 80`` always
    captures it. Under-threshold docs are never checked (a header there is allowed and
    unvalidated). Every over-threshold doc lands one advisory oversize row.

    Per-doc emission is pinned: ``undecodable`` and ``missing`` are exclusive (in that
    priority); otherwise the shape problems are evaluated independently, may co-occur, and are
    emitted in the fixed order ``not-first``, ``too-long``, ``not-contained``. Pure +
    deterministic (findings preserve the sorted ``docs`` order) and never raises: a byte-read
    ``OSError`` contributes nothing (the size is unknowable — no oversize row, no issue); a
    ``UnicodeDecodeError`` over threshold keeps its oversize row (bytes are a byte-level fact)
    and gates ``undecodable`` — fail-closed, an unverifiable over-threshold doc never silently
    passes. The size is measured on the ORIGINAL raw bytes; the decoded text is then
    newline-normalized (CRLF/CR → LF) for the line scan, so a CRLF/CR checkout parses exactly
    like the text-mode (universal-newline) reads the rest of the module uses. Runs independently
    of the cluster registry (like :func:`scan_cues`).
    """
    issues: list[DistillationIssue] = []
    oversize: list[OversizeDoc] = []
    for doc in docs:
        try:
            data = (repo_root / doc.path).read_bytes()
        except OSError:
            continue
        if len(data) <= DISTILLATION_THRESHOLD_BYTES:
            continue
        oversize.append(OversizeDoc(doc=doc.path, bytes=len(data)))
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            issues.append(DistillationIssue(doc=doc.path, problem="undecodable"))
            continue
        issues.extend(
            DistillationIssue(doc=doc.path, problem=problem)
            for problem in _distillation_problems(text)
        )
    return DistillationFindings(issues=tuple(issues), oversize=tuple(oversize))


def _distillation_problems(text: str) -> tuple[str, ...]:
    """One decodable over-threshold doc's header problems, in the pinned emission order.

    ``missing`` is exclusive; otherwise ``not-first``/``too-long``/``not-contained`` are
    evaluated independently. The input is newline-normalized first (CRLF/CR → LF — the byte
    decode has no text-mode universal-newline translation, and the LF-only checks below must
    see what ``Path.read_text`` would). Line indexing is whole-file (frontmatter included —
    exactly what ``read`` sees); the frontmatter is skipped only to locate the BODY's headings
    (the same ``---`` splitter semantics as ``docs_scan``'s frontmatter parse).
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    body_start = 0
    if text.startswith("---\n"):
        end = next((i for i in range(1, len(lines)) if lines[i] == "---"), None)
        if end is not None:
            body_start = end + 1
    heading = next(
        (i for i in range(body_start, len(lines)) if lines[i].rstrip() == DISTILLATION_HEADING),
        None,
    )
    if heading is None:
        return ("missing",)
    problems: list[str] = []
    first_h2 = next(i for i in range(body_start, len(lines)) if lines[i].startswith("## "))
    if first_h2 != heading:
        problems.append("not-first")
    # The extent: heading through the last non-blank line before the next H1/H2 (or EOF).
    last = heading
    for i in range(heading + 1, len(lines)):
        if _DISTILLATION_SECTION_END_RE.match(lines[i]):
            break
        if lines[i].strip():
            last = i
    if last - heading + 1 > DISTILLATION_MAX_LINES:
        problems.append("too-long")
    if last + 1 > DISTILLATION_WINDOW_LINES:  # 1-indexed whole-file line number
        problems.append("not-contained")
    return tuple(problems)


def _stale_files(
    repo_root: Path, docs: tuple[LearnedDoc, ...], registry: ClusterRegistry | None
) -> tuple[str, ...]:
    """The generated artifacts whose live region != a fresh registry-aware render (absent markers
    ⇒ stale)."""
    routing = generate_routing_block(docs, registry)
    catalog = generate_catalog(docs, registry)
    stale: list[str] = []
    for rel, region in ((_APPEND_REL, routing), (_INDEX_REL, catalog)):
        path = repo_root / rel
        try:
            live = path.read_text(encoding="utf-8") if path.is_file() else ""
        except (OSError, UnicodeDecodeError):
            live = ""
        if _extract_region(live) != region:
            stale.append(rel)
    return tuple(sorted(stale))


def _extract_region(text: str) -> str | None:
    """The content between the ``BEGIN``/``END`` markers (one surrounding newline stripped), or
    ``None`` when either marker is absent."""
    if BEGIN_MARKER not in text or END_MARKER not in text:
        return None
    mid = text.split(BEGIN_MARKER, 1)[1].split(END_MARKER, 1)[0]
    return mid.strip("\n")


def _source_code_blocks(repo_root: Path) -> tuple[SourceCodeBlock, ...]:
    """The D4 heuristic over every learned doc body; never raises (per-doc skip on read failure)."""
    root = repo_root / "docs" / "learned"
    if not root.is_dir():
        return ()
    index_md = root / "index.md"
    out: list[SourceCodeBlock] = []
    for path in sorted(root.glob("**/*.md")):
        if not path.is_file() or path == index_md:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        out.extend(_scan_fences(path.relative_to(repo_root).as_posix(), text))
    return tuple(out)


def _scan_fences(rel: str, text: str) -> list[SourceCodeBlock]:
    """Flag each closed ```` ``` ```` block whose info-language is a source language and whose body
    has ``>= _MAX_SOURCE_BLOCK_LINES`` non-blank lines."""
    out: list[SourceCodeBlock] = []
    in_block = False
    language = ""
    count = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not in_block:
            if stripped.startswith("```"):
                info = stripped[3:].strip()
                language = info.split()[0].lower() if info else ""
                in_block = True
                count = 0
            continue
        if stripped.startswith("```"):
            if language in _SOURCE_FENCE_LANGS and count >= _MAX_SOURCE_BLOCK_LINES:
                out.append(SourceCodeBlock(doc=rel, language=language, lines=count))
            in_block = False
            continue
        if stripped:
            count += 1
    return out
