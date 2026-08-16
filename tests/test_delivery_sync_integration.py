"""Candidate-calculation integration for the sync operation (real repos + a bare remote).

The one non-hermetic sync lane: ``Delivery.sync`` runs with ``RepoDeliveryGit``
(fetch/rebase/atomic push/temp refs/isolated worktree) against a real three-layer train on a
bare ``origin`` — only the status projection, GitHub reads, and persistence are faked. Pins
the exact transplanted heads (parentage, tree content), that
user branches/worktrees never move, and that the isolated calculation residue is cleaned.
The protocol arms themselves are pinned hermetically in ``test_delivery_sync.py``.
"""

import os
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import ClassVar, cast

import pytest

from perk.delivery import (
    Delivery,
    DeliveryGitHub,
    DeliveryPersistence,
    StatusRequest,
    StatusResult,
    SyncRequest,
    continuation,
    observe,
    recover,
    sync,
)
from perk.delivery.journal import (
    EventRole,
    JournalFold,
    OutcomeRecord,
    PreparedRecord,
    mint_operation_id,
)
from perk.delivery.persistence import AppendResult
from perk.delivery.train import (
    BuildReadiness,
    DeliveryTrain,
    LayerFinalization,
    LayerGit,
    LayerIntent,
    LayerMembership,
    LayerPr,
    LayerPublication,
    LayerWriter,
    PrFactsView,
    TrainLayer,
)
from perk.github.stacks import StackRestEntry, StackRestFacts
from perk.substrate import git as git_mod


def _git(cwd, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, timeout=60
    ).stdout


def _sha(repo, ref: str = "HEAD") -> str:
    return _git(repo, "rev-parse", ref).strip()


def _commit_file(repo, name: str, content: str, message: str) -> str:
    (repo / name).write_text(content, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", message)
    return _sha(repo)


class _Recorder:
    def __init__(self) -> None:
        self.prepared: list[PreparedRecord] = []
        self.outcomes: list[OutcomeRecord] = []
        self.checkpoints: list[tuple[str, str, str]] = []

    def read_journal(self, objective_id: str) -> JournalFold:
        return JournalFold(events=(), operations={}, unresolved=(), delivery_lineage="01L")

    def append_prepared(self, objective_id: str, record: PreparedRecord) -> AppendResult:
        self.prepared.append(record)
        return AppendResult(record.operation_id, EventRole.PREPARED, existed=False)

    def append_outcome(self, objective_id: str, record: OutcomeRecord) -> AppendResult:
        self.outcomes.append(record)
        return AppendResult(record.operation_id, record.role, existed=False)

    def write_checkpoints(
        self, plan_id: str, *, parent_checkpoint_sha: str, published_head_sha: str
    ) -> None:
        self.checkpoints.append((plan_id, parent_checkpoint_sha, published_head_sha))


class _GitHub:
    """Strict GitHub facts backed by the real test remote's branch heads."""

    _BRANCHES: ClassVar[dict[int, tuple[str, str]]] = {
        201: ("plan-101", "main"),
        202: ("plan-102", "plan-101"),
        203: ("plan-103", "plan-102"),
    }

    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root

    def pr_facts(self, number: int) -> PrFactsView | None:
        branch, base = self._BRANCHES[number]
        head = git_mod.remote_branch_head(self._repo_root, branch)
        assert head is not None
        return PrFactsView(number, "OPEN", True, base, branch, head)

    def strict_stack(self, number: int) -> StackRestFacts | None:
        if number not in self._BRANCHES:
            return None
        entries = tuple(
            StackRestEntry(
                pr_number=pr_number,
                state="open",
                draft=True,
                merged=False,
                head_ref=branch,
                head_sha="h" * 40,
            )
            for pr_number, (branch, _base) in self._BRANCHES.items()
        )
        return StackRestFacts(number=1, size=len(entries), entries=entries)

    def active_writer_plan_ids(
        self,
        plan_ids: tuple[str, ...],
        *,
        trigger_plan_id: str | None,
        trigger_run_id: str | None,
    ) -> frozenset[str]:
        return frozenset()


class _IntegrationDelivery(Delivery):
    def __init__(self, repo_root: Path, recorder: _Recorder, train: DeliveryTrain) -> None:
        self._train = train
        super().__init__(
            persistence=cast("DeliveryPersistence", recorder),
            git=observe.RepoDeliveryGit(repo_root),
            github=cast("DeliveryGitHub", _GitHub(repo_root)),
        )

    def status(self, request: StatusRequest) -> StatusResult:
        return StatusResult(
            self._train.objective_id,
            self._train.objective_url,
            self._train.redirected_from,
            self._train,
            None,
        )


def _runtime(worktree_root: Path) -> sync._SyncRuntime:
    return replace(
        sync._DEFAULT_SYNC_RUNTIME,
        worktree_root=lambda repo_root: worktree_root,
        sleep=lambda seconds: None,
    )


def _layer(node_id: str, plan_id: str, pr: int, parent: str, head: str) -> TrainLayer:
    return TrainLayer(
        node_id=node_id,
        plan_id=plan_id,
        branch=f"plan-{plan_id}",
        pr_number=pr,
        intent=LayerIntent.PLANNED,
        publication=LayerPublication.PUBLISHED,
        git=LayerGit.SYNCED,
        pr=LayerPr.DRAFT,
        membership=LayerMembership.EXACT,
        writer=LayerWriter.FREE,
        finalization=LayerFinalization.NOT_MERGED,
        parent_checkpoint_sha=parent,
        published_head_sha=head,
        observed_remote_head_sha=head,
        observed_pr_base=None,
        expected_pr_base=None,
    )


def test_amended_bottom_layer_cascades_with_exact_transplants(tmp_path):
    # --- a real three-layer train pushed to a bare origin -------------------------------
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    _git(work, "config", "user.email", "t@example.com")
    _git(work, "config", "user.name", "perk tests")
    main_sha = _commit_file(work, "base.txt", "base\n", "base")
    _git(work, "checkout", "-q", "-b", "plan-101")
    a1 = _commit_file(work, "layer1.txt", "one\n", "layer 1")
    _git(work, "checkout", "-q", "-b", "plan-102")
    b1 = _commit_file(work, "layer2.txt", "two\n", "layer 2")
    _git(work, "checkout", "-q", "-b", "plan-103")
    c1 = _commit_file(work, "layer3.txt", "three\n", "layer 3")
    bare = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", str(bare))
    _git(work, "remote", "add", "origin", str(bare))
    _git(work, "push", "-q", "origin", "main", "plan-101", "plan-102", "plan-103")

    # Amend the BOTTOM layer locally (a content rewrite — the cascade trigger).
    _git(work, "checkout", "-q", "plan-101")
    (work / "layer1.txt").write_text("one, amended\n", encoding="utf-8")
    _git(work, "add", ".")
    _git(work, "commit", "-q", "--amend", "-m", "layer 1 (amended)")
    a2 = _sha(work)
    _git(work, "checkout", "-q", "plan-103")  # the user sits elsewhere; sync must not care
    user_head = _sha(work)

    train = DeliveryTrain(
        objective_id="500",
        objective_url="u",
        delivery_lineage="01L",
        base="main",
        redirected_from=None,
        layers=(
            _layer("1.1", "101", 201, main_sha, a1),
            _layer("1.2", "102", 202, a1, b1),
            _layer("1.3", "103", 203, b1, c1),
        ),
        published_prefix_len=0,  # deliberately untrusted by sync
        unresolved_operation=None,
        findings=(),
        build_readiness=BuildReadiness(next_node_id=None, ready=False, reason="x"),
        observed_base_head_sha=main_sha,
    )

    recorder = _Recorder()
    delivery = _IntegrationDelivery(work, recorder, train)
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(sync, "_DEFAULT_SYNC_RUNTIME", _runtime(work / ".worktrees"))
        result = delivery.sync(
            SyncRequest(mode="cascade", objective_id="500", run_id="01RUN"), consent=None
        )

    # The whole claimed prefix cascaded from the amended bottom layer.
    assert [s.plan_id for s in result.affected] == ["101", "102", "103"]
    assert result.affected[0].after_sha == a2  # fast path: unchanged parent edge, no rebase
    r2 = result.affected[1].after_sha
    r3 = result.affected[2].after_sha
    assert r2 not in (b1, a2) and r3 not in (c1, r2)  # genuinely new transplants

    # The remote moved atomically to the exact candidates…
    assert _sha(bare, "plan-101") == a2
    assert _sha(bare, "plan-102") == r2
    assert _sha(bare, "plan-103") == r3
    # …with exact parentage (each candidate sits on its predecessor's candidate)…
    assert _sha(work, f"{r2}^") == a2
    assert _sha(work, f"{r3}^") == r2
    # …and the transplants carry BOTH sides' content.
    assert _git(work, "show", f"{r3}:layer1.txt") == "one, amended\n"
    assert _git(work, "show", f"{r3}:layer3.txt") == "three\n"

    # User branches/worktree never move: the local successors are deliberately stale.
    assert _sha(work, "plan-102") == b1
    assert _sha(work, "plan-103") == c1
    assert _sha(work) == user_head

    # Checkpoints bottom→top with the new parent edges, then completed.
    assert recorder.checkpoints == [("101", main_sha, a2), ("102", a2, r2), ("103", r2, r3)]
    assert [o.role for o in recorder.outcomes] == [EventRole.COMPLETED]

    # The isolated calculation residue is cleaned: no temp refs, no sync worktree.
    assert _git(work, "for-each-ref", "--format=%(refname)", "refs/perk/") == ""
    assert not list((work / ".worktrees").glob("sync-*"))


def test_conflicted_cascade_resolves_through_the_real_continue_arc(tmp_path):
    """The full §8.49 continue arc with production git seams: a real conflicted rebase stop
    (residue retained under the manifest), a human-style resolution (`git rebase
    --continue` in the retained worktree), then ``Delivery.sync(mode="continue")``
    completing against the bare remote under the manifest's operation identity."""
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    _git(work, "config", "user.email", "t@example.com")
    _git(work, "config", "user.name", "perk tests")
    main_sha = _commit_file(work, "base.txt", "base\n", "base")
    _git(work, "checkout", "-q", "-b", "plan-101")
    a1 = _commit_file(work, "shared.txt", "one\n", "layer 1")
    _git(work, "checkout", "-q", "-b", "plan-102")
    b1 = _commit_file(work, "shared.txt", "one plus two\n", "layer 2")  # same line as layer 1
    _git(work, "checkout", "-q", "-b", "plan-103")
    c1 = _commit_file(work, "layer3.txt", "three\n", "layer 3")
    bare = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", str(bare))
    _git(work, "remote", "add", "origin", str(bare))
    _git(work, "push", "-q", "origin", "main", "plan-101", "plan-102", "plan-103")

    # Amend the bottom layer's SAME line — the successor's transplant must conflict.
    _git(work, "checkout", "-q", "plan-101")
    (work / "shared.txt").write_text("ONE\n", encoding="utf-8")
    _git(work, "add", ".")
    _git(work, "commit", "-q", "--amend", "-m", "layer 1 (amended)")
    a2 = _sha(work)
    _git(work, "checkout", "-q", "plan-103")

    train = DeliveryTrain(
        objective_id="500",
        objective_url="u",
        delivery_lineage="01L",
        base="main",
        redirected_from=None,
        layers=(
            _layer("1.1", "101", 201, main_sha, a1),
            _layer("1.2", "102", 202, a1, b1),
            _layer("1.3", "103", 203, b1, c1),
        ),
        published_prefix_len=0,
        unresolved_operation=None,
        findings=(),
        build_readiness=BuildReadiness(next_node_id=None, ready=False, reason="x"),
        observed_base_head_sha=main_sha,
    )

    recorder = _Recorder()
    delivery = _IntegrationDelivery(work, recorder, train)
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(sync, "_DEFAULT_SYNC_RUNTIME", _runtime(work / ".worktrees"))
        with pytest.raises(sync.SyncError) as excinfo:
            delivery.sync(
                SyncRequest(mode="cascade", objective_id="500", run_id="01RUN"), consent=None
            )
    assert excinfo.value.error_type == "rebase_conflict"
    assert recorder.prepared == []  # pre-journal: nothing appended at the stop

    # The residue was genuinely retained: manifest + conflicted worktree + temp ref.
    pending = continuation.pending_continuation(work, "01L")
    assert pending is not None and pending.manifest is not None
    manifest = pending.manifest
    assert manifest.conflict_node_id == "1.2" and manifest.run_id == "01RUN"
    retained = Path(manifest.worktree_path)
    assert retained.is_dir()
    assert git_mod.rebase_in_progress(retained) is True

    # The human resolves the conflict and finishes the rebase in the retained worktree.
    (retained / "shared.txt").write_text("ONE plus two\n", encoding="utf-8")
    _git(retained, "add", "shared.txt")
    subprocess.run(
        ["git", "rebase", "--continue"],
        cwd=retained,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "GIT_EDITOR": "true"},
    )
    assert git_mod.rebase_in_progress(retained) is False

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(sync, "_DEFAULT_SYNC_RUNTIME", _runtime(work / ".worktrees"))
        result = delivery.sync(SyncRequest(mode="continue", objective_id="500"), consent=None)
    assert result.continued is True and result.operation_id == manifest.operation_id
    record = recorder.prepared[0]
    assert record.operation_id == manifest.operation_id and record.run_id == "01RUN"

    # The remote moved atomically to the resolved candidates with exact parentage/content.
    x2 = result.affected[1].after_sha
    r3 = result.affected[2].after_sha
    assert _sha(bare, "plan-101") == a2
    assert _sha(bare, "plan-102") == x2 and _sha(work, f"{x2}^") == a2
    assert _sha(bare, "plan-103") == r3 and _sha(work, f"{r3}^") == x2
    assert _git(work, "show", f"{r3}:shared.txt") == "ONE plus two\n"
    assert _git(work, "show", f"{r3}:layer3.txt") == "three\n"
    assert recorder.checkpoints == [("101", main_sha, a2), ("102", a2, x2), ("103", x2, r3)]
    assert [o.role for o in recorder.outcomes] == [EventRole.COMPLETED]

    # The manifest retired; every trace of the retained residue is gone (prune included).
    assert continuation.pending_continuation(work, "01L") is None
    assert _git(work, "for-each-ref", "--format=%(refname)", "refs/perk/") == ""
    assert not list((work / ".worktrees").glob("sync-*"))
    assert "sync-" not in _git(work, "worktree", "list")


def test_orphan_sweep_removes_real_residue_and_prunes(git_repo):
    """The recover orphan sweep with production git seams: real orphaned `sync-<ulid>`
    worktrees and `refs/perk/sync/` refs are removed (manifest-protected residue survives),
    and the one trailing prune clears a stale worktree-admin entry whose directory is gone."""
    work = git_repo
    head = _sha(work)
    worktree_root = work / ".worktrees"

    orphan = mint_operation_id()
    protected = mint_operation_id()
    stale = mint_operation_id()
    for op in (orphan, protected, stale):
        _git(work, "worktree", "add", "--detach", str(worktree_root / f"sync-{op}"), head)
    subprocess.run(
        ["git", "update-ref", "--stdin"],
        cwd=work,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
        input="".join(
            f"update refs/perk/sync/{op}/plan-101 {head}\n" for op in (orphan, protected, stale)
        ),
    )
    _git(work, "worktree", "add", "--detach", str(worktree_root / "plan-101"), head)
    # The stale-admin case: the directory vanished but git's admin entry survives.
    shutil.rmtree(worktree_root / f"sync-{stale}")

    # A real (foreign-lineage) manifest protects its operation's residue.
    continuation.write_manifest(
        work,
        continuation.ContinuationManifest(
            operation_id=protected,
            objective_id="777",
            delivery_lineage="01OTHERLINEAGE",
            run_id="01RUN",
            include_base=False,
            captured_base_head=None,
            layers=(),
            conflict_node_id="9.9",
            worktree_path=str(worktree_root / f"sync-{protected}"),
            created="2026-01-01T00:00:00Z",
        ),
    )

    train = DeliveryTrain(
        objective_id="500",
        objective_url="u",
        delivery_lineage="01L",
        base="main",
        redirected_from=None,
        layers=(),
        published_prefix_len=0,
        unresolved_operation=None,
        findings=(),
        build_readiness=BuildReadiness(next_node_id=None, ready=False, reason="x"),
        observed_base_head_sha=head,
    )
    recorder = _Recorder()
    result = recover.recover_operations(
        work,
        objective_id="500",
        worktree_root=worktree_root,
        reconstruct=lambda root, oid: train,
        persistence_factory=lambda root: recorder,
        sleep=lambda seconds: None,
    )
    assert result.operations == () and result.sweep_failures == ()
    # The on-disk orphan is removed directly; the stale admin entry (directory gone) is
    # classified too and collected by the trailing prune — BOTH ride swept_worktrees.
    assert tuple(result.swept_worktrees) == (
        str(worktree_root / f"sync-{orphan}"),
        str(worktree_root / f"sync-{stale}"),
    )
    assert set(result.swept_refs) == {
        f"refs/perk/sync/{orphan}/plan-101",
        f"refs/perk/sync/{stale}/plan-101",
    }

    listed = _git(work, "worktree", "list")
    assert f"sync-{orphan}" not in listed
    assert f"sync-{stale}" not in listed  # pruned
    assert f"sync-{protected}" in listed  # manifest-protected
    assert "plan-101" in listed  # not sync residue
    assert not (worktree_root / f"sync-{orphan}").exists()
    refs = _git(work, "for-each-ref", "--format=%(refname)", "refs/perk/")
    assert refs.split() == [f"refs/perk/sync/{protected}/plan-101"]
