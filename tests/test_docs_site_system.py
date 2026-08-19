"""Docs-site system-stylesheet and diagram-geometry guard.

`docs/site/src/styles/system.css` applies the binding visual blueprint's type scale, measure,
focus, reduced-motion, containment, eyebrow/wide-mode, and article-page/shell-chrome finish
decisions (`docs/design/docs-site-visual-blueprint.md` §2/§3/§4/§6/§11), and the five diagram
components apply the §5 label-size floor — the four static-SVG components through
container-query variant exposure, the interactive core-flow component through explicit ≥16px
declarations under its own source contract. Following the
`tests/test_docs_site_tokens.py` spec↔artifact discipline, these tests parse *both* the
blueprint and the site sources and compare — no third transcription — with loud parser-sanity
asserts on row counts. Four families:

- **Contrast math** — the committed WCAG 2.2 check over the LIVE token values (all §9 pairs in
  both themes, plus the inline-code backgrounds), replacing axe's layout-dependent
  `color-contrast` rule (disabled in `docs/site/checks/a11y.test.mjs`), and the §11
  code-palette evidence recomputed against the live surface tokens.
- **system.css structure** — the §3 scale's custom properties AND their consuming rules (a
  token without its consumer is dead), the §2 measure/focus/inline-code treatments, the §6
  reduced-motion block value-complete, the §4C containment/wide mode, and the §4B eyebrows
  with their exact route enumeration (set equality — a sixth `:is()` arm or a prefix match
  fails).
- **§11/§12 finish treatments** — the bound-treatments tables realized value-exact: §11 in
  system.css (one rule per selector; U7 resolves through the single `:root` rule), §12 across
  its named files (compositions.css, system.css, the two-planes diagram component), plus the
  §12 hero-wash contrast evidence recomputed against the live tokens.
- **Diagram geometry** — provable-by-construction §5 label sizing: container-query exposure
  keyed on the content column, `max-width` equal to each variant's viewBox width (no
  upscaling, so declared px sizes are final), and every `<text>` resolving to a ≥16px rule;
  plus the core-flow component's interactive source contract (zero SVG, three details-open
  disclosures, the bound 640/960 container thresholds, px ≥16 font sizes).
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BLUEPRINT = REPO_ROOT / "docs/design/docs-site-visual-blueprint.md"
TOKENS_CSS = REPO_ROOT / "docs/site/src/styles/tokens.css"
SYSTEM_CSS = REPO_ROOT / "docs/site/src/styles/system.css"
COMPOSITIONS_CSS = REPO_ROOT / "docs/site/src/styles/compositions.css"
COMPONENTS_DIR = REPO_ROOT / "docs/site/src/components"

DARK_SCOPE = ":root"
LIGHT_SCOPE = ':root[data-theme="light"]'
MEDIA_768 = "@media (min-width: 768px)"
MEDIA_1280 = "@media (min-width: 1280px)"
CONTAINER_736 = "@container (min-width: 736px)"

# The settled §4B/§4C route enumerations (operator-confirmed in the plan): the four quadrant
# landings with their eyebrow labels, and the five configuration children that opt into the
# path eyebrow + 92ch wide mode. A new route must be enrolled here deliberately.
LANDING_EYEBROWS = {
    "/tutorials/": "Tutorials",
    "/how-to/": "How-to",
    "/reference/": "Reference",
    "/explanation/": "Explanation",
}
CONFIG_WIDE_ROUTES = {
    "/reference/configuration/repository-layout/",
    "/reference/configuration/workflow-and-ci/",
    "/reference/configuration/backends/",
    "/reference/configuration/models-and-compaction/",
    "/reference/configuration/skills-and-bindings/",
}

# §12 file vocabulary (`docs/site/src/`-relative, as the bound-treatments table names them)
# → repo paths, and the selectors whose rules live inside the 1280px media block (the U14 duo
# seam exists only where bands 4+5 share a row).
SECTION_12_FILES = {
    "styles/compositions.css": COMPOSITIONS_CSS,
    "styles/system.css": SYSTEM_CSS,
    "components/TwoPlanesDiagram.astro": COMPONENTS_DIR / "TwoPlanesDiagram.astro",
}
SECTION_12_MEDIA_1280_SELECTORS = {".perk-home-duo", ".perk-home-duo .perk-band"}

# §9 pair vocabulary → the live token carrying each side (resolved through var() indirection
# in tokens.css). `accent-invert` is the §2 primary-button text — white on the light accent,
# dark canvas on the dark accent — exactly `--sl-color-text-invert`.
PAIR_TOKENS = {
    "text": "--perk-text",
    "muted": "--perk-muted",
    "accent": "--perk-accent",
    "accent-strong": "--perk-accent-strong",
    "accent-invert": "--sl-color-text-invert",
    "success": "--perk-success",
    "success-low": "--perk-success-low",
    "warning": "--perk-warning",
    "warning-low": "--perk-warning-low",
    "danger": "--perk-danger",
    "danger-low": "--perk-danger-low",
    "canvas": "--perk-canvas",
    "surface": "--perk-surface",
}

# The §12 hero-wash pairs additionally name the wash/hover surfaces and the primary-button
# text tier directly (`text-invert` is Starlight's own property; the two accent surfaces have
# no `--perk-*` alias).
WASH_PAIR_TOKENS = PAIR_TOKENS | {
    "text-invert": "--sl-color-text-invert",
    "accent-low": "--sl-color-accent-low",
    "accent-high": "--sl-color-accent-high",
}


# --- Shared parsing helpers -------------------------------------------------------------


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _must_match(pattern: str, text: str) -> re.Match[str]:
    match = re.match(pattern, text)
    assert match is not None, f"{pattern!r} does not match {text!r}"
    return match


def _must_search(pattern: str, text: str, flags: int = 0) -> re.Match[str]:
    match = re.search(pattern, text, flags)
    assert match is not None, f"{pattern!r} not found"
    return match


class Rule:
    """One flattened CSS rule: at-rule context, selector path, and its declarations."""

    def __init__(self, contexts: tuple[str, ...], selectors: tuple[str, ...]):
        self.contexts = contexts
        self.selectors = selectors
        self.declarations: dict[str, str] = {}

    @property
    def selector(self) -> str:
        return " ".join(self.selectors)


def _parse_css(css_text: str) -> list[Rule]:
    """Brace-aware parse of a (possibly nested) stylesheet into flattened `Rule`s.

    Handles the shapes this repo's stylesheets use: at-rule blocks (`@media`, `@container`)
    and one level of selector nesting (the system.css config scope; a nested selector joins
    its parent with a descendant space). Selectors and values are whitespace-normalized.
    Parser-sanity asserts in the tests keep a silent mis-parse from passing vacuously.
    """
    css_text = re.sub(r"/\*.*?\*/", "", css_text, flags=re.DOTALL)
    rules: list[Rule] = []

    def parse_block(pos: int, contexts: tuple[str, ...], selectors: tuple[str, ...]) -> int:
        rule = Rule(contexts, selectors)
        if selectors:
            rules.append(rule)
        buffer = ""
        while pos < len(css_text):
            char = css_text[pos]
            if char == "}":
                return pos + 1
            if char == ";":
                prop, _, value = buffer.partition(":")
                if value:
                    rule.declarations[_normalize(prop)] = _normalize(value)
                buffer = ""
                pos += 1
            elif char == "{":
                header = _normalize(buffer)
                buffer = ""
                if header.startswith("@"):
                    pos = parse_block(pos + 1, (*contexts, header), ())
                else:
                    pos = parse_block(pos + 1, contexts, (*selectors, header))
            else:
                buffer += char
                pos += 1
        return pos

    parse_block(0, (), ())
    return rules


def _find_rule(rules: list[Rule], selector: str, contexts: tuple[str, ...] = ()) -> Rule:
    matches = [r for r in rules if r.selector == selector and r.contexts == contexts]
    assert len(matches) == 1, f"expected exactly one rule {contexts} {selector!r}: {len(matches)}"
    return matches[0]


def _section(text: str, start: str, end: str) -> str:
    start_idx = text.index(start)
    end_idx = text.index(end, start_idx)
    return text[start_idx:end_idx]


def _px_to_rem(px: int) -> str:
    return f"{px / 16:g}rem"


# --- Blueprint parsing (the spec side) --------------------------------------------------


def _parse_type_scale(blueprint: str) -> dict[str, dict[str, str]]:
    """The §3 type-scale table: role -> {narrow, wide, line_height} (raw cell text)."""
    section = _section(blueprint, "### Type scale and rules", "## §4 Compositions")
    rows: dict[str, dict[str, str]] = {}
    for line in section.splitlines():
        match = re.match(r"^\| ([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \|$", line)
        if match is None or match.group(1).strip() == "Role":
            continue
        rows[match.group(1).strip()] = {
            "narrow": match.group(2).strip(),
            "wide": match.group(3).strip(),
            "line_height": match.group(4).strip(),
        }
    return rows


def _parse_shape_rows(blueprint: str) -> dict[str, str]:
    """The §2 spacing/shape/measure table: row label -> raw bound-value cell."""
    section = _section(blueprint, "### Spacing, shape, and measure", "## §3 Typography")
    rows: dict[str, str] = {}
    for line in section.splitlines():
        match = re.match(r"^\| ([^|]+) \| ([^|]+) \|$", line)
        if match is not None:
            rows[match.group(1).strip()] = match.group(2).strip()
    return rows


def _parse_inline_code_hexes(blueprint: str) -> tuple[str, str]:
    """The §2 prose-bound inline-code backgrounds: (light hex, dark hex), lowercased."""
    match = _must_search(
        r"Inline code backgrounds are `(#[0-9A-Fa-f]{6})` light and `(#[0-9A-Fa-f]{6})` dark",
        blueprint,
    )
    return match.group(1).lower(), match.group(2).lower()


def _parse_contrast_pairs(blueprint: str) -> list[tuple[str, str, str, str, str]]:
    """The §9 verbatim contrast rows: (theme, fg name, bg name, fg hex, bg hex)."""
    section = _section(blueprint, "### Programmatic WCAG 2.2 AA contrast check", "Exit status:")
    pairs = []
    for line in section.splitlines():
        match = re.match(
            r"^(light|dark)\s+([\w-]+)/([\w-]+)\s+(#[0-9A-Fa-f]{6})\s+(#[0-9A-Fa-f]{6})\s",
            line,
        )
        if match is None:
            continue
        pairs.append(
            (
                match.group(1),
                match.group(2),
                match.group(3),
                match.group(4).lower(),
                match.group(5).lower(),
            )
        )
    return pairs


def _parse_finish_rows(blueprint: str) -> list[tuple[str, str, str, str]]:
    """The §11 bound-treatments table: (unit, selector, property, value) — backtick-exact."""
    section = _section(
        blueprint,
        "## §11 Article-page and shell-chrome finish",
        "### Code-palette contrast evidence",
    )
    rows = []
    for line in section.splitlines():
        match = re.match(r"^\| (U\d) \| `([^`]+)` \| `([^`]+)` \| `([^`]+)` \|$", line)
        if match is not None:
            rows.append((match.group(1), match.group(2), match.group(3), match.group(4)))
    return rows


def _parse_palette_rows(blueprint: str) -> list[tuple[str, str, str, str]]:
    """The §11 contrast-evidence table: (theme, fg hex, bg hex, recorded 2-decimal ratio)."""
    section = _section(
        blueprint, "### Code-palette contrast evidence", "## §12 Home and landing finish"
    )
    rows = []
    for line in section.splitlines():
        match = re.match(
            r"^\| (light|dark) \| `(#[0-9a-f]{6})` \| `(#[0-9a-f]{6})` \| ([\d.]+) \|$", line
        )
        if match is not None:
            rows.append((match.group(1), match.group(2), match.group(3), match.group(4)))
    return rows


def _parse_home_landing_rows(blueprint: str) -> list[tuple[str, str, str, str, str]]:
    """The §12 bound-treatments table: (unit, file, selector, property, value) — backtick-exact."""
    section = _section(
        blueprint, "## §12 Home and landing finish", "### Hero-wash contrast evidence"
    )
    rows = []
    for line in section.splitlines():
        match = re.match(
            r"^\| (U\d+) \| `([^`]+)` \| `([^`]+)` \| `([^`]+)` \| `([^`]+)` \|$", line
        )
        if match is not None:
            rows.append(
                (match.group(1), match.group(2), match.group(3), match.group(4), match.group(5))
            )
    return rows


def _parse_wash_rows(blueprint: str) -> list[tuple[str, str, str, str, str, str]]:
    """The §12 hero-wash evidence: (theme, fg name, bg name, fg hex, bg hex, recorded ratio).

    Deliberately a 5-column shape in the blueprint — it can never match the §11 palette
    parser's 4-column row regex.
    """
    section = blueprint[blueprint.index("### Hero-wash contrast evidence") :]
    rows = []
    for line in section.splitlines():
        match = re.match(
            r"^\| (light|dark) \| ([\w-]+)/([\w-]+) \| `(#[0-9a-f]{6})` \|"
            r" `(#[0-9a-f]{6})` \| ([\d.]+) \|$",
            line,
        )
        if match is not None:
            rows.append(
                (
                    match.group(1),
                    match.group(2),
                    match.group(3),
                    match.group(4),
                    match.group(5),
                    match.group(6),
                )
            )
    return rows


# --- Live token resolution + WCAG math --------------------------------------------------


def _token_scopes() -> dict[str, dict[str, str]]:
    rules = _parse_css(TOKENS_CSS.read_text(encoding="utf-8"))
    scopes = {rule.selector: rule.declarations for rule in rules}
    assert set(scopes) == {DARK_SCOPE, LIGHT_SCOPE}, sorted(scopes)
    return scopes


def _resolve(scopes: dict[str, dict[str, str]], theme: str, prop: str) -> str:
    """Resolve a custom property to its hex in a theme scope (light falls back to :root —
    the cascade: light-scope declarations override the :root defaults)."""
    scope = LIGHT_SCOPE if theme == "light" else DARK_SCOPE
    for _ in range(5):
        value = scopes[scope].get(prop) or scopes[DARK_SCOPE].get(prop)
        assert value is not None, f"{theme}: {prop} not declared in tokens.css"
        inner = re.fullmatch(r"var\((--[\w-]+)\)", value)
        if inner is None:
            assert re.fullmatch(r"#[0-9a-f]{6}", value), f"{theme} {prop}: non-hex {value!r}"
            return value
        prop = inner.group(1)
    raise AssertionError(f"var() indirection too deep resolving {prop}")


def _luminance(hex_color: str) -> float:
    channels = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(fg: str, bg: str) -> float:
    lighter, darker = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


# --- Contrast: the committed WCAG check over the live tokens ----------------------------


def test_live_tokens_meet_wcag_contrast():
    blueprint = BLUEPRINT.read_text(encoding="utf-8")
    pairs = _parse_contrast_pairs(blueprint)
    assert len(pairs) == 28, f"expected the 28 §9 rows, parsed {len(pairs)}"
    assert sum(1 for theme, *_ in pairs if theme == "light") == 14

    scopes = _token_scopes()
    for theme, fg_name, bg_name, fg_hex, bg_hex in pairs:
        fg = _resolve(scopes, theme, PAIR_TOKENS[fg_name])
        bg = _resolve(scopes, theme, PAIR_TOKENS[bg_name])
        # The live token must still be the §9-verified value (a drifted transcription would
        # make the recorded evidence a lie)…
        assert fg == fg_hex, f"{theme} {fg_name}: live {fg} != §9 {fg_hex}"
        assert bg == bg_hex, f"{theme} {bg_name}: live {bg} != §9 {bg_hex}"
        # …and the pair must pass AA normal-text contrast by live math.
        ratio = _contrast(fg, bg)
        assert ratio >= 4.5, f"{theme} {fg_name}/{bg_name}: {ratio:.2f} < 4.5"

    # The §2 inline-code backgrounds (hosted in system.css — no named token) against each
    # theme's primary text: the substitute for axe's disabled color-contrast rule.
    light_code, dark_code = _parse_inline_code_hexes(blueprint)
    for theme, code_bg in (("light", light_code), ("dark", dark_code)):
        text = _resolve(scopes, theme, "--perk-text")
        ratio = _contrast(text, code_bg)
        assert ratio >= 4.5, f"{theme} text/inline-code: {ratio:.2f} < 4.5"


# --- system.css structure: consumers, not just tokens -----------------------------------


def test_system_css_applies_the_type_scale_with_consumers():
    scale = _parse_type_scale(BLUEPRINT.read_text(encoding="utf-8"))
    assert len(scale) == 8, sorted(scale)

    rules = _parse_css(SYSTEM_CSS.read_text(encoding="utf-8"))
    root = _find_rule(rules, DARK_SCOPE)
    root_768 = _find_rule(rules, DARK_SCOPE, (MEDIA_768,))

    # Size custom properties, narrow + >=768px (roles whose wide value differs re-declare in
    # the media block; same-size roles must not).
    text_vars = {
        "Body": "--sl-text-base",
        "Small/meta": "--sl-text-sm",
        "Article H1": "--sl-text-h1",
        "H2": "--sl-text-h2",
        "H3": "--sl-text-h3",
        "H4": "--sl-text-h4",
    }
    for role, var in text_vars.items():
        narrow_px = int(_must_match(r"(\d+)px", scale[role]["narrow"]).group(1))
        wide_cell = scale[role]["wide"]
        wide_px = int(_must_match(r"(\d+)px", wide_cell).group(1)) if "px" in wide_cell else 0
        assert root.declarations.get(var) == _px_to_rem(narrow_px), f"{role} narrow ({var})"
        if wide_px != narrow_px:
            assert root_768.declarations.get(var) == _px_to_rem(wide_px), f"{role} wide ({var})"
        else:
            assert var not in root_768.declarations, f"{role}: needless {var} media re-declaration"

    # The consuming rules — the token alone is dead (Starlight's body has no font-size).
    assert _find_rule(rules, "body").declarations.get("font-size") == "var(--sl-text-base)"
    assert root.declarations.get("--sl-line-height") == scale["Body"]["line_height"]

    small_meta = _find_rule(rules, ".perk-diagram-text, .perk-band-compact")
    assert small_meta.declarations.get("line-height") == scale["Small/meta"]["line_height"]

    heading_roles = {"h1": "Article H1", "h2": "H2", "h3": "H3", "h4": "H4"}
    for element, role in heading_roles.items():
        rule = _find_rule(rules, element)
        assert rule.declarations.get("line-height") == scale[role]["line_height"], element

    # Eyebrow line-height consumer: the compositions.css band eyebrows are h2-styled, so the
    # global h2 rule above would otherwise apply (the h1#_top::before consumer is asserted
    # with the shared eyebrow block).
    eyebrow_lh = scale["Eyebrow"]["line_height"]
    assert _find_rule(rules, ".perk-band h2").declarations.get("line-height") == eyebrow_lh

    # Home hero H1 — the sole display-sized text.
    hero = _find_rule(rules, ".hero h1")
    hero_narrow = int(_must_match(r"(\d+)px", scale["Home hero H1"]["narrow"]).group(1))
    hero_wide = int(_must_match(r"(\d+)px", scale["Home hero H1"]["wide"]).group(1))
    assert hero.declarations.get("font-size") == _px_to_rem(hero_narrow)
    assert hero.declarations.get("line-height") == scale["Home hero H1"]["line_height"]
    hero_768 = _find_rule(rules, ".hero h1", (MEDIA_768,))
    assert hero_768.declarations.get("font-size") == _px_to_rem(hero_wide)


def test_system_css_applies_measure_focus_motion_and_containment():
    blueprint = BLUEPRINT.read_text(encoding="utf-8")
    shape = _parse_shape_rows(blueprint)
    rules = _parse_css(SYSTEM_CSS.read_text(encoding="utf-8"))
    root = _find_rule(rules, DARK_SCOPE)

    # §2 prose measure (72ch target; ch resolves at the consuming container).
    prose_measure = _must_match(r"`(\d+ch)` target", shape["Prose measure"]).group(1)
    assert root.declarations.get("--sl-content-width") == prose_measure

    # §2 focus: the universal rule from the bound Focus row, plus the ONE pinned inset
    # exception (Starlight's mobile-ToC full-width <summary>).
    focus = _must_match(r"(\d+px) `(--[\w-]+)` outline, (\d+px) offset", shape["Focus"])
    universal = _find_rule(rules, ":focus-visible")
    assert universal.declarations.get("outline") == f"{focus.group(1)} solid var({focus.group(2)})"
    assert universal.declarations.get("outline-offset") == focus.group(3)
    inset = _find_rule(rules, "mobile-starlight-toc summary:focus-visible")
    assert inset.declarations.get("outline-offset") == "var(--sl-outline-offset-inside)"

    # §6 reduced motion — value-complete: the exact selector and all four declarations.
    motion = _find_rule(rules, "*, ::before, ::after", ("@media (prefers-reduced-motion: reduce)",))
    assert motion.declarations == {
        "animation-duration": "0.01ms !important",
        "animation-iteration-count": "1 !important",
        "transition-duration": "0.01ms !important",
        "scroll-behavior": "auto !important",
    }

    # §4C table containment: the visible frame (scroll behavior itself stays Starlight's).
    table = _find_rule(rules, ".sl-markdown-content table")
    assert table.declarations.get("background") == "var(--perk-surface)"
    assert table.declarations.get("border") == "1px solid var(--perk-border)"
    assert table.declarations.get("border-radius") == "var(--perk-radius-control)"
    assert table.declarations.get("padding") == "0.5rem 1rem"

    # §2 inline-code backgrounds — the one sanctioned literal-hex exception, equal to the
    # blueprint's prose sentence in both theme scopes.
    light_code, dark_code = _parse_inline_code_hexes(blueprint)
    assert root.declarations.get("--sl-color-bg-inline-code") == dark_code
    light_scope = _find_rule(rules, LIGHT_SCOPE)
    assert light_scope.declarations.get("--sl-color-bg-inline-code") == light_code


def test_system_css_eyebrows_and_wide_mode_enumerate_the_settled_routes():
    blueprint = BLUEPRINT.read_text(encoding="utf-8")
    scale = _parse_type_scale(blueprint)
    shape = _parse_shape_rows(blueprint)
    css_text = SYSTEM_CSS.read_text(encoding="utf-8")
    rules = _parse_css(css_text)

    # No prefix/substring attribute matching anywhere: enrollment is exact-href only.
    assert "href^=" not in css_text and "href*=" not in css_text

    # The shared eyebrow block: §3 eyebrow type (12px, 600, 0.08em tracking, 1.4), muted, an
    # exact §2 spacing-step bottom margin, and NO content declaration (only a matching label
    # rule below generates a box).
    eyebrow = _must_match(r"(\d+)px, (\d+), `([\d.]+em)` tracking", scale["Eyebrow"]["narrow"])
    shared = _find_rule(rules, "h1#_top::before")
    assert shared.declarations.get("display") == "block"
    assert shared.declarations.get("font-family") == "var(--sl-font-mono), monospace"
    assert shared.declarations.get("font-size") == _px_to_rem(int(eyebrow.group(1)))
    assert shared.declarations.get("font-weight") == eyebrow.group(2)
    assert shared.declarations.get("letter-spacing") == eyebrow.group(3)
    assert shared.declarations.get("line-height") == scale["Eyebrow"]["line_height"]
    assert shared.declarations.get("text-transform") == "uppercase"
    assert shared.declarations.get("color") == "var(--perk-muted)"
    assert shared.declarations.get("margin-block") == "0 0.5rem"
    assert "content" not in shared.declarations
    steps = _must_search(r"spacing steps `([\d, ]+)px`", shape["Base grid"])
    step_values = [int(step) for step in steps.group(1).split(",")]
    assert 0.5 * 16 in step_values, "eyebrow bottom margin must be an exact §2 spacing step"

    # The four landing label rules, each with the `/ ""` alt-text form (decorative — the
    # eyebrow must not pollute the H1's accessible name).
    for href, label in LANDING_EYEBROWS.items():
        selector = f'body:has(a[aria-current="page"][href="{href}"]) h1#_top::before'
        rule = _find_rule(rules, selector)
        assert rule.declarations.get("content") == f'"{label}" / ""', href

    # The §4C config scope: ONE body:has() rule enumerating EXACTLY the five settled hrefs.
    scope_selectors = {
        rule.selectors[0]
        for rule in rules
        if rule.selectors
        and rule.selectors[0].startswith("body:has(")
        and 'a[aria-current="page"]:is(' in rule.selectors[0]
    }
    assert len(scope_selectors) == 1, scope_selectors
    scope_selector = scope_selectors.pop()
    hrefs = set(re.findall(r'\[href="([^"]+)"\]', scope_selector))
    assert hrefs == CONFIG_WIDE_ROUTES, hrefs.symmetric_difference(CONFIG_WIDE_ROUTES)

    # Wide mode: 92ch on the scope, prose re-capped at 72ch inside the same scope, and the
    # path eyebrow (a file path — never uppercased).
    wide_measure = _must_match(r"`(\d+ch)` maximum", shape["Reference-wide measure"]).group(1)
    prose_measure = _must_match(r"`(\d+ch)` target", shape["Prose measure"]).group(1)
    scope = _find_rule(rules, scope_selector)
    assert scope.declarations.get("--sl-content-width") == wide_measure
    path_eyebrow = _find_rule(rules, f"{scope_selector} h1#_top::before")
    assert path_eyebrow.declarations.get("content") == '".perk/config.toml" / ""'
    assert path_eyebrow.declarations.get("text-transform") == "none"
    recap = _find_rule(rules, f"{scope_selector} .sl-markdown-content :is(p, ul, ol, blockquote)")
    assert recap.declarations.get("max-width") == prose_measure


# --- §11 finish treatments: the bound table realized value-exact -------------------------


def test_system_css_applies_article_shell_finish():
    """Every §11 bound-treatments row exists in system.css value-exact (spec↔artifact)."""
    rows = _parse_finish_rows(BLUEPRINT.read_text(encoding="utf-8"))
    # Parser sanity: the exact approved-row count and unit set pinned at amendment time.
    assert len(rows) == 19, f"expected the 19 §11 rows, parsed {len(rows)}"
    assert {unit for unit, *_ in rows} == {f"U{n}" for n in range(1, 10)}

    rules = _parse_css(SYSTEM_CSS.read_text(encoding="utf-8"))
    for unit, selector, prop, value in rows:
        rule = _find_rule(rules, selector)
        assert rule.declarations.get(prop) == value, f"{unit}: {selector!r} {prop}"


def test_code_palette_contrast_evidence():
    """The §11 dated palette evidence holds by live math against the live surface tokens."""
    rows = _parse_palette_rows(BLUEPRINT.read_text(encoding="utf-8"))
    assert len(rows) == 21, f"expected the 21 §11 evidence rows, parsed {len(rows)}"
    assert sum(1 for theme, *_ in rows if theme == "dark") == 11
    assert sum(1 for theme, *_ in rows if theme == "light") == 10

    scopes = _token_scopes()
    for theme, fg, bg, recorded in rows:
        # The recorded background must be the LIVE resolved --perk-surface for its theme (a
        # drifted token would make the recorded evidence a lie)…
        assert bg == _resolve(scopes, theme, "--perk-surface"), f"{theme} background drift"
        # …and every ratio must pass AA and agree with the recorded 2-decimal value.
        ratio = _contrast(fg, bg)
        assert ratio >= 4.5, f"{theme} {fg}: {ratio:.2f} < 4.5"
        assert f"{ratio:.2f}" == recorded, f"{theme} {fg}: live {ratio:.2f} != recorded {recorded}"

    # The §11 method note's membership claim: the stock --ec-codeFg values are palette members.
    assert "#d6deeb" in {fg for theme, fg, *_ in rows if theme == "dark"}
    assert "#403f53" in {fg for theme, fg, *_ in rows if theme == "light"}


# --- §12 home/landing finish: the bound table realized value-exact -----------------------


def test_home_landing_finish_applies_the_section_12_table():
    """Every §12 bound-treatments row exists in its named file value-exact (spec↔artifact)."""
    rows = _parse_home_landing_rows(BLUEPRINT.read_text(encoding="utf-8"))
    # Parser sanity: the exact landed row count and unit set pinned at amendment time.
    assert len(rows) == 26, f"expected the 26 §12 rows, parsed {len(rows)}"
    assert {unit for unit, *_ in rows} == {f"U{n}" for n in range(10, 20)}

    rules_by_file: dict[str, list[Rule]] = {}
    for file_key, path in SECTION_12_FILES.items():
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".astro":
            text = _must_search(r"<style>(.*?)</style>", text, re.DOTALL).group(1)
        rules_by_file[file_key] = _parse_css(text)

    for unit, file_key, selector, prop, value in rows:
        assert file_key in rules_by_file, f"{unit}: unknown §12 file {file_key!r}"
        contexts = (MEDIA_1280,) if selector in SECTION_12_MEDIA_1280_SELECTORS else ()
        rule = _find_rule(rules_by_file[file_key], selector, contexts)
        assert rule.declarations.get(prop) == value, f"{unit}: {selector!r} {prop}"


def test_hero_wash_contrast_evidence():
    """The §12 dated hero-wash evidence holds by live math against the live tokens."""
    rows = _parse_wash_rows(BLUEPRINT.read_text(encoding="utf-8"))
    # Parser sanity: the four bound pairs per theme.
    assert len(rows) == 8, f"expected the 8 §12 evidence rows, parsed {len(rows)}"
    assert sum(1 for theme, *_ in rows if theme == "light") == 4
    assert sum(1 for theme, *_ in rows if theme == "dark") == 4

    scopes = _token_scopes()
    for theme, fg_name, bg_name, fg_hex, bg_hex, recorded in rows:
        fg = _resolve(scopes, theme, WASH_PAIR_TOKENS[fg_name])
        bg = _resolve(scopes, theme, WASH_PAIR_TOKENS[bg_name])
        # The recorded hexes must be the LIVE resolved tokens (a drifted transcription would
        # make the recorded evidence a lie)…
        assert fg == fg_hex, f"{theme} {fg_name}: live {fg} != §12 {fg_hex}"
        assert bg == bg_hex, f"{theme} {bg_name}: live {bg} != §12 {bg_hex}"
        # …and every pair must pass AA normal-text contrast with 2-decimal agreement.
        ratio = _contrast(fg, bg)
        assert ratio >= 4.5, f"{theme} {fg_name}/{bg_name}: {ratio:.2f} < 4.5"
        assert f"{ratio:.2f}" == recorded, (
            f"{theme} {fg_name}/{bg_name}: live {ratio:.2f} != recorded {recorded}"
        )


# --- Diagram geometry: the §5 label floor by construction -------------------------------

# The committed component set: four static-SVG components under the §5 two-variant contract,
# plus the interactive semantic-HTML core-flow component (its own source contract below).
SVG_DIAGRAM_COMPONENTS = {
    "TwoPlanesDiagram.astro",
    "PlansInsideObjectivesDiagram.astro",
    "WarmColdDoorsDiagram.astro",
    "HeadlessRemoteDiagram.astro",
}
CORE_FLOW_COMPONENT = "CoreFlowDiagram.astro"


def test_diagram_components_hold_the_label_floor_by_construction():
    components = sorted(COMPONENTS_DIR.glob("*.astro"))
    assert {component.name for component in components} == SVG_DIAGRAM_COMPONENTS | {
        CORE_FLOW_COMPONENT
    }, [component.name for component in components]

    # The exposure container: figure.perk-diagram is the inline-size container the components'
    # @container queries key on (the core-flow figure reuses it through the shared class).
    composition_rules = _parse_css(COMPOSITIONS_CSS.read_text(encoding="utf-8"))
    figure = _find_rule(composition_rules, ".perk-diagram")
    assert figure.declarations.get("container-type") == "inline-size"

    for component in components:
        name = component.name
        if name == CORE_FLOW_COMPONENT:
            continue  # interactive semantic-HTML contract — its own test below
        # Strip the {/* … */} header comment — it narrates the markup it precedes (e.g.
        # `<svg role="img">`), which must not read as elements.
        text = re.sub(r"\{/\*.*?\*/\}", "", component.read_text(encoding="utf-8"), flags=re.DOTALL)

        svgs = re.findall(r"<svg\b.*?</svg>", text, flags=re.DOTALL)
        assert len(svgs) == 2, f"{name}: expected exactly two SVG variants"
        widths: dict[str, int] = {}
        texts_by_variant: dict[str, list[str]] = {}
        for svg in svgs:
            tag = svg[: svg.index(">")]
            assert 'role="img"' in tag, f"{name}: SVG without role"
            variant = _must_search(r'data-variant="(\w+)"', tag).group(1)
            widths[variant] = int(_must_search(r'viewBox="0 0 (\d+) \d+"', tag).group(1))
            texts_by_variant[variant] = re.findall(r"<text\b([^>]*)>", svg)
        assert set(widths) == {"wide", "narrow"}, f"{name}: {sorted(widths)}"
        # Wide is exposed only at container >= 736 (its viewBox width — scale 1); narrow must
        # fit the ~288px content column at the 320px acceptance floor.
        assert widths["wide"] == 736, f"{name}: wide viewBox width {widths['wide']}"
        assert widths["narrow"] <= 288, f"{name}: narrow viewBox width {widths['narrow']}"

        style_text = _must_search(r"<style>(.*?)</style>", text, re.DOTALL).group(1)
        # Exposure is container-keyed only — no viewport media query may remain.
        assert "@media" not in style_text, f"{name}: viewport media query remains"
        style_rules = _parse_css(style_text)

        for variant, width in widths.items():
            base = _find_rule(style_rules, f'svg[data-variant="{variant}"]')
            # max-width == viewBox width: no upscaling, so declared px label sizes are final
            # at exposure.
            assert base.declarations.get("max-width") == f"{width}px", f"{name}: {variant}"
        # Default (narrow container, or no container-query support): narrow shows, wide is
        # hidden; the @container flip keeps exactly one variant rendered (and in the
        # accessibility tree) at any width, each only where it fits at scale 1.
        wide_base = _find_rule(style_rules, 'svg[data-variant="wide"]')
        assert wide_base.declarations.get("display") == "none", f"{name}: wide must default hidden"
        narrow_base = _find_rule(style_rules, 'svg[data-variant="narrow"]')
        assert narrow_base.declarations.get("display") != "none", f"{name}: narrow is the default"
        wide_flip = _find_rule(style_rules, 'svg[data-variant="wide"]', (CONTAINER_736,))
        assert wide_flip.declarations.get("display") == "block", name
        narrow_flip = _find_rule(style_rules, 'svg[data-variant="narrow"]', (CONTAINER_736,))
        assert narrow_flip.declarations.get("display") == "none", name

        # Text-to-rule association: every <text> carries a class resolving to an explicit
        # >= 16px font-size rule in this component's own <style>.
        class_sizes: dict[str, str] = {}
        for rule in style_rules:
            if "font-size" not in rule.declarations:
                continue
            for part in rule.selector.split(","):
                simple = re.fullmatch(r"\.([\w-]+)", part.strip())
                if simple is not None:
                    class_sizes[simple.group(1)] = rule.declarations["font-size"]
        for variant, text_tags in texts_by_variant.items():
            assert len(text_tags) > 0, f"{name} {variant}: no <text> labels"
            for attrs in text_tags:
                class_match = re.search(r'class="([^"]+)"', attrs)
                assert class_match is not None, f"{name} {variant}: <text> without a class"
                classes = class_match.group(1).split()
                sizes = [class_sizes[cls] for cls in classes if cls in class_sizes]
                assert sizes, f"{name} {variant}: no font-size rule for classes {classes}"
                for size in sizes:
                    px = re.fullmatch(r"([\d.]+)px", size)
                    assert px is not None, f"{name} {variant}: non-px font-size {size!r}"
                    assert float(px.group(1)) >= 16, f"{name} {variant}: {size} < 16px"


def test_core_flow_component_holds_the_interactive_source_contract():
    """The §5 interactive semantic-HTML contract, provable from source: zero inline SVG,
    three source-expanded disclosures (no-JS/print content-completeness), exactly the two
    bound container thresholds keyed on the shared figure container (no viewport media query;
    `@media print` is the sole permitted exception), and every declared font-size px ≥ 16."""
    component = COMPONENTS_DIR / CORE_FLOW_COMPONENT
    # Strip the {/* … */} header comment — it narrates markup, which must not read as elements.
    text = re.sub(r"\{/\*.*?\*/\}", "", component.read_text(encoding="utf-8"), flags=re.DOTALL)

    assert "<svg" not in text, "the core-flow component must carry no inline SVG at all"

    details = re.findall(r"<details\b[^>]*>", text)
    assert len(details) == 3, f"expected exactly three <details>, found {len(details)}"
    for tag in details:
        assert re.search(r"<details open\b", tag), f"<details> must ship open in source: {tag}"
        assert "data-core-flow-disclosure" in tag, f"missing the controller hook: {tag}"

    style_text = _must_search(r"<style>(.*?)</style>", text, re.DOTALL).group(1)

    # Container-keyed layout only: the shared figure container at exactly the bound 640/960
    # thresholds, plus the named per-card `satellite` container at its one intentional
    # threshold (each card's summary flips on the CARD's width, never the viewport's).
    figure_thresholds: list[int] = []
    satellite_thresholds: list[int] = []
    for prelude in re.findall(r"@container\s*([^{]+)\{", style_text):
        named = re.fullmatch(r"satellite\s+\(min-width:\s*(\d+)px\)", prelude.strip())
        unnamed = re.fullmatch(r"\(min-width:\s*(\d+)px\)", prelude.strip())
        assert named is not None or unnamed is not None, (
            f"unexpected container prelude: {prelude!r}"
        )
        if named is not None:
            satellite_thresholds.append(int(named.group(1)))
        else:
            assert unnamed is not None
            figure_thresholds.append(int(unnamed.group(1)))
    assert sorted(set(figure_thresholds)) == [640, 960], (
        f"bound figure thresholds drifted: {figure_thresholds}"
    )
    assert sorted(set(satellite_thresholds)) == [440], (
        f"bound satellite-card threshold drifted: {satellite_thresholds}"
    )
    # The named container itself must exist on the satellite cards.
    assert re.search(r"container:\s*satellite\s*/\s*inline-size", style_text), (
        "the satellite cards must declare the named `satellite` inline-size container"
    )

    # No viewport media query may drive exposure; @media print is the sole permitted form.
    for prelude in re.findall(r"@media\s*([^{]+)\{", style_text):
        assert prelude.strip() == "print", f"viewport media query in the core flow: {prelude!r}"

    # Every declared font size is px and >= 16 (mono/Inter floors alike).
    sizes = re.findall(r"font-size:\s*([^;}]+)", style_text)
    assert sizes, "expected explicit font-size declarations"
    for size in sizes:
        px = re.fullmatch(r"([\d.]+)px", size.strip())
        assert px is not None, f"non-px font-size {size!r}"
        assert float(px.group(1)) >= 16, f"{size} < 16px"
