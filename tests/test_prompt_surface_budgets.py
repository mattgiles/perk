"""Gates #2/#3 of the context-diet gate set: byte ceilings on perk's ambient prompt surfaces.

Gate #2 bounds every perk-authored skill's ambient ``description`` (the discovery cue pi shows
the model); gate #3 bounds every committed prompt template under ``prompts/``, one ceiling per
surface class — SEED/launch vs INJECTED-CONTEXT. The canonical layering rule and carrier map
live in ``shared/contracts.md`` §8.57; these ceilings are the enforced bound that makes carrier
regression loud (prose *shape* stays §8.57 judgment).

Two measurement semantics, deliberately different per surface:

- **descriptions** — UTF-8 bytes of the *parsed* YAML scalar (a quoted/folded description is
  measured by value, never by raw-line bytes);
- **templates** — raw committed file bytes (``wc -c`` semantics: pre-render, frontmatter/CRLF/
  multibyte included). Marker-injected context *values* interpolated at render time are
  unbounded by design — only the committed template is gated.

Each ceiling derives from the measured post-diet maximum * 1.25, rounded up to the next 64-byte
boundary; the derivation is fixed in each constant's comment and does not float with future
scans. A reset is an ordinary human-reviewed code change justified in its PR — no automatic
ratchet, no exemption list.
"""

from pathlib import Path

from perk.convergence.init.skills import PERK_SKILLS
from perk.substrate.skill_exposure import parse_skill_frontmatter

REPO_ROOT = Path(__file__).resolve().parents[1]

# Gate #2: every perk-authored skill's ambient `description` (the parsed frontmatter scalar,
# UTF-8 bytes). Derivation is fixed from the recorded post-diet actual, not the current scan:
# 688 bytes (`skills/perk-expert/SKILL.md` — an ambient-visible knowledge skill whose
# description is a legitimate live trigger surface per shared/contracts.md §8.57) * 1.25 =
# 860.0, rounded up to the next 64-byte boundary = 14 * 64 = 896. A reset is an ordinary
# human-reviewed code change justified in its PR — no automatic ratchet, no exemption list.
SKILL_AMBIENT_DESCRIPTION_MAX_BYTES = 896

# Gate #3, SEED/launch class: every committed template under `prompts/` that is not injected
# context (stages/**, common/** include partials, commit-and-compact.md) — raw committed file
# bytes. Derivation is fixed from the recorded post-diet actual, not the current scan:
# 7,225 bytes (`prompts/stages/pr-review-terminal/active.md` and `foreign.md`, the node-3.3
# post-diet maxima) * 1.25 = 9,031.25, rounded up to the next 64-byte boundary = 142 * 64 =
# 9,088. A reset is an ordinary human-reviewed code change justified in its PR — no automatic
# ratchet, no exemption list (shared/contracts.md §8.57).
SEED_TEMPLATE_MAX_BYTES = 9_088

# Gate #3, INJECTED-CONTEXT class: every committed template under `prompts/contexts/` (adapter
# blocks included — they are injected context surfaces) — raw committed file bytes. Derivation
# is fixed from the recorded post-diet actual, not the current scan: 1,556 bytes
# (`prompts/contexts/plan-authoring.md`, the plan stage's designated flow carrier — legitimately
# the class max per shared/contracts.md §8.57) * 1.25 = 1,945.0, rounded up to the next 64-byte
# boundary = 31 * 64 = 1,984. A reset is an ordinary human-reviewed code change justified in its
# PR — no automatic ratchet, no exemption list.
INJECTED_CONTEXT_TEMPLATE_MAX_BYTES = 1_984

# The gate-#3 universe: every *.md under prompts/ EXCEPT the README (documentation, never
# rendered) and the parity fixtures (test corpus, not shipped prose). A closed rule — prose
# cannot evade the gate by moving into an include partial.
_PROMPTS_ROOT = REPO_ROOT / "prompts"
_TEMPLATE_EXCLUDED = (_PROMPTS_ROOT / "README.md",)
_CONTEXTS_ROOT = _PROMPTS_ROOT / "contexts"
_FIXTURES_ROOT = _PROMPTS_ROOT / "_fixtures"


def _template_files() -> list[Path]:
    return sorted(
        path
        for path in _PROMPTS_ROOT.rglob("*.md")
        if path.is_file()
        and path not in _TEMPLATE_EXCLUDED
        and not path.is_relative_to(_FIXTURES_ROOT)
    )


def _template_offenders(files: list[Path], ceiling: int) -> list[str]:
    return [
        f"{path.relative_to(REPO_ROOT)}: {path.stat().st_size} B > {ceiling} B — diet the "
        "template per shared/contracts.md §8.57 or reset the budget in a reviewed change"
        for path in files
        if path.stat().st_size > ceiling
    ]


def test_skill_ambient_descriptions_within_budget():
    scanned = sorted((REPO_ROOT / "skills").glob("perk-*/SKILL.md"))
    expected = {name for name in PERK_SKILLS if name.startswith("perk-")}
    assert {path.parent.name for path in scanned} == expected, (
        "the skills/perk-*/SKILL.md scan does not match the perk-authored names in "
        "PERK_SKILLS (perk.convergence.init.skills) — update PERK_SKILLS when adding or "
        "removing a perk skill, and keep every perk-authored skill dir carrying a SKILL.md"
    )
    offenders: list[str] = []
    for path in scanned:
        frontmatter, reason = parse_skill_frontmatter(path.read_text(encoding="utf-8"))
        assert reason is None, f"{path.relative_to(REPO_ROOT)}: {reason}"
        description = frontmatter.get("description")
        assert isinstance(description, str) and description.strip(), (
            f"{path.relative_to(REPO_ROOT)}: frontmatter `description` is missing or not a "
            "non-empty string"
        )
        measured = len(description.encode("utf-8"))
        if measured > SKILL_AMBIENT_DESCRIPTION_MAX_BYTES:
            offenders.append(
                f"{path.relative_to(REPO_ROOT)}: description is {measured} B > "
                f"{SKILL_AMBIENT_DESCRIPTION_MAX_BYTES} B — diet the description per "
                "shared/contracts.md §8.57 or reset the budget in a reviewed change"
            )
    assert not offenders, "\n".join(offenders)


def test_seed_templates_within_budget():
    seeds = [path for path in _template_files() if not path.is_relative_to(_CONTEXTS_ROOT)]
    names = {str(path.relative_to(_PROMPTS_ROOT)) for path in seeds}
    # The sentinel, not the floor, carries the layout-drift signal.
    assert "stages/implement.md" in names, (
        "prompts/stages/implement.md is missing from the SEED-class scan — the template "
        "universe rule looks broken"
    )
    assert len(seeds) >= 20, (
        f"only {len(seeds)} SEED-class templates found under prompts/ — the corpus scan "
        "looks broken"
    )
    offenders = _template_offenders(seeds, SEED_TEMPLATE_MAX_BYTES)
    assert not offenders, "\n".join(offenders)


def test_injected_context_templates_within_budget():
    contexts = [path for path in _template_files() if path.is_relative_to(_CONTEXTS_ROOT)]
    names = {str(path.relative_to(_PROMPTS_ROOT)) for path in contexts}
    # The sentinel, not the floor, carries the layout-drift signal.
    assert "contexts/plan-authoring.md" in names, (
        "prompts/contexts/plan-authoring.md is missing from the CONTEXT-class scan — the "
        "template universe rule looks broken"
    )
    assert len(contexts) >= 5, (
        f"only {len(contexts)} CONTEXT-class templates found under prompts/contexts/ — the "
        "corpus scan looks broken"
    )
    offenders = _template_offenders(contexts, INJECTED_CONTEXT_TEMPLATE_MAX_BYTES)
    assert not offenders, "\n".join(offenders)
