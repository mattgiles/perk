# Phase 2 · Turn 12 — Phase-2 dogfood gate: retire `rpiv-todo`, reconcile docs, record the gate

> The decision-complete plan lives on GitHub plan **#25** (`plan-body` block). This doc records the
> prior-art pass, the turn's decisions, the live dogfood runbook, and — written **after** the run —
> the as-built **outcomes**. A **checkpoint turn** (mirrors P0.T7 + `phase-0-gate.md` and P1.T6 +
> `phase-1-gate.md`): no new spine handlers.

## 1. Objective & the gate

Phase 2's closing checkpoint turn. It (1) drives perk's **full** deepened workflow on perk's own repo
as a live dogfood run, (2) **retires `@juicesharp/rpiv-todo`** now the conditional gate (perk-owned
checkpoints, T2c) has landed, (3) **reconciles** `README`/`AGENTS`(via `init`)/`contracts`/`ROADMAP`/
`index` to "Phase 2 complete," (4) confirms both new stages' (`address`, `objective-plan`) registry
state-I/O + `doors` are filled and `perk registry check` passes, and (5) ships
`scripts/verify-p2-t12.sh` (offline preconditions) + `docs/planning/phase-2-gate.md` (the visible
boundary). The live-run "what was demonstrated" + the turn's **outcomes** are written *after* the run.

The turn splits into an **offline-implementable slice** (retirement, docs, verify script, gate-record
scaffold — built + tested with no GitHub/model) and a **live operator slice** (the dogfood run,
recorded post-hoc). This mirrors P1.T6 exactly.

## 2. Prior-art pass (verified before writing)

- **All of T1–T11 landed**, each with a `phase-2-turn-N.md` "Outcomes" section + a green
  `verify-p2-t*.sh` wired into `justfile`'s `verify`.
- **The registry is already complete** — both new stages have filled I/O + `doors` (T7/T10).
  `objective-plan` (`requires: [github.objective]`, `predecessors: []`, `successors: [plan]`),
  `address` (`requires: [github.pr]`, between `submit` and `land`, `cold_remote: true`). T12 only
  **asserts**; no registry edit.
- **T2c (perk-owned checkpoints) landed** — `extension/checkpoints.ts` exports the `perk:checkpoint`
  entry (`CHECKPOINT_TYPE`), seeded from the plan body's `## Steps`, scan-after-marker rebuild,
  `ctx.hasUI`-safe. This is the **conditional gate** for retiring `rpiv-todo`; it is satisfied.
- **`rpiv-todo` retirement surface (verified live):** `perk/init.py` `BORROWED_PACKAGES`,
  `.pi/settings.json` `packages`, `scripts/verify-t7.sh` Check 2's `need` array (would FAIL unless
  updated in lockstep), `shared/contracts.md` (Checkpoints paragraph), `docs/ROADMAP.md`
  (internalization schedule + Phase-2 gate prose + borrowed-packages listing). `tests/test_init_idempotent.py`
  asserts wiring (the P2.T2a `pi-plan` precedent) but had no `rpiv-todo` assertion yet.
- **`init`'s settings convergence is additive-only** — it never removes a package no longer desired.
  The P2.T2a `pi-plan` retirement therefore required dropping it from `BORROWED_PACKAGES` **and**
  manually editing the committed `.pi/settings.json`. T12 mirrors that two-step precedent; consumer
  repos that already wired `rpiv-todo` keep it (the forward-convergence boundary — flagged in the
  gate record, **not** fixed by adding removal logic to `init`).
- **Docs drift:** `README` said "Phase 1 complete" with a pre-Phase-2 command table; `init`'s
  `POST_INIT_TEMPLATE` said the spine "is being built (Phase 1)"; `docs/index.md` had rows for
  Phase-2 turns 1, 2, 8 only.

## 3. Decisions

- **D1 — Retire `rpiv-todo` (the conditional gate is satisfied).** T2c shipped perk-owned
  checkpoints, so the `phase-2-plan.md` §T12 "conditional on T2c landing" branch resolves to *retire*.
- **D2 — Two-step retirement, no `init` removal logic.** Drop from `BORROWED_PACKAGES` + edit the
  committed `.pi/settings.json` (the P2.T2a `pi-plan` precedent). `init` stays additive-only; the
  consumer-keeps-it boundary is documented, not engineered away.
- **D3 — `verify-t7.sh` edited in lockstep.** The Phase-0 gate's Check 2 `need` array hardcodes the
  borrowed set; dropping `rpiv-todo` there is the one cross-script coupling in this turn.
- **D4 — No registry edit; assert only.** Both new stages were filled as built in T7/T10. If an
  assertion surfaces a gap, fill from the handler's reality (never author ahead).
- **D5 — Gate record + outcomes written after the live run.** `phase-2-gate.md` ships with a marked
  placeholder for the live-run subsection so the offline Check 5 passes on its "Phase 2 gate met"
  header. Mirrors `phase-1-gate.md` / P1.T6.
- **D6 — The dogfood subject is a Phase-3 objective.** Exercise the genuine differentiator (the plan
  factory) on real forward work; the factory selects the node at runtime (that selection *is* the
  demonstration); the bound is "one CI-testable seam," not a pre-decided diff.

## 4. The offline precondition gate — `scripts/verify-p2-t12.sh`

Six fully-offline checks (no network/GitHub/model), wired into `justfile`'s `verify` after
`verify-p2-t11.sh`, using the `verify-t7.sh` idioms verbatim (`set -uo pipefail`, `pass`/`bad`,
`perk_in`/`py_run` over `uv run --project`, a `mktemp -d` workspace with `trap … EXIT`):

1. **scaffold + healthy** — fresh repo → `perk init` → `perk doctor --json healthy:true`, exit 0.
2. **`rpiv-todo` retired** — absent from scaffolded `.pi/settings.json` **and** `BORROWED_PACKAGES`;
   surviving borrowed set + self entry present; `settings-wiring` ok.
3. **both new stages filled + self-check passes** — `perk registry check` exit 0; `address` +
   `objective-plan` non-empty `requires`/`reads`/`writes` + complete `doors`; graph shape holds.
4. **checkpoints own implement-progress** — `extension/checkpoints.ts` exports `CHECKPOINT_TYPE`.
5. **gate record present** — `phase-2-gate.md` asserts "Phase 2 gate met".
6. **retirement test green** — `tests/test_init_idempotent.py` passes.

## 5. Live dogfood runbook (the operator executes; reports each ▶ back)

Run live on `github.com/mattgiles/perk`, exercising the **deepened** stages the gate names. The
concrete subject: a **Phase-3 objective**. Steps marked `[cold]` are bash-scriptable cold doors;
`[pi]` are interactive `pi` sessions (mirrors P1.T6).

1. ▶ `[cold]` **Create the objective** — `perk objective create` a "**perk Phase 3 — headless worker
   + queue**" objective issue, seeding its roadmap nodes from `docs/ROADMAP.md` §"Phase 3" (the
   headless worker, the queue, migration helpers, the worker/RPC test layer, the `doctor workflow`
   CI smoke). Populates `github.objective` + sets `active_objective`. Record the objective issue #.
2. ▶ `[pi]` **`/objective-plan`** — selects the next actionable node (T9's dependency-graph `next`)
   and emits a **bounded plan** through the `plan → save` spine (the factory chooses; bound = "one
   seam, has a verify gate, not multi-day"). Optionally spawn `perk.objective-explorer` for the
   read-only exploration half. Record the plan issue #.
3. ▶ `[cold]`/`[pi]` **`perk implement`** the emitted plan; the **read-only CI executor (T5)** iterates
   Run→Report→Fix→Verify on its tests; **`/submit`** opens a draft PR with the T8a HTML-enhanced body;
   **`/ready`** flips it. Record the PR #.
4. ▶ `[pi]` **`/address`** — classifies the self-review in the spawned `perk.review-classifier` child
   (verbose feedback JSON stays out of the parent transcript), the parent fixes only actionable items,
   `resolve_review_threads` batch-resolves the threads.
5. ▶ `[cold]`/`[pi]` **`/land`** squash-merges + **mechanically marks the objective node done** +
   nudges `/objective-reconcile`; **`/objective-reconcile`** reconciles the objective's Reconcilable
   prose against the real diff (never clobbering Immutable notes). **`/learn`** captures. Record the
   merge commit + the reconciliation diff.
6. ▶ Record the issue/PR numbers, merge commit, and reconciliation diff into `phase-2-gate.md`
   §"the live run" and §6 outcomes below.

The live run is **not** CI-gated (needs live GitHub + a model); its automatable preconditions are
`verify-p2-t12.sh` + the cumulative `just verify`.

## 6. Outcomes (as built)

> _Written after the offline slice lands + the operator runs §5. Records deviations, any defects the
> dogfood surfaced (the whole point of a dogfood gate — P1.T6 surfaced two), and fix-forward work._

### Offline slice (landed)

- Retired `@juicesharp/rpiv-todo`: dropped from `perk/init.py` `BORROWED_PACKAGES` (+ comment block
  recording the P2.T12 retirement), removed from the committed `.pi/settings.json`, dropped from
  `scripts/verify-t7.sh` Check 2's `need` array, and asserted absent in `tests/test_init_idempotent.py`.
- Flipped the retirement prose in `shared/contracts.md` (Checkpoints paragraph) and `docs/ROADMAP.md`
  (internalization schedule row, Phase-2 gate prose, borrowed-packages listing).
- Reconciled `README.md` (status banner → "Phase 2 complete", command-surface table + warm-doors line,
  borrow line) and `perk/init.py` `POST_INIT_TEMPLATE` (spine closed + deepened).
- Reconciled `docs/index.md` — added rows for Phase-2 turns 3–7, 9–11 + the gate record.
- Shipped `scripts/verify-p2-t12.sh` (six offline checks) wired into `justfile`'s `verify`; scaffolded
  `docs/planning/phase-2-gate.md` with a placeholder live-run subsection.
- Confirmed the registry needed no edit — both new stages' I/O + doors were already filled (T7/T10).

### Live run

> _Pending the operator run — filled post-hoc._
