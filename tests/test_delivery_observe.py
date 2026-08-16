"""Tests for the delivery module's production wiring leaf (``perk/delivery/observe.py``).

The seams the pure-reconstruction suite deliberately fakes: lazy aligned persistence,
``RepoDeliveryGit`` over a real local repo + bare remote (hermetic, offline), and
``RepoDeliveryGitHub`` over monkeypatched GitHub gateways. The tests pin exact publication
delegation plus the status failure-posture split (`GitError` → typed ``git_error``, stable
`GitHubError` → typed ``github_error``, preview `GitHubError` → `available=False`).
"""

import subprocess
from pathlib import Path

import pytest

from perk.backends.issue_backend import PlanHeaderUpdate
from perk.delivery import land, observe
from perk.delivery._fakes import FakeDeliveryGit, FakeDeliveryPersistence
from perk.delivery.facade import (
    Delivery,
    DeliveryError,
    DeliveryGit,
    DeliveryGitHub,
    PublishRequest,
)
from perk.delivery.train import (
    BaseHeadObservation,
    PrFactsView,
    StackView,
    TrainReconstructionError,
)
from perk.delivery.writers import WriterObservationError
from perk.github import GitHubError, prs, stacks
from perk.run import discovery
from perk.substrate import git as git_mod


def _g(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


# ----------------------------------------------------------------- RepoDeliveryPersistence


class TestRepoDeliveryPersistence:
    def test_publication_plan_body_and_header_delegate_exactly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[object, ...]] = []

        class _Issues:
            def get_plan_body(self, *, issue_id: str) -> str | None:
                calls.append(("body", issue_id))
                return "Plan body"

            def update_plan_header(
                self, *, issue_id: str, fields: dict[str, object]
            ) -> PlanHeaderUpdate:
                calls.append(("header", issue_id, dict(fields)))
                return PlanHeaderUpdate(fields_updated=tuple(fields), dry_run=False)

        authority = observe.RepoDeliveryPersistence(tmp_path)
        monkeypatch.setattr(authority, "_resolve", lambda: (object(), _Issues(), object()))

        assert authority.get_plan_body(issue_id="101") == "Plan body"
        assert authority.update_plan_header(
            issue_id="101", fields={"branch": "plan-101"}
        ) == PlanHeaderUpdate(fields_updated=("branch",), dry_run=False)
        assert calls == [
            ("body", "101"),
            ("header", "101", {"branch": "plan-101"}),
        ]


# ----------------------------------------------------------------- RepoDeliveryGit


class TestRepoDeliveryGit:
    def test_fetch_and_remote_branch_sha(self, git_repo_with_remote) -> None:
        clone, _remote, advance = git_repo_with_remote
        probe = observe.RepoDeliveryGit(clone)
        assert probe.trunk_branch() == "main"
        advanced = advance()
        probe.fetch()
        # ls-remote asks the remote itself; an absent branch is an observation, not an error.
        assert probe.remote_branch_sha("main") == advanced
        assert probe.remote_branch_sha("absent") is None

    def test_trunk_failure_is_typed_git_error(self, git_repo_with_remote, monkeypatch) -> None:
        clone, _remote, _advance = git_repo_with_remote

        def boom(*_args: object, **_kwargs: object) -> None:
            raise git_mod.GitError("no trunk")

        monkeypatch.setattr(git_mod, "detect_trunk_branch", boom)
        with pytest.raises(TrainReconstructionError) as excinfo:
            observe.RepoDeliveryGit(clone).trunk_branch()
        assert excinfo.value.error_type == "git_error"

    def test_fetch_failure_is_typed_git_error(self, git_repo_with_remote, monkeypatch) -> None:
        clone, _remote, _advance = git_repo_with_remote

        def boom(*_args: object, **_kwargs: object) -> None:
            raise git_mod.GitError("network down")

        monkeypatch.setattr(git_mod, "fetch", boom)
        with pytest.raises(TrainReconstructionError) as excinfo:
            observe.RepoDeliveryGit(clone).fetch()
        assert excinfo.value.error_type == "git_error"

    def test_push_urls_converts_success_and_expected_failure(
        self, git_repo_with_remote, monkeypatch
    ) -> None:
        clone, _remote, _advance = git_repo_with_remote
        seen: list[tuple[Path, str]] = []

        def success(root: Path, remote: str = "origin") -> list[str]:
            seen.append((root, remote))
            return ["fake://one", "fake://two"]

        monkeypatch.setattr(git_mod, "push_urls", success)
        probe = observe.RepoDeliveryGit(clone, remote="upstream")
        assert probe.push_urls() == DeliveryGit.PushUrlsResult(urls=("fake://one", "fake://two"))
        assert seen == [(clone, "upstream")]

        def expected(*_args: object, **_kwargs: object) -> list[str]:
            raise git_mod.GitError("no remote")

        monkeypatch.setattr(git_mod, "push_urls", expected)
        assert probe.push_urls() == DeliveryGit.ProbeError(message="no remote")

    def test_atomic_push_converts_success_and_expected_failure(
        self, git_repo_with_remote, monkeypatch
    ) -> None:
        clone, _remote, _advance = git_repo_with_remote
        seen: list[tuple[Path, str, str, str]] = []

        def success(root: Path, *, push_url: str, base_branch: str, base_sha: str) -> None:
            seen.append((root, push_url, base_branch, base_sha))

        monkeypatch.setattr(git_mod, "probe_atomic_push", success)
        probe = observe.RepoDeliveryGit(clone)
        assert (
            probe.probe_atomic_push(push_url="fake://origin", base_branch="main", base_sha="a")
            == DeliveryGit.AtomicPushResult()
        )
        assert seen == [(clone, "fake://origin", "main", "a")]

        def expected(*_args: object, **_kwargs: object) -> None:
            raise git_mod.GitError("atomic unsupported")

        monkeypatch.setattr(git_mod, "probe_atomic_push", expected)
        assert probe.probe_atomic_push(
            push_url="fake://origin", base_branch="main", base_sha="a"
        ) == DeliveryGit.ProbeError(message="atomic unsupported")

    def test_sync_git_methods_are_direct_substrate_delegates(
        self, git_repo_with_remote, monkeypatch
    ) -> None:
        clone, _remote, _advance = git_repo_with_remote
        worktree = clone.parent / "sync-op"
        update = git_mod.RefUpdate(branch="plan-1", expected_remote_sha="a", new_sha="b")
        rebase = git_mod.RebaseConflict(detail="conflict")
        calls: list[tuple] = []

        monkeypatch.setattr(
            git_mod,
            "resolve_commit",
            lambda root, ref: calls.append(("resolve", root, ref)) or "c" * 40,
        )
        monkeypatch.setattr(
            git_mod,
            "push_atomic_with_leases",
            lambda root, updates: calls.append(("push", root, tuple(updates))),
        )
        monkeypatch.setattr(
            git_mod,
            "push_with_exact_lease",
            lambda root, branch, *, expected_remote_sha: calls.append(
                ("lease", root, branch, expected_remote_sha)
            ),
        )
        monkeypatch.setattr(
            git_mod, "update_ref", lambda root, ref, sha: calls.append(("update", root, ref, sha))
        )
        monkeypatch.setattr(
            git_mod, "delete_ref", lambda root, ref: calls.append(("delete", root, ref))
        )
        monkeypatch.setattr(
            git_mod,
            "list_refs",
            lambda root, prefix: calls.append(("list", root, prefix)) or ["r1"],
        )
        monkeypatch.setattr(
            git_mod,
            "worktree_add_detached",
            lambda root, path, commit: calls.append(("add", root, path, commit)),
        )
        monkeypatch.setattr(
            git_mod,
            "worktree_remove",
            lambda root, path, *, force: calls.append(("remove", root, path, force)),
        )
        monkeypatch.setattr(git_mod, "worktree_prune", lambda root: calls.append(("prune", root)))
        monkeypatch.setattr(
            git_mod,
            "checkout_detached",
            lambda path, sha: calls.append(("checkout", path, sha)),
        )
        monkeypatch.setattr(
            git_mod,
            "rebase_onto",
            lambda path, *, onto, upstream: (
                calls.append(("rebase", path, onto, upstream)) or rebase
            ),
        )
        monkeypatch.setattr(
            git_mod,
            "rebase_in_progress",
            lambda path: calls.append(("rebasing", path)) or True,
        )
        monkeypatch.setattr(
            git_mod, "is_dirty", lambda path: calls.append(("dirty", path)) or False
        )

        authority = observe.RepoDeliveryGit(clone)
        assert authority.repo_root == clone
        assert authority.resolve_commit("HEAD", cwd=worktree) == "c" * 40
        authority.push_with_exact_lease("plan-1", expected_remote_sha="a")
        authority.push_atomic((update,))
        authority.update_ref("refs/perk/x", "d" * 40)
        authority.delete_ref("refs/perk/x")
        assert authority.list_refs("refs/perk/") == ("r1",)
        authority.add_detached_worktree(worktree, "e" * 40)
        authority.remove_worktree(worktree)
        authority.prune_worktrees()
        authority.checkout_detached(worktree, "f" * 40)
        assert authority.rebase_onto(worktree, onto="a", upstream="b") is rebase
        assert authority.rebase_in_progress(worktree) is True
        assert authority.worktree_dirty(worktree) is False

        assert calls == [
            ("resolve", worktree, "HEAD"),
            ("lease", clone, "plan-1", "a"),
            ("push", clone, (update,)),
            ("update", clone, "refs/perk/x", "d" * 40),
            ("delete", clone, "refs/perk/x"),
            ("list", clone, "refs/perk/"),
            ("add", clone, worktree, "e" * 40),
            ("remove", clone, worktree, True),
            ("prune", clone),
            ("checkout", worktree, "f" * 40),
            ("rebase", worktree, "a", "b"),
            ("rebasing", worktree),
            ("dirty", worktree),
        ]

    def test_sync_git_mutation_errors_reuse_raw_substrate_types(
        self, git_repo_with_remote, monkeypatch
    ) -> None:
        clone, _remote, _advance = git_repo_with_remote
        rejected = git_mod.PushRejectedError("lease rejected")

        def reject(*args: object, **kwargs: object) -> None:
            raise rejected

        monkeypatch.setattr(git_mod, "push_atomic_with_leases", reject)
        monkeypatch.setattr(git_mod, "push_with_exact_lease", reject)
        with pytest.raises(git_mod.PushRejectedError) as lease_error:
            observe.RepoDeliveryGit(clone).push_with_exact_lease("plan-1", expected_remote_sha="a")
        assert lease_error.value is rejected
        with pytest.raises(git_mod.PushRejectedError) as excinfo:
            observe.RepoDeliveryGit(clone).push_atomic(
                (git_mod.RefUpdate(branch="plan-1", expected_remote_sha="a", new_sha="b"),)
            )
        assert excinfo.value is rejected

    def test_prepare_git_probes_propagate_unexpected_errors(
        self, git_repo_with_remote, monkeypatch
    ) -> None:
        clone, _remote, _advance = git_repo_with_remote

        def boom(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("programming error")

        monkeypatch.setattr(git_mod, "push_urls", boom)
        with pytest.raises(RuntimeError, match="programming error"):
            observe.RepoDeliveryGit(clone).push_urls()

        monkeypatch.setattr(git_mod, "probe_atomic_push", boom)
        with pytest.raises(RuntimeError, match="programming error"):
            observe.RepoDeliveryGit(clone).probe_atomic_push(
                push_url="fake://origin", base_branch="main", base_sha="a"
            )

    def test_remote_branch_sha_failure_is_typed_git_error(
        self, git_repo_with_remote, monkeypatch
    ) -> None:
        clone, _remote, _advance = git_repo_with_remote
        failure = git_mod.GitError("network down")

        def boom(*_args: object, **_kwargs: object) -> None:
            raise failure

        monkeypatch.setattr(git_mod, "remote_branch_head", boom)
        with pytest.raises(TrainReconstructionError) as excinfo:
            observe.RepoDeliveryGit(clone).remote_branch_sha("main")
        assert excinfo.value.error_type == "git_error"
        assert excinfo.value.__cause__ is failure

    def test_resolve_commit_failure_preserves_raw_cause(
        self, git_repo_with_remote, monkeypatch
    ) -> None:
        clone, _remote, _advance = git_repo_with_remote
        failure = git_mod.GitError("object unavailable")

        def boom(*_args: object, **_kwargs: object) -> None:
            raise failure

        monkeypatch.setattr(git_mod, "resolve_commit", boom)
        with pytest.raises(TrainReconstructionError) as excinfo:
            observe.RepoDeliveryGit(clone).resolve_commit("HEAD")
        assert excinfo.value.error_type == "git_error"
        assert excinfo.value.__cause__ is failure

    def test_is_ancestor_arms(self, git_repo_with_remote) -> None:
        clone, _remote, advance = git_repo_with_remote
        probe = observe.RepoDeliveryGit(clone)
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
        probe = observe.RepoDeliveryGit(clone)
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
        assert observe.RepoDeliveryGit(clone).base_head("develop") == BaseHeadObservation(
            sha=None, failure=None
        )

    def test_base_head_read_failure_degrades_into_the_failure_arm(
        self, git_repo_with_remote, monkeypatch
    ) -> None:
        clone, _remote, _advance = git_repo_with_remote

        def boom(*_args: object, **_kwargs: object) -> None:
            raise git_mod.GitError("network down")

        monkeypatch.setattr(git_mod, "remote_branch_head", boom)
        observation = observe.RepoDeliveryGit(clone).base_head("main")
        assert observation.sha is None
        assert observation.failure is not None and "network down" in observation.failure

    def test_worktree_branches_maps_the_writer_axis(self, git_repo_with_remote) -> None:
        clone, _remote, _advance = git_repo_with_remote
        side = clone.parent / "side-wt"
        _g(clone, "worktree", "add", "-q", "-b", "side", str(side))
        (side / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")
        facts = {f.branch: f for f in observe.RepoDeliveryGit(clone).worktree_branches()}
        assert facts["main"].dirty is False
        assert facts["side"].dirty is True
        assert facts["side"].path == str(side)


# ----------------------------------------------------------------- RepoDeliveryGitHub


class TestRepoDeliveryGitHub:
    def test_stack_capability_passes_through_fail_closed_bool(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        roots: list[Path] = []
        results = iter((False, True))

        def stack_capability(root: Path) -> bool:
            roots.append(root)
            return next(results)

        monkeypatch.setattr(stacks, "stack_capability", stack_capability)
        probe = observe.RepoDeliveryGitHub(tmp_path)
        assert probe.stack_capability() is False
        assert probe.stack_capability() is True
        assert roots == [tmp_path, tmp_path]

    def test_base_merge_rules_converts_success_and_expected_failure(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        seen: list[tuple[Path, str]] = []

        def success(root: Path, base: str) -> stacks.MergeRules:
            seen.append((root, base))
            return stacks.MergeRules(squash_allowed=False, merge_queue_required=True)

        monkeypatch.setattr(stacks, "base_merge_rules", success)
        probe = observe.RepoDeliveryGitHub(tmp_path)
        assert probe.base_merge_rules("develop") == DeliveryGitHub.MergeRules(
            squash_allowed=False, merge_queue_required=True
        )

        def expected(root: Path, base: str) -> stacks.MergeRules:
            seen.append((root, base))
            raise GitHubError("HTTP 500")

        monkeypatch.setattr(stacks, "base_merge_rules", expected)
        assert probe.base_merge_rules("develop") == DeliveryGitHub.ProbeError(message="HTTP 500")
        assert seen == [(tmp_path, "develop"), (tmp_path, "develop")]

    def test_base_merge_rules_propagates_unexpected_error(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        def boom(*_args: object, **_kwargs: object) -> stacks.MergeRules:
            raise RuntimeError("programming error")

        monkeypatch.setattr(stacks, "base_merge_rules", boom)
        with pytest.raises(RuntimeError, match="programming error"):
            observe.RepoDeliveryGitHub(tmp_path).base_merge_rules("main")

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
        view = observe.RepoDeliveryGitHub(tmp_path).pr_facts(201)
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
        assert observe.RepoDeliveryGitHub(tmp_path).pr_facts(201) is None

    def test_pr_facts_failure_is_typed_github_error(self, tmp_path, monkeypatch) -> None:
        failure = GitHubError("HTTP 500")

        def boom(**_kw: object) -> None:
            raise failure

        monkeypatch.setattr(stacks, "pr_delivery_facts", boom)
        with pytest.raises(TrainReconstructionError) as excinfo:
            observe.RepoDeliveryGitHub(tmp_path).pr_facts(201)
        assert excinfo.value.error_type == "github_error"
        assert excinfo.value.__cause__ is failure

    def test_strict_stack_returns_rich_facts_and_fails_closed(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        observed = stacks.StackRestFacts(
            number=9,
            size=2,
            entries=(
                stacks.StackRestEntry(201, "OPEN", True, False, "plan-1", "a"),
                stacks.StackRestEntry(202, "OPEN", True, False, "plan-2", "b"),
            ),
        )
        monkeypatch.setattr(stacks, "stack_for_pr", lambda **kwargs: observed)
        authority = observe.RepoDeliveryGitHub(tmp_path)
        assert authority.strict_stack(201) == observed

        monkeypatch.setattr(stacks, "stack_for_pr", lambda **kwargs: None)
        assert authority.strict_stack(201) is None

        failure = GitHubError("HTTP 500")

        def unavailable(**kwargs) -> None:
            raise failure

        monkeypatch.setattr(stacks, "stack_for_pr", unavailable)
        with pytest.raises(TrainReconstructionError) as excinfo:
            authority.strict_stack(201)
        assert excinfo.value.error_type == "github_error"
        assert excinfo.value.__cause__ is failure

    def test_active_writers_use_only_a_corroborated_exact_trigger_pair(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        calls: list[dict[str, object]] = []

        def active(root, plan_ids, **kwargs) -> frozenset[str]:
            calls.append({"root": root, "plan_ids": plan_ids, **kwargs})
            return frozenset({"102"})

        monkeypatch.setattr(discovery, "active_writer_plan_ids", active)
        monkeypatch.setattr(
            observe,
            "_corroborated_remote_run_id",
            lambda root, plan_id, run_id: run_id if plan_id == "101" else None,
        )
        authority = observe.RepoDeliveryGitHub(tmp_path)

        assert authority.active_writer_plan_ids(
            ("101", "102"), trigger_plan_id="101", trigger_run_id="01RUN"
        ) == frozenset({"102"})
        assert authority.active_writer_plan_ids(
            ("101",), trigger_plan_id="999", trigger_run_id="01RUN"
        ) == frozenset({"102"})
        assert authority.active_writer_plan_ids(
            ("101",), trigger_plan_id=None, trigger_run_id=None
        ) == frozenset({"102"})
        assert calls == [
            {
                "root": tmp_path,
                "plan_ids": ["101", "102"],
                "exclude_run_id": "01RUN",
                "exclude_plan_id": "101",
            },
            {
                "root": tmp_path,
                "plan_ids": ["101"],
                "exclude_run_id": None,
                "exclude_plan_id": None,
            },
            {
                "root": tmp_path,
                "plan_ids": ["101"],
                "exclude_run_id": None,
                "exclude_plan_id": None,
            },
        ]

    def test_active_writer_expected_failure_is_typed_and_unexpected_propagates(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        authority = observe.RepoDeliveryGitHub(tmp_path)

        def unavailable(*args, **kwargs) -> None:
            raise GitHubError("API down")

        monkeypatch.setattr(discovery, "active_writer_plan_ids", unavailable)
        with pytest.raises(WriterObservationError, match="API down"):
            authority.active_writer_plan_ids(("101",), trigger_plan_id=None, trigger_run_id=None)

        def programmer_bug(*args, **kwargs) -> None:
            raise RuntimeError("bug")

        monkeypatch.setattr(discovery, "active_writer_plan_ids", programmer_bug)
        with pytest.raises(RuntimeError, match="bug"):
            authority.active_writer_plan_ids(("101",), trigger_plan_id=None, trigger_run_id=None)

    def test_pr_for_branch_returns_the_rich_pr(self, tmp_path, monkeypatch) -> None:
        pr = prs.PullRequest(
            number=201, url="u", is_draft=False, state="MERGED", existed=True, head_ref="plan-101"
        )
        seen: list[str] = []

        def fake(*, branch: str, repo_root) -> prs.PullRequest:
            seen.append(branch)
            return pr

        monkeypatch.setattr(prs, "find_pr_for_branch", fake)
        view = observe.RepoDeliveryGitHub(tmp_path).pr_for_branch("plan-101")
        assert view == pr
        assert seen == ["plan-101"]

    def test_pr_for_branch_none_passthrough(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(prs, "find_pr_for_branch", lambda **_kw: None)
        assert observe.RepoDeliveryGitHub(tmp_path).pr_for_branch("plan-101") is None

    def test_pr_for_branch_failure_is_typed_github_error(self, tmp_path, monkeypatch) -> None:
        # A STABLE read (§8.54): the cancellation proof must fail closed on an unobservable
        # authority — never silently read "no PR".
        failure = GitHubError("HTTP 500")

        def boom(**_kw: object) -> None:
            raise failure

        monkeypatch.setattr(prs, "find_pr_for_branch", boom)
        with pytest.raises(TrainReconstructionError) as excinfo:
            observe.RepoDeliveryGitHub(tmp_path).pr_for_branch("plan-101")
        assert excinfo.value.error_type == "github_error"
        assert excinfo.value.__cause__ is failure

    def test_publish_bridge_unwraps_the_real_branch_adapter_cause(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        failure = GitHubError("HTTP 500")

        def boom(**_kw: object) -> None:
            raise failure

        monkeypatch.setattr(prs, "find_pr_for_branch", boom)
        service = Delivery(
            persistence=FakeDeliveryPersistence(),
            git=FakeDeliveryGit(repo_root=tmp_path),
            github=observe.RepoDeliveryGitHub(tmp_path),
        )
        with pytest.raises(DeliveryError) as excinfo:
            service.publish(PublishRequest(kind="ready", plan_id="101", delivery="incremental"))
        assert (excinfo.value.error_type, excinfo.value.phase, excinfo.value.origin) == (
            "github_error",
            "ready",
            "github",
        )
        assert excinfo.value.__cause__ is failure

    def test_publication_github_effects_delegate_exact_arguments(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr = prs.PullRequest(42, "u/42", True, "OPEN", False)
        body_update = prs.PrBodyUpdate(number=42, dry_run=False)
        outcome = stacks.StackMutationOutcome(
            applied=True,
            status=201,
            retry_after_seconds=None,
            rate_limited=False,
            raw_detail="created",
        )
        calls: list[tuple[object, ...]] = []
        monkeypatch.setattr(
            prs,
            "get_pr",
            lambda **kwargs: calls.append(("get", kwargs)) or pr,
        )
        monkeypatch.setattr(
            prs,
            "create_pr",
            lambda **kwargs: calls.append(("create", kwargs)) or pr,
        )
        monkeypatch.setattr(
            prs,
            "update_pr_body",
            lambda **kwargs: calls.append(("body", kwargs)) or body_update,
        )
        monkeypatch.setattr(
            prs,
            "update_pr_base",
            lambda **kwargs: calls.append(("base", kwargs)),
        )
        monkeypatch.setattr(
            prs,
            "reopen_pr",
            lambda **kwargs: calls.append(("reopen", kwargs)),
        )
        monkeypatch.setattr(
            prs,
            "mark_pr_ready",
            lambda **kwargs: calls.append(("ready", kwargs)),
        )
        monkeypatch.setattr(
            stacks,
            "create_stack",
            lambda **kwargs: calls.append(("stack-create", kwargs)) or outcome,
        )
        monkeypatch.setattr(
            stacks,
            "append_to_stack",
            lambda **kwargs: calls.append(("stack-append", kwargs)) or outcome,
        )
        authority = observe.RepoDeliveryGitHub(tmp_path)

        assert authority.get_pr(42) is pr
        assert (
            authority.create_pr(head="plan-101", base="main", title="Plan", body="body", draft=True)
            is pr
        )
        assert authority.update_pr_body(42, body="new") is body_update
        authority.update_pr_base(42, base="develop")
        authority.reopen_pr(42)
        authority.mark_pr_ready(42)
        assert authority.create_stack((41, 42)) is outcome
        assert authority.append_stack(9, pull_requests=(42,)) is outcome
        assert calls == [
            ("get", {"number": 42, "repo_root": tmp_path}),
            (
                "create",
                {
                    "head": "plan-101",
                    "base": "main",
                    "title": "Plan",
                    "body": "body",
                    "repo_root": tmp_path,
                    "draft": True,
                },
            ),
            ("body", {"number": 42, "body": "new", "repo_root": tmp_path}),
            ("base", {"number": 42, "base": "develop", "repo_root": tmp_path}),
            ("reopen", {"number": 42, "repo_root": tmp_path}),
            ("ready", {"number": 42, "repo_root": tmp_path}),
            ("stack-create", {"pull_requests": (41, 42), "repo_root": tmp_path}),
            (
                "stack-append",
                {"stack_number": 9, "pull_requests": (42,), "repo_root": tmp_path},
            ),
        ]

    def test_publication_github_effect_errors_remain_raw(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        failure = GitHubError("HTTP 500")

        def boom(**kwargs: object) -> None:
            raise failure

        monkeypatch.setattr(prs, "get_pr", boom)
        with pytest.raises(GitHubError) as excinfo:
            observe.RepoDeliveryGitHub(tmp_path).get_pr(42)
        assert excinfo.value is failure

    def test_pr_stack_failure_degrades_to_unavailable(self, tmp_path, monkeypatch) -> None:
        # The preview read's tolerance lives at THIS seam too: even a raised GitHubError
        # (e.g. the PR-lookup-miss raise) degrades, never aborts status.
        def boom(**_kw: object) -> None:
            raise GitHubError("could not resolve")

        monkeypatch.setattr(stacks, "pr_stack", boom)
        assert observe.RepoDeliveryGitHub(tmp_path).pr_stack(201) == StackView(available=False)

    def test_pr_stack_unavailable_passthrough(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(
            stacks, "pr_stack", lambda **_kw: stacks.StackObservation(available=False)
        )
        assert observe.RepoDeliveryGitHub(tmp_path).pr_stack(201) == StackView(available=False)

    def test_pr_stack_null_stack_is_not_stacked(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(
            stacks, "pr_stack", lambda **_kw: stacks.StackObservation(available=True, stack=None)
        )
        assert observe.RepoDeliveryGitHub(tmp_path).pr_stack(201) == StackView(
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
        view = observe.RepoDeliveryGitHub(tmp_path).pr_stack(201)
        assert view.available is True and view.stacked is True and view.truncated is True
        assert [(e.position, e.pr_number) for e in view.entries] == [(1, 201), (2, 202)]


# ----------------------------------------------------------------- GatewayLandObservations


class TestGatewayLandObservations:
    def test_pr_readiness_converts_to_the_view_type(self, tmp_path, monkeypatch) -> None:
        facts = stacks.PrLandFacts(
            number=501,
            state="OPEN",
            is_draft=False,
            base_ref="main",
            head_ref="plan-101",
            head_sha="b" * 40,
            mergeable="MERGEABLE",
            merge_state_status="CLEAN",
            review_decision=None,
            rollup_state="SUCCESS",
            checks=(stacks.CheckFacts(name="ci", is_required=True, outcome="passed"),),
            unresolved_thread_count=3,
        )
        seen: list[int] = []

        def fake(*, number: int, repo_root) -> stacks.PrLandFacts:
            seen.append(number)
            return facts

        monkeypatch.setattr(stacks, "pr_land_facts", fake)
        view = observe.GatewayLandObservations(tmp_path, base="main").pr_readiness(501)
        # The gateway's rollup aggregate state is deliberately NOT part of the core view
        # (it is consumed for pagination coherence; the assessment classifies the
        # per-check outcomes + mergeStateStatus instead).
        assert view == land.PrLandView(
            number=501,
            state="OPEN",
            is_draft=False,
            base_ref="main",
            head_ref="plan-101",
            head_sha="b" * 40,
            mergeable="MERGEABLE",
            merge_state_status="CLEAN",
            review_decision=None,
            checks=(land.CheckView(name="ci", is_required=True, outcome="passed"),),
            unresolved_thread_count=3,
        )
        assert seen == [501]

    def test_pr_readiness_none_passthrough(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(stacks, "pr_land_facts", lambda **_kw: None)
        assert observe.GatewayLandObservations(tmp_path, base="main").pr_readiness(501) is None

    def test_pr_readiness_failure_wraps_to_land_observation_error(
        self, tmp_path, monkeypatch
    ) -> None:
        def boom(**_kw: object) -> None:
            raise GitHubError("HTTP 500")

        monkeypatch.setattr(stacks, "pr_land_facts", boom)
        with pytest.raises(land.LandObservationError, match="HTTP 500"):
            observe.GatewayLandObservations(tmp_path, base="main").pr_readiness(501)

    def test_base_merge_rules_converts_and_uses_the_bound_base(self, tmp_path, monkeypatch) -> None:
        seen: list[str] = []

        def fake(repo_root, base: str) -> stacks.MergeRules:
            seen.append(base)
            return stacks.MergeRules(squash_allowed=False, merge_queue_required=True)

        monkeypatch.setattr(stacks, "base_merge_rules", fake)
        rules = observe.GatewayLandObservations(tmp_path, base="develop").base_merge_rules()
        assert rules == land.MergeRulesView(squash_allowed=False, merge_queue_required=True)
        assert seen == ["develop"]

    def test_base_merge_rules_failure_wraps_to_land_observation_error(
        self, tmp_path, monkeypatch
    ) -> None:
        def boom(*_args: object, **_kw: object) -> None:
            raise GitHubError("HTTP 502")

        monkeypatch.setattr(stacks, "base_merge_rules", boom)
        with pytest.raises(land.LandObservationError, match="HTTP 502"):
            observe.GatewayLandObservations(tmp_path, base="main").base_merge_rules()

    def test_stack_capability_bool_passthrough(self, tmp_path, monkeypatch) -> None:
        # The declared boolean arm (§8.55): the gateway's fail-closed bool passes through
        # unwrapped — no LandObservationError translation exists for this read.
        monkeypatch.setattr(stacks, "stack_capability", lambda _root: False)
        assert observe.GatewayLandObservations(tmp_path, base="main").stack_capability() is False
        monkeypatch.setattr(stacks, "stack_capability", lambda _root: True)
        assert observe.GatewayLandObservations(tmp_path, base="main").stack_capability() is True
