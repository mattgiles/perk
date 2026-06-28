"""`perk learn evidence` CLI surface (contracts.md §8.35, node 3.1)."""

import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk import github, plan
from perk.backends import resolve
from perk.backends.issue_backend import PlanState
from perk.cli.cli import cli
from perk.state import cache

_REF = plan.PlanRef(
    provider="github",
    pr_id="7",
    url="https://gh/o/r/issues/7",
    labels=("perk:plan",),
    objective_id=None,
)


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


class _FakeBackend:
    def __init__(self, header: dict[str, object]) -> None:
        self._header = header

    def get_plan(self, *, issue_id: str) -> PlanState:
        return PlanState(
            id=issue_id, url="u", title="Feat", header=self._header, pr=None, state="OPEN"
        )

    def get_plan_body(self, *, issue_id: str) -> str | None:
        return "PLAN BODY"


def _run(monkeypatch, *, header: dict[str, object], write_ref: bool = True):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        if write_ref:
            cache.write_plan_ref(Path(d), _REF)
        monkeypatch.setattr(resolve, "resolve_issue_backend", lambda root: _FakeBackend(header))
        monkeypatch.setattr(github, "list_prs_for_branch", lambda **k: ())
        result = runner.invoke(cli, ["learn", "evidence", "--json"])
    return result


def test_evidence_json_envelope(monkeypatch):
    result = _run(monkeypatch, header={"run_id": "01RUN_P", "impl_run_ids": []})
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert set(data) == {
        "success",
        "error_type",
        "message",
        "skipped",
        "skip_reason",
        "plan_id",
        "bundle_dir",
        "sources",
        "existing_docs",
    }
    assert data["success"] is True and data["skipped"] is False
    assert data["plan_id"] == "7"
    categories = {s["category"] for s in data["sources"]}
    assert {
        "plan",
        "pr",
        "planning-session",
        "implementation-session",
        "existing-docs",
    } <= categories
    source = data["sources"][0]
    assert set(source) == {"category", "label", "status", "artifact", "detail"}


def test_evidence_skip_arm(monkeypatch):
    result = _run(monkeypatch, header={"consumed_learn": ["12"]})
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["skipped"] is True
    assert data["sources"] == [] and data["existing_docs"] == []


def test_evidence_no_plan_ref_exits_1(monkeypatch):
    result = _run(monkeypatch, header={"run_id": "x"}, write_ref=False)
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "no_plan_ref"


def test_evidence_not_a_repo_exits_2():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["learn", "evidence", "--json"])
    assert result.exit_code == 2
    assert json.loads(result.output)["error_type"] == "not_a_repo"
