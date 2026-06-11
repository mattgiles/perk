import subprocess

from perk import git


def _sha(repo, ref: str = "HEAD") -> str:
    return subprocess.run(
        ["git", "rev-parse", ref], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_repo_root_inside_and_outside(git_repo, tmp_path_factory):
    root = git.repo_root(git_repo)
    assert root is not None and root.samefile(git_repo)
    outside = tmp_path_factory.mktemp("not-a-repo")
    assert git.repo_root(outside) is None


def test_worktree_lifecycle(git_repo):
    wt = git_repo / ".worktrees" / "wt1"
    git.worktree_add(git_repo, wt, branch="wt1", create_branch=True)

    listed = git.worktree_list(git_repo)
    assert "wt1" in {w.path.name for w in listed}
    assert "wt1" in {w.branch for w in listed}

    git.worktree_remove(git_repo, wt, force=True)
    assert "wt1" not in {w.path.name for w in git.worktree_list(git_repo)}


def test_delete_branch(git_repo):
    import pytest

    subprocess.run(
        ["git", "branch", "scratch"], cwd=git_repo, check=True, capture_output=True, text=True
    )
    assert "scratch" in _git(git_repo, "branch", "--format=%(refname:short)").split()
    git.delete_branch(git_repo, "scratch")
    assert "scratch" not in _git(git_repo, "branch", "--format=%(refname:short)").split()
    with pytest.raises(git.GitError):
        git.delete_branch(git_repo, "no-such-branch")


def _git(cwd, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def _work_and_bare(tmp_path):
    """A work repo with one commit + a bare ``origin`` it has pushed ``plan-x`` to."""
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-q")
    _git(work, "config", "user.email", "t@example.com")
    _git(work, "config", "user.name", "perk tests")
    _git(work, "checkout", "-q", "-b", "plan-x")
    (work / "f.txt").write_text("hi\n", encoding="utf-8")
    _git(work, "add", ".")
    _git(work, "commit", "-qm", "init")
    bare = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", str(bare))
    _git(work, "remote", "add", "origin", str(bare))
    return work, bare


def test_first_push_is_plain_and_succeeds(tmp_path):
    work, bare = _work_and_bare(tmp_path)
    git.push(work, "plan-x")  # default force=False
    assert _git(bare, "rev-parse", "plan-x").strip()


def test_rewrite_plain_push_is_rejected(tmp_path):
    import pytest

    work, _bare = _work_and_bare(tmp_path)
    git.push(work, "plan-x")
    _git(work, "commit", "--amend", "-qm", "rewritten")
    with pytest.raises(git.PushRejectedError):
        git.push(work, "plan-x", force=False)


def test_rewrite_force_with_lease_succeeds(tmp_path):
    work, bare = _work_and_bare(tmp_path)
    git.push(work, "plan-x")
    _git(work, "commit", "--amend", "-qm", "rewritten")
    amended = _git(work, "rev-parse", "HEAD").strip()
    git.push(work, "plan-x", force=True)
    assert _git(bare, "rev-parse", "plan-x").strip() == amended


def test_is_dirty(tmp_path):
    work, _ = _work_and_bare(tmp_path)
    assert git.is_dirty(work) is False
    (work / "g.txt").write_text("new\n", encoding="utf-8")
    assert git.is_dirty(work) is True


# --- origin-aware create base helpers ---------------------------------------------------


def test_detect_trunk_branch_from_origin_head(git_repo_with_remote):
    clone, _remote, _advance = git_repo_with_remote
    assert git.detect_trunk_branch(clone) == "main"


def test_detect_trunk_branch_local_fallback(git_repo):
    # No remote at all: falls back to the existing local head (default branch may be main/master).
    head = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=git_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    expected = head if head in ("main", "master") else "main"
    assert git.detect_trunk_branch(git_repo) == expected


def test_remote_ref_exists(git_repo_with_remote):
    clone, _remote, _advance = git_repo_with_remote
    assert git.remote_ref_exists(clone, "origin/main") is True
    assert git.remote_ref_exists(clone, "origin/absent") is False


def test_fetch_brings_origin_up_to_date(git_repo_with_remote):
    clone, _remote, advance = git_repo_with_remote
    advanced = advance()
    assert _sha(clone, "origin/main") != advanced  # behind until fetch
    git.fetch(clone)
    assert _sha(clone, "origin/main") == advanced


def test_worktree_add_with_base(git_repo_with_remote):
    clone, _remote, advance = git_repo_with_remote
    advanced = advance()
    git.fetch(clone)
    wt = clone / ".worktrees" / "based"
    git.worktree_add(clone, wt, branch="based", create_branch=True, base="origin/main")
    assert _sha(wt) == advanced


def test_run_disables_git_terminal_prompt(monkeypatch):
    """`git._run` injects GIT_TERMINAL_PROMPT=0 (credential prompts fail fast instead of
    hanging to the timeout — Node 4.2) while inheriting the ambient environment."""
    captured: dict = {}

    def fake_run(args, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(args, 0, stdout="ok\n", stderr="")

    monkeypatch.setenv("PERK_TEST_AMBIENT", "yes")
    monkeypatch.setattr(subprocess, "run", fake_run)
    git._run(["status"])
    env = captured["env"]
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["PERK_TEST_AMBIENT"] == "yes"
