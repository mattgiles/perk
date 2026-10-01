"""The prompt guard's Python half (contracts.md §8.40): a carrier may name only tools eligible in
every (stage, mode) landing it has.

The TS half (`extension/substrate/stageTools.test.ts`) covers the warm drives and the gated
contexts from the live catalog; this half covers what only the Python plane launches — the cold-door
seed templates, the composed `prompts/common/**` fragments they interpolate, and the stage-bound
skill bodies — against the derived matrix both planes share (`shared/fixtures/tool-matrix.json`,
drift-guarded by `extension/substrate/toolMatrix.test.ts`).

Coverage, stated narrowly: the raw seed/fragment/skill SOURCE text (Jinja tags included).
Dynamic DATA blocks, interpolated runtime values and user transclusions are out of scope.

The match rule is shared with the TS half: the scan universe is the matrix's perk- and
foreign-owned names (builtins excluded — never stage-scoped, and `read`/`write`/`find` are
ordinary English); a name containing `_` matches as a bare word, a single-word name only
backtick-quoted (an unquoted single-word mention is an accepted, recorded miss).
"""

import json
import re
from pathlib import Path

import pytest

from perk.substrate.registry import load_registry
from perk.substrate.skill_exposure import parse_skill_frontmatter, parse_stages_field

REPO_ROOT = Path(__file__).resolve().parents[1]
MATRIX = json.loads((REPO_ROOT / "shared" / "fixtures" / "tool-matrix.json").read_text("utf-8"))
REGISTRY = load_registry(REPO_ROOT / "shared" / "registry.yaml")
STAGE_MODES = {stage.id: stage.mode for stage in REGISTRY.stages}
PROMPTS = REPO_ROOT / "prompts"

type Landing = tuple[str, str]
"""One (stage id, mode) landing a carrier can have."""

WORKTREE_RW: tuple[Landing, ...] = tuple(
    (stage, "read-write") for stage in ("implement", "submit", "address", "land", "learn")
)

# Each cold-door seed → its door's (stage id, registry mode); composed fragments → the union of
# their interpolators' landings.
LANDINGS: dict[str, tuple[Landing, ...]] = {
    "stages/objective-plan/seed.md": (("objective-plan", "read-only"),),
    "stages/objective-refine/seed.md": (("objective-refine", "read-only"),),
    "stages/gist-author/seed.md": (("gist-author", "read-only"),),
    "stages/objective-author/seed.md": (("objective-author", "read-only"),),
    "stages/objective-author/file.md": (("objective-author", "read-only"),),
    "stages/objective-author/adopt.md": (("objective-author", "read-only"),),
    "stages/objective-replan.md": (("objective-author", "read-only"),),
    "stages/learn-harvest.md": (("objective-author", "read-only"),),
    "stages/learn-dream.md": (("objective-author", "read-only"),),
    "stages/plan-from/file.md": (("plan", "read-only"),),
    "stages/plan-from/adopt.md": (("plan", "read-only"),),
    "stages/replan.md": (("plan", "read-only"),),
    "stages/learn-code.md": (("plan", "read-only"),),
    "stages/learn-docs.md": (("plan", "read-only"),),
    "stages/audit.md": (("audit", "read-only"),),
    "stages/implement.md": (("implement", "read-write"),),
    "stages/stack-review/cold.md": (("stack-review", "read-write"),),
    # The worker-launched worktree prompts (the warm drives of the same templates are TS rows).
    "stages/learn.md": (("learn", "read-write"),),
    "stages/address/preview.md": (("address", "read-write"),),
    "stages/address/action.md": (("address", "read-write"),),
    # The write-capable cold doors borrowing the `save` stage descriptor.
    "stages/skills/create.md": (("save", "read-write"),),
    "stages/skills/create-from.md": (("save", "read-write"),),
    "stages/skills/refine.md": (("save", "read-write"),),
    "stages/librarian/add-docs.md": (("save", "read-write"),),
    "stages/librarian/refresh-docs.md": (("save", "read-write"),),
    # Composed fragments.
    "common/objective-read/linear.md": (
        ("objective-plan", "read-only"),
        ("objective-refine", "read-only"),
        ("objective-author", "read-only"),
    ),
    "common/plan-read/linear.md": (("plan", "read-only"), *WORKTREE_RW),
    # The learn factories' save step: the cold door's review-first carrier, and the warm door's
    # explicit plan_save carrier (it runs only where that tool is active; the unscoped landing is
    # the TS half's row).
    "common/learn-save/cold.md": (("plan", "read-only"),),
    "common/learn-save/warm.md": (
        ("plan", "read-write"),
        ("save", "read-write"),
        ("objective-plan", "read-write"),
    ),
}

# Fragments that name no tool at all (the census still requires every fragment be classified).
TOOL_FREE_FRAGMENTS = frozenset(
    {
        "common/plan-read/github.md",
        "common/plan-read/other.md",
        "common/resume-advisory.md",
        "common/review-wave-yield.md",
    }
)

# Stage templates delivered only as warm drives — every one is a row of the TS half's table.
WARM_ONLY = frozenset(
    {
        "stages/conflict-resolution.md",
        "stages/conflict-resolution-continuation.md",
        "stages/gist-save.md",
        "stages/learn-orchestrate.md",
        "stages/objective-land.md",
        "stages/objective-plan/guidance.md",
        "stages/objective-reconcile.md",
        "stages/objective-reconcile-ready.md",
        "stages/objective-recover.md",
        "stages/objective-review-browser.md",
        "stages/objective-save.md",
        "stages/objective-sync.md",
        "stages/plan-review-browser.md",
        "stages/pr-review.md",
        "stages/pr-review-browser/active.md",
        "stages/pr-review-browser/foreign.md",
        "stages/pr-review-terminal/active.md",
        "stages/pr-review-terminal/foreign.md",
        "stages/pr-review-terminal/local.md",
        "stages/simplify.md",
        "stages/stack-review-browser/stack.md",
    }
)


def _scan_universe() -> list[str]:
    return sorted(name for name, entry in MATRIX["tools"].items() if entry["owner"] != "builtin")


def _mention(name: str) -> re.Pattern[str]:
    if "_" in name:
        return re.compile(rf"\b{re.escape(name)}\b")
    return re.compile(rf"`{re.escape(name)}`")


def referenced_tools(text: str) -> list[str]:
    """Every scan-universe tool name the text references, under the shared match rule."""
    return [name for name in _scan_universe() if _mention(name).search(text)]


def eligible(stage: str | None, mode: str) -> set[str]:
    key = "unscoped" if stage is None else stage
    return set(MATRIX["eligible"][key][mode])


def _violations(label: str, text: str, landings: tuple[Landing, ...]) -> list[str]:
    named = referenced_tools(text)
    return [
        f"{label} names `{name}` — ineligible in ({stage}, {mode})"
        for stage, mode in landings
        for name in named
        if name not in eligible(stage, mode)
    ]


def _skill_landings() -> list[tuple[Path, tuple[Landing, ...]]]:
    rows: list[tuple[Path, tuple[Landing, ...]]] = []
    for path in sorted((REPO_ROOT / "skills").glob("perk-*/SKILL.md")):
        frontmatter, problem = parse_skill_frontmatter(path.read_text(encoding="utf-8"))
        assert problem is None, f"{path}: {problem}"
        stages = parse_stages_field(frontmatter)
        if stages in ("all", "malformed"):
            continue
        rows.append((path, tuple((stage, STAGE_MODES[stage]) for stage in sorted(stages))))
    return rows


def test_matrix_shape_matches_the_registry() -> None:
    assert MATRIX["stages"] == [stage.id for stage in REGISTRY.stages]
    assert set(MATRIX["eligible"]) == {*STAGE_MODES, "unscoped"}


@pytest.mark.parametrize("template", sorted(LANDINGS))
def test_prompt_carriers_name_only_eligible_tools(template: str) -> None:
    text = (PROMPTS / template).read_text(encoding="utf-8")
    assert _violations(template, text, LANDINGS[template]) == []


@pytest.mark.parametrize(
    ("path", "landings"),
    _skill_landings(),
    ids=lambda value: value.parent.name if isinstance(value, Path) else "",
)
def test_stage_bound_skill_bodies_name_only_eligible_tools(
    path: Path, landings: tuple[Landing, ...]
) -> None:
    text = path.read_text(encoding="utf-8")
    assert _violations(str(path.relative_to(REPO_ROOT)), text, landings) == []


def test_every_seed_landing_is_a_real_registry_stage_at_its_mode() -> None:
    for template, landings in LANDINGS.items():
        for stage, mode in landings:
            assert stage in STAGE_MODES, f"{template}: unknown stage {stage}"
            assert mode in ("read-only", "read-write"), f"{template}: bad mode {mode}"


def test_every_stage_template_is_classified() -> None:
    stages = {path.relative_to(PROMPTS).as_posix() for path in (PROMPTS / "stages").rglob("*.md")}
    classified = {key for key in LANDINGS if key.startswith("stages/")} | WARM_ONLY
    assert stages - classified == set(), "classify every new stage template (row or WARM_ONLY)"
    assert classified - stages == set(), "stale classification rows"
    assert not (WARM_ONLY & set(LANDINGS)), "a template is either a landing row or warm-only"


def test_every_common_fragment_is_classified() -> None:
    fragments = {
        path.relative_to(PROMPTS).as_posix() for path in (PROMPTS / "common").rglob("*.md")
    }
    classified = {key for key in LANDINGS if key.startswith("common/")} | TOOL_FREE_FRAGMENTS
    assert fragments - classified == set(), "classify every new fragment (row or TOOL_FREE)"
    assert classified - fragments == set(), "stale classification rows"
    for fragment in TOOL_FREE_FRAGMENTS:
        assert referenced_tools((PROMPTS / fragment).read_text(encoding="utf-8")) == [], fragment


def test_match_rule_representative_cases() -> None:
    assert referenced_tools("edit/write are blocked; the plan is ready") == []
    assert referenced_tools("then call `submit`") == ["submit"]
    assert "submit" not in eligible("plan", "read-only")
    assert referenced_tools("when ready, submit the work") == []
    assert referenced_tools("fall back to plan_save") == ["plan_save"]
    assert "plan_save" not in eligible("objective-plan", "read-only")
    assert referenced_tools("`subagent` and subagent_supervisor") == [
        "subagent",
        "subagent_supervisor",
    ]
    assert "read" not in _scan_universe()
    assert "write" not in _scan_universe()
