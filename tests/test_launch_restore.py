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

from perk.backends import issue_backend
from perk.cli.ensure import UserFacingCliError
from perk.run.launch.worktree import resolve_worktree
from perk.state import cache
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
