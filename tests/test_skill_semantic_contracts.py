"""Clause-bound semantic pins for the §8.57-rewritten stage skills.

The rewritten skills (`perk-learn`, `perk-learn-docs`, `perk-learn-code`, `perk-implement`,
`perk-address`) are the SOLE carriers of the operational detail their launch seeds shed — and
skill bodies are otherwise CI-inert (no ceiling gate yet), so a drift there would be silent.
Each test pins the newly sole-carried clauses of one skill: small, whitespace-normalized
substring pins (the `test_learn_harvest_cmd.py::test_skill_semantic_contract` pattern), never
full snapshots. `perk-learn-harvest` stays covered by its existing dedicated test.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


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
