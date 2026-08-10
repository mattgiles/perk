"""Tests for ``perk objective stack status`` (``commands/objective/stack/status_cmd.py``).

CLI-level via ``CliRunner`` over the full ``cli`` in an isolated repo, with the reconstruction
seam (``train.reconstruct_train``) monkeypatched — the projection itself is pinned in
``test_delivery_train.py``; here the envelope, resolution order, exit codes, and the
stdout/stderr split are the contract.
"""

import json
import subprocess

from click.testing import CliRunner

from perk import plan
from perk.cli.cli import cli
from perk.delivery import train
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


def _invoke(args, *, monkeypatch, result=None, git_init=True):
    """Invoke the CLI in an isolated repo with ``reconstruct_train`` returning (or raising)
    ``result``; records the objective id the reconstruction was asked for."""
    asked: list[str] = []

    def fake_reconstruct(objective_id, **_kwargs):
        asked.append(objective_id)
        if isinstance(result, Exception):
            raise result
        assert result is not None, "reconstruct_train must not be reached"
        return result

    monkeypatch.setattr(train, "reconstruct_train", fake_reconstruct)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        if git_init:
            subprocess.run(["git", "init", "-q"], cwd=d, check=True)
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
    assert set(payload) == {"success", "error_type", "objective", "delivery", "train", "no_train"}
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
    }
    assert body["published_prefix_len"] == 1
    assert body["next_build_ready"] == {
        "node_id": None,
        "ready": False,
        "reason": "all layers published",
    }
    layer = body["layers"][0]
    assert layer["node_id"] == "1.2" and layer["pr_number"] == 1465
    assert layer["publication"] == "published" and layer["membership"] == "exact"


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
    error = train.TrainReconstructionError(
        "no canonical delivery order exists: cycle", error_type="invalid_train"
    )
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
