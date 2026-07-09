"""The stitched dot-directory migration gate (the capstone dogfood).

The `.perk/` dot-directory migration is code-complete and component-covered across
`test_doctor.py` / `test_init_idempotent.py` / `test_config.py`. This file stitches those proven
primitives into one coherent end-to-end gate that proves the *whole* migration on a throwaway repo:

- a freshly converged repo has **zero** dot-directory drift (config / repo-skills / legacy-workflow
  all clean, no doctor surface references a legacy `.pi/` dot-path); and
- a legacy-seeded repo (all three families: config, workflow cache, repo-skills) is **detected**
  then **repaired forward** by `doctor --fix`, landing on a clean tree.

Note on `repo-skills`: that check is verify-gated (it renders a fragment via a GitHub read, so it
cannot run as an offline managed check) — it is present only under `verify=True`. The `stub_env`
fixture keeps those runs offline; `github.repo_identity` is stubbed where a migrated skill must
converge.
"""

import subprocess

from perk import github
from perk.convergence.doctor import run_doctor
from perk.convergence.init import run_init
from perk.state import cache
from perk.substrate import git

_LEGACY_DOT_PATHS = (".pi/perk.toml", ".pi/perk.local.toml", ".pi/workflow")


def _by_name(report) -> dict:
    return {c.name: c for c in report.checks}


def _git(repo, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _stub_identity(monkeypatch, *, name="acme") -> None:
    monkeypatch.setattr(
        github,
        "repo_identity",
        lambda root: github.RepoIdentity(name, f"https://github.com/x/{name}", "main"),
    )


def test_converged_repo_has_no_dot_directory_drift(git_repo, stub_env):
    assert run_init(git_repo, verify=False).ok

    report = run_doctor(git_repo, verify=False)
    assert report.healthy and report.exit_code == 0
    checks = _by_name(report)
    assert checks["config"].status == "ok"
    assert checks["legacy-workflow"].status == "ok"

    # No doctor surface points back at a legacy dot-path (guards a future legacy re-introduction
    # from quietly surfacing through any check's detail).
    for c in report.checks:
        assert all(legacy not in (c.detail or "") for legacy in _LEGACY_DOT_PATHS)

    # `repo-skills` is verify-gated; on a converged repo with no repo-authored skills it is `ok`.
    verified = _by_name(run_doctor(git_repo, verify=True))
    assert verified["repo-skills"].status == "ok"

    # Topology: the new dot-directory layout, none of the legacy artifacts.
    assert (git_repo / ".perk" / "config.toml").is_file()
    workflow = git_repo / ".perk" / "workflow"
    assert workflow.is_dir()
    for sub in cache.SUBDIRS:
        assert (workflow / sub).is_dir()
    assert not (workflow / ".gitkeep").exists()
    assert not (git_repo / ".pi" / "perk.toml").exists()
    assert not (git_repo / ".pi" / "perk.local.toml").exists()

    gitignore = (git_repo / ".gitignore").read_text(encoding="utf-8")
    assert "/.perk/workflow/" in gitignore and "/.perk/local.toml" in gitignore
    assert "/.pi/workflow/" not in gitignore and "/.pi/perk.local.toml" not in gitignore

    # Idempotency: a second init + doctor is still clean with the same three checks `ok`.
    assert run_init(git_repo, verify=False).ok
    again = _by_name(run_doctor(git_repo, verify=False))
    assert run_doctor(git_repo, verify=False).healthy
    assert again["config"].status == "ok" and again["legacy-workflow"].status == "ok"


def test_legacy_repo_is_detected_then_repaired_by_fix(git_repo, stub_env, monkeypatch):
    assert run_init(git_repo, verify=False).ok

    # Simulate a pre-migration repo across all three families:
    # (1) committed legacy config, no `.perk/config.toml`;
    (git_repo / ".perk" / "config.toml").unlink()
    (git_repo / ".pi").mkdir(parents=True, exist_ok=True)
    (git_repo / ".pi" / "perk.toml").write_text(
        '[worktree]\nroot = "legacy-wt"\n', encoding="utf-8"
    )
    # (2) a tracked legacy workflow layout sentinel;
    gitkeep = git_repo / ".pi" / "workflow" / ".gitkeep"
    gitkeep.parent.mkdir(parents=True, exist_ok=True)
    gitkeep.write_text("", encoding="utf-8")
    _git(git_repo, "add", "-f", ".pi/workflow/.gitkeep")
    assert git.is_tracked(git_repo, ".pi/workflow/.gitkeep")
    # (3) a legacy repo-authored skill source.
    legacy_skill = git_repo / ".pi" / "skills" / "foo" / "SKILL.md"
    legacy_skill.parent.mkdir(parents=True, exist_ok=True)
    # `stages: all` keeps the post-migration repo-skills check `ok` (an undeclared skill now
    # draws doctor's stages nudge — out of scope for this migration test).
    legacy_skill.write_text(
        "---\nname: foo\ndescription: a legacy repo-authored skill\nstages: all\n---\nbody\n",
        encoding="utf-8",
    )

    # Drift detected.
    drift = _by_name(run_doctor(git_repo, verify=False))
    assert drift["config"].status == "fail" and drift["config"].detail == ".pi/perk.toml"
    assert drift["legacy-workflow"].status == "warn"

    # Repair, forward, across all three families.
    run_doctor(git_repo, fix=True, verify=False)
    assert (git_repo / ".perk" / "config.toml").is_file()
    assert not (git_repo / ".pi" / "perk.toml").exists()
    assert not git.is_tracked(git_repo, ".pi/workflow/.gitkeep")
    assert (git_repo / ".perk" / "skills" / "foo" / "SKILL.md").is_file()
    assert not legacy_skill.exists()

    # Clean after fix — config + legacy-workflow converge.
    cleaned = _by_name(run_doctor(git_repo, verify=False))
    assert cleaned["config"].status == "ok"
    assert cleaned["legacy-workflow"].status == "ok"

    # The migrated repo-skill converges to `ok` once committed (verify-gated check). Commit the
    # migrated tree and write the fragment via `--fix`, then the plain verify check is `ok`.
    _git(git_repo, "add", "-A")
    _git(git_repo, "commit", "-qm", "migrate")
    _stub_identity(monkeypatch)
    run_doctor(git_repo, fix=True, verify=True)
    assert _by_name(run_doctor(git_repo, verify=True))["repo-skills"].status == "ok"

    # A second `--fix` is idempotent — no `.pi/` path is migrated again.
    again = run_doctor(git_repo, fix=True, verify=False)
    assert not any(".pi/" in line for line in again.fixed)
