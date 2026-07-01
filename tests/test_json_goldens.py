"""Golden byte-identity tests for the nine in-scope ``--json`` OUTPUT envelopes.

Each test builds a fully-populated (or nullable-arm) domain result with the dataclass
constructor (trusted typed values — no Pydantic coercion), calls the envelope's ``--json``
builder, and asserts the result equals a committed snapshot. The snapshots were generated
from the *pre-swap* hand-rolled builders, so a green run after the swap to ``OutputModel``s
proves the serialized keys stayed byte-identical.

Regen all snapshots with ``PERK_UPDATE_GOLDEN=1 uv run pytest tests/test_json_goldens.py``.
"""

from _golden import assert_golden

# --- init report --------------------------------------------------------------------------


def _init_report_full():
    from perk.backends import linear
    from perk.convergence.env import EnvCheck
    from perk.convergence.init.report import GitHubReport, InitReport, LinearReport
    from perk.github import AuthStatus, RepoAccess

    return InitReport(
        ok=True,
        mode="github",
        env=[
            EnvCheck(name="node", ok=True, detail="v22.19.0", remediation=""),
            EnvCheck(name="gh", ok=False, detail="missing", remediation="brew install gh"),
        ],
        changes=["wrote .perk/config.toml", "wrote .gitignore"],
        github=GitHubReport(
            auth=AuthStatus(ok=True, user="mat", scopes=("repo", "read:org"), error=None),
            repo=RepoAccess(ok=True, repo="owner/repo", can_push=True, error=None),
        ),
        handoff=".perk/workflow/post-init.md",
        capabilities=("settings-wiring", "workflow-dir"),
        error_type=None,
        message=None,
        linear=LinearReport(
            readiness=linear.LinearReadiness(
                auth_ok=True,
                user="Mat",
                team_ok=True,
                missing_labels=("perk:learn",),
                created_labels=("perk:plan",),
                error=None,
            ),
            team="ENG",
            error=None,
            project=linear.LinearProjectReadiness(
                projects_ok=True,
                projects_error=None,
                missing_state_types=("canceled",),
                states_error=None,
            ),
        ),
        warnings=["untracked: docs/foo.md"],
    )


def _init_report_minimal():
    from perk.convergence.env import EnvCheck
    from perk.convergence.init.report import InitReport

    return InitReport(
        ok=False,
        mode="unknown",
        env=[EnvCheck(name="git", ok=False, detail="not a repo", remediation="git init")],
        changes=[],
        github=None,
        handoff=None,
        capabilities=(),
        error_type="not_a_repo",
        message="Not a git repository",
        linear=None,
        warnings=[],
    )


def test_golden_init_report_full() -> None:
    from perk.convergence.init.report import report_to_dict

    assert_golden("init_report", report_to_dict(_init_report_full()))


def test_golden_init_report_minimal() -> None:
    from perk.convergence.init.report import report_to_dict

    assert_golden("init_report_minimal", report_to_dict(_init_report_minimal()))


# --- doctor report ------------------------------------------------------------------------


def _doctor_report_full():
    from perk.convergence.doctor.data import Check, DoctorReport

    return DoctorReport(
        checks=[
            Check("settings-wiring", "package", "ok", "wired"),
            Check("github", "github", "warn", "unauthed", detail="gh not logged in"),
            Check("node", "env", "info", "optional", remediation="install node"),
            Check("registry", "repository", "fail", "drift", detail="d", remediation="r"),
        ],
        fixed=["re-converged settings-wiring"],
        self_repo=True,
        error_type=None,
        message=None,
        fix_errors=["skills sync failed"],
    )


def test_golden_doctor_report() -> None:
    from perk.convergence.doctor import report_to_dict

    assert_golden("doctor_report", report_to_dict(_doctor_report_full()))


# --- plan save ----------------------------------------------------------------------------


def _plan_ref():
    from perk import plan

    return plan.PlanRef(
        provider="github",
        pr_id="123",
        url="https://github.com/o/r/issues/123",
        labels=("perk:plan",),
        objective_id="63",
        consumed_learn=("45",),
        base="main",
    )


def _plan_save_result(*, with_node: bool):
    from perk.backends import issue_backend
    from perk.cli.commands.plan.save_cmd import ObjectiveNodeLink, PlanSaveResult

    return PlanSaveResult(
        issue=issue_backend.IssueRef(
            id="123", url="https://github.com/o/r/issues/123", existed=False
        ),
        plan_ref=_plan_ref(),
        issue_body="<header>",
        body_comment="<body>",
        dry_run=False,
        cached=True,
        updated=False,
        objective_node=(
            ObjectiveNodeLink(linked=True, node="1.1", status="in_progress", error=None)
            if with_node
            else None
        ),
    )


def test_golden_plan_save_with_node() -> None:
    from perk.cli.commands.plan.save_cmd import _result_to_dict

    assert_golden("plan_save", _result_to_dict(_plan_save_result(with_node=True)))


def test_golden_plan_save_no_node() -> None:
    from perk.cli.commands.plan.save_cmd import _result_to_dict

    assert_golden("plan_save_no_node", _result_to_dict(_plan_save_result(with_node=False)))


# --- pr submit / ready / land / feedback / review-context ---------------------------------


def _pull_request():
    from perk import github

    return github.PullRequest(
        number=42,
        url="https://github.com/o/r/pull/42",
        is_draft=True,
        state="OPEN",
        existed=False,
        base_ref="main",
    )


def _pr_submit_result():
    from perk.backends import issue_backend
    from perk.cli.commands.pr.submit_cmd import PrSubmitResult

    return PrSubmitResult(
        pr=_pull_request(),
        branch="plan-42",
        issue="42",
        header_update=issue_backend.PlanHeaderUpdate(
            fields_updated=("branch", "pr", "lifecycle_stage"), dry_run=False
        ),
        plan_embedded=True,
        pr_checked=True,
        dry_run=False,
        base="main",
        mergeable=False,
        conflicts=("perk/foo.py", "perk/bar.py"),
    )


def _pr_ready_result():
    from perk.cli.commands.pr.ready_cmd import PrReadyResult

    return PrReadyResult(pr=_pull_request(), was_draft=True, dry_run=False)


def _pr_land_result():
    from perk.cli.commands.pr.land_cmd import (
        LearnConsumeUpdate,
        ObjectiveLandUpdate,
        PrLandResult,
    )

    return PrLandResult(
        pr=_pull_request(),
        branch="plan-42",
        issue="42",
        pending_learn=True,
        dry_run=False,
        objective=ObjectiveLandUpdate(
            objective="63", nodes_marked=("1.1", "1.2"), skipped_reason=None, closed=True
        ),
        learn=LearnConsumeUpdate(closed=("45",), skipped_reason=None),
        plan_issue_closed=True,
    )


def _pr_feedback_result():
    from perk import github
    from perk.cli.commands.pr.feedback_cmd import PrFeedbackResult

    feedback = github.PrFeedback(
        pr_number=42,
        review_threads=(
            github.ReviewThread(
                thread_id="PRRT_1",
                is_resolved=False,
                is_outdated=False,
                path="perk/foo.py",
                line=10,
                comments=(
                    github.ReviewComment(
                        comment_id=100,
                        body="nit",
                        author="reviewer",
                        path="perk/foo.py",
                        line=10,
                        created_at="2026-01-01T00:00:00Z",
                    ),
                ),
            ),
        ),
        discussion_comments=(
            github.DiscussionComment(
                comment_id=200,
                body="overall looks good",
                author="reviewer",
                created_at="2026-01-01T00:00:00Z",
            ),
        ),
        reviews=(
            github.Review(
                review_id="PRR_1",
                author="reviewer",
                body="changes please",
                state="CHANGES_REQUESTED",
                submitted_at="2026-01-01T00:00:00Z",
            ),
        ),
    )
    return PrFeedbackResult(feedback=feedback, branch="plan-42")


def _pr_review_context_result():
    from perk import github
    from perk.cli.commands.pr.review_context_cmd import PrReviewContextResult

    context = github.PrReviewContext(
        pr_number=42,
        base_ref="main",
        head_ref="plan-42",
        title="My PR",
        body="PR body",
        diff="diff --git a/x b/x\n",
        plan_body="# Plan\n",
    )
    return PrReviewContextResult(context=context, branch="plan-42")


def test_golden_pr_submit() -> None:
    from perk.cli.commands.pr.submit_cmd import _result_to_dict

    assert_golden("pr_submit", _result_to_dict(_pr_submit_result()))


def test_golden_pr_ready() -> None:
    from perk.cli.commands.pr.ready_cmd import _result_to_dict

    assert_golden("pr_ready", _result_to_dict(_pr_ready_result()))


def test_golden_pr_land() -> None:
    from perk.cli.commands.pr.land_cmd import _result_to_dict

    assert_golden("pr_land", _result_to_dict(_pr_land_result()))


def test_golden_pr_feedback() -> None:
    from perk.cli.commands.pr.feedback_cmd import _result_to_dict

    assert_golden("pr_feedback", _result_to_dict(_pr_feedback_result()))


def test_golden_pr_review_context() -> None:
    from perk.cli.commands.pr.review_context_cmd import _result_to_dict

    assert_golden("pr_review_context", _result_to_dict(_pr_review_context_result()))


# --- learn capture ------------------------------------------------------------------------


def _learn_capture_result(*, dry_run: bool):
    from perk.backends import issue_backend
    from perk.cli.commands.learn.capture_cmd import LearnCaptureResult

    return LearnCaptureResult(
        learn_issue=issue_backend.IssueRef(
            id="77", url="https://github.com/o/r/issues/77", existed=False
        ),
        plan_issue="42",
        commented=not dry_run,
        pending_cleared=not dry_run,
        dry_run=dry_run,
    )


def test_golden_learn_capture() -> None:
    from perk.cli.commands.learn.capture_cmd import _result_to_dict

    assert_golden("learn_capture", _result_to_dict(_learn_capture_result(dry_run=False)))


def test_golden_learn_capture_dry_run() -> None:
    from perk.cli.commands.learn.capture_cmd import _result_to_dict

    assert_golden("learn_capture_dry_run", _result_to_dict(_learn_capture_result(dry_run=True)))
