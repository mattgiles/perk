import dataclasses
import json
import subprocess
from pathlib import Path

from _pr_feedback_fixtures import mixed_feedback
from click.testing import CliRunner

from perk import github, plan
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


def _invoke_with(monkeypatch, feedback: github.PrFeedback):
    monkeypatch.setattr(
        github,
        "find_pr_for_branch",
        lambda **k: github.PullRequest(
            number=42, url="u", is_draft=False, state="OPEN", existed=True
        ),
    )
    monkeypatch.setattr(github, "get_pr_feedback", lambda **k: feedback)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), _REF)
        return runner.invoke(cli, ["pr", "feedback", "--json"])


def test_feedback_mixed_payload_flags_and_counts(monkeypatch):
    result = _invoke_with(monkeypatch, mixed_feedback())
    assert result.exit_code == 0
    data = json.loads(result.output)
    flags = [(t["thread_id"], t["is_resolved"], t["is_outdated"]) for t in data["review_threads"]]
    assert flags == [
        ("PRRT_open", False, False),
        ("PRRT_resolved", True, False),
        ("PRRT_outdated", False, True),
    ]
    assert data["review_threads"][2]["comments"][0]["comment_id"] is None
    assert data["review_threads"][2]["comments"][0]["author"] is None
    assert [c["comment_id"] for c in data["discussion_comments"]] == [7, 8]
    assert data["counts"] == {
        "review_threads": 3,
        "unresolved_threads": 2,
        "discussion_comments": 2,
        "reviews": 1,
    }


def test_feedback_duplicate_thread_id_refused(monkeypatch):
    fb = mixed_feedback()
    dup = dataclasses.replace(fb.review_threads[1], thread_id="PRRT_open")
    feedback = dataclasses.replace(
        fb, review_threads=(fb.review_threads[0], dup, fb.review_threads[2])
    )
    result = _invoke_with(monkeypatch, feedback)
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["error_type"] == "duplicate_feedback_id"
    assert "PRRT_open" in data["message"]


def test_feedback_duplicate_discussion_comment_id_refused(monkeypatch):
    fb = mixed_feedback()
    dup = dataclasses.replace(fb.discussion_comments[1], comment_id=7)
    feedback = dataclasses.replace(fb, discussion_comments=(fb.discussion_comments[0], dup))
    result = _invoke_with(monkeypatch, feedback)
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["error_type"] == "duplicate_feedback_id"
    assert "comments [7]" in data["message"]


def test_feedback_duplicate_review_id_is_outside_the_coverage_set(monkeypatch):
    fb = mixed_feedback()
    feedback = dataclasses.replace(fb, reviews=(fb.reviews[0], fb.reviews[0]))
    result = _invoke_with(monkeypatch, feedback)
    assert result.exit_code == 0
    assert json.loads(result.output)["counts"]["reviews"] == 2
