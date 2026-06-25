"""Conformance guard: every `prompts/` template stays inside the frozen mini-jinja subset.

The frozen template-grammar subset (the SSOT is `shared/contracts.md §8.31`) is exactly:

1. Variable substitution `{{ <ident> }}` (bare identifier only).
2. Include `{% include "<path>" %}` (double-quoted path).
3. Conditionals `{% if/elif <cond> %}` / `{% else %}` / `{% endif %}`, where `<cond>` is built
   only from bare identifiers, double-quoted strings, `==`, and `and`/`or`/`not`.
4. Plain `{% %}` tags only (no `{%- … -%}` / `{{- … -}}` whitespace-control markers).

This guard uses an **allowlist posture**: it extracts every `{{ … }}` / `{% … %}` block and fails
on any block matching no recognized construct — mirroring the node-4.2 vendored renderer's
throw-loudly-on-anything-unsupported discipline. It checks construct membership only, not if/endif
nesting balance (structural balance is proven by the golden harness rendering every real template).
The validator is test-only tooling (like `extension/surfacesGuard.test.ts`), not runtime code.
"""

import re

from perk._resources import prompts_dir

# A `{{ … }}`, `{% … %}`, or `{# … #}` block, captured non-greedily (blocks never span lines).
# Comments are matched only so the guard can REJECT them (not in the frozen subset).
_BLOCK = re.compile(r"\{\{(.*?)\}\}|\{%(.*?)%\}|\{#(.*?)#\}")

# A bare identifier — the only thing admitted inside `{{ }}` and the atom of a condition.
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# `include "<path>"` — double-quoted path only, NO escapes (`[^"\\]*`, mirroring miniJinja). The
# captured path is additionally checked for containment (non-empty / non-absolute / no `..`).
_INCLUDE = re.compile(r'include\s+"([^"\\]*)"')

# A whole `if`/`elif` condition: one-or-more of {identifier, double-quoted string (no escapes),
# `==`} separated by whitespace. Anything else (parens, `!=`, `<`/`>`, filters, dots, numbers,
# escaped quotes) leaves unrecognized text → no full match → violation. The string literal is
# `[^"\\]*` to mirror miniJinja's reject-escapes rule.
_COND = re.compile(r'(?:\s*(?:[A-Za-z_][A-Za-z0-9_]*|"[^"\\]*"|==)\s*)+')

# Bare-word tokens that LOOK like identifiers but are jinja operators outside the frozen subset.
# (The admitted keywords are exactly `and`/`or`/`not`; every other bare word is a variable name.)
_BANNED_COND_WORDS = {"in", "is"}

# Matches one condition token: a double-quoted string (no escapes), `==`, or a bare word.
_COND_TOKEN = re.compile(r'"[^"\\]*"|==|[A-Za-z_][A-Za-z0-9_]*')


def _cond_shape_valid(cond: str) -> bool:
    """True iff the condition is well-formed in miniJinja's grammar (`or` < `and` < `not` < `==`).

    `_COND` gates the character set; THIS rejects malformed valid-token sequences — `a b` (adjacent
    atoms), `a ==` / `== a` (missing operand), bare `not` — that the runtime renderer throws on,
    keeping the author-time guard consistent with render time.
    """
    kinds: list[str] = []
    for match in _COND_TOKEN.finditer(cond):
        token = match.group(0)
        if token == "==":
            kinds.append("eq")
        elif token in ("and", "or", "not"):
            kinds.append(token)
        else:
            kinds.append("atom")  # identifier or double-quoted string
    pos = 0

    def peek() -> str | None:
        return kinds[pos] if pos < len(kinds) else None

    def atom() -> bool:
        nonlocal pos
        if peek() == "atom":
            pos += 1
            return True
        return False

    def eq() -> bool:
        nonlocal pos
        if not atom():
            return False
        if peek() == "eq":
            pos += 1
            return atom()
        return True

    def not_expr() -> bool:
        nonlocal pos
        if peek() == "not":
            pos += 1
            return not_expr()
        return eq()

    def and_expr() -> bool:
        nonlocal pos
        if not not_expr():
            return False
        while peek() == "and":
            pos += 1
            if not not_expr():
                return False
        return True

    def or_expr() -> bool:
        nonlocal pos
        if not and_expr():
            return False
        while peek() == "or":
            pos += 1
            if not and_expr():
                return False
        return True

    return or_expr() and pos == len(kinds)


def _include_path_is_valid(p: str) -> bool:
    """Mirror miniJinja's resolveTemplatePath containment: non-empty / non-absolute / no `..`."""
    if not p:
        return False
    if p.startswith("/") or re.match(r"^[A-Za-z]:", p):  # absolute (posix or windows drive)
        return False
    return ".." not in re.split(r"[\\/]", p)


def _block_is_valid(raw: str, is_variable: bool) -> bool:
    """True iff one extracted block (without its delimiters) is in the frozen subset."""
    inner = raw.strip()
    if is_variable:
        # `{{ X }}`: X must be a single bare identifier (catches `{{- x -}}`, dots, filters, …).
        return bool(_IDENT.fullmatch(inner))
    # `{% X %}` (catches `{%- … -%}` since the leading `-` breaks every branch below).
    if inner in {"else", "endif"}:
        return True
    include = _INCLUDE.fullmatch(inner)
    if include is not None:
        return _include_path_is_valid(include.group(1))
    for keyword in ("if", "elif"):
        prefix = keyword + " "
        if inner.startswith(prefix):
            cond = inner[len(prefix) :].strip()
            if not cond or not _COND.fullmatch(cond):
                return False
            # Reject `in`/`is` operators (lexically identifiers) outside string literals.
            words = _IDENT.findall(re.sub(r'"[^"\\]*"', " ", cond))
            if any(word in _BANNED_COND_WORDS for word in words):
                return False
            # Reject malformed condition shapes the runtime renderer throws on.
            return _cond_shape_valid(cond)
    return False


def _violations(text: str, rel: str) -> list[str]:
    """Collect `path:line: <block>` violations in one template's source."""
    out: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for match in _BLOCK.finditer(line):
            if match.group(3) is not None:
                # `{# … #}` comment — never in the subset.
                out.append(f"{rel}:{lineno}: {match.group(0)}")
                continue
            is_variable = match.group(1) is not None
            inner = match.group(1) if is_variable else match.group(2)
            assert inner is not None
            if not _block_is_valid(inner, is_variable):
                out.append(f"{rel}:{lineno}: {match.group(0)}")
    return out


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
