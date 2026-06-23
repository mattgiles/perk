import json
import subprocess
from pathlib import Path

import pytest
from _launch_helpers import _PLAN_REF, _config, _stage

from perk.cli.ensure import UserFacingCliError
from perk.run import launch
from perk.run.launch import (
    _address_prompt,
    _initial_prompt,
    _pi_agent_dir,
    _sweep_stale_pi_agent_locks,
    launch_stage,
    resolve_base,
    resolve_plan_worktree_name,
    resolve_target,
    resolve_worktree,
)
from perk.state import cache
from perk.substrate import git as git_mod
from perk.substrate.bindings import Binding
from perk.substrate.config import Config
from perk.substrate.git import GitError


def _binding(trigger: str, skill: str, mode: str = "nudge") -> "Binding":
    kind, target_id = trigger.split(":", 1)
    return Binding(trigger, kind, target_id, skill, mode)


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


def test_resolve_worktree_none_is_repo_root(tmp_path):
    resolved = resolve_worktree(
        repo_root=tmp_path,
        config=_config(tmp_path),
        stage=_stage("plan"),
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


# --- T4a: plan-ref-aware worktree resolution -------------------------------------------


@pytest.mark.parametrize(
    ("pr_id", "expected"),
    [("42", "plan-42"), ("PROJ-123", "plan-PROJ-123")],
)
def test_resolve_plan_worktree_name(pr_id, expected):
    assert resolve_plan_worktree_name({"pr_id": pr_id}) == expected


@pytest.mark.parametrize("pr_id", ["", "a/b", ".", ".."])
def test_resolve_plan_worktree_name_rejects_unusable(pr_id):
    with pytest.raises(UserFacingCliError, match="unusable as a worktree name"):
        resolve_plan_worktree_name({"pr_id": pr_id})


def test_implement_no_plan_ref_errors(tmp_path):
    with pytest.raises(UserFacingCliError, match="needs a saved plan") as exc:
        resolve_worktree(
            repo_root=tmp_path,
            config=_config(tmp_path),
            stage=_stage("implement"),
            worktree=None,
            materialize=False,
        )
    assert exc.value.error_type == "no_plan_ref"


def test_implement_derives_name_from_active_plan_ref(tmp_path):
    cache.write_plan_ref(tmp_path, _PLAN_REF)
    resolved = resolve_worktree(
        repo_root=tmp_path,
        config=_config(tmp_path),
        stage=_stage("implement"),
        worktree=None,
        materialize=False,  # dry-run: derive without creating
    )
    assert resolved.path == _config(tmp_path).worktree_root / "plan-42"
    assert resolved.plan_ref == _PLAN_REF


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
    assert data["plan_ref"] == _PLAN_REF
    # The implement launch is primed — argv carries the initial prompt.
    assert data["argv"][0] == "pi"
    assert len(data["argv"]) == 3
    assert "gh issue view 42 --comments" in data["argv"][-1]
    # implement is a `worktree: create` stage, so perk auto-approves project trust for the run.
    assert "--approve" in data["argv"]
    assert data["argv"][1] == "--approve"
    # dry run is side-effect-free: no worktree, no handoff
    assert not (_config(tmp_path).worktree_root / "plan-42").exists()


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
    assert "Follow the `custom-implement` skill." in prompt  # delivered additively


def test_idle_launch_does_not_synthesize_binding_prompt(tmp_path, capsys):
    # (D2): cold delivery AUGMENTS an existing prompt only — it never synthesizes one. The
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
    assert data["argv"][-1].count("perk-implement") == 1
    assert "Follow the `perk-implement` skill." in data["argv"][-1]


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
    assert "Follow the `perk-objective-plan` skill." in data["argv"][-1]


def test_initial_prompt_primes_implement_and_address():
    """Implement and address are primed; other stages launch unprimed."""
    impl = _initial_prompt(_stage("implement"), _PLAN_REF)
    assert impl is not None and "gh issue view 42 --comments" in impl and "/submit" in impl
    # The implement prompt teaches the marker protocol; the perk-implement skill pointer is NOT
    # hardcoded here anymore (it rides the skill-binding mechanism).
    assert "[DONE:" in impl and "[WIP:" in impl and "perk-implement" not in impl
    addr = _initial_prompt(_stage("address"), _PLAN_REF)
    assert addr is not None and "perk-address" not in addr and "review-classifier" in addr
    assert _initial_prompt(_stage("plan"), _PLAN_REF) is None
    assert _initial_prompt(_stage("implement"), None) is None
    assert _initial_prompt(_stage("address"), None) is None
    # The new defaulted `preview` param leaves the non-preview address prompt unchanged.
    assert _initial_prompt(_stage("address"), _PLAN_REF, preview=False) == addr


def test_address_prompt_preview_is_classification_only():
    """The cold `--preview` flag shapes the address seed to classify-only (no action),
    mirroring the warm `addressGuidance(preview=true)` shape; non-preview body is unchanged."""
    preview = _address_prompt(_PLAN_REF, preview=True)
    assert "PREVIEWING" in preview
    assert "take NO action" in preview and "preview only" in preview
    # The fix→resolve→land tail is omitted in preview.
    assert "resolve_review_threads" not in preview
    assert "/land" not in preview
    # The non-preview body (the default) keeps the full loop.
    full = _address_prompt(_PLAN_REF)
    assert _address_prompt(_PLAN_REF, preview=False) == full
    assert "resolve_review_threads" in full and "PREVIEWING" not in full


def test_initial_prompt_injects_classifier_model_from_config():
    """A configured `[subagents] review-classifier` model is injected into the address
    prompt's spawn clause; an absent key (or no config) leaves it unset."""
    config = Config(worktree_root=Path("/tmp/x"), subagents={"review-classifier": "test/model"})
    primed = _initial_prompt(_stage("address"), _PLAN_REF, config)
    assert primed is not None and 'model: "test/model"' in primed
    bare = _initial_prompt(_stage("address"), _PLAN_REF, Config(worktree_root=Path("/tmp/x")))
    assert bare is not None and "passing `model:" not in bare


def test_initial_prompt_primes_learn():
    """The learn stage is primed — it derives the merged PR from the plan-<pr_id> head
    branch and stays unprimed without a plan-ref (the perk-learn pointer rides the binding
    mechanism — not the hardcoded prompt)."""
    learn = _initial_prompt(_stage("learn"), _PLAN_REF)
    assert learn is not None
    assert "perk-learn" not in learn  # the skill pointer rides the binding mechanism
    assert "plan-42" in learn  # the derived head branch (pr_id is the plan-issue number)
    assert "gh pr list --head plan-42" in learn
    assert "learn` tool" in learn  # drives the durable capture path
    assert "/learn skip" in learn
    assert _initial_prompt(_stage("learn"), None) is None


_LINEAR_PLAN_REF = {
    "provider": "linear",
    "pr_id": "a1b2c3d4-0000-0000-0000-000000000000",
    "url": "https://linear.app/acme/issue/ENG-123",
}


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
    assert f"gh pr list --head plan-{_LINEAR_PLAN_REF['pr_id']} --state merged" in prompt


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
    assert not (tmp_path / ".pi" / "workflow" / "handoff").exists()


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


# --- T8c: the launch target resolver --------------------------------------------------


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

    cache.write_plan_ref(tmp_path, {**_PLAN_REF, "base": "develop"})
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


def _no_exec(monkeypatch):
    monkeypatch.setattr("perk.run.launch.os.chdir", lambda _p: None)
    monkeypatch.setattr("perk.run.launch.os.execvpe", lambda f, a, e: None)
    monkeypatch.setattr("perk.backends.github.plans.get_plan_body", lambda **_k: None)


def test_create_bases_off_fresh_origin_trunk(git_repo_with_remote, monkeypatch):
    """Materialize-create fetches origin and bases the new branch on origin/<trunk>, not the
    stale local HEAD."""
    clone, _remote, advance = git_repo_with_remote
    advanced = advance()  # origin/main is now ahead of the clone's local HEAD
    cache.write_plan_ref(clone, _PLAN_REF)
    _no_exec(monkeypatch)
    launch_stage(
        repo_root=clone,
        config=Config(worktree_root=clone / ".worktrees"),
        stage=_stage("implement"),
        worktree=None,
        dry_run=False,
        remote=None,
        pi_args=[],
    )
    wt = clone / ".worktrees" / "plan-42"
    assert _sha(wt) == advanced  # based off freshly-fetched origin/main, not stale local HEAD


def test_reuse_does_not_fetch_or_rebase(git_repo_with_remote, monkeypatch):
    clone, _remote, _advance = git_repo_with_remote
    cache.write_plan_ref(clone, _PLAN_REF)
    _no_exec(monkeypatch)
    fetches: list[Path] = []
    real_fetch = git_mod.fetch
    monkeypatch.setattr(
        "perk.run.launch.git.fetch",
        lambda repo, **k: (fetches.append(repo), real_fetch(repo, **k))[1],
    )

    def _run():
        launch_stage(
            repo_root=clone,
            config=Config(worktree_root=clone / ".worktrees"),
            stage=_stage("implement"),
            worktree=None,
            dry_run=False,
            remote=None,
            pi_args=[],
        )

    _run()
    assert len(fetches) == 1  # create fetched once
    _run()  # path now exists -> reuse
    assert len(fetches) == 1  # reuse did not fetch again


def test_offline_fetch_failure_warns_and_falls_back(git_repo_with_remote, monkeypatch, capsys):
    clone, _remote, _advance = git_repo_with_remote
    cache.write_plan_ref(clone, _PLAN_REF)
    _no_exec(monkeypatch)

    def boom(repo, **k):
        raise GitError("offline")

    monkeypatch.setattr("perk.run.launch.git.fetch", boom)
    launch_stage(
        repo_root=clone,
        config=Config(worktree_root=clone / ".worktrees"),
        stage=_stage("implement"),
        worktree=None,
        dry_run=False,
        remote=None,
        pi_args=[],
    )
    wt = clone / ".worktrees" / "plan-42"
    assert wt.is_dir()  # still created
    assert "STALE" in capsys.readouterr().err  # loud warning
    # based off last-known origin/main
    assert _sha(wt) == _sha(clone, "origin/main")


def test_remote_branch_exists_bases_off_tracking(git_repo_with_remote, monkeypatch):
    clone, _remote, _advance = git_repo_with_remote
    # Create origin/plan-42 pointing at a distinct commit on the remote.
    subprocess.run(["git", "branch", "plan-42", "main"], cwd=clone, check=True, capture_output=True)
    subprocess.run(
        ["git", "push", "-q", "origin", "plan-42"], cwd=clone, check=True, capture_output=True
    )
    subprocess.run(["git", "branch", "-D", "plan-42"], cwd=clone, check=True, capture_output=True)
    cache.write_plan_ref(clone, _PLAN_REF)
    _no_exec(monkeypatch)
    bases: list[str | None] = []
    real_add = git_mod.worktree_add
    monkeypatch.setattr(
        "perk.run.launch.git.worktree_add",
        lambda *a, **k: (bases.append(k.get("base")), real_add(*a, **k))[1],
    )
    launch_stage(
        repo_root=clone,
        config=Config(worktree_root=clone / ".worktrees"),
        stage=_stage("implement"),
        worktree=None,
        dry_run=False,
        remote=None,
        pi_args=[],
    )
    assert bases == ["origin/plan-42"]


def test_base_override_is_used_verbatim(git_repo_with_remote, monkeypatch):
    clone, _remote, _advance = git_repo_with_remote
    cache.write_plan_ref(clone, _PLAN_REF)
    _no_exec(monkeypatch)
    bases: list[str | None] = []
    real_add = git_mod.worktree_add
    monkeypatch.setattr(
        "perk.run.launch.git.worktree_add",
        lambda *a, **k: (bases.append(k.get("base")), real_add(*a, **k))[1],
    )
    launch_stage(
        repo_root=clone,
        config=Config(worktree_root=clone / ".worktrees"),
        stage=_stage("implement"),
        worktree=None,
        dry_run=False,
        remote=None,
        pi_args=[],
        base="main",
    )
    assert bases == ["main"]  # verbatim, no origin/<trunk> override


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
    cache.write_plan_ref(clone, {**_PLAN_REF, "base": "develop"})
    _no_exec(monkeypatch)
    bases: list[str | None] = []
    real_add = git_mod.worktree_add
    monkeypatch.setattr(
        "perk.run.launch.git.worktree_add",
        lambda *a, **k: (bases.append(k.get("base")), real_add(*a, **k))[1],
    )
    launch_stage(
        repo_root=clone,
        config=Config(worktree_root=clone / ".worktrees"),
        stage=_stage("implement"),
        worktree=None,
        dry_run=False,
        remote=None,
        pi_args=[],
    )
    assert bases == ["origin/develop"]
    wt = clone / ".worktrees" / "plan-42"
    assert _sha(wt) == _sha(clone, "origin/develop")


def test_explicit_worktree_recovers_base_but_does_not_clobber_plan_ref(
    git_repo_with_remote, monkeypatch
):
    # Regression guard: an explicit --worktree NAME recovers the active plan-ref's pinned
    # base for the start-point, but must NOT write that ref into the named worktree (the returned
    # ResolvedWorktree.plan_ref stays None on this path).
    clone, _remote, _advance = git_repo_with_remote
    _push_origin_branch(clone, "develop")
    cache.write_plan_ref(clone, {**_PLAN_REF, "base": "develop"})
    _no_exec(monkeypatch)
    bases: list[str | None] = []
    real_add = git_mod.worktree_add
    monkeypatch.setattr(
        "perk.run.launch.git.worktree_add",
        lambda *a, **k: (bases.append(k.get("base")), real_add(*a, **k))[1],
    )
    launch_stage(
        repo_root=clone,
        config=Config(worktree_root=clone / ".worktrees"),
        stage=_stage("implement"),
        worktree="custom-wt",
        dry_run=False,
        remote=None,
        pi_args=[],
    )
    # The pinned base still drove the start-point...
    assert bases == ["origin/develop"]
    # ...but the named worktree's own cache.plan-ref was NOT written (no clobber).
    assert not (clone / ".worktrees" / "custom-wt" / ".pi" / "workflow" / "plan-ref.json").exists()


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
