---
title: The cross-plane prompt-template seam — bundling tier, the frozen mini-jinja subset + author-time guard, the byte-parity render config (jinja2 + vendored miniJinja), the two-tier render-parity tests, and the prompt-move pattern
read_when: You are bundling a new top-level resource dir, working the cross-plane jinja2/miniJinja render seam, the frozen mini-jinja subset + its author-time grammar guard, the two-tier render-parity tests (contract-snapshot goldens vs live cross-engine equality), the CRLF byte-parity hazard / string-only contract, the bare-import source-scan guard, or moving an inline prompt literal onto a canonical `prompts/` template (the unify-vs-split decision rule keyed on WHY the bodies differ, conditional templates and the `trim_blocks` whitespace gotcha, raw-var string coercion, single-file-vs-subdir, the single-arm subdirectory, demote-in-place substring constants, no-trailing-newline fragments, the byte-stability `/tmp`-capture de-risker).
---

# Cross-plane prompt templates

perk's prompts live as canonical templates under top-level `prompts/`, rendered on **both planes** —
jinja2 in Python, the **vendored zero-dependency `miniJinja`** in the TS extension
(`extension/substrate/miniJinja.ts`) — from the **same** template bytes. This doc captures the
seam's load-bearing decisions: which bundling tier a new resource dir joins, the **frozen mini-jinja
subset** that is the renderer's input contract (and the author-time grammar guard that must match
the runtime), the exact render config that makes both engines byte-identical, the **two-tier
render-parity tests** (contract-snapshot goldens + live cross-engine equality), and the
**prompt-move pattern** (the cornerstone — how to relocate an inline prompt literal onto a template
without changing output).

## Which bundling tier a new top-level resource dir joins

There are two precedents, and the deciding question is always: **does the TS extension read this
directly at runtime, or does Python materialize it for consumers?**

- **The `shared/` tier** — bundled into **all three** artifacts (wheel force-include, sdist
  only-include, **and** npm `files`) — for resources the **TS extension reads at runtime** from the
  npm tarball.
- **The `agents/` tier** — **Python-plane-only**, **absent** from npm `files` — for resources
  **materialized by `perk init` from the wheel** and never read by the extension at runtime.

`prompts/` joins the **`shared/` tier** because the extension **renders templates at runtime**. The
cross-plane resolver is proven by a **four-test pattern**: Python editable + Python wheel + npm tarball
+ TS dev-tree all resolve the templates. And the **durable-README-probe-over-throwaway-placeholder**
rule: templates load by **explicit name** via the resolver, never by scanning a dir, so the resolver
test probes a committed `prompts/README.md` rather than a throwaway placeholder file.

## The vendored engine — miniJinja replaces nunjucks (the 2nd vendored-engine precedent)

The TS plane renders via `extension/substrate/miniJinja.ts`, the **2nd vendored-engine precedent
after `miniYaml`**: an **fs-coupled module that OWNS the filesystem** (`readFileSync` + `promptsDir`),
with a header comment explaining *why it exists* (the zero-runtime-dep / bare-git-clone-loadable
invariant) and the explicitly-unsupported scope (throw loudly on out-of-subset). Signature
`render(name, vars, rootDir = promptsDir())`; the optional `rootDir` default makes it unit-testable
(point it at a `mkdtempSync` dir of throwaway templates — the only way to test a renderer whose
production input is guarded against the very out-of-subset cases you must test). The frozen render
config is **baked in — no config object** (the subset is frozen, so a config object would be dead
flexibility).

**Removing the runtime dep means dropping the `dependencies` KEY ENTIRELY** (not `{}`) — the
packaging guard accepts key-absent OR empty. The committed jinja2 goldens are the
engine-independent byte-parity proof, so the removed engine is **NOT** kept as a dev-dep oracle
(contrast `miniYaml` keeping `yaml`, where there's no committed golden for YAML parsing).

## The byte-parity render config (data shape)

The two engines are configured to render **byte-identically**. The exact config is recorded here as a
**data shape** (a sanctioned exception to the One Code Rule — getting one flag wrong silently diverges
the planes):

- **jinja2:** `autoescape=False`, `trim_blocks=True`, `lstrip_blocks=False`,
  `keep_trailing_newline=True`, `undefined=StrictUndefined`.
- **miniJinja:** `trimBlocks` on, `lstripBlocks` off, keep-trailing-newline on,
  `throwOnUndefined` (the config is baked in, not a passed object).

> **`trim_blocks` / `trimBlocks` is now GLOBAL `True`** (it used to be the default-`False`,
> conditional-templates-opt-in shape — superseded). The reason the **env flag** does the trimming,
> not a `{%- -%}` marker, is the whitespace-control gotcha: `{%- -%}` can't trim-newline-only (it
> also eats the next line's leading indent). `trim_blocks` strips only the single newline after a
> block tag, preserving indentation. `lstrip_blocks` stays **off** (tags sit at column 0).

`keep_trailing_newline=True` is **load-bearing**: jinja2 otherwise strips one trailing `\n` while
miniJinja keeps it, so omitting it diverges the planes on every template that ends in a newline.
`{% include "<root-relative path>" %}` resolves **root-relative under `prompts/`** on both engines;
watch the include-trailing-newline-plus-post-tag-newline **blank-line gotcha** (an included fragment's
trailing newline plus the newline after the `%}` tag yields a blank line).

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

## The author-time guard MUST be tightened to match the stricter runtime (the cross-cutting insight)

A grammar guard MORE PERMISSIVE than the runtime lets a template pass author-time and fail later at
render/golden time. The author-time guards (`extension/substrate/promptGrammar.test.ts` +
`tests/test_prompt_grammar.py` — inline test-only validators, allowlist posture) were tightened
into alignment with the miniJinja runtime:

- **reject escaped string literals** (`[^"\\]*`, not `[^"]*`);
- **reject out-of-containment include paths** (empty / absolute / `..`-segment);
- **reject malformed condition SHAPES** via a recursive-descent shape validator mirroring the
  runtime's precedence (`or < and < not < == < atom`) — catches `a b` adjacent atoms, `a ==` /
  `== a` missing operand, bare `not`.

**The regex char-set gate and the shape validator are complementary**: the regex gates the
character SET (rejects parens / `!=` / numbers / dots), the validator gates the token SHAPE (rejects
valid-token-but-malformed sequences the regex's `(token)+` repetition accepts). Neither alone
suffices. The guard is now a **fourth lockstep surface**: widening the subset later amends
`§8.31` + the runtime renderer (both planes) + **both** grammar guards.

Guard gotchas: `{# … #}` comments contain neither `{{` nor `{%`, so an extractor silently MISSES
them — add a third regex alternative purely to **REJECT** comments (a synthetic `{# comment #}`
negative test catches this). `in`/`is` are lexically identifiers, so the condition regex admits
them — after stripping string literals, re-scan identifiers and reject a banned-word set (`{in, is}`;
the admitted keywords are exactly `and`/`or`/`not`, every other bare word is a legitimate variable
name). Both guards self-check against a **vacuous scan** (assert non-empty + known anchors) and skip
`README.md` (it deliberately carries out-of-subset example constructs as prose).

## The CRLF byte-parity hazard (any cross-plane TS module byte-matching a Python file read)

Python text-mode `open` does universal-newline translation (`\r\n`/`\r`→`\n`) **before** jinja2 sees
the source; Node `readFileSync(f, "utf8")` does **NOT**. For byte-for-byte parity the TS renderer
must `src.replace(/\r\n?/g, "\n")` at the top of `render`. Most visible via `trim_blocks` (it
consumes the single `\n` after `%}` — on a CRLF checkout the next char is `\r`, so the newline isn't
trimmed and the planes diverge). **A latent platform-specific divergence invisible on an LF dev
machine** — worth a defensive normalize in any vendored file-reading renderer/parser that must match
a Python twin.

## String-only contract: lazy (TS) vs eager (Python), both planes

The TS renderer throws **lazily** on a *referenced* non-string (at lookup, jinja2 `StrictUndefined`
parity); Python validates the whole var map **eagerly** (`TypeError` before delegating to jinja2).
"Reference engine unchanged" does NOT mean "skip enforcing the shared contract on that plane" — a
documented cross-plane contract is mechanically enforced on **both** planes (the *when* may differ —
lazy vs eager — as long as both forbid the `str(value)`/`String(value)` coercion divergence).

## Two-tier render-parity replaces the prose-copy golden bridge

**The golden file's only load-bearing role was the cross-process parity bridge.** jinja2 (Python)
and miniJinja (TS) can't call each other in one process, so the committed `_fixtures/golden/*.txt`
existed *only* so each engine could compare to the same frozen bytes (transitively proving the two
engines agree). Because those goldens were copies of **real prompt prose**, every prose edit forced
a paired golden hand-edit — and the golden was never an independent oracle of "correct prose"
(rendering is mechanical var-substitution; the `.md` source is already reviewed). Recognizing that
unlocks the split:

- **Tier A — contract snapshots (golden, sui generis).** Goldens only for **purpose-built** fixture
  templates that each isolate ONE feature of the frozen render contract (var subst, include,
  if/else, elif chain, `==`/`and`/`or`/`not`, `trim_blocks` block-tag-on-own-line vs inline,
  trailing-newline, no-trailing-newline fragment). Stable — change only when the **contract**
  changes, never when prose changes; generated **by the reference engine** (jinja2) in a throwaway
  scratch script (so the Python snapshot passes by construction), and the TS side confirms
  byte-reproduction. Each conditional fixture renders **multiple var arms** so both branches are
  pinned.
- **Tier B — live cross-engine equality (NO goldens).** A `live.yaml` manifest lists every **real**
  template with representative vars (no `golden:` field). A **Python-owned** test renders each
  natively with jinja2, shells out **once** to a small node renderer
  (`extension/testing/renderLive.ts`) that renders the same manifest with miniJinja, and asserts
  byte-equality per template. Editing real prose touches **no** fixture. A coverage guard asserts
  every real template appears in the manifest (subset check, not equality — multi-arm entries
  repeat a template) so a new prompt can't silently skip Tier B.

Mechanics:

- **Node renderer placement = tarball exclusion + still typechecked.** `extension/testing/renderLive.ts`
  (NOT a `.test.ts`) is excluded from the npm tarball by the existing `!extension/testing/` rule yet
  is still covered by `tsc --noEmit` + `biome check extension`. It is invoked only by the Python
  test (never by `node --test "extension/**/*.test.ts"` — wrong suffix); Node 26 runs a bare
  `node extension/testing/renderLive.ts` via native type-stripping, printing `JSON.stringify(results)`
  in **manifest order** so the Python side zips positionally.
- The Python→node subprocess **skips** when `node` is absent (mirrors `test_packaging.py`'s
  `shutil.which` skip). A `subprocess.run` inside a *test* file needs **no** sanctioned-subprocess-guard
  entry — `tests/test_tooling.py::_SANCTIONED_SUBPROCESS_WRAPPERS` scans `perk/`, not `tests/`.
- Both `cases.yaml` and `live.yaml` stay in the **miniYaml subset** (block maps/seqs, double-quoted
  strings, **string-only vars**, the backtick-quoting rule, no `|`/`>` block scalars — empty flow
  map `vars: {}` parses on both sides). Seed `live.yaml` **verbatim** from the old real-template
  `vars` blocks (drop each `golden:` line) to preserve curated conditional-arm coverage (provider
  arms, with-url/no-url, model-clause empty/populated) for free.
- Selection-guard tests (`test_worker_prompt_parity.py`, `test_objective_prompt_parity.py`,
  `worker.test.ts`, `objectivePlan.test.ts`) assert *which arm is selected*, never read goldens —
  unaffected by the split (only their "golden cases" comments needed rewording to "live-parity
  cases").

## The bare-import source-scan guard (the bare-clone invariant)

The vendored modules must stay zero-runtime-dependency so a bare git clone loads them. A source-scan
guard enforces it:

- **Strip block+line comments BEFORE scanning** — the vendored modules' own headers contain
  explanatory `import … from "nunjucks"` / `"yaml"` text, so a naive scan false-positives on the
  very module that removed the dep (mirrors `surfacesGuard`).
- **Scan dynamic forms too**: `import("pkg")` / `require("pkg")` string-literal specifiers (a
  computed specifier has no literal to scan, acceptably).
- **Exclude both `*.test.ts` AND `testing/`** (only test-reachable, never in the runtime import
  graph rooted at `index.ts`; the tarball ships neither).
- Pair the TS scan with a Python `tests/test_packaging.py::test_no_runtime_dependencies`
  (package.json runtime `dependencies` absent or empty) — two guards, two planes, one invariant.

## The prompt-move pattern (the cornerstone)

How to relocate an inline prompt string literal onto a canonical template **without changing output**:

- **Single inline file vs subdirectory-of-arm-files — the deciding factor is in-code BODY branching,
  not just var differences.** If the prompt **body** branches in code (a provider arm, preview-vs-action)
  → a **subdirectory** with one complete-body template per branch (branching is template *selection*
  in code; conditional templates are the documented exception below). If only an injected **var**
  differs (computed by an existing helper) → a **single inline file**, no subdirectory.

- **The unify-vs-split decision rule — keyed on WHY the cold/warm bodies differ (the cornerstone of
  the whole 2.1–2.7 move series).** When relocating a cold/warm (sometimes worker) prompt pair, the
  unify-vs-split choice is a **plan-time decision driven by the *reason* the bodies differ**, not by
  surface diffing:
  - **UNIFY into one flat template (zero `{% if %}`)** when the differences are **superficial
    house-style** — header wording, a header blank line, step-number indentation, a plane-only
    qualifier, closing-paragraph phrasing. **Converge them away**: pick one canonical form, both planes
    emit it. Pattern: implement-2.2, learn-2.4, learn-docs-2.7.
  - **SPLIT into arm files in a subdirectory** (`prompts/stages/<x>/{seed,guidance}.md`) when the
    difference is **load-bearing semantics** — the **cold-injects / warm-instructs** asymmetry. The
    cold session launches a *fresh read-only session* and **injects** data (an `<untrusted_objective>`
    block; the node already marked `planning` by the cold door before launch); the warm session runs
    *in-session* and **instructs** the model to *fetch* it (`perk objective show` / `node-engagement`)
    and to mark state *itself* (the `objective_node` tool). Unifying would change behavior. Pattern:
    objective-plan-2.6. Keep the arm files separate even when the roadmap node title reads singular.
  - **The load-bearing caveat: unifying CHANGES output** (a plane gains/loses bytes), so it is a
    deliberate, user-approved **plan-time** decision — never an implementation default.
  - **The plane-only-qualifier tell.** A cold-only qualifier (e.g. "from this read-only session") is a
    tell for **superficial** — but verify its *premise* before deciding it is load-bearing. The warm
    `/learn-docs` session is **NOT** read-only (it injects via `pi.sendUserMessage`), so the qualifier
    was only cold-*accurate*; the bare "NEVER write the docs directly" is correct in both planes, so it
    dropped. **Verify the premise, then drop the qualifier if the bare wording holds on both planes.**

- **No-trailing-newline arm templates for mid-prompt fragments.** Fragments that embed inline are
  authored — template **and** golden — **without** a trailing newline, so `render()` returns the prior
  literal **byte-for-byte** (a deliberate departure from the fixture trailing-newline convention).
  Author with `printf` (**never** `echo`, which appends a newline); verify with `tail -c1 | xxd`. This
  keeps downstream consumers byte-identical.

- **Branching stays in code; pass the UNION of vars to every arm.** StrictUndefined / throwOnUndefined
  fire only on a **referenced** missing var, so passing unused vars to an arm is harmless. The render
  call convention is **`.md`-suffixed, root-relative under `prompts/`** (the objective's no-extension
  illustration is loose framing — don't copy it).

- **"Reconcile the warm/cold variance" can mean UNIFY, not just parameterize** — the superficial-arm
  of the decision rule above. When near-copy sites differ only by a house-style omission, unifying (one
  side *gains* the missing content → all sites byte-identical) is cleaner than a conditional preserving
  the divergence; it still **changes output**, so it stays a plan-time decision to confirm.

- **The single-arm subdirectory.** A conditional/early-return arm contributes **no template file and no
  golden** — only the rendering arm(s) do; branching stays in code (objective-read's `backend !=
  "linear" → ""`: github/other return `""` directly, no `github.md`/`other.md`, no `{% if %}`). Keep the
  **subdirectory shape** (`common/objective-read/linear.md`) even with a single arm file, for path-shape
  consistency across the common-prompt arms — don't collapse to a flat single file.

- **Demote-in-place a substring constant — check for other local consumers before deleting.** When
  swapping a cross-plane substring lockstep → golden parity, check whether the substring constant has
  **other local consumers** (retained per-plane selection / `_seed_prompt`-composition tests) before
  deleting it. `OBJECTIVE_LINEAR_SUBSTRINGS` **survived as a local in both planes** (its composition
  tests still consume it) — only the cross-plane *lockstep framing/comments* were removed. Contrast the
  earlier moves where `IMPLEMENT_SUBSTRINGS`/`ADDRESS_SUBSTRINGS` were deleted/"replaced". **Demote in
  place; don't churn.**

- **The byte-stability de-risker (the reusable workflow for transcription-risk moves).** Before deleting
  each literal, capture the **pre-change** output of the literal helper (`_seed_prompt(...)` /
  `factoryGuidance(...)`) for representative arg sets to `/tmp`, then assert the new `render(...)` equals
  the captured bytes in a **throwaway scratch script (NOT committed)**. This catches exact
  conditional-template transcription (em-dashes / backticks / `{% %}`) before you touch the committed
  golden harness — it complements the `printf` / `tail -c1 | xxd` no-trailing-newline mechanics above.

- **The `cases.yaml` backtick-quoting rule.** For a render var carrying literal backticks **plus**
  embedded quotes: do **NOT** escape the backtick — only `\"` / `\\` / `\n` / `\t` are escapable in
  this fixture format. miniYaml's `unescapeDoubleQuoted` leaves `` \` `` as a literal
  backslash-plus-backtick (golden mismatch) and PyYAML rejects it outright. Use a double-quoted scalar
  with **literal** backticks and only the inner `"` escaped.

- **Test posture: golden-fixture parity REPLACES substring parity, but keep a thin per-plane selection
  test** — one in each plane proving the code picks the right arm and `render()` is wired.

- **Warm guidance seeded via `pi.sendUserMessage` → assert on `notifies`, not `seeded`.** The harness's
  `seeded` only captures messages routed through a replaced `newSession({withSession})` ctx — **NOT** a
  direct `pi.sendUserMessage` on the real API (what `/address`, `/learn` use). Assert on the
  `report(...)` info/warning message instead — the canonical way to test a warm command that seeds a
  turn. The converged warm door also becomes **ref-aware** (resolves the active plan-ref via the same
  helper the learn door uses, null-guarding with a warning mirroring `/implement`).

## Conditional templates — whitespace control is the load-bearing gotcha

Most arm templates use `{{ var }}` only and keep branching in code. When branching instead moves
**into** a template as `{% if %}` (the learn-2.4 / objective-plan-2.6 pattern), whitespace control is
the gotcha that decides whether the output is byte-stable:

- **`{%- -%}` whitespace-control markers CANNOT express "trim newline only."** `-%}` strips the
  following newline **and** the next line's leading indentation — so a `  - ` bullet indent gets eaten,
  corrupting indented content. There is **no jinja/miniJinja marker for "trim newline only."**
- **The fix is the env flag `trim_blocks` (jinja2) / `trimBlocks` (miniJinja), now GLOBAL on.** It
  strips only the single newline immediately after a block tag, **preserving indentation** — so
  plain `{% %}` tags sit on their own lines and indented bullet content renders intact.
  `lstrip_blocks` stays **off** (tags at column 0). miniJinja `trimBlocks` matches jinja2
  `trim_blocks` **byte-for-byte** (the Tier-A contract snapshots are the proof; generate goldens
  with jinja2, the reference engine, then let the TS test confirm parity).
- **Bounded blast radius of a render-env flip.** `trim_blocks` only affects templates **containing
  block tags** — before flipping a shared render env, `grep '{%' across prompts/` to bound the impact.
  Keep an affected fixture's golden byte-stable by editing the **template** (e.g. add an explicit blank
  line) rather than regenerating the golden (the `with_include` fixture broke this way — the trim ate
  the blank line after `{% include %}`).
- **Coerce raw vars to strings so the `{% if %}` false arm behaves.** When branching moves into the
  template, helpers pass **raw** vars but must coerce — `model or ""` (Python) / `node ?? ""` (TS). A
  bare `None`/`undefined` either renders the literal or trips StrictUndefined/throwOnUndefined; the
  `{% if model %}` false arm only behaves on a string-typed empty value. Two byte-stable conditional
  shapes: **block-level** tags on their own line (`trim_blocks` swallows the trailing newline) and
  **inline** mid-line tags (no newline after `%}`, so `trim_blocks` is a no-op — no whitespace shift).
- **Selection stays in code; only string-ASSEMBLY moves to the template.** Distinguish *which clause to
  render* (the backend-arm selection — stays in code, e.g.
  `objective_read_instruction`/`objectiveReadInstruction`) from *how the clause is glued into the
  surrounding prose* (assembly — moves to the template). The arm logic is untouched; only the intro
  wrapping / leading space / clause wording moves into the template.
- **The stale-claim ripple (cross-ref `doc-reconciliation.md`).** A render-env or grammar change can
  flip *standing claims* in earlier nodes' LANDED notes ("trim/lstrip off"; "the frozen subset has no
  conditionals"). Record the **supersession in the node that caused it** — do **not** rewrite the
  historically-accurate older records — and amend `shared/contracts.md §8.31`. Residual the grammar-freeze
  spec must carry: `{% if/elif/else/endif %}` + string `==` + `or`/`not` as the frozen conditional subset.

## Recurring mechanics

- **`npm ci` in a fresh worktree before TS checks** when a recent node added a runtime dep (cross-ref
  `toolchain/worktree-node-modules.md`).
- The **`edit`-fails-across-an-em-dash** trap → a Python `str.replace` heredoc escape hatch.
- **`run_ci` green ≠ committed-format-green** — run the Biome formatter before assuming `lint-js` is
  clean (cross-ref `toolchain/biome.md`).
- Keep `contracts.md §8.31` references intact through comment-hygiene sweeps.

## Cross-references

- `docs/learned/workflow/shared-contracts.md` — the cross-plane SSOT prompt-fragment discipline + the
  vendored `miniYaml` reader (why `cases.yaml` must stay in the subset)
- `docs/learned/workflow/extension-clone-lifecycle.md`, `docs/learned/workflow/distribution.md` — the
  zero-runtime-dep invariant the vendored `miniJinja` now upholds (it removed the former nunjucks dep)
- `docs/learned/toolchain/worktree-node-modules.md` — `npm ci` in a fresh worktree
- `docs/learned/toolchain/biome.md` — `run_ci` green ≠ committed-format-green
- `extension/substrate/miniJinja.ts` — the vendored TS renderer; `extension/testing/renderLive.ts` —
  the Tier-B node renderer
- `prompts/` — the canonical templates; `prompts/_fixtures/cases.yaml` (Tier-A contract snapshots) +
  `prompts/_fixtures/live.yaml` (Tier-B live cross-engine parity manifest)
