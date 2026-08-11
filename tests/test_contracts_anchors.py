"""Anchor-liveness guard for the `shared/contracts.md` §8.x section network.

The prose contract sections are cited from code/docs by their `§8.x` anchors. This guard
converts that anchor network from convention into a check, in three directions:

- **Liveness (wide corpus):** every heading anchor is referenced at least once outside
  `contracts.md` itself — an uncited section is either dead spec or missing its citation.
- **Validity (code corpus):** every `§8.x` token in code cites a live heading — docs may
  deliberately discuss absent numbers (e.g. the skipped 8.8); code must not.
- **History integrity:** every `§8.x` in a `contracts-history.md` group heading is a live
  `contracts.md` heading.

Self-reference confers no liveness: `contracts.md` and `contracts-history.md` are excluded
from every reference corpus.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = REPO_ROOT / "shared" / "contracts.md"
CONTRACTS_HISTORY = REPO_ROOT / "shared" / "contracts-history.md"

HEADING_RE = re.compile(r"^#{2,3} (§8\.\d+[a-z]?) ·", re.MULTILINE)
ANCHOR_RE = re.compile(r"§8\.\d+[a-z]?")

_SUFFIXES = {".py", ".ts", ".md", ".yaml", ".yml", ".json", ".jinja"}
_CONTRACTS_REL = Path("shared/contracts.md")
_CONTRACTS_HISTORY_REL = Path("shared/contracts-history.md")

WIDE_ROOTS = ("src", "extension", "tests", "shared", "docs", "skills", "agents", "prompts")
CODE_ROOTS = ("src", "extension", "tests")


def _heading_anchors() -> list[str]:
    return HEADING_RE.findall(CONTRACTS.read_text(encoding="utf-8"))


def _references_by_file(
    source_corpus: dict[Path, str], roots: tuple[str, ...]
) -> dict[str, set[str]]:
    refs: dict[str, set[str]] = {}
    for relative, text in source_corpus.items():
        if (
            relative.parts[0] not in roots
            or relative.suffix not in _SUFFIXES
            or relative in (_CONTRACTS_REL, _CONTRACTS_HISTORY_REL)
        ):
            continue
        found = set(ANCHOR_RE.findall(text))
        if found:
            refs[str(relative)] = found
    return refs


@pytest.fixture(scope="session")
def contract_reference_indexes(
    source_corpus: dict[Path, str],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Build the wide and code-only contract indexes once for both liveness checks."""
    wide = _references_by_file(source_corpus, WIDE_ROOTS)
    code = _references_by_file(source_corpus, CODE_ROOTS)
    for relative, text in source_corpus.items():
        if relative.parent != Path("shared") or relative.suffix != ".yaml":
            continue
        found = set(ANCHOR_RE.findall(text))
        if found:
            code[str(relative)] = found
    return wide, code


def test_heading_anchors_unique() -> None:
    anchors = _heading_anchors()
    assert anchors, "no §8.x headings found in shared/contracts.md"
    duplicates = {a for a in anchors if anchors.count(a) > 1}
    assert not duplicates, {"duplicate_headings": duplicates}


@pytest.mark.xdist_group("source_scan")
def test_every_heading_is_cited_somewhere(
    contract_reference_indexes: tuple[dict[str, set[str]], dict[str, set[str]]],
) -> None:
    # Liveness over the WIDE corpus: an anchor nobody cites is dead spec (or a missing
    # citation — fix whichever is true, never silence the guard).
    headings = set(_heading_anchors())
    cited: set[str] = set()
    wide_refs, _code_refs = contract_reference_indexes
    for refs in wide_refs.values():
        cited.update(refs)
    uncited = headings - cited
    assert not uncited, {"uncited_headings": sorted(uncited)}


@pytest.mark.xdist_group("source_scan")
def test_every_code_citation_is_a_live_heading(
    contract_reference_indexes: tuple[dict[str, set[str]], dict[str, set[str]]],
) -> None:
    # Validity over the CODE corpus (+ the parsed shared YAML contracts): code must cite
    # only live headings. Docs are deliberately excluded — they may discuss absent numbers.
    headings = set(_heading_anchors())
    _wide_refs, refs = contract_reference_indexes
    dangling = {
        rel: sorted(anchors - headings)
        for rel, anchors in sorted(refs.items())
        if anchors - headings
    }
    assert not dangling, {"dangling_citations": dangling}


def test_history_group_headings_are_live() -> None:
    # Cheap integrity: contracts-history.md groups its entries under `## §N.M · …`
    # headings; each such anchor must still be a live contracts.md heading.
    headings = set(_heading_anchors())
    history_anchors: set[str] = set()
    for line in CONTRACTS_HISTORY.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            history_anchors.update(ANCHOR_RE.findall(line))
    dangling = history_anchors - headings
    assert not dangling, {"dangling_history_groups": sorted(dangling)}
