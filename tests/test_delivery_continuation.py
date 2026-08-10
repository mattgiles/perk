"""The sync continuation manifest (``perk/delivery/continuation.py``, §8.49).

The conflict-stop record's lifecycle: lineage-keyed round-trip, the fail-closed gate read
(absent / present / present-but-unparseable), main-root anchoring across linked worktrees,
and the import-order cycle guard (``continuation`` must never reach ``perk.state.cache``).
"""

import json
import subprocess
import sys

import pytest

from perk.delivery import continuation
from perk.substrate import git as git_mod

LINEAGE = "01JLINEAGEAAAAAAAAAAAAAAAA"


def _manifest(lineage: str = LINEAGE) -> continuation.ContinuationManifest:
    return continuation.ContinuationManifest(
        operation_id="01JOPAAAAAAAAAAAAAAAAAAAAA",
        objective_id="10",
        delivery_lineage=lineage,
        run_id="01JRUNAAAAAAAAAAAAAAAAAAAA",
        include_base=True,
        captured_base_head="a" * 40,
        layers=(
            continuation.ContinuationLayer(
                node_id="1.1",
                plan_id="101",
                branch="plan-101",
                before_sha="b" * 40,
                old_parent_edge="a" * 40,
                source_sha="c" * 40,
                new_parent_edge="d" * 40,
                candidate_temp_ref="refs/perk/sync/01JOP/plan-101",
                candidate_sha=None,  # the conflicting layer: no candidate computed
            ),
        ),
        conflict_node_id="1.1",
        worktree_path="/repo/.worktrees/sync-01JOP",
        created="2026-01-01T00:00:00Z",
    )


class TestManifestLifecycle:
    def test_round_trip_is_lineage_keyed(self, tmp_path) -> None:
        path = continuation.write_manifest(tmp_path, _manifest())
        assert path == tmp_path / ".perk/workflow/sync-continuations" / f"{LINEAGE}.json"
        pending = continuation.pending_continuation(tmp_path, LINEAGE)
        assert pending is not None and pending.path == path
        assert pending.manifest == _manifest()

    def test_absent_manifest_is_none(self, tmp_path) -> None:
        assert continuation.pending_continuation(tmp_path, LINEAGE) is None

    def test_cross_lineage_isolation(self, tmp_path) -> None:
        # A conflict on lineage B never overwrites (or gates) lineage A.
        other = "01JLINEAGEBBBBBBBBBBBBBBBB"
        continuation.write_manifest(tmp_path, _manifest())
        continuation.write_manifest(tmp_path, _manifest(other))
        first = continuation.pending_continuation(tmp_path, LINEAGE)
        second = continuation.pending_continuation(tmp_path, other)
        assert first is not None and first.manifest is not None
        assert first.manifest.delivery_lineage == LINEAGE
        assert second is not None and second.manifest is not None
        assert second.manifest.delivery_lineage == other

    def test_unparseable_manifest_still_gates(self, tmp_path) -> None:
        # Fail closed: a present-but-unaccountable manifest is pending all the same.
        path = continuation.manifest_path(tmp_path, LINEAGE)
        path.parent.mkdir(parents=True)
        path.write_text("not json {", encoding="utf-8")
        pending = continuation.pending_continuation(tmp_path, LINEAGE)
        assert pending is not None and pending.manifest is None

        path.write_text(json.dumps({"schema_version": "1"}), encoding="utf-8")  # foreign shape
        pending = continuation.pending_continuation(tmp_path, LINEAGE)
        assert pending is not None and pending.manifest is None

    def test_schema_version_is_pinned_for_the_future_reader(self, tmp_path) -> None:
        continuation.write_manifest(tmp_path, _manifest())
        raw = json.loads(continuation.manifest_path(tmp_path, LINEAGE).read_text(encoding="utf-8"))
        assert raw["schema_version"] == "1"


class TestMainRootAnchoring:
    def test_worktree_write_is_visible_from_the_main_checkout(self, git_repo) -> None:
        # Sync residue is repo-common: a manifest written from a plan-<N> worktree gates a
        # sync run from the main checkout, and vice versa.
        wt = git_repo / ".worktrees" / "plan-101"
        git_mod.worktree_add_detached(git_repo, wt, "HEAD")
        path = continuation.write_manifest(wt, _manifest())
        assert path == git_repo / ".perk/workflow/sync-continuations" / f"{LINEAGE}.json"
        from_main = continuation.pending_continuation(git_repo, LINEAGE)
        from_worktree = continuation.pending_continuation(wt, LINEAGE)
        assert from_main is not None and from_main.manifest == _manifest()
        assert from_worktree is not None and from_worktree.path == from_main.path


class TestImportOrder:
    """The Task-4 cycle guard: ``state/cache.py`` imports ``perk.delivery.layer`` at module
    scope, so the delivery plane must reach the atomic-write seam through ``perk.substrate.fs``
    — both import orders must resolve in a fresh interpreter."""

    def _fresh_import(self, statements: str) -> None:
        subprocess.run(
            [sys.executable, "-c", statements],
            check=True,
            capture_output=True,
            timeout=120,
        )

    def test_cache_first_import_order(self) -> None:
        self._fresh_import("import perk.state.cache; import perk.delivery")

    def test_delivery_first_import_order(self) -> None:
        self._fresh_import("import perk.delivery; import perk.state.cache")

    def test_continuation_never_imports_perk_state(self) -> None:
        self._fresh_import(
            "import sys; import perk.delivery.continuation; "
            "assert not any(m.startswith('perk.state') for m in sys.modules), "
            "sorted(m for m in sys.modules if m.startswith('perk.state'))"
        )


class TestLineageSafety:
    """The lineage is stored objective metadata AND a filename: only path-safe tokens may
    reach a path derivation — a hostile value can never escape the continuation directory."""

    def test_hostile_lineages_are_refused_everywhere(self, tmp_path) -> None:
        for hostile in ("../escape", "a/b", "/abs/path", "..", "x.y", "", "-lead", "a" * 65):
            with pytest.raises(ValueError):
                continuation.manifest_path(tmp_path, hostile)
            with pytest.raises(ValueError):
                continuation.pending_continuation(tmp_path, hostile)
        with pytest.raises(ValueError):
            continuation.write_manifest(tmp_path, _manifest("../escape"))
        assert not (tmp_path.parent / "escape.json").exists()  # nothing escaped the root

    def test_safe_lineage_vocabulary(self) -> None:
        assert continuation.is_safe_lineage("01JLINEAGEAAAAAAAAAAAAAAAA") is True
        assert continuation.is_safe_lineage("with_underscore-and-dash1") is True
        assert continuation.is_safe_lineage("../escape") is False
        assert continuation.is_safe_lineage("a" * 64) is True
        assert continuation.is_safe_lineage("a" * 65) is False
