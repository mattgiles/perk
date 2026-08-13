import json
import subprocess
from typing import cast

from click.testing import CliRunner

from perk import github as gh_mod
from perk.cli.cli import cli
from perk.convergence import env as env_mod
from perk.convergence import init as init_mod
from perk.convergence.env import EnvCheck
from perk.convergence.init import report_to_dict, run_init
from perk.convergence.init import skills as _skills_mod


def _git_init(path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _lean_ci_env() -> list[EnvCheck]:
    """A lean CI host: git/gh/node present, pi absent (the GHA shape that broke main)."""
    return [
        EnvCheck("git", True, "ok", ""),
        EnvCheck("gh", True, "ok", ""),
        EnvCheck("node", True, "v22.19.0", ""),
        EnvCheck(
            "pi", False, "not found", "Install Pi: npm install -g @earendil-works/pi-coding-agent"
        ),
        EnvCheck("skills", True, "ok", ""),
    ]


# --- pure convergence (verify=False) -----------------------------------------


def test_convergence_writes_handoff_and_capabilities(tmp_path):
    report = run_init(tmp_path, verify=False)
    assert report.ok and report.github is None
    assert report.handoff == ".perk/workflow/post-init.md"
    assert (tmp_path / ".perk" / "workflow" / "post-init.md").is_file()
    assert "settings-wiring" in report.capabilities


def test_force_reseeds_config(tmp_path):
    run_init(tmp_path, verify=False)
    cfg = tmp_path / ".perk" / "config.toml"
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
    monkeypatch.setattr(init_mod, "sync_skills", lambda root, changes, **kw: called.append(root))
    run_init(git_repo, verify=True)
    assert called == [git_repo]


def test_sync_skills_runs_for_consumer_under_verify(git_repo, monkeypatch, stub_env):
    called = []
    monkeypatch.setattr(init_mod, "sync_skills", lambda root, changes, **kw: called.append(root))
    run_init(git_repo, verify=True)
    assert called == [git_repo]


def test_sync_skills_not_run_without_verify(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(init_mod, "sync_skills", lambda root, changes, **kw: called.append(root))
    run_init(tmp_path, verify=False)  # unit-test path: no external shells
    assert called == []


def _install_perk_skills(root):
    """Plant every MANAGED_SKILL_NAMES SKILL.md under .agents/skills/ (a delivered substrate)."""
    for name in init_mod.MANAGED_SKILL_NAMES:
        path = root / ".agents" / "skills" / name / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# skill\n", encoding="utf-8")


class _Proc:
    def __init__(self, returncode=0, stderr=""):
        self.returncode = returncode
        self.stderr = stderr


def test_sync_skills_fails_when_cli_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(init_mod.shutil, "which", lambda name: None)
    error = init_mod.sync_skills(tmp_path, [])
    assert error is not None and "not on PATH" in error


def test_sync_skills_reports_only_on_link_change(tmp_path, monkeypatch):
    monkeypatch.setattr(init_mod.shutil, "which", lambda name: "/usr/bin/skills")
    monkeypatch.setattr(init_mod.subprocess, "run", lambda *a, **k: _Proc())
    _install_perk_skills(tmp_path)
    # Link set changes across the sync -> one change entry.
    states = iter([{}, {"perk-plan": "/cache/perk-plan"}])
    monkeypatch.setattr(_skills_mod, "_skill_link_state", lambda root: next(states))
    changes: list[str] = []
    assert init_mod.sync_skills(tmp_path, changes) is None
    assert changes == [".agents/skills/: synchronized via skills update --sync"]

    # Link set unchanged -> no change entry (idempotent reporting).
    monkeypatch.setattr(_skills_mod, "_skill_link_state", lambda root: {"perk-plan": "/cache/x"})
    changes2: list[str] = []
    assert init_mod.sync_skills(tmp_path, changes2) is None
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
    error = init_mod.sync_skills(tmp_path, [])
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
    error = init_mod.sync_skills(tmp_path, [])
    assert error is not None
    assert "skills update --sync" in error and "manifest not found" in error


def test_sync_skills_fails_on_subprocess_error(tmp_path, monkeypatch):
    # No longer silent: OSError/timeout are failure messages.
    monkeypatch.setattr(init_mod.shutil, "which", lambda name: "/usr/bin/skills")

    def boom(*a, **k):
        raise OSError("skills exploded")

    monkeypatch.setattr(init_mod.subprocess, "run", boom)
    error = init_mod.sync_skills(tmp_path, [])
    assert error is not None and "skills exploded" in error

    def slow(*a, **k):
        raise subprocess.TimeoutExpired(cmd="skills", timeout=30)

    monkeypatch.setattr(init_mod.subprocess, "run", slow)
    error = init_mod.sync_skills(tmp_path, [])
    assert error is not None and "timed out" in error


def test_sync_skills_fails_when_delivery_missing(tmp_path, monkeypatch):
    # Post-sync presence verification: a sync that links nothing (outdated CLI) is a failure.
    monkeypatch.setattr(init_mod.shutil, "which", lambda name: "/usr/bin/skills")
    monkeypatch.setattr(init_mod.subprocess, "run", lambda *a, **k: _Proc())
    error = init_mod.sync_skills(tmp_path, [])
    assert error is not None
    assert "did not deliver" in error and "perk-plan" in error


_REPO_HINT = "If a skill under `.perk/skills/` was just added"


def test_sync_skills_repo_hint_on_command_failure(tmp_path, monkeypatch):
    # The repo-aware remediation clause is appended whenever repo_skill_names is non-empty.
    monkeypatch.setattr(init_mod.shutil, "which", lambda name: "/usr/bin/skills")
    monkeypatch.setattr(
        init_mod.subprocess,
        "run",
        lambda args, **k: (
            _Proc(2, "missing-skill: myskill") if args[:2] == ["skills", "update"] else _Proc()
        ),
    )
    error = init_mod.sync_skills(tmp_path, [], repo_skill_names=("myskill",))
    assert error is not None and _REPO_HINT in error
    # Generic message (no repo-authored skills) carries no clause.
    generic = init_mod.sync_skills(tmp_path, [])
    assert generic is not None and _REPO_HINT not in generic


def test_sync_skills_repo_hint_on_delivery_failure(tmp_path, monkeypatch):
    # A declared repo skill that the sync did not install: presence-loop fold + repo hint.
    monkeypatch.setattr(init_mod.shutil, "which", lambda name: "/usr/bin/skills")
    monkeypatch.setattr(init_mod.subprocess, "run", lambda *a, **k: _Proc())
    _install_perk_skills(tmp_path)  # every MANAGED_SKILL_NAMES present …
    error = init_mod.sync_skills(tmp_path, [], repo_skill_names=("myskill",))  # … but not myskill
    assert error is not None
    assert "did not deliver" in error and "myskill" in error and _REPO_HINT in error


# --- env gates (verify=True) -------------------------------------------------


def test_tracked_skills_conflict_short_circuits_init(git_repo, stub_env):
    # Committed content under a skills-CLI managed path fails init BEFORE convergence.
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
    assert report.ok  # stubbed sync_skills succeeds


def test_sync_failure_is_fatal_and_preserves_changes(git_repo, monkeypatch, stub_env):
    monkeypatch.setattr(init_mod, "sync_skills", lambda root, changes, **kw: "sync exploded")
    report = run_init(git_repo, verify=True)
    assert not report.ok and report.error_type == "skills_sync_failed" and report.exit_code == 2
    assert report.message == "sync exploded"
    assert report.changes  # convergence already happened and stays recorded
    assert report.github is None and report.handoff is None


def _stub_identity(monkeypatch):
    monkeypatch.setattr(
        gh_mod,
        "repo_identity",
        lambda root: gh_mod.RepoIdentity("acme", "https://github.com/x/acme", "main"),
    )


def _plant_repo_skill(root, dir_name, *, name=None, body_fm=None):
    skill = root / ".perk" / "skills" / dir_name / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    fm = body_fm or f"---\nname: {name or dir_name}\ndescription: A skill.\n---\n# body\n"
    skill.write_text(fm, encoding="utf-8")
    return skill


def _commit_all(root):
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "x"], cwd=root, check=True, capture_output=True)


def test_init_writes_repo_skills_fragment_before_sync(git_repo, monkeypatch, stub_env):
    # The fragment must exist on disk by the time sync_skills runs (so the CLI sees the source).
    _plant_repo_skill(git_repo, "alpha")
    _commit_all(git_repo)
    _stub_identity(monkeypatch)
    fragment = git_repo / ".agents" / "manifest.d" / "perk-repo-skills.yaml"
    seen = {}
    monkeypatch.setattr(
        init_mod,
        "sync_skills",
        lambda root, changes, **kw: seen.update(
            exists=fragment.is_file(), names=kw.get("repo_skill_names")
        ),
    )
    report = run_init(git_repo, verify=True)
    assert report.ok and seen["exists"] is True
    assert seen["names"] == ("alpha",)
    assert any("perk-repo-skills.yaml: created" in c for c in report.changes)


def test_init_structural_errors_are_nonfatal_warnings(git_repo, monkeypatch, stub_env):
    # A malformed SKILL.md is a NON-FATAL clear report: init exits 0, errors land on `warnings`.
    _plant_repo_skill(git_repo, "alpha", body_fm="no frontmatter here\n")
    _commit_all(git_repo)
    _stub_identity(monkeypatch)
    report = run_init(git_repo, verify=True)
    assert report.ok and report.exit_code == 0
    assert any("alpha" in w for w in report.warnings)


def test_init_untracked_repo_skill_warns(git_repo, monkeypatch, stub_env):
    # A planted-but-uncommitted skill renders the fragment but warns (exit 0).
    _plant_repo_skill(git_repo, "alpha")  # NOT committed
    _stub_identity(monkeypatch)
    report = run_init(git_repo, verify=True)
    assert report.ok and report.exit_code == 0
    assert any("not committed" in w for w in report.warnings)


def test_init_no_repo_skills_no_warnings(git_repo, stub_env):
    # No `.perk/skills/` → no fragment, no warnings, no repo-skills change (idempotency intact).
    report = run_init(git_repo, verify=True)
    assert report.ok and report.warnings == []
    assert not any("perk-repo-skills" in c for c in report.changes)


def test_not_a_repo_is_exit_2(tmp_path, monkeypatch):
    # With git present, the repo gate wins over a missing non-git tool: not_a_repo, never
    # missing_tool (run_init's ordering: git check -> repo gate -> remaining required tools).
    monkeypatch.setattr(env_mod, "check_environment", _lean_ci_env)
    report = run_init(tmp_path, verify=True, interactive=False)  # tmp_path is not a git repo
    assert not report.ok and report.error_type == "not_a_repo" and report.exit_code == 2


def test_missing_tool_is_exit_2(git_repo, monkeypatch):
    # Hermetic + non-interactive: the failure derives organically from the failing `pi` check
    # (never the host toolchain), and the guided-install pass can never prompt.
    monkeypatch.setattr(env_mod, "check_environment", _lean_ci_env)
    report = run_init(git_repo, verify=True, interactive=False)
    assert not report.ok and report.error_type == "missing_tool" and report.exit_code == 2
    assert "pi" in (report.message or "")


def test_github_error_is_non_fatal(git_repo, monkeypatch, stub_env):
    # A flaky/slow/broken gh (GitHubError) must not crash init (D3 — GitHub non-fatal).
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
        assert payload["handoff"] == ".perk/workflow/post-init.md"


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


# --- Linear readiness (verify-gated, non-fatal) -------------------------------


def _select_linear(root, *, team=True) -> None:
    cfg = root / ".perk"
    cfg.mkdir(parents=True, exist_ok=True)
    body = '[issues]\nbackend = "linear"\n'
    if team:
        body += 'team = "ENG"\n'
    (cfg / "config.toml").write_text(body, encoding="utf-8")


def test_report_to_dict_linear_null_when_not_evaluated(tmp_path):
    data = report_to_dict(run_init(tmp_path, verify=False))
    assert data["linear"] is None


def test_linear_readiness_skipped_without_verify(tmp_path):
    _select_linear(tmp_path)
    report = run_init(tmp_path, verify=False)
    assert report.ok and report.linear is None


def test_linear_readiness_skipped_on_github_selection(git_repo, stub_env):
    report = run_init(git_repo, verify=True)
    assert report.ok and report.linear is None


def test_linear_readiness_runs_when_selected(git_repo, stub_env, monkeypatch):
    _select_linear(git_repo)
    monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")
    ready = init_mod.linear.LinearReadiness(auth_ok=True, user="Mat", team_ok=True)
    calls = []

    def fake_readiness(client, *, team_key, ensure_labels):
        calls.append((team_key, ensure_labels))
        return ready

    monkeypatch.setattr(init_mod.linear, "check_readiness", fake_readiness)
    project = init_mod.linear.LinearProjectReadiness(projects_ok=True)
    monkeypatch.setattr(
        init_mod.linear,
        "check_project_readiness",
        lambda client, *, team_key: project,
    )
    report = run_init(git_repo, verify=True)
    assert report.ok and report.linear is not None
    assert report.linear.ok and report.linear.readiness == ready
    assert report.linear.team == "ENG"
    assert report.linear.project == project  # probed when auth_ok && team_ok
    assert calls == [("ENG", True)]  # init ensures the labels upfront
    # Created labels are reported through LinearReport, never the filesystem-delta changes.
    assert not any("linear" in c.lower() for c in report.changes if "pi-mono-linear" not in c)
    data = report_to_dict(report)
    linear_dict = cast("dict[str, object]", data["linear"])
    assert isinstance(linear_dict, dict) and linear_dict["ok"] is True
    project_dict = cast("dict[str, object]", linear_dict["project"])
    assert isinstance(project_dict, dict) and project_dict["projects_ok"] is True


def test_linear_project_readiness_gap_non_fatal(git_repo, stub_env, monkeypatch):
    _select_linear(git_repo)
    monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")
    monkeypatch.setattr(
        init_mod.linear,
        "check_readiness",
        lambda client, *, team_key, ensure_labels: init_mod.linear.LinearReadiness(
            auth_ok=True, user="Mat", team_ok=True
        ),
    )
    gap = init_mod.linear.LinearProjectReadiness(
        projects_ok=False, projects_error="no access", missing_state_types=("canceled",)
    )
    monkeypatch.setattr(init_mod.linear, "check_project_readiness", lambda client, *, team_key: gap)
    report = run_init(git_repo, verify=True)
    # Project readiness is non-fatal: it does NOT flip LinearReport.ok.
    assert report.ok and report.linear is not None and report.linear.ok
    assert report.linear.project == gap
    data = report_to_dict(report)
    linear_dict = cast("dict[str, object]", data["linear"])
    project_dict = cast("dict[str, object]", linear_dict["project"])
    assert project_dict["projects_ok"] is False
    assert project_dict["missing_state_types"] == ["canceled"]


def test_linear_project_readiness_skipped_on_auth_degrade(git_repo, stub_env, monkeypatch):
    _select_linear(git_repo)
    monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")
    monkeypatch.setattr(
        init_mod.linear,
        "check_readiness",
        lambda client, *, team_key, ensure_labels: init_mod.linear.LinearReadiness(
            auth_ok=False, user=None, team_ok=False, error="bad key"
        ),
    )

    def _boom(client, *, team_key):
        raise AssertionError("check_project_readiness must not run when auth/team failed")

    monkeypatch.setattr(init_mod.linear, "check_project_readiness", _boom)
    report = run_init(git_repo, verify=True)
    assert report.linear is not None and report.linear.project is None


def test_linear_readiness_degrades_on_missing_api_key(git_repo, stub_env, monkeypatch):
    _select_linear(git_repo)
    monkeypatch.delenv("LINEAR_API_KEY", raising=False)
    report = run_init(git_repo, verify=True)
    assert report.ok  # non-fatal (D3): convergence already succeeded
    assert report.linear is not None and not report.linear.ok
    assert "LINEAR_API_KEY" in (report.linear.error or "")


def test_linear_readiness_degrades_on_missing_team(git_repo, stub_env, monkeypatch):
    _select_linear(git_repo, team=False)
    monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")
    report = run_init(git_repo, verify=True)
    assert report.ok
    assert report.linear is not None and not report.linear.ok
    assert "[issues] team" in (report.linear.error or "")
