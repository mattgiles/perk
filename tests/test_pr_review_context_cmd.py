import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk import github, plan
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


def _context() -> github.PrReviewContext:
    return github.PrReviewContext(
        pr_number=42,
        base_ref="main",
        head_ref="plan-7",
        title="Add a thing",
        body="does the thing",
        diff="diff --git a/x b/x\n+new line\n",
        plan_body="# Plan\n\nbody",
    )


def _foreign_context() -> github.PrReviewContext:
    # The --pr arm's shape: a foreign head ref and no plan body (plan-ref-free).
    return github.PrReviewContext(
        pr_number=123,
        base_ref="main",
        head_ref="feature-x",
        title="A foreign PR",
        body="no plan behind it",
        diff="diff --git a/y b/y\n+foreign line\n",
        plan_body=None,
    )


def _open_pr():
    return github.PullRequest(number=42, url="u", is_draft=False, state="OPEN", existed=True)


def test_context_success_json(monkeypatch):
    monkeypatch.setattr(github, "find_pr_for_branch", lambda **k: _open_pr())
    monkeypatch.setattr(github, "get_pr_review_context", lambda **k: _context())
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), plan.PlanRefModel.model_validate(_REF).to_domain())
        result = runner.invoke(cli, ["pr", "review-context", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["success"] is True
    assert data["pr"] == 42 and data["branch"] == "plan-7"
    assert data["base_ref"] == "main" and data["head_ref"] == "plan-7"
    assert "new line" in data["diff"]
    assert data["plan_body"].startswith("# Plan")


def test_context_no_plan_ref_exits_1():
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["pr", "review-context", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "no_plan_ref"


def test_context_no_pr_exits_1(monkeypatch):
    monkeypatch.setattr(github, "find_pr_for_branch", lambda **k: None)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), plan.PlanRefModel.model_validate(_REF).to_domain())
        result = runner.invoke(cli, ["pr", "review-context", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "no_pr"


def test_context_not_a_repo_exits_2():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["pr", "review-context", "--json"])
    assert result.exit_code == 2
    assert json.loads(result.output)["error_type"] == "not_a_repo"


def test_context_github_error_exits_1(monkeypatch):
    monkeypatch.setattr(github, "find_pr_for_branch", lambda **k: _open_pr())

    def _boom(**k):
        raise github.GitHubError("HTTP 500")

    monkeypatch.setattr(github, "get_pr_review_context", _boom)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), plan.PlanRefModel.model_validate(_REF).to_domain())
        result = runner.invoke(cli, ["pr", "review-context", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "github_error"


def test_context_pr_flag_success_json(monkeypatch):
    # No plan-ref is written; the plan-ref path is provably untouched (find_pr_for_branch
    # would raise) — the explicit flag wins.
    monkeypatch.setattr(
        github,
        "get_pr",
        lambda **k: github.PullRequest(
            number=123, url="u", is_draft=False, state="OPEN", existed=True, head_ref="feature-x"
        ),
    )
    seen: dict[str, object] = {}

    def _capture(**k):
        seen.update(k)
        return _foreign_context()

    monkeypatch.setattr(github, "get_pr_review_context", _capture)

    def _no_plan_ref_path(**k):
        raise AssertionError("--pr must never resolve the plan-ref branch")

    monkeypatch.setattr(github, "find_pr_for_branch", _no_plan_ref_path)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["pr", "review-context", "--pr", "123", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["success"] is True
    assert data["branch"] == "feature-x" and data["pr"] == 123
    assert data["plan_body"] is None
    assert seen["branch"] == "feature-x"
    assert seen["plan_body"] is None
    assert seen["pr_number"] == 123


def test_context_pr_flag_not_found_exits_1(monkeypatch):
    monkeypatch.setattr(github, "get_pr", lambda **k: None)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["pr", "review-context", "--pr", "999", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "pr_not_found"


def test_context_pr_flag_github_error_exits_1(monkeypatch):
    def _boom(**k):
        raise github.GitHubError("HTTP 500")

    monkeypatch.setattr(github, "get_pr", _boom)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["pr", "review-context", "--pr", "123", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "github_error"


def test_context_flagless_never_calls_get_pr(monkeypatch):
    # The flagless arm never touches the by-number lookup (byte-identical to before the flag).
    monkeypatch.setattr(github, "find_pr_for_branch", lambda **k: _open_pr())
    monkeypatch.setattr(github, "get_pr_review_context", lambda **k: _context())

    def _no_by_number(**k):
        raise AssertionError("the flagless arm must never call get_pr")

    monkeypatch.setattr(github, "get_pr", _no_by_number)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), plan.PlanRefModel.model_validate(_REF).to_domain())
        result = runner.invoke(cli, ["pr", "review-context", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["success"] is True


def test_resolve_plan_body_prefers_cache_mirror(monkeypatch, tmp_path):
    # The primary path: the worktree cache mirror is read first (backend-neutral), no backend hit.
    from perk.cli.commands.pr.review_context_cmd import _resolve_plan_body

    mirror = cache.plan_body_path(tmp_path)
    mirror.parent.mkdir(parents=True, exist_ok=True)
    mirror.write_text("# Mirror plan\n\nbody", encoding="utf-8")

    def _no_backend(_root):
        raise AssertionError("must not resolve a backend when the mirror is present")

    monkeypatch.setattr(
        "perk.cli.commands.pr.review_context_cmd.resolve.resolve_issue_backend", _no_backend
    )
    body = _resolve_plan_body(tmp_path, plan.PlanRefModel.model_validate(_REF).to_domain())
    assert body is not None and body.startswith("# Mirror plan")


def test_resolve_plan_body_falls_back_to_resolver_for_linear_id(monkeypatch, tmp_path):
    # The fallback path: no mirror → fetch via the resolved backend, which owns the id shape
    # (a non-github Linear-shaped `pr_id` like `ENG-123` flows straight through — the §G hoist
    # drops the old `provider == "github"` / `pr_id.isdigit()` gate).
    from perk.cli.commands.pr.review_context_cmd import _resolve_plan_body

    seen: dict[str, str] = {}

    class _Backend:
        def get_plan_body(self, *, issue_id: str) -> str:
            seen["issue_id"] = issue_id
            return "# Linear plan body"

    monkeypatch.setattr(
        "perk.cli.commands.pr.review_context_cmd.resolve.resolve_issue_backend",
        lambda _root: _Backend(),
    )
    ref = plan.PlanRefModel.model_validate(
        {**_REF, "provider": "linear", "pr_id": "ENG-123"}
    ).to_domain()
    assert _resolve_plan_body(tmp_path, ref) == "# Linear plan body"
    assert seen["issue_id"] == "ENG-123"
