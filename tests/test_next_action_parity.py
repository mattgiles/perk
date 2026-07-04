"""Cross-surface parity for the shared next-action classifier (contracts.md §8.37).

For the same canonical plan state, `perk plan resume --dry-run --json` and
`perk objective run --dry-run --json` must report the **same** `next_action` — the parity
guarantee that motivated extracting `resume.resolve_next_action`. Every backend read
(`plans.get_plan` / `objectives.get_objective` / `github.get_pr_feedback` / auth) is faked;
launching is forbidden outright.
"""

import json
import subprocess

import pytest
from click.testing import CliRunner

from perk import github, objective
from perk.backends.github import objectives, plans
from perk.cli.cli import cli
from perk.run import launch, resume

N = objective.NodeStatus


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _pr(*, state="OPEN", is_draft=False) -> github.PullRequest:
    return github.PullRequest(
        number=55, url="u/pr/55", is_draft=is_draft, state=state, existed=True
    )


def _feedback(*, threads=(), reviews=()) -> github.PrFeedback:
    return github.PrFeedback(
        pr_number=55, review_threads=tuple(threads), discussion_comments=(), reviews=tuple(reviews)
    )


_ACTIONABLE = _feedback(
    threads=(
        github.ReviewThread(
            thread_id="T", is_resolved=False, is_outdated=False, path=None, line=None, comments=()
        ),
    )
)
_CLEAN = _feedback(
    reviews=(
        github.Review(
            review_id="R", author="alice", body="", state="APPROVED", submitted_at="2024-01-01"
        ),
    )
)


def _objective_state() -> objectives.ObjectiveState:
    nodes = (
        objective.ObjectiveNode(
            id="1.1", description="B", status=N.IN_PROGRESS, pr="#7", depends_on=()
        ),
    )
    return objectives.ObjectiveState(number=137, url="u/137", title="O", header={}, nodes=nodes)


def _last_json_line(output: str) -> dict:
    line = [ln for ln in output.splitlines() if ln.strip()][-1]
    return json.loads(line)


# The seven distinguished plan states → the shared verdict both surfaces must report.
@pytest.mark.parametrize(
    ("pr", "header", "feedback", "expected"),
    [
        (None, {}, None, "implement"),
        (_pr(state="MERGED"), {"learn_state": "pending"}, None, "learn"),
        (_pr(state="MERGED"), {"learn_state": "captured"}, None, "done"),
        (_pr(state="CLOSED"), {}, None, "pr_closed"),
        (_pr(is_draft=True), {}, None, "ready_for_review"),
        (_pr(), {}, _ACTIONABLE, "address"),
        (_pr(), {}, _CLEAN, "awaiting_review"),
    ],
)
def test_both_dry_runs_report_the_same_next_action(monkeypatch, pr, header, feedback, expected):
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(True, "octocat", ("repo",), None)
    )
    monkeypatch.setattr(
        plans,
        "get_plan",
        lambda **k: plans.PlanState(number=7, url="u/7", title="P", header=header, pr=pr),
    )
    monkeypatch.setattr(objectives, "get_objective", lambda **k: _objective_state())
    if feedback is not None:
        monkeypatch.setattr(github, "get_pr_feedback", lambda **k: feedback)

    def boom(**k):
        raise AssertionError("dry-run parity must never launch")

    monkeypatch.setattr(launch, "launch_stage", boom)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        resume_result = runner.invoke(cli, ["plan", "resume", "7", "--dry-run", "--json"])
        assert resume_result.exit_code == 0, resume_result.output
        resume_payload = json.loads(resume_result.stdout)
        run_result = runner.invoke(cli, ["objective", "run", "137", "--dry-run", "--json"])
        assert run_result.exit_code == 0, run_result.output
        run_payload = _last_json_line(run_result.output)
    assert resume_payload["next_action"] == expected
    assert run_payload["next_action"] == expected

    # Stage-selection parity (contracts.md §8.38): the two surfaces must pick the SAME stage,
    # not merely the same verdict — except the one named divergence below.
    expected_stage = resume.NextAction(expected).stage_id
    if expected == "learn":
        # Named divergence (§8.38): resume launches learn locally; the supervisor never
        # dispatches it (learn has no remote door) — it emits a `perk plan resume` remediation.
        assert resume_payload["resumed_stage"] == "learn"
        assert run_payload["stage"] is None
        assert "perk plan resume" in run_payload["remediation"]
    elif expected_stage is not None:  # implement / address: both select the verdict's stage
        assert resume_payload["resumed_stage"] == expected_stage
        assert run_payload["stage"] == expected_stage
    else:  # gate/terminal verdicts: neither surface selects a stage
        assert resume_payload["resumed_stage"] is None
        assert run_payload["stage"] is None
