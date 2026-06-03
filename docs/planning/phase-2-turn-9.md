# Phase 2 · Turn 9 — Objective storage + mechanics (the plan factory's foundation)

> The decision-complete plan lives on GitHub issue
> [#19](https://github.com/mattgiles/perk/issues/19) (`plan-body` block). This doc records the
> per-turn decisions in brief + the as-built **outcomes** once landed.

## Summary

Add the **objective layer** — a long-running goal that *generates* bounded plans rather than being
implemented directly (PRIOR_ART §3). T9 ships the **deterministic mechanics only**: a pure Python
objective module (`perk/objective.py`), the GitHub gateway ops that persist objectives, the cold-door
`perk objective …` workers, and the TS extension substrate for **budget accounting +
threshold-triggered compaction** keyed off the now-live `active_objective`. **No registry stage and
no model-facing transition tools** — the `objective-plan` stage, the plan factory, the
completion-audit, and the bounded "fire only when…" tools are **T10**. Status model is
**explicit-status-only** (foundation open #3): node status is never inferred from a PR column.

## Decisions (as planned)

- **D1** — `perk/objective.py`: a pure module mirroring `plan.py`, reusing its generic block engine
  (`render_metadata_block`/`replace_metadata_block`/`find_metadata_block`) — no `plan.py` refactor.
  `NodeStatus` StrEnum, `ObjectiveNode`/`ObjectiveHeader` frozen dataclasses, roadmap parse/render,
  phase-from-ID-prefix, explicit-status-only `update_node`/`add_node`, dependency graph +
  `next_node`/`is_complete`/`summary`. Schema starts at perk's own `"1"`.
- **D2** — `perk/github.py` objective ops: `find_objective_issue` (label-scoped via the
  parameterized finder), `create_objective_issue` (two-step create + comment-id backfill),
  `get_objective`, `update_objective_node` (body + comment both re-rendered), `update_objective_header`.
- **D3** — the `perk objective` cold-door group (`create`/`show`/`node`/`next`), registered in `cli.py`.
- **D4** — `extension/objective.ts` (`registerObjective`): `/objective [<id>|clear]`, budget
  accounting (stateless rebuild from a dedicated `perk:objective-budget` marker), threshold compaction.
- **D5** — no registry stage; contract (§8.3 budget + §8.4 objective ops) + `registry.yaml` vocabulary
  comment amendments only.

## Verify

`scripts/verify-p2-t9.sh` (offline): touched Python suites green; registry valid + `perk objective`
lists `create`/`show`/`node`/`next`; gateway ops present; group registered; `extension/objective.ts`
+ `registerObjective`; `extension/objective.test.ts` green; contract amendments present; `perk:objective`
label constant. Wired into `just verify`.

## Outcomes (as built)

Built as planned, with these specifics worth recording:

- **`perk/objective.py`** reuses `plan.render_metadata_block`/`find_metadata_block` directly — the
  objective `objective-roadmap` block is a normal perk metadata block (details + YAML), so erk's
  separate roadmap-block renderer was **not** ported. Only the node validation (`validate_roadmap`),
  the compact serialization (`render_roadmap_block`, omitting `depends_on`/`comment` columns unless
  used), the rendered table (`render_roadmap_table` + `render_body_comment` + `rerender_body_table`),
  phase derivation, mutation, and the dependency graph are new. erk's sparkline/head-state display
  helpers were **dropped** (not needed for mechanics).
- **Explicit-status-only**: `update_node` takes `status` verbatim or preserves it; erk's
  `in_progress`-when-PR-set inference branch is **dropped** (open #3).
- **Gateway**: `create_objective_issue` is the two-step create (idempotency check → lazy
  `perk:objective` label → compose body → POST issue → POST `objective-body` comment via a new
  `_post_comment_with_id` (`--jq {id:.id}`) → backfill `objective_comment_id` via
  `update_objective_header`). `update_objective_node` re-renders the authoritative `objective-roadmap`
  block in the issue body AND best-effort re-renders the table in the `objective-body` comment
  (fetched by `objective_comment_id`). A not-found node raises `GitHubError`; the `node` command maps
  it to `error_type: node_not_found`.
- **Config**: the threshold is read as `[objective] compact_threshold` through `extension/config.ts`.
  Because the TS TOML subset reads only **string** values (and a test pins that non-string scalars are
  ignored), the threshold must be written **quoted** (`compact_threshold = "0.8"`); `loadPerkConfig`
  `parseFloat`s + range-validates it. Default `0.8` (`DEFAULT_COMPACT_THRESHOLD`).
- **Budget**: the dedicated `perk:objective-budget` activation marker carries `{ objective_id,
  activated_at }`; budget is a stateless rebuild (sum assistant `usage.input+output` after the latest
  marker, clamped ≥0). Rebuilt/rendered on `session_start`, `session_tree`, **and** `agent_end`;
  status is `ctx.hasUI`-guarded and inert when `active_objective == null`. Never throws.

### Deferrals (flagged)

- The `objective-plan` registry stage, the plan factory, the completion-audit, and the bounded
  model-facing transition tools are **T10** (would be authoring fiction here per AGENTS.md).
- The custom cheaper-model `session_before_compact` summarization is deferred; T9 ships the simpler
  threshold-triggered `ctx.compact`.
- **Offline boundary**: live `agent_end` token usage and live `ctx.compact` need a real model →
  a dogfood/manual gate, not CI. CI covers the pure helpers, the Python workers (fake gateway), and
  the wiring.
