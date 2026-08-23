"""Tests for `perk pr review checkout --stack` — the stacked-review hydration boundary.

Real-git fixtures (3-layer stacks pushed to ``refs/pull/<n>/head`` on a bare origin): the
multi-refspec fetch + snapshot envelope, the fail-closed post-fetch topology gate, drift
notes, the flag-combination refusals, and the non-stack byte-compat pin.
"""

import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

import perk.cli.commands.pr.review.checkout_cmd as checkout_cmd
from perk import github
from perk.cli.cli import cli
from perk.cli.commands.pr.review.stack_resolve import ResolvedStack, StackMember
from perk.substrate import git


def _git(cwd, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def _sha(repo, ref: str = "HEAD") -> str:
    return _git(repo, "rev-parse", ref).strip()


def _commit(clone: Path, name: str) -> str:
    (clone / f"{name}.txt").write_text(f"{name}\n", encoding="utf-8")
    _git(clone, "add", ".")
    _git(clone, "commit", "-qm", name)
    return _sha(clone)


def _member(pr: int, head: str, base: str, *, recorded: str | None = None) -> StackMember:
    return StackMember(
        pr_number=pr,
        url=f"u/{pr}",
        head_ref=head,
        base_ref=base,
        head_repo="me/repo",
        node_id=None,
        plan_id=None,
        recorded_head_sha=recorded,
    )


def _stack(members: list[StackMember], *, base: str = "main", notes: tuple[str, ...] = ()):
    return ResolvedStack(
        members=tuple(members),
        base_ref=base,
        kind="chain",
        objective_id=None,
        notes=notes,
    )


def _seed_linear_stack(clone: Path) -> dict[str, str]:
    """Three stacked heads, each pushed to ``refs/pull/<n>/head``; returns name→sha."""
    shas: dict[str, str] = {"base": _sha(clone)}
    _git(clone, "checkout", "-qb", "feat-a")
    shas["a"] = _commit(clone, "a")
    _git(clone, "push", "-q", "origin", "HEAD:refs/pull/1/head")
    _git(clone, "checkout", "-qb", "feat-b")
    shas["b"] = _commit(clone, "b")
    _git(clone, "push", "-q", "origin", "HEAD:refs/pull/2/head")
    _git(clone, "checkout", "-qb", "feat-c")
    shas["c"] = _commit(clone, "c")
    _git(clone, "push", "-q", "origin", "HEAD:refs/pull/3/head")
    _git(clone, "checkout", "-q", "main")
    return shas


def _wire_stack(monkeypatch, stack: ResolvedStack) -> None:
    monkeypatch.setattr(checkout_cmd, "resolve_stack_from_pr", lambda repo_root, pr: stack)


def test_stack_checkout_success_snapshot_envelope(git_repo_with_remote, monkeypatch):
    clone, _remote, advance_origin = git_repo_with_remote
    shas = _seed_linear_stack(clone)
    advance_origin()  # origin/main moves on — the combined merge-base must stay the fork point
    members = [
        _member(1, "feat-a", "main"),
        _member(2, "feat-b", "feat-a"),
        _member(3, "feat-c", "feat-b"),
    ]
    _wire_stack(monkeypatch, _stack(members))
    monkeypatch.chdir(clone)

    result = CliRunner().invoke(cli, ["pr", "review", "checkout", "--stack", "--pr", "2", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    # Top-PR + combined-base identity on the existing fields.
    assert data["pr"] == 3
    assert data["url"] == "u/3"
    assert data["head_sha"] == shas["c"]
    assert data["base_sha"] == shas["base"]
    assert data["base_ref"] == "main"
    # The additive pinned snapshot: ordered bottom→top with hydrated member heads.
    assert [row["pr"] for row in data["stack"]] == [1, 2, 3]
    assert [row["head_sha"] for row in data["stack"]] == [shas["a"], shas["b"], shas["c"]]
    assert [row["branch"] for row in data["stack"]] == ["feat-a", "feat-b", "feat-c"]
    assert data["stack_base_ref"] == "main"
    assert data["stack_notes"] == []
    # The checkout is the TOP head at review-<top> (cleanup --pr <top> works unchanged).
    wt = Path(data["path"])
    assert wt.resolve() == (clone / ".worktrees" / "review-3").resolve()
    assert _sha(wt) == shas["c"]
    assert git.current_branch(wt) is None
    # All member temp refs are gone.
    for n in (1, 2, 3):
        assert git.resolve_commit(clone, f"refs/perk/review/{n}") is None


def test_stack_checkout_topology_broken_fails_closed(git_repo_with_remote, monkeypatch):
    # feat-b forks from MAIN, not feat-a: ref-name linkage would look fine, but the commit
    # topology is broken — refuse before any worktree mutation.
    clone, _remote, _advance = git_repo_with_remote
    _git(clone, "checkout", "-qb", "feat-a")
    _commit(clone, "a")
    _git(clone, "push", "-q", "origin", "HEAD:refs/pull/1/head")
    _git(clone, "checkout", "-q", "main")
    _git(clone, "checkout", "-qb", "feat-b")
    _commit(clone, "b")
    _git(clone, "push", "-q", "origin", "HEAD:refs/pull/2/head")
    _git(clone, "checkout", "-q", "main")
    members = [_member(1, "feat-a", "main"), _member(2, "feat-b", "feat-a")]
    _wire_stack(monkeypatch, _stack(members))
    monkeypatch.chdir(clone)

    result = CliRunner().invoke(cli, ["pr", "review", "checkout", "--stack", "--pr", "1", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "stack_topology_broken"
    assert not (clone / ".worktrees" / "review-2").exists()


def test_stack_checkout_drift_note_warns_not_refuses(git_repo_with_remote, monkeypatch):
    clone, _remote, _advance = git_repo_with_remote
    shas = _seed_linear_stack(clone)
    members = [
        _member(1, "feat-a", "main", recorded=shas["a"]),
        _member(2, "feat-b", "feat-a", recorded="0" * 40),  # recorded head drifted
        _member(3, "feat-c", "feat-b"),  # no recorded head — never a note
    ]
    _wire_stack(monkeypatch, _stack(members, notes=("[blocker_code] train warning",)))
    monkeypatch.chdir(clone)

    result = CliRunner().invoke(cli, ["pr", "review", "checkout", "--stack", "--pr", "1", "--json"])
    assert result.exit_code == 0, result.output
    notes = json.loads(result.stdout)["stack_notes"]
    assert notes[0] == "[blocker_code] train warning"  # resolution notes carried through
    assert len(notes) == 2 and "drift: PR #2" in notes[1]


def test_stack_checkout_remote_tracking_only_base(git_repo_with_remote, monkeypatch):
    # The stack base exists ONLY on the remote (no local branch): the bare-branch fetch
    # materializes origin/<base>, which is all the combined merge-base needs.
    clone, _remote, _advance = git_repo_with_remote
    _git(clone, "checkout", "-qb", "stackbase")
    base_sha = _commit(clone, "base")
    _git(clone, "push", "-q", "origin", "stackbase")
    _git(clone, "checkout", "-qb", "feat-a")
    _commit(clone, "a")
    _git(clone, "push", "-q", "origin", "HEAD:refs/pull/1/head")
    _git(clone, "checkout", "-qb", "feat-b")
    top_sha = _commit(clone, "b")
    _git(clone, "push", "-q", "origin", "HEAD:refs/pull/2/head")
    _git(clone, "checkout", "-q", "main")
    _git(clone, "branch", "-qD", "stackbase")
    _git(clone, "update-ref", "-d", "refs/remotes/origin/stackbase")
    members = [_member(1, "feat-a", "stackbase"), _member(2, "feat-b", "feat-a")]
    _wire_stack(monkeypatch, _stack(members, base="stackbase"))
    monkeypatch.chdir(clone)

    result = CliRunner().invoke(cli, ["pr", "review", "checkout", "--stack", "--pr", "1", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["base_sha"] == base_sha
    assert data["head_sha"] == top_sha
    assert data["stack_base_ref"] == "stackbase"


def test_stack_flag_combination_refusals(git_repo, monkeypatch):
    monkeypatch.chdir(git_repo)
    runner = CliRunner()

    r = runner.invoke(cli, ["pr", "review", "checkout", "--objective", "7", "--json"])
    assert r.exit_code == 1
    assert json.loads(r.stdout)["error_type"] == "invalid_input"

    r = runner.invoke(
        cli,
        ["pr", "review", "checkout", "--stack", "--pr", "1", "--objective", "7", "--json"],
    )
    assert r.exit_code == 1
    assert json.loads(r.stdout)["error_type"] == "invalid_input"

    r = runner.invoke(cli, ["pr", "review", "checkout", "--stack", "--json"])
    assert r.exit_code == 1
    assert json.loads(r.stdout)["error_type"] == "invalid_input"

    r = runner.invoke(cli, ["pr", "review", "checkout", "--json"])
    assert r.exit_code == 1
    assert json.loads(r.stdout)["error_type"] == "invalid_input"


def test_stack_objective_arm_routes_to_objective_resolver(git_repo_with_remote, monkeypatch):
    clone, _remote, _advance = git_repo_with_remote
    shas = _seed_linear_stack(clone)
    calls: list[tuple[Path, str]] = []

    def fake_resolve(repo_root, objective_id):
        calls.append((repo_root, objective_id))
        return _stack([_member(1, "feat-a", "main"), _member(2, "feat-b", "feat-a")], base="main")

    monkeypatch.setattr(checkout_cmd, "resolve_stack_from_objective", fake_resolve)
    monkeypatch.chdir(clone)

    result = CliRunner().invoke(
        cli, ["pr", "review", "checkout", "--stack", "--objective", "77", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert calls and calls[0][1] == "77"
    assert json.loads(result.stdout)["head_sha"] == shas["b"]


def test_non_stack_envelope_byte_compat_pin(git_repo_with_remote, monkeypatch):
    # The non-stack --json payload carries EXACTLY the original keys — no stack keys, not
    # even null ones.
    clone, _remote, _advance = git_repo_with_remote
    _git(clone, "checkout", "-qb", "feature")
    _commit(clone, "f")
    _git(clone, "push", "-q", "origin", "HEAD:refs/pull/7/head")
    _git(clone, "checkout", "-q", "main")
    monkeypatch.setattr(
        github,
        "get_pr",
        lambda **k: github.PullRequest(
            number=7,
            url="u",
            is_draft=False,
            state="OPEN",
            existed=True,
            base_ref="main",
            head_ref="feature",
        ),
    )
    monkeypatch.chdir(clone)

    result = CliRunner().invoke(cli, ["pr", "review", "checkout", "--pr", "7", "--json"])
    assert result.exit_code == 0, result.output
    assert list(json.loads(result.stdout).keys()) == [
        "success",
        "error_type",
        "message",
        "path",
        "pr",
        "url",
        "head_sha",
        "base_sha",
        "base_ref",
    ]
