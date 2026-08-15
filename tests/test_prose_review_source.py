"""The seeded whole-file SourceAdapter: containment, membership, text-only decode."""

from pathlib import Path

import pytest
from perk_dev.prose_map.catalog import build_catalog
from perk_dev.prose_map.models import Candidate, RoutedUnit
from perk_dev.prose_review.catalog import CatalogSnapshot
from perk_dev.prose_review.source_adapter import (
    SourceReadError,
    read_unit_file,
    read_whole_file,
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
