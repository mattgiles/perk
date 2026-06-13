from pathlib import Path

from click.testing import CliRunner

from perk.cli.cli import cli
from perk.cli.context import PerkContext
from perk.substrate.config import Config


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


def test_learn_is_dedicated_hybrid_group(git_repo):
    # Node 2.2: `learn` is a hand-written hybrid group — bare invocation default-dispatches to the
    # hidden stage launcher (byte-identical to the generated launcher); `capture`/`docs` are verbs.
    from perk.cli.stages import DEDICATED_STAGES

    assert "learn" in DEDICATED_STAGES

    # Bare launcher preserved: a non-verb invocation falls through to the hidden launcher, with
    # launcher options (--worktree/--dry-run) surviving group-level parsing intact.
    (git_repo / ".worktrees" / "wt1").mkdir(parents=True)  # learn reuses an existing worktree
    dry = CliRunner().invoke(cli, ["learn", "--worktree", "wt1", "--dry-run"], obj=_ctx(git_repo))
    assert dry.exit_code == 0, dry.output
    assert "would launch stage 'learn'" in dry.output

    # `--help` renders the GROUP help (listing the verbs), not the launcher's.
    helped = CliRunner().invoke(cli, ["learn", "--help"])
    assert helped.exit_code == 0
    assert "capture" in helped.output and "docs" in helped.output

    # The verbs resolve.
    assert CliRunner().invoke(cli, ["learn", "capture", "--help"]).exit_code == 0
    assert CliRunner().invoke(cli, ["learn", "docs", "--help"]).exit_code == 0

    # The old flat spellings (and their aliases) are gone.
    for old in (["learn-capture", "--json"], ["learn-docs", "--json"], ["lc"], ["ldocs"]):
        gone = CliRunner().invoke(cli, old)
        assert gone.exit_code == 2
        assert "No such command" in gone.output


def test_remote_door_blocked():
    # plan is cold_remote:false (P2.T8c) -> local-only.
    result = CliRunner().invoke(cli, ["plan", "--remote"], obj=_ctx(Path("/repo")))
    assert result.exit_code == 1
    assert "local-only" in result.output


def test_implement_remote_dry_run_is_dispatch_preview(git_repo):
    # implement is cold_remote:true (Node 2.1): --remote --dry-run is a side-effect-free dispatch
    # PREVIEW (success:true), not the retired not-driven error exit.
    import json

    from perk.state import cache

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
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["success"] is True and payload["dry_run"] is True
    assert payload["stage"] == "implement"


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


def _submit_merged_command():
    # Build an *unregistered* MergedCommand over the real `submit` stage + the `submit_pr` worker
    # (Node 2.1, D1/D2): no live command is folded — this proves the factory in isolation.
    from perk.cli.commands.pr.submit_cmd import submit_pr
    from perk.cli.stages import make_merged_command
    from perk.substrate.registry import load_registry

    stage = next(s for s in load_registry().stages if s.id == "submit")
    return make_merged_command(stage, submit_pr)


def _seed_plan_ref(repo):
    from perk.state import cache

    cache.write_plan_ref(
        repo,
        {
            "provider": "github",
            "pr_id": "42",
            "url": "u/42",
            "labels": ["perk:plan"],
            "objective_id": None,
        },
    )


def test_merged_command_launcher_default(git_repo):
    # No --json → launcher half → opens (here, dry-runs) the primed pi session for `submit`.
    (git_repo / ".worktrees" / "wt1").mkdir(parents=True)  # submit reuses an existing worktree
    cmd = _submit_merged_command()
    result = CliRunner().invoke(cmd, ["--worktree", "wt1", "--dry-run"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output
    assert "would launch stage 'submit'" in result.output


def test_merged_command_json_routes_to_worker(git_repo):
    # --json anywhere → worker half → deterministic machine output (offline dry-run).
    import json

    _seed_plan_ref(git_repo)
    cmd = _submit_merged_command()
    result = CliRunner().invoke(cmd, ["--json", "--dry-run"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["success"] is True
    assert payload["dry_run"] is True


def test_merged_command_help_shows_launcher_body_and_worker_note():
    # --help (no --json) renders the launcher half's help body PLUS the worker-routing note.
    cmd = _submit_merged_command()
    result = CliRunner().invoke(cmd, ["--help"])
    assert result.exit_code == 0, result.output
    assert "Opens a primed pi session for the 'submit' stage" in result.output
    assert "Run with --json to execute the deterministic worker" in result.output


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
