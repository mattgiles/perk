"""Live-corpus guards: every perk-owned skill declares its stage exposure (contracts.md §8.39).

`skills/` (shipped) and `.perk/skills/` (repo-authored) frontmatter must declare a well-formed
`stages:`; the exemptions are verbatim-vendored third-party skills (`ast-grep`, `dignified-python`),
whose frontmatter perk does not own — each is scoped by a committed `[skills.stages]` config row.
The config rows themselves are pinned too: a typo'd skill name or stage id in `[skills.stages]`
is silently inert at runtime, so CI is the loud surface. The config table is parsed directly from
the committed `.perk/config.toml` (never `load_config`) so a developer's gitignored `local.toml`
overlay cannot perturb these guards.
"""

import re
import tomllib
from pathlib import Path

import yaml

from perk.convergence.init.skills import (
    MANAGED_SKILL_NAMES,
    PERK_SKILLS,
    REQUIRED_EXTERNAL_SKILLS,
)
from perk.substrate.config import SkillsTable
from perk.substrate.registry import load_registry
from perk.substrate.skill_exposure import parse_skill_frontmatter, parse_stages_field

REPO_ROOT = Path(__file__).resolve().parents[1]

# The only `skills/` dirs allowed to leave `stages:` undeclared: vendored third-party content
# (upstream-owned frontmatter), declared by a `[skills.stages]` config row instead.
CONFIG_DECLARED_SHIPPED_SKILLS = frozenset({"ast-grep", "dignified-python"})

# Package-bundled skills sanctioned for `[skills.stages]` rows. The known-name universe must be
# static — CI cannot enumerate the gitignored `.pi/npm` tier — so package-skill rows are
# sanctioned by this explicit literal (pi-subagents ships `pi-subagents`; pi-web-access ships
# `librarian`).
PACKAGE_SKILLS = frozenset({"librarian", "pi-subagents"})


def _frontmatters(root: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for md in sorted(root.glob("*/SKILL.md")):
        frontmatter, reason = parse_skill_frontmatter(md.read_text(encoding="utf-8"))
        assert reason is None, f"{md}: {reason}"
        out[md.parent.name] = frontmatter
    return out


def _committed_skills_policy():
    data = tomllib.loads((REPO_ROOT / ".perk" / "config.toml").read_text(encoding="utf-8"))
    return SkillsTable.model_validate(data.get("skills", {})).to_domain()


def test_shipped_skills_declare_stages():
    frontmatters = _frontmatters(REPO_ROOT / "skills")
    # Non-vacuous: a layout change must not silently empty the scan.
    assert len(frontmatters) >= 16, (
        f"only {len(frontmatters)} skills found under skills/ — the corpus scan looks broken"
    )
    stage_ids = load_registry().stage_ids()
    for name, frontmatter in frontmatters.items():
        if name in CONFIG_DECLARED_SHIPPED_SKILLS:
            assert "stages" not in frontmatter, (
                f"skills/{name} declares stages: in frontmatter — drop it from the "
                "config-declared allowlist (vendored frontmatter is upstream-owned)"
            )
            continue
        assert "stages" in frontmatter, f"skills/{name} does not declare stages:"
        parsed = parse_stages_field(frontmatter)
        assert parsed != "malformed", f"skills/{name} has a malformed stages: declaration"
        if isinstance(parsed, frozenset):
            assert parsed <= stage_ids, (
                f"skills/{name} declares unknown stage id(s): {sorted(parsed - stage_ids)}"
            )


def test_config_declared_shipped_skills_have_config_rows():
    # The exemption is declaration-by-config, not declaration-by-nothing: every allowlisted
    # shipped skill must carry a committed `[skills.stages]` row.
    policy = _committed_skills_policy()
    for name in sorted(CONFIG_DECLARED_SHIPPED_SKILLS):
        assert (REPO_ROOT / "skills" / name / "SKILL.md").is_file(), (
            f"{name} is allowlisted but skills/{name}/SKILL.md does not exist"
        )
        assert name in policy.stages, (
            f"skills/{name} is undeclared in frontmatter and has no [skills.stages] row"
        )


def test_repo_authored_skills_declare_stages():
    # Self-repo dogfood of the doctor nudge: every `.perk/skills/` skill declares stages:.
    frontmatters = _frontmatters(REPO_ROOT / ".perk" / "skills")
    assert frontmatters, ".perk/skills/ scan came up empty — the corpus scan looks broken"
    stage_ids = load_registry().stage_ids()
    for name, frontmatter in frontmatters.items():
        assert "stages" in frontmatter, f".perk/skills/{name} does not declare stages:"
        parsed = parse_stages_field(frontmatter)
        assert parsed != "malformed", f".perk/skills/{name} has a malformed stages: declaration"
        if isinstance(parsed, frozenset):
            assert parsed <= stage_ids, (
                f".perk/skills/{name} declares unknown stage id(s): {sorted(parsed - stage_ids)}"
            )


def test_shipped_skill_read_path_pointers_resolve():
    # A shipped skill body that points at `.agents/skills/<name>/SKILL.md` for a name perk never
    # delivers is a silently dangling pointer (the class of bug where `grill-with-docs` sent the
    # model to an absent `grilling` skill). Scan every shipped body and pin each pointer to the
    # managed delivery set.
    pointer = re.compile(r"\.agents/skills/([a-z0-9-]+)/SKILL\.md")
    managed = set(MANAGED_SKILL_NAMES)
    found: list[tuple[str, str]] = []
    for md in sorted((REPO_ROOT / "skills").glob("*/*.md")):
        for name in pointer.findall(md.read_text(encoding="utf-8")):
            found.append((str(md.relative_to(REPO_ROOT)), name))
    assert found, "no read-path pointers found under skills/ — the pointer scan looks broken"
    dangling = [(path, name) for path, name in found if name not in managed]
    assert not dangling, (
        f"skill bodies point at non-managed skills (dangling read paths): {dangling}"
    )


def test_config_stage_rows_reference_known_skills_and_stages():
    # A `[skills.stages]` row keyed by a name no enumerated skill carries is silently inert, as is
    # an unknown stage id — pin both against the full known-name universe.
    policy = _committed_skills_policy()
    manifest = yaml.safe_load((REPO_ROOT / ".agents" / "manifest.yaml").read_text(encoding="utf-8"))
    manifest_names = {entry["name"] for entry in manifest.get("skills", [])}
    repo_authored = {
        p.name for p in (REPO_ROOT / ".perk" / "skills").iterdir() if (p / "SKILL.md").is_file()
    }
    known = (
        set(PERK_SKILLS)
        | {name for _, name in REQUIRED_EXTERNAL_SKILLS}
        | manifest_names
        | repo_authored
        | PACKAGE_SKILLS
    )
    stage_ids = load_registry().stage_ids()
    assert policy.stages, "[skills.stages] scan came up empty — the config rows look broken"
    for name, row in policy.stages.items():
        assert name in known, f"[skills.stages] row {name!r} matches no known skill name (inert)"
        if row is not None:
            unknown = sorted(set(row) - stage_ids)
            assert not unknown, (
                f"[skills.stages] row {name!r} lists unknown stage id(s): {unknown} (inert)"
            )
