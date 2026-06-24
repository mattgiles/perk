---
title: The cross-plane prompt-template seam — bundling tier, the byte-parity render config, the golden harness, and the prompt-move pattern
read_when: You are bundling a new top-level resource dir, working the cross-plane jinja2/nunjucks render seam, the golden-fixture parity harness, or moving an inline prompt literal onto a canonical `prompts/` template (single-file-vs-subdir, no-trailing-newline fragments, unify-vs-parameterize).
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
  → a **subdirectory** with one complete-body template per branch (the frozen jinja subset has **no
  conditionals**, so branching is template *selection* in code). If only an injected **var** differs
  (computed by an existing helper) → a **single inline file**, no subdirectory.

- **No-trailing-newline arm templates for mid-prompt fragments.** Fragments that embed inline are
  authored — template **and** golden — **without** a trailing newline, so `render()` returns the prior
  literal **byte-for-byte** (a deliberate departure from the fixture trailing-newline convention).
  Author with `printf` (**never** `echo`, which appends a newline); verify with `tail -c1 | xxd`. This
  keeps downstream consumers byte-identical.

- **Branching stays in code; pass the UNION of vars to every arm.** StrictUndefined / throwOnUndefined
  fire only on a **referenced** missing var, so passing unused vars to an arm is harmless. The render
  call convention is **`.md`-suffixed, root-relative under `prompts/`** (the objective's no-extension
  illustration is loose framing — don't copy it).

- **"Reconcile the warm/cold variance" can mean UNIFY, not just parameterize.** When near-copy sites
  differ only by an omission, **unifying** (one side *gains* the missing content → all sites
  byte-identical) is often cleaner than a fragment/conditional preserving the divergence — but it
  **changes output**, so it is a **plan-time decision to confirm**, not an implementation default.

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
