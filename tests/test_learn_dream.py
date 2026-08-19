"""The gather core for `perk learn dream` (resolution, cluster lanes, findings, manifest)."""

import json
import os
from pathlib import Path

import pytest

from perk.cli.ensure import UserFacingCliError
from perk.learn.docs_scan import LearnedDoc
from perk.learn.docs_sync import ClusterDef, ClusterRegistry
from perk.learn.dream import (
    DREAM_MANIFEST_FILENAME,
    DREAM_MANIFEST_SCHEMA_VERSION,
    DreamLane,
    gather_dream,
    partition_dream_lanes,
    render_manifest,
    resolve_dream_docs,
    write_manifest,
)
from perk.learn.harvest import partition_lanes
from perk.state import cache


def _doc(
    root: Path,
    category: str,
    slug: str,
    *,
    cluster: str | None = None,
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
    if cluster is not None:
        front += f"cluster: {cluster}\n"
    front += "---\n\n"
    path.write_text(front + body, encoding="utf-8")
    return path


def _registry(root: Path, clusters: list[tuple[str, str]]) -> Path:
    path = root / "docs" / "learned" / "clusters.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["clusters:"]
    for cluster_id, rollup in clusters:
        lines.append(f"  - id: {cluster_id}")
        lines.append(f"    rollup: {rollup}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _paths(docs: tuple[LearnedDoc, ...]) -> list[str]:
    return [d.path for d in docs]


def _ld(category: str, slug: str, *, cluster: str | None = None) -> LearnedDoc:
    parent = "docs/learned" if category == "." else f"docs/learned/{category}"
    return LearnedDoc(
        category=category,
        slug=slug,
        path=f"{parent}/{slug}.md",
        title=None,
        read_when=None,
        cluster=cluster,
    )


# --- resolution -----------------------------------------------------------------------------------


def test_empty_corpus_is_no_learned_docs(tmp_path: Path):
    with pytest.raises(UserFacingCliError) as exc_info:
        resolve_dream_docs(tmp_path)
    assert exc_info.value.error_type == "no_learned_docs"


def test_symlinked_corpus_root_outside_repo_is_refused(tmp_path: Path):
    repo = tmp_path / "repo"
    outside = tmp_path / "outside"
    _doc(outside, "workflow", "exfil", cluster="wf")
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "learned").symlink_to(outside / "docs" / "learned")

    with pytest.raises(UserFacingCliError) as exc_info:
        resolve_dream_docs(repo)
    assert exc_info.value.error_type == "invalid_input"
    assert "outside the repository" in str(exc_info.value)


def test_escaping_symlink_doc_is_refused_naming_the_doc(tmp_path: Path):
    """Dream REFUSES an escaping doc where harvest silently filters it — a complete-corpus
    audit never narrows the corpus."""
    _doc(tmp_path, "workflow", "real", cluster="wf")
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside\n", encoding="utf-8")
    escaped = tmp_path / "docs" / "learned" / "workflow" / "escaped.md"
    escaped.symlink_to(outside)

    with pytest.raises(UserFacingCliError) as exc_info:
        resolve_dream_docs(tmp_path)
    assert exc_info.value.error_type == "invalid_input"
    assert "docs/learned/workflow/escaped.md" in str(exc_info.value)


def test_resolution_returns_full_corpus_pairs_in_corpus_order(tmp_path: Path):
    a = _doc(tmp_path, "workflow", "a", cluster="wf")
    z = _doc(tmp_path, "toolchain", "z", cluster="tc")
    pairs = resolve_dream_docs(tmp_path)
    assert [(doc.path, resolved) for doc, resolved in pairs] == [
        ("docs/learned/toolchain/z.md", z.resolve()),
        ("docs/learned/workflow/a.md", a.resolve()),
    ]


# --- partition (registry mode) --------------------------------------------------------------------


def test_lanes_follow_registry_file_order_not_sorted_ids():
    registry = ClusterRegistry(
        clusters=(
            ClusterDef(id="zeta", rollup="Zeta rollup."),
            ClusterDef(id="alpha", rollup="Alpha rollup."),
        )
    )
    docs = [_ld("workflow", "a", cluster="alpha"), _ld("workflow", "b", cluster="zeta")]
    lanes = partition_dream_lanes(docs, registry)
    assert [lane.id for lane in lanes] == ["zeta-1", "alpha-1"]
    assert [lane.rollup for lane in lanes] == ["Zeta rollup.", "Alpha rollup."]
    assert _paths(lanes[0].docs) == ["docs/learned/workflow/b.md"]
    assert _paths(lanes[1].docs) == ["docs/learned/workflow/a.md"]


def test_over_cap_cluster_chunks_with_same_rollup_on_every_chunk():
    registry = ClusterRegistry(clusters=(ClusterDef(id="alpha", rollup="Alpha rollup."),))
    docs = [_ld("workflow", f"d{n}", cluster="alpha") for n in range(1, 10)]
    lanes = partition_dream_lanes(docs, registry)
    assert [lane.id for lane in lanes] == ["alpha-1", "alpha-2"]
    assert [lane.rollup for lane in lanes] == ["Alpha rollup.", "Alpha rollup."]
    assert _paths(lanes[0].docs) == [f"docs/learned/workflow/d{n}.md" for n in range(1, 9)]
    assert _paths(lanes[1].docs) == ["docs/learned/workflow/d9.md"]


def test_empty_cluster_emits_no_lane():
    registry = ClusterRegistry(
        clusters=(
            ClusterDef(id="alpha", rollup="Alpha rollup."),
            ClusterDef(id="spare", rollup="No members."),
        )
    )
    lanes = partition_dream_lanes([_ld("workflow", "a", cluster="alpha")], registry)
    assert [lane.id for lane in lanes] == ["alpha-1"]


def test_partition_sorts_shuffled_input_across_the_chunk_boundary():
    # Direct LearnedDoc input, deliberately jumbled — the partition must do its own path sort
    # (never lean on resolver order). The nested workflow/sub docs make path order differ from
    # the input order: path-sorting places sub/a + sub/b before z, pushing z over the eight-doc
    # lane boundary into wf-2 (the pipeline-fed-suite lesson).
    registry = ClusterRegistry(clusters=(ClusterDef(id="wf", rollup="Workflow rollup."),))
    shuffled = [
        _ld("workflow", "z", cluster="wf"),
        _ld("workflow/sub", "b", cluster="wf"),
        _ld("workflow", "e", cluster="wf"),
        _ld("workflow", "c", cluster="wf"),
        _ld("workflow", "h", cluster="wf"),
        _ld("workflow/sub", "a", cluster="wf"),
        _ld("workflow", "f", cluster="wf"),
        _ld("workflow", "d", cluster="wf"),
        _ld("workflow", "g", cluster="wf"),
    ]
    lanes = partition_dream_lanes(shuffled, registry)
    assert [lane.id for lane in lanes] == ["wf-1", "wf-2"]
    assert _paths(lanes[0].docs) == [
        "docs/learned/workflow/c.md",
        "docs/learned/workflow/d.md",
        "docs/learned/workflow/e.md",
        "docs/learned/workflow/f.md",
        "docs/learned/workflow/g.md",
        "docs/learned/workflow/h.md",
        "docs/learned/workflow/sub/a.md",
        "docs/learned/workflow/sub/b.md",
    ]
    assert _paths(lanes[1].docs) == ["docs/learned/workflow/z.md"]


# --- refusals -------------------------------------------------------------------------------------


def test_missing_cluster_frontmatter_is_incomplete_registry(tmp_path: Path):
    _registry(tmp_path, [("wf", "Workflow rollup.")])
    _doc(tmp_path, "workflow", "a", cluster="wf")
    _doc(tmp_path, "workflow", "b")  # no cluster declared
    with pytest.raises(UserFacingCliError) as exc_info:
        gather_dream(tmp_path)
    assert exc_info.value.error_type == "incomplete_registry"
    assert "docs/learned/workflow/b.md" in str(exc_info.value)


def test_unknown_cluster_id_is_incomplete_registry():
    registry = ClusterRegistry(clusters=(ClusterDef(id="wf", rollup="Workflow rollup."),))
    docs = [_ld("workflow", "a", cluster="wf"), _ld("workflow", "b", cluster="nope")]
    with pytest.raises(UserFacingCliError) as exc_info:
        partition_dream_lanes(docs, registry)
    assert exc_info.value.error_type == "incomplete_registry"
    assert "docs/learned/workflow/b.md" in str(exc_info.value)


def test_invalid_registry_is_refused_with_loader_reason(tmp_path: Path):
    # ONE representative invalid case (malformed YAML) — the loader's own refusal matrix is
    # exhaustively covered in tests/test_learn_docs_sync.py.
    _doc(tmp_path, "workflow", "a", cluster="wf")
    (tmp_path / "docs" / "learned" / "clusters.yaml").write_text("clusters: [\n", encoding="utf-8")
    with pytest.raises(UserFacingCliError) as exc_info:
        gather_dream(tmp_path)
    assert exc_info.value.error_type == "invalid_registry"
    assert "YAML parse error" in str(exc_info.value)


def test_absent_registry_falls_back_to_category_lanes(tmp_path: Path):
    _doc(tmp_path, "workflow", "a")
    _doc(tmp_path, "workflow/sub", "x")
    _doc(tmp_path, "toolchain", "z")
    gather = gather_dream(tmp_path)
    assert gather.registry_mode == "categories"
    expected = partition_lanes(gather.docs)
    assert gather.lanes == tuple(
        DreamLane(id=lane.id, rollup=None, docs=lane.docs) for lane in expected
    )
    assert all(lane.rollup is None for lane in gather.lanes)


# --- gather + findings ----------------------------------------------------------------------------


def test_gather_registry_mode_counts_sizes_and_findings(tmp_path: Path):
    _registry(tmp_path, [("wf", "Workflow rollup."), ("spare", "No members.")])
    a = _doc(
        tmp_path,
        "workflow",
        "a",
        cluster="wf",
        read_when="When A.",
        body="# A\n\n`perk/nonexistent_module.py::gone` and [gone](../missing-target.md).\n",
    )
    _doc(tmp_path, "workflow", "b", cluster="wf", read_when="Same cue.")
    _doc(tmp_path, "workflow", "c", cluster="wf", read_when="Same cue.")
    # Frontmatter present (cluster only) — title/read_when None → missing_frontmatter.
    d = tmp_path / "docs" / "learned" / "workflow" / "d.md"
    d.write_text("---\ncluster: wf\n---\n\n# D\n", encoding="utf-8")
    # A user-doc-owned finding must NOT appear (owner-doc filter).
    user_doc = tmp_path / "docs" / "user-docs" / "x.md"
    user_doc.parent.mkdir(parents=True, exist_ok=True)
    user_doc.write_text("# X\n\n[gone](missing.md)\n", encoding="utf-8")

    gather = gather_dream(tmp_path)
    assert gather.registry_mode == "clusters"
    assert gather.doc_count == 4
    assert [lane.id for lane in gather.lanes] == ["wf-1"]
    assert gather.lanes[0].rollup == "Workflow rollup."
    assert gather.sizes["docs/learned/workflow/a.md"] == len(a.read_bytes())
    assert gather.total_bytes == sum(gather.sizes.values())

    findings = gather.findings
    assert [(p.doc, p.pointer, p.reason) for p in findings.stale_pointers] == [
        ("docs/learned/workflow/a.md", "perk/nonexistent_module.py::gone", "missing-file")
    ]
    # The broken target is OUT of corpus — kept anyway: filtering is owner-doc-only (the
    # broken target IS the finding), and the user-doc-owned row is dropped.
    assert [(b.doc, b.target) for b in findings.broken_doc_paths] == [
        ("docs/learned/workflow/a.md", "../missing-target.md")
    ]
    assert [(g.key, g.docs) for g in findings.duplicate_cues] == [
        ("same cue.", ("docs/learned/workflow/b.md", "docs/learned/workflow/c.md"))
    ]
    assert findings.missing_frontmatter == ("docs/learned/workflow/d.md",)
    assert findings.empty_clusters == ("spare",)
    assert findings.distillation_issues == ()
    assert findings.source_code_blocks == ()
    assert findings.overlong_cues == ()
    assert findings.cue_hazards == ()


def test_gather_category_fallback_has_no_empty_clusters(tmp_path: Path):
    _doc(tmp_path, "workflow", "a")
    gather = gather_dream(tmp_path)
    assert gather.registry_mode == "categories"
    assert gather.findings.empty_clusters == ()


# --- manifest -------------------------------------------------------------------------------------


def test_render_manifest_exact_shape_and_null_carriage(tmp_path: Path):
    _doc(tmp_path, "workflow", "a", title=None, read_when=None, body="# A\n")
    gather = gather_dream(tmp_path)  # absent registry → category fallback, rollup null
    rendered = render_manifest(gather, commit_sha="abc123")
    size = (tmp_path / "docs" / "learned" / "workflow" / "a.md").stat().st_size
    assert json.loads(rendered) == {
        "schema_version": DREAM_MANIFEST_SCHEMA_VERSION,
        "commit_sha": "abc123",
        "registry_mode": "categories",
        "doc_count": 1,
        "total_bytes": size,
        "findings": {
            "structural": {
                "stale_pointers": [],
                "broken_doc_paths": [],
                "duplicate_cues": [],
                "missing_frontmatter": ["docs/learned/workflow/a.md"],
            },
            "advisory": {
                "distillation_issues": [],
                "source_code_blocks": [],
                "overlong_cues": [],
                "cue_hazards": [],
                "empty_clusters": [],
            },
        },
        "lanes": [
            {
                "id": "workflow-1",
                "rollup": None,
                "docs": [
                    {
                        "path": "docs/learned/workflow/a.md",
                        "title": None,
                        "read_when": None,
                        "cluster": None,
                        "bytes": size,
                    }
                ],
            }
        ],
    }
    assert DREAM_MANIFEST_SCHEMA_VERSION == "1"


def test_render_manifest_is_byte_deterministic(tmp_path: Path):
    _registry(tmp_path, [("wf", "Workflow rollup.")])
    _doc(tmp_path, "workflow", "a", cluster="wf")
    _doc(tmp_path, "workflow", "b", cluster="wf")
    first = render_manifest(gather_dream(tmp_path), commit_sha="deadbeef")
    second = render_manifest(gather_dream(tmp_path), commit_sha="deadbeef")
    assert first == second


def test_manifest_total_bytes_is_sum_of_per_doc_bytes(tmp_path: Path):
    _registry(tmp_path, [("wf", "Workflow rollup.")])
    _doc(tmp_path, "workflow", "a", cluster="wf", body="# A\n\nLonger body text.\n")
    _doc(tmp_path, "workflow", "b", cluster="wf")
    payload = json.loads(render_manifest(gather_dream(tmp_path), commit_sha="x"))
    per_doc = [doc["bytes"] for lane in payload["lanes"] for doc in lane["docs"]]
    assert payload["total_bytes"] == sum(per_doc)
    assert payload["doc_count"] == len(per_doc) == 2


# --- writer ---------------------------------------------------------------------------------------


def test_write_manifest_writes_run_scoped_scratch(tmp_path: Path):
    _doc(tmp_path, "workflow", "a")
    gather = gather_dream(tmp_path)
    path = write_manifest(tmp_path, "run-1", gather, commit_sha="deadbeef")
    assert path == cache.run_scratch_dir(tmp_path, "run-1") / DREAM_MANIFEST_FILENAME
    assert path.as_posix().endswith(".perk/workflow/scratch/runs/run-1/dream-manifest.json")
    content = path.read_text(encoding="utf-8")
    assert content == render_manifest(gather, commit_sha="deadbeef")
    assert content.endswith("\n")


@pytest.mark.skipif(os.geteuid() == 0, reason="permission bits are advisory as root")
def test_unreadable_doc_bytes_is_invalid_input(tmp_path: Path):
    _doc(tmp_path, "workflow", "a")
    sealed = _doc(tmp_path, "workflow", "b")
    sealed.chmod(0o000)
    try:
        with pytest.raises(UserFacingCliError) as exc_info:
            gather_dream(tmp_path)
        assert exc_info.value.error_type == "invalid_input"
        assert "docs/learned/workflow/b.md" in str(exc_info.value)
    finally:
        sealed.chmod(0o644)
