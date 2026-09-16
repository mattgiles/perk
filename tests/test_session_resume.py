"""The session-resume engine (`perk.run.launch.session_resume`, contracts.md §8.71).

Fixtures seed REAL registered worktrees (`git.worktree_add` + `cache.write_plan_ref`) — the
validators refuse a bare `mkdir` as `worktree_unregistered`. The process boundary is the shared
`launch_exec_recorder` (it patches the facade names + the shared `os` attributes the one
`exec_pi` pipeline reads), so every "exec'd" assertion is a stubbed argv/env-construction test.
"""

import json
from pathlib import Path

import pytest

from perk import __version__, plan
from perk.cli.ensure import UserFacingCliError
from perk.run import launch
from perk.run.launch import session_resume
from perk.state import cache
from perk.substrate import git
from perk.substrate.config import Config, PiAgentDir

pytestmark = pytest.mark.usefixtures("stub_launch_extension_warm")


def _ref(pr_id: str) -> plan.PlanRef:
    return plan.PlanRef(
        provider="github", pr_id=pr_id, url=f"https://gh/o/r/issues/{pr_id}", labels=("perk:plan",)
    )


def _config(root: Path) -> Config:
    return Config(worktree_root=root / ".worktrees")


def _bound_worktree(root: Path, name: str, *, branch: str, bound_to: str | None) -> Path:
    """A REAL registered worktree at `<root>/.worktrees/<name>` on `branch`, bound to plan
    `bound_to` (or left unbound)."""
    wt = root / ".worktrees" / name
    git.worktree_add(root, wt, branch=branch, create_branch=True)
    if bound_to is not None:
        cache.write_plan_ref(wt, _ref(bound_to))
    return wt


def _resolve(root: Path, *, invocation_root: Path | None = None, ref=None, worktree=None) -> Path:
    return session_resume.resolve_resume_checkout(
        invocation_root=invocation_root if invocation_root is not None else root,
        main_root=root,
        config=_config(root),
        ref=ref,
        worktree=worktree,
    )


# --- resolve_resume_checkout: the target table ---------------------------------------------


def test_bare_from_main_is_the_main_root(git_repo):
    assert _resolve(git_repo) == git_repo


def test_bare_from_linked_worktree_is_that_worktree_and_ignores_the_root_selector(git_repo):
    # The main-root `plan-ref` selector (a FOREIGN plan) is never read by the bare form.
    cache.write_plan_ref(git_repo, _ref("99"))
    wt = _bound_worktree(git_repo, "plan-42", branch="plan-42", bound_to="42")
    assert _resolve(git_repo, invocation_root=wt) == wt


def test_worktree_root_word_is_the_main_root(git_repo):
    assert _resolve(git_repo, worktree="root") == git_repo


def test_worktree_name_registered_resolves_without_a_binding(git_repo):
    # No plan binding is required for a bare `--worktree NAME` reopen.
    wt = _bound_worktree(git_repo, "scratch", branch="scratch", bound_to=None)
    assert _resolve(git_repo, worktree="scratch") == wt


def test_worktree_name_missing_refuses_not_found_naming_implement(git_repo):
    with pytest.raises(UserFacingCliError) as exc:
        _resolve(git_repo, worktree="plan-42")
    assert exc.value.error_type == "worktree_not_found"
    assert "perk implement <PLAN> --worktree plan-42" in str(exc.value)
    assert "never creates, restores, or rebinds" in str(exc.value)


def test_worktree_name_unregistered_dir_refuses(git_repo):
    (git_repo / ".worktrees" / "loose").mkdir(parents=True)
    with pytest.raises(UserFacingCliError) as exc:
        _resolve(git_repo, worktree="loose")
    assert exc.value.error_type == "worktree_unregistered"


def test_worktree_name_registered_but_broken_refuses(git_repo):
    # A retained admin entry whose gitfile is gone: git resolves the path to the MAIN checkout.
    wt = _bound_worktree(git_repo, "broken", branch="broken", bound_to=None)
    (wt / ".git").unlink()
    with pytest.raises(UserFacingCliError) as exc:
        _resolve(git_repo, worktree="broken")
    assert exc.value.error_type == "worktree_unregistered"
    assert "not a usable git worktree" in str(exc.value)


def test_plan_with_existing_bound_worktree_resolves(git_repo):
    wt = _bound_worktree(git_repo, "plan-42", branch="plan-42", bound_to="42")
    assert _resolve(git_repo, ref=_ref("42")) == wt


def test_plan_missing_refuses_not_found_naming_implement_id(git_repo):
    with pytest.raises(UserFacingCliError) as exc:
        _resolve(git_repo, ref=_ref("42"))
    assert exc.value.error_type == "worktree_not_found"
    assert "no checkout for plan #42" in str(exc.value)
    assert "perk implement 42 creates or restores it" in str(exc.value)


def test_plan_with_named_worktree_of_another_plan_refuses_branch_mismatch(git_repo):
    # An ordinary checkout of plan 43 sits on `plan-43`: the branch probe fires BEFORE the
    # binding comparison (the validator's existing probe order).
    _bound_worktree(git_repo, "other", branch="plan-43", bound_to="43")
    with pytest.raises(UserFacingCliError) as exc:
        _resolve(git_repo, ref=_ref("42"), worktree="other")
    assert exc.value.error_type == "worktree_branch_mismatch"


def test_plan_with_named_worktree_on_right_branch_but_foreign_binding_refuses_plan_mismatch(
    git_repo,
):
    # A deliberately inconsistent checkout: on `plan-42` but bound to plan 43.
    _bound_worktree(git_repo, "odd", branch="plan-42", bound_to="43")
    with pytest.raises(UserFacingCliError) as exc:
        _resolve(git_repo, ref=_ref("42"), worktree="odd")
    assert exc.value.error_type == "worktree_plan_mismatch"


def test_plan_with_unbound_worktree_refuses_unbound(git_repo):
    _bound_worktree(git_repo, "plan-42", branch="plan-42", bound_to=None)
    with pytest.raises(UserFacingCliError) as exc:
        _resolve(git_repo, ref=_ref("42"))
    assert exc.value.error_type == "worktree_unbound"


def test_plan_with_named_worktree_missing_refuses_not_found_naming_the_name(git_repo):
    with pytest.raises(UserFacingCliError) as exc:
        _resolve(git_repo, ref=_ref("42"), worktree="plan-42-b")
    assert exc.value.error_type == "worktree_not_found"
    assert "perk implement 42 --worktree plan-42-b creates one" in str(exc.value)


def test_plan_with_worktree_root_word_is_invalid_input(git_repo):
    with pytest.raises(UserFacingCliError) as exc:
        _resolve(git_repo, ref=_ref("42"), worktree="root")
    assert exc.value.error_type == "invalid_input"
    assert "never a plan's implementation worktree" in str(exc.value)


@pytest.mark.parametrize("ref", [None, _ref("42")])
def test_invalid_worktree_name_refuses_before_any_filesystem_probe(tmp_path, monkeypatch, ref):
    # `checked_name` fires first: no `exists()` probe, no git — the untyped invariant refusal
    # maps to `invalid_input` at the command boundary.
    def _no_probe(self):
        raise AssertionError("no filesystem probe for an invalid name")

    monkeypatch.setattr(Path, "exists", _no_probe)
    with pytest.raises(UserFacingCliError, match="Invalid worktree name"):
        _resolve(tmp_path, ref=ref, worktree="../x")


# --- prepare_session_resume: argv built once, no --approve ---------------------------------


@pytest.mark.parametrize("linked", [False, True])
def test_prepare_argv_is_exactly_pi_resume_with_no_approve(git_repo, linked):
    checkout = (
        _bound_worktree(git_repo, "plan-42", branch="plan-42", bound_to="42")
        if linked
        else git_repo
    )
    spec = session_resume.prepare_session_resume(main_root=git_repo, checkout=checkout)
    assert spec.argv == ("pi", "--resume")
    assert "--approve" not in spec.argv
    assert spec.checkout == checkout and spec.main_root == git_repo
    assert spec.agent_dir.resolution is not None and spec.agent_dir.resolution.source == "env"


def test_prepare_refuses_a_non_directory_agent_dir_before_anything_else(tmp_path, monkeypatch):
    monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
    (tmp_path / ".perk").mkdir()
    (tmp_path / ".perk/config.toml").write_text('[pi]\nagent_dir = "file"\n', encoding="utf-8")
    (tmp_path / "file").touch()
    with pytest.raises(UserFacingCliError) as exc:
        session_resume.prepare_session_resume(main_root=tmp_path, checkout=tmp_path)
    assert exc.value.error_type == "pi_agent_dir_invalid"


# --- exec_session_resume: the one shared pipeline ------------------------------------------


def _spec(main_root: Path, checkout: Path) -> session_resume.SessionResumeLaunch:
    return session_resume.prepare_session_resume(main_root=main_root, checkout=checkout)


def test_exec_chdirs_then_execs_absolute_pi_with_pi_resume(
    tmp_path, monkeypatch, launch_exec_recorder
):
    monkeypatch.setenv("PERK_RUN_ID", "01OPERATOR")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    session_resume.exec_session_resume(_spec(tmp_path, checkout))
    assert launch_exec_recorder.chdirs == [checkout]
    program, argv, env = launch_exec_recorder.calls[0]
    assert program == launch_exec_recorder.pi_path
    assert argv == ("pi", "--resume")
    assert "PERK_RUN_ID" not in env  # the operator's run id is DROPPED, never forwarded
    assert env["PERK_CLI_VERSION"] == __version__
    # The env arm's redirect is forwarded untouched (no injection, no scrub).
    assert env["PI_CODING_AGENT_DIR"] == str(launch_exec_recorder.agent_dir)


def test_exec_config_arm_injects_main_root_relative_dir_from_a_linked_worktree(
    git_repo, monkeypatch, launch_exec_recorder
):
    # Committed `[pi] agent_dir` + a main-only `local.toml` overlay; a relative value resolves
    # under the MAIN root even when the reopen targets a linked worktree.
    monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
    (git_repo / ".perk").mkdir(exist_ok=True)
    (git_repo / ".perk/config.toml").write_text(
        '[pi]\nagent_dir = "committed-agent"\n', encoding="utf-8"
    )
    (git_repo / ".perk/local.toml").write_text(
        '[pi]\nagent_dir = "local-agent"\n', encoding="utf-8"
    )
    agent_dir = git_repo / "local-agent"
    agent_dir.mkdir()
    stale_lock = agent_dir / "settings.json.lock"
    stale_lock.touch()
    wt = _bound_worktree(git_repo, "plan-42", branch="plan-42", bound_to="42")
    session_resume.exec_session_resume(_spec(git_repo, wt))
    env = launch_exec_recorder.calls[0][2]
    assert env["PI_CODING_AGENT_DIR"] == str(agent_dir)
    assert not stale_lock.exists()  # the stale-lock sweep targets the resolved store
    assert launch_exec_recorder.chdirs == [wt]


@pytest.mark.parametrize("value", ["", " \t "])
def test_exec_scrubs_a_blank_inherited_redirect(tmp_path, monkeypatch, launch_exec_recorder, value):
    monkeypatch.setenv("PI_CODING_AGENT_DIR", value)
    session_resume.exec_session_resume(_spec(tmp_path, tmp_path))
    assert "PI_CODING_AGENT_DIR" not in launch_exec_recorder.calls[0][2]


def test_exec_seeds_linear_key_from_main_local_toml_only_when_absent(
    tmp_path, monkeypatch, launch_exec_recorder
):
    (tmp_path / ".perk").mkdir()
    (tmp_path / ".perk/local.toml").write_text(
        '[linear]\napi_key = "lin_local"\n', encoding="utf-8"
    )
    monkeypatch.delenv("LINEAR_API_KEY", raising=False)
    session_resume.exec_session_resume(_spec(tmp_path, tmp_path))
    assert launch_exec_recorder.calls[0][2]["LINEAR_API_KEY"] == "lin_local"
    monkeypatch.setenv("LINEAR_API_KEY", "lin_env")
    session_resume.exec_session_resume(_spec(tmp_path, tmp_path))
    assert launch_exec_recorder.calls[1][2]["LINEAR_API_KEY"] == "lin_env"  # env wins


def test_exec_pi_missing_refuses_typed_before_any_chdir(
    tmp_path, monkeypatch, launch_exec_recorder
):
    def _missing():
        raise UserFacingCliError("pi CLI not found on PATH", error_type="pi_cli_missing")

    monkeypatch.setattr(launch, "_resolve_pi_executable", _missing)
    with pytest.raises(UserFacingCliError) as exc:
        session_resume.exec_session_resume(_spec(tmp_path, tmp_path))
    assert exc.value.error_type == "pi_cli_missing"
    assert launch_exec_recorder.chdirs == [] and launch_exec_recorder.calls == []


def test_exec_oserror_is_launch_failed(tmp_path, monkeypatch, launch_exec_recorder):
    def _boom(program, argv, env):
        raise OSError("exec denied")

    monkeypatch.setattr(launch.os, "execvpe", _boom)
    with pytest.raises(UserFacingCliError) as exc:
        session_resume.exec_session_resume(_spec(tmp_path, tmp_path))
    assert exc.value.error_type == "launch_failed"
    assert f"could not launch pi in {tmp_path}" in str(exc.value)


# --- emit_session_resume_preview: the dry-run report + preview/exec parity ----------------


def test_preview_renders_four_lines_and_the_ordered_payload(tmp_path, capsys, launch_exec_recorder):
    spec = _spec(tmp_path, tmp_path)
    session_resume.emit_session_resume_preview(spec)
    captured = capsys.readouterr()
    err_lines = captured.err.splitlines()
    assert "resume --dry-run (session picker — resolve only, no launch)" in err_lines[0]
    assert err_lines[1] == f"  checkout: {tmp_path}"
    assert err_lines[2] == f"  agent dir: {launch_exec_recorder.agent_dir} (env)"
    assert err_lines[3] == "  command:  pi --resume"
    payload = json.loads(captured.out)
    assert list(payload) == [
        "success",
        "checkout",
        "agent_dir",
        "agent_dir_source",
        "argv",
        "dry_run",
    ]
    assert payload == {
        "success": True,
        "checkout": str(tmp_path),
        "agent_dir": str(launch_exec_recorder.agent_dir),
        "agent_dir_source": "env",
        "argv": ["pi", "--resume"],
        "dry_run": True,
    }
    # Parity: the previewed argv IS the exec'd argv for the same spec.
    session_resume.exec_session_resume(spec)
    assert payload["argv"] == list(spec.argv) == list(launch_exec_recorder.calls[0][1])


def test_preview_unresolved_agent_dir(tmp_path, capsys):
    spec = session_resume.SessionResumeLaunch(
        main_root=tmp_path,
        checkout=tmp_path,
        argv=("pi", "--resume"),
        agent_dir=launch.LaunchAgentDir(resolution=None, injected=None),
    )
    session_resume.emit_session_resume_preview(spec)
    captured = capsys.readouterr()
    assert "  agent dir: unresolved" in captured.err
    payload = json.loads(captured.out)
    assert payload["agent_dir"] is None and payload["agent_dir_source"] is None


def test_preview_config_arm_reports_config_source(tmp_path, capsys):
    spec = session_resume.SessionResumeLaunch(
        main_root=tmp_path,
        checkout=tmp_path,
        argv=("pi", "--resume"),
        agent_dir=launch.LaunchAgentDir(
            resolution=PiAgentDir(tmp_path / "agent", "config"), injected=tmp_path / "agent"
        ),
    )
    session_resume.emit_session_resume_preview(spec)
    captured = capsys.readouterr()
    assert f"  agent dir: {tmp_path / 'agent'} (config)" in captured.err
    assert json.loads(captured.out)["agent_dir_source"] == "config"


# --- import direction ------------------------------------------------------------------------


def test_facade_never_imports_the_engine():
    """The facade `__init__` must not import `session_resume` (which imports the facade and
    reads its helpers as attributes at call time) — the name-binding rule's import direction."""
    assert "session_resume" not in Path(launch.__file__).read_text(encoding="utf-8")
