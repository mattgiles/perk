"""The runtime CLI-vs-repo version warning (`perk/cli/version_check.py`).

Two layers:
- **pure core**: the suppression-matrix cases call `version_mismatch_warning` directly with
  explicit `argv`/`subcommand`/`env`/`interactive` — no monkeypatched globals;
- **CliRunner integration**: the root-callback hook, with the wrapper's gates forced open
  (`_interactive` monkeypatched — CliRunner's captured stderr is never a TTY).
"""

import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from perk import __version__
from perk.cli import version_check
from perk.cli.cli import cli
from perk.cli.version_check import version_mismatch_warning
from perk.substrate import paths

_STALE = "0.0.1"


def _call(cwd: Path, *, argv=(), subcommand=None, env=None, interactive=True):
    return version_mismatch_warning(
        argv=list(argv),
        subcommand=subcommand,
        cwd=cwd,
        env=env or {},
        interactive=interactive,
    )


def _write_pin(repo: Path, version: str) -> Path:
    pin = paths.required_version_file(repo)
    pin.parent.mkdir(parents=True, exist_ok=True)
    pin.write_text(f"{version}\n", encoding="utf-8")
    return pin


# --- pure core: the suppression matrix -------------------------------------------------------


def test_outside_a_git_repo_is_silent(tmp_path):
    assert _call(tmp_path) is None


def test_missing_pin_is_silent(git_repo):
    assert _call(git_repo) is None


def test_matching_pin_is_silent(git_repo):
    _write_pin(git_repo, __version__)
    assert _call(git_repo) is None


def test_mismatch_warns_with_both_versions_and_the_optout(git_repo):
    _write_pin(git_repo, _STALE)
    message = _call(git_repo)
    assert message is not None
    assert __version__ in message and _STALE in message
    assert "PERK_SKIP_VERSION_CHECK" in message


@pytest.mark.parametrize("value", ["1", "yes-please"])
def test_skip_env_var_suppresses_any_nonempty_value(git_repo, value):
    _write_pin(git_repo, _STALE)
    assert _call(git_repo, env={"PERK_SKIP_VERSION_CHECK": value}) is None


def test_ci_env_suppresses(git_repo):
    _write_pin(git_repo, _STALE)
    assert _call(git_repo, env={"CI": "true"}) is None


def test_json_flag_suppresses(git_repo):
    _write_pin(git_repo, _STALE)
    assert _call(git_repo, argv=["doctor", "--json"]) is None


@pytest.mark.parametrize("flag", ["--help", "--version"])
def test_help_and_version_suppress(git_repo, flag):
    _write_pin(git_repo, _STALE)
    assert _call(git_repo, argv=["doctor", flag]) is None


def test_run_worker_subcommand_suppresses(git_repo):
    _write_pin(git_repo, _STALE)
    assert _call(git_repo, subcommand="run-worker") is None


def test_non_interactive_suppresses(git_repo):
    _write_pin(git_repo, _STALE)
    assert _call(git_repo, interactive=False) is None


def test_unreadable_pin_reports_softly(git_repo, monkeypatch):
    # `is_file()` passed but the read failed (permissions/race): reported, never swallowed —
    # and still non-fatal. The deterministic form (no chmod games).
    def boom(root):
        raise OSError("permission denied")

    monkeypatch.setattr(version_check, "read_version_pin", boom)
    message = _call(git_repo)
    assert message is not None
    assert "unreadable" in message and "perk doctor" in message


# --- CliRunner integration (the root-callback hook) -------------------------------------------


def _force_gates_open(monkeypatch, repo):
    monkeypatch.chdir(repo)
    monkeypatch.setattr(version_check, "_interactive", lambda: True)
    monkeypatch.setattr(sys, "argv", ["perk", "registry", "show"])
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("PERK_SKIP_VERSION_CHECK", raising=False)


def test_cli_emits_warning_on_stale_pin(git_repo, monkeypatch):
    _write_pin(git_repo, _STALE)
    _force_gates_open(monkeypatch, git_repo)
    result = CliRunner().invoke(cli, ["registry", "show"])
    assert result.exit_code == 0
    assert "\u26a0" in result.stderr and _STALE in result.stderr and __version__ in result.stderr


def test_cli_stays_silent_on_matching_pin(git_repo, monkeypatch):
    # Same forced-open gates: proves the emission is mismatch-gated, not gate-gated.
    _write_pin(git_repo, __version__)
    _force_gates_open(monkeypatch, git_repo)
    result = CliRunner().invoke(cli, ["registry", "show"])
    assert result.exit_code == 0
    assert "\u26a0" not in result.stderr
