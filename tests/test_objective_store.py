"""Tests for the ``ObjectiveStore`` protocol module (Objective #548, Node 2.1).

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
from perk.backends import objective_store


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

    def create_objective(
        self,
        *,
        title: str,
        body: str,
        run_id: str,
        status: str = "active",
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

    def test_objective_body_update_exposes_objective_id(self) -> None:
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
    def test_objective_store_module_never_imports_issues(self) -> None:
        # The contract stays implementation-free: the protocol module never references the
        # concrete backend/resolver module.
        source = Path(objective_store.__file__).read_text(encoding="utf-8")
        assert "perk.backends.issues" not in source
        assert "import issues" not in source

    def test_objective_store_module_never_imports_github(self) -> None:
        # No PR field on any objective value type → no `perk.github` import (unlike issue_backend,
        # whose PlanState carries a PullRequest). Proves the no-github-import decision.
        source = Path(objective_store.__file__).read_text(encoding="utf-8")
        assert "perk.github" not in source
        assert "import github" not in source
