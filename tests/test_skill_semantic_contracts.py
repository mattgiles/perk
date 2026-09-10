"""Clause-bound semantic pins for the §8.57-rewritten stage skills.

The rewritten skills (`perk-learn`, `perk-learn-docs`, `perk-learn-code`, `perk-implement`,
`perk-address`) are the SOLE carriers of the operational detail their launch seeds shed — and
skill bodies are otherwise CI-inert (no ceiling gate yet), so a drift there would be silent.
The three authoring skills (`perk-plan`, `perk-objective-plan`, `perk-objective-author`) are
likewise the sole carriers of the stage-specific judgment tier behind the `run_scout_wave` tool's
`promptGuidelines` (when a scout wave is worth it at that stage, what its reports are worth, and
how the call is recorded) — the shared mechanics stay in the tool and are deliberately NOT
restated in any skill, so no pin here echoes them.
Each test pins the newly sole-carried clauses of one skill: small, whitespace-normalized
substring pins (the `test_learn_harvest_cmd.py::test_skill_semantic_contract` pattern), never
full snapshots. `perk-learn-harvest` stays covered by its existing dedicated test.
"""

import re
from pathlib import Path

from perk.substrate.skill_exposure import parse_skill_frontmatter

REPO_ROOT = Path(__file__).resolve().parents[1]

# The scout launcher's judgment tier rides exactly these three skills (each bound to the one stage
# whose STAGE_TOOLS list carries the tool).
SCOUT_GUIDANCE_SKILLS: dict[str, list[str]] = {
    "perk-plan": ["plan"],
    "perk-objective-plan": ["objective-plan"],
    "perk-objective-author": ["objective-author"],
}

# Mechanics the `run_scout_wave` tool's `promptGuidelines` (extension/pi/v1/scoutWave.ts) carry
# ALONE — the brief shape and caps, pointer-not-paste, `inferred`-as-lead, the attempt policy and
# the partial-wave fallback. Compared case-insensitively against the whitespace-normalized skill
# bodies. Every entry must also occur in the tool's guidelines block, so this list can only name
# facts the tool actually states (drop the entry when the tool drops the fact).
SCOUT_TOOL_OWNED_MECHANICS: tuple[str, ...] = (
    "self-contained",
    "pointer-style",
    "[a-z0-9]",
    "8 kib",
    "at most 6",
    "pasting",
    "inferred",
    "one attempt",
    "no retry",
    "partial or failed wave",
)


def _norm(skill: str) -> str:
    text = (REPO_ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    return " ".join(text.split())


def test_perk_learn_sole_carried_detail():
    norm = _norm("perk-learn")
    # The child report contract: the engine-injected completion call + the payload shape tokens.
    assert "`structured_output`" in norm
    assert "candidates" in norm
    for token in (
        "CAPTURE_LEARN",
        "SHOULD_BE_CODE",
        "UPDATE_EXISTING_DOC",
        "NEW_DOC",
        "STALE_DOC",
        "SKIP",
    ):
        assert token in norm, f"decision enum member missing: {token}"
    # The derived-verdict rule.
    assert "any non-`SKIP` candidate ⇒ `actionable`, else `clean`" in norm
    # Children never capture.
    assert "**never** capture, create an issue, post, write files, or spawn subagents" in norm
    # The earned-SKIP / do-not-churn rule.
    assert "*earned* by the analysts' reads, not defaulted to" in norm
    assert "Do not churn" in norm
    # The four-angle rubric headers (the skill is the rubric's canonical carrier).
    for angle in (
        "`session-deviations`",
        "`plan-vs-implementation`",
        "`existing-docs`",
        "`validation-risk`",
    ):
        assert angle in norm, f"angle rubric header missing: {angle}"


def test_perk_learn_docs_sole_carried_detail():
    norm = _norm("perk-learn-docs")
    # The inbox-only read rule (the untrusted-envelope boundary — no gh re-fetch).
    assert "do **not** re-fetch them via `gh`" in norm
    assert "<untrusted_learning>" in norm
    # The five knowledge-placement hierarchy rows.
    assert (
        "**Type/constant** (catalogs, fixed option sets, error codes) → source, not a doc" in norm
    )
    assert "**Code comment** → insight about a single line/block" in norm
    assert "**Docstring** → insight about a single function/class" in norm
    assert "**Schema / user-docs** → a contract shape or operator-facing behavior" in norm
    assert (
        "**Learned doc** → insight that spans multiple files, connects systems, or captures "
        "a decision" in norm
    )
    # The cue contract (its ONE full carrier is the Light frontmatter bullet).
    assert "≤200 chars" in norm
    assert "never ` #`" in norm
    assert "no `: `" in norm
    assert "`docs/learned/clusters.yaml` registry" in norm
    assert "an **existing id** from that registry" in norm
    # The distillation-first contract (its ONE full carrier is the big-docs bullet).
    assert "## Distillation" in norm
    assert "12,288 bytes" in norm
    assert "fully inside the file's first 80 lines" in norm
    # consumed_learn semantics: no per-item subsetting; the on-land label.
    assert "no per-item subsetting" in norm
    assert "`perk:consolidated`" in norm


def test_perk_learn_code_sole_carried_detail():
    norm = _norm("perk-learn-code")
    # The inbox-only read rule (the untrusted-envelope boundary — no gh re-fetch).
    assert "do **not** re-fetch them via `gh`" in norm
    assert "<untrusted_learning>" in norm
    # The knowledge-placement hierarchy rows.
    assert (
        "**Type/constant** (catalogs, fixed option sets, error codes) → the source definition"
        in norm
    )
    assert "**Code comment** → a single line/block" in norm
    assert "**Docstring** → a single function/class" in norm
    assert "**Schema** → a contract shape" in norm
    assert "**User-docs** → operator-facing behavior" in norm
    # The verify rule: the target is a hint, read the code first.
    assert "Verify `target` against the real codebase before committing a step" in norm
    assert "The target is a hint, not a verdict" in norm
    # The route-back nuance + the on-land label.
    assert "route back to `/learn-docs`" in norm
    assert "`perk:consolidated`" in norm


def test_perk_implement_sole_carried_detail():
    norm = _norm("perk-implement")
    # The per-backend reading recipes pointer.
    assert "`backends/<backend>.md` (`github`, `linear`)" in norm
    # The plan body is the contract.
    assert "The plan body is the contract" in norm
    assert "implement *that*, not a reinterpretation" in norm


def test_perk_address_sole_carried_detail():
    norm = _norm("perk-address")
    # The corrected actionable triage rule: the REQUESTED change, with the Plan File Mode arm.
    assert "`actionable` gets the requested change" in norm
    assert "in Plan File Mode a plan-text edit" in norm
    # finalize_address elaboration: the retry_threads reduced-batch semantics.
    assert "`retry_threads`" in norm
    assert "retry only that reduced batch" in norm
    assert "omits successful rows and strips replies already reported as posted" in norm
    # The untrusted-review fence + the hand-off.
    assert "<untrusted_review>" in norm
    assert "go to `/land`" in norm


def test_perk_objective_plan_sole_carried_detail():
    norm = _norm("perk-objective-plan")
    # The warm worker form (JSON, after the planning transition).
    assert "perk objective node-engagement N --node <id> --json" in norm
    # The byte-slice recipe: `read` names the oversized line; sed | tail | head slices it (the
    # path quoted, so a directory with spaces stays one argument); the offsets advance by the
    # slice size; the slicing ends on an empty slice, paging resumes at the next line, and the
    # whole recipe repeats per oversized line.
    assert "[Line N is <size>, exceeds 50 KB limit" in norm
    assert "sed -n 'Np' '<path>' | tail -c +<offset> | head -c 51200" in norm
    assert "the path single-quoted" in norm
    assert "offsets `+1`, `+51201`, `+102401`, …" in norm
    assert "until a slice comes back empty" in norm
    assert "`offset` N+1" in norm
    assert "Repeat for every such line" in norm
    assert "`max_line_bytes` in the pointer tells you up front" in norm
    # The boundary-token rule's elaboration + the honest-reporting rule.
    assert "same boundary token as the opener" in norm
    assert "never auto-retry" in norm
    # The scout-wave delta this skill alone owns: the explorer-vs-wave positioning (the two
    # gathering carriers sit side by side) and the plan-stage record rule for the call.
    assert (
        "`explore_objective_node` maps this one node through a single typed explorer lane" in norm
    )
    assert "brief keys, complete/incomplete, the model that ran" in norm


def test_perk_plan_sole_carried_detail():
    norm = _norm("perk-plan")
    # The pointer-back that keeps the skill from becoming a second carrier of the wave mechanics.
    assert "The `run_scout_wave` tool's guidelines carry the mechanics" in norm
    # The plan-stage record rule: verified claims + failed/unanswered briefs land in Assumptions.
    assert "record in `## Assumptions` which claims you verified" in norm


def test_perk_objective_author_sole_carried_detail():
    norm = _norm("perk-objective-author")
    # The stage's never-delegate boundary for a scout wave.
    assert (
        "Never delegate the goal framing, the roadmap decomposition, or the user conversation"
        in norm
    )


def test_scout_launcher_guidance_rides_exactly_the_three_authoring_skills():
    """The dispatch-parity / negative-space pin for the scout launcher's guidance carriers.

    `run_scout_wave` rides exactly the `plan` / `objective-plan` / `objective-author` `STAGE_TOOLS`
    lists (contracts §8.70 item 6; pinned on the TS side by `extension/substrate/stageTools.test.ts`
    "run_scout_wave rides exactly the three authoring stage lists"), and the skill guidance naming
    it rides exactly the skills bound to those three stages — the two-carrier shape
    `explore_objective_node` established (tool `promptGuidelines` for the mechanics, the bound
    stage skill for the judgment). Consequence: no other `skills/perk-*/SKILL.md` (`perk-expert`,
    `perk-grill`, `perk-replan`, …) may carry the literal `run_scout_wave`; the
    `skills/perk-expert/references/*.md` mirror is outside this sweep and may.
    """
    carriers: dict[str, Path] = {}
    for path in sorted((REPO_ROOT / "skills").glob("perk-*/SKILL.md")):
        if "run_scout_wave" in path.read_text(encoding="utf-8"):
            carriers[path.parent.name] = path
    assert set(carriers) == set(SCOUT_GUIDANCE_SKILLS), (
        "the skills naming `run_scout_wave` must be exactly the three authoring skills bound to "
        "the stages the tool rides (plan / objective-plan / objective-author); got "
        f"{sorted(carriers)}"
    )
    for skill, stages in SCOUT_GUIDANCE_SKILLS.items():
        frontmatter, reason = parse_skill_frontmatter(carriers[skill].read_text(encoding="utf-8"))
        assert reason is None, f"{skill}: {reason}"
        assert frontmatter.get("stages") == stages, (
            f"{skill} must be bound to exactly {stages} (the stage whose STAGE_TOOLS list carries "
            f"run_scout_wave); got {frontmatter.get('stages')!r}"
        )


def test_review_skills_require_and_do_not_duplicate_ponytail_coverage():
    automated = _norm("perk-pr-review")
    assert "`ponytail` lane is **required automatic coverage**" in automated
    assert "Ponytail exclusively owns standalone findings" in automated
    assert "Ordinary lanes may mention simplification only when inseparable" in automated

    for skill in ("perk-pr-review-terminal", "perk-pr-review-browser"):
        norm = _norm(skill)
        assert "**required automatic** final `ponytail` lane" in norm
        assert "Ponytail exclusively owns standalone deletion/YAGNI" in norm
        assert "ordinary lanes mention simplification only when inseparable" in norm

    for skill in ("perk-plan-review-browser", "perk-objective-review-browser"):
        norm = _norm(skill)
        assert "**required automatic** final `ponytail` lane" in norm
        assert "Scope owns goal boundaries plus missing/extraneous deliverables" in norm
        assert "Ponytail exclusively owns standalone deletion/YAGNI" in norm


def _scout_prompt_guidelines() -> str:
    """The `run_scout_wave` registration's `promptGuidelines` block, lowercased.

    Sliced from the installer source rather than imported: the guidelines are in-place string
    literals at the registration site (the prose-review TS adapter reads them there too), and the
    Python suite must not depend on a TS build.
    """
    source = (REPO_ROOT / "extension" / "pi" / "v1" / "scoutWave.ts").read_text(encoding="utf-8")
    match = re.search(r"promptGuidelines:\s*\[(.*?)\n\s*\],", source, re.DOTALL)
    assert match is not None, "run_scout_wave's promptGuidelines block not found in scoutWave.ts"
    return " ".join(match.group(1).split()).lower()


def test_authoring_skills_do_not_restate_scout_wave_mechanics():
    """The negative-space twin of the semantic pins: the single-carrier boundary.

    The three skills carry the stage-specific judgment (when a wave is worth it, what its reports
    are worth, how the call is recorded) and point back at the tool for the mechanics. A skill
    that copies a tool-owned mechanic becomes a second prose carrier that can drift from the tool
    contract — so each mechanic phrase must be absent from every guidance skill AND present in the
    tool's `promptGuidelines` (the list may only name facts the tool actually states).
    """
    guidelines = _scout_prompt_guidelines()
    for phrase in SCOUT_TOOL_OWNED_MECHANICS:
        assert phrase in guidelines, (
            f"{phrase!r} is not in run_scout_wave's promptGuidelines — the negative-space list may "
            "only forbid mechanics the tool itself carries; drop or reword the entry"
        )
    for skill in SCOUT_GUIDANCE_SKILLS:
        norm = _norm(skill).lower()
        restated = [phrase for phrase in SCOUT_TOOL_OWNED_MECHANICS if phrase in norm]
        assert restated == [], (
            f"{skill} restates run_scout_wave mechanics {restated}: the tool's promptGuidelines "
            "are the single carrier of the brief shape/caps, pointer-not-paste, inferred-as-lead, "
            "the attempt policy and the partial-wave fallback — keep the skill to stage-specific "
            "judgment and point back at the tool"
        )
