# Phase 2 · Turn 10 — `/objective-plan` factory + completion-audit (new `objective-plan` stage)

> The decision-complete plan lives on GitHub issue
> [#21](https://github.com/mattgiles/perk/issues/21) (`plan-body` block). This doc records the
> per-turn decisions in brief + the as-built **outcomes** once landed.

## Summary

Add the objective **transition** surface on top of T9's deterministic mechanics: a plan factory
that selects the next actionable objective node and emits a **bounded plan** through the existing
`plan → save` spine, plus the **completion-audit** contract exposed as a **bounded model tool**.
Adds the **`objective-plan`** registry stage + its dedicated cold door `perk objective-plan`,
establishes the **node↔plan link** (which T11 reconciliation-on-land depends on), and an **optional
Explore-then-Plan child** (`perk.objective-explorer`). Deterministic mechanics stay in Python
(`perk objective …`, T9); judgment (node selection, scope bounding, the prompt-to-artifact audit)
lives in the `perk-objective-plan` skill; durable writes stay with the parent.

## Decisions (as planned)

- **D1** — graph: `objective-plan → plan`; `objective-plan` is the new single initial (the only
  placement that satisfies the validator's exactly-one-initial rule; `learn` stays the single terminal).
- **D2** — `objective-plan` registry descriptor: `mode: read-only`, `worktree: none`,
  `doors.cold_remote: false`, `requires/reads: [github.objective]`,
  `writes: [github.objective, session.workflow-state]`.
- **D3** — dedicated `perk objective-plan [NUMBER] [--node ID]` cold door (`DEDICATED_STAGES`):
  require NUMBER, select next/explicit actionable node, mark it `planning`, launch a read-only
  plan-mode session seeded with the node.
- **D4** — `launch_stage(prompt_override=…)`: the override is the seeded prompt instead of
  `_initial_prompt` (objective-plan has no plan-ref). All existing callers pass `None`.
- **D5** — seed prompt + `skills/perk-objective-plan/SKILL.md`: the judgment layer (read objective,
  optional explorer spawn, author a bounded plan, always save, link the node back).
- **D6** — `.pi/agents/objective-explorer.md`: a perk-owned read-only Explore-then-Plan child
  (cheap model, `read/grep/find/ls/bash`, double-delivery findings).
- **D7** — thread `objective_id` through plan-save: `perk plan-save --objective-id` + the warm
  `plan_save` tool's `objective_id` param → `plan.PlanHeader`/`plan.PlanRef`.
- **D8** — `extension/objectivePlan.ts` (`registerObjectivePlan`): the `objective_node` bounded
  transition tool (delegates to the Python cold door, never throws; two arg shapes — `pr`-only
  backlink with no `--status`, and status-change with `--status`) + the completion-audit gate
  (`status:"done"` requires a `trim().length ≥ 40` `audit`, model-path-only) + the `/objective-plan`
  command.
- **D9** — `shared/contracts.md` §8.3 + §8.4 P2.T10 amendments (incl. the honest model-path-only
  enforcement note).

## Verify

`scripts/verify-p2-t10.sh` (offline; wired into `justfile` after `verify-p2-t9.sh`): touched Python
suites; registry valid + objective-plan initial-before-plan + dedicated; cli/DEDICATED_STAGES
wiring; the agent def + skill; the extension wiring + `objective_id` thread; the extension tests
(incl. the audit-refusal + `pr`-only-omits-status cases); the contract amendments; `plan-save
--objective-id`; doctor lists `objective-explorer`.

## Outcomes (as built)

Built as planned across both planes; no decision deviated. Notes:

- **Cold-door dry-run** emits a single resolution payload (`{success, objective, node,
  marked_status, dry_run}`) and does **not** fall through to `launch_stage` (avoids a second JSON
  object on stdout). `--remote` is rejected via `launch.resolve_target` **before** any node mutation.
- **`buildObjectiveNodeArgs`** is exported as a pure helper and unit-tested alongside the live
  delegation (a `fakePerk` argv-capture, added as an `argvFile` option on the test harness).
- **`isNonTrivialAudit`** is the pinned predicate (`typeof === "string" && trim().length ≥ 40`,
  `MIN_AUDIT_LENGTH = 40`), exported + unit-tested at the boundary.
- **doctor** `_subagent_engine_check` now enumerates committed `.pi/agents/*.md` defs in its detail
  (lists `perk.objective-explorer` + `perk.review-classifier`) rather than a constant example.
- The warm `/objective-plan` command resolves the objective from its arg else `active_objective`;
  it injects factory guidance via `pi.sendUserMessage` (mirrors `/address`), headless-safe.

### Deferrals (flagged)

- **Objective-level rollup-to-`done`** (whole-objective completion via `update_objective_header`) —
  no CLI command; T10's completion-audit unit is the **node**.
- **Automatic on-merge node-done** + objective prose reconciliation — **T11** (deliberately
  non-audited; T10 establishes the node↔plan link it consumes).
- **Multi-node plans** (erk's `--node X --node Y`) — T10 ships single-node selection.
- The **live factory turn + live `objective-explorer` spawn + live `ctx.compact`** are a
  dogfood/manual gate (mirrors T7/T9), not CI.
