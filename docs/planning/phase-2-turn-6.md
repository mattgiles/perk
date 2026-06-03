# Phase 2 · Turn 6 — spawned delegation engine seam

> Implementation-level plan for **P2.T6** — perk's *second* context-isolation shape: a **spawned**
> read-only child engine stood up by **borrowing the `pi-subagents` engine** behind a thin seam
> rather than building a spawn primitive. T6 is **substrate only**: wire the package, establish the
> perk-owned agent-definitions home (`.pi/agents/`), add a standing `perk doctor` signal, amend the
> cross-plane contract, and record the de-risking spike that settles open decision #6. No registry
> stage, no in-session TS consumer, no perk-authored agent definitions, no roster/model-tier config —
> those land with the seam's first consumer, **T7 (`/address`)**.

The canonical plan (objective, corrections, decisions, test plan) is GitHub plan issue **#13**.
This doc records the prior-art pass and the **outcomes**.

---

## 1. Prior-art pass (what exists, what we borrow)

- **`pi-subagents` v0.26.0** (`~/dev/github/nicobailon/pi-subagents`, npm `pi-subagents`) — the borrow
  target. Registers a single `subagent` tool + slash commands; `package.json` exposes
  `pi.extensions`, `pi.skills`, `pi.prompts`, `bin: pi-subagents`. Children spawn with
  `["--mode","json","-p"]` (`src/runs/foreground/execution.ts`, `src/runs/background/subagent-runner.ts`);
  every clarify-UI path is guarded by `ctx.hasUI` — structurally headless-safe.
- **`perk/init.py` `BORROWED_PACKAGES` + `_converge_settings`** — the clean borrow seam. `_npm_name`
  dedup already handles unscoped names (`pi-subagents`: `rfind("@") == -1` ⇒ whole name). T6 appends
  `npm:pi-subagents`.
- **`init.managed_convergences` / `doctor._managed_checks`** — the one desired-state SSOT (D2): `init`
  applies (`apply=True`), `doctor` dry-runs (`apply=False`) for drift and `--fix` re-applies. T6 adds
  the `subagent-agents` convergence (mirrors `_converge_workflow_dir`'s shape).
- **`doctor._registry_check`** — the precedent for a standalone, non-managed check covering something
  no convergence owns. T6's `_subagent_engine_check` follows it (a constant informational pointer).
- **`shared/contracts.md` §8.3** — the `**In-process read-only child sessions (P2.T4).**` and
  `**Read-only CI executor (P2.T5).**` bold-paragraph amendments. T6 files as a sibling bold paragraph
  in the same cluster, binding the spawned shape to the T4 handoff contract.

## 2. Outcomes (as-built)

- **Borrow wired, defs owned.** `npm:pi-subagents` added to `BORROWED_PACKAGES`; `subagent-engine`
  capability declared (`required`, `scope="both"`); `borrowed-packages` summary updated. perk authors
  **no** `subagent` tool — it borrows the engine and owns only the defs/signal/contract.
- **`.pi/agents/` is the perk-owned defs home.** New `_converge_subagent_agents` idempotently creates
  `.pi/agents/.gitkeep` (committed, **not** gitignored — perk owns and commits its defs). Registered
  as the `subagent-agents` convergence after `workflow-dir`. Shipped **empty** on purpose — T7 drops
  the first real def in it (no fiction authored now).
- **One SSOT, no duplicate drift.** Package presence is owned by `settings-wiring`; the defs dir by
  `subagent-agents` (fails when removed, repaired by `--fix`). The new `_subagent_engine_check` is a
  **constant** `ok` pointer in the `package` group — it reads nothing and never re-derives that drift;
  its `detail` carries the honesty note that the live-spawn smoke is a Phase-3 deferral. Tests prove
  removing `.pi/agents/` fails only `subagent-agents` while `subagent-engine` stays `ok`.
- **Contract amended in §8.3** as `**Spawned delegation engine seam (P2.T6).**` (sibling to T4/T5),
  documenting the borrow boundary, defs location, handoff reuse, never-delegate boundaries, locked
  model-tiering convention (value deferred to T7), the standing-signal/spike/live-smoke split, and the
  deferred roster control + `.agents/`-collision mitigation.
- **Dogfood converged** via `perk init` (self mode): `.pi/settings.json` gained `npm:pi-subagents` and
  `.pi/agents/.gitkeep` is committed.
- **Offline hard gate** `scripts/verify-p2-t6.sh` wired into `just verify` after `verify-p2-t5.sh`;
  six checks (python suite, code wiring, fresh-init convergence, offline doctor signal, dogfood,
  contract). No live spawn in CI — consistent with T4/T5.

### Deferred / not done (no fiction)

- No registry change (`address` stage is T7); no in-session TS consumer; no perk agent definition.
- No roster/model-tier config, no `subagents.disableBuiltins`, no `.agents/`-recursion-collision
  mitigation — all land with T7, the seam's first consumer. The `.agents/skills/*/SKILL.md` collision
  (the borrow's recursive `.agents/**/*.md` scan would discover each `SKILL.md` as a stray agent) is
  **inert at T6** (no perk workflow invokes `subagent` yet) and recorded here for T7.
- Promoting the §8.3 context-isolation/handoff cluster (T4/T5/T6) into a dedicated section is a
  deferred doc refactor.

## 3. The de-risking spike (open decision #6)

**Code-inspection de-risking (done):** `pi-subagents` spawns children with `--mode json -p` and guards
all clarify UI behind `ctx.hasUI`, so it is structurally headless-safe; perk's cold door
(`perk/launch.py` `launch_stage`) passes the full env through to `pi`, the substrate the Phase-3
worker reuses.

**One-time live spike (gate-zero, run by the implementer with an API key):** from a throwaway dir with
`pi-subagents` installed, drive a read-only child headlessly and confirm a clean exit + structured
result, e.g.:

```
pi --mode json -p --tools subagent \
  'Use subagent to run scout on "list the files in this directory" with tools read,grep,find,ls'
```

**Outcome gating (locked):** if the spike **passes** (the expected result per code inspection), proceed
exactly as planned (this turn). If it **fails**, do **not** ship the borrow: fall back to T4's
in-process read-only SDK session shape for T7's `/address` classify child, drop the package wiring,
and adjust the contract note — the spine never assumes the borrow (`docs/phase-2-plan.md` T6).
