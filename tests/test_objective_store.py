"""Tests for the ``ObjectiveStore`` protocol module.

The real conformance check is **static**: ``_FakeObjectiveStore`` is assigned to an
``objective_store.ObjectiveStore``-annotated binding, so ty fails the suite if the fake and the
protocol drift. The runtime tests are smoke proofs that the contract is satisfiable with string
ids, plus value-type sanity (the ``issue_id → objective_id`` rename) and the import-direction
guards (the contract stays implementation-free and never imports ``perk.github``).
"""

import dataclasses
from pathlib import Path

import pytest

from perk import objective
from perk.backends import engagement, objective_store


@dataclasses.dataclass
class _FakeObjective:
    title: str
    body: str
    run_id: str
    nodes: tuple[objective.ObjectiveNode, ...]
    state: str = "OPEN"


class _FakeObjectiveStore:
    """A minimal in-memory ``ObjectiveStore`` proving the contract is satisfiable."""

    backend_id = "fake"

    def __init__(self) -> None:
        self._objectives: dict[str, _FakeObjective] = {}
        self._next_id = 1

    def find_objective(self, *, run_id: str) -> objective_store.ObjectiveRef | None:
        for objective_id, obj in self._objectives.items():
            if obj.run_id == run_id and obj.state == "OPEN":
                return objective_store.ObjectiveRef(
                    id=objective_id, url=f"fake://objective/{objective_id}", existed=True
                )
        return None

    def read_objective_source(
        self, *, source_id: str
    ) -> objective_store.AdoptableObjectiveSource | None:
        # The minimal fake has no project-source surface (the dormant "doesn't adopt" signal).
        return None

    def adopt_source_as_objective(
        self,
        *,
        source_id: str,
        title: str,
        prose: str,
        run_id: str,
        status: str = "active",
        base: str | None = None,
        roadmap_nodes: list[objective.ObjectiveNode],
        adopt_map: dict[str, str],
        dry_run: bool = False,
    ) -> objective_store.ObjectiveRef | None:
        # The minimal fake does not support in-place adoption (the "doesn't adopt" signal).
        return None

    def create_objective(
        self,
        *,
        title: str,
        body: str,
        run_id: str,
        status: str = "active",
        base: str | None = None,
        roadmap_nodes: list[objective.ObjectiveNode] | None = None,
        dry_run: bool = False,
    ) -> objective_store.ObjectiveRef:
        if dry_run:
            return objective_store.ObjectiveRef(id="0", url="(dry-run)", existed=False)
        existing = self.find_objective(run_id=run_id)
        if existing is not None:
            return existing
        if not roadmap_nodes:
            raise objective_store.ObjectiveStoreError("objective roadmap is empty")
        objective_id = str(self._next_id)
        self._next_id += 1
        self._objectives[objective_id] = _FakeObjective(
            title=title, body=body, run_id=run_id, nodes=tuple(roadmap_nodes)
        )
        return objective_store.ObjectiveRef(
            id=objective_id, url=f"fake://objective/{objective_id}", existed=False
        )

    def get_objective(self, *, objective_id: str) -> objective_store.ObjectiveState | None:
        obj = self._objectives.get(objective_id)
        if obj is None:
            return None
        return objective_store.ObjectiveState(
            id=objective_id,
            url=f"fake://objective/{objective_id}",
            title=obj.title,
            header={},
            nodes=obj.nodes,
        )

    def update_objective_header(
        self, *, objective_id: str, fields: dict[str, object], dry_run: bool = False
    ) -> objective_store.ObjectiveHeaderUpdate:
        return objective_store.ObjectiveHeaderUpdate(fields_updated=tuple(fields), dry_run=dry_run)

    def update_objective_node(
        self,
        *,
        objective_id: str,
        node_id: str,
        status: objective.NodeStatus | None = None,
        pr: str | None = None,
        description: str | None = None,
        dry_run: bool = False,
    ) -> objective_store.ObjectiveNodeUpdate:
        return objective_store.ObjectiveNodeUpdate(
            objective_id=objective_id, node_id=node_id, comment_updated=False, dry_run=dry_run
        )

    def update_objective_body(
        self, *, objective_id: str, prose: str, dry_run: bool = False
    ) -> objective_store.ObjectiveBodyUpdate:
        return objective_store.ObjectiveBodyUpdate(
            objective_id=objective_id, comment_id=None, updated=not dry_run, dry_run=dry_run
        )

    def add_objective_node(
        self,
        *,
        objective_id: str,
        phase: int,
        description: str,
        status: objective.NodeStatus = objective.NodeStatus.PENDING,
        slug: str | None = None,
        depends_on: tuple[str, ...] | None = None,
        comment: str | None = None,
        dry_run: bool = False,
    ) -> objective_store.ObjectiveNodeAdd:
        obj = self._objectives.get(objective_id)
        if obj is None:
            raise objective_store.ObjectiveStoreError(f"objective {objective_id!r} not found")
        result = objective.add_node(
            list(obj.nodes),
            phase=phase,
            description=description,
            status=status,
            slug=slug,
            depends_on=depends_on,
            comment=comment,
        )
        if result is None:
            raise objective_store.ObjectiveStoreError("id collision")
        updated, new_id = result
        if not dry_run:
            self._objectives[objective_id] = dataclasses.replace(obj, nodes=tuple(updated))
        return objective_store.ObjectiveNodeAdd(
            objective_id=objective_id, node_id=new_id, comment_updated=False, dry_run=dry_run
        )

    def save_node_plan(
        self,
        *,
        objective_id: str,
        node_id: str,
        header_fields: dict[str, object],
        plan_markdown: str,
        dry_run: bool = False,
    ) -> objective_store.ObjectiveRef | None:
        # The minimal fake does not unify node + plan (the single "doesn't unify" signal).
        return None

    def close_objective(self, *, objective_id: str, dry_run: bool = False) -> bool:
        if dry_run:
            return False
        obj = self._objectives.get(objective_id)
        if obj is not None:
            self._objectives[objective_id] = dataclasses.replace(obj, state="CLOSED")
        return True

    def post_status_update(self, *, objective_id: str, body: str, dry_run: bool = False) -> bool:
        # The minimal fake has no status-update surface.
        return False

    def detect_objective_drift(self, *, objective_id: str) -> objective_store.DriftReport:
        # The minimal fake has no divergence surface.
        return objective_store.DriftReport()

    def repair_objective_drift(
        self, *, objective_id: str, dry_run: bool = False
    ) -> objective_store.RepairResult:
        return objective_store.RepairResult(
            applied=(), failed=None, remaining=(), aborted=False, dry_run=dry_run
        )

    # --- human-engagement reads ---

    def read_comments(self, *, objective_id: str) -> tuple[engagement.EngagementComment, ...]:
        return ()

    def read_description_edits(
        self, *, objective_id: str
    ) -> tuple[engagement.DescriptionEdit, ...]:
        return ()

    def read_agent_session(self, *, objective_id: str) -> engagement.AgentSessionRead:
        return engagement.EMPTY_AGENT_SESSION

    def read_node_engagement(self, *, objective_id: str, node_id: str) -> engagement.NodeEngagement:
        return engagement.EMPTY_NODE_ENGAGEMENT


def _make_store() -> objective_store.ObjectiveStore:
    """The static conformance check: ty verifies ``_FakeObjectiveStore`` satisfies the protocol."""
    store: objective_store.ObjectiveStore = _FakeObjectiveStore()
    return store


def _node() -> objective.ObjectiveNode:
    return objective.ObjectiveNode(
        id="1.1", description="seed", status=objective.NodeStatus.PENDING
    )


class TestFakeStoreConformance:
    def test_create_find_round_trip_on_run_id(self) -> None:
        store = _make_store()
        created = store.create_objective(
            title="t", body="b", run_id="RUN1", roadmap_nodes=[_node()]
        )
        assert isinstance(created.id, str)
        assert created.existed is False
        found = store.find_objective(run_id="RUN1")
        assert found is not None
        assert found.id == created.id
        assert found.existed is True
        # idempotent re-create returns the existing objective
        again = store.create_objective(title="t", body="b", run_id="RUN1", roadmap_nodes=[_node()])
        assert again.id == created.id
        assert again.existed is True

    def test_create_objective_dry_run_shape(self) -> None:
        store = _make_store()
        ref = store.create_objective(title="t", body="b", run_id="RUN1", dry_run=True)
        assert ref == objective_store.ObjectiveRef(id="0", url="(dry-run)", existed=False)

    def test_get_and_update_node_string_id_round_trip(self) -> None:
        store = _make_store()
        ref = store.create_objective(title="t", body="b", run_id="RUN2", roadmap_nodes=[_node()])
        state = store.get_objective(objective_id=ref.id)
        assert state is not None
        assert isinstance(state.id, str)
        assert state.nodes == (_node(),)
        update = store.update_objective_node(objective_id=ref.id, node_id="1.1")
        assert isinstance(update.objective_id, str)
        assert update.objective_id == ref.id

    def test_add_objective_node_assigns_next_id(self) -> None:
        store = _make_store()
        ref = store.create_objective(title="t", body="b", run_id="RUN3", roadmap_nodes=[_node()])
        added = store.add_objective_node(objective_id=ref.id, phase=1, description="Delta")
        assert added.node_id == "1.2"
        assert added.dry_run is False
        state = store.get_objective(objective_id=ref.id)
        assert state is not None
        assert [n.id for n in state.nodes] == ["1.1", "1.2"]

    def test_add_objective_node_dry_run_does_not_persist(self) -> None:
        store = _make_store()
        ref = store.create_objective(title="t", body="b", run_id="RUN4", roadmap_nodes=[_node()])
        added = store.add_objective_node(
            objective_id=ref.id, phase=1, description="Delta", dry_run=True
        )
        assert added.node_id == "1.2"
        assert added.dry_run is True
        state = store.get_objective(objective_id=ref.id)
        assert state is not None
        assert [n.id for n in state.nodes] == ["1.1"]

    def test_adoption_no_op_signals(self) -> None:
        # A store with no project-source surface returns None for both adoption methods.
        store = _make_store()
        assert store.read_objective_source(source_id="anything") is None
        assert (
            store.adopt_source_as_objective(
                source_id="anything",
                title="t",
                prose="p",
                run_id="RUN5",
                roadmap_nodes=[_node()],
                adopt_map={},
            )
            is None
        )


class TestAdoptableSourceShapes:
    def test_adoptable_source_issue_frozen_fields(self) -> None:
        issue = objective_store.AdoptableSourceIssue(
            id="uuid-1", identifier="ENG-1", url="u", title="T", body="B"
        )
        assert issue.id == "uuid-1"
        assert issue.identifier == "ENG-1"
        assert issue.title == "T"
        with pytest.raises(dataclasses.FrozenInstanceError):
            issue.title = "X"  # ty: ignore[invalid-assignment]

    def test_adoptable_objective_source_defaults_empty_issues(self) -> None:
        src = objective_store.AdoptableObjectiveSource(id="7", url="u", title="T", prose="P")
        assert src.issues == ()
        with pytest.raises(dataclasses.FrozenInstanceError):
            src.prose = "X"  # ty: ignore[invalid-assignment]


class TestValueTypes:
    def test_objective_ref_is_frozen_with_string_id(self) -> None:
        ref = objective_store.ObjectiveRef(id="42", url="u", existed=False)
        assert ref.id == "42"
        with pytest.raises(dataclasses.FrozenInstanceError):
            ref.id = "43"  # ty: ignore[invalid-assignment]

    def test_objective_node_update_exposes_objective_id(self) -> None:
        update = objective_store.ObjectiveNodeUpdate(
            objective_id="9", node_id="1.1", comment_updated=True, dry_run=False
        )
        assert update.objective_id == "9"
        with pytest.raises(dataclasses.FrozenInstanceError):
            update.comment_updated = False  # ty: ignore[invalid-assignment]

    def test_objective_node_add_exposes_fields(self) -> None:
        added = objective_store.ObjectiveNodeAdd(
            objective_id="9", node_id="2.3", comment_updated=True, dry_run=False
        )
        assert added.objective_id == "9"
        assert added.node_id == "2.3"
        with pytest.raises(dataclasses.FrozenInstanceError):
            added.node_id = "2.4"  # ty: ignore[invalid-assignment]

    def test_objective_body_update_exposes_objective_id(self) -> None:
        update = objective_store.ObjectiveBodyUpdate(
            objective_id="9", comment_id="123", updated=True, dry_run=False
        )
        assert update.objective_id == "9"
        assert update.comment_id == "123"
        with pytest.raises(dataclasses.FrozenInstanceError):
            update.updated = False  # ty: ignore[invalid-assignment]

    def test_objective_body_update_string_comment_id(self) -> None:
        # Moved from tests/test_issue_backend.py with the objective tier's extraction:
        # the comment id is a string at the boundary (backend-owned opaque value).
        update = objective_store.ObjectiveBodyUpdate(
            objective_id="9", comment_id="123", updated=True, dry_run=False
        )
        assert update.objective_id == "9"
        assert update.comment_id == "123"
        with pytest.raises(dataclasses.FrozenInstanceError):
            update.updated = False  # ty: ignore[invalid-assignment]


class TestErrorType:
    def test_objective_store_error_is_raisable_exception(self) -> None:
        assert issubclass(objective_store.ObjectiveStoreError, Exception)
        with pytest.raises(objective_store.ObjectiveStoreError, match="boom"):
            raise objective_store.ObjectiveStoreError("boom")


class TestImportDirection:
    def test_objective_store_module_never_imports_the_resolver(self) -> None:
        # The contract stays implementation-free: the protocol module never references the
        # concrete backend/resolver modules.
        source = Path(objective_store.__file__).read_text(encoding="utf-8")
        assert "perk.backends.resolve" not in source
        assert "perk.backends.github" not in source

    def test_objective_store_module_never_imports_github(self) -> None:
        # No PR field on any objective value type → no `perk.github` import (unlike issue_backend,
        # whose PlanState carries a PullRequest). Proves the no-github-import decision.
        source = Path(objective_store.__file__).read_text(encoding="utf-8")
        assert "perk.github" not in source
        assert "import github" not in source
