"""The stacked-authoring capability preflight (``perk/delivery/capability.py``, §8.45).

Pure composition over injected probe fakes: the all-pass report, each single-failure arm
(native stack, merge rules, an absent/unreadable remote base, a failing push URL), the
multi-push-URL all-must-pass rule, and the honest not-write-permission caveat on the push
probe's detail (success AND failure).
"""

from pathlib import Path

import pytest

from perk.delivery import capability
from perk.github import GitHubError, stacks
from perk.substrate.git import GitError

ROOT = Path("/repo")
SHA = "a" * 40


def _preflight(**overrides):
    probes = {
        "stack_probe": lambda _root: True,
        "merge_rules_probe": lambda _root, _base: stacks.MergeRules(
            squash_allowed=True, merge_queue_required=False
        ),
        "remote_head_probe": lambda _root, _base: SHA,
        "push_urls_probe": lambda _root: ["https://gh/octo/repo.git"],
        "atomic_push_probe": lambda _root, _url, _branch, _sha: None,
    }
    probes.update(overrides)
    return capability.preflight_stacked_authoring(ROOT, base="main", **probes)


def _check(report: capability.CapabilityReport, name: str) -> capability.CapabilityCheck:
    matches = [c for c in report.checks if c.name == name]
    assert matches, f"no {name!r} check in {report.checks!r}"
    return matches[0]


def test_all_pass_report():
    report = _preflight()
    assert report.ok is True
    assert report.failures() == ()
    assert [c.name for c in report.checks] == [
        "native-stack",
        "merge-rules",
        "remote-base",
        "atomic-push",
    ]
    # The honesty caveats ride the PASSING details too.
    assert "does not prove per-repository preview enrollment" in (
        _check(report, "native-stack").detail
    )
    assert "not branch write permission" in _check(report, "atomic-push").detail
    assert SHA in _check(report, "remote-base").detail


def test_native_stack_unavailable_fails_that_check_only():
    report = _preflight(stack_probe=lambda _root: False)
    assert report.ok is False
    assert [c.name for c in report.failures()] == ["native-stack"]
    assert "expected a PullRequest.stack field" in report.failures()[0].detail


def test_merge_rules_squash_disallowed_fails_with_expected_vs_observed():
    report = _preflight(
        merge_rules_probe=lambda _root, _base: stacks.MergeRules(
            squash_allowed=False, merge_queue_required=False
        )
    )
    failed = _check(report, "merge-rules")
    assert failed.ok is False
    assert "expected squash direct-merge allowed" in failed.detail
    assert "observed squash merge disallowed" in failed.detail


def test_merge_rules_merge_queue_required_fails():
    report = _preflight(
        merge_rules_probe=lambda _root, _base: stacks.MergeRules(
            squash_allowed=True, merge_queue_required=True
        )
    )
    failed = _check(report, "merge-rules")
    assert failed.ok is False and "merge queue required" in failed.detail


def test_merge_rules_read_failure_fails_closed():
    def _boom(_root, _base):
        raise GitHubError("HTTP 500")

    report = _preflight(merge_rules_probe=_boom)
    failed = _check(report, "merge-rules")
    assert failed.ok is False
    assert "could not verify" in failed.detail and "HTTP 500" in failed.detail


def test_absent_remote_base_is_a_capability_failure_and_skips_the_push_probe():
    pushed: list[str] = []

    def _push(_root, url, _branch, _sha):
        pushed.append(url)

    report = _preflight(remote_head_probe=lambda _root, _base: None, atomic_push_probe=_push)
    failed = _check(report, "remote-base")
    assert failed.ok is False
    assert "observed no such remote branch" in failed.detail
    assert pushed == []  # no SHA to probe with
    assert all(c.name != "atomic-push" for c in report.checks)


def test_remote_base_read_failure_is_a_failed_check_not_a_crash():
    def _boom(_root, _base):
        raise GitError("ls-remote timed out")

    report = _preflight(remote_head_probe=_boom)
    failed = _check(report, "remote-base")
    assert failed.ok is False and "ls-remote timed out" in failed.detail


def test_every_push_url_is_probed_and_all_must_pass():
    def _push(_root, url, branch, sha):
        assert branch == "main" and sha == SHA
        if "mirror" in url:
            raise GitError("atomic push not supported by the receiving end")

    report = _preflight(
        push_urls_probe=lambda _root: ["https://gh/a.git", "https://gh/mirror.git"],
        atomic_push_probe=_push,
    )
    push_checks = [c for c in report.checks if c.name == "atomic-push"]
    assert [c.ok for c in push_checks] == [True, False]
    assert report.ok is False
    failed = report.failures()[0]
    assert "https://gh/mirror.git" in failed.detail
    assert "not branch write permission" in failed.detail  # the caveat rides failure too
    assert "atomic push not supported" in failed.detail


def test_no_push_urls_is_a_failed_check():
    report = _preflight(push_urls_probe=lambda _root: [])
    failed = _check(report, "atomic-push")
    assert failed.ok is False and "observed none" in failed.detail


def test_push_urls_read_failure_is_a_failed_check():
    def _boom(_root):
        raise GitError("no such remote")

    report = _preflight(push_urls_probe=_boom)
    failed = _check(report, "atomic-push")
    assert failed.ok is False and "no such remote" in failed.detail


def test_production_defaults_are_the_real_probes():
    # The injectable seams default to the production probe functions (wiring, not behavior).
    import inspect

    sig = inspect.signature(capability.preflight_stacked_authoring)
    assert sig.parameters["stack_probe"].default is stacks.stack_capability
    assert sig.parameters["merge_rules_probe"].default is stacks.base_merge_rules
    with pytest.raises(TypeError):
        capability.preflight_stacked_authoring(ROOT)  # base is keyword-required
