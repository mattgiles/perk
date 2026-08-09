import shlex
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from perk.cli.cli import cli
from perk.cli.commands.worktree.checkout_cmd import _checkout_impl
from perk.cli.context import PerkContext
from perk.cli.ensure import UserFacingCliError
from perk.substrate import git
from perk.substrate.config import Config


def _add_worktree(repo: Path, name: str) -> Path:
    path = repo / ".worktrees" / name
    git.worktree_add(repo, path, branch=name, create_branch=True)
    return path


def _ctx(repo: Path) -> PerkContext:
    return PerkContext.for_test(
        cwd=repo, repo_root=repo, config=Config(worktree_root=repo / ".worktrees")
    )


# --- bare mode --------------------------------------------------------------


def test_bare_prints_path_on_stdout_and_hint_on_stderr(git_repo, capsys):
    wt = _add_worktree(git_repo, "feature")
    _checkout_impl(
        repo_root=git_repo, worktree_root=git_repo / ".worktrees", name="feature", script=False
    )
    captured = capsys.readouterr()
    # stdout is exactly the target path + newline, nothing else.
    assert Path(captured.out.strip()).resolve() == wt.resolve()
    assert captured.out == captured.out.strip() + "\n"


def test_bare_stderr_hint_names_the_source_gesture(git_repo, capsys):
    _add_worktree(git_repo, "feature")
    _checkout_impl(
        repo_root=git_repo, worktree_root=git_repo / ".worktrees", name="feature", script=False
    )
    captured = capsys.readouterr()
    assert "source <(perk wt co feature --script)" in captured.err


def test_bare_hint_shell_quotes_a_metacharacter_name(git_repo, capsys):
    # A loose dir may carry whitespace; the pasted hint must keep the NAME one shell argument.
    (git_repo / ".worktrees" / "my wt").mkdir(parents=True)
    _checkout_impl(
        repo_root=git_repo, worktree_root=git_repo / ".worktrees", name="my wt", script=False
    )
    hint = capsys.readouterr().err.strip()
    inner = hint.removeprefix("to switch: source <(").removesuffix(")")
    assert shlex.split(inner) == ["perk", "wt", "co", "my wt", "--script"]


def test_bare_hint_quotes_the_hash_prefixed_form(git_repo, capsys):
    # Unquoted, `#7` would start a shell comment when the hint is pasted.
    _add_worktree(git_repo, "plan-7")
    _checkout_impl(
        repo_root=git_repo, worktree_root=git_repo / ".worktrees", name="#7", script=False
    )
    hint = capsys.readouterr().err.strip()
    assert "source <(perk wt co '#7' --script)" in hint
    inner = hint.removeprefix("to switch: source <(").removesuffix(")")
    assert shlex.split(inner) == ["perk", "wt", "co", "#7", "--script"]


# --- --script mode ----------------------------------------------------------


def test_script_emits_cd_and_echo_on_stdout(git_repo, capsys):
    wt = _add_worktree(git_repo, "feature")
    _checkout_impl(
        repo_root=git_repo, worktree_root=git_repo / ".worktrees", name="feature", script=True
    )
    captured = capsys.readouterr()
    assert f"cd '{wt}'" in captured.out
    assert "✓ checked out feature [feature]" in captured.out
    assert captured.err == ""


def test_script_omits_branch_suffix_for_unregistered_dir(git_repo, capsys):
    # An unregistered dir under the worktree root is still checkout-able (it's just a cd).
    loose = git_repo / ".worktrees" / "loose"
    loose.mkdir(parents=True)
    _checkout_impl(
        repo_root=git_repo, worktree_root=git_repo / ".worktrees", name="loose", script=True
    )
    captured = capsys.readouterr()
    assert f"cd '{loose}'" in captured.out
    assert "echo '✓ checked out loose'" in captured.out
    assert "[" not in captured.out


# --- target resolution ------------------------------------------------------


@pytest.mark.parametrize("name", ["7", "#7"])
def test_plan_number_sugar_resolves_plan_worktree(git_repo, capsys, name):
    wt = _add_worktree(git_repo, "plan-7")
    _checkout_impl(
        repo_root=git_repo, worktree_root=git_repo / ".worktrees", name=name, script=False
    )
    captured = capsys.readouterr()
    assert Path(captured.out.strip()).resolve() == wt.resolve()


def test_literal_name_beats_plan_number_sugar(git_repo, capsys):
    _add_worktree(git_repo, "plan-7")
    literal = _add_worktree(git_repo, "7")
    _checkout_impl(
        repo_root=git_repo, worktree_root=git_repo / ".worktrees", name="7", script=False
    )
    captured = capsys.readouterr()
    assert Path(captured.out.strip()).resolve() == literal.resolve()


def test_root_keyword_resolves_main_checkout(git_repo, capsys):
    wt = _add_worktree(git_repo, "feature")
    # Resolve from inside the worktree: `root` still points back at the main checkout.
    _checkout_impl(repo_root=wt, worktree_root=git_repo / ".worktrees", name="root", script=False)
    captured = capsys.readouterr()
    assert Path(captured.out.strip()).resolve() == git_repo.resolve()


@pytest.mark.parametrize("name", ["../outside", "/tmp", "..", "."])
def test_traversal_and_absolute_names_are_rejected(git_repo, name):
    with pytest.raises(UserFacingCliError) as exc:
        _checkout_impl(
            repo_root=git_repo, worktree_root=git_repo / ".worktrees", name=name, script=False
        )
    assert "Invalid worktree name" in exc.value.message


def test_regular_file_target_is_rejected(git_repo):
    # A regular file would only make the emitted `cd` fail — resolution refuses it up front.
    (git_repo / ".worktrees").mkdir()
    (git_repo / ".worktrees" / "blob").write_text("x", encoding="utf-8")
    with pytest.raises(UserFacingCliError) as exc:
        _checkout_impl(
            repo_root=git_repo, worktree_root=git_repo / ".worktrees", name="blob", script=False
        )
    assert "Worktree not found" in exc.value.message


def test_missing_target_raises_plain_error(git_repo):
    with pytest.raises(UserFacingCliError) as exc:
        _checkout_impl(
            repo_root=git_repo, worktree_root=git_repo / ".worktrees", name="nope", script=False
        )
    assert "Worktree not found" in exc.value.message
    assert str(git_repo / ".worktrees" / "nope") in exc.value.message


def test_missing_numeric_target_names_both_tried_paths(git_repo):
    with pytest.raises(UserFacingCliError) as exc:
        _checkout_impl(
            repo_root=git_repo, worktree_root=git_repo / ".worktrees", name="7", script=False
        )
    assert str(git_repo / ".worktrees" / "7") in exc.value.message
    assert f"also tried {git_repo / '.worktrees' / 'plan-7'}" in exc.value.message


# --- end-to-end through the CLI ----------------------------------------------


def test_script_missing_target_emits_return_1_stub(git_repo):
    # Through CliRunner so the Click-intercepted error path runs end-to-end: the sourced
    # stdout content returns non-zero while `Error: …` lands on stderr with exit 1.
    result = CliRunner().invoke(
        cli, ["worktree", "checkout", "nope", "--script"], obj=_ctx(git_repo)
    )
    assert result.exit_code == 1
    assert "return 1" in result.stdout
    assert "Error:" in result.stderr
    assert "Worktree not found" in result.stderr


def test_wt_co_alias_routes_end_to_end(git_repo):
    wt = _add_worktree(git_repo, "feature")
    result = CliRunner().invoke(cli, ["wt", "co", "feature"], obj=_ctx(git_repo))
    assert result.exit_code == 0
    # Click ≥8.2 separates the streams: the path is stdout, the hint is stderr.
    assert Path(result.stdout.strip()).resolve() == wt.resolve()
    assert "source <(perk wt co feature --script)" in result.stderr


# --- sourcing the emitted scripts in a real shell -----------------------------


def _bash_source(script_text: str, scratch: Path, *, then: str) -> subprocess.CompletedProcess:
    """Write ``script_text`` to a file and ``source`` it in bash, followed by ``&& {then}``."""
    script_file = scratch / "activate.sh"
    script_file.write_text(script_text, encoding="utf-8")
    return subprocess.run(
        ["bash", "-c", f"source {shlex.quote(str(script_file))} && {then}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def test_sourced_script_changes_directory_and_escapes_apostrophe(git_repo, tmp_path):
    target = git_repo / ".worktrees" / "it's here"
    target.mkdir(parents=True)
    result = CliRunner().invoke(cli, ["wt", "co", "it's here", "--script"], obj=_ctx(git_repo))
    assert result.exit_code == 0
    proc = _bash_source(result.stdout, tmp_path, then="pwd")
    assert proc.returncode == 0
    assert "✓ checked out it's here" in proc.stdout
    assert Path(proc.stdout.splitlines()[-1]).resolve() == target.resolve()


def test_sourced_error_stub_returns_nonzero_and_breaks_chain(git_repo, tmp_path):
    result = CliRunner().invoke(cli, ["wt", "co", "nope", "--script"], obj=_ctx(git_repo))
    assert result.exit_code == 1
    proc = _bash_source(result.stdout, tmp_path, then="echo unreachable")
    assert proc.returncode != 0
    assert "unreachable" not in proc.stdout


def test_sourced_script_cd_failure_returns_nonzero(git_repo, tmp_path):
    # The target vanishing between resolution and sourcing must not echo success or return 0.
    target = git_repo / ".worktrees" / "gone"
    target.mkdir(parents=True)
    result = CliRunner().invoke(cli, ["wt", "co", "gone", "--script"], obj=_ctx(git_repo))
    assert result.exit_code == 0
    target.rmdir()
    proc = _bash_source(result.stdout, tmp_path, then="echo unreachable")
    assert proc.returncode != 0
    assert "unreachable" not in proc.stdout
    assert "✓" not in proc.stdout
