---
title: §8.57 single-carrier prompt layering — carrier-migration craft across seeds, skills, and contracts
read_when: You are migrating a stage or door family to §8.57 single-carrier layering, dieting seed/skill prose, moving a statement's canonical carrier, or reconciling contracts.md carrier references.
cluster: cross-plane-contracts
---

# §8.57 single-carrier prompt layering — carrier-migration craft

`shared/contracts.md` §8.57 assigns every prompt-surface statement ONE canonical carrier (seed vs
skill vs contracts), with the other tiers pointing rather than restating. The evidence base for
this doc is the two carrier migrations run so far — the authoring family and the six review/wave
doors. Anchors: `shared/contracts.md` §8.57, the seeds under `prompts/`, the `skills/perk-*`
bodies, and the door-suite tests (e.g. `extension/doors/prReviewTerminal.test.ts`).

## Diet economics and verification

- **The payoff is the skill tier, not the seeds.** In a warm-door family the seeds were already
  near-minimal (2–12 % shrink; one seed changed by 2 lines) while skills shrank 15–44 % and
  frontmatter descriptions 60–75 % (net −216 lines for six doors). Budget and review-scrutinize
  carrier-migration nodes accordingly.
- **The door-suite test pins ARE the machine-checkable flow tier.** A budgeted full six-suite pin
  reconcile reduced to one re-anchored comment — the suites pin exactly the operational
  invariants + tool/param shapes the diet keeps. Treat pin reconciliation as a *verification*
  step, and read the pins as the de-facto definition of what a seed must keep.
- **The diet test-pin shape:** seed pins flip from "pointer present" to negative path assertions
  (`".agents/skills/perk-X" not in prompt`) plus one shape-delta pin per seed; context pins flip
  to state+pointer match/doesNotMatch pairs. Recurring trick: `"objective_save" not in prompt`
  works because hyphenated `/objective-save` doesn't substring-match.

## Carrier claims must be verified per session shape

- **Exact prose blocks in a plan are unsafe when the prose makes carrier claims.** Any
  prompt-surface sentence asserting *what else is injected/delivered* must be checked against
  **every session shape** receiving that surface (seeded doors, borrowed stages, provider
  postures) — three of one plan's "authoritative" texts were themselves false: marker-named
  pointers to a context the REPLACE posture never injects (fix: provider-neutral "this session's
  injected plan-authoring context"); an "in **every** plan-stage shape" claim contradicting its
  own carve-out; and a "(delivered as a nudge at launch)" claim false in replan sessions where
  the cold `command:` binding suppresses the warm stage nudge.
- **Carrier moves ripple beyond the amended sections** — grep `shared/contracts.md` for the old
  carrier identifiers (see `shared-contracts.md`'s same-turn-rule failure mode and its
  carrier-move corollary).
- **One nudge per launch trigger is the delivery design:** a cold `command:<id>` binding
  intentionally suppresses the warm `stage:<id>` nudge (header dedup); base-skill reachability
  moves to explicit read-path cross-references *inside* the specialized skills.

## Migration craft

- **A mutation-skipping carve-out needs its control-arm test in the same change** — for any
  `if`-guard that skips a save/mutation, pin BOTH arms (the carve-out and the ordinary path), or
  a broadened guard silently drops every ordinary case with no failing test.
- **When a doc's "only X does this" setup claim gains a second instance, generalize the claim to
  the mechanism** with instances listed after — never append a contradicting example.
- **Latent falsehoods surface reliably during carrier inventories** — the authoring migration
  flushed out dead direct-save endings, a wrong adapter flavor, and a real silent-data-loss bug
  (Plannotator gist approvals dropping browser Direct Edits). Budget for finding real bugs, not
  just prose moves.
- **Evidence a later node depends on must land in the PR body via an explicit post-submit
  `gh pr edit` step** — perk's squash-land drops branch commit messages from main's history and
  `submit` composes the PR body from the plan. (The §8.57 before/after byte measurements lived
  only in a branch commit; the ceilings derived from a fresh committed-tree re-measure instead —
  the re-measure resolved the debt, but the PR-body rule stands.)
- **The pointer-recap bar is settled** (recorded in §8.57): a pointer sentence MAY name the
  rules it defers to — the byte ceilings are the enforced bound; prose shape stays §8.57
  judgment.

## Residuals

- §8.57's byte ceilings landed in `tests/test_prompt_surface_budgets.py` (skill ambient
  descriptions + committed template files), but skill-body *content* pins remain **partial** —
  exactly the five §8.57-rewritten skills in `tests/test_skill_semantic_contracts.py`
  (`perk-learn`, `perk-learn-docs`, `perk-learn-code`, `perk-implement`, `perk-address`) plus
  `perk-learn-harvest`'s dedicated test — so body drift in the other perk skills remains
  CI-inert (bounded in bytes only).
- Provider-neutral seed flow-pointers rest on the REPLACE-posture adapter genuinely carrying the
  flow — asserted in contracts, not verified per session shape by any test.

## Cross-references

- `shared/contracts.md` §8.57 — the normative layering contract
- `docs/learned/workflow/shared-contracts.md` — the same-turn rule + the carrier-move sweep
- `docs/learned/workflow/skill-bindings.md` — the `binding_trigger` borrows-a-stage mechanism
- `docs/learned/workflow/test-pin-sweeps.md` — the pin-reconcile craft the diet leaned on
- `docs/learned/workflow/plan-review-flow.md` — the review-first flow the seeds point into
