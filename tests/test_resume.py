import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from perk import github, plan
from perk.backends import issue_backend, resolve
from perk.backends.github import plans
from perk.cli.cli import cli
from perk.run import launch, resume
from perk.state import cache


def _pr(state: str, *, is_draft: bool = False) -> github.PullRequest:
    return github.PullRequest(
        number=55, url="u/pr/55", is_draft=is_draft, state=state, existed=True
    )


def _boom_feedback(_n: int) -> github.PrFeedback:
    raise AssertionError("get_feedback must only be called on the OPEN-non-draft arm")


def _feedback(*, threads=(), reviews=(), comments=()) -> github.PrFeedback:
    return github.PrFeedback(
        pr_number=55,
        review_threads=tuple(threads),
        discussion_comments=tuple(comments),
        reviews=tuple(reviews),
    )


def _thread(resolved: bool) -> github.ReviewThread:
    return github.ReviewThread(
        thread_id="T", is_resolved=resolved, is_outdated=False, path=None, line=None, comments=()
    )


def _review(author: str, state: str, submitted_at: str | None) -> github.Review:
    return github.Review(
        review_id="R", author=author, body="", state=state, submitted_at=submitted_at
    )


def _neutral_state(
    *, header: dict | None = None, pr: github.PullRequest | None = None
) -> issue_backend.PlanState:
    """The backend-neutral shape consumed by the pure resolution functions."""
    return issue_backend.PlanState(
        id="7", url="https://gh/o/r/issues/7", title="T", header=header or {}, pr=pr, state="OPEN"
    )


def _state(*, header: dict | None = None, pr: github.PullRequest | None = None) -> plans.PlanState:
    """The github-native shape returned by monkeypatched ``plans.get_plan`` fakes."""
    return plans.PlanState(
        number=7, url="https://gh/o/r/issues/7", title="T", header=header or {}, pr=pr
    )


# --- the pure resolution matrix (contracts.md §8.37) ------------------------------------

A = resume.NextAction


@pytest.mark.parametrize(
    ("state", "pending", "expected"),
    [
        (_neutral_state(header={"lifecycle_stage": "planned"}), False, A.IMPLEMENT),
        (_neutral_state(header={"lifecycle_stage": "impl"}), False, A.IMPLEMENT),  # no PR yet
        (_neutral_state(pr=_pr("MERGED")), True, A.LEARN),
        (_neutral_state(pr=_pr("MERGED")), False, A.DONE),  # merged + learned -> nothing
        # The canonical plan-header `learn_state` field wins over the local marker (§8.36):
        # `pending` resolves to learn with NO local marker (the fresh-clone acceptance) …
        (_neutral_state(header={"learn_state": "pending"}, pr=_pr("MERGED")), False, A.LEARN),
        # … and a terminal value resolves done even against a STALE local marker.
        (_neutral_state(header={"learn_state": "captured"}, pr=_pr("MERGED")), True, A.DONE),
        (_neutral_state(header={"learn_state": "skipped"}, pr=_pr("MERGED")), True, A.DONE),
        # Absent field -> the legacy marker fallback (both directions).
        (_neutral_state(header={}, pr=_pr("MERGED")), True, A.LEARN),
        (_neutral_state(header={}, pr=_pr("MERGED")), False, A.DONE),
        # An unrecognized value falls back to the marker too (here: unset -> done).
        (_neutral_state(header={"learn_state": "bogus"}, pr=_pr("MERGED")), False, A.DONE),
        # Closed unmerged — the human-attention gate (never "done").
        (_neutral_state(pr=_pr("CLOSED")), False, A.PR_CLOSED),
        # A draft PR gates on ready-for-review — feedback is never fetched.
        (_neutral_state(pr=_pr("OPEN", is_draft=True)), False, A.READY_FOR_REVIEW),
    ],
)
def test_resolve_next_action_matrix(state, pending, expected):
    # `_boom_feedback` doubles as the laziness guard: none of these arms may fetch feedback.
    assert (
        resume.resolve_next_action(state, has_pending_learn=pending, get_feedback=_boom_feedback)
        == expected
    )


def test_open_nondraft_with_actionable_feedback_is_address():
    verdict = resume.resolve_next_action(
        _neutral_state(pr=_pr("OPEN")),
        has_pending_learn=False,
        get_feedback=lambda _n: _feedback(threads=(_thread(False),)),
    )
    assert verdict == A.ADDRESS


def test_open_nondraft_clean_is_awaiting_review():
    verdict = resume.resolve_next_action(
        _neutral_state(pr=_pr("OPEN")),
        has_pending_learn=False,
        get_feedback=lambda _n: _feedback(reviews=(_review("alice", "APPROVED", "2024-01-01"),)),
    )
    assert verdict == A.AWAITING_REVIEW


def test_unknown_pr_state_is_treated_as_open():
    seen: list[int] = []

    def _get(n: int) -> github.PrFeedback:
        seen.append(n)
        return _feedback()

    verdict = resume.resolve_next_action(
        _neutral_state(pr=_pr("WEIRD")), has_pending_learn=False, get_feedback=_get
    )
    assert verdict == A.AWAITING_REVIEW and seen == [55]


def test_stage_id_maps_launchable_verdicts_only():
    assert A.IMPLEMENT.stage_id == "implement"
    assert A.ADDRESS.stage_id == "address"
    assert A.LEARN.stage_id == "learn"
    for gate in (A.READY_FOR_REVIEW, A.AWAITING_REVIEW, A.PR_CLOSED, A.DONE):
        assert gate.stage_id is None


# --- needs_address (pure; spec in contracts.md §8.37) -----------------------------------


def test_needs_address_unresolved_thread_true():
    assert resume.needs_address(_feedback(threads=(_thread(False),))) is True


def test_needs_address_resolved_thread_false():
    assert resume.needs_address(_feedback(threads=(_thread(True),))) is False


def test_needs_address_latest_changes_requested_true():
    fb = _feedback(reviews=(_review("alice", "CHANGES_REQUESTED", "2024-01-02"),))
    assert resume.needs_address(fb) is True


def test_needs_address_changes_requested_superseded_by_approved_false():
    fb = _feedback(
        reviews=(
            _review("alice", "CHANGES_REQUESTED", "2024-01-01"),
            _review("alice", "APPROVED", "2024-01-02"),
        )
    )
    assert resume.needs_address(fb) is False


def test_needs_address_only_discussion_comments_false():
    comment = github.DiscussionComment(comment_id=1, body="nit", author="bob", created_at=None)
    assert resume.needs_address(_feedback(comments=(comment,))) is False


def test_reconstruct_plan_ref():
    # `provider` is a passthrough from the caller's resolved backend (no config read here).
    ref = resume.reconstruct_plan_ref(
        _neutral_state(header={"objective_id": "O1"}), provider="github"
    )
    assert ref == plan.PlanRef(
        provider="github",
        pr_id="7",
        url="https://gh/o/r/issues/7",
        labels=("perk:plan",),
        objective_id="O1",
        consumed_learn=(),
        base=None,
    )


def test_reconstruct_plan_ref_carries_base():
    # The pinned base is recovered from the canonical plan-header.
    ref = resume.reconstruct_plan_ref(_neutral_state(header={"base": "develop"}), provider="github")
    assert ref.base == "develop"


# --- the CLI (CliRunner; get_plan + launch_stage stubbed) ------------------------------


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _authed(monkeypatch) -> None:
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(True, "octocat", ("repo",), None)
    )


def test_dry_run_resolves_stage_without_launching(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(
        plans, "get_plan", lambda **k: _state(header={"lifecycle_stage": "planned"})
    )

    def boom(**k):
        raise AssertionError("dry run must not launch")

    monkeypatch.setattr(launch, "launch_stage", boom)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["plan", "resume", "42", "--dry-run", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)  # stdout only: the lookup line is on stderr
        assert data["resumed_stage"] == "implement" and data["worktree"] == "plan-7"
        assert data["next_action"] == "implement"
        assert data["plan_ref"]["pr_id"] == "7"
        # dry run writes no ref
        assert not cache.plan_ref_path(Path(d)).exists()
        # The lookup runs on the dry-run path too, so the wait IS narrated (to stderr).
        assert "looking up plan #42" in result.stderr


def test_url_argument_peeled_to_id_reaches_backend(monkeypatch):
    # A pasted Linear issue URL is peeled to SAV-9 before the backend read; the extracted id
    # reaches the backend `get_plan` and appears verbatim in the dry-run report.
    _authed(monkeypatch)
    seen: dict[str, object] = {}

    class _FakeBackend:
        backend_id = "linear"

        def get_plan(self, *, issue_id: str):
            seen["issue_id"] = issue_id
            return _neutral_state(header={"lifecycle_stage": "planned"})

    monkeypatch.setattr(resolve, "resolve_issue_backend", lambda _root: _FakeBackend())
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(
            cli,
            ["plan", "resume", "https://linear.app/acme/issue/SAV-9/x", "--dry-run", "--json"],
        )
        assert result.exit_code == 0, result.output
        assert seen["issue_id"] == "SAV-9"
        assert json.loads(result.stdout)["plan"] == "SAV-9"  # stdout only (lookup line on stderr)


def test_real_resume_writes_ref_and_launches(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(plans, "get_plan", lambda **k: _state(pr=_pr("OPEN")))
    # An unresolved review thread makes the OPEN non-draft PR actionable → launch `address`.
    monkeypatch.setattr(github, "get_pr_feedback", lambda **k: _feedback(threads=(_thread(False),)))
    launched: dict[str, object] = {}

    def _launch(**k):
        launched["stage"] = k["stage"].id

    monkeypatch.setattr(launch, "launch_stage", _launch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["plan", "resume", "7"])
        assert result.exit_code == 0
        assert launched["stage"] == "address"  # PR open + actionable feedback -> address
        assert "looking up plan #7" in result.stderr  # narrates the backend lookup wait
        assert "\u2713 found plan #7" in result.stderr  # the lookup step resolves on success
        # the ref was materialized at the repo root for launch_stage to derive from
        assert cache.read_plan_ref(Path(d)) is not None


def test_implement_resume_into_existing_worktree_carries_advisory(monkeypatch):
    """An implement resume whose plan worktree already exists locally (the D4 reuse arm)
    passes the prior-work advisory as the launch prompt_suffix (contracts.md §8.38)."""
    _authed(monkeypatch)
    monkeypatch.setattr(
        plans, "get_plan", lambda **k: _state(header={"lifecycle_stage": "planned"})
    )
    launched: dict[str, object] = {}

    def _launch(**k):
        launched["prompt_suffix"] = k["prompt_suffix"]

    monkeypatch.setattr(launch, "launch_stage", _launch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        # The default worktree_root is <repo>/.worktrees — pre-create the reuse-arm path.
        (Path(d) / ".worktrees" / "plan-7").mkdir(parents=True)
        result = runner.invoke(cli, ["plan", "resume", "7"])
        assert result.exit_code == 0, result.output
        suffix = launched["prompt_suffix"]
        assert isinstance(suffix, str)
        assert "RESUMED into an existing worktree" in suffix


def test_implement_resume_fresh_worktree_has_no_advisory(monkeypatch):
    """No pre-existing worktree → no advisory (local-reuse only; a fresh create — even from
    origin/plan-<N> — is deliberately excluded)."""
    _authed(monkeypatch)
    monkeypatch.setattr(
        plans, "get_plan", lambda **k: _state(header={"lifecycle_stage": "planned"})
    )
    launched: dict[str, object] = {}

    def _launch(**k):
        launched["prompt_suffix"] = k["prompt_suffix"]

    monkeypatch.setattr(launch, "launch_stage", _launch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["plan", "resume", "7"])
        assert result.exit_code == 0, result.output
        assert launched["prompt_suffix"] is None


def test_address_resume_into_existing_worktree_has_no_advisory(monkeypatch):
    """The advisory is implement-only: an address resume into an existing worktree carries
    no suffix."""
    _authed(monkeypatch)
    monkeypatch.setattr(plans, "get_plan", lambda **k: _state(pr=_pr("OPEN")))
    monkeypatch.setattr(github, "get_pr_feedback", lambda **k: _feedback(threads=(_thread(False),)))
    launched: dict[str, object] = {}

    def _launch(**k):
        launched["stage"] = k["stage"].id
        launched["prompt_suffix"] = k["prompt_suffix"]

    monkeypatch.setattr(launch, "launch_stage", _launch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        (Path(d) / ".worktrees" / "plan-7").mkdir(parents=True)
        result = runner.invoke(cli, ["plan", "resume", "7"])
        assert result.exit_code == 0, result.output
        assert launched["stage"] == "address"
        assert launched["prompt_suffix"] is None


def test_real_launch_banner_precedes_lookup(monkeypatch):
    """A real local launch heads stderr with the banner BEFORE the `looking up #X` narration."""
    _authed(monkeypatch)
    monkeypatch.setattr(plans, "get_plan", lambda **k: _state(pr=_pr("OPEN")))
    monkeypatch.setattr(github, "get_pr_feedback", lambda **k: _feedback(threads=(_thread(False),)))
    monkeypatch.setattr(launch, "launch_stage", lambda **k: None)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["plan", "resume", "7"])
        assert result.exit_code == 0, result.output
        err = result.stderr
        assert err.index("skills \u00b7") < err.index("looking up")


def test_dry_run_emits_no_banner(monkeypatch):
    """The banner is gated off on `--dry-run` (the preview path owns the output)."""
    _authed(monkeypatch)
    monkeypatch.setattr(
        plans, "get_plan", lambda **k: _state(header={"lifecycle_stage": "planned"})
    )
    monkeypatch.setattr(launch, "launch_stage", lambda **k: None)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["plan", "resume", "42", "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "skills \u00b7" not in result.stderr


def test_merged_pending_header_resumes_learn_without_local_marker(monkeypatch):
    """The fresh-clone acceptance: a merged plan whose header says `learn_state: pending`
    resolves to the learn stage with NO local pending-learn marker present (§8.36)."""
    _authed(monkeypatch)
    monkeypatch.setattr(
        plans, "get_plan", lambda **k: _state(header={"learn_state": "pending"}, pr=_pr("MERGED"))
    )
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        assert not cache.has_marker(Path(d), cache.PENDING_LEARN)  # no local marker
        result = runner.invoke(cli, ["plan", "resume", "7", "--dry-run", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["resumed_stage"] == "learn" and data["next_action"] == "learn"


def test_nothing_to_resume_exits_0(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(plans, "get_plan", lambda **k: _state(pr=_pr("MERGED")))
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["plan", "resume", "7", "--json"])
        assert result.exit_code == 0
        # Parse stdout (not the combined .output): the real-path `looking up …` line is on stderr.
        data = json.loads(result.stdout)
        assert data["resumed_stage"] is None and data["next_action"] == "done"


# --- the human-gate arms: report, never launch (real AND dry-run) -----------------------


def _gate_case(monkeypatch, pr, *, feedback=None):
    """Invoke a real (non-dry-run) resume against a gate-arm PR; launching is forbidden."""
    _authed(monkeypatch)
    monkeypatch.setattr(plans, "get_plan", lambda **k: _state(pr=pr))
    if feedback is not None:
        monkeypatch.setattr(github, "get_pr_feedback", lambda **k: feedback)

    def boom(**k):
        raise AssertionError("a gate verdict must never launch")

    monkeypatch.setattr(launch, "launch_stage", boom)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["plan", "resume", "7", "--json"])
        assert result.exit_code == 0
        assert not cache.plan_ref_path(Path(d)).exists()  # gate arms write no ref
    return json.loads(result.stdout)


def test_draft_pr_gates_on_ready_for_review(monkeypatch):
    data = _gate_case(monkeypatch, _pr("OPEN", is_draft=True))
    assert data["next_action"] == "ready_for_review" and data["resumed_stage"] is None
    assert data["pr"] == 55 and "draft PR" in data["message"]


def test_open_clean_pr_gates_on_awaiting_review(monkeypatch):
    data = _gate_case(monkeypatch, _pr("OPEN"), feedback=_feedback(threads=(_thread(True),)))
    assert data["next_action"] == "awaiting_review" and data["resumed_stage"] is None
    assert "awaiting the human review/land gate" in data["message"]


def test_closed_unmerged_pr_gates_on_pr_closed(monkeypatch):
    data = _gate_case(monkeypatch, _pr("CLOSED"))
    assert data["next_action"] == "pr_closed" and data["resumed_stage"] is None
    assert "closed unmerged" in data["message"]


def test_plan_not_found_exits_1(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(plans, "get_plan", lambda **k: None)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["plan", "resume", "999", "--json"])
        assert result.exit_code == 1
        # Parse stdout (not the combined .output): the real-path `looking up …` line is on stderr.
        assert json.loads(result.stdout)["error_type"] == "plan_not_found"


def test_backend_error_exits_1(monkeypatch):
    """An `IssueBackendError` from the plan read renders the github_error envelope (exit 1)."""
    _authed(monkeypatch)

    def _raise(**k):
        raise issue_backend.IssueBackendError("backend unavailable")

    monkeypatch.setattr(plans, "get_plan", _raise)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["plan", "resume", "7", "--json"])
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["success"] is False and data["error_type"] == "github_error"
        assert "backend unavailable" in data["message"]


def test_feedback_fetch_github_error_exits_1(monkeypatch):
    """A `GitHubError` from the OPEN-non-draft feedback fetch — the one arm that fetches —
    is translated at the command boundary to the github_error envelope (exit 1)."""
    _authed(monkeypatch)
    monkeypatch.setattr(plans, "get_plan", lambda **k: _state(pr=_pr("OPEN")))

    def _raise(**k):
        raise github.GitHubError("feedback fetch failed")

    monkeypatch.setattr(github, "get_pr_feedback", _raise)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["plan", "resume", "7", "--json"])
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["success"] is False and data["error_type"] == "github_error"
        assert "feedback fetch failed" in data["message"]


def test_invalid_plan_id_exits_1(monkeypatch):
    _authed(monkeypatch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        # Ids are opaque strings now — only empty / path-unsafe ids are rejected up front.
        result = runner.invoke(cli, ["plan", "resume", "bad/id", "--json"])
        assert result.exit_code == 1
        assert json.loads(result.output)["error_type"] == "invalid_input"


def test_not_a_repo_exits_2():
    runner = CliRunner()
    with runner.isolated_filesystem():  # no git init
        result = runner.invoke(cli, ["plan", "resume", "7", "--dry-run", "--json"])
    assert result.exit_code == 2
    assert json.loads(result.output)["error_type"] == "not_a_repo"
