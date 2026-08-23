"""Tests for the stacked-PR review resolution (`pr/review/stack_resolve.py`).

Wire-facts-only resolution over a fake gateway (non-identity ids — PR numbers never mirror
branch names) and a fake delivery façade: the chain walk with its full refusal matrix
(fork arms included), the objective arm's linkage checks, and the shared cardinality gates.
"""

from pathlib import Path

import pytest

from perk import github
from perk.cli.commands.pr.review import stack_resolve
from perk.cli.commands.pr.review.stack_resolve import (
    STACK_REVIEW_MAX_MEMBERS,
    resolve_stack_from_objective,
    resolve_stack_from_pr,
)
from perk.cli.ensure import UserFacingCliError
from perk.delivery import DeliveryError
from perk.delivery.facade import StatusResult
from perk.delivery.train import (
    BuildReadiness,
    DeliveryTrain,
    FindingKind,
    LayerFinalization,
    LayerGit,
    LayerIntent,
    LayerMembership,
    LayerPr,
    LayerPublication,
    LayerWriter,
    TrainFinding,
    TrainLayer,
)

ROOT = Path("/repo")
HOME = "me/repo"


def _pr(
    number: int,
    head: str,
    base: str,
    *,
    state: str = "OPEN",
    head_repo: str = HOME,
) -> github.PullRequest:
    return github.PullRequest(
        number=number,
        url=f"https://github.com/me/repo/pull/{number}",
        is_draft=False,
        state=state,
        existed=True,
        base_ref=base,
        head_ref=head,
        head_repo=head_repo,
    )


def _wire_gateway(monkeypatch, prs: list[github.PullRequest]) -> None:
    """Wire the three gateway reads the walks consume over an in-memory PR set."""
    by_number = {p.number: p for p in prs}

    def get_pr(*, number, repo_root):
        assert repo_root == ROOT
        return by_number.get(number)

    def find_pr_for_branch(*, branch, repo_root):
        assert repo_root == ROOT
        matching = [p for p in prs if p.head_ref == branch]
        if not matching:
            return None
        return next((p for p in matching if p.state == "OPEN"), matching[0])

    def list_open_prs_for_base(*, base, repo_root):
        assert repo_root == ROOT
        return tuple(p for p in prs if p.base_ref == base and p.state == "OPEN")

    monkeypatch.setattr(github, "get_pr", get_pr)
    monkeypatch.setattr(github, "find_pr_for_branch", find_pr_for_branch)
    monkeypatch.setattr(github, "list_open_prs_for_base", list_open_prs_for_base)
    monkeypatch.setattr(
        github,
        "repo_identity",
        lambda repo_root: github.RepoIdentity(
            name="repo", url="https://github.com/me/repo", default_branch="main"
        ),
    )


# --------------------------------------------------------------------- the chain walk


def test_chain_walk_from_middle_orders_bottom_to_top(monkeypatch):
    # Non-identity ids: numbers never mirror branch names or positions.
    _wire_gateway(
        monkeypatch,
        [
            _pr(402, "feat-a", "main"),
            _pr(87, "feat-b", "feat-a"),
            _pr(215, "feat-c", "feat-b"),
        ],
    )
    stack = resolve_stack_from_pr(ROOT, 87)
    assert [m.pr_number for m in stack.members] == [402, 87, 215]
    assert stack.base_ref == "main"
    assert stack.top.pr_number == 215
    assert stack.kind == "chain"
    assert stack.objective_id is None
    assert stack.notes == ()
    # Chain members carry no node/plan linkage and no recorded head.
    assert all(m.node_id is None and m.plan_id is None for m in stack.members)
    assert all(m.recorded_head_sha is None for m in stack.members)


def test_chain_walk_merged_lower_pr_ends_walk(monkeypatch):
    # The merged bottom PR is not a member — its head branch is where the walk stops, so the
    # bottom OPEN member's base is the stack base.
    _wire_gateway(
        monkeypatch,
        [
            _pr(11, "feat-a", "main", state="MERGED"),
            _pr(22, "feat-b", "feat-a"),
            _pr(33, "feat-c", "feat-b"),
        ],
    )
    stack = resolve_stack_from_pr(ROOT, 33)
    assert [m.pr_number for m in stack.members] == [22, 33]
    assert stack.base_ref == "feat-a"


def test_chain_walk_pr_not_found(monkeypatch):
    _wire_gateway(monkeypatch, [])
    with pytest.raises(UserFacingCliError) as exc:
        resolve_stack_from_pr(ROOT, 999)
    assert exc.value.error_type == "pr_not_found"


def test_chain_walk_pr_not_open(monkeypatch):
    _wire_gateway(monkeypatch, [_pr(5, "feat-a", "main", state="CLOSED")])
    with pytest.raises(UserFacingCliError) as exc:
        resolve_stack_from_pr(ROOT, 5)
    assert exc.value.error_type == "pr_not_open"


def test_chain_walk_initial_fork_refused(monkeypatch):
    _wire_gateway(monkeypatch, [_pr(5, "feat-a", "main", head_repo="forker/repo")])
    with pytest.raises(UserFacingCliError) as exc:
        resolve_stack_from_pr(ROOT, 5)
    assert exc.value.error_type == "fork_unsupported"


def test_chain_walk_blank_head_repo_fails_closed(monkeypatch):
    # An unavailable head-repository identity ("" — e.g. a deleted fork) is never same-repo.
    _wire_gateway(monkeypatch, [_pr(5, "feat-a", "main", head_repo="")])
    with pytest.raises(UserFacingCliError) as exc:
        resolve_stack_from_pr(ROOT, 5)
    assert exc.value.error_type == "fork_unsupported"


def test_chain_walk_upward_fork_candidate_never_matches(monkeypatch):
    # A fork child based on the top head does not extend the walk (and is not ambiguous
    # against the one same-repo child).
    _wire_gateway(
        monkeypatch,
        [
            _pr(1, "feat-a", "main"),
            _pr(2, "feat-b", "feat-a"),
            _pr(3, "feat-fork", "feat-b", head_repo="forker/repo"),
        ],
    )
    stack = resolve_stack_from_pr(ROOT, 1)
    assert [m.pr_number for m in stack.members] == [1, 2]


def test_chain_walk_downward_fork_ends_walk(monkeypatch):
    # A fork PR below never joins the chain — the walk stops above it.
    _wire_gateway(
        monkeypatch,
        [
            _pr(1, "feat-a", "main", head_repo="forker/repo"),
            _pr(2, "feat-b", "feat-a"),
            _pr(3, "feat-c", "feat-b"),
        ],
    )
    stack = resolve_stack_from_pr(ROOT, 3)
    assert [m.pr_number for m in stack.members] == [2, 3]
    assert stack.base_ref == "feat-a"


def test_chain_walk_ambiguous_up(monkeypatch):
    _wire_gateway(
        monkeypatch,
        [
            _pr(1, "feat-a", "main"),
            _pr(2, "feat-b", "feat-a"),
            _pr(3, "feat-c", "feat-a"),
        ],
    )
    with pytest.raises(UserFacingCliError) as exc:
        resolve_stack_from_pr(ROOT, 1)
    assert exc.value.error_type == "ambiguous_stack"
    assert "#2" in str(exc.value) and "#3" in str(exc.value)


def test_chain_walk_single_pr_is_not_a_stack(monkeypatch):
    _wire_gateway(monkeypatch, [_pr(7, "feat-a", "main")])
    with pytest.raises(UserFacingCliError) as exc:
        resolve_stack_from_pr(ROOT, 7)
    assert exc.value.error_type == "not_a_stack"
    assert "/pr-review-browser" in str(exc.value)


def test_chain_walk_too_deep(monkeypatch):
    count = STACK_REVIEW_MAX_MEMBERS + 1
    prs = [_pr(100 + i, f"feat-{i}", "main" if i == 0 else f"feat-{i - 1}") for i in range(count)]
    _wire_gateway(monkeypatch, prs)
    with pytest.raises(UserFacingCliError) as exc:
        resolve_stack_from_pr(ROOT, 100)
    assert exc.value.error_type == "stack_too_deep"


def test_chain_walk_base_ref_cycle_ends_walk(monkeypatch):
    # A degenerate base-ref cycle (A↔B) cannot loop forever — the seen-set ends the walk and
    # the two members still resolve.
    _wire_gateway(
        monkeypatch,
        [
            _pr(1, "feat-a", "feat-b"),
            _pr(2, "feat-b", "feat-a"),
        ],
    )
    stack = resolve_stack_from_pr(ROOT, 1)
    assert len(stack.members) == 2


# --------------------------------------------------------------------- the objective arm


def _layer(
    node_id: str,
    plan_id: str | None,
    branch: str | None,
    pr_number: int | None,
    *,
    published_head_sha: str | None = None,
) -> TrainLayer:
    return TrainLayer(
        node_id=node_id,
        plan_id=plan_id,
        branch=branch,
        pr_number=pr_number,
        intent=LayerIntent.PLANNED if plan_id is not None else LayerIntent.UNPLANNED,
        publication=LayerPublication.PUBLISHED,
        git=LayerGit.SYNCED,
        pr=LayerPr.DRAFT,
        membership=LayerMembership.NOT_APPLICABLE,
        writer=LayerWriter.FREE,
        finalization=LayerFinalization.NOT_MERGED,
        parent_checkpoint_sha=None,
        published_head_sha=published_head_sha,
        observed_remote_head_sha=None,
        observed_pr_base=None,
        expected_pr_base=None,
    )


def _train(
    layers: tuple[TrainLayer, ...],
    *,
    base: str = "main",
    findings: tuple[TrainFinding, ...] = (),
) -> DeliveryTrain:
    return DeliveryTrain(
        objective_id="77",
        objective_url="https://github.com/me/repo/issues/77",
        delivery_lineage="lineage-1",
        base=base,
        redirected_from=None,
        layers=layers,
        published_prefix_len=len(layers),
        unresolved_operation=None,
        findings=findings,
        build_readiness=BuildReadiness(next_node_id=None, ready=False, reason=None),
    )


class _FakeDelivery:
    def __init__(self, result: StatusResult | None, error: DeliveryError | None = None) -> None:
        self.result = result
        self.error = error
        self.requests: list[object] = []

    def status(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.result


def _wire_delivery(monkeypatch, delivery: _FakeDelivery) -> None:
    monkeypatch.setattr(stack_resolve, "resolve_delivery", lambda repo_root: delivery)


def _status(train: DeliveryTrain | None, *, no_train_reason: str | None = None) -> StatusResult:
    return StatusResult(
        objective_id="77",
        objective_url="https://github.com/me/repo/issues/77",
        redirected_from=None,
        train=train,
        no_train_reason=no_train_reason,
    )


def test_objective_arm_resolves_members_with_layer_linkage(monkeypatch):
    layers = (
        _layer("1.1", "301", "plan-301", 41, published_head_sha="a" * 40),
        _layer("1.2", "302", "plan-302", 52, published_head_sha="b" * 40),
    )
    _wire_delivery(monkeypatch, _FakeDelivery(_status(_train(layers))))
    _wire_gateway(
        monkeypatch,
        [
            _pr(41, "plan-301", "main"),
            _pr(52, "plan-302", "plan-301"),
        ],
    )
    stack = resolve_stack_from_objective(ROOT, "77")
    assert stack.kind == "objective"
    assert stack.objective_id == "77"
    assert [m.pr_number for m in stack.members] == [41, 52]
    assert [m.node_id for m in stack.members] == ["1.1", "1.2"]
    assert [m.plan_id for m in stack.members] == ["301", "302"]
    assert [m.recorded_head_sha for m in stack.members] == ["a" * 40, "b" * 40]
    assert stack.base_ref == "main"
    assert stack.notes == ()


def test_objective_arm_blockers_become_notes_and_proceed(monkeypatch):
    layers = (
        _layer("1.1", "301", "plan-301", 41),
        _layer("1.2", "302", "plan-302", 52),
    )
    findings = (
        TrainFinding(kind=FindingKind.BLOCKER, code="prefix_gap", message="gap detail"),
        TrainFinding(kind=FindingKind.INFO, code="informational", message="ignored"),
    )
    _wire_delivery(monkeypatch, _FakeDelivery(_status(_train(layers, findings=findings))))
    _wire_gateway(
        monkeypatch,
        [_pr(41, "plan-301", "main"), _pr(52, "plan-302", "plan-301")],
    )
    stack = resolve_stack_from_objective(ROOT, "77")
    assert stack.notes == ("[prefix_gap] gap detail",)


def test_objective_arm_not_stacked(monkeypatch):
    _wire_delivery(monkeypatch, _FakeDelivery(_status(None, no_train_reason="no delivery lineage")))
    with pytest.raises(UserFacingCliError) as exc:
        resolve_stack_from_objective(ROOT, "77")
    assert exc.value.error_type == "not_stacked"


def test_objective_arm_delivery_error_maps_to_typed_refusal(monkeypatch):
    _wire_delivery(
        monkeypatch,
        _FakeDelivery(None, error=DeliveryError("boom", error_type="objective_not_found")),
    )
    with pytest.raises(UserFacingCliError) as exc:
        resolve_stack_from_objective(ROOT, "77")
    assert exc.value.error_type == "objective_not_found"


def test_objective_arm_skips_non_open_and_prless_layers(monkeypatch):
    layers = (
        _layer("1.1", "301", "plan-301", 41),  # MERGED below — not a member
        _layer("1.2", "302", "plan-302", 52),
        _layer("1.3", None, None, None),  # no PR — never a member
        _layer("1.4", "304", "plan-304", 63),
    )
    _wire_delivery(monkeypatch, _FakeDelivery(_status(_train(layers))))
    _wire_gateway(
        monkeypatch,
        [
            _pr(41, "plan-301", "main", state="MERGED"),
            _pr(52, "plan-302", "main"),
            _pr(63, "plan-304", "plan-302"),
        ],
    )
    stack = resolve_stack_from_objective(ROOT, "77")
    assert [m.pr_number for m in stack.members] == [52, 63]


def test_objective_arm_discontiguous_refused(monkeypatch):
    layers = (
        _layer("1.1", "301", "plan-301", 41),
        _layer("1.2", "302", "plan-302", 52),
    )
    _wire_delivery(monkeypatch, _FakeDelivery(_status(_train(layers))))
    _wire_gateway(
        monkeypatch,
        [
            _pr(41, "plan-301", "main"),
            _pr(52, "plan-302", "main"),  # observed base skips its predecessor
        ],
    )
    with pytest.raises(UserFacingCliError) as exc:
        resolve_stack_from_objective(ROOT, "77")
    assert exc.value.error_type == "stack_discontiguous"


def test_objective_arm_first_member_base_must_match_train_base(monkeypatch):
    layers = (
        _layer("1.1", "301", "plan-301", 41),
        _layer("1.2", "302", "plan-302", 52),
    )
    _wire_delivery(monkeypatch, _FakeDelivery(_status(_train(layers, base="develop"))))
    _wire_gateway(
        monkeypatch,
        [_pr(41, "plan-301", "main"), _pr(52, "plan-302", "plan-301")],
    )
    with pytest.raises(UserFacingCliError) as exc:
        resolve_stack_from_objective(ROOT, "77")
    assert exc.value.error_type == "stack_discontiguous"


def test_objective_arm_fork_member_refused(monkeypatch):
    layers = (
        _layer("1.1", "301", "plan-301", 41),
        _layer("1.2", "302", "plan-302", 52),
    )
    _wire_delivery(monkeypatch, _FakeDelivery(_status(_train(layers))))
    _wire_gateway(
        monkeypatch,
        [
            _pr(41, "plan-301", "main"),
            _pr(52, "plan-302", "plan-301", head_repo="forker/repo"),
        ],
    )
    with pytest.raises(UserFacingCliError) as exc:
        resolve_stack_from_objective(ROOT, "77")
    assert exc.value.error_type == "fork_unsupported"


def test_objective_arm_single_open_layer_is_not_a_stack(monkeypatch):
    # The one-open-PR train previously passed resolution and failed later — now a typed gate.
    layers = (_layer("1.1", "301", "plan-301", 41),)
    _wire_delivery(monkeypatch, _FakeDelivery(_status(_train(layers))))
    _wire_gateway(monkeypatch, [_pr(41, "plan-301", "main")])
    with pytest.raises(UserFacingCliError) as exc:
        resolve_stack_from_objective(ROOT, "77")
    assert exc.value.error_type == "not_a_stack"


def test_objective_arm_too_deep(monkeypatch):
    count = STACK_REVIEW_MAX_MEMBERS + 1
    layers = tuple(
        _layer(f"1.{i + 1}", str(300 + i), f"plan-{300 + i}", 400 + i) for i in range(count)
    )
    _wire_delivery(monkeypatch, _FakeDelivery(_status(_train(layers))))
    _wire_gateway(
        monkeypatch,
        [
            _pr(400 + i, f"plan-{300 + i}", "main" if i == 0 else f"plan-{300 + i - 1}")
            for i in range(count)
        ],
    )
    with pytest.raises(UserFacingCliError) as exc:
        resolve_stack_from_objective(ROOT, "77")
    assert exc.value.error_type == "stack_too_deep"


def test_max_members_constant_pinned():
    assert STACK_REVIEW_MAX_MEMBERS == 20
