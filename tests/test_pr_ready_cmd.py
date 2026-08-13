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


# --- explicit PLAN selection (canonical, worktree-independent) -------------------------------


def test_pr_ready_explicit_plan_from_root_is_a_single_read(monkeypatch):
    # `perk pr ready 7` works from the repository root: no worktree, no cache.plan-ref. The
    # selection's ONE canonical read replaces the command's own plan re-read (the pinned
    # narrowed-read contract).
    _authed(monkeypatch)
    reads: list[dict] = []

    def _get_plan(**kwargs):
        reads.append(kwargs)
        return plans.PlanState(number=7, url="u/7", title="Plan", header={}, pr=None)

    monkeypatch.setattr(plans, "get_plan", _get_plan)
    branches: list[str] = []

    def _find(**k):
        branches.append(k["branch"])
        return github.PullRequest(
            number=42, url="u/pr/42", is_draft=True, state="OPEN", existed=True
        )

    monkeypatch.setattr(github, "find_pr_for_branch", _find)
    marked: list[int] = []
    monkeypatch.setattr(github, "mark_pr_ready", lambda **k: marked.append(k["number"]))
    result = _run(monkeypatch, ["pr", "ready", "7", "--json"], write_ref=False)
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["success"] is True and data["was_draft"] is True
    assert len(reads) == 1  # exactly ONE plan read for the incremental explicit-id path
    assert branches == ["plan-7"]
    assert marked == [42]


def test_pr_ready_explicit_plan_beats_conflicting_root_selector(monkeypatch):
    # An explicit PLAN is canonical authority: an unrelated root selector neither competes nor
    # gets overwritten (ready is not a launcher — it never writes the selector).
    _authed(monkeypatch)
    _stub_plan(monkeypatch)
    branches: list[str] = []

    def _find(**k):
        branches.append(k["branch"])
        return github.PullRequest(
            number=42, url="u/pr/42", is_draft=False, state="OPEN", existed=True
        )

    monkeypatch.setattr(github, "find_pr_for_branch", _find)
    monkeypatch.setattr(github, "mark_pr_ready", lambda **k: None)
    stale = plan.PlanRef(
        provider="github", pr_id="9", url="https://gh/o/r/issues/9", labels=("perk:plan",)
    )
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), stale)
        result = runner.invoke(cli, ["pr", "ready", "7", "--json"])
        assert result.exit_code == 0, result.output
        assert branches == ["plan-7"]  # acted on the explicit plan, not the selector
        assert cache.read_plan_ref(Path(d)) == stale  # the root selector is untouched


def test_pr_ready_explicit_stacked_plan_from_root(monkeypatch):
    # The stacked path keeps its train-reconstruction reads unchanged; explicit selection only
    # replaces the command's own plan read.
    _authed(monkeypatch)
    calls = _stub_stacked(monkeypatch, train=_stacked_train(), is_draft=True)
    result = _run(monkeypatch, ["pr", "ready", "7", "--json"], write_ref=False)
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["pr"] == {"number": 42, "url": "u/pr/42"}
    assert calls == {"marked": True, "get_pr": 42}


def test_pr_ready_explicit_plan_not_found(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(plans, "get_plan", lambda **k: None)
    result = _run(monkeypatch, ["pr", "ready", "999", "--json"], write_ref=False)
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "plan_not_found"


def test_pr_ready_explicit_plan_invalid_id_rejected_even_on_dry_run(monkeypatch):
    # The selector is parse-validated before any backend read — including on --dry-run.
    result = _run(monkeypatch, ["pr", "ready", "a/b", "--dry-run", "--json"], write_ref=False)
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "invalid_input"


def test_pr_ready_explicit_plan_dry_run_needs_no_cache(monkeypatch):
    # A parse-valid explicit PLAN dry-runs offline without requiring a saved plan-ref.
    result = _run(monkeypatch, ["pr", "ready", "7", "--dry-run", "--json"], write_ref=False)
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["success"] is True and data["dry_run"] is True


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


def test_pr_ready_no_arg_inside_linked_worktree_reads_its_own_binding(git_repo, monkeypatch):
    # The retained no-argument form reads the INVOCATION checkout's binding: inside a plan
    # worktree that is the worktree's own plan, even when the main-checkout selector conflicts.
    from perk.cli.context import PerkContext
    from perk.substrate import git as git_mod

    _authed(monkeypatch)
    _stub_plan(monkeypatch)
    branches: list[str] = []

    def _find(**k):
        branches.append(k["branch"])
        return github.PullRequest(
            number=42, url="u/pr/42", is_draft=False, state="OPEN", existed=True
        )

    monkeypatch.setattr(github, "find_pr_for_branch", _find)
    monkeypatch.setattr(github, "mark_pr_ready", lambda **k: None)
    wt = git_repo / ".worktrees" / "plan-7"
    git_mod.worktree_add(git_repo, wt, branch="plan-7", create_branch=True)
    cache.write_plan_ref(wt, _REF)  # the worktree's own plan (#7)
    cache.write_plan_ref(  # a CONFLICTING main-checkout selector (#9) that must not leak in
        git_repo,
        plan.PlanRef(provider="github", pr_id="9", url="u/9", labels=("perk:plan",)),
    )
    ctx = PerkContext.for_test(cwd=wt, repo_root=wt)
    result = CliRunner().invoke(cli, ["pr", "ready", "--json"], obj=ctx)
    assert result.exit_code == 0, result.output
    assert branches == ["plan-7"]  # the invocation worktree's binding, not the main selector
