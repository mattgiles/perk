"""The shared seeded-cold-door pipeline (`perk/cli/commands/seeded_door.py`) and its two
primitives (`registry.stage_by_id`, `emit.fail`).

`launch.launch_stage` is stubbed on its defining module (no `exec pi`); the toy doors inject a
`PerkContext.for_test` so no git repo / GitHub is touched.
"""

import json
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from perk.cli.commands.seeded_door import SeededLaunch, run_seeded_door, seeded_door_options
from perk.cli.context import PerkContext
from perk.cli.emit import fail
from perk.cli.ensure import UserFacingCliError
from perk.run import launch
from perk.substrate.config import Config
from perk.substrate.registry import RegistryError, stage_by_id

# ------------------------------------------------------------------- stage_by_id


def test_stage_by_id_returns_the_registry_stage():
    stage = stage_by_id("plan")
    assert stage.id == "plan"
    assert stage.mode == "read-only"


def test_stage_by_id_unknown_id_raises_registry_error_not_stop_iteration():
    with pytest.raises(RegistryError, match="unknown stage id: 'no-such-stage'"):
        stage_by_id("no-such-stage")


# --------------------------------------------------------------------------- fail


@click.command("failer")
@click.option("--json", "as_json", is_flag=True)
@click.option("--error-type", default="boom")
@click.option("--with-extra", is_flag=True)
@click.pass_context
def _failer(ctx: click.Context, *, as_json: bool, error_type: str, with_extra: bool) -> None:
    fail(
        ctx,
        as_json=as_json,
        error_type=error_type,
        message="the message",
        extra={"dry_run": False} if with_extra else None,
    )


def test_fail_json_payload_shape_without_extra():
    result = CliRunner().invoke(_failer, ["--json"])
    assert result.exit_code == 1
    assert result.stdout.strip() == (
        '{"success": false, "error_type": "boom", "message": "the message"}'
    )


def test_fail_json_extra_merges_after_the_base_keys():
    result = CliRunner().invoke(_failer, ["--json", "--with-extra"])
    assert result.exit_code == 1
    assert result.stdout.strip() == (
        '{"success": false, "error_type": "boom", "message": "the message", "dry_run": false}'
    )


def test_fail_not_a_repo_exits_2():
    result = CliRunner().invoke(_failer, ["--json", "--error-type", "not_a_repo"])
    assert result.exit_code == 2


def test_fail_human_path_writes_styled_error_to_stderr():
    result = CliRunner().invoke(_failer, [])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Error: the message" in result.stderr


# ----------------------------------------------------------------- run_seeded_door


class _BackendBoom(Exception):
    pass


def _spec(**over: object) -> SeededLaunch:
    base: dict = {
        "seed": "SEED TEXT",
        "launch_note": "launching toy",
        "dry_run_label": "toy --dry-run (report only)",
        "dry_run_fields": ("  toy=1  scratch=s.md",),
        "dry_run_payload": {"success": True, "error_type": None, "toy": 1, "dry_run": True},
    }
    base.update(over)
    return SeededLaunch(**base)


def _toy_door(gather) -> click.Command:
    @click.command("toy")
    @seeded_door_options(worktree_help="W.", dry_run_help="D.", remote_subject="toy")
    @click.pass_context
    def toy(
        ctx: click.Context,
        *,
        worktree: str | None,
        dry_run: bool,
        remote: str | None,
        as_json: bool,
        no_sync: bool,
        pi_args: tuple[str, ...],
    ) -> None:
        run_seeded_door(
            ctx,
            stage_id="plan",
            worktree=worktree,
            dry_run=dry_run,
            remote=remote,
            as_json=as_json,
            no_sync=no_sync,
            pi_args=pi_args,
            backend_errors=(_BackendBoom,),
            gather=gather,
        )

    return toy


def _invoke(cmd: click.Command, args: list[str], tmp_path: Path):
    obj = PerkContext.for_test(repo_root=tmp_path, config=Config(worktree_root=tmp_path))
    return CliRunner().invoke(cmd, args, obj=obj)


def _no_launch(monkeypatch) -> None:
    def boom(**k):
        raise AssertionError("launch_stage must not be called")

    monkeypatch.setattr(launch, "launch_stage", boom)


def test_backend_error_maps_to_github_error(monkeypatch, tmp_path):
    _no_launch(monkeypatch)

    def gather(repo_root, config, stage):
        raise _BackendBoom("backend down")

    result = _invoke(_toy_door(gather), ["--json"], tmp_path)
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload == {"success": False, "error_type": "github_error", "message": "backend down"}


def test_user_facing_error_maps_to_its_error_type(monkeypatch, tmp_path):
    _no_launch(monkeypatch)

    def gather(repo_root, config, stage):
        raise UserFacingCliError("not open", error_type="plan_not_open")

    result = _invoke(_toy_door(gather), ["--json"], tmp_path)
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "plan_not_open"


def test_user_facing_error_without_type_defaults_to_invalid_input(monkeypatch, tmp_path):
    _no_launch(monkeypatch)

    def gather(repo_root, config, stage):
        raise UserFacingCliError("bad input")

    result = _invoke(_toy_door(gather), ["--json"], tmp_path)
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "invalid_input"


def test_dry_run_json_emits_exactly_the_policy_payload(monkeypatch, tmp_path):
    _no_launch(monkeypatch)
    spec = _spec()
    result = _invoke(_toy_door(lambda r, c, s: spec), ["--dry-run", "--json"], tmp_path)
    assert result.exit_code == 0
    # A single JSON object on stdout, byte-identical to the policy payload.
    assert result.stdout.strip() == json.dumps(spec.dry_run_payload)


def test_dry_run_human_renders_label_fields_and_seed(monkeypatch, tmp_path):
    _no_launch(monkeypatch)
    result = _invoke(_toy_door(lambda r, c, s: _spec()), ["--dry-run"], tmp_path)
    assert result.exit_code == 0
    assert "toy --dry-run (report only)" in result.stderr
    assert "  toy=1  scratch=s.md" in result.stderr
    assert "── seed prompt ──" in result.stderr
    assert "SEED TEXT" in result.stderr


def test_dry_run_human_suppresses_seed_when_flagged_off(monkeypatch, tmp_path):
    _no_launch(monkeypatch)
    spec = _spec(dry_run_shows_seed=False)
    result = _invoke(_toy_door(lambda r, c, s: spec), ["--dry-run"], tmp_path)
    assert result.exit_code == 0
    assert "toy --dry-run (report only)" in result.stderr
    assert "── seed prompt ──" not in result.stderr
    assert "SEED TEXT" not in result.stderr


def test_real_launch_threads_the_spec_through_launch_stage(monkeypatch, tmp_path):
    captured: dict = {}
    monkeypatch.setattr(launch, "launch_stage", lambda **k: captured.update(k))
    spec = _spec(
        handoff_extra={"adopt_from": "42"},
        binding_trigger="command:toy",
        run_id_override="RID",
    )
    result = _invoke(_toy_door(lambda r, c, s: spec), ["--json", "--no-sync"], tmp_path)
    assert result.exit_code == 0
    assert captured["stage"].id == "plan"
    assert captured["prompt_override"] == "SEED TEXT"
    assert captured["handoff_extra"] == {"adopt_from": "42"}
    assert captured["binding_trigger"] == "command:toy"
    assert captured["run_id_override"] == "RID"
    assert captured["sync_main"] is False
    assert captured["dry_run"] is False
    # The launch note is a --json-only stderr line.
    assert "launching toy" in result.stderr


def test_real_launch_prints_no_launch_note_without_json(monkeypatch, tmp_path):
    monkeypatch.setattr(launch, "launch_stage", lambda **k: None)
    result = _invoke(_toy_door(lambda r, c, s: _spec()), [], tmp_path)
    assert result.exit_code == 0
    assert "launching toy" not in result.stderr


def test_gather_receives_repo_root_config_and_stage(monkeypatch, tmp_path):
    monkeypatch.setattr(launch, "launch_stage", lambda **k: None)
    seen: dict = {}

    def gather(repo_root, config, stage):
        seen.update(repo_root=repo_root, config=config, stage=stage)
        return _spec()

    result = _invoke(_toy_door(gather), [], tmp_path)
    assert result.exit_code == 0
    assert seen["repo_root"] == tmp_path
    assert seen["config"].worktree_root == tmp_path
    assert seen["stage"].id == "plan"


# -------------------------------------------------------------- seeded_door_options


def test_seeded_door_options_renders_help_in_canonical_order():
    @click.command("toy")
    @click.argument("plan")
    @seeded_door_options(
        worktree_help="Worktree to position (toy runs at repo root).",
        dry_run_help="Materialize + print the seed; launch nothing.",
        remote_subject="toy",
    )
    @click.pass_context
    def toy(ctx: click.Context, **_kw: object) -> None:
        pass

    result = CliRunner().invoke(toy, ["--help"])
    assert result.exit_code == 0
    help_text = result.output
    # The leading argument stays ahead of the shared block in the usage line.
    assert "PLAN [PI_ARGS]..." in help_text
    # The five shared options render in the canonical order with the parameterized phrases.
    indices = [
        help_text.index("--worktree"),
        help_text.index("--dry-run"),
        help_text.index("--remote"),
        help_text.index("--json"),
        help_text.index("--no-sync"),
    ]
    assert indices == sorted(indices)
    normalized = " ".join(help_text.split())  # Click wraps long help onto a second row
    assert "Worktree to position (toy runs at repo root)." in normalized
    assert "Materialize + print the seed; launch nothing." in normalized
    assert "toy is local-only (cold_remote:false)." in normalized


# ------------------------------------------------------------- source-scan guard

_CLI_ROOT = Path(__file__).resolve().parent.parent / "src" / "perk" / "cli"

# The sanctioned `fail`/`_fail` definition sites: the canonical reporter, plan save's
# extra-delegating wrapper (baked `"dry_run": False`), and the deliberately-divergent
# always-exit-1 `skills_fail` home.
_FAIL_DEF_ALLOWLIST = {
    "emit.py",
    "commands/plan/save_cmd.py",
    "commands/skills/shared.py",
}


def _cli_sources() -> list[tuple[str, Path]]:
    """Every production module under `perk/cli/`, keyed by its cli-relative posix path."""
    files = sorted(_CLI_ROOT.rglob("*.py"))
    rel = [(p.relative_to(_CLI_ROOT).as_posix(), p) for p in files]
    # Self-check against a vacuous scan: the tree is non-empty and contains known anchors.
    names = {r for r, _ in rel}
    assert "ensure.py" in names and "commands/seeded_door.py" in names
    return rel


def test_no_stage_lookup_idiom_outside_stage_by_id():
    """The `next(s for s in load_registry().stages if ...)` idiom is retired — every stage
    lookup goes through `registry.stage_by_id` (which raises RegistryError, not StopIteration)."""
    violations = [
        f"{rel}:{n}: {line.strip()}"
        for rel, path in _cli_sources()
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if "next(s for s in load_registry" in line
    ]
    assert not violations, (
        "stage lookups must use perk.substrate.registry.stage_by_id, not the inline "
        "next(...) idiom:\n" + "\n".join(violations)
    )


def test_no_fail_definitions_outside_the_allowlist():
    """`fail`/`_fail` copies are retired — the canonical reporter lives in `perk.cli.emit`;
    only the allowlisted wrappers may define one."""
    violations = [
        f"{rel}:{n}: {line.strip()}"
        for rel, path in _cli_sources()
        if rel not in _FAIL_DEF_ALLOWLIST
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if line.lstrip().startswith(("def fail(", "def _fail("))
    ]
    assert not violations, (
        "failure reporting must go through perk.cli.emit.fail (or an allowlisted wrapper):\n"
        + "\n".join(violations)
    )
    # Pattern-matches-the-seam self-check: the canonical definition itself is found.
    emit_text = (_CLI_ROOT / "emit.py").read_text(encoding="utf-8")
    assert "def fail(" in emit_text
