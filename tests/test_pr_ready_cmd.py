import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from perk import delivery, github, plan
from perk.backends.github import plans
from perk.backends.issue_backend import IssueBackendError
from perk.backends.objective_store import ObjectiveStoreError
from perk.cli.cli import cli
from perk.delivery import train as train_mod
from perk.delivery._fakes import FakeDeliveryGit, FakeDeliveryGitHub, FakeDeliveryPersistence
from perk.delivery.journal import JournalCorruptionError, JournalRecordTooLarge
from perk.delivery.persistence import (
    JournalAppendAmbiguous,
    StampAppendResult,
    TrainPersistenceError,
)
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
# Valid 40-hex heads: the stacked ready arm constructs a ReadyStampRecord from the projection,
# so every stacked fixture must carry a real object-id shape.
_PARENT_SHA = "a" * 40
_HEAD_SHA = "b" * 40
_STAMP_KEY = f"500:7:1.1:{_HEAD_SHA}"


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
            number=7, url="u/7", title="Plan", header=header or {}, pr=None, has_plan_header=True
        ),
    )


def _bind_ready_delivery(
    monkeypatch,
    *,
    branch_pr: github.PullRequest | None = None,
    numbered_pr: github.PullRequest | None = None,
    train: train_mod.DeliveryTrain | None = None,
    errors: dict[tuple[object, ...], Exception] | None = None,
    persistence: FakeDeliveryPersistence | None = None,
) -> tuple[FakeDeliveryGitHub, list[delivery.PublishRequest]]:
    authority = FakeDeliveryGitHub(
        branch_prs={"plan-7": branch_pr} if branch_pr is not None else {},
        pull_requests={42: numbered_pr} if numbered_pr is not None else {},
        errors=errors,
    )
    requests: list[delivery.PublishRequest] = []

    class _ReadyDelivery(delivery.Delivery):
        def status(self, request: delivery.StatusRequest) -> delivery.StatusResult:
            if train is None:
                raise AssertionError("incremental ready unexpectedly reconstructed a train")
            return delivery.StatusResult(
                train.objective_id,
                train.objective_url,
                train.redirected_from,
                train,
                None,
            )

        def publish(self, request: delivery.PublishRequest) -> delivery.PublishResult:
            requests.append(request)
            return super().publish(request)

    service = _ReadyDelivery(
        persistence=persistence if persistence is not None else FakeDeliveryPersistence(),
        git=FakeDeliveryGit(),
        github=authority,
    )
    monkeypatch.setattr(delivery, "resolve_delivery", lambda _root: service)
    return authority, requests


def _stub_pr(
    monkeypatch, *, is_draft: bool, state: str = "OPEN"
) -> tuple[FakeDeliveryGitHub, list[delivery.PublishRequest]]:
    _stub_plan(monkeypatch)
    pr = github.PullRequest(number=42, url="u/pr/42", is_draft=is_draft, state=state, existed=True)
    return _bind_ready_delivery(monkeypatch, branch_pr=pr)


def _run(monkeypatch, args, *, write_ref=True, ref: plan.PlanRef = _REF):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        if write_ref:
            cache.write_plan_ref(Path(d), ref)
        return runner.invoke(cli, args)


def test_pr_ready_marks_draft(monkeypatch):
    _authed(monkeypatch)
    persistence = FakeDeliveryPersistence()
    _stub_plan(monkeypatch)
    pr = github.PullRequest(number=42, url="u/pr/42", is_draft=True, state="OPEN", existed=True)
    authority, requests = _bind_ready_delivery(monkeypatch, branch_pr=pr, persistence=persistence)
    result = _run(monkeypatch, ["pr", "ready", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["success"] is True and data["was_draft"] is True
    # Incremental untouched: no stamp mechanics, and the continuation facts are honest —
    # stacked=false, everything else null.
    assert data["stacked"] is False
    assert (
        data["objective"]
        is data["node"]
        is data["stamped_head"]
        is data["stamp_advanced"]
        is data["reconcile_notice"]
        is data["reconcile_retry"]
        is None
    )
    assert not [call for call in persistence.calls if call[0] == "append_ready_stamp"]
    assert authority.calls == [("pr_for_branch", "plan-7"), ("mark_pr_ready", 42)]
    assert requests == [delivery.PublishRequest(kind="ready", plan_id="7", delivery="incremental")]


def test_pr_ready_idempotent_already_ready(monkeypatch):
    _authed(monkeypatch)
    authority, requests = _stub_pr(monkeypatch, is_draft=False)
    result = _run(monkeypatch, ["pr", "ready", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["success"] is True and data["was_draft"] is False
    assert authority.calls == [("pr_for_branch", "plan-7")]
    assert requests == [delivery.PublishRequest(kind="ready", plan_id="7", delivery="incremental")]


@pytest.mark.parametrize("state", ["OPEN", "CLOSED", "MERGED"])
@pytest.mark.parametrize("is_draft", [True, False])
def test_incremental_ready_preserves_all_state_compatibility(monkeypatch, state, is_draft):
    _authed(monkeypatch)
    authority, _requests = _stub_pr(monkeypatch, is_draft=is_draft, state=state)

    result = _run(monkeypatch, ["pr", "ready", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["was_draft"] is is_draft
    expected: list[tuple[object, ...]] = [("pr_for_branch", "plan-7")]
    if is_draft:
        expected.append(("mark_pr_ready", 42))
    assert authority.calls == expected


def test_pr_ready_no_pr_exits_1(monkeypatch):
    _authed(monkeypatch)
    _stub_plan(monkeypatch)
    authority, _requests = _bind_ready_delivery(monkeypatch)
    result = _run(monkeypatch, ["pr", "ready", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "no_pr"
    assert authority.calls == [("pr_for_branch", "plan-7")]


def test_incremental_ready_gateway_failure_uses_ready_prefix(monkeypatch):
    _authed(monkeypatch)
    _stub_plan(monkeypatch)
    pr = github.PullRequest(number=42, url="u/pr/42", is_draft=True, state="CLOSED", existed=True)
    _bind_ready_delivery(
        monkeypatch,
        branch_pr=pr,
        errors={("mark_pr_ready", 42): github.GitHubError("cannot mark closed PR")},
    )

    result = _run(monkeypatch, ["pr", "ready", "--json"])

    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["error_type"] == "github_error"
    assert data["message"] == "pr ready failed\ncannot mark closed PR"


def _stacked_train(
    *,
    publication: train_mod.LayerPublication = train_mod.LayerPublication.PUBLISHED,
    findings: tuple[train_mod.TrainFinding, ...] = (),
    unresolved: tuple[train_mod.UnresolvedOperationFacts, ...] = (),
    delivery_lineage: str | None = "01LINEAGE",
) -> train_mod.DeliveryTrain:
    layer = train_mod.TrainLayer(
        node_id="1.1",
        plan_id="7",
        branch="plan-7",
        pr_number=42,
        intent=train_mod.LayerIntent.PLANNED,
        publication=publication,
        git=(
            train_mod.LayerGit.SYNCED
            if publication is train_mod.LayerPublication.PUBLISHED
            else train_mod.LayerGit.REMOTE_AHEAD
        ),
        pr=train_mod.LayerPr.DRAFT,
        membership=train_mod.LayerMembership.NOT_APPLICABLE,
        writer=train_mod.LayerWriter.FREE,
        finalization=train_mod.LayerFinalization.NOT_MERGED,
        parent_checkpoint_sha=_PARENT_SHA,
        published_head_sha=_HEAD_SHA,
        observed_remote_head_sha=_HEAD_SHA,
        observed_pr_base="main",
        expected_pr_base="main",
    )
    return train_mod.DeliveryTrain(
        objective_id="500",
        objective_url="u/objective/500",
        delivery_lineage=delivery_lineage,
        base="main",
        redirected_from=None,
        layers=(layer,),
        published_prefix_len=1 if publication is train_mod.LayerPublication.PUBLISHED else 0,
        unresolved_operation=unresolved[0] if unresolved else None,
        findings=findings,
        build_readiness=train_mod.BuildReadiness(
            next_node_id=None, ready=False, reason="all layers published"
        ),
        unresolved_operations=unresolved,
    )


def _stub_stacked(
    monkeypatch,
    *,
    train: train_mod.DeliveryTrain,
    is_draft: bool,
    pr_exists: bool = True,
    pr_state: str = "OPEN",
    errors: dict[tuple[object, ...], Exception] | None = None,
    persistence: FakeDeliveryPersistence | None = None,
) -> tuple[FakeDeliveryGitHub, list[delivery.PublishRequest]]:
    _stub_plan(
        monkeypatch,
        {"delivery_lineage": "01LINEAGE", "objective_id": "500"},
    )
    pr = (
        github.PullRequest(
            number=42,
            url="u/pr/42",
            is_draft=is_draft,
            state=pr_state,
            existed=True,
        )
        if pr_exists
        else None
    )
    return _bind_ready_delivery(
        monkeypatch, numbered_pr=pr, train=train, errors=errors, persistence=persistence
    )


def test_stacked_ready_fetches_published_pr_then_marks_then_stamps(monkeypatch):
    _authed(monkeypatch)
    persistence = FakeDeliveryPersistence()
    authority, requests = _stub_stacked(
        monkeypatch, train=_stacked_train(), is_draft=True, persistence=persistence
    )
    result = _run(monkeypatch, ["pr", "ready", "--json"], ref=_STACKED_REF)
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["pr"] == {"number": 42, "url": "u/pr/42"}
    assert data["was_draft"] is True
    assert data["stacked"] is True
    assert data["objective"] == "500" and data["node"] == "1.1"
    assert data["stamped_head"] == _HEAD_SHA
    assert data["stamp_advanced"] is True
    assert "not launched" in data["reconcile_notice"]
    assert data["reconcile_retry"] == "perk ready 7"
    assert authority.calls == [("get_pr", 42), ("mark_pr_ready", 42)]
    assert ("append_ready_stamp", "500", _STAMP_KEY) in persistence.calls
    assert requests == [
        delivery.PublishRequest(kind="ready", plan_id="7", delivery="stacked", objective_id="500")
    ]


def test_stacked_ready_existing_stamp_reports_not_advanced(monkeypatch):
    _authed(monkeypatch)
    persistence = FakeDeliveryPersistence(
        stamp_results={_STAMP_KEY: StampAppendResult(key=_STAMP_KEY, existed=True)}
    )
    _authority, _requests = _stub_stacked(
        monkeypatch, train=_stacked_train(), is_draft=True, persistence=persistence
    )
    result = _run(monkeypatch, ["pr", "ready", "--json"], ref=_STACKED_REF)
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["stamp_advanced"] is False
    assert data["stamped_head"] == _HEAD_SHA


@pytest.mark.parametrize(
    ("boom", "fragment", "claims_rerun_convergence"),
    [
        (
            JournalAppendAmbiguous("append of ready-stamp is unverifiable"),
            "converges via the deterministic event key",
            True,
        ),
        (
            JournalCorruptionError("conflicting duplicate under the key"),
            "re-running will NOT converge",
            False,
        ),
        (
            JournalRecordTooLarge("rendered journal event is 70000 chars"),
            "oversize",
            False,
        ),
        (
            TrainPersistenceError("objective 500 stores delivery_lineage '01OTHER'"),
            "identity/lineage mismatch",
            False,
        ),
        (IssueBackendError("backend down"), "re-run to retry", True),
        (ObjectiveStoreError("store unavailable"), "re-run to retry", True),
    ],
)
def test_stacked_ready_append_failure_matrix(monkeypatch, boom, fragment, claims_rerun_convergence):
    # The stamp append exception matrix (contracts.md §8.43): every arm is ready_stamp_failed
    # with the truthful PR facts, mark-first ordering holds (the append failure surfaces AFTER
    # the flip), and only the ambiguous/transient causes claim the converging re-run —
    # JournalAppendAmbiguous must keep its own arm despite being a TrainPersistenceError
    # subclass (catch-order regression guard).
    _authed(monkeypatch)
    persistence = FakeDeliveryPersistence(errors={("append_ready_stamp", "500", _STAMP_KEY): boom})
    authority, _requests = _stub_stacked(
        monkeypatch, train=_stacked_train(), is_draft=True, persistence=persistence
    )
    result = _run(monkeypatch, ["pr", "ready", "--json"], ref=_STACKED_REF)
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["error_type"] == "ready_stamp_failed"
    assert data["pr"] == {"number": 42, "url": "u/pr/42"}
    assert data["was_draft"] is True
    assert data["dry_run"] is False
    assert fragment in data["message"]
    # Only the ambiguous/transient arms may claim the converging/retrying re-run.
    if not claims_rerun_convergence:
        assert "re-run to retry" not in data["message"]
        assert "converges via the deterministic event key" not in data["message"]
    # Mark-first ordering: the flip happened before the failed append.
    assert authority.calls == [("get_pr", 42), ("mark_pr_ready", 42)]


def test_stacked_ready_mark_failure_never_appends(monkeypatch):
    _authed(monkeypatch)
    persistence = FakeDeliveryPersistence()
    _authority, _requests = _stub_stacked(
        monkeypatch,
        train=_stacked_train(),
        is_draft=True,
        errors={("mark_pr_ready", 42): github.GitHubError("cannot mark")},
        persistence=persistence,
    )
    result = _run(monkeypatch, ["pr", "ready", "--json"], ref=_STACKED_REF)
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "github_error"
    assert not [call for call in persistence.calls if call[0] == "append_ready_stamp"]


@pytest.mark.parametrize(
    ("lineage", "fragment"),
    [
        # No stored lineage: refused before ReadyStampRecord construction is even attempted.
        (None, "stores no delivery_lineage"),
        # A marker-unsafe stored segment: ReadyStampRecord construction raises ValueError and
        # the translation names the nonconforming id (no convergence-on-re-run claim).
        ("01 LINEAGE!", "cannot carry a handoff stamp"),
    ],
)
def test_stacked_ready_unconstructable_stamp_refuses_pre_mutation(monkeypatch, lineage, fragment):
    # The pre-mutation construction refusal: an unconstructable stamp refuses the WHOLE
    # gesture before any mutation — the PR is never flipped and nothing is appended.
    _authed(monkeypatch)
    persistence = FakeDeliveryPersistence()
    authority, _requests = _stub_stacked(
        monkeypatch,
        train=_stacked_train(delivery_lineage=lineage),
        is_draft=True,
        persistence=persistence,
    )
    result = _run(monkeypatch, ["pr", "ready", "--json"], ref=_STACKED_REF)
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["error_type"] == "ready_stamp_failed"
    assert fragment in data["message"]
    assert data["pr"] == {"number": 42, "url": "u/pr/42"}
    assert data["was_draft"] is True
    assert authority.calls == [("get_pr", 42)]
    assert not [call for call in persistence.calls if call[0] == "append_ready_stamp"]


def test_stacked_already_ready_validates_target_but_ignores_global_vetoes(monkeypatch):
    # The stamp append sits outside the one-unresolved-operation gate (§8.43): a non-draft PR
    # stamps even while an operation is unresolved — the suspended→resume and failed-append
    # re-run paths stay convergent.
    _authed(monkeypatch)
    operation = train_mod.UnresolvedOperationFacts("01OP", "sync", "t0")
    finding = train_mod.TrainFinding(
        kind=train_mod.FindingKind.BLOCKER,
        code="missing_lineage",
        message="lineage absent",
    )
    train = _stacked_train(findings=(finding,), unresolved=(operation,))
    persistence = FakeDeliveryPersistence()
    authority, _requests = _stub_stacked(
        monkeypatch, train=train, is_draft=False, persistence=persistence
    )
    result = _run(monkeypatch, ["pr", "ready", "--json"], ref=_STACKED_REF)
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["was_draft"] is False
    assert data["stacked"] is True and data["stamp_advanced"] is True
    assert authority.calls == [("get_pr", 42)]
    assert ("append_ready_stamp", "500", _STAMP_KEY) in persistence.calls


def test_stacked_ready_missing_pr_is_no_pr(monkeypatch):
    _authed(monkeypatch)
    authority, _requests = _stub_stacked(
        monkeypatch, train=_stacked_train(), is_draft=True, pr_exists=False
    )
    result = _run(monkeypatch, ["pr", "ready", "--json"], ref=_STACKED_REF)
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "no_pr"
    assert authority.calls == [("get_pr", 42)]


def test_stacked_ready_rejects_freshly_closed_pr(monkeypatch):
    _authed(monkeypatch)
    authority, _requests = _stub_stacked(
        monkeypatch,
        train=_stacked_train(),
        is_draft=False,
        pr_state="CLOSED",
    )
    result = _run(monkeypatch, ["pr", "ready", "--json"], ref=_STACKED_REF)
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "pr_not_open"
    assert authority.calls == [("get_pr", 42)]


def test_stacked_ready_target_drift_is_layer_not_published(monkeypatch):
    _authed(monkeypatch)
    finding = train_mod.TrainFinding(
        kind=train_mod.FindingKind.BLOCKER,
        code="checkpoint_drift",
        message="expected h, observed x",
        node_id="1.1",
        plan_id="7",
    )
    train = _stacked_train(
        publication=train_mod.LayerPublication.PUBLICATION_DRIFT,
        findings=(finding,),
    )
    authority, _requests = _stub_stacked(monkeypatch, train=train, is_draft=True)
    result = _run(monkeypatch, ["pr", "ready", "--json"], ref=_STACKED_REF)
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["error_type"] == "layer_not_published"
    assert "[checkpoint_drift] expected h, observed x" in data["message"]
    assert authority.calls == [("get_pr", 42)]


@pytest.mark.parametrize("pr_state", ["CLOSED", "MERGED"])
def test_stacked_ready_projected_non_open_keeps_layer_not_published(monkeypatch, pr_state):
    _authed(monkeypatch)
    train = _stacked_train(publication=train_mod.LayerPublication.PUBLICATION_DRIFT)
    authority, _requests = _stub_stacked(
        monkeypatch,
        train=train,
        is_draft=False,
        pr_state=pr_state,
    )
    result = _run(monkeypatch, ["pr", "ready", "--json"], ref=_STACKED_REF)
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "layer_not_published"
    assert authority.calls == [("get_pr", 42)]


def test_stacked_already_ready_target_drift_is_layer_not_published(monkeypatch):
    _authed(monkeypatch)
    finding = train_mod.TrainFinding(
        kind=train_mod.FindingKind.BLOCKER,
        code="checkpoint_drift",
        message="expected h, observed x",
        node_id="1.1",
        plan_id="7",
    )
    train = _stacked_train(
        publication=train_mod.LayerPublication.PUBLICATION_DRIFT,
        findings=(finding,),
    )
    authority, _requests = _stub_stacked(monkeypatch, train=train, is_draft=False)
    result = _run(monkeypatch, ["pr", "ready", "--json"], ref=_STACKED_REF)
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "layer_not_published"
    assert authority.calls == [("get_pr", 42)]


def test_stacked_ready_draft_refuses_unresolved_operation(monkeypatch):
    _authed(monkeypatch)
    operation = train_mod.UnresolvedOperationFacts("01OP", "sync", "t0")
    persistence = FakeDeliveryPersistence()
    authority, _requests = _stub_stacked(
        monkeypatch,
        train=_stacked_train(unresolved=(operation,)),
        is_draft=True,
        persistence=persistence,
    )
    result = _run(monkeypatch, ["pr", "ready", "--json"], ref=_STACKED_REF)
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "unresolved_operation"
    assert authority.calls == [("get_pr", 42)]
    assert not [call for call in persistence.calls if call[0] == "append_ready_stamp"]


def test_stacked_ready_draft_refuses_structural_blocker(monkeypatch):
    _authed(monkeypatch)
    finding = train_mod.TrainFinding(
        kind=train_mod.FindingKind.BLOCKER,
        code="missing_lineage",
        message="lineage absent",
    )
    authority, _requests = _stub_stacked(
        monkeypatch,
        train=_stacked_train(findings=(finding,)),
        is_draft=True,
    )
    result = _run(monkeypatch, ["pr", "ready", "--json"], ref=_STACKED_REF)
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "structural_blockers"
    assert authority.calls == [("get_pr", 42)]


def test_ready_header_lineage_wins_over_stale_ref(monkeypatch):
    _authed(monkeypatch)
    authority, requests = _stub_stacked(monkeypatch, train=_stacked_train(), is_draft=True)
    result = _run(monkeypatch, ["pr", "ready", "--json"], ref=_REF)
    assert result.exit_code == 0, result.output
    assert authority.calls == [("get_pr", 42), ("mark_pr_ready", 42)]
    assert requests == [
        delivery.PublishRequest(kind="ready", plan_id="7", delivery="stacked", objective_id="500")
    ]


# --- explicit PLAN selection (canonical, worktree-independent) -------------------------------


def test_pr_ready_explicit_plan_from_root_is_a_single_read(monkeypatch):
    # `perk pr ready 7` works from the repository root: no worktree, no cache.plan-ref. The
    # selection's ONE canonical read replaces the command's own plan re-read (the pinned
    # narrowed-read contract).
    _authed(monkeypatch)
    reads: list[dict] = []

    def _get_plan(**kwargs):
        reads.append(kwargs)
        return plans.PlanState(
            number=7, url="u/7", title="Plan", header={}, pr=None, has_plan_header=True
        )

    monkeypatch.setattr(plans, "get_plan", _get_plan)
    pr = github.PullRequest(number=42, url="u/pr/42", is_draft=True, state="OPEN", existed=True)
    authority, requests = _bind_ready_delivery(monkeypatch, branch_pr=pr)

    result = _run(monkeypatch, ["pr", "ready", "7", "--json"], write_ref=False)

    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["success"] is True and data["was_draft"] is True
    assert len(reads) == 1
    assert authority.calls == [("pr_for_branch", "plan-7"), ("mark_pr_ready", 42)]
    assert requests == [delivery.PublishRequest(kind="ready", plan_id="7", delivery="incremental")]


def test_pr_ready_explicit_plan_beats_conflicting_root_selector(monkeypatch):
    # An explicit PLAN is canonical authority: an unrelated root selector neither competes nor
    # gets overwritten (ready is not a launcher — it never writes the selector).
    _authed(monkeypatch)
    _stub_plan(monkeypatch)
    pr = github.PullRequest(number=42, url="u/pr/42", is_draft=False, state="OPEN", existed=True)
    authority, requests = _bind_ready_delivery(monkeypatch, branch_pr=pr)
    stale = plan.PlanRef(
        provider="github", pr_id="9", url="https://gh/o/r/issues/9", labels=("perk:plan",)
    )
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), stale)
        result = runner.invoke(cli, ["pr", "ready", "7", "--json"])
        assert result.exit_code == 0, result.output
        assert authority.calls == [("pr_for_branch", "plan-7")]
        assert requests == [
            delivery.PublishRequest(kind="ready", plan_id="7", delivery="incremental")
        ]
        assert cache.read_plan_ref(Path(d)) == stale


def test_pr_ready_explicit_stacked_plan_from_root(monkeypatch):
    # The stacked path keeps its train-reconstruction reads unchanged; explicit selection only
    # replaces the command's own plan read.
    _authed(monkeypatch)
    authority, requests = _stub_stacked(monkeypatch, train=_stacked_train(), is_draft=True)
    result = _run(monkeypatch, ["pr", "ready", "7", "--json"], write_ref=False)
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["pr"] == {"number": 42, "url": "u/pr/42"}
    assert authority.calls == [("get_pr", 42), ("mark_pr_ready", 42)]
    assert requests == [
        delivery.PublishRequest(kind="ready", plan_id="7", delivery="stacked", objective_id="500")
    ]


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
    authority, requests = _bind_ready_delivery(monkeypatch)

    result = _run(monkeypatch, ["pr", "ready", "#7", "--dry-run", "--json"], write_ref=False)

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["success"] is True and data["dry_run"] is True
    assert requests == [delivery.PublishRequest(kind="ready", plan_id="7", dry_run=True)]
    assert authority.calls == []


def test_pr_ready_dry_run_offline(monkeypatch):
    authority, requests = _bind_ready_delivery(monkeypatch)

    result = _run(monkeypatch, ["pr", "ready", "--dry-run", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["success"] is True and data["dry_run"] is True
    # The offline preview classifies nothing: all seven continuation fields are null.
    assert (
        data["stacked"]
        is data["objective"]
        is data["node"]
        is data["stamped_head"]
        is data["stamp_advanced"]
        is data["reconcile_notice"]
        is data["reconcile_retry"]
        is None
    )
    assert requests == [delivery.PublishRequest(kind="ready", plan_id="7", dry_run=True)]
    assert authority.calls == []


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
    pr = github.PullRequest(number=42, url="u/pr/42", is_draft=False, state="OPEN", existed=True)
    authority, requests = _bind_ready_delivery(monkeypatch, branch_pr=pr)
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
    assert authority.calls == [("pr_for_branch", "plan-7")]
    assert requests == [delivery.PublishRequest(kind="ready", plan_id="7", delivery="incremental")]
