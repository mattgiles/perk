import subprocess
from pathlib import Path

from click.testing import CliRunner

from perk import __version__
from perk.cli.cli import cli


def _git_init(path: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def test_version_format():
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"perk {__version__}"


def test_init_via_cli(tmp_path, stub_env):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as d:
        _git_init(d)
        result = runner.invoke(cli, ["init"])
        assert result.exit_code == 0
        assert (Path(d) / ".pi" / "settings.json").is_file()
        assert not (Path(d) / ".perk" / "workflow" / ".gitkeep").exists()
        assert (Path(d) / ".perk" / "workflow" / "plans").is_dir()
        assert (Path(d) / ".perk" / "workflow" / "post-init.md").is_file()


def test_init_malformed_settings_errors_cleanly(tmp_path, stub_env):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as d:
        _git_init(d)
        pi = Path(d) / ".pi"
        pi.mkdir()
        (pi / "settings.json").write_text("{not json", encoding="utf-8")
        result = runner.invoke(cli, ["init"])
        assert result.exit_code == 1  # UserFacingCliError -> styled, exit 1
        assert "not valid JSON" in result.output


def test_state_new_run_missing_handoff_file_errors_cleanly(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["state", "new-run", "--handoff", "@nope.json"])
        assert result.exit_code == 1  # clean UserFacingCliError, not a traceback
        assert "file not found" in result.output
        assert result.exception is None or isinstance(result.exception, SystemExit)


def test_state_new_run_bad_handoff_json_errors_cleanly(tmp_path):
    # A non-object payload (a JSON array here) now fails with a strict field-path message.
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["state", "new-run", "--handoff", "[1, 2]"])
        assert result.exit_code == 1
        assert "--handoff" in result.output and "dictionary" in result.output
        assert result.exception is None or isinstance(result.exception, SystemExit)


def test_state_new_run_scalar_handoff_errors_cleanly(tmp_path):
    # A scalar (a JSON number) is likewise rejected as not-an-object.
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["state", "new-run", "--handoff", "5"])
        assert result.exit_code == 1
        assert "dictionary" in result.output
