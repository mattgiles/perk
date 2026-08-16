"""The seeded whole-file SourceAdapter: containment, membership, text-only decode."""

import ast
import json
import threading
import token
import tokenize
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Literal

import pytest
from perk_dev.prose_map.catalog import build_catalog
from perk_dev.prose_map.models import Candidate, ProseKind, RoutedUnit
from perk_dev.prose_review import source_adapter
from perk_dev.prose_review.catalog import CatalogSnapshot
from perk_dev.prose_review.source_adapter import (
    FocusedSource,
    RangeResolution,
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
from perk_dev.prose_review.source_adapter import python as python_adapter_module
from perk_dev.prose_review.source_adapter import typescript as typescript_adapter_module
from perk_dev.prose_review.source_adapter.python import PythonSourceAdapter
from perk_dev.prose_review.source_adapter.typescript import (
    TypeScriptAdapterUnavailable,
    TypeScriptSourceAdapter,
)

from perk.substrate.proc import ProcFailure

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
    assert not hasattr(source_adapter, "PythonSourceAdapter")
    assert not hasattr(source_adapter, "TypeScriptAdapterUnavailable")
    assert not hasattr(source_adapter, "TypeScriptSourceAdapter")
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

    malformed = "---\ndescription: [broken\n---\nbody\n"
    syntax = adapter.validate(malformed, ("file-body", "frontmatter.description"))
    assert len(syntax) == 1
    assert syntax[0].code == "syntax-error"
    assert syntax[0].selector is None
    assert adapter.validate(malformed, ()) == syntax


def test_markdown_adapter_rejects_valid_multidocument_frontmatter() -> None:
    adapter = source_adapter_for(_unit("doc.md"))
    assert adapter is not None
    text = "---\ndescription: first\n--- # second document\ndescription: second\n---\nBody\n"
    extraction = adapter.extract(text, "frontmatter.description")
    assert isinstance(extraction.resolution, UnresolvedRange)
    assert extraction.resolution.reason == "unsupported-source-shape"
    assert extraction.before == ""
    assert extraction.focus == text
    assert extraction.after == ""
    diagnostics = adapter.validate(text, ("frontmatter.description",))
    assert len(diagnostics) == 1
    assert diagnostics[0].code == "unsupported-source-shape"
    assert diagnostics[0].line == 4


def _python_unit(
    path: str = "module.py",
    *,
    kind: ProseKind = "python-symbol",
) -> RoutedUnit:
    return RoutedUnit(
        candidate=Candidate(
            id=f"{kind}:fixture",
            kind=kind,
            path=path,
            selector="symbol:target",
            fragments=(),
        ),
        capability="foundation",
        audience="both",
        role="context",
    )


def _typescript_unit(
    kind: ProseKind = "typescript-tool",
    path: str = "module.ts",
) -> RoutedUnit:
    return RoutedUnit(
        candidate=Candidate(
            id=f"{kind}:fixture",
            kind=kind,
            path=path,
            selector="tool:fixture",
            fragments=(),
        ),
        capability="foundation",
        audience="both",
        role="context",
    )


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


def test_yaml_quoted_literal_merge_key_remains_a_supported_mapping_key() -> None:
    adapter = source_adapter_for(_yaml_unit())
    assert adapter is not None
    text = '"<<": literal\nvalue: ok\n'
    literal = adapter.extract(text, "<<")
    assert literal.focus == "literal"
    assert literal.before + literal.focus + literal.after == text
    unrelated = adapter.extract(text, "value")
    assert unrelated.focus == "ok"


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
    python_adapter = source_adapter_for(_python_unit())
    managed_python = source_adapter_for(_python_unit(kind="managed-prose"))
    managed_markdown = source_adapter_for(_python_unit("AGENTS.md", kind="managed-prose"))
    assert markdown is not None
    assert yaml_adapter is not None
    assert python_adapter is not None
    assert managed_python is python_adapter
    assert managed_python is not markdown
    assert managed_markdown is markdown
    assert markdown.affected_check_hints(_unit("doc.md")) == ("prose-map",)
    assert python_adapter.affected_check_hints(_python_unit()) == ("prose-map",)
    assert yaml_adapter.affected_check_hints(_yaml_unit()) == (
        "prose-map",
        "learned-docs",
    )
    assert source_adapter_for(_unit("doc.py")) is None
    assert source_adapter_for(_python_unit("doc.md")) is None
    assert source_adapter_for(_python_unit("doc.ts", kind="managed-prose")) is None

    typescript_adapter = TypeScriptSourceAdapter(ROOT)
    for kind in ("typescript-tool", "typescript-model-call", "typescript-symbol"):
        unit = _typescript_unit(kind)
        assert source_adapter_for(unit, typescript_adapter=typescript_adapter) is typescript_adapter
        assert source_adapter_for(unit) is None
    assert (
        source_adapter_for(
            _typescript_unit("typescript-tool", "module.js"),
            typescript_adapter=typescript_adapter,
        )
        is None
    )
    assert (
        source_adapter_for(
            _python_unit("module.ts", kind="python-symbol"),
            typescript_adapter=typescript_adapter,
        )
        is None
    )


def test_read_source_whole_markdown_yaml_unsupported_and_unknown_fragment(
    snapshot: CatalogSnapshot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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

    focused_typescript = read_source(
        snapshot,
        tmp_path,
        unsupported_unit.candidate.id,
        "description",
        typescript_adapter=TypeScriptSourceAdapter(ROOT),
    )
    assert focused_typescript.editable is True
    assert focused_typescript.read_only_reason is None
    assert focused_typescript.before + focused_typescript.focus + focused_typescript.after == (
        unsupported_path.read_text(encoding="utf-8")
    )
    assert focused_typescript.focus.startswith('"')

    def unavailable(*_args: object, **_kwargs: object) -> str:
        raise ProcFailure("timeout", ("node",))

    monkeypatch.setattr(typescript_adapter_module, "run_checked", unavailable)
    fallback = read_source(
        snapshot,
        tmp_path,
        unsupported_unit.candidate.id,
        "description",
        typescript_adapter=TypeScriptSourceAdapter(ROOT),
    )
    assert fallback.editable is False
    assert fallback.read_only_reason == "adapter-unavailable"
    assert fallback.focus == unsupported_path.read_text(encoding="utf-8")


def test_every_real_python_backed_fragment_resolves_and_recomposes(
    snapshot: CatalogSnapshot,
) -> None:
    units = [
        unit
        for unit in snapshot.units
        if unit.candidate.kind == "python-symbol"
        or (unit.candidate.kind == "managed-prose" and Path(unit.candidate.path).suffix == ".py")
    ]
    assert len(units) == 15
    for unit in units:
        expected = (ROOT / unit.candidate.path).read_text(encoding="utf-8")
        fragments = snapshot.fragments_for_unit(unit.candidate.id)
        assert len(fragments) == 1
        source = read_source(
            snapshot,
            ROOT,
            unit.candidate.id,
            fragments[0].fragment.id,
        )
        assert source.editable is True
        assert source.read_only_reason is None
        assert source.before + source.focus + source.after == expected


def _python_adapter() -> PythonSourceAdapter:
    adapter = source_adapter_for(_python_unit())
    assert isinstance(adapter, PythonSourceAdapter)
    return adapter


@pytest.mark.parametrize(
    ("text", "selector", "focus"),
    [
        (
            "# leading context\n"
            "def target(value: str):\n"
            "    first = value\n"
            "    return first.upper()\n"
            "# trailing context\n",
            "symbol:target",
            "def target(value: str):\n    first = value\n    return first.upper()",
        ),
        (
            'before = 0\r\nasync def target():\r\n    return "line 😀"\r\nafter = 1\r\n',
            "symbol:target",
            'async def target():\r\n    return "line 😀"',
        ),
        (
            'value = (\n    "first"\n    "second"\n)  # trailing comment\n',
            "symbol:value",
            'value = (\n    "first"\n    "second"\n)',
        ),
        (
            'typed: tuple[str, ...] = (\n    "alpha",\n    "beta",\n)\n',
            "symbol:typed",
            'typed: tuple[str, ...] = (\n    "alpha",\n    "beta",\n)',
        ),
        (
            'before = "😀"; café = "inside ��� and 😀"; after = 1\n',
            "symbol:café",
            'café = "inside ��� and 😀"',
        ),
        ("match = 1\n", "symbol:match", "match = 1"),
        ("case = 1\n", "symbol:case", "case = 1"),
        ("type = 1\n", "symbol:type", "type = 1"),
        ('only = "whole file"', "symbol:only", 'only = "whole file"'),
    ],
)
def test_python_adapter_exact_symbol_focus_and_recomposition(
    text: str,
    selector: str,
    focus: str,
) -> None:
    extraction = _python_adapter().extract(text, selector)
    assert extraction.focus == focus
    assert extraction.before + extraction.focus + extraction.after == text
    assert isinstance(extraction.resolution, ResolvedRange)


@pytest.mark.parametrize("definition", ["def target():", "async def target():"])
def test_python_adapter_decorators_start_at_physical_marker_and_ignore_matrix_operator(
    definition: str,
) -> None:
    text = (
        "prefix = 1\n"
        "@(\n"
        "    decorator_factory(left @ right)\n"
        ")\n"
        "@second_decorator\n"
        f"{definition}\n"
        '    return "focused 😀"\n'
        "# trailing context\n"
    )
    expected = (
        "@(\n"
        "    decorator_factory(left @ right)\n"
        ")\n"
        "@second_decorator\n"
        f"{definition}\n"
        '    return "focused 😀"'
    )

    extraction = _python_adapter().extract(text, "symbol:target")
    assert extraction.focus == expected
    assert extraction.before + extraction.focus + extraction.after == text


def test_python_adapter_ignores_matrix_operator_on_explicitly_continued_decorator() -> None:
    text = "@left " + "\\\n" + "@ right\ndef target():\n    pass\n"
    expected = "@left " + "\\\n" + "@ right\ndef target():\n    pass"

    extraction = _python_adapter().extract(text, "symbol:target")
    assert extraction.focus == expected
    assert extraction.before + extraction.focus + extraction.after == text


@pytest.mark.parametrize(
    "selector",
    [
        "",
        "symbol:",
        "symbol:target.name",
        "symbol:for",
        " symbol:target",
        "symbol:target ",
        "symbol:target/extra",
        "call-argument:target:value",
    ],
)
def test_python_adapter_rejects_every_unemitted_selector_shape(selector: str) -> None:
    result = _python_adapter().resolve_range("target = 1\n", selector)
    assert isinstance(result, UnresolvedRange)
    assert result.reason == "unsupported-selector"
    assert result.diagnostic == SourceDiagnostic(
        code="unsupported-selector",
        message="The selector is not supported by the Python adapter.",
        selector=selector,
        line=None,
        column=None,
    )


@pytest.mark.parametrize(
    "text",
    [
        "class target:\n    pass\n",
        "target, other = (1, 2)\n",
        "target = other = 1\n",
        "def outer():\n    def target():\n        pass\n",
    ],
)
def test_python_adapter_treats_unsupported_same_name_bindings_as_not_found(text: str) -> None:
    result = _python_adapter().resolve_range(text, "symbol:target")
    assert isinstance(result, UnresolvedRange)
    assert result.reason == "selector-not-found"
    assert result.diagnostic == SourceDiagnostic(
        code="selector-not-found",
        message="The selector does not resolve in the current Python source.",
        selector="symbol:target",
        line=None,
        column=None,
    )


def test_python_adapter_reports_duplicate_supported_symbols_at_second_unicode_location() -> None:
    text = 'target = 1\nprefix = "😀"; target = 2\n'
    result = _python_adapter().resolve_range(text, "symbol:target")
    assert isinstance(result, UnresolvedRange)
    assert result.reason == "selector-ambiguous"
    assert result.diagnostic == SourceDiagnostic(
        code="selector-ambiguous",
        message="The selector resolves more than once in the current Python source.",
        selector="symbol:target",
        line=2,
        column=text.splitlines()[1].index("target") + 1,
    )


@pytest.mark.parametrize("text", ["def broken(:\n", "target = 1\nreturn\n", "target = 1\nbreak\n"])
def test_python_adapter_parse_and_compiler_failures_are_document_level(text: str) -> None:
    adapter = _python_adapter()
    result = adapter.resolve_range(text, "call-argument:unsupported")
    assert isinstance(result, UnresolvedRange)
    assert result.reason == "invalid-source"
    assert result.diagnostic.code == "syntax-error"
    assert result.diagnostic.message == "The Python source is not syntactically valid."
    assert result.diagnostic.selector is None
    assert result.diagnostic.line is not None
    assert result.diagnostic.column is not None
    assert adapter.validate(text, ()) == (result.diagnostic,)


def test_python_adapter_batch_validation_parses_compiles_and_tokenizes_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"parse": 0, "compile": 0, "tokenize": 0}
    original_parse = python_adapter_module.ast.parse
    original_compile = compile
    original_generate_tokens = python_adapter_module.tokenize.generate_tokens

    def counting_parse(source: str, filename: str) -> ast.Module:
        calls["parse"] += 1
        return original_parse(source, filename=filename)

    def counting_compile(source: ast.Module, filename: str, mode: str) -> object:
        calls["compile"] += 1
        return original_compile(source, filename, mode)

    def counting_generate_tokens(
        readline: Callable[[], str],
    ) -> Iterator[tokenize.TokenInfo]:
        calls["tokenize"] += 1
        return original_generate_tokens(readline)

    monkeypatch.setattr(python_adapter_module.ast, "parse", counting_parse)
    monkeypatch.setattr(python_adapter_module, "compile", counting_compile, raising=False)
    monkeypatch.setattr(
        python_adapter_module.tokenize,
        "generate_tokens",
        counting_generate_tokens,
    )

    diagnostics = _python_adapter().validate(
        "target = 1\n",
        ("symbol:missing", "bad-selector", "symbol:target", "symbol:also_missing"),
    )
    assert [diagnostic.code for diagnostic in diagnostics] == [
        "selector-not-found",
        "unsupported-selector",
        "selector-not-found",
    ]
    assert [diagnostic.selector for diagnostic in diagnostics] == [
        "symbol:missing",
        "bad-selector",
        "symbol:also_missing",
    ]
    assert calls == {"parse": 1, "compile": 1, "tokenize": 1}


def test_python_adapter_tokenizer_failure_retains_reported_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_tokenization(
        _readline: Callable[[], str],
    ) -> Iterator[tokenize.TokenInfo]:
        raise tokenize.TokenError("fixture token failure", (2, 3))

    monkeypatch.setattr(python_adapter_module.tokenize, "generate_tokens", fail_tokenization)
    diagnostics = _python_adapter().validate("target = 1\n", ("symbol:target",))
    assert diagnostics == (
        SourceDiagnostic(
            code="syntax-error",
            message="The Python source is not syntactically valid.",
            selector=None,
            line=2,
            column=4,
        ),
    )


def test_python_adapter_decorator_token_mismatch_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_generate_tokens = python_adapter_module.tokenize.generate_tokens

    def without_target_marker(
        readline: Callable[[], str],
    ) -> Iterator[tokenize.TokenInfo]:
        return (
            current
            for current in original_generate_tokens(readline)
            if not (current.type == token.OP and current.string == "@" and current.start == (4, 0))
        )

    monkeypatch.setattr(
        python_adapter_module.tokenize,
        "generate_tokens",
        without_target_marker,
    )
    text = "@first\ndef previous():\n    pass\n@second\ndef target():\n    pass\n"
    extraction = _python_adapter().extract(text, "symbol:target")
    assert extraction.before == ""
    assert extraction.focus == text
    assert extraction.after == ""
    assert isinstance(extraction.resolution, UnresolvedRange)
    assert extraction.resolution.reason == "invalid-source"
    assert extraction.resolution.diagnostic.selector is None


def test_python_adapter_check_hint_is_only_prose_map() -> None:
    assert _python_adapter().affected_check_hints(_unit("doc.py")) == ("prose-map",)


def _typescript_adapter() -> TypeScriptSourceAdapter:
    return TypeScriptSourceAdapter(ROOT)


def _ok_response(*results: dict[str, object]) -> str:
    return json.dumps({"version": 1, "status": "ok", "results": results})


def _resolved_result(selector: str, start: int = 0, end: int = 1) -> dict[str, object]:
    return {
        "selector": selector,
        "status": "resolved",
        "start": start,
        "end": end,
    }


def test_typescript_adapter_invokes_exact_temp_snapshot_protocol_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    helper_root = tmp_path / "helper checkout"
    helper_root.mkdir()
    text = 'const value = "exact 😀";\n'
    selectors = ("symbol:value", "tool:demo.description")
    observed: dict[str, object] = {}

    def fake_run_checked(
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        timeout: int,
        env_overlay: Mapping[str, str] | None = None,
    ) -> str:
        request_path = Path(argv[2])
        observed.update(
            argv=tuple(argv),
            cwd=cwd,
            timeout=timeout,
            env_overlay=env_overlay,
            request_path=request_path,
            request=json.loads(request_path.read_text(encoding="utf-8")),
            existed=request_path.is_file(),
        )
        return _ok_response(
            _resolved_result(selectors[0], 0, 5),
            {
                "selector": selectors[1],
                "status": "unresolved",
                "reason": "selector-not-found",
                "line": None,
                "column": None,
            },
        )

    monkeypatch.setattr(typescript_adapter_module, "run_checked", fake_run_checked)
    adapter = TypeScriptSourceAdapter(helper_root)
    diagnostics = adapter.validate(text, selectors)

    assert diagnostics == (
        SourceDiagnostic(
            code="selector-not-found",
            message="The selector does not resolve in the current TypeScript source.",
            selector=selectors[1],
            line=None,
            column=None,
        ),
    )
    assert observed["argv"] == (
        "node",
        str(helper_root / "tools/prose-map/selector.ts"),
        str(observed["request_path"]),
    )
    assert observed["cwd"] == helper_root
    assert observed["timeout"] == 5
    assert observed["env_overlay"] is None
    assert observed["request"] == {
        "version": 1,
        "source": text,
        "selectors": list(selectors),
    }
    assert observed["existed"] is True
    request_path = observed["request_path"]
    assert isinstance(request_path, Path)
    assert not request_path.exists()
    assert not str(request_path).startswith(str(helper_root))
    assert text not in str(observed["argv"])


def test_typescript_adapter_real_helper_resolves_and_recomposes_representative_sites() -> None:
    adapter = _typescript_adapter()
    text = (
        'pi.registerTool({ name: "demo", description: "direct" + suffix, '
        "promptSnippet: helper });\n"
        "function owner() { client.complete(`hello ${name}`); }\n"
    )
    direct = adapter.extract(text, "tool:demo.description")
    assert direct.focus == '"direct" + suffix'
    assert direct.before + direct.focus + direct.after == text
    assert isinstance(direct.resolution, ResolvedRange)

    call = adapter.extract(text, "symbol:owner/call:complete/0/argument:0")
    assert call.focus == "`hello ${name}`"
    assert call.before + call.focus + call.after == text
    assert isinstance(call.resolution, ResolvedRange)

    extended_text = """
function owner() {
  completeStructured({ system: "structured system" });
  pi.on("before_agent_start", () => "event handler");
  return { workflowScript: "workflow body" };
}
"""
    for selector, expected in (
        ("symbol:owner/call:completeStructured/system", '"structured system"'),
        ("symbol:owner/event:before_agent_start/0/handler", '() => "event handler"'),
        ("symbol:owner/property:workflowScript/0", '"workflow body"'),
    ):
        extraction = adapter.extract(extended_text, selector)
        assert extraction.focus == expected
        assert extraction.before + extraction.focus + extraction.after == extended_text
        assert isinstance(extraction.resolution, ResolvedRange)

    invalid_prefix = 'const prefix = "😀"; '
    invalid = adapter.resolve_range(
        f"{invalid_prefix}const broken = ;",
        "symbol:module/call:complete/0/argument:0",
    )
    assert isinstance(invalid, UnresolvedRange)
    assert invalid.reason == "invalid-source"
    assert invalid.diagnostic.line == 1
    assert invalid.diagnostic.column == len(invalid_prefix) + 16

    unsupported = adapter.extract(text, "tool:demo.promptSnippet")
    assert isinstance(unsupported.resolution, UnresolvedRange)
    assert unsupported.resolution.reason == "unsupported-source-shape"
    assert unsupported.before == ""
    assert unsupported.focus == text
    assert unsupported.after == ""


def test_typescript_adapter_maps_every_diagnostic_and_parser_short_circuits_empty_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selectors = (
        "unsupported",
        "shape",
        "missing",
        "duplicate",
    )
    response = _ok_response(
        {
            "selector": selectors[0],
            "status": "unresolved",
            "reason": "unsupported-selector",
            "line": None,
            "column": None,
        },
        {
            "selector": selectors[1],
            "status": "unresolved",
            "reason": "unsupported-source-shape",
            "line": 1,
            "column": 1,
        },
        {
            "selector": selectors[2],
            "status": "unresolved",
            "reason": "selector-not-found",
            "line": None,
            "column": None,
        },
        {
            "selector": selectors[3],
            "status": "unresolved",
            "reason": "selector-ambiguous",
            "line": 1,
            "column": 2,
        },
    )
    calls = 0

    def fake_run_checked(
        _argv: Sequence[str],
        *,
        cwd: Path | None = None,
        timeout: int,
        env_overlay: Mapping[str, str] | None = None,
    ) -> str:
        del cwd, timeout, env_overlay
        nonlocal calls
        calls += 1
        return response

    monkeypatch.setattr(typescript_adapter_module, "run_checked", fake_run_checked)
    diagnostics = _typescript_adapter().validate("text", selectors)
    actual_diagnostics = [
        (item.code, item.message, item.selector, item.line, item.column) for item in diagnostics
    ]
    assert actual_diagnostics == [
        (
            "unsupported-selector",
            "The selector is not supported by the TypeScript adapter.",
            "unsupported",
            None,
            None,
        ),
        (
            "unsupported-source-shape",
            "The TypeScript selector resolves to a source shape that is not safely editable.",
            "shape",
            1,
            1,
        ),
        (
            "selector-not-found",
            "The selector does not resolve in the current TypeScript source.",
            "missing",
            None,
            None,
        ),
        (
            "selector-ambiguous",
            "The selector resolves more than once in the current TypeScript source.",
            "duplicate",
            1,
            2,
        ),
    ]
    assert calls == 1

    monkeypatch.setattr(
        typescript_adapter_module,
        "run_checked",
        lambda *_args, **_kwargs: json.dumps(
            {"version": 1, "status": "invalid-source", "line": 1, "column": 2}
        ),
    )
    assert _typescript_adapter().validate("x", ()) == (
        SourceDiagnostic(
            code="syntax-error",
            message="The TypeScript source is not syntactically valid.",
            selector=None,
            line=1,
            column=2,
        ),
    )


@pytest.mark.parametrize(
    "stdout",
    [
        "not json",
        json.dumps({"version": 2, "status": "ok", "results": []}),
        json.dumps({"version": 1, "status": "unknown", "results": []}),
        json.dumps({"version": 1, "status": "ok", "results": [], "extra": True}),
        _ok_response(_resolved_result("wrong")),
        _ok_response(_resolved_result("selected", -1, 1)),
        _ok_response(_resolved_result("selected", 1, 1)),
        _ok_response(_resolved_result("selected", 0, 5)),
        _ok_response(
            {
                "selector": "selected",
                "status": "unresolved",
                "reason": "selector-not-found",
                "line": 1,
                "column": 1,
            }
        ),
        _ok_response(
            {
                "selector": "selected",
                "status": "unresolved",
                "reason": "selector-ambiguous",
                "line": None,
                "column": None,
            }
        ),
        _ok_response(
            {
                "selector": "selected",
                "status": "unresolved",
                "reason": "selector-ambiguous",
                "line": 1,
                "column": None,
            }
        ),
        _ok_response(
            {
                "selector": "selected",
                "status": "unresolved",
                "reason": "selector-ambiguous",
                "line": 2,
                "column": 1,
            }
        ),
        _ok_response(
            {
                "selector": "selected",
                "status": "unresolved",
                "reason": "selector-ambiguous",
                "line": 1,
                "column": 3,
            }
        ),
        json.dumps({"version": 1, "status": "invalid-source", "line": 2, "column": 1}),
    ],
)
def test_typescript_adapter_rejects_protocol_corruption(
    monkeypatch: pytest.MonkeyPatch,
    stdout: str,
) -> None:
    monkeypatch.setattr(
        typescript_adapter_module,
        "run_checked",
        lambda *_args, **_kwargs: stdout,
    )
    with pytest.raises(TypeScriptAdapterUnavailable):
        _typescript_adapter().resolve_range("x", "selected")


@pytest.mark.parametrize("kind", ["spawn", "timeout", "exit"])
def test_typescript_adapter_translates_every_process_failure_and_releases_slot(
    monkeypatch: pytest.MonkeyPatch,
    kind: Literal["spawn", "timeout", "exit"],
) -> None:
    def fail(
        _argv: Sequence[str],
        *,
        cwd: Path | None = None,
        timeout: int,
        env_overlay: Mapping[str, str] | None = None,
    ) -> str:
        del cwd, timeout, env_overlay
        raise ProcFailure(kind, ("node",))

    monkeypatch.setattr(typescript_adapter_module, "run_checked", fail)
    adapter = _typescript_adapter()
    with pytest.raises(TypeScriptAdapterUnavailable):
        adapter.resolve_range("x", "selected")

    monkeypatch.setattr(
        typescript_adapter_module,
        "run_checked",
        lambda *_args, **_kwargs: _ok_response(_resolved_result("selected")),
    )
    assert adapter.resolve_range("x", "selected") == ResolvedRange(
        status="resolved",
        source_range=SourceRange(start=0, end=1),
    )


def test_typescript_adapter_translates_tempfile_failure_and_releases_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _typescript_adapter()
    original_temporary_directory = typescript_adapter_module.tempfile.TemporaryDirectory

    def fail_tempfile(*_args: object, **_kwargs: object) -> object:
        raise OSError("fixture tempfile failure")

    monkeypatch.setattr(typescript_adapter_module.tempfile, "TemporaryDirectory", fail_tempfile)
    with pytest.raises(TypeScriptAdapterUnavailable):
        adapter.resolve_range("x", "selected")

    monkeypatch.setattr(
        typescript_adapter_module.tempfile,
        "TemporaryDirectory",
        original_temporary_directory,
    )
    monkeypatch.setattr(
        typescript_adapter_module,
        "run_checked",
        lambda *_args, **_kwargs: _ok_response(_resolved_result("selected")),
    )
    assert isinstance(adapter.resolve_range("x", "selected"), ResolvedRange)


def test_typescript_adapter_is_fail_fast_under_overlap_and_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    calls = 0

    def blocked(
        _argv: Sequence[str],
        *,
        cwd: Path | None = None,
        timeout: int,
        env_overlay: Mapping[str, str] | None = None,
    ) -> str:
        del cwd, timeout, env_overlay
        nonlocal calls
        calls += 1
        entered.set()
        assert release.wait(timeout=5)
        return _ok_response(_resolved_result("selected"))

    monkeypatch.setattr(typescript_adapter_module, "run_checked", blocked)
    adapter = _typescript_adapter()
    first_result: list[RangeResolution] = []
    failures: list[BaseException] = []

    def first() -> None:
        try:
            first_result.append(adapter.resolve_range("x", "selected"))
        except BaseException as exc:
            failures.append(exc)

    thread = threading.Thread(target=first)
    thread.start()
    assert entered.wait(timeout=5)
    with pytest.raises(TypeScriptAdapterUnavailable, match="busy"):
        adapter.resolve_range("x", "selected")
    assert calls == 1

    release.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert failures == []
    assert first_result == [
        ResolvedRange(status="resolved", source_range=SourceRange(start=0, end=1))
    ]

    assert isinstance(adapter.resolve_range("x", "selected"), ResolvedRange)
    assert calls == 2


def test_every_real_typescript_fragment_is_batch_covered_through_the_python_adapter(
    snapshot: CatalogSnapshot,
) -> None:
    selectors_by_path: dict[str, list[str]] = {}
    total = 0
    for unit in snapshot.units:
        if unit.candidate.kind not in (
            "typescript-tool",
            "typescript-model-call",
            "typescript-symbol",
        ):
            continue
        selectors = selectors_by_path.setdefault(unit.candidate.path, [])
        for routed_fragment in snapshot.fragments_for_unit(unit.candidate.id):
            selectors.append(routed_fragment.fragment.selector)
            total += 1

    assert total == 276
    adapter = _typescript_adapter()
    for relative, selectors in selectors_by_path.items():
        text = (ROOT / relative).read_text(encoding="utf-8")
        response = adapter._invoke(text, tuple(selectors))
        assert isinstance(response, tuple), relative
        assert len(response) == len(selectors), relative
        for expected, current in zip(selectors, response, strict=True):
            assert current.selector == expected, relative
            if isinstance(current, typescript_adapter_module._HelperResolved):
                source_range = current.source_range
                assert 0 <= source_range.start < source_range.end <= len(text), relative
                before = text[: source_range.start]
                focus = text[source_range.start : source_range.end]
                after = text[source_range.end :]
                assert focus
                assert before + focus + after == text, relative
            else:
                assert isinstance(current, typescript_adapter_module._HelperUnresolved)
                assert current.reason == "unsupported-source-shape", relative


def test_typescript_adapter_check_hint_is_only_prose_map() -> None:
    assert _typescript_adapter().affected_check_hints(_python_unit("module.ts")) == ("prose-map",)
