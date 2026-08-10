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
