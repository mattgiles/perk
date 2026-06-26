"""Tests for the repo-authored-skills substrate (``perk/convergence/init/repo_skills.py``) and
its supporting GitHub gateway read (``perk/github/repo.py``). Dormant substrate: pure
parse/validate/render helpers plus the orchestrator, exercised offline.
"""

import json
import subprocess
from pathlib import Path

import pytest

from perk import github
from perk.convergence.init import repo_skills as rs
from perk.convergence.init.skills import MANAGED_HEADER
from perk.github import GitHubError

# ---------------------------------------------------------------------------
# Pure: frontmatter parsing + validation
# ---------------------------------------------------------------------------

_GOOD_FM = "---\nname: foo\ndescription: A foo skill.\n---\n# body\n"


def test_parse_frontmatter_well_formed():
    fm, reason = rs.parse_skill_frontmatter(_GOOD_FM)
    assert reason is None
    assert fm == {"name": "foo", "description": "A foo skill."}


def test_parse_frontmatter_no_opening_delimiter():
    fm, reason = rs.parse_skill_frontmatter("name: foo\n")
    assert fm == {} and reason and "opening" in reason


def test_parse_frontmatter_no_closing_delimiter():
    fm, reason = rs.parse_skill_frontmatter("---\nname: foo\n")
    assert fm == {} and reason and "closing" in reason


def test_parse_frontmatter_malformed_yaml():
    fm, reason = rs.parse_skill_frontmatter("---\nname: : :\n  bad\n---\n")
    assert fm == {} and reason and "malformed" in reason


def test_parse_frontmatter_non_mapping_body():
    fm, reason = rs.parse_skill_frontmatter("---\n- just\n- a list\n---\n")
    assert fm == {} and reason and "mapping" in reason


def test_validate_skill_ok():
    skill, reason = rs.validate_skill("foo", {"name": "foo", "description": "A foo skill."})
    assert reason is None
    assert skill == rs.RepoSkill(
        name="foo", description="A foo skill.", dir_name="foo", rel_path=".pi/skills/foo/SKILL.md"
    )


def test_validate_skill_missing_name():
    skill, reason = rs.validate_skill("foo", {"description": "d"})
    assert skill is None and reason and "name" in reason


def test_validate_skill_empty_description():
    skill, reason = rs.validate_skill("foo", {"name": "foo", "description": "   "})
    assert skill is None and reason and "description" in reason


def test_validate_skill_name_mismatch():
    skill, reason = rs.validate_skill("foo", {"name": "bar", "description": "d"})
    assert skill is None and reason and "directory name" in reason


# ---------------------------------------------------------------------------
# Pure: rendering
# ---------------------------------------------------------------------------


def test_render_sorts_by_name_and_byte_matches():
    source = rs.RepoSkillSource(alias="perk-acme", url="https://github.com/x/acme", ref="main")
    skills = [
        rs.RepoSkill("zebra", "z", "zebra", ".pi/skills/zebra/SKILL.md"),
        rs.RepoSkill("alpha", "a", "alpha", ".pi/skills/alpha/SKILL.md"),
    ]
    out = rs.render_repo_skills_manifest(source, skills)
    assert out == (
        f"{MANAGED_HEADER}"
        "sources:\n"
        "  perk-acme:\n"
        "    url: https://github.com/x/acme\n"
        "    ref: main\n"
        "skills:\n"
        "  - source: perk-acme\n"
        "    name: alpha\n"
        "  - source: perk-acme\n"
        "    name: zebra\n"
    )


# ---------------------------------------------------------------------------
# derive_repo_source (stubbed gateway read)
# ---------------------------------------------------------------------------


def test_derive_repo_source(monkeypatch):
    monkeypatch.setattr(
        github,
        "repo_identity",
        lambda root: github.RepoIdentity("acme", "https://github.com/x/acme", "main"),
    )
    assert rs.derive_repo_source(Path("/x")) == rs.RepoSkillSource(
        "perk-acme", "https://github.com/x/acme", "main"
    )


# ---------------------------------------------------------------------------
# Orchestrator (git_repo fixture)
# ---------------------------------------------------------------------------


def _plant_skill(
    root: Path, dir_name: str, *, name: str | None = None, desc: str = "A skill."
) -> Path:
    skill = root / ".pi" / "skills" / dir_name / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(f"---\nname: {name or dir_name}\ndescription: {desc}\n---\n# body\n", "utf-8")
    return skill


def _commit(root: Path, *paths: str) -> None:
    subprocess.run(["git", "add", *paths], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "add"], cwd=root, check=True, capture_output=True)


def _stub_identity(monkeypatch, *, name="acme", calls=None):
    def fake(root):
        if calls is not None:
            calls.append(root)
        return github.RepoIdentity(name, f"https://github.com/x/{name}", "main")

    monkeypatch.setattr(github, "repo_identity", fake)


def test_orchestrator_happy_path(git_repo, monkeypatch):
    root = git_repo
    _plant_skill(root, "alpha")
    _plant_skill(root, "beta")
    _commit(root, ".pi")
    _stub_identity(monkeypatch)
    result = rs.build_repo_skills_manifest(root)
    assert result.errors == () and result.warnings == ()
    assert {s.name for s in result.skills} == {"alpha", "beta"}
    assert result.fragment == (
        f"{MANAGED_HEADER}"
        "sources:\n"
        "  perk-acme:\n"
        "    url: https://github.com/x/acme\n"
        "    ref: main\n"
        "skills:\n"
        "  - source: perk-acme\n"
        "    name: alpha\n"
        "  - source: perk-acme\n"
        "    name: beta\n"
    )


def test_orchestrator_no_skills_skips_network(git_repo, monkeypatch):
    calls: list = []
    _stub_identity(monkeypatch, calls=calls)
    result = rs.build_repo_skills_manifest(git_repo)
    assert result == rs.RepoSkillsManifest(None, (), (), ())
    assert calls == []  # the GitHub read was never reached


def test_orchestrator_no_github_remote(git_repo, monkeypatch):
    root = git_repo
    _plant_skill(root, "alpha")
    _commit(root, ".pi")

    def boom(root):
        raise GitHubError("no remote")

    monkeypatch.setattr(github, "repo_identity", boom)
    result = rs.build_repo_skills_manifest(root)
    assert result.fragment is None
    assert any("GitHub origin" in e for e in result.errors)


def test_orchestrator_alias_collision(git_repo, monkeypatch):
    root = git_repo
    _plant_skill(root, "alpha")
    _commit(root, ".pi")
    manifest = root / ".agents" / "manifest.yaml"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text("sources:\n  perk-acme:\n    url: u\n    ref: main\nskills: []\n", "utf-8")
    _stub_identity(monkeypatch)
    result = rs.build_repo_skills_manifest(root)
    assert result.fragment is None
    assert any("already exists" in e for e in result.errors)


def test_orchestrator_self_fragment_not_a_collision(git_repo, monkeypatch):
    root = git_repo
    _plant_skill(root, "alpha")
    _commit(root, ".pi")
    # Our own previously-rendered fragment declaring the same alias must be self-excluded.
    frag = root / ".agents" / "manifest.d" / rs.REPO_SKILLS_MANIFEST_FILENAME
    frag.parent.mkdir(parents=True, exist_ok=True)
    frag.write_text("sources:\n  perk-acme:\n    url: u\n    ref: main\nskills: []\n", "utf-8")
    _stub_identity(monkeypatch)
    result = rs.build_repo_skills_manifest(root)
    assert result.fragment is not None and result.errors == ()


def test_orchestrator_untracked_warning(git_repo, monkeypatch):
    root = git_repo
    _plant_skill(root, "alpha")  # planted but NOT committed
    _stub_identity(monkeypatch)
    result = rs.build_repo_skills_manifest(root)
    assert result.fragment is not None and result.errors == ()
    assert any(".pi/skills/alpha/SKILL.md" in w for w in result.warnings)


def test_orchestrator_duplicate_name(git_repo, monkeypatch):
    root = git_repo
    _plant_skill(root, "alpha")
    # A tracked SKILL.md outside .pi/skills/ with the same frontmatter name.
    other = root / "skills" / "alpha" / "SKILL.md"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text("---\nname: alpha\ndescription: d\n---\n", "utf-8")
    _commit(root, ".pi", "skills")
    _stub_identity(monkeypatch)
    result = rs.build_repo_skills_manifest(root)
    assert result.fragment is None
    assert any("collides" in e for e in result.errors)


def test_orchestrator_frontmatter_error_skips_network(git_repo, monkeypatch):
    root = git_repo
    skill = root / ".pi" / "skills" / "alpha" / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text("no frontmatter here\n", "utf-8")
    _commit(root, ".pi")
    calls: list = []
    _stub_identity(monkeypatch, calls=calls)
    result = rs.build_repo_skills_manifest(root)
    assert result.fragment is None and result.errors
    assert calls == []  # offline failure → network skipped


# ---------------------------------------------------------------------------
# Gateway: github.repo_identity
# ---------------------------------------------------------------------------


def test_repo_identity_parses(monkeypatch):
    payload = json.dumps(
        {"name": "acme", "url": "https://github.com/x/acme", "defaultBranchRef": {"name": "main"}}
    )
    monkeypatch.setattr(
        subprocess, "run", lambda args, **_: subprocess.CompletedProcess(args, 0, payload, "")
    )
    ident = github.repo_identity(Path("/x"))
    assert ident == github.RepoIdentity("acme", "https://github.com/x/acme", "main")


def test_repo_identity_nonzero_raises(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **_: subprocess.CompletedProcess(args, 1, "", "no remote"),
    )
    with pytest.raises(GitHubError):
        github.repo_identity(Path("/x"))


def test_repo_identity_missing_default_branch_raises(monkeypatch):
    payload = json.dumps({"name": "acme", "url": "https://github.com/x/acme"})
    monkeypatch.setattr(
        subprocess, "run", lambda args, **_: subprocess.CompletedProcess(args, 0, payload, "")
    )
    with pytest.raises(GitHubError):
        github.repo_identity(Path("/x"))
