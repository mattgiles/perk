"""The idempotent post-merge land finalization seam (`perk.delivery.finalize`).

The four durable bookkeeping effects extracted from `perk pr land`: the learn-state stamp, the
explicit plan-issue close, the objective reconciliation, and the learn-issue consume — driven by
reconstructed inputs (`LandedPlan`), never the worktree cache. The CLI-level land behavior stays
pinned in `tests/test_pr_land.py`; the import-level cache-independence proof is the
fresh-interpreter guard in `tests/test_delivery_continuation.py` (no `perk.state` module loads
with `perk.delivery`).
"""

from pathlib import Path

import pytest

from perk import github, objective
from perk.backends import issue_backend, objective_store, resolve
from perk.backends.github import GitHubIssueBackend, objectives, plans
from perk.delivery import finalize
from perk.delivery.finalize import (
    LandedPlan,
    LandFinalization,
    LearnConsumeUpdate,
    ObjectiveLandUpdate,
    _close_plan_issue_on_land,
    _consume_learn_on_land,
    _reconcile_objective_on_land,
    finalize_landed_plan,
)
from perk.state import cache

# --- explicit plan-issue close on a non-default-base github land -----------------------


def test_close_plan_issue_non_default_base_failure_is_fail_open(monkeypatch, capsys):
    """A close failure on a non-default github base is fail-open: returns False, warns on stderr,
    never raises (so the land result is unchanged)."""
    monkeypatch.setattr(github, "default_branch", lambda repo_root: "main")

    def _boom(**k):
        raise github.GitHubError("gh exploded")

    monkeypatch.setattr(plans, "close_issue", _boom)
    backend = GitHubIssueBackend(repo_root=Path())
    out = _close_plan_issue_on_land(backend, issue="7", repo_root=Path(), pr_base="release")
    assert out is False
    assert "plan issue close skipped (non-fatal)" in capsys.readouterr().err


# --- mechanical auto-on-merge node-done --------------------------------------------


def _objective_state(nodes: list[objective.ObjectiveNode]) -> objectives.ObjectiveState:
    return objectives.ObjectiveState(
        number=5, url="u/5", title="Obj", header={}, nodes=tuple(nodes)
    )


def _node(node_id: str, *, pr: str | None, status=objective.NodeStatus.PENDING):
    return objective.ObjectiveNode(id=node_id, description=node_id, status=status, pr=pr)


def test_reconcile_on_land_no_objective_link():
    out = _reconcile_objective_on_land(
        landed=LandedPlan(plan_id="7", objective_id=None), repo_root=Path()
    )
    assert out == ObjectiveLandUpdate(None, (), "no_objective_link")


def test_reconcile_on_land_bad_objective_id():
    # Ids are opaque strings now — only an empty (post-`#`-strip) id is "bad".
    out = _reconcile_objective_on_land(
        landed=LandedPlan(plan_id="7", objective_id="#"), repo_root=Path()
    )
    assert out == ObjectiveLandUpdate(None, (), "bad_objective_id")


def test_reconcile_on_land_objective_not_found(monkeypatch):
    monkeypatch.setattr(objectives, "get_objective", lambda **k: None)
    out = _reconcile_objective_on_land(
        landed=LandedPlan(plan_id="7", objective_id="5"), repo_root=Path()
    )
    assert out == ObjectiveLandUpdate("5", (), "objective_not_found")


def test_reconcile_on_land_no_linked_node(monkeypatch):
    monkeypatch.setattr(
        objectives, "get_objective", lambda **k: _objective_state([_node("1.1", pr="#99")])
    )
    out = _reconcile_objective_on_land(
        landed=LandedPlan(plan_id="7", objective_id="5"), repo_root=Path()
    )
    assert out == ObjectiveLandUpdate("5", (), "no_linked_node")


def test_reconcile_on_land_marks_backlinked_node_done(monkeypatch):
    marked: list[str] = []
    monkeypatch.setattr(
        objectives,
        "get_objective",
        lambda **k: _objective_state([_node("1.1", pr="#7"), _node("1.2", pr="#99")]),
    )

    def _update(**k):
        assert k["status"] == objective.NodeStatus.DONE
        marked.append(k["node_id"])
        return objectives.ObjectiveNodeUpdate(
            number=k["number"], node_id=k["node_id"], comment_updated=True, dry_run=False
        )

    monkeypatch.setattr(objectives, "update_objective_node", _update)
    closed: list[int] = []
    monkeypatch.setattr(plans, "close_issue", lambda **k: closed.append(k["number"]) or True)
    out = _reconcile_objective_on_land(
        landed=LandedPlan(plan_id="7", objective_id="#5"), repo_root=Path()
    )
    # node 1.2 stays non-terminal → roadmap incomplete → no close.
    assert out == ObjectiveLandUpdate("5", ("1.1",), None)
    assert out.closed is False
    assert marked == ["1.1"]
    assert closed == []


def test_reconcile_on_land_skips_already_terminal_node(monkeypatch):
    # Re-land idempotency: the target is already done and the graph is complete — the close still
    # runs (idempotent convergence) even though zero nodes were marked.
    monkeypatch.setattr(
        objectives,
        "get_objective",
        lambda **k: _objective_state([_node("1.1", pr="#7", status=objective.NodeStatus.DONE)]),
    )
    closed: list[int] = []
    monkeypatch.setattr(plans, "close_issue", lambda **k: closed.append(k["number"]) or True)
    out = _reconcile_objective_on_land(
        landed=LandedPlan(plan_id="7", objective_id="5"), repo_root=Path()
    )
    assert out == ObjectiveLandUpdate("5", (), None, closed=True)
    assert closed == [5]


def test_reconcile_on_land_closes_objective_when_final_node_completes(monkeypatch):
    # Landing the final non-terminal node → every node terminal → the objective issue is closed.
    monkeypatch.setattr(
        objectives,
        "get_objective",
        lambda **k: _objective_state(
            [
                _node("1.1", pr="#99", status=objective.NodeStatus.DONE),
                _node("1.2", pr="#98", status=objective.NodeStatus.SKIPPED),
                _node("1.3", pr="#7"),
            ]
        ),
    )
    monkeypatch.setattr(
        objectives,
        "update_objective_node",
        lambda **k: objectives.ObjectiveNodeUpdate(
            number=k["number"], node_id=k["node_id"], comment_updated=True, dry_run=False
        ),
    )
    closed: list[int] = []
    monkeypatch.setattr(plans, "close_issue", lambda **k: closed.append(k["number"]) or True)
    out = _reconcile_objective_on_land(
        landed=LandedPlan(plan_id="7", objective_id="5"), repo_root=Path()
    )
    assert out == ObjectiveLandUpdate("5", ("1.3",), None, closed=True)
    assert closed == [5]


def test_reconcile_on_land_close_failure_is_isolated(monkeypatch, capsys):
    # A close failure must NOT discard the already-marked node ids (isolated fail-open) and must
    # never affect the land result.
    monkeypatch.setattr(
        objectives,
        "get_objective",
        lambda **k: _objective_state([_node("1.1", pr="#7")]),
    )
    monkeypatch.setattr(
        objectives,
        "update_objective_node",
        lambda **k: objectives.ObjectiveNodeUpdate(
            number=k["number"], node_id=k["node_id"], comment_updated=True, dry_run=False
        ),
    )

    def _boom(**k):
        raise github.GitHubError("gh exploded")

    monkeypatch.setattr(plans, "close_issue", _boom)
    out = _reconcile_objective_on_land(
        landed=LandedPlan(plan_id="7", objective_id="5"), repo_root=Path()
    )
    assert out.nodes_marked == ("1.1",)
    assert out.closed is False
    assert out.skipped_reason is not None and out.skipped_reason.startswith("close_failed:")
    assert "objective close skipped (non-fatal)" in capsys.readouterr().err


def test_reconcile_on_land_completes_via_store_close_objective(monkeypatch):
    # Completion closes through the OBJECTIVE STORE (store.close_objective), not the issue
    # tier (backend.close_issue). Inject a fake store and assert it owns the close.
    calls: dict[str, object] = {}
    marked: list[str] = []
    posts: list[dict] = []

    class _Store:
        backend_id = "linear"

        def get_objective(self, *, objective_id):
            return objective_store.ObjectiveState(
                id=objective_id,
                url="u",
                title="O",
                header={},
                nodes=(_node("1.1", pr="#ENG-7"),),
            )

        def update_objective_node(self, **k):
            marked.append(k["node_id"])
            return objective_store.ObjectiveNodeUpdate(
                objective_id=str(k["objective_id"]),
                node_id=k["node_id"],
                comment_updated=False,
                dry_run=False,
            )

        def close_objective(self, *, objective_id, dry_run=False):
            calls["closed"] = objective_id
            return True

        def post_status_update(self, *, objective_id, body, dry_run=False):
            posts.append({"objective_id": objective_id, "body": body})
            return True

    monkeypatch.setattr(resolve, "resolve_objective_store", lambda _root: _Store())
    # If the close reached the issue tier, this would fire — it must NOT.
    monkeypatch.setattr(
        plans, "close_issue", lambda **k: (_ for _ in ()).throw(AssertionError("issue-tier close"))
    )
    out = _reconcile_objective_on_land(
        landed=LandedPlan(plan_id="ENG-7", objective_id="proj-1"), repo_root=Path()
    )
    assert out == ObjectiveLandUpdate("proj-1", ("1.1",), None, closed=True)
    assert calls["closed"] == "proj-1"
    # A "plan landed" Project Update is posted once on completion (complete branch).
    assert len(posts) == 1
    assert posts[0]["objective_id"] == "proj-1"
    assert posts[0]["body"] == (
        "**Plan landed** — node(s) 1.1 (PR #ENG-7) marked done.\n\nObjective complete."
    )


def test_reconcile_on_land_posts_update_incomplete_and_fail_open(monkeypatch, capsys):
    # The incomplete branch posts a "plan landed" update (no "Objective complete."), and a post
    # failure is fail-open: the land result is byte-unchanged and a non-fatal line hits stderr.
    class _Store:
        backend_id = "linear"

        def get_objective(self, *, objective_id):
            return objective_store.ObjectiveState(
                id=objective_id,
                url="u",
                title="O",
                header={},
                nodes=(_node("1.1", pr="#ENG-7"), _node("1.2", pr="#ENG-9")),
            )

        def update_objective_node(self, **k):
            return objective_store.ObjectiveNodeUpdate(
                objective_id=str(k["objective_id"]),
                node_id=k["node_id"],
                comment_updated=False,
                dry_run=False,
            )

        def post_status_update(self, *, objective_id, body, dry_run=False):
            raise objective_store.ObjectiveStoreError("linear update boom")

    monkeypatch.setattr(resolve, "resolve_objective_store", lambda _root: _Store())
    out = _reconcile_objective_on_land(
        landed=LandedPlan(plan_id="ENG-7", objective_id="proj-1"), repo_root=Path()
    )
    # 1.2 stays non-terminal → incomplete → no close; the post failure never changes the result.
    assert out == ObjectiveLandUpdate("proj-1", ("1.1",), None)
    assert "project update skipped (non-fatal)" in capsys.readouterr().err


def test_reconcile_on_land_is_fail_open(monkeypatch):
    def _boom(**k):
        raise github.GitHubError("gh exploded")

    monkeypatch.setattr(objectives, "get_objective", _boom)
    out = _reconcile_objective_on_land(
        landed=LandedPlan(plan_id="7", objective_id="5"), repo_root=Path()
    )
    assert out.objective == "5" and out.nodes_marked == ()
    assert out.skipped_reason is not None and out.skipped_reason.startswith("error:")


def test_reconcile_on_land_propagates_programming_error(monkeypatch):
    # Fail-open covers expected store failures (ObjectiveStoreError) only — a bug in the
    # store must surface, not dissolve into a skipped_reason.
    def _boom(**k):
        raise RuntimeError("bug in the objective store")

    monkeypatch.setattr(objectives, "get_objective", _boom)
    with pytest.raises(RuntimeError):
        _reconcile_objective_on_land(
            landed=LandedPlan(plan_id="7", objective_id="5"), repo_root=Path()
        )


# --- learned-docs consume on land (hop-2) ----------------------------------------------------


def _github_backend() -> GitHubIssueBackend:
    return GitHubIssueBackend(repo_root=Path())


def test_consume_learn_on_land_no_consumed():
    out = _consume_learn_on_land(_github_backend(), landed=LandedPlan(plan_id="7"))
    assert out.closed == () and out.skipped_reason == "no_consumed_learn"


def test_consume_learn_on_land_closes_listed_issues(monkeypatch):
    closed: list[int] = []
    monkeypatch.setattr(
        plans,
        "close_and_label_consolidated",
        lambda *, issue, repo_root, **k: closed.append(issue) or True,
    )
    out = _consume_learn_on_land(
        _github_backend(), landed=LandedPlan(plan_id="7", consumed_learn=("45", "50"))
    )
    assert out.closed == ("45", "50") and out.skipped_reason is None
    assert closed == [45, 50]


def test_consume_learn_on_land_is_fail_open(monkeypatch):
    # A fully-failing close is fail-open (never raises) and the failure is recorded per-issue.
    def _boom(**k):
        raise github.GitHubError("gh exploded")

    monkeypatch.setattr(plans, "close_and_label_consolidated", _boom)
    out = _consume_learn_on_land(
        _github_backend(), landed=LandedPlan(plan_id="7", consumed_learn=("45",))
    )
    assert out.closed == ()
    assert out.skipped_reason == "failed: #45"


def test_consume_learn_on_land_isolates_one_bad_issue(monkeypatch):
    # One bad issue must not strand the rest — the good closes still land, the failure is
    # rolled into `failed: #N` while the result stays fail-open.
    closed: list[int] = []

    def _close(*, issue, repo_root, **k):
        if issue == 50:
            raise github.GitHubError("already deleted")
        closed.append(issue)
        return True

    monkeypatch.setattr(plans, "close_and_label_consolidated", _close)
    out = _consume_learn_on_land(
        _github_backend(), landed=LandedPlan(plan_id="7", consumed_learn=("45", "50", "51"))
    )
    assert out.closed == ("45", "51")
    assert closed == [45, 51]
    assert out.skipped_reason == "failed: #50"


# --- the composed operation: reconstructed inputs, convergence, the close guard --------------


class _FakeBackend:
    """A stateful non-github issue backend (explicit plan close, no autoclose short-circuit)."""

    backend_id = "linear"

    def __init__(self) -> None:
        self.header: dict[str, object] = {}
        self.header_stamps: list[dict[str, object]] = []
        self.plan_closes = 0
        self.consolidated: list[str] = []

    def get_plan(self, *, issue_id: str) -> issue_backend.PlanState:
        return issue_backend.PlanState(
            id=issue_id, url="u", title="T", header=dict(self.header), pr=None, state="OPEN"
        )

    def update_plan_header(self, *, issue_id: str, fields: dict[str, object]):
        self.header.update(fields)
        self.header_stamps.append(dict(fields))
        return issue_backend.PlanHeaderUpdate(fields_updated=tuple(fields), dry_run=False)

    def close_issue(self, *, issue_id: str) -> bool:
        self.plan_closes += 1
        return True

    def close_and_label_consolidated(self, *, issue_id: str) -> bool:
        self.consolidated.append(issue_id)
        return True


class _FakeStore:
    """A stateful objective store: node marks persist, so a second run sees terminal nodes."""

    backend_id = "linear"

    def __init__(self, nodes: list[objective.ObjectiveNode]) -> None:
        self.nodes = list(nodes)
        self.node_updates: list[str] = []
        self.closes = 0
        self.posts: list[str] = []

    def get_objective(self, *, objective_id: str) -> objective_store.ObjectiveState:
        return objective_store.ObjectiveState(
            id=objective_id, url="u", title="O", header={}, nodes=tuple(self.nodes)
        )

    def update_objective_node(self, **k):
        self.node_updates.append(k["node_id"])
        self.nodes = [
            objective.ObjectiveNode(id=n.id, description=n.description, status=k["status"], pr=n.pr)
            if n.id == k["node_id"]
            else n
            for n in self.nodes
        ]
        return objective_store.ObjectiveNodeUpdate(
            objective_id=str(k["objective_id"]),
            node_id=k["node_id"],
            comment_updated=False,
            dry_run=False,
        )

    def close_objective(self, *, objective_id: str, dry_run: bool = False) -> bool:
        self.closes += 1
        return True

    def post_status_update(self, *, objective_id: str, body: str, dry_run: bool = False) -> bool:
        self.posts.append(body)
        return True


def _wire(monkeypatch, backend: _FakeBackend, store: _FakeStore) -> None:
    monkeypatch.setattr(resolve, "resolve_issue_backend", lambda _root: backend)
    monkeypatch.setattr(resolve, "resolve_objective_store", lambda _root: store)


def test_finalize_with_reconstructed_inputs_touches_no_worktree_cache(monkeypatch, tmp_path):
    """The behavioral cache-independence proof: a repo root with NO cache.plan-ref (and no
    worktree state at all) still gets all four durable effects from reconstructed inputs.
    The import-level proof is the fresh-interpreter guard in test_delivery_continuation.py."""
    backend = _FakeBackend()
    store = _FakeStore([_node("1.1", pr="#ENG-7")])
    _wire(monkeypatch, backend, store)
    fin = finalize_landed_plan(
        tmp_path,
        landed=LandedPlan(plan_id="ENG-7", objective_id="proj-1", consumed_learn=("45",)),
        pr_base="main",
    )
    assert fin == LandFinalization(
        learn_state="skipped",  # a consolidation plan is stamped skipped up front
        plan_issue_closed=True,  # non-github backend → always the explicit close
        objective=ObjectiveLandUpdate("proj-1", ("1.1",), None, closed=True),
        learn=LearnConsumeUpdate(("45",), None),
    )
    assert backend.header_stamps == [{"learn_state": "skipped"}]
    assert backend.plan_closes == 1
    assert backend.consolidated == ["45"]
    assert store.node_updates == ["1.1"] and store.closes == 1
    # Nothing touched the worktree: no plan-ref, no marker, no file at all under the repo root.
    assert cache.read_plan_ref(tmp_path) is None
    assert list(tmp_path.iterdir()) == []


def test_finalize_twice_converges(monkeypatch, tmp_path):
    """Convergent-final-state idempotency: the second run marks no nodes (terminal-skip), keeps
    the learn_state (never-downgrade), and re-issues only backend-idempotent calls (the re-close
    is success, not a second effect)."""
    backend = _FakeBackend()
    store = _FakeStore([_node("1.1", pr="#ENG-7")])
    _wire(monkeypatch, backend, store)
    landed = LandedPlan(plan_id="ENG-7", objective_id="proj-1")

    first = finalize_landed_plan(tmp_path, landed=landed, pr_base="main")
    assert first.learn_state == "pending"
    assert first.objective == ObjectiveLandUpdate("proj-1", ("1.1",), None, closed=True)

    # Simulate the /learn pass completing between the two lands.
    backend.header["learn_state"] = "captured"

    second = finalize_landed_plan(tmp_path, landed=landed, pr_base="main")
    # Never-downgrade: `captured` is kept (no second stamp write) and reported as effective.
    assert second.learn_state == "captured"
    assert backend.header_stamps == [{"learn_state": "pending"}]
    # Terminal-skip: no second update_objective_node for the already-done node.
    assert store.node_updates == ["1.1"]
    # Idempotent re-closes are success, not a second effect (converged final state).
    assert store.closes == 2 and backend.plan_closes == 2
    assert second.objective == ObjectiveLandUpdate("proj-1", (), None, closed=True)
    assert second.learn == LearnConsumeUpdate((), "no_consumed_learn")  # benign skip
    # The "plan landed" update posts only when nodes were marked — once, on the first run.
    assert len(store.posts) == 1


def test_finalize_close_objective_on_complete_false_never_closes(monkeypatch, tmp_path):
    """The stacked per-layer guard: nodes are still marked and the honest computed `complete`
    still rides the project update, but close_objective is NEVER called — the aggregate close
    is the stacked caller's obligation after every layer outcome verifies."""
    backend = _FakeBackend()
    store = _FakeStore([_node("1.1", pr="#ENG-7")])
    _wire(monkeypatch, backend, store)

    def _never(**k):
        raise AssertionError("close_objective must not be called under the guard")

    monkeypatch.setattr(store, "close_objective", _never)
    fin = finalize_landed_plan(
        tmp_path,
        landed=LandedPlan(plan_id="ENG-7", objective_id="proj-1"),
        pr_base="main",
        close_objective_on_complete=False,
    )
    assert fin.objective == ObjectiveLandUpdate("proj-1", ("1.1",), None)
    assert fin.objective.closed is False
    assert store.node_updates == ["1.1"]
    # The roadmap IS complete after the mark — the update carries the honest computed value.
    assert len(store.posts) == 1
    assert store.posts[0].endswith("Objective complete.")


# --- the fail-open literal prefix stays byte-stable for the incremental caller ---------------


def test_fail_open_warnings_keep_the_land_prefix(monkeypatch, capsys):
    """The extracted helpers keep their exact `"perk pr land: …"` user_output literals (zero
    drift for the incremental caller; a stacked caller may parameterize later)."""

    def _boom(**k):
        raise github.GitHubError("gh exploded")

    monkeypatch.setattr(plans, "get_plan", _boom)
    out = finalize._stamp_learn_state(_github_backend(), landed=LandedPlan(plan_id="7"))
    assert out is None
    assert "perk pr land: learn-state stamp skipped (non-fatal)" in capsys.readouterr().err
