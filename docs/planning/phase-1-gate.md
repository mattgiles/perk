# Phase 1 — the gate record

> The explicit, visible boundary that closes **Phase 1** and opens **Phase 2**. It records the
> end-to-end demonstration of the ROADMAP's Phase-1 acceptance gate — **perk shipped perk** — on
> perk's own repo. Authored in T6 (see [phase-1-turn-6.md](./phase-1-turn-6.md)), after the live run.

## The gate (verbatim, from [phase-1-plan.md](../docs/phase-1-plan.md) §"Acceptance gate")

> **perk ships perk.** A real change to perk is **authored and saved as a perk plan, then
> implemented, submitted, landed, and learned-from through perk's own thin loop** — end to end, on
> perk's own repo. From that point, every Phase-2/3 change rides the validated spine, not planning
> alone.

## How the gate maps onto what Phase 1 built

The spine the gate exercises — each stage with a cold door (CLI → fresh `pi`) and, where legal, a
warm door (in-session slash command):

| Stage | Cold door | Warm door | Built in |
| --- | --- | --- | --- |
| **plan** | `perk plan` (read-only plan mode, borrowed `pi-plan`) | `/plan` | P0.T4 + borrow |
| **save** | `perk plan-save` | `plan_save` tool / `/plan-save` | P1.T2a/T2b/T3 (+ T3b) |
| **implement** | `perk implement [PLAN]` (primed, plan-aware) | `/implement` (guard-only) | P1.T4a/T4b (+ T4c) |
| **submit** | `perk pr-submit` | `submit` tool / `/submit` | P1.T5a |
| **land** | `perk pr-land` | `land` tool / `/land` | P1.T5b |
| **learn** | *(none — by design)* | `learn` tool / `/learn` | P1.T5b |
| **resume** | `perk resume <plan>` | *(cross-stage verb)* | P1.T5c |

GitHub mutations are canonical in the Python gateway; the warm doors **delegate** to thin workers via
`pi.exec` (contracts §8.4, D1).

## What was demonstrated

### The live run — perk shipped perk (the dogfood artifact)

A real perk change — **add `prek` + a ruff pre-commit hook** — was driven through the whole loop on
`github.com/mattgiles/perk`, end to end:

1. **plan** — authored in a live `perk plan` read-only plan-mode session.
2. **save** — stored to GitHub as **plan issue [#1](https://github.com/mattgiles/perk/issues/1)**
   (now **CLOSED**), with the local `cache.plan-ref` written.
3. **implement** — `perk implement` materialized the `plan-1` worktree/branch and a fresh `pi`
   session did the work (`prek.toml`, the `just hooks` recipe, README); `prek run --all-files` ran
   ruff green; committed.
4. **submit** — opened a **draft PR [#2](https://github.com/mattgiles/perk/pull/2)** linking the plan.
5. **land** — marked ready + **squash-merged** (merge commit `4acee9d`; `Closes #1` closed the plan);
   set `pending-learn`. No review gate blocked the self-merge.
6. **learn** — cleared `pending-learn`, releasing the worktree.

**The definitive closed-loop proof:** `perk resume 1 --dry-run` →
`{"resumed_stage": null, "message": "plan #1 is merged and learned — nothing to resume"}`. perk's own
resume state machine sees the loop as fully closed (PR merged + learned).

### Automatable preconditions — PASS (the cumulative gates)

The spine is present, healthy, and launchable **fully offline** — proven by `just verify` (all gates
green), not a single new script:

- **plan/implement/submit/land resolve `--dry-run` offline with no side effects** — `verify-p1-t4a`
  (implement derives `plan-<pr_id>` + is primed), `verify-p1-t5a/b` (submit/land), `verify-p1-t4c`
  (priming + the plan arg).
- **registry per-stage state-I/O + doors filled for all six spine stages** — asserted across
  `verify-p1-t4a` / `t5a` / `t5b`.
- **the dogfood change itself** is gate-checked by **`verify-p1-t6.sh`** (prek.toml validity, the
  ruff rev ↔ pyproject floor lockstep, `just setup` wiring) — the as-built T6 script verifies the
  *payload*, while the spine preconditions are covered by the cumulative gates above.

### The gate's real value — two bugs the dogfood surfaced and fixed forward

Dogfooding earned its keep: the run exposed two genuine defects that offline fakes never could, both
fixed as corrective turns (converging forward, history intact):

- **[T4c](./phase-1-turn-4c.md)** — `perk implement` launched a **bare, idle `pi`** (no priming →
  "does nothing") and ignored a plan positional (`perk implement 1` forwarded `1` to pi). Fixed:
  `launch_stage` now primes the implement session (read the plan → implement → `/submit`), and
  `perk implement [PLAN]` accepts an issue number.
- **[T3b](./phase-1-turn-3b.md)** — `/plan-save` saved a **conversational message** as the plan and a
  TOML `# comment` became the title, because the `<proposed_plan>` marker was **perk-invented, not
  native** to `pi-plan`. Fixed: the `plan_save` tool (explicit `plan` param) is canonical; `savePlan`
  **fails fast while plan mode is active** (detected via pi-plan's own `plan-mode-state` entry);
  `derive_title` skips `#` inside code fences.

### As-built deviation (recorded, not hidden)

The implement session chose the **remote `astral-sh/ruff-pre-commit`** repo in `prek.toml` (PATH-free:
prek builds its own ruff env) over the plan's `local`+`uv run` hook (single ruff source), keeping the
rev in **lockstep** with the pyproject ruff floor (gate-enforced). A defensible trade (PATH-independence
for a second pin) — the dogfood realizing the plan with judgment, as intended.

## Phase 1 deferral boundary (what Phase 1 did *not* ship)

Quoted from [phase-1-plan.md](../docs/phase-1-plan.md) §"Explicitly deferred", so the boundary is a
*choice*: perk-owned plan mode + the tool-gating primitive (removes the `pi-plan` coupling; makes
save the read-only→read-write gesture); objectives, the CI executor, the review/`address` loop,
feedback classification; PR-body two-target craft, `pr check`, draft→ready nuance, reconciliation
typing, deep learn tooling; the end-to-end **worker** tests (Phase 3); subagent delegation +
untrusted-input hygiene; the in-process `ctx.newSession` warm-path fresh context.

## Verdict

**Phase 1 gate met.** A real change rode perk's own thin loop end to end — authored, saved,
implemented, submitted, landed, and learned-from — leaving a merged PR (#2), a closed plan issue
(#1), and a resume state machine that reports the loop complete. The run also did what a dogfood gate
is *for*: it surfaced two real defects (T4c, T3b) that were fixed forward. Every Phase-2/3 change now
rides the validated spine. **Phase 2 may begin.**

**Verifying commands:** `just verify` (cumulative Phase-0 + Phase-1 hard gates, ALL PASS) · `just ci`
(lint + types + tests, both planes) · `perk resume 1 --dry-run` (the closed-loop proof).
