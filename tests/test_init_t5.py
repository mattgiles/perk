import json
import subprocess

from click.testing import CliRunner

from perk import env as env_mod
from perk import github as gh_mod
from perk import init as init_mod
from perk.cli.cli import cli
from perk.init import report_to_dict, run_init


def _git_init(path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


# --- pure convergence (verify=False) -----------------------------------------


def test_convergence_writes_handoff_and_capabilities(tmp_path):
    report = run_init(tmp_path, verify=False)
    assert report.ok and report.github is None
    assert report.handoff == ".pi/workflow/post-init.md"
    assert (tmp_path / ".pi" / "workflow" / "post-init.md").is_file()
    assert "settings-wiring" in report.capabilities


def test_force_reseeds_config(tmp_path):
    run_init(tmp_path, verify=False)
    cfg = tmp_path / ".pi" / "perk.toml"
    cfg.write_text("[worktree]\nroot = 'hacked'\n", encoding="utf-8")

    report = run_init(tmp_path, verify=False, force=True, interactive=False)
    assert 'root = ".worktrees"' in cfg.read_text(encoding="utf-8")
    assert any("re-seeded" in c for c in report.changes)


def test_report_to_dict_shape(tmp_path):
    data = report_to_dict(run_init(tmp_path, verify=False))
    assert data["success"] is True
    assert set(data) >= {"success", "mode", "env", "github", "capabilities", "changes", "handoff"}


# --- skills sync orchestration (§2.7) ----------------------------------------


def test_sync_skills_runs_for_self_repo(git_repo, monkeypatch, stub_env):
    # The `skills` CLI is the single delivery path in both trees: self-repo now syncs too.
    (git_repo / "pyproject.toml").write_text("[tool.perk]\nself = true\n", encoding="utf-8")
    called = []
    monkeypatch.setattr(init_mod, "_sync_skills", lambda root, changes, **kw: called.append(root))
    run_init(git_repo, verify=True)
    assert called == [git_repo]


def test_sync_skills_runs_for_consumer_under_verify(git_repo, monkeypatch, stub_env):
    called = []
    monkeypatch.setattr(init_mod, "_sync_skills", lambda root, changes, **kw: called.append(root))
    run_init(git_repo, verify=True)
    assert called == [git_repo]


def test_sync_skills_not_run_without_verify(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(init_mod, "_sync_skills", lambda root, changes, **kw: called.append(root))
    run_init(tmp_path, verify=False)  # unit-test path: no external shells
    assert called == []


def _install_perk_skills(root):
    """Plant every PERK_SKILLS SKILL.md under .agents/skills/ (a delivered substrate)."""
    for name in init_mod.PERK_SKILLS:
        path = root / ".agents" / "skills" / name / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# skill\n", encoding="utf-8")


class _Proc:
    def __init__(self, returncode=0, stderr=""):
        self.returncode = returncode
        self.stderr = stderr


def test_sync_skills_fails_when_cli_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(init_mod.shutil, "which", lambda name: None)
    error = init_mod._sync_skills(tmp_path, [])
    assert error is not None and "not on PATH" in error


def test_sync_skills_reports_only_on_link_change(tmp_path, monkeypatch):
    monkeypatch.setattr(init_mod.shutil, "which", lambda name: "/usr/bin/skills")
    monkeypatch.setattr(init_mod.subprocess, "run", lambda *a, **k: _Proc())
    _install_perk_skills(tmp_path)
    # Link set changes across the sync -> one change entry.
    states = iter([{}, {"perk-plan": "/cache/perk-plan"}])
    monkeypatch.setattr(init_mod, "_skill_link_state", lambda root: next(states))
    changes: list[str] = []
    assert init_mod._sync_skills(tmp_path, changes) is None
    assert changes == [".agents/skills/: synchronized via skills update --sync"]

    # Link set unchanged -> no change entry (idempotent reporting).
    monkeypatch.setattr(init_mod, "_skill_link_state", lambda root: {"perk-plan": "/cache/x"})
    changes2: list[str] = []
    assert init_mod._sync_skills(tmp_path, changes2) is None
    assert changes2 == []


def test_sync_skills_fails_on_nonzero_skills_init(tmp_path, monkeypatch):
    monkeypatch.setattr(init_mod.shutil, "which", lambda name: "/usr/bin/skills")
    monkeypatch.setattr(
        init_mod.subprocess,
        "run",
        lambda args, **k: (
            _Proc(1, "managed runtime paths already contain tracked Git content")
            if args[:2] == ["skills", "init"]
            else _Proc()
        ),
    )
    error = init_mod._sync_skills(tmp_path, [])
    assert error is not None
    assert "skills init --cache=local" in error and "tracked Git content" in error


def test_sync_skills_fails_on_nonzero_skills_update(tmp_path, monkeypatch):
    monkeypatch.setattr(init_mod.shutil, "which", lambda name: "/usr/bin/skills")
    monkeypatch.setattr(
        init_mod.subprocess,
        "run",
        lambda args, **k: (
            _Proc(2, "manifest not found") if args[:2] == ["skills", "update"] else _Proc()
        ),
    )
    error = init_mod._sync_skills(tmp_path, [])
    assert error is not None
    assert "skills update --sync" in error and "manifest not found" in error


def test_sync_skills_fails_on_subprocess_error(tmp_path, monkeypatch):
    # No longer silent (#289): OSError/timeout are failure messages.
    monkeypatch.setattr(init_mod.shutil, "which", lambda name: "/usr/bin/skills")

    def boom(*a, **k):
        raise OSError("skills exploded")

    monkeypatch.setattr(init_mod.subprocess, "run", boom)
    error = init_mod._sync_skills(tmp_path, [])
    assert error is not None and "skills exploded" in error

    def slow(*a, **k):
        raise subprocess.TimeoutExpired(cmd="skills", timeout=30)

    monkeypatch.setattr(init_mod.subprocess, "run", slow)
    error = init_mod._sync_skills(tmp_path, [])
    assert error is not None and "timed out" in error


def test_sync_skills_fails_when_delivery_missing(tmp_path, monkeypatch):
    # Post-sync presence verification: a sync that links nothing (outdated CLI) is a failure.
    monkeypatch.setattr(init_mod.shutil, "which", lambda name: "/usr/bin/skills")
    monkeypatch.setattr(init_mod.subprocess, "run", lambda *a, **k: _Proc())
    error = init_mod._sync_skills(tmp_path, [])
    assert error is not None
    assert "did not deliver" in error and "perk-plan" in error


# --- env gates (verify=True) -------------------------------------------------


def test_tracked_skills_conflict_short_circuits_init(git_repo, stub_env):
    # #289: committed content under a skills-CLI managed path fails init BEFORE convergence.
    skill = git_repo / ".claude" / "skills" / "x" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# x\n", encoding="utf-8")
    subprocess.run(["git", "add", ".claude"], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-qm", "skills"], cwd=git_repo, check=True, capture_output=True
    )
    report = run_init(git_repo, verify=True)
    assert not report.ok and report.error_type == "skills_conflict" and report.exit_code == 2
    assert ".claude/skills" in (report.message or "")
    assert report.changes == []  # nothing converged
    assert not (git_repo / ".pi" / "settings.json").exists()


def test_conflict_probe_giterror_degrades_to_no_short_circuit(git_repo, monkeypatch, stub_env):
    # A failed probe never blocks (and never silently passes — the sync step owns the failure).
    def boom(root):
        raise init_mod.git.GitError("probe failed")

    monkeypatch.setattr(init_mod, "skills_conflict_paths", boom)
    report = run_init(git_repo, verify=True)
    assert report.ok  # stubbed _sync_skills succeeds


def test_sync_failure_is_fatal_and_preserves_changes(git_repo, monkeypatch, stub_env):
    monkeypatch.setattr(init_mod, "_sync_skills", lambda root, changes, **kw: "sync exploded")
    report = run_init(git_repo, verify=True)
    assert not report.ok and report.error_type == "skills_sync_failed" and report.exit_code == 2
    assert report.message == "sync exploded"
    assert report.changes  # convergence already happened and stays recorded
    assert report.github is None and report.handoff is None


def test_not_a_repo_is_exit_2(tmp_path):
    report = run_init(tmp_path, verify=True)  # tmp_path is not a git repo
    assert not report.ok and report.error_type == "not_a_repo" and report.exit_code == 2


def test_missing_tool_is_exit_2(git_repo, monkeypatch):
    monkeypatch.setattr(env_mod, "required_tools_ok", lambda checks: False)
    report = run_init(git_repo, verify=True)
    assert not report.ok and report.error_type == "missing_tool" and report.exit_code == 2


def test_github_error_is_non_fatal(git_repo, monkeypatch):
    # A flaky/slow/broken gh (GitHubError) must not crash init (D3 — GitHub non-fatal).
    monkeypatch.setattr(env_mod, "required_tools_ok", lambda checks: True)
    monkeypatch.setattr(init_mod, "_sync_skills", lambda root, changes, **kw: None)  # no network

    def boom():
        raise gh_mod.GitHubError("gh timed out")

    monkeypatch.setattr(gh_mod, "check_auth", boom)
    report = run_init(git_repo, verify=True)
    assert report.ok and report.github is not None
    assert report.github.auth.ok is False and "timed out" in (report.github.auth.error or "")


# --- CLI surface -------------------------------------------------------------


def test_cli_json_success(tmp_path, stub_env):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as d:
        _git_init(d)
        result = runner.invoke(cli, ["init", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["success"] is True and payload["mode"] == "consumer"
        assert payload["github"]["auth"]["ok"] is False  # stubbed unauthed (non-fatal)
        assert payload["handoff"] == ".pi/workflow/post-init.md"


def test_cli_json_not_a_repo(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["init", "--json"])
        assert result.exit_code == 2
        payload = json.loads(result.stdout)
        assert payload["success"] is False and payload["error_type"] == "not_a_repo"


def test_cli_idempotent_second_run(tmp_path, stub_env):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as d:
        _git_init(d)
        assert runner.invoke(cli, ["init"]).exit_code == 0
        result = runner.invoke(cli, ["init", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.stdout)["changes"] == []
