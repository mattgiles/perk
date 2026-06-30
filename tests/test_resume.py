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


def _pr(state: str) -> github.PullRequest:
    return github.PullRequest(number=55, url="u/pr/55", is_draft=False, state=state, existed=True)


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


# --- the pure resolution matrix (D5) ---------------------------------------------------


@pytest.mark.parametrize(
    ("state", "pending", "expected"),
    [
        (_neutral_state(header={"lifecycle_stage": "planned"}), False, "implement"),
        (_neutral_state(header={"lifecycle_stage": "impl"}), False, "implement"),  # no PR yet
        (_neutral_state(pr=_pr("OPEN")), False, "submit"),
        (_neutral_state(pr=_pr("MERGED")), True, "learn"),
        (_neutral_state(pr=_pr("MERGED")), False, None),  # merged + learned -> nothing
    ],
)
def test_resolve_resume_stage_matrix(state, pending, expected):
    assert resume.resolve_resume_stage(state, has_pending_learn=pending) == expected


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
    launched: dict[str, object] = {}

    def _launch(**k):
        launched["stage"] = k["stage"].id

    monkeypatch.setattr(launch, "launch_stage", _launch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["plan", "resume", "7"])
        assert result.exit_code == 0
        assert launched["stage"] == "submit"  # PR open -> submit
        assert "looking up plan #7" in result.stderr  # narrates the backend lookup wait
        # the ref was materialized at the repo root for launch_stage to derive from
        assert cache.read_plan_ref(Path(d)) is not None


def test_real_launch_banner_precedes_lookup(monkeypatch):
    """A real local launch heads stderr with the banner BEFORE the `looking up #X` narration."""
    _authed(monkeypatch)
    monkeypatch.setattr(plans, "get_plan", lambda **k: _state(pr=_pr("OPEN")))
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


def test_nothing_to_resume_exits_0(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(plans, "get_plan", lambda **k: _state(pr=_pr("MERGED")))
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["plan", "resume", "7", "--json"])
        assert result.exit_code == 0
        # Parse stdout (not the combined .output): the real-path `looking up …` line is on stderr.
        assert json.loads(result.stdout)["resumed_stage"] is None


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
