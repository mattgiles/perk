"""The layered skills-exposure resolution matrix (contracts.md §8.39).

Pure `tmp_path` scaffolds: project skills under `.agents/skills/`, npm-package skills under
`.pi/npm/node_modules/`, the `[skills]` policy passed directly. `defaults=[]` keeps the shipped
binding set out of the matrix except where a test exercises the bound-skill union.
"""

import json
from pathlib import Path

from perk.substrate.bindings import Binding
from perk.substrate.skill_exposure import (
    SkillsPolicy,
    parse_stages_field,
    skill_exposure_argv,
)

# --- scaffolding -----------------------------------------------------------------


def _skill_md(name: str, stages: str | None = None) -> str:
    lines = ["---", f"name: {name}", "description: d"]
    if stages is not None:
        lines.append(f"stages: {stages}")
    lines += ["---", "", "body", ""]
    return "\n".join(lines)


def _add_skill(repo: Path, name: str, stages: str | None = None, *, text: str | None = None):
    d = repo / ".agents" / "skills" / name
    d.mkdir(parents=True)
    body = text if text is not None else _skill_md(name, stages)
    (d / "SKILL.md").write_text(body, encoding="utf-8")


def _write_settings(repo: Path, packages: list) -> None:
    (repo / ".pi").mkdir(exist_ok=True)
    (repo / ".pi" / "settings.json").write_text(
        json.dumps({"packages": packages}), encoding="utf-8"
    )


def _add_package(
    repo: Path,
    name: str,
    *,
    pi_skills: list | None = None,
    skills: tuple[str, ...] = (),
    skills_root: str = "skills",
) -> None:
    pkg = repo / ".pi" / "npm" / "node_modules" / name
    pkg.mkdir(parents=True)
    package_json: dict = {"name": name}
    if pi_skills is not None:
        package_json["pi"] = {"skills": pi_skills}
    (pkg / "package.json").write_text(json.dumps(package_json), encoding="utf-8")
    for skill in skills:
        d = pkg / skills_root / skill
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(_skill_md(skill), encoding="utf-8")


def _compose(
    repo: Path,
    stage_id: str = "implement",
    *,
    trigger: str | None = None,
    policy: SkillsPolicy | None = None,
    user_bindings: list[Binding] | None = None,
    defaults: list[Binding] | None = None,
) -> tuple[list[str], list[str]]:
    return skill_exposure_argv(
        repo,
        stage_id=stage_id,
        trigger=trigger or f"stage:{stage_id}",
        policy=policy or SkillsPolicy(),
        user_bindings=user_bindings or [],
        defaults=defaults if defaults is not None else [],
    )


def _skill_paths(args: list[str]) -> list[str]:
    return [args[i + 1] for i, arg in enumerate(args) if arg == "--skill"]


# A minimal engaging policy for tests whose subject is not the engagement rule itself.
_ENGAGED = SkillsPolicy(include_packages=True)


# --- parse_stages_field ----------------------------------------------------------


def test_parse_stages_field_vocabulary():
    assert parse_stages_field({}) == "all"
    assert parse_stages_field({"stages": "all"}) == "all"
    assert parse_stages_field({"stages": ["plan", " implement "]}) == frozenset(
        {"plan", "implement"}
    )
    assert parse_stages_field({"stages": []}) == frozenset()
    # Malformed shapes: wrong type, non-string entries, blank entries, an unknown string.
    for bad in (5, True, None, {"a": 1}, [1], [""], ["plan", None], "everything"):
        assert parse_stages_field({"stages": bad}) == "malformed"


# --- the three-layer resolution matrix -------------------------------------------


def test_undeclared_skill_exposed_everywhere(tmp_path):
    _add_skill(tmp_path, "plain")
    for stage_id in ("plan", "implement", "learn"):
        args, _ = _compose(tmp_path, stage_id, policy=_ENGAGED)
        assert ".agents/skills/plain" in _skill_paths(args)


def test_stages_all_is_undeclared_equivalent(tmp_path):
    _add_skill(tmp_path, "wide", "all")
    for stage_id in ("plan", "implement"):
        args, warnings = _compose(tmp_path, stage_id)
        assert ".agents/skills/wide" in _skill_paths(args)
        assert warnings == []


def test_declared_list_exposes_member_stages_only(tmp_path):
    _add_skill(tmp_path, "narrow", "[plan, implement]")
    assert ".agents/skills/narrow" in _skill_paths(_compose(tmp_path, "implement")[0])
    assert ".agents/skills/narrow" in _skill_paths(_compose(tmp_path, "plan")[0])
    assert ".agents/skills/narrow" not in _skill_paths(_compose(tmp_path, "learn")[0])


def test_explicit_empty_list_exposes_nowhere(tmp_path):
    _add_skill(tmp_path, "interactive-only", "[]")
    for stage_id in ("plan", "implement", "learn"):
        args, _ = _compose(tmp_path, stage_id)
        assert _skill_paths(args) == []
        assert args[0] == "--no-skills"  # declared -> engaged, so scoping is on


def test_config_row_narrows_frontmatter_and_undeclared(tmp_path):
    _add_skill(tmp_path, "wide", "all")
    _add_skill(tmp_path, "plain")
    policy = SkillsPolicy(stages={"wide": ("plan",), "plain": ("plan",)})
    assert _skill_paths(_compose(tmp_path, "implement", policy=policy)[0]) == []
    assert _skill_paths(_compose(tmp_path, "plan", policy=policy)[0]) == [
        ".agents/skills/plain",
        ".agents/skills/wide",
    ]


def test_config_all_row_rewidens_narrow_frontmatter(tmp_path):
    _add_skill(tmp_path, "narrow", "[plan]")
    policy = SkillsPolicy(stages={"narrow": None})  # "all" re-widening
    assert ".agents/skills/narrow" in _skill_paths(
        _compose(tmp_path, "implement", policy=policy)[0]
    )


def test_empty_config_row_hides_unless_bound(tmp_path):
    _add_skill(tmp_path, "killed")
    policy = SkillsPolicy(stages={"killed": ()})
    assert _skill_paths(_compose(tmp_path, "implement", policy=policy)[0]) == []
    # The bound-skill union trumps the `= []` row (and any frontmatter exclusion).
    bound = [Binding("stage:implement", "killed", "nudge")]
    args, _ = _compose(tmp_path, "implement", policy=policy, user_bindings=bound)
    assert ".agents/skills/killed" in _skill_paths(args)
    # ...but only on the launch trigger the binding names.
    args, _ = _compose(tmp_path, "plan", policy=policy, user_bindings=bound)
    assert _skill_paths(args) == []


def test_bound_skill_trumps_frontmatter_exclusion(tmp_path):
    _add_skill(tmp_path, "hidden", "[]")
    bound = [Binding("stage:implement", "hidden", "nudge")]
    args, _ = _compose(tmp_path, "implement", user_bindings=bound)
    assert ".agents/skills/hidden" in _skill_paths(args)


def test_bound_but_missing_skill_still_yields_entry(tmp_path):
    # A dangling binding still produces the delivery-path arg — pi emits its own
    # missing-path diagnostic (the existing dangling-binding symptom).
    bound = [Binding("command:learn-docs", "ghost", "nudge")]
    args, _ = _compose(
        tmp_path, "plan", trigger="command:learn-docs", policy=_ENGAGED, user_bindings=bound
    )
    assert _skill_paths(args) == [".agents/skills/ghost"]


def test_malformed_frontmatter_exposed_with_warning(tmp_path):
    _add_skill(tmp_path, "broken", text="---\nname: broken\nno closing delimiter\n")
    args, warnings = _compose(tmp_path, "implement", policy=_ENGAGED)
    assert ".agents/skills/broken" in _skill_paths(args)
    assert any("broken/SKILL.md" in w for w in warnings)


def test_malformed_stages_exposed_with_warning(tmp_path):
    _add_skill(tmp_path, "odd", "5")
    args, warnings = _compose(tmp_path, "implement")
    assert ".agents/skills/odd" in _skill_paths(args)  # fail-open: treated as all
    assert any("malformed `stages:`" in w for w in warnings)


def test_unknown_stage_ids_kept_inert(tmp_path):
    # Registry-free parsing: an unknown id neither raises nor exposes elsewhere.
    _add_skill(tmp_path, "future", "[not-a-stage]")
    assert _skill_paths(_compose(tmp_path, "implement")[0]) == []
    assert _compose(tmp_path, "implement")[1] == []


# --- engagement (zero-change rollout) --------------------------------------------


def test_unengaged_repo_composes_nothing(tmp_path):
    _add_skill(tmp_path, "plain")  # undeclared skills alone do not engage
    _write_settings(tmp_path, ["npm:pkg"])
    _add_package(tmp_path, "pkg", pi_skills=["./skills"], skills=("p-skill",))
    assert _compose(tmp_path, "implement") == ([], [])


def test_each_engagement_signal_alone_engages(tmp_path):
    signals = [
        SkillsPolicy(stages={"x": ("plan",)}),
        SkillsPolicy(include_dirs=("dir",)),
        SkillsPolicy(include_packages=False),
        SkillsPolicy(include_packages=True),  # explicitly set counts, even as the default value
    ]
    for policy in signals:
        args, _ = _compose(tmp_path, "implement", policy=policy)
        assert args[0] == "--no-skills"


def test_frontmatter_declaration_alone_engages(tmp_path):
    _add_skill(tmp_path, "declared", "all")
    _add_skill(tmp_path, "plain")
    args, _ = _compose(tmp_path, "implement")
    assert args[0] == "--no-skills"
    assert _skill_paths(args) == [".agents/skills/declared", ".agents/skills/plain"]


def test_package_declaration_alone_engages(tmp_path):
    _write_settings(tmp_path, ["npm:pkg"])
    _add_package(tmp_path, "pkg", pi_skills=["./skills"])
    d = tmp_path / ".pi/npm/node_modules/pkg/skills/scoped"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(_skill_md("scoped", "[implement]"), encoding="utf-8")
    args, _ = _compose(tmp_path, "implement")
    assert args == ["--no-skills", "--skill", ".pi/npm/node_modules/pkg/skills/scoped"]
    assert _compose(tmp_path, "plan")[0] == ["--no-skills"]


def test_unengaged_is_silent_even_on_package_tier_trouble(tmp_path):
    # No declarations + no config: byte-identical launch means no warnings either.
    _write_settings(tmp_path, ["npm:absent-pkg"])
    assert _compose(tmp_path, "implement") == ([], [])


# --- include_dirs ------------------------------------------------------------------


def test_include_dirs_tilde_expansion_and_relative_resolution(tmp_path):
    policy = SkillsPolicy(include_dirs=("~/myskills", "rel/dir"))
    args, _ = _compose(tmp_path, "implement", policy=policy)
    assert _skill_paths(args) == [
        str(Path.home() / "myskills"),
        str(tmp_path / "rel" / "dir"),  # relative -> repo root, passed absolute
    ]


def test_composed_ordering_whitelist_packages_project(tmp_path):
    _add_skill(tmp_path, "zeta")
    _add_skill(tmp_path, "alpha", "[implement]")
    _write_settings(tmp_path, ["npm:pkg"])
    _add_package(tmp_path, "pkg", pi_skills=["./skills"], skills=("p-skill",))
    policy = SkillsPolicy(include_dirs=("wl",))
    args, warnings = _compose(tmp_path, "implement", policy=policy)
    assert args[0] == "--no-skills"
    assert _skill_paths(args) == [
        str(tmp_path / "wl"),
        ".pi/npm/node_modules/pkg/skills/p-skill",
        ".agents/skills/alpha",  # project tier sorted by name
        ".agents/skills/zeta",
    ]
    assert warnings == []


# --- the npm-package tier ----------------------------------------------------------


def test_package_skills_config_narrowable_by_name(tmp_path):
    _write_settings(tmp_path, ["npm:pkg"])
    _add_package(tmp_path, "pkg", pi_skills=["./skills"], skills=("p-skill",))
    policy = SkillsPolicy(stages={"p-skill": ("plan",)})
    assert _skill_paths(_compose(tmp_path, "implement", policy=policy)[0]) == []
    assert _skill_paths(_compose(tmp_path, "plan", policy=policy)[0]) == [
        ".pi/npm/node_modules/pkg/skills/p-skill"
    ]


def test_package_conventional_skills_dir_fallback(tmp_path):
    _write_settings(tmp_path, [{"source": "npm:@scope/pkg"}])  # object-form {source} row
    _add_package(tmp_path, "@scope/pkg", skills=("conv-skill",))  # no pi.skills declared
    args, _ = _compose(tmp_path, "implement", policy=_ENGAGED)
    assert ".pi/npm/node_modules/@scope/pkg/skills/conv-skill" in _skill_paths(args)


def test_package_root_without_children_degrades_to_wholesale_root(tmp_path):
    _write_settings(tmp_path, ["npm:pkg"])
    _add_package(tmp_path, "pkg", pi_skills=["./skills"])
    root = tmp_path / ".pi/npm/node_modules/pkg/skills"
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(_skill_md("pkg"), encoding="utf-8")  # not one-level-nested
    args, _ = _compose(tmp_path, "implement", policy=_ENGAGED)
    assert ".pi/npm/node_modules/pkg/skills" in _skill_paths(args)


def test_package_pattern_pi_skills_degrades_to_wholesale_package(tmp_path):
    _write_settings(tmp_path, ["npm:pkg"])
    _add_package(tmp_path, "pkg", pi_skills=["skills/*"], skills=("p-skill",))
    args, _ = _compose(tmp_path, "implement", policy=_ENGAGED)
    assert ".pi/npm/node_modules/pkg" in _skill_paths(args)
    assert ".pi/npm/node_modules/pkg/skills/p-skill" not in _skill_paths(args)


def test_local_path_and_git_packages_not_enumerated(tmp_path):
    # First-party skills come from .agents/skills full stop — no committed-skills/ fallback.
    _write_settings(tmp_path, ["..", "git:github.com/o/r", "npm:pkg@1.2.3"])
    _add_package(tmp_path, "pkg", pi_skills=["./skills"], skills=("p-skill",))
    args, warnings = _compose(tmp_path, "implement", policy=_ENGAGED)
    assert _skill_paths(args) == [".pi/npm/node_modules/pkg/skills/p-skill"]
    assert warnings == []


def test_include_packages_false_omits_the_tier(tmp_path):
    _write_settings(tmp_path, ["npm:pkg"])
    _add_package(tmp_path, "pkg", pi_skills=["./skills"], skills=("p-skill",))
    args, warnings = _compose(tmp_path, "implement", policy=SkillsPolicy(include_packages=False))
    assert args == ["--no-skills"]
    assert warnings == []


def test_object_package_with_skills_disabled_is_never_enumerated(tmp_path):
    _add_skill(tmp_path, "declared", "all")
    _write_settings(
        tmp_path,
        [
            {
                "source": "npm:@dietrichgebert/ponytail",
                "extensions": [],
                "skills": [],
                "prompts": [],
                "themes": [],
            }
        ],
    )
    # No install tree is needed: `skills: []` removes the package from the cold skill tier, so
    # it neither emits --skill nor forces the whole composition to fail open.
    args, warnings = _compose(tmp_path, "implement")
    assert args == ["--no-skills", "--skill", ".agents/skills/declared"]
    assert "ponytail" not in " ".join(args)
    assert warnings == []


def test_other_object_filter_shapes_keep_existing_package_fail_open(tmp_path):
    _add_skill(tmp_path, "declared", "all")
    _write_settings(
        tmp_path,
        [{"source": "npm:@dietrichgebert/ponytail", "skills": ["./skills"]}],
    )
    args, warnings = _compose(tmp_path, "implement")
    assert args == []
    assert any("@dietrichgebert/ponytail" in warning for warning in warnings)


def test_absent_package_dir_degrades_whole_composition(tmp_path):
    _add_skill(tmp_path, "declared", "all")  # engaged via the declaration
    _write_settings(tmp_path, ["npm:ghost"])
    args, warnings = _compose(tmp_path, "implement")
    assert args == []  # unscoped: never per-package skips (they would drop whole packages)
    assert any("ghost" in w for w in warnings)


def test_malformed_settings_json_degrades_whole_composition(tmp_path):
    _add_skill(tmp_path, "declared", "all")
    (tmp_path / ".pi").mkdir()
    (tmp_path / ".pi" / "settings.json").write_text("{not json", encoding="utf-8")
    args, warnings = _compose(tmp_path, "implement")
    assert args == []
    assert any("settings.json" in w for w in warnings)


def test_missing_settings_json_is_no_packages_not_degrade(tmp_path):
    _add_skill(tmp_path, "declared", "all")
    args, warnings = _compose(tmp_path, "implement")
    assert args == ["--no-skills", "--skill", ".agents/skills/declared"]
    assert warnings == []
