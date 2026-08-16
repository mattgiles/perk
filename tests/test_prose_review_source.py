"""The seeded whole-file SourceAdapter: containment, membership, text-only decode."""

from pathlib import Path

import pytest
from perk_dev.prose_map.catalog import build_catalog
from perk_dev.prose_map.models import Candidate, RoutedUnit
from perk_dev.prose_review import source_adapter
from perk_dev.prose_review.catalog import CatalogSnapshot
from perk_dev.prose_review.source_adapter import (
    FocusedSource,
    ResolvedRange,
    SourceDiagnostic,
    SourceExtraction,
    SourceRange,
    SourceReadError,
    UnresolvedRange,
    read_source,
    read_unit_file,
    read_whole_file,
    source_adapter_for,
)

ROOT = Path(__file__).parents[1]


@pytest.fixture(scope="module")
def snapshot() -> CatalogSnapshot:
    return CatalogSnapshot.from_catalog(build_catalog(ROOT))


def _unit(path: str) -> RoutedUnit:
    """A directly-constructed routed unit pointing at an arbitrary candidate path."""
    return RoutedUnit(
        candidate=Candidate(
            id=f"markdown:{path}",
            kind="markdown",
            path=path,
            selector="markdown-doc",
            fragments=(),
        ),
        capability="foundation",
        audience="both",
        role="context",
    )


def test_read_whole_file_returns_the_exact_decoded_bytes(snapshot: CatalogSnapshot) -> None:
    source = read_whole_file(snapshot, ROOT, "managed:repo-agents")
    assert source.unit_id == "managed:repo-agents"
    assert source.path == "AGENTS.md"
    assert source.kind == "managed-prose"
    assert source.text == (ROOT / "AGENTS.md").read_bytes().decode("utf-8")


def test_unknown_unit_id_is_refused(snapshot: CatalogSnapshot) -> None:
    with pytest.raises(SourceReadError) as excinfo:
        read_whole_file(snapshot, ROOT, "markdown:no/such/unit.md")
    assert excinfo.value.reason == "unknown_unit"


def _read_failure(repo_root: Path, path: str) -> str:
    with pytest.raises(SourceReadError) as excinfo:
        read_unit_file(repo_root, _unit(path))
    return excinfo.value.reason


def test_traversal_path_is_contained(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (tmp_path / "outside.txt").write_text("outside\n", encoding="utf-8")
    assert _read_failure(root, "../outside.txt") == "not_found"


def test_absolute_path_naming_a_real_in_root_file_is_rejected_lexically(tmp_path: Path) -> None:
    # Containment alone would pass this: the file genuinely sits under the root. The
    # lexical rejection must fire first, because a pathlib join silently discards the
    # root for an absolute right-hand side.
    inside = tmp_path / "inside.md"
    inside.write_text("inside\n", encoding="utf-8")
    assert _read_failure(tmp_path, str(inside)) == "not_found"


def test_symlink_escaping_the_root_is_contained(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (tmp_path / "outside.txt").write_text("outside\n", encoding="utf-8")
    (root / "escape.md").symlink_to(tmp_path / "outside.txt")
    assert _read_failure(root, "escape.md") == "not_found"


def test_in_root_symlink_resolving_inside_the_root_is_allowed(tmp_path: Path) -> None:
    (tmp_path / "target.md").write_text("linked content\n", encoding="utf-8")
    (tmp_path / "alias.md").symlink_to(tmp_path / "target.md")
    source = read_unit_file(tmp_path, _unit("alias.md"))
    assert source.text == "linked content\n"


def test_missing_file_is_not_found(tmp_path: Path) -> None:
    assert _read_failure(tmp_path, "missing.md") == "not_found"


def test_non_utf8_bytes_are_not_text(tmp_path: Path) -> None:
    # UnicodeDecodeError is a ValueError subclass: this pins the decode arm sitting
    # OUTSIDE the not_found failure boundary.
    (tmp_path / "binary.md").write_bytes(b"\xff\xfe\x00\x01")
    assert _read_failure(tmp_path, "binary.md") == "not_text"


def test_embedded_nul_path_is_not_found(tmp_path: Path) -> None:
    assert _read_failure(tmp_path, "bad\x00name.md") == "not_found"


def test_package_facade_has_the_exact_public_contract() -> None:
    assert source_adapter.__all__ == [
        "CheckHintId",
        "FocusedSource",
        "RangeFailure",
        "RangeResolution",
        "ReadOnlyReason",
        "ResolvedRange",
        "SourceAdapter",
        "SourceDiagnostic",
        "SourceDiagnosticCode",
        "SourceExtraction",
        "SourceRange",
        "SourceReadError",
        "SourceReadFailure",
        "UnresolvedRange",
        "WholeFileSource",
        "read_source",
        "read_unit_file",
        "read_whole_file",
        "source_adapter_for",
    ]
    assert not hasattr(source_adapter, "MarkdownSourceAdapter")
    assert not hasattr(source_adapter, "YamlSourceAdapter")


def test_contract_values_validate_and_extract_uses_canonical_fallback() -> None:
    with pytest.raises(ValueError, match="0 <= start <= end"):
        SourceRange(start=-1, end=0)
    with pytest.raises(ValueError, match="one-based"):
        SourceDiagnostic(
            code="selector-not-found",
            message="missing",
            selector="file-body",
            line=0,
            column=1,
        )
    with pytest.raises(ValueError, match="requires a fragment"):
        FocusedSource(
            unit_id="u",
            path="x.md",
            kind="markdown",
            fragment=None,
            before="",
            focus="text",
            after="",
            editable=True,
            read_only_reason=None,
        )

    adapter = source_adapter_for(_unit("doc.md"))
    assert adapter is not None
    resolved = adapter.extract("# One\nbody\n", "heading:one")
    assert resolved == SourceExtraction(
        before="# One\n",
        focus="body\n",
        after="",
        resolution=ResolvedRange(status="resolved", source_range=SourceRange(start=6, end=11)),
    )
    unresolved = adapter.extract("# One\nbody\n", "heading:missing")
    assert unresolved.before == ""
    assert unresolved.focus == "# One\nbody\n"
    assert unresolved.after == ""
    assert isinstance(unresolved.resolution, UnresolvedRange)
    assert unresolved.resolution.reason == "selector-not-found"


def test_markdown_adapter_resolves_body_description_headings_and_batch_failures() -> None:
    adapter = source_adapter_for(_unit("doc.md"))
    assert adapter is not None
    text = '---\ndescription: "quoted 😀"\n---\n# One\nbody\n## Two\nnested\n# Empty\n'
    description = adapter.extract(text, "frontmatter.description")
    assert description.focus == '"quoted 😀"'
    assert description.before + description.focus + description.after == text
    first = adapter.extract(text, "heading:one")
    assert first.focus == "body\n"
    nested = adapter.extract(text, "heading:one/two")
    assert nested.focus == "nested\n"
    empty = adapter.extract(text, "heading:empty")
    assert empty.focus == ""
    assert empty.before + empty.focus + empty.after == text

    diagnostics = adapter.validate(
        "# One\nbody\n",
        ("heading:missing", "heading:*", "frontmatter.description"),
    )
    assert [diagnostic.code for diagnostic in diagnostics] == [
        "selector-not-found",
        "unsupported-selector",
        "selector-not-found",
    ]
    assert [diagnostic.selector for diagnostic in diagnostics] == [
        "heading:missing",
        "heading:*",
        "frontmatter.description",
    ]

    syntax = adapter.validate(
        "---\ndescription: [broken\n---\nbody\n",
        ("file-body", "frontmatter.description"),
    )
    assert len(syntax) == 1
    assert syntax[0].code == "syntax-error"
    assert syntax[0].selector is None


def _yaml_unit(path: str = "routing.yaml") -> RoutedUnit:
    return RoutedUnit(
        candidate=Candidate(
            id="ambient:fixture",
            kind="ambient-routing",
            path=path,
            selector="items.*.value",
            fragments=(),
        ),
        capability="knowledge",
        audience="both",
        role="ambient-discovery",
    )


def test_yaml_adapter_resolves_map_id_sequence_scalar_styles_and_collections() -> None:
    adapter = source_adapter_for(_yaml_unit())
    assert adapter is not None
    text = (
        'title: "quoted 😀"\n'
        "items:\n"
        "  - id: alpha\n"
        "    value: |\n"
        "      first\n"
        "      second\n"
        "  - id: beta\n"
        "    value: plain\n"
    )
    title = adapter.extract(text, "title")
    assert title.focus == '"quoted 😀"'
    block = adapter.extract(text, "items.alpha.value")
    assert block.focus == "|\n      first\n      second\n"
    assert block.before + block.focus + block.after == text
    collection = adapter.extract(text, "items")
    assert collection.focus.startswith("- id: alpha")
    assert collection.focus.endswith("value: plain\n")


@pytest.mark.parametrize(
    ("text", "selector", "reason", "code"),
    [
        ("value: ok\n", "value.*", "unsupported-selector", "unsupported-selector"),
        ("value: ok\n", "value.0", "unsupported-selector", "unsupported-selector"),
        ("value: ok\n", "value.child", "unsupported-source-shape", "unsupported-source-shape"),
        ("value: ok\n", "missing", "selector-not-found", "selector-not-found"),
        ("value: one\nvalue: two\n", "value", "selector-ambiguous", "selector-ambiguous"),
        ("value: [broken\n", "value", "invalid-source", "syntax-error"),
        (
            "---\nvalue: one\n---\nvalue: two\n",
            "value",
            "unsupported-source-shape",
            "unsupported-source-shape",
        ),
        (
            "base: &copy {value: one}\nitem: *copy\n",
            "item.value",
            "unsupported-source-shape",
            "unsupported-source-shape",
        ),
        (
            "base: &base {value: one}\nitem:\n  <<: *base\n",
            "item.value",
            "unsupported-source-shape",
            "unsupported-source-shape",
        ),
        ("1: value\n", "missing", "unsupported-source-shape", "unsupported-source-shape"),
    ],
)
def test_yaml_adapter_exhaustive_reason_mapping(
    text: str, selector: str, reason: str, code: str
) -> None:
    adapter = source_adapter_for(_yaml_unit())
    assert adapter is not None
    extraction = adapter.extract(text, selector)
    assert isinstance(extraction.resolution, UnresolvedRange)
    assert extraction.resolution.reason == reason
    assert extraction.resolution.diagnostic.code == code
    assert extraction.resolution.diagnostic.selector == (
        None if code == "syntax-error" else selector
    )
    assert extraction.before == ""
    assert extraction.focus == text
    assert extraction.after == ""


def test_yaml_id_sequence_duplicate_and_batch_diagnostic_order() -> None:
    adapter = source_adapter_for(_yaml_unit())
    assert adapter is not None
    duplicate = "items:\n  - id: alpha\n    value: one\n  - id: alpha\n    value: two\n"
    result = adapter.resolve_range(duplicate, "items.alpha.value")
    assert isinstance(result, UnresolvedRange)
    assert result.reason == "selector-ambiguous"
    assert (result.diagnostic.line, result.diagnostic.column) == (4, 9)

    diagnostics = adapter.validate(
        "items:\n  - id: alpha\n    value: one\n",
        ("missing", "items.beta.value", "items.*.value"),
    )
    assert [diagnostic.code for diagnostic in diagnostics] == [
        "selector-not-found",
        "selector-not-found",
        "unsupported-selector",
    ]
    syntax = adapter.validate("value: [broken\n", ("missing", "value"))
    assert len(syntax) == 1
    assert syntax[0].code == "syntax-error"


def test_adapter_dispatch_and_semantic_check_hints() -> None:
    markdown = source_adapter_for(_unit("doc.md"))
    yaml_adapter = source_adapter_for(_yaml_unit("doc.yml"))
    assert markdown is not None
    assert yaml_adapter is not None
    assert markdown.affected_check_hints(_unit("doc.md")) == ("prose-map",)
    assert yaml_adapter.affected_check_hints(_yaml_unit()) == (
        "prose-map",
        "learned-docs",
    )
    assert source_adapter_for(_unit("doc.py")) is None


def test_read_source_whole_markdown_yaml_unsupported_and_unknown_fragment(
    snapshot: CatalogSnapshot, tmp_path: Path
) -> None:
    (tmp_path / "AGENTS.md").write_bytes((ROOT / "AGENTS.md").read_bytes())
    clusters = tmp_path / "docs/learned/clusters.yaml"
    clusters.parent.mkdir(parents=True)
    clusters.write_bytes((ROOT / "docs/learned/clusters.yaml").read_bytes())

    whole = read_source(snapshot, tmp_path, "managed:repo-agents")
    assert whole.fragment is None
    assert whole.editable is False
    assert whole.read_only_reason == "whole-unit"
    assert whole.before == "" and whole.after == ""
    assert whole.focus == (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    markdown = read_source(
        snapshot,
        tmp_path,
        "managed:repo-agents",
        "section:agents/developing-perk",
    )
    assert markdown.editable is True
    assert markdown.fragment is not None
    assert markdown.focus.startswith("\n*Conventions for working **on** perk itself")
    assert markdown.before + markdown.focus + markdown.after == whole.focus

    yaml_source = read_source(
        snapshot,
        tmp_path,
        "ambient:learned-routing",
        "cluster:pi-extension",
    )
    assert yaml_source.editable is True
    assert yaml_source.fragment is not None
    assert "Pi SDK/extension substrate craft" in yaml_source.focus
    assert yaml_source.before + yaml_source.focus + yaml_source.after == clusters.read_text(
        encoding="utf-8"
    )

    with pytest.raises(SourceReadError) as excinfo:
        read_source(snapshot, tmp_path, "managed:repo-agents", "cluster:pi-extension")
    assert excinfo.value.reason == "unknown_fragment"

    unsupported_unit = snapshot.get_unit("typescript-tool:plan_review")
    assert unsupported_unit is not None
    unsupported_path = tmp_path / unsupported_unit.candidate.path
    unsupported_path.parent.mkdir(parents=True, exist_ok=True)
    unsupported_path.write_bytes((ROOT / unsupported_unit.candidate.path).read_bytes())
    unsupported_fragment = snapshot.fragments_for_unit(unsupported_unit.candidate.id)[0]
    unsupported = read_source(
        snapshot,
        tmp_path,
        unsupported_unit.candidate.id,
        unsupported_fragment.fragment.id,
    )
    assert unsupported.editable is False
    assert unsupported.read_only_reason == "unsupported-family"
    assert unsupported.before == "" and unsupported.after == ""
    assert unsupported.focus == unsupported_path.read_text(encoding="utf-8")
