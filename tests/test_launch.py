import dataclasses
import json
import os
import subprocess
from pathlib import Path

import pytest
from _launch_helpers import _PLAN_REF, _PLAN_REF_JSON, _PLAN_REF_MODEL, _config, _request, _stage

from perk import __version__, plan
from perk.cli.ensure import UserFacingCliError
from perk.delivery import DeliveryError, PrepareResult
from perk.run import launch
from perk.run.launch import (
    _address_prompt,
    _build_exec_env,
    _initial_prompt,
    _pi_agent_dir,
    _stage_model_argv,
    _sweep_stale_pi_agent_locks,
    launch_stage,
    resolve_base,
    resolve_plan_worktree_name,
    resolve_target,
    resolve_worktree,
)
from perk.run.launch import worktree as worktree_mod
from perk.state import cache
from perk.substrate import git as git_mod
from perk.substrate.bindings import Binding
from perk.substrate.config import Config, StageModel
from perk.substrate.git import GitError
from perk.substrate.skill_exposure import SkillsPolicy

pytestmark = pytest.mark.usefixtures("stub_launch_extension_warm")


def _pointer(skill: str) -> str:
    """The path-carrying nudge pointer line the renderer emits for ``skill``."""
    return f"Follow the `{skill}` skill (read `.agents/skills/{skill}/SKILL.md`)."


def _binding(trigger: str, skill: str, mode: str = "nudge") -> "Binding":
    return Binding(trigger=trigger, skill=skill, mode=mode)


def test_sweep_removes_stale_lock_files(tmp_path):
    """A stale regular *file* at each agent-dir lock path is removed."""
    for name in ("settings.json.lock", "auth.json.lock"):
        (tmp_path / name).write_text("", encoding="utf-8")
    _sweep_stale_pi_agent_locks(tmp_path)
    assert not (tmp_path / "settings.json.lock").exists()
    assert not (tmp_path / "auth.json.lock").exists()


def test_sweep_leaves_live_lock_directory(tmp_path):
    """A directory is a *live* proper-lockfile lock — never touched (the safety guarantee)."""
    (tmp_path / "settings.json.lock").mkdir()
    _sweep_stale_pi_agent_locks(tmp_path)
    assert (tmp_path / "settings.json.lock").is_dir()


def test_sweep_is_noop_when_absent(tmp_path):
    """No lock paths present — no exception."""
    _sweep_stale_pi_agent_locks(tmp_path)  # must not raise


def test_sweep_swallows_oserror(tmp_path, monkeypatch):
    """A removal OSError never propagates (best-effort/non-fatal)."""
    (tmp_path / "settings.json.lock").write_text("", encoding="utf-8")

    def _boom(self, *a, **k):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "unlink", _boom)
    _sweep_stale_pi_agent_locks(tmp_path)  # must not raise


def test_pi_agent_dir_honors_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "custom"))
    assert _pi_agent_dir() == tmp_path / "custom"


def test_pi_agent_dir_env_expanduser(monkeypatch):
    monkeypatch.setenv("PI_CODING_AGENT_DIR", "~/somewhere")
    assert _pi_agent_dir() == Path.home() / "somewhere"


def test_pi_agent_dir_falls_back_to_home(monkeypatch):
    monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
    assert _pi_agent_dir() == Path.home() / ".pi" / "agent"


@pytest.mark.parametrize("agent_dir", [None, Path("/configured/agent")])
def test_build_exec_env_pi_agent_dir(agent_dir):
    env = _build_exec_env(
        run_id="01TEST",
        environ={} if agent_dir is None else {"PI_CODING_AGENT_DIR": "/ignored-at-this-layer"},
        fallback_linear_api_key=None,
        pi_agent_dir=agent_dir,
    )
    if agent_dir is None:
        assert "PI_CODING_AGENT_DIR" not in env
    else:
        assert env["PI_CODING_AGENT_DIR"] == str(agent_dir)


@pytest.mark.parametrize("value", ["", " \t ", "/operator/agent", "  /operator/agent  "])
def test_build_exec_env_pi_agent_dir_normalizes_only_blank_values(value):
    environ = {"PI_CODING_AGENT_DIR": value}
    env = _build_exec_env(
        run_id="01TEST",
        environ=environ,
        fallback_linear_api_key=None,
        pi_agent_dir=None,
    )
    if value.strip():
        assert env["PI_CODING_AGENT_DIR"] == value
    else:
        assert "PI_CODING_AGENT_DIR" not in env
    assert environ == {"PI_CODING_AGENT_DIR": value}


def _write_pi_config(root, text):
    config_dir = root / ".perk"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.toml").write_text(text, encoding="utf-8")


def _launch_agent_dir_plan(root, *, dry_run=False):
    # A preloaded caller Config without the knob must not hide the effective disk read.
    launch_stage(
        repo_root=root,
        config=_config(root),
        stage=_stage("plan"),
        worktree=None,
        dry_run=dry_run,
        remote=None,
        pi_args=[],
        sync_main=False,
        run_id_override="01TEST",
    )


@pytest.mark.parametrize("operator_value", [None, "", "  "])
def test_launch_configured_pi_agent_dir_and_lock_sweep(
    tmp_path, monkeypatch, launch_exec_recorder, operator_value
):
    monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
    if operator_value is not None:
        monkeypatch.setenv("PI_CODING_AGENT_DIR", operator_value)
    _write_pi_config(tmp_path, '[pi]\nagent_dir = ".pi/agent"\n')
    agent_dir = tmp_path / ".pi/agent"
    agent_dir.mkdir(parents=True)
    stale_lock = agent_dir / "settings.json.lock"
    stale_lock.touch()
    _launch_agent_dir_plan(tmp_path)
    assert launch_exec_recorder.calls[0][2]["PI_CODING_AGENT_DIR"] == str(agent_dir)
    assert not stale_lock.exists()
    assert "PI_CODING_AGENT_DIR" not in launch_exec_recorder.calls[0][1]


def test_launch_pi_agent_dir_operator_wins_without_config_read(
    tmp_path, monkeypatch, launch_exec_recorder
):
    monkeypatch.setenv("PI_CODING_AGENT_DIR", "/operator/agent")

    def no_read(root):
        pytest.fail("operator choice must skip the main-root config read")

    monkeypatch.setattr(launch, "effective_pi_agent_dir", no_read)
    _launch_agent_dir_plan(tmp_path)
    assert launch_exec_recorder.calls[0][2]["PI_CODING_AGENT_DIR"] == "/operator/agent"


def test_remote_launch_never_reads_pi_agent_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)

    def no_read(root):
        pytest.fail("remote dispatch must not consult the local agent directory")

    calls = []
    monkeypatch.setattr(launch, "effective_pi_agent_dir", no_read)
    monkeypatch.setattr(launch, "_drive_remote_target", lambda **kwargs: calls.append(kwargs))
    launch_stage(
        repo_root=tmp_path,
        config=_config(tmp_path),
        stage=_stage("implement"),
        worktree=None,
        dry_run=False,
        remote="github",
        pi_args=[],
    )
    assert len(calls) == 1


def test_launch_pi_agent_dir_unconfigured(tmp_path, monkeypatch, launch_exec_recorder):
    monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
    _launch_agent_dir_plan(tmp_path)
    assert "PI_CODING_AGENT_DIR" not in launch_exec_recorder.calls[0][2]


@pytest.mark.parametrize("value", ["", " \t "])
@pytest.mark.parametrize("config_text", ["", "[pi", "[pi]\nagent_dir = 7\n"])
def test_launch_blank_pi_agent_dir_without_config_uses_default_store(
    tmp_path, monkeypatch, launch_exec_recorder, capsys, value, config_text
):
    monkeypatch.setenv("PI_CODING_AGENT_DIR", value)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    # Exercise the real fallback instead of the exec fixture's isolated-directory stub.
    monkeypatch.setattr(launch, "_pi_agent_dir", _pi_agent_dir)
    default_dir = tmp_path / "home/.pi/agent"
    default_dir.mkdir(parents=True)
    stale_lock = default_dir / "settings.json.lock"
    stale_lock.touch()
    _write_pi_config(tmp_path, config_text)

    _launch_agent_dir_plan(tmp_path)

    assert "PI_CODING_AGENT_DIR" not in launch_exec_recorder.calls[0][2]
    assert not stale_lock.exists()
    assert os.environ["PI_CODING_AGENT_DIR"] == value
    if config_text:
        assert "launching without the redirect" in capsys.readouterr().err


def test_launch_pi_agent_dir_main_overlay_from_linked_worktree(
    git_repo, monkeypatch, launch_exec_recorder
):
    monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
    _write_pi_config(git_repo, '[pi]\nagent_dir = "committed-agent"\n')
    (git_repo / ".perk/local.toml").write_text(
        '[pi]\nagent_dir = "local-agent"\n', encoding="utf-8"
    )
    agent_dir = git_repo / "local-agent"
    agent_dir.mkdir()
    wt = git_repo / ".worktrees/linked"
    git_mod.worktree_add(git_repo, wt, branch="linked", create_branch=True)
    _launch_agent_dir_plan(wt)
    assert launch_exec_recorder.calls[0][2]["PI_CODING_AGENT_DIR"] == str(agent_dir)


def test_launch_missing_pi_agent_dir_warns_and_execs(
    tmp_path, monkeypatch, capsys, launch_exec_recorder
):
    monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
    _write_pi_config(tmp_path, '[pi]\nagent_dir = "missing"\n')
    _launch_agent_dir_plan(tmp_path)
    assert launch_exec_recorder.calls[0][2]["PI_CODING_AGENT_DIR"] == str(tmp_path / "missing")
    assert "no auth.json/models.json" in capsys.readouterr().err
    assert not (tmp_path / "missing").exists()


@pytest.mark.parametrize("dry_run", [False, True])
def test_launch_non_directory_pi_agent_dir_refuses(
    tmp_path, monkeypatch, launch_exec_recorder, dry_run
):
    monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
    _write_pi_config(tmp_path, '[pi]\nagent_dir = "file"\n')
    (tmp_path / "file").touch()
    with pytest.raises(UserFacingCliError, match="not a directory") as exc:
        _launch_agent_dir_plan(tmp_path, dry_run=dry_run)
    assert exc.value.error_type == "pi_agent_dir_invalid"
    assert launch_exec_recorder.calls == []


@pytest.mark.parametrize("text", ["[pi", "[pi]\nagent_dir = 7\n"])
def test_launch_bad_main_pi_config_warns_without_redirect(
    tmp_path, monkeypatch, capsys, launch_exec_recorder, text
):
    monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
    _write_pi_config(tmp_path, text)
    _launch_agent_dir_plan(tmp_path)
    assert "PI_CODING_AGENT_DIR" not in launch_exec_recorder.calls[0][2]
    assert "launching without the redirect" in capsys.readouterr().err


def test_launch_pi_agent_dir_home_expansion_failure_warns_and_execs(
    tmp_path, monkeypatch, capsys, launch_exec_recorder
):
    monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
    value = "~missing-user/agent"
    _write_pi_config(tmp_path, f'[pi]\nagent_dir = "{value}"\n')
    expanduser = Path.expanduser

    def fail_configured_home(path):
        if path == Path(value):
            raise RuntimeError("Could not determine home directory.")
        return expanduser(path)

    monkeypatch.setattr(Path, "expanduser", fail_configured_home)
    _launch_agent_dir_plan(tmp_path)
    assert "PI_CODING_AGENT_DIR" not in launch_exec_recorder.calls[0][2]
    err = capsys.readouterr().err
    assert "launching without the redirect" in err
    assert "pi.agent_dir: cannot expand home directory" in err


def test_launch_pi_agent_dir_dry_run_preview(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
    _launch_agent_dir_plan(tmp_path, dry_run=True)
    baseline = capsys.readouterr()
    assert "pi_agent_dir" not in json.loads(baseline.out)
    _write_pi_config(tmp_path, '[pi]\nagent_dir = "missing"\n')
    _launch_agent_dir_plan(tmp_path, dry_run=True)
    configured = capsys.readouterr()
    data = json.loads(configured.out)
    assert data.pop("pi_agent_dir") == str(tmp_path / "missing")
    assert data == json.loads(baseline.out)
    assert f"  PI_CODING_AGENT_DIR={tmp_path / 'missing'}" in configured.err
    assert "no auth.json/models.json" in configured.err
    assert not (tmp_path / "missing").exists()
    (tmp_path / ".perk/config.toml").unlink()
    _launch_agent_dir_plan(tmp_path, dry_run=True)
    assert capsys.readouterr().out == baseline.out


def test_resolve_worktree_none_is_repo_root(tmp_path):
    resolved = resolve_worktree(
        repo_root=tmp_path,
        config=_config(tmp_path),
        request=_request("plan"),
        worktree=None,
        materialize=True,
    )
    assert resolved.path == tmp_path
    assert resolved.plan_ref is None


# --- plan_base drives the start-point ---------------------------------------------


def test_resolve_base_uses_plan_base_as_trunk(monkeypatch, tmp_path):
    # A plan's pinned base replaces the detected trunk as the trunk source.
    monkeypatch.setattr(git_mod, "remote_ref_exists", lambda _root, ref: ref == "origin/develop")

    def _no_detect(_root):
        raise AssertionError("detect_trunk_branch must not run when plan_base is set")

    monkeypatch.setattr(git_mod, "detect_trunk_branch", _no_detect)
    assert resolve_base(tmp_path, "plan-42", None, "develop") == "origin/develop"


def test_resolve_base_explicit_override_wins_over_plan_base(monkeypatch, tmp_path):
    # An explicit --base still wins verbatim, even over a plan_base.
    monkeypatch.setattr(git_mod, "remote_ref_exists", lambda _root, ref: True)
    assert resolve_base(tmp_path, "plan-42", "custom-ref", "develop") == "custom-ref"


def test_resolve_base_no_plan_base_uses_detected_trunk(monkeypatch, tmp_path):
    # With no plan_base, behavior is unchanged: detect_trunk_branch supplies the trunk.
    monkeypatch.setattr(git_mod, "remote_ref_exists", lambda _root, ref: ref == "origin/main")
    monkeypatch.setattr(git_mod, "detect_trunk_branch", lambda _root: "main")
    assert resolve_base(tmp_path, "plan-42", None, None) == "origin/main"


def test_resolve_base_resumed_branch_wins_over_plan_base(monkeypatch, tmp_path):
    # An existing origin/<name> (a resumed/remote plan) is tracked before the plan_base trunk.
    monkeypatch.setattr(git_mod, "remote_ref_exists", lambda _root, ref: True)
    monkeypatch.setattr(git_mod, "detect_trunk_branch", lambda _root: "main")
    assert resolve_base(tmp_path, "plan-42", None, "develop") == "origin/plan-42"


# --- plan-ref-aware worktree resolution -------------------------------------------


@pytest.mark.parametrize(
    ("pr_id", "expected"),
    [("42", "plan-42"), ("PROJ-123", "plan-PROJ-123")],
)
def test_resolve_plan_worktree_name(pr_id, expected):
    ref = dataclasses.replace(_PLAN_REF_MODEL, pr_id=pr_id)
    assert resolve_plan_worktree_name(ref) == expected


@pytest.mark.parametrize("pr_id", ["", "a/b", ".", ".."])
def test_resolve_plan_worktree_name_rejects_unusable(pr_id):
    with pytest.raises(UserFacingCliError, match="unusable as a worktree name"):
        resolve_plan_worktree_name(dataclasses.replace(_PLAN_REF_MODEL, pr_id=pr_id))


def test_implement_no_plan_ref_errors(tmp_path):
    with pytest.raises(UserFacingCliError, match="needs a saved plan") as exc:
        resolve_worktree(
            repo_root=tmp_path,
            config=_config(tmp_path),
            request=_request("implement"),
            worktree=None,
            materialize=False,
        )
    assert exc.value.error_type == "no_plan_ref"


def test_implement_derives_name_from_active_plan_ref(tmp_path):
    cache.write_plan_ref(tmp_path, _PLAN_REF)
    resolved = resolve_worktree(
        repo_root=tmp_path,
        config=_config(tmp_path),
        request=_request("implement"),
        worktree=None,
        materialize=False,  # dry-run: derive without creating
    )
    assert resolved.path == _config(tmp_path).worktree_root / "plan-42"
    assert resolved.plan_ref == _PLAN_REF_MODEL


def test_implement_dry_run_json_carries_worktree_and_plan_ref(tmp_path, capsys):
    cache.write_plan_ref(tmp_path, _PLAN_REF)
    launch_stage(
        repo_root=tmp_path,
        config=_config(tmp_path),
        stage=_stage("implement"),
        worktree=None,
        dry_run=True,
        remote=None,
        pi_args=[],
    )
    data = json.loads(capsys.readouterr().out)
    assert data["stage"] == "implement"
    assert data["worktree"].endswith("/plan-42")
    assert data["plan_ref"] == _PLAN_REF_JSON
    # The implement launch is primed — argv carries the initial prompt.
    assert data["argv"][0] == "pi"
    assert len(data["argv"]) == 3
    assert "gh issue view 42 --comments" in data["argv"][-1]
    # implement is a `worktree: create` stage, so perk auto-approves project trust for the run.
    assert "--approve" in data["argv"]
    assert data["argv"][1] == "--approve"
    # dry run is side-effect-free: no worktree, no handoff
    assert not (_config(tmp_path).worktree_root / "plan-42").exists()


def test_launch_stage_forwards_bare_plan_id_to_the_positioner(tmp_path, monkeypatch, capsys):
    # The bare-id passthrough (the `plan watch` twin): `launch_stage(plan_id=…)` reaches
    # `resolve_worktree(plan_id=…)`, and a `worktree="reuse"`-replaced plan-family stage rides
    # the existing pipeline (worktree-stage trust arg, restore-preview disposition) with no
    # backend read on the dry-run preview.
    captured: dict = {}
    real = launch.resolve_worktree

    def spy(**kwargs):
        captured.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(launch, "resolve_worktree", spy)
    effective = dataclasses.replace(_stage("objective-plan"), worktree="reuse")
    launch_stage(
        repo_root=tmp_path,
        config=_config(tmp_path),
        stage=effective,
        worktree=None,
        dry_run=True,
        remote=None,
        pi_args=[],
        plan_id="42",
    )
    assert captured["plan_id"] == "42"
    data = json.loads(capsys.readouterr().out)
    assert data["stage"] == "objective-plan"
    assert data["worktree"].endswith("/plan-42")
    assert data["disposition"] == "restore-remote"
    # The effective stage is a worktree stage for this launch — project trust auto-approves.
    assert "--approve" in data["argv"]
    # A bare-id dry-run restore preview performs no canonical read — no plan_ref in the payload.
    assert "plan_ref" not in data


def test_worktree_stage_auto_approves_and_respects_user_no_approve(tmp_path, capsys):
    # Worktree stages auto-inject `--approve` (perk launches its own managed checkout, so project
    # trust is implicit), but a user-passed `--no-approve` wins via pi's last-wins trust parsing.
    cache.write_plan_ref(tmp_path, _PLAN_REF)
    launch_stage(
        repo_root=tmp_path,
        config=_config(tmp_path),
        stage=_stage("implement"),
        worktree=None,
        dry_run=True,
        remote=None,
        pi_args=["--no-approve"],
    )
    data = json.loads(capsys.readouterr().out)
    assert "--approve" in data["argv"]
    assert "--no-approve" in data["argv"]
    assert data["argv"].index("--approve") < data["argv"].index("--no-approve")

    # `worktree: none` stages run in the repo root the user trusts manually — no auto-approve.
    launch_stage(
        repo_root=tmp_path,
        config=_config(tmp_path),
        stage=_stage("plan"),
        worktree=None,
        dry_run=True,
        remote=None,
        pi_args=[],
    )
    data = json.loads(capsys.readouterr().out)
    assert "--approve" not in data["argv"]


# --- [models.stages.<id>] per-stage model/thinking injection ---------------------------------


def test_stage_model_argv_unconfigured_is_empty(tmp_path):
    assert _stage_model_argv(_config(tmp_path), "implement") == []


def test_stage_model_argv_both_knobs(tmp_path):
    config = dataclasses.replace(
        _config(tmp_path),
        stage_models={"implement": StageModel(model="a/opus", thinking="high")},
    )
    assert _stage_model_argv(config, "implement") == ["--model", "a/opus", "--thinking", "high"]


def test_stage_model_argv_thinking_only(tmp_path):
    config = dataclasses.replace(
        _config(tmp_path), stage_models={"implement": StageModel(thinking="high")}
    )
    assert _stage_model_argv(config, "implement") == ["--thinking", "high"]


def test_stage_model_injected_after_trust_before_pi_args(tmp_path, capsys):
    config = dataclasses.replace(
        _config(tmp_path),
        stage_models={"implement": StageModel(model="a/opus", thinking="high")},
    )
    cache.write_plan_ref(tmp_path, _PLAN_REF)
    launch_stage(
        repo_root=tmp_path,
        config=config,
        stage=_stage("implement"),
        worktree=None,
        dry_run=True,
        remote=None,
        pi_args=[],
    )
    argv = json.loads(capsys.readouterr().out)["argv"]
    assert "--model" in argv and argv[argv.index("--model") + 1] == "a/opus"
    assert "--thinking" in argv and argv[argv.index("--thinking") + 1] == "high"
    # injected after `--approve` (trust), before the seeded prompt (the only pi_arg-tail entry)
    assert argv.index("--approve") < argv.index("--model")
    assert argv.index("--thinking") < len(argv) - 1


def test_stage_model_thinking_only_injects_no_model(tmp_path, capsys):
    config = dataclasses.replace(
        _config(tmp_path), stage_models={"implement": StageModel(thinking="high")}
    )
    cache.write_plan_ref(tmp_path, _PLAN_REF)
    launch_stage(
        repo_root=tmp_path,
        config=config,
        stage=_stage("implement"),
        worktree=None,
        dry_run=True,
        remote=None,
        pi_args=[],
    )
    argv = json.loads(capsys.readouterr().out)["argv"]
    assert "--thinking" in argv
    assert "--model" not in argv


def test_stage_model_unconfigured_leaves_argv_untouched(tmp_path, capsys):
    cache.write_plan_ref(tmp_path, _PLAN_REF)
    launch_stage(
        repo_root=tmp_path,
        config=_config(tmp_path),  # no stage_models
        stage=_stage("implement"),
        worktree=None,
        dry_run=True,
        remote=None,
        pi_args=[],
    )
    argv = json.loads(capsys.readouterr().out)["argv"]
    # unchanged length: ["pi", "--approve", <prompt>] (pi's own resolution untouched)
    assert len(argv) == 3
    assert "--model" not in argv and "--thinking" not in argv


def test_stage_model_explicit_flag_wins_last(tmp_path, capsys):
    config = dataclasses.replace(
        _config(tmp_path), stage_models={"implement": StageModel(model="a/config")}
    )
    cache.write_plan_ref(tmp_path, _PLAN_REF)
    launch_stage(
        repo_root=tmp_path,
        config=config,
        stage=_stage("implement"),
        worktree=None,
        dry_run=True,
        remote=None,
        pi_args=["--model", "a/explicit"],
    )
    argv = json.loads(capsys.readouterr().out)["argv"]
    # both appear; the config one precedes the explicit one (pi parses last-wins)
    assert argv.index("a/config") < argv.index("a/explicit")


# --- [skills]/stages: skill-exposure scoping (contracts.md §8.39) ----------------------------


def test_skill_exposure_unengaged_leaves_argv_untouched(tmp_path, capsys):
    # No `[skills]` config and no `stages:` declarations -> the composition contributes nothing
    # (the launch argv is byte-identical to unscoped discovery).
    cache.write_plan_ref(tmp_path, _PLAN_REF)
    launch_stage(
        repo_root=tmp_path,
        config=_config(tmp_path),
        stage=_stage("implement"),
        worktree=None,
        dry_run=True,
        remote=None,
        pi_args=[],
    )
    argv = json.loads(capsys.readouterr().out)["argv"]
    assert "--no-skills" not in argv and "--skill" not in argv


def test_skill_exposure_injected_between_model_args_and_pi_args(tmp_path, capsys):
    # Engaged (explicit include_packages): `--no-skills` + `--skill` land after the per-stage
    # model args and before user pi_args (user flags stay last / additive). Built once before
    # the dry_run branch, so `--dry-run --json` previews the exact exec vector.
    config = dataclasses.replace(
        _config(tmp_path),
        stage_models={"implement": StageModel(model="a/opus")},
        skills=SkillsPolicy(include_packages=True),
    )
    cache.write_plan_ref(tmp_path, _PLAN_REF)
    launch_stage(
        repo_root=tmp_path,
        config=config,
        stage=_stage("implement"),
        worktree=None,
        dry_run=True,
        remote=None,
        pi_args=["--zzz"],
    )
    argv = json.loads(capsys.readouterr().out)["argv"]
    assert argv.index("--model") < argv.index("--no-skills") < argv.index("--zzz")
    # The shipped `stage:implement` binding's skill is unioned in (bound skills are always
    # exposed), even though tmp_path has no installed skills — the delivery-path entry dangles.
    assert argv[argv.index("--skill") + 1] == ".agents/skills/perk-implement"


def test_skill_exposure_never_reintroduces_ambiently_disabled_ponytail(tmp_path, capsys):
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    pi_dir.joinpath("settings.json").write_text(
        json.dumps(
            {
                "packages": [
                    {
                        "source": "npm:@dietrichgebert/ponytail",
                        "extensions": [],
                        "skills": [],
                        "prompts": [],
                        "themes": [],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    config = dataclasses.replace(_config(tmp_path), skills=SkillsPolicy(include_packages=True))
    cache.write_plan_ref(tmp_path, _PLAN_REF)
    launch_stage(
        repo_root=tmp_path,
        config=config,
        stage=_stage("implement"),
        worktree=None,
        dry_run=True,
        remote=None,
        pi_args=[],
    )
    captured = capsys.readouterr()
    argv = json.loads(captured.out)["argv"]
    assert "ponytail" not in " ".join(argv)
    assert "ponytail-review" not in " ".join(argv)
    assert "ponytail" not in captured.err


def test_skill_exposure_binding_trigger_override_selects_command_bindings(tmp_path, capsys):
    # A stage-borrowing cold door's `binding_trigger` override drives the bound-skill union on
    # its command trigger — the same normalization `_resolve_prompt` uses.
    config = dataclasses.replace(_config(tmp_path), skills=SkillsPolicy(include_packages=True))
    launch_stage(
        repo_root=tmp_path,
        config=config,
        stage=_stage("plan"),
        worktree=None,
        dry_run=True,
        remote=None,
        pi_args=[],
        binding_trigger="command:learn-docs",
    )
    argv = json.loads(capsys.readouterr().out)["argv"]
    skills = [argv[i + 1] for i, arg in enumerate(argv) if arg == "--skill"]
    assert ".agents/skills/perk-learn-docs" in skills
    assert ".agents/skills/perk-plan" not in skills  # stage:plan bindings do not fire


def test_skill_exposure_fail_open_on_unexpected_error(tmp_path, capsys, monkeypatch):
    # The blanket fail-open guard: a composition bug degrades the launch to unscoped discovery
    # (one warning, argv unchanged) — never blocks.
    def _boom(*args, **kwargs):
        raise RuntimeError("composition bug")

    monkeypatch.setattr(launch, "skill_exposure_argv", _boom)
    config = dataclasses.replace(_config(tmp_path), skills=SkillsPolicy(include_packages=True))
    cache.write_plan_ref(tmp_path, _PLAN_REF)
    launch_stage(
        repo_root=tmp_path,
        config=config,
        stage=_stage("implement"),
        worktree=None,
        dry_run=True,
        remote=None,
        pi_args=[],
    )
    captured = capsys.readouterr()
    argv = json.loads(captured.out)["argv"]
    assert "--no-skills" not in argv and "--skill" not in argv
    assert "skills: exposure composition failed" in captured.err


def test_skill_exposure_degrade_warning_reaches_stderr(tmp_path, capsys):
    # A returned composition warning (here: the package-tier degrade) is surfaced via log_warn.
    (tmp_path / ".pi").mkdir()
    (tmp_path / ".pi" / "settings.json").write_text('{"packages": ["npm:ghost"]}')
    config = dataclasses.replace(_config(tmp_path), skills=SkillsPolicy(include_packages=True))
    cache.write_plan_ref(tmp_path, _PLAN_REF)
    launch_stage(
        repo_root=tmp_path,
        config=config,
        stage=_stage("implement"),
        worktree=None,
        dry_run=True,
        remote=None,
        pi_args=[],
    )
    captured = capsys.readouterr()
    argv = json.loads(captured.out)["argv"]
    assert "--no-skills" not in argv  # whole composition degraded to unscoped
    assert "ghost" in captured.err


def test_user_binding_appended_to_initial_prompt(tmp_path, capsys):
    # A user override of the stage:implement trigger is delivered ADDITIVELY — it
    # appears appended to the hardcoded implement prompt (which is unchanged).
    cache.write_plan_ref(tmp_path, _PLAN_REF)
    launch_stage(
        repo_root=tmp_path,
        config=_config(tmp_path, [_binding("stage:implement", "custom-implement")]),
        stage=_stage("implement"),
        worktree=None,
        dry_run=True,
        remote=None,
        pi_args=[],
    )
    data = json.loads(capsys.readouterr().out)
    prompt = data["argv"][-1]
    assert "gh issue view 42 --comments" in prompt  # hardcoded prompt preserved
    assert _pointer("custom-implement") in prompt  # delivered additively


def test_prompt_suffix_appended_between_primer_and_binding(tmp_path, capsys):
    # A caller-supplied prompt_suffix (e.g. the resume prior-work advisory) lands between
    # the stage primer and the skill-binding suffix: primer → \n\n → suffix → \n\n → binding.
    cache.write_plan_ref(tmp_path, _PLAN_REF)
    launch_stage(
        repo_root=tmp_path,
        config=_config(tmp_path, [_binding("stage:implement", "custom-implement")]),
        stage=_stage("implement"),
        worktree=None,
        dry_run=True,
        remote=None,
        pi_args=[],
        prompt_suffix="ADVISORY SUFFIX",
    )
    prompt = json.loads(capsys.readouterr().out)["argv"][-1]
    # The primer's final line is immediately followed by the suffix (\n\n-joined) …
    assert "where the implementation actually stands.\n\nADVISORY SUFFIX" in prompt
    # … and the binding pointer comes AFTER the suffix.
    assert prompt.index("ADVISORY SUFFIX") < prompt.index(_pointer("custom-implement"))


def test_prompt_suffix_never_synthesizes_a_prompt(tmp_path, capsys):
    # Augment-only (the binding-delivery D2 rule): a stage with no initial prompt stays idle
    # even when a suffix is supplied — the suffix is dropped, never promoted to the prompt.
    launch_stage(
        repo_root=tmp_path,
        config=_config(tmp_path),
        stage=_stage("plan"),
        worktree=None,
        dry_run=True,
        remote=None,
        pi_args=[],
        prompt_suffix="ADVISORY SUFFIX",
    )
    data = json.loads(capsys.readouterr().out)
    assert data["argv"] == ["pi"]


def test_idle_launch_does_not_synthesize_binding_prompt(tmp_path, capsys):
    # Cold delivery AUGMENTS an existing prompt only — it never synthesizes one. The
    # `save` stage has no _initial_prompt, so even a user binding at stage:save does NOT become the
    # launch prompt: argv stays a no-prompt argv (length 1). The warm Mechanism A delivers it there.
    launch_stage(
        repo_root=tmp_path,
        config=_config(tmp_path, [_binding("stage:save", "my-save-skill")]),
        stage=_stage("save"),
        worktree=None,
        dry_run=True,
        remote=None,
        pi_args=[],
    )
    data = json.loads(capsys.readouterr().out)
    assert len(data["argv"]) == 1
    assert data["argv"] == ["pi"]


def test_shipped_default_delivered_once_to_initial_prompt(tmp_path, capsys):
    # With no user bindings, the shipped default stage:implement nudge IS now delivered
    # (perk no longer hardcodes it) — appended once to the implement initial prompt.
    cache.write_plan_ref(tmp_path, _PLAN_REF)
    launch_stage(
        repo_root=tmp_path,
        config=_config(tmp_path),
        stage=_stage("implement"),
        worktree=None,
        dry_run=True,
        remote=None,
        pi_args=[],
    )
    data = json.loads(capsys.readouterr().out)
    # The pointer names "perk-implement" twice (skill name + read path) — count the whole
    # pointer line to pin single delivery.
    assert data["argv"][-1].count(_pointer("perk-implement")) == 1
    assert data["argv"][-1].count("Follow the") == 1


def test_prompt_override_overrides_initial_prompt(tmp_path, capsys):
    # prompt_override wins over _initial_prompt (objective-plan has no plan-ref, so
    # _initial_prompt would be None). The seeded prompt lands as the launch argv.
    launch_stage(
        repo_root=tmp_path,
        config=_config(tmp_path),
        stage=_stage("objective-plan"),
        worktree=None,
        dry_run=True,
        remote=None,
        pi_args=[],
        prompt_override="SEED PROMPT for node 2.3",
    )
    data = json.loads(capsys.readouterr().out)
    assert data["stage"] == "objective-plan"
    assert data["argv"][0] == "pi"
    # The seed wins over _initial_prompt; the stage:objective-plan default binding is appended
    # (perk no longer hardcodes the pointer in the seed) additively after it.
    assert data["argv"][-1].startswith("SEED PROMPT for node 2.3")
    assert _pointer("perk-objective-plan") in data["argv"][-1]


def test_initial_prompt_primes_implement_and_address():
    """Implement and address are primed; other stages launch unprimed."""
    impl = _initial_prompt(_stage("implement"), _PLAN_REF_MODEL)
    assert impl is not None and "gh issue view 42 --comments" in impl and "/submit" in impl
    # The implement prompt teaches the todo checklist discipline; the perk-implement skill pointer
    # is NOT hardcoded here anymore (it rides the skill-binding mechanism).
    assert "Progress tracking:" in impl and "todo" in impl and "perk-implement" not in impl
    addr = _initial_prompt(_stage("address"), _PLAN_REF_MODEL)
    assert addr is not None and "perk-address" not in addr and "review-classifier" in addr
    # The classify step is ONE classify_review_feedback call — no transcribed mechanics.
    assert "classify_review_feedback" in addr
    assert "outputSchema" not in addr
    assert "workflowScript" not in addr
    assert "passing `model:" not in addr
    assert _initial_prompt(_stage("plan"), _PLAN_REF_MODEL) is None
    assert _initial_prompt(_stage("implement"), None) is None
    assert _initial_prompt(_stage("address"), None) is None
    # The new defaulted `preview` param leaves the non-preview address prompt unchanged.
    assert _initial_prompt(_stage("address"), _PLAN_REF_MODEL, preview=False) == addr


def test_address_prompt_preview_is_classification_only():
    """The cold `--preview` flag shapes the address seed to classify-only (no action),
    mirroring the warm `addressGuidance(preview=true)` shape; non-preview body is unchanged."""
    preview = _address_prompt(_PLAN_REF_MODEL, preview=True)
    assert "PREVIEWING" in preview
    assert "take NO action" in preview and "preview only" in preview
    # The fix→publish→resolve tail is omitted in preview.
    assert "finalize_address" not in preview
    assert "/land" not in preview
    # Preview takes no action, so Plan File Mode (an action step) is omitted.
    assert "Plan File Mode" not in preview
    # The non-preview body (the default) keeps the full loop.
    full = _address_prompt(_PLAN_REF_MODEL)
    assert _address_prompt(_PLAN_REF_MODEL, preview=False) == full
    assert "finalize_address" in full and "PREVIEWING" not in full
    assert "Never push manually" in full
    # The converged body upgrades cold/worker with warm's Plan File Mode step.
    assert "Plan File Mode" in full


def test_initial_prompt_primes_learn():
    """The learn stage is primed — it derives the merged PR from the plan-<pr_id> head
    branch and stays unprimed without a plan-ref (the perk-learn pointer rides the binding
    mechanism — not the hardcoded prompt)."""
    learn = _initial_prompt(_stage("learn"), _PLAN_REF_MODEL)
    assert learn is not None
    assert "perk-learn" not in learn  # the skill pointer rides the binding mechanism
    assert "plan-42" in learn  # the derived head branch (pr_id is the plan-issue number)
    assert "gh pr list --head plan-42" in learn
    assert "learn` tool" in learn  # drives the durable capture path
    assert "/learn skip" in learn
    assert _initial_prompt(_stage("learn"), None) is None


_LINEAR_PLAN_REF = plan.PlanRef(
    provider="linear",
    pr_id="a1b2c3d4-0000-0000-0000-000000000000",
    url="https://linear.app/acme/issue/ENG-123",
    labels=("perk:plan",),
)


def test_implement_prompt_linear_uses_linear_tools_with_url_fallback():
    """A linear plan-ref renders the pi-mono-linear read recipe (not `gh issue view`),
    with `open <url>` as the in-prompt fallback."""
    prompt = _initial_prompt(_stage("implement"), _LINEAR_PLAN_REF)
    assert prompt is not None
    assert "linear_get_issue" in prompt
    assert "linear_list_comments" in prompt
    assert "open https://linear.app/acme/issue/ENG-123" in prompt
    assert "gh issue view" not in prompt


def test_learn_prompt_linear_keeps_gh_pr_derivation():
    """The linear learn prompt reads the plan via the linear tools, but the merged-PR
    derivation stays `gh` — PRs are GitHub-universal under every issue backend."""
    prompt = _initial_prompt(_stage("learn"), _LINEAR_PLAN_REF)
    assert prompt is not None
    assert "linear_get_issue" in prompt and "linear_list_comments" in prompt
    assert f"gh pr list --head plan-{_LINEAR_PLAN_REF.pr_id} --state merged" in prompt


def test_dry_run_has_no_side_effects(tmp_path, capsys):
    launch_stage(
        repo_root=tmp_path,
        config=_config(tmp_path),
        stage=_stage("plan"),
        worktree=None,
        dry_run=True,
        remote=None,
        pi_args=["-p", "x"],
    )
    data = json.loads(capsys.readouterr().out)
    assert data["stage"] == "plan"
    assert data["argv"] == ["pi", "-p", "x"]
    # no handoff written on a dry run
    assert not (tmp_path / ".perk" / "workflow" / "handoff").exists()


def test_run_id_override_reuses_existing_run_id(tmp_path, capsys):
    # The replan cold door re-enters an existing plan's run_id instead of minting a fresh one.
    launch_stage(
        repo_root=tmp_path,
        config=_config(tmp_path),
        stage=_stage("plan"),
        worktree=None,
        dry_run=True,
        remote=None,
        pi_args=[],
        run_id_override="01ABCDEF0123456789ABCDEFGH",
    )
    data = json.loads(capsys.readouterr().out)
    assert data["run_id"] == "01ABCDEF0123456789ABCDEFGH"


def test_no_run_id_override_mints(tmp_path, capsys):
    # Existing behavior unchanged: omitting the override mints a fresh ULID-shaped run_id.
    launch_stage(
        repo_root=tmp_path,
        config=_config(tmp_path),
        stage=_stage("plan"),
        worktree=None,
        dry_run=True,
        remote=None,
        pi_args=[],
    )
    data = json.loads(capsys.readouterr().out)
    assert data["run_id"] != "01ABCDEF0123456789ABCDEFGH"
    assert len(data["run_id"]) == 26  # a minted ULID


# --- the launch target resolver --------------------------------------------------


def test_resolve_target_none_is_local():
    target = resolve_target(_stage("plan"), None)
    assert target.is_remote is False and target.runner is None


def test_resolve_target_remote_on_local_only_stage_is_blocked():
    # plan is cold_remote:false -> remote_blocked.
    with pytest.raises(UserFacingCliError) as exc:
        resolve_target(_stage("plan"), "")
    assert exc.value.error_type == "remote_blocked"


@pytest.mark.parametrize("stage_id", ["implement", "address"])
def test_resolve_target_remote_on_drivable_stage_resolves(stage_id):
    # implement + address are cold_remote:true -> a remote Target (no raise).
    target = resolve_target(_stage(stage_id), "ci-large")
    assert target.is_remote is True and target.runner == "ci-large"


def test_remote_blocked_stage_raises_in_launch(tmp_path):
    with pytest.raises(UserFacingCliError) as exc:
        launch_stage(
            repo_root=tmp_path,
            config=_config(tmp_path),
            stage=_stage("plan"),
            worktree=None,
            dry_run=False,
            remote="",
            pi_args=[],
        )
    assert exc.value.error_type == "remote_blocked"


def test_remote_dry_run_is_side_effect_free_dispatch_preview(tmp_path, capsys, monkeypatch):
    # implement is cold_remote:true: --dry-run --remote is a side-effect-free dispatch PREVIEW
    # (success:true, an inputs preview) that writes NOTHING (no dispatch.json, no trigger).
    monkeypatch.setattr(launch.github, "default_branch", lambda _r: "main")
    monkeypatch.setattr(
        launch.runner, "select_runner", lambda _ref: _boom_runner("dispatch must not run")
    )
    cache.write_plan_ref(tmp_path, _PLAN_REF)
    launch_stage(
        repo_root=tmp_path,
        config=_config(tmp_path),
        stage=_stage("implement"),
        worktree=None,
        dry_run=True,
        remote="ci-large",
        pi_args=[],
    )
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["success"] is True and payload["dry_run"] is True
    assert payload["stage"] == "implement" and payload["runner"] == "ci-large"
    assert payload["inputs"]["stage"] == "implement" and payload["inputs"]["plan"] == "42"
    assert payload["inputs"]["workflow"] == launch.runner.GITHUB_ACTIONS_WORKFLOW
    # No run dir was created (no scratch/runs/<run_id>/dispatch.json).
    runs_dir = cache.workflow_dir(tmp_path) / "scratch" / "runs"
    assert not runs_dir.exists() or not any(runs_dir.iterdir())


class _FakeRunner:
    kind = "github-actions"

    def __init__(self, handle=None, exc=None):
        self._handle = handle
        self._exc = exc
        self.calls = []

    def dispatch(self, *, stage, plan_ref, run_id, base, repo_root):
        self.calls.append({"stage": stage, "run_id": run_id, "base": base})
        if self._exc is not None:
            raise self._exc
        return self._handle


def _boom_runner(message):
    class _Boom:
        kind = "github-actions"

        def dispatch(self, **_k):
            raise AssertionError(message)

    return _Boom()


def _last_dispatch(tmp_path):
    runs_dir = cache.workflow_dir(tmp_path) / "scratch" / "runs"
    rid = next(iter(runs_dir.iterdir()))
    return json.loads((rid / "dispatch.json").read_text())


def test_remote_drive_persists_verified_linkage_and_surfaces_handle(tmp_path, capsys, monkeypatch):
    from perk.run import runner

    cache.write_plan_ref(tmp_path, _PLAN_REF)
    handle = runner.RunHandle(
        runner="ci-large", kind="github-actions", run_ref="99", url="https://gh/run/99"
    )
    fake = _FakeRunner(handle=handle)
    monkeypatch.setattr(launch.github, "default_branch", lambda _r: "trunk")
    monkeypatch.setattr(launch.runner, "select_runner", lambda _ref: fake)
    launch_stage(
        repo_root=tmp_path,
        config=_config(tmp_path),
        stage=_stage("implement"),
        worktree=None,
        dry_run=False,
        remote="ci-large",
        pi_args=[],
    )
    record = _last_dispatch(tmp_path)
    assert record["status"] == "dispatched"
    assert record["plan_ref"]["pr_id"] == "42" and record["runner"] == "ci-large"
    assert record["run_handle"]["run_ref"] == "99"
    assert fake.calls and fake.calls[0]["base"] == "trunk"
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert payload["success"] is True and payload["run_handle"]["run_ref"] == "99"
    assert payload["run_id"] == record["run_id"]


def test_remote_drive_prefers_pinned_plan_base(tmp_path, capsys, monkeypatch):
    # A base-carrying plan-ref makes the runner input target the pinned base, NOT the
    # GitHub default branch (which must not even be consulted).
    from perk.run import runner

    cache.write_plan_ref(tmp_path, dataclasses.replace(_PLAN_REF, base="develop"))
    handle = runner.RunHandle(
        runner="ci-large", kind="github-actions", run_ref="99", url="https://gh/run/99"
    )
    fake = _FakeRunner(handle=handle)

    def _no_default(_r):
        raise AssertionError("default_branch must not be consulted when the plan pins a base")

    monkeypatch.setattr(launch.github, "default_branch", _no_default)
    monkeypatch.setattr(launch.runner, "select_runner", lambda _ref: fake)
    launch_stage(
        repo_root=tmp_path,
        config=_config(tmp_path),
        stage=_stage("implement"),
        worktree=None,
        dry_run=False,
        remote="ci-large",
        pi_args=[],
    )
    assert fake.calls and fake.calls[0]["base"] == "develop"


def test_remote_drive_failure_records_failed_and_raises(tmp_path, monkeypatch):
    from perk.run import runner

    cache.write_plan_ref(tmp_path, _PLAN_REF)
    fake = _FakeRunner(exc=runner.RunnerError("workflow not found"))
    monkeypatch.setattr(launch.github, "default_branch", lambda _r: "main")
    monkeypatch.setattr(launch.runner, "select_runner", lambda _ref: fake)
    with pytest.raises(UserFacingCliError) as exc:
        launch_stage(
            repo_root=tmp_path,
            config=_config(tmp_path),
            stage=_stage("implement"),
            worktree=None,
            dry_run=False,
            remote="ci-large",
            pi_args=[],
        )
    assert exc.value.error_type == "dispatch_failed"
    record = _last_dispatch(tmp_path)
    assert record["status"] == "failed" and "workflow not found" in record["error"]


def test_remote_drive_no_plan_ref_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(launch.github, "default_branch", lambda _r: "main")
    with pytest.raises(UserFacingCliError) as exc:
        launch_stage(
            repo_root=tmp_path,
            config=_config(tmp_path),
            stage=_stage("implement"),
            worktree=None,
            dry_run=False,
            remote="ci-large",
            pi_args=[],
        )
    assert exc.value.error_type == "no_plan_ref"


# --- origin-aware create base ---------------------------------------------------------


def _sha(repo, ref="HEAD"):
    return subprocess.run(
        ["git", "rev-parse", ref], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _resolve_implement(
    repo_root: Path, *, worktree: str | None = None, base: str | None = None
) -> launch.ResolvedWorktree:
    return resolve_worktree(
        repo_root=repo_root,
        config=Config(worktree_root=repo_root / ".worktrees"),
        request=_request("implement"),
        worktree=worktree,
        materialize=True,
        base=base,
    )


def test_create_bases_off_fresh_origin_trunk(git_repo_with_remote):
    """Materialize-create fetches origin and bases the new branch on origin/<trunk>, not the
    stale local HEAD."""
    clone, _remote, advance = git_repo_with_remote
    advanced = advance()  # origin/main is now ahead of the clone's local HEAD
    cache.write_plan_ref(clone, _PLAN_REF)
    resolved = _resolve_implement(clone)
    assert _sha(resolved.path) == advanced  # freshly-fetched origin/main, not stale local HEAD


def test_create_narrates_worktree_creation(git_repo_with_remote, capsys):
    """A fresh worktree-create launch narrates the create wait + its completion milestone."""
    clone, _remote, _advance = git_repo_with_remote
    cache.write_plan_ref(clone, _PLAN_REF)
    _resolve_implement(clone)
    err = capsys.readouterr().err
    assert "\u2713 fetched origin" in err  # the pre-create fetch resolves on success
    assert "creating worktree plan-42" in err
    assert "created worktree plan-42" in err


def test_launch_injects_cli_version_env():
    """The local launch seam injects PERK_CLI_VERSION = the running CLI's version into the exec
    env, alongside PERK_RUN_ID, so the extension can surface the soft version-parity signal."""
    captured = _build_exec_env(
        run_id="01TEST",
        environ={"PERK_CLI_VERSION": "stale", "PERK_RUN_ID": "stale"},
        fallback_linear_api_key=None,
        pi_agent_dir=None,
    )
    assert captured["PERK_CLI_VERSION"] == __version__
    assert captured["PERK_RUN_ID"] == "01TEST"


def test_launch_injects_fff_override_env_default():
    """The local launch seam injects the PI_FFF_MODE=override default (FFF replaces the builtin
    find/grep in perk-launched sessions) when the operator environment does not set it."""
    captured = _build_exec_env(
        run_id="01TEST",
        environ={},
        fallback_linear_api_key=None,
        pi_agent_dir=None,
    )
    assert captured["PI_FFF_MODE"] == "override"


def test_launch_operator_env_wins_over_fff_override_default():
    """An operator-set PI_FFF_MODE wins over the injected default (merge order: os.environ is
    spread after FFF_OVERRIDE_ENV), restoring pi-fff's additive default on demand."""
    captured = _build_exec_env(
        run_id="01TEST",
        environ={"PI_FFF_MODE": "tools-and-ui"},
        fallback_linear_api_key=None,
        pi_agent_dir=None,
    )
    assert captured["PI_FFF_MODE"] == "tools-and-ui"


def test_reuse_does_not_fetch_or_rebase(git_repo_with_remote, monkeypatch):
    clone, _remote, _advance = git_repo_with_remote
    cache.write_plan_ref(clone, _PLAN_REF)
    fetches: list[Path] = []
    real_fetch = git_mod.fetch
    monkeypatch.setattr(
        "perk.run.launch.git.fetch",
        lambda repo, **k: (fetches.append(repo), real_fetch(repo, **k))[1],
    )

    _resolve_implement(clone)
    assert len(fetches) == 1  # create fetched once
    _resolve_implement(clone)  # path now exists -> reuse
    assert len(fetches) == 1  # reuse did not fetch again


def test_offline_fetch_failure_warns_and_falls_back(git_repo_with_remote, monkeypatch, capsys):
    clone, _remote, _advance = git_repo_with_remote
    cache.write_plan_ref(clone, _PLAN_REF)

    def boom(repo, **k):
        raise GitError("offline")

    monkeypatch.setattr("perk.run.launch.git.fetch", boom)
    resolved = _resolve_implement(clone)
    assert resolved.path.is_dir()  # still created
    assert "STALE" in capsys.readouterr().err  # loud warning
    # based off last-known origin/main
    assert _sha(resolved.path) == _sha(clone, "origin/main")


def test_remote_branch_exists_bases_off_tracking(git_repo_with_remote, monkeypatch):
    clone, _remote, _advance = git_repo_with_remote
    # Create origin/plan-42 pointing at a distinct commit on the remote.
    subprocess.run(["git", "branch", "plan-42", "main"], cwd=clone, check=True, capture_output=True)
    subprocess.run(
        ["git", "push", "-q", "origin", "plan-42"], cwd=clone, check=True, capture_output=True
    )
    subprocess.run(["git", "branch", "-D", "plan-42"], cwd=clone, check=True, capture_output=True)
    cache.write_plan_ref(clone, _PLAN_REF)
    bases: list[str | None] = []
    real_add = git_mod.worktree_add
    monkeypatch.setattr(
        "perk.run.launch.git.worktree_add",
        lambda *a, **k: (bases.append(k.get("base")), real_add(*a, **k))[1],
    )
    _resolve_implement(clone)
    assert bases == ["origin/plan-42"]


def _push_origin_branch(clone, name: str) -> None:
    """Create ``origin/<name>`` pointing at a distinct commit, then drop the local branch."""
    subprocess.run(
        ["git", "checkout", "-q", "-b", name, "main"], cwd=clone, check=True, capture_output=True
    )
    (clone / f"{name}.txt").write_text("branch\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=clone, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-qm", f"on {name}"], cwd=clone, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "push", "-q", "origin", name], cwd=clone, check=True, capture_output=True
    )
    subprocess.run(["git", "checkout", "-q", "main"], cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "branch", "-qD", name], cwd=clone, check=True, capture_output=True)


def test_create_bases_off_pinned_plan_base(git_repo_with_remote, monkeypatch):
    # A plan-ref carrying `base` cuts the worktree from origin/<base>, not the trunk.
    clone, _remote, _advance = git_repo_with_remote
    _push_origin_branch(clone, "develop")
    cache.write_plan_ref(clone, dataclasses.replace(_PLAN_REF, base="develop"))
    bases: list[str | None] = []
    real_add = git_mod.worktree_add
    monkeypatch.setattr(
        "perk.run.launch.git.worktree_add",
        lambda *a, **k: (bases.append(k.get("base")), real_add(*a, **k))[1],
    )
    resolved = _resolve_implement(clone)
    assert bases == ["origin/develop"]
    assert _sha(resolved.path) == _sha(clone, "origin/develop")


def test_explicit_ref_with_directory_override_stays_on_plan_branch(git_repo_with_remote):
    # An explicit plan id plus --worktree NAME changes only the directory: the branch stays
    # plan-<id>, the pinned base still drives the start-point, and the positioner binds the
    # fresh checkout to the selected ref (positioner-owned materialization).
    clone, _remote, _advance = git_repo_with_remote
    _push_origin_branch(clone, "develop")
    ref = dataclasses.replace(_PLAN_REF, base="develop")
    resolved = resolve_worktree(
        repo_root=clone,
        config=Config(worktree_root=clone / ".worktrees"),
        request=_request("implement"),
        worktree="custom-wt",
        materialize=True,
        selected_ref=ref,
    )
    assert resolved.path == clone / ".worktrees" / "custom-wt"
    assert resolved.disposition == "create-fresh"
    assert resolved.branch == "plan-42"
    assert resolved.base == "origin/develop"
    head_branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=resolved.path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert head_branch == "plan-42"  # the override never renames the plan branch
    assert cache.read_plan_ref(resolved.path) == ref  # bound at creation


def test_explicit_missing_worktree_without_plan_id_is_refused(git_repo_with_remote):
    # A missing explicit custom directory without a plan id cannot invent a binding — the
    # unrelated root selector is NOT consulted for it.
    clone, _remote, _advance = git_repo_with_remote
    cache.write_plan_ref(clone, _PLAN_REF)  # an unrelated root selector must not leak in
    with pytest.raises(UserFacingCliError) as exc:
        _resolve_implement(clone, worktree="custom-wt")
    assert exc.value.error_type == "worktree_not_found"
    assert not (clone / ".worktrees" / "custom-wt").exists()


def test_dry_run_surfaces_base_without_fetching(git_repo_with_remote, monkeypatch, capsys):
    clone, _remote, _advance = git_repo_with_remote
    cache.write_plan_ref(clone, _PLAN_REF)

    def fail_if_called(*a, **k):
        raise AssertionError("dry-run must not fetch")

    monkeypatch.setattr("perk.run.launch.git.fetch", fail_if_called)
    launch_stage(
        repo_root=clone,
        config=Config(worktree_root=clone / ".worktrees"),
        stage=_stage("implement"),
        worktree=None,
        dry_run=True,
        remote=None,
        pi_args=[],
    )
    data = json.loads(capsys.readouterr().out)
    assert data["base"] == "origin/main"
    assert not (clone / ".worktrees" / "plan-42").exists()


# --- main-checkout sync gating (read-only worktree:none stages) -----------------------


class _SyncCalls:
    """Typed recorder for the sync-helper probes (so a skip is asserted by a probe NOT reached)."""

    def __init__(self) -> None:
        self.fetch = 0
        self.upstream_ref = 0
        self.merge_ff_only: list[str] = []


def _patch_sync_git(
    monkeypatch,
    *,
    has_remote=True,
    branch="main",
    dirty=False,
    upstream="origin/main",
    ff=True,
    fetch_raises=False,
) -> _SyncCalls:
    """Monkeypatch the sync helpers on `perk.run.launch.worktree.git` + record calls."""
    calls = _SyncCalls()

    def _fetch(_repo, **_k):
        calls.fetch += 1
        if fetch_raises:
            raise GitError("offline")

    def _merge(_repo, ref):
        calls.merge_ff_only.append(ref)
        return ff

    def _upstream(_repo):
        calls.upstream_ref += 1
        return upstream

    monkeypatch.setattr("perk.run.launch.worktree.git.has_remote", lambda _r, *a, **k: has_remote)
    monkeypatch.setattr("perk.run.launch.worktree.git.current_branch", lambda _r: branch)
    monkeypatch.setattr("perk.run.launch.worktree.git.is_dirty", lambda _r: dirty)
    monkeypatch.setattr("perk.run.launch.worktree.git.fetch", _fetch)
    monkeypatch.setattr("perk.run.launch.worktree.git.upstream_ref", _upstream)
    monkeypatch.setattr("perk.run.launch.worktree.git.merge_ff_only", _merge)
    # Keep the pre-exec npm-install warming offline + the exec a no-op.
    monkeypatch.setattr(
        launch.init, "ensure_extension_install_present", lambda repo_root, *, self_repo: None
    )
    monkeypatch.setattr("perk.run.launch._resolve_pi_executable", lambda: "/stub/bin/pi")
    monkeypatch.setattr("perk.run.launch.os.chdir", lambda _p: None)
    monkeypatch.setattr("perk.run.launch.os.execvpe", lambda _f, _a, _e: None)
    return calls


def _launch_plan(tmp_path, **kwargs):
    launch_stage(
        repo_root=tmp_path,
        config=_config(tmp_path),
        stage=_stage("plan"),
        worktree=None,
        dry_run=False,
        remote=None,
        pi_args=[],
        **kwargs,
    )


def test_sync_fast_forwards_clean_read_only_none_stage(tmp_path, monkeypatch, capsys):
    calls = _patch_sync_git(monkeypatch)
    _launch_plan(tmp_path)
    assert calls.merge_ff_only == ["origin/main"]
    err = capsys.readouterr().err
    assert "fetching origin" in err  # the new step before the network round-trip
    assert "synced main → origin/main" in err


def test_sync_skips_on_dirty_tree(tmp_path, monkeypatch, capsys):
    calls = _patch_sync_git(monkeypatch, dirty=True)
    _launch_plan(tmp_path)
    assert calls.merge_ff_only == []  # never fast-forwards a dirty tree
    assert calls.fetch == 0  # short-circuits before the network
    assert "uncommitted changes" in capsys.readouterr().err


def test_sync_skips_on_detached_head(tmp_path, monkeypatch, capsys):
    calls = _patch_sync_git(monkeypatch, branch=None)
    _launch_plan(tmp_path)
    assert calls.merge_ff_only == []
    assert "detached HEAD" in capsys.readouterr().err


def test_sync_skips_without_upstream(tmp_path, monkeypatch, capsys):
    calls = _patch_sync_git(monkeypatch, upstream=None)
    _launch_plan(tmp_path)
    assert calls.fetch == 1  # fetched, then found no upstream
    assert calls.merge_ff_only == []
    assert "no upstream" in capsys.readouterr().err


def test_sync_noop_without_remote_is_fully_offline(tmp_path, monkeypatch):
    calls = _patch_sync_git(monkeypatch, has_remote=False)
    _launch_plan(tmp_path)
    assert calls.fetch == 0  # no remote -> no network at all
    assert calls.merge_ff_only == []


def test_sync_skips_on_divergence_but_launch_proceeds(tmp_path, monkeypatch, capsys):
    calls = _patch_sync_git(monkeypatch, ff=False)
    _launch_plan(tmp_path)  # must NOT raise — a non-FF only warns
    assert calls.merge_ff_only == ["origin/main"]
    assert "diverged" in capsys.readouterr().err


def test_sync_skips_on_fetch_failure(tmp_path, monkeypatch, capsys):
    calls = _patch_sync_git(monkeypatch, fetch_raises=True)
    _launch_plan(tmp_path)
    assert calls.fetch == 1
    assert calls.merge_ff_only == []  # never reached after a fetch failure
    assert "STALE" in capsys.readouterr().err


def test_sync_disabled_by_sync_main_false(tmp_path, monkeypatch):
    calls = _patch_sync_git(monkeypatch)
    _launch_plan(tmp_path, sync_main=False)
    assert calls.fetch == 0
    assert calls.merge_ff_only == []


def test_sync_not_run_for_read_write_none_stage(tmp_path, monkeypatch):
    calls = _patch_sync_git(monkeypatch)
    launch_stage(
        repo_root=tmp_path,
        config=_config(tmp_path),
        stage=_stage("save"),  # read-write, worktree: none
        worktree=None,
        dry_run=False,
        remote=None,
        pi_args=[],
    )
    assert calls.fetch == 0
    assert calls.merge_ff_only == []


def test_sync_not_run_for_create_stage(git_repo_with_remote, monkeypatch):
    clone, _remote, _advance = git_repo_with_remote
    cache.write_plan_ref(clone, _PLAN_REF)
    calls = _patch_sync_git(monkeypatch)
    monkeypatch.setattr("perk.backends.github.plans.get_plan_body", lambda **_k: None)
    launch_stage(
        repo_root=clone,
        config=Config(worktree_root=clone / ".worktrees"),
        stage=_stage("implement"),  # worktree: create
        worktree=None,
        dry_run=False,
        remote=None,
        pi_args=[],
    )
    assert calls.merge_ff_only == []  # create keeps its own fresh-base path, not the sync


def test_dry_run_previews_sync_for_qualifying_stage(tmp_path, monkeypatch, capsys):
    calls = _patch_sync_git(monkeypatch)
    launch_stage(
        repo_root=tmp_path,
        config=_config(tmp_path),
        stage=_stage("plan"),
        worktree=None,
        dry_run=True,
        remote=None,
        pi_args=[],
    )
    out = capsys.readouterr()
    assert calls.fetch == 0 and calls.merge_ff_only == []  # dry-run never syncs
    assert "would sync main checkout" in out.err
    assert json.loads(out.out)["sync_main"] is True


def test_dry_run_no_sync_preview_when_disabled(tmp_path, monkeypatch, capsys):
    _patch_sync_git(monkeypatch)
    launch_stage(
        repo_root=tmp_path,
        config=_config(tmp_path),
        stage=_stage("plan"),
        worktree=None,
        dry_run=True,
        remote=None,
        pi_args=[],
        sync_main=False,
    )
    out = capsys.readouterr()
    assert "would sync main checkout" not in out.err
    assert "sync_main" not in json.loads(out.out)


def test_dry_run_no_sync_preview_for_read_write_stage(tmp_path, monkeypatch, capsys):
    _patch_sync_git(monkeypatch)
    launch_stage(
        repo_root=tmp_path,
        config=_config(tmp_path),
        stage=_stage("save"),
        worktree=None,
        dry_run=True,
        remote=None,
        pi_args=[],
    )
    out = capsys.readouterr()
    assert "would sync main checkout" not in out.err
    assert "sync_main" not in json.loads(out.out)


# --- stacked parent-aware fresh creation (contracts.md §8.46) ----------------------


_LINEAGE = "01JB0000000000000000000000"


def _stacked_ref(pr_id: str = "102") -> plan.PlanRef:
    return dataclasses.replace(_PLAN_REF, pr_id=pr_id, objective_id="10", delivery_lineage=_LINEAGE)


def _prepared_start(parent_sha: str = "a" * 40) -> PrepareResult:
    from perk.delivery import layer as layer_mod

    context = layer_mod.LayerContext(
        objective_id="10",
        node_id="1.2",
        plan_id="102",
        delivery_lineage=_LINEAGE,
        predecessor_plan_id="101",
        base="main",
        parent_branch="plan-101",
        branch="plan-102",
    )
    return PrepareResult(
        kind="layer_start",
        mode="execution",
        layer=context,
        parent_sha=parent_sha,
    )


def _stub_delivery(monkeypatch, result):
    calls = []

    class FakeDelivery:
        def prepare(self, request):
            calls.append(request)
            if isinstance(result, DeliveryError):
                raise result
            return result

    monkeypatch.setattr(worktree_mod, "resolve_delivery", lambda _root: FakeDelivery())
    return calls


def _push_side_branch(remote: Path, name: str, *, parent_dir: Path) -> str:
    """Push branch ``name`` (one commit ahead of main) to the bare remote from a side clone;
    return its head SHA. Keeps the primary clone free of local stack metadata."""
    side = parent_dir / f"side-{name}"
    subprocess.run(["git", "clone", "-q", str(remote), str(side)], check=True, capture_output=True)

    def g(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=side, check=True, capture_output=True, text=True
        ).stdout

    g("config", "user.email", "t@example.com")
    g("config", "user.name", "perk tests")
    g("checkout", "-q", "-b", name)
    (side / f"{name}.txt").write_text("layer\n", encoding="utf-8")
    g("add", ".")
    g("commit", "-qm", f"seed {name}")
    g("push", "-q", "-u", "origin", name)
    return g("rev-parse", "HEAD").strip()


def test_stacked_explicit_base_is_a_typed_refusal(git_repo_with_remote, monkeypatch):
    clone, _remote, _advance = git_repo_with_remote
    monkeypatch.setattr(
        worktree_mod,
        "resolve_delivery",
        lambda *_a: pytest.fail("--base refusal must pre-empt Delivery.status"),
    )
    cache.write_plan_ref(clone, _stacked_ref())
    with pytest.raises(UserFacingCliError) as excinfo:
        resolve_worktree(
            repo_root=clone,
            config=_config(clone),
            request=_request("implement"),
            worktree=None,
            materialize=True,
            base="origin/main",
        )
    assert excinfo.value.error_type == "invalid_input"
    assert "derived from the delivery train" in str(excinfo.value)


def test_stacked_missing_objective_refuses_without_reconstruction_step(
    git_repo_with_remote, monkeypatch, capsys
):
    clone, _remote, _advance = git_repo_with_remote
    ref = dataclasses.replace(_stacked_ref(), objective_id=None)
    monkeypatch.setattr(
        worktree_mod,
        "resolve_delivery",
        lambda *_a: pytest.fail("missing-objective guard must pre-empt Prepare"),
    )
    cache.write_plan_ref(clone, ref)
    with pytest.raises(UserFacingCliError) as excinfo:
        resolve_worktree(
            repo_root=clone,
            config=_config(clone),
            request=_request("implement"),
            worktree=None,
            materialize=True,
        )
    assert excinfo.value.error_type == "invalid_train"
    assert "reconstructing the delivery train" not in capsys.readouterr().err


def test_stacked_not_ready_is_a_typed_refusal_and_creates_nothing(
    git_repo_with_remote, monkeypatch
):
    clone, _remote, _advance = git_repo_with_remote
    _stub_delivery(
        monkeypatch,
        DeliveryError(
            "layer 1.2 (plan #102) is not build-ready: the train has blocker findings: [x] y",
            error_type="node_not_build_ready",
        ),
    )
    cache.write_plan_ref(clone, _stacked_ref())
    with pytest.raises(UserFacingCliError) as excinfo:
        resolve_worktree(
            repo_root=clone,
            config=_config(clone),
            request=_request("implement"),
            worktree=None,
            materialize=True,
        )
    assert excinfo.value.error_type == "node_not_build_ready"
    assert "[x] y" in str(excinfo.value)
    assert not (_config(clone).worktree_root / "plan-102").exists()


def test_stacked_status_error_preserves_code_and_message(git_repo_with_remote, monkeypatch):
    clone, _remote, _advance = git_repo_with_remote
    _stub_delivery(monkeypatch, DeliveryError("journal unavailable", error_type="github_error"))
    cache.write_plan_ref(clone, _stacked_ref())

    with pytest.raises(UserFacingCliError) as excinfo:
        resolve_worktree(
            repo_root=clone,
            config=_config(clone),
            request=_request("implement"),
            worktree=None,
            materialize=True,
        )

    assert excinfo.value.error_type == "github_error"
    assert str(excinfo.value) == "journal unavailable"
    assert not (_config(clone).worktree_root / "plan-102").exists()


def test_stacked_status_without_train_fails_closed(git_repo_with_remote, monkeypatch):
    clone, _remote, _advance = git_repo_with_remote
    _stub_delivery(
        monkeypatch,
        DeliveryError(
            "plan #102 carries delivery_lineage but objective #10 has no delivery train "
            "(objective uses incremental delivery).",
            error_type="invalid_train",
        ),
    )
    cache.write_plan_ref(clone, _stacked_ref())

    with pytest.raises(UserFacingCliError) as excinfo:
        resolve_worktree(
            repo_root=clone,
            config=_config(clone),
            request=_request("implement"),
            worktree=None,
            materialize=True,
        )

    assert excinfo.value.error_type == "invalid_train"
    assert "has no delivery train (objective uses incremental delivery)" in str(excinfo.value)
    assert not (_config(clone).worktree_root / "plan-102").exists()


def test_stacked_resumed_layer_keeps_the_ordinary_resume_arm(git_repo_with_remote, monkeypatch):
    # An existing origin/plan-<id> (a resumed layer) never routes into the parent-aware path —
    # it tracks the remote branch exactly like an incremental resume.
    clone, remote, _advance = git_repo_with_remote
    layer_sha = _push_side_branch(remote, "plan-102", parent_dir=clone.parent)
    monkeypatch.setattr(
        worktree_mod,
        "resolve_delivery",
        lambda *_a: pytest.fail("a resumed layer must not read Delivery.status"),
    )
    cache.write_plan_ref(clone, _stacked_ref())
    resolved = resolve_worktree(
        repo_root=clone,
        config=_config(clone),
        request=_request("implement"),
        worktree=None,
        materialize=True,
    )
    assert resolved.base == "origin/plan-102"
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=resolved.path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert head == layer_sha
    assert not (resolved.path / ".perk" / "workflow" / "layer-context.json").exists()


def test_stacked_dry_run_stays_offline_and_names_the_derivation(git_repo_with_remote, monkeypatch):
    clone, _remote, _advance = git_repo_with_remote
    from perk.run.launch.worktree import STACKED_DRY_RUN_BASE

    monkeypatch.setattr(
        worktree_mod,
        "resolve_delivery",
        lambda *_a: pytest.fail("a dry run must stay offline"),
    )
    cache.write_plan_ref(clone, _stacked_ref())
    resolved = resolve_worktree(
        repo_root=clone,
        config=_config(clone),
        request=_request("implement"),
        worktree=None,
        materialize=False,
    )
    assert resolved.base == STACKED_DRY_RUN_BASE
    assert not resolved.path.exists()
