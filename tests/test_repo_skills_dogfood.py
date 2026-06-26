"""The offline-verifiable half of the repo-authored-skills dogfood (Objective #863, Node 4.1).

These stitch the *precondition* the manual network dogfood relies on into one coherent gate:
``perk skills scaffold`` writes a frontmatter-valid skill **and** a sync-ready manifest fragment —
the exact input ``skills sync`` consumes to materialize ``.agents/skills/<name>/SKILL.md`` — and
``perk skills refine`` re-opens a skill **without** any sync/reconverge.

The real ``skills`` binary stays out of CI (the source is a GitHub-URL clone, an inherently manual
step); only ``github.repo_identity`` is stubbed so the convergence renders offline. Component
behaviour is covered in ``test_repo_skills.py`` / ``test_skills_cmd.py``; this asserts the
*stitched* precondition as the dogfood gate.
"""

import yaml
from click.testing import CliRunner

from perk import github
from perk.cli.cli import cli
from perk.cli.commands.skills import refine_cmd, shared
from perk.cli.context import PerkContext
from perk.convergence.init import repo_skills as rs
from perk.convergence.init.repo_skills import parse_skill_frontmatter, validate_skill
from perk.substrate.config import Config


def _ctx(repo) -> PerkContext:
    return PerkContext.for_test(
        cwd=repo, repo_root=repo, config=Config(worktree_root=repo / ".worktrees")
    )


def _stub_identity(monkeypatch, *, name="acme"):
    monkeypatch.setattr(
        github,
        "repo_identity",
        lambda root: github.RepoIdentity(name, f"https://github.com/x/{name}", "main"),
    )


def test_scaffold_writes_a_sync_ready_fragment(git_repo, monkeypatch):
    """scaffold demo → valid SKILL.md + a fragment naming source perk-<repo> and skill demo."""
    # Resolve the main checkout to the fixture repo itself (mirrors test_skills_cmd's pin).
    monkeypatch.setattr(shared.git, "main_worktree_root", lambda _root: None)
    _stub_identity(monkeypatch)

    result = CliRunner().invoke(cli, ["skills", "scaffold", "demo"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output

    # 1. The skill itself is frontmatter-valid (the input the author then fills in).
    skill_md = git_repo / ".perk" / "skills" / "demo" / "SKILL.md"
    assert skill_md.is_file()
    mapping, reason = parse_skill_frontmatter(skill_md.read_text(encoding="utf-8"))
    assert reason is None
    skill, vreason = validate_skill("demo", mapping)
    assert vreason is None and skill is not None

    # 2. The converged fragment is exactly what `skills sync` consumes to materialize the link:
    #    a source aliased perk-<repo> (the repo's GitHub URL + default branch) listing skill `demo`.
    fragment = git_repo / ".agents" / "manifest.d" / rs.REPO_SKILLS_MANIFEST_FILENAME
    assert fragment.is_file()
    doc = yaml.safe_load(fragment.read_text(encoding="utf-8"))
    assert doc["sources"] == {"perk-acme": {"url": "https://github.com/x/acme", "ref": "main"}}
    assert doc["skills"] == [{"source": "perk-acme", "name": "demo"}]


def test_refine_re_opens_without_sync(git_repo, monkeypatch):
    """refine demo launches an authoring session but never reconverges / syncs (no sync noise)."""
    # Spy on the reconverge seam scaffold/create use, and on the upstream `skills` pass-through —
    # refine must take neither path.
    converge_calls: list = []
    sync_calls: list = []
    monkeypatch.setattr(
        shared, "converge_repo_skills_manifest", lambda *a, **k: converge_calls.append((a, k))
    )
    monkeypatch.setattr(shared, "run_skills", lambda *a, **k: sync_calls.append((a, k)))
    launches: list = []
    monkeypatch.setattr(refine_cmd.launch, "launch_stage", lambda **kw: launches.append(kw))

    target = git_repo / ".perk" / "skills" / "demo"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("existing body", encoding="utf-8")

    result = CliRunner().invoke(cli, ["skills", "refine", "demo"], obj=_ctx(git_repo))
    assert result.exit_code == 0, result.output

    assert len(launches) == 1  # the refine session launched
    assert converge_calls == []  # but no reconverge
    assert sync_calls == []  # and no `skills sync`
    # The door is read-only on the filesystem until the launched session edits.
    assert (target / "SKILL.md").read_text(encoding="utf-8") == "existing body"
