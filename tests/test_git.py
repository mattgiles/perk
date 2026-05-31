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
