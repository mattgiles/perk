# prompts — perk's externalized prompt prose

This directory is the canonical home for **all** of perk's externalized prompt prose. A
template may be **cross-plane** (rendered in production by both planes) or **single-plane**
(rendered by only one plane — e.g. a warm-door-only or cold-door-only seed/guidance prompt);
either way it is authored within the frozen mini-jinja subset below and listed in
`_fixtures/live.yaml`, where it is rendered on **both** engines and asserted byte-equal
regardless of which plane consumes it in production (a free cross-engine portability guarantee,
costing nothing since the subset is shared).

The templates are authored once and **bundled into every build artifact**
(the Python wheel as package data `perk/_prompts/`; the npm package under `prompts/`),
exactly like `shared/`. Each plane locates this directory at runtime through its own
resolver — `prompts_dir()` (`perk/_resources.py`) and `promptsDir()`
(`extension/substrate/resources.ts`): installed bundle → editable repo-sibling fallback.

Templates are rendered by jinja2 (Python) and a vendored TS subset (the extension), and
are loaded by explicit name through the resolver — never by scanning the directory, so
this README is a durable doc, not a template.

## Layering — one statement of contract

A compact, **non-normative** summary of the layering rule for prompt authors — the canonical
rule is [`shared/contracts.md` §8.57](../shared/contracts.md). Per stage, each contract
statement has exactly one canonical carrier; every other surface points at it, never restates
it. The **launch statement** (classified by delivery call site — cold seed, warm guidance turn,
headless primer — never by template path) states the flow once per session shape; **injected
contexts** carry live state + pointers, never a restatement; **adapter blocks** carry only the
provider-surface delta; the **bound skill** is the read-on-demand detail tier. One named
exception: the `plan` stage launches idle, so its mode context
(`contexts/plan-authoring.md`) is its designated flow carrier.

## Frozen template grammar

The templates use a deliberately tiny, **frozen** subset of jinja syntax — the canonical
"mini-jinja" surface. jinja2 is the reference engine; the extension renders the same subset. A
**cross-plane conformance guard** (`tests/test_prompt_grammar.py` +
`extension/substrate/promptGrammar.test.ts`) fails CI if any template uses a construct outside the
subset.

## Render parity — two decoupled tiers

The two render seams (jinja2 on Python, the vendored mini-jinja on TS) are kept byte-identical by
two tiers that separate the frozen render **contract** from real prompt **prose**:

- **Tier A — contract snapshots.** `_fixtures/cases.yaml` lists purpose-built fixture templates
  under `_fixtures/templates/` (one per render feature) with committed goldens under
  `_fixtures/golden/` (jinja2's output). Both planes assert `render == golden`
  (`tests/test_prompts.py` + `extension/substrate/prompts.test.ts`). These goldens change only when
  the render contract changes — never when a real prompt's prose changes.
- **Tier B — live cross-engine equality.** `_fixtures/live.yaml` lists every real template with
  representative vars and **no** golden. `tests/test_prompt_parity.py` renders each real template
  with jinja2, shells out once to `extension/testing/renderLive.ts` (mini-jinja), and asserts the
  two outputs are byte-equal — so editing a real prompt's prose touches no fixture. A coverage
  guard asserts every real template is listed in `live.yaml`.

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
