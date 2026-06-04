from perk import git


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


def _git(cwd, *args: str) -> str:
    import subprocess

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
