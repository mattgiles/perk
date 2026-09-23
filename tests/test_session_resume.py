"""The session-resume engine (`perk.run.launch.session_resume`, contracts.md §8.71).

Fixtures seed REAL registered worktrees (`git.worktree_add` + `cache.write_plan_ref`) — the
validators refuse a bare `mkdir` as `worktree_unregistered`. The process boundary is the shared
`launch_exec_recorder` (it patches the facade names + the shared `os` attributes the one
`exec_pi` pipeline reads), so every "exec'd" assertion is a stubbed argv/env-construction test.
"""

import ast
import json
from pathlib import Path

import pytest

from perk import __version__, plan
from perk.cli.ensure import UserFacingCliError
from perk.run import launch, pi_exec
from perk.run.launch import session_resume
from perk.state import cache, session_pointers
from perk.state.run_id import mint
from perk.state.session_pointers import RunSessionEntry, SessionPointers
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


# --- resolve_run_session: the run arm's selector -------------------------------------------


def _entry(
    pi_session_id: str, *, session_file: Path | str, cwd: Path | str, at: str
) -> RunSessionEntry:
    return RunSessionEntry(
        pi_session_id=pi_session_id, session_file=str(session_file), cwd=str(cwd), at=at
    )


def _live_entry(tmp_path: Path, name: str, at: str) -> RunSessionEntry:
    """An entry whose session file AND cwd exist under ``tmp_path``."""
    checkout = tmp_path / f"checkout-{name}"
    checkout.mkdir(exist_ok=True)
    session_file = tmp_path / f"{name}.jsonl"
    session_file.write_text("{}\n", encoding="utf-8")
    return _entry(f"{name}.jsonl", session_file=session_file, cwd=checkout, at=at)


def _write_record(root: Path, run_id: str, *entries: RunSessionEntry) -> Path:
    return session_pointers.write_session_pointers(
        root, run_id, SessionPointers(run_id=run_id, sessions=entries)
    )


def test_run_session_refuses_run_not_found_when_no_record(tmp_path, capsys):
    rid = mint()
    with pytest.raises(UserFacingCliError) as exc:
        session_resume.resolve_run_session(tmp_path, rid)
    assert exc.value.error_type == "run_not_found"
    message = str(exc.value)
    assert str(session_pointers.session_pointers_path(tmp_path, rid)) in message
    assert "perk state prune" in message and "perk resume" in message
    assert capsys.readouterr().err == ""


def test_run_session_refuses_run_not_found_when_sessions_is_empty(tmp_path):
    rid = mint()
    _write_record(tmp_path, rid)
    with pytest.raises(UserFacingCliError) as exc:
        session_resume.resolve_run_session(tmp_path, rid)
    assert exc.value.error_type == "run_not_found"


def test_run_session_refuses_run_not_found_for_an_invalid_utf8_record(tmp_path, capsys):
    # Decision 7: a corrupt record of ANY class arrives as the reader's `None` (after its own
    # path-naming warning) and reports as `run_not_found` — one typed error, no traceback.
    rid = mint()
    path = session_pointers.session_pointers_path(tmp_path, rid)
    path.parent.mkdir(parents=True)
    path.write_bytes(b'\xff\xfe{"run_id":')
    with pytest.raises(UserFacingCliError) as exc:
        session_resume.resolve_run_session(tmp_path, rid)
    assert exc.value.error_type == "run_not_found"
    err = capsys.readouterr().err
    assert "skipping unreadable session-pointers record" in err and str(path) in err


_ULID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"


@pytest.mark.parametrize("run_id", [f"{_ULID}./../x", f"{_ULID}/x", "42", ""])
def test_run_session_refuses_a_non_canonical_id_before_any_filesystem_probe(
    tmp_path, monkeypatch, run_id
):
    def _no_probe(self, *args, **kwargs):
        raise AssertionError("no filesystem probe for a non-canonical run id")

    monkeypatch.setattr(Path, "is_file", _no_probe)
    monkeypatch.setattr(Path, "is_dir", _no_probe)
    monkeypatch.setattr(Path, "resolve", _no_probe)
    with pytest.raises(UserFacingCliError) as exc:
        session_resume.resolve_run_session(tmp_path, run_id)
    assert exc.value.error_type == "invalid_input"
    assert "not a canonical perk run id" in str(exc.value)


def test_run_session_containment_assertion_is_live(tmp_path, monkeypatch):
    # Unreachable through the grammar — bypass it by rebinding the path derivation so the
    # derived record escapes the run-scratch root; the assertion must fire on its own.
    outside = tmp_path / "outside" / "session-pointers.json"
    monkeypatch.setattr(session_pointers, "session_pointers_path", lambda root, run_id: outside)
    with pytest.raises(UserFacingCliError) as exc:
        session_resume.resolve_run_session(tmp_path, mint())
    assert exc.value.error_type == "invalid_input"
    assert "escapes" in str(exc.value) and str(outside) in str(exc.value)


def test_run_session_newest_first_captured_at_wins_and_lists_the_others(tmp_path, capsys):
    rid = mint()
    e3 = _live_entry(tmp_path, "c", "2026-06-01T03:00:00.000Z")
    e1 = _live_entry(tmp_path, "a", "2026-06-01T01:00:00.000Z")
    e2 = _live_entry(tmp_path, "b", "2026-06-01T02:00:00.000Z")
    _write_record(tmp_path, rid, e3, e1, e2)  # written out of order
    target = session_resume.resolve_run_session(tmp_path, rid)
    assert target == session_resume.RunSessionTarget(
        checkout=Path(e3.cwd), session_file=Path(e3.session_file), pi_session_id="c.jsonl"
    )
    err_lines = capsys.readouterr().err.splitlines()
    assert len(err_lines) == 1
    assert err_lines[0] == (
        f"run {rid} has 3 recorded conversations — opening the newest (c.jsonl); "
        "others: a.jsonl, b.jsonl"
    )


def test_run_session_tie_on_at_goes_to_the_later_list_entry(tmp_path):
    rid = mint()
    at = "2026-06-01T01:00:00.000Z"
    first = _live_entry(tmp_path, "first", at)
    later = _live_entry(tmp_path, "later", at)
    _write_record(tmp_path, rid, first, later)
    assert session_resume.resolve_run_session(tmp_path, rid).pi_session_id == "later.jsonl"


def test_run_session_refuses_session_missing_naming_the_deferred_first_flush(tmp_path):
    rid = mint()
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    gone = tmp_path / "gone.jsonl"
    _write_record(
        tmp_path,
        rid,
        _entry("gone.jsonl", session_file=gone, cwd=checkout, at="2026-06-01T01:00:00.000Z"),
    )
    with pytest.raises(UserFacingCliError) as exc:
        session_resume.resolve_run_session(tmp_path, rid)
    assert exc.value.error_type == "session_missing"
    message = str(exc.value)
    assert "gone.jsonl" in message and str(gone) in message
    assert "first assistant reply" in message and "perk resume" in message


# A path component longer than NAME_MAX: `Path.is_file()` / `is_dir()` raise `ENAMETOOLONG`
# (not the swallowed `ENOENT`) on Python 3.13, so it exercises the probe boundary deterministically
# (a permission-denied fixture would not fail under root).
_UNPROBEABLE = "x" * 300


def test_run_session_unprobeable_session_file_is_session_missing_not_a_traceback(tmp_path):
    rid = mint()
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    unprobeable = tmp_path / _UNPROBEABLE / "s.jsonl"
    _write_record(
        tmp_path,
        rid,
        _entry("s.jsonl", session_file=unprobeable, cwd=checkout, at="2026-06-01T01:00:00.000Z"),
    )
    with pytest.raises(UserFacingCliError) as exc:
        session_resume.resolve_run_session(tmp_path, rid)
    assert exc.value.error_type == "session_missing"


def test_run_session_unprobeable_checkout_is_checkout_missing_not_a_traceback(tmp_path):
    rid = mint()
    session_file = tmp_path / "s.jsonl"
    session_file.write_text("{}\n", encoding="utf-8")
    unprobeable = tmp_path / _UNPROBEABLE
    _write_record(
        tmp_path,
        rid,
        _entry(
            "s.jsonl", session_file=session_file, cwd=unprobeable, at="2026-06-01T01:00:00.000Z"
        ),
    )
    with pytest.raises(UserFacingCliError) as exc:
        session_resume.resolve_run_session(tmp_path, rid)
    assert exc.value.error_type == "checkout_missing"


def test_run_session_refuses_checkout_missing_naming_implement(tmp_path):
    rid = mint()
    session_file = tmp_path / "s.jsonl"
    session_file.write_text("{}\n", encoding="utf-8")
    missing = tmp_path / "removed-checkout"
    _write_record(
        tmp_path,
        rid,
        _entry("s.jsonl", session_file=session_file, cwd=missing, at="2026-06-01T01:00:00.000Z"),
    )
    with pytest.raises(UserFacingCliError) as exc:
        session_resume.resolve_run_session(tmp_path, rid)
    assert exc.value.error_type == "checkout_missing"
    message = str(exc.value)
    assert str(missing) in message
    assert "perk implement <PLAN>" in message and "never creates, restores, or rebinds" in message


def test_run_session_happy_path_is_silent_for_a_single_entry(tmp_path, capsys):
    rid = mint()
    entry = _live_entry(tmp_path, "only", "2026-06-01T01:00:00.000Z")
    _write_record(tmp_path, rid, entry)
    target = session_resume.resolve_run_session(tmp_path, rid)
    assert target == session_resume.RunSessionTarget(
        checkout=Path(entry.cwd), session_file=Path(entry.session_file), pi_session_id="only.jsonl"
    )
    assert capsys.readouterr().err == ""


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
    assert spec.session_file is None
    assert spec.checkout == checkout and spec.main_root == git_repo
    assert spec.agent_dir.resolution is not None and spec.agent_dir.resolution.source == "env"


def test_prepare_with_session_file_pins_pi_session_with_no_approve(tmp_path):
    session_file = tmp_path / "s.jsonl"
    spec = session_resume.prepare_session_resume(
        main_root=tmp_path, checkout=tmp_path, session_file=session_file
    )
    assert spec.argv == ("pi", "--session", str(session_file))
    assert "--approve" not in spec.argv
    assert spec.session_file == session_file


def test_prepare_run_arm_honors_the_pi_agent_dir_config_arm(
    git_repo, monkeypatch, launch_exec_recorder
):
    # Decision 10: "offline" is not config-free — the run arm resolves the agent dir through the
    # SAME precedence as the picker (the main checkout's committed `[pi] agent_dir`).
    monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
    (git_repo / ".perk").mkdir(exist_ok=True)
    (git_repo / ".perk/config.toml").write_text(
        '[pi]\nagent_dir = "committed-agent"\n', encoding="utf-8"
    )
    agent_dir = git_repo / "committed-agent"
    agent_dir.mkdir()
    session_file = git_repo / "s.jsonl"
    session_file.touch()
    spec = session_resume.prepare_session_resume(
        main_root=git_repo, checkout=git_repo, session_file=session_file
    )
    assert spec.agent_dir.resolution is not None
    assert spec.agent_dir.resolution.source == "config"
    session_resume.exec_session_resume(spec)
    env = launch_exec_recorder.calls[0][2]
    assert env["PI_CODING_AGENT_DIR"] == str(agent_dir)


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

    monkeypatch.setattr(pi_exec, "_resolve_pi_executable", _missing)
    with pytest.raises(UserFacingCliError) as exc:
        session_resume.exec_session_resume(_spec(tmp_path, tmp_path))
    assert exc.value.error_type == "pi_cli_missing"
    assert launch_exec_recorder.chdirs == [] and launch_exec_recorder.calls == []


def test_exec_oserror_is_launch_failed(tmp_path, monkeypatch, launch_exec_recorder):
    def _boom(program, argv, env):
        raise OSError("exec denied")

    monkeypatch.setattr(pi_exec.os, "execvpe", _boom)
    with pytest.raises(UserFacingCliError) as exc:
        session_resume.exec_session_resume(_spec(tmp_path, tmp_path))
    assert exc.value.error_type == "launch_failed"
    assert f"could not launch pi in {tmp_path}" in str(exc.value)


# --- emit_session_resume_preview: the dry-run report + preview/exec parity ----------------


_PAYLOAD_KEYS = [
    "success",
    "checkout",
    "session_file",
    "agent_dir",
    "agent_dir_source",
    "argv",
    "dry_run",
]


def test_preview_renders_four_lines_and_the_ordered_payload(tmp_path, capsys, launch_exec_recorder):
    spec = _spec(tmp_path, tmp_path)
    session_resume.emit_session_resume_preview(spec)
    captured = capsys.readouterr()
    err_lines = captured.err.splitlines()
    assert len(err_lines) == 4
    assert "resume --dry-run (session picker — resolve only, no launch)" in err_lines[0]
    assert err_lines[1] == f"  checkout: {tmp_path}"
    assert err_lines[2] == f"  agent dir: {launch_exec_recorder.agent_dir} (env)"
    assert err_lines[3] == "  command:  pi --resume"
    payload = json.loads(captured.out)
    assert list(payload) == _PAYLOAD_KEYS
    assert payload == {
        "success": True,
        "checkout": str(tmp_path),
        "session_file": None,
        "agent_dir": str(launch_exec_recorder.agent_dir),
        "agent_dir_source": "env",
        "argv": ["pi", "--resume"],
        "dry_run": True,
    }
    # Parity: the previewed argv IS the exec'd argv for the same spec.
    session_resume.exec_session_resume(spec)
    assert payload["argv"] == list(spec.argv) == list(launch_exec_recorder.calls[0][1])


def test_preview_run_arm_renders_five_lines_and_the_same_key_order(
    tmp_path, capsys, launch_exec_recorder
):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    session_file = tmp_path / "s.jsonl"
    spec = session_resume.prepare_session_resume(
        main_root=tmp_path, checkout=checkout, session_file=session_file
    )
    session_resume.emit_session_resume_preview(spec)
    captured = capsys.readouterr()
    err_lines = captured.err.splitlines()
    assert len(err_lines) == 5
    assert "resume --dry-run (recorded session — resolve only, no launch)" in err_lines[0]
    assert err_lines[1] == f"  checkout: {checkout}"
    assert err_lines[2] == f"  session:  {session_file}"
    assert err_lines[3] == f"  agent dir: {launch_exec_recorder.agent_dir} (env)"
    assert err_lines[4] == f"  command:  pi --session {session_file}"
    payload = json.loads(captured.out)
    assert list(payload) == _PAYLOAD_KEYS
    assert payload["session_file"] == str(session_file)
    assert payload["checkout"] == str(checkout)
    assert payload["argv"] == ["pi", "--session", str(session_file)]
    # Exec parity: the same spec chdirs into the recorded cwd and execs the previewed argv
    # with the inherited run id dropped.
    session_resume.exec_session_resume(spec)
    _program, argv, env = launch_exec_recorder.calls[0]
    assert payload["argv"] == list(spec.argv) == list(argv)
    assert launch_exec_recorder.chdirs == [checkout]
    assert "PERK_RUN_ID" not in env


def test_preview_unresolved_agent_dir(tmp_path, capsys):
    spec = session_resume.SessionResumeLaunch(
        main_root=tmp_path,
        checkout=tmp_path,
        argv=("pi", "--resume"),
        agent_dir=pi_exec.LaunchAgentDir(resolution=None, injected=None),
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
        agent_dir=pi_exec.LaunchAgentDir(
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


def _imported_modules(source: str) -> set[str]:
    """Every module name an `import`/`from … import …` statement binds, at ANY nesting depth —
    function-local imports are the documented tiering mechanism, so a textual top-level scan
    would miss exactly the regression shape that matters."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
            # `from perk.run import launch` binds a submodule: record the dotted spelling too.
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def test_exec_seam_imports_neither_launch_nor_the_cli():
    """`pi_exec` sits on the bare-`perk` import tier (python-cli-guidelines §8.3): it must never
    import the launch facade (which would drag the whole orchestrator — github, backends,
    convergence — under bare `perk`) and its only `perk.cli` import is the typed-error module.
    AST-based, so an inline (function-local) import is caught the same as a module-level one."""
    imported = _imported_modules(Path(pi_exec.__file__).read_text(encoding="utf-8"))

    def under(package: str) -> set[str]:
        return {m for m in imported if m == package or m.startswith(package + ".")}

    assert under("perk.run.launch") == set()
    assert under("perk.cli") == {"perk.cli.ensure", "perk.cli.ensure.UserFacingCliError"}


def test_import_scan_sees_function_local_imports():
    # The guard's own vacuity check: a nested import is reported exactly like a top-level one.
    source = "def f():\n    from perk.cli.context import require_repo\n    import perk.run.launch\n"
    imported = _imported_modules(source)
    assert "perk.cli.context" in imported
    assert "perk.run.launch" in imported
