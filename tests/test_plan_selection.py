"""The neutral CLI-level plan-selection seam (`perk.cli.plan_selection`).

`select_plan` is the ONE canonical backend read every plan-selecting cold door shares (parser
coverage lives in test_plan_id_parsing.py); `main_repo_root` is the two-roots rule's main-root
resolver. The matching `PlanState`/`PlanRef` pair it returns is what launches consume directly.
Positive plan identification (contracts §8.1): an existing issue with no plan-header refuses
typed (`issue_kind_mismatch`) — covered here for all three `select_plan` doors at once.
"""

import pytest

from perk.backends import issue_backend, resolve
from perk.backends.github import plans
from perk.cli.ensure import UserFacingCliError
from perk.cli.plan_selection import main_repo_root, select_plan
from perk.substrate import git


def test_select_plan_one_read_yields_matching_state_and_ref(git_repo, monkeypatch):
    reads: list[dict] = []

    def _get_plan(**kwargs):
        reads.append(kwargs)
        return plans.PlanState(
            number=7,
            url="https://gh/o/r/issues/7",
            title="T",
            header={"objective_id": "63", "base": "develop", "consumed_learn": ["45"]},
            pr=None,
            has_plan_header=True,
        )

    monkeypatch.setattr(plans, "get_plan", _get_plan)
    selected = select_plan(git_repo, "#7")
    assert len(reads) == 1  # ONE canonical read
    assert selected.plan_id == "7"
    assert selected.state.id == "7" and selected.state.url == "https://gh/o/r/issues/7"
    # The ref is `resume.reconstruct_plan_ref` over that same state — id/url/header agree.
    assert selected.ref.pr_id == "7"
    assert selected.ref.url == selected.state.url
    assert selected.ref.objective_id == "63"
    assert selected.ref.base == "develop"
    assert selected.ref.consumed_learn == ("45",)


def test_select_plan_url_selector_peels_to_the_id(git_repo, monkeypatch):
    seen: list[str] = []

    def _get_plan(**kwargs):
        seen.append(str(kwargs["number"]))
        # `header={}` (e.g. a malformed-but-present block) still selects — kind evidence rides
        # the presence flag, not header truthiness.
        return plans.PlanState(
            number=7, url="u/7", title="T", header={}, pr=None, has_plan_header=True
        )

    monkeypatch.setattr(plans, "get_plan", _get_plan)
    selected = select_plan(git_repo, "https://github.com/o/r/issues/7")
    assert seen == ["7"] and selected.plan_id == "7"


def test_select_plan_not_found_is_typed(git_repo, monkeypatch):
    monkeypatch.setattr(plans, "get_plan", lambda **k: None)
    with pytest.raises(UserFacingCliError) as exc:
        select_plan(git_repo, "999")
    assert exc.value.error_type == "plan_not_found"


def test_select_plan_headerless_issue_refuses_kind_mismatch(git_repo, monkeypatch):
    """An existing issue with NO plan-header is positively not a plan — typed refusal."""
    monkeypatch.setattr(
        plans,
        "get_plan",
        lambda **k: plans.PlanState(number=63, url="u/63", title="T", header={}, pr=None),
    )
    with pytest.raises(UserFacingCliError) as exc:
        select_plan(git_repo, "63")
    assert exc.value.error_type == "issue_kind_mismatch"
    assert "not a perk plan" in str(exc.value)


def test_select_plan_github_objective_names_the_right_door(git_repo, monkeypatch):
    """A GitHub objective-header'd issue refuses with the `perk objective plan <N>` hint."""
    monkeypatch.setattr(
        plans,
        "get_plan",
        lambda **k: plans.PlanState(
            number=63, url="u/63", title="T", header={}, pr=None, has_objective_header=True
        ),
    )
    with pytest.raises(UserFacingCliError) as exc:
        select_plan(git_repo, "63")
    assert exc.value.error_type == "issue_kind_mismatch"
    assert "perk objective plan 63" in str(exc.value)


def test_select_plan_linear_objective_refuses_without_the_door_hint(git_repo, monkeypatch):
    """The right-door hint is GitHub-only: a Linear objective-header'd issue (a metadata
    sentinel) refuses with the generic message — its id is not the objective id."""

    class _FakeLinearBackend:
        backend_id = "linear"

        def get_plan(self, *, issue_id):
            return issue_backend.PlanState(
                id=issue_id,
                url="u/SEN-9",
                title="T",
                header={},
                pr=None,
                state="OPEN",
                has_objective_header=True,
            )

    monkeypatch.setattr(resolve, "resolve_issue_backend", lambda root: _FakeLinearBackend())
    with pytest.raises(UserFacingCliError) as exc:
        select_plan(git_repo, "SEN-9")
    assert exc.value.error_type == "issue_kind_mismatch"
    assert "perk objective plan" not in str(exc.value)
    assert "not a perk plan" in str(exc.value)


def test_select_plan_both_headers_carrier_still_selects(git_repo, monkeypatch):
    """A both-headers carrier still selects as a plan (its plan side can be legitimate
    mid-incident) — doctor is the both-headers surface, not selection."""
    monkeypatch.setattr(
        plans,
        "get_plan",
        lambda **k: plans.PlanState(
            number=7,
            url="u/7",
            title="T",
            header={},
            pr=None,
            has_plan_header=True,
            has_objective_header=True,
        ),
    )
    selected = select_plan(git_repo, "7")
    assert selected.plan_id == "7"


def test_select_plan_invalid_id_is_typed_and_offline(git_repo, monkeypatch):
    monkeypatch.setattr(
        plans, "get_plan", lambda **k: (_ for _ in ()).throw(AssertionError("no backend read"))
    )
    with pytest.raises(UserFacingCliError) as exc:
        select_plan(git_repo, "a/b")
    assert exc.value.error_type == "invalid_input"


def test_main_repo_root_resolves_linked_worktree_to_the_main_checkout(git_repo):
    wt = git_repo / ".worktrees" / "plan-42"
    git.worktree_add(git_repo, wt, branch="plan-42", create_branch=True)
    assert main_repo_root(wt) == git_repo
    assert main_repo_root(git_repo) == git_repo  # the main checkout maps to itself
