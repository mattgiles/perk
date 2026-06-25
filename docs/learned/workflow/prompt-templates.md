---
title: The cross-plane prompt-template seam — bundling tier, the byte-parity render config, the golden harness, and the prompt-move pattern
read_when: You are bundling a new top-level resource dir, working the cross-plane jinja2/nunjucks render seam, the golden-fixture parity harness, or moving an inline prompt literal onto a canonical `prompts/` template (the unify-vs-split decision rule keyed on WHY the bodies differ, conditional templates and the `trim_blocks` whitespace gotcha, raw-var string coercion, single-file-vs-subdir, the single-arm subdirectory, demote-in-place substring constants, no-trailing-newline fragments, the byte-stability `/tmp`-capture de-risker).
---

# Cross-plane prompt templates

perk's prompts live as canonical templates under top-level `prompts/`, rendered on **both planes** —
jinja2 in Python, nunjucks in the TS extension — from the **same** template bytes. This doc captures
the seam's load-bearing decisions: which bundling tier a new resource dir joins, the exact render
config that makes both engines byte-identical, the golden-fixture parity harness, and the
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

## The cross-plane render seam — the byte-parity Environment config

The two engines are configured to render **byte-identically**. The exact config is recorded here as a
**data shape** (a sanctioned exception to the One Code Rule — getting one flag wrong silently diverges
the planes):

- **jinja2:** `autoescape=False`, `trim_blocks=False`, `lstrip_blocks=False`,
  `keep_trailing_newline=True`, `undefined=StrictUndefined`.
- **nunjucks:** `{ autoescape: false, trimBlocks: false, lstripBlocks: false, throwOnUndefined: true }`.

> **`trim_blocks` is the one default conditional templates flip on.** The table above records
> `trim_blocks=False` / `trimBlocks:false` as the seam default. Templates that use **block tags**
> (`{% if %}` on their own line) render with `trim_blocks`/`trimBlocks` **on** so the single newline
> after each tag is swallowed and indented bullet content survives (see "Conditional templates"
> below). This is keep-and-annotate, not a contradiction: the default stays `False`; conditional
> templates opt in. `lstrip_blocks` stays off in both modes (tags sit at column 0).

`keep_trailing_newline=True` is **load-bearing**: jinja2 otherwise strips one trailing `\n` while
nunjucks keeps it, so omitting it diverges the planes on every template that ends in a newline.
`{% include "<root-relative path>" %}` resolves **root-relative under `prompts/`** on both engines;
watch the include-trailing-newline-plus-post-tag-newline **blank-line gotcha** (an included fragment's
trailing newline plus the newline after the `%}` tag yields a blank line).

**jinja2 is the reference engine** — the committed golden bytes ARE jinja2 output: generate once with
jinja2, then assert nunjucks matches byte-for-byte.

## The golden-fixture parity harness

`cases.yaml` drives the parity harness, but it is read on the TS side via the vendored **`miniYaml`**
subset (see `shared-contracts.md`), which **throws on `|` / `>` block scalars**. Consequences for
authoring cases:

- **Golden outputs are separate committed files** referenced by a `golden:` path — **never** inline
  multiline YAML.
- Author cases **within the miniYaml subset** (block maps/seqs, double-quoted strings).
- **Vars are strings only**, to sidestep the jinja2-vs-nunjucks non-string divergence (`True`/`true`,
  number formatting differ between engines).

Dependency posture: nunjucks is a **runtime** dep that **deliberately breaks the zero-runtime-dep
invariant** (see `extension-clone-lifecycle.md` / `distribution.md`) until the vendored-renderer node.

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
  corrupting indented content. There is **no jinja/nunjucks marker for "trim newline only."**
- **The fix is the env flag `trim_blocks` (jinja2) / `trimBlocks` (nunjucks).** It strips only the
  single newline immediately after a block tag, **preserving indentation** — so plain `{% %}` tags sit
  on their own lines and indented bullet content renders intact. `lstrip_blocks` stays **off** (tags at
  column 0). nunjucks `trimBlocks` matches jinja2 `trim_blocks` **byte-for-byte** (the golden suite is
  the proof; generate goldens with jinja2, the reference engine, then let the TS test confirm parity).
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
  zero-runtime-dep invariant the nunjucks dep temporarily breaks
- `docs/learned/toolchain/worktree-node-modules.md` — `npm ci` in a fresh worktree
- `docs/learned/toolchain/biome.md` — `run_ci` green ≠ committed-format-green
- `prompts/` — the canonical templates; `prompts/_fixtures/cases.yaml` — the golden parity harness
