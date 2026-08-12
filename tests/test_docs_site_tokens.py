"""Docs-site token transcription guard.

`docs/site/src/styles/tokens.css` transcribes the binding visual blueprint
(`docs/design/docs-site-visual-blueprint.md` §2 token tables + §3 fonts), and
`docs/site/astro.config.mjs` wires the blueprint's ordered `customCss` list. The blueprint is
the single source of truth: these tests parse *both* the blueprint and the site sources and
assert value-exact agreement (normalizing only quote style, whitespace, and hex case — Biome
formats the CSS) — no hand-maintained transcription lives in the tests. A wrong, swapped,
missing, stray, or reordered value fails here; changing a bound value requires an explicit
objective reconciliation first (the blueprint's own rule).
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BLUEPRINT = REPO_ROOT / "docs/design/docs-site-visual-blueprint.md"
TOKENS_CSS = REPO_ROOT / "docs/site/src/styles/tokens.css"
ASTRO_CONFIG = REPO_ROOT / "docs/site/astro.config.mjs"

DARK_SCOPE = ":root"
LIGHT_SCOPE = ':root[data-theme="light"]'


def _normalize_value(value: str) -> str:
    """Normalize a CSS value for comparison: quotes, whitespace, backticks, hex case.

    Blueprint values arrive in backticks with uppercase hex and (in prose snippets) single
    quotes; Biome formats the CSS to lowercase hex and double quotes. Neither difference is
    semantic, so both sides normalize before the exact comparison.
    """
    value = value.strip().strip("`").strip()
    value = value.replace("'", '"')
    value = re.sub(r"\s+", " ", value)
    return re.sub(r"#([0-9A-Fa-f]+)\b", lambda m: "#" + m.group(1).lower(), value)


def _parse_css_scopes(css_text: str) -> dict[str, dict[str, str]]:
    """Parse the flat token stylesheet into `selector -> {property: normalized value}`."""
    css_text = re.sub(r"/\*.*?\*/", "", css_text, flags=re.DOTALL)
    scopes: dict[str, dict[str, str]] = {}
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css_text):
        selector = _normalize_value(match.group(1))
        declarations: dict[str, str] = {}
        for declaration in match.group(2).split(";"):
            declaration = declaration.strip()
            if not declaration:
                continue
            prop, _, value = declaration.partition(":")
            declarations[prop.strip()] = _normalize_value(value)
        scopes[selector] = declarations
    return scopes


def _section(text: str, start: str, end: str) -> str:
    start_idx = text.index(start)
    end_idx = text.index(end, start_idx)
    return text[start_idx:end_idx]


def _parse_core_table(blueprint: str) -> dict[str, tuple[str, str]]:
    """Parse the §2 core/semantic table: `--perk-*` -> (light value, dark value)."""
    section = _section(
        blueprint, "### Core and semantic tokens", "### Starlight accent and gray ramps"
    )
    tokens: dict[str, tuple[str, str]] = {}
    for line in section.splitlines():
        match = re.match(r"^\| `(--perk-[\w-]+)` \| (`[^`]+`) \| (`[^`]+`) \|", line)
        if match is None:
            continue
        tokens[match.group(1)] = (
            _normalize_value(match.group(2)),
            _normalize_value(match.group(3)),
        )
    return tokens


def _parse_shape_table(blueprint: str) -> dict[str, str]:
    """Parse the §2 spacing/shape table's radius rows: `--perk-radius-*` -> value.

    Rows bind a backticked value to a backticked property name in parentheses
    (e.g. ``| Controls/code radius | `6px` (`--perk-radius-control`) |``).
    """
    section = _section(blueprint, "### Spacing, shape, and measure", "## §3 Typography")
    radii: dict[str, str] = {}
    for line in section.splitlines():
        match = re.match(r"^\|[^|]+\| `([^`]+)` \(`(--perk-radius-[\w-]+)`\) \|", line)
        if match is None:
            continue
        radii[match.group(2)] = _normalize_value(match.group(1))
    return radii


def _parse_font_assignments(blueprint: str) -> dict[str, str]:
    """Parse the §3 selected-font CSS snippet: `--sl-font`/`--sl-font-mono` -> value.

    Scoped to the snippet introduced by "The token CSS then applies:" so the §3 *fallback*
    stacks (documented, not selected) can never be picked up.
    """
    section = _section(blueprint, "The token CSS then applies:", "### Documented fallback")
    return {
        prop: _normalize_value(value)
        for prop, value in re.findall(r"(--sl-font(?:-mono)?):\s*([^;]+);", section)
    }


def _parse_blueprint_custom_css(blueprint: str) -> list[str]:
    """Parse the §3 `customCss` snippet's ordered entry list (fonts first, tokens last)."""
    section = _section(blueprint, "### Selected local fonts", "The token CSS then applies:")
    match = re.search(r"customCss:\s*\[([^\]]*)\]", section)
    assert match is not None, "blueprint §3 customCss snippet not found"
    return re.findall(r"['\"]([^'\"]+)['\"]", match.group(1))


def _parse_config_custom_css(config_text: str) -> list[str]:
    """Parse the ordered `customCss` entry list out of `docs/site/astro.config.mjs`."""
    match = re.search(r"customCss:\s*\[([^\]]*)\]", config_text)
    assert match is not None, "astro.config.mjs declares no customCss list"
    return re.findall(r"['\"]([^'\"]+)['\"]", match.group(1))


def _parse_ramp_table(section: str) -> dict[str, str]:
    """Parse a §2 Starlight ramp table: `--sl-*` -> value.

    A row may bind multiple comma-separated properties to one value
    (e.g. ``| `--sl-color-white`, `--sl-color-gray-1` | `#F1F5F0` | ... |``).
    """
    assignments: dict[str, str] = {}
    for line in section.splitlines():
        match = re.match(r"^\| ((?:`--sl-[\w-]+`(?:, )?)+) \| (`[^`]+`) \|", line)
        if match is None:
            continue
        value = _normalize_value(match.group(2))
        for prop in re.findall(r"`(--sl-[\w-]+)`", match.group(1)):
            assignments[prop] = value
    return assignments


def test_tokens_css_matches_blueprint():
    blueprint = BLUEPRINT.read_text(encoding="utf-8")
    core = _parse_core_table(blueprint)
    dark_ramp = _parse_ramp_table(
        _section(blueprint, "**Dark/default theme:**", "**Light theme:**")
    )
    light_ramp = _parse_ramp_table(
        _section(blueprint, "**Light theme:**", "### Spacing, shape, and measure")
    )

    # Parser sanity: a silently-empty parse must not pass vacuously.
    assert len(core) == 13, sorted(core)
    assert len(dark_ramp) >= 15, sorted(dark_ramp)
    assert len(light_ramp) >= 17, sorted(light_ramp)

    scopes = _parse_css_scopes(TOKENS_CSS.read_text(encoding="utf-8"))
    assert set(scopes) == {DARK_SCOPE, LIGHT_SCOPE}, sorted(scopes)
    dark_scope = scopes[DARK_SCOPE]
    light_scope = scopes[LIGHT_SCOPE]

    # §2 shape tokens (radius rows of the spacing/shape table) and §3 font assignments —
    # parsed from the blueprint like the color tables (no third transcription).
    radii = _parse_shape_table(blueprint)
    fonts = _parse_font_assignments(blueprint)
    assert set(radii) == {"--perk-radius-control", "--perk-radius-card"}, radii
    assert set(fonts) == {"--sl-font", "--sl-font-mono"}, fonts

    expected_dark = {prop: dark for prop, (_light, dark) in core.items()} | dark_ramp | radii
    expected_light = {prop: light for prop, (light, _dark) in core.items()} | light_ramp

    for prop, value in (expected_dark | fonts).items():
        assert dark_scope.get(prop) == value, f":root {prop}: {dark_scope.get(prop)!r} != {value!r}"
    for prop, value in expected_light.items():
        assert light_scope.get(prop) == value, (
            f"light {prop}: {light_scope.get(prop)!r} != {value!r}"
        )

    # No stray/renamed tokens: every declared --perk-*/--sl-color-* must come from the blueprint.
    for scope_name, scope, expected in (
        (DARK_SCOPE, dark_scope, expected_dark),
        (LIGHT_SCOPE, light_scope, expected_light),
    ):
        declared = {p for p in scope if p.startswith(("--perk-", "--sl-color-"))}
        extras = declared - set(expected)
        assert not extras, f"{scope_name} declares tokens the blueprint does not bind: {extras}"


def test_astro_config_wires_blueprint_custom_css():
    # The stylesheet is only effective if Starlight actually loads it: the config's `customCss`
    # must be the blueprint §3 list verbatim — same entries, same order (fonts first, tokens
    # last so they land after Starlight's `starlight` cascade layer). A dropped, added, or
    # reordered entry fails here even though tokens.css itself still matches the blueprint.
    expected = _parse_blueprint_custom_css(BLUEPRINT.read_text(encoding="utf-8"))
    assert len(expected) == 5, expected
    actual = _parse_config_custom_css(ASTRO_CONFIG.read_text(encoding="utf-8"))
    assert actual == expected

    # The relative entry must resolve to the guarded stylesheet from the config's directory.
    relative_entries = [e for e in actual if e.startswith("./")]
    assert [(ASTRO_CONFIG.parent / e).resolve() for e in relative_entries] == [TOKENS_CSS]
