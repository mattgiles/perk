"""`perk learn docs-sync` / `docs-check` CLI surfaces (contracts.md §8.35, node 6.1)."""

import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk.cli.cli import cli


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _doc(
    root: Path,
    category: str,
    slug: str,
    *,
    read_when: str = "When you touch X.",
    cluster: str | None = None,
) -> None:
    path = root / "docs" / "learned" / category / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    front = f"---\ntitle: T\nread_when: {read_when}\n"
    if cluster is not None:
        front += f"cluster: {cluster}\n"
    path.write_text(front + "---\n\n# Doc\n", encoding="utf-8")


def _registry(root: Path, *defs: tuple[str, str]) -> Path:
    path = root / "docs" / "learned" / "clusters.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["clusters:"]
    for cid, rollup in defs:
        lines.append(f"  - id: {cid}")
        lines.append(f'    rollup: "{rollup}"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


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
            "overlong_cues",
            "cue_hazards",
            "registry_error",
            "cluster_issues",
            "empty_clusters",
            "overlong_rollups",
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


def test_docs_check_fresh_but_overlong_cue_exits_1():
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        _doc(Path(d), "workflow", "a", read_when="x" * 201)
        assert runner.invoke(cli, ["learn", "docs-sync"]).exit_code == 0
        result = runner.invoke(cli, ["learn", "docs-check", "--json"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["fresh"] is True  # the artifacts are current — the cue budget alone gates
        assert data["overlong_cues"] == [{"doc": "docs/learned/workflow/a.md", "length": 201}]
        assert data["cue_hazards"] == []


def test_docs_check_cue_hazard_exits_1():
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        _doc(Path(d), "workflow", "a", read_when="Fixes #123 the widget.")
        assert runner.invoke(cli, ["learn", "docs-sync"]).exit_code == 0
        result = runner.invoke(cli, ["learn", "docs-check", "--json"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["cue_hazards"] == [
            {"doc": "docs/learned/workflow/a.md", "hazard": "space-hash"}
        ]


def test_docs_check_human_render_lists_cue_violations():
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        _doc(Path(d), "workflow", "long", read_when="x" * 201)
        _doc(Path(d), "workflow", "hazard", read_when="Fixes #123 the widget.")
        runner.invoke(cli, ["learn", "docs-sync"])
        result = runner.invoke(cli, ["learn", "docs-check"])
        assert result.exit_code == 1
        assert (
            "cue over budget: docs/learned/workflow/long.md — 201 chars (max 200)" in result.output
        )
        assert "cue hazard: docs/learned/workflow/hazard.md — space-hash" in result.output
        assert "fix the frontmatter" in result.output


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


# --- the cluster registry (CLI surfaces) ----------------------------------------------------------


def test_docs_sync_invalid_registry_exits_1_and_writes_nothing():
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        _doc(Path(d), "workflow", "a")
        (Path(d) / "docs" / "learned" / "clusters.yaml").write_text(
            "clusters: []\n", encoding="utf-8"
        )
        result = runner.invoke(cli, ["learn", "docs-sync", "--json"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        # The standard fail envelope, artifacts untouched.
        assert data["success"] is False
        assert data["error_type"] == "invalid_cluster_registry"
        assert "`clusters` is empty" in data["message"]
        assert data["dry_run"] is False
        assert not (Path(d) / ".pi" / "APPEND_SYSTEM.md").exists()
        assert not (Path(d) / "docs" / "learned" / "index.md").exists()


def test_docs_sync_registry_mode_renders_cluster_lines():
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        _doc(Path(d), "workflow", "a", cluster="alpha")
        _registry(Path(d), ("alpha", "A rollup."))
        result = runner.invoke(cli, ["learn", "docs-sync", "--json"])
        assert result.exit_code == 0
        append = (Path(d) / ".pi" / "APPEND_SYSTEM.md").read_text(encoding="utf-8")
        assert "- **alpha** — A rollup. (workflow/a)" in append


def test_docs_check_registry_error_exits_1():
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        _doc(Path(d), "workflow", "a", cluster="alpha")
        _registry(Path(d), ("alpha", "A rollup."))
        assert runner.invoke(cli, ["learn", "docs-sync"]).exit_code == 0
        (Path(d) / "docs" / "learned" / "clusters.yaml").write_text(
            "clusters: not-a-list\n", encoding="utf-8"
        )
        result = runner.invoke(cli, ["learn", "docs-check", "--json"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert "`clusters` is not a list" in data["registry_error"]
        assert data["fresh"] is True  # the routing/catalog freshness comparison is skipped


def test_docs_check_cluster_issue_exits_1():
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        _doc(Path(d), "workflow", "a", cluster="alpha")
        _doc(Path(d), "workflow", "bare")
        _registry(Path(d), ("alpha", "A rollup."))
        assert runner.invoke(cli, ["learn", "docs-sync"]).exit_code == 0
        result = runner.invoke(cli, ["learn", "docs-check", "--json"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["cluster_issues"] == [
            {"doc": "docs/learned/workflow/bare.md", "cluster": None, "problem": "missing"}
        ]


def test_docs_check_empty_cluster_exits_1():
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        _doc(Path(d), "workflow", "a", cluster="alpha")
        _registry(Path(d), ("alpha", "A rollup."), ("hollow", "No members."))
        assert runner.invoke(cli, ["learn", "docs-sync"]).exit_code == 0
        result = runner.invoke(cli, ["learn", "docs-check", "--json"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["empty_clusters"] == ["hollow"]


def test_docs_check_overlong_rollup_exits_1():
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        _doc(Path(d), "workflow", "a", cluster="alpha")
        _registry(Path(d), ("alpha", "x" * 161))
        assert runner.invoke(cli, ["learn", "docs-sync"]).exit_code == 0
        result = runner.invoke(cli, ["learn", "docs-check", "--json"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["overlong_rollups"] == [{"cluster": "alpha", "length": 161}]


def test_docs_check_human_render_lists_cluster_violations():
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        _doc(Path(d), "workflow", "a", cluster="alpha")
        _doc(Path(d), "workflow", "bare")
        _doc(Path(d), "pi", "ghosted", cluster="ghost")
        _registry(Path(d), ("alpha", "x" * 161), ("hollow", "No members."))
        runner.invoke(cli, ["learn", "docs-sync"])
        result = runner.invoke(cli, ["learn", "docs-check"])
        assert result.exit_code == 1
        assert "cluster missing: docs/learned/workflow/bare.md" in result.output
        assert "cluster unknown: docs/learned/pi/ghosted.md" in result.output
        assert "empty cluster: hollow" in result.output
        assert "rollup over budget: alpha — 161 chars (max 160)" in result.output


def test_docs_check_registry_mode_clean_exits_0():
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        _doc(Path(d), "workflow", "a", cluster="alpha")
        _registry(Path(d), ("alpha", "A rollup."))
        assert runner.invoke(cli, ["learn", "docs-sync"]).exit_code == 0
        result = runner.invoke(cli, ["learn", "docs-check", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["registry_error"] is None
        assert data["cluster_issues"] == []
        assert data["empty_clusters"] == []
        assert data["overlong_rollups"] == []
