# Phase 3 · Turn 9 — Unified `[subagents]` model config (#196)

> **Naming note.** The plan (#196) called this doc `phase-2-turn-<M>`, but the repo's per-turn docs
> are `phase-3-turn-1..8`; the genuinely next-available doc is `phase-3-turn-9.md`. Following the
> real sequence (the plan author predated the phase-3 numbering).

## Decisions

- **Agent-keyed `[subagents]` table.** Replace the single `[pr-review] model` key with one flat
  `[subagents]` table keyed by the bare agent names — `pr-reviewer`, `review-classifier`,
  `objective-explorer` — matching each `.pi/agents/<name>.md` `name:` frontmatter and the
  `perk.<name>` invocation. Shape mirrors the flat `[providers]` selection (always-present object in
  TS; only-known-keys dict in Python; absent/blank/unknown keys omitted; no doctor validation).
- **Clean break, no alias.** `[pr-review] model` / `Config.pr_review_model` / `PerkConfig.prReview`
  are removed outright. Justified by perk `0.0.1` pre-release + AGENTS.md "init converges forward,
  no back-compat migrations." No migration shim in `init`/`doctor`.
- **All six spawn sites inject the configured inline `model`** the same way (a per-call inline
  `model` override on the `subagent` call — NOT `subagents.agentOverrides`, which reaches builtins
  only via `pi-subagents`' `applyBuiltinOverrides`):
  1. `extension/prReview.ts` `prReviewGuidance` → `perk.pr-reviewer`
  2. `extension/address.ts` `addressGuidance` → `perk.review-classifier`
  3. `extension/objectivePlan.ts` `factoryGuidance` → `perk.objective-explorer`
  4. `extension/worker.ts` `initialPromptFor` (address branch) → `perk.review-classifier`
  5. `perk/launch.py` `_address_prompt` → `perk.review-classifier`
  6. `perk/cli/commands/objective_plan_cmd.py` `_seed_prompt` → `perk.objective-explorer`
- **Parity literal (sites #4 + #5).** The review-classifier model clause is byte-identical in
  `worker.ts` (`ADDRESS_MODEL_CLAUSE`) and `launch.py` (`_address_prompt`), kept in lockstep by
  `extension/worker.test.ts` + `tests/test_worker_prompt_parity.py`:
  `, passing \`model: "<m>"\` on that call (the configured [subagents] review-classifier model)`.
- **Config threading.** `_initial_prompt` grew an optional `config` param so the address prompt can
  read `config.subagents["review-classifier"]`; `initialPromptForWorktree` reads
  `loadPerkConfig(worktree)`. The warm TS handlers read `loadPerkConfig(ctx.cwd)`.

## Prior art

- `[providers]` selection (Node 2.1): `parseProvidersSelection` (TS) /
  `_parse_providers_selection` (Python) — the exact shape the new `[subagents]` parser mirrors
  (flat table, string-only, unknown keys omitted, no doctor validation).
- The `/pr-review` inline-override precedent (#175) and the `applyBuiltinOverrides`
  builtins-only correction recorded in `shared/contracts.md` §8.3.

## Outcomes

- Config layer: `extension/config.ts` `PerkConfig.subagents` + `parseSubagentsSelection`;
  `perk/config.py` `Config.subagents` + `_parse_subagents_selection`. `[pr-review]` reader removed
  from both planes.
- All six spawn sites inject the inline model; `addressGuidance`/`factoryGuidance` exported for
  focused offline tests. `_seed_prompt`/`_address_prompt`/`_initial_prompt` gained model params.
- `perk/init.py` template: commented `[pr-review]` block replaced by a commented `[subagents]`
  block documenting all three agent keys (stays inert — `test_seeded_template_is_inert` passes).
- `shared/contracts.md` §8.3 amended: agent-keyed `[subagents]` paragraph (all-three/all-six), the
  T6 classifier-override note, and the address-under-worker open-dependency note.
- Tests added/updated across `config.test.ts`, `test_config.py`, `prReview.test.ts`,
  `address.test.ts`, `objectivePlan.test.ts`, `worker.test.ts`, `test_worker_prompt_parity.py`,
  `test_launch.py`, `test_objective_plan_cmd.py`.
- **Deferral:** `docs/learned/pi/subagents.md` still references the old `[pr-review] model` knob;
  learned-docs reconciliation is owned by `/learn-docs` (not hand-edited here) — intentional, noted.
</content>
