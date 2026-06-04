import json

import pytest

from perk import __version__
from perk.cli.ensure import UserFacingCliError
from perk.init import run_init


def _snapshot(root):
    return {
        p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
        for p in root.rglob("*")
        if p.is_file() and ".git/" not in p.relative_to(root).as_posix()
    }


def test_init_converges_and_is_idempotent(tmp_path):
    # tmp_path has no `[tool.perk] self` marker -> consumer mode.
    # verify=False: pure convergence (no repo/tooling/GitHub shells).
    assert run_init(tmp_path, verify=False).ok

    settings = json.loads((tmp_path / ".pi" / "settings.json").read_text())
    packages = settings["packages"]
    assert f"npm:@perk/pi@{__version__}" in packages
    assert "npm:@tombell/pi-status" in packages
    assert "npm:@tombell/pi-plan" not in packages  # P2.T2a: perk owns plan mode now
    assert "npm:@juicesharp/rpiv-todo" not in packages  # P2.T12: perk owns checkpoints now
    assert "npm:pi-subagents" in packages  # P2.T6: borrowed spawned-delegation engine

    assert (tmp_path / ".pi" / "workflow" / ".gitkeep").is_file()
    # P2.T6: perk-owned agent-definitions home (committed; T7 populates it).
    assert (tmp_path / ".pi" / "agents" / ".gitkeep").is_file()
    gitignore = (tmp_path / ".gitignore").read_text()
    assert "/.pi/npm/" in gitignore
    assert "/.pi/workflow/plan-ref.json" in gitignore  # cache.plan-ref local mirror (T2b)
    assert "/.pi/workflow/plan.md" in gitignore  # cache.plan materialized body (transient, #43)
    assert "perk conventions" in (tmp_path / "AGENTS.md").read_text()

    # Idempotency: a second run changes nothing on disk.
    before = _snapshot(tmp_path)
    assert run_init(tmp_path, verify=False).ok
    after = _snapshot(tmp_path)
    assert before == after


def test_init_preserves_user_settings(tmp_path):
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    (pi_dir / "settings.json").write_text(
        json.dumps({"packages": ["npm:@me/custom"], "theme": "nightowl"}, indent=2) + "\n"
    )

    run_init(tmp_path, verify=False)

    settings = json.loads((pi_dir / "settings.json").read_text())
    assert "npm:@me/custom" in settings["packages"]  # user entry preserved
    assert settings["theme"] == "nightowl"  # unknown key preserved
    assert f"npm:@perk/pi@{__version__}" in settings["packages"]  # perk entry added


def test_init_rejects_malformed_settings(tmp_path):
    pi_dir = tmp_path / ".pi"
    pi_dir.mkdir()
    (pi_dir / "settings.json").write_text("{not json", encoding="utf-8")
    # The operation must error, not silently clobber the user's file.
    with pytest.raises(UserFacingCliError):
        run_init(tmp_path, verify=False)
    assert (pi_dir / "settings.json").read_text() == "{not json"  # untouched


def test_init_self_mode_uses_local_path(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.perk]\nself = true\n", encoding="utf-8")
    run_init(tmp_path, verify=False)
    packages = json.loads((tmp_path / ".pi" / "settings.json").read_text())["packages"]
    assert ".." in packages
    assert not any(p.startswith("npm:@perk/pi") for p in packages)
