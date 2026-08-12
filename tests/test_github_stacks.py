"""Tests for the GitHub-native stacked-PR read adapter (``perk/github/stacks.py``).

Wire-level via the shared ``_GhDispatch`` fake-subprocess pattern: exact GraphQL argv/variables,
the stable-vs-preview failure-posture split (``pr_delivery_facts`` fails honestly;
``pr_stack`` degrades to ``available=False`` on anything but a PR lookup miss), position
ordering, truncation, and the labelled malformed-payload error.
"""

import json
import subprocess

import pytest
from _github_fakes import ROOT, _GhDispatch, _has, _Proc

from perk.github import GitHubError, stacks

_OWNER_REPO = (_has("repo", "view", "nameWithOwner"), _Proc(0, "octo/repo\n"))


def _facts_payload(**overrides: object) -> str:
    node: dict[str, object] = {
        "number": 42,
        "state": "OPEN",
        "isDraft": False,
        "baseRefName": "main",
        "headRefName": "plan-42",
        "headRefOid": "a" * 40,
    }
    node.update(overrides)
    return json.dumps({"data": {"repository": {"pullRequest": node}}})


def _stack_payload(stack: object) -> str:
    return json.dumps(
        {"data": {"repository": {"pullRequest": {"stackEntry": {"position": 1}, "stack": stack}}}}
    )


def _entries(*pairs: tuple[int, int], has_next: bool = False) -> dict[str, object]:
    return {
        "nodes": [{"position": pos, "pullRequest": {"number": number}} for pos, number in pairs],
        "pageInfo": {"hasNextPage": has_next},
    }


# --- pr_delivery_facts (stable read) --------------------------------------------------


def test_pr_delivery_facts_happy_path_and_argv(monkeypatch):
    rec = _GhDispatch([_OWNER_REPO, (_has("graphql", "headRefOid"), _Proc(0, _facts_payload()))])
    monkeypatch.setattr(subprocess, "run", rec)
    facts = stacks.pr_delivery_facts(number=42, repo_root=ROOT)
    assert facts == stacks.PrDeliveryFacts(
        number=42,
        state="OPEN",
        is_draft=False,
        base_ref="main",
        head_ref="plan-42",
        head_sha="a" * 40,
    )
    graphql_call = rec.calls[-1]
    assert graphql_call[:2] == ["api", "graphql"]
    assert f"query={stacks.PR_DELIVERY_FACTS_QUERY}" in graphql_call
    assert "owner=octo" in graphql_call and "repo=repo" in graphql_call
    assert "number=42" in graphql_call
    # Typed variables: strings via -f, the PR number via -F.
    assert graphql_call[graphql_call.index("number=42") - 1] == "-F"


def test_pr_delivery_facts_not_found_returns_none(monkeypatch):
    rec = _GhDispatch(
        [
            _OWNER_REPO,
            (
                _has("graphql"),
                _Proc(1, stderr="GraphQL: Could not resolve to a PullRequest (pullRequest)"),
            ),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    assert stacks.pr_delivery_facts(number=999, repo_root=ROOT) is None


def test_pr_delivery_facts_infra_failure_raises(monkeypatch):
    rec = _GhDispatch([_OWNER_REPO, (_has("graphql"), _Proc(1, stderr="HTTP 500"))])
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(GitHubError, match="delivery facts for PR #42"):
        stacks.pr_delivery_facts(number=42, repo_root=ROOT)


def test_pr_delivery_facts_malformed_payload_is_labelled_error(monkeypatch):
    payload = json.dumps({"data": {"repository": {"pullRequest": {"number": "junk"}}}})
    rec = _GhDispatch([_OWNER_REPO, (_has("graphql"), _Proc(0, payload))])
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(GitHubError, match="delivery facts for PR #42"):
        stacks.pr_delivery_facts(number=42, repo_root=ROOT)


def test_pr_delivery_facts_partial_payload_is_labelled_error(monkeypatch):
    # Every stable fact is REQUIRED at the wire boundary: a payload carrying only `number`
    # must never read as an open/false/empty observation.
    payload = json.dumps({"data": {"repository": {"pullRequest": {"number": 42}}}})
    rec = _GhDispatch([_OWNER_REPO, (_has("graphql"), _Proc(0, payload))])
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(GitHubError, match="delivery facts for PR #42"):
        stacks.pr_delivery_facts(number=42, repo_root=ROOT)


def test_pr_delivery_facts_unknown_state_is_labelled_error(monkeypatch):
    rec = _GhDispatch([_OWNER_REPO, (_has("graphql"), _Proc(0, _facts_payload(state="WEIRD")))])
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(GitHubError, match="delivery facts for PR #42"):
        stacks.pr_delivery_facts(number=42, repo_root=ROOT)


def test_pr_delivery_facts_missing_pr_node_is_labelled_error(monkeypatch):
    rec = _GhDispatch([_OWNER_REPO, (_has("graphql"), _Proc(0, json.dumps({"data": {}})))])
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(GitHubError, match="no pullRequest node"):
        stacks.pr_delivery_facts(number=42, repo_root=ROOT)


# --- pr_stack (tolerant preview read) --------------------------------------------------


def test_pr_stack_happy_path_sorts_entries_by_position(monkeypatch):
    stack = {"number": 7, "size": 3, "entries": _entries((3, 30), (1, 10), (2, 20))}
    rec = _GhDispatch(
        [_OWNER_REPO, (_has("graphql", "stackEntry"), _Proc(0, _stack_payload(stack)))]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    obs = stacks.pr_stack(number=10, repo_root=ROOT)
    assert obs.available is True
    assert obs.stack is not None
    assert obs.stack.number == 7 and obs.stack.size == 3
    assert obs.stack.truncated is False
    assert [(e.position, e.pr_number) for e in obs.stack.entries] == [(1, 10), (2, 20), (3, 30)]
    graphql_call = rec.calls[-1]
    assert f"query={stacks.PR_STACK_QUERY}" in graphql_call
    assert "owner=octo" in graphql_call and "repo=repo" in graphql_call
    assert "number=10" in graphql_call


def test_pr_stack_null_stack_means_genuinely_not_stacked(monkeypatch):
    rec = _GhDispatch([_OWNER_REPO, (_has("graphql"), _Proc(0, _stack_payload(None)))])
    monkeypatch.setattr(subprocess, "run", rec)
    assert stacks.pr_stack(number=10, repo_root=ROOT) == stacks.StackObservation(
        available=True, stack=None
    )


def test_pr_stack_not_found_pr_raises(monkeypatch):
    # A PR lookup miss is a STABLE fact, never preview noise — it raises rather than degrading.
    rec = _GhDispatch(
        [
            _OWNER_REPO,
            (
                _has("graphql"),
                _Proc(1, stderr="GraphQL: Could not resolve to a PullRequest (pullRequest)"),
            ),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(GitHubError, match="native stack for PR #999"):
        stacks.pr_stack(number=999, repo_root=ROOT)


def test_pr_stack_schema_rejection_degrades_to_unavailable(monkeypatch):
    rec = _GhDispatch(
        [
            _OWNER_REPO,
            (_has("graphql"), _Proc(1, stderr="Field 'stack' doesn't exist on type PullRequest")),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    assert stacks.pr_stack(number=10, repo_root=ROOT) == stacks.StackObservation(available=False)


def test_pr_stack_has_next_page_reports_truncated(monkeypatch):
    stack = {"number": 7, "size": 101, "entries": _entries((1, 10), (2, 20), has_next=True)}
    rec = _GhDispatch([_OWNER_REPO, (_has("graphql"), _Proc(0, _stack_payload(stack)))])
    monkeypatch.setattr(subprocess, "run", rec)
    obs = stacks.pr_stack(number=10, repo_root=ROOT)
    assert obs.available is True
    assert obs.stack is not None and obs.stack.truncated is True


def test_pr_stack_malformed_payload_degrades_to_unavailable(monkeypatch):
    rec = _GhDispatch([_OWNER_REPO, (_has("graphql"), _Proc(0, "not json"))])
    monkeypatch.setattr(subprocess, "run", rec)
    assert stacks.pr_stack(number=10, repo_root=ROOT) == stacks.StackObservation(available=False)


def test_pr_stack_malformed_entry_degrades_to_unavailable(monkeypatch):
    stack = {"number": 7, "size": 2, "entries": {"nodes": [{"position": "x"}]}}
    rec = _GhDispatch([_OWNER_REPO, (_has("graphql"), _Proc(0, _stack_payload(stack)))])
    monkeypatch.setattr(subprocess, "run", rec)
    assert stacks.pr_stack(number=10, repo_root=ROOT) == stacks.StackObservation(available=False)


def test_pr_stack_missing_page_info_degrades_to_unavailable(monkeypatch):
    # Exactness relies on OBSERVED non-truncation: absent pagination evidence must degrade,
    # never default to "not truncated" (which would let a bigger stack classify EXACT).
    stack = {
        "number": 7,
        "size": 2,
        "entries": {"nodes": [{"position": 1, "pullRequest": {"number": 10}}]},
    }
    rec = _GhDispatch([_OWNER_REPO, (_has("graphql"), _Proc(0, _stack_payload(stack)))])
    monkeypatch.setattr(subprocess, "run", rec)
    assert stacks.pr_stack(number=10, repo_root=ROOT) == stacks.StackObservation(available=False)


# --- stack_capability (schema introspection; fail closed) ------------------------------


def _introspection_payload(field_names: list[str]) -> str:
    return json.dumps({"data": {"__type": {"fields": [{"name": name} for name in field_names]}}})


def test_stack_capability_field_present(monkeypatch):
    rec = _GhDispatch(
        [(_has("graphql"), _Proc(0, _introspection_payload(["number", "stack", "state"])))]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    assert stacks.stack_capability(ROOT) is True
    graphql_call = rec.calls[-1]
    assert f"query={stacks.STACK_CAPABILITY_QUERY}" in graphql_call


def test_stack_capability_field_missing_is_false(monkeypatch):
    rec = _GhDispatch([(_has("graphql"), _Proc(0, _introspection_payload(["number", "state"])))])
    monkeypatch.setattr(subprocess, "run", rec)
    assert stacks.stack_capability(ROOT) is False


def test_stack_capability_introspection_failure_fails_closed(monkeypatch):
    rec = _GhDispatch([(_has("graphql"), _Proc(1, stderr="HTTP 500"))])
    monkeypatch.setattr(subprocess, "run", rec)
    assert stacks.stack_capability(ROOT) is False


def test_stack_capability_malformed_payload_fails_closed(monkeypatch):
    rec = _GhDispatch([(_has("graphql"), _Proc(0, "not json"))])
    monkeypatch.setattr(subprocess, "run", rec)
    assert stacks.stack_capability(ROOT) is False


# --- base_merge_rules (squash + merge-queue reads; strict) -----------------------------


def _squash_payload(allowed: bool) -> str:
    return json.dumps({"data": {"repository": {"squashMergeAllowed": allowed}}})


def _merge_rules_dispatch(*, squash: bool, rules: object) -> _GhDispatch:
    return _GhDispatch(
        [
            _OWNER_REPO,
            (_has("graphql"), _Proc(0, _squash_payload(squash))),
            (_has("rules/branches/main"), _Proc(0, json.dumps(rules))),
        ]
    )


def test_base_merge_rules_happy_path(monkeypatch):
    rec = _merge_rules_dispatch(squash=True, rules=[{"type": "pull_request"}])
    monkeypatch.setattr(subprocess, "run", rec)
    rules = stacks.base_merge_rules(ROOT, "main")
    assert rules == stacks.MergeRules(squash_allowed=True, merge_queue_required=False)
    rest_call = rec.calls[-1]
    assert rest_call[0] == "api" and "rules/branches/main" in rest_call[1]
    assert rest_call[2:4] == ["-X", "GET"]


def test_base_merge_rules_squash_disallowed(monkeypatch):
    rec = _merge_rules_dispatch(squash=False, rules=[])
    monkeypatch.setattr(subprocess, "run", rec)
    assert stacks.base_merge_rules(ROOT, "main").squash_allowed is False


def test_base_merge_rules_merge_queue_rule_detected(monkeypatch):
    rec = _merge_rules_dispatch(squash=True, rules=[{"type": "deletion"}, {"type": "merge_queue"}])
    monkeypatch.setattr(subprocess, "run", rec)
    rules = stacks.base_merge_rules(ROOT, "main")
    assert rules.merge_queue_required is True


def test_base_merge_rules_infra_failure_raises(monkeypatch):
    rec = _GhDispatch([_OWNER_REPO, (_has("graphql"), _Proc(1, stderr="HTTP 500"))])
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(GitHubError, match="merge rules for base 'main'"):
        stacks.base_merge_rules(ROOT, "main")


def test_base_merge_rules_rest_failure_raises(monkeypatch):
    # The REST half fails closed too: a non-zero branch-rules read is a GitHubError, never
    # "no merge queue".
    rec = _GhDispatch(
        [
            _OWNER_REPO,
            (_has("graphql"), _Proc(0, _squash_payload(True))),
            (_has("rules/branches/main"), _Proc(1, stderr="HTTP 500")),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(GitHubError, match="merge rules for base 'main'"):
        stacks.base_merge_rules(ROOT, "main")


@pytest.mark.parametrize(
    "payload",
    [
        {"message": "Not a list"},  # a non-list JSON value
        [{"type": "pull_request"}, "junk"],  # a non-dict rule element
        [{"kind": "merge_queue"}],  # a rule object with no string `type`
        [{"type": 7}],  # a mistyped `type`
    ],
)
def test_base_merge_rules_malformed_rules_payload_raises(monkeypatch, payload):
    # A malformed-but-zero-exit rules payload must raise (can't verify ⇒ don't promise) — the
    # tolerant `_dicts` normalization would silently read it as merge_queue_required=False.
    rec = _merge_rules_dispatch(squash=True, rules=payload)
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(GitHubError, match="branch rules payload"):
        stacks.base_merge_rules(ROOT, "main")


def test_base_merge_rules_malformed_squash_payload_raises(monkeypatch):
    rec = _GhDispatch(
        [_OWNER_REPO, (_has("graphql"), _Proc(0, json.dumps({"data": {"repository": {}}})))]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(GitHubError, match="squashMergeAllowed missing"):
        stacks.base_merge_rules(ROOT, "main")


# --- pr_land_facts (the §8.55 strict landing-readiness read) ---------------------------


def _check_run(
    name: str = "ci",
    *,
    status: str = "COMPLETED",
    conclusion: str | None = "SUCCESS",
    required: bool = True,
) -> dict[str, object]:
    return {
        "__typename": "CheckRun",
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "isRequired": required,
    }


def _status_context(
    context: str = "lint", *, state: str = "SUCCESS", required: bool = False
) -> dict[str, object]:
    return {
        "__typename": "StatusContext",
        "context": context,
        "state": state,
        "isRequired": required,
    }


def _land_payload(
    *,
    scalars: dict[str, object] | None = None,
    rollup: object = "unset",
    checks: list[dict[str, object]] | None = None,
    checks_page: dict[str, object] | None = None,
    threads: list[bool] | None = None,
    threads_page: dict[str, object] | None = None,
    commits_nodes: object = None,
) -> str:
    node: dict[str, object] = {
        "number": 42,
        "state": "OPEN",
        "isDraft": False,
        "baseRefName": "main",
        "headRefName": "plan-42",
        "headRefOid": "a" * 40,
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN",
        "reviewDecision": "APPROVED",
    }
    node.update(scalars or {})
    if rollup == "unset":
        rollup_value: object = {
            "state": "SUCCESS",
            "contexts": {
                "nodes": checks if checks is not None else [_check_run()],
                "pageInfo": checks_page
                if checks_page is not None
                else {"hasNextPage": False, "endCursor": "c-end"},
            },
        }
    else:
        rollup_value = rollup
    node["commits"] = {
        "nodes": commits_nodes
        if commits_nodes is not None
        else [{"commit": {"statusCheckRollup": rollup_value}}]
    }
    node["reviewThreads"] = {
        "nodes": [
            {"isResolved": resolved} for resolved in (threads if threads is not None else [])
        ],
        "pageInfo": threads_page
        if threads_page is not None
        else {"hasNextPage": False, "endCursor": "t-end"},
    }
    return json.dumps({"data": {"repository": {"pullRequest": node}}})


class _GhSequence:
    """Route the owner/repo read via predicate, then serve graphql calls IN SEQUENCE (the
    pagination fixtures need per-request replies that `_GhDispatch`'s first-match cannot
    express)."""

    def __init__(self, pages: list[_Proc]) -> None:
        self._pages = list(pages)
        self.calls: list[list[str]] = []

    def __call__(self, args, **_):
        gh = args[1:]
        self.calls.append(gh)
        if any("nameWithOwner" in tok for tok in gh):
            return _Proc(0, "octo/repo\n")
        if self._pages:
            return self._pages.pop(0)
        return _Proc(1, stderr="unexpected extra graphql request")

    def graphql_calls(self) -> list[list[str]]:
        return [c for c in self.calls if "graphql" in c]


def test_pr_land_facts_happy_path_and_argv(monkeypatch):
    payload = _land_payload(
        checks=[
            _check_run("ci", conclusion="SUCCESS", required=True),
            _status_context("lint", state="PENDING", required=False),
        ],
        threads=[True, False, False],
    )
    rec = _GhSequence([_Proc(0, payload)])
    monkeypatch.setattr(subprocess, "run", rec)
    facts = stacks.pr_land_facts(number=42, repo_root=ROOT)
    assert facts == stacks.PrLandFacts(
        number=42,
        state="OPEN",
        is_draft=False,
        base_ref="main",
        head_ref="plan-42",
        head_sha="a" * 40,
        mergeable="MERGEABLE",
        merge_state_status="CLEAN",
        review_decision="APPROVED",
        rollup_state="SUCCESS",
        checks=(
            stacks.CheckFacts(name="ci", is_required=True, outcome="passed"),
            stacks.CheckFacts(name="lint", is_required=False, outcome="pending"),
        ),
        unresolved_thread_count=2,
    )
    (graphql_call,) = rec.graphql_calls()
    assert graphql_call[:2] == ["api", "graphql"]
    assert f"query={stacks.PR_LAND_READINESS_QUERY}" in graphql_call
    assert "owner=octo" in graphql_call and "repo=repo" in graphql_call
    assert "number=42" in graphql_call
    assert graphql_call[graphql_call.index("number=42") - 1] == "-F"
    # First request: both cursors omitted (null).
    assert not any("checksCursor=" in tok or "threadsCursor=" in tok for tok in graphql_call)


def test_pr_land_facts_not_found_returns_none(monkeypatch):
    rec = _GhSequence(
        [_Proc(1, stderr="GraphQL: Could not resolve to a PullRequest (pullRequest)")]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    assert stacks.pr_land_facts(number=999, repo_root=ROOT) is None


def test_pr_land_facts_infra_failure_raises(monkeypatch):
    rec = _GhSequence([_Proc(1, stderr="HTTP 500")])
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(GitHubError, match="landing readiness for PR #42"):
        stacks.pr_land_facts(number=42, repo_root=ROOT)


@pytest.mark.parametrize(
    "mutation",
    [
        {"mergeable": None},  # missing/null mergeable
        {"mergeable": "WEIRD"},  # unknown enum value
        {"mergeStateStatus": "ODD"},
        {"reviewDecision": "MAYBE"},
        {"state": "HALF_OPEN"},
    ],
)
def test_pr_land_facts_bad_scalars_raise(monkeypatch, mutation):
    rec = _GhSequence([_Proc(0, _land_payload(scalars=mutation))])
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(GitHubError, match="landing readiness for PR #42"):
        stacks.pr_land_facts(number=42, repo_root=ROOT)


def test_pr_land_facts_empty_page_info_raises(monkeypatch):
    rec = _GhSequence([_Proc(0, _land_payload(checks_page={}))])
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(GitHubError, match="landing readiness for PR #42"):
        stacks.pr_land_facts(number=42, repo_root=ROOT)


def _payload_without(*path: str | int) -> str:
    """A happy payload with the node at ``path`` (rooted at the PR node) DELETED — a truly
    omitted key, not a null one (the strict boundary must reject both, and a future field
    default would only mask the omitted arm)."""
    payload = json.loads(_land_payload())
    node = payload["data"]["repository"]["pullRequest"]
    for step in path[:-1]:
        node = node[step]
    del node[path[-1]]
    return json.dumps(payload)


def test_pr_land_facts_omitted_mergeable_key_raises(monkeypatch):
    rec = _GhSequence([_Proc(0, _payload_without("mergeable"))])
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(GitHubError, match="landing readiness for PR #42"):
        stacks.pr_land_facts(number=42, repo_root=ROOT)


def test_pr_land_facts_omitted_page_info_key_raises(monkeypatch):
    rec = _GhSequence(
        [
            _Proc(
                0,
                _payload_without(
                    "commits", "nodes", 0, "commit", "statusCheckRollup", "contexts", "pageInfo"
                ),
            )
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(GitHubError, match="landing readiness for PR #42"):
        stacks.pr_land_facts(number=42, repo_root=ROOT)


def test_pr_land_facts_wrong_pr_number_in_payload_raises(monkeypatch):
    # The identity check: a zero-exit payload carrying a DIFFERENT PR node must never become
    # the requested PR's readiness evidence.
    rec = _GhSequence([_Proc(0, _land_payload(scalars={"number": 43}))])
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(GitHubError, match=r"carries PR #43, expected #42"):
        stacks.pr_land_facts(number=42, repo_root=ROOT)


def test_pr_land_facts_unknown_check_typename_raises(monkeypatch):
    rec = _GhSequence([_Proc(0, _land_payload(checks=[{"__typename": "Mystery"}]))])
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(GitHubError, match="check context 'Mystery'"):
        stacks.pr_land_facts(number=42, repo_root=ROOT)


def test_pr_land_facts_empty_commits_nodes_is_malformed(monkeypatch):
    # A PR always has ≥1 commit — an empty commits.nodes is malformed authority, never
    # silently "no checks".
    rec = _GhSequence([_Proc(0, _land_payload(commits_nodes=[]))])
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(GitHubError, match=r"empty commits\.nodes"):
        stacks.pr_land_facts(number=42, repo_root=ROOT)


@pytest.mark.parametrize(
    ("nodes", "match"),
    [
        ("junk", r"malformed commits\.nodes"),  # not a list at all
        (["junk"], r"malformed commits\.nodes"),  # sole element is not a dict
        (
            # last: 1 fixes the cardinality — a second element (even beside a junk first
            # one) is malformed authority, never tolerantly filtered down to a usable node.
            [None, {"commit": {"statusCheckRollup": None}}],
            r"2 commits\.nodes",
        ),
    ],
)
def test_pr_land_facts_malformed_commits_nodes_raise(monkeypatch, nodes, match):
    rec = _GhSequence([_Proc(0, _land_payload(commits_nodes=nodes))])
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(GitHubError, match=match):
        stacks.pr_land_facts(number=42, repo_root=ROOT)


def test_pr_land_facts_null_review_decision_and_null_rollup(monkeypatch):
    # Both nullable arms: reviewDecision null (base requires no review) and a null
    # statusCheckRollup (no checks at all).
    payload = _land_payload(scalars={"reviewDecision": None}, rollup=None, threads=[True])
    rec = _GhSequence([_Proc(0, payload)])
    monkeypatch.setattr(subprocess, "run", rec)
    facts = stacks.pr_land_facts(number=42, repo_root=ROOT)
    assert facts is not None
    assert facts.review_decision is None
    assert facts.rollup_state is None and facts.checks == ()
    assert facts.unresolved_thread_count == 0


@pytest.mark.parametrize(
    ("node", "outcome"),
    [
        (_check_run(status="IN_PROGRESS", conclusion=None), "pending"),
        (_check_run(status="QUEUED", conclusion=None), "pending"),
        (_check_run(conclusion="SUCCESS"), "passed"),
        (_check_run(conclusion="NEUTRAL"), "passed"),
        (_check_run(conclusion="SKIPPED"), "passed"),
        (_check_run(conclusion="FAILURE"), "failed"),
        (_check_run(conclusion="TIMED_OUT"), "failed"),
        (_check_run(conclusion="CANCELLED"), "failed"),
        (_check_run(conclusion="ACTION_REQUIRED"), "failed"),
        (_check_run(conclusion="STALE"), "failed"),
        (_check_run(conclusion="STARTUP_FAILURE"), "failed"),
        # COMPLETED + null conclusion is contradictory — fail-closed: pending, never passed.
        (_check_run(status="COMPLETED", conclusion=None), "pending"),
        (_status_context(state="SUCCESS"), "passed"),
        (_status_context(state="ERROR"), "failed"),
        (_status_context(state="FAILURE"), "failed"),
        (_status_context(state="EXPECTED"), "pending"),
        (_status_context(state="PENDING"), "pending"),
    ],
)
def test_pr_land_facts_check_outcome_normalization(monkeypatch, node, outcome):
    rec = _GhSequence([_Proc(0, _land_payload(checks=[node]))])
    monkeypatch.setattr(subprocess, "run", rec)
    facts = stacks.pr_land_facts(number=42, repo_root=ROOT)
    assert facts is not None
    assert facts.checks[0].outcome == outcome


def test_pr_land_facts_two_page_pagination_advances_cursors_independently(monkeypatch):
    # Page 1: both connections have another page. Page 2: checks exhaust, threads continue.
    # Page 3: threads exhaust — and the checks connection's re-returned nodes are IGNORED
    # (never re-accumulated after exhaustion).
    page1 = _land_payload(
        checks=[_check_run("ci-1")],
        checks_page={"hasNextPage": True, "endCursor": "c1"},
        threads=[False],
        threads_page={"hasNextPage": True, "endCursor": "t1"},
    )
    page2 = _land_payload(
        checks=[_check_run("ci-2")],
        checks_page={"hasNextPage": False, "endCursor": "c2"},
        threads=[False],
        threads_page={"hasNextPage": True, "endCursor": "t2"},
    )
    page3 = _land_payload(
        checks=[_check_run("ci-ghost")],  # re-returned after exhaustion: must be ignored
        checks_page={"hasNextPage": False, "endCursor": "c2"},
        threads=[False],
        threads_page={"hasNextPage": False, "endCursor": "t3"},
    )
    rec = _GhSequence([_Proc(0, page1), _Proc(0, page2), _Proc(0, page3)])
    monkeypatch.setattr(subprocess, "run", rec)
    facts = stacks.pr_land_facts(number=42, repo_root=ROOT)
    assert facts is not None
    assert [c.name for c in facts.checks] == ["ci-1", "ci-2"]
    assert facts.unresolved_thread_count == 3
    calls = rec.graphql_calls()
    assert len(calls) == 3
    assert not any("checksCursor=" in tok for tok in calls[0])
    assert "checksCursor=c1" in calls[1] and "threadsCursor=t1" in calls[1]
    # The exhausted checks connection keeps its final cursor; threads advance to t2.
    assert "checksCursor=c2" in calls[2] and "threadsCursor=t2" in calls[2]


def test_pr_land_facts_scalar_change_between_pages_raises(monkeypatch):
    # The scalar-coherence guard: a headRefOid changing between pages means checks/threads
    # would be combined across different commits — refuse the whole read.
    page1 = _land_payload(threads_page={"hasNextPage": True, "endCursor": "t1"})
    page2 = _land_payload(
        scalars={"headRefOid": "b" * 40},
        threads_page={"hasNextPage": False, "endCursor": "t2"},
    )
    rec = _GhSequence([_Proc(0, page1), _Proc(0, page2)])
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(GitHubError, match="PR changed during the readiness read"):
        stacks.pr_land_facts(number=42, repo_root=ROOT)


def test_pr_land_facts_non_advancing_cursor_raises(monkeypatch):
    page1 = _land_payload(threads_page={"hasNextPage": True, "endCursor": "t1"})
    page2 = _land_payload(threads_page={"hasNextPage": True, "endCursor": "t1"})
    rec = _GhSequence([_Proc(0, page1), _Proc(0, page2)])
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(GitHubError, match="non-advancing review threads pagination"):
        stacks.pr_land_facts(number=42, repo_root=ROOT)


def test_pr_land_facts_null_continuing_cursor_raises(monkeypatch):
    page1 = _land_payload(threads_page={"hasNextPage": True, "endCursor": None})
    rec = _GhSequence([_Proc(0, page1)])
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(GitHubError, match="non-advancing review threads pagination"):
        stacks.pr_land_facts(number=42, repo_root=ROOT)


def test_pr_land_facts_request_cap_raises(monkeypatch):
    # A pathologically deep (but always-advancing) connection breaches the 20-request cap.
    pages = [
        _Proc(0, _land_payload(threads_page={"hasNextPage": True, "endCursor": f"t{i}"}))
        for i in range(25)
    ]
    rec = _GhSequence(pages)
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(GitHubError, match="pagination exceeded 20 requests"):
        stacks.pr_land_facts(number=42, repo_root=ROOT)
    assert len(rec.graphql_calls()) == 20


# --- the REST write surface (§8.47) ---------------------------------------------------


def _rest_stack(number: int = 3, *prs: int) -> dict[str, object]:
    """A REST stack resource with members bottom→top (extra resource fields kept — the
    lenient parse ignores them)."""
    return {
        "id": 900 + number,
        "number": number,
        "node_id": "ST_x",
        "url": f"https://gh/o/r/stacks/{number}",
        "base": {"ref": "main"},
        "open": True,
        "created_at": "2026-01-01T00:00:00Z",
        "pull_requests": [
            {
                "number": pr,
                "state": "open",
                "draft": True,
                "merged_at": None,
                "head": {"ref": f"plan-{pr}", "sha": format(pr, "x") * 20},
            }
            for pr in prs
        ],
    }


def test_stack_for_pr_happy_path_preserves_bottom_to_top_order(monkeypatch):
    rec = _GhDispatch(
        [(_has("stacks", "pull_request=55"), _Proc(0, json.dumps([_rest_stack(3, 55, 56)])))]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    facts = stacks.stack_for_pr(number=55, repo_root=ROOT)
    assert facts is not None
    assert facts.number == 3 and facts.size == 2
    assert facts.member_numbers == (55, 56)
    assert facts.entries[0].head_ref == "plan-55" and facts.entries[0].draft is True
    assert facts.entries[0].merged is False
    # The exact REST argv: GET with the pull_request filter field.
    call = rec.calls[-1]
    assert call[0] == "api" and call[1] == "repos/{owner}/{repo}/stacks"
    assert call[2:4] == ["-X", "GET"]
    assert "pull_request=55" in call


def test_stack_for_pr_empty_array_is_none(monkeypatch):
    rec = _GhDispatch([(_has("stacks"), _Proc(0, "[]"))])
    monkeypatch.setattr(subprocess, "run", rec)
    assert stacks.stack_for_pr(number=55, repo_root=ROOT) is None


def test_stack_for_pr_empty_output_raises(monkeypatch):
    # A successful process with EMPTY stdout is a malformed authority reply — only a literal
    # `[]` payload means "in no stack"; the mutation-adjacent read fails closed.
    rec = _GhDispatch([(_has("stacks"), _Proc(0, ""))])
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(GitHubError, match="stacks"):
        stacks.stack_for_pr(number=55, repo_root=ROOT)


def test_stack_for_pr_404_raises(monkeypatch):
    # 404 = stacked PRs unavailable for the repo — the strict authority read fails loudly
    # (deliberately unlike the tolerant preview read pr_stack).
    rec = _GhDispatch([(_has("stacks"), _Proc(1, stderr="HTTP 404: Not Found"))])
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(GitHubError, match="native stack for PR #55"):
        stacks.stack_for_pr(number=55, repo_root=ROOT)


@pytest.mark.parametrize(
    "payload",
    [
        {"message": "not a list"},
        [{"number": "junk", "pull_requests": []}],
        [{"number": 3, "pull_requests": [{"number": 55}]}],  # member missing state/draft/head
        [  # member with an OMITTED merged_at — required-but-nullable, never silently False
            {
                "number": 3,
                "pull_requests": [
                    {
                        "number": 55,
                        "state": "open",
                        "draft": True,
                        "head": {"ref": "plan-55", "sha": "a" * 40},
                    }
                ],
            }
        ],
    ],
)
def test_stack_for_pr_malformed_payload_raises(monkeypatch, payload):
    rec = _GhDispatch([(_has("stacks"), _Proc(0, json.dumps(payload)))])
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(GitHubError):
        stacks.stack_for_pr(number=55, repo_root=ROOT)


def test_stack_for_pr_multiple_stacks_raises(monkeypatch):
    # A PR belongs to at most one stack; a multi-stack reply is a malformed authority read.
    rec = _GhDispatch(
        [(_has("stacks"), _Proc(0, json.dumps([_rest_stack(3, 55), _rest_stack(4, 55)])))]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(GitHubError, match=">1 stack"):
        stacks.stack_for_pr(number=55, repo_root=ROOT)


class _InputCapture:
    """Route `gh` argv like `_GhDispatch` while reading `--input <file>` bodies at call time
    (the temp body file is deleted when the contextmanager exits)."""

    def __init__(self, proc: _Proc) -> None:
        self._proc = proc
        self.calls: list[list[str]] = []
        self.input_bodies: list[str] = []

    def __call__(self, args, **_):
        gh = args[1:]
        self.calls.append(gh)
        if "--input" in gh:
            from pathlib import Path

            self.input_bodies.append(Path(gh[gh.index("--input") + 1]).read_text(encoding="utf-8"))
        return self._proc


def _http(status_line: str, headers: dict[str, str], body: str) -> str:
    head = "\n".join([status_line, *[f"{k}: {v}" for k, v in headers.items()]])
    return f"{head}\n\n{body}"


def test_create_stack_argv_body_and_applied(monkeypatch):
    stdout = _http(
        "HTTP/2.0 201 Created",
        {"Content-Type": "application/json"},
        json.dumps(_rest_stack(3, 55, 56)),
    )
    rec = _InputCapture(_Proc(0, stdout))
    monkeypatch.setattr(subprocess, "run", rec)
    outcome = stacks.create_stack(pull_requests=[55, 56], repo_root=ROOT)
    assert outcome.applied is True and outcome.status == 201
    assert outcome.rate_limited is False and outcome.retry_after_seconds is None
    assert outcome.stack is not None and outcome.stack.member_numbers == (55, 56)
    call = rec.calls[-1]
    assert call[:5] == ["api", "repos/{owner}/{repo}/stacks", "-X", "POST", "--include"]
    assert json.loads(rec.input_bodies[-1]) == {"pull_requests": [55, 56]}


def test_append_to_stack_argv_and_body(monkeypatch):
    stdout = _http("HTTP/2.0 200 OK", {}, json.dumps(_rest_stack(3, 55, 56, 57)))
    rec = _InputCapture(_Proc(0, stdout))
    monkeypatch.setattr(subprocess, "run", rec)
    outcome = stacks.append_to_stack(stack_number=3, pull_requests=[57], repo_root=ROOT)
    assert outcome.applied is True and outcome.status == 200
    assert outcome.stack is not None and outcome.stack.member_numbers == (55, 56, 57)
    call = rec.calls[-1]
    assert call[:5] == ["api", "repos/{owner}/{repo}/stacks/3/add", "-X", "POST", "--include"]
    assert json.loads(rec.input_bodies[-1]) == {"pull_requests": [57]}


def test_stack_mutation_429_parses_retry_after(monkeypatch):
    stdout = _http(
        "HTTP/2.0 429 Too Many Requests",
        {"Retry-After": "30"},
        json.dumps({"message": "rate limited"}),
    )
    rec = _InputCapture(_Proc(1, stdout, stderr="gh: HTTP 429"))
    monkeypatch.setattr(subprocess, "run", rec)
    outcome = stacks.create_stack(pull_requests=[55, 56], repo_root=ROOT)
    assert outcome.applied is False and outcome.status == 429
    assert outcome.rate_limited is True and outcome.retry_after_seconds == 30


def test_stack_mutation_403_rate_limit_folds(monkeypatch):
    stdout = _http("HTTP/2.0 403 Forbidden", {}, json.dumps({"message": "API rate limit exceeded"}))
    rec = _InputCapture(_Proc(1, stdout, stderr=""))
    monkeypatch.setattr(subprocess, "run", rec)
    outcome = stacks.create_stack(pull_requests=[55, 56], repo_root=ROOT)
    assert outcome.applied is False and outcome.status == 403
    assert outcome.rate_limited is True


def test_stack_mutation_plain_403_is_not_rate_limited(monkeypatch):
    stdout = _http("HTTP/2.0 403 Forbidden", {}, json.dumps({"message": "Must have admin"}))
    rec = _InputCapture(_Proc(1, stdout))
    monkeypatch.setattr(subprocess, "run", rec)
    outcome = stacks.create_stack(pull_requests=[55, 56], repo_root=ROOT)
    assert outcome.rate_limited is False and outcome.status == 403


def test_stack_mutation_5xx_carries_status(monkeypatch):
    stdout = _http("HTTP/2.0 502 Bad Gateway", {}, "")
    rec = _InputCapture(_Proc(1, stdout, stderr="gh: HTTP 502"))
    monkeypatch.setattr(subprocess, "run", rec)
    outcome = stacks.create_stack(pull_requests=[55, 56], repo_root=ROOT)
    assert outcome.applied is False and outcome.status == 502
    assert "502" in outcome.raw_detail


def test_stack_mutation_network_failure_is_ambiguous_none_status(monkeypatch):
    # The process died before an HTTP status was observable (a timeout) — the total helper
    # returns the ambiguous arm rather than raising; refetch-and-classify decides.
    def _boom(args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=args, timeout=30)

    monkeypatch.setattr(subprocess, "run", _boom)
    outcome = stacks.create_stack(pull_requests=[55, 56], repo_root=ROOT)
    assert outcome.applied is False and outcome.status is None
    assert outcome.rate_limited is False and outcome.retry_after_seconds is None


def test_stack_mutation_2xx_unparseable_body_is_not_applied(monkeypatch):
    # A 2xx whose body fails to parse returns applied=False WITH the 2xx status — the
    # caller's refetch decides; the helper stays total.
    stdout = _http("HTTP/2.0 201 Created", {}, "not json")
    rec = _InputCapture(_Proc(0, stdout))
    monkeypatch.setattr(subprocess, "run", rec)
    outcome = stacks.create_stack(pull_requests=[55, 56], repo_root=ROOT)
    assert outcome.applied is False and outcome.status == 201
    assert outcome.stack is None


def test_stack_mutation_redirect_uses_last_status_line(monkeypatch):
    # `--include` prints one head block per hop — the LAST HTTP/ status line wins.
    stdout = "HTTP/2.0 307 Temporary Redirect\nLocation: elsewhere\n\n" + _http(
        "HTTP/2.0 200 OK", {}, json.dumps(_rest_stack(3, 55, 56))
    )
    rec = _InputCapture(_Proc(0, stdout))
    monkeypatch.setattr(subprocess, "run", rec)
    outcome = stacks.create_stack(pull_requests=[55, 56], repo_root=ROOT)
    assert outcome.applied is True and outcome.status == 200


# --- the landing write surface (§8.56) -------------------------------------------------


def _async_pending(uuid: str = "u-1", *, expected: str = "a" * 40) -> str:
    return json.dumps(
        {
            "status": "pending",
            "details": {
                "uuid": uuid,
                "merge_method": "squash",
                "merge_action": "direct_merge",
                "expected_head_sha": expected,
                "message": "queued",
            },
        }
    )


def test_submit_merge_async_argv_body_and_202_pending(monkeypatch):
    stdout = _http("HTTP/2.0 202 Accepted", {}, _async_pending())
    rec = _InputCapture(_Proc(0, stdout))
    monkeypatch.setattr(subprocess, "run", rec)
    outcome = stacks.submit_merge_async(number=77, sha="a" * 40, repo_root=ROOT)
    assert outcome.status == 202 and outcome.state == "pending"
    assert outcome.uuid == "u-1"
    assert outcome.merge_method == "squash" and outcome.merge_action == "direct_merge"
    assert outcome.expected_head_sha == "a" * 40
    assert outcome.rate_limited is False and outcome.retry_after_seconds is None
    call = rec.calls[-1]
    expected_argv = ["api", "repos/{owner}/{repo}/pulls/77/merge-async", "-X", "PUT", "--include"]
    assert call[:5] == expected_argv
    # The body is EXACTLY the three pinned fields — incl. the `sha` head-pin, no commit text.
    assert json.loads(rec.input_bodies[-1]) == {
        "merge_action": "direct_merge",
        "merge_method": "squash",
        "sha": "a" * 40,
    }


def test_submit_merge_async_200_merged(monkeypatch):
    stdout = _http("HTTP/2.0 200 OK", {}, json.dumps({"status": "merged"}))
    rec = _InputCapture(_Proc(0, stdout))
    monkeypatch.setattr(subprocess, "run", rec)
    outcome = stacks.submit_merge_async(number=77, sha="a" * 40, repo_root=ROOT)
    assert outcome.status == 200 and outcome.state == "merged"
    assert outcome.uuid is None


def test_submit_merge_async_409_existing_pending_request(monkeypatch):
    # A 409 carries an EXISTING merge request whose options may differ — the caller verifies.
    stdout = _http("HTTP/2.0 409 Conflict", {}, _async_pending("u-foreign", expected="b" * 40))
    rec = _InputCapture(_Proc(1, stdout, stderr="gh: HTTP 409"))
    monkeypatch.setattr(subprocess, "run", rec)
    outcome = stacks.submit_merge_async(number=77, sha="a" * 40, repo_root=ROOT)
    assert outcome.status == 409 and outcome.state == "pending"
    assert outcome.uuid == "u-foreign" and outcome.expected_head_sha == "b" * 40


def test_submit_merge_async_400_failed(monkeypatch):
    stdout = _http("HTTP/2.0 400 Bad Request", {}, json.dumps({"status": "failed"}))
    rec = _InputCapture(_Proc(1, stdout, stderr="gh: HTTP 400"))
    monkeypatch.setattr(subprocess, "run", rec)
    outcome = stacks.submit_merge_async(number=77, sha="a" * 40, repo_root=ROOT)
    assert outcome.status == 400 and outcome.state == "failed"


def test_submit_merge_async_404_and_422_carry_status(monkeypatch):
    for status_line, code in (("HTTP/2.0 404 Not Found", 404), ("HTTP/2.0 422 Bad", 422)):
        rec = _InputCapture(_Proc(1, _http(status_line, {}, json.dumps({"message": "nope"}))))
        monkeypatch.setattr(subprocess, "run", rec)
        outcome = stacks.submit_merge_async(number=77, sha="a" * 40, repo_root=ROOT)
        assert outcome.status == code and outcome.state is None


def test_submit_merge_async_unparseable_2xx_body_is_state_none(monkeypatch):
    stdout = _http("HTTP/2.0 202 Accepted", {}, "not json")
    rec = _InputCapture(_Proc(0, stdout))
    monkeypatch.setattr(subprocess, "run", rec)
    outcome = stacks.submit_merge_async(number=77, sha="a" * 40, repo_root=ROOT)
    assert outcome.status == 202 and outcome.state is None  # ambiguous — never guessed success


def test_submit_merge_async_spawn_failure_is_ambiguous(monkeypatch):
    def _boom(args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=args, timeout=30)

    monkeypatch.setattr(subprocess, "run", _boom)
    outcome = stacks.submit_merge_async(number=77, sha="a" * 40, repo_root=ROOT)
    assert outcome.status is None and outcome.state is None
    assert "submit async merge" in outcome.raw_detail


def test_submit_merge_async_retry_after_and_rate_limit(monkeypatch):
    stdout = _http(
        "HTTP/2.0 429 Too Many Requests",
        {"Retry-After": "12"},
        json.dumps({"message": "rate limited"}),
    )
    rec = _InputCapture(_Proc(1, stdout))
    monkeypatch.setattr(subprocess, "run", rec)
    outcome = stacks.submit_merge_async(number=77, sha="a" * 40, repo_root=ROOT)
    assert outcome.rate_limited is True and outcome.retry_after_seconds == 12


def test_merge_async_result_pending_merged_enqueued_failed(monkeypatch):
    for state, details, sha in (
        ("pending", {"uuid": "u-1", "message": "going"}, None),
        ("merged", {"sha": "c" * 40}, "c" * 40),
        ("enqueued", {}, None),
        ("failed", {"message": "conflict"}, None),
    ):
        rec = _GhDispatch(
            [
                (
                    _has("merge-async/u-1"),
                    _Proc(0, json.dumps({"status": state, "details": details})),
                )
            ]
        )
        monkeypatch.setattr(subprocess, "run", rec)
        result = stacks.merge_async_result(number=77, uuid="u-1", repo_root=ROOT)
        assert result.state == state and result.sha == sha
        call = rec.calls[-1]
        assert call[:2] == ["api", "repos/{owner}/{repo}/pulls/77/merge-async/u-1"]


def test_merge_async_result_merged_without_sha_raises(monkeypatch):
    rec = _GhDispatch([(_has("merge-async"), _Proc(0, json.dumps({"status": "merged"})))])
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(GitHubError, match=r"merged without details\.sha"):
        stacks.merge_async_result(number=77, uuid="u-1", repo_root=ROOT)


def test_merge_async_result_unknown_status_raises(monkeypatch):
    rec = _GhDispatch([(_has("merge-async"), _Proc(0, json.dumps({"status": "sideways"})))])
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(GitHubError, match="status 'sideways'"):
        stacks.merge_async_result(number=77, uuid="u-1", repo_root=ROOT)


def test_merge_async_result_404_raises(monkeypatch):
    rec = _GhDispatch([(_has("merge-async"), _Proc(1, stderr="HTTP 404: Not Found"))])
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(GitHubError, match="poll async merge"):
        stacks.merge_async_result(number=77, uuid="u-1", repo_root=ROOT)


@pytest.mark.parametrize("body", ["not json", "[]", json.dumps({"details": {}})])
def test_merge_async_result_malformed_raises(monkeypatch, body):
    rec = _GhDispatch([(_has("merge-async"), _Proc(0, body))])
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(GitHubError):
        stacks.merge_async_result(number=77, uuid="u-1", repo_root=ROOT)


# --- the total recovery probe (§8.51) ---------------------------------------------------


def test_merge_async_probe_live_states_pass_through(monkeypatch):
    for state, details, sha in (
        ("pending", {"uuid": "u-1", "message": "going"}, None),
        ("merged", {"sha": "c" * 40}, "c" * 40),
        ("enqueued", {}, None),
        ("failed", {"message": "conflict"}, None),
    ):
        stdout = _http("HTTP/2.0 200 OK", {}, json.dumps({"status": state, "details": details}))
        rec = _InputCapture(_Proc(0, stdout))
        monkeypatch.setattr(subprocess, "run", rec)
        probe = stacks.merge_async_probe(number=77, uuid="u-1", repo_root=ROOT)
        assert probe.state == state and probe.sha == sha
        call = rec.calls[-1]
        assert call[:2] == ["api", "repos/{owner}/{repo}/pulls/77/merge-async/u-1"]
        assert "--include" in call


def test_merge_async_probe_exact_404_is_expired(monkeypatch):
    stdout = _http("HTTP/2.0 404 Not Found", {}, json.dumps({"message": "gone"}))
    rec = _InputCapture(_Proc(1, stdout, stderr="gh: HTTP 404"))
    monkeypatch.setattr(subprocess, "run", rec)
    probe = stacks.merge_async_probe(number=77, uuid="u-1", repo_root=ROOT)
    assert probe.state == "expired"


def test_merge_async_probe_merged_without_sha_is_unreadable(monkeypatch):
    stdout = _http("HTTP/2.0 200 OK", {}, json.dumps({"status": "merged"}))
    rec = _InputCapture(_Proc(0, stdout))
    monkeypatch.setattr(subprocess, "run", rec)
    probe = stacks.merge_async_probe(number=77, uuid="u-1", repo_root=ROOT)
    assert probe.state == "unreadable" and "details.sha" in probe.message


@pytest.mark.parametrize(
    "body", ["not json", "[]", json.dumps({"details": {}}), json.dumps({"status": "sideways"})]
)
def test_merge_async_probe_malformed_or_unknown_status_is_unreadable(monkeypatch, body):
    stdout = _http("HTTP/2.0 200 OK", {}, body)
    rec = _InputCapture(_Proc(0, stdout))
    monkeypatch.setattr(subprocess, "run", rec)
    probe = stacks.merge_async_probe(number=77, uuid="u-1", repo_root=ROOT)
    assert probe.state == "unreadable"


def test_merge_async_probe_infra_failures_are_unreadable_never_raise(monkeypatch):
    # Spawn death (no HTTP status at all).
    def _boom(args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=args, timeout=30)

    monkeypatch.setattr(subprocess, "run", _boom)
    probe = stacks.merge_async_probe(number=77, uuid="u-1", repo_root=ROOT)
    assert probe.state == "unreadable" and "probe async merge" in probe.message

    # A 5xx reply — even one carrying a parseable live state — is unreadable, never trusted.
    stdout = _http("HTTP/2.0 502 Bad Gateway", {}, json.dumps({"status": "pending"}))
    rec = _InputCapture(_Proc(1, stdout, stderr="gh: HTTP 502"))
    monkeypatch.setattr(subprocess, "run", rec)
    probe = stacks.merge_async_probe(number=77, uuid="u-1", repo_root=ROOT)
    assert probe.state == "unreadable" and "502" in probe.message


def test_merge_pr_direct_argv_body_and_200_sha(monkeypatch):
    stdout = _http("HTTP/2.0 200 OK", {}, json.dumps({"sha": "d" * 40, "merged": True}))
    rec = _InputCapture(_Proc(0, stdout))
    monkeypatch.setattr(subprocess, "run", rec)
    outcome = stacks.merge_pr_direct(
        number=55, sha="a" * 40, commit_message="title\n\nCloses #1", repo_root=ROOT
    )
    assert outcome.merged is True and outcome.status == 200
    assert outcome.sha == "d" * 40
    call = rec.calls[-1]
    assert call[:5] == ["api", "repos/{owner}/{repo}/pulls/55/merge", "-X", "PUT", "--include"]
    assert json.loads(rec.input_bodies[-1]) == {
        "merge_method": "squash",
        "sha": "a" * 40,
        "commit_message": "title\n\nCloses #1",
    }


def test_merge_pr_direct_none_message_omits_the_field(monkeypatch):
    stdout = _http("HTTP/2.0 200 OK", {}, json.dumps({"sha": "d" * 40}))
    rec = _InputCapture(_Proc(0, stdout))
    monkeypatch.setattr(subprocess, "run", rec)
    stacks.merge_pr_direct(number=55, sha="a" * 40, commit_message=None, repo_root=ROOT)
    assert json.loads(rec.input_bodies[-1]) == {"merge_method": "squash", "sha": "a" * 40}


def test_merge_pr_direct_already_merged_arm(monkeypatch):
    stdout = _http("HTTP/2.0 405 Method Not Allowed", {}, json.dumps({"message": "Already merged"}))
    rec = _InputCapture(_Proc(1, stdout, stderr=""))
    monkeypatch.setattr(subprocess, "run", rec)
    outcome = stacks.merge_pr_direct(number=55, sha="a" * 40, commit_message=None, repo_root=ROOT)
    assert outcome.merged is True and outcome.sha is None  # verification re-reads the commit


@pytest.mark.parametrize("status_line,code", [("HTTP/2.0 405 No", 405), ("HTTP/2.0 409 C", 409)])
def test_merge_pr_direct_rejected_is_not_merged(monkeypatch, status_line, code):
    stdout = _http(status_line, {}, json.dumps({"message": "Head branch was modified"}))
    rec = _InputCapture(_Proc(1, stdout, stderr=f"gh: HTTP {code}"))
    monkeypatch.setattr(subprocess, "run", rec)
    outcome = stacks.merge_pr_direct(number=55, sha="a" * 40, commit_message=None, repo_root=ROOT)
    assert outcome.merged is False and outcome.status == code
    assert "modified" in outcome.raw_detail or str(code) in outcome.raw_detail


def test_merge_pr_direct_ambiguous_spawn_failure(monkeypatch):
    def _boom(args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=args, timeout=30)

    monkeypatch.setattr(subprocess, "run", _boom)
    outcome = stacks.merge_pr_direct(number=55, sha="a" * 40, commit_message=None, repo_root=ROOT)
    assert outcome.merged is False and outcome.status is None


def _merged_evidence_payload(state: str = "MERGED", oid: str | None = "e" * 40) -> str:
    node: dict[str, object] = {
        "number": 55,
        "state": state,
        "baseRefName": "main",
        "headRefName": "plan-55",
        "headRefOid": "a" * 40,
        "mergeCommit": None if oid is None else {"oid": oid},
    }
    return json.dumps({"data": {"repository": {"pullRequest": node}}})


def test_pr_merged_evidence_merged_with_identity_and_oid(monkeypatch):
    rec = _GhDispatch(
        [_OWNER_REPO, (_has("graphql", "mergeCommit"), _Proc(0, _merged_evidence_payload()))]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    evidence = stacks.pr_merged_evidence(number=55, repo_root=ROOT)
    assert evidence == stacks.PrMergedEvidence(
        number=55,
        state="MERGED",
        base_ref="main",
        head_ref="plan-55",
        head_sha="a" * 40,
        merge_commit_sha="e" * 40,
    )
    call = rec.calls[-1]
    assert f"query={stacks.PR_MERGED_EVIDENCE_QUERY}" in call


def test_pr_merged_evidence_null_merge_commit(monkeypatch):
    rec = _GhDispatch(
        [
            _OWNER_REPO,
            (_has("graphql"), _Proc(0, _merged_evidence_payload(state="OPEN", oid=None))),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    evidence = stacks.pr_merged_evidence(number=55, repo_root=ROOT)
    assert evidence is not None
    assert evidence.state == "OPEN" and evidence.merge_commit_sha is None


def test_pr_merged_evidence_missing_pr_is_none(monkeypatch):
    rec = _GhDispatch(
        [
            _OWNER_REPO,
            (_has("graphql"), _Proc(1, stderr="Could not resolve to a PullRequest")),
        ]
    )
    monkeypatch.setattr(subprocess, "run", rec)
    assert stacks.pr_merged_evidence(number=55, repo_root=ROOT) is None


def test_pr_merged_evidence_zero_exit_null_node_is_none(monkeypatch):
    # The other missing-PR wire shape: a SUCCESSFUL reply carrying an explicitly-null
    # pullRequest node honors the same lookup convention (None, never a raise).
    payload = json.dumps({"data": {"repository": {"pullRequest": None}}})
    rec = _GhDispatch([_OWNER_REPO, (_has("graphql"), _Proc(0, payload))])
    monkeypatch.setattr(subprocess, "run", rec)
    assert stacks.pr_merged_evidence(number=55, repo_root=ROOT) is None


@pytest.mark.parametrize(
    "node",
    [
        {"number": 55, "state": "MERGED"},  # identity fields + mergeCommit omitted
        {  # mergeCommit key omitted entirely (wire-shape drift, never "not merged")
            "number": 55,
            "state": "MERGED",
            "baseRefName": "main",
            "headRefName": "plan-55",
            "headRefOid": "a" * 40,
        },
    ],
)
def test_pr_merged_evidence_malformed_raises(monkeypatch, node):
    payload = json.dumps({"data": {"repository": {"pullRequest": node}}})
    rec = _GhDispatch([_OWNER_REPO, (_has("graphql"), _Proc(0, payload))])
    monkeypatch.setattr(subprocess, "run", rec)
    with pytest.raises(GitHubError, match="merged evidence"):
        stacks.pr_merged_evidence(number=55, repo_root=ROOT)
