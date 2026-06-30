"""`perk learn docs-sync` / `docs-check` CLI surfaces (contracts.md §8.35, node 6.1)."""

import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk.cli.cli import cli


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _doc(root: Path, category: str, slug: str, *, read_when: str = "When you touch X.") -> None:
    path = root / "docs" / "learned" / category / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\ntitle: T\nread_when: {read_when}\n---\n\n# Doc\n", encoding="utf-8")


# --- docs-sync ------------------------------------------------------------------------------------


def test_docs_sync_json_envelope_and_write():
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        _doc(Path(d), "workflow", "a")
        result = runner.invoke(cli, ["learn", "docs-sync", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert set(data) == {
            "success",
            "error_type",
            "message",
            "written",
            "unchanged",
            "dry_run",
        }
        assert data["success"] is True and data["dry_run"] is False
        assert set(data["written"]) == {".pi/APPEND_SYSTEM.md", "docs/learned/index.md"}
        assert (Path(d) / "docs" / "learned" / "index.md").exists()


def test_docs_sync_dry_run_writes_nothing():
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        _doc(Path(d), "workflow", "a")
        result = runner.invoke(cli, ["learn", "docs-sync", "--dry-run", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["dry_run"] is True
        assert set(data["written"]) == {".pi/APPEND_SYSTEM.md", "docs/learned/index.md"}
        assert not (Path(d) / "docs" / "learned" / "index.md").exists()
        assert not (Path(d) / ".pi" / "APPEND_SYSTEM.md").exists()


def test_docs_sync_not_a_repo_exits_2():
    runner = CliRunner()
    with runner.isolated_filesystem():  # no git init
        result = runner.invoke(cli, ["learn", "docs-sync", "--json"])
        assert result.exit_code == 2
        assert json.loads(result.output)["error_type"] == "not_a_repo"


# --- docs-check -----------------------------------------------------------------------------------


def test_docs_check_fresh_exits_0():
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        _doc(Path(d), "workflow", "a")
        assert runner.invoke(cli, ["learn", "docs-sync"]).exit_code == 0
        result = runner.invoke(cli, ["learn", "docs-check", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["fresh"] is True and data["stale_files"] == []
        assert set(data) == {
            "success",
            "error_type",
            "message",
            "fresh",
            "stale_files",
            "missing_frontmatter",
            "source_code_blocks",
            "duplicate_read_when",
            "stale_pointers",
            "broken_doc_paths",
        }


def test_docs_check_stale_exits_1():
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        _doc(Path(d), "workflow", "a")  # never synced → stale
        result = runner.invoke(cli, ["learn", "docs-check", "--json"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["fresh"] is False
        assert set(data["stale_files"]) == {".pi/APPEND_SYSTEM.md", "docs/learned/index.md"}


def test_docs_check_not_a_repo_exits_2():
    runner = CliRunner()
    with runner.isolated_filesystem():  # no git init
        result = runner.invoke(cli, ["learn", "docs-check", "--json"])
        assert result.exit_code == 2
        assert json.loads(result.output)["error_type"] == "not_a_repo"


def test_docs_check_human_path_renders_headline():
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        _doc(Path(d), "workflow", "a")
        runner.invoke(cli, ["learn", "docs-sync"])
        result = runner.invoke(cli, ["learn", "docs-check"])
        assert result.exit_code == 0
        assert "fresh" in result.output and "hygiene" in result.output
