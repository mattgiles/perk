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
