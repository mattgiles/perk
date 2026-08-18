"""Conformance guard: every `prompts/` template stays inside the frozen mini-jinja subset.

The frozen template-grammar subset (the SSOT is `shared/contracts.md §8.31`) is exactly:

1. Variable substitution `{{ <ident> }}` (bare identifier only).
2. Include `{% include "<path>" %}` (double-quoted path).
3. Conditionals `{% if/elif <cond> %}` / `{% else %}` / `{% endif %}`, where `<cond>` is built
   only from bare identifiers, double-quoted strings, `==`, and `and`/`or`/`not`.
4. Plain `{% %}` tags only (no `{%- … -%}` / `{{- … -}}` whitespace-control markers).

The scanner implementation is `perk_dev.prompt_grammar.scan_template` (shared with the
prose-review Assembly preview gate); this guard consumes it over every real template with an
allowlist posture — fail on any block matching no recognized construct — and additionally pins
the scanner's whole-source lexical completeness (multiline/unterminated/stray delimiter forms
are violations, a Python-side narrowing versus the TS runtime tokenizer).
"""

from perk_dev.prompt_grammar import scan_template

from perk._resources import prompts_dir


def _violations(text: str, rel: str) -> list[str]:
    """Collect `path:line N: <block>` violations in one template's source."""
    return [f"{rel}:{violation}" for violation in scan_template(text).violations]


def _template_files() -> list[tuple[str, str]]:
    """Every rendered `prompts/` template: (relative-path, text), README.md excluded."""
    root = prompts_dir()
    files: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root).as_posix()
        if rel == "README.md":
            continue
        files.append((rel, path.read_text()))
    return files


def test_scan_is_not_vacuous() -> None:
    rels = {rel for rel, _ in _template_files()}
    assert rels, "prompt-template scan came up empty — guard is vacuous"
    for anchor in (
        "stages/learn.md",
        "stages/objective-plan/seed.md",
        "common/plan-read/github.md",
        "_fixtures/templates/with_include.md",
    ):
        assert anchor in rels, f"scan missed {anchor} — guard is misaimed"
    assert "README.md" not in rels, "README.md must be excluded from the grammar scan"


def test_all_templates_in_frozen_subset() -> None:
    violations: list[str] = []
    for rel, text in _template_files():
        violations.extend(_violations(text, rel))
    assert not violations, (
        "prompt template(s) use constructs outside the frozen mini-jinja subset:\n"
        + "\n".join(violations)
        + "\nSee the frozen template-grammar subset in shared/contracts.md §8.31."
    )


def test_validator_flags_out_of_subset_blocks() -> None:
    bad = [
        "{% for x in y %}",
        "{% endfor %}",
        "{% set a = 1 %}",
        "{{ user.name }}",
        "{{ x | upper }}",
        "{%- if a -%}",
        "{{- x -}}",
        "{% if a in b %}",
        "{% if a != b %}",
        "{% if (a or b) %}",
        "{# comment #}",
        # Escaped string literals + out-of-containment include paths the runtime rejects.
        r'{% if a == "x\"y" %}',
        '{% include "../x.md" %}',
        '{% include "/x.md" %}',
        '{% include "" %}',
        '{% include "a/../b.md" %}',
        # Malformed condition shapes the runtime throws on.
        "{% if a b %}",
        "{% if a == %}",
        "{% if == a %}",
        "{% if not %}",
    ]
    for block in bad:
        assert _violations(block, "synthetic.md"), f"expected violation for {block!r}"


def test_validator_accepts_in_subset_blocks() -> None:
    good = [
        "{{ provider }}",
        "{{ pr_id }}",
        '{% if provider == "github" or provider == "linear" %}',
        "{% if not pr_id %}",
        "{% if a and b %}",
        "{% elif model %}",
        "{% else %}",
        "{% endif %}",
        '{% include "_fixtures/templates/_greeting.md" %}',
    ]
    for block in good:
        assert not _violations(block, "synthetic.md"), f"unexpected violation for {block!r}"


def test_whole_source_scan_flags_multiline_unterminated_stray_and_nested_forms() -> None:
    bad = [
        # Multiline blocks are violations even when their stripped content would be in-subset
        # (deliberately stricter than the TS runtime tokenizer, which accepts multiline tags).
        "{{ x\n}}",
        "{%\nif a %}text{% endif %}",
        "{% if a\n%}text{% endif %}",
        "{# spanning\ncomment #}",
        # Unterminated openers.
        "{{ x",
        "text {% if a",
        "{# never closed",
        # Stray closers (the TS runtime treats these as literal text; the scan does not).
        "plain }} text",
        "plain %} text",
        "plain #} text",
        "{{ x }}}}",
        # Nested / partially matched delimiter forms.
        "{{ a {% b %} }}",
        "{{ {{ x }} }}",
        "{% if a %} }}",
    ]
    for text in bad:
        assert scan_template(text).violations, f"expected violation for {text!r}"


def test_whole_source_scan_reports_start_lines_and_continues_past_violations() -> None:
    text = 'ok {{ provider }}\n{# bad #}\n{% if a\n%}\n{% include "x.md" %}\n'
    scan = scan_template(text)
    assert scan.violations == ("line 2: {# bad #}", "line 3: {% if a")
    assert scan.has_include is True
    assert scan.identifiers == frozenset({"provider"})

    unterminated = "one\ntwo {{ never\nthree {{ ignored }}\n"
    assert scan_template(unterminated).violations == ("line 2: {{ never",)


def test_has_include_is_true_exactly_for_valid_include_tags() -> None:
    assert scan_template('{% include "a/b.md" %}').has_include is True
    assert scan_template("{{ provider }}").has_include is False
    for invalid in ('{% include "../x.md" %}', '{% include "" %}', '{% include "/x.md" %}'):
        scan = scan_template(invalid)
        assert scan.has_include is False
        assert scan.violations


def test_identifiers_collect_substitution_and_condition_names_minus_keywords() -> None:
    text = (
        "{{ provider }}\n"
        '{% if provider == "github" and not pr_id or true %}\n'
        "{% elif false %}\n"
        "{% elif none %}\n"
        "{% else %}\n"
        "{% endif %}\n"
        '{% include "common/x.md" %}\n'
    )
    scan = scan_template(text)
    assert scan.violations == ()
    # `true`/`false`/`none` are lexically identifiers to the scan (jinja literals are NOT
    # admitted by the subset's variable namespace, so callers can reject them by mapping).
    assert scan.identifiers == frozenset({"provider", "pr_id", "true", "false", "none"})
    assert "and" not in scan.identifiers
    assert "or" not in scan.identifiers
    assert "not" not in scan.identifiers
