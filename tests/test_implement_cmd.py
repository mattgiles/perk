"""`perk implement [PLAN]`: the dedicated implement cold door.

Covers Bug 2 (the optional plan positional + active-ref fallback) at the CLI boundary. The
priming prompt (Bug 1) is covered in test_launch.py. `plans.get_plan` + `launch.launch_stage`
are stubbed (no GitHub, no `exec pi`), mirroring test_resume.py.
"""

import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk import github, plan
from perk.backends.github import plans
from perk.cli.cli import cli
from perk.run import launch
from perk.state import cache

_PLAN_REF = plan.PlanRef(
    provider="github",
    pr_id="7",
    url="https://gh/o/r/issues/7",
    labels=("perk:plan",),
    objective_id=None,
    consumed_learn=(),
    base=None,
)


def _state() -> plans.PlanState:
    return plans.PlanState(
        number=7, url="https://gh/o/r/issues/7", title="T", header={}, pr=None, has_plan_header=True
    )


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _authed(monkeypatch) -> None:
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(True, "octocat", ("repo",), None)
    )


def test_implement_with_plan_writes_active_ref_and_launches(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(plans, "get_plan", lambda **k: _state())
    launched: dict[str, object] = {}
    monkeypatch.setattr(launch, "launch_stage", lambda **k: launched.update(stage=k["stage"].id))
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["implement", "7"])
        assert result.exit_code == 0, result.output
        assert launched["stage"] == "implement"
        # #7 is now the active plan (mirrors resume): the ref is materialized at the repo root.
        assert cache.read_plan_ref(Path(d)) == _PLAN_REF
        # The banner heads the pre-launch narration, then the lookup wait narrates + resolves.
        err = result.stderr
        assert err.index("skills \u00b7") < err.index("looking up plan #7")
        assert "\u2713 found plan #7" in err


def test_implement_with_plan_dry_run_does_not_write_or_launch(monkeypatch):
    # The dry run flows through the ONE unified launch preview (no launcher-local rendering):
    # it selects canonically, previews the create disposition, and writes/launches nothing.
    _authed(monkeypatch)
    monkeypatch.setattr(plans, "get_plan", lambda **k: _state())
    monkeypatch.setattr(launch, "_exec_pi", lambda _ctx: (_ for _ in ()).throw(AssertionError))
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["implement", "7", "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "plan-7" in result.output  # the resolved worktree name (stdout JSON + stderr human)
        assert not cache.plan_ref_path(Path(d)).exists()  # side-effect-free: no selector write
        assert not (Path(d) / ".worktrees").exists()  # …and no worktree materialized
        # The dry-run JSON carries the resolved base (null here: no remote on this repo) and the
        # would-be disposition.
        # Parse stdout only: the lookup narration now lands on stderr ahead of the payload.
        payload = json.loads(result.stdout)
        assert "base" in payload and payload["base"] is None
        assert payload["disposition"] == "create-fresh"
        # The lookup runs on the dry-run path too, so the wait IS narrated — banner-free.
        assert "looking up plan #7" in result.stderr
        assert "skills \u00b7" not in result.stderr


def test_implement_plan_not_found_exits_1(monkeypatch):
    _authed(monkeypatch)
    monkeypatch.setattr(plans, "get_plan", lambda **k: None)
    # Hermeticity: the digits miss reaches the seam's PR-fallback probe — fake a clean miss
    # (the original typed error re-raises verbatim; no real `gh` subprocess).
    monkeypatch.setattr(github, "get_pr", lambda **k: None)
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["implement", "999"])
        assert result.exit_code == 1
        assert "not found" in result.output


def test_implement_objective_issue_refuses_kind_mismatch(monkeypatch):
    """The incident door (positive identification, contracts §8.1): implement of an
    objective-shaped issue exits 1 typed — address/ready share the seam via the selector
    unit tests."""
    _authed(monkeypatch)
    monkeypatch.setattr(
        plans,
        "get_plan",
        lambda **k: plans.PlanState(
            number=63, url="u/63", title="T", header={}, pr=None, has_objective_header=True
        ),
    )
    monkeypatch.setattr(github, "get_pr", lambda **k: None)  # hermetic fallback-probe miss
    monkeypatch.setattr(
        launch, "launch_stage", lambda **k: (_ for _ in ()).throw(AssertionError("no launch"))
    )
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["implement", "63"])
        assert result.exit_code == 1
        assert "perk objective plan 63" in result.output
        assert not cache.plan_ref_path(Path(d)).exists()  # refused before any selector write


def test_implement_no_plan_uses_active_ref_without_github(monkeypatch):
    """No plan id: implement the active saved ref. No GitHub read, no auth needed."""

    def no_github(**k):
        raise AssertionError("implement of the active plan must not read GitHub")

    monkeypatch.setattr(plans, "get_plan", no_github)
    launched: dict[str, object] = {}
    monkeypatch.setattr(launch, "launch_stage", lambda **k: launched.update(stage=k["stage"].id))
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), _PLAN_REF)
        result = runner.invoke(cli, ["implement"])
        assert result.exit_code == 0, result.output
        assert launched["stage"] == "implement"


# --- two-roots + grammar regressions ----------------------------------------------------------


def test_implement_explicit_id_inside_linked_worktree_writes_main_selector_only(
    git_repo, monkeypatch
):
    # Invoked from INSIDE a linked plan worktree, `perk implement 7` updates only the MAIN-root
    # selector, leaves the invoking worktree's durable binding byte-identical, and positions
    # into the selected plan's own worktree (the two-role clobber hazard, pinned).
    from perk.cli.context import PerkContext
    from perk.substrate import git
    from perk.substrate.config import Config

    _authed(monkeypatch)
    monkeypatch.setattr(plans, "get_plan", lambda **k: _state())
    ref42 = plan.PlanRef(provider="github", pr_id="42", url="u/42", labels=("perk:plan",))
    wt42 = git_repo / ".worktrees" / "plan-42"
    git.worktree_add(git_repo, wt42, branch="plan-42", create_branch=True)
    cache.write_plan_ref(wt42, ref42)
    binding_bytes = cache.plan_ref_path(wt42).read_bytes()

    captured: dict = {}
    monkeypatch.setattr(launch, "_exec_pi", lambda c: captured.update(ctx=c))
    monkeypatch.setattr(launch, "_warm_extension_install", lambda _c: None)
    monkeypatch.setattr(launch, "_materialize_into_worktree", lambda _c: None)
    ctx = PerkContext.for_test(
        cwd=wt42, repo_root=wt42, config=Config(worktree_root=git_repo / ".worktrees")
    )
    result = CliRunner().invoke(cli, ["implement", "7"], obj=ctx)
    assert result.exit_code == 0, result.output
    assert captured["ctx"].resolved.path == git_repo / ".worktrees" / "plan-7"
    assert cache.read_plan_ref(git_repo) == _PLAN_REF  # the MAIN-root selector
    assert cache.plan_ref_path(wt42).read_bytes() == binding_bytes  # never clobbered
    assert cache.read_plan_ref(git_repo / ".worktrees" / "plan-7") == _PLAN_REF


def test_implement_no_arg_inside_linked_worktree_selects_its_own_plan(git_repo, monkeypatch):
    # The no-argument cache fallback reads the INVOCATION root: inside a plan worktree that is
    # the worktree's own binding, even when the main-root selector names a different plan.
    from perk.cli.context import PerkContext
    from perk.substrate import git
    from perk.substrate.config import Config

    ref42 = plan.PlanRef(provider="github", pr_id="42", url="u/42", labels=("perk:plan",))
    wt42 = git_repo / ".worktrees" / "plan-42"
    git.worktree_add(git_repo, wt42, branch="plan-42", create_branch=True)
    cache.write_plan_ref(wt42, ref42)
    cache.write_plan_ref(
        git_repo, plan.PlanRef(provider="github", pr_id="9", url="u/9", labels=("perk:plan",))
    )
    ctx = PerkContext.for_test(
        cwd=wt42, repo_root=wt42, config=Config(worktree_root=git_repo / ".worktrees")
    )
    result = CliRunner().invoke(cli, ["implement", "--dry-run"], obj=ctx)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["plan_ref"]["pr_id"] == "42"  # its own plan, not the main selector's #9


def test_implement_rejects_extra_pre_separator_tokens(monkeypatch):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        result = runner.invoke(cli, ["implement", "7", "stray", "--dry-run"])
        assert result.exit_code == 2
        assert "before the first bare '--'" in result.output


def test_implement_forwards_separator_tail_verbatim_in_order(monkeypatch):
    runner = CliRunner()
    with runner.isolated_filesystem() as d:
        _git_init(d)
        cache.write_plan_ref(Path(d), _PLAN_REF)
        result = runner.invoke(
            cli, ["implement", "--dry-run", "--", "--model", "prov/m", "--no-approve"]
        )
        assert result.exit_code == 0, result.output
        argv = json.loads(result.stdout)["argv"]
        i = argv.index("--model")
        assert argv[i : i + 3] == ["--model", "prov/m", "--no-approve"]
