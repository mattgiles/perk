"""Safe whole-buffer source persistence and conditional atomic replacement."""

import hashlib
import stat
from pathlib import Path

import pytest
from perk_dev.prose_map.catalog import build_catalog
from perk_dev.prose_review.catalog import CatalogSnapshot
from perk_dev.prose_review.source_adapter import (
    SourceConflict,
    SourceRefused,
    SourceSaved,
    SourceValidationFailed,
    save_source,
)
from perk_dev.prose_review.source_adapter import write as write_module

ROOT = Path(__file__).parents[1]


@pytest.fixture(scope="module")
def snapshot() -> CatalogSnapshot:
    return CatalogSnapshot.from_catalog(build_catalog(ROOT))


def _copy(relative: str, root: Path) -> Path:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((ROOT / relative).read_bytes())
    return target


def test_markdown_save_writes_exact_utf8_and_preserves_latest_special_mode(
    snapshot: CatalogSnapshot,
    tmp_path: Path,
) -> None:
    target = _copy("AGENTS.md", tmp_path)
    target.chmod(0o6751)
    original = target.read_bytes()
    text = original.decode("utf-8").replace(
        "*Conventions for working", "*Saved 😀 conventions for working", 1
    )

    result = save_source(
        snapshot,
        tmp_path,
        "managed:repo-agents",
        hashlib.sha256(original).hexdigest(),
        text,
    )

    assert isinstance(result, SourceSaved)
    assert result.source.content == text.encode("utf-8")
    assert result.source.load_hash == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert result.source.newline_style == "lf"
    assert result.source.mode == 0o6751
    assert stat.S_IMODE(target.stat().st_mode) == 0o6751
    assert target.read_bytes() == text.encode("utf-8")
    assert result.materialized == ()
    assert [(check.id, check.command) for check in result.checks] == [
        ("prose-map", "perk-dev prose-map check")
    ]
    assert [path for path in target.parent.iterdir() if path.name.endswith(".tmp")] == []


def test_yaml_save_reports_materialization_and_both_named_checks(
    snapshot: CatalogSnapshot,
    tmp_path: Path,
) -> None:
    target = _copy("docs/learned/clusters.yaml", tmp_path)
    original = target.read_bytes()
    text = original.decode("utf-8").replace(
        "Pi SDK/extension substrate craft", "Saved extension substrate craft", 1
    )

    result = save_source(
        snapshot,
        tmp_path,
        "ambient:learned-routing",
        hashlib.sha256(original).hexdigest(),
        text,
    )

    assert isinstance(result, SourceSaved)
    assert target.read_bytes() == text.encode("utf-8")
    assert [view.lineage.id for view in result.materialized] == ["ambient-index"]
    assert [(check.id, check.command) for check in result.checks] == [
        ("prose-map", "perk-dev prose-map check"),
        ("learned-docs", "perk learn docs-check"),
    ]


def test_validation_is_syntax_first_and_leaves_target_unchanged(
    snapshot: CatalogSnapshot,
    tmp_path: Path,
) -> None:
    target = _copy("AGENTS.md", tmp_path)
    original = target.read_bytes()

    result = save_source(
        snapshot,
        tmp_path,
        "managed:repo-agents",
        hashlib.sha256(original).hexdigest(),
        "---\ndescription: [broken\n---\n",
    )

    assert isinstance(result, SourceValidationFailed)
    assert len(result.diagnostics) == 1
    assert result.diagnostics[0].code == "syntax-error"
    assert result.diagnostics[0].selector is None
    assert target.read_bytes() == original


def test_unsupported_python_is_refused_without_mutation(
    snapshot: CatalogSnapshot,
    tmp_path: Path,
) -> None:
    unit_id = "python-symbol:packages/perk-dev/src/perk_dev/audit/bounding.py:_PREAMBLE"
    unit = snapshot.get_unit(unit_id)
    assert unit is not None
    target = _copy(unit.candidate.path, tmp_path)
    original = target.read_bytes()

    result = save_source(
        snapshot,
        tmp_path,
        unit_id,
        hashlib.sha256(original).hexdigest(),
        original.decode("utf-8") + "\n",
    )

    assert result == SourceRefused(
        status="refused",
        reason="unsupported-family",
        detail="Save support has not landed for this source family.",
    )
    assert target.read_bytes() == original


def test_every_symlink_component_is_refused(snapshot: CatalogSnapshot, tmp_path: Path) -> None:
    target = tmp_path / "actual.md"
    target.write_bytes((ROOT / "AGENTS.md").read_bytes())
    (tmp_path / "AGENTS.md").symlink_to(target)

    result = save_source(
        snapshot,
        tmp_path,
        "managed:repo-agents",
        hashlib.sha256(target.read_bytes()).hexdigest(),
        target.read_text(encoding="utf-8"),
    )

    assert isinstance(result, SourceRefused)
    assert result.reason == "unsafe-path"
    assert target.read_bytes() == (ROOT / "AGENTS.md").read_bytes()


def test_early_conflict_creates_no_temp(
    snapshot: CatalogSnapshot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _copy("AGENTS.md", tmp_path)

    def unexpected_temp(*_args: object, **_kwargs: object) -> tuple[int, str]:
        raise AssertionError("early conflict created a temp file")

    monkeypatch.setattr(write_module.tempfile, "mkstemp", unexpected_temp)
    result = save_source(
        snapshot,
        tmp_path,
        "managed:repo-agents",
        "0" * 64,
        target.read_text(encoding="utf-8"),
    )

    assert result == SourceConflict(
        status="conflict",
        detail="Source changed on disk. The workbench did not overwrite it.",
    )


def test_late_conflict_after_temp_preparation_cleans_temp_without_replacement(
    snapshot: CatalogSnapshot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _copy("AGENTS.md", tmp_path)
    original = target.read_bytes()
    external = original.replace(
        b"*Conventions for working", b"*External conventions for working", 1
    )
    real_mkstemp = write_module.tempfile.mkstemp

    def mutate_after_temp(*, prefix: str, suffix: str, dir: Path) -> tuple[int, str]:
        created = real_mkstemp(prefix=prefix, suffix=suffix, dir=dir)
        target.write_bytes(external)
        return created

    monkeypatch.setattr(write_module.tempfile, "mkstemp", mutate_after_temp)
    result = save_source(
        snapshot,
        tmp_path,
        "managed:repo-agents",
        hashlib.sha256(original).hexdigest(),
        original.decode("utf-8").replace(
            "*Conventions for working", "*Reviewed conventions for working", 1
        ),
    )

    assert isinstance(result, SourceConflict)
    assert target.read_bytes() == external
    assert [path for path in tmp_path.iterdir() if path.name.endswith(".tmp")] == []
