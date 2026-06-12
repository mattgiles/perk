---
title: Plan factory pattern
read_when: You are building or debugging a perk plan factory (learn-docs, objective-plan, or any new on-demand factory that launches a read-only planning session).
---

# Plan factory pattern

## The central constraint: inbox-over-gh

A seeded read-only plan-mode session historically **could not run `gh`/`perk` in bash** —
`extension/toolGating.ts` `SAFE_PATTERNS` allowed only
`cat`/`head`/`tail`/`grep`/`find`/`ls`/`git status|log|diff`/`jq`/`curl`.
So any cold-door factory must **do every GitHub read up front** and materialize the result into a
file the session reads via the `read` tool (e.g. `.pi/workflow/scratch/learn-docs-inbox.md`).
Untrusted fetched bodies are wrapped in a marker (`<untrusted_learning>…</untrusted_learning>`).
This is *why* the cold door gathers, not the model — at the time, the model couldn't call `gh` in
a plan session. (Since #416, read-only `gh` *query* subcommands pass the gate, so the constraint
is no longer structural — but the inbox pattern remains the canonical factory data flow:
deterministic, token-cheap, and prompt-injection-bounded via the untrusted markers.)

## Non-stage factories borrow the `plan` stage descriptor + `prompt_override`

A batched/on-demand factory does **not** need a `registry.yaml` stage. Reuse the existing `plan`
stage (`mode: read-only`, `worktree: none`, `cold_remote: false`) and seed via
`launch.launch_stage(stage=plan_stage, prompt_override=seed)`.

- `_initial_prompt` returns `None` for `plan`, so the override is the only seed.
- The `stage: "plan"` handoff makes the session present correctly.
- `plan` does not consume `cache.plan-ref` (no stale-ref leak into the factory session).
- `objective-plan` established this pattern; `learn-docs` reused it without touching
  `DEDICATED_STAGES` (that set only suppresses generic same-named launchers — a factory with no
  dedicated stage needs no entry there).

## On-land bookkeeping

When a learn-docs plan lands, consumed `perk:learn` issues are closed and labelled
`perk:consolidated`. This is handled by `_consume_learn_on_land` in the Python plane, which mirrors
the fail-open `_reconcile_objective_on_land` shape — see `docs/learned/workflow/plan-ref-lifecycle.md`
for the canonical fail-open pattern.

## Cross-references

- `docs/learned/workflow/plan-ref-lifecycle.md` — fail-open on-land bookkeeping pattern
- `docs/learned/pi/context-system.md` — the bash allowlist and why inbox-over-gh is necessary
