"""The learned-docs navigation generator + checker (contracts.md §8.35)."""

from pathlib import Path

from perk.learn.docs_scan import read_learned_docs
from perk.learn.docs_sync import (
    BEGIN_MARKER,
    END_MARKER,
    READ_WHEN_MAX_CHARS,
    check_docs,
    generate_catalog,
    generate_routing_block,
    render_with_markers,
    scan_cues,
    sync_docs,
)

_APPEND_REL = ".pi/APPEND_SYSTEM.md"
_INDEX_REL = "docs/learned/index.md"


def _doc(
    root: Path,
    category: str,
    slug: str,
    *,
    title: str | None = "Title",
    read_when: str | None = "When you touch X.",
    body: str = "# Doc\n\nBody.\n",
) -> Path:
    path = root / "docs" / "learned" / category / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    front = "---\n"
    if title is not None:
        front += f"title: {title}\n"
    if read_when is not None:
        front += f"read_when: {read_when}\n"
    front += "---\n\n"
    path.write_text(front + body, encoding="utf-8")
    return path


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
    first = sync_docs(tmp_path, dry_run=False)
    assert set(first.written) == {_APPEND_REL, _INDEX_REL}
    second = sync_docs(tmp_path, dry_run=False)
    assert second.written == ()
    assert set(second.unchanged) == {_APPEND_REL, _INDEX_REL}


def test_sync_dry_run_writes_nothing(tmp_path: Path):
    _doc(tmp_path, "workflow", "a")
    result = sync_docs(tmp_path, dry_run=True)
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
