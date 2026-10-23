"""Isolated install-root staging: clonefile, the hardlink tier, the depth-<=1 detach rule."""

import os
import shutil
import stat
import sys
from pathlib import Path

import pytest

from perk.substrate import fsclone
from perk.substrate.fsclone import clone_tree, detach_shared_files

DEPTH_LE_ONE = ("package.json", "package-lock.json", "node_modules/.hidden-lock")
PACKAGE_FILE = "node_modules/pkg/package.json"


def _seed_install_root(root: Path) -> Path:
    """A small npm install root: depth<=1 metadata, one package, symlinks at both depths."""
    (root / "node_modules" / "pkg" / "lib").mkdir(parents=True)
    (root / "package.json").write_text('{"dependencies": {"pkg": "1.0.0"}}\n', encoding="utf-8")
    (root / "package-lock.json").write_text('{"lockfileVersion": 3}\n', encoding="utf-8")
    (root / "package-lock.json").chmod(0o640)
    (root / "node_modules" / ".hidden-lock").write_text("hidden\n", encoding="utf-8")
    (root / PACKAGE_FILE).write_text('{"name": "pkg", "version": "1.0.0"}\n', encoding="utf-8")
    (root / "node_modules" / "pkg" / "lib" / "index.js").write_text("// pkg\n", encoding="utf-8")
    (root / "settings-link").symlink_to("package.json")
    (root / "node_modules" / "alias").symlink_to("pkg")
    return root


def _hardlinked_copy(src: Path, dst: Path) -> Path:
    shutil.copytree(src, dst, symlinks=True, copy_function=os.link)
    return dst


def _files(root: Path) -> list[str]:
    return sorted(
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    )


# --- detach_shared_files ---------------------------------------------------------------------


def test_detach_gives_depth_le_one_files_their_own_inodes(tmp_path: Path) -> None:
    src = _seed_install_root(tmp_path / "src")
    dst = _hardlinked_copy(src, tmp_path / "dst")
    assert detach_shared_files(dst) == len(DEPTH_LE_ONE)
    for relative in DEPTH_LE_ONE:
        detached, original = dst / relative, src / relative
        assert detached.stat().st_nlink == 1, relative
        assert detached.stat().st_ino != original.stat().st_ino, relative
        assert detached.read_bytes() == original.read_bytes(), relative
        assert stat.S_IMODE(detached.stat().st_mode) == stat.S_IMODE(original.stat().st_mode)
    before = (src / "package.json").read_bytes()
    (dst / "package.json").write_text("{}\n", encoding="utf-8")
    assert (src / "package.json").read_bytes() == before


def test_detach_leaves_package_files_and_symlinks_alone(tmp_path: Path) -> None:
    src = _seed_install_root(tmp_path / "src")
    dst = _hardlinked_copy(src, tmp_path / "dst")
    detach_shared_files(dst)
    assert (dst / PACKAGE_FILE).stat().st_ino == (src / PACKAGE_FILE).stat().st_ino
    assert (dst / "settings-link").is_symlink()
    assert (dst / "settings-link").readlink() == Path("package.json")
    assert (dst / "node_modules" / "alias").is_symlink()
    assert not list(dst.rglob("*.perk-detach"))  # no temp residue


def test_detach_is_idempotent(tmp_path: Path) -> None:
    src = _seed_install_root(tmp_path / "src")
    dst = _hardlinked_copy(src, tmp_path / "dst")
    assert detach_shared_files(dst) == 3
    assert detach_shared_files(dst) == 0


def test_detach_without_node_modules_reads_the_root_only(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "package.json").write_text("{}\n", encoding="utf-8")
    dst = tmp_path / "dst"
    dst.mkdir()
    os.link(src / "package.json", dst / "package.json")
    assert detach_shared_files(dst) == 1


# --- clone_tree ------------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform != "darwin", reason="clonefile(2) is macOS-only")
def test_clone_tree_uses_clonefile_on_macos(tmp_path: Path) -> None:
    src = _seed_install_root(tmp_path / "src")
    dst = tmp_path / "wt" / ".pi" / "npm"
    assert clone_tree(src, dst) == "clonefile"
    assert _files(dst) == _files(src)
    for relative in _files(src):
        assert (dst / relative).stat().st_ino != (src / relative).stat().st_ino, relative
        assert (dst / relative).stat().st_nlink == 1, relative
        assert (dst / relative).read_bytes() == (src / relative).read_bytes(), relative
    assert (dst / "node_modules" / "alias").is_symlink()
    before = (src / PACKAGE_FILE).read_bytes()
    (dst / PACKAGE_FILE).write_text("changed\n", encoding="utf-8")
    assert (src / PACKAGE_FILE).read_bytes() == before


def test_clone_tree_hardlink_tier(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fsclone.sys, "platform", "linux")
    src = _seed_install_root(tmp_path / "src")
    dst = tmp_path / "wt" / ".pi" / "npm"
    assert clone_tree(src, dst) == "hardlink"
    assert _files(dst) == _files(src)
    assert (dst / PACKAGE_FILE).stat().st_ino == (src / PACKAGE_FILE).stat().st_ino
    for relative in DEPTH_LE_ONE:
        assert (dst / relative).stat().st_ino != (src / relative).stat().st_ino, relative
        assert (dst / relative).stat().st_nlink == 1, relative
    assert (dst / "node_modules" / "alias").readlink() == Path("pkg")


def test_a_failed_clonefile_falls_to_the_hardlink_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fsclone.sys, "platform", "darwin")
    monkeypatch.setattr(fsclone, "_clonefile", lambda src, dst: False)
    src = _seed_install_root(tmp_path / "src")
    assert clone_tree(src, tmp_path / "dst") == "hardlink"


def test_a_failing_hardlink_tier_raises_and_leaves_no_copies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fsclone.sys, "platform", "linux")

    def no_links(src: str, dst: str) -> None:
        raise OSError(18, "Cross-device link")

    monkeypatch.setattr(fsclone.os, "link", no_links)
    src = _seed_install_root(tmp_path / "src")
    dst = tmp_path / "dst"
    with pytest.raises(OSError):
        clone_tree(src, dst)
    assert not dst.exists() or _files(dst) == []


def test_clone_tree_refuses_an_existing_destination(tmp_path: Path) -> None:
    src = _seed_install_root(tmp_path / "src")
    dst = tmp_path / "dst"
    dst.mkdir()
    with pytest.raises(FileExistsError):
        clone_tree(src, dst)
