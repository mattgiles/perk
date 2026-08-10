from pathlib import Path

from click.testing import CliRunner

from perk import plan
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
        "plan",
        "implement",
        "submit",
        "address",
        "land",
        "learn",
    ):
        assert stage_id in result.output


def test_objective_plan_is_dedicated_not_generic():
    # objective-plan is a dedicated command (in DEDICATED_STAGES), skipped by the generic
    # generator — so it carries its own positional NUMBER arg, not the generic launcher shape.
    # It now lives inside the `objective` group as `objective plan`.
    from perk.cli.stages import DEDICATED_STAGES

    assert "objective-plan" in DEDICATED_STAGES
    assert "objective-save" in DEDICATED_STAGES
    result = CliRunner().invoke(cli, ["objective", "plan", "--help"])
    assert result.exit_code == 0
    assert "NUMBER" in result.output  # the dedicated command's positional arg


def test_objective_author_is_dedicated_and_local_only(git_repo):
    # objective author is a dedicated seeded launcher (no positional number); local-only.
    # It now lives inside the `objective` group as `objective author`.
    from perk.cli.stages import DEDICATED_STAGES

    assert "objective-author" in DEDICATED_STAGES
    helped = CliRunner().invoke(cli, ["objective", "author", "--help"])
    assert helped.exit_code == 0
    # A dry-run resolves + prints the launch plan (seeded prompt), launching nothing.
    dry = CliRunner().invoke(cli, ["objective", "author", "--dry-run"], obj=_ctx(git_repo))
    assert dry.exit_code == 0, dry.output
    assert "would launch stage 'objective-author'" in dry.output
    # --remote is rejected (cold_remote:false).
    remote = CliRunner().invoke(cli, ["objective", "author", "--remote"], obj=_ctx(git_repo))
    assert remote.exit_code == 1
    assert "local-only" in remote.output


def test_learn_is_dedicated_hybrid_group(git_repo):
    # `learn` is a hand-written hybrid group — bare invocation default-dispatches to the
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
    assert CliRunner().invoke(cli, ["learn", "harvest", "--help"]).exit_code == 0

    # The old flat spellings (and their aliases) are gone.
    for old in (["learn-capture", "--json"], ["learn-docs", "--json"], ["lc"], ["ldocs"]):
        gone = CliRunner().invoke(cli, old)
        assert gone.exit_code == 2
        assert "No such command" in gone.output


def test_plan_is_dedicated_hybrid_group(git_repo):
    # `plan` is a hand-written hybrid group mirroring `learn` — bare invocation
    # default-dispatches to the hidden stage launcher; `save`/`resume`/`replan` are verbs.
    from perk.cli.stages import DEDICATED_STAGES

    assert "plan" in DEDICATED_STAGES

    # Bare launcher preserved: a non-verb invocation falls through to the hidden launcher, with
    # launcher options (--dry-run/--remote) surviving group-level parsing intact.
    dry = CliRunner().invoke(cli, ["plan", "--dry-run"], obj=_ctx(git_repo))
    assert dry.exit_code == 0, dry.output
    assert "would launch stage 'plan'" in dry.output
    # plan is cold_remote:false -> local-only, even through the hidden launcher.
    remote = CliRunner().invoke(cli, ["plan", "--remote"], obj=_ctx(git_repo))
    assert remote.exit_code == 1
    assert "local-only" in remote.output

    # `--help` renders the GROUP help (listing the verbs), not the launcher's.
    helped = CliRunner().invoke(cli, ["plan", "--help"])
    assert helped.exit_code == 0
    assert all(v in helped.output for v in ("save", "resume", "replan"))

    # The verbs resolve.
    assert CliRunner().invoke(cli, ["plan", "save", "--help"]).exit_code == 0
    assert CliRunner().invoke(cli, ["plan", "resume", "--help"]).exit_code == 0
    assert CliRunner().invoke(cli, ["plan", "replan", "--help"]).exit_code == 0

    # The old flat spellings (and their aliases) are gone with no back-compat alias.
    for old in (
        ["save"],
        ["resume", "42"],
        ["replan", "42"],
        ["plan-save"],
        ["psave"],
        ["res"],
        ["rp"],
    ):
        gone = CliRunner().invoke(cli, old)
        assert gone.exit_code == 2, old
        assert "No such command" in gone.output


def test_implement_remote_dry_run_is_dispatch_preview(git_repo):
    # implement is cold_remote:true: --remote --dry-run is a side-effect-free dispatch
    # PREVIEW (success:true), not the retired not-driven error exit.
    import json

    from perk.state import cache

    cache.write_plan_ref(
        git_repo,
        plan.PlanRef(
            provider="github",
            pr_id="42",
            url="u/42",
            labels=("perk:plan",),
            objective_id=None,
        ),
    )
    result = CliRunner().invoke(cli, ["implement", "--remote", "--dry-run"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["success"] is True and payload["dry_run"] is True
    assert payload["stage"] == "implement"


def test_plan_save_merged_launcher_default(git_repo):
    # `perk plan save` with NO --json hits the launcher half (a session), end-to-end
    # through the registered `cli` (not an unregistered factory build).
    (git_repo / ".worktrees" / "wt1").mkdir(parents=True)  # save reuses an existing worktree
    result = CliRunner().invoke(
        cli, ["plan", "save", "--worktree", "wt1", "--dry-run"], obj=_ctx(git_repo)
    )
    assert result.exit_code == 0, result.output
    assert "would launch stage 'save'" in result.output


def test_plan_save_merged_json_routes_to_worker(git_repo):
    # `perk plan save --json` routes to the deterministic worker (machine output).
    import json

    plan_file = git_repo / "plan.md"
    plan_file.write_text("# A plan\n\nbody\n", encoding="utf-8")
    result = CliRunner().invoke(
        cli,
        ["plan", "save", "--json", "--dry-run", "--plan-file", str(plan_file)],
        obj=_ctx(git_repo),
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["success"] is True
    assert payload["dry_run"] is True


def test_implement_requires_plan_ref():
    # implement derives the worktree from the active plan-ref; with none, it asks for a plan.
    result = CliRunner().invoke(cli, ["implement"], obj=_ctx(Path("/repo")))
    assert result.exit_code == 1
    assert "needs a saved plan" in result.output


def _submit_merged_command():
    # Build an *unregistered* MergedCommand over the real `submit` stage + the `submit_pr` worker
    # (D1/D2): no live command is folded — this proves the factory in isolation.
    from perk.cli.commands.pr.submit_cmd import submit_pr
    from perk.cli.stages import make_merged_command
    from perk.substrate.registry import load_registry

    stage = next(s for s in load_registry().stages if s.id == "submit")
    return make_merged_command(stage, submit_pr)


def _seed_plan_ref(repo):
    from perk.state import cache

    cache.write_plan_ref(
        repo,
        plan.PlanRef(
            provider="github",
            pr_id="42",
            url="u/42",
            labels=("perk:plan",),
            objective_id=None,
        ),
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


def test_remote_help_census_states_cold_remote_scope():
    # The --remote help states the door scope per stage. Keyed off the registry doors (not a
    # hand-written stage list) so this census can't drift from test_registry.py's
    # cold_remote == {"implement", "address"} pin.
    from perk.substrate.registry import load_registry

    remotable = {s.id for s in load_registry().stages if s.doors.get("cold_remote") is True}
    surfaces: dict[str, list[str]] = {
        # Merged launcher+worker commands + the hidden bare `plan`/`learn` launchers (the
        # hidden `launch` verbs): the generic make_stage_launcher help is their only
        # --remote help surface.
        "submit": ["pr", "submit"],
        "land": ["pr", "land"],
        "save": ["plan", "save"],
        "plan": ["plan", "launch"],
        "learn": ["learn", "launch"],
        # The remotely runnable dedicated commands must NOT claim to be local-only.
        "implement": ["implement"],
        "address": ["pr", "address"],
    }
    for stage_id, argv in surfaces.items():
        result = CliRunner().invoke(cli, [*argv, "--help"])
        assert result.exit_code == 0, result.output
        flat = " ".join(result.output.split())  # Click wraps help text; compare unwrapped
        if stage_id in remotable:
            assert "local-only (cold_remote:false)" not in flat, argv
        else:
            assert "local-only (cold_remote:false)" in flat, argv

    # `plan resume`'s stage-dynamic --remote help statically names the remotable set; pin it to
    # the registry so the wording can't drift if the set ever changes.
    result = CliRunner().invoke(cli, ["plan", "resume", "--help"])
    assert result.exit_code == 0, result.output
    flat = " ".join(result.output.split())
    for stage_id in remotable:
        assert stage_id in flat, f"plan resume --remote help must name '{stage_id}'"


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
