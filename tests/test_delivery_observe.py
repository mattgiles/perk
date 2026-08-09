"""Tests for the delivery module's production wiring leaf (``perk/delivery/observe.py``).

The seam the pure-reconstruction suite deliberately fakes: ``RepoGitProbe`` over a real local
git repo + bare remote (hermetic, offline) and ``GatewayGitHubProbe`` over monkeypatched
``perk.github.stacks`` reads — pinning both the successful conversions into the ``train.py``
view types and the §8.44 failure-posture split (`GitError` → typed ``git_error``, stable
``GitHubError`` → typed ``github_error``, preview ``GitHubError`` → ``available=False``).
"""

import subprocess
from pathlib import Path

import pytest

from perk.delivery import observe
from perk.delivery.train import PrFactsView, StackView, TrainReconstructionError
from perk.github import GitHubError, stacks
from perk.substrate import git as git_mod


def _g(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


# ----------------------------------------------------------------- RepoGitProbe


class TestRepoGitProbe:
    def test_fetch_and_remote_branch_sha(self, git_repo_with_remote) -> None:
        clone, _remote, advance = git_repo_with_remote
        probe = observe.RepoGitProbe(clone)
        advanced = advance()
        probe.fetch()
        # ls-remote asks the remote itself; an absent branch is an observation, not an error.
        assert probe.remote_branch_sha("main") == advanced
        assert probe.remote_branch_sha("absent") is None

    def test_fetch_failure_is_typed_git_error(self, git_repo_with_remote, monkeypatch) -> None:
        clone, _remote, _advance = git_repo_with_remote

        def boom(*_args: object, **_kwargs: object) -> None:
            raise git_mod.GitError("network down")

        monkeypatch.setattr(git_mod, "fetch", boom)
        with pytest.raises(TrainReconstructionError) as excinfo:
            observe.RepoGitProbe(clone).fetch()
        assert excinfo.value.error_type == "git_error"

    def test_remote_branch_sha_failure_is_typed_git_error(
        self, git_repo_with_remote, monkeypatch
    ) -> None:
        clone, _remote, _advance = git_repo_with_remote

        def boom(*_args: object, **_kwargs: object) -> None:
            raise git_mod.GitError("network down")

        monkeypatch.setattr(git_mod, "remote_branch_head", boom)
        with pytest.raises(TrainReconstructionError) as excinfo:
            observe.RepoGitProbe(clone).remote_branch_sha("main")
        assert excinfo.value.error_type == "git_error"

    def test_is_ancestor_arms(self, git_repo_with_remote) -> None:
        clone, _remote, advance = git_repo_with_remote
        probe = observe.RepoGitProbe(clone)
        initial = _g(clone, "rev-parse", "HEAD").strip()
        advanced = advance()
        probe.fetch()  # bring the advanced objects local
        assert probe.is_ancestor(initial, advanced) is True
        assert probe.is_ancestor(advanced, initial) is False
        # Unavailable objects: ancestry is unknowable, never an error.
        assert probe.is_ancestor("f" * 40, advanced) is None
        assert probe.is_ancestor(initial, "f" * 40) is None

    def test_worktree_branches_maps_the_writer_axis(self, git_repo_with_remote) -> None:
        clone, _remote, _advance = git_repo_with_remote
        side = clone.parent / "side-wt"
        _g(clone, "worktree", "add", "-q", "-b", "side", str(side))
        (side / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")
        facts = {f.branch: f for f in observe.RepoGitProbe(clone).worktree_branches()}
        assert facts["main"].dirty is False
        assert facts["side"].dirty is True
        assert facts["side"].path == str(side)


# ----------------------------------------------------------------- GatewayGitHubProbe


class TestGatewayGitHubProbe:
    def test_pr_facts_converts_to_the_view_type(self, tmp_path, monkeypatch) -> None:
        facts = stacks.PrDeliveryFacts(
            number=201,
            state="OPEN",
            is_draft=True,
            base_ref="main",
            head_ref="plan-101",
            head_sha="b" * 40,
        )
        monkeypatch.setattr(stacks, "pr_delivery_facts", lambda **_kw: facts)
        view = observe.GatewayGitHubProbe(tmp_path).pr_facts(201)
        assert view == PrFactsView(
            number=201,
            state="OPEN",
            is_draft=True,
            base_ref="main",
            head_ref="plan-101",
            head_sha="b" * 40,
        )

    def test_pr_facts_none_passthrough(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(stacks, "pr_delivery_facts", lambda **_kw: None)
        assert observe.GatewayGitHubProbe(tmp_path).pr_facts(201) is None

    def test_pr_facts_failure_is_typed_github_error(self, tmp_path, monkeypatch) -> None:
        def boom(**_kw: object) -> None:
            raise GitHubError("HTTP 500")

        monkeypatch.setattr(stacks, "pr_delivery_facts", boom)
        with pytest.raises(TrainReconstructionError) as excinfo:
            observe.GatewayGitHubProbe(tmp_path).pr_facts(201)
        assert excinfo.value.error_type == "github_error"

    def test_pr_stack_failure_degrades_to_unavailable(self, tmp_path, monkeypatch) -> None:
        # The preview read's tolerance lives at THIS seam too: even a raised GitHubError
        # (e.g. the PR-lookup-miss raise) degrades, never aborts status.
        def boom(**_kw: object) -> None:
            raise GitHubError("could not resolve")

        monkeypatch.setattr(stacks, "pr_stack", boom)
        assert observe.GatewayGitHubProbe(tmp_path).pr_stack(201) == StackView(available=False)

    def test_pr_stack_unavailable_passthrough(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(
            stacks, "pr_stack", lambda **_kw: stacks.StackObservation(available=False)
        )
        assert observe.GatewayGitHubProbe(tmp_path).pr_stack(201) == StackView(available=False)

    def test_pr_stack_null_stack_is_not_stacked(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(
            stacks, "pr_stack", lambda **_kw: stacks.StackObservation(available=True, stack=None)
        )
        assert observe.GatewayGitHubProbe(tmp_path).pr_stack(201) == StackView(
            available=True, stacked=False
        )

    def test_pr_stack_converts_entries_and_truncation(self, tmp_path, monkeypatch) -> None:
        observation = stacks.StackObservation(
            available=True,
            stack=stacks.StackFacts(
                number=7,
                size=2,
                entries=(
                    stacks.StackEntryFacts(position=1, pr_number=201),
                    stacks.StackEntryFacts(position=2, pr_number=202),
                ),
                truncated=True,
            ),
        )
        monkeypatch.setattr(stacks, "pr_stack", lambda **_kw: observation)
        view = observe.GatewayGitHubProbe(tmp_path).pr_stack(201)
        assert view.available is True and view.stacked is True and view.truncated is True
        assert [(e.position, e.pr_number) for e in view.entries] == [(1, 201), (2, 202)]


# ----------------------------------------------------------------- composition


def test_resolve_train_reads_composes_offline(git_repo_with_remote) -> None:
    clone, _remote, _advance = git_repo_with_remote
    reads = observe.resolve_train_reads(clone)
    assert reads.trunk == "main"
    assert isinstance(reads.git, observe.RepoGitProbe)
    assert isinstance(reads.github, observe.GatewayGitHubProbe)
