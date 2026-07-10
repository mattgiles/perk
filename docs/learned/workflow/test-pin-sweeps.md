---
title: Editing test-pinned prose and constants — the assertion-scan sweep
read_when: You are editing prose or constants that tests pin — planning an editorial rewrite of tested prose, a wrap-bisected substring pin, or an exact-set deepEqual pin on a grown constant.
---

# Editing test-pinned prose and constants — the assertion-scan sweep

perk pins load-bearing prose (guidance text, injected context, skill/template fragments) and
constants (tool censuses, key tuples) with test assertions. Editing anything in that class is a
sweep with its own craft — these are the durable rules.

## Enumerate pins by scanning assertions, not by reasoning

A plan claiming an editorial rewrite "passes by construction (all pinned phrases preserved)" is a
smell unless backed by a grep of the test sources for assertion patterns (`assert.match`,
`.includes(`, regex literals) over the prose being rewritten — undocumented pins otherwise surface
only as implementation test failures. The pin inventory is a scan output, never a memory exercise.

## Per-pin, the fix splits honestly

Each failing pin resolves one of two ways: **keep the phrase** (when the pin IS the contract — the
test exists to stop that wording drifting) vs **update the pin** (when the rewrite deliberately
drops a restatement the pin was only mirroring). Decide per pin; a blanket "update all the tests"
pass erases contracts, and a blanket "keep all the phrases" pass blocks legitimate rewrites.

## Line wraps can bisect substring pins

A substring pin fails when a re-wrap splits the pinned phrase across a newline. A plan supplying
exact multi-line prose should place wrap points off the pinned substrings, or state that wrapping
is flexible provided pinned phrases stay contiguous. An implementer hitting such a failure should
**move the wrap point, not weaken the pin**.

## Exact-composition pins on constants ripple

When a change grows a pinned constant (e.g. a tool-census array), expect exact-set `deepEqual`
pins in *sibling* test files to need the same-turn update — grep for the constant's name across
test files before declaring the change test-neutral.

## Cross-references

- `docs/learned/workflow/skill-bindings.md` — the single-delivery test pins
- `docs/learned/workflow/prompt-templates.md` — template prose under byte-parity tests
- `docs/learned/workflow/plan-ref-lifecycle.md` — "exact-dict assertions ripple" (the
  schema-extension cousin of the grown-constant ripple)
