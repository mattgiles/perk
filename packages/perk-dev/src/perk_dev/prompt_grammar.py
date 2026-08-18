"""Whole-source conformance scanner for the frozen mini-jinja template subset.

The frozen template-grammar subset (the SSOT is ``shared/contracts.md §8.31``) is exactly:

1. Variable substitution ``{{ <ident> }}`` (bare identifier only).
2. Include ``{% include "<path>" %}`` (double-quoted contained path).
3. Conditionals ``{% if/elif <cond> %}`` / ``{% else %}`` / ``{% endif %}``, where ``<cond>`` is
   built only from bare identifiers, double-quoted strings, ``==``, and ``and``/``or``/``not``.
4. Plain ``{% %}`` tags only (no ``{%- … -%}`` / ``{{- … -}}`` whitespace-control markers).

The scan keeps the allowlist posture — any block matching no recognized construct is a
violation — and is **lexically complete over the whole source**: unterminated openers, blocks
spanning newlines, stray closing delimiters, and nested/partially matched delimiter forms are
violations rather than unexamined text. That whole-source strictness is a deliberate
Python-side narrowing relative to the TS runtime tokenizer (``extension/substrate/miniJinja.ts``
accepts multiline tags and treats stray closers as literal text); the frozen construct set
itself is unchanged. Consumed by the ``tests/test_prompt_grammar.py`` conformance guard and by
the prose-review Assembly preview gate, which must prove editable text stays inside the subset
before the production render seam ever compiles it.

It checks construct membership only, not if/endif nesting balance (structural balance is proven
at render time — the golden harness for committed templates, the guarded render call for
Assembly preview).
"""

import re
from dataclasses import dataclass

# A bare identifier — the only thing admitted inside `{{ }}` and the atom of a condition.
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# `include "<path>"` — double-quoted path only, NO escapes (`[^"\\]*`, mirroring miniJinja). The
# captured path is additionally checked for containment (non-empty / non-absolute / no `..`).
_INCLUDE = re.compile(r'include\s+"([^"\\]*)"')

# A whole `if`/`elif` condition: one-or-more of {identifier, double-quoted string (no escapes),
# `==`} separated by blanks. Anything else (parens, `!=`, `<`/`>`, filters, dots, numbers,
# escaped quotes) leaves unrecognized text → no full match → violation. The string literal is
# `[^"\\]*` to mirror miniJinja's reject-escapes rule; `[ \t]` (not `\s`) keeps the character
# gate single-line even though multiline blocks are already rejected lexically.
_COND = re.compile(r'(?:[ \t]*(?:[A-Za-z_][A-Za-z0-9_]*|"[^"\\]*"|==)[ \t]*)+')

# Bare-word tokens that LOOK like identifiers but are jinja operators outside the frozen subset.
# (The admitted keywords are exactly `and`/`or`/`not`; every other bare word is a variable name —
# including `true`/`false`/`none`, which jinja parses as literals but the subset does not admit.)
_BANNED_COND_WORDS = frozenset({"in", "is"})
_COND_KEYWORDS = frozenset({"and", "or", "not"})

# Matches one condition token: a double-quoted string (no escapes), `==`, or a bare word.
_COND_TOKEN = re.compile(r'"[^"\\]*"|==|[A-Za-z_][A-Za-z0-9_]*')

_OPENERS = ("{{", "{%", "{#")
_CLOSERS = {"{{": "}}", "{%": "%}", "{#": "#}"}
_STRAY_CLOSERS = ("}}", "%}", "#}")


@dataclass(frozen=True, slots=True)
class TemplateScan:
    """One whole-source scan outcome over the frozen mini-jinja subset."""

    violations: tuple[str, ...]  # safe "line N: <block>" strings for out-of-subset blocks
    has_include: bool  # True when any (valid) include tag is present
    identifiers: frozenset[str]  # bare identifiers referenced by substitutions/conditions,
    # excluding the keywords and/or/not


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
        elif token in _COND_KEYWORDS:
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


def _include_path_is_valid(path: str) -> bool:
    """Mirror miniJinja's resolveTemplatePath containment: non-empty / non-absolute / no `..`."""
    if not path:
        return False
    if path.startswith("/") or re.match(r"^[A-Za-z]:", path):  # absolute (posix or windows drive)
        return False
    return ".." not in re.split(r"[\\/]", path)


def _cond_identifiers(cond: str) -> frozenset[str]:
    """Bare identifier tokens in a valid condition, minus the admitted keywords."""
    words = _IDENT.findall(re.sub(r'"[^"\\]*"', " ", cond))
    return frozenset(word for word in words if word not in _COND_KEYWORDS)


@dataclass(frozen=True, slots=True)
class _BlockResult:
    valid: bool
    is_include: bool = False
    identifiers: frozenset[str] = frozenset()


def _check_block(opener: str, inner: str) -> _BlockResult:
    """Classify one extracted single-line block (without its delimiters)."""
    if opener == "{#":
        return _BlockResult(valid=False)  # comments are never in the subset
    stripped = inner.strip()
    if opener == "{{":
        # `{{ X }}`: X must be a single bare identifier (catches `{{- x -}}`, dots, filters, …).
        if _IDENT.fullmatch(stripped) is None:
            return _BlockResult(valid=False)
        return _BlockResult(valid=True, identifiers=frozenset({stripped}))
    # `{% X %}` (catches `{%- … -%}` since the leading `-` breaks every branch below).
    if stripped in ("else", "endif"):
        return _BlockResult(valid=True)
    include = _INCLUDE.fullmatch(stripped)
    if include is not None:
        if not _include_path_is_valid(include.group(1)):
            return _BlockResult(valid=False)
        return _BlockResult(valid=True, is_include=True)
    for keyword in ("if", "elif"):
        prefix = keyword + " "
        if stripped.startswith(prefix):
            cond = stripped[len(prefix) :].strip()
            if not cond or not _COND.fullmatch(cond):
                return _BlockResult(valid=False)
            # Reject `in`/`is` operators (lexically identifiers) outside string literals.
            words = _IDENT.findall(re.sub(r'"[^"\\]*"', " ", cond))
            if any(word in _BANNED_COND_WORDS for word in words):
                return _BlockResult(valid=False)
            # Reject malformed condition shapes the runtime renderer throws on.
            if not _cond_shape_valid(cond):
                return _BlockResult(valid=False)
            return _BlockResult(valid=True, identifiers=_cond_identifiers(cond))
    return _BlockResult(valid=False)


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _line_snippet(text: str, start: int) -> str:
    """The raw source from ``start`` to its line end — a safe single-line violation display."""
    newline = text.find("\n", start)
    end = len(text) if newline == -1 else newline
    return text[start:end].rstrip("\r")


def scan_template(text: str) -> TemplateScan:
    """Scan one whole template source against the frozen mini-jinja subset."""
    violations: list[str] = []
    identifiers: set[str] = set()
    has_include = False
    index = 0
    length = len(text)
    while index < length:
        window = text[index : index + 2]
        if window in _OPENERS:
            closer = _CLOSERS[window]
            end = text.find(closer, index + 2)
            if end == -1:
                # Unterminated opener: everything after is unparseable — one violation, stop.
                violations.append(f"line {_line_of(text, index)}: {_line_snippet(text, index)}")
                break
            inner = text[index + 2 : end]
            if "\n" in inner or "\r" in inner:
                # Multiline block: a violation regardless of what it strips down to.
                violations.append(f"line {_line_of(text, index)}: {_line_snippet(text, index)}")
            else:
                result = _check_block(window, inner)
                if result.valid:
                    has_include = has_include or result.is_include
                    identifiers.update(result.identifiers)
                else:
                    violations.append(
                        f"line {_line_of(text, index)}: {text[index : end + len(closer)]}"
                    )
            index = end + len(closer)
            continue
        if window in _STRAY_CLOSERS:
            violations.append(f"line {_line_of(text, index)}: {window}")
            index += 2
            continue
        index += 1
    return TemplateScan(
        violations=tuple(violations),
        has_include=has_include,
        identifiers=frozenset(identifiers),
    )
