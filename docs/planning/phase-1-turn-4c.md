# Phase 1 · Turn 4c — implement priming + the plan positional (a corrective turn)

> A **small corrective turn**, cut mid-Phase-1-gate (T6): the **dogfood run surfaced two real bugs**
> in the cold `implement` door. It is a *direct* fix (committed outside the loop) because of a
> chicken-and-egg: you cannot implement the implement-fix through a broken implement loop. It
> **converges forward** on T4a — T4a's history is not rewritten; this turn amends `implement`'s
> contract (see contracts §8.4 "Status (P1.T4c)"). Implemented + green before this doc was written.

---

## 1. Why (what the dogfood surfaced)

Driving the prek dogfood plan through the loop, `perk implement` failed two ways:

- **Bug 1 — no session priming ("does nothing").** `launch_stage` ended with `argv = ["pi",
  *pi_args]`; for implement `pi_args` is empty, so `pi` opened an **idle interactive session**. The
  handoff + plan-ref set *state* (the extension links `active_plan_ref`), but **nothing told the
  agent to read and implement the plan** — it just waited. This hit `perk resume` too (same
  `launch_stage`). *This was the actual blocker.*
- **Bug 2 — no plan positional.** `perk implement 1` forwarded `1` to `pi` as a **stray prompt**
  (T4a's D2 made implement read the *active* ref only). But [phase-1-plan.md](../phase-1-plan.md)
  §P1.T4 specified `perk implement <plan>` — so **D2 was the deviation**, and `perk implement N` is
  the natural verb. The user confirmed this is the intent.

## 2. Decisions

- **D1 — fix forward, not rewrite.** T4a stays a historical record; this turn supersedes its D2
  (no-positional) and adds priming. The contract is amended in the same turn (no drift).
- **D2 — `perk implement [PLAN]` is a dedicated command.** The generic registry launcher can't carry
  a typed positional; `implement` graduates to a hand-written command (`implement_cmd.py`), and the
  generic generator **skips** it (`stages.DEDICATED_STAGES`). Optional `PLAN` resolves via
  `perk resume`'s pieces (`github.get_plan` + `resume.reconstruct_plan_ref`), writes the active
  `cache.plan-ref` (so `#N` becomes the active plan, mirroring resume), then launches; omitting it
  uses the active ref (the T4a behavior, unchanged).
- **D3 — priming lives in the launcher (exterior).** `pi` delivers the first turn only via its CLI
  `[messages...]`, which the extension cannot synthesize — so "launch primed" (cli-vs-pi §2.3) is the
  launcher's job. `launch_stage` composes a stage-aware initial prompt; **only `implement`** is
  primed (read the plan via `gh issue view <n> --comments`, implement on the branch, `/submit` when
  committed). `plan` stays user-driven (unprimed).
- **D4 — share `parse_plan_id`.** Promoted from `resume_cmd._parse_plan_id` to a public
  `resume_cmd.parse_plan_id` (one canonical path); implement reuses it.

## 3. What was built

- **`perk/launch.py`** — `_initial_prompt(stage, plan_ref) -> str | None` (implement-only); wired into
  `launch_stage` so `argv = ["pi", *pi_args, *([prompt] if prompt else [])]`. When `--worktree`
  bypasses ref derivation, the prompt falls back to the repo-root active ref.
- **`perk/cli/commands/implement_cmd.py`** (NEW) — the dedicated `implement [PLAN]` command:
  optional positional → `require_github` + `get_plan` + `reconstruct_plan_ref` → write active ref →
  `launch_stage(worktree=None)`; `--dry-run` with a plan renders a resolve-only preview (no write, no
  launch); no positional → `launch_stage` reads the active ref (raises the T4a "needs a saved plan"
  when absent). Failures exit 1 (Click renders `UserFacingCliError`).
- **`perk/cli/stages.py`** — `DEDICATED_STAGES = {"implement"}`; the generator skips it.
- **`perk/cli/cli.py`** — registers the dedicated `implement`.
- **`perk/cli/commands/resume_cmd.py`** — `_parse_plan_id` → public `parse_plan_id`.

## 4. Tests & gate

- **`tests/test_launch.py`** — `argv` carries the priming prompt for the implement dry-run;
  `_initial_prompt` primes implement only (not `plan`, not a `None` ref).
- **`tests/test_implement_cmd.py`** (NEW, 4 CliRunner) — `implement N` writes the active ref +
  launches; `implement N --dry-run` neither writes nor launches; plan-not-found exits 1; `implement`
  (no arg) uses the active ref **without** reading GitHub.
- **`tests/test_cli_stages.py`** — `test_implement_requires_plan_ref` stays green (the dedicated
  command propagates the same `UserFacingCliError`).
- **`scripts/verify-p1-t4c.sh`** (offline) — priming present for implement / absent for plan;
  `implement` dedicated + in `--help` + rejects `implement 0`; unit suites green. Wired into
  `just verify` after `p1-t4b`.

## 5. Contract / registry

- **contracts §8.4** — added "Status (P1.T4c)": the plan arg + priming, fix-forward over T4a's D2.
- **registry** — **no I/O change** (`implement` still `requires/reads:[cache.plan-ref]`,
  `writes:[session.workflow-state]`, `doors.warm:false`). The change is door *ergonomics*, not state.

## 6. Out of scope (still Phase 2+)

The warm-path in-process `ctx.newSession` fresh context; per-stage priming beyond implement; fetching
+ embedding the plan body into the worktree (the prompt points the agent at `gh issue view` instead);
the `implement <plan>` → branch-protection / existing-PR nuances (resume already covers re-entry).

## 7. Outcomes (landed, all green)

- **Green sweep:** `just ci` green (168 pytest, +5; ruff + ruff-format + ty + biome + tsc clean);
  `just verify` — all 17 gates PASS incl. the new `P1.T4c`.
- **Verified live shape:** `perk implement --dry-run` (seeded active ref) emits
  `argv = ["pi", "<read plan #N … /submit>"]`; `perk implement N` resolves + selects the plan.
- **Deviations from plan:** none material. The `implement N --dry-run` preview prints JSON (stdout) +
  a human line (stderr) without a `--json` flag (implement is a launcher, not a query verb); tests
  assert on substrings + side-effects rather than parsing mixed streams.
- **Unblocks:** the T6 dogfood run resumes at Step 3 with `perk implement 1` working — fresh primed
  session that reads plan #1 and implements it.
