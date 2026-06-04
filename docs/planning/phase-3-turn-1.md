# Phase 3 · Turn 1 — the learned-docs consumer (erk hop-2)

GitHub plan **#46**. perk's `/learn` already synthesizes durable learnings into terminal
`perk:learn` issues (P2.T8b/T15), but nothing consumed them — `contracts.md` §8.4 deferred "the
`docs/learned/*.md` documentation-plan loop … to its own objective node." This turn builds that
missing consumer as a **plan factory** that consolidates `perk:learn` records into committed
`docs/learned/` knowledge.

## Decisions (locked)

- **A — factory, not restructure.** `/learn` and the `perk:learn` record are untouched; this adds a
  separate batched consumer. (erk's learn issue *is* a plan; perk's is a prose *record*, so perk
  needs the extra hop.)
- **Minimal `docs/learned/`.** `docs/learned/<category>/*.md` with light frontmatter (`title`,
  `read_when`); category-placement judgment lives in the new `perk-learn-docs` skill. erk's heavier
  machinery (per-category auto-`index.md`, tripwire generation, `docs sync` codegen, multi-agent
  session preprocessing) is **deferred** — perk's synthesized `perk:learn` records replace erk's
  session-analysis pipeline.
- **3b-i — ambient index = `.pi/APPEND_SYSTEM.md`.** A plan-maintained **compressed** routing index
  lives in Pi's project-scoped system-prompt append (ambient on every session); the full catalog is
  standalone in `docs/learned/index.md`. Not `init`-managed, no codegen. (Correction: Pi has no
  in-file `@`-transclusion, so the ambient index is a real two-layer split, not an `@`-reference.)
- **Not a linear registry stage.** Dedicated cold door (`perk learn-docs`) + warm command
  (`/learn-docs`); borrow the existing `plan` stage descriptor to launch. `registry.yaml` unchanged.
- **Manual cadence; close + label on land.** Run on demand; consumed `perk:learn` issues are closed
  + labelled `perk:consolidated` at land (closing excludes them from the next `state=open` gather;
  the label is the durable/queryable record). Mirrors `_reconcile_objective_on_land` (fail-open).
- **Full consumer in one plan**, with a `## Steps` list for checkpoints.

## Findings (verified)

- **Discoveries.** The read-only tool gate's bash allowlist excludes `gh`/`perk`, so the seeded
  factory session must read the materialized inbox via the `read` tool (the cold door does every
  GitHub read). `launch_stage(prompt_override=…)` + the `plan` stage (`worktree: none`,
  `cold_remote:false`) is the launch seam. `find_plan_issue`'s list call is reused label-scoped for
  `list_learn_issues`. No close/label gateway op existed → `close_and_label_consolidated` added.
- **Corrections.** No in-file `@`-transclusion in Pi (context files load verbatim) → two-layer
  index. Not a registry stage (on-demand/batched) → no `registry.yaml` change.

## Outcomes

_(Write after the turn lands: deviations, refinements, deferrals.)_
