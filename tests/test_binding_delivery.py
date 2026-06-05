"""Node 2.1: cold-door delivery of user-originated skill bindings (`perk/binding_delivery.py`).

The shipped defaults are passed explicitly so the tests are independent of the bundled
`bindings.yaml`, except where they deliberately exercise the no-double-delivery filter.
"""

from pathlib import Path

from perk.binding_delivery import _HEADER, render_cold_bindings
from perk.bindings import Binding, load_bindings

_DEFAULTS = [
    Binding("stage:implement", "stage", "implement", "perk-implement", "nudge"),
    Binding("stage:plan", "stage", "plan", "perk-plan", "nudge"),
]


def test_binding_header_is_the_cross_plane_dedup_marker():
    # Pinned byte-for-byte alongside the TS sibling (extension/bindingDelivery.test.ts): both planes
    # render under this exact literal so a cold launch + a warm injection never double-deliver.
    assert _HEADER == "The following skill binding(s) apply here (configured via .pi/perk.toml):"


def _user(trigger: str, skill: str, mode: str) -> Binding:
    kind, target_id = trigger.split(":", 1)
    return Binding(trigger, kind, target_id, skill, mode)


def _write_skill(repo_root: Path, skill: str, body: str) -> None:
    path = repo_root / ".agents" / "skills" / skill / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_nudge_at_new_trigger_renders_pointer(tmp_path):
    user = [_user("stage:save", "my-skill", "nudge")]
    delivery = render_cold_bindings(user, tmp_path, "stage:save", defaults=_DEFAULTS)
    assert delivery.text is not None
    assert "Follow the `my-skill` skill." in delivery.text
    assert ".pi/perk.toml" in delivery.text  # the header
    assert delivery.warnings == [] and delivery.issues == []


def test_transclude_inlines_body_with_frontmatter_stripped(tmp_path):
    _write_skill(
        tmp_path,
        "deep-skill",
        "---\nname: deep-skill\ndescription: x\n---\n\n# Deep\n\nThe body lives here.\n",
    )
    user = [_user("stage:save", "deep-skill", "transclude")]
    delivery = render_cold_bindings(user, tmp_path, "stage:save", defaults=_DEFAULTS)
    assert delivery.text is not None
    assert "The body lives here." in delivery.text
    assert "# Deep" in delivery.text
    assert "name: deep-skill" not in delivery.text  # frontmatter stripped
    assert "inlined for `stage:save`" in delivery.text
    assert delivery.warnings == []


def test_missing_transclude_target_warns_and_falls_back_to_nudge(tmp_path):
    user = [_user("stage:save", "ghost-skill", "transclude")]
    delivery = render_cold_bindings(user, tmp_path, "stage:save", defaults=_DEFAULTS)
    assert delivery.text is not None
    assert "Follow the `ghost-skill` skill." in delivery.text  # nudge fallback
    assert len(delivery.warnings) == 1
    assert "ghost-skill" in delivery.warnings[0]


def test_shipped_default_is_not_redelivered(tmp_path):
    # No user override of stage:implement -> the resolved binding equals the shipped default,
    # so it is filtered out (perk still hardcodes that nudge). No double-delivery.
    delivery = render_cold_bindings([], tmp_path, "stage:implement", defaults=_DEFAULTS)
    assert delivery.text is None


def test_user_override_of_perk_owned_trigger_is_delivered(tmp_path):
    user = [_user("stage:implement", "custom-implement", "nudge")]
    delivery = render_cold_bindings(user, tmp_path, "stage:implement", defaults=_DEFAULTS)
    assert delivery.text is not None
    assert "Follow the `custom-implement` skill." in delivery.text


def test_shape_invalid_user_binding_surfaces_issue(tmp_path):
    user = [_user("stage:save", "", "nudge")]  # missing skill
    delivery = render_cold_bindings(user, tmp_path, "stage:save", defaults=_DEFAULTS)
    assert delivery.text is None  # the invalid binding was dropped
    assert any("skill" in issue.message for issue in delivery.issues)


def test_only_matching_trigger_is_rendered(tmp_path):
    user = [
        _user("stage:save", "save-skill", "nudge"),
        _user("stage:other", "other-skill", "nudge"),
    ]
    delivery = render_cold_bindings(user, tmp_path, "stage:save", defaults=_DEFAULTS)
    assert delivery.text is not None
    assert "save-skill" in delivery.text
    assert "other-skill" not in delivery.text


def test_default_resolution_uses_bundled_bindings(tmp_path):
    # When defaults is omitted, the bundled shipped set is used: stage:implement is a default,
    # so an unbound launch delivers nothing.
    assert load_bindings().bindings  # sanity: the bundled set loads
    delivery = render_cold_bindings([], tmp_path, "stage:implement")
    assert delivery.text is None
