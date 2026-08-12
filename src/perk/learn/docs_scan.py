"""The doc-scanning pure leaf for the learn evidence bundle (`contracts.md` §8.35).

Two concerns, one dependency-light leaf (imports only stdlib + ``yaml`` + ``perk.boundary``):

- **The basic inventory** (``scan_existing_docs`` → ``DocEntry`` tuples) — the read of the three
  conventional docs roots (frontmatter / first-heading metadata), surfaced on the bundle's
  ``existing_docs[]``.
- **The rich, deterministic, advisory scan** (``scan_docs_richly`` → ``DocFindings``) — the
  verifiable facts the existing-docs analyst angle needs to point a capture at an *existing* doc
  with *verified evidence*: which source pointers no longer resolve (phantoms), which doc→doc links
  are broken, and (a cheap guard) which docs share an *exact* normalized title / routing cue.

Both are pure (no GitHub/backends), deterministic (sorted output, no wall-clock/random), and **never
raise** (per-doc try/except; ``OSError`` → skip). The split honors "deterministic" (the scan) and
"advisory" (the analyst does candidate-vs-corpus de-dup judgment using these facts). The leaf is
dependency-light on purpose so a future on-demand ``docs-check`` hygiene command can import it
without dragging in ``github``/``backends``.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from perk.boundary import LenientParseModel

_SNIPPET_LEN = 240

# The three conventional existing-docs roots. Top-level `skills/` is deliberately excluded — it is
# perk's own codebase, not the workflow-managed skill surface; `.perk/skills/` is the repo-authored
# skill surface.
_LEARNED_GLOB = ("docs/learned", "**/*.md")
_USER_DOCS_GLOB = ("docs/user-docs", "**/*.md")
_SKILLS_GLOB = (".perk/skills", "*/SKILL.md")

# The real top-level source dirs a backtick `path::symbol` pointer may name — excludes example /
# third-party / runtime paths, keeping stale-pointer detection high-precision (validated on the live
# corpus: an illustrative `perk/foo.py` is rare advisory noise; a `vendor/foo.py` is skipped). `.md`
# targets are rule 2 (broken doc paths), never a source pointer. `perk/...` pointers stay
# import-path-shaped and resolve via `_resolve_source_pointer` (src-layout + module→package probes).
_SOURCE_ROOTS = ("perk", "extension", "shared", "tests", "agents")

# A generous pathological guard on each finding family; sorted BEFORE the cap so the cut is
# deterministic. Never bites a normal corpus.
_MAX_FINDINGS = 200

# An inline-code span (backtick-wrapped, single line).
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")

# A source pointer: a real source path (code extension) with an optional `::symbol`. The whole span
# content must match.
_POINTER_RE = re.compile(r"^(?P<path>[\w./-]+\.(?:py|ts|tsx|js))(?:::(?P<symbol>[\w.]+))?$")

# A Markdown link's target (the parenthesized part).
_MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


class _DocFrontmatter(LenientParseModel):
    """The untrusted read edge for any inventoried doc's YAML frontmatter.

    Serves a learned doc (``title``/``read_when``/``cluster``) and a skill
    (``name``/``description``); the lenient base (``extra="ignore"``) drops every other
    frontmatter key a doc may carry.
    """

    title: str | None = None
    read_when: str | None = None
    cluster: str | None = None
    name: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class DocEntry:
    """One inventoried existing doc: its kind, repo-relative path, and (best-effort) metadata."""

    kind: str  # "learned" | "user-doc" | "skill"
    path: str
    title: str | None
    snippet: str | None


@dataclass(frozen=True)
class LearnedDoc:
    """One learned doc, read for generation: its category, slug, repo-rel path, and FULL metadata.

    The single source of truth the ``docs-sync`` generator + ``docs-check`` checker share. Unlike
    :class:`DocEntry`, ``title``/``read_when`` are the **untruncated** frontmatter values (the
    generator must reproduce them verbatim); ``None`` when the doc lacks frontmatter or it is
    unreadable/malformed.
    """

    category: str  # the posix relative dir under docs/learned/ (e.g. "workflow")
    slug: str  # the filename stem (e.g. "plan-factories")
    path: str  # repo-relative posix path
    title: str | None
    read_when: str | None
    cluster: str | None = None  # the declared clusters.yaml id (two-tier routing), or undeclared


@dataclass(frozen=True)
class StalePointer:
    """A source pointer that no longer resolves (a "ghost")."""

    doc: str  # repo-rel path of the doc containing the pointer
    pointer: str  # the backtick token, e.g. "perk/run/launch.py::_plan_read_instruction"
    reason: str  # "missing-file" | "missing-symbol"


@dataclass(frozen=True)
class BrokenDocPath:
    """A doc→doc Markdown (.md) link whose target no longer exists."""

    doc: str
    target: str  # the link target as written


@dataclass(frozen=True)
class DuplicateGroup:
    """>=2 docs sharing an EXACT normalized title / routing cue (a rare-by-design guard)."""

    basis: str  # "title" | "read_when"
    key: str  # the shared normalized value
    docs: tuple[str, ...]


@dataclass(frozen=True)
class DocFindings:
    """The rich-scan result; all-empty on a healthy corpus or a skip bundle."""

    stale_pointers: tuple[StalePointer, ...] = ()
    broken_doc_paths: tuple[BrokenDocPath, ...] = ()
    duplicate_groups: tuple[DuplicateGroup, ...] = ()


# ---------------------------------------------------------------------------
# Basic inventory
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
        except (OSError, UnicodeDecodeError):
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
# Full-metadata learned-doc read (the generation SSOT)
# ---------------------------------------------------------------------------


def read_learned_docs(repo_root: Path) -> tuple[LearnedDoc, ...]:
    """Read every ``docs/learned/**/*.md`` doc's FULL frontmatter metadata (the generation SSOT).

    Excludes ``docs/learned/index.md`` (the generated output, not a source). Deterministic — sorted
    by ``(category, slug)`` — and **never raises**: an unreadable file or malformed frontmatter
    yields ``title``/``read_when``/``cluster`` = ``None``. Unlike :func:`scan_existing_docs`, the
    values are **untruncated** (the generator reproduces them verbatim).
    """
    root = repo_root / _LEARNED_GLOB[0]
    if not root.is_dir():
        return ()
    index_md = root / "index.md"
    docs: list[LearnedDoc] = []
    for path in root.glob(_LEARNED_GLOB[1]):
        if not path.is_file() or path == index_md:
            continue
        rel_to_root = path.relative_to(root)
        category = rel_to_root.parent.as_posix()
        title, read_when, cluster = _learned_frontmatter(path)
        docs.append(
            LearnedDoc(
                category=category,
                slug=path.stem,
                path=_rel(repo_root, path),
                title=title,
                read_when=read_when,
                cluster=cluster,
            )
        )
    return tuple(sorted(docs, key=lambda d: (d.category, d.slug)))


def _learned_frontmatter(path: Path) -> tuple[str | None, str | None, str | None]:
    """Best-effort FULL ``(title, read_when, cluster)`` for one learned doc; never raises."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None, None, None
    front = _frontmatter_dict(text)
    if not front:
        return None, None, None
    try:
        meta = _DocFrontmatter.model_validate(front)
    except ValueError:
        return None, None, None
    return meta.title, meta.read_when, meta.cluster


# ---------------------------------------------------------------------------
# Rich, deterministic, advisory scan
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ScannedDoc:
    """One doc read once for the rich scan: its path, full text, kind, and raw collision bases."""

    path: Path
    rel: str
    kind: str
    text: str
    title: str | None
    read_when: str | None


def scan_docs_richly(repo_root: Path) -> DocFindings:
    """The rich, deterministic, advisory scan over the three conventional roots.

    Deterministic (sorted output), bounded (each doc read once; each finding family sorted then
    capped at ``_MAX_FINDINGS``), and **never raises** (per-doc ``OSError`` → skip). Verifiable
    facts only: stale source pointers (phantoms), broken doc→doc links, and exact normalized
    title/routing-cue collisions (a guard). The de-dup *decision* is candidate-vs-corpus — the
    analyst's, powered by these facts; this scan never decides de-dup.
    """
    docs = _read_docs(repo_root)

    stale: list[StalePointer] = []
    broken: list[BrokenDocPath] = []
    for doc in docs:
        stale.extend(_stale_pointers(repo_root, doc))
        broken.extend(_broken_doc_paths(repo_root, doc))

    return DocFindings(
        stale_pointers=tuple(sorted(stale, key=lambda s: (s.doc, s.pointer))[:_MAX_FINDINGS]),
        broken_doc_paths=tuple(sorted(broken, key=lambda b: (b.doc, b.target))[:_MAX_FINDINGS]),
        duplicate_groups=_duplicate_groups(docs),
    )


def _read_docs(repo_root: Path) -> list[_ScannedDoc]:
    """Read every doc in the three roots once (full body); skip unreadable files (never raises)."""
    out: list[_ScannedDoc] = []
    for kind, glob in (
        ("learned", _LEARNED_GLOB),
        ("user-doc", _USER_DOCS_GLOB),
        ("skill", _SKILLS_GLOB),
    ):
        root = repo_root / glob[0]
        if not root.is_dir():
            continue
        for path in root.glob(glob[1]):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            title, read_when = _collision_bases(kind, text)
            out.append(
                _ScannedDoc(
                    path=path,
                    rel=_rel(repo_root, path),
                    kind=kind,
                    text=text,
                    title=title,
                    read_when=read_when,
                )
            )
    return out


def _collision_bases(kind: str, text: str) -> tuple[str | None, str | None]:
    """The raw ``(title, read_when)`` for collision detection (read_when only for learned docs)."""
    if kind in ("learned", "skill"):
        front = _frontmatter_dict(text)
        if not front:
            return None, None
        try:
            meta = _DocFrontmatter.model_validate(front)
        except ValueError:
            return None, None
        if kind == "skill":
            return meta.name, None
        return meta.title, meta.read_when
    title, _ = _user_doc_metadata(text)
    return title, None


def _is_existing_file(path: Path) -> bool:
    """``path.is_file()`` hardened against a pathological, text-derived path (an embedded NUL byte
    raises ``ValueError``; OS-illegal characters raise ``OSError``) — a bad path degrades to
    "not a file", never raises out of the advisory scan."""
    try:
        return path.is_file()
    except (OSError, ValueError):
        return False


def _resolve_source_pointer(repo_root: Path, path: str) -> Path | None:
    """Resolve a doc's source pointer to the file whose text backs symbol probing.

    Doc pointers stay **import-path-shaped** (``perk/...``), not filesystem-literal: since the
    uv-workspace src-layout move the Python tree lives at ``src/perk/...``, and the
    module→package splits preserved import paths (``perk/backends/linear.py`` →
    ``src/perk/backends/linear/``), so historical split-narrative citations remain valid. Probe
    order for a ``perk/...`` pointer: the literal path, the src-layout path, then the
    module→package form (a package dir counts as existing; its ``__init__.py`` backs symbol
    probing). The other roots (``extension``, ``shared``, ``tests``, ``agents``) never moved
    under ``src/`` — plain probe only. ``None`` = the pointer is genuinely missing.
    """
    literal = repo_root / path
    if _is_existing_file(literal):
        return literal
    if path.split("/")[0] != "perk":
        return None
    src_form = repo_root / "src" / path
    if _is_existing_file(src_form):
        return src_form
    if path.endswith(".py"):
        package_init = repo_root / "src" / path.removesuffix(".py") / "__init__.py"
        if _is_existing_file(package_init):
            return package_init
    return None


def _stale_pointers(repo_root: Path, doc: _ScannedDoc) -> list[StalePointer]:
    """The phantom source pointers a doc cites: backtick ``path::symbol`` spans that no longer
    resolve (missing file, or present file whose last symbol segment is absent from its text)."""
    found: dict[str, StalePointer] = {}  # dedup per doc, keyed by the pointer token
    for span in _INLINE_CODE_RE.findall(doc.text):
        match = _POINTER_RE.match(span)
        if match is None:
            continue
        path = match.group("path")
        if path.split("/")[0] not in _SOURCE_ROOTS:
            continue
        target = _resolve_source_pointer(repo_root, path)
        if target is None:
            found.setdefault(span, StalePointer(doc=doc.rel, pointer=span, reason="missing-file"))
            continue
        symbol = match.group("symbol")
        if symbol is None:
            continue
        try:
            body = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if symbol.split(".")[-1] not in body:
            found.setdefault(span, StalePointer(doc=doc.rel, pointer=span, reason="missing-symbol"))
    return list(found.values())


def _broken_doc_paths(repo_root: Path, doc: _ScannedDoc) -> list[BrokenDocPath]:
    """The doc→doc ``.md`` Markdown links a doc carries that no longer resolve.

    Resolves relative to the doc's parent dir (normalizing ``..`` so cross-tree links resolve);
    skips external links, pure anchors, and whitespace/``|`` captures (the validated false-positive
    code-snippet shapes ``](cmd: C)`` / ``](scratch|runs)``).
    """
    parent = doc.path.parent
    found: dict[str, BrokenDocPath] = {}
    for raw in _MD_LINK_RE.findall(doc.text):
        target = raw.split("#", 1)[0]
        if not target.endswith(".md"):
            continue
        if any(c.isspace() for c in target) or "|" in target:
            continue
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        try:
            resolved = (parent / target).resolve()
        except (OSError, ValueError):
            continue  # a pathological link target degrades to skip, never crashes the scan
        if not _is_existing_file(resolved):
            found.setdefault(raw, BrokenDocPath(doc=doc.rel, target=target))
    return sorted(found.values(), key=lambda b: b.target)


def _duplicate_groups(docs: list[_ScannedDoc]) -> tuple[DuplicateGroup, ...]:
    """Exact normalized title (same-kind) / ``read_when`` (learned) collisions — a rare-by-design
    guard, empty on a healthy corpus."""
    groups: list[DuplicateGroup] = []

    by_title: dict[tuple[str, str], list[str]] = {}
    for doc in docs:
        key = _normalize(doc.title)
        if key:
            by_title.setdefault((doc.kind, key), []).append(doc.rel)
    for (_kind, key), rels in by_title.items():
        if len(rels) >= 2:
            groups.append(DuplicateGroup(basis="title", key=key, docs=tuple(sorted(rels))))

    by_read_when: dict[str, list[str]] = {}
    for doc in docs:
        if doc.kind != "learned":
            continue
        key = _normalize(doc.read_when)
        if key:
            by_read_when.setdefault(key, []).append(doc.rel)
    for key, rels in by_read_when.items():
        if len(rels) >= 2:
            groups.append(DuplicateGroup(basis="read_when", key=key, docs=tuple(sorted(rels))))

    return tuple(sorted(groups, key=lambda g: (g.basis, g.key))[:_MAX_FINDINGS])


def _normalize(value: str | None) -> str:
    """Whitespace-collapsed lowercase normalization for exact-collision keying (``""`` if empty)."""
    if not value:
        return ""
    return " ".join(value.lower().split())
