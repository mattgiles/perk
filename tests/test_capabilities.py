from perk.convergence import capabilities


def test_inventory_all_required_in_phase0():
    assert capabilities.CAPABILITIES
    assert all(c.required for c in capabilities.CAPABILITIES)
    assert all(c.scope == "both" for c in capabilities.CAPABILITIES)


def test_subagent_engine_capability_present():
    assert "subagent-engine" in {c.name for c in capabilities.CAPABILITIES}


def test_skills_manifest_capability_present():
    assert "skills-manifest" in {c.name for c in capabilities.CAPABILITIES}


def test_required_perk_version_capability_present():
    assert "required-perk-version" in {c.name for c in capabilities.CAPABILITIES}


def test_applicable_returns_full_set_either_way():
    full = {c.name for c in capabilities.CAPABILITIES}
    assert {c.name for c in capabilities.applicable(True)} == full
    assert {c.name for c in capabilities.applicable(False)} == full
