import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk import github
from perk.cli.cli import cli
from perk.state import cache

_REF = {
    "provider": "github",
    "pr_id": "7",
    "url": "https://gh/o/r/issues/7",
    "labels": ["perk:plan"],
    "objective_id": None,
}


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _feedback() -> github.PrFeedback:
    return github.PrFeedback(
        pr_number=42,
        review_threads=(
            github.ReviewThread(
                thread_id="PRRT_1",
                is_resolved=False,
                is_outdated=False,
                path="perk/github.py",
                line=12,
                comments=(
                    github.ReviewComment(
                        comment_id=99,
                        body="rename this",
                        author="rev",
                        path="perk/github.py",
                        line=12,
                        created_at=None,
                    ),
                ),
            ),
        ),
        discussion_comments=(
            github.DiscussionComment(comment_id=7, body="nice", author="rev", created_at=None),
        ),
        reviews=(
            github.Review(
                review_id="PRR_1", author="rev", body="ok", state="APPROVED", submitted_at=None
            ),
        ),
    )


def test_feedback_success_json(monkeypatch):
    monkeypatch.setattr(
        github,
        "find_pr_for_branch",
        lambda **k: github.PullRequest(
            number=42, url="u", is_draft=False, state="OPEN", existed=True
        ),
    )
    monkeypatch.setattr(github, "get_pr_feedback", lambda **k: _feedback())
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), _REF)
        result = runner.invoke(cli, ["pr", "feedback", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["success"] is True and data["pr"] == 42 and data["branch"] == "plan-7"
    assert data["counts"]["unresolved_threads"] == 1
    assert data["review_threads"][0]["thread_id"] == "PRRT_1"
    assert data["discussion_comments"][0]["comment_id"] == 7


def test_feedback_no_plan_ref_exits_1():
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["pr", "feedback", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "no_plan_ref"


def test_feedback_no_pr_exits_1(monkeypatch):
    monkeypatch.setattr(github, "find_pr_for_branch", lambda **k: None)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), _REF)
        result = runner.invoke(cli, ["pr", "feedback", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "no_pr"


def test_feedback_not_a_repo_exits_2():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["pr", "feedback", "--json"])
    assert result.exit_code == 2
    assert json.loads(result.output)["error_type"] == "not_a_repo"


def test_feedback_github_error_exits_1(monkeypatch):
    monkeypatch.setattr(
        github,
        "find_pr_for_branch",
        lambda **k: github.PullRequest(
            number=42, url="u", is_draft=False, state="OPEN", existed=True
        ),
    )

    def _boom(**k):
        raise github.GitHubError("HTTP 500")

    monkeypatch.setattr(github, "get_pr_feedback", _boom)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), _REF)
        result = runner.invoke(cli, ["pr", "feedback", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "github_error"
