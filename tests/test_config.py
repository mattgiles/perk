from pathlib import Path

from perk.config import load_config


def _write(repo: Path, name: str, text: str) -> None:
    pi = repo / ".pi"
    pi.mkdir(parents=True, exist_ok=True)
    (pi / name).write_text(text, encoding="utf-8")


def test_defaults_when_absent(tmp_path):
    assert load_config(tmp_path).worktree_root == tmp_path / ".worktrees"


def test_relative_root_resolves_against_repo(tmp_path):
    _write(tmp_path, "perk.toml", '[worktree]\nroot = "wt"\n')
    assert load_config(tmp_path).worktree_root == tmp_path / "wt"


def test_local_overrides_committed(tmp_path):
    _write(tmp_path, "perk.toml", '[worktree]\nroot = "wt"\n')
    _write(tmp_path, "perk.local.toml", '[worktree]\nroot = "local-wt"\n')
    assert load_config(tmp_path).worktree_root == tmp_path / "local-wt"


def test_absolute_root_preserved(tmp_path):
    _write(tmp_path, "perk.toml", '[worktree]\nroot = "/abs/wt"\n')
    assert load_config(tmp_path).worktree_root == Path("/abs/wt")
