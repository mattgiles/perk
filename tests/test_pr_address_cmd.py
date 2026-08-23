"""``perk pr address`` — the launcher-only address door + its flat alias.

``address`` has a launcher half + the warm review flow but no deterministic worker, so it is a
dedicated launcher (not a ``MergedCommand``) carrying the new cold ``--preview`` flag. These tests
cover the dry-run launch, the ``--preview`` seed shaping, and the ``perk address`` flat alias.
"""

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from perk import github, plan
from perk.backends.github import plans
from perk.cli.cli import cli
from perk.cli.commands.pr import pr_address_command
from perk.cli.context import PerkContext
from perk.run import launch
from perk.state import cache
from perk.substrate import git
from perk.substrate.config import Config


def _ctx(repo: Path) -> PerkContext:
    return PerkContext.for_test(
        cwd=repo, repo_root=repo, config=Config(worktree_root=repo / ".worktrees")
    )


def _seed(repo: Path) -> Path:
    """Seed the active plan-ref and a REAL bound ``plan-42`` worktree (address validates before
    reuse — a bare directory would refuse ``worktree_unregistered``)."""
    ref = plan.PlanRef(
        provider="github",
        pr_id="42",
        url="u/42",
        labels=("perk:plan",),
        objective_id=None,
    )
    cache.write_plan_ref(repo, ref)
    wt = repo / ".worktrees" / "plan-42"
    git.worktree_add(repo, wt, branch="plan-42", create_branch=True)
    cache.write_plan_ref(wt, ref)
    return wt


def test_pr_address_dry_run_launches(git_repo):
    _seed(git_repo)
    result = CliRunner().invoke(cli, ["pr", "address", "--dry-run"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output
    assert "would launch stage 'address'" in result.output


def test_pr_address_preview_seeds_classification_only(git_repo):
    _seed(git_repo)
    result = CliRunner().invoke(
        cli, ["pr", "address", "--preview", "--dry-run"], obj=_ctx(git_repo)
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    seed = "\n".join(payload["argv"])
    assert "PREVIEWING" in seed and "take NO action" in seed
    # The fix→publish→resolve tail is absent in the preview seed.
    assert "finalize_address" not in seed


def test_pr_address_non_preview_seeds_full_loop(git_repo):
    _seed(git_repo)
    result = CliRunner().invoke(cli, ["pr", "address", "--dry-run"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    seed = "\n".join(payload["argv"])
    assert "finalize_address" in seed
    assert "Never push manually" in seed
    assert "PREVIEWING" not in seed


def test_flat_address_alias_resolves_to_same_launcher(git_repo):
    # `perk address` (flat alias) is the SAME command object as `perk pr address`.
    assert cli.commands["address"] is pr_address_command
    _seed(git_repo)
    result = CliRunner().invoke(cli, ["address", "--dry-run"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output
    assert "would launch stage 'address'" in result.output


# --- the selection/positioning parity matrix (canonical + flat forms) ------------------------
#
# One selection seam, three sources, fixed precedence: explicit PLAN > an explicit existing
# --worktree's own binding > the invocation-root active selector. The dry-run payload, the
# resolved plan_ref, and the seed prompt must all name the SAME plan.


def _authed(monkeypatch) -> None:
    monkeypatch.setattr(
        github, "check_auth", lambda: github.AuthStatus(True, "octocat", ("repo",), None)
    )


def _canonical_plan(monkeypatch, pr_id: str = "7") -> plan.PlanRef:
    """Stub the ONE canonical backend read for plan ``pr_id``; return the ref it reconstructs."""
    monkeypatch.setattr(
        plans,
        "get_plan",
        lambda **k: plans.PlanState(
            number=int(pr_id),
            url=f"https://gh/o/r/issues/{pr_id}",
            title="T",
            header={},
            pr=None,
            has_plan_header=True,
        ),
    )
    return plan.PlanRef(
        provider="github",
        pr_id=pr_id,
        url=f"https://gh/o/r/issues/{pr_id}",
        labels=("perk:plan",),
    )


def _dry_payload(result) -> dict:
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("form", [["pr", "address"], ["address"]], ids=["canonical", "flat"])
def test_explicit_id_with_different_root_cache_selects_requested_plan(git_repo, monkeypatch, form):
    # The root selector names plan 42; the explicit id 7 wins, and the id is consumed as a
    # selector — never forwarded to pi as a token.
    _seed(git_repo)
    _authed(monkeypatch)
    _canonical_plan(monkeypatch, "7")
    payload = _dry_payload(CliRunner().invoke(cli, [*form, "7", "--dry-run"], obj=_ctx(git_repo)))
    assert Path(payload["worktree"]).name == "plan-7"
    assert payload["plan_ref"]["pr_id"] == "7"
    assert payload["disposition"] == "restore-remote"  # reuse stage, checkout missing
    seed = payload["argv"][-1]
    assert "issues/7" in seed and "issues/42" not in seed  # the seed names the SAME plan
    assert "7" not in payload["argv"][:-1]  # not a standalone pi token


def test_explicit_worktree_with_different_root_cache_uses_its_binding(git_repo):
    # Precedence arm 2: an explicit existing --worktree selects through its OWN binding; the
    # unrelated root selector is not a competing source.
    _seed(git_repo)  # the bound plan-42 worktree
    cache.write_plan_ref(
        git_repo,
        plan.PlanRef(provider="github", pr_id="9", url="u/9", labels=("perk:plan",)),
    )
    payload = _dry_payload(
        CliRunner().invoke(
            cli, ["pr", "address", "--worktree", "plan-42", "--dry-run"], obj=_ctx(git_repo)
        )
    )
    assert payload["plan_ref"]["pr_id"] == "42"
    assert payload["disposition"] == "reuse-local"


def test_no_selector_uses_the_active_cache_fallback(git_repo):
    _seed(git_repo)
    payload = _dry_payload(
        CliRunner().invoke(cli, ["pr", "address", "--dry-run"], obj=_ctx(git_repo))
    )
    assert payload["plan_ref"]["pr_id"] == "42"
    assert Path(payload["worktree"]).name == "plan-42"


def test_explicit_id_plus_directory_override_keeps_plan_identity(git_repo, monkeypatch):
    # --worktree NAME changes only the directory — never plan identity or the plan-<id> branch.
    _seed(git_repo)
    _authed(monkeypatch)
    _canonical_plan(monkeypatch, "7")
    payload = _dry_payload(
        CliRunner().invoke(
            cli,
            ["pr", "address", "7", "--worktree", "custom-wt", "--dry-run"],
            obj=_ctx(git_repo),
        )
    )
    assert Path(payload["worktree"]).name == "custom-wt"
    assert payload["plan_ref"]["pr_id"] == "7"
    assert payload["base"] == "origin/plan-7"  # the restore source IS the plan branch


def test_pi_tokens_appear_only_after_bare_separator_in_order(git_repo):
    _seed(git_repo)
    payload = _dry_payload(
        CliRunner().invoke(
            cli,
            ["pr", "address", "--dry-run", "--", "--model", "prov/m", "--thinking", "high"],
            obj=_ctx(git_repo),
        )
    )
    argv = payload["argv"]
    i = argv.index("--model")
    assert argv[i : i + 4] == ["--model", "prov/m", "--thinking", "high"]  # verbatim, in order


def test_extra_pre_separator_token_is_a_usage_error_with_grammar_hint(git_repo):
    result = CliRunner().invoke(
        cli, ["pr", "address", "7", "stray-token", "--dry-run"], obj=_ctx(git_repo)
    )
    assert result.exit_code == 2
    assert "before the first bare '--'" in result.output


def test_explicit_id_backend_failure_maps_github_error_no_write_no_launch(git_repo, monkeypatch):
    # The explicit-PLAN transport boundary: a backend transport failure out of the canonical
    # selection maps to github_error, rewrites no selector, and launches nothing.
    from perk.cli.ensure import UserFacingCliError

    _seed(git_repo)
    _authed(monkeypatch)
    selector_before = cache.plan_ref_path(git_repo).read_bytes()

    def _boom(**_kwargs):
        raise github.GitHubError("gh exploded")

    monkeypatch.setattr(plans, "get_plan", _boom)
    monkeypatch.setattr(
        launch,
        "launch_stage",
        lambda **_k: (_ for _ in ()).throw(AssertionError("launched after a failed selection")),
    )
    result = CliRunner().invoke(
        cli, ["pr", "address", "7"], obj=_ctx(git_repo), standalone_mode=False
    )
    assert isinstance(result.exception, UserFacingCliError)
    assert result.exception.error_type == "github_error"
    assert "address failed" in result.exception.format_message()
    assert cache.plan_ref_path(git_repo).read_bytes() == selector_before


def test_id_vs_worktree_branch_disagreement_fails_before_launch(git_repo, monkeypatch):
    # Supplying both selectors requires exact agreement: id 7 against the plan-42 checkout
    # surfaces as the branch check (the checkout sits on plan-42, selection expects plan-7).
    _seed(git_repo)
    _authed(monkeypatch)
    _canonical_plan(monkeypatch, "7")
    monkeypatch.setattr(
        launch, "_exec_pi", lambda _ctx: (_ for _ in ()).throw(AssertionError("launched"))
    )
    result = CliRunner().invoke(
        cli, ["pr", "address", "7", "--worktree", "plan-42"], obj=_ctx(git_repo)
    )
    assert result.exit_code == 1
    assert "perk never repositions an existing checkout" in result.output


def test_id_vs_binding_full_field_disagreement_fails_before_launch(git_repo, monkeypatch):
    # The full-ref equality check: right branch, but the binding disagrees field-by-field
    # (a stale binding for the same plan id still refuses — equality is every PlanRef field).
    _authed(monkeypatch)
    ref7 = _canonical_plan(monkeypatch, "7")
    wt = git_repo / ".worktrees" / "plan-7"
    git.worktree_add(git_repo, wt, branch="plan-7", create_branch=True)
    cache.write_plan_ref(wt, plan.PlanRef(provider="github", pr_id="7", url="u/stale", labels=()))
    monkeypatch.setattr(
        launch, "_exec_pi", lambda _ctx: (_ for _ in ()).throw(AssertionError("launched"))
    )
    result = CliRunner().invoke(cli, ["pr", "address", "7"], obj=_ctx(git_repo))
    assert result.exit_code == 1
    assert "disagrees with the worktree binding" in result.output
    assert "url" in result.output and "labels" in result.output  # the differing fields, named
    assert cache.read_plan_ref(wt) != ref7  # the binding was not rewritten


def test_branch_mismatch_fails_before_launch(git_repo):
    wt = _seed(git_repo)
    subprocess.run(
        ["git", "checkout", "-q", "-b", "not-the-plan-branch"],
        cwd=wt,
        check=True,
        capture_output=True,
    )
    result = CliRunner().invoke(cli, ["pr", "address", "--dry-run"], obj=_ctx(git_repo))
    assert result.exit_code == 1
    assert "checked out on branch" in result.output


def test_unbound_checkout_fails_before_launch(git_repo):
    wt = _seed(git_repo)
    cache.plan_ref_path(wt).unlink()
    result = CliRunner().invoke(cli, ["pr", "address", "--dry-run"], obj=_ctx(git_repo))
    assert result.exit_code == 1
    assert "no readable plan-ref binding" in result.output


def test_worktree_with_remote_is_rejected(git_repo):
    _seed(git_repo)
    result = CliRunner().invoke(
        cli, ["pr", "address", "--worktree", "plan-42", "--remote", ""], obj=_ctx(git_repo)
    )
    assert result.exit_code == 1
    assert "--worktree cannot combine with --remote" in result.output


def test_plan_with_remote_dispatches_the_selected_ref(git_repo, monkeypatch):
    # Selection happens BEFORE the local-vs-remote split: --remote receives the resolved ref
    # directly (never a re-read of the root cache, which still names plan 42 here).
    _seed(git_repo)
    _authed(monkeypatch)
    ref7 = _canonical_plan(monkeypatch, "7")
    dispatched: dict = {}
    monkeypatch.setattr(launch, "_drive_remote_target", lambda **k: dispatched.update(k))
    result = CliRunner().invoke(cli, ["pr", "address", "7", "--remote", ""], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output
    assert dispatched["plan_ref"] == ref7
    assert dispatched["stage"].id == "address"


def test_real_launch_materialized_ref_handoff_and_cwd_agree(git_repo, monkeypatch):
    # Exec-stubbed real launch (explicit id, existing bound checkout): the positioner's ref,
    # the handoff, the cwd, and the worktree's extension-consumed binding all name plan 7 —
    # while the MAIN-root selector write is the only selector mutation.
    _authed(monkeypatch)
    ref7 = _canonical_plan(monkeypatch, "7")
    wt7 = git_repo / ".worktrees" / "plan-7"
    git.worktree_add(git_repo, wt7, branch="plan-7", create_branch=True)
    cache.write_plan_ref(wt7, ref7)
    stale = plan.PlanRef(provider="github", pr_id="42", url="u/42", labels=("perk:plan",))
    cache.write_plan_ref(git_repo, stale)  # the pre-existing (different) root selector
    captured: dict = {}
    monkeypatch.setattr(launch, "_exec_pi", lambda ctx: captured.update(ctx=ctx))
    monkeypatch.setattr(launch, "_warm_extension_install", lambda _ctx: None)
    monkeypatch.setattr(launch, "_materialize_into_worktree", lambda _ctx: None)
    result = CliRunner().invoke(cli, ["pr", "address", "7"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output
    ctx = captured["ctx"]
    assert ctx.resolved.path == wt7  # cwd: the selected plan's checkout
    assert ctx.resolved.plan_ref == ref7  # launch authority: the resolved ref
    handoff = cache.read_handoff(wt7, ctx.rid)
    assert handoff is not None and handoff.stage == "address"
    assert cache.read_plan_ref(wt7) == ref7  # the extension-consumed binding
    assert cache.read_plan_ref(git_repo) == ref7  # the main-root selector was updated


def test_address_explicit_id_inside_linked_worktree_writes_main_selector_only(
    git_repo, monkeypatch
):
    # Invoked from INSIDE a different plan's linked worktree, `perk address 7` updates only the
    # MAIN-root selector, leaves the invoking worktree's durable binding byte-identical, and
    # positions into the selected plan's own worktree under the MAIN root.
    from perk.cli.context import PerkContext

    _authed(monkeypatch)
    ref7 = _canonical_plan(monkeypatch, "7")
    wt7 = git_repo / ".worktrees" / "plan-7"
    git.worktree_add(git_repo, wt7, branch="plan-7", create_branch=True)
    cache.write_plan_ref(wt7, ref7)
    invoking = _seed(git_repo)  # the plan-42 linked worktree we invoke FROM
    binding_bytes = cache.plan_ref_path(invoking).read_bytes()
    captured: dict = {}
    monkeypatch.setattr(launch, "_exec_pi", lambda ctx: captured.update(ctx=ctx))
    monkeypatch.setattr(launch, "_warm_extension_install", lambda _ctx: None)
    monkeypatch.setattr(launch, "_materialize_into_worktree", lambda _ctx: None)
    ctx = PerkContext.for_test(
        cwd=invoking, repo_root=invoking, config=Config(worktree_root=git_repo / ".worktrees")
    )
    result = CliRunner().invoke(cli, ["pr", "address", "7"], obj=ctx)
    assert result.exit_code == 0, result.output
    assert captured["ctx"].resolved.path == wt7  # positioned under the MAIN root
    assert captured["ctx"].resolved.plan_ref == ref7
    assert cache.read_plan_ref(git_repo) == ref7  # the MAIN-root selector was written...
    assert cache.plan_ref_path(invoking).read_bytes() == binding_bytes  # ...never the binding


def test_address_no_arg_inside_linked_worktree_selects_its_own_plan(git_repo):
    # The no-argument cache fallback reads the INVOCATION root: inside a plan worktree that is
    # the worktree's own binding, even when the main-root selector names a different plan.
    from perk.cli.context import PerkContext

    wt42 = _seed(git_repo)
    cache.write_plan_ref(
        git_repo, plan.PlanRef(provider="github", pr_id="9", url="u/9", labels=("perk:plan",))
    )
    ctx = PerkContext.for_test(
        cwd=wt42, repo_root=wt42, config=Config(worktree_root=git_repo / ".worktrees")
    )
    payload = _dry_payload(CliRunner().invoke(cli, ["pr", "address", "--dry-run"], obj=ctx))
    assert payload["plan_ref"]["pr_id"] == "42"  # its own plan, not the main selector's #9
