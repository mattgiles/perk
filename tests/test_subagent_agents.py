"""Convergence tests for `_converge_subagent_agents` (the `subagent-agents` capability).

perk delivers its agent defs (`PERK_AGENTS`) into the consumer-owned `.pi/agents/perk/`
subdir, byte-for-byte from the bundled `agents/` sources, as a committed managed convergence:
fresh delivery, idempotency, drift rewrite, stray pruning, and `apply=False` dry-run parity.
"""

import yaml

from perk import _resources
from perk.convergence.init import PERK_AGENTS, _converge_subagent_agents


def _source_bytes(name):
    return (_resources.agents_dir() / f"{name}.md").read_bytes()


def test_fresh_delivery_writes_all_defs_byte_identical(tmp_path):
    changes = _converge_subagent_agents(tmp_path, apply=True)
    perk_dir = tmp_path / ".pi" / "agents" / "perk"
    for name in PERK_AGENTS:
        target = perk_dir / f"{name}.md"
        assert target.is_file()
        assert target.read_bytes() == _source_bytes(name)
        assert f".pi/agents/perk/{name}.md: created" in changes
    # The committed `.gitkeep` keeps `.pi/agents/` present.
    assert (tmp_path / ".pi" / "agents" / ".gitkeep").is_file()
    assert ".pi/agents/: created" in changes


def test_reviewer_defs_source_bind_only_the_exact_ponytail_skill_paths():
    package_skills = "../../npm/node_modules/@dietrichgebert/ponytail/skills"
    expected = {
        "draft-reviewer": (
            f"{package_skills}/ponytail/SKILL.md",
            ".pi/npm/node_modules/@dietrichgebert/ponytail/skills/ponytail/SKILL.md",
            "ponytail",
        ),
        "pr-reviewer": (
            f"{package_skills}/ponytail-review/SKILL.md",
            ".pi/npm/node_modules/@dietrichgebert/ponytail/skills/ponytail-review/SKILL.md",
            "ponytail-review",
        ),
        "adversarial-reviewer": (
            f"{package_skills}/ponytail-review/SKILL.md",
            ".pi/npm/node_modules/@dietrichgebert/ponytail/skills/ponytail-review/SKILL.md",
            "ponytail-review",
        ),
    }
    for name, (skill_path, runtime_path, skill_name) in expected.items():
        text = _source_bytes(name).decode()
        frontmatter = yaml.safe_load(text.split("---", 2)[1])
        assert frontmatter["inheritSkills"] is False
        assert frontmatter["skillPath"] == [skill_path]
        assert "skills" not in frontmatter
        assert "**Source-bound Ponytail check.**" in text
        assert runtime_path in text
        assert f"frontmatter name is `{skill_name}`" in text
        compact = " ".join(text.split())
        assert "terminate without calling `structured_output`" in compact
        assert "never resolve a same-named project/user skill" in compact


def test_committed_reviewer_mirrors_are_byte_identical():
    root = _resources.agents_dir().parent
    for name in ("draft-reviewer", "pr-reviewer", "adversarial-reviewer"):
        mirror = root / ".pi" / "agents" / "perk" / f"{name}.md"
        assert mirror.read_bytes() == _source_bytes(name)


def test_second_run_is_idempotent(tmp_path):
    _converge_subagent_agents(tmp_path, apply=True)
    assert _converge_subagent_agents(tmp_path, apply=True) == []


def test_drifted_def_is_rewritten(tmp_path):
    _converge_subagent_agents(tmp_path, apply=True)
    drifted = tmp_path / ".pi" / "agents" / "perk" / f"{PERK_AGENTS[0]}.md"
    drifted.write_text("hand-edited drift\n", encoding="utf-8")
    changes = _converge_subagent_agents(tmp_path, apply=True)
    assert changes == [f".pi/agents/perk/{PERK_AGENTS[0]}.md: updated"]
    assert drifted.read_bytes() == _source_bytes(PERK_AGENTS[0])


def test_stray_in_perk_subdir_is_removed_but_user_agents_untouched(tmp_path):
    _converge_subagent_agents(tmp_path, apply=True)
    perk_dir = tmp_path / ".pi" / "agents" / "perk"
    stray = perk_dir / "stray.md"
    stray.write_text("not a perk agent\n", encoding="utf-8")
    # A user's own top-level agent must never be touched.
    mine = tmp_path / ".pi" / "agents" / "mine.md"
    mine.write_text("user agent\n", encoding="utf-8")

    changes = _converge_subagent_agents(tmp_path, apply=True)
    assert changes == [".pi/agents/perk/stray.md: removed"]
    assert not stray.exists()
    assert mine.read_text(encoding="utf-8") == "user agent\n"


def test_apply_false_returns_same_change_list_without_writing(tmp_path):
    # Fresh repo: dry-run reports every create but writes nothing.
    dry = _converge_subagent_agents(tmp_path, apply=False)
    assert not (tmp_path / ".pi" / "agents" / "perk").exists()
    assert not (tmp_path / ".pi" / "agents" / ".gitkeep").exists()
    # Applying yields the identical change list.
    assert _converge_subagent_agents(tmp_path, apply=True) == dry
