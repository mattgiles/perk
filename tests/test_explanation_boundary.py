"""Live-corpus guard: the Explanation quadrant's editorial boundary holds over the real
`docs/user-docs/explanation/` tree.

The executable counterpart to the Explanation contract in `docs/user-docs/_authoring.md`:
outside fenced code blocks, no Explanation source may contain an ordered list or a
Markdown/HTML table (action sequences belong to how-to, exact tables to reference), and every
article except the landing must end in a final ``## Related`` section of 1-3 intent-labeled
links drawn from the Explanation subset (Understand / Do / Look up), at least one of them a
``Do`` or ``Look up`` route out to task/reference material. The landing
(``explanation/index.*``) is exempt only from the ``Related`` requirement.

The scanner is unit-tested in this module against synthetic sources (both directions), so the
live-corpus assertion stays trustworthy rather than merely reflecting today's passing files.
"""

import re
from itertools import pairwise
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPLANATION_DIR = REPO_ROOT / "docs" / "user-docs" / "explanation"

# The Explanation subset of the Related label vocabulary; a conceptual article must route the
# reader onward to at least one actionable/exact-detail destination.
ALLOWED_LABELS = ("Understand", "Do", "Look up")
ACTION_LABELS = ("Do", "Look up")

_ORDERED_ITEM = re.compile(r"^\s*\d+[.)]\s")
# A GFM table delimiter row: pipe-separated cells of `:?-+:?` (leading/trailing pipe optional).
_TABLE_DELIMITER = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$")
_HTML_TABLE = re.compile(r"<table\b", re.IGNORECASE)
# A fence opens with 3+ backticks or tildes (info string allowed) and closes at the next line
# carrying at least as many of the same character and nothing else (CommonMark close rule).
_FENCE_MARKER = re.compile(r"^ {0,3}(`{3,}|~{3,})")
# One folded Related item: `- **Label:** [Title](target) — reason` (label validated separately
# so a wrong label is reported as a label problem, not a shape problem).
_RELATED_ITEM = re.compile(r"^- \*\*(?P<label>[^*]+):\*\* \[[^\]]+\]\(\S+\) — \S.*$")


def _body_lines(text: str) -> list[tuple[int, str]]:
    """``(1-based source line number, line)`` pairs of the body, YAML frontmatter stripped."""
    lines = text.split("\n")
    start = 0
    if lines and lines[0] == "---":
        for index in range(1, len(lines)):
            if lines[index] == "---":
                start = index + 1
                break
    return list(enumerate(lines, start=1))[start:]


def _outside_fences(numbered: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """The lines outside fenced code blocks (fence delimiter lines excluded too)."""
    outside: list[tuple[int, str]] = []
    open_fence: str | None = None
    for number, line in numbered:
        if open_fence is None:
            match = _FENCE_MARKER.match(line)
            if match:
                open_fence = match.group(1)
            else:
                outside.append((number, line))
            continue
        closing = re.match(
            rf"^ {{0,3}}({re.escape(open_fence[0])}{{{len(open_fence)},}})\s*$", line
        )
        if closing:
            open_fence = None
    return outside


def _fold_related_items(tail: list[tuple[int, str]]) -> tuple[list[tuple[int, str]], list[str]]:
    """Fold the post-``## Related`` lines into logical items (a ``- `` line plus its indented
    continuation lines). Returns ``(items, violations)`` where each item is
    ``(first line number, folded one-line text)``."""
    items: list[tuple[int, str]] = []
    violations: list[str] = []
    for number, line in tail:
        if not line.strip():
            continue
        if line.startswith("- "):
            items.append((number, line.rstrip()))
        elif line[:1].isspace() and items:
            first, folded = items[-1]
            items[-1] = (first, f"{folded} {line.strip()}")
        else:
            violations.append(
                f"line {number}: non-item content after `## Related`: {line.strip()!r}"
            )
    return items, violations


def scan_explanation_source(name: str, text: str, *, landing: bool = False) -> list[str]:
    """All Explanation-boundary violations in one source, each prefixed ``<name>:<line>``."""
    numbered = _outside_fences(_body_lines(text))
    violations: list[str] = []

    for number, line in numbered:
        if _ORDERED_ITEM.match(line):
            violations.append(
                f"{name}:{number}: ordered-list marker outside a fence: {line.strip()!r}"
            )
        if _HTML_TABLE.search(line):
            violations.append(f"{name}:{number}: HTML table start outside a fence")
    for (number, line), (_, following) in pairwise(numbered):
        if "|" in line and _TABLE_DELIMITER.match(following):
            violations.append(f"{name}:{number}: Markdown pipe table outside a fence")

    if landing:
        return violations

    headings = [(number, line.rstrip()) for number, line in numbered if line.startswith("## ")]
    if not headings or headings[-1][1] != "## Related":
        violations.append(f"{name}: `## Related` must exist and be the final `##` section")
        return violations

    related_line = headings[-1][0]
    tail = [(number, line) for number, line in numbered if number > related_line]
    items, item_violations = _fold_related_items(tail)
    violations.extend(f"{name}:{violation}" for violation in item_violations)
    if not 1 <= len(items) <= 3:
        violations.append(f"{name}: `## Related` must carry 1-3 items, found {len(items)}")

    labels: list[str] = []
    for number, folded in items:
        match = _RELATED_ITEM.match(folded)
        if match is None:
            violations.append(
                f"{name}:{number}: Related item not shaped "
                f"`- **Label:** [Title](target) — reason`: {folded!r}"
            )
            continue
        label = match.group("label")
        if label not in ALLOWED_LABELS:
            violations.append(f"{name}:{number}: Related label {label!r} outside {ALLOWED_LABELS}")
            continue
        labels.append(label)
    if items and not item_violations and all(label not in ACTION_LABELS for label in labels):
        violations.append(f"{name}: `## Related` needs at least one `Do` or `Look up` route out")
    return violations


# --- the live corpus --------------------------------------------------------------------------


def _explanation_sources() -> list[Path]:
    """The routed Explanation sources — `.md` and `.mdx` discovered at runtime, mirroring the
    site collection's admission rule (`_`-prefixed basenames are unrouted)."""
    return sorted(
        path
        for path in EXPLANATION_DIR.iterdir()
        if path.suffix in {".md", ".mdx"} and not path.name.startswith("_")
    )


def test_the_explanation_corpus_is_non_empty():
    # Non-vacuous self-check: a tree/layout change must not silently empty the scan.
    assert len(_explanation_sources()) >= 5, (
        f"only {len(_explanation_sources())} Explanation sources found — the walk looks broken"
    )


def test_the_live_explanation_corpus_upholds_the_boundary():
    violations: list[str] = []
    for path in _explanation_sources():
        violations.extend(
            scan_explanation_source(
                path.relative_to(REPO_ROOT).as_posix(),
                path.read_text(encoding="utf-8"),
                landing=path.stem == "index",
            )
        )
    assert violations == [], "Explanation boundary violation(s):\n" + "\n".join(violations)


# --- scanner unit cases (synthetic sources) ---------------------------------------------------

GOOD_RELATED = """
## Related

- **Understand:** [Neighbor](./neighbor.md) — why the ideas connect.
- **Do:** [A task](../how-to/task.md) — get the thing done.
- **Look up:** [Exact detail](../reference/detail.md) — the
  exact fields, wrapped onto a continuation line.
"""

FRONTMATTER = '---\ntitle: "T"\ndescription: "D"\n---\n'


def _article(body: str) -> str:
    return f"{FRONTMATTER}\n# T\n\nProse.\n{body}"


def test_a_valid_article_passes_including_wrapped_items():
    assert scan_explanation_source("a.md", _article(GOOD_RELATED)) == []


def test_ordered_list_markers_are_caught_at_any_indentation():
    body = "1. first\n\n   2) nested\n" + GOOD_RELATED
    violations = scan_explanation_source("a.md", _article(body))
    assert len([v for v in violations if "ordered-list" in v]) == 2


def test_markdown_and_html_tables_are_caught():
    body = "| a | b |\n| --- | --- |\n| 1 | 2 |\n\n<TABLE>\n</TABLE>\n" + GOOD_RELATED
    violations = scan_explanation_source("a.md", _article(body))
    assert any("Markdown pipe table" in v for v in violations)
    assert any("HTML table" in v for v in violations)


def test_fenced_examples_never_trip_the_scan():
    body = (
        "```md\n1. step\n| a | b |\n| --- | --- |\n<table>\n```\n\n"
        "~~~text\n1) tilde-fenced step\n~~~\n" + GOOD_RELATED
    )
    assert scan_explanation_source("a.md", _article(body)) == []


def test_unordered_lists_imports_and_jsx_are_permitted():
    body = (
        'import Diagram from "../../site/src/components/Diagram.astro";\n\n'
        "- an unordered point\n- another\n\n<Diagram />\n\n"
        '<div class="perk-diagram-text">every node and edge</div>\n' + GOOD_RELATED
    )
    assert scan_explanation_source("a.mdx", _article(body)) == []


def test_missing_related_is_caught():
    violations = scan_explanation_source("a.md", _article("## Ideas\n\nProse.\n"))
    assert any("`## Related` must exist" in v for v in violations)


def test_non_final_related_is_caught():
    body = "## Related\n\n- **Do:** [T](t.md) — why.\n\n## Afterword\n\nProse.\n"
    violations = scan_explanation_source("a.md", _article(body))
    assert any("`## Related` must exist and be the final" in v for v in violations)


def test_invalid_label_is_caught():
    body = "## Related\n\n- **Learn:** [Tutorial](../tutorials/t.md) — labels outside the subset.\n"
    violations = scan_explanation_source("a.md", _article(body))
    assert any("outside" in v and "'Learn'" in v for v in violations)


def test_malformed_item_shape_is_caught():
    body = "## Related\n\n- [Bare link](t.md) with no label or reason\n"
    violations = scan_explanation_source("a.md", _article(body))
    assert any("not shaped" in v for v in violations)


def test_too_many_items_are_caught():
    items = "\n".join(f"- **Do:** [T{i}](t{i}.md) — why." for i in range(4))
    violations = scan_explanation_source("a.md", _article(f"## Related\n\n{items}\n"))
    assert any("1-3 items, found 4" in v for v in violations)


def test_empty_related_is_caught():
    violations = scan_explanation_source("a.md", _article("## Related\n"))
    assert any("1-3 items, found 0" in v for v in violations)


def test_all_understand_trailer_is_caught():
    body = "## Related\n\n- **Understand:** [A](a.md) — why.\n- **Understand:** [B](b.md) — why.\n"
    violations = scan_explanation_source("a.md", _article(body))
    assert any("at least one `Do` or `Look up`" in v for v in violations)


def test_non_item_content_after_related_is_caught():
    body = "## Related\n\n- **Do:** [T](t.md) — why.\n\nTrailing prose paragraph.\n"
    violations = scan_explanation_source("a.md", _article(body))
    assert any("non-item content" in v for v in violations)


def test_the_landing_is_exempt_from_related_but_not_from_structure():
    body = "- [A](./a.md) — a blurb.\n\n1. an ordered step\n"
    violations = scan_explanation_source("index.md", _article(body), landing=True)
    assert len(violations) == 1 and "ordered-list" in violations[0]
