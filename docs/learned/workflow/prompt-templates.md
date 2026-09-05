---
title: The prompt-template seam — cross-plane parity, Python source-text rendering, static fixture unions, prompt moves
read_when: You are working on prompt loading/rendering, source-text includes, static Jinja fixture completeness, cross-plane parity, grammar guards, or moving inline prompts to `prompts/`.
cluster: cross-plane-contracts
---

# Cross-plane prompt templates

perk's prompts live as canonical templates under top-level `prompts/`, rendered on **both planes** —
jinja2 in Python, the vendored zero-dependency `miniJinja` in the TS extension
(`extension/substrate/miniJinja.ts`) — from the **same** template bytes. This doc holds the seam's
load-bearing decisions: bundling tier, the frozen grammar and its author-time guards, the exact
byte-parity render config, the two-tier parity tests, and the prompt-move decision rules.

## Distillation

- Templates render on BOTH planes from the same bytes: jinja2 in Python, the vendored
  zero-dependency `miniJinja` in TS — "The vendored engine — miniJinja replaces nunjucks"; a
  new top-level resource dir picks its bundling tier per "Which bundling tier a new top-level
  resource dir joins".
- The **frozen mini-jinja subset** is the renderer's INPUT CONTRACT (extend it deliberately,
  never ad hoc) — "The frozen mini-jinja subset"; the byte-parity render settings live in
  "The byte-parity render config (data shape)".
- Author-time grammar guards must be tightened to MATCH the stricter runtime; the Python guard's
  scanner is the shared `perk_dev.prompt_grammar.scan_template` (also the prose-review Assembly
  preview gate), the TS guard stays test-local — "The author-time guard MUST be tightened to
  match the stricter runtime".
- CRLF: Python's text-mode read normalizes newlines, Node's does not — normalize at every TS
  read boundary whose bytes must match a Python read — "The CRLF byte-parity hazard".
- Parity testing is two-tier (contract-snapshot goldens + live cross-engine equality), replacing
  prose-copy goldens — "Two-tier render-parity replaces the prose-copy golden bridge"; flow
  clauses need per-prompt semantic pins — "Seed prompts need their own semantic-contract test".
- Moving an inline prompt literal onto a template without output change (single-plane prompts
  belong in `prompts/` too) — "The prompt-move pattern (the cornerstone)".
- Python's canonical source-text entry point shares one loader-bound Environment with named
  rendering; its contract is output bytes and exception classes, not diagnostics — "The Python
  two-entry-point render seam".
- Fixture completeness is the static union of variables across every conditional arm and include,
  not one StrictUndefined render path — "Static-union fixture validation".

## Which bundling tier a new top-level resource dir joins

Two precedents; the deciding question is always: **does the TS extension read this directly at
runtime, or does Python materialize it for consumers?**

- **The `shared/` tier** — bundled into **all three** artifacts (wheel force-include, sdist
  only-include, **and** npm `files`) — for resources the **TS extension reads at runtime** from the
  npm tarball.
- **The `agents/` tier** — **Python-plane-only**, **absent** from npm `files` — for resources
  **materialized by `perk init` from the wheel** and never read by the extension at runtime.

`prompts/` joins the **`shared/` tier** because the extension renders templates at runtime.
Resolution is proven per plane by `tests/test_resources.py` (`perk._resources.prompts_dir`) +
`extension/substrate/resources.test.ts` (`promptsDir`), and artifact bundling by
`tests/test_packaging.py` (`test_wheel_bundles_prompts`,
`test_npm_pack_lists_shipped_and_excludes_dev`). Templates load by **explicit name** via the
resolver, never by scanning a dir, so the resolution probe is a committed `prompts/README.md`
rather than a throwaway placeholder file.

## The vendored engine — miniJinja replaces nunjucks (the 2nd vendored-engine precedent)

The TS plane renders via `extension/substrate/miniJinja.ts`: an fs-coupled module that OWNS the
filesystem (`readFileSync` + `promptsDir`), with a header comment explaining *why it exists* (the
zero-runtime-dep / bare-git-clone-loadable invariant) and the explicitly-unsupported scope (throw
loudly on out-of-subset input). Signature `render(name, vars, rootDir = promptsDir())`; the
optional `rootDir` default makes it unit-testable (point it at a `mkdtempSync` dir of throwaway
templates — the only way to exercise the out-of-subset failures production input is guarded
against). The frozen render config is **baked in — no config object** (the subset is frozen, so a
config object would be dead flexibility).

The dependency invariant: package.json runtime `dependencies` **absent or empty** — the committed
package drops the key entirely — guarded by
`tests/test_packaging.py::test_no_runtime_dependencies` plus the bare-import scan below. The
committed jinja2 goldens are the engine-independent byte-parity proof, so the removed engine is
**NOT** kept as a dev-dep oracle (contrast `miniYaml` keeping `yaml`, where there is no committed
golden for YAML parsing).

## The byte-parity render config (data shape)

The two engines are configured to render **byte-identically**. The exact config is recorded here as a
**data shape** (a sanctioned exception to the One Code Rule — getting one flag wrong silently diverges
the planes):

- **jinja2:** `autoescape=False`, `trim_blocks=True`, `lstrip_blocks=False`,
  `keep_trailing_newline=True`, `undefined=StrictUndefined`.
- **miniJinja:** the corresponding behavior is **baked in** (there is no options object): no
  escaping, `trimBlocks` on, `lstripBlocks` off, trailing newline kept, referenced absent or
  non-string values throw.

Why each flag matters:

- `trim_blocks`/`trimBlocks` is **global on**: it strips only the single newline after a block
  tag, preserving indentation. The **env flag** does the trimming — not a `{%- -%}` marker —
  because `{%- -%}` cannot express "trim newline only" (it also eats the next line's leading
  indent; see the conditional-templates section). `lstrip_blocks` stays **off** (tags sit at
  column 0).
- `keep_trailing_newline=True` is **load-bearing**: jinja2 otherwise strips one trailing `\n`
  while miniJinja keeps it, diverging the planes on every template that ends in a newline.
- `{% include "<root-relative path>" %}` resolves **root-relative under `prompts/`** on both
  engines. Two include-authoring gotchas: an included fragment's trailing newline plus the newline
  after the `%}` tag yields a **blank line**; and an `{% include %}` inside an indented fenced
  block sits at **column 0** — neither engine reindents included multi-line content, so an
  indented include tag indents only the *first* rendered line (markdown fences tolerate the flush
  tag).

**jinja2 is the reference engine** — the committed golden bytes ARE jinja2 output: generate once with
jinja2, then assert miniJinja matches byte-for-byte.

## The frozen mini-jinja subset (the renderer's input contract)

The templates are restricted to a **frozen subset** — exactly four categories, documented in
`shared/contracts.md §8.31` + `prompts/README.md`:

1. **bare-identifier `{{ ident }}` substitution** (no filters/dots/parens/literals/operators);
2. **`{% include "<path>" %}`** (double-quoted, root-relative);
3. **`{% if/elif/else/endif %}`** over bare identifiers / double-quoted strings / `==` /
   `and`/`or`/`not`;
4. **plain `{% %}` tags** — `{%- -%}` / `{{- -}}` whitespace-control markers are **OUT** (tag-line
   trimming rides the env `trim_blocks` flag, not a marker).

Everything else is outside the subset: `{# … #}` comments, loops, `set`/`macro`/`block`/
`extends`/`raw`, filters, dotted access, parentheses, numeric literals, `!=`/`<`/`>`, `in`, `is`,
and escaped string literals.

## The author-time guard MUST be tightened to match the stricter runtime (the cross-cutting insight)

A grammar guard MORE PERMISSIVE than the runtime lets a template pass author-time and fail later at
render/golden time. Ownership: the Python guard's scanner is
`perk_dev.prompt_grammar.scan_template` (`packages/perk-dev/src/perk_dev/prompt_grammar.py`) —
**shared** between `tests/test_prompt_grammar.py` and the prose-review Assembly preview gate
(`AssemblyRenderer._render_prompt_layer` in `packages/perk-dev/src/perk_dev/prose_review/assembly.py`);
the TS guard remains local to `extension/substrate/promptGrammar.test.ts`. Both take an allowlist
posture aligned with the miniJinja runtime:

- **reject escaped string literals** (`[^"\\]*`, not `[^"]*`);
- **reject out-of-containment include paths** (empty / absolute / `..`-segment);
- **reject malformed condition SHAPES** via a recursive-descent shape validator mirroring the
  runtime's precedence (`or < and < not < == < atom`) — catches `a b` adjacent atoms, `a ==` /
  `== a` missing operand, bare `not`.

Guard agreement is construct-membership agreement, **not identical lexical acceptance**: the Python
whole-source scanner deliberately rejects multiline, unterminated, stray, nested, and partially
matched delimiter forms, while the TS tokenizer accepts multiline tags and treats stray closers as
text (`shared/contracts.md §8.31` records the asymmetry). Neither guard checks if/endif nesting
balance — rendering every real template supplies the structural check.

**The regex char-set gate and the shape validator are complementary**: the regex gates the
character SET (rejects parens / `!=` / numbers / dots), the validator gates the token SHAPE (rejects
valid-token-but-malformed sequences the regex's `(token)+` repetition accepts). Neither alone
suffices. The guard is a **fourth lockstep surface**: widening the subset later amends `§8.31` +
its authoring documentation (`prompts/README.md`) + the runtime renderer (both planes) + **both**
grammar guards.

Guard gotchas: `{# … #}` comments contain neither `{{` nor `{%`, so an extractor silently MISSES
them — add a third regex alternative purely to **REJECT** comments (a synthetic `{# comment #}`
negative test catches this). `in`/`is` are lexically identifiers, so the condition regex admits
them — after stripping string literals, re-scan identifiers and reject a banned-word set (`{in, is}`;
the admitted keywords are exactly `and`/`or`/`not`, every other bare word is a legitimate variable
name). Both guards self-check against a **vacuous scan** (assert non-empty + known anchors) and skip
`README.md` (it deliberately carries out-of-subset example constructs as prose).

The scanner belongs to dev authoring/preview tooling, never the production render path — and
sharing it does not give Assembly preview every production feature: `_render_prompt_layer` rejects
includes before calling `render_text`, while production named/source-text rendering supports
root-relative includes.

## The CRLF byte-parity hazard (any cross-plane TS module byte-matching a Python file read)

Python text-mode reads (`open`, `Path.read_text()`) do universal-newline translation
(`\r\n`/`\r`→`\n`) **before** jinja2 sees the source; Node `readFileSync(f, "utf8")` does **NOT**.
For byte-for-byte parity the TS side must normalize `src.replace(/\r\n?/g, "\n")` **at the read
boundary**, not in each downstream consumer. A latent platform-specific divergence invisible on an
LF dev machine — two instances so far:

- **The renderer**: `miniJinja.ts` normalizes at the top of `render`. Most visible via
  `trim_blocks` (it consumes the single `\n` after `%}` — on a CRLF checkout the next char is
  `\r`, so the newline isn't trimmed and the planes diverge).
- **Binding delivery**: TS `stripFrontmatter` checked `startsWith("---\n")` — false on CRLF — so
  frontmatter would have leaked into warm/worker prompts on a CRLF checkout. The cross-plane
  byte-parity test (`tests/test_binding_render_parity.py`) exposed it; the fix normalizes in
  `readSkillBody` (`extension/substrate/bindingDelivery.ts`), mirroring the renderer.

Test pattern: write one fixture with **explicit CRLF bytes** (`write_bytes`, as the parity test's
`_scaffold` does) to pin the arm. The rule: **when writing any TS file-read whose output must
byte-match a Python read, normalize newlines at the read boundary.**

## String-only contract: lazy (TS) vs eager (Python), both planes

The TS renderer throws **lazily** on a *referenced* absent or non-string value (at lookup, jinja2
`StrictUndefined` parity); Python validates the whole var map **eagerly** (`TypeError` before
delegating to jinja2), and a referenced missing variable still fails loudly on both planes.
"Reference engine unchanged" does NOT mean "skip enforcing the shared contract on that plane" — a
documented cross-plane contract is mechanically enforced on **both** planes (the *when* may differ —
lazy vs eager — as long as both forbid the `str(value)`/`String(value)` coercion divergence).

## The Python two-entry-point render seam

Python has two entry points for one renderer. `render_text` is the canonical low-level operation
for caller-supplied template source; `render` resolves a named source through the module loader and
delegates to it. Both use the single module-level loader bound into the single Jinja Environment.
Do not create a second Environment or expose a loader/config parameter: that shared binding is what
lets includes inside caller-supplied text resolve root-relative to `prompts/` with exactly the same
policy as named templates.

Source text renders through Jinja's `from_string` path; the accepted cost is loss of bytecode cache
and source name/filename provenance. Accordingly, the stable contract is rendered bytes plus
exception classes — diagnostic wording and filenames are not API. Validate that every variable
value is a string *before* loader lookup so bad-data errors have deterministic precedence over a
missing include or source; pin that ordering with regressions rather than relying on Jinja's
incidental lookup sequence.

`render_text` accepts **trusted repository source** — it is a render mechanism, neither a sandbox
nor a runtime grammar validator. Grammar restrictions remain author-time policy in the prompt
guards; the shared `scan_template` scanner stays dev tooling, never a production security boundary.
The TypeScript twin deliberately exposes only named rendering because no TS consumer needs source
text; cross-plane surface symmetry is not a goal when ownership is single-plane.

Tier-A golden fixtures exercise both Python entry points against the same committed bytes, locking
named-source and source-text behavior without a second set of expected outputs.

## Static-union fixture validation

Rendering with `StrictUndefined` visits one conditional arm and cannot prove a fixture supplies the
variables needed by the other arms. Fixture completeness is computed by static Jinja AST inspection:
collect the union of referenced variables across every branch and every statically named include.
Use one per-template metadata cache for repeated parsing, but start a fresh visited set for each
top-level template so cycle protection does not leak across independent analyses.

The inspection Environment stays separate from production rendering configuration. It exists to
establish requirements, not to reproduce output. Missing fixture data is an aggregate finding so an
author sees every gap at once; inability to parse a template or establish its include graph is a
hard contextual error because no trustworthy requirement set exists.

Scope the check to scenarios that can actually preview a template: a template is previewable when a
session shape references it. Extra variables in a scenario are allowed because one scenario may
serve multiple consumers. Only Markdown under `prompts/` is parsed as Jinja; neighboring manifests
and support files are not templates. `perk_dev.prose_map.catalog` owns the inspection and scenario
mapping.

## Two-tier render-parity replaces the prose-copy golden bridge

The old prose-copy golden's only load-bearing role was the cross-process parity bridge: jinja2
(Python) and miniJinja (TS) can't call each other in one process, so committed golden bytes let each
engine compare to the same frozen output. Because those goldens were copies of **real prompt
prose**, every prose edit forced a paired golden hand-edit while never independently proving the
prose "correct" (rendering is mechanical var-substitution; the `.md` source is already reviewed).
That recognition splits parity into two tiers:

- **Tier A — contract snapshots (golden, sui generis).** Goldens only for **purpose-built** fixture
  templates (`prompts/_fixtures/cases.yaml` + `_fixtures/golden/`), each isolating ONE feature of
  the frozen render contract (var subst, include, if/else, elif chain, `==`/`and`/`or`/`not`,
  `trim_blocks` block-tag-on-own-line vs inline, trailing-newline, no-trailing-newline fragment).
  Stable — they change only when the **contract** changes, never when prose changes; generated by
  the reference engine (jinja2) in a throwaway scratch script, byte-reproduced by the TS side.
  Each conditional fixture renders **multiple var arms** so both branches are pinned.
- **Tier B — live cross-engine equality (NO goldens).** `prompts/_fixtures/live.yaml` lists every
  **real** template with representative vars. A Python-owned test
  (`tests/test_prompt_parity.py::test_live_cross_engine_parity`) renders each natively with
  jinja2, shells out **once** to a small node renderer (`extension/testing/renderLive.ts`) that
  renders the same manifest with miniJinja, and asserts byte-equality **positionally** (the node
  side prints results in manifest order). Editing real prose touches **no** fixture.

The coverage predicate: `test_live_manifest_covers_every_real_template` asserts the real-template
set — every `*.md` under `prompts/` except `README.md` and `_fixtures/` — is a **subset** of the
manifest (not equality: multi-arm entries repeat a template). Partials and single-plane templates
are real templates: an `{% include %}` partial needs its **own** entry (a parent's include does not
cover it; no production template carries `{% include %}` today, but the Tier-A fixtures still pin
the feature), and single-plane consumption does not exempt a template. Use `vars: {}` for var-free
templates. Editing prose alone needs no fixture change; adding a template or changing required
vars/branches does. Curate conditional-arm coverage in the manifest (provider arms, with-url/no-url,
empty/populated optional clauses) — representative arms are the only branch evidence Tier B has.

Mechanics:

- **Node renderer placement = tarball exclusion + still typechecked.** `extension/testing/renderLive.ts`
  (NOT a `.test.ts`) is excluded from the npm tarball by the existing `!extension/testing/` rule yet
  is still covered by `tsc --noEmit` + `biome check extension`. It is invoked only by the Python
  test (never by the `node --test` glob — wrong suffix); Node 26 runs it bare via native
  type-stripping, printing `JSON.stringify(results)`.
- The Python→node subprocess **skips when `node` is absent** — the tier is then *unexercised*, not
  cross-engine-passed; use the prepared worktree toolchain so both planes actually run. A
  `subprocess.run` inside a *test* file needs **no** sanctioned-subprocess-guard entry
  (`tests/test_tooling.py::_SANCTIONED_SUBPROCESS_WRAPPERS` scans `perk/`, not `tests/`).
- Both `cases.yaml` and `live.yaml` stay in the **miniYaml subset** (block maps/seqs, double-quoted
  strings, **string-only vars**, the backtick-quoting rule in the move checklist below, no `|`/`>`
  block scalars — the empty flow map `vars: {}` parses on both sides).

## Seed prompts need their own semantic-contract test (#1990)

Every new seed prompt needs its own semantic-contract test — the parity/grammar/budget suites
prove render *mechanics*, never flow clauses. The pattern: whitespace-normalized pins over the
captured real-launch prompt covering the single-call/no-retry rule and every incomplete/stop
arm.

## The bare-import source-scan guard (the bare-clone invariant)

The vendored modules must stay zero-runtime-dependency so a bare git clone loads them. A source-scan
guard (`extension/bareImportGuard.test.ts`) enforces it: a specifier is allowed iff it is a
`node:` builtin, a relative path, or in the guard's host/peer allowlist (`isAllowed` — refer to it
rather than copying its package roster). Mechanics:

- **Strip block+line comments BEFORE scanning** (`stripComments`) — the vendored modules' own
  headers contain explanatory `import … from "nunjucks"` / `"yaml"` text, so a naive scan
  false-positives on the very module that removed the dep (mirrors `surfacesGuard`).
- **Scan static, side-effect, re-export, and literal dynamic forms** (`specifiersOf`): `from`
  clauses, bare `import "pkg"`, and `import("pkg")` / `require("pkg")` string-literal specifiers
  (a computed specifier has no literal to scan, acceptably).
- **Exclude both `*.test.ts` AND `testing/`** from the scanned production set (`productionFiles`) —
  only test-reachable, never in the runtime import graph rooted at `index.ts`; the tarball ships
  neither.
- Pair the TS scan with `tests/test_packaging.py::test_no_runtime_dependencies` (package.json
  runtime `dependencies` absent or empty) — two guards, two planes, one invariant.

## The prompt-move pattern (the cornerstone)

How to relocate an inline prompt string literal onto a canonical template **without changing output**:

1. **All externalized prompt prose belongs in `prompts/`** — single-plane consumers too. A
   warm-door-only guidance prompt or a cold-door-only seed prompt is authored in the same frozen
   subset and listed in `live.yaml`, riding cross-engine parity for free (the subset is shared, so
   a single-plane move costs nothing extra).
2. **Flat file vs subdirectory-of-arm-files — the deciding factor is in-code BODY branching, not
   just var differences.** If the prompt **body** branches in code → a subdirectory with one
   complete-body template per branch (branching is template *selection* in code). If only an
   injected **var** differs → a single flat file. Keep a **one-rendering-arm subdirectory** when
   the other branches return an empty string — `prompts/common/objective-read/linear.md`
   (github/other return `""` directly): no empty templates, no `{% if %}`, and the subdirectory
   path shape stays consistent across the common-prompt arms.
3. **Unify vs split is keyed on WHY the bodies differ, not on surface diffing.** UNIFY into one
   flat template when the differences are **superficial house-style** (header wording, a blank
   line, step-number indentation, a plane-only qualifier) — and **verify the qualifier's premise**
   first: drop it only if the bare wording holds on both planes. SPLIT into arm files
   (`prompts/stages/objective-plan/{seed,guidance}.md`) when the difference is **load-bearing
   semantics** — the **cold-injects / warm-instructs** asymmetry (the cold door launches a fresh
   session and injects data; the warm command instructs the model to fetch it and mark state
   itself). **Unifying CHANGES output** (a plane gains/loses bytes), so it is a deliberate,
   user-approved plan-time decision — never an implementation default.
4. **Semantic selection stays in code; only prose assembly moves.** Pass string values, and the
   **UNION** of arm vars to every arm (StrictUndefined/throwOnUndefined fire only on a *referenced*
   missing var, so unused vars are harmless); normalize optional absent values to `""` — do not
   reach for arbitrary `str()`/`String()` coercion. Names are `.md`-suffixed and root-relative
   under `prompts/`.
5. **De-risk transcription with captured bytes, not new goldens.** Before deleting each literal,
   capture the pre-change output of the literal helper (e.g. `_seed_prompt(...)` /
   `factoryGuidance(...)`) for representative arg sets, then assert the new `render(...)` equals
   the captured bytes for **every arm** in a throwaway scratch script — never newly committed
   real-prose goldens. Generate a long template from the capture by string replacement instead of
   hand-transcribing it, and **replace vars longest-first** to avoid substring collisions (a URL
   containing a bare issue id must be replaced before the id, or the shorter substitution corrupts
   the URL).
6. **Preserve exact trailing-newline choices for embedded fragments.** Mid-prompt fragments are
   authored **without** a trailing newline so `render()` returns the prior literal byte-for-byte;
   author with `printf` (never newline-appending `echo`) and verify actual bytes
   (`tail -c1 | xxd`). Only Tier-A fixture fragments have committed goldens.
7. **Keep thin per-plane selection/wiring tests and the semantic-contract pins.** Render parity
   replaces duplicate prose/substring lockstep, not behavior pins; selection tests assert *which
   arm* is chosen and never read goldens. Before deleting a substring constant, check for other
   local consumers — demote it in place if per-plane composition tests still use it.
8. **Warm guidance seeded via `pi.sendUserMessage`: prove injection with `spyInjections`**
   (`extension/testing/harness.ts`; see "Asserting `pi.sendUserMessage` injection offline: spy on
   the session instance" in `docs/learned/pi/extension-api.md`). Offline capture proves
   *attempted* injection, not persisted delivery. Independent caution: when moving a warm door's
   prose, preserve its plan-ref resolution and null-guard behavior.
9. **The `cases.yaml` backtick-quoting rule.** For a render var carrying literal backticks
   **plus** embedded quotes: do **NOT** escape the backtick — only `\"` / `\\` / `\n` / `\t` are
   escapable in this fixture format. miniYaml's `unescapeDoubleQuoted` leaves `` \` `` as a
   literal backslash-plus-backtick and PyYAML rejects it outright. Use a double-quoted scalar with
   **literal** backticks and only the inner `"` escaped.

## Conditional templates — whitespace control is the load-bearing gotcha

Most arm templates use `{{ var }}` only and keep branching in code. When branching instead moves
**into** a template as `{% if %}`, whitespace control decides whether the output is byte-stable
(the render-config section above records the exact flags):

- **`{%- -%}` cannot mean "trim newline only"** — `-%}` strips the following newline **and** the
  next line's leading indentation, corrupting indented content; there is no jinja/miniJinja marker
  for "trim newline only". The env flag `trim_blocks`/`trimBlocks` (global on) strips only the
  single newline after a block tag, preserving indentation; `lstrip_blocks` stays off. Two
  byte-stable conditional shapes: **block-level** tags on their own lines (`trim_blocks` swallows
  the tag line's newline, content indentation survives) and **inline** mid-line tags (no newline
  directly after `%}`, so a truly mid-line tag does not trim a following non-newline character).
- **An end-of-line inline `{% endif %}` consumes the structural newline** (`trim_blocks` removes
  the newline after ANY block tag), merging the line with the next. Author an absorbed extra blank
  line — `{% endif %}\n\n` — so one newline survives. Include fragments' trailing newlines and
  column-zero include placement need byte checks too (the render-config section's include
  gotchas).
- **Selection stays in code; only string-ASSEMBLY moves into the template.** Distinguish *which
  clause to render* (the arm selection — stays in code) from *how the clause is glued into the
  surrounding prose* (assembly — the intro wrapping / leading space / clause wording moves into
  the template).
- **Before flipping a shared render-env flag, inventory block-tag templates** (`grep '{%'` across
  `prompts/`) to bound the blast radius, and keep an affected fixture's golden byte-stable by
  editing the **template** (e.g. an explicit blank line) — never regenerate goldens to conceal an
  unintended output change. Preserve optional-variable arm coverage when vars change.
- **A new optional free-form `{% if %}` var needs no new mechanism** — thread it like the existing
  optional vars: widen the pure door helper signature, pass `?? ""` / `or ""`, and cover the new
  var in **both** existing `live.yaml` arms plus one new true-arm entry (string-only per the
  miniYaml subset) or the parity render throws. A runtime value substituted for `{{ var }}` is
  **not** re-parsed as template grammar, so operator text containing `{% %}` cannot inject.
  Doc-mirror scope for a command-argument change: `shared/contracts.md` + the user-docs command
  section + the **bound skill** source, in the same turn (the `perk-expert` mirror is
  config/provider/backend changes only).
- **The stale-claim ripple** (cross-ref `doc-reconciliation.md`): when a real grammar/config change
  supersedes a historical record, preserve the record's historical status and record the new
  contract where the change happened — never present obsolete settings as current.

## Recurring mechanics

- **`[[ci.checks]]` glob-skips the TS suites on a `prompts/`-only diff — but the TS plane reads
  `prompts/` at RUNTIME.** The JS check rows carry code-suffix globs, so a diff touching only
  templates or `prompts/_fixtures/live.yaml` skips `lint-js`/`typecheck-js`/`test-js` while
  `promptGrammar.test.ts` (frozen-grammar validation of every template) and `prompts.test.ts`
  (the Tier-A goldens) never run. Whenever a change adds or edits anything under `prompts/`, run
  `node --test extension/substrate/promptGrammar.test.ts extension/substrate/prompts.test.ts`
  explicitly (or `just test-js`), even with a zero-`.ts` diff. (Python's `test_prompt_parity`
  shells to node and does run under `test-py`.)
- Fresh-worktree TS toolchain and formatter cautions live in their topical docs:
  `toolchain/worktree-node-modules.md` (`npm ci` before TS checks) and `toolchain/biome.md`
  (`run_ci` green ≠ committed-format-green).
- The `edit`-fails-across-an-em-dash trap → a Python `str.replace` heredoc escape hatch for
  Unicode-safe exact edits.
- Keep `contracts.md §8.31` references intact through comment-hygiene sweeps.

## Cross-references

- `docs/learned/workflow/shared-contracts.md` — the cross-plane SSOT prompt-fragment discipline + the
  vendored `miniYaml` reader (why `cases.yaml` must stay in the subset)
- `docs/learned/workflow/distribution.md` — the npm extension-delivery lifecycle the vendored
  `miniJinja`'s zero-dep posture rides
- `docs/learned/pi/extension-api.md` — "Asserting `pi.sendUserMessage` injection offline: spy on
  the session instance" (the injection-proof pattern the move checklist points to)
- `docs/learned/toolchain/worktree-node-modules.md` — `npm ci` in a fresh worktree
- `docs/learned/toolchain/biome.md` — `run_ci` green ≠ committed-format-green
- `extension/substrate/miniJinja.ts` — the vendored TS renderer; `extension/testing/renderLive.ts` —
  the Tier-B node renderer; `packages/perk-dev/src/perk_dev/prompt_grammar.py` — the shared Python
  grammar scanner
- `prompts/` — the canonical templates; `prompts/_fixtures/cases.yaml` (Tier-A contract snapshots) +
  `prompts/_fixtures/live.yaml` (Tier-B live cross-engine parity manifest)
