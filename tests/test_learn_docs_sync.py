"""The learned-docs navigation generator + checker (contracts.md §8.35)."""

from pathlib import Path

import pytest

from perk.learn.docs_scan import read_learned_docs
from perk.learn.docs_sync import (
    BEGIN_MARKER,
    CLUSTER_ROLLUP_MAX_CHARS,
    END_MARKER,
    READ_WHEN_MAX_CHARS,
    ClusterRegistry,
    InvalidClusterRegistry,
    SyncResult,
    check_docs,
    generate_catalog,
    generate_routing_block,
    load_cluster_registry,
    render_with_markers,
    scan_cues,
    sync_docs,
)

_APPEND_REL = ".pi/APPEND_SYSTEM.md"
_INDEX_REL = "docs/learned/index.md"
_CLUSTERS_REL = "docs/learned/clusters.yaml"


def _doc(
    root: Path,
    category: str,
    slug: str,
    *,
    title: str | None = "Title",
    read_when: str | None = "When you touch X.",
    cluster: str | None = None,
    body: str = "# Doc\n\nBody.\n",
) -> Path:
    path = root / "docs" / "learned" / category / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    front = "---\n"
    if title is not None:
        front += f"title: {title}\n"
    if read_when is not None:
        front += f"read_when: {read_when}\n"
    if cluster is not None:
        front += f"cluster: {cluster}\n"
    front += "---\n\n"
    path.write_text(front + body, encoding="utf-8")
    return path


def _registry_yaml(*defs: tuple[str, str]) -> str:
    """A well-formed clusters.yaml body from ``(id, rollup)`` pairs (file order preserved)."""
    lines = ["clusters:"]
    for cid, rollup in defs:
        lines.append(f"  - id: {cid}")
        lines.append(f'    rollup: "{rollup}"')
    return "\n".join(lines) + "\n"


def _write_registry(root: Path, text: str) -> Path:
    path = root / _CLUSTERS_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _load_valid(root: Path) -> ClusterRegistry:
    registry = load_cluster_registry(root)
    assert isinstance(registry, ClusterRegistry)
    return registry


def _sync_ok(root: Path, *, dry_run: bool = False) -> SyncResult:
    result = sync_docs(root, dry_run=dry_run)
    assert isinstance(result, SyncResult)
    return result


# --- generation -----------------------------------------------------------------------------------


def test_routing_line_and_catalog_row(tmp_path: Path):
    _doc(tmp_path, "workflow", "foo", title="Foo", read_when="When you touch foo.")
    docs = read_learned_docs(tmp_path)
    assert generate_routing_block(docs) == "- **workflow/foo** — When you touch foo."
    catalog = generate_catalog(docs)
    assert catalog.splitlines()[0] == "| Category | Doc | When to read |"
    assert (
        catalog.splitlines()[-1] == "| workflow | [foo.md](workflow/foo.md) | When you touch foo. |"
    )


def test_catalog_escapes_pipe_but_routing_does_not(tmp_path: Path):
    _doc(tmp_path, "toolchain", "biome", read_when="You hit `a | b` in the toolchain.")
    docs = read_learned_docs(tmp_path)
    # The table cell escapes `|`; the terse routing block (not a table) leaves it literal.
    assert "`a \\| b`" in generate_catalog(docs)
    assert "`a | b`" in generate_routing_block(docs)


def test_ordering_is_alphabetical_by_category_then_slug(tmp_path: Path):
    _doc(tmp_path, "workflow", "b")
    _doc(tmp_path, "workflow", "a")
    _doc(tmp_path, "pi", "z")
    _doc(tmp_path, "toolchain", "m")
    docs = read_learned_docs(tmp_path)
    assert [(d.category, d.slug) for d in docs] == [
        ("pi", "z"),
        ("toolchain", "m"),
        ("workflow", "a"),
        ("workflow", "b"),
    ]


def test_index_md_is_excluded_from_the_doc_set(tmp_path: Path):
    _doc(tmp_path, "workflow", "real")
    (tmp_path / "docs" / "learned" / "index.md").write_text(
        "# generated output\n", encoding="utf-8"
    )
    docs = read_learned_docs(tmp_path)
    assert [d.slug for d in docs] == ["real"]


# --- markers / bootstrap-vs-replace ---------------------------------------------------------------


def test_render_bootstrap_writes_preamble_and_markers():
    out = render_with_markers("", "REGION", "PREAMBLE\n\n")
    assert out == f"PREAMBLE\n\n{BEGIN_MARKER}\nREGION\n{END_MARKER}\n"


def test_render_replace_preserves_text_outside_markers():
    existing = f"MY PREAMBLE\n\n{BEGIN_MARKER}\nOLD\n{END_MARKER}\nMY FOOTER\n"
    out = render_with_markers(existing, "NEW", "DEFAULT\n\n")
    # The hand-editable preamble + footer survive; only the region is replaced; default unused.
    assert out == f"MY PREAMBLE\n\n{BEGIN_MARKER}\nNEW\n{END_MARKER}\nMY FOOTER\n"
    assert "DEFAULT" not in out


def test_sync_is_idempotent(tmp_path: Path):
    _doc(tmp_path, "workflow", "a")
    _doc(tmp_path, "pi", "b")
    first = _sync_ok(tmp_path)
    assert set(first.written) == {_APPEND_REL, _INDEX_REL}
    second = _sync_ok(tmp_path)
    assert second.written == ()
    assert set(second.unchanged) == {_APPEND_REL, _INDEX_REL}


def test_sync_dry_run_writes_nothing(tmp_path: Path):
    _doc(tmp_path, "workflow", "a")
    result = _sync_ok(tmp_path, dry_run=True)
    assert set(result.written) == {_APPEND_REL, _INDEX_REL}
    assert not (tmp_path / _APPEND_REL).exists()
    assert not (tmp_path / _INDEX_REL).exists()


def test_sync_preserves_a_hand_edited_preamble_across_a_doc_change(tmp_path: Path):
    _doc(tmp_path, "workflow", "a", read_when="First cue.")
    sync_docs(tmp_path, dry_run=False)
    append_path = tmp_path / _APPEND_REL
    # Hand-edit the preamble OUTSIDE the markers.
    text = append_path.read_text(encoding="utf-8")
    append_path.write_text("CUSTOM HEADER LINE\n" + text, encoding="utf-8")
    # Change a doc's frontmatter, re-sync.
    _doc(tmp_path, "workflow", "a", read_when="Second cue.")
    sync_docs(tmp_path, dry_run=False)
    updated = append_path.read_text(encoding="utf-8")
    assert updated.startswith("CUSTOM HEADER LINE\n")
    assert "Second cue." in updated and "First cue." not in updated


# --- checking -------------------------------------------------------------------------------------


def test_check_fresh_after_sync(tmp_path: Path):
    _doc(tmp_path, "workflow", "a")
    sync_docs(tmp_path, dry_run=False)
    report = check_docs(tmp_path)
    assert report.fresh is True
    assert report.stale_files == ()


def test_check_absent_markers_is_stale(tmp_path: Path):
    _doc(tmp_path, "workflow", "a")  # never synced → no markers exist
    report = check_docs(tmp_path)
    assert report.fresh is False
    assert set(report.stale_files) == {_APPEND_REL, _INDEX_REL}


def test_check_detects_freshness_drift_when_read_when_mutates(tmp_path: Path):
    _doc(tmp_path, "workflow", "a", read_when="Original.")
    sync_docs(tmp_path, dry_run=False)
    assert check_docs(tmp_path).fresh is True
    _doc(tmp_path, "workflow", "a", read_when="Mutated.")
    report = check_docs(tmp_path)
    assert report.fresh is False
    assert set(report.stale_files) == {_APPEND_REL, _INDEX_REL}


def test_check_missing_frontmatter(tmp_path: Path):
    _doc(tmp_path, "workflow", "ok")
    _doc(tmp_path, "workflow", "nofm", title="T", read_when=None)
    report = check_docs(tmp_path)
    assert report.missing_frontmatter == ("docs/learned/workflow/nofm.md",)


def test_check_source_code_block_threshold(tmp_path: Path):
    short = "```ts\nconst a = 1;\nconst b = 2;\nconst c = 3;\n```\n"
    long_body = "```ts\n" + "".join(f"const x{i} = {i};\n" for i in range(12)) + "```\n"
    data_block = "```json\n" + "".join(f'{{"k": {i}}}\n' for i in range(12)) + "```\n"
    _doc(tmp_path, "toolchain", "short", body=short)
    _doc(tmp_path, "toolchain", "long", body=long_body)
    _doc(tmp_path, "toolchain", "data", body=data_block)
    report = check_docs(tmp_path)
    flagged = {b.doc for b in report.source_code_blocks}
    assert flagged == {"docs/learned/toolchain/long.md"}
    block = report.source_code_blocks[0]
    assert block.language == "ts" and block.lines == 12


def test_check_reuses_duplicate_read_when(tmp_path: Path):
    _doc(tmp_path, "workflow", "a", read_when="Exactly the same cue.")
    _doc(tmp_path, "workflow", "b", read_when="Exactly the same cue.")
    report = check_docs(tmp_path)
    assert any(g.basis == "read_when" for g in report.duplicate_read_when)


def test_check_reuses_broken_link_and_stale_pointer(tmp_path: Path):
    (tmp_path / "perk" / "run").mkdir(parents=True)  # a dir → the .py pointer is a phantom
    _doc(
        tmp_path,
        "workflow",
        "a",
        body="See [gone](./missing.md) and `perk/run/launch.py` for context.\n",
    )
    report = check_docs(tmp_path)
    assert any(b.target == "./missing.md" for b in report.broken_doc_paths)
    assert any(p.pointer == "perk/run/launch.py" for p in report.stale_pointers)


# --- cue budget + hazards (gating) ----------------------------------------------------------------


def test_overlong_cue_flagged_at_201_but_not_200(tmp_path: Path):
    _doc(tmp_path, "workflow", "long", read_when="x" * (READ_WHEN_MAX_CHARS + 1))
    _doc(tmp_path, "workflow", "exact", read_when="x" * READ_WHEN_MAX_CHARS)
    docs = read_learned_docs(tmp_path)
    findings = scan_cues(tmp_path, docs)
    assert [(c.doc, c.length) for c in findings.overlong] == [
        ("docs/learned/workflow/long.md", READ_WHEN_MAX_CHARS + 1)
    ]
    assert findings.hazards == ()


def test_space_hash_hazard_and_the_silent_truncation_it_flags(tmp_path: Path):
    _doc(tmp_path, "workflow", "a", read_when="Fixes #123 the widget.")
    docs = read_learned_docs(tmp_path)
    # The parsed value is silently truncated at the ` #` (YAML comment start) — it measures short
    # and looks valid, which is exactly why the raw line must be scanned.
    assert docs[0].read_when == "Fixes"
    findings = scan_cues(tmp_path, docs)
    assert [(h.doc, h.hazard) for h in findings.hazards] == [
        ("docs/learned/workflow/a.md", "space-hash")
    ]


def test_colon_space_hazard_and_the_failed_parse_it_explains(tmp_path: Path):
    _doc(tmp_path, "workflow", "a", read_when="You hit: a thing.")
    docs = read_learned_docs(tmp_path)
    # The `: ` fails the WHOLE frontmatter parse — the doc lands in missing_frontmatter with no
    # clue about the cause; the hazard finding names it.
    assert docs[0].read_when is None
    findings = scan_cues(tmp_path, docs)
    assert [(h.doc, h.hazard) for h in findings.hazards] == [
        ("docs/learned/workflow/a.md", "colon-space")
    ]
    report = check_docs(tmp_path)
    assert "docs/learned/workflow/a.md" in report.missing_frontmatter


def test_quoted_scalar_is_the_sanctioned_escape_and_never_hazard_flagged(tmp_path: Path):
    _doc(tmp_path, "workflow", "a", read_when='"You hit: a thing"')
    docs = read_learned_docs(tmp_path)
    assert docs[0].read_when == "You hit: a thing"  # the quoted parse succeeds
    assert scan_cues(tmp_path, docs).hazards == ()


def test_block_scalar_cue_is_a_multiline_hazard(tmp_path: Path):
    _doc(tmp_path, "workflow", "a", read_when="|\n  Line one.\n  Line two.")
    docs = read_learned_docs(tmp_path)
    findings = scan_cues(tmp_path, docs)
    assert [(h.doc, h.hazard) for h in findings.hazards] == [
        ("docs/learned/workflow/a.md", "multiline")
    ]


def test_check_docs_surfaces_cue_findings(tmp_path: Path):
    _doc(tmp_path, "workflow", "long", read_when="x" * (READ_WHEN_MAX_CHARS + 5))
    _doc(tmp_path, "workflow", "hazard", read_when="Fixes #123 the widget.")
    report = check_docs(tmp_path)
    assert [(c.doc, c.length) for c in report.overlong_cues] == [
        ("docs/learned/workflow/long.md", READ_WHEN_MAX_CHARS + 5)
    ]
    assert [(h.doc, h.hazard) for h in report.cue_hazards] == [
        ("docs/learned/workflow/hazard.md", "space-hash")
    ]


def test_scan_cues_skips_an_unreadable_doc_without_raising(tmp_path: Path):
    _doc(tmp_path, "workflow", "real")
    binary = tmp_path / "docs" / "learned" / "workflow" / "blob.md"
    binary.write_bytes(b"\xff\xfe\x00\x01not utf-8")
    docs = read_learned_docs(tmp_path)
    findings = scan_cues(tmp_path, docs)
    assert findings.overlong == () and findings.hazards == ()


def test_check_never_raises_on_a_binary_doc(tmp_path: Path):
    _doc(tmp_path, "workflow", "real")
    binary = tmp_path / "docs" / "learned" / "workflow" / "blob.md"
    binary.write_bytes(b"\xff\xfe\x00\x01not utf-8")
    # Neither read nor check raises; the binary doc surfaces as missing-frontmatter.
    docs = read_learned_docs(tmp_path)
    assert any(d.slug == "blob" and d.read_when is None for d in docs)
    report = check_docs(tmp_path)
    assert "docs/learned/workflow/blob.md" in report.missing_frontmatter


# --- the cluster registry (loading) ---------------------------------------------------------------


def test_registry_absent_is_legacy_mode(tmp_path: Path):
    assert load_cluster_registry(tmp_path) is None


def test_registry_valid_preserves_file_order(tmp_path: Path):
    _write_registry(tmp_path, _registry_yaml(("zeta", "Z rollup."), ("alpha", "A rollup.")))
    registry = _load_valid(tmp_path)
    assert [(c.id, c.rollup) for c in registry.clusters] == [
        ("zeta", "Z rollup."),
        ("alpha", "A rollup."),
    ]


# Every invalid-registry class with the expected reason fragment; shared by the loader test AND
# the `sync_docs` write-safety test (a broken registry must refuse without touching artifacts).
_INVALID_REGISTRIES = [
    ("clusters: [\n", "YAML parse error"),  # unclosed flow sequence
    ("- not-a-mapping\n", "root is not a mapping"),
    ("clusters: not-a-list\n", "Input should be a valid tuple"),
    ("other: 1\n", "`clusters` is missing"),
    ("clusters: []\n", "`clusters` is empty"),
    ("clusters:\n  - just-a-string\n", "clusters.0"),  # entry not a mapping
    ('clusters:\n  - id: [a, b]\n    rollup: "R."\n', "clusters.0.id"),  # non-string id
    ('clusters:\n  - rollup: "R."\n', "clusters[0] is missing an id"),
    ('clusters:\n  - id: ""\n    rollup: "R."\n', "clusters[0] is missing an id"),
    ('clusters:\n  - id: Not-Kebab\n    rollup: "R."\n', "is not kebab-case"),
    # A double-quoted YAML scalar with a trailing LF: `match` + `$` would accept it and render a
    # newline inside the ambient line — `fullmatch` rejects it.
    ('clusters:\n  - id: "alpha\\n"\n    rollup: "R."\n', "is not kebab-case"),
    (
        'clusters:\n  - id: dup\n    rollup: "A."\n  - id: dup\n    rollup: "B."\n',
        "duplicate cluster id 'dup'",
    ),
    ("clusters:\n  - id: a\n", "('a') is missing a rollup"),
    ('clusters:\n  - id: a\n    rollup: ""\n', "('a') is missing a rollup"),
    ('clusters:\n  - id: a\n    rollup: "   "\n', "('a') is missing a rollup"),  # whitespace-only
    ('clusters:\n  - id: a\n    rollup: "one\\ntwo"\n', "rollup spans multiple lines"),
    # A carriage return is a line separator too (`splitlines`, not an LF-only check).
    ('clusters:\n  - id: a\n    rollup: "one\\rtwo"\n', "rollup spans multiple lines"),
]


@pytest.mark.parametrize(("text", "reason_fragment"), _INVALID_REGISTRIES)
def test_registry_invalid_classes_report_a_precise_reason(
    tmp_path: Path, text: str, reason_fragment: str
):
    _write_registry(tmp_path, text)
    registry = load_cluster_registry(tmp_path)
    assert isinstance(registry, InvalidClusterRegistry)
    assert _CLUSTERS_REL in registry.reason
    assert reason_fragment in registry.reason


def test_registry_non_utf8_is_invalid_not_legacy(tmp_path: Path):
    path = tmp_path / _CLUSTERS_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xfe not utf-8")
    registry = load_cluster_registry(tmp_path)
    assert isinstance(registry, InvalidClusterRegistry)
    assert "unreadable" in registry.reason


def test_registry_path_is_a_directory_is_invalid_not_legacy(tmp_path: Path):
    (tmp_path / _CLUSTERS_REL).mkdir(parents=True)
    registry = load_cluster_registry(tmp_path)
    assert isinstance(registry, InvalidClusterRegistry)
    assert "unreadable" in registry.reason


def test_registry_dangling_symlink_is_invalid_not_legacy(tmp_path: Path):
    path = tmp_path / _CLUSTERS_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(tmp_path / "gone.yaml")  # target never exists
    registry = load_cluster_registry(tmp_path)
    assert isinstance(registry, InvalidClusterRegistry)
    assert "dangling symlink" in registry.reason


# --- cluster-grained generation -------------------------------------------------------------------


def test_cluster_lines_render_in_registry_order_with_sorted_members(tmp_path: Path):
    _doc(tmp_path, "workflow", "b", cluster="beta")
    _doc(tmp_path, "pi", "z", cluster="beta")
    _doc(tmp_path, "workflow", "a", cluster="alpha")
    _write_registry(tmp_path, _registry_yaml(("beta", "B rollup."), ("alpha", "A rollup.")))
    docs = read_learned_docs(tmp_path)
    routing = generate_routing_block(docs, _load_valid(tmp_path))
    # Registry file order (beta before alpha), members sorted (category, slug), parens grammar.
    assert routing == (
        "- **beta** — B rollup. (pi/z, workflow/b)\n- **alpha** — A rollup. (workflow/a)"
    )


def test_empty_cluster_renders_without_parens(tmp_path: Path):
    _doc(tmp_path, "workflow", "a", cluster="alpha")
    _write_registry(tmp_path, _registry_yaml(("alpha", "A rollup."), ("hollow", "No members.")))
    docs = read_learned_docs(tmp_path)
    routing = generate_routing_block(docs, _load_valid(tmp_path))
    assert routing.splitlines()[1] == "- **hollow** — No members."


def test_unassigned_docs_render_trailing_per_doc_lines(tmp_path: Path):
    _doc(tmp_path, "workflow", "in", cluster="alpha", read_when="In-cluster cue.")
    _doc(tmp_path, "workflow", "missing", read_when="Missing cue.")
    _doc(tmp_path, "pi", "unknown", cluster="ghost", read_when="Unknown cue.")
    _write_registry(tmp_path, _registry_yaml(("alpha", "A rollup.")))
    docs = read_learned_docs(tmp_path)
    routing = generate_routing_block(docs, _load_valid(tmp_path))
    # Cluster lines first, then the unassigned docs as legacy per-doc lines in corpus order.
    assert routing == (
        "- **alpha** — A rollup. (workflow/in)\n"
        "- **pi/unknown** — Unknown cue.\n"
        "- **workflow/missing** — Missing cue."
    )


def test_legacy_mode_renders_per_doc_lines_even_with_cluster_frontmatter(tmp_path: Path):
    # No registry ⇒ byte-identical legacy rendering: per-doc block + 3-column catalog, the
    # declared `cluster` frontmatter ignored.
    _doc(tmp_path, "workflow", "foo", title="Foo", read_when="When you touch foo.", cluster="c1")
    docs = read_learned_docs(tmp_path)
    assert generate_routing_block(docs) == "- **workflow/foo** — When you touch foo."
    catalog = generate_catalog(docs)
    assert catalog.splitlines()[0] == "| Category | Doc | When to read |"
    assert (
        catalog.splitlines()[-1] == "| workflow | [foo.md](workflow/foo.md) | When you touch foo. |"
    )


def test_catalog_registry_mode_four_columns_and_cluster_pipe_escape(tmp_path: Path):
    _doc(tmp_path, "workflow", "a", read_when="Cue.", cluster="a|b")
    _doc(tmp_path, "workflow", "b", read_when="Cue.")
    _write_registry(tmp_path, _registry_yaml(("alpha", "A rollup.")))
    catalog = generate_catalog(read_learned_docs(tmp_path), _load_valid(tmp_path))
    lines = catalog.splitlines()
    assert lines[0] == "| Category | Doc | Cluster | When to read |"
    assert lines[1] == "|----------|-----|---------|-------------|"
    # A hostile declared value renders verbatim with `|` escaped; undeclared renders empty.
    assert lines[2] == "| workflow | [a.md](workflow/a.md) | a\\|b | Cue. |"
    assert lines[3] == "| workflow | [b.md](workflow/b.md) |  | Cue. |"


# --- sync + freshness in registry mode ------------------------------------------------------------


def test_sync_is_idempotent_in_registry_mode(tmp_path: Path):
    _doc(tmp_path, "workflow", "a", cluster="alpha")
    _write_registry(tmp_path, _registry_yaml(("alpha", "A rollup.")))
    first = _sync_ok(tmp_path)
    assert set(first.written) == {_APPEND_REL, _INDEX_REL}
    second = _sync_ok(tmp_path)
    assert second.written == ()
    assert set(second.unchanged) == {_APPEND_REL, _INDEX_REL}


def test_sync_invalid_registry_returns_refusal_and_writes_nothing(tmp_path: Path):
    _doc(tmp_path, "workflow", "a", cluster="alpha")
    _write_registry(tmp_path, "clusters: []\n")
    result = sync_docs(tmp_path, dry_run=False)
    assert isinstance(result, InvalidClusterRegistry)
    assert "`clusters` is empty" in result.reason
    assert not (tmp_path / _APPEND_REL).exists()
    assert not (tmp_path / _INDEX_REL).exists()


def test_sync_invalid_registry_never_regresses_a_committed_block(tmp_path: Path):
    # A converged registry-mode tree whose registry then breaks: sync refuses and the committed
    # cluster-grained artifacts stay byte-identical (no silent per-doc regression).
    _doc(tmp_path, "workflow", "a", cluster="alpha")
    _write_registry(tmp_path, _registry_yaml(("alpha", "A rollup.")))
    _sync_ok(tmp_path)
    before = (tmp_path / _APPEND_REL).read_text(encoding="utf-8")
    _write_registry(tmp_path, "clusters: [\n")
    result = sync_docs(tmp_path, dry_run=False)
    assert isinstance(result, InvalidClusterRegistry)
    assert (tmp_path / _APPEND_REL).read_text(encoding="utf-8") == before


@pytest.mark.parametrize(("text", "reason_fragment"), _INVALID_REGISTRIES)
def test_sync_refuses_each_invalid_class_and_leaves_artifacts_untouched(
    tmp_path: Path, text: str, reason_fragment: str
):
    # The write-safety guarantee across EVERY invalid class: a converged registry-mode tree whose
    # registry then breaks gets a refusal with the precise reason and byte-identical artifacts.
    _doc(tmp_path, "workflow", "a", cluster="alpha")
    _write_registry(tmp_path, _registry_yaml(("alpha", "A rollup.")))
    _sync_ok(tmp_path)
    before_append = (tmp_path / _APPEND_REL).read_text(encoding="utf-8")
    before_index = (tmp_path / _INDEX_REL).read_text(encoding="utf-8")
    _write_registry(tmp_path, text)
    result = sync_docs(tmp_path, dry_run=False)
    assert isinstance(result, InvalidClusterRegistry)
    assert reason_fragment in result.reason
    assert (tmp_path / _APPEND_REL).read_text(encoding="utf-8") == before_append
    assert (tmp_path / _INDEX_REL).read_text(encoding="utf-8") == before_index


def test_sync_unreadable_registry_refuses_and_leaves_artifacts_untouched(tmp_path: Path):
    _doc(tmp_path, "workflow", "a", cluster="alpha")
    _write_registry(tmp_path, _registry_yaml(("alpha", "A rollup.")))
    _sync_ok(tmp_path)
    before = (tmp_path / _APPEND_REL).read_text(encoding="utf-8")
    (tmp_path / _CLUSTERS_REL).write_bytes(b"\xff\xfe not utf-8")
    result = sync_docs(tmp_path, dry_run=False)
    assert isinstance(result, InvalidClusterRegistry)
    assert "unreadable" in result.reason
    assert (tmp_path / _APPEND_REL).read_text(encoding="utf-8") == before


def test_check_unreadable_registry_reports_registry_error(tmp_path: Path):
    _doc(tmp_path, "workflow", "a", cluster="alpha")
    (tmp_path / _CLUSTERS_REL).write_bytes(b"\xff\xfe not utf-8")
    report = check_docs(tmp_path)
    assert report.registry_error is not None
    assert "unreadable" in report.registry_error


def test_check_detects_freshness_drift_on_a_rollup_edit(tmp_path: Path):
    _doc(tmp_path, "workflow", "a", cluster="alpha")
    _write_registry(tmp_path, _registry_yaml(("alpha", "Original rollup.")))
    _sync_ok(tmp_path)
    assert check_docs(tmp_path).fresh is True
    _write_registry(tmp_path, _registry_yaml(("alpha", "Mutated rollup.")))
    report = check_docs(tmp_path)
    assert report.fresh is False
    # Only the routing block renders the rollup (the catalog cell carries the doc's declared id).
    assert report.stale_files == (_APPEND_REL,)


# --- the cluster gates (check_docs) ---------------------------------------------------------------


def test_check_registry_error_gates_and_skips_routing_freshness(tmp_path: Path):
    _doc(tmp_path, "workflow", "a", cluster="alpha")
    _write_registry(tmp_path, _registry_yaml(("alpha", "A rollup.")))
    _sync_ok(tmp_path)
    _write_registry(tmp_path, "clusters: not-a-list\n")
    report = check_docs(tmp_path)
    assert report.registry_error is not None
    assert "Input should be a valid tuple" in report.registry_error
    # Freshness of the routing/catalog comparison is skipped — the registry gate covers it.
    assert report.fresh is True and report.stale_files == ()
    assert report.cluster_issues == () and report.empty_clusters == ()


def test_check_cluster_issues_missing_and_unknown(tmp_path: Path):
    _doc(tmp_path, "workflow", "ok", cluster="alpha")
    _doc(tmp_path, "workflow", "bare")
    _doc(tmp_path, "pi", "ghosted", cluster="ghost")
    _write_registry(tmp_path, _registry_yaml(("alpha", "A rollup.")))
    report = check_docs(tmp_path)
    assert [(i.doc, i.cluster, i.problem) for i in report.cluster_issues] == [
        ("docs/learned/pi/ghosted.md", "ghost", "unknown"),
        ("docs/learned/workflow/bare.md", None, "missing"),
    ]


def test_check_empty_clusters_gate(tmp_path: Path):
    _doc(tmp_path, "workflow", "a", cluster="alpha")
    _write_registry(tmp_path, _registry_yaml(("alpha", "A rollup."), ("hollow", "No members.")))
    report = check_docs(tmp_path)
    assert report.empty_clusters == ("hollow",)


def test_check_overlong_rollup_boundary_160_clean_161_flagged(tmp_path: Path):
    _doc(tmp_path, "workflow", "a", cluster="exact")
    _doc(tmp_path, "workflow", "b", cluster="over")
    _write_registry(
        tmp_path,
        _registry_yaml(
            ("exact", "x" * CLUSTER_ROLLUP_MAX_CHARS),
            ("over", "x" * (CLUSTER_ROLLUP_MAX_CHARS + 1)),
        ),
    )
    report = check_docs(tmp_path)
    assert [(r.cluster, r.length) for r in report.overlong_rollups] == [
        ("over", CLUSTER_ROLLUP_MAX_CHARS + 1)
    ]


def test_check_legacy_mode_has_no_cluster_findings(tmp_path: Path):
    _doc(tmp_path, "workflow", "a")  # no registry, no cluster frontmatter
    report = check_docs(tmp_path)
    assert report.registry_error is None
    assert report.cluster_issues == ()
    assert report.empty_clusters == ()
    assert report.overlong_rollups == ()


def test_bootstrap_preamble_matches_the_rendering_mode(tmp_path: Path):
    # A legacy (no-registry) bootstrap must not self-document a registry it doesn't have; a
    # registry-mode bootstrap describes the two-tier grain.
    _doc(tmp_path, "workflow", "a")
    _sync_ok(tmp_path)
    legacy = (tmp_path / _APPEND_REL).read_text(encoding="utf-8")
    assert "clusters.yaml" not in legacy
    assert "one terse routing line per durable doc" in legacy
    legacy_index = (tmp_path / _INDEX_REL).read_text(encoding="utf-8")
    assert "clusters.yaml" not in legacy_index

    clustered_root = tmp_path / "clustered"
    _doc(clustered_root, "workflow", "a", cluster="alpha")
    _write_registry(clustered_root, _registry_yaml(("alpha", "A rollup.")))
    _sync_ok(clustered_root)
    clustered = (clustered_root / _APPEND_REL).read_text(encoding="utf-8")
    assert "docs/learned/clusters.yaml" in clustered
    assert "one line per cluster — id + rollup cue + member" in clustered
    clustered_index = (clustered_root / _INDEX_REL).read_text(encoding="utf-8")
    assert "docs/learned/clusters.yaml" in clustered_index
