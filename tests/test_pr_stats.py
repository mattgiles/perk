"""`perk pr stats` — base precedence, the fetch flag, the envelope, and the failure arms."""

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from perk import plan
from perk.cli.cli import cli
from perk.cli.commands.pr import stats_cmd
from perk.delivery import change_stats
from perk.state import cache

_STATS = change_stats.ChangeStats(
    base="a" * 40,
    head="b" * 40,
    rows=(
        change_stats.RowStats("code", "Code", 12, 3, 1),
        change_stats.RowStats("tests", "Tests", 0, 0, 0),
        change_stats.RowStats("comments", "Comments", 2, 0, 0),
        change_stats.RowStats("learned_docs", "Learned docs", 0, 0, 0),
        change_stats.RowStats("other", "Other", 0, 0, 0),
    ),
)
_REF = {
    "provider": "github",
    "pr_id": "7",
    "url": "https://gh/o/r/issues/7",
    "labels": ["perk:plan"],
    "objective_id": None,
}


def _stub(monkeypatch, *, error: change_stats.ChangeStatsUnavailable | None = None) -> dict:
    seen: dict[str, object] = {}

    def _resolve(root, *, base, fetch):
        seen.update(base=base, fetch=fetch)
        if error is not None:
            raise error
        return change_stats.DiffRange(base="a" * 40, head="b" * 40, base_ref=f"origin/{base}")

    def _summarize(root, base, head):
        seen["range"] = (base, head)
        return _STATS

    monkeypatch.setattr(stats_cmd.change_stats, "resolve_range", _resolve)
    monkeypatch.setattr(stats_cmd.change_stats, "summarize", _summarize)
    monkeypatch.setattr(stats_cmd.git, "detect_trunk_branch", lambda root: "trunk")
    return seen


def _invoke(args: list[str], *, ref: dict | None = None, repo: bool = True):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        if repo:
            subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        if ref is not None:
            cache.write_plan_ref(Path(d), plan.PlanRefModel.model_validate(ref).to_domain())
        return runner.invoke(cli, ["pr", "stats", *args])


@pytest.mark.parametrize(
    ("args", "ref", "expected"),
    [
        (["--base", "explicit"], {**_REF, "base": "develop"}, "explicit"),
        ([], {**_REF, "base": "develop"}, "develop"),
        ([], {**_REF, "base": "  "}, "trunk"),
        ([], None, "trunk"),
    ],
)
def test_base_precedence(monkeypatch, args, ref, expected):
    seen = _stub(monkeypatch)
    result = _invoke([*args, "--json"], ref=ref)
    assert result.exit_code == 0, result.output
    assert seen["base"] == expected
    assert seen["fetch"] is False  # offline by default
    assert seen["range"] == ("a" * 40, "b" * 40)


def test_fetch_flag_threads_through(monkeypatch):
    seen = _stub(monkeypatch)
    result = _invoke(["--fetch", "--json"])
    assert result.exit_code == 0, result.output
    assert seen["fetch"] is True


def test_json_envelope(monkeypatch):
    _stub(monkeypatch)
    result = _invoke(["--json", "--base", "main"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data == {
        "success": True,
        "error_type": None,
        "message": None,
        "base_ref": "origin/main",
        "stats": change_stats.ChangeStatsOut.from_domain(_STATS).model_dump(mode="json"),
    }


def test_human_render(monkeypatch):
    _stub(monkeypatch)
    result = _invoke(["--base", "main"])
    assert result.exit_code == 0, result.output
    assert "change stats vs origin/main (aaaaaaa..bbbbbbb)" in result.stderr
    assert "Code          +12     \u22123      ~1" in result.stderr
    assert "Tests" not in result.stderr  # zero rows are hidden


@pytest.mark.parametrize("kind", ["cloc_missing", "cloc_failed", "range_unresolved", "git_failed"])
def test_unavailable_exits_1_with_the_kind(monkeypatch, kind):
    _stub(monkeypatch, error=change_stats.ChangeStatsUnavailable(kind, "nope"))
    result = _invoke(["--json"])
    assert result.exit_code == 1
    data = json.loads(result.stdout)
    assert data["success"] is False
    assert data["error_type"] == kind
    assert data["message"] == "change stats unavailable\nnope"


def test_not_a_repo_exits_2():
    result = _invoke(["--json"], repo=False)
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error_type"] == "not_a_repo"
