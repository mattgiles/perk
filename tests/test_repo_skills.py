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
        name="foo", description="A foo skill.", dir_name="foo", rel_path=".perk/skills/foo/SKILL.md"
    )


def test_validate_skill_stages_field_absent_is_none():
    skill, _ = rs.validate_skill("foo", {"name": "foo", "description": "d"})
    assert skill is not None and skill.stages_field is None


def test_validate_skill_stages_field_list_is_frozenset():
    skill, _ = rs.validate_skill(
        "foo", {"name": "foo", "description": "d", "stages": ["plan", "implement"]}
    )
    assert skill is not None and skill.stages_field == frozenset({"plan", "implement"})


def test_validate_skill_stages_field_all():
    skill, _ = rs.validate_skill("foo", {"name": "foo", "description": "d", "stages": "all"})
    assert skill is not None and skill.stages_field == "all"


def test_validate_skill_stages_field_malformed():
    # Malformed stays advisory (never a validation failure) — doctor warns, exposure fails open.
    skill, reason = rs.validate_skill("foo", {"name": "foo", "description": "d", "stages": 7})
    assert reason is None and skill is not None and skill.stages_field == "malformed"


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
        rs.RepoSkill("zebra", "z", "zebra", ".perk/skills/zebra/SKILL.md"),
        rs.RepoSkill("alpha", "a", "alpha", ".perk/skills/alpha/SKILL.md"),
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
    skill = root / ".perk" / "skills" / dir_name / "SKILL.md"
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
    _commit(root, ".perk")
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
    _commit(root, ".perk")

    def boom(root):
        raise GitHubError("no remote")

    monkeypatch.setattr(github, "repo_identity", boom)
    result = rs.build_repo_skills_manifest(root)
    assert result.fragment is None
    assert any("GitHub origin" in e for e in result.errors)


def test_orchestrator_alias_collision(git_repo, monkeypatch):
    root = git_repo
    _plant_skill(root, "alpha")
    _commit(root, ".perk")
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
    _commit(root, ".perk")
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
    assert any(".perk/skills/alpha/SKILL.md" in w for w in result.warnings)


def test_orchestrator_duplicate_name(git_repo, monkeypatch):
    root = git_repo
    _plant_skill(root, "alpha")
    # A tracked SKILL.md outside .perk/skills/ with the same frontmatter name.
    other = root / "skills" / "alpha" / "SKILL.md"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text("---\nname: alpha\ndescription: d\n---\n", "utf-8")
    _commit(root, ".perk", "skills")
    _stub_identity(monkeypatch)
    result = rs.build_repo_skills_manifest(root)
    assert result.fragment is None
    assert any("collides" in e for e in result.errors)


def test_orchestrator_frontmatter_error_skips_network(git_repo, monkeypatch):
    root = git_repo
    skill = root / ".perk" / "skills" / "alpha" / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text("no frontmatter here\n", "utf-8")
    _commit(root, ".perk")
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


# ---------------------------------------------------------------------------
# Convergence gesture: converge_repo_skills_manifest
# ---------------------------------------------------------------------------

_FRAGMENT_REL = f".agents/manifest.d/{rs.REPO_SKILLS_MANIFEST_FILENAME}"


def _fragment_path(root: Path) -> Path:
    return root / ".agents" / "manifest.d" / rs.REPO_SKILLS_MANIFEST_FILENAME


def test_converge_creates_fragment(git_repo, monkeypatch):
    root = git_repo
    _plant_skill(root, "alpha")
    _commit(root, ".perk")
    _stub_identity(monkeypatch)
    conv = rs.converge_repo_skills_manifest(root, apply=True)
    assert conv.changes == [f"{_FRAGMENT_REL}: created"]
    assert _fragment_path(root).read_text(encoding="utf-8") == conv.manifest.fragment


def test_converge_updates_fragment(git_repo, monkeypatch):
    root = git_repo
    _plant_skill(root, "alpha")
    _commit(root, ".perk")
    _stub_identity(monkeypatch)
    path = _fragment_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# stale\n", encoding="utf-8")
    conv = rs.converge_repo_skills_manifest(root, apply=True)
    assert conv.changes == [f"{_FRAGMENT_REL}: updated"]
    assert path.read_text(encoding="utf-8") == conv.manifest.fragment


def test_converge_removes_stale_fragment(git_repo, monkeypatch):
    # No `.perk/skills/` at all, but a leftover fragment from a since-deleted skill.
    root = git_repo
    path = _fragment_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# leftover\n", encoding="utf-8")
    calls: list = []
    _stub_identity(monkeypatch, calls=calls)
    conv = rs.converge_repo_skills_manifest(root, apply=True)
    assert conv.changes == [f"{_FRAGMENT_REL}: removed"]
    assert not path.exists()
    assert calls == []  # no skills → no network


def test_converge_no_skills_no_fragment_is_noop(git_repo, monkeypatch):
    root = git_repo
    _stub_identity(monkeypatch)
    conv = rs.converge_repo_skills_manifest(root, apply=True)
    assert conv.changes == []
    assert not _fragment_path(root).exists()


def test_converge_errors_do_not_clobber_existing_fragment(git_repo, monkeypatch):
    root = git_repo
    # A previously-good fragment on disk.
    path = _fragment_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# previously good\n", encoding="utf-8")
    # A bad SKILL.md (no frontmatter) makes the manifest fatal → fragment is None + errors.
    skill = root / ".perk" / "skills" / "alpha" / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text("no frontmatter\n", encoding="utf-8")
    _commit(root, ".perk")
    _stub_identity(monkeypatch)
    conv = rs.converge_repo_skills_manifest(root, apply=True)
    assert conv.changes == []
    assert conv.manifest.errors
    assert path.read_text(encoding="utf-8") == "# previously good\n"  # untouched


def test_converge_idempotent_and_dry_run_matches(git_repo, monkeypatch):
    root = git_repo
    _plant_skill(root, "alpha")
    _commit(root, ".perk")
    _stub_identity(monkeypatch)
    # apply=False computes the same change list without writing.
    dry = rs.converge_repo_skills_manifest(root, apply=False)
    assert dry.changes == [f"{_FRAGMENT_REL}: created"]
    assert not _fragment_path(root).exists()
    # First apply writes; second apply is a no-op (idempotent).
    first = rs.converge_repo_skills_manifest(root, apply=True)
    assert first.changes == [f"{_FRAGMENT_REL}: created"]
    second = rs.converge_repo_skills_manifest(root, apply=True)
    assert second.changes == []
