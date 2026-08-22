"""The rich, deterministic, advisory docs scan (contracts.md §8.35, node 5.1)."""

from pathlib import Path

from perk.learn.docs_scan import (
    BrokenDocPath,
    DocFindings,
    DuplicateGroup,
    StalePointer,
    read_learned_docs,
    scan_docs_richly,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# --- stale source pointers --------------------------------------------------------------------


def test_stale_pointer_missing_file(tmp_path: Path):
    # `perk/run/launch.py` is a DIR here (module-split) → the pointer's file is gone.
    (tmp_path / "perk/run/launch").mkdir(parents=True)
    _write(
        tmp_path / "docs/learned/workflow/p.md",
        "See `perk/run/launch.py::_plan_read_instruction` for the seam.\n",
    )
    findings = scan_docs_richly(tmp_path)
    assert findings.stale_pointers == (
        StalePointer(
            doc="docs/learned/workflow/p.md",
            pointer="perk/run/launch.py::_plan_read_instruction",
            reason="missing-file",
        ),
    )


def test_stale_pointer_missing_symbol(tmp_path: Path):
    _write(tmp_path / "perk/learn/evidence.py", "def gather_evidence():\n    pass\n")
    _write(
        tmp_path / "docs/learned/x.md",
        "The helper `perk/learn/evidence.py::no_such_fn` is gone.\n",
    )
    findings = scan_docs_richly(tmp_path)
    assert findings.stale_pointers == (
        StalePointer(
            doc="docs/learned/x.md",
            pointer="perk/learn/evidence.py::no_such_fn",
            reason="missing-symbol",
        ),
    )


def test_present_pointers_no_finding(tmp_path: Path):
    # Plain path, path::symbol, and Class.method whose method-segment is present → all clean.
    _write(
        tmp_path / "perk/x.py",
        "def present_symbol():\n    pass\n\n\nclass Klass:\n    def method(self):\n        pass\n",
    )
    _write(
        tmp_path / "docs/learned/x.md",
        "Refs: `perk/x.py`, `perk/x.py::present_symbol`, `perk/x.py::Klass.method`.\n",
    )
    assert scan_docs_richly(tmp_path).stale_pointers == ()


def test_src_layout_pointer_resolves(tmp_path: Path):
    # Import-path-shaped `perk/...` pointer whose file lives under `src/` (the uv-workspace
    # src-layout) → clean, and the symbol probe reads the src-resolved file.
    _write(tmp_path / "src/perk/learn/evidence.py", "def gather_evidence():\n    pass\n")
    _write(
        tmp_path / "docs/learned/x.md",
        "Refs: `perk/learn/evidence.py`, `perk/learn/evidence.py::gather_evidence`,"
        " and the stale `perk/learn/evidence.py::no_such_fn`.\n",
    )
    findings = scan_docs_richly(tmp_path)
    assert findings.stale_pointers == (
        StalePointer(
            doc="docs/learned/x.md",
            pointer="perk/learn/evidence.py::no_such_fn",
            reason="missing-symbol",
        ),
    )


def test_module_split_package_dir_resolves(tmp_path: Path):
    # A module→package split preserved the import path (`perk/backends/linear.py` →
    # `src/perk/backends/linear/`) → the historical module pointer stays valid; symbol
    # probing reads the package `__init__.py`.
    _write(
        tmp_path / "src/perk/backends/linear/__init__.py",
        "from perk.backends.linear.client import client_from_env\n",
    )
    _write(
        tmp_path / "docs/learned/x.md",
        "Refs: `perk/backends/linear.py`, `perk/backends/linear.py::client_from_env`,"
        " and the stale `perk/backends/linear.py::no_such_fn`.\n",
    )
    findings = scan_docs_richly(tmp_path)
    assert findings.stale_pointers == (
        StalePointer(
            doc="docs/learned/x.md",
            pointer="perk/backends/linear.py::no_such_fn",
            reason="missing-symbol",
        ),
    )


def test_genuinely_missing_perk_pointer_still_flags(tmp_path: Path):
    # None of the probes hit (no literal file, no src/ file, no package dir) → missing-file.
    (tmp_path / "src/perk").mkdir(parents=True)
    _write(tmp_path / "docs/learned/x.md", "Gone: `perk/no_such_module.py::fn`.\n")
    findings = scan_docs_richly(tmp_path)
    assert findings.stale_pointers == (
        StalePointer(
            doc="docs/learned/x.md",
            pointer="perk/no_such_module.py::fn",
            reason="missing-file",
        ),
    )


def test_non_perk_root_never_probes_src(tmp_path: Path):
    # Non-`perk` roots keep the plain probe — an `extension/...` file under `src/` does NOT count.
    _write(tmp_path / "src/extension/index.ts", "export {};\n")
    _write(tmp_path / "docs/learned/x.md", "See `extension/index.ts`.\n")
    findings = scan_docs_richly(tmp_path)
    assert findings.stale_pointers == (
        StalePointer(
            doc="docs/learned/x.md",
            pointer="extension/index.ts",
            reason="missing-file",
        ),
    )


def test_non_source_root_pointer_skipped(tmp_path: Path):
    # `vendor` is not a real source root → never a stale pointer even though the file is absent.
    _write(tmp_path / "docs/learned/x.md", "A made-up `vendor/foo.py` path.\n")
    assert scan_docs_richly(tmp_path).stale_pointers == ()


def test_stale_pointer_deduped_per_doc(tmp_path: Path):
    (tmp_path / "perk/run/launch").mkdir(parents=True)
    _write(
        tmp_path / "docs/learned/x.md",
        "First `perk/run/launch.py::a` then again `perk/run/launch.py::a`.\n",
    )
    findings = scan_docs_richly(tmp_path)
    assert len(findings.stale_pointers) == 1


# --- broken doc paths -------------------------------------------------------------------------


def test_broken_doc_path_catalog_link(tmp_path: Path):
    _write(tmp_path / "docs/learned/index.md", "- [Ghost](workflow/ghost.md)\n")
    findings = scan_docs_richly(tmp_path)
    assert findings.broken_doc_paths == (
        BrokenDocPath(doc="docs/learned/index.md", target="workflow/ghost.md"),
    )


def test_broken_doc_path_non_findings(tmp_path: Path):
    _write(tmp_path / "docs/learned/workflow/real.md", "# Real\n")
    _write(tmp_path / "docs/user-docs/cross.md", "# Cross\n")
    _write(
        tmp_path / "docs/learned/workflow/sub.md",
        (
            "Valid relative: [real](real.md). "
            "Cross-tree: [x](../../user-docs/cross.md). "
            "External: [ext](https://example.com/page.md). "
            "Anchor: [a](#section). "
            "Code-capture: [c](cmd: C) and [s](scratch|runs). "
            "Filtered .md with space: [w](broken file.md) and pipe: [p](broken|path.md).\n"
        ),
    )
    # The fragment-stripped self-anchor and all skip-rules fire → no broken-doc-path findings.
    assert scan_docs_richly(tmp_path).broken_doc_paths == ()


def test_broken_doc_path_strips_fragment(tmp_path: Path):
    _write(tmp_path / "docs/learned/workflow/real.md", "# Real\n")
    _write(
        tmp_path / "docs/learned/workflow/sub.md",
        "Anchored valid: [r](real.md#heading). Anchored broken: [g](ghost.md#heading).\n",
    )
    findings = scan_docs_richly(tmp_path)
    assert findings.broken_doc_paths == (
        BrokenDocPath(doc="docs/learned/workflow/sub.md", target="ghost.md"),
    )


def test_broken_doc_path_mdx_target(tmp_path: Path):
    _write(tmp_path / "docs/learned/workflow/sub.md", "[Ghost](ghost.mdx)\n")
    findings = scan_docs_richly(tmp_path)
    assert findings.broken_doc_paths == (
        BrokenDocPath(doc="docs/learned/workflow/sub.md", target="ghost.mdx"),
    )


def test_valid_doc_path_mdx_target(tmp_path: Path):
    _write(tmp_path / "docs/user-docs/target.mdx", "# Target\n")
    _write(tmp_path / "docs/user-docs/source.md", "[Target](target.mdx)\n")
    assert scan_docs_richly(tmp_path).broken_doc_paths == ()


# --- broken doc references: full-span backtick doc-path tokens ---------------------------------


def test_backtick_doc_token_repo_root_missing_flags(tmp_path: Path):
    # The motivating class: a repo-root-anchored `docs/planning/…` citation whose tree was removed.
    _write(
        tmp_path / "docs/learned/workflow/doc.md",
        "See `docs/planning/stacked-prs/objective.md` for the shape.\n",
    )
    findings = scan_docs_richly(tmp_path)
    assert findings.broken_doc_paths == (
        BrokenDocPath(
            doc="docs/learned/workflow/doc.md",
            target="docs/planning/stacked-prs/objective.md",
        ),
    )


def test_backtick_doc_token_repo_root_present_clean(tmp_path: Path):
    # The `shared/contracts.md`-shape case: a repo-root-anchored citation of a real doc is clean.
    _write(tmp_path / "docs/planning/stacked-prs/objective.md", "# Objective\n")
    _write(
        tmp_path / "docs/learned/workflow/doc.md",
        "See `docs/planning/stacked-prs/objective.md` for the shape.\n",
    )
    assert scan_docs_richly(tmp_path).broken_doc_paths == ()


def test_backtick_doc_token_strips_fragment(tmp_path: Path):
    _write(tmp_path / "docs/learned/x.md", "Anchored: `docs/guide.md#heading`.\n")
    findings = scan_docs_richly(tmp_path)
    assert findings.broken_doc_paths == (
        BrokenDocPath(doc="docs/learned/x.md", target="docs/guide.md"),
    )
    _write(tmp_path / "docs/guide.md", "# Guide\n")
    assert scan_docs_richly(tmp_path).broken_doc_paths == ()


def test_backtick_doc_token_mdx_detected(tmp_path: Path):
    _write(tmp_path / "docs/learned/x.md", "An `guides/page.mdx` token.\n")
    findings = scan_docs_richly(tmp_path)
    assert findings.broken_doc_paths == (
        BrokenDocPath(doc="docs/learned/x.md", target="guides/page.mdx"),
    )


def test_backtick_doc_token_parent_base(tmp_path: Path):
    # A parent-relative sibling mention resolves against the containing doc's dir.
    _write(tmp_path / "docs/learned/workflow/sub.md", "See `guides/x.md`.\n")
    findings = scan_docs_richly(tmp_path)
    assert findings.broken_doc_paths == (
        BrokenDocPath(doc="docs/learned/workflow/sub.md", target="guides/x.md"),
    )
    _write(tmp_path / "docs/learned/workflow/guides/x.md", "# X\n")
    assert scan_docs_richly(tmp_path).broken_doc_paths == ()


def test_backtick_doc_token_learned_scan_root_base(tmp_path: Path):
    # The two-tier index's cross-category shorthand: a `workflow/` doc citing `pi/b.md` resolves
    # against the learned scan root (`docs/learned/`).
    _write(tmp_path / "docs/learned/workflow/a.md", "Cross-category: `pi/b.md`.\n")
    findings = scan_docs_richly(tmp_path)
    assert findings.broken_doc_paths == (
        BrokenDocPath(doc="docs/learned/workflow/a.md", target="pi/b.md"),
    )
    _write(tmp_path / "docs/learned/pi/b.md", "# B\n")
    assert scan_docs_richly(tmp_path).broken_doc_paths == ()


def test_backtick_doc_token_user_docs_scan_root_base(tmp_path: Path):
    # A user doc citing another user doc from the user-docs root resolves via its scan root.
    _write(tmp_path / "docs/user-docs/reference/b.md", "# B\n")
    _write(tmp_path / "docs/user-docs/guides/a.md", "# A\n\nSee `reference/b.md`.\n")
    assert scan_docs_richly(tmp_path).broken_doc_paths == ()


def test_backtick_doc_token_slashless_skipped(tmp_path: Path):
    # A bare filename is a name-mention, not a path claim (corpus-tuned) — never flagged.
    _write(tmp_path / "docs/learned/x.md", "Every skill has a `SKILL.md`.\n")
    assert scan_docs_richly(tmp_path).broken_doc_paths == ()


def test_backtick_doc_token_non_full_span_and_pointer_shaped_skipped(tmp_path: Path):
    # Prose-carrying spans and pointer-shaped spans are not doc-path tokens.
    _write(
        tmp_path / "docs/learned/x.md",
        "Prose `see docs/x.md` and pointer-shaped `docs/x.md::sym`.\n",
    )
    assert scan_docs_richly(tmp_path) == DocFindings()


def test_backtick_doc_token_url_skipped(tmp_path: Path):
    _write(tmp_path / "docs/learned/x.md", "External `https://example.com/x.md`.\n")
    assert scan_docs_richly(tmp_path).broken_doc_paths == ()


def test_backtick_doc_token_absolute_skipped(tmp_path: Path):
    _write(tmp_path / "docs/learned/x.md", "Absolute `/docs/x.md`.\n")
    assert scan_docs_richly(tmp_path).broken_doc_paths == ()


def test_stale_pointer_and_backtick_doc_token_fire_independently(tmp_path: Path):
    # The extension families are disjoint: one doc carrying a phantom source pointer AND a stale
    # backtick doc token yields one finding in EACH family.
    (tmp_path / "src/perk").mkdir(parents=True)
    _write(
        tmp_path / "docs/learned/x.md",
        "Ghost `perk/gone.py::fn` beside stale `docs/planning/objective.md`.\n",
    )
    findings = scan_docs_richly(tmp_path)
    assert findings.stale_pointers == (
        StalePointer(doc="docs/learned/x.md", pointer="perk/gone.py::fn", reason="missing-file"),
    )
    assert findings.broken_doc_paths == (
        BrokenDocPath(doc="docs/learned/x.md", target="docs/planning/objective.md"),
    )


def test_backtick_doc_token_deduped_per_doc(tmp_path: Path):
    _write(
        tmp_path / "docs/learned/x.md",
        "First `docs/gone.md` then again `docs/gone.md`.\n",
    )
    assert len(scan_docs_richly(tmp_path).broken_doc_paths) == 1


def test_cross_arm_dedup_link_and_backtick_share_one_row(tmp_path: Path):
    # A Markdown link and a backtick token sharing one fragment-stripped target → one row.
    _write(
        tmp_path / "docs/learned/x.md",
        "[g](sub/ghost.md#frag) and the same `sub/ghost.md` token.\n",
    )
    findings = scan_docs_richly(tmp_path)
    assert findings.broken_doc_paths == (
        BrokenDocPath(doc="docs/learned/x.md", target="sub/ghost.md"),
    )


def test_links_differing_only_in_fragment_dedupe_to_one_row(tmp_path: Path):
    # The per-doc dedup key is the fragment-stripped target (deliberate micro-change).
    _write(
        tmp_path / "docs/learned/x.md",
        "[a](ghost.md#one) and [b](ghost.md#two).\n",
    )
    findings = scan_docs_richly(tmp_path)
    assert findings.broken_doc_paths == (BrokenDocPath(doc="docs/learned/x.md", target="ghost.md"),)


def test_mixed_arm_findings_sorted_by_doc_then_target(tmp_path: Path):
    _write(
        tmp_path / "docs/learned/x.md",
        "Token `a-token/ghost.md` and link [z](z-link-ghost.md).\n",
    )
    findings = scan_docs_richly(tmp_path)
    assert [(b.doc, b.target) for b in findings.broken_doc_paths] == [
        ("docs/learned/x.md", "a-token/ghost.md"),
        ("docs/learned/x.md", "z-link-ghost.md"),
    ]


def test_climbing_backtick_token_degrades_never_raises(tmp_path: Path):
    # A `..`-climbing token walks the guarded resolve on every base without raising — the
    # outcome is flag-or-skip, never an exception out of the advisory scan.
    _write(
        tmp_path / "docs/learned/x.md",
        "Climb: `../../../../../../nowhere-perk-test/ghost.md`.\n",
    )
    findings = scan_docs_richly(tmp_path)
    assert len(findings.broken_doc_paths) <= 1


# --- duplicate / routing collisions -----------------------------------------------------------


def test_duplicate_groups_title_and_read_when(tmp_path: Path):
    _write(
        tmp_path / "docs/learned/a.md",
        "---\ntitle: Same Title\nread_when: working on foo\n---\n",
    )
    _write(
        tmp_path / "docs/learned/b.md",
        "---\ntitle: same   title\nread_when: working on foo\n---\n",
    )
    pair = ("docs/learned/a.md", "docs/learned/b.md")
    findings = scan_docs_richly(tmp_path)
    assert findings.duplicate_groups == (
        DuplicateGroup(basis="read_when", key="working on foo", docs=pair),
        DuplicateGroup(basis="title", key="same title", docs=pair),
    )


def test_duplicate_groups_distinct_docs_none(tmp_path: Path):
    _write(tmp_path / "docs/learned/a.md", "---\ntitle: Alpha\nread_when: foo\n---\n")
    _write(tmp_path / "docs/learned/b.md", "---\ntitle: Beta\nread_when: bar\n---\n")
    assert scan_docs_richly(tmp_path).duplicate_groups == ()


def test_duplicate_title_same_kind_only(tmp_path: Path):
    # A learned doc and a user-doc sharing a title do NOT collide (different kind).
    _write(tmp_path / "docs/learned/a.md", "---\ntitle: Shared\n---\n")
    _write(tmp_path / "docs/user-docs/b.md", "# Shared\n\nBody.\n")
    assert scan_docs_richly(tmp_path).duplicate_groups == ()


def test_user_doc_duplicate_title_keys_on_frontmatter(tmp_path: Path):
    # The user-doc duplicate-title guard keys on the frontmatter-first title: two user docs with
    # the same frontmatter `title` collide even though their H1s differ.
    _write(tmp_path / "docs/user-docs/a.md", '---\ntitle: "Shared"\n---\n\n# H1 alpha\n')
    _write(tmp_path / "docs/user-docs/b.md", '---\ntitle: "shared"\n---\n\n# H1 beta\n')
    findings = scan_docs_richly(tmp_path)
    assert findings.duplicate_groups == (
        DuplicateGroup(
            basis="title",
            key="shared",
            docs=("docs/user-docs/a.md", "docs/user-docs/b.md"),
        ),
    )


def test_user_doc_frontmatter_title_collides_with_legacy_h1(tmp_path: Path):
    # A frontmatter title collides with another user doc's same-text legacy H1 title.
    _write(tmp_path / "docs/user-docs/a.md", '---\ntitle: "Shared"\n---\n\n# H1 alpha\n')
    _write(tmp_path / "docs/user-docs/b.md", "# Shared\n\nBody.\n")
    findings = scan_docs_richly(tmp_path)
    assert findings.duplicate_groups == (
        DuplicateGroup(
            basis="title",
            key="shared",
            docs=("docs/user-docs/a.md", "docs/user-docs/b.md"),
        ),
    )


def test_user_doc_underscore_and_dot_paths_contribute_no_findings(tmp_path: Path):
    # Excluded user-doc paths (`_`-prefixed basename, dot-prefixed component) never enter the
    # rich scan: their broken links and duplicate titles are invisible.
    _write(tmp_path / "docs/user-docs/_authoring.md", "# Shared\n\n[ghost](ghost.md)\n")
    _write(tmp_path / "docs/user-docs/.obsidian/note.md", "# Shared\n\n[ghost](ghost.md)\n")
    _write(tmp_path / "docs/user-docs/real.md", "# Shared\n\nBody.\n")
    assert scan_docs_richly(tmp_path) == DocFindings()


def test_user_doc_mdx_broken_links_detected(tmp_path: Path):
    # An admitted `.mdx` user doc's broken `.md` links are still detected.
    _write(
        tmp_path / "docs/user-docs/page.mdx",
        '---\ntitle: "MDX"\n---\n\n# MDX\n\n[ghost](ghost.md)\n',
    )
    findings = scan_docs_richly(tmp_path)
    assert findings.broken_doc_paths == (
        BrokenDocPath(doc="docs/user-docs/page.mdx", target="ghost.md"),
    )


# --- determinism / bounding / never-raises ----------------------------------------------------


def test_findings_sorted_deterministic(tmp_path: Path):
    (tmp_path / "perk/run/launch").mkdir(parents=True)
    _write(
        tmp_path / "docs/learned/x.md",
        "`perk/run/launch.py::zeta` and `perk/run/launch.py::alpha`.\n",
    )
    pointers = scan_docs_richly(tmp_path).stale_pointers
    assert [p.pointer for p in pointers] == sorted(p.pointer for p in pointers)


def test_max_findings_truncation_is_deterministic(tmp_path: Path):
    links = " ".join(f"[l](link-{i:03d}.md)" for i in range(250))
    _write(tmp_path / "docs/learned/index.md", links + "\n")
    broken = scan_docs_richly(tmp_path).broken_doc_paths
    assert len(broken) == 200  # _MAX_FINDINGS
    # sorted BEFORE the cap → the first 200 lexicographic targets survive
    assert [b.target for b in broken] == [f"link-{i:03d}.md" for i in range(200)]


def test_max_findings_truncation_stale_pointers(tmp_path: Path):
    # 250 distinct phantom `perk/…::x` pointers in one doc; `perk/` never exists in tmp so each is
    # a missing-file stale pointer. Cap-then-sort determinism: the 200 lexicographically-smallest
    # pointer tokens survive (sorted by (doc, pointer) BEFORE the `_MAX_FINDINGS` cap).
    spans = " ".join(f"`perk/z-{i:03d}.py::sym`" for i in range(250))
    _write(tmp_path / "docs/learned/x.md", spans + "\n")
    pointers = scan_docs_richly(tmp_path).stale_pointers
    assert len(pointers) == 200  # _MAX_FINDINGS
    assert [p.pointer for p in pointers] == [f"perk/z-{i:03d}.py::sym" for i in range(200)]


def test_max_findings_truncation_duplicate_groups(tmp_path: Path):
    # 250 distinct titles, each shared by two learned docs → 250 title-collision groups; cap-then-
    # sort keeps the 200 lexicographically-smallest keys (sorted by (basis, key) BEFORE the cap).
    for i in range(250):
        title = f"dup title {i:03d}"
        _write(tmp_path / f"docs/learned/a{i:03d}.md", f"---\ntitle: {title}\n---\nA\n")
        _write(tmp_path / f"docs/learned/b{i:03d}.md", f"---\ntitle: {title}\n---\nB\n")
    groups = scan_docs_richly(tmp_path).duplicate_groups
    assert len(groups) == 200  # _MAX_FINDINGS
    assert all(g.basis == "title" for g in groups)
    assert [g.key for g in groups] == [f"dup title {i:03d}" for i in range(200)]


def test_malformed_frontmatter_never_raises(tmp_path: Path):
    _write(tmp_path / "docs/learned/bad.md", "---\nthis: : : not yaml\n---\nBody\n")
    # No crash; malformed frontmatter contributes no collision basis.
    assert scan_docs_richly(tmp_path) == DocFindings()


def test_empty_roots_all_empty(tmp_path: Path):
    assert scan_docs_richly(tmp_path) == DocFindings()


def test_non_utf8_doc_skipped_never_raises(tmp_path: Path):
    # A non-UTF-8 `.md` raises UnicodeDecodeError on read; the scan degrades to skip, never raises.
    bad = tmp_path / "docs/learned/binary.md"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(b"\xff\xfe not valid utf-8 \x80\n")
    assert scan_docs_richly(tmp_path) == DocFindings()


def test_pathological_link_target_skipped_never_raises(tmp_path: Path):
    # A link target with an embedded NUL byte makes `(parent / target).resolve()` raise
    # ValueError; the per-link guard degrades to skip rather than crashing the scan.
    _write(tmp_path / "docs/learned/index.md", "[x](bad\x00name.md)\n")
    assert scan_docs_richly(tmp_path) == DocFindings()


# --- the `cluster` frontmatter read (LearnedDoc) ----------------------------------------------


def test_cluster_declared_is_read(tmp_path: Path):
    _write(
        tmp_path / "docs/learned/workflow/a.md",
        "---\ntitle: T\nread_when: Cue.\ncluster: alpha\n---\nBody.\n",
    )
    (doc,) = read_learned_docs(tmp_path)
    assert doc.cluster == "alpha"


def test_cluster_absent_is_none(tmp_path: Path):
    _write(tmp_path / "docs/learned/workflow/a.md", "---\ntitle: T\nread_when: Cue.\n---\nBody.\n")
    (doc,) = read_learned_docs(tmp_path)
    assert doc.cluster is None
    assert doc.title == "T" and doc.read_when == "Cue."


def test_cluster_non_string_degrades_to_all_none_metadata(tmp_path: Path):
    # A non-string value fails the whole frontmatter model exactly like a bad `title`: the doc
    # degrades to all-None metadata (and surfaces as missing-frontmatter downstream).
    _write(
        tmp_path / "docs/learned/workflow/a.md",
        "---\ntitle: T\nread_when: Cue.\ncluster: [a, b]\n---\nBody.\n",
    )
    (doc,) = read_learned_docs(tmp_path)
    assert doc.title is None and doc.read_when is None and doc.cluster is None
