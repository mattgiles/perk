"""Docs-site token transcription guard.

`docs/site/src/styles/tokens.css` transcribes the binding visual blueprint
(`docs/design/docs-site-visual-blueprint.md` §2 token tables + §3 fonts). The blueprint is the
single source of truth: this test parses *both* the blueprint tables and the CSS and asserts
they agree exactly — no third hand-maintained transcription. A wrong, swapped, missing, or
stray token value fails here; changing a bound value requires an explicit objective
reconciliation first (the blueprint's own rule).
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BLUEPRINT = REPO_ROOT / "docs/design/docs-site-visual-blueprint.md"
TOKENS_CSS = REPO_ROOT / "docs/site/src/styles/tokens.css"

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

    # §2 shape tokens (spacing/shape table — small literals, not row-parseable).
    radii = {"--perk-radius-control": "6px", "--perk-radius-card": "10px"}
    # §3 font assignments (small literals).
    fonts = {"--sl-font": '"Inter Variable"', "--sl-font-mono": '"IBM Plex Mono"'}

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
