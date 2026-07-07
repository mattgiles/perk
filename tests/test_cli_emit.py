"""The shared result-envelope helpers (`perk.cli.emit`): failure path + success dispatch.

Driven through scratch `@click.command`s + `CliRunner` (Click >= 8.2 separates stdout/stderr).
The JSON assertions compare raw strings — the key order is part of the envelope contract.
"""

import click
from click.testing import CliRunner

from perk.cli.emit import emit, fail


def _fail_cmd(**fail_kwargs):
    @click.command()
    def cmd() -> None:
        ctx = click.get_current_context()
        fail(ctx, **fail_kwargs)

    return cmd


def test_fail_json_default_exit_1():
    result = CliRunner().invoke(_fail_cmd(as_json=True, error_type="boom", message="it broke"), [])
    assert result.exit_code == 1
    assert (
        result.stdout.strip() == '{"success": false, "error_type": "boom", "message": "it broke"}'
    )
    assert result.stderr == ""


def test_fail_json_not_a_repo_exit_2():
    result = CliRunner().invoke(
        _fail_cmd(as_json=True, error_type="not_a_repo", message="not inside a git repository"), []
    )
    assert result.exit_code == 2
    expected = (
        '{"success": false, "error_type": "not_a_repo", "message": "not inside a git repository"}'
    )
    assert result.stdout.strip() == expected


def test_fail_json_extra_merges_after_base_keys():
    result = CliRunner().invoke(
        _fail_cmd(as_json=True, error_type="boom", message="it broke", extra={"dry_run": False}),
        [],
    )
    assert result.exit_code == 1
    assert (
        result.stdout.strip()
        == '{"success": false, "error_type": "boom", "message": "it broke", "dry_run": false}'
    )


def test_fail_human_arm():
    result = CliRunner().invoke(_fail_cmd(as_json=False, error_type="boom", message="it broke"), [])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Error: " in result.stderr
    assert "it broke" in result.stderr


def test_fail_human_not_a_repo_exit_2():
    result = CliRunner().invoke(
        _fail_cmd(as_json=False, error_type="not_a_repo", message="nope"), []
    )
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "nope" in result.stderr


def test_emit_json_skips_render():
    calls: list[str] = []

    @click.command()
    def cmd() -> None:
        emit(as_json=True, payload={"success": True, "n": 1}, render=lambda: calls.append("x"))

    result = CliRunner().invoke(cmd, [])
    assert result.exit_code == 0
    assert result.stdout.strip() == '{"success": true, "n": 1}'
    assert calls == []


def test_emit_human_invokes_render_once():
    calls: list[str] = []

    @click.command()
    def cmd() -> None:
        emit(as_json=False, payload={"success": True}, render=lambda: calls.append("x"))

    result = CliRunner().invoke(cmd, [])
    assert result.exit_code == 0
    assert result.stdout == ""
    assert calls == ["x"]
