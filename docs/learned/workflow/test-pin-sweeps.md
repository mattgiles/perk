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

That holds even for a plan whose pin enumeration is **presented as verified and self-correcting**
— a plan that explicitly corrected the count ("two pins exist, not one") was still wrong (four
existed). The implementer re-runs the grep over test sources for distinctive substrings of the
text being *removed* before trusting the count. Two hotspot facts: prompt-template **tail text is
a pin hotspot** — `endsWith(...)` pins target the template's *final line* specifically — and the
cross-plane parity suites duplicate the same pin, so **expect pins in pairs across planes**
(`extension/worker/worker.test.ts` + `tests/test_worker_prompt_parity.py`).

The prose flavor of the same rule: enumerated comment/phrase-sweep file lists fail **in both
directions** — a planned file can lack the phrase while an unplanned file carries it (including a
*data file's* comment block, e.g. `shared/providers.yaml` — easy to exclude from a code-comment
mental model). Sweep by grepping the phrase itself at implementation time; the plan's list is a
set of hypotheses / a floor, never the inventory.

## A negative substring pin can shape prose, not just guard it

A negative pin can force a clean structural rule rather than merely blocking a regression: "the
no-model arm must not contain the substring `model:` anywhere" forced the rule that fenced
skeletons never name a model field — the model rides only the prose arm as a workflow-level
default — which made the multi-site byte-parity survivable with zero churn. When wording pinned
prose, consider whether a negative pin can carry the architecture.

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

## A door's tool contract has TWO independently authored pinned surfaces

A model-facing tool contract is pinned in two places that do not share source: the **strict param
decode** and the **registered tool schema/guidance**. Widening an enum or a `maxItems` can be
green in the decoder suite while the live registered contract drifts — blocking the model from
calls the decoder would happily accept. The harness exposes `registeredTool(name)`
(name/description/parameters/promptGuidelines, mirroring `registeredCommands()`); door
registration tests pin enum/minItems/maxItems + guideline lines. The assertion-scan sweep must
enumerate **both** surfaces whenever a tool contract changes.

## Exact-composition pins on constants ripple

When a change grows a pinned constant (e.g. a tool-census array), expect exact-set `deepEqual`
pins in *sibling* test files to need the same-turn update — grep for the constant's name across
test files before declaring the change test-neutral. The perk-dev expectation-catalog census
(`test_committed_catalog_census`) is a fresh instance of the exact-set-pin pattern — see
`session-audit-expectations.md`.

The inverse trap: **presence checks are not least-privilege pins**. `includes(...)` assertions on
a stage's tool list let unrelated scoped tools ride undetected — tool-gating assertions guard
least privilege only as sorted exact-set `deepEqual` pins per stage. Companion lesson:
plan-fidelity review lanes earn their keep on exactly this "planned test deliverable quietly
downgraded" drift.

## Cross-references

- `docs/learned/workflow/skill-bindings.md` — the single-delivery test pins
- `docs/learned/workflow/prompt-templates.md` — template prose under byte-parity tests
- `docs/learned/workflow/plan-ref-lifecycle.md` — "exact-dict assertions ripple" (the
  schema-extension cousin of the grown-constant ripple)
