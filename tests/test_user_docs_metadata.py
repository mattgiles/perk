"""Live-corpus guard: the operator-docs metadata contract (`docs/design/docs-site-blueprint.md`
§6) holds over the real `docs/user-docs/` tree.

Routed-or-excluded accounting, required frontmatter (`title`/`description`/`sidebar.order`),
the byte-equal title↔H1 rule, corpus-wide title/description/route uniqueness, the §3
1000-block `sidebar.order` discipline, and the `sidebarGroup` ownership discipline for the
flat `how-to/` tree. The site build (`docsSchema()` + the extended schema in
`docs/site/src/content.config.ts`) is the second, build-time validation surface; this guard
covers what the schema cannot (accounting, uniqueness, per-directory requiredness, block
discipline). Each check collects ALL offenders before asserting, so one failure names every
violating file.
"""

from pathlib import Path

import pytest

from perk.learn.docs_scan import _frontmatter_dict, _normalize, _strip_frontmatter

REPO_ROOT = Path(__file__).resolve().parents[1]
USER_DOCS = REPO_ROOT / "docs" / "user-docs"

# The only permitted excluded (`_`-prefixed) source: the maintainer-facing authoring reference.
EXPECTED_EXCLUDED = {"_authoring.md"}

ROUTED_SUFFIXES = {".md", ".mdx"}

# The §3 sidebar sections and their 1000-block bases: section dir (relative to the user-docs
# root; "" = the root home page) → the block base its index.md must carry. Non-index pages fall
# strictly inside their section's block (base < order < base + 1000).
SECTION_BASES = {"": 0, "tutorials": 1000, "how-to": 2000, "reference": 3000, "explanation": 4000}
BLOCK_SIZE = 1000

# The five §3 how-to operator groups, in §3 order — the closed `sidebarGroup` value set.
HOW_TO_GROUPS = (
    "Core workflow",
    "Objectives & learnings",
    "Headless & remote",
    "Customization",
    "Providers & backends",
)


def _walk_files() -> list[Path]:
    """Every file under the user-docs root, skipping dot-prefixed basenames/directories
    (mirrors the site loader's dotfile exclusion; also ignores `.DS_Store`-class noise)."""
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


def _route(path: Path) -> str:
    """The §2 route for a routed file: the suffix-less path, with an `index` basename routing
    to its parent directory (root `index` → `/`)."""
    rel = path.relative_to(USER_DOCS)
    stem_path = rel.parent if rel.stem == "index" else rel.parent / rel.stem
    return "/" + stem_path.as_posix().removeprefix(".")


def _frontmatter(path: Path) -> dict[str, object]:
    return _frontmatter_dict(path.read_text(encoding="utf-8"))


def _first_h1(path: Path) -> str | None:
    body = _strip_frontmatter(path.read_text(encoding="utf-8"))
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


def _order(path: Path) -> int:
    front = _frontmatter(path)
    sidebar = front.get("sidebar")
    assert isinstance(sidebar, dict), f"{_rel(path)}: sidebar is not a mapping"
    order = sidebar.get("order")
    assert isinstance(order, int) and not isinstance(order, bool), (
        f"{_rel(path)}: sidebar.order is not an int"
    )
    return order


def _section(path: Path) -> str:
    parts = path.relative_to(USER_DOCS).parts
    return parts[0] if len(parts) > 1 else ""


# --- 1. routed-or-excluded accounting ---------------------------------------------------------


def test_corpus_is_non_empty():
    # The non-vacuous self-check: a tree/layout change must not silently empty the walk.
    assert len(_routed_files()) >= 40, (
        f"only {len(_routed_files())} routed user docs found — the corpus walk looks broken"
    )


def test_every_file_is_an_approved_format():
    offenders = [_rel(p) for p in _walk_files() if p.suffix not in ROUTED_SUFFIXES]
    assert offenders == [], (
        f"non-.md/.mdx file(s) under docs/user-docs: {', '.join(offenders)} — every source is "
        "routed or explicitly excluded; a new asset kind needs explicit accounting here"
    )


def test_excluded_set_is_exactly_the_authoring_file():
    excluded = {_rel(p) for p in _walk_files() if p.name.startswith("_")}
    assert excluded == EXPECTED_EXCLUDED, (
        f"excluded (_-prefixed) files {sorted(excluded)} != {sorted(EXPECTED_EXCLUDED)} — every "
        "source is routed exactly once or explicitly excluded and tested as such (blueprint §6)"
    )


# --- 2. required frontmatter on every routed page ---------------------------------------------


def test_every_routed_page_has_a_frontmatter_block():
    offenders = [
        _rel(p) for p in _routed_files() if not p.read_text(encoding="utf-8").startswith("---\n")
    ]
    assert offenders == [], f"routed page(s) without a leading frontmatter block: {offenders}"


def test_frontmatter_parses_to_a_non_empty_mapping():
    offenders = [_rel(p) for p in _routed_files() if not _frontmatter(p)]
    assert offenders == [], f"routed page(s) with unparseable/empty frontmatter: {offenders}"


def test_title_is_a_non_empty_string():
    offenders = [
        _rel(p)
        for p in _routed_files()
        if not isinstance(t := _frontmatter(p).get("title"), str) or not t.strip()
    ]
    assert offenders == [], f"routed page(s) without a non-empty title: {offenders}"


def test_description_is_a_non_empty_single_line_string():
    offenders = [
        _rel(p)
        for p in _routed_files()
        if not isinstance(d := _frontmatter(p).get("description"), str)
        or not d.strip()
        or "\n" in d
    ]
    assert offenders == [], (
        f"routed page(s) without a one-line non-empty description: {offenders} — one sentence, "
        "unique corpus-wide (blueprint §6)"
    )


def test_sidebar_order_is_a_non_negative_int():
    offenders = []
    for path in _routed_files():
        sidebar = _frontmatter(path).get("sidebar")
        if not isinstance(sidebar, dict):
            offenders.append(f"{_rel(path)} (sidebar: {sidebar!r})")
            continue
        order = sidebar.get("order")
        if not isinstance(order, int) or isinstance(order, bool) or order < 0:
            offenders.append(f"{_rel(path)} (order: {order!r})")
    assert offenders == [], f"routed page(s) without a valid sidebar.order: {offenders}"


# --- 3. title ↔ H1 ----------------------------------------------------------------------------


def test_title_is_byte_equal_to_the_standalone_h1():
    offenders = []
    for path in _routed_files():
        h1 = _first_h1(path)
        title = _frontmatter(path).get("title")
        if h1 is None:
            offenders.append(f"{_rel(path)} (no `# ` heading in the body)")
        elif title != h1:
            offenders.append(f"{_rel(path)} (title {title!r} != H1 {h1!r})")
    assert offenders == [], (
        f"title↔H1 mismatch: {offenders} — frontmatter title must be byte-equal to the source's "
        "standalone `#` H1 (blueprint §6); change one, change both"
    )


# --- 4. corpus-wide uniqueness ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "key_of"),
    [
        ("title", lambda p: _normalize(str(_frontmatter(p).get("title")))),
        ("description", lambda p: _normalize(str(_frontmatter(p).get("description")))),
        ("route", _route),
    ],
)
def test_unique_corpus_wide(label, key_of):
    by_key: dict[str, list[str]] = {}
    for path in _routed_files():
        by_key.setdefault(key_of(path), []).append(_rel(path))
    collisions = {key: rels for key, rels in by_key.items() if len(rels) > 1}
    assert collisions == {}, (
        f"{label} collision(s) across routed pages: {collisions} — titles, descriptions, and "
        "routes are unique corpus-wide (blueprint §6)"
    )


# --- 5. sidebar.order discipline --------------------------------------------------------------


def test_orders_unique_within_each_directory():
    by_dir: dict[str, dict[int, list[str]]] = {}
    for path in _routed_files():
        by_dir.setdefault(str(path.parent), {}).setdefault(_order(path), []).append(_rel(path))
    collisions = [rels for orders in by_dir.values() for rels in orders.values() if len(rels) > 1]
    assert collisions == [], f"sidebar.order collision(s) within a directory: {collisions}"


def test_section_indexes_carry_the_block_base_and_pages_stay_in_block():
    sections = {_section(p) for p in _routed_files()}
    assert sections == set(SECTION_BASES), (
        f"section set {sorted(sections)} != {sorted(SECTION_BASES)} — a new top-level section "
        "needs a §3 block base recorded here"
    )
    offenders = []
    for path in _routed_files():
        base = SECTION_BASES[_section(path)]
        order = _order(path)
        # A section landing page (incl. the root home page) is a direct `index.*` child of its
        # section dir; it carries its block base exactly, so Starlight's min-order directory
        # weighting keeps sections in §3 order. Every other page falls strictly inside the block.
        is_section_index = path.stem == "index" and len(path.relative_to(USER_DOCS).parts) <= 2
        if is_section_index:
            if order != base:
                offenders.append(f"{_rel(path)} (order {order} != block base {base})")
        elif not base < order < base + BLOCK_SIZE:
            offenders.append(f"{_rel(path)} (order {order} outside ({base}, {base + BLOCK_SIZE}))")
    assert offenders == [], f"sidebar.order block violation(s): {offenders}"


# --- 6. sidebarGroup discipline ---------------------------------------------------------------


def test_sidebar_group_required_on_how_to_guides_and_absent_elsewhere():
    offenders = []
    for path in _routed_files():
        group = _frontmatter(path).get("sidebarGroup")
        if _section(path) == "how-to" and path.name != "index.md":
            if group not in HOW_TO_GROUPS:
                offenders.append(f"{_rel(path)} (sidebarGroup: {group!r})")
        elif group is not None:
            offenders.append(f"{_rel(path)} (unexpected sidebarGroup: {group!r})")
    assert offenders == [], (
        f"sidebarGroup violation(s): {offenders} — required (one of the five §3 groups) on every "
        "routed how-to/ page except index.md, absent everywhere else"
    )


def test_sidebar_groups_are_contiguous_and_in_section_order():
    # Walk the how-to guide pages in sidebar.order; the group sequence must be exactly the five
    # §3 groups, each as one contiguous run — so the ownership record and the order record agree.
    guides = sorted(
        (p for p in _routed_files() if _section(p) == "how-to" and p.name != "index.md"),
        key=_order,
    )
    sequence = [_frontmatter(p).get("sidebarGroup") for p in guides]
    runs = [group for i, group in enumerate(sequence) if i == 0 or sequence[i - 1] != group]
    assert runs == list(HOW_TO_GROUPS), (
        f"how-to group runs (by ascending sidebar.order) {runs} != {list(HOW_TO_GROUPS)} — pages "
        "sharing a sidebarGroup must occupy a contiguous order range, groups in §3 order"
    )
