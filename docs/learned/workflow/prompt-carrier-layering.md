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
- **Classify every clause before dieting it:** flow stays at the launch carrier, elaboration moves
  behind the pointer, and invariants move to a surviving carrier — they never vanish. Security
  invariants are especially easy to mistake for redundant elaboration: one diet removed the rule
  to read the materialized learn inbox rather than re-fetch it, reopening a path around the
  `<untrusted_learning>` envelope.
- **Pointer-back openings must be shape-aware.** A skill that serves multiple session shapes
  cannot present one shape's flow as universal (for example, `perk-address` serves `/address` and
  `--preview`, while `perk-learn` serves wave and cold/fallback shapes). Name the shapes together,
  then route on their deterministic branch instead of saying only "your launch guidance said."

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
- **The concrete §8.57 carrier map: one flow statement per session shape** (#1955) — the shared
  plan-authoring context; the tombell REPLACE adapter carve-out; the three objective-author
  launch variants (seed/adopt/file). The bound skill *recaps* rather than restates, and the
  carrier inventory is verified against `pi/v1/plan.ts` deferrals/`installPlanMode` before
  writing.
- **One nudge per launch trigger is the delivery design:** a cold `command:<id>` binding
  intentionally suppresses the warm `stage:<id>` nudge (header dedup); base-skill reachability
  moves to explicit read-path cross-references *inside* the specialized skills.
- **Closed: the REPLACE-posture flow-carrier claim is pinned by one generic seeded-plan-shape
  proof.** The adapter is shape-blind (it reads only the rebuilt workflow state's mode/stage
  plus branch markers), every pointer-carrying seeded door presents the identical
  `{mode: read-only, stage: plan}` state, and `pi/v1/providers/tombell.test.ts`'s gate-active case
  (injection + flow content) plus dedup case (once-only) exercise exactly that state, with the
  objective-plan control arm pinning the exception set at exactly
  `{objective-author, gist-author}`. One generic shape test beats per-door lookalike fixtures
  when the shapes are adapter-indistinguishable.

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
- **Do not use the PR body as an intermediate evidence carrier.** The submit flow in
  `src/perk/cli/commands/pr/submit_cmd.py` owns that body and recomposes it from the plan on every
  publish, so a manual append is erased by any later perk publish. An `/address` pass proved this
  by wiping a twice-executed append. The verified mechanism scope (#2026, #1993): layer
  publish/re-publish gestures (the submit and address paths) recompose the body via
  `create_pr`/`update_pr_body`, while the `ready` gesture dispatches before body composition
  (`src/perk/delivery/publish.py`). A plan-MANDATED record aimed at the PR body therefore
  silently drops unless an explicit post-publish step exists — route mandated records to a
  durable PR comment or the plan issue. "Post-submit, next turn" steps are unreliable for the same
  structural reason: `submit` and `finalize_address` terminate their turns, leaving the promised
  follow-up to compete with whatever happens next. Prefer, in order: re-derivable facts anchored
  to a commit SHA (re-measure the committed tree); a PR comment, which submit never recomposes; or
  the plan/objective issue. Use the PR body only after the final publish — a moment that cannot be
  known in advance. The earlier diagnosis that the measurements had existed only in a branch
  commit was wrong: the PR-body step ran and its output was lost anyway; the downstream work
  recovered by re-measuring the committed tree.
- **The pointer-recap bar is settled** (recorded in §8.57): a pointer sentence MAY name the
  rules it defers to — the byte ceilings are the enforced bound; prose shape stays §8.57
  judgment.

## Residuals

- §8.57's byte ceilings landed in `tests/test_prompt_surface_budgets.py` (skill ambient
  descriptions + committed template files), but skill-body *content* pins remain **partial**: the
  live census of pinned bodies is `tests/test_skill_semantic_contracts.py` (read the test file —
  it now covers review-skill bodies beyond the original five §8.57-rewritten skills) plus
  `perk-learn-harvest`'s dedicated pin
  (`tests/test_learn_harvest_cmd.py::test_skill_semantic_contract`). The ceilings gate ambient
  descriptions and committed template files only — they never measure a skill *body* — so body
  drift in any skill outside those pins remains CI-inert (no body-size guard exists).

## Cross-references

- `shared/contracts.md` §8.57 — the normative layering contract
- `docs/learned/workflow/shared-contracts.md` — the same-turn rule + the carrier-move sweep
- `docs/learned/workflow/skill-bindings.md` — the `binding_trigger` borrows-a-stage mechanism
- `docs/learned/workflow/test-pin-sweeps.md` — the pin-reconcile craft the diet leaned on
- `docs/learned/workflow/plan-review-flow.md` — the review-first flow the seeds point into
