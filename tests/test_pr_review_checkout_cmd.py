import json
import os
import subprocess
import time
from pathlib import Path

from click.testing import CliRunner

from perk import github
from perk.cli.cli import cli
from perk.run import launch
from perk.substrate import git


def _git(cwd, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def _sha(repo, ref: str = "HEAD") -> str:
    return _git(repo, "rev-parse", ref).strip()


def _pr(number: int = 7, *, state: str = "OPEN", base_ref: str = "main") -> github.PullRequest:
    return github.PullRequest(
        number=number,
        url="u",
        is_draft=False,
        state=state,
        existed=True,
        base_ref=base_ref,
        head_ref="feature",
    )


def _seed_pull_ref(clone: Path, pr_number: int = 7) -> tuple[str, str]:
    """Diverge a PR head from main and push it to ``refs/pull/<n>/head`` on the bare remote.

    Returns ``(head_sha, merge_base_sha)`` — the divergence point is the expected merge-base.
    """
    base_sha = _sha(clone)
    _git(clone, "checkout", "-qb", "feature")
    (clone / "feature.txt").write_text("f\n", encoding="utf-8")
    _git(clone, "add", ".")
    _git(clone, "commit", "-qm", "feature")
    head_sha = _sha(clone)
    _git(clone, "push", "-q", "origin", f"HEAD:refs/pull/{pr_number}/head")
    _git(clone, "checkout", "-q", "main")
    return head_sha, base_sha


def test_checkout_success_json(git_repo_with_remote, monkeypatch):
    clone, _remote, advance_origin = git_repo_with_remote
    head_sha, base_sha = _seed_pull_ref(clone)
    advance_origin()  # main moves past the divergence point — merge-base must stay base_sha
    monkeypatch.setattr(github, "get_pr", lambda **k: _pr())
    monkeypatch.chdir(clone)

    result = CliRunner().invoke(cli, ["pr", "review", "checkout", "--pr", "7", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["success"] is True
    assert data["pr"] == 7
    assert data["url"] == "u"
    assert data["head_sha"] == head_sha
    assert data["base_sha"] == base_sha
    assert data["base_ref"] == "main"
    # macOS: /var→/private/var — .resolve() BOTH sides.
    wt = Path(data["path"])
    assert wt.resolve() == (clone / ".worktrees" / "review-7").resolve()
    # A detached worktree at the exact head.
    assert _sha(wt) == head_sha
    assert git.current_branch(wt) is None
    # The temp ref is gone.
    assert git.resolve_commit(clone, "refs/perk/review/7") is None


def test_checkout_non_open_state_notes_but_succeeds(git_repo_with_remote, monkeypatch):
    clone, _remote, _advance = git_repo_with_remote
    _seed_pull_ref(clone)
    monkeypatch.setattr(github, "get_pr", lambda **k: _pr(state="MERGED"))
    monkeypatch.chdir(clone)

    result = CliRunner().invoke(cli, ["pr", "review", "checkout", "--pr", "7"])
    assert result.exit_code == 0, result.output
    assert "note: PR is MERGED" in result.output


def test_checkout_pr_not_found_exits_1(git_repo_with_remote, monkeypatch):
    clone, _remote, _advance = git_repo_with_remote
    monkeypatch.setattr(github, "get_pr", lambda **k: None)
    monkeypatch.chdir(clone)

    result = CliRunner().invoke(cli, ["pr", "review", "checkout", "--pr", "999", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "pr_not_found"


def test_checkout_github_error_exits_1(git_repo_with_remote, monkeypatch):
    clone, _remote, _advance = git_repo_with_remote

    def _boom(**k):
        raise github.GitHubError("HTTP 500")

    monkeypatch.setattr(github, "get_pr", _boom)
    monkeypatch.chdir(clone)

    result = CliRunner().invoke(cli, ["pr", "review", "checkout", "--pr", "7", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "github_error"


def test_checkout_not_a_repo_exits_2(monkeypatch):
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["pr", "review", "checkout", "--pr", "7", "--json"])
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error_type"] == "not_a_repo"


def test_checkout_fetch_failure_leaves_existing_worktree(git_repo_with_remote, monkeypatch):
    # No pull ref on the remote → the fetch fails → git_error. The fetch-before-remove
    # ordering is pinned: a pre-existing checkout survives untouched.
    clone, _remote, _advance = git_repo_with_remote
    old_sha = _sha(clone)
    wt = clone / ".worktrees" / "review-7"
    git.worktree_add_detached(clone, wt, old_sha)
    monkeypatch.setattr(github, "get_pr", lambda **k: _pr())
    monkeypatch.chdir(clone)

    result = CliRunner().invoke(cli, ["pr", "review", "checkout", "--pr", "7", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "git_error"
    assert wt.is_dir()
    assert _sha(wt) == old_sha


def test_checkout_refreshes_existing_to_current_head(git_repo_with_remote, monkeypatch):
    clone, _remote, _advance = git_repo_with_remote
    stale_sha = _sha(clone)
    wt = clone / ".worktrees" / "review-7"
    git.worktree_add_detached(clone, wt, stale_sha)
    head_sha, _base = _seed_pull_ref(clone)
    monkeypatch.setattr(github, "get_pr", lambda **k: _pr())
    monkeypatch.chdir(clone)

    result = CliRunner().invoke(cli, ["pr", "review", "checkout", "--pr", "7", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["head_sha"] == head_sha
    assert _sha(wt) == head_sha  # recreated at the current head, not the stale one
    assert git.current_branch(wt) is None


def test_checkout_reaps_stale_review_worktrees_only(git_repo_with_remote, monkeypatch):
    clone, _remote, _advance = git_repo_with_remote
    sha = _sha(clone)
    stale = clone / ".worktrees" / "review-99"
    fresh = clone / ".worktrees" / "review-88"
    plan_wt = clone / ".worktrees" / "plan-5"
    git.worktree_add_detached(clone, stale, sha)
    git.worktree_add_detached(clone, fresh, sha)
    git.worktree_add(clone, plan_wt, branch="plan-5", create_branch=True)
    # Age the gitlinks of the stale candidate AND plan-5: plan-5 must survive on the name
    # filter alone, not on freshness.
    aged = time.time() - 8 * 86400
    os.utime(stale / ".git", (aged, aged))
    os.utime(plan_wt / ".git", (aged, aged))

    _seed_pull_ref(clone)
    monkeypatch.setattr(github, "get_pr", lambda **k: _pr())
    monkeypatch.chdir(clone)

    result = CliRunner().invoke(cli, ["pr", "review", "checkout", "--pr", "7", "--json"])
    assert result.exit_code == 0, result.output
    assert not stale.exists()
    assert fresh.is_dir()
    assert plan_wt.is_dir()
    names = {w.path.name for w in git.worktree_list(clone)}
    assert "review-99" not in names
    assert {"review-88", "plan-5", "review-7"} <= names


def test_checkout_refresh_removal_failure_is_enveloped(git_repo_with_remote, monkeypatch):
    # A failed refresh removal is translated at the boundary — a stable git_error envelope,
    # never a raw traceback.
    import perk.cli.commands.pr.review.checkout_cmd as checkout_cmd

    clone, _remote, _advance = git_repo_with_remote
    _seed_pull_ref(clone)
    monkeypatch.setattr(github, "get_pr", lambda **k: _pr())

    def _boom(_repo_root, _path):
        raise git.GitError("worktree locked")

    monkeypatch.setattr(checkout_cmd, "remove_review_worktree", _boom)
    monkeypatch.chdir(clone)

    result = CliRunner().invoke(cli, ["pr", "review", "checkout", "--pr", "7", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "git_error"


def test_stale_classifier_missing_gitlink_and_filters(tmp_path):
    # Pure classification: a missing .git gitlink is stale (broken residue); the target (skip),
    # non-review names, fresh checkouts, and foreign-parent paths are never candidates.
    from datetime import UTC, datetime

    from perk.cli.commands.pr.review.checkout_cmd import _stale_review_worktrees

    root = tmp_path / ".worktrees"
    now = datetime.now(UTC)

    def wt(name: str, *, gitlink: bool, parent: Path = root) -> git.Worktree:
        path = parent / name
        path.mkdir(parents=True, exist_ok=True)
        if gitlink:
            (path / ".git").write_text("gitdir: x\n", encoding="utf-8")
        return git.Worktree(path=path, branch=None, head=None)

    broken = wt("review-99", gitlink=False)  # missing gitlink -> stale
    fresh = wt("review-88", gitlink=True)  # fresh gitlink -> kept
    target = wt("review-7", gitlink=False)  # the skip target -> never a candidate
    plan_wt = wt("plan-5", gitlink=False)  # name filter -> never a candidate
    foreign = wt("review-66", gitlink=False, parent=tmp_path / "elsewhere")  # parent filter

    stale = _stale_review_worktrees(
        [broken, fresh, target, plan_wt, foreign], root, skip="review-7", now=now
    )
    assert [w.path.name for w in stale] == ["review-99"]


def test_checkout_never_runs_worktree_setup(git_repo_with_remote, monkeypatch):
    # The structural untrusted-code posture: even with [worktree] setup configured, the
    # checkout door never calls the run_worktree_setup facade (contrast: worktree create does).
    clone, _remote, _advance = git_repo_with_remote
    perk_dir = clone / ".perk"
    perk_dir.mkdir()
    (perk_dir / "config.toml").write_text(
        '[worktree]\nsetup = ["touch marker"]\n', encoding="utf-8"
    )
    calls: list = []
    monkeypatch.setattr(launch, "run_worktree_setup", lambda path, cmds: calls.append((path, cmds)))

    _seed_pull_ref(clone)
    monkeypatch.setattr(github, "get_pr", lambda **k: _pr())
    monkeypatch.chdir(clone)

    result = CliRunner().invoke(cli, ["pr", "review", "checkout", "--pr", "7", "--json"])
    assert result.exit_code == 0, result.output
    assert calls == []
    assert not (clone / ".worktrees" / "review-7" / "marker").exists()
