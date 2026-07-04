"""The rich, deterministic, advisory docs scan (contracts.md §8.35, node 5.1)."""

from pathlib import Path

from perk.learn.docs_scan import (
    BrokenDocPath,
    DocFindings,
    DuplicateGroup,
    StalePointer,
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
