import json
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

from click.testing import CliRunner, Result

from perk import github, plan
from perk.cli.cli import cli
from perk.state import cache
from perk.substrate import git as git_mod

_REF = {
    "provider": "github",
    "pr_id": "7",
    "url": "https://gh/o/r/issues/7",
    "labels": ["perk:plan"],
    "objective_id": None,
}


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _context() -> github.PrReviewContext:
    return github.PrReviewContext(
        pr_number=42,
        base_ref="main",
        head_ref="plan-7",
        title="Add a thing",
        body="does the thing",
        diff="diff --git a/x b/x\n+new line\n",
        plan_body="# Plan\n\nbody",
    )


def _foreign_context() -> github.PrReviewContext:
    # The --pr arm's shape: a foreign head ref and no plan body (plan-ref-free).
    return github.PrReviewContext(
        pr_number=123,
        base_ref="main",
        head_ref="feature-x",
        title="A foreign PR",
        body="no plan behind it",
        diff="diff --git a/y b/y\n+foreign line\n",
        plan_body=None,
    )


def _open_pr():
    return github.PullRequest(number=42, url="u", is_draft=False, state="OPEN", existed=True)


def test_context_success_json(monkeypatch):
    monkeypatch.setattr(github, "find_pr_for_branch", lambda **k: _open_pr())
    monkeypatch.setattr(github, "get_pr_review_context", lambda **k: _context())
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), plan.PlanRefModel.model_validate(_REF).to_domain())
        result = runner.invoke(cli, ["pr", "review-context", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["success"] is True
    assert data["pr"] == 42 and data["branch"] == "plan-7"
    assert data["base_ref"] == "main" and data["head_ref"] == "plan-7"
    assert "new line" in data["diff"]
    assert data["plan_body"].startswith("# Plan")


def test_context_no_plan_ref_exits_1():
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["pr", "review-context", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "no_plan_ref"


def test_context_no_pr_exits_1(monkeypatch):
    monkeypatch.setattr(github, "find_pr_for_branch", lambda **k: None)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), plan.PlanRefModel.model_validate(_REF).to_domain())
        result = runner.invoke(cli, ["pr", "review-context", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "no_pr"


def test_context_not_a_repo_exits_2():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["pr", "review-context", "--json"])
    assert result.exit_code == 2
    assert json.loads(result.output)["error_type"] == "not_a_repo"


def test_context_github_error_exits_1(monkeypatch):
    monkeypatch.setattr(github, "find_pr_for_branch", lambda **k: _open_pr())

    def _boom(**k):
        raise github.GitHubError("HTTP 500")

    monkeypatch.setattr(github, "get_pr_review_context", _boom)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), plan.PlanRefModel.model_validate(_REF).to_domain())
        result = runner.invoke(cli, ["pr", "review-context", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "github_error"


def test_context_pr_flag_success_json(monkeypatch):
    # No plan-ref is written; the plan-ref path is provably untouched (find_pr_for_branch
    # would raise) — the explicit flag wins.
    monkeypatch.setattr(
        github,
        "get_pr",
        lambda **k: github.PullRequest(
            number=123, url="u", is_draft=False, state="OPEN", existed=True, head_ref="feature-x"
        ),
    )
    seen: dict[str, object] = {}

    def _capture(**k):
        seen.update(k)
        return _foreign_context()

    monkeypatch.setattr(github, "get_pr_review_context", _capture)

    def _no_plan_ref_path(**k):
        raise AssertionError("--pr must never resolve the plan-ref branch")

    monkeypatch.setattr(github, "find_pr_for_branch", _no_plan_ref_path)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["pr", "review-context", "--pr", "123", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["success"] is True
    assert data["branch"] == "feature-x" and data["pr"] == 123
    assert data["plan_body"] is None
    assert seen["branch"] == "feature-x"
    assert seen["plan_body"] is None
    assert seen["pr_number"] == 123


def test_context_pr_flag_not_found_exits_1(monkeypatch):
    monkeypatch.setattr(github, "get_pr", lambda **k: None)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["pr", "review-context", "--pr", "999", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "pr_not_found"


def test_context_pr_flag_github_error_exits_1(monkeypatch):
    def _boom(**k):
        raise github.GitHubError("HTTP 500")

    monkeypatch.setattr(github, "get_pr", _boom)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["pr", "review-context", "--pr", "123", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_type"] == "github_error"


def test_context_flagless_never_calls_get_pr(monkeypatch):
    # The flagless arm never touches the by-number lookup (byte-identical to before the flag).
    monkeypatch.setattr(github, "find_pr_for_branch", lambda **k: _open_pr())
    monkeypatch.setattr(github, "get_pr_review_context", lambda **k: _context())

    def _no_by_number(**k):
        raise AssertionError("the flagless arm must never call get_pr")

    monkeypatch.setattr(github, "get_pr", _no_by_number)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), plan.PlanRefModel.model_validate(_REF).to_domain())
        result = runner.invoke(cli, ["pr", "review-context", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["success"] is True


def test_context_expected_pr_preserves_active_plan_context(monkeypatch):
    monkeypatch.setattr(github, "find_pr_for_branch", lambda **k: _open_pr())
    seen: dict[str, object] = {}

    def _capture(**kwargs):
        seen.update(kwargs)
        return replace(_context(), plan_body=kwargs["plan_body"])

    monkeypatch.setattr(github, "get_pr_review_context", _capture)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), plan.PlanRefModel.model_validate(_REF).to_domain())
        cache.plan_body_path(Path(d)).write_text("# Snapshot plan\n", encoding="utf-8")
        result = runner.invoke(cli, ["pr", "review-context", "--expected-pr", "42", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["pr"] == 42
    assert data["plan_body"] == "# Snapshot plan"
    assert seen["plan_body"] == "# Snapshot plan"


def test_context_expected_pr_mismatch_fails_before_context_fetch(monkeypatch):
    monkeypatch.setattr(github, "find_pr_for_branch", lambda **k: _open_pr())

    def _no_fetch(**_kwargs):
        raise AssertionError("mismatch must fail before fetching review context")

    monkeypatch.setattr(github, "get_pr_review_context", _no_fetch)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), plan.PlanRefModel.model_validate(_REF).to_domain())
        result = runner.invoke(cli, ["pr", "review-context", "--expected-pr", "99", "--json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["error_type"] == "review_target_changed"
    assert "expected PR #99" in data["message"]
    assert "PR #42" in data["message"]


def test_context_expected_pr_rejects_non_positive_and_mutual_exclusion(monkeypatch):
    def _no_resolution(**_kwargs):
        raise AssertionError("invalid input must fail before PR resolution")

    monkeypatch.setattr(github, "find_pr_for_branch", _no_resolution)
    monkeypatch.setattr(github, "get_pr", _no_resolution)
    runner = CliRunner()
    for args in (
        ["--expected-pr", "0"],
        ["--expected-pr", "-1"],
        ["--pr", "42", "--expected-pr", "42"],
    ):
        with runner.isolated_filesystem() as d:
            _git_init(d)
            result = runner.invoke(cli, ["pr", "review-context", *args, "--json"])
        assert result.exit_code == 1
        assert json.loads(result.output)["error_type"] == "invalid_input"


def test_resolve_plan_body_prefers_cache_mirror(monkeypatch, tmp_path):
    # The primary path: the worktree cache mirror is read first (backend-neutral), no backend hit.
    from perk.cli.commands.pr.review_context_cmd import _resolve_plan_body

    mirror = cache.plan_body_path(tmp_path)
    mirror.parent.mkdir(parents=True, exist_ok=True)
    mirror.write_text("# Mirror plan\n\nbody", encoding="utf-8")

    def _no_backend(_root):
        raise AssertionError("must not resolve a backend when the mirror is present")

    monkeypatch.setattr(
        "perk.cli.commands.pr.review_context_cmd.resolve.resolve_issue_backend", _no_backend
    )
    body = _resolve_plan_body(tmp_path, plan.PlanRefModel.model_validate(_REF).to_domain())
    assert body is not None and body.startswith("# Mirror plan")


def test_resolve_plan_body_falls_back_to_resolver_for_linear_id(monkeypatch, tmp_path):
    # The fallback path: no mirror → fetch via the resolved backend, which owns the id shape
    # (a non-github Linear-shaped `pr_id` like `ENG-123` flows straight through — the §G hoist
    # drops the old `provider == "github"` / `pr_id.isdigit()` gate).
    from perk.cli.commands.pr.review_context_cmd import _resolve_plan_body

    seen: dict[str, str] = {}

    class _Backend:
        def get_plan_body(self, *, issue_id: str) -> str:
            seen["issue_id"] = issue_id
            return "# Linear plan body"

    monkeypatch.setattr(
        "perk.cli.commands.pr.review_context_cmd.resolve.resolve_issue_backend",
        lambda _root: _Backend(),
    )
    ref = plan.PlanRefModel.model_validate(
        {**_REF, "provider": "linear", "pr_id": "ENG-123"}
    ).to_domain()
    assert _resolve_plan_body(tmp_path, ref) == "# Linear plan body"
    assert seen["issue_id"] == "ENG-123"


# --------------------------------------------------------------------- the --stack arm


def _stack_members():
    from perk.cli.commands.pr.review.stack_resolve import ResolvedStack, StackMember

    members = (
        StackMember(
            pr_number=1,
            url="u/1",
            head_ref="plan-301",
            base_ref="main",
            node_id="1.1",
            plan_id="301",
        ),
        StackMember(
            pr_number=2,
            url="u/2",
            head_ref="feat-b",
            base_ref="plan-301",
            node_id=None,
            plan_id=None,
        ),
    )
    return ResolvedStack(
        members=members, base_ref="main", kind="chain", objective_id=None, notes=()
    )


def _member_context(pr_number: int, head: str, base: str) -> github.PrReviewContext:
    return github.PrReviewContext(
        pr_number=pr_number,
        base_ref=base,
        head_ref=head,
        title=f"title {pr_number}",
        body=f"body {pr_number}",
        diff=f"diff {pr_number}",
        plan_body=None,
    )


def _perk_ref_oids(repo: Path) -> dict[str, str]:
    """Name→target-OID snapshot of every ref under ``refs/perk/``.

    Mapping equality proves the refs kept their names AND their target OIDs — a name-only
    set could not detect a retargeted ref. These refs point directly at commits (fetched PR
    heads and the base branch), so ``resolve_commit`` observes target identity.
    """
    oids: dict[str, str] = {}
    for ref in git_mod.list_refs(repo, "refs/perk/"):
        sha = git_mod.resolve_commit(repo, ref)
        assert sha is not None, f"live ref {ref} must resolve to a commit"
        oids[ref] = sha
    return oids


@dataclass
class _InterleaveState:
    """Observations captured by the fetch-seam race hook (typed so ``ty`` narrows cleanly)."""

    calls: int = 0
    b_result: Result | None = None
    refs_at_b_start: dict[str, str] | None = None
    refs_during_b: dict[str, str] | None = None
    refs_after_b: dict[str, str] | None = None


def test_stack_context_sections_and_combined_diff(git_repo_with_remote, monkeypatch):
    import perk.cli.commands.pr.review_context_cmd as review_context_cmd
    from perk.substrate import git as git_mod

    clone, _remote, _advance = git_repo_with_remote
    # Two stacked heads pushed to refs/pull/<n>/head; the combined diff must contain both.
    subprocess.run(["git", "checkout", "-qb", "plan-301"], cwd=clone, check=True)
    (clone / "a.txt").write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=clone, check=True)
    subprocess.run(["git", "commit", "-qm", "a"], cwd=clone, check=True)
    subprocess.run(["git", "push", "-q", "origin", "HEAD:refs/pull/1/head"], cwd=clone, check=True)
    subprocess.run(["git", "checkout", "-qb", "feat-b"], cwd=clone, check=True)
    (clone / "b.txt").write_text("b\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=clone, check=True)
    subprocess.run(["git", "commit", "-qm", "b"], cwd=clone, check=True)
    subprocess.run(["git", "push", "-q", "origin", "HEAD:refs/pull/2/head"], cwd=clone, check=True)
    subprocess.run(["git", "checkout", "-q", "main"], cwd=clone, check=True)

    monkeypatch.setattr(
        review_context_cmd, "resolve_stack_from_pr", lambda repo_root, pr: _stack_members()
    )
    contexts = {
        1: _member_context(1, "plan-301", "main"),
        2: _member_context(2, "feat-b", "plan-301"),
    }
    monkeypatch.setattr(
        github, "get_pr_review_context", lambda *, pr_number, **k: contexts[pr_number]
    )

    class _Backend:
        def get_plan_body(self, *, issue_id: str) -> str:
            assert issue_id == "301"
            return "# Plan 301"

    monkeypatch.setattr(
        "perk.cli.commands.pr.review_context_cmd.resolve.resolve_issue_backend",
        lambda _root: _Backend(),
    )
    monkeypatch.chdir(clone)

    result = CliRunner().invoke(cli, ["pr", "review-context", "--pr", "2", "--stack", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    # Top-level fields describe the TOP PR.
    assert data["pr"] == 2 and data["branch"] == "feat-b"
    assert data["title"] == "title 2"
    # Per-member sections, bottom→top; the plan-branch member is enriched.
    assert [row["pr"] for row in data["stack"]] == [1, 2]
    assert data["stack"][0]["plan_body"] == "# Plan 301"
    assert data["stack"][1]["plan_body"] is None
    # The combined base→top diff carries BOTH layers' changes.
    assert "a.txt" in data["combined_diff"] and "b.txt" in data["combined_diff"]
    # The per-invocation temp-ref namespace is fully cleaned up after the read — no ref
    # under refs/perk/ survives (checkout's shared refs/perk/review/<n> names included:
    # this worker must never touch them, or concurrent lanes would clobber each other).
    listed = subprocess.run(
        ["git", "for-each-ref", "refs/perk/", "--format=%(refname)"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert listed.stdout.strip() == ""
    assert git_mod.resolve_commit(clone, "refs/perk/review/2") is None


def test_stack_context_topology_broken_refuses(git_repo_with_remote, monkeypatch):
    # A successor head that does NOT descend from its predecessor head (e.g. a lower layer
    # force-pushed after the upper branched) fails closed — never a "combined" diff that
    # silently omits a layer. The temp namespace is still cleaned up on the failure path.
    import perk.cli.commands.pr.review_context_cmd as review_context_cmd

    clone, _remote, _advance = git_repo_with_remote
    # Two SIBLING branches off main: PR 2's head does not contain PR 1's head.
    subprocess.run(["git", "checkout", "-qb", "plan-301"], cwd=clone, check=True)
    (clone / "a.txt").write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=clone, check=True)
    subprocess.run(["git", "commit", "-qm", "a"], cwd=clone, check=True)
    subprocess.run(["git", "push", "-q", "origin", "HEAD:refs/pull/1/head"], cwd=clone, check=True)
    subprocess.run(["git", "checkout", "-q", "main"], cwd=clone, check=True)
    subprocess.run(["git", "checkout", "-qb", "feat-b"], cwd=clone, check=True)
    (clone / "b.txt").write_text("b\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=clone, check=True)
    subprocess.run(["git", "commit", "-qm", "b"], cwd=clone, check=True)
    subprocess.run(["git", "push", "-q", "origin", "HEAD:refs/pull/2/head"], cwd=clone, check=True)
    subprocess.run(["git", "checkout", "-q", "main"], cwd=clone, check=True)

    monkeypatch.setattr(
        review_context_cmd, "resolve_stack_from_pr", lambda repo_root, pr: _stack_members()
    )
    contexts = {
        1: _member_context(1, "plan-301", "main"),
        2: _member_context(2, "feat-b", "plan-301"),
    }
    monkeypatch.setattr(
        github, "get_pr_review_context", lambda *, pr_number, **k: contexts[pr_number]
    )

    class _Backend:
        def get_plan_body(self, *, issue_id: str) -> str:
            return "# Plan 301"

    monkeypatch.setattr(
        "perk.cli.commands.pr.review_context_cmd.resolve.resolve_issue_backend",
        lambda _root: _Backend(),
    )
    monkeypatch.chdir(clone)

    result = CliRunner().invoke(cli, ["pr", "review-context", "--pr", "2", "--stack", "--json"])
    assert result.exit_code != 0
    data = json.loads(result.stdout)
    assert data["error_type"] == "stack_topology_broken"
    listed = subprocess.run(
        ["git", "for-each-ref", "refs/perk/", "--format=%(refname)"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert listed.stdout.strip() == ""


def test_stack_context_two_workers_interleaved_ref_isolation(git_repo_with_remote, monkeypatch):
    # Concurrent reviewer lanes all fetch the SAME top PR while sharing ONE ref store, so the
    # per-invocation temp-ref namespace is the ONLY thing separating their refs. Worker B's
    # complete fetch→read→delete lifecycle runs synchronously inside worker A's ref-sensitive
    # window (between A's fetch and A's first by-name read) via a race hook on the fetch seam —
    # deterministic, no sleeps or threads. A shared OR target-derived namespace regression
    # (e.g. refs/perk/review-ctx/<top-pr>) necessarily collides: B's cleanup would delete A's
    # live refs, A would fail loudly, and the snapshots would diverge.
    import perk.cli.commands.pr.review_context_cmd as review_context_cmd

    clone, _remote, _advance = git_repo_with_remote
    # ONE two-member stack in the shared clone/ref store; both workers target it.
    subprocess.run(["git", "checkout", "-qb", "plan-301"], cwd=clone, check=True, timeout=30)
    (clone / "a.txt").write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=clone, check=True, timeout=30)
    subprocess.run(["git", "commit", "-qm", "a"], cwd=clone, check=True, timeout=30)
    subprocess.run(
        ["git", "push", "-q", "origin", "HEAD:refs/pull/1/head"], cwd=clone, check=True, timeout=30
    )
    subprocess.run(["git", "checkout", "-qb", "feat-b"], cwd=clone, check=True, timeout=30)
    (clone / "b.txt").write_text("b\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=clone, check=True, timeout=30)
    subprocess.run(["git", "commit", "-qm", "b"], cwd=clone, check=True, timeout=30)
    subprocess.run(
        ["git", "push", "-q", "origin", "HEAD:refs/pull/2/head"], cwd=clone, check=True, timeout=30
    )
    subprocess.run(["git", "checkout", "-q", "main"], cwd=clone, check=True, timeout=30)

    monkeypatch.setattr(
        review_context_cmd, "resolve_stack_from_pr", lambda repo_root, pr: _stack_members()
    )
    contexts = {
        1: _member_context(1, "plan-301", "main"),
        2: _member_context(2, "feat-b", "plan-301"),
    }
    monkeypatch.setattr(
        github, "get_pr_review_context", lambda *, pr_number, **k: contexts[pr_number]
    )

    class _Backend:
        def get_plan_body(self, *, issue_id: str) -> str:
            assert issue_id == "301"
            return "# Plan 301"

    monkeypatch.setattr(
        "perk.cli.commands.pr.review_context_cmd.resolve.resolve_issue_backend",
        lambda _root: _Backend(),
    )
    monkeypatch.chdir(clone)

    # Both workers invoke the identical command — the review-wave fan-out shape.
    args = ["pr", "review-context", "--pr", "2", "--stack", "--json"]
    state = _InterleaveState()
    real_fetch = git_mod.fetch_refspecs

    def fetch_then_interleave(*fetch_args, **fetch_kwargs):
        # fetch_refspecs is called exactly once per invocation, so the call counter is the
        # reentrancy guard: call 1 is worker A's fetch (open the window, run B to completion
        # inside it); call 2 is worker B's own nested fetch (the in-lifecycle point where
        # BOTH namespaces are live).
        state.calls += 1
        call = state.calls
        real_fetch(*fetch_args, **fetch_kwargs)
        if call == 1:
            state.refs_at_b_start = _perk_ref_oids(clone)
            state.b_result = CliRunner().invoke(cli, args)
            state.refs_after_b = _perk_ref_oids(clone)
        elif call == 2:
            state.refs_during_b = _perk_ref_oids(clone)

    monkeypatch.setattr(git_mod, "fetch_refspecs", fetch_then_interleave)

    result = CliRunner().invoke(cli, args)

    # Worker A completed correctly despite B's full lifecycle inside its window.
    assert result.exit_code == 0, result.output
    data_a = json.loads(result.stdout)
    assert data_a["pr"] == 2 and data_a["branch"] == "feat-b"
    assert [row["pr"] for row in data_a["stack"]] == [1, 2]
    assert data_a["stack"][0]["plan_body"] == "# Plan 301"
    assert data_a["stack"][1]["plan_body"] is None
    assert "a.txt" in data_a["combined_diff"] and "b.txt" in data_a["combined_diff"]

    # Worker B completed independently — the narrowing doubles as the barrier-liveness proof
    # (the interleave actually fired; a seam rename cannot silently turn this sequential).
    assert state.b_result is not None
    assert state.b_result.exit_code == 0, state.b_result.output
    data_b = json.loads(state.b_result.stdout)
    assert data_b["pr"] == 2 and data_b["branch"] == "feat-b"
    assert [row["pr"] for row in data_b["stack"]] == [1, 2]
    assert data_b["stack"][0]["plan_body"] == "# Plan 301"
    assert data_b["stack"][1]["plan_body"] is None
    assert "a.txt" in data_b["combined_diff"] and "b.txt" in data_b["combined_diff"]

    # A's namespace before B started: two member refs + base under ONE namespace prefix.
    assert state.refs_at_b_start is not None
    assert len(state.refs_at_b_start) == 3
    assert all(ref.startswith("refs/perk/review-ctx/") for ref in state.refs_at_b_start)
    assert len({ref.rsplit("/", 1)[0] for ref in state.refs_at_b_start}) == 1

    # While B was live: BOTH namespaces coexist and A's exact name→OID entries are untouched —
    # the direct per-invocation-isolation observation, excluding transient clobber-and-restore
    # (which a before/after pair alone cannot).
    assert state.refs_during_b is not None
    assert len(state.refs_during_b) == 6
    during_namespaces = {ref.rsplit("/", 1)[0] for ref in state.refs_during_b}
    assert len(during_namespaces) == 2
    assert all(ns.startswith("refs/perk/review-ctx/") for ns in during_namespaces)
    assert state.refs_at_b_start.items() <= state.refs_during_b.items()

    # After B's full lifecycle: A's refs kept their names AND target OIDs — B created and
    # deleted ONLY its own namespace.
    assert state.refs_after_b is not None
    assert state.refs_after_b == state.refs_at_b_start

    # The shared-store sweep LAST (so it proves isolation rather than masking a failed
    # worker): no residual ref from either worker.
    assert git_mod.list_refs(clone, "refs/perk/") == []


def test_stack_requires_pr(git_repo, monkeypatch):
    monkeypatch.chdir(git_repo)
    result = CliRunner().invoke(cli, ["pr", "review-context", "--stack", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "invalid_input"


def test_stack_with_expected_pr_refused(git_repo, monkeypatch):
    monkeypatch.chdir(git_repo)
    result = CliRunner().invoke(
        cli, ["pr", "review-context", "--stack", "--pr", "2", "--expected-pr", "2", "--json"]
    )
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "invalid_input"


def test_non_stack_context_envelope_byte_identical(monkeypatch):
    # The flagless envelope carries EXACTLY the original keys — no stack keys, not even nulls.
    monkeypatch.setattr(github, "find_pr_for_branch", lambda **k: _open_pr())
    monkeypatch.setattr(github, "get_pr_review_context", lambda **k: _context())
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), plan.PlanRefModel.model_validate(_REF).to_domain())
        result = runner.invoke(cli, ["pr", "review-context", "--json"])
    assert result.exit_code == 0
    assert list(json.loads(result.output).keys()) == [
        "success",
        "error_type",
        "message",
        "branch",
        "pr",
        "base_ref",
        "head_ref",
        "title",
        "body",
        "diff",
        "plan_body",
    ]
