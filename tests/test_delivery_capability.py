"""Focused coverage for private capability rows and the retained sync push helper."""

import subprocess
from pathlib import Path

import pytest

from perk.delivery import capability
from perk.substrate.git import GitError

ROOT = Path("/repo")
SHA = "a" * 40


def test_private_success_rows_retain_both_honesty_caveats() -> None:
    native = capability._native_stack_check(True)
    atomic = capability._atomic_push_check("https://gh/octo/repo.git")

    assert native.ok is True
    assert native.detail == (
        "the GraphQL schema exposes PullRequest.stack on this GitHub host — the native-stack "
        "API surface exists (schema presence does not prove per-repository preview enrollment; "
        "the end-to-end dogfood does)"
    )
    assert atomic.ok is True
    assert atomic.detail == (
        "the no-op --atomic --dry-run push to https://gh/octo/repo.git succeeded "
        "(proves server capability and authentication, not branch write permission)"
    )


def test_private_atomic_failure_row_retains_the_permission_caveat() -> None:
    failed = capability._atomic_push_check("https://gh/mirror.git", error="atomic push unsupported")

    assert failed.ok is False
    assert failed.detail == (
        "the no-op --atomic --dry-run push to https://gh/mirror.git failed "
        "(proves server capability and authentication, not branch write permission): "
        "atomic push unsupported"
    )


def test_probe_atomic_push_urls_probes_each_url_with_the_given_refspec() -> None:
    calls: list[tuple[str, str, str]] = []

    def probe(_root: Path, url: str, branch: str, sha: str) -> None:
        calls.append((url, branch, sha))
        if url == "/bogus/mirror.git":
            raise GitError("no atomic")

    checks = capability.probe_atomic_push_urls(
        ROOT,
        ref_branch="plan-101",
        ref_sha=SHA,
        push_urls_probe=lambda _root: ["https://gh/octo/repo.git", "/bogus/mirror.git"],
        atomic_push_probe=probe,
    )

    assert calls == [
        ("https://gh/octo/repo.git", "plan-101", SHA),
        ("/bogus/mirror.git", "plan-101", SHA),
    ]
    assert [(check.name, check.ok) for check in checks] == [
        ("atomic-push", True),
        ("atomic-push", False),
    ]
    assert "not branch write permission" in checks[0].detail
    assert "no atomic" in checks[1].detail


def test_probe_atomic_push_urls_reuses_resolved_urls() -> None:
    checks = capability.probe_atomic_push_urls(
        ROOT,
        ref_branch="main",
        ref_sha=SHA,
        push_urls_probe=lambda _root: pytest.fail("URLs must not be resolved twice"),
        atomic_push_probe=lambda _root, _url, _branch, _sha: None,
        resolved_push_urls=["https://gh/octo/repo.git"],
    )

    assert len(checks) == 1 and checks[0].ok is True


def test_probe_atomic_push_urls_unresolvable_and_empty_urls_are_failed_rows() -> None:
    def boom(_root: Path) -> list[str]:
        raise GitError("no remote")

    (failed,) = capability.probe_atomic_push_urls(
        ROOT, ref_branch="main", ref_sha=SHA, push_urls_probe=boom
    )
    assert failed.ok is False
    assert failed.detail == "could not resolve the push URLs for origin: no remote"

    (empty,) = capability.probe_atomic_push_urls(
        ROOT, ref_branch="main", ref_sha=SHA, push_urls_probe=lambda _root: []
    )
    assert empty.ok is False
    assert empty.detail == "expected at least one configured push URL for origin; observed none"


def test_probe_atomic_push_urls_real_probe_against_a_non_atomic_transport_fails_the_check(
    tmp_path: Path,
) -> None:
    def _git(cwd: Path, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
        ).stdout

    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-q")
    _git(work, "config", "user.email", "t@example.com")
    _git(work, "config", "user.name", "perk tests")
    _git(work, "checkout", "-q", "-b", "main")
    (work / "f.txt").write_text("hi\n", encoding="utf-8")
    _git(work, "add", ".")
    _git(work, "commit", "-qm", "init")
    bare = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", str(bare))
    _git(work, "remote", "add", "origin", str(bare))
    _git(work, "push", "-q", "origin", "main")
    _git(bare, "config", "receive.advertiseAtomic", "false")
    sha = _git(work, "rev-parse", "HEAD").strip()
    before = _git(bare, "rev-parse", "refs/heads/main").strip()

    (failed,) = capability.probe_atomic_push_urls(work, ref_branch="main", ref_sha=sha)

    assert failed.name == "atomic-push" and failed.ok is False
    assert "does not support --atomic" in failed.detail
    assert "not branch write permission" in failed.detail
    assert _git(bare, "rev-parse", "refs/heads/main").strip() == before
