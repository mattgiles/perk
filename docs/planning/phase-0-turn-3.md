# Phase 0 · Turn 3 — State-tiering helpers (both planes), no workflow logic

Detailed execution plan for **T3** of [phase-0-plan.md](./phase-0-plan.md). T3 builds the **real
read/write helpers** for the two non-GitHub state tiers — the `.pi/workflow/` **cache** (tier-2,
both planes) and the `perk:workflow-state` **session entry** (tier-3, extension) — plus the
`run_id`/`PERK_RUN_ID` plumbing that links them. It implements the contracts T2 locked
([`shared/contracts.md`](../../shared/contracts.md) §8.1–§8.3) with **zero workflow semantics** on
top. This is the substrate T4's launch primitive and every Phase-1 stage handler will call.

> **Scope discipline.** T3 builds **state-tiering primitives only**: ULID mint/derive, the
> `.pi/workflow/` I/O (scratch, handoff, markers), the `perk:workflow-state` rebuild + claim, and
> the verified-linkage discipline. It does **not** add workflow meaning — no stage transitions, no
> `pending-learn` semantics, no `/plan-save`, no launch command (that's T4), no config/worktrees
> (T4), no gateway (T5), no `doctor` (T6). The helpers are deliberately *mechanism without
> policy*.

---

## 1. Objective & the gate

**Goal.** Land the cache- and session-tier helpers on both planes and prove the ROADMAP's
Phase-0 state proof end-to-end: a session **persists state via `appendEntry`, restores it on
reload, and both planes read/write the same local cache**, with the `run_id` round-tripping
**shell → `PERK_RUN_ID` → claim → `perk:workflow-state`**.

**Hard gate (must pass to land T3).** Via `scripts/verify-t3.sh` on a fresh clone — using two
findings that make the live round-trip *real*, not simulated:
- the TS test runner is **Node's built-in `node:test`** running `.ts` directly (Node 22.19 strips
  types with no flags, **zero new deps** — spiked green);
- `pi` exposes **`--session-dir` / `--session-id` / `--fork`**, so we can drive genuine
  cross-process reload and fork headlessly.

1. **run_id round-trip + reload (2 real `pi` processes).** `perk state new-run` mints a ULID and
   writes `handoff/<run_id>.json`; **P1** (`PERK_RUN_ID` set) claims it — `appendEntry` →
   read-back via `getBranch()` → mark handoff `consumed: true`; **P2** resumes the *same* session
   with **`PERK_RUN_ID` unset** and restores the `run_id` **from the session, not the env**.
2. **fork derives a child id (1 real `pi --fork`).** Forking P1's session mints
   `<run_id>.<n>` (child-scoped), recording the parent as predecessor.
3. **both planes share `.pi/workflow/`.** Python writes the handoff (`perk/cache.py`), the
   extension reads + consumes it (`extension/cache.ts`) and sets a marker the Python helper then
   sees — bidirectional cross-plane cache I/O.
4. **deterministic unit tests.** `pytest` (run_id mint/derive/parse; cache scratch/handoff/marker
   round-trips; idempotent consume) **and** `node --test extension/*.test.ts` (LWW rebuild incl.
   out-of-order + non-perk entries ignored; the **`/tree` re-scan**; claim idempotency-on-reload;
   fork-derive sibling increment).

`/tree` navigation is the one mechanic not headlessly scriptable (it's interactive), so it is
discharged by the **unit test** of the rebuild-on-`session_tree` path; everything else is a real
process round-trip. `just verify` runs t1 + t2 + **t3**; `just test` gains `node --test`.

---

## 2. Grounding & doc lineage (what governs T3)

T3 is the first turn that writes *behavioral* code against the contracts, so the lineage is
load-bearing:

- **The contracts are already locked (T2).** `contracts.md` §8.1 (`.pi/workflow/` layout), §8.2
  (`PERK_RUN_ID` protocol), §8.3 (`perk:workflow-state` schema) are the exact target. T3
  implements them verbatim; any change here is a *contract* change (amend `contracts.md` in the
  same PR), not a silent drift. The registry's `run_id` policy (`warm: keep`, `cold_*: mint`) and
  the `cache.*` / `session.workflow-state` vocabulary are the T2-locked source of truth.
- **Source decisions:** `Q1` (single `perk:workflow-state` entry, per-field LWW), `Q2`
  (`.pi/workflow/` layout + ULID `run_id` + `PERK_RUN_ID` channel), `Q3` (tiered verified
  linkage). These were resolved in [foundation-open-questions.md](../foundation-open-questions.md).
- **Pi mechanics (confirmed against pi-best-practices.md §3–§4, §8 and the installed SDK docs):**
  `pi.appendEntry(customType, data)` persists a custom entry that does **not** enter LLM context;
  rebuild by scanning `ctx.sessionManager.getBranch()` for
  `entry.type === "custom" && entry.customType === "perk:workflow-state"`; `session_start` carries
  `event.reason ∈ {startup, reload, new, resume, fork}` and `event.previousSessionFile`;
  `session_tree` carries `{newLeafId, oldLeafId}`; `session_before_fork` carries `{entryId,
  position}`.
- **Repo convention now in force (post-T2 dignified pass):** **no `from __future__ import
  annotations`** anywhere (Python floor is 3.13; PEP 649 defers natively). New Python modules omit
  it. dignified-python remains the Python standard (LBYL, modern typing, `encoding="utf-8"`,
  `click.echo` via `output.py`, `UserFacingCliError` only at the CLI boundary).

---

## 3. Revisions & findings folded in (from the prior-art + spike pass)

1. **Reject erk's silent session-id fallback.** erk's `get_or_generate_session_id(cwd)` *generates
   a new id if none is found* — a silent fallback. perk's `run_id` is **established before consume**
   (Q3): a missing/mismatched handoff on claim is a **hard, actionable error**, never a silent
   `pass` or a fresh-mint. The verified-linkage helper exists precisely to kill that failure mode.
2. **ULID over env, not session-id over CLI-flags/hook-reminders.** erk threaded the Claude
   session-id through `--session-id` options and `📌 session:` hook-reminder parsing; perk mints a
   **ULID** in the CLI and passes it via the **`PERK_RUN_ID` env channel** (the only clean launch
   channel — an initial message would pollute LLM context). ULID is canonical (decision below):
   time-sortable + self-dating ⇒ GC-by-id and chronological ordering for free.
3. **Mirror erk's free-function cache style.** erk's `scratch.py`/`markers.py` are free functions
   over **explicit paths** with **named constants** (`PENDING_LEARN_MARKER`), markers as
   existence-only files. T3 mirrors that style (free functions over `(root, run_id)`), building
   **only the primitives** — no `pending-learn` *semantics* (that's Phase-1 workflow).
4. **TS test runner = Node built-in `node:test`** (spiked: Node 22.19 runs `.ts` test files with
   **no flags and zero new deps** via native type-stripping). No `tsx`/`vitest`.
5. **The gate is real, not simulated.** `pi --session-dir`/`--session-id` enable a true
   **2-process reload**; `pi --fork` enables a true **fork** test. Only `/tree` stays a unit test
   (interactive-only). This upgrades the gate from "live sentinel + unit tests" to "real reload +
   real fork + unit tests."
6. **Custom entries vs tool-result `details` — the forking-safe nuance** (pi-best-practices
   §4/§13). The Pi reference guarantees **tool-result `details`** survive forking; it makes **no**
   such guarantee for `appendEntry` custom entries. `perk:workflow-state` deliberately uses
   `appendEntry` (it is not a tool's output, §8.3), so **fork-child derivation must not assume the
   parent's entry survives into the child's `getBranch()`** — the spike verifies that and the code
   falls back to `event.previousSessionFile` (§8.3). Relatedly, the verified-linkage hard error must
   surface **headless-safe** (§8.1), not as a bare `throw` from `session_start`.

---

## 4. Repo additions (end of T3)

```
perk/
├── perk/
│   ├── run_id.py             # NEW — ULID mint / derive-child / parse (CLI is the only minter)
│   ├── cache.py              # NEW — .pi/workflow/ I/O: scratch, handoff, markers (free functions)
│   └── cli/
│       ├── cli.py            # (modified: register the `state` group)
│       └── commands/
│           └── state_cmd.py   # NEW — `perk state` group: new-run, show (dev/CI/doctor surface)
├── extension/
│   ├── cache.ts             # NEW — twin of cache.py (handoff read/consume, markers, scratch)
│   ├── workflowState.ts     # NEW — rebuildWorkflowState (LWW) + claimRunId + deriveForkRunId
│   ├── workflowState.test.ts # NEW — node:test (rebuild/claim/fork-derive)
│   ├── cache.test.ts        # NEW — node:test (cache round-trips on a temp dir)
│   └── index.ts             # (modified: claim on session_start; rebuild on session_start+session_tree;
│                            #             fork handling; selfcheck sentinel emits the rebuilt state)
├── tests/
│   ├── test_run_id.py       # NEW
│   └── test_cache.py        # NEW
├── scripts/
│   └── verify-t3.sh         # NEW — the T3 hard gate (checks 1–4)
├── pyproject.toml           # (modified: add `python-ulid` runtime dep)
└── justfile                 # (modified: `test` adds `node --test`; `verify` adds t3)
```

`package.json` gains **no** runtime dep (`node:test` is built-in; only the CLI mints ULIDs, so the
extension needs no ULID lib). New Python state code bundles nothing new into `shared/`; the
contracts it implements already shipped in T2.

---

## 5. Locked choices (the six decisions + their easy-to-forget details)

| Choice | Locked value | Why / easy-to-forget detail |
|---|---|---|
| **run_id format** | **canonical ULID** via `python-ulid` (runtime dep) | Import is `from ulid import ULID` (package **`python-ulid`**, *not* `ulid-py` — they both import as `ulid` and conflict; pin the right one). `str(ULID())` → 26-char Crockford base32. Time-sortable + self-dating ⇒ GC/order for free; keeps `contracts.md` §8.2 verbatim. **Only the CLI mints**; the extension never mints (warm keeps, cold mints in the CLI, fork derives-by-suffix). |
| **ULID + ty** | rely on the package's own `py.typed` | `python-ulid` ships inline types; ty resolves it with **no** stubs (same posture as `yaml` in T2). If it ever fails, add a typed shim — never a blanket ignore. |
| **`perk state` visibility** | a **normal, visible** command group (not hidden) | Dev/CI/doctor surface (like `perk registry`), **not an agent affordance** — the agent reads state via an extension tool (Phase 1+), never by shelling `perk`. Visible by default; can graduate or hide later. |
| **`perk state` surface** | `new-run`, `show` (lean) | `new-run` mints + writes the handoff and prints the bare run_id on **stdout** (so `RID=$(perk state new-run …)` captures it); human text to **stderr**. `show` inspects a run (handoff + markers + scratch) — a dev/doctor convenience. No speculative `cache-put`/`marker` commands (dignified: no unused API). |
| **fork depth** | **implement now**: detect + derive `<run_id>.<n>` | `n` = max existing sibling under `scratch/runs/` + 1 (else 1). It's the run_id state-tiering mechanic (not workflow), and `--fork` makes it e2e-testable. No fork-specific *workflow* behavior. Child records its predecessor. |
| **mark consumed** | write **`consumed: true`** into the handoff JSON; **keep the file** | Primary idempotency is `getBranch()` (run_id already in rebuilt state ⇒ skip, don't touch the file). The flag is audit + a future `doctor` check + the *consume* half of establish-before-consume — set **only after** read-back confirms the entry persisted. Deletion (the erk GC pain) is rejected; perk-owned GC prunes later. |
| **TS test runner** | Node built-in `node:test`, run `.ts` directly | `node --test extension/*.test.ts` — zero deps, native type-stripping. Test files must use `import type` for type-only imports (matches `verbatimModuleSyntax`) and avoid un-strippable TS (enums/namespaces/param-properties). Folded into `just test`; tsc + biome still cover `*.test.ts`. |
| **Gate shape** | real 2-process reload + real fork + unit `/tree` | `appendEntry` needs a **real session** to persist into ⇒ the gate launches `pi` **with `--session-dir`/`--session-id`** (NOT `--no-session`, unlike the T1/T2 sentinel). Reload restores from the **session**, with `PERK_RUN_ID` **unset** in P2. |
| **Verify wiring** | add `scripts/verify-t3.sh`; `just verify` runs t1 + t2 + t3 | Gates are cumulative; T1 and T2 must keep passing. |

---

## 6. Work breakdown (ordered)

A short **de-risking spike** opens T3 — the live `pi` reload/fork mechanics carry the only real
uncertainty.

### T3.spike — the live-`pi` reload/fork harness (throwaway)
Before building real structure, prove headlessly: (a) `pi --session-dir T --session-id S -p …`
**creates a session** and `appendEntry` from an extension **persists to the JSONL** (and the entry
survives process exit); (b) re-running with the same `--session-id` **resumes** and `getBranch()`
returns the prior custom entry (with `PERK_RUN_ID` unset); (c) **decision fork** — does
`pi --fork <file> -p …` fire `session_start` with `reason: "fork"` **and carry the parent's
`appendEntry` custom entry into the child's `getBranch()`?** pi-best-practices §4 only guarantees
tool-result `details` survive forking, *not* custom entries — so if the parent's
`perk:workflow-state` is **not** in the child branch, fork derivation reads the parent `run_id`
from **`event.previousSessionFile`** instead (§8.3); (d) what **throwing from a `session_start`
handler** actually does headlessly (does it crash/abort the session, or is it caught?) — informs
how the verified-linkage hard error surfaces (§8.1).
*Pin these details here:* the fork-target reference form (prefer the **session file path** under
`--session-dir` over a partial id), whether `appendEntry` flushes before the watchdog kill (give P1
enough time; only `pi` is watchdog-wrapped — macOS has no `timeout`), the exact `pi_session_id`
accessor (`ctx.sessionManager.getSessionFile()` stem vs a UUID getter), **and the fork
custom-entry-survival + headless-throw answers above**.
*Accept:* the behaviors observed (incl. the fork-survival path + the headless-throw behavior);
carry the working invocations into `verify-t3.sh`.

### T3.a — Python: `perk/run_id.py`
`mint() -> str` (`str(ULID())`); `derive_child(parent, n) -> str` (`f"{parent}.{n}"`);
`base_ulid(run_id) -> str` (strip `.n` suffixes → the root 26 chars); `timestamp(run_id) ->
datetime` (`ULID.from_str(base).datetime`); `is_run_id(s) -> bool` (parse-validates the base).
LBYL, fully typed.
*Accept:* `test_run_id.py` — mint is unique + parseable + sortable-by-time; derive/base/timestamp
round-trip; `is_run_id` rejects junk.

### T3.b — Python: `perk/cache.py`
Free functions over `(root: Path, …)` implementing §8.1:
`workflow_dir(root)`, `ensure_layout(root)` (idempotent mkdir of `plans/ scratch/runs/ handoff/
markers/`), scratch (`run_scratch_dir`, `write_scratch`, `read_scratch`), handoff
(`handoff_path`, `write_handoff(root, run_id, data)`, `read_handoff(root, run_id) -> dict | None`,
`mark_handoff_consumed(root, run_id, *, pi_session_id)`), markers (`set_marker`, `has_marker`,
`clear_marker`). JSON with `encoding="utf-8"`. Markers are existence-only files (erk style).
*Accept:* `test_cache.py` — scratch/handoff/marker round-trips; `read_handoff` returns `None` when
absent (not an exception); `mark_handoff_consumed` is idempotent and sets `consumed: true`.

### T3.c — Python: `perk state` group (`perk/cli/commands/state_cmd.py` + register in `cli.py`)
`perk state new-run [--handoff <json|@file>]` → mint a run_id, `ensure_layout`, write the handoff
(defaulting `{run_id}` plus any provided fields), print the bare run_id on **stdout**.
`perk state show [--run-id <id>]` → with an id, dump that run's handoff (incl. `consumed`),
markers, and scratch listing; without, list known runs. Thin adapters over `run_id.py`/`cache.py`,
per [python-cli-guidelines.md](../python-cli-guidelines.md) (human → stderr via `user_output`,
data → stdout via `machine_output`).
*Accept:* `RID=$(perk state new-run --handoff '{"mode":"read-only"}')` prints a ULID and writes
`handoff/<RID>.json`.

### T3.d — TS: `extension/cache.ts`
Twin of `cache.py` over `ctx.cwd`: `workflowDir(cwd)`, `handoffPath`, `readHandoff(cwd, runId)`,
`markHandoffConsumed(cwd, runId, { piSessionId })`, marker `setMarker/hasMarker/clearMarker`,
scratch read/write. Same file shapes as the Python side (the cross-plane contract is the *files*,
not a shared module).
*Accept:* `cache.test.ts` — round-trips on a temp dir; reads a handoff the Python side could have
written (and vice-versa, asserted live in gate check 3).

### T3.e — TS: `extension/workflowState.ts`
- `WORKFLOW_STATE_TYPE = "perk:workflow-state"`.
- `rebuildWorkflowState(entries) -> WorkflowState` — per-field LWW over entries whose
  `type === "custom" && customType === WORKFLOW_STATE_TYPE`; ignore everything else; later writes
  win per field (undefined fields don't clobber).
- `claimRunId(pi, ctx) -> WorkflowState` — the **verified-linkage claim** (§8): rebuild from
  `getBranch()`; if `run_id` already present → return (idempotent reload, no file touch); else read
  `process.env.PERK_RUN_ID` (absent → return unchanged), `readHandoff`, `appendEntry` the state,
  **read-back** via `getBranch()` (mismatch → raise a **headless-safe** hard error, §8.1), then
  `markHandoffConsumed`.
- `deriveForkRunId(parentRunId, cwd) -> string` — `derive_child` twin: scan `scratch/runs/` for
  existing `<parentRunId>.<k>`, return `<parentRunId>.<max+1 || 1>`.
*Accept:* `workflowState.test.ts` — LWW (incl. out-of-order, non-perk ignored); claim idempotency
when run_id present; fork-derive sibling increment.

### T3.f — TS: wire `extension/index.ts`
On `session_start`: if `event.reason === "fork"` → rebuild, read the parent `run_id` (from the
child branch if forks carry custom entries, else from `event.previousSessionFile` — §8.3), derive
the child id, `appendEntry` the child state (with `predecessor`), ensure the child scratch dir;
else → `claimRunId`. **On both `session_start` and `session_tree`** → re-`rebuildWorkflowState` (skipping
`session_tree` is *the* stale-state bug, §8.3). Extend the env-gated `PERK_SELFCHECK` sentinel to
emit the rebuilt `run_id`, `mode`, the **source** (`env` vs `session` vs `fork`), and any
`predecessor`. Keep `ctx.hasUI` discipline (the sentinel path is env-gated, not UI).
*Accept:* gate checks 1–3.

### T3.g — Deps, tests, verify, just
`uv add python-ulid`; `uv lock`/`uv sync`. Write `tests/test_run_id.py`, `tests/test_cache.py`,
`extension/*.test.ts`, and `scripts/verify-t3.sh` (checks 1–4). `just test` → `pytest` **and**
`node --test extension/*.test.ts`; `just verify` → t1 + t2 + t3. Keep `ruff`/`ty`/`biome`/`tsc`
green.
*Accept:* the whole T3 gate is one command; `just ci` stays green.

---

## 7. The state-tiering API (the locked surface)

### 7.1 `run_id` rules (Q2)
- **One minter — the CLI.** `mint()` returns a fresh ULID. The extension **never** mints.
- **Warm keeps / cold mints / fork derives.** A warm in-session transition keeps the id (realized
  in T3 as **reload** — the id is restored from the session). A cold relaunch mints a new ULID in
  the CLI **recording its predecessor**. A fork **derives** `<run_id>.<n>` (suffix, not a new
  ULID) so the child's scratch is isolated yet traceable.
- **The id is the join key** across launcher → `handoff/<run_id>.json` → the session's
  `perk:workflow-state` → `scratch/runs/<run_id>/` (§8.2). Never key on the Pi session id (it does
  not exist at cold-door launch).

### 7.2 `.pi/workflow/` cache I/O (§8.1) — both planes, same files
| concern | files | key helpers (Python ‖ TS) |
|---|---|---|
| scratch | `scratch/runs/<run_id>/<name>` | `write_scratch`/`read_scratch` ‖ `writeScratch`/`readScratch` |
| handoff | `handoff/<run_id>.json` | `write_handoff`/`read_handoff`/`mark_handoff_consumed` ‖ `readHandoff`/`markHandoffConsumed` |
| markers | `markers/<name>` (existence-only) | `set_marker`/`has_marker`/`clear_marker` ‖ `setMarker`/`hasMarker`/`clearMarker` |
| plans | `plans/…` | (paths only in T3; population is Phase 1) |

The **handoff** is the only blob the CLI writes for the extension to claim; in T3 it carries a
minimal `{run_id, mode?}` (full payload — `active_plan_ref` etc. — is Phase 1). `read_handoff`
returns `None` (not an exception) when absent — absence is a normal, branchable condition (LBYL).

### 7.3 `perk:workflow-state` (§8.3) — extension-owned tier-3
- **Written only by the extension**, via `pi.appendEntry("perk:workflow-state", data)` — the
  *custom-entry* channel. (The other Pi channel, tool-result `details`, is for state that **is** a
  tool's output; only `details` is documented forking-safe, which shapes fork handling — §8.3.)
  Python never writes this tier.
- **Fields (per-field LWW):** `run_id`, `pi_session_id`, `mode`, `active_plan_ref` (null in T3),
  `active_objective` (null; Phase 2), `last_review_batch` (null; Phase 2). T3 actively sets
  `run_id`, `pi_session_id`, `mode`.
- **Rebuild** scans `getBranch()` (the *current branch*, not `getEntries()` which spans all
  branches) on **`session_start` and `session_tree`**.

---

## 8. The load-bearing algorithms (claim / rebuild / fork)

### 8.1 Claim on `session_start` (the verified-linkage sequence, Q3)
```
state = rebuildWorkflowState(getBranch())
if state.run_id is set:                       # reload / re-entry → already claimed
    return state                              #   idempotent: do NOT re-read or re-consume
rid = process.env.PERK_RUN_ID
if not rid: return state                      # warm-in-process or non-perk launch → nothing to claim
handoff = readHandoff(cwd, rid)
if handoff is None or handoff.run_id != rid:  # establish-before-consume (Q3 STRICT)
    throw hard, actionable error              #   NEVER a silent pass or a fresh-mint (anti-erk)
appendEntry({ run_id: rid, pi_session_id: <session handle>, mode: handoff.mode })
if rebuildWorkflowState(getBranch()).run_id != rid:   # READ-BACK before consume
    throw hard, actionable error
markHandoffConsumed(cwd, rid, { piSessionId })        # consume only after the link is durable
```
- **Tiers (Q3):** `run_id`, the `run_id ↔ pi_session_id` mapping, and (Phase 1) `active_plan_ref`
  are **strict** — durable, cross-process ⇒ read-back + correct ordering. Purely transient fields
  cheaply reconstructable next `session_start`/`session_tree` (e.g. `mode`) are
  **best-effort-with-logging** — a failure is **logged, never silently swallowed**.
- **Headless-safe failure (pi-best-practices §7/§11):** the two hard errors above must **not** be
  a bare `throw` from `session_start` (it can destabilize a headless session, e.g. the worker).
  Surface them loudly through a **non-UI channel** — `ctx.ui.notify` *only if* `ctx.hasUI`, **plus**
  a stderr line / an error marker the CLI/worker can observe — and leave the workflow-state
  **unclaimed** (do **not** mark the handoff consumed). The spike pins what a thrown `session_start`
  error actually does.

### 8.2 Rebuild (the non-negotiable discipline, §8.3)
- Scan `getBranch()` for `type === "custom" && customType === "perk:workflow-state"`; apply
  **per-field LWW** (two tools writing different fields in one turn must not clobber each other).
- Run it on **`session_start` AND `session_tree`** — skipping the latter is the bug that makes
  state stale after the user navigates the tree.
- **Plan-mode subtlety (documented, lands Phase 1):** when rebuilding state tied to a *current
  execution*, only re-scan entries **after** the marker that began it, so a previous execution's
  stale fields don't resurrect. T3's rebuild is whole-branch (no execution markers exist yet);
  the hook is noted so Phase 1 adds the "after-marker" filter rather than rediscovering it.

### 8.3 Fork vs `/tree` (the easy-to-get-wrong distinction, §8.2)
- **Fork / clone / `newSession({parentSession})`** → a **new session file**. Derive the child id in
  **`session_start` with `reason: "fork"`** — *not* in `session_before_fork`, which is a **cancel**
  gate (`{cancel:true}`) that fires *before the new session exists* (no `getBranch()` yet)
  (pi-best-practices §3/§7). Read the parent `run_id` and **derive `<run_id>.<n>`** — *do not*
  blindly inherit `PERK_RUN_ID` (that would hand the parent's id to the child).
  - **Parent-`run_id` source (spike-verified, with fallback):** the Pi reference only guarantees
    tool-result **`details`** survive forking — it makes **no** such guarantee for `appendEntry`
    custom entries (pi-best-practices §4). So **if** the child's `getBranch()` carries the parent's
    `perk:workflow-state`, read it there; **else** fall back to scanning **`event.previousSessionFile`**
    (present on `reason: "fork"`) for the parent's last `run_id`. The spike decides which path is
    live; the fallback is wired either way so fork derivation never silently mis-keys the child.
- **`/tree`** branches **in place** (same file/UUID/process) → `PERK_RUN_ID` survives and the
  `run_id` stays **stable**; only the rebuild re-runs (on `session_tree`).

---

## 9. The unit-test matrix (what each test asserts)

**Python — `tests/test_run_id.py`:** mint returns a valid, unique, time-sortable ULID;
`derive_child`/`base_ulid` round-trip (`base_ulid(derive_child(u, 3)) == u`); `timestamp` parses
the embedded time; `is_run_id` accepts a real id and rejects junk/empty.

**Python — `tests/test_cache.py`:** `ensure_layout` is idempotent; scratch write→read round-trip;
handoff write→read round-trip; `read_handoff` on a missing file returns `None`;
`mark_handoff_consumed` sets `consumed: true` and re-marking is a no-op; marker set→has→clear.

**TS — `extension/workflowState.test.ts`:**
- LWW: later per-field writes win; non-`perk:workflow-state` custom entries are ignored;
  out-of-order/interleaved entries resolve per-field correctly; `undefined` fields don't clobber.
- `/tree` re-scan: rebuilding over a branch that gained an entry reflects the new field
  (simulating the `session_tree` re-run).
- claim idempotency: when the rebuilt state already has `run_id`, the claim is a pure no-op (no
  handoff read/consume).
- fork-derive: `deriveForkRunId` returns `<id>.1` with no siblings and `<id>.(max+1)` with
  existing `<id>.k` dirs.

**TS — `extension/cache.test.ts`:** handoff and marker round-trips on a temp `cwd`; a handoff
written in the shape `cache.py` produces is read correctly (and the consume flag it writes is
visible to a second read).

---

## 10. Acceptance gate — concrete, runnable checks (`scripts/verify-t3.sh`)

Reuses T1/T2's harness conventions: **only `pi` is watchdog-wrapped** (macOS has no `timeout`);
artifact/file membership via Python, never `grep` under `pipefail`; `uv run --project` for all
Python; env-gated `PERK_SELFCHECK` sentinel.

1. **run_id round-trip + reload (2 processes).**
   - `RID=$(perk state new-run --handoff '{"mode":"read-only"}')` → asserts `handoff/<RID>.json`
     exists and is **not** yet consumed.
   - **P1:** `PERK_RUN_ID=$RID PERK_SELFCHECK=1 pi --session-dir $T/sessions --session-id perk-t3
     -e ./extension/index.ts -p --no-tools "reply ok"`. After: assert (a) the handoff is now
     `consumed: true`; (b) the session JSONL under `$T/sessions` contains a `custom` entry with
     `customType: "perk:workflow-state"` and `data.run_id == $RID` (scan via Python); (c) the
     sentinel reports `run_id=$RID source=env`.
   - **P2 (reload, `PERK_RUN_ID` UNSET):** `PERK_SELFCHECK=1 pi --session-dir $T/sessions
     --session-id perk-t3 -e … -p --no-tools "reply ok"`. Assert the sentinel reports
     `run_id=$RID source=session` — the id was **restored from the session, not the env**, and the
     handoff was **not** re-consumed.
2. **fork derives a child id.** `PERK_SELFCHECK=1 pi --fork <P1 session file> --session-dir
   $T/sessions -e … -p --no-tools "reply ok"` (`PERK_RUN_ID` unset). Assert the sentinel reports
   `run_id=$RID.<n>` with `source=fork predecessor=$RID`, and `scratch/runs/$RID.<n>/` exists.
3. **both planes share `.pi/workflow/`.** From checks 1–2: the Python-written handoff was
   read+consumed by the TS plane (proven by the `consumed: true` flag the script re-reads), and the
   extension set a marker via `cache.ts` that the Python helper sees —
   `uv run python -c "from perk.cache import has_marker; assert has_marker(root, '<sentinel>')"`.
   Bidirectional cross-plane cache I/O.
4. **unit tests.** `uv run pytest tests/test_run_id.py tests/test_cache.py -q` **and**
   `node --test extension/workflowState.test.ts extension/cache.test.ts` both pass.

`just verify` runs `verify-t1.sh` + `verify-t2.sh` + `verify-t3.sh`; `just ci` (ruff + biome + ty +
tsc + **pytest** + **node --test**) stays green.

---

## 11. Risks & mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| `appendEntry` doesn't flush before the watchdog kills `pi` (entry missing from JSONL) | med | the spike pins flush timing; give P1 a generous watchdog window + short prompt; if flakey, the extension can `getSessionFile()` and confirm the write, or the script polls the JSONL briefly |
| Fork-target reference form (`--fork <id>` vs `<path>`) is finicky | med | spike it; prefer the **session file path** under `--session-dir` (deterministic) over a partial id |
| `appendEntry` custom entries may **not** survive a fork into the child's `getBranch()` (only tool-result `details` are documented forking-safe, pi-bp §4) | med | spike-verify; fall back to scanning `event.previousSessionFile` for the parent `run_id` (§8.3) |
| A hard linkage error **thrown** from `session_start` destabilizes a **headless** session | med | surface headless-safe — `notify` only if `hasUI` + stderr/error-marker, not a bare `throw` (§8.1); spike what throwing does |
| Wrong `python-ulid` package (`ulid-py` vs `python-ulid`) — both import `ulid` | low-med | pin **`python-ulid`** explicitly; `test_run_id.py` asserts the 26-char Crockford form + sortability, catching the wrong lib |
| `node --test` type-stripping chokes on a TS construct | low | keep test files plain (`import type`, no enums/namespaces); spiked green on 22.19 |
| Reload restores from the **env** instead of the session (false green) | med | P2 **unsets `PERK_RUN_ID`** and the sentinel reports `source`; a `source=env` in P2 fails the gate |
| `pi_session_id` accessor differs from assumption | low | pinned in the spike; stored value is opaque to T3 (only used as a handle later) |
| `getEntries()` used instead of `getBranch()` (spans all branches) | low | §7.3/§8.2 mandate `getBranch()`; the `/tree` unit test would catch cross-branch bleed |

---

## 12. Explicitly out of scope for T3 (pointers)

- **The launch *command*** (`exec pi` priming a stage's worktree/mode/door + setting
  `PERK_RUN_ID`) — **T4**. T3 provides the *helpers* and a `perk state new-run` dev wrapper; the
  gate sets `PERK_RUN_ID` itself to stand in for T4's launcher.
- **Cold-mint-with-predecessor across a real relaunch** — the *helper* (`derive`/predecessor
  recording) is built and the fork path exercises predecessor recording; the **CLI relaunch** that
  cold-mints lands with T4's launch primitive.
- **Workflow semantics** — `pending-learn` meaning, stage transitions, plan-mode markers, the
  "after-marker" rebuild filter — Phase 1+ (T3 builds only the marker/rebuild *primitives*).
- **`active_plan_ref` / `active_objective` / `last_review_batch` population** — Phase 1/2 (null in
  T3; the fields exist in the schema).
- **Cache **GC** / prune command** — surfaced later as a `doctor` check (T6) + prune; T3 only
  writes `consumed: true` so GC has a signal.
- **In-process session-swap rebinding** (`session.bindExtensions({})` + re-subscribing after a
  runtime session replacement, pi-best-practices §2/§13#11) — **not a T3 concern**: T3's reload and
  fork are *separate `pi` processes*, each with a clean `session_start` + fresh extension bind. The
  rebind discipline lands with **T4's launch / the Phase-3 SDK worker**.
- **Config, worktrees, subcommand generation** — T4. **Gateway** — T5. **`doctor`** — T6.

## 13. Open questions to settle during T3 (lean answers)

1. **`pi_session_id` source** — `getSessionFile()` stem vs a dedicated UUID getter. *(Lean: use
   whatever the SDK exposes as the stable session handle; it's opaque to T3.)* Pin in the spike.
2. **`perk state new-run` output** — bare id vs `PERK_RUN_ID=<id>` vs `export …`. *(Lean: bare id
   on stdout — most composable: `RID=$(perk state new-run)`.)*
3. **Handoff minimal shape in T3** — `{run_id}` only vs `{run_id, mode}`. *(Lean: `{run_id, mode}`
   so the claim has a non-trivial field to carry into `perk:workflow-state`.)*
4. **`derive_child` of a child** (`<ulid>.<a>.<b>`) — allow nested forks now? *(Lean: yes, it falls
   out of suffix-append + `base_ulid` stripping all `.n`; a unit test covers one level, nesting is
   free.)*

## 14. Definition of done

The four hard-gate checks in §10 pass via `scripts/verify-t3.sh` on a fresh clone; `pytest`
(run_id + cache) and `node --test` (rebuild/claim/fork) pass; a session **persists
`perk:workflow-state` via `appendEntry` and restores it on a real reload** with `PERK_RUN_ID`
unset; **fork derives `<run_id>.<n>`**; both planes provably read/write the same `.pi/workflow/`
files; `just ci` and `just verify` (t1 + t2 + t3) are green. T3 lands; **T4 can build the launch
primitive on `perk state`'s helpers (closing the shell → `PERK_RUN_ID` → claim loop) and every
Phase-1 stage handler has its cache + session-state substrate.**

---

## 15. T3 outcomes (recorded after implementation)

**Status: implemented; T3 hard gate ALL PASS; T1 + T2 gates still PASS; `just ci` green.**

**Built (as planned):** `perk/run_id.py` (mint/derive_child/base_ulid/is_run_id/timestamp);
`perk/cache.py` (ensure_layout, scratch, handoff write/read/mark-consumed, markers);
`perk/cli/commands/state_cmd.py` (`perk state new-run` / `show`, registered in `cli.py`);
`extension/cache.ts` (cache twin), `extension/workflowState.ts` (rebuild + decideClaim +
deriveForkRunId), wired `extension/index.ts` (claim on `session_start`, rebuild on
`session_start` AND `session_tree`, fork handling, selfcheck sentinel); `tests/test_run_id.py`,
`tests/test_cache.py`, `extension/workflowState.test.ts`, `extension/cache.test.ts`;
`scripts/verify-t3.sh`; `just test` now runs `node --test`; `just verify` runs t1+t2+t3.

**Gate results:** all four checks PASS — (1) `perk state new-run` mints a ULID + fresh handoff;
P1 claims (`source=env`, handoff `consumed`, entry persisted to the session JSONL); P2 **reloads
with `PERK_RUN_ID` unset and restores `run_id` from the session** (`source=session`); (2) a real
`pi --fork` derives `<run_id>.1` (predecessor recorded, child scratch created); (3) the
Python-written handoff was consumed by the TS plane and a TS-written marker is visible to the
Python cache helper; (4) `pytest` (run_id + cache, 11) and `node --test` (11) pass. Full suite:
**27 pytest + 11 node:test**.

**Spike findings that shaped the build (important — some supersede the plan body):**
- **Fork detection is by the `run_id ↔ pi_session_id` mapping, NOT `event.reason`.** A headless
  `pi --fork <file>` fires `session_start` with **`reason: "startup"`** (not `"fork"`) and
  `previousSessionFile: null` — so the planned `reason === "fork"` test (§6.f/§8.3) is unreliable.
  Instead `decideClaim` compares the rebuilt entry's `pi_session_id` to the **current** session
  (basename of `getSessionFile()`): equal ⇒ reload (keep), different ⇒ fork (derive child). This is
  exactly why the contract stores `pi_session_id`, and it covers **both** interactive `/fork` and
  headless `--fork`.
- **`appendEntry` custom entries DO survive a fork** into the child's `getBranch()` (the
  decision-fork from the pi-best-practices §4 review resolved in favor of survival) — so the
  `event.previousSessionFile` **fallback was not needed** and is not wired. (`previousSessionFile`
  was `null` for CLI `--fork` anyway.)
- **A `throw` from `session_start` is caught + logged by pi** (`Extension error (…): <msg>` to
  stderr) and is **non-fatal** (rc=0, the session continues). So the headless-safe linkage error is
  implemented as `console.error` + `notify`-if-`hasUI` + **leave unclaimed** (no `throw` needed);
  the un-consumed handoff is the durable, observable failure signal.
- **The in-handler read-back works:** `getBranch()` reflects the just-`appendEntry`'d entry
  synchronously, so establish-before-consume is a real same-tick check (P1 consumed the handoff).
- **Session file naming:** `<session-dir>/<ISO-timestamp>_<id-or-uuid>.jsonl`; reload yields a
  byte-identical path; a fork gets a new UUID-named file. `pi_session_id` is stored as the
  **basename** (location-independent; the fork discriminator).

**Contract reconciliation (`shared/contracts.md`, per §2's "amend the contract, don't drift").**
The spike findings changed contract *behavior*, so the canonical spec was amended in the same turn:
§8.2's fork bullet now describes the **`run_id ↔ pi_session_id` discriminator** (replacing the
`parentSession`/`session_before_fork` detection, which is unreliable for headless `pi --fork`); §8.3
gained a **`predecessor`** field and `pi_session_id`'s type was corrected from "(UUID)" to the
**session-file basename** (the fork discriminator / resume handle). `registry.yaml` and the other
contracts are unchanged.

**Deps locked:** **`python-ulid>=2.7,<3`** (Python runtime). `python-ulid==3.x` has a packaging
bug — it imports `from typing_extensions import Self` unconditionally but declares no
`typing_extensions` dependency, so it fails to import on a clean env; `2.7.0` is clean on 3.13 and
ty resolves it from its own `py.typed`. **No new TS runtime/dev dep** (`node:test` is built-in).

**Toolchain notes (easy-to-forget, for later turns):**
- **`node --test` requires explicit `.ts` import extensions** (its native type-stripping does not
  resolve `./cache`). jiti (pi's loader) and tsc both accept `.ts` imports, so the extension
  standardized on **explicit `.ts` extensions** + `allowImportingTsExtensions: true` in
  `tsconfig.json`. New `extension/*.ts` must import siblings as `./x.ts`.
- **Exclude `*.test.ts` from the npm tarball via a negated `files` glob** (`"!extension/**/*.test.ts"`).
  A root `.npmignore` does **not** override a directory listed in `files`; the negated `files`
  entry does. (Verified `npm pack --dry-run`: 5 source files ship, 0 test files; `shared/` intact.)
- The T1/T2 `.perk-loaded` sentinel line is unchanged; T3 adds a separate `.perk-t3.json` sentinel
  (source/run_id/mode/predecessor/pi_session_id) so the gate parses state without disturbing the
  T1/T2 checks.

**Still deferred (unchanged):** the launch *command* that sets `PERK_RUN_ID` + cold-mints across a
real relaunch (T4); workflow semantics + the "after-marker" rebuild filter (Phase 1); plan-ref /
objective / review-batch population (Phase 1/2); cache GC/prune (T6 `doctor`); in-process
session-swap rebinding (T4 / Phase-3 worker).

**Verify:** `bash scripts/verify-t3.sh` (4/4 PASS), `just verify` (t1+t2+t3 ALL PASS),
`just ci` green (ruff + biome + ty + tsc + 27 pytest + 11 node:test).
