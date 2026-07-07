"""Generate + check the learned-docs navigation (`contracts.md` §8.35).

A pure, deterministic leaf (imports only ``docs_scan`` — no ``github``/``backends``) that derives
two navigation artifacts from each learned doc's ``title`` + ``read_when`` frontmatter (the single
source of truth):

- **The terse routing block** (→ ``.pi/APPEND_SYSTEM.md``) — one line per doc, loaded ambiently into
  every session's system prompt.
- **The per-doc catalog table** (→ ``docs/learned/index.md``) — one row per doc, a richer browse
  surface.

Both wrap their generated region in ``BEGIN``/``END`` markers so a hand-editable preamble survives
re-generation. Generation is byte-for-byte deterministic (sorted by ``(category, slug)``, fixed
formatting, single trailing newline, no wall-clock/random), so re-running ``docs-sync`` on a
converged tree is a no-op.

The checker (:func:`check_docs`) splits **freshness** (the generated region matches a fresh render —
gates the ``docs-check`` exit) from **advisory hygiene** (missing frontmatter, copied-source-looking
code blocks, plus the reused ``docs_scan`` dup-``read_when``/stale-pointer/broken-link facts —
reported, never gating).
"""

from dataclasses import dataclass
from pathlib import Path

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

# The catalog table header (a fixed two-row preamble inside the generated region).
_CATALOG_HEADER = "| Category | Doc | When to read |"
_CATALOG_SEP = "|----------|-----|-------------|"

# The D4 source-code-block heuristic: an info-string in this set AND a body of >= this many
# non-blank lines flags a fenced block as copied-source-looking (advisory). Data-format/CLI fences
# (json/yaml/toml/text/console/sh/bash/diff/ini) and untagged fences are always allowed; the
# threshold leaves every existing short illustrative snippet (<=3 lines) clean.
_SOURCE_FENCE_LANGS = frozenset(
    {"py", "python", "ts", "typescript", "js", "javascript", "tsx", "jsx", "rust", "rs", "go"}
)
_MAX_SOURCE_BLOCK_LINES = 10

# The hand-editable preamble baked for a bootstrap (absent markers) write. On a converged file the
# real preamble outside the markers is preserved verbatim and these constants are never consulted.
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

_INDEX_PREAMBLE = """\
# Learned Index

This is the per-doc **catalog** of `docs/learned/` — one row per doc, linking the doc and giving a
single-line *when to read* cue. The compressed, ambient form of this routing (one terse line per
doc, loaded into every session's system prompt) lives in `.pi/APPEND_SYSTEM.md`.

The table below is GENERATED from each doc's `title` + `read_when` frontmatter by
`perk learn docs-sync` — edit the docs' frontmatter, not this table.

"""


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def generate_routing_block(docs: tuple[LearnedDoc, ...]) -> str:
    """The terse ambient routing block: one ``- **<category>/<slug>** — <read_when>`` line per doc.

    Full (untruncated) ``read_when``; a doc missing it renders an empty cue. No table → no escaping.
    """
    lines = [f"- **{doc.category}/{doc.slug}** — {doc.read_when or ''}".rstrip() for doc in docs]
    return "\n".join(lines)


def generate_catalog(docs: tuple[LearnedDoc, ...]) -> str:
    """The per-doc catalog table: a fixed header + one ``| cat | [slug.md](…) | read_when |`` row.

    Links use the doc's real ``<category>/<slug>.md`` filename; ``read_when`` has its ``|`` escaped
    (a table cell) — see ``biome.md`` / ``in-place-adoption.md`` which carry a literal ``|``.
    """
    rows = [_CATALOG_HEADER, _CATALOG_SEP]
    for doc in docs:
        cue = (doc.read_when or "").replace("|", "\\|")
        link = f"[{doc.slug}.md]({doc.category}/{doc.slug}.md)"
        rows.append(f"| {doc.category} | {link} | {cue} |")
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


def sync_docs(repo_root: Path, *, dry_run: bool) -> SyncResult:
    """Regenerate both artifacts; write only those whose content changed (``dry_run`` writes none).

    Deterministic + idempotent: on a converged tree every artifact lands in ``unchanged``.
    """
    docs = read_learned_docs(repo_root)
    routing = generate_routing_block(docs)
    catalog = generate_catalog(docs)
    written: list[str] = []
    unchanged: list[str] = []
    for rel, region, preamble in (
        (_APPEND_REL, routing, _APPEND_PREAMBLE),
        (_INDEX_REL, catalog, _INDEX_PREAMBLE),
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
class DocsCheckReport:
    """The on-demand check result: freshness (gates the exit) + advisory hygiene findings."""

    fresh: bool
    stale_files: tuple[str, ...]
    missing_frontmatter: tuple[str, ...]
    source_code_blocks: tuple[SourceCodeBlock, ...]
    duplicate_read_when: tuple[DuplicateGroup, ...]
    stale_pointers: tuple[StalePointer, ...]
    broken_doc_paths: tuple[BrokenDocPath, ...]


def check_docs(repo_root: Path) -> DocsCheckReport:
    """Verify the generated artifacts are current + collect advisory hygiene findings.

    Freshness compares each artifact's live marked region to a fresh render (absent markers or a
    mismatch ⇒ stale). Hygiene reuses the never-raising ``docs_scan.scan_docs_richly`` facts plus
    two learned-doc-only passes (missing frontmatter, the D4 source-block heuristic). Pure +
    deterministic; never raises on the scan paths.
    """
    docs = read_learned_docs(repo_root)
    stale = _stale_files(repo_root, docs)
    missing = tuple(doc.path for doc in docs if doc.title is None or doc.read_when is None)
    findings = scan_docs_richly(repo_root)
    return DocsCheckReport(
        fresh=not stale,
        stale_files=stale,
        missing_frontmatter=missing,
        source_code_blocks=_source_code_blocks(repo_root),
        duplicate_read_when=tuple(g for g in findings.duplicate_groups if g.basis == "read_when"),
        stale_pointers=findings.stale_pointers,
        broken_doc_paths=findings.broken_doc_paths,
    )


def _stale_files(repo_root: Path, docs: tuple[LearnedDoc, ...]) -> tuple[str, ...]:
    """The generated artifacts whose live region != a fresh render (absent markers ⇒ stale)."""
    routing = generate_routing_block(docs)
    catalog = generate_catalog(docs)
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
