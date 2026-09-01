"""Tests for ``perk objective stack status`` (``commands/objective/stack/status_cmd.py``).

CLI-level via ``CliRunner`` over the full ``cli`` in an isolated repo, with the
``Delivery.status`` seam monkeypatched — the projection itself is pinned in
``test_delivery_train.py``; here the envelope, resolution order, exit codes, and the
stdout/stderr split are the contract.
"""

import json
import subprocess
from dataclasses import replace
from pathlib import Path

from click.testing import CliRunner

from perk import plan
from perk.cli.cli import cli
from perk.cli.commands.objective.stack import status_cmd
from perk.cli.ensure import UserFacingCliError
from perk.delivery import DeliveryError, StatusResult, continuation, recover, train
from perk.state import cache

_URL = "https://github.com/o/r/issues/1431"


def _no_train(objective_id: str = "1431", redirected_from: str | None = None):
    return train.NoDeliveryTrain(
        objective_id=objective_id,
        objective_url=_URL,
        redirected_from=redirected_from,
        reason=train.NO_TRAIN_INCREMENTAL_REASON,
    )


def _layer(**overrides) -> train.TrainLayer:
    values: dict = {
        "node_id": "1.2",
        "plan_id": "1457",
        "branch": "plan-1457",
        "pr_number": 1465,
        "intent": train.LayerIntent.PLANNED,
        "publication": train.LayerPublication.PUBLISHED,
        "git": train.LayerGit.SYNCED,
        "pr": train.LayerPr.READY,
        "membership": train.LayerMembership.EXACT,
        "writer": train.LayerWriter.FREE,
        "finalization": train.LayerFinalization.NOT_MERGED,
        "parent_checkpoint_sha": "a" * 40,
        "published_head_sha": "b" * 40,
        "observed_remote_head_sha": "b" * 40,
        "observed_pr_base": "main",
        "expected_pr_base": "main",
        "handoff": train.LayerHandoff.NOT_APPLICABLE,
    }
    values.update(overrides)
    return train.TrainLayer(**values)


def _train(
    *,
    findings: tuple[train.TrainFinding, ...] = (),
    layers: tuple[train.TrainLayer, ...] | None = None,
) -> train.DeliveryTrain:
    return train.DeliveryTrain(
        objective_id="1431",
        objective_url=_URL,
        delivery_lineage="01JB0000000000000000000000",
        base="main",
        redirected_from=None,
        layers=layers if layers is not None else (_layer(),),
        published_prefix_len=1,
        unresolved_operation=None,
        findings=findings,
        build_readiness=train.BuildReadiness(
            next_node_id=None, ready=False, reason="all layers published"
        ),
    )


def _invoke(args, *, monkeypatch, result=None, git_init=True, setup=None):
    """Invoke the CLI with ``Delivery.status`` returning (or raising) ``result`` and record
    the requested objective id. ``setup`` receives the repo root before invocation."""
    asked: list[str] = []

    class FakeDelivery:
        def status(self, request):
            asked.append(request.objective_id)
            if isinstance(result, Exception):
                raise result
            assert result is not None, "Delivery.status must not be reached"
            if isinstance(result, train.NoDeliveryTrain):
                return StatusResult(
                    objective_id=result.objective_id,
                    objective_url=result.objective_url,
                    redirected_from=result.redirected_from,
                    train=None,
                    no_train_reason=result.reason,
                )
            return StatusResult(
                objective_id=result.objective_id,
                objective_url=result.objective_url,
                redirected_from=result.redirected_from,
                train=result,
                no_train_reason=None,
            )

    monkeypatch.setattr(status_cmd, "resolve_delivery", lambda _root: FakeDelivery())
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        if git_init:
            subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        if setup is not None:
            setup(Path(d))
        outcome = runner.invoke(cli, args)
    return outcome, asked


def test_incremental_objective_json(monkeypatch):
    result, asked = _invoke(
        ["objective", "stack", "status", "1431", "--json"],
        monkeypatch=monkeypatch,
        result=_no_train(),
    )
    assert result.exit_code == 0
    assert asked == ["1431"]
    payload = json.loads(result.stdout)
    assert payload["success"] is True and payload["error_type"] is None
    assert payload["delivery"] == "incremental"
    assert payload["train"] is None
    assert payload["no_train"] == train.NO_TRAIN_INCREMENTAL_REASON
    assert payload["objective"] == {"id": "1431", "url": _URL, "redirected_from": None}
    assert result.stderr == ""


def test_incremental_objective_human(monkeypatch):
    result, _ = _invoke(
        ["objective", "stack", "status", "1431"], monkeypatch=monkeypatch, result=_no_train()
    )
    assert result.exit_code == 0
    assert result.stdout == ""  # human render is stderr-only
    assert train.NO_TRAIN_INCREMENTAL_REASON in result.stderr


def test_explicit_argument_accepts_hash_form(monkeypatch):
    _, asked = _invoke(
        ["objective", "stack", "status", "#1431", "--json"],
        monkeypatch=monkeypatch,
        result=_no_train(),
    )
    assert asked == ["1431"]


def test_stacked_happy_path_envelope(monkeypatch):
    result, _ = _invoke(
        ["objective", "stack", "status", "1431", "--json"],
        monkeypatch=monkeypatch,
        result=_train(),
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["delivery"] == "stacked" and payload["no_train"] is None
    assert set(payload) == {
        "success",
        "error_type",
        "objective",
        "delivery",
        "train",
        "no_train",
        "operations",
        "continuation",
        "orphaned_residue",
    }
    # The §8.44 detailed-status additions on a clean world: no unresolved operations, no
    # pending continuation, and a genuinely-clean POSITIVE residue observation.
    assert payload["operations"] == []
    assert payload["continuation"] is None
    assert payload["orphaned_residue"] == {
        "observed": True,
        "reason": None,
        "worktrees": [],
        "refs": [],
    }
    body = payload["train"]
    assert set(body) == {
        "delivery_lineage",
        "base",
        "published_prefix_len",
        "layers",
        "unresolved_operation",
        "blockers",
        "information",
        "next_build_ready",
        "observed_base_head_sha",
        "landed_prefix_len",
        "planning_gate",
    }
    assert body["published_prefix_len"] == 1
    assert body["observed_base_head_sha"] is None  # the defaulted honest "not observed" fact
    assert body["next_build_ready"] == {
        "node_id": None,
        "ready": False,
        "reason": "all layers published",
    }
    layer = body["layers"][0]
    assert layer["node_id"] == "1.2" and layer["pr_number"] == 1465
    assert layer["publication"] == "published" and layer["membership"] == "exact"
    assert layer["handoff"] == "not_applicable"  # the defaulted honest no-surface fact


def test_blockers_present_still_exits_zero(monkeypatch):
    finding = train.TrainFinding(
        kind=train.FindingKind.BLOCKER,
        code="checkpoint_drift",
        message="recorded b... observed d...",
        node_id="1.2",
        plan_id="1457",
    )
    result, _ = _invoke(
        ["objective", "stack", "status", "1431", "--json"],
        monkeypatch=monkeypatch,
        result=_train(findings=(finding,)),
    )
    assert result.exit_code == 0  # blockers are a successful DETECTION
    payload = json.loads(result.stdout)
    assert payload["train"]["blockers"] == [
        {
            "code": "checkpoint_drift",
            "message": "recorded b... observed d...",
            "node_id": "1.2",
            "plan_id": "1457",
        }
    ]
    assert payload["train"]["information"] == []


def test_human_render_lists_layers_and_findings(monkeypatch):
    finding = train.TrainFinding(
        kind=train.FindingKind.INFO, code="stack_read_unavailable", message="preview down"
    )
    result, _ = _invoke(
        ["objective", "stack", "status", "1431"],
        monkeypatch=monkeypatch,
        result=_train(findings=(finding,)),
    )
    assert result.exit_code == 0
    assert "1. 1.2 plan #1457 [published] pr #1465 (ready) stack exact" in result.stderr
    assert "information:" in result.stderr
    assert "[stack_read_unavailable] preview down" in result.stderr
    assert "build blocked: all layers published" in result.stderr


def test_human_render_and_envelope_carry_the_landed_prefix(monkeypatch):
    landed = replace(_train(), landed_prefix_len=1)
    result, _ = _invoke(
        ["objective", "stack", "status", "1431", "--json"],
        monkeypatch=monkeypatch,
        result=landed,
    )
    assert json.loads(result.stdout)["train"]["landed_prefix_len"] == 1
    result, _ = _invoke(
        ["objective", "stack", "status", "1431"],
        monkeypatch=monkeypatch,
        result=landed,
    )
    assert "published prefix 1/1, landed 1" in result.stderr
    # Zero landed layers: the headline stays the pre-growth shape.
    result, _ = _invoke(
        ["objective", "stack", "status", "1431"], monkeypatch=monkeypatch, result=_train()
    )
    assert "published prefix 1/1)" in result.stderr


def test_handoff_axis_rides_the_envelope_and_the_render(monkeypatch):
    stamped = _train(layers=(_layer(handoff=train.LayerHandoff.READY),))
    result, _ = _invoke(
        ["objective", "stack", "status", "1431", "--json"],
        monkeypatch=monkeypatch,
        result=stamped,
    )
    assert json.loads(result.stdout)["train"]["layers"][0]["handoff"] == "ready"
    result, _ = _invoke(
        ["objective", "stack", "status", "1431"], monkeypatch=monkeypatch, result=stamped
    )
    assert "1. 1.2 plan #1457 [published] pr #1465 (ready) stack exact handoff ready" in (
        result.stderr
    )
    stale = _train(layers=(_layer(handoff=train.LayerHandoff.STALE),))
    result, _ = _invoke(
        ["objective", "stack", "status", "1431"], monkeypatch=monkeypatch, result=stale
    )
    assert "handoff stale" in result.stderr
    # A not_applicable layer renders without the part (the pre-growth line shape).
    result, _ = _invoke(
        ["objective", "stack", "status", "1431"], monkeypatch=monkeypatch, result=_train()
    )
    assert "handoff" not in result.stderr


def test_human_render_names_the_build_ready_layer(monkeypatch):
    ready_train = train.DeliveryTrain(
        objective_id="1431",
        objective_url=_URL,
        delivery_lineage="01JB0000000000000000000000",
        base="main",
        redirected_from=None,
        layers=(_layer(),),
        published_prefix_len=0,
        unresolved_operation=None,
        findings=(),
        build_readiness=train.BuildReadiness(next_node_id="2.2", ready=True, reason=None),
    )
    result, _ = _invoke(
        ["objective", "stack", "status", "1431"], monkeypatch=monkeypatch, result=ready_train
    )
    assert result.exit_code == 0
    assert "next build-ready: 2.2" in result.stderr


def test_plan_ref_inference(monkeypatch):
    ref = plan.PlanRef(provider="github", pr_id="1474", url="u", labels=(), objective_id="1431")
    monkeypatch.setattr(cache, "read_plan_ref", lambda _root: ref)
    _, asked = _invoke(
        ["objective", "stack", "status", "--json"], monkeypatch=monkeypatch, result=_no_train()
    )
    assert asked == ["1431"]


def test_no_objective_is_a_typed_failure(monkeypatch):
    # No argument and no plan-ref in the fresh repo → no_objective, exit 1.
    result, asked = _invoke(
        ["objective", "stack", "status", "--json"], monkeypatch=monkeypatch, result=_no_train()
    )
    assert result.exit_code == 1
    assert asked == []
    payload = json.loads(result.stdout)
    assert payload["success"] is False and payload["error_type"] == "no_objective"


def test_reconstruction_failure_maps_error_type(monkeypatch):
    error = DeliveryError("no canonical delivery order exists: cycle", error_type="invalid_train")
    result, _ = _invoke(
        ["objective", "stack", "status", "1431", "--json"],
        monkeypatch=monkeypatch,
        result=error,
    )
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error_type"] == "invalid_train"
    assert "cycle" in payload["message"]


def test_not_a_repo_exits_two(monkeypatch):
    result, _ = _invoke(
        ["objective", "stack", "status", "1431", "--json"],
        monkeypatch=monkeypatch,
        result=_no_train(),
        git_init=False,
    )
    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["error_type"] == "not_a_repo"


def test_redirected_from_is_reported(monkeypatch):
    result, _ = _invoke(
        ["objective", "stack", "status", "9", "--json"],
        monkeypatch=monkeypatch,
        result=_no_train(redirected_from="9"),
    )
    payload = json.loads(result.stdout)
    assert payload["objective"]["redirected_from"] == "9"
    human, _ = _invoke(
        ["objective", "stack", "status", "9"],
        monkeypatch=monkeypatch,
        result=_no_train(redirected_from="9"),
    )
    assert "redirected from #9" in human.stderr


# ----------------------------------------------------------------- detailed status (§8.44)


def _manifest(lineage: str = "01JB0000000000000000000000") -> continuation.ContinuationManifest:
    return continuation.ContinuationManifest(
        operation_id="01JOP0000000000000000000AA",
        objective_id="1431",
        delivery_lineage=lineage,
        run_id="01RUN",
        include_base=False,
        captured_base_head=None,
        layers=(),
        conflict_node_id="1.2",
        worktree_path="/wt/sync-01JOP0000000000000000000AA",
        created="2026-01-01T00:00:00Z",
        adopted_node="1.2",
    )


def test_every_unresolved_operation_rides_the_envelope(monkeypatch):
    facts = (
        train.UnresolvedOperationFacts(
            operation_id="01OPA", kind="sync", prepared_created="2026-01-01T00:00:00Z"
        ),
        train.UnresolvedOperationFacts(
            operation_id="01OPB", kind="publish", prepared_created="2026-01-02T00:00:00Z"
        ),
    )
    stacked = train.DeliveryTrain(
        objective_id="1431",
        objective_url=_URL,
        delivery_lineage="01JB0000000000000000000000",
        base="main",
        redirected_from=None,
        layers=(_layer(),),
        published_prefix_len=1,
        unresolved_operation=facts[0],
        findings=(),
        build_readiness=train.BuildReadiness(
            next_node_id=None, ready=False, reason="all layers published"
        ),
        unresolved_operations=facts,
    )
    result, _ = _invoke(
        ["objective", "stack", "status", "1431", "--json"],
        monkeypatch=monkeypatch,
        result=stacked,
    )
    payload = json.loads(result.stdout)
    assert payload["operations"] == [
        {"operation_id": "01OPA", "kind": "sync", "prepared_created": "2026-01-01T00:00:00Z"},
        {"operation_id": "01OPB", "kind": "publish", "prepared_created": "2026-01-02T00:00:00Z"},
    ]
    # The legacy single field stays the first element.
    assert payload["train"]["unresolved_operation"] == payload["operations"][0]

    human, _ = _invoke(
        ["objective", "stack", "status", "1431"], monkeypatch=monkeypatch, result=stacked
    )
    assert human.stderr.count("active operation:") == 2


def test_pending_continuation_block_and_next_steps(monkeypatch):
    result, _ = _invoke(
        ["objective", "stack", "status", "1431", "--json"],
        monkeypatch=monkeypatch,
        result=_train(),
        setup=lambda root: continuation.write_manifest(root, _manifest()),
    )
    payload = json.loads(result.stdout)
    block = payload["continuation"]
    assert block["operation_id"] == "01JOP0000000000000000000AA"
    assert block["conflict_node_id"] == "1.2" and block["adopted_node"] == "1.2"
    assert block["worktree_path"] == "/wt/sync-01JOP0000000000000000000AA"
    assert block["parseable"] is True
    assert block["manifest_path"].endswith("01JB0000000000000000000000.json")
    # A PARSEABLE manifest protects its residue — the observation itself stays positive.
    assert payload["orphaned_residue"]["observed"] is True

    human, _ = _invoke(
        ["objective", "stack", "status", "1431"],
        monkeypatch=monkeypatch,
        result=_train(),
        setup=lambda root: continuation.write_manifest(root, _manifest()),
    )
    assert "pending continuation: operation 01JOP0000000000000000000AA" in human.stderr
    assert "sync --continue" in human.stderr and "sync --abort" in human.stderr


def test_contained_continuation_targets_report_true(monkeypatch):
    # The manifest's worktree resolves to exactly `<configured worktree_root>/sync-<op>` —
    # the canonical `validated_targets` containment passes and the envelope reports it.
    # The fixture's operation id is NOT a canonical Crockford ULID (it carries an `O`), so
    # the contained arm needs a genuinely valid one.
    def plant(root: Path) -> None:
        op = "01JQP0000000000000000000AA"
        worktree = root / ".worktrees" / f"sync-{op}"
        worktree.mkdir(parents=True)
        continuation.write_manifest(
            root,
            replace(_manifest(), operation_id=op, worktree_path=str(worktree)),
        )

    result, _ = _invoke(
        ["objective", "stack", "status", "1431", "--json"],
        monkeypatch=monkeypatch,
        result=_train(),
        setup=plant,
    )
    payload = json.loads(result.stdout)
    block = payload["continuation"]
    assert block["parseable"] is True
    assert block["targets_contained"] is True


def test_symlinked_continuation_worktree_reports_targets_contained_false(monkeypatch):
    # A symlink planted at the expected worktree location resolves elsewhere — the
    # containment validation refuses it and the observation fails closed (never raises).
    def plant(root: Path) -> None:
        op = "01JOP0000000000000000000AA"
        outside = root / "elsewhere"
        outside.mkdir(parents=True)
        worktrees = root / ".worktrees"
        worktrees.mkdir(parents=True)
        (worktrees / f"sync-{op}").symlink_to(outside)
        continuation.write_manifest(
            root, replace(_manifest(), worktree_path=str(worktrees / f"sync-{op}"))
        )

    result, _ = _invoke(
        ["objective", "stack", "status", "1431", "--json"],
        monkeypatch=monkeypatch,
        result=_train(),
        setup=plant,
    )
    payload = json.loads(result.stdout)
    block = payload["continuation"]
    assert block["parseable"] is True
    assert block["targets_contained"] is False


def test_foreign_and_relative_continuation_worktrees_report_targets_contained_false(monkeypatch):
    # A foreign absolute parent and a relative path both fall outside the configured
    # worktree root — `targets_contained` is false while the row itself stays parseable.
    for worktree_path in (
        "/wt/sync-01JOP0000000000000000000AA",
        "rel/sync-01JOP0000000000000000000AA",
    ):
        result, _ = _invoke(
            ["objective", "stack", "status", "1431", "--json"],
            monkeypatch=monkeypatch,
            result=_train(),
            setup=lambda root, wt=worktree_path: continuation.write_manifest(
                root, replace(_manifest(), worktree_path=wt)
            ),
        )
        payload = json.loads(result.stdout)
        block = payload["continuation"]
        assert block["parseable"] is True
        assert block["targets_contained"] is False, worktree_path


def test_unparseable_continuation_row_carries_nulls(monkeypatch):
    def plant(root: Path) -> None:
        path = continuation.manifest_path(root, "01JB0000000000000000000000")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not json {", encoding="utf-8")

    result, _ = _invoke(
        ["objective", "stack", "status", "1431", "--json"],
        monkeypatch=monkeypatch,
        result=_train(),
        setup=plant,
    )
    payload = json.loads(result.stdout)
    block = payload["continuation"]
    assert block["parseable"] is False
    assert block["targets_contained"] is False
    assert block["operation_id"] is None and block["worktree_path"] is None
    assert block["manifest_path"].endswith("01JB0000000000000000000000.json")
    # An unparseable manifest ALSO fires the sweep classifier's fail-safe: the residue
    # state is honestly unobserved, never clean empty lists.
    residue = payload["orphaned_residue"]
    assert residue["observed"] is False and "unparseable" in residue["reason"]
    assert residue["worktrees"] == [] and residue["refs"] == []


def test_residue_observation_failure_is_observed_false(monkeypatch):
    def boom(*_args, **_kwargs):
        raise OSError("disk unreadable")

    monkeypatch.setattr(recover, "observe_orphans", boom)
    result, _ = _invoke(
        ["objective", "stack", "status", "1431", "--json"],
        monkeypatch=monkeypatch,
        result=_train(),
    )
    assert result.exit_code == 0  # a failed LOCAL observation never fails status
    payload = json.loads(result.stdout)
    residue = payload["orphaned_residue"]
    assert residue["observed"] is False
    assert "disk unreadable" in residue["reason"]

    human, _ = _invoke(
        ["objective", "stack", "status", "1431"], monkeypatch=monkeypatch, result=_train()
    )
    assert "orphaned residue: not observed —" in human.stderr


def test_config_unavailable_is_a_successful_observed_false_status(monkeypatch):
    def config_unavailable(_ctx):
        raise UserFacingCliError(".perk config invalid: worktree_root is malformed")

    monkeypatch.setattr(status_cmd, "require_config", config_unavailable)
    result, _ = _invoke(
        ["objective", "stack", "status", "1431", "--json"],
        monkeypatch=monkeypatch,
        result=_train(),
    )
    assert result.exit_code == 0
    residue = json.loads(result.stdout)["orphaned_residue"]
    assert residue == {
        "observed": False,
        "reason": "config unavailable: .perk config invalid: worktree_root is malformed",
        "worktrees": [],
        "refs": [],
    }

    human, _ = _invoke(
        ["objective", "stack", "status", "1431"],
        monkeypatch=monkeypatch,
        result=_train(),
    )
    assert human.exit_code == 0
    assert "orphaned residue: not observed — config unavailable:" in human.stderr
    assert "worktree_root is malformed" in human.stderr


def test_orphaned_residue_counts_render_with_the_recover_hint(monkeypatch):
    def plant(root: Path) -> None:
        worktrees = root / ".worktrees" / "sync-01JAAAAAAAAAAAAAAAAAAAAAAA"
        worktrees.mkdir(parents=True)
        ref = "refs/perk/sync/01JAAAAAAAAAAAAAAAAAAAAAAA/plan-1457"
        subprocess.run(
            ["git", "update-ref", ref, _sha(root)],
            cwd=root,
            check=True,
            timeout=60,
        )

    result, _ = _invoke(
        ["objective", "stack", "status", "1431", "--json"],
        monkeypatch=monkeypatch,
        result=_train(),
        setup=plant,
    )
    payload = json.loads(result.stdout)
    residue = payload["orphaned_residue"]
    assert residue["observed"] is True
    assert len(residue["worktrees"]) == 1
    assert residue["worktrees"][0].endswith("sync-01JAAAAAAAAAAAAAAAAAAAAAAA")
    assert residue["refs"] == ["refs/perk/sync/01JAAAAAAAAAAAAAAAAAAAAAAA/plan-1457"]

    human, _ = _invoke(
        ["objective", "stack", "status", "1431"],
        monkeypatch=monkeypatch,
        result=_train(),
        setup=plant,
    )
    assert "orphaned residue: 1 worktree(s), 1 ref(s)" in human.stderr
    assert "perk objective stack recover" in human.stderr


def _sha(root: Path) -> str:
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "t@example.com"], check=True, timeout=60
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "perk tests"], check=True, timeout=60
    )
    subprocess.run(
        ["git", "-C", str(root), "commit", "-q", "--allow-empty", "-m", "seed"],
        check=True,
        timeout=60,
    )
    out = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return out.stdout.strip()


# --- the planning_gate block (§8.46) ------------------------------------------------------


def _gated_world():
    """A technically-ready two-layer train: published-unstamped 1.1, candidate 1.2 whose
    direct dep is 1.1 (the roadmap rides train.objective_nodes)."""
    from perk import objective

    nodes = (
        objective.ObjectiveNode(
            id="1.1",
            description="A",
            status=objective.NodeStatus.IN_PROGRESS,
            pr="#1457",
            depends_on=(),
        ),
        objective.ObjectiveNode(
            id="1.2",
            description="B",
            status=objective.NodeStatus.PENDING,
            depends_on=("1.1",),
        ),
    )
    bottom = _layer(node_id="1.1", handoff=train.LayerHandoff.UNSTAMPED)
    top = _layer(
        node_id="1.2",
        plan_id=None,
        branch=None,
        pr_number=None,
        intent=train.LayerIntent.UNPLANNED,
        publication=train.LayerPublication.UNPUBLISHED,
        git=train.LayerGit.ABSENT,
        pr=train.LayerPr.ABSENT,
        membership=train.LayerMembership.NOT_APPLICABLE,
        parent_checkpoint_sha=None,
        published_head_sha=None,
        observed_remote_head_sha=None,
        observed_pr_base=None,
    )
    return nodes, replace(
        _train(layers=(bottom, top)),
        build_readiness=train.BuildReadiness(next_node_id="1.2", ready=True, reason=None),
        objective_nodes=nodes,
    )


def test_planning_gate_no_candidate_arm(monkeypatch):
    result, _ = _invoke(
        ["objective", "stack", "status", "1431", "--json"],
        monkeypatch=monkeypatch,
        result=_train(),
    )
    payload = json.loads(result.stdout)
    assert payload["train"]["planning_gate"] == {"node_id": None, "ready": False, "blockers": []}
    # LayerOut is unchanged: the internal stamped head never reaches the per-layer envelope.
    layer = payload["train"]["layers"][0]
    assert "stamped_head_sha" not in layer and "stamped_head" not in layer


def test_planning_gate_handoff_arm_and_human_line(monkeypatch):
    _nodes, world = _gated_world()
    result, _ = _invoke(
        ["objective", "stack", "status", "1431", "--json"],
        monkeypatch=monkeypatch,
        result=world,
    )
    payload = json.loads(result.stdout)
    gate = payload["train"]["planning_gate"]
    assert gate["node_id"] == "1.2" and gate["ready"] is False
    (row,) = gate["blockers"]
    assert row["kind"] == "handoff" and row["dependency_node_id"] == "1.1"
    assert row["plan"] == "1457" and row["pr"] == 1465
    assert row["handoff_state"] == "unstamped" and row["remediation"] == "perk ready 1457"
    human, _ = _invoke(
        ["objective", "stack", "status", "1431"], monkeypatch=monkeypatch, result=world
    )
    assert "next build-ready: 1.2" in human.stderr
    assert (
        "planning gated: 1.2 waits on 1.1 (plan #1457, PR #1465) — unstamped; "
        "record the handoff: perk ready 1457"
    ) in human.stderr


def test_planning_gate_stale_human_line_names_the_head_mismatch(monkeypatch):
    _nodes, world = _gated_world()
    stale = replace(
        world,
        layers=(
            replace(
                world.layers[0],
                handoff=train.LayerHandoff.STALE,
                stamped_head_sha="s" * 40,
                observed_remote_head_sha="d" * 40,
            ),
            world.layers[1],
        ),
    )
    human, _ = _invoke(
        ["objective", "stack", "status", "1431"], monkeypatch=monkeypatch, result=stale
    )
    assert (
        f"planning gated: 1.2 waits on 1.1 (plan #1457, PR #1465) — stale; "
        f"stamped {'s' * 12} ≠ head {'d' * 12}; record the handoff: perk ready 1457"
    ) in human.stderr


def test_planning_gate_ready_arm(monkeypatch):
    _nodes, world = _gated_world()
    stamped = replace(
        world,
        layers=(
            replace(
                world.layers[0],
                handoff=train.LayerHandoff.READY,
                stamped_head_sha="b" * 40,
            ),
            world.layers[1],
        ),
    )
    result, _ = _invoke(
        ["objective", "stack", "status", "1431", "--json"],
        monkeypatch=monkeypatch,
        result=stamped,
    )
    payload = json.loads(result.stdout)
    assert payload["train"]["planning_gate"] == {
        "node_id": "1.2",
        "ready": True,
        "blockers": [],
    }
    human, _ = _invoke(
        ["objective", "stack", "status", "1431"], monkeypatch=monkeypatch, result=stamped
    )
    assert "planning gated" not in human.stderr


def test_planning_gate_technical_arm(monkeypatch):
    finding = train.TrainFinding(
        kind=train.FindingKind.BLOCKER, code="checkpoint_drift", message="moved"
    )
    _nodes, world = _gated_world()
    vetoed = replace(
        world,
        findings=(finding,),
        build_readiness=train.BuildReadiness(
            next_node_id="1.2", ready=False, reason="the train has blocker findings"
        ),
    )
    result, _ = _invoke(
        ["objective", "stack", "status", "1431", "--json"],
        monkeypatch=monkeypatch,
        result=vetoed,
    )
    gate = json.loads(result.stdout)["train"]["planning_gate"]
    assert gate["ready"] is False
    (row,) = gate["blockers"]
    assert row["kind"] == "technical" and row["code"] == "checkpoint_drift"
    assert row["remediation"] == "perk objective stack status 1431"
    human, _ = _invoke(
        ["objective", "stack", "status", "1431"], monkeypatch=monkeypatch, result=vetoed
    )
    assert "planning gated" not in human.stderr  # only handoff rows render the gated line


def test_planning_gate_defensive_dependency_not_ready_arm(monkeypatch):
    _nodes, world = _gated_world()
    # Drop the dep's layer entirely: the layerless non-terminal dep fails closed as the
    # gate-owned dependency_not_ready technical row.
    depless = replace(world, layers=(world.layers[1],))
    result, _ = _invoke(
        ["objective", "stack", "status", "1431", "--json"],
        monkeypatch=monkeypatch,
        result=depless,
    )
    gate = json.loads(result.stdout)["train"]["planning_gate"]
    assert gate["ready"] is False
    (row,) = gate["blockers"]
    assert row["kind"] == "technical" and row["code"] == "dependency_not_ready"
    assert row["message"].startswith("1.1: ")
    assert row["remediation"] == "perk objective stack status 1431"
