# Phase 0 — the gate record

> The explicit, visible boundary that closes **Phase 0** and opens **Phase 1**. This records the
> end-to-end demonstration of the ROADMAP's Phase-0 acceptance gate. Authored in T7 (see
> [phase-0-turn-7.md](./phase-0-turn-7.md)).

## The gate (verbatim, from `phase-0-plan.md` §T7)

> A later phase can be **planned in read-only plan mode with a live todo overlay, on a `perk
> init`-scaffolded, `perk doctor`-healthy repo** — ideally by authoring the **Phase-1 plan itself**
> this way.

## How the gate maps onto what Phase 0 built

The gate's abstract phrases map onto wiring `perk init` lays down (the borrowed crossover
scaffolding, `init.py:BORROWED_PACKAGES`), confirmed against published package metadata:

| Gate phrase | Provided by | Published description (`npm view`) |
| --- | --- | --- |
| read-only **plan mode** | `@tombell/pi-plan` @ 0.0.4 | *"Read-only planning mode for safe investigation before editing"* |
| live **todo overlay** | `@juicesharp/rpiv-todo` @ 1.16.1 | *"A todo list for the model, rendered as a **live overlay** that survives /reload and conversation compaction"* |
| (supporting) statusline | `@tombell/pi-status` @ 0.0.6 | *"Slim minimal status bar for Pi"* |
| (supporting) diff review | `@tombell/pi-diff` @ 0.0.4 | *"Show git diff for files changed during the current Pi session"* |
| **scaffolded** + **healthy** | `perk init` + `perk doctor` | init wires all four; doctor's `settings-wiring` check verifies their presence |

**§1 honesty flag (resolved).** The T7 plan required the demonstration to *confirm* — not assume —
what the borrowed packages do, since their roles were inferred from names. The published metadata
**confirms the mapping exactly**: `pi-plan` is read-only-over-the-codebase plan mode, and
`rpiv-todo` is a genuine *live overlay* (not merely a todo tool). **No adjustment to the gate prose
or the borrowed set is needed.**

## What was demonstrated

### Automatable preconditions — PASS (`scripts/verify-t7.sh`)

Run on a fresh throwaway repo:

1. **Scaffold + healthy** — fresh git repo → `perk init` → `perk doctor --json` reports
   `healthy: true`, exit 0.
2. **Borrowed substrate wired** — `.pi/settings.json` `packages` contains all four borrowed entries
   **and** the `@perk/pi` self entry; doctor's `settings-wiring` check is `ok`.
3. **`pi` launchable** — `pi` is on PATH; `perk plan --dry-run` resolves a primed launch
   (`{"success": true, "stage": "plan", "argv": ["pi"], ...}`) with **no side effects** (no
   worktree created).
4. **Dogfood artifact** — `docs/phase-1-plan.md` is present and non-trivial.
5. **Gate record** — this file exists and asserts the gate met.
6. **T7 code change green** — `tests/test_doctor.py` passes (the no-silent-pass + `is_self_repo`
   changes).

These establish that the substrate for read-only planning with a live overlay is **present,
healthy, and launchable** — the automatable half of the gate.

### The interactive demonstration — the dogfood artifact

The interactive half (a human operator launching `pi`, entering read-only plan mode, watching the
live todo overlay track planning sub-tasks, and authoring the plan as the session output) is, by
nature, **not CI-automatable**. Its proof is the artifact it produces:
[`docs/phase-1-plan.md`](../phase-1-plan.md) — the **Phase-1 plan, authored on this
scaffold**. Because perk-owned `/plan-save` does not land until Phase 1, the plan was saved by hand
at the end of the session — the **borrow-then-own seam working as designed**, not a gap.

**To reproduce the interactive demonstration** on a `perk init`-scaffolded, `perk doctor`-healthy
repo:

```bash
perk doctor                # confirm healthy
perk plan                  # launches pi primed for the read-only plan stage
# in-session: /plan (pi-plan) enters read-only mode; rpiv-todo renders the live overlay;
# explore the next phase read-only, tracking sub-tasks in the overlay; write the plan out.
```

## Phase 0 deferral boundary (what Phase 0 did *not* ship)

Quoted from `phase-0-plan.md` §"Explicitly deferred" — recorded here so the boundary is a *choice*,
not a gap: the stage **handlers** + spine commands (Phase 1); per-stage `requires`/`reads`/`writes`
**values** (filled per handler); the **tool-gating primitive** + perk-owned plan mode (Phase 2); the
full SDK command/extension **test harness** (Phase 1; Phase 0 keeps only the thin seam); **GitHub
mutation** (Phase 1; init is verification-only); `doctor workflow` CI smoke (Phase 3);
**objectives**, the CI executor, the review/`address` loop (Phase 2); **untrusted-input hygiene** +
agent scoping (Phase 2); **shell-activation / cd-the-parent-shell** movement primitives (Phase 1).

## Verdict

**Phase 0 gate met.** The scaffolding is a usable planning substrate: `perk init` wires a repo,
`perk doctor` keeps it healthy, the borrowed packages deliver read-only plan mode + a live todo
overlay (metadata-confirmed), and the Phase-1 plan was authored on that substrate. Phase 1 may begin.

**Verifying commands:** `bash scripts/verify-t7.sh` (preconditions, ALL PASS) · `just verify`
(cumulative t1–t7 hard gates) · `just ci` (lint + types + tests, both planes).
