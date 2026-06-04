from pathlib import Path

from click.testing import CliRunner

from perk.cli.cli import cli
from perk.cli.context import PerkContext
from perk.config import Config


def _ctx(repo: Path) -> PerkContext:
    return PerkContext.for_test(
        cwd=repo, repo_root=repo, config=Config(worktree_root=repo / ".worktrees")
    )


def test_all_stages_are_generated():
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    for stage_id in (
        "objective-author",
        "objective-save",
        "objective-plan",
        "plan",
        "save",
        "implement",
        "submit",
        "address",
        "land",
        "learn",
    ):
        assert stage_id in result.output


def test_objective_plan_is_dedicated_not_generic():
    # P2.T10: objective-plan is a dedicated command (in DEDICATED_STAGES), skipped by the generic
    # generator — so it carries its own positional NUMBER arg, not the generic launcher shape.
    from perk.cli.stages import DEDICATED_STAGES

    assert "objective-plan" in DEDICATED_STAGES
    result = CliRunner().invoke(cli, ["objective-plan", "--help"])
    assert result.exit_code == 0
    assert "NUMBER" in result.output  # the dedicated command's positional arg


def test_objective_author_is_dedicated_and_local_only(git_repo):
    # P3.T2: objective-author is a dedicated seeded launcher (no positional number); local-only.
    from perk.cli.stages import DEDICATED_STAGES

    assert "objective-author" in DEDICATED_STAGES
    helped = CliRunner().invoke(cli, ["objective-author", "--help"])
    assert helped.exit_code == 0
    # A dry-run resolves + prints the launch plan (seeded prompt), launching nothing.
    dry = CliRunner().invoke(cli, ["objective-author", "--dry-run"], obj=_ctx(git_repo))
    assert dry.exit_code == 0, dry.output
    assert "would launch stage 'objective-author'" in dry.output
    # --remote is rejected (cold_remote:false).
    remote = CliRunner().invoke(cli, ["objective-author", "--remote"], obj=_ctx(git_repo))
    assert remote.exit_code == 1
    assert "local-only" in remote.output


def test_remote_door_blocked():
    # plan is cold_remote:false (P2.T8c) -> local-only.
    result = CliRunner().invoke(cli, ["plan", "--remote"], obj=_ctx(Path("/repo")))
    assert result.exit_code == 1
    assert "local-only" in result.output


def test_implement_remote_resolves_then_exits_not_driven(git_repo):
    # implement is cold_remote:true (P2.T8c): --remote resolves a remote target descriptor (stdout
    # json) and exits remote_not_driven; it does NOT drive the (unbuilt) Phase-3 worker.
    import json

    from perk import cache

    cache.write_plan_ref(
        git_repo,
        {
            "provider": "github",
            "pr_id": "42",
            "url": "u/42",
            "labels": ["perk:plan"],
            "objective_id": None,
        },
    )
    result = CliRunner().invoke(cli, ["implement", "--remote", "--dry-run"], obj=_ctx(git_repo))
    assert result.exit_code == 1
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["error_type"] == "remote_not_driven" and payload["stage"] == "implement"


def test_plan_local_dry_run_still_launches(git_repo):
    # No --remote: the local path is unchanged (dry-run prints the launch plan, exits 0).
    result = CliRunner().invoke(cli, ["plan", "--dry-run"], obj=_ctx(git_repo))
    assert result.exit_code == 0
    assert "would launch stage 'plan'" in result.output


def test_implement_requires_plan_ref():
    # T4a: implement derives the worktree from the active plan-ref; with none, it asks for a plan.
    result = CliRunner().invoke(cli, ["implement"], obj=_ctx(Path("/repo")))
    assert result.exit_code == 1
    assert "needs a saved plan" in result.output


def test_worktree_create_list_remove(git_repo):
    runner = CliRunner()
    obj = _ctx(git_repo)
    created = runner.invoke(cli, ["worktree", "create", "wt1"], obj=obj)
    assert created.exit_code == 0, created.output
    assert (git_repo / ".worktrees" / "wt1").is_dir()

    listed = runner.invoke(cli, ["worktree", "list"], obj=obj)
    assert "wt1" in listed.output

    removed = runner.invoke(cli, ["worktree", "remove", "wt1"], obj=obj)
    assert removed.exit_code == 0, removed.output
    assert not (git_repo / ".worktrees" / "wt1").exists()
