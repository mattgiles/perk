import subprocess

from perk.substrate import git


def _sha(repo, ref: str = "HEAD") -> str:
    return subprocess.run(
        ["git", "rev-parse", ref], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_repo_root_inside_and_outside(git_repo, tmp_path_factory):
    root = git.repo_root(git_repo)
    assert root is not None and root.samefile(git_repo)
    outside = tmp_path_factory.mktemp("not-a-repo")
    assert git.repo_root(outside) is None


def test_main_worktree_root(git_repo, tmp_path_factory):
    # Main checkout: resolves to its own root.
    main = git.main_worktree_root(git_repo)
    assert main is not None and main.resolve() == git_repo.resolve()

    # Linked worktree: resolves back to the MAIN checkout root, not the worktree.
    wt = git_repo / ".worktrees" / "wt-main-root"
    git.worktree_add(git_repo, wt, branch="plan-x", create_branch=True)
    from_wt = git.main_worktree_root(wt)
    assert from_wt is not None and from_wt.resolve() == git_repo.resolve()

    # Non-repo: None.
    outside = tmp_path_factory.mktemp("not-a-repo")
    assert git.main_worktree_root(outside) is None


def test_worktree_lifecycle(git_repo):
    wt = git_repo / ".worktrees" / "wt1"
    git.worktree_add(git_repo, wt, branch="wt1", create_branch=True)

    listed = git.worktree_list(git_repo)
    assert "wt1" in {w.path.name for w in listed}
    assert "wt1" in {w.branch for w in listed}

    git.worktree_remove(git_repo, wt, force=True)
    assert "wt1" not in {w.path.name for w in git.worktree_list(git_repo)}


def test_worktree_prune_clears_orphan_admin_entry(git_repo):
    import shutil

    wt = git_repo / ".worktrees" / "orphan"
    git.worktree_add(git_repo, wt, branch="orphan", create_branch=True)
    # Delete the working dir directly, leaving the .git/worktrees/<id> admin entry behind.
    shutil.rmtree(wt)
    assert "orphan" in {w.path.name for w in git.worktree_list(git_repo)}

    git.worktree_prune(git_repo)
    assert "orphan" not in {w.path.name for w in git.worktree_list(git_repo)}


def test_worktree_remove_recovers_from_missing_gitlink(git_repo):
    wt = git_repo / ".worktrees" / "broken"
    git.worktree_add(git_repo, wt, branch="broken", create_branch=True)
    # Reproduce the `validation failed … '.git' does not exist` mode (--force does NOT bypass it).
    (wt / ".git").unlink()

    git.worktree_remove(git_repo, wt, force=True)  # must not raise
    assert not wt.exists()

    git.worktree_prune(git_repo)
    assert "broken" not in {w.path.name for w in git.worktree_list(git_repo)}


def test_worktree_remove_recovers_from_timeout(git_repo, monkeypatch):
    wt = git_repo / ".worktrees" / "slow"
    git.worktree_add(git_repo, wt, branch="slow", create_branch=True)

    real_run = git._run

    def fake_run(args, **kwargs):
        if args[:2] == ["worktree", "remove"]:
            raise git.GitError(f"git worktree remove --force {wt} timed out")
        return real_run(args, **kwargs)

    monkeypatch.setattr(git, "_run", fake_run)
    git.worktree_remove(git_repo, wt, force=True)  # must not raise — fallback removes the dir
    assert not wt.exists()


def test_worktree_remove_dirty_refusal_not_recovered(git_repo):
    import pytest

    wt = git_repo / ".worktrees" / "dirty"
    git.worktree_add(git_repo, wt, branch="dirty", create_branch=True)
    (wt / "uncommitted.txt").write_text("x\n", encoding="utf-8")

    # The dirty refusal is NOT recoverable: the shutil.rmtree fallback must not fire, so the
    # worktree (and its uncommitted work) survives.
    with pytest.raises(git.GitError):
        git.worktree_remove(git_repo, wt, force=False)
    assert wt.exists()
    assert (wt / "uncommitted.txt").exists()


def test_tracked_paths(git_repo):
    import pytest

    skill = git_repo / ".claude" / "skills" / "x" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# x\n", encoding="utf-8")
    pathspecs = [".claude/skills", ".agents/skills"]
    assert git.tracked_paths(git_repo, pathspecs) == []  # untracked -> clean
    subprocess.run(
        ["git", "add", ".claude"], cwd=git_repo, check=True, capture_output=True, text=True
    )
    assert git.tracked_paths(git_repo, pathspecs) == [".claude/skills/x/SKILL.md"]
    with pytest.raises(git.GitError):  # a failed probe propagates (no silent pass)
        git.tracked_paths(git_repo.parent, pathspecs)


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
    hanging to the timeout) while inheriting the ambient environment."""
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


# --- batched / best-effort branch deletion helpers --------------------------------------


def _make_branch(repo, name: str) -> None:
    subprocess.run(["git", "branch", name], cwd=repo, check=True, capture_output=True, text=True)


def test_delete_branches_happy_path(git_repo):
    _make_branch(git_repo, "scratch-a")
    _make_branch(git_repo, "scratch-b")
    deleted = git.delete_branches(git_repo, ["scratch-a", "scratch-b"], force=True)
    assert set(deleted) == {"scratch-a", "scratch-b"}
    remaining = subprocess.run(
        ["git", "branch", "--format=%(refname:short)"],
        cwd=git_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    assert "scratch-a" not in remaining and "scratch-b" not in remaining


def test_delete_branches_empty_is_noop(git_repo):
    assert git.delete_branches(git_repo, [], force=True) == []


def test_delete_branches_missing_branch_absent_no_raise(git_repo):
    _make_branch(git_repo, "scratch-a")
    deleted = git.delete_branches(git_repo, ["scratch-a", "never-existed"], force=True)
    assert deleted == ["scratch-a"]  # the missing branch is simply absent, no raise


def test_has_remote(git_repo, git_repo_with_remote):
    assert git.has_remote(git_repo) is False
    clone, _remote, _advance = git_repo_with_remote
    assert git.has_remote(clone) is True


def test_delete_remote_branches_happy_path(git_repo_with_remote):
    clone, _remote, _advance = git_repo_with_remote
    subprocess.run(
        ["git", "push", "-q", "origin", "main:refs/heads/plan-X"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    )
    deleted = git.delete_remote_branches(clone, ["plan-X"])
    assert deleted == ["plan-X"]
    heads = subprocess.run(
        ["git", "ls-remote", "--heads", "origin"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "plan-X" not in heads


def test_delete_remote_branches_already_absent_no_raise(git_repo_with_remote):
    clone, _remote, _advance = git_repo_with_remote
    assert git.delete_remote_branches(clone, ["never-pushed"]) == []


def test_delete_remote_branches_empty_is_noop(git_repo_with_remote):
    clone, _remote, _advance = git_repo_with_remote
    assert git.delete_remote_branches(clone, []) == []


# --- detect_merge_conflicts (local git merge-tree probe) --------------------------------


def test_detect_merge_conflicts_clean(git_repo_with_remote):
    clone, _remote, advance = git_repo_with_remote
    # A branch that adds a NEW file; origin/main advances an UNRELATED file -> no conflict.
    _git(clone, "checkout", "-q", "-b", "feat")
    (clone / "new.txt").write_text("added\n", encoding="utf-8")
    _git(clone, "add", ".")
    _git(clone, "commit", "-qm", "feat add")
    advance()  # origin/main now touches f.txt only
    probe = git.detect_merge_conflicts(clone, base="main", branch_ref="feat")
    assert probe.determined is True
    assert probe.mergeable is True
    assert probe.conflicts == ()


def test_detect_merge_conflicts_conflicting(git_repo_with_remote):
    clone, _remote, advance = git_repo_with_remote
    # The branch and origin/main edit the SAME file divergently -> a genuine conflict.
    _git(clone, "checkout", "-q", "-b", "feat")
    (clone / "f.txt").write_text("feat-side\n", encoding="utf-8")
    _git(clone, "add", ".")
    _git(clone, "commit", "-qm", "feat edit")
    advance()  # origin/main writes f.txt = "advanced\n"
    probe = git.detect_merge_conflicts(clone, base="main", branch_ref="feat")
    assert probe.determined is True
    assert probe.mergeable is False
    assert probe.conflicts == ("f.txt",)


def test_detect_merge_conflicts_missing_base_is_undetermined(git_repo_with_remote):
    clone, _remote, _advance = git_repo_with_remote
    # A base ref that does not exist on origin: fetch fails -> fail-open undetermined.
    probe = git.detect_merge_conflicts(clone, base="no-such-base", branch_ref="HEAD")
    assert probe.determined is False
    assert probe.mergeable is False
    assert probe.conflicts == ()


def test_detect_merge_conflicts_no_remote_is_undetermined(git_repo):
    # No `origin` at all: the best-effort fetch fails -> undetermined (never raises).
    probe = git.detect_merge_conflicts(git_repo, base="main", branch_ref="HEAD")
    assert probe.determined is False
    assert probe.mergeable is False
    assert probe.conflicts == ()


def test_parse_merge_conflicts_unparseable_nonzero_yields_empty():
    # A determined nonzero exit whose stdout we can't parse still yields () (caller treats
    # determined+nonzero as conflicts-present).
    from perk.substrate.git import _parse_merge_conflicts

    assert _parse_merge_conflicts("treeoid\n\nCONFLICT (content): unparsed\n") == ()


def test_detect_merge_conflicts_unparseable_conflict_is_still_unmergeable(
    git_repo_with_remote, monkeypatch
):
    # Regression (review): a conflict EXIT (returncode 1) whose conflicted paths fail to parse
    # must still report `mergeable=False` from the exit code — never falsely clean because the
    # path tuple came back empty. mergeable is taken from the exit code, NOT len(conflicts) == 0.
    clone, _remote, _advance = git_repo_with_remote

    def fake_capture(args, **_kwargs):
        return subprocess.CompletedProcess(args, returncode=1, stdout="treeoid\n\n", stderr="")

    monkeypatch.setattr(git, "_run_capture", fake_capture)
    probe = git.detect_merge_conflicts(clone, base="main", branch_ref="HEAD")
    assert probe.determined is True
    assert probe.mergeable is False  # the bug would have made this True
    assert probe.conflicts == ()


# --- upstream_ref / merge_ff_only -----------------------------------------------------


def test_upstream_ref_returns_tracking_ref(git_repo_with_remote):
    clone, _remote, _advance = git_repo_with_remote
    assert git.upstream_ref(clone) == "origin/main"


def test_upstream_ref_none_without_upstream(git_repo):
    # A repo with no remote/upstream configured -> None (never raises).
    assert git.upstream_ref(git_repo) is None


def test_merge_ff_only_fast_forwards_clean(git_repo_with_remote):
    clone, _remote, advance = git_repo_with_remote
    advanced = advance()  # origin/main moves ahead of the clone's local main
    git.fetch(clone)
    assert git.merge_ff_only(clone, "origin/main") is True
    assert _sha(clone) == advanced  # the working tree fast-forwarded


def test_merge_ff_only_false_on_divergence(git_repo_with_remote):
    clone, _remote, advance = git_repo_with_remote
    # Local main commits independently while origin/main also advances -> diverged, no FF.
    (clone / "local.txt").write_text("local\n", encoding="utf-8")
    _git(clone, "add", ".")
    _git(clone, "commit", "-qm", "local-only commit")
    advance()
    git.fetch(clone)
    assert git.merge_ff_only(clone, "origin/main") is False
