"""The shared PR-body kernel: part order, the plan-embed fit judged with every section and the
footer reserved on both passes, the too-large pointer, and the no-plan arm."""

from perk.delivery import pr_body

_LEAD = ["Closes #7", "Plan: #7"]
_SECTION = "### Change stats\n\n_No lines counted by cloc over 1234567..abcdef0._"


def _fixed_len(sections: list[str]) -> int:
    """The composed length with an empty plan embed and no footer."""
    embed = pr_body.plan_embed(issue="7", plan_body="")
    return len("\n\n".join([*_LEAD, *sections, embed]) + "\n")


def test_parts_join_in_order_with_the_footer_last():
    composed = pr_body.compose(
        issue="7", lead=_LEAD, sections=[_SECTION], plan_body="# Plan", pr_number=42
    )
    assert composed.plan_embedded is True
    assert composed.text == (
        "Closes #7\n\nPlan: #7\n\n"
        f"{_SECTION}\n\n"
        "<details><summary>Plan #7</summary>\n\n# Plan\n\n</details>\n\n"
        "`gh pr checkout 42`\n"
    )


def test_no_plan_body_means_no_embed():
    for plan_body in (None, ""):
        composed = pr_body.compose(
            issue="7", lead=_LEAD, sections=[], plan_body=plan_body, pr_number=None
        )
        assert composed == pr_body.ComposedBody("Closes #7\n\nPlan: #7\n", plan_embedded=False)


def test_plan_embed_fit_is_judged_with_the_footer_reserved():
    # Exactly at the boundary the create pass (no PR number yet) and the update pass (footer
    # appended) must agree, so the fit is judged with the footer reserved on both.
    room = pr_body.PR_BODY_MAX_CHARS - _fixed_len([]) - pr_body.FOOTER_RESERVE
    for plan_body, fits in (("p" * room, True), ("p" * (room + 1), False)):
        create = pr_body.compose(
            issue="7", lead=_LEAD, sections=[], plan_body=plan_body, pr_number=None
        )
        update = pr_body.compose(
            issue="7", lead=_LEAD, sections=[], plan_body=plan_body, pr_number=9_999_999
        )
        assert create.plan_embedded is update.plan_embedded is fits
        assert ("<details>" in create.text) is ("<details>" in update.text) is fits
        assert len(update.text) <= pr_body.PR_BODY_MAX_CHARS


def test_a_section_that_tips_the_body_over_drops_the_embed_on_both_passes():
    room = pr_body.PR_BODY_MAX_CHARS - _fixed_len([]) - pr_body.FOOTER_RESERVE
    plan_body = "p" * room  # fits exactly without the section, not with it
    assert pr_body.compose(
        issue="7", lead=_LEAD, sections=[], plan_body=plan_body, pr_number=None
    ).plan_embedded
    for pr_number in (None, 42):
        composed = pr_body.compose(
            issue="7", lead=_LEAD, sections=[_SECTION], plan_body=plan_body, pr_number=pr_number
        )
        assert composed.plan_embedded is False
        assert _SECTION in composed.text  # sections are never dropped
        assert "<details>" not in composed.text
        assert len(composed.text) <= pr_body.PR_BODY_MAX_CHARS


def test_the_pointer_names_the_plan_size_and_the_cap():
    huge = "x" * 70_000
    composed = pr_body.compose(issue="7", lead=_LEAD, sections=[], plan_body=huge, pr_number=42)
    assert composed.plan_embedded is False
    assert composed.text == (
        "Closes #7\n\nPlan: #7\n\n"
        "_Plan #7 is too large to embed here (70,000 characters; GitHub caps a PR body at "
        "65,536) — read it on the plan issue._\n\n"
        "`gh pr checkout 42`\n"
    )
