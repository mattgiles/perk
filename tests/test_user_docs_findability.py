"""Live-corpus guard: the findability conventions hold over the real `docs/user-docs/` tree.

Three families keep the corpus reachable rather than merely present:

- **Related trailers** — every routed page ends with a final ``## Related`` section of 1-3
  intent-labeled links in the closed four-label vocabulary, or is one of the frozen deliberate
  omissions (pure routers and the lookup index). The allowlist is ratcheted: an allowlisted
  page that gains a trailer fails as a stale entry. The Explanation quadrant's stricter guard
  (`tests/test_explanation_boundary.py`: narrower label subset, action-route rule) stays in
  force alongside this corpus-wide shape check.
- **Stable entry-point links** — the repo's front doors (`README.md`, `docs/index.md`) keep
  resolving into the corpus, with a minimum coverage floor (not an exact census — entry
  points may grow).
- **Pagination discipline** — the ``prev``/``next`` frontmatter opt-ins appear on exactly the
  tutorials chain with exactly the decided values, nowhere else (the source mirror of the
  rendered-edge assertion in `docs/site/checks/built-site.test.mjs`).

Each check collects ALL offenders before asserting, so one failure names every violating file.
"""

import re
from pathlib import Path

from perk.learn.docs_scan import _frontmatter_dict

REPO_ROOT = Path(__file__).resolve().parents[1]
USER_DOCS = REPO_ROOT / "docs" / "user-docs"

# The closed Related label vocabulary (docs/user-docs/_authoring.md, "Related links").
ALLOWED_LABELS = ("Learn", "Do", "Look up", "Understand")

# The deliberate omissions: the home page and the four quadrant landings are pure routers,
# and the glossary is a lookup index — none carries a Related trailer. Frozen and ratcheted:
# a page listed here that gains a trailer fails as a stale allowlist entry.
NO_RELATED = frozenset(
    {
        "index.mdx",
        "tutorials/index.md",
        "how-to/index.md",
        "reference/index.md",
        "explanation/index.md",
        "reference/glossary.md",
    }
)

# The pagination opt-ins: global pagination is off, and per-page `prev`/`next: true` is
# allowed only for a deliberately linear reading sequence — currently exactly the tutorials
# chain (four rendered edges; no prev into the tutorials landing, no next out of the last
# tutorial).
PAGINATION = {
    "tutorials/get-started.md": {"next": True},
    "tutorials/drive-an-objective.mdx": {"prev": True, "next": True},
    "tutorials/drive-a-stacked-objective.md": {"prev": True},
}

# One folded Related item (the shape bound in `_authoring.md`); the label is validated
# separately so a wrong label reports as a label problem, not a shape problem. A local copy
# of the `tests/test_explanation_boundary.py` item regex, with one corpus-wide widening: link
# text is matched greedily (`.+`) instead of `[^\]]+`, because general-corpus link texts
# legitimately carry brackets (backticked `[[ci.checks]]`-style tokens) and a lookup item may
# name two exact command surfaces as sibling links before its one — reason.
_RELATED_ITEM = re.compile(r"^- \*\*(?P<label>[^*]+):\*\* \[.+\]\(\S+\) — \S.*$")
# A fence opens with 3+ backticks or tildes and closes at the next line carrying at least as
# many of the same character and nothing else. Local copy of the explanation guard's scanner.
_FENCE_MARKER = re.compile(r"^ {0,3}(`{3,}|~{3,})")
# A local markdown link target: `[text](target)` (images included — they are links too).
_MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)


def _walk_files() -> list[Path]:
    """Every file under the user-docs root, skipping dot-prefixed basenames/directories
    (mirrors `tests/test_user_docs_metadata.py::_walk_files` and the site loader)."""
    return [
        path
        for path in sorted(USER_DOCS.rglob("*"))
        if path.is_file()
        and not any(part.startswith(".") for part in path.relative_to(USER_DOCS).parts)
    ]


def _routed_files() -> list[Path]:
    return [p for p in _walk_files() if not p.name.startswith("_")]


def _rel(path: Path) -> str:
    return path.relative_to(USER_DOCS).as_posix()


def _body_lines(text: str) -> list[str]:
    """The body lines with any leading frontmatter block removed."""
    lines = text.split("\n")
    start = 0
    if lines and lines[0] == "---":
        for index in range(1, len(lines)):
            if lines[index] == "---":
                start = index + 1
                break
    return lines[start:]


def _outside_fences(lines: list[str]) -> list[str]:
    """The lines outside fenced code blocks (fence delimiter lines excluded too)."""
    outside: list[str] = []
    open_fence: str | None = None
    for line in lines:
        if open_fence is None:
            match = _FENCE_MARKER.match(line)
            if match:
                open_fence = match.group(1)
            else:
                outside.append(line)
            continue
        if re.match(rf"^ {{0,3}}({re.escape(open_fence[0])}{{{len(open_fence)},}})\s*$", line):
            open_fence = None
    return outside


def _fold_items(tail: list[str]) -> tuple[list[str], list[str]]:
    """Fold post-``## Related`` lines into logical items (a ``- `` line plus indented
    continuations). Returns ``(items, violations)``."""
    items: list[str] = []
    violations: list[str] = []
    for line in tail:
        if not line.strip():
            continue
        if line.startswith("- "):
            items.append(line.rstrip())
        elif line[:1].isspace() and items:
            items[-1] = f"{items[-1]} {line.strip()}"
        else:
            violations.append(f"non-item content after `## Related`: {line.strip()!r}")
    return items, violations


def _related_violations(name: str, text: str) -> list[str]:
    """All Related-trailer violations in one routed source (which must carry a trailer)."""
    lines = _outside_fences(_body_lines(text))
    headings = [line.rstrip() for line in lines if line.startswith("## ")]
    if not headings or headings[-1] != "## Related":
        return [f"{name}: `## Related` must exist and be the final `##` section"]
    related_at = max(index for index, line in enumerate(lines) if line.rstrip() == "## Related")
    items, violations = _fold_items(lines[related_at + 1 :])
    violations = [f"{name}: {violation}" for violation in violations]
    if not 1 <= len(items) <= 3:
        violations.append(f"{name}: `## Related` must carry 1-3 items, found {len(items)}")
    for folded in items:
        match = _RELATED_ITEM.match(folded)
        if match is None:
            violations.append(
                f"{name}: Related item not shaped "
                f"`- **Label:** [Title](target) — reason`: {folded!r}"
            )
        elif match.group("label") not in ALLOWED_LABELS:
            violations.append(
                f"{name}: Related label {match.group('label')!r} outside {ALLOWED_LABELS}"
            )
    return violations


# --- 1. Related shape + deliberate-omission accounting ----------------------------------------


def test_the_corpus_walk_is_non_vacuous():
    assert len(_routed_files()) >= 40, (
        f"only {len(_routed_files())} routed user docs found — the corpus walk looks broken"
    )


def test_every_routed_page_has_a_related_trailer_or_is_a_deliberate_omission():
    violations: list[str] = []
    for path in _routed_files():
        rel = _rel(path)
        text = path.read_text(encoding="utf-8")
        has_related = any(
            line.rstrip() == "## Related" for line in _outside_fences(_body_lines(text))
        )
        if rel in NO_RELATED:
            # The ratchet: a deliberate omission that gains a trailer is a stale allowlist
            # entry — shrink NO_RELATED rather than carrying dead accounting.
            if has_related:
                violations.append(f"{rel}: gained a `## Related` trailer — stale NO_RELATED entry")
            continue
        violations.extend(_related_violations(rel, text))
    assert violations == [], "Related-trailer violation(s):\n" + "\n".join(violations)


def test_the_omission_allowlist_names_only_existing_routed_pages():
    routed = {_rel(p) for p in _routed_files()}
    missing = sorted(NO_RELATED - routed)
    assert missing == [], f"NO_RELATED entries without a routed page: {missing}"


# --- 2. stable entry-point links ---------------------------------------------------------------


def _corpus_link_targets(source: Path) -> list[tuple[str, Path]]:
    """The `(raw href, resolved repo path)` pairs of `source`'s local markdown links that
    resolve under `docs/user-docs/` — resolved against the CONTAINING FILE's directory, which
    handles both README's repo-root-style hrefs and `docs/index.md`'s `./…` form without
    special-casing either file."""
    targets: list[tuple[str, Path]] = []
    for match in _MD_LINK.finditer(source.read_text(encoding="utf-8")):
        href = match.group(1)
        if _SCHEME.match(href) or href.startswith(("#", "/")):
            continue
        resolved = (source.parent / re.sub(r"[?#].*$", "", href)).resolve()
        if resolved.is_relative_to(USER_DOCS):
            targets.append((href, resolved))
    return targets


ENTRY_POINTS = {
    # README must reach the corpus home, all four quadrant landings, and the first tutorial.
    "README.md": (
        "index.mdx",
        "tutorials/index.md",
        "how-to/index.md",
        "reference/index.md",
        "explanation/index.md",
        "tutorials/get-started.md",
    ),
    # The contributor docs index must reach the corpus home.
    "docs/index.md": ("index.mdx",),
}


def test_entry_points_resolve_and_cover_the_corpus_doors():
    violations: list[str] = []
    for entry, minimum in ENTRY_POINTS.items():
        source = REPO_ROOT / entry
        targets = _corpus_link_targets(source)
        assert targets != [], f"{entry}: no corpus links found — the entry-point scan is broken"
        for href, resolved in targets:
            if not resolved.is_file():
                violations.append(f"{entry}: dangling corpus link {href!r}")
        reached = {_rel(resolved) for _, resolved in targets if resolved.is_file()}
        for required in minimum:
            if required not in reached:
                violations.append(f"{entry}: no link reaching docs/user-docs/{required}")
    assert violations == [], "entry-point link violation(s):\n" + "\n".join(violations)


# --- 3. pagination discipline (source mirror) ---------------------------------------------------


def test_prev_next_keys_are_exactly_the_tutorials_chain():
    offenders: list[str] = []
    for path in _routed_files():
        front = _frontmatter_dict(path.read_text(encoding="utf-8"))
        actual = {key: front[key] for key in ("prev", "next") if key in front}
        expected = PAGINATION.get(_rel(path), {})
        if actual != expected:
            offenders.append(f"{_rel(path)}: prev/next {actual!r} != expected {expected!r}")
    assert offenders == [], (
        "pagination frontmatter violation(s): "
        + "; ".join(offenders)
        + " — `prev`/`next` opt-ins are allowed only for the deliberate tutorials chain "
        "(docs/user-docs/_authoring.md metadata contract)"
    )
