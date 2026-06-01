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


def test_plan_ref_to_data_pr_id_is_string():
    ref = plan.PlanRef(provider="github", pr_id="123", url="u", labels=(plan.PLAN_LABEL,))
    data = ref.to_data()
    assert data == {
        "provider": "github",
        "pr_id": "123",  # string, not int
        "url": "u",
        "labels": ["perk:plan"],
        "objective_id": None,
    }


def test_render_plan_body_keeps_markdown_verbatim():
    body = plan.render_plan_body("# My Plan\n\nStep 1.\n")
    assert "# My Plan" in body and "Step 1." in body
    assert "<!-- perk:metadata-block:plan-body -->" in body


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
