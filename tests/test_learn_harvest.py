"""The gather/partition core for `perk learn harvest` (resolution, lanes, manifest)."""

import json
from pathlib import Path

import pytest

from perk.cli.ensure import UserFacingCliError
from perk.learn.docs_scan import LearnedDoc
from perk.learn.harvest import (
    MANIFEST_FILENAME,
    MANIFEST_SCHEMA_VERSION,
    MAX_LANE_DOCS,
    HarvestLane,
    partition_lanes,
    render_manifest,
    resolve_harvest_docs,
    write_manifest,
)
from perk.state import cache


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


def _paths(docs: tuple[LearnedDoc, ...]) -> list[str]:
    return [d.path for d in docs]


# --- resolution -----------------------------------------------------------------------------------


def test_no_targets_selects_full_corpus_in_order(tmp_path: Path):
    _doc(tmp_path, "workflow", "b")
    _doc(tmp_path, "toolchain", "z")
    _doc(tmp_path, "workflow", "a")
    docs = resolve_harvest_docs(tmp_path, ())
    assert _paths(docs) == [
        "docs/learned/toolchain/z.md",
        "docs/learned/workflow/a.md",
        "docs/learned/workflow/b.md",
    ]


def test_relative_file_target_selects_exactly_that_doc(tmp_path: Path):
    _doc(tmp_path, "workflow", "a")
    _doc(tmp_path, "workflow", "b")
    docs = resolve_harvest_docs(tmp_path, ("docs/learned/workflow/a.md",))
    assert _paths(docs) == ["docs/learned/workflow/a.md"]


def test_directory_target_selects_recursively(tmp_path: Path):
    _doc(tmp_path, "workflow", "a")
    _doc(tmp_path, "workflow/sub", "x")
    _doc(tmp_path, "toolchain", "z")
    docs = resolve_harvest_docs(tmp_path, ("docs/learned/workflow",))
    assert _paths(docs) == ["docs/learned/workflow/a.md", "docs/learned/workflow/sub/x.md"]
    # docs/learned itself as a target == the no-target selection.
    assert resolve_harvest_docs(tmp_path, ("docs/learned",)) == resolve_harvest_docs(tmp_path, ())


def test_absolute_target_works(tmp_path: Path):
    path = _doc(tmp_path, "workflow", "a")
    _doc(tmp_path, "workflow", "b")
    docs = resolve_harvest_docs(tmp_path, (str(path),))
    assert _paths(docs) == ["docs/learned/workflow/a.md"]


def test_overlapping_targets_union_deduped_in_corpus_order(tmp_path: Path):
    _doc(tmp_path, "workflow", "a")
    _doc(tmp_path, "workflow", "b")
    docs = resolve_harvest_docs(tmp_path, ("docs/learned/workflow/b.md", "docs/learned/workflow"))
    assert _paths(docs) == ["docs/learned/workflow/a.md", "docs/learned/workflow/b.md"]


def test_target_outside_docs_learned_is_invalid_from(tmp_path: Path):
    _doc(tmp_path, "workflow", "a")
    outside = tmp_path / "docs" / "user-docs" / "x.md"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("# X\n", encoding="utf-8")
    with pytest.raises(UserFacingCliError) as exc_info:
        resolve_harvest_docs(tmp_path, ("docs/user-docs/x.md",))
    assert exc_info.value.error_type == "invalid_from"
    with pytest.raises(UserFacingCliError) as exc_info:
        resolve_harvest_docs(tmp_path, ("docs/learned/../user-docs/x.md",))
    assert exc_info.value.error_type == "invalid_from"


def test_nonexistent_contained_target_is_invalid_from(tmp_path: Path):
    _doc(tmp_path, "workflow", "a")
    with pytest.raises(UserFacingCliError) as exc_info:
        resolve_harvest_docs(tmp_path, ("docs/learned/missing.md",))
    assert exc_info.value.error_type == "invalid_from"


def test_from_symlink_escaping_tree_is_invalid_from(tmp_path: Path):
    _doc(tmp_path, "workflow", "a")
    elsewhere = tmp_path / "elsewhere.md"
    elsewhere.write_text("# Elsewhere\n", encoding="utf-8")
    link = tmp_path / "docs" / "learned" / "link.md"
    link.symlink_to(elsewhere)
    with pytest.raises(UserFacingCliError) as exc_info:
        resolve_harvest_docs(tmp_path, ("docs/learned/link.md",))
    assert exc_info.value.error_type == "invalid_from"


def test_index_md_target_selects_nothing(tmp_path: Path):
    _doc(tmp_path, "workflow", "a")
    index = tmp_path / "docs" / "learned" / "index.md"
    index.write_text("# Index\n", encoding="utf-8")
    with pytest.raises(UserFacingCliError) as exc_info:
        resolve_harvest_docs(tmp_path, ("docs/learned/index.md",))
    assert exc_info.value.error_type == "no_harvest_docs"


def test_empty_corpus_is_no_harvest_docs(tmp_path: Path):
    with pytest.raises(UserFacingCliError) as exc_info:
        resolve_harvest_docs(tmp_path, ())
    assert exc_info.value.error_type == "no_harvest_docs"


def test_corpus_symlink_containment(tmp_path: Path):
    real = _doc(tmp_path, "workflow", "real")
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside\n", encoding="utf-8")
    escaped = tmp_path / "docs" / "learned" / "workflow" / "escaped.md"
    escaped.symlink_to(outside)
    inside_link = tmp_path / "docs" / "learned" / "workflow" / "linked.md"
    inside_link.symlink_to(real)

    default = resolve_harvest_docs(tmp_path, ())
    explicit = resolve_harvest_docs(tmp_path, ("docs/learned",))
    assert default == explicit
    assert _paths(default) == [
        "docs/learned/workflow/linked.md",
        "docs/learned/workflow/real.md",
    ]


# --- partition ------------------------------------------------------------------------------------


def test_single_category_within_cap_is_one_lane(tmp_path: Path):
    for slug in ("a", "b", "c"):
        _doc(tmp_path, "workflow", slug)
    lanes = partition_lanes(resolve_harvest_docs(tmp_path, ()))
    assert [lane.id for lane in lanes] == ["workflow-1"]
    assert _paths(lanes[0].docs) == [f"docs/learned/workflow/{s}.md" for s in ("a", "b", "c")]


def test_single_category_over_cap_splits_at_eight(tmp_path: Path):
    for n in range(1, 10):
        _doc(tmp_path, "workflow", f"d{n}")
    lanes = partition_lanes(resolve_harvest_docs(tmp_path, ()))
    assert [lane.id for lane in lanes] == ["workflow-1", "workflow-2"]
    assert _paths(lanes[0].docs) == [f"docs/learned/workflow/d{n}.md" for n in range(1, 9)]
    assert _paths(lanes[1].docs) == ["docs/learned/workflow/d9.md"]


def test_multiple_categories_sorted_with_per_group_numbering(tmp_path: Path):
    _doc(tmp_path, "workflow", "a")
    _doc(tmp_path, "toolchain", "z")
    lanes = partition_lanes(resolve_harvest_docs(tmp_path, ()))
    assert [lane.id for lane in lanes] == ["toolchain-1", "workflow-1"]
    assert _paths(lanes[0].docs) == ["docs/learned/toolchain/z.md"]
    assert _paths(lanes[1].docs) == ["docs/learned/workflow/a.md"]


def test_nested_category_groups_under_first_component(tmp_path: Path):
    _doc(tmp_path, "workflow/sub", "x")
    lanes = partition_lanes(resolve_harvest_docs(tmp_path, ()))
    assert [lane.id for lane in lanes] == ["workflow-1"]
    assert _paths(lanes[0].docs) == ["docs/learned/workflow/sub/x.md"]


def test_top_level_doc_groups_under_root(tmp_path: Path):
    top = tmp_path / "docs" / "learned" / "x.md"
    top.parent.mkdir(parents=True, exist_ok=True)
    top.write_text("---\ntitle: X\nread_when: When.\n---\n\n# X\n", encoding="utf-8")
    lanes = partition_lanes(resolve_harvest_docs(tmp_path, ()))
    assert [lane.id for lane in lanes] == ["root-1"]
    assert _paths(lanes[0].docs) == ["docs/learned/x.md"]


def test_root_category_and_top_level_doc_co_group(tmp_path: Path):
    _doc(tmp_path, "root", "a")
    top = tmp_path / "docs" / "learned" / "b.md"
    top.write_text("---\ntitle: B\nread_when: When.\n---\n\n# B\n", encoding="utf-8")
    lanes = partition_lanes(resolve_harvest_docs(tmp_path, ()))
    assert [lane.id for lane in lanes] == ["root-1"]
    assert _paths(lanes[0].docs) == ["docs/learned/b.md", "docs/learned/root/a.md"]


def test_max_lane_docs_pinned():
    assert MAX_LANE_DOCS == 8


# --- manifest -------------------------------------------------------------------------------------


def test_render_manifest_exact_shape():
    lanes = (
        HarvestLane(
            id="workflow-1",
            docs=(
                LearnedDoc(
                    category="workflow",
                    slug="a",
                    path="docs/learned/workflow/a.md",
                    title="A",
                    read_when="When A.",
                ),
                LearnedDoc(
                    category="workflow",
                    slug="b",
                    path="docs/learned/workflow/b.md",
                    title=None,
                    read_when=None,
                ),
            ),
        ),
    )
    rendered = render_manifest(lanes, commit_sha="abc123")
    assert json.loads(rendered) == {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "commit_sha": "abc123",
        "lanes": [
            {
                "id": "workflow-1",
                "docs": [
                    {"path": "docs/learned/workflow/a.md", "title": "A", "read_when": "When A."},
                    {"path": "docs/learned/workflow/b.md", "title": None, "read_when": None},
                ],
            }
        ],
    }
    assert MANIFEST_SCHEMA_VERSION == "1"


def test_write_manifest_writes_run_scoped_scratch(tmp_path: Path):
    _doc(tmp_path, "workflow", "a")
    lanes = partition_lanes(resolve_harvest_docs(tmp_path, ()))
    path = write_manifest(tmp_path, "run-1", lanes, commit_sha="deadbeef")
    assert path == cache.run_scratch_dir(tmp_path, "run-1") / MANIFEST_FILENAME
    content = path.read_text(encoding="utf-8")
    assert content == render_manifest(lanes, commit_sha="deadbeef")
    assert content.endswith("\n")
