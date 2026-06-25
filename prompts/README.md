# prompts — canonical cross-plane prompt templates

perk's prompt templates, authored once and **bundled into every build artifact**
(the Python wheel as package data `perk/_prompts/`; the npm package under `prompts/`),
exactly like `shared/`. Each plane locates this directory at runtime through its own
resolver — `prompts_dir()` (`perk/_resources.py`) and `promptsDir()`
(`extension/substrate/resources.ts`): installed bundle → editable repo-sibling fallback.

Templates are rendered by jinja2 (Python) and a vendored TS subset (the extension), and
are loaded by explicit name through the resolver — never by scanning the directory, so
this README is a durable doc, not a template.

## Frozen template grammar

The templates use a deliberately tiny, **frozen** subset of jinja syntax — the canonical
"mini-jinja" surface. jinja2 is the reference engine (the committed golden files under
`_fixtures/golden/` are jinja2's output); the extension renders the same subset. A **cross-plane
conformance guard** (`tests/test_prompt_grammar.py` + `extension/substrate/promptGrammar.test.ts`)
fails CI if any template uses a construct outside the subset.

The subset is exactly four categories:

1. **Variable substitution** — `{{ name }}`, where the contents are a single bare identifier
   (`[A-Za-z_][A-Za-z0-9_]*`). Nothing else: no filters, no dotted access, no parentheses, no
   literals, no operators.
2. **Include** — `{% include "path/to/file.md" %}`, a double-quoted root-relative path only.
3. **Conditionals** — `{% if cond %}` / `{% elif cond %}` / `{% else %}` / `{% endif %}`, where
   `cond` uses only bare identifiers (truthiness), double-quoted string literals, `==`, and the
   keywords `and` / `or` / `not`. For example: `{% if provider == "github" or provider == "linear" %}`,
   `{% if not pr_id %}`.
4. **Plain tags** — `{% %}` only. The whitespace-control markers `{%- … -%}` / `{{- … -}}` are
   **not allowed**; tag-line stripping is handled by the render env's `trim_blocks` setting.

**Not allowed** (the guard fails on these): `{% for x in y %}` / `{% endfor %}`, `{% set %}`,
`{% macro %}` / `{% block %}` / `{% extends %}` / `{% raw %}`, `{# comments #}`, filters
(`{{ x | upper }}`), attribute access (`{{ user.name }}`), `!=` / `<` / `>`, `in`, `is`,
parentheses, and numeric literals.

This README is **excluded** from the guard's scan — it is documentation, never rendered, and the
out-of-subset examples above are shown deliberately as prose. The canonical spec lives in
[`shared/contracts.md` §8.31](../shared/contracts.md). Widening the subset is a deliberate
decision that amends §8.31 **and** both guards.
