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
