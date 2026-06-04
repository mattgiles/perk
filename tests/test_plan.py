from perk import plan


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
    data = header.to_data()
    assert data["run_id"] == "01R"
    assert data["lifecycle_stage"] == "planned"  # StrEnum -> value
    assert data["branch"] is None and data["pr"] is None and data["objective_id"] is None
    assert data["consumed_learn"] == []  # hop-2: empty by default, serialized as a list


def test_plan_header_consumed_learn_round_trips():
    header = plan.PlanHeader(run_id="01R", created="2026-05-30T00:00:00Z", consumed_learn=(45, 50))
    data = header.to_data()
    assert data["consumed_learn"] == [45, 50]
    rendered = plan.render_metadata_block(plan.PLAN_HEADER_KEY, data)
    parsed = plan.find_metadata_block(rendered, plan.PLAN_HEADER_KEY)
    assert parsed is not None and parsed["consumed_learn"] == [45, 50]
    assert "consumed_learn" in plan.PLAN_HEADER_FIELDS


def test_plan_ref_consumed_learn_in_to_data():
    ref = plan.PlanRef(
        provider="github",
        pr_id="123",
        url="u",
        labels=(plan.PLAN_LABEL,),
        consumed_learn=(7, 9),
    )
    assert ref.to_data()["consumed_learn"] == [7, 9]


def test_plan_ref_to_data_pr_id_is_string():
    ref = plan.PlanRef(provider="github", pr_id="123", url="u", labels=(plan.PLAN_LABEL,))
    data = ref.to_data()
    assert data == {
        "provider": "github",
        "pr_id": "123",  # string, not int
        "url": "u",
        "labels": ["perk:plan"],
        "objective_id": None,
        "consumed_learn": [],
    }


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
        plan.PLAN_HEADER_KEY, plan.PlanHeader(run_id="01RID", created="t").to_data()
    )
    assert plan.extract_run_id(rendered) == "01RID"


def test_extract_run_id_absent_or_empty_is_none():
    assert plan.extract_run_id("nothing") is None
    empty = plan.render_metadata_block(
        plan.PLAN_HEADER_KEY, plan.PlanHeader(run_id="", created="t").to_data()
    )
    assert plan.extract_run_id(empty) is None


def test_derive_title_uses_first_heading_else_fallback():
    assert plan.derive_title("# Real Title\n\nbody") == "Real Title"
    assert plan.derive_title("no heading here") == "perk plan"


def test_derive_title_ignores_hash_inside_code_fence():
    # The P1.T6 dogfood failure: a TOML `# comment` inside a ```toml block became the title.
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
