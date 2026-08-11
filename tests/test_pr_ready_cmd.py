import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from perk import delivery, github, plan
from perk.backends.github import plans
from perk.cli.cli import cli
from perk.state import cache

_REF = plan.PlanRef(
    provider="github",
    pr_id="7",
    url="https://gh/o/r/issues/7",
    labels=("perk:plan",),
    objective_id=None,
)
_STACKED_REF = plan.PlanRef(
    provider="github",
    pr_id="7",
    url="https://gh/o/r/issues/7",
    labels=("perk:plan",),
    objective_id="500",
    delivery_lineage="01LINEAGE",
)


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _authed(monkeypatch) -> None:
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(True, "octocat", ("repo",), None)
    )


def _stub_plan(monkeypatch, header: dict[str, object] | None = None) -> None:
    monkeypatch.setattr(
        plans,
        "get_plan",
        lambda **kwargs: plans.PlanState(
            number=7, url="u/7", title="Plan", header=header or {}, pr=None
        ),
    )


def _stub_pr(monkeypatch, *, is_draft: bool) -> dict[str, object]:
    _stub_plan(monkeypatch)
    calls: dict[str, object] = {"marked": False}
    monkeypatch.setattr(
        github,
        "find_pr_for_branch",
        lambda **k: github.PullRequest(
            number=42, url="u/pr/42", is_draft=is_draft, state="OPEN", existed=True
        ),
    )

    def _mark(**k):
        calls["marked"] = True

    monkeypatch.setattr(github, "mark_pr_ready", _mark)
    return calls


def _run(monkeypatch, args, *, write_ref=True, ref: plan.PlanRef = _REF):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        if write_ref:
            cache.write_plan_ref(Path(d), ref)
        return runner.invoke(cli, args)


def test_pr_ready_marks_draft(monkeypatch):
    _authed(monkeypatch)
    calls = _stub_pr(monkeypatch, is_draft=True)
    result = _run(monkeypatch, ["pr", "ready", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["success"] is True and data["was_draft"] is True
    assert calls["marked"] is True


def test_pr_ready_idempotent_already_ready(monkeypatch):
    _authed(monkeypatch)
    calls = _stub_pr(monkeypatch, is_draft=False)
    result = _run(monkeypatch, ["pr", "ready", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["success"] is True and data["was_draft"] is False
    assert calls["marked"] is False  # already-ready never re-marks


def test_pr_ready_no_pr_exits_1(monkeypatch):
    _authed(monkeypatch)
    _stub_plan(monkeypatch)
    monkeypatch.setattr(github, "find_pr_for_branch", lambda **k: None)
    result = _run(monkeypatch, ["pr", "ready", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "no_pr"


def _stacked_train(
    *,
    publication: delivery.LayerPublication = delivery.LayerPublication.PUBLISHED,
    findings: tuple[delivery.TrainFinding, ...] = (),
    unresolved: tuple[delivery.UnresolvedOperationFacts, ...] = (),
) -> delivery.DeliveryTrain:
    layer = delivery.TrainLayer(
        node_id="1.1",
        plan_id="7",
        branch="plan-7",
        pr_number=42,
        intent=delivery.LayerIntent.PLANNED,
        publication=publication,
        git=(
            delivery.LayerGit.SYNCED
            if publication is delivery.LayerPublication.PUBLISHED
            else delivery.LayerGit.REMOTE_AHEAD
        ),
        pr=delivery.LayerPr.DRAFT,
        membership=delivery.LayerMembership.NOT_APPLICABLE,
        writer=delivery.LayerWriter.FREE,
        finalization=delivery.LayerFinalization.NOT_MERGED,
        parent_checkpoint_sha="p" * 40,
        published_head_sha="h" * 40,
        observed_remote_head_sha="h" * 40,
        observed_pr_base="main",
        expected_pr_base="main",
    )
    return delivery.DeliveryTrain(
        objective_id="500",
        objective_url="u/objective/500",
        delivery_lineage="01LINEAGE",
        base="main",
        redirected_from=None,
        layers=(layer,),
        published_prefix_len=1 if publication is delivery.LayerPublication.PUBLISHED else 0,
        unresolved_operation=unresolved[0] if unresolved else None,
        findings=findings,
        build_readiness=delivery.BuildReadiness(
            next_node_id=None, ready=False, reason="all layers published"
        ),
        unresolved_operations=unresolved,
    )


def _stub_stacked(
    monkeypatch,
    *,
    train: delivery.DeliveryTrain,
    is_draft: bool,
    pr_exists: bool = True,
    pr_state: str = "OPEN",
) -> dict[str, object]:
    _stub_plan(
        monkeypatch,
        {"delivery_lineage": "01LINEAGE", "objective_id": "500"},
    )
    calls: dict[str, object] = {"marked": False, "get_pr": None}
    monkeypatch.setattr(delivery, "reconstruct_repo_train", lambda root, objective_id: train)

    def get_pr(*, number, repo_root):
        calls["get_pr"] = number
        if not pr_exists:
            return None
        return github.PullRequest(
            number=number,
            url=f"u/pr/{number}",
            is_draft=is_draft,
            state=pr_state,
            existed=True,
        )

    monkeypatch.setattr(github, "get_pr", get_pr)
    monkeypatch.setattr(github, "mark_pr_ready", lambda **kwargs: calls.__setitem__("marked", True))
    monkeypatch.setattr(
        github,
        "find_pr_for_branch",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("incremental lookup used")),
    )
    return calls


def test_stacked_ready_fetches_published_pr_then_marks(monkeypatch):
    _authed(monkeypatch)
    calls = _stub_stacked(monkeypatch, train=_stacked_train(), is_draft=True)
    result = _run(monkeypatch, ["pr", "ready", "--json"], ref=_STACKED_REF)
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["pr"] == {"number": 42, "url": "u/pr/42"}
    assert data["was_draft"] is True
    assert calls == {"marked": True, "get_pr": 42}


def test_stacked_already_ready_validates_target_but_ignores_global_vetoes(monkeypatch):
    _authed(monkeypatch)
    operation = delivery.UnresolvedOperationFacts("01OP", "sync", "t0")
    finding = delivery.TrainFinding(
        kind=delivery.FindingKind.BLOCKER,
        code="missing_lineage",
        message="lineage absent",
    )
    train = _stacked_train(findings=(finding,), unresolved=(operation,))
    calls = _stub_stacked(monkeypatch, train=train, is_draft=False)
    result = _run(monkeypatch, ["pr", "ready", "--json"], ref=_STACKED_REF)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["was_draft"] is False
    assert calls["marked"] is False


def test_stacked_ready_missing_pr_is_no_pr(monkeypatch):
    _authed(monkeypatch)
    calls = _stub_stacked(monkeypatch, train=_stacked_train(), is_draft=True, pr_exists=False)
    result = _run(monkeypatch, ["pr", "ready", "--json"], ref=_STACKED_REF)
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "no_pr"
    assert calls["get_pr"] == 42 and calls["marked"] is False


def test_stacked_ready_rejects_freshly_closed_pr(monkeypatch):
    _authed(monkeypatch)
    calls = _stub_stacked(
        monkeypatch,
        train=_stacked_train(),
        is_draft=False,
        pr_state="CLOSED",
    )
    result = _run(monkeypatch, ["pr", "ready", "--json"], ref=_STACKED_REF)
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "pr_not_open"
    assert calls["get_pr"] == 42 and calls["marked"] is False


def test_stacked_ready_target_drift_is_layer_not_published(monkeypatch):
    _authed(monkeypatch)
    finding = delivery.TrainFinding(
        kind=delivery.FindingKind.BLOCKER,
        code="checkpoint_drift",
        message="expected h, observed x",
        node_id="1.1",
        plan_id="7",
    )
    train = _stacked_train(
        publication=delivery.LayerPublication.PUBLICATION_DRIFT,
        findings=(finding,),
    )
    calls = _stub_stacked(monkeypatch, train=train, is_draft=True)
    result = _run(monkeypatch, ["pr", "ready", "--json"], ref=_STACKED_REF)
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["error_type"] == "layer_not_published"
    assert "[checkpoint_drift] expected h, observed x" in data["message"]
    assert calls["get_pr"] == 42 and calls["marked"] is False


@pytest.mark.parametrize("pr_state", ["CLOSED", "MERGED"])
def test_stacked_ready_projected_non_open_keeps_layer_not_published(monkeypatch, pr_state):
    _authed(monkeypatch)
    train = _stacked_train(publication=delivery.LayerPublication.PUBLICATION_DRIFT)
    calls = _stub_stacked(
        monkeypatch,
        train=train,
        is_draft=False,
        pr_state=pr_state,
    )
    result = _run(monkeypatch, ["pr", "ready", "--json"], ref=_STACKED_REF)
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "layer_not_published"
    assert calls["get_pr"] == 42 and calls["marked"] is False


def test_stacked_already_ready_target_drift_is_layer_not_published(monkeypatch):
    _authed(monkeypatch)
    finding = delivery.TrainFinding(
        kind=delivery.FindingKind.BLOCKER,
        code="checkpoint_drift",
        message="expected h, observed x",
        node_id="1.1",
        plan_id="7",
    )
    train = _stacked_train(
        publication=delivery.LayerPublication.PUBLICATION_DRIFT,
        findings=(finding,),
    )
    calls = _stub_stacked(monkeypatch, train=train, is_draft=False)
    result = _run(monkeypatch, ["pr", "ready", "--json"], ref=_STACKED_REF)
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "layer_not_published"
    assert calls["get_pr"] == 42 and calls["marked"] is False


def test_stacked_ready_draft_refuses_unresolved_operation(monkeypatch):
    _authed(monkeypatch)
    operation = delivery.UnresolvedOperationFacts("01OP", "sync", "t0")
    calls = _stub_stacked(
        monkeypatch,
        train=_stacked_train(unresolved=(operation,)),
        is_draft=True,
    )
    result = _run(monkeypatch, ["pr", "ready", "--json"], ref=_STACKED_REF)
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "unresolved_operation"
    assert calls["marked"] is False


def test_stacked_ready_draft_refuses_structural_blocker(monkeypatch):
    _authed(monkeypatch)
    finding = delivery.TrainFinding(
        kind=delivery.FindingKind.BLOCKER,
        code="missing_lineage",
        message="lineage absent",
    )
    calls = _stub_stacked(
        monkeypatch,
        train=_stacked_train(findings=(finding,)),
        is_draft=True,
    )
    result = _run(monkeypatch, ["pr", "ready", "--json"], ref=_STACKED_REF)
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "structural_blockers"
    assert calls["marked"] is False


def test_ready_header_lineage_wins_over_stale_ref(monkeypatch):
    _authed(monkeypatch)
    calls = _stub_stacked(monkeypatch, train=_stacked_train(), is_draft=True)
    result = _run(monkeypatch, ["pr", "ready", "--json"], ref=_REF)
    assert result.exit_code == 0, result.output
    assert calls["get_pr"] == 42 and calls["marked"] is True


def test_pr_ready_dry_run_offline(monkeypatch):
    result = _run(monkeypatch, ["pr", "ready", "--dry-run", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["success"] is True and data["dry_run"] is True


def test_pr_ready_not_a_repo_exits_2(monkeypatch):
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["pr", "ready", "--json"])
    assert result.exit_code == 2
    assert json.loads(result.output)["error_type"] == "not_a_repo"
