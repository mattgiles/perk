"""Anchor-liveness guard for the `shared/contracts.md` §8.x section network.

The prose contract sections are cited from code/docs by their `§8.x` anchors. This guard
converts that anchor network from convention into a check, in two directions:

- **Liveness (wide corpus):** every heading anchor is referenced at least once outside
  `contracts.md` itself — an uncited section is either dead spec or missing its citation.
- **Validity (code corpus):** every `§8.x` token in code cites a live heading — docs may
  deliberately discuss absent numbers (e.g. the skipped 8.8); code must not.

Self-reference confers no liveness: `contracts.md` is excluded from every reference corpus.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = REPO_ROOT / "shared" / "contracts.md"

HEADING_RE = re.compile(r"^#{2,3} (§8\.\d+[a-z]?) ·", re.MULTILINE)
ANCHOR_RE = re.compile(r"§8\.\d+[a-z]?")

_SUFFIXES = {".py", ".ts", ".md", ".yaml", ".yml", ".json", ".jinja"}
_CONTRACTS_REL = Path("shared/contracts.md")

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
            or relative == _CONTRACTS_REL
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


# The banned provenance families (compiled regex, short reason). contracts.md is an
# eternal-present spec: plan/objective/task provenance, decision-era Status blocks, and
# concrete issue/PR numbers belong to git history, never the living contract. Live vocabulary
# shared with code (T1/T3, the D1..D9 decision-arm names, Invariant 20, hop-N) is deliberately
# NOT banned. No allowlist mechanism exists: a future legitimate hit is rephrased to a
# placeholder, or this guard is amended under review.
_PROVENANCE_FAMILIES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"node \d+\.\d+", re.IGNORECASE), "roadmap-node provenance (node N.M)"),
    (re.compile(r"Objective #\d+"), "objective provenance (Objective #N)"),
    (re.compile(r"[Pp]hase[-\s]\d"), "phase provenance (phase N)"),
    (re.compile(r"P\d+\.T\d+"), "plan-task provenance (PN.TM)"),
    (re.compile(r"\bQ\d+\b"), "question-number provenance (QN)"),
    (re.compile(r"\bGap \d\b"), "gap-number provenance (Gap N)"),
    (re.compile(r"(?<![A-Za-z])erk\b"), "standalone erk pointer (perk's ancestor)"),
    (re.compile(r"\*\*Status"), "decision-era Status block"),
    (re.compile(r"dogfood", re.IGNORECASE), "dogfood narration"),
    (re.compile(r"#\d{3,}"), "concrete issue/PR number (use #<n> or a short placeholder)"),
)


def test_no_provenance_vocabulary() -> None:
    # contracts.md stays eternal-present: no plan provenance survives an edit. Hits are
    # reported as {line_number: (matched_token, line_excerpt)} so they are locatable.
    hits: dict[int, tuple[str, str]] = {}
    for number, line in enumerate(CONTRACTS.read_text(encoding="utf-8").splitlines(), 1):
        for pattern, reason in _PROVENANCE_FAMILIES:
            match = pattern.search(line)
            if match is not None:
                hits[number] = (f"{match.group(0)} ({reason})", line.strip()[:120])
                break
    assert not hits, hits
