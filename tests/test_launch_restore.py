"""Real-git restoration semantics of the shared worktree positioner (contracts.md §8.38).

A missing `worktree: reuse` checkout (submit/address/land — never learn) is restored
non-destructively from the existing `origin/plan-<id>` branch: strict fetch, create the local
branch from the remote tip when absent, attach when equal, fast-forward only when provably
behind and not checked out anywhere — every other shape refuses `worktree_restore_failed`
WITHOUT touching local branch refs. Stacked restores additionally rebuild `layer-context.json`
from the canonical checkpoint pair.
"""

import dataclasses
import json
import subprocess
from pathlib import Path

import pytest
from _launch_helpers import _PLAN_REF, _request

from perk import plan
from perk.backends import issue_backend
from perk.cli.ensure import UserFacingCliError
from perk.run.launch.worktree import resolve_worktree
from perk.state import cache
from perk.substrate import git as git_mod
from perk.substrate.config import Config


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def _sha(cwd: Path, ref: str = "HEAD") -> str:
    return _git(cwd, "rev-parse", ref)


def _push_plan_branch(clone: Path, branch: str = "plan-42") -> str:
    """Create ``origin/<branch>`` at a distinct commit and drop the local branch; return its
    tip sha (what a restore must reproduce)."""
    _git(clone, "checkout", "-q", "-b", branch, "main")
    (clone / f"{branch}.txt").write_text("branch\n", encoding="utf-8")
    _git(clone, "add", ".")
    _git(clone, "commit", "-qm", f"on {branch}")
    sha = _sha(clone)
    _git(clone, "push", "-q", "origin", branch)
    _git(clone, "checkout", "-q", "main")
    _git(clone, "branch", "-qD", branch)
    return sha


def _restore(clone: Path, *, ref=_PLAN_REF, consumer: str = "address", **kwargs):
    return resolve_worktree(
        repo_root=clone,
        config=Config(worktree_root=clone / ".worktrees"),
        request=_request(consumer),
        worktree=None,
        materialize=True,
        selected_ref=ref,
        **kwargs,
    )


def test_restore_creates_local_branch_from_remote_tip(git_repo_with_remote):
    clone, _remote, _advance = git_repo_with_remote
    remote_sha = _push_plan_branch(clone)
    resolved = _restore(clone)
    assert resolved.disposition == "restore-remote"
    assert resolved.branch == "plan-42" and resolved.base == "origin/plan-42"
    assert _sha(resolved.path) == remote_sha
    assert _git(resolved.path, "rev-parse", "--abbrev-ref", "HEAD") == "plan-42"
    # Positioner-owned materialization: binding + the setup-pending marker.
    assert cache.read_plan_ref(resolved.path) == _PLAN_REF
    assert cache.has_marker(resolved.path, cache.SETUP_PENDING)


def test_restore_attaches_equal_local_branch(git_repo_with_remote):
    clone, _remote, _advance = git_repo_with_remote
    remote_sha = _push_plan_branch(clone)
    _git(clone, "branch", "plan-42", remote_sha)  # local branch already AT the remote tip
    resolved = _restore(clone)
    assert resolved.disposition == "restore-remote"
    assert _sha(resolved.path) == remote_sha
    assert _sha(clone, "refs/heads/plan-42") == remote_sha  # untouched


def test_restore_fast_forwards_only_a_provably_behind_branch(git_repo_with_remote):
    clone, _remote, _advance = git_repo_with_remote
    remote_sha = _push_plan_branch(clone)
    _git(clone, "branch", "plan-42", "main")  # strictly behind the remote tip
    resolved = _restore(clone)
    assert resolved.disposition == "restore-remote"
    assert _sha(clone, "refs/heads/plan-42") == remote_sha  # safe fast-forward
    assert _sha(resolved.path) == remote_sha


def test_restore_refuses_ahead_local_branch_without_touching_it(git_repo_with_remote):
    clone, _remote, _advance = git_repo_with_remote
    remote_sha = _push_plan_branch(clone)
    _git(clone, "checkout", "-q", "-b", "plan-42", remote_sha)
    (clone / "ahead.txt").write_text("ahead\n", encoding="utf-8")
    _git(clone, "add", ".")
    _git(clone, "commit", "-qm", "local-only work")
    ahead_sha = _sha(clone)
    _git(clone, "checkout", "-q", "main")
    with pytest.raises(UserFacingCliError) as exc:
        _restore(clone)
    assert exc.value.error_type == "worktree_restore_failed"
    assert "ahead of" in str(exc.value)
    assert _sha(clone, "refs/heads/plan-42") == ahead_sha  # local refs unchanged
    assert not (clone / ".worktrees" / "plan-42").exists()


def test_restore_refuses_divergent_local_branch_without_touching_it(git_repo_with_remote):
    clone, _remote, _advance = git_repo_with_remote
    _push_plan_branch(clone)
    _git(clone, "checkout", "-q", "-b", "plan-42", "main")
    (clone / "diverge.txt").write_text("diverge\n", encoding="utf-8")
    _git(clone, "add", ".")
    _git(clone, "commit", "-qm", "divergent work")
    diverged_sha = _sha(clone)
    _git(clone, "checkout", "-q", "main")
    with pytest.raises(UserFacingCliError) as exc:
        _restore(clone)
    assert exc.value.error_type == "worktree_restore_failed"
    assert "divergent from" in str(exc.value)
    assert _sha(clone, "refs/heads/plan-42") == diverged_sha  # local refs unchanged
    assert not (clone / ".worktrees" / "plan-42").exists()


def test_restore_refuses_branch_checked_out_elsewhere(git_repo_with_remote):
    clone, _remote, _advance = git_repo_with_remote
    remote_sha = _push_plan_branch(clone)
    elsewhere = clone / ".worktrees" / "elsewhere"
    _git(clone, "worktree", "add", "-q", "-b", "plan-42", str(elsewhere), remote_sha)
    with pytest.raises(UserFacingCliError) as exc:
        _restore(clone)
    assert exc.value.error_type == "worktree_restore_failed"
    assert "already checked out" in str(exc.value)
    assert _sha(clone, "refs/heads/plan-42") == remote_sha  # untouched
    assert not (clone / ".worktrees" / "plan-42").exists()


def test_restore_refuses_unfetchable_remote_branch(git_repo_with_remote):
    clone, _remote, _advance = git_repo_with_remote  # origin exists, but has no plan-42 branch
    with pytest.raises(UserFacingCliError) as exc:
        _restore(clone)
    assert exc.value.error_type == "worktree_restore_failed"
    assert "could not be fetched" in str(exc.value)
    # Nothing was synthesized: no local branch, no directory.
    assert _git(clone, "branch", "--list", "plan-42") == ""
    assert not (clone / ".worktrees" / "plan-42").exists()


def test_restore_refuses_stale_registration_with_prune_remediation(git_repo_with_remote):
    clone, _remote, _advance = git_repo_with_remote
    _push_plan_branch(clone)
    first = _restore(clone)  # a real restore registers the worktree...
    subprocess.run(["rm", "-rf", str(first.path)], check=True)  # ...then the dir vanishes
    with pytest.raises(UserFacingCliError) as exc:
        _restore(clone)
    assert exc.value.error_type == "worktree_stale_registration"
    assert "git worktree prune" in str(exc.value)


def test_valid_reuse_performs_no_mutating_or_network_git_ops(git_repo_with_remote, monkeypatch):
    clone, _remote, _advance = git_repo_with_remote
    _push_plan_branch(clone)
    _restore(clone)  # materialize once (registered + bound)

    def _boom(name):
        def inner(*_a, **_k):
            raise AssertionError(f"reuse of a valid checkout must not call git.{name}")

        return inner

    for fn in ("fetch", "fetch_refspecs", "worktree_add", "update_ref"):
        monkeypatch.setattr(f"perk.run.launch.worktree.git.{fn}", _boom(fn))
    resolved = _restore(clone)
    assert resolved.disposition == "reuse-local"
    assert resolved.base is None  # per-disposition base contract


_STACKED_REF = dataclasses.replace(
    _PLAN_REF, objective_id="500", delivery_lineage="01LINEAGE", base="main"
)


def _stacked_state(header: dict[str, object]) -> issue_backend.PlanState:
    return issue_backend.PlanState(
        id="42", url=_PLAN_REF.url, title="T", header=header, pr=None, state="OPEN"
    )


def test_stacked_restore_rebuilds_layer_context_from_checkpoint_pair(git_repo_with_remote):
    clone, _remote, _advance = git_repo_with_remote
    remote_sha = _push_plan_branch(clone)
    parent_sha = _sha(clone, "main")
    state = _stacked_state(
        {
            "delivery_lineage": "01LINEAGE",
            "objective_id": "500",
            "objective_node_id": "1.2",
            "predecessor_plan_id": "41",
            "parent_checkpoint_sha": parent_sha,
            "published_head_sha": remote_sha,
        }
    )
    resolved = _restore(clone, ref=_STACKED_REF, plan_state=state)
    assert resolved.disposition == "restore-remote"
    record = json.loads(cache.layer_context_path(resolved.path).read_text(encoding="utf-8"))
    assert record["parent_sha"] == parent_sha  # the verified checkpoint, byte-exact
    assert record["parent_branch"] == "plan-41"  # from predecessor_plan_id
    assert record["branch"] == "plan-42"
    assert record["node_id"] == "1.2"


def test_stacked_restore_bottom_layer_parent_branch_is_the_base(git_repo_with_remote):
    clone, _remote, _advance = git_repo_with_remote
    remote_sha = _push_plan_branch(clone)
    parent_sha = _sha(clone, "main")
    state = _stacked_state(
        {
            "delivery_lineage": "01LINEAGE",
            "objective_id": "500",
            "objective_node_id": "1.1",
            "parent_checkpoint_sha": parent_sha,
            "published_head_sha": remote_sha,
        }
    )
    resolved = _restore(clone, ref=_STACKED_REF, plan_state=state)
    record = json.loads(cache.layer_context_path(resolved.path).read_text(encoding="utf-8"))
    assert record["parent_branch"] == "main"  # no predecessor: the bottom layer's base


def test_stacked_restore_without_checkpoint_pair_refuses(git_repo_with_remote):
    # A stacked plan with a remote branch but no checkpoint pair is anomalous: refuse before
    # fetching or creating anything.
    clone, _remote, _advance = git_repo_with_remote
    _push_plan_branch(clone)
    state = _stacked_state({"delivery_lineage": "01LINEAGE", "objective_id": "500"})
    with pytest.raises(UserFacingCliError) as exc:
        _restore(clone, ref=_STACKED_REF, plan_state=state)
    assert exc.value.error_type == "worktree_restore_failed"
    assert "no checkpoint pair" in str(exc.value)
    assert not (clone / ".worktrees" / "plan-42").exists()
    assert _git(clone, "branch", "--list", "plan-42") == ""


def test_learn_missing_checkout_refuses_and_never_fetches(git_repo_with_remote, monkeypatch):
    # learn is documented local-checkout-only: post-squash-merge the remote branch is commonly
    # gone, and its real input (session evidence) is machine-local. No fetch is even attempted.
    clone, _remote, _advance = git_repo_with_remote
    _push_plan_branch(clone)  # even WITH a restorable remote branch, learn refuses
    monkeypatch.setattr(
        "perk.run.launch.worktree.git.fetch_refspecs",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("learn must never fetch")),
    )
    with pytest.raises(UserFacingCliError) as exc:
        _restore(clone, consumer="learn")
    assert exc.value.error_type == "worktree_not_found"
    assert "machine" in str(exc.value)
    assert not (clone / ".worktrees" / "plan-42").exists()


# --- marker-gated setup: end-to-end fail-then-retry (fresh + restored dispositions) -----------


def _stub_launch_phases(monkeypatch, execs: list[str]) -> None:
    """Exec + heavy phases stubbed; positioning and the REAL marker-gated setup stay live."""
    from perk.run import launch

    monkeypatch.setattr(launch, "_exec_pi", lambda _ctx: execs.append("pi"))
    monkeypatch.setattr(launch, "_warm_extension_install", lambda _ctx: None)
    monkeypatch.setattr(launch, "_materialize_into_worktree", lambda _ctx: None)


def _launch(clone: Path, stage_id: str, setup: list[str]) -> None:
    from _launch_helpers import _stage

    from perk.run import launch

    launch.launch_stage(
        repo_root=clone,
        config=Config(worktree_root=clone / ".worktrees", worktree_setup=setup),
        stage=_stage(stage_id),
        worktree=None,
        dry_run=False,
        remote=None,
        pi_args=[],
    )


def test_fresh_create_setup_fails_then_retries_end_to_end(git_repo_with_remote, monkeypatch):
    # Through the REAL resolver + launcher + bash hook: a fresh create whose setup fails aborts
    # before exec and leaves the marker; the SAME launch re-run reuses the checkout, RETRIES the
    # hook, clears the marker on success, and reaches exec.
    clone, _remote, _advance = git_repo_with_remote
    cache.write_plan_ref(clone, _PLAN_REF)
    execs: list[str] = []
    _stub_launch_phases(monkeypatch, execs)
    with pytest.raises(UserFacingCliError) as exc:
        _launch(clone, "implement", ["false"])  # a really-failing setup command
    assert exc.value.error_type == "worktree_setup_failed"
    wt = clone / ".worktrees" / "plan-42"
    assert wt.exists() and execs == []  # created, but the launch aborted before exec
    assert cache.has_marker(wt, cache.SETUP_PENDING)  # the retry signal
    _launch(clone, "implement", ["true"])  # fixed: the reuse re-run retries the hook
    assert execs == ["pi"]
    assert not cache.has_marker(wt, cache.SETUP_PENDING)  # cleared only on success


def test_restored_setup_fails_then_retries_end_to_end(git_repo_with_remote, monkeypatch):
    # The same fail-then-retry contract on the RESTORED disposition: restore succeeds, setup
    # fails (marker stays), and the re-run retries the hook on the now-local checkout.
    clone, _remote, _advance = git_repo_with_remote
    _push_plan_branch(clone)
    cache.write_plan_ref(clone, _PLAN_REF)
    execs: list[str] = []
    _stub_launch_phases(monkeypatch, execs)
    with pytest.raises(UserFacingCliError) as exc:
        _launch(clone, "address", ["false"])
    assert exc.value.error_type == "worktree_setup_failed"
    wt = clone / ".worktrees" / "plan-42"
    assert wt.exists() and execs == []  # restored, but the launch aborted before exec
    assert cache.has_marker(wt, cache.SETUP_PENDING)
    _launch(clone, "address", ["true"])
    assert execs == ["pi"]
    assert not cache.has_marker(wt, cache.SETUP_PENDING)


# --- existing-checkout validation: the live-worktree probe arms --------------------------------


def test_existing_unregistered_directory_refuses(git_repo_with_remote):
    clone, _remote, _advance = git_repo_with_remote
    (clone / ".worktrees" / "plan-42").mkdir(parents=True)  # a bare directory, never registered
    with pytest.raises(UserFacingCliError) as exc:
        _restore(clone)
    assert exc.value.error_type == "worktree_unregistered"


def test_equivalent_resolved_path_is_accepted(git_repo_with_remote):
    # The macOS /var → /private/var shape: a worktree root that is textually different but
    # RESOLVES to the registered location still validates (both sides Path.resolve()d).
    clone, _remote, _advance = git_repo_with_remote
    _push_plan_branch(clone)
    _restore(clone)  # materialize under the real .worktrees root
    alias_root = clone / "wt-alias"
    alias_root.symlink_to(clone / ".worktrees")
    resolved = resolve_worktree(
        repo_root=clone,
        config=Config(worktree_root=alias_root),
        request=_request("address"),
        worktree=None,
        materialize=True,
        selected_ref=_PLAN_REF,
    )
    assert resolved.disposition == "reuse-local"
    assert resolved.path == alias_root / "plan-42"  # the caller's spelling, same checkout


def test_prunable_registered_entry_refuses_with_repair_remediation(git_repo_with_remote):
    # `git worktree list` retains a prunable admin entry when the checkout's .git gitfile is
    # gone; git commands there would silently resolve to the MAIN checkout. The live toplevel
    # probe refuses it.
    clone, _remote, _advance = git_repo_with_remote
    _push_plan_branch(clone)
    first = _restore(clone)
    (first.path / ".git").unlink()  # break the checkout metadata; the entry stays registered
    with pytest.raises(UserFacingCliError) as exc:
        _restore(clone)
    assert exc.value.error_type == "worktree_unregistered"
    assert "git worktree repair" in str(exc.value)


# --- bare-id selection: backend canonicalization ------------------------------------------------


def _stub_canonical_get_plan(monkeypatch, header: dict[str, object] | None = None) -> None:
    """The one lazy canonical read: raw selector `007` canonicalizes to plan id `7`."""
    from perk.backends.github import plans

    monkeypatch.setattr(
        plans,
        "get_plan",
        lambda **k: plans.PlanState(
            number=7, url="https://gh/o/r/issues/7", title="T", header=header or {}, pr=None
        ),
    )


def _resolve_bare_id(clone: Path, plan_id: str):
    return resolve_worktree(
        repo_root=clone,
        config=Config(worktree_root=clone / ".worktrees"),
        request=_request("address"),
        worktree=None,
        materialize=True,
        plan_id=plan_id,
    )


def test_bare_id_canonicalization_reuses_the_canonical_checkout(git_repo_with_remote, monkeypatch):
    # Raw selector "007" canonicalizes to plan #7: an existing plan-7 checkout is validated
    # reuse — never a parallel plan-007 restore.
    clone, _remote, _advance = git_repo_with_remote
    _stub_canonical_get_plan(monkeypatch)
    ref7 = plan.PlanRef(
        provider="github", pr_id="7", url="https://gh/o/r/issues/7", labels=("perk:plan",)
    )
    wt7 = clone / ".worktrees" / "plan-7"
    git_mod.worktree_add(clone, wt7, branch="plan-7", create_branch=True)
    cache.write_plan_ref(wt7, ref7)
    resolved = _resolve_bare_id(clone, "007")
    assert resolved.disposition == "reuse-local"
    assert resolved.path == wt7 and resolved.branch == "plan-7"
    assert resolved.plan_ref == ref7


def test_bare_id_canonicalization_restores_the_canonical_branch(git_repo_with_remote, monkeypatch):
    # With no local checkout, the restore positions from the CANONICAL id: branch/directory
    # plan-7, never a plan-007 directory bound to plan #7.
    clone, _remote, _advance = git_repo_with_remote
    _stub_canonical_get_plan(monkeypatch)
    _push_plan_branch(clone, "plan-7")
    resolved = _resolve_bare_id(clone, "007")
    assert resolved.disposition == "restore-remote"
    assert resolved.branch == "plan-7" and resolved.path.name == "plan-7"
    ref = cache.read_plan_ref(resolved.path)
    assert ref is not None and ref.pr_id == "7"
    assert not (clone / ".worktrees" / "plan-007").exists()


# --- stacked restore: checkpoint validation against the fetched tip ----------------------------


def test_stacked_restore_refuses_drifted_published_head(git_repo_with_remote):
    # The recorded published head must BE the remote tip: a manually-moved branch refuses
    # before any materialization.
    clone, _remote, _advance = git_repo_with_remote
    remote_sha = _push_plan_branch(clone)
    parent_sha = _sha(clone, "main")
    state = _stacked_state(
        {
            "delivery_lineage": "01LINEAGE",
            "objective_id": "500",
            "parent_checkpoint_sha": parent_sha,
            "published_head_sha": "e" * 40,  # a stale/foreign publication record
        }
    )
    with pytest.raises(UserFacingCliError) as exc:
        _restore(clone, ref=_STACKED_REF, plan_state=state)
    assert exc.value.error_type == "worktree_restore_failed"
    assert "drifted from its recorded publication" in str(exc.value)
    assert not (clone / ".worktrees" / "plan-42").exists()
    assert _sha(clone, "refs/remotes/origin/plan-42") == remote_sha  # fetch only; no local refs


def test_stacked_restore_refuses_non_ancestor_parent_checkpoint(git_repo_with_remote):
    # A parent checkpoint that is not an ancestor of the fetched tip (a force-pushed or
    # malformed branch) refuses instead of restoring a wrong layer-context parent_sha.
    clone, _remote, _advance = git_repo_with_remote
    remote_sha = _push_plan_branch(clone)
    state = _stacked_state(
        {
            "delivery_lineage": "01LINEAGE",
            "objective_id": "500",
            "parent_checkpoint_sha": "f" * 40,  # unrelated to the branch's history
            "published_head_sha": remote_sha,
        }
    )
    with pytest.raises(UserFacingCliError) as exc:
        _restore(clone, ref=_STACKED_REF, plan_state=state)
    assert exc.value.error_type == "worktree_restore_failed"
    assert "not an ancestor" in str(exc.value)
    assert not (clone / ".worktrees" / "plan-42").exists()
