"""The interactive `perk init` onboarding gestures (contracts.md §8.5).

Gesture unit tests patch the module-level seams (`onboarding.user_confirm`/`user_prompt`,
the substrate module attributes) so everything stays offline and prompt-free; the `run_init`
wiring tests ride the `stub_env` fixture and override exactly the seam under test.
"""

import json

import pytest
from click.testing import CliRunner

from perk import github as gh_mod
from perk.cli.cli import cli
from perk.cli.commands import init_cmd as init_cmd_mod
from perk.cli.commands.init_cmd import _render_human, _repo_wiring_changes
from perk.convergence import env as env_mod
from perk.convergence import init as init_mod
from perk.convergence.env import EnvCheck
from perk.convergence.init import (
    GitHubReport,
    InitReport,
    LinearReport,
    onboarding,
    report_to_dict,
    run_init,
)
from perk.substrate import config as config_mod
from perk.substrate import git as git_mod
from perk.substrate import npm as npm_mod
from perk.substrate import proc as proc_mod

_ALL_OK = [
    EnvCheck("git", True, "ok", ""),
    EnvCheck("gh", True, "ok", ""),
    EnvCheck("node", True, "v22.19.0", ""),
    EnvCheck("pi", True, "ok", ""),
    EnvCheck("skills", True, "ok", ""),
]


def _env(*failing: str) -> list[EnvCheck]:
    return [
        EnvCheck(c.name, False, "not found", f"Install {c.name}: cmd") if c.name in failing else c
        for c in _ALL_OK
    ]


def _never(*_args, **_kwargs):
    raise AssertionError("this seam must not be reached")


# --- installer resolution (the guide-vs-install matrix) --------------------------------------


def test_resolve_installer_git_and_node_are_guide_only():
    assert onboarding._resolve_installer("git", node_ok=True) is None
    assert onboarding._resolve_installer("node", node_ok=True) is None


def test_resolve_installer_gh_is_brew_gated(monkeypatch):
    monkeypatch.setattr(onboarding.shutil, "which", lambda name: None)
    assert onboarding._resolve_installer("gh", node_ok=True) is None
    monkeypatch.setattr(
        onboarding.shutil,
        "which",
        lambda name: "/opt/homebrew/bin/brew" if name == "brew" else None,
    )
    installer = onboarding._resolve_installer("gh", node_ok=True)
    assert installer is not None and installer.label == "brew install gh"


def test_resolve_installer_pi_is_node_gated():
    assert onboarding._resolve_installer("pi", node_ok=False) is None
    installer = onboarding._resolve_installer("pi", node_ok=True)
    assert installer is not None and onboarding.PI_NPM_SPEC in installer.label


def test_resolve_installer_skills_darwin_vs_linux(monkeypatch):
    monkeypatch.setattr(onboarding.sys, "platform", "darwin")
    monkeypatch.setattr(onboarding.shutil, "which", lambda name: None)
    installer = onboarding._resolve_installer("skills", node_ok=True)
    assert installer is not None and installer.label == "the official install script"

    monkeypatch.setattr(onboarding.sys, "platform", "linux")
    assert onboarding._resolve_installer("skills", node_ok=True) is None  # no go on PATH
    monkeypatch.setattr(
        onboarding.shutil, "which", lambda name: "/usr/bin/go" if name == "go" else None
    )
    installer = onboarding._resolve_installer("skills", node_ok=True)
    assert installer is not None and installer.label == f"go install {onboarding.SKILLS_GO_SPEC}"


# --- guide_missing_tools ----------------------------------------------------------------------


def test_guide_healthy_host_is_a_silent_noop(monkeypatch):
    monkeypatch.setattr(onboarding, "user_confirm", _never)
    checks = [*_ALL_OK, EnvCheck("ast-grep", False, "not found", "opt", optional=True)]
    assert onboarding.guide_missing_tools(checks) == ([], [])  # optional never offered


def test_guide_installs_pi_happy_path(monkeypatch):
    confirms: list[str] = []
    monkeypatch.setattr(
        onboarding, "user_confirm", lambda prompt, *, default: confirms.append(prompt) or True
    )
    installed: list[tuple[str, int]] = []
    monkeypatch.setattr(
        npm_mod, "install_global", lambda spec, *, timeout: installed.append((spec, timeout))
    )
    monkeypatch.setattr(
        onboarding.shutil, "which", lambda name: "/usr/local/bin/pi" if name == "pi" else None
    )
    changes, warnings = onboarding.guide_missing_tools(_env("pi"))
    assert confirms == [f"Install pi via npm install -g {onboarding.PI_NPM_SPEC}?"]
    assert installed == [(onboarding.PI_NPM_SPEC, 600)]
    assert changes == [f"tool pi: installed (npm -g {onboarding.PI_NPM_SPEC})"]
    assert warnings == []


def test_guide_decline_warns_with_the_remediation(monkeypatch):
    monkeypatch.setattr(onboarding, "user_confirm", lambda prompt, *, default: False)
    monkeypatch.setattr(npm_mod, "install_global", _never)
    changes, warnings = onboarding.guide_missing_tools(_env("pi"))
    assert changes == []
    assert warnings == ["pi not installed; install manually: Install pi: cmd"]


def test_guide_install_failure_warns(monkeypatch):
    monkeypatch.setattr(onboarding, "user_confirm", lambda prompt, *, default: True)

    def _boom(spec, *, timeout):
        raise npm_mod.NpmError("registry down")

    monkeypatch.setattr(npm_mod, "install_global", _boom)
    changes, warnings = onboarding.guide_missing_tools(_env("pi"))
    assert changes == []
    assert len(warnings) == 1
    assert "registry down" in warnings[0] and "install manually" in warnings[0]


def test_guide_still_absent_after_install_warns(monkeypatch):
    monkeypatch.setattr(onboarding, "user_confirm", lambda prompt, *, default: True)
    ran: list[list[str]] = []
    monkeypatch.setattr(onboarding, "_run_install", lambda argv: ran.append(argv))
    monkeypatch.setattr(
        onboarding.shutil,
        "which",
        lambda name: "/opt/homebrew/bin/brew" if name == "brew" else None,
    )
    changes, warnings = onboarding.guide_missing_tools(_env("gh"))
    assert ran == [["brew", "install", "gh"]]
    assert changes == []
    assert len(warnings) == 1 and "not on PATH" in warnings[0]


def test_guide_skills_darwin_runs_the_official_script(monkeypatch):
    monkeypatch.setattr(onboarding.sys, "platform", "darwin")
    monkeypatch.setattr(onboarding, "user_confirm", lambda prompt, *, default: True)
    ran: list[list[str]] = []
    monkeypatch.setattr(onboarding, "_run_install", lambda argv: ran.append(argv))
    monkeypatch.setattr(
        onboarding.shutil,
        "which",
        lambda name: "/usr/local/bin/skills" if name == "skills" else None,
    )
    changes, warnings = onboarding.guide_missing_tools(_env("skills"))
    assert ran == [["/bin/sh", "-c", onboarding.SKILLS_INSTALL_SCRIPT]]
    assert changes == ["tool skills: installed (official install script)"]
    assert warnings == []


def test_guide_skills_go_install_carries_the_gopath_hint(monkeypatch):
    # A go install that lands outside PATH warns with the $(go env GOPATH)/bin hint.
    monkeypatch.setattr(onboarding.sys, "platform", "linux")
    monkeypatch.setattr(onboarding, "user_confirm", lambda prompt, *, default: True)
    monkeypatch.setattr(onboarding, "_run_install", lambda argv: None)
    monkeypatch.setattr(
        onboarding.shutil, "which", lambda name: "/usr/bin/go" if name == "go" else None
    )
    changes, warnings = onboarding.guide_missing_tools(_env("skills"))
    assert changes == []
    assert warnings == ["skills installed but not on PATH; add $(go env GOPATH)/bin to your PATH"]


def test_guide_pi_without_node_notes_node_first(monkeypatch):
    monkeypatch.setattr(onboarding, "user_confirm", _never)  # no offer without node
    changes, warnings = onboarding.guide_missing_tools(_env("pi", "node"))
    assert changes == []
    assert warnings == [
        f"pi: install Node >= 22 first, then: npm install -g {onboarding.PI_NPM_SPEC}"
    ]


# --- offer_gh_login ---------------------------------------------------------------------------


def test_offer_gh_login_accept_spawns_the_interactive_login(monkeypatch):
    monkeypatch.setattr(onboarding, "user_confirm", lambda prompt, *, default: True)
    calls: list[tuple[list[str], int]] = []
    monkeypatch.setattr(
        proc_mod,
        "run_interactive",
        lambda argv, *, timeout: calls.append((list(argv), timeout)) or 0,
    )
    assert onboarding.offer_gh_login() is True
    assert calls == [(["gh", "auth", "login"], 900)]


def test_offer_gh_login_decline_never_spawns(monkeypatch):
    monkeypatch.setattr(onboarding, "user_confirm", lambda prompt, *, default: False)
    monkeypatch.setattr(proc_mod, "run_interactive", _never)
    assert onboarding.offer_gh_login() is False


def test_offer_gh_login_proc_failure_returns_false(monkeypatch):
    monkeypatch.setattr(onboarding, "user_confirm", lambda prompt, *, default: True)

    def _boom(argv, *, timeout):
        raise proc_mod.ProcFailure("spawn", tuple(argv), cause_text="gh vanished")

    monkeypatch.setattr(proc_mod, "run_interactive", _boom)
    assert onboarding.offer_gh_login() is False


# --- ensure_git_identity ----------------------------------------------------------------------


def _identity(monkeypatch, mapping: dict[str, str]) -> None:
    monkeypatch.setattr(git_mod, "config_get", lambda root, key: mapping.get(key))


def test_identity_both_present_is_a_silent_noop(monkeypatch, tmp_path):
    _identity(monkeypatch, {"user.name": "Mat", "user.email": "m@x.com"})
    monkeypatch.setattr(onboarding, "user_prompt", _never)
    assert onboarding.ensure_git_identity(tmp_path, interactive=True) == ([], [])


def test_identity_probe_giterror_warns_never_raises(monkeypatch, tmp_path):
    def _boom(root, key):
        raise git_mod.GitError("git broke")

    monkeypatch.setattr(git_mod, "config_get", _boom)
    changes, warnings = onboarding.ensure_git_identity(tmp_path, interactive=True)
    assert changes == []
    assert warnings == ["git identity unverifiable: git broke"]


def test_identity_noninteractive_missing_warns_with_manual_commands(monkeypatch, tmp_path):
    _identity(monkeypatch, {})
    monkeypatch.setattr(onboarding, "user_prompt", _never)
    changes, warnings = onboarding.ensure_git_identity(tmp_path, interactive=False)
    assert changes == []
    assert len(warnings) == 1
    assert "git identity not set (user.name, user.email)" in warnings[0]
    assert 'git config --global user.name "Your Name"' in warnings[0]


def test_identity_interactive_prompts_and_sets_globally_by_default(monkeypatch, tmp_path):
    _identity(monkeypatch, {"user.name": "Mat"})  # only email missing
    monkeypatch.setattr(onboarding, "user_prompt", lambda prompt, **kw: " m@x.com ")
    monkeypatch.setattr(onboarding, "user_confirm", lambda prompt, *, default: True)
    sets: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        git_mod, "config_set", lambda root, key, value, *, scope: sets.append((key, value, scope))
    )
    changes, warnings = onboarding.ensure_git_identity(tmp_path, interactive=True)
    assert sets == [("user.email", "m@x.com", "global")]  # the answer is stripped
    assert changes == ["git identity: user.email set (global)"]
    assert warnings == []


def test_identity_scope_decline_sets_repo_local(monkeypatch, tmp_path):
    _identity(monkeypatch, {})
    answers = iter(["Mat", "m@x.com"])
    monkeypatch.setattr(onboarding, "user_prompt", lambda prompt, **kw: next(answers))
    monkeypatch.setattr(onboarding, "user_confirm", lambda prompt, *, default: False)
    sets: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        git_mod, "config_set", lambda root, key, value, *, scope: sets.append((key, value, scope))
    )
    changes, warnings = onboarding.ensure_git_identity(tmp_path, interactive=True)
    assert sets == [("user.name", "Mat", "local"), ("user.email", "m@x.com", "local")]
    assert changes == [
        "git identity: user.name set (local)",
        "git identity: user.email set (local)",
    ]
    assert warnings == []


def test_identity_blank_answer_skips_with_manual_commands(monkeypatch, tmp_path):
    _identity(monkeypatch, {})
    monkeypatch.setattr(onboarding, "user_prompt", lambda prompt, **kw: "   ")
    monkeypatch.setattr(git_mod, "config_set", _never)
    changes, warnings = onboarding.ensure_git_identity(tmp_path, interactive=True)
    assert changes == []
    assert len(warnings) == 1 and "git config --global" in warnings[0]


def test_identity_write_giterror_warns(monkeypatch, tmp_path):
    _identity(monkeypatch, {})
    answers = iter(["Mat", "m@x.com"])
    monkeypatch.setattr(onboarding, "user_prompt", lambda prompt, **kw: next(answers))
    monkeypatch.setattr(onboarding, "user_confirm", lambda prompt, *, default: True)

    def _boom(root, key, value, *, scope):
        raise git_mod.GitError("config locked")

    monkeypatch.setattr(git_mod, "config_set", _boom)
    changes, warnings = onboarding.ensure_git_identity(tmp_path, interactive=True)
    assert changes == []
    assert len(warnings) == 1
    assert "config locked" in warnings[0] and "git config --global" in warnings[0]


# --- prompt_linear_api_key --------------------------------------------------------------------


def _linear_repo(tmp_path, *, backend: str = "linear", team: bool = True):
    cfg = tmp_path / ".perk"
    cfg.mkdir(parents=True, exist_ok=True)
    body = f'[issues]\nbackend = "{backend}"\n'
    if team:
        body += 'team = "ENG"\n'
    (cfg / "config.toml").write_text(body, encoding="utf-8")


def _ready(auth_ok: bool = True, team_ok: bool = True, error: str | None = None):
    return init_mod.linear.LinearReadiness(
        auth_ok=auth_ok, user="Mat" if auth_ok else None, team_ok=team_ok, error=error
    )


@pytest.fixture
def _no_env_key(monkeypatch):
    monkeypatch.delenv("LINEAR_API_KEY", raising=False)


def test_linear_prompt_guard_matrix_never_prompts(tmp_path, monkeypatch, _no_env_key):
    monkeypatch.setattr(onboarding, "user_prompt", _never)
    # github backend → skip.
    _linear_repo(tmp_path, backend="github")
    assert onboarding.prompt_linear_api_key(tmp_path) == ([], [])
    # linear without a team → skip (the LinearReport error owns that gap).
    _linear_repo(tmp_path, team=False)
    assert onboarding.prompt_linear_api_key(tmp_path) == ([], [])
    # env key set → skip.
    _linear_repo(tmp_path)
    monkeypatch.setenv("LINEAR_API_KEY", "lin_api_env")
    assert onboarding.prompt_linear_api_key(tmp_path) == ([], [])
    # local key stored → skip.
    monkeypatch.delenv("LINEAR_API_KEY")
    (tmp_path / ".perk" / "local.toml").write_text(
        '[linear]\napi_key = "lin_api_local"\n', encoding="utf-8"
    )
    assert onboarding.prompt_linear_api_key(tmp_path) == ([], [])


def test_linear_prompt_config_error_defers_to_the_config_check(tmp_path, monkeypatch, _no_env_key):
    monkeypatch.setattr(onboarding, "user_prompt", _never)
    (tmp_path / ".perk").mkdir()
    (tmp_path / ".perk" / "config.toml").write_text("[issues\nbackend =", encoding="utf-8")
    assert onboarding.prompt_linear_api_key(tmp_path) == ([], [])


def test_linear_prompt_invalid_then_valid_saves_and_reports(tmp_path, monkeypatch, _no_env_key):
    _linear_repo(tmp_path)
    answers = iter(["bad key!!", "lin_api_good"])
    prompts: list[dict] = []
    monkeypatch.setattr(
        onboarding, "user_prompt", lambda prompt, **kw: prompts.append(kw) or next(answers)
    )
    probes: list[tuple[str, str, bool]] = []

    def fake_readiness(client, *, team_key, ensure_labels):
        probes.append((client._api_key, team_key, ensure_labels))
        return _ready()

    monkeypatch.setattr(onboarding.linear, "check_readiness", fake_readiness)
    changes, warnings = onboarding.prompt_linear_api_key(tmp_path)
    assert changes == [".perk/local.toml: [linear] api_key set"]
    assert warnings == []
    # The charset-invalid entry never reached the probe; the prompt hides input.
    assert probes == [("lin_api_good", "ENG", False)]
    assert all(kw.get("hide_input") is True for kw in prompts)
    assert config_mod.load_local_linear_api_key(tmp_path) == "lin_api_good"


def test_linear_prompt_rejected_key_reprompts(tmp_path, monkeypatch, _no_env_key):
    _linear_repo(tmp_path)
    answers = iter(["lin_api_bad", "lin_api_good"])
    monkeypatch.setattr(onboarding, "user_prompt", lambda prompt, **kw: next(answers))
    responses = iter([_ready(auth_ok=False, team_ok=False, error="bad key"), _ready()])
    monkeypatch.setattr(
        onboarding.linear,
        "check_readiness",
        lambda client, *, team_key, ensure_labels: next(responses),
    )
    changes, warnings = onboarding.prompt_linear_api_key(tmp_path)
    assert changes == [".perk/local.toml: [linear] api_key set"] and warnings == []
    assert config_mod.load_local_linear_api_key(tmp_path) == "lin_api_good"


def test_linear_prompt_saves_even_when_team_fails(tmp_path, monkeypatch, _no_env_key):
    # A team failure is a config problem, not a key problem — the readiness probe right after
    # reports it; the validated key is still stored.
    _linear_repo(tmp_path)
    monkeypatch.setattr(onboarding, "user_prompt", lambda prompt, **kw: "lin_api_good")
    monkeypatch.setattr(
        onboarding.linear,
        "check_readiness",
        lambda client, *, team_key, ensure_labels: _ready(team_ok=False, error="no such team"),
    )
    changes, warnings = onboarding.prompt_linear_api_key(tmp_path)
    assert changes == [".perk/local.toml: [linear] api_key set"] and warnings == []


def test_linear_prompt_three_strikes_skips_with_warning(tmp_path, monkeypatch, _no_env_key):
    _linear_repo(tmp_path)
    monkeypatch.setattr(onboarding, "user_prompt", lambda prompt, **kw: "not a key!!")
    monkeypatch.setattr(onboarding.linear, "check_readiness", _never)  # never reaches the probe
    changes, warnings = onboarding.prompt_linear_api_key(tmp_path)
    assert changes == []
    assert len(warnings) == 1 and "after 3 attempts" in warnings[0]
    assert not (tmp_path / ".perk" / "local.toml").exists()


def test_linear_prompt_blank_entry_skips(tmp_path, monkeypatch, _no_env_key):
    _linear_repo(tmp_path)
    monkeypatch.setattr(onboarding, "user_prompt", lambda prompt, **kw: "")
    changes, warnings = onboarding.prompt_linear_api_key(tmp_path)
    assert changes == []
    assert len(warnings) == 1 and "LINEAR_API_KEY" in warnings[0]


def test_linear_prompt_save_oserror_degrades_to_warning(tmp_path, monkeypatch, _no_env_key):
    # An unwritable target must never crash init after convergence.
    _linear_repo(tmp_path)
    monkeypatch.setattr(onboarding, "user_prompt", lambda prompt, **kw: "lin_api_good")
    monkeypatch.setattr(
        onboarding.linear,
        "check_readiness",
        lambda client, *, team_key, ensure_labels: _ready(),
    )

    def _boom(root, key):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(config_mod, "save_local_linear_api_key", _boom)
    changes, warnings = onboarding.prompt_linear_api_key(tmp_path)
    assert changes == []
    assert len(warnings) == 1
    assert "read-only filesystem" in warnings[0] and "LINEAR_API_KEY" in warnings[0]


def test_linear_prompt_unparseable_local_toml_warns_and_preserves_bytes(
    tmp_path, monkeypatch, _no_env_key
):
    _linear_repo(tmp_path)
    original = "[linear\napi_key ="
    (tmp_path / ".perk" / "local.toml").write_text(original, encoding="utf-8")
    monkeypatch.setattr(onboarding, "user_prompt", lambda prompt, **kw: "lin_api_good")
    monkeypatch.setattr(
        onboarding.linear,
        "check_readiness",
        lambda client, *, team_key, ensure_labels: _ready(),
    )
    changes, warnings = onboarding.prompt_linear_api_key(tmp_path)
    assert changes == []
    assert len(warnings) == 1 and "not valid TOML" in warnings[0]
    assert (tmp_path / ".perk" / "local.toml").read_text(encoding="utf-8") == original


# --- run_init wiring: the preflight reorder ----------------------------------------------------


@pytest.mark.parametrize("interactive", [True, False])
def test_missing_git_in_a_real_repo_is_missing_tool(git_repo, monkeypatch, interactive):
    # The classification fix (both modes): a missing git must never degrade the repo_root
    # probe into `not_a_repo` — and repo_root is never even shelled.
    monkeypatch.setattr(env_mod, "check_environment", lambda: _env("git"))
    monkeypatch.setattr(init_mod, "guide_missing_tools", lambda checks: ([], []))
    monkeypatch.setattr(git_mod, "repo_root", _never)
    report = run_init(git_repo, verify=True, interactive=interactive)
    assert not report.ok and report.error_type == "missing_tool" and report.exit_code == 2


def test_non_repo_with_git_present_is_not_a_repo(tmp_path, stub_env):
    report = run_init(tmp_path, verify=True)
    assert not report.ok and report.error_type == "not_a_repo" and report.exit_code == 2


def test_non_interactive_missing_tool_keeps_env_failure_and_never_prompts(git_repo, monkeypatch):
    monkeypatch.setattr(env_mod, "check_environment", lambda: _env("pi"))
    monkeypatch.setattr(init_mod, "guide_missing_tools", _never)
    report = run_init(git_repo, verify=True, interactive=False)
    assert not report.ok and report.error_type == "missing_tool" and report.exit_code == 2
    assert report.changes == [] and report.warnings == []


def test_guided_pass_fixes_the_gap_and_init_proceeds(git_repo, stub_env, monkeypatch):
    # First probe: pi missing; the guided install fixes it; the re-probe is healthy.
    probes = iter([_env("pi"), list(_ALL_OK)])
    monkeypatch.setattr(env_mod, "check_environment", lambda: next(probes))
    change = f"tool pi: installed (npm -g {onboarding.PI_NPM_SPEC})"
    monkeypatch.setattr(init_mod, "guide_missing_tools", lambda checks: ([change], []))
    report = run_init(git_repo, verify=True)
    assert report.ok
    assert change in report.changes
    assert all(c.ok for c in report.env)  # the report carries the refreshed checks


def test_guided_pass_failure_preserves_changes_and_warnings(git_repo, stub_env, monkeypatch):
    # A guided pass that installed one tool but not the other: the inline missing_tool report
    # preserves the accumulated changes/warnings (the skills_sync_failed pattern).
    monkeypatch.setattr(env_mod, "check_environment", lambda: _env("pi"))
    monkeypatch.setattr(
        init_mod,
        "guide_missing_tools",
        lambda checks: (["tool gh: installed (brew install gh)"], ["pi not installed; nope"]),
    )
    report = run_init(git_repo, verify=True)
    assert not report.ok and report.error_type == "missing_tool" and report.exit_code == 2
    assert report.changes == ["tool gh: installed (brew install gh)"]
    assert report.warnings == ["pi not installed; nope"]


def test_guided_pass_runs_once(git_repo, stub_env, monkeypatch):
    monkeypatch.setattr(env_mod, "check_environment", lambda: _env("pi"))
    calls: list[int] = []
    monkeypatch.setattr(
        init_mod, "guide_missing_tools", lambda checks: (calls.append(1), ([], []))[1]
    )
    report = run_init(git_repo, verify=True)
    assert calls == [1]
    assert not report.ok and report.error_type == "missing_tool"


# --- run_init wiring: the verify-gated gestures -------------------------------------------------


def test_gh_login_accept_reprobes_and_reports_the_fresh_auth(git_repo, stub_env, monkeypatch):
    auths = iter(
        [
            gh_mod.AuthStatus(False, None, (), "not authed"),
            gh_mod.AuthStatus(True, "mat", ("repo",), None),
        ]
    )
    monkeypatch.setattr(gh_mod, "check_auth", lambda: next(auths))
    monkeypatch.setattr(init_mod, "offer_gh_login", lambda: True)
    report = run_init(git_repo, verify=True)
    assert report.ok and report.github is not None
    assert report.github.auth.ok and report.github.auth.user == "mat"


def test_gh_login_decline_keeps_the_unauthed_report(git_repo, stub_env, monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(init_mod, "offer_gh_login", lambda: calls.append(1) or False)
    report = run_init(git_repo, verify=True)
    assert calls == [1]
    assert report.ok and report.github is not None and not report.github.auth.ok


def test_identity_gesture_output_folds_into_the_report(git_repo, stub_env, monkeypatch):
    monkeypatch.setattr(
        init_mod,
        "ensure_git_identity",
        lambda root, *, interactive: (["git identity: user.email set (global)"], ["idw"]),
    )
    report = run_init(git_repo, verify=True)
    assert "git identity: user.email set (global)" in report.changes
    assert "idw" in report.warnings


def test_non_interactive_identity_probe_warning_lands_on_the_report(
    git_repo, stub_env, monkeypatch
):
    # The deliberate new non-interactive value: the probe-side git-identity warning.
    monkeypatch.setattr(init_mod, "ensure_git_identity", onboarding.ensure_git_identity)
    monkeypatch.setattr(git_mod, "config_get", lambda root, key: None)
    report = run_init(git_repo, verify=True, interactive=False)
    assert report.ok
    assert any("git identity not set" in w for w in report.warnings)


def test_linear_key_prompt_runs_before_the_readiness_probe(git_repo, stub_env, monkeypatch):
    order: list[str] = []
    monkeypatch.setattr(
        init_mod, "prompt_linear_api_key", lambda root: (order.append("prompt"), ([], []))[1]
    )
    monkeypatch.setattr(init_mod, "_linear_readiness", lambda root: order.append("probe"))
    run_init(git_repo, verify=True)
    assert order == ["prompt", "probe"]


def test_linear_key_gesture_output_folds_into_the_report(git_repo, stub_env, monkeypatch):
    monkeypatch.setattr(
        init_mod,
        "prompt_linear_api_key",
        lambda root: ([".perk/local.toml: [linear] api_key set"], ["lw"]),
    )
    report = run_init(git_repo, verify=True)
    assert ".perk/local.toml: [linear] api_key set" in report.changes
    assert "lw" in report.warnings


def test_non_interactive_skips_the_prompting_gestures(git_repo, stub_env, monkeypatch):
    monkeypatch.setattr(init_mod, "offer_gh_login", _never)
    monkeypatch.setattr(init_mod, "prompt_linear_api_key", _never)
    seen: dict[str, bool] = {}
    monkeypatch.setattr(
        init_mod,
        "ensure_git_identity",
        lambda root, *, interactive: (seen.update(interactive=interactive), ([], []))[1],
    )
    report = run_init(git_repo, verify=True, interactive=False)
    assert report.ok
    # The identity probe still runs (its non-interactive arm is a probe-side warning), but is
    # told not to prompt.
    assert seen == {"interactive": False}


def test_verify_false_skips_every_gesture(tmp_path, monkeypatch):
    for name in (
        "guide_missing_tools",
        "offer_gh_login",
        "ensure_git_identity",
        "prompt_linear_api_key",
    ):
        monkeypatch.setattr(init_mod, name, _never)
    assert run_init(tmp_path, verify=False).ok


# --- the --json schema invariance --------------------------------------------------------------

_EXPECTED_REPORT_FIELDS = {
    "success",
    "mode",
    "error_type",
    "message",
    "env",
    "github",
    "linear",
    "capabilities",
    "changes",
    "warnings",
    "handoff",
}


def test_json_field_set_is_unchanged_on_the_guided_paths(git_repo, stub_env, monkeypatch):
    # Values deliberately differ; the field SCHEMA is the compatibility contract.
    success = report_to_dict(run_init(git_repo, verify=True))
    assert set(success) == _EXPECTED_REPORT_FIELDS
    assert all(set(entry) == {"name", "ok", "detail", "remediation"} for entry in success["env"])

    monkeypatch.setattr(env_mod, "check_environment", lambda: _env("pi"))
    monkeypatch.setattr(
        init_mod, "guide_missing_tools", lambda checks: (["tool x: installed (y)"], ["w"])
    )
    failure = report_to_dict(run_init(git_repo, verify=True))
    assert failure["success"] is False and failure["error_type"] == "missing_tool"
    assert set(failure) == _EXPECTED_REPORT_FIELDS


# --- the command layer: the --json interactivity gate + the human render ------------------------


class _TtySys:
    """A fake `sys` for init_cmd: a TTY-true stdin regardless of CliRunner's stdin swap."""

    class stdin:
        @staticmethod
        def isatty() -> bool:
            return True


def test_json_disables_interactivity_even_on_a_tty(tmp_path, monkeypatch):
    # The supervisor-channel fix: --json is a machine surface — no prompt/inherited-stdio
    # gesture may interleave with the one stdout JSON object.
    monkeypatch.setattr(init_cmd_mod, "sys", _TtySys)
    seen: dict[str, bool] = {}

    def fake_run_init(*, force, interactive):
        seen["interactive"] = interactive
        return InitReport(
            ok=True,
            mode="consumer",
            env=[],
            changes=[],
            github=None,
            handoff=None,
        )

    monkeypatch.setattr(init_cmd_mod, "run_init", fake_run_init)
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["init", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.stdout)["success"] is True
    assert seen == {"interactive": False}

    with runner.isolated_filesystem(temp_dir=tmp_path):
        assert runner.invoke(cli, ["init"]).exit_code == 0
    assert seen == {"interactive": True}  # the TTY-true human path stays interactive


def test_repo_wiring_changes_classification():
    host_local = [
        "tool pi: installed (npm -g @earendil-works/pi-coding-agent)",
        "hunk CLI: installed hunkdiff (npm -g)",
        "git identity: user.email set (global)",
        ".perk/local.toml: [linear] api_key set",
        ".perk/workflow/: created",
    ]
    assert _repo_wiring_changes(host_local) == []
    wiring = [".pi/settings.json: packages + perk entry", ".gitignore: managed block updated"]
    assert _repo_wiring_changes(host_local + wiring) == wiring


def _ok_env() -> list[EnvCheck]:
    return list(_ALL_OK)


def test_failure_render_numbered_checklist_and_completed_preface(capsys):
    report = InitReport(
        ok=False,
        mode="unknown",
        env=[
            EnvCheck("git", True, "ok", ""),
            EnvCheck("pi", False, "not found", "Install Pi: npm install -g x"),
            EnvCheck("skills", False, "not found", "Install the skills CLI: y"),
            EnvCheck("ast-grep", False, "not found", "optional hint", optional=True),
        ],
        changes=["tool gh: installed (brew install gh)"],
        github=None,
        handoff=None,
        error_type="missing_tool",
        message="Missing or outdated required tool(s): pi, skills.",
        warnings=["pi not installed; nope"],
    )
    _render_human(report)
    err = capsys.readouterr().err
    assert "To finish setup:" in err
    assert "1. pi: Install Pi: npm install -g x" in err
    assert "2. skills: Install the skills CLI: y" in err
    assert "optional hint" not in err  # optional checks are never on the checklist
    assert "Completed before failure:" in err and "Converged before failure" not in err
    assert "tool gh: installed (brew install gh)" in err
    assert "pi not installed; nope" in err


def test_success_render_next_steps_and_single_gh_source(capsys):
    report = InitReport(
        ok=True,
        mode="consumer",
        env=_ok_env(),
        changes=["tool pi: installed (npm -g x)", ".pi/settings.json: packages + perk entry"],
        github=GitHubReport(
            auth=gh_mod.AuthStatus(False, None, (), "not logged in"),
            repo=gh_mod.RepoAccess.skipped(),
        ),
        handoff=".perk/workflow/post-init.md",
        linear=LinearReport(readiness=None, error="LINEAR_API_KEY is not set; hint"),
    )
    _render_human(report)
    err = capsys.readouterr().err
    assert "Next steps:" in err
    assert "- Authenticate GitHub: gh auth login" in err
    assert err.count("gh auth login") == 1  # the old inline second line is gone (single source)
    assert "- Linear: LINEAR_API_KEY is not set; hint" in err
    assert "- Review and commit the wiring perk added (see: git status)" in err
    assert "git add -A" not in err
    assert "- Start with: perk plan" in err
    assert (
        "Agent on-ramp (optional): .perk/workflow/post-init.md — point an agent at this file" in err
    )


def test_success_render_host_only_changes_skip_the_commit_hint(capsys):
    report = InitReport(
        ok=True,
        mode="consumer",
        env=_ok_env(),
        changes=[
            "tool pi: installed (npm -g x)",
            ".perk/local.toml: [linear] api_key set",
            "git identity: user.email set (global)",
        ],
        github=GitHubReport(
            auth=gh_mod.AuthStatus(True, "mat", ("repo",), None),
            repo=gh_mod.RepoAccess.skipped(),
        ),
        handoff=".perk/workflow/post-init.md",
    )
    _render_human(report)
    err = capsys.readouterr().err
    assert "Review and commit" not in err  # host/local-only deltas never suggest a commit
    assert "- Authenticate GitHub" not in err
    assert "- Start with: perk plan" in err  # always present
