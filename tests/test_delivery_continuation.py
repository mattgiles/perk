"""The sync continuation manifest (``perk/delivery/continuation.py``, §8.49).

The conflict-stop record's lifecycle: lineage-keyed round-trip, the fail-closed gate read
(absent / present / present-but-unparseable), main-root anchoring across linked worktrees,
and the import-order cycle guard (``continuation`` must never reach ``perk.state.cache``).
"""

import json
import subprocess
import sys
from dataclasses import replace

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

    @pytest.mark.parametrize(
        "missing_key", ["captured_base_head", "new_parent_edge", "candidate_sha"]
    )
    def test_missing_nullable_key_gates_as_unaccountable(self, tmp_path, missing_key) -> None:
        # The nullable boundary fields are required-but-nullable: the writer always emits
        # explicit nulls, so a payload MISSING one of these keys is a foreign shape and must
        # fail the parse — still gating (manifest=None), never parsing as an implicit null.
        path = continuation.write_manifest(tmp_path, _manifest())
        raw = json.loads(path.read_text(encoding="utf-8"))
        if missing_key in raw:
            del raw[missing_key]
        else:
            del raw["layers"][0][missing_key]
        path.write_text(json.dumps(raw), encoding="utf-8")
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


class TestClearManifest:
    def test_clear_deletes_the_lineage_file(self, tmp_path) -> None:
        continuation.write_manifest(tmp_path, _manifest())
        continuation.clear_manifest(tmp_path, LINEAGE)
        assert continuation.pending_continuation(tmp_path, LINEAGE) is None

    def test_clear_is_missing_ok(self, tmp_path) -> None:
        continuation.clear_manifest(tmp_path, LINEAGE)  # retiring nothing is a no-op

    def test_clear_refuses_a_hostile_lineage(self, tmp_path) -> None:
        with pytest.raises(ValueError):
            continuation.clear_manifest(tmp_path, "../escape")

    def test_clear_is_lineage_scoped(self, tmp_path) -> None:
        other = "01JLINEAGEBBBBBBBBBBBBBBBB"
        continuation.write_manifest(tmp_path, _manifest())
        continuation.write_manifest(tmp_path, _manifest(other))
        continuation.clear_manifest(tmp_path, LINEAGE)
        assert continuation.pending_continuation(tmp_path, LINEAGE) is None
        assert continuation.pending_continuation(tmp_path, other) is not None


class TestIterManifests:
    def test_empty_directory_is_an_empty_scan(self, tmp_path) -> None:
        scan = continuation.iter_manifests(tmp_path)
        assert scan.manifests == () and scan.unparseable == ()

    def test_all_lineages_enumerate_with_unparseable_paths(self, tmp_path) -> None:
        other = "01JLINEAGEBBBBBBBBBBBBBBBB"
        continuation.write_manifest(tmp_path, _manifest())
        continuation.write_manifest(tmp_path, _manifest(other))
        broken = continuation.manifest_path(tmp_path, "01JLINEAGECCCCCCCCCCCCCCCC")
        broken.write_text("not json {", encoding="utf-8")
        scan = continuation.iter_manifests(tmp_path)
        assert {m.delivery_lineage for m in scan.manifests} == {LINEAGE, other}
        assert scan.unparseable == (broken,)


class TestAdoptedNodeCompat:
    """The additive v1 optional: 3.1 manifests (no ``adopted_node`` key) stay readable, and
    the render includes the field explicitly for the continue reader."""

    def test_absent_field_parses_as_none(self, tmp_path) -> None:
        path = continuation.write_manifest(tmp_path, _manifest())
        raw = json.loads(path.read_text(encoding="utf-8"))
        del raw["adopted_node"]  # a 3.1-era manifest
        path.write_text(json.dumps(raw), encoding="utf-8")
        pending = continuation.pending_continuation(tmp_path, LINEAGE)
        assert pending is not None and pending.manifest is not None
        assert pending.manifest.adopted_node is None

    def test_render_round_trips_the_adopted_node(self, tmp_path) -> None:
        manifest = replace(_manifest(), adopted_node="1.1")
        path = continuation.write_manifest(tmp_path, manifest)
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw["adopted_node"] == "1.1" and raw["schema_version"] == "1"
        pending = continuation.pending_continuation(tmp_path, LINEAGE)
        assert pending is not None and pending.manifest == manifest


class TestValidatedTargets:
    """Decision 14's containment seam: manifest data is never deletion authority by itself
    — every named target must match the perk-minted shapes exactly."""

    OP = "01JARSTVWXYZ0123456789ABCD"  # a canonical Crockford ULID

    def _contained(self, tmp_path, **overrides) -> continuation.ContinuationManifest:
        worktree_root = tmp_path / "wt"
        base = replace(
            _manifest(),
            operation_id=self.OP,
            worktree_path=str(worktree_root / f"sync-{self.OP}"),
            layers=(
                continuation.ContinuationLayer(
                    node_id="1.1",
                    plan_id="101",
                    branch="plan-101",
                    before_sha="b" * 40,
                    old_parent_edge="a" * 40,
                    source_sha="c" * 40,
                    new_parent_edge="d" * 40,
                    candidate_temp_ref=f"refs/perk/sync/{self.OP}/plan-101",
                    candidate_sha=None,
                ),
            ),
        )
        return replace(base, **overrides)

    def test_contained_manifest_yields_the_exact_targets(self, tmp_path) -> None:
        worktree_root = tmp_path / "wt"
        targets = continuation.validated_targets(self._contained(tmp_path), worktree_root)
        assert targets.operation_id == self.OP
        assert targets.worktree == (worktree_root / f"sync-{self.OP}").resolve()
        assert targets.ref_prefix == f"refs/perk/sync/{self.OP}/"
        assert targets.temp_refs == (f"refs/perk/sync/{self.OP}/plan-101",)

    def test_non_ulid_operation_id_is_a_violation(self, tmp_path) -> None:
        manifest = self._contained(tmp_path, operation_id="not-a-ulid")
        with pytest.raises(continuation.ContainmentViolation, match="canonical ULID"):
            continuation.validated_targets(manifest, tmp_path / "wt")

    def test_foreign_worktree_path_is_a_violation(self, tmp_path) -> None:
        for hostile in (
            "/etc/passwd",
            str(tmp_path / "elsewhere" / f"sync-{self.OP}"),
            str(tmp_path / "wt" / "sync-01JDIFFERENTOPAAAAAAAAAAAA"),
            str(tmp_path / "wt" / ".." / "wt2" / f"sync-{self.OP}"),
        ):
            manifest = self._contained(tmp_path, worktree_path=hostile)
            with pytest.raises(continuation.ContainmentViolation, match="worktree"):
                continuation.validated_targets(manifest, tmp_path / "wt")

    def test_symlink_escape_is_a_violation(self, tmp_path) -> None:
        # The stored path resolves through a symlink to somewhere outside worktree_root.
        worktree_root = tmp_path / "wt"
        worktree_root.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (worktree_root / f"sync-{self.OP}").symlink_to(outside)
        manifest = self._contained(tmp_path)
        with pytest.raises(continuation.ContainmentViolation, match="worktree"):
            continuation.validated_targets(manifest, worktree_root)

    def test_foreign_temp_ref_is_a_violation(self, tmp_path) -> None:
        for hostile in (
            "refs/heads/main",
            "refs/perk/sync/01JDIFFERENTOPAAAAAAAAAAAA/plan-101",
            f"refs/perk/sync/{self.OP}/other-branch",
        ):
            layer = self._contained(tmp_path).layers[0]
            manifest = self._contained(
                tmp_path, layers=(replace(layer, candidate_temp_ref=hostile),)
            )
            with pytest.raises(continuation.ContainmentViolation):
                continuation.validated_targets(manifest, tmp_path / "wt")

    def test_traversal_branch_segment_is_a_violation(self, tmp_path) -> None:
        layer = self._contained(tmp_path).layers[0]
        manifest = self._contained(
            tmp_path,
            layers=(
                replace(
                    layer,
                    branch="../../heads/main",
                    candidate_temp_ref=f"refs/perk/sync/{self.OP}/../../heads/main",
                ),
            ),
        )
        with pytest.raises(continuation.ContainmentViolation, match="containable"):
            continuation.validated_targets(manifest, tmp_path / "wt")
