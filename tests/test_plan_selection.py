"""The neutral CLI-level plan-selection seam (`perk.cli.plan_selection`).

`select_plan` is the ONE canonical backend read every plan-selecting cold door shares (parser
coverage lives in test_plan_id_parsing.py); `main_repo_root` is the two-roots rule's main-root
resolver. The matching `PlanState`/`PlanRef` pair it returns is what launches consume directly.
"""

import pytest

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
        return plans.PlanState(number=7, url="u/7", title="T", header={}, pr=None)

    monkeypatch.setattr(plans, "get_plan", _get_plan)
    selected = select_plan(git_repo, "https://github.com/o/r/issues/7")
    assert seen == ["7"] and selected.plan_id == "7"


def test_select_plan_not_found_is_typed(git_repo, monkeypatch):
    monkeypatch.setattr(plans, "get_plan", lambda **k: None)
    with pytest.raises(UserFacingCliError) as exc:
        select_plan(git_repo, "999")
    assert exc.value.error_type == "plan_not_found"


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
