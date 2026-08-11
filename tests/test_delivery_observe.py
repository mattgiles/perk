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
from perk.delivery.train import (
    BaseHeadObservation,
    BranchPrView,
    PrFactsView,
    StackView,
    TrainReconstructionError,
)
from perk.github import GitHubError, prs, stacks
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

    def test_base_head_is_the_authoritative_live_read(self, git_repo_with_remote) -> None:
        # ls-remote asks the remote itself: a freshly-pushed base head is observed WITHOUT a
        # fetch, and an absent branch is the honest "ref absent" arm (failure=None).
        clone, _remote, advance = git_repo_with_remote
        probe = observe.RepoGitProbe(clone)
        advanced = advance()
        assert probe.base_head("main") == BaseHeadObservation(sha=advanced, failure=None)
        assert probe.base_head("absent") == BaseHeadObservation(sha=None, failure=None)

    def test_base_head_deleted_base_beats_the_stale_tracking_ref(
        self, git_repo_with_remote
    ) -> None:
        # The trap the authoritative read exists for: a plain fetch has no --prune, so a
        # DELETED remote base leaves a stale remote-tracking ref that still resolves — the
        # live read must answer None (+ the ref-absent arm), never the stale tracking sha.
        clone, remote, _advance = git_repo_with_remote
        _g(clone, "push", "-q", "origin", "HEAD:refs/heads/develop")
        _g(clone, "fetch", "-q", "origin")  # materialize the tracking ref
        assert git_mod.remote_ref_exists(clone, "origin/develop") is True
        # An out-of-band deletion (another writer): the clone's own `push --delete` would
        # remove its tracking ref too, so delete directly on the bare remote instead.
        _g(remote, "update-ref", "-d", "refs/heads/develop")
        _g(clone, "fetch", "-q", "origin")  # no --prune: the tracking ref survives
        assert git_mod.remote_ref_exists(clone, "origin/develop") is True  # the stale ref
        assert observe.RepoGitProbe(clone).base_head("develop") == BaseHeadObservation(
            sha=None, failure=None
        )

    def test_base_head_read_failure_degrades_into_the_failure_arm(
        self, git_repo_with_remote, monkeypatch
    ) -> None:
        clone, _remote, _advance = git_repo_with_remote

        def boom(*_args: object, **_kwargs: object) -> None:
            raise git_mod.GitError("network down")

        monkeypatch.setattr(git_mod, "remote_branch_head", boom)
        observation = observe.RepoGitProbe(clone).base_head("main")
        assert observation.sha is None
        assert observation.failure is not None and "network down" in observation.failure

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

    def test_pr_for_branch_converts_to_the_view_type(self, tmp_path, monkeypatch) -> None:
        pr = prs.PullRequest(
            number=201, url="u", is_draft=False, state="MERGED", existed=True, head_ref="plan-101"
        )
        seen: list[str] = []

        def fake(*, branch: str, repo_root) -> prs.PullRequest:
            seen.append(branch)
            return pr

        monkeypatch.setattr(prs, "find_pr_for_branch", fake)
        view = observe.GatewayGitHubProbe(tmp_path).pr_for_branch("plan-101")
        assert view == BranchPrView(number=201, state="MERGED")
        assert seen == ["plan-101"]

    def test_pr_for_branch_none_passthrough(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(prs, "find_pr_for_branch", lambda **_kw: None)
        assert observe.GatewayGitHubProbe(tmp_path).pr_for_branch("plan-101") is None

    def test_pr_for_branch_failure_is_typed_github_error(self, tmp_path, monkeypatch) -> None:
        # A STABLE read (§8.54): the cancellation proof must fail closed on an unobservable
        # authority — never silently read "no PR".
        def boom(**_kw: object) -> None:
            raise GitHubError("HTTP 500")

        monkeypatch.setattr(prs, "find_pr_for_branch", boom)
        with pytest.raises(TrainReconstructionError) as excinfo:
            observe.GatewayGitHubProbe(tmp_path).pr_for_branch("plan-101")
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
