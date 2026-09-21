"""Bare `perk` — the plain-session door (contracts.md §8.72).

Driven through the registered `cli` object (CliRunner) with an injected `PerkContext.for_test`
and the shared `launch_exec_recorder` (stubs `_resolve_pi_executable`, `os.chdir`, `os.execvpe`);
the TTY seam swaps the door module's `sys` (CliRunner replaces `sys.stdin`, so patching
`sys.stdin.isatty` alone would not reach it). These tests prove what the ROOT DISPATCH
contributes — checkout, argv, `run_id=None`, ordering — not the shared executor's environment
composition (`tests/test_launch.py` pins `PERK_CLI_VERSION`, `PI_FFF_MODE`, and the
inherited-`PERK_RUN_ID` removal).
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from perk.cli import plain_session
from perk.cli.cli import cli
from perk.cli.context import PerkContext
from perk.cli.ensure import UserFacingCliError
from perk.run import launch
from perk.state import cache
from perk.substrate import git
from perk.substrate.config import Config


def _fake_sys(*, stdin_tty: bool, stdout_tty: bool) -> type:
    class _Stream:
        def __init__(self, tty: bool) -> None:
            self._tty = tty

        def isatty(self) -> bool:
            return self._tty

    class _Sys:
        stdin = _Stream(stdin_tty)
        stdout = _Stream(stdout_tty)

    return _Sys


def _tty(monkeypatch, *, stdin: bool = True, stdout: bool = True) -> None:
    monkeypatch.setattr(plain_session, "sys", _fake_sys(stdin_tty=stdin, stdout_tty=stdout))


def _invoke(root: Path, args: list[str] | None = None, *, cwd: Path | None = None):
    checkout = cwd if cwd is not None else root
    ctx = PerkContext.for_test(
        cwd=checkout, repo_root=checkout, config=Config(worktree_root=root / ".worktrees")
    )
    return CliRunner().invoke(cli, args or [], obj=ctx)


def _write_main_config(root: Path, body: str) -> None:
    """The `git_repo` template carries no `.perk/`; write the MAIN checkout's config."""
    (root / ".perk").mkdir(exist_ok=True)
    (root / ".perk" / "config.toml").write_text(body, encoding="utf-8")


def _assert_plain_exec_in(recorder, checkout: Path) -> None:
    assert recorder.chdirs == [checkout]
    assert len(recorder.calls) == 1
    program, argv, env = recorder.calls[0]
    assert program == recorder.pi_path
    assert argv == ("pi",)  # literally `pi` — no `--approve`, no stage flags
    assert "PERK_RUN_ID" not in env  # the dispatch passed run_id=None


def _assert_nothing_written(root: Path) -> None:
    assert not cache.plan_ref_path(root).exists()
    workflow = root / ".perk" / "workflow"
    assert not workflow.exists() or not any(workflow.rglob("handoff*"))


def _assert_untouched(recorder) -> None:
    assert recorder.calls == [] and recorder.chdirs == []


# --- _require_terminal: the typed code ------------------------------------------------------


def test_require_terminal_passes_on_both_ttys(monkeypatch):
    _tty(monkeypatch)
    plain_session._require_terminal()  # must not raise


@pytest.mark.parametrize(("stdin", "stdout"), [(False, True), (True, False), (False, False)])
def test_require_terminal_refuses_not_a_tty(monkeypatch, stdin, stdout):
    _tty(monkeypatch, stdin=stdin, stdout=stdout)
    with pytest.raises(UserFacingCliError) as exc:
        plain_session._require_terminal()
    assert exc.value.error_type == "not_a_tty"
    assert "perk --help" in str(exc.value)


# --- the bare exec ------------------------------------------------------------------------------


def test_bare_perk_execs_plain_pi_in_the_invocation_root(
    git_repo, monkeypatch, launch_exec_recorder
):
    _tty(monkeypatch)
    monkeypatch.setenv("PERK_RUN_ID", "01OPERATOR")
    result = _invoke(git_repo)
    assert result.exit_code == 0, result.output
    _assert_plain_exec_in(launch_exec_recorder, git_repo)
    # Exactly the one announce line: the version surfaces are suppressed under CliRunner's
    # non-TTY stderr, and a plain session prints no launch banner.
    assert result.stderr == f"opening a plain Pi session in {git_repo}: pi\n"
    assert result.stdout == ""
    assert "skills \u00b7" not in result.stderr
    _assert_nothing_written(git_repo)


def test_lone_separator_is_the_bare_invocation(git_repo, monkeypatch, launch_exec_recorder):
    _tty(monkeypatch)
    result = _invoke(git_repo, ["--"])
    assert result.exit_code == 0, result.output
    _assert_plain_exec_in(launch_exec_recorder, git_repo)
    assert f"opening a plain Pi session in {git_repo}: pi" in result.stderr


def test_linked_worktree_opens_itself_with_the_main_checkouts_agent_dir(
    git_repo, monkeypatch, launch_exec_recorder
):
    # Two roots: config anchors to the MAIN checkout; the session opens at the invocation root.
    _tty(monkeypatch)
    monkeypatch.delenv("PI_CODING_AGENT_DIR")  # exercise the config arm
    wt = git_repo / ".worktrees" / "plan-42"
    git.worktree_add(git_repo, wt, branch="plan-42", create_branch=True)
    _write_main_config(git_repo, '[pi]\nagent_dir = ".pi/agent"\n')
    (git_repo / ".pi" / "agent").mkdir(parents=True)
    result = _invoke(git_repo, cwd=wt)
    assert result.exit_code == 0, result.output
    _assert_plain_exec_in(launch_exec_recorder, wt)
    _program, _argv, env = launch_exec_recorder.calls[0]
    assert env["PI_CODING_AGENT_DIR"] == str(git_repo / ".pi" / "agent")
    assert f"opening a plain Pi session in {wt}: pi" in result.stderr


# --- the refusal ladder --------------------------------------------------------------------------


def test_non_tty_refuses_before_any_config_read_or_agent_dir_resolution(
    git_repo, monkeypatch, launch_exec_recorder
):
    # The default CliRunner is non-TTY. The raising fakes prove NO main-root probe and NO
    # agent-dir resolution (which reads the main checkout's config) happen before the refusal.
    def _no_main_root(root):
        raise AssertionError("the main root must not resolve before the TTY check")

    def _no_agent_dir(root):
        raise AssertionError("the agent dir must not resolve before the TTY check")

    monkeypatch.setattr(plain_session, "main_repo_root", _no_main_root)
    monkeypatch.setattr(launch, "resolve_launch_agent_dir", _no_agent_dir)
    result = _invoke(git_repo)
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Error:" in result.stderr and "perk --help" in result.stderr
    assert "not_a_tty" not in result.stderr  # the human surface never renders the code
    _assert_untouched(launch_exec_recorder)


def test_outside_a_repo_exits_2_with_the_pi_hint():
    # No `launch_exec_recorder` here: it stubs `os.chdir`, which `isolated_filesystem` needs.
    runner = CliRunner()
    with runner.isolated_filesystem():  # no git init; the default runner is non-TTY
        result = runner.invoke(cli, [])
    assert result.exit_code == 2  # `not_a_repo` wins over `not_a_tty`
    assert "Not a git repository" in result.stderr
    assert "run `pi` directly" in result.stderr
    assert "perk --help" in result.stderr


def test_agent_dir_invalid_refuses_before_the_announce(git_repo, monkeypatch, launch_exec_recorder):
    _tty(monkeypatch)
    monkeypatch.delenv("PI_CODING_AGENT_DIR")
    _write_main_config(git_repo, '[pi]\nagent_dir = "not-a-dir"\n')
    (git_repo / "not-a-dir").write_text("regular file\n", encoding="utf-8")
    result = _invoke(git_repo)
    assert result.exit_code == 1
    assert "is not a directory" in result.stderr
    assert "opening a plain Pi session" not in result.stderr
    _assert_untouched(launch_exec_recorder)


# --- the unchanged root surfaces ---------------------------------------------------------------


def test_root_help_still_renders_sections_and_describes_the_bare_form(launch_exec_recorder):
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0, result.output
    assert "Stage Launchers" in result.output
    assert "Command Groups:" in result.output
    assert "Setup & Health:" in result.output
    assert "plain Pi session" in result.output  # the one intended help change
    _assert_untouched(launch_exec_recorder)


def test_version_still_short_circuits(launch_exec_recorder):
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0, result.output
    assert result.output.startswith("perk ")
    _assert_untouched(launch_exec_recorder)


def test_unknown_command_is_still_a_usage_error(git_repo, monkeypatch, launch_exec_recorder):
    _tty(monkeypatch)  # even on a TTY: resolution fails before the callback's bare arm
    result = _invoke(git_repo, ["definitely-not-a-command"])
    assert result.exit_code == 2
    assert "No such command" in result.output
    _assert_untouched(launch_exec_recorder)
