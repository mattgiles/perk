import dataclasses

import pytest

from perk import plan
from perk.boundary import ValidationError


def test_plan_header_byte_order_is_stable():
    # Pin the YAML key order so a future field reorder cannot silently churn stored bodies.
    header = plan.PlanHeader(
        run_id="01R",
        created="2026-05-30T00:00:00Z",
        lifecycle_stage=plan.LifecycleStage.IMPL,
        branch="plan-7",
        pr="55",
        objective_id="911",
        consumed_learn=("45",),
        base="develop",
        adopted_from="7",
    )
    rendered = plan.render_metadata_block(
        plan.PLAN_HEADER_KEY, plan.PlanHeaderOut.from_domain(header).model_dump(mode="json")
    )
    order = [
        "run_id",
        "lifecycle_stage",
        "branch",
        "pr",
        "created",
        "objective_id",
        "consumed_learn",
        "base",
        "adopted_from",
    ]
    positions = [rendered.find(f"{key}:") for key in order]
    assert all(p != -1 for p in positions)
    assert positions == sorted(positions)


def test_plan_header_out_strict_scalar_rejection():
    # The validate edge: PlanHeaderOut rejects a non-str `run_id` even under lax coercion.
    with pytest.raises(ValidationError):
        plan.PlanHeaderOut.model_validate({"run_id": 5, "created": "t"})


def test_plan_header_frozen():
    header = plan.PlanHeader(run_id="r", created="t")
    with pytest.raises(dataclasses.FrozenInstanceError):
        header.run_id = "x"  # ty: ignore[invalid-assignment]


def test_metadata_block_round_trips():
    data: dict[str, object] = {
        "run_id": "01TESTRUN",
        "lifecycle_stage": "planned",
        "branch": None,
        "pr": None,
        "created": "2026-05-30T00:00:00Z",
        "objective_id": None,
    }
    rendered = plan.render_metadata_block(plan.PLAN_HEADER_KEY, data)
    assert plan.find_metadata_block(rendered, plan.PLAN_HEADER_KEY) == data


def test_metadata_block_is_collapsible_and_delimited():
    rendered = plan.render_metadata_block("plan-header", {"a": 1})
    assert "<!-- perk:metadata-block:plan-header -->" in rendered
    assert "<!-- /perk:metadata-block:plan-header -->" in rendered
    assert "<details><summary><code>plan-header</code></summary>" in rendered
    assert "```yaml" in rendered


def test_find_absent_block_is_none():
    assert plan.find_metadata_block("no blocks here", plan.PLAN_HEADER_KEY) is None


def test_find_malformed_block_is_none():
    # open marker present, but no closing fence/marker -> None, never raises
    broken = "<!-- perk:metadata-block:plan-header -->\n<details>\n```yaml\nrun_id: x"
    assert plan.find_metadata_block(broken, plan.PLAN_HEADER_KEY) is None


def test_plan_header_to_data_shape():
    header = plan.PlanHeader(run_id="01R", created="2026-05-30T00:00:00Z")
    data = plan.PlanHeaderOut.from_domain(header).model_dump(mode="json")
    assert data["run_id"] == "01R"
    assert data["lifecycle_stage"] == "planned"  # StrEnum -> value
    assert data["branch"] is None and data["pr"] is None and data["objective_id"] is None
    assert data["consumed_learn"] == []  # hop-2: empty by default, serialized as a list
    assert data["base"] is None  # absent by default


def test_plan_header_consumed_learn_round_trips():
    header = plan.PlanHeader(
        run_id="01R", created="2026-05-30T00:00:00Z", consumed_learn=("45", "50")
    )
    data = plan.PlanHeaderOut.from_domain(header).model_dump(mode="json")
    assert data["consumed_learn"] == ["45", "50"]
    rendered = plan.render_metadata_block(plan.PLAN_HEADER_KEY, data)
    parsed = plan.find_metadata_block(rendered, plan.PLAN_HEADER_KEY)
    assert parsed is not None and parsed["consumed_learn"] == ["45", "50"]
    assert "consumed_learn" in plan.PLAN_HEADER_FIELDS


def test_plan_ref_consumed_learn_in_to_data():
    ref = plan.PlanRef(
        provider="github",
        pr_id="123",
        url="u",
        labels=(plan.PLAN_LABEL,),
        consumed_learn=("7", "9"),
    )
    assert plan.PlanRefOut.from_domain(ref).model_dump(mode="json")["consumed_learn"] == ["7", "9"]


def test_plan_ref_to_data_pr_id_is_string():
    ref = plan.PlanRef(provider="github", pr_id="123", url="u", labels=(plan.PLAN_LABEL,))
    data = plan.PlanRefOut.from_domain(ref).model_dump(mode="json")
    assert data == {
        "provider": "github",
        "pr_id": "123",  # string, not int
        "url": "u",
        "labels": ["perk:plan"],
        "objective_id": None,
        "consumed_learn": [],
        "base": None,
    }


def test_plan_header_base_round_trips():
    header = plan.PlanHeader(run_id="01R", created="2026-05-30T00:00:00Z", base="develop")
    data = plan.PlanHeaderOut.from_domain(header).model_dump(mode="json")
    assert data["base"] == "develop"
    rendered = plan.render_metadata_block(plan.PLAN_HEADER_KEY, data)
    parsed = plan.find_metadata_block(rendered, plan.PLAN_HEADER_KEY)
    assert parsed is not None and parsed["base"] == "develop"
    assert "base" in plan.PLAN_HEADER_FIELDS


def test_plan_ref_base_in_to_data():
    ref = plan.PlanRef(
        provider="github",
        pr_id="123",
        url="u",
        labels=(plan.PLAN_LABEL,),
        base="develop",
    )
    assert plan.PlanRefOut.from_domain(ref).model_dump(mode="json")["base"] == "develop"


def test_render_plan_body_keeps_markdown_verbatim():
    body = plan.render_plan_body("# My Plan\n\nStep 1.\n")
    assert "# My Plan" in body and "Step 1." in body
    assert "<!-- perk:metadata-block:plan-body -->" in body


def test_extract_plan_body_round_trips_render():
    markdown = "# Add retry\n\n## Steps\n1. Add helper\n2. Wire it in\n"
    comment = plan.render_plan_body(markdown)
    # The block may be embedded in a larger comment body.
    wrapped = f"some preamble\n\n{comment}\n\ntrailing text\n"
    assert plan.extract_plan_body(wrapped) == markdown.strip()


def test_extract_plan_body_absent_or_malformed_is_none():
    assert plan.extract_plan_body("no block here") is None
    # Open marker without a close marker -> malformed -> None.
    assert plan.extract_plan_body("<!-- perk:metadata-block:plan-body -->\n<details>") is None


def test_extract_run_id_from_header():
    rendered = plan.render_metadata_block(
        plan.PLAN_HEADER_KEY,
        plan.PlanHeaderOut.from_domain(plan.PlanHeader(run_id="01RID", created="t")).model_dump(
            mode="json"
        ),
    )
    assert plan.extract_run_id(rendered) == "01RID"


def test_extract_run_id_absent_or_empty_is_none():
    assert plan.extract_run_id("nothing") is None
    empty = plan.render_metadata_block(
        plan.PLAN_HEADER_KEY,
        plan.PlanHeaderOut.from_domain(plan.PlanHeader(run_id="", created="t")).model_dump(
            mode="json"
        ),
    )
    assert plan.extract_run_id(empty) is None


def test_derive_title_uses_first_heading_else_fallback():
    assert plan.derive_title("# Real Title\n\nbody") == "Real Title"
    assert plan.derive_title("no heading here") == "perk plan"


def test_derive_title_ignores_hash_inside_code_fence():
    # The dogfood failure: a TOML `# comment` inside a ```toml block became the title.
    md = (
        "Here is the plan.\n\n"
        "```toml\n"
        "# Add only if you want format-on-commit too:\n"
        'id = "ruff-check"\n'
        "```\n"
    )
    assert plan.derive_title(md) == "perk plan"  # no real H1 -> fallback, not the fenced comment


def test_derive_title_prefers_real_h1_over_fenced_hash():
    md = "# Add prek hook\n\n```sh\n# not a title\n```\n"
    assert plan.derive_title(md) == "Add prek hook"


def test_derive_title_ignores_indented_code_hash():
    assert plan.derive_title("    # four-space code, not a heading\n") == "perk plan"


# --------------------------------------------------------------- dual encoding


def test_render_metadata_block_inline_code_golden_shape():
    rendered = plan.render_metadata_block("plan-header", {"a": 1}, style="inline-code")
    lines = rendered.splitlines()
    assert lines[0] == "`perk:metadata-block:plan-header`"
    assert lines[-1] == "`/perk:metadata-block:plan-header`"
    assert "```yaml" in rendered
    assert "<details>" not in rendered and "<!--" not in rendered


def test_find_metadata_block_parses_both_encodings():
    data: dict[str, object] = {"run_id": "01DUAL", "pr": None}
    html = plan.render_metadata_block(plan.PLAN_HEADER_KEY, data)
    inline = plan.render_metadata_block(plan.PLAN_HEADER_KEY, data, style="inline-code")
    assert plan.find_metadata_block(html, plan.PLAN_HEADER_KEY) == data
    assert plan.find_metadata_block(inline, plan.PLAN_HEADER_KEY) == data


def test_extract_run_id_from_inline_code_body():
    rendered = plan.render_metadata_block(
        plan.PLAN_HEADER_KEY, {"run_id": "01INLINE"}, style="inline-code"
    )
    body = f"intro text\n\n{rendered}\n\ntrailing\n"
    assert plan.extract_run_id(body) == "01INLINE"


def test_replace_metadata_block_preserves_inline_code_form():
    original = plan.render_metadata_block(
        plan.PLAN_HEADER_KEY, {"run_id": "01X"}, style="inline-code"
    )
    text = f"prefix\n\n{original}\n\nsuffix"
    replaced = plan.replace_metadata_block(text, plan.PLAN_HEADER_KEY, {"run_id": "01X", "pr": "7"})
    assert "<!--" not in replaced and "<details>" not in replaced
    assert "`perk:metadata-block:plan-header`" in replaced
    parsed = plan.find_metadata_block(replaced, plan.PLAN_HEADER_KEY)
    assert parsed == {"run_id": "01X", "pr": "7"}
    assert replaced.startswith("prefix") and replaced.endswith("suffix")


def test_replace_metadata_block_preserves_html_form():
    original = plan.render_metadata_block(plan.PLAN_HEADER_KEY, {"run_id": "01Y"})
    replaced = plan.replace_metadata_block(
        original, plan.PLAN_HEADER_KEY, {"run_id": "01Y", "pr": "9"}
    )
    assert "<!-- perk:metadata-block:plan-header -->" in replaced
    assert "<details><summary><code>plan-header</code></summary>" in replaced
    assert plan.find_metadata_block(replaced, plan.PLAN_HEADER_KEY) == {"run_id": "01Y", "pr": "9"}


def test_replace_metadata_block_append_when_absent_stays_html():
    appended = plan.replace_metadata_block("just prose", plan.PLAN_HEADER_KEY, {"run_id": "01Z"})
    assert "<!-- perk:metadata-block:plan-header -->" in appended
    assert "`perk:metadata-block:plan-header`" not in appended


def test_render_plan_body_inline_code_round_trips():
    markdown = "# Plan\n\n## Steps\n1. one\n\n```python\nprint('#### not a heading')\n```\n"
    comment = plan.render_plan_body(markdown, style="inline-code")
    assert "<details>" not in comment and "<!--" not in comment
    wrapped = f"preamble\n\n{comment}\n\ntrailing\n"
    assert plan.extract_plan_body(wrapped) == markdown.strip()


def test_has_metadata_block_both_encodings():
    html = plan.render_metadata_block(plan.PLAN_HEADER_KEY, {"run_id": "x"})
    inline = plan.render_metadata_block(plan.PLAN_HEADER_KEY, {"run_id": "x"}, style="inline-code")
    assert plan.has_metadata_block(html, plan.PLAN_HEADER_KEY)
    assert plan.has_metadata_block(inline, plan.PLAN_HEADER_KEY)


def test_has_metadata_block_absent_is_false():
    assert not plan.has_metadata_block("no blocks here", plan.PLAN_HEADER_KEY)
    # a different key's block never matches
    other = plan.render_metadata_block("learn-header", {"run_id": "x"})
    assert not plan.has_metadata_block(other, plan.PLAN_HEADER_KEY)


def test_has_metadata_block_is_presence_only_even_when_malformed():
    # find_metadata_block returns None for both absent AND malformed; has_metadata_block
    # discriminates: a present-but-malformed block is still "present".
    broken_html = "<!-- perk:metadata-block:plan-header -->\n```yaml\nrun_id: x"
    broken_inline = "`perk:metadata-block:plan-header`\n```yaml\nrun_id: x"
    assert plan.find_metadata_block(broken_html, plan.PLAN_HEADER_KEY) is None
    assert plan.find_metadata_block(broken_inline, plan.PLAN_HEADER_KEY) is None
    assert plan.has_metadata_block(broken_html, plan.PLAN_HEADER_KEY)
    assert plan.has_metadata_block(broken_inline, plan.PLAN_HEADER_KEY)


def test_render_command_callout_shape():
    out = plan.render_command_callout("Do it:", "perk impl 42", "Some hint.")
    assert out == "**Do it:**\n\n```\nperk impl 42\n```\n\n_Some hint._"


def test_plan_callout_content():
    out = plan.plan_callout("42")
    assert "**Implement this plan:**" in out
    assert "```\nperk impl 42\n```" in out
    assert "_Run from the repo root to start a worktree session._" in out


def test_prepend_callout_prepends_when_absent():
    out = plan.prepend_callout("BODY", "CALLOUT", command="perk impl 42")
    assert out == "CALLOUT\n\nBODY"


def test_prepend_callout_noop_when_command_present():
    body = "CALLOUT\n\nperk impl 42 lives here"
    assert plan.prepend_callout(body, "NEW", command="perk impl 42") == body


def test_prepend_callout_empty_body():
    assert plan.prepend_callout("", "CALLOUT", command="perk impl 42") == "CALLOUT\n"
