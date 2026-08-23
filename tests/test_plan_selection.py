"""The neutral CLI-level plan-selection seam (`perk.cli.plan_selection`).

`select_plan` is the ONE canonical selection every plan-selecting cold door shares (parser
coverage lives in test_plan_id_parsing.py); `main_repo_root` is the two-roots rule's main-root
resolver. The matching `PlanState`/`PlanRef` pair it returns is what launches consume directly.
Positive plan identification (contracts §8.1): an existing issue with no plan-header refuses
typed (`issue_kind_mismatch`) — covered here for all four `select_plan` doors at once.

PR selectors (`.../pull/N` URL or a bare number that only resolves as a PR) resolve through
the probe tier (`github.get_pr` → the `plan-<id>` head candidate) into the same canonical
selection, gated by the corroboration rule (the plan's recorded `plan-header.pr` must name the
supplied PR). Every digits-selector failure test fakes `perk.github.get_pr` explicitly — the
fallback probe must never escape into a real `gh` subprocess.
"""

import pytest

from perk import github
from perk.backends import issue_backend, resolve
from perk.backends.github import plans
from perk.cli.ensure import UserFacingCliError
from perk.cli.plan_selection import main_repo_root, select_plan
from perk.substrate import git


def _pull(number: int, head_ref: str) -> github.PullRequest:
    return github.PullRequest(
        number=number,
        url=f"https://gh/o/r/pull/{number}",
        is_draft=True,
        state="OPEN",
        existed=True,
        head_ref=head_ref,
    )


def _plan_state(number: int, *, header: dict | None = None) -> plans.PlanState:
    return plans.PlanState(
        number=number,
        url=f"https://gh/o/r/issues/{number}",
        title="T",
        header=header or {},
        pr=None,
        has_plan_header=True,
    )


def _pr_carrier(number: int, *, has_plan_header: bool = False) -> plans.PlanState:
    """The GitHub quirk: `gh issue view <PR#>` resolves the PR — an issue-shaped record whose
    url names a pull request."""
    return plans.PlanState(
        number=number,
        url=f"https://gh/o/r/pull/{number}",
        title="PR",
        header={},
        pr=None,
        has_plan_header=has_plan_header,
    )


def _stub_plans(monkeypatch, states: dict[int, plans.PlanState], reads: list | None = None) -> None:
    def _get_plan(**kwargs):
        if reads is not None:
            reads.append(kwargs)
        return states.get(int(kwargs["number"]))

    monkeypatch.setattr(plans, "get_plan", _get_plan)


def _stub_get_pr(
    monkeypatch,
    prs: dict[int, github.PullRequest | None],
    calls: list[int] | None = None,
) -> None:
    def _get_pr(*, number: int, repo_root):
        if calls is not None:
            calls.append(number)
        assert number in prs, f"unexpected get_pr({number})"
        return prs[number]

    monkeypatch.setattr(github, "get_pr", _get_pr)


def _no_probe(monkeypatch) -> None:
    def _get_pr(**kwargs):
        raise AssertionError("select_plan must not probe get_pr on this path")

    monkeypatch.setattr(github, "get_pr", _get_pr)


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
    # Hermeticity: the digits miss now probes the PR fallback — fake it to a clean miss.
    _stub_get_pr(monkeypatch, {999: None})
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
    _stub_get_pr(monkeypatch, {63: None})  # hermetic: the fallback probe misses cleanly
    with pytest.raises(UserFacingCliError) as exc:
        select_plan(git_repo, "63")
    assert exc.value.error_type == "issue_kind_mismatch"
    assert "not a perk plan" in str(exc.value)


def test_select_plan_github_objective_names_the_right_door(git_repo, monkeypatch):
    """A GitHub objective-header'd issue refuses with the `perk objective plan <N>` hint —
    preserved verbatim through the PR fallback's clean probe miss."""
    monkeypatch.setattr(
        plans,
        "get_plan",
        lambda **k: plans.PlanState(
            number=63, url="u/63", title="T", header={}, pr=None, has_objective_header=True
        ),
    )
    _stub_get_pr(monkeypatch, {63: None})  # hermetic + the right-door-hint preservation pin
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


# --- PR selectors (the explicit /pull/N arm + the bare-number fallback) ---------------------


def test_explicit_pull_url_resolves_to_the_corroborated_plan(git_repo, monkeypatch):
    reads: list[dict] = []
    _stub_plans(monkeypatch, {7: _plan_state(7, header={"pr": 888, "base": "develop"})}, reads)
    _stub_get_pr(monkeypatch, {888: _pull(888, "plan-7")})
    selected = select_plan(git_repo, "https://github.com/o/r/pull/888")
    assert selected.plan_id == "7"
    assert len(reads) == 1  # exactly one get_plan read — the header rode the selection
    # State/ref agree exactly as a direct-id selection would.
    assert selected.state.id == "7" and selected.ref.pr_id == "7"
    assert selected.ref.base == "develop"


def test_bare_pr_number_falls_back_through_the_carrier_guard(git_repo, monkeypatch):
    # GitHub shape: `gh issue view 1984` resolves the PR itself — the carrier guard refuses
    # (url-shaped evidence), then the fallback probes the PR and selects the peeled plan.
    _stub_plans(
        monkeypatch,
        {1984: _pr_carrier(1984), 1983: _plan_state(1983, header={"pr": 1984})},
    )
    _stub_get_pr(monkeypatch, {1984: _pull(1984, "plan-1983")})
    selected = select_plan(git_repo, "1984")
    assert selected.plan_id == "1983"
    assert selected.state.id == "1983" and selected.ref.pr_id == "1983"


def test_pr_carrier_guard_ignores_a_header_positive_scan(git_repo, monkeypatch):
    """Regression: submit embeds the plan markdown verbatim in the PR body, so a PR carrier
    can scan header-positive (`has_plan_header=True` is a raw delimiter scan). Kind evidence
    for a PR carrier is the url — the guard still refuses and the fallback still resolves;
    the PR number is never selected as a plan id."""
    _stub_plans(
        monkeypatch,
        {
            1984: _pr_carrier(1984, has_plan_header=True),
            1983: _plan_state(1983, header={"pr": 1984}),
        },
    )
    _stub_get_pr(monkeypatch, {1984: _pull(1984, "plan-1983")})
    selected = select_plan(git_repo, "1984")
    assert selected.plan_id == "1983"


def test_bare_pr_number_resolves_on_linear_too(git_repo, monkeypatch):
    # Linear shape: a digits-only id is an honest `get_plan → None` miss; the PR tier is
    # GitHub-universal, so the probe still peels the plan-<id> head (a Linear-native id).
    class _FakeLinearBackend:
        backend_id = "linear"

        def get_plan(self, *, issue_id):
            if issue_id == "1984":
                return None
            assert issue_id == "PER-15"
            return issue_backend.PlanState(
                id="PER-15",
                url="u/PER-15",
                title="T",
                header={"pr": 1984},
                pr=None,
                state="OPEN",
                has_plan_header=True,
            )

    monkeypatch.setattr(resolve, "resolve_issue_backend", lambda root: _FakeLinearBackend())
    _stub_get_pr(monkeypatch, {1984: _pull(1984, "plan-PER-15")})
    selected = select_plan(git_repo, "1984")
    assert selected.plan_id == "PER-15"
    assert selected.ref.provider == "linear"


@pytest.mark.parametrize("selector", ["https://github.com/o/r/pull/888", "888"])
def test_corroboration_mismatch_refuses_typed_on_both_arms(git_repo, monkeypatch, selector):
    # The head branch is a candidate pointer, never provenance: a stray/fork plan-7 branch
    # whose PR the plan does not record must not select (both arms — the selection tier is
    # arm-independent, so the fallback does NOT re-raise here).
    _stub_plans(monkeypatch, {7: _plan_state(7, header={"pr": 555})})
    _stub_get_pr(monkeypatch, {888: _pull(888, "plan-7")})
    with pytest.raises(UserFacingCliError) as exc:
        select_plan(git_repo, selector)
    assert exc.value.error_type == "issue_kind_mismatch"
    message = str(exc.value)
    assert "PR #888" in message and "plan #7" in message and "PR #555" in message


@pytest.mark.parametrize("selector", ["https://github.com/o/r/pull/888", "888"])
def test_corroboration_refuses_an_unrecorded_pr(git_repo, monkeypatch, selector):
    # An unsubmitted plan records no PR — the positive-evidence gate refuses (both arms).
    _stub_plans(monkeypatch, {7: _plan_state(7)})
    _stub_get_pr(monkeypatch, {888: _pull(888, "plan-7")})
    with pytest.raises(UserFacingCliError) as exc:
        select_plan(git_repo, selector)
    assert exc.value.error_type == "issue_kind_mismatch"
    assert "records no PR" in str(exc.value)


@pytest.mark.parametrize("head", ["plan-#42", "plan-", "plan-a/b", "plan-.", "feature/foo"])
def test_non_conforming_head_is_a_probe_miss_on_the_explicit_arm(git_repo, monkeypatch, head):
    # One rule covers every shape: missing prefix, empty peel, parser-rejected peel (its
    # invalid_input never leaks), and a normalizing peel (plan-#42 fails the round-trip).
    _stub_plans(monkeypatch, {})
    _stub_get_pr(monkeypatch, {888: _pull(888, head)})
    with pytest.raises(UserFacingCliError) as exc:
        select_plan(git_repo, "https://github.com/o/r/pull/888")
    assert exc.value.error_type == "issue_kind_mismatch"
    assert "was not created from a perk plan" in str(exc.value)
    assert repr(head) in str(exc.value)


@pytest.mark.parametrize("head", ["plan-#42", "plan-", "plan-a/b", "plan-.", "feature/foo"])
def test_non_conforming_head_re_raises_the_original_on_the_fallback_arm(
    git_repo, monkeypatch, head
):
    _stub_plans(monkeypatch, {})
    _stub_get_pr(monkeypatch, {888: _pull(888, head)})
    with pytest.raises(UserFacingCliError) as exc:
        select_plan(git_repo, "888")
    assert exc.value.error_type == "plan_not_found"
    assert "Plan issue #888 not found" in str(exc.value)  # the original error, verbatim


def test_fallback_missing_pr_re_raises_the_original(git_repo, monkeypatch):
    _stub_plans(monkeypatch, {})
    _stub_get_pr(monkeypatch, {999: None})
    with pytest.raises(UserFacingCliError) as exc:
        select_plan(git_repo, "999")
    assert exc.value.error_type == "plan_not_found"
    assert "Plan issue #999 not found" in str(exc.value)


def test_fallback_probe_github_error_re_raises_the_original(git_repo, monkeypatch):
    _stub_plans(monkeypatch, {})

    def _boom(**kwargs):
        raise github.GitHubError("rate limited")

    monkeypatch.setattr(github, "get_pr", _boom)
    with pytest.raises(UserFacingCliError) as exc:
        select_plan(git_repo, "999")
    assert exc.value.error_type == "plan_not_found"  # the probe is best-effort


def test_explicit_arm_probe_github_error_translates_to_backend_error(git_repo, monkeypatch):
    # The explicit arm must not leak a bare GitHubError past address/implement's existing
    # `except IssueBackendError` boundaries.
    _stub_plans(monkeypatch, {})

    def _boom(**kwargs):
        raise github.GitHubError("rate limited")

    monkeypatch.setattr(github, "get_pr", _boom)
    with pytest.raises(issue_backend.IssueBackendError):
        select_plan(git_repo, "https://github.com/o/r/pull/888")


def test_explicit_arm_missing_pr_is_typed_not_found(git_repo, monkeypatch):
    _stub_plans(monkeypatch, {})
    _stub_get_pr(monkeypatch, {888: None})
    with pytest.raises(UserFacingCliError) as exc:
        select_plan(git_repo, "https://github.com/o/r/pull/888")
    assert exc.value.error_type == "plan_not_found"
    assert "PR #888 not found" in str(exc.value)


@pytest.mark.parametrize("selector", ["https://github.com/o/r/pull/888", "888"])
def test_selection_tier_failure_propagates_naming_the_peeled_plan(git_repo, monkeypatch, selector):
    # Past the probe, the peeled plan's own failure propagates as-is (strictly more
    # informative than the original) — and get_pr is called exactly once: no chained fallback.
    calls: list[int] = []
    _stub_plans(monkeypatch, {})  # the peeled plan #7 is missing too
    _stub_get_pr(monkeypatch, {888: _pull(888, "plan-7")}, calls)
    with pytest.raises(UserFacingCliError) as exc:
        select_plan(git_repo, selector)
    assert exc.value.error_type == "plan_not_found"
    assert "Plan issue #7 not found" in str(exc.value)
    assert calls == [888]


def test_non_digit_id_never_probes(git_repo, monkeypatch):
    class _FakeLinearBackend:
        backend_id = "linear"

        def get_plan(self, *, issue_id):
            return None

    monkeypatch.setattr(resolve, "resolve_issue_backend", lambda root: _FakeLinearBackend())
    _no_probe(monkeypatch)
    with pytest.raises(UserFacingCliError) as exc:
        select_plan(git_repo, "ENG-123")
    assert exc.value.error_type == "plan_not_found"


def test_fallback_narration_leaves_no_dangling_step(git_repo, monkeypatch, capsys):
    """The append-shape narration pin (non-TTY stderr — the CliRunner/CI shape): a successful
    bare-number fallback warn-resolves the initial lookup step before continuing, so every
    step line is followed by its own resolution line."""
    _stub_plans(
        monkeypatch,
        {1984: _pr_carrier(1984), 1983: _plan_state(1983, header={"pr": 1984})},
    )
    _stub_get_pr(monkeypatch, {1984: _pull(1984, "plan-1983")})
    select_plan(git_repo, "1984")
    err = capsys.readouterr().err
    assert "\u203a looking up plan #1984" in err
    assert "⚠ #1984 is a pull request, not a plan issue" in err
    assert "\u203a resolving PR #1984" in err
    assert "✓ PR #1984 → plan #1983" in err
    assert "\u203a looking up plan #1983" in err
    assert "✓ found plan #1983" in err
    # No dangling step: every step line is immediately followed by a resolution line.
    lines = [line.strip() for line in err.splitlines() if line.strip()]
    for i, line in enumerate(lines):
        if line.startswith("\u203a"):
            assert lines[i + 1][0] in "✓⚠", f"dangling step line: {line!r}"


def test_main_repo_root_resolves_linked_worktree_to_the_main_checkout(git_repo):
    wt = git_repo / ".worktrees" / "plan-42"
    git.worktree_add(git_repo, wt, branch="plan-42", create_branch=True)
    assert main_repo_root(wt) == git_repo
    assert main_repo_root(git_repo) == git_repo  # the main checkout maps to itself
