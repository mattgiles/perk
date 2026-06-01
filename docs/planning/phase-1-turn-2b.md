# Phase 1 · Turn 2b — Plan ref (materialize `cache.plan-ref` + the session linkage)

Detailed execution plan for **P1.T2b** of [phase-1-plan.md](../phase-1-plan.md). T2a **emits** the
provider-agnostic plan-ref but persists nothing local. T2b makes the ref **durable and
discoverable** in the two complementary places the rest of the spine reads
([contracts.md](../../shared/contracts.md) §8.1/§8.3/§8.4): the **`cache.plan-ref` file** (the local
mirror of the canonical GitHub plan) and the **`active_plan_ref` session linkage** (the "this
session is working on plan X" tier, reconciled at session boundaries). This is the turn that lets a
**cold-saved plan be picked up by the next session** — the seam T4 `implement` reads — and it is
fully verifiable **now** through the T1 harness.

> **Scope discipline.** T2b is **mostly TS** (the `extension/` session linkage) with **one small
> Python touch** (the cold door persists the file). It ships: the `cache.plan-ref` file primitive in
> **both** planes (`perk/cache.py` + `extension/cache.ts`, same file — no shared module), the
> `session_start` **reconciliation** that links `active_plan_ref` from that file, the one-line cold
> door write in `perk plan-save`, and the `init` gitignore entry. It writes **`cache.plan-ref`** (so
> `save.writes` becomes `[github.plan, cache.plan-ref]`). It does **not** build the warm `/plan-save`
> tool's direct in-session append (**T3**), worktree materialization from the ref (**T4** reads it),
> or any plan-ref staleness/sync (`created_at`/`synced_at`, Phase 2).

---

## 1. Objective & the gate

**Goal.** Materialize the provider-agnostic plan-ref (PRIOR_ART §2) as a durable local file and a
session-linkage field, so the ref survives the cold→warm handoff, reload, compaction, and branch
navigation — the foundation `implement`/`submit`/`resume` all read.

**The two storage tiers (and why both).** The **canonical** copy is the GitHub plan (T2a). T2b adds:
1. **`cache.plan-ref`** (`.pi/workflow/plan-ref.json`) — the durable local mirror, **cross-plane**
   (both the CLI worker and the extension read/write the same file), written by whoever saves.
2. **`active_plan_ref`** (a `perk:workflow-state` field, §8.3) — the **transient session linkage**,
   reconciled from the cache file on `session_start` (idempotent) and restored by the existing LWW
   rebuild on `session_tree`, so it survives reload / compaction / branch navigation (the named
   antidote to erk's silent-stale-state bug).

**Hard gate (must pass to land T2b).** Via `scripts/verify-p1-t2b.sh` on a fresh `perk init`-ed repo,
**fully offline** (no `gh`, no LLM, no network):

1. **The TS live suite passes offline** — the new `extension/planRef.test.ts` cases drive a real
   bound `AgentSession` (the T1 harness) and prove: a planted `cache.plan-ref` is **linked** into
   `active_plan_ref` on `session_start`; a `reload()` does **not** duplicate it; `session_tree`
   navigation **preserves** it; a planted fork **keeps** the inherited ref.
2. **The cache-file primitive round-trips in both planes** — `read_plan_ref(write_plan_ref(…)) == …`
   (Python) and `readPlanRef(writePlanRef(…))` (TS), proven by the unit suites the gate runs.
3. **The cold door persists the ref** — `perk plan-save` writes `.pi/workflow/plan-ref.json` on a
   successful create and **does not** on `--dry-run` (proven by the `tests/test_plan_save.py`
   assertions; the gate runs the pytest subset offline).
4. **The registry `save` stage now declares `writes: [github.plan, cache.plan-ref]`** (and the
   registry self-check still passes).
5. **`init` ignores the new file** — a fresh `perk init` lists `/.pi/workflow/plan-ref.json` in
   `.gitignore`, and re-running `init` is a no-op (idempotent convergence).
6. **The pytest + node suites are green** (the extended `tests/test_cache.py` /
   `tests/test_plan_save.py` / `tests/test_init_idempotent.py` and the extended
   `extension/cache.test.ts` / `extension/workflowState.test.ts` + the new `planRef.test.ts`).

`just verify` runs t1…t7 + p1-t1 + p1-t2a **+ p1-t2b**; `just ci` stays green.

---

## 2. Grounding & doc lineage (what governs T2b)

- **The phase plan.** [phase-1-plan.md](../phase-1-plan.md) §P1.T2 → **T2b**: *materialize the
  provider-agnostic plan ref in `.pi/workflow/` (contracts §8.4) — canonical copy in GitHub,
  transient linkage in the session `appendEntry`, idempotent on the Pi session id; the transient
  linkage is rebuilt on both `session_start` and `session_tree` with last-write-wins, so it survives
  reload, compaction, and branch navigation; tested via the T1 harness; fills the registry `save`
  stage's `writes` (`github.plan`, `cache.plan-ref`).* T2b discharges that verbatim.
- **The predecessor.** [phase-1-turn-2a.md](./phase-1-turn-2a.md) §D4 (the T2a↔T2b seam: *T2a writes
  `github.plan` and emits the plan-ref; it never touches `cache.plan-ref` or a session entry — all of
  `cache.plan-ref` is T2b*) and §10 (the explicit pointers to this turn). T2a's `PlanRef` dataclass
  (`perk/plan.py`, with `to_data()`) is the bridge T2b serializes.
- **The storage model.** [PRIOR_ART.md](../PRIOR_ART.md) §2 (provider-agnostic ref) and the
  [plan-ref-architecture reference](../../.prior-art/erk/docs/learned/architecture/plan-ref-architecture.md):
  erk stores the ref in a per-worktree `plan-ref.json`; `pr_id` is a **string** (LBYL `.isdigit()`
  before any `int()`); `save_plan_ref`'s params are keyword-only; `read_plan_ref → PlanRef | None`.
- **The state-tier contract.** [contracts.md](../../shared/contracts.md) §8.1 (the `.pi/workflow/`
  layout — `cache.plan-ref` is a declared state key; the dir stays tracked, transient files are
  gitignored, `init` manages the entries), §8.3 (the `perk:workflow-state` schema — `active_plan_ref`
  is already a field; the **rebuild on both `session_start` AND `session_tree`** discipline; the
  **verified-linkage tier**: `active_plan_ref` is *strict* — durable/cross-process → read-back +
  correct ordering), §8.4 (the plan-ref payload — *"T2b materializes it into `cache.plan-ref` and the
  session linkage"*).
- **The reconciliation discipline.** The T1 spike + [phase-1-turn-1.md](./phase-1-turn-1.md): the
  rebuild runs on `session_start` and `session_tree`, headless-safe (loud-but-non-fatal, never
  throws). The plan-ref reconciliation reuses that exact shape (the existing claim block's
  `reportError` + read-back).
- **The division of labor.** [cli-vs-pi.md](../cli-vs-pi.md) §3 (no in-process coupling — the planes
  coordinate through the durable file, not a shared module; the extension never shells `perk`).
- **Repo conventions in force.** uv + ruff + ty + dignified-python (no `from __future__`; pathlib;
  LBYL; pure cache primitives return `None`/`null` on absence) on the Python side; biome + tsc + the
  T1 harness on the TS side. `cache.py`/`cache.ts` stay **pure file primitives** (no workflow
  semantics, no `plan.py` import).

---

## 3. Design decisions (locked — agreed with the user)

- **D1 — File: `.pi/workflow/plan-ref.json`, the §8.4 struct verbatim.** Contents are exactly
  `{ provider, pr_id, url, labels, objective_id }` — **no** `created_at`/`synced_at` (erk has them;
  staleness/sync is Phase 2). **One active ref per workspace/worktree** (`.pi/workflow/` is
  per-checkout, so each impl worktree carries its own once T4 lands). Stored as **plain JSON**, the
  same way the handoff blob is (dict in, `dict | None` out) — so `cache.py` / `cache.ts` stay pure
  file primitives with **no `plan.py` import**; the *command* does the `PlanRef ↔ dict` bridge via
  the existing `PlanRef.to_data()`. `pr_id` stays a **string** (the erk tripwire: LBYL before any
  `int()`).
- **D2 — T2b is cross-plane (mostly TS, one small Python touch).** To *honestly* fill
  `save.writes: [github.plan, cache.plan-ref]`, the **cold door writes the file**: `perk plan-save`
  gains one call — after a successful **non-dry-run** create, `cache.write_plan_ref(repo_root,
  plan_ref.to_data())`. (`--dry-run` writes nothing — it shells nothing.) The bulk of the turn is the
  TS session linkage. The pure-TS alternative (file written only by the future warm T3 tool) was
  rejected: it would make `save.writes: cache.plan-ref` a lie for the cold path and leave cold-saved
  plans locally invisible to T4.
- **D3 — Linkage trigger = `session_start` reconciliation.** In `index.ts`, **after** the run_id
  claim block: read `cache.plan-ref`; if it exists and the rebuilt `active_plan_ref` does **not**
  already match it, `pi.appendEntry("perk:workflow-state", { active_plan_ref: ref })` with a
  **strict read-back** (the §8.3 verified-linkage tier), reported **loud-but-non-fatal** on a
  read-back mismatch (reusing the claim path's `reportError` → headless-safe, never throws).
  `session_tree` keeps **only** the existing rebuild — which already restores `active_plan_ref` via
  LWW — plus the sentinel; it does **not** re-read the cache file (navigating to a pre-link branch
  point legitimately shows the ref absent: correct LWW semantics).
- **D4 — Idempotency (the practical form of "idempotent on the Pi session id").** Append **only**
  when the rebuilt `active_plan_ref` differs from the cache ref, compared by **`(provider, pr_id)`**.
  Naturally idempotent across reloads (the same branch already carries the entry → skip) and
  fork-safe (the child inherits the entry and keeps it → skip). No separate session-id bookkeeping is
  needed; the linkage living on the session branch *is* the per-session record.
- **D5 — Types + a pure dedup helper.** Narrow `active_plan_ref?: unknown` → `PlanRef | null` in
  `workflowState.ts` (define/`export` a `PlanRef` interface — `extension/cache.ts` owns it, mirrors
  `perk/plan.py`'s dataclass), and add a small **pure** `planRefsEqual(a, b)` (compares
  `provider` + `pr_id`) so the dedup decision is unit-testable next to `rebuildWorkflowState`.
- **D6 — `init` gains the gitignore entry.** Add `/.pi/workflow/plan-ref.json` to `init`'s ignore
  list (it is a local cache; GitHub is canonical — §8.1). `init` stays idempotent; the convergence is
  asserted in `tests/test_init_idempotent.py`.

---

## 4. Deliverables

| Path | What |
|---|---|
| `extension/cache.ts` | A `PlanRef` interface + `planRefPath` / `readPlanRef` (→ `PlanRef \| null`) / `writePlanRef` over `.pi/workflow/plan-ref.json`. Pure file primitives (node builtins only). |
| `extension/workflowState.ts` | Narrow `active_plan_ref?` to `PlanRef \| null`; add the pure `planRefsEqual(a, b)` dedup helper. |
| `extension/index.ts` | The `session_start` plan-ref reconciliation (D3/D4) — read → append (strict read-back, headless-safe); add `active_plan_ref` to the `.perk-t3.json` sentinel (observability for the harness); `session_tree` sentinel includes it. |
| `perk/cache.py` | `plan_ref_path` / `read_plan_ref` (→ `dict \| None`) / `write_plan_ref` over the same file — the TS twin's Python half (JSON, like the handoff blob). |
| `perk/cli/commands/plan_save_cmd.py` | One call: after a successful non-dry-run create, `cache.write_plan_ref(repo_root, plan_ref.to_data())`; surface `cached: true` in `--json`. |
| `perk/init.py` | Add `/.pi/workflow/plan-ref.json` to the managed `.gitignore` entries. |
| `shared/contracts.md` | §8.1 (add `plan-ref.json` to the layout + gitignore note); §8.3 (`active_plan_ref` reconciled from `cache.plan-ref`); §8.4 (flip "T2b materializes…" to a shipped status note + the reconciliation behavior). |
| `shared/registry.yaml` | `save.writes: [github.plan, cache.plan-ref]`. |
| `extension/planRef.test.ts` (new) | The four harness-driven linkage cases (link / no-dup reload / session_tree survives / fork keeps). |
| `extension/cache.test.ts`, `extension/workflowState.test.ts` (extend) | The TS plan-ref round-trip + the `planRefsEqual` unit. |
| `tests/test_cache.py`, `tests/test_plan_save.py`, `tests/test_init_idempotent.py` (extend) | Python round-trip; cold-door writes-on-success / not-on-dry-run; gitignore convergence. |
| `scripts/verify-p1-t2b.sh` + `justfile` | The offline hard gate; appended to `just verify` after `verify-p1-t2a.sh`. |

No new dependency; no `gh`/network/LLM anywhere in the turn or its gate.

---

## 5. The cache-file primitive (`cache.plan-ref`)

`.pi/workflow/plan-ref.json` holds the §8.4 struct, written verbatim from `PlanRef.to_data()`:

```json
{ "provider": "github",
  "pr_id": "42",
  "url": "https://github.com/owner/repo/issues/42",
  "labels": ["perk:plan"],
  "objective_id": null }
```

- **Python (`perk/cache.py`)** — `plan_ref_path(root)`, `write_plan_ref(root, data: dict[str, Any])
  -> Path` (creates `.pi/workflow/`, writes pretty JSON + trailing newline, like `write_handoff`),
  `read_plan_ref(root) -> dict[str, Any] | None` (LBYL `.is_file()` → `None` on absence). **No
  `plan.py` import** — the command bridges `PlanRef ↔ dict`.
- **TS (`extension/cache.ts`)** — `planRefPath(cwd)`, `writePlanRef(cwd, ref: PlanRef)`,
  `readPlanRef(cwd): PlanRef | null` (returns `null` when the file is absent), and the `PlanRef`
  interface (`provider`, `pr_id`, `url`, `labels: string[]`, `objective_id: string | null`).
- **The cross-plane contract is the *file*** (§8.1), not a shared module — the Python cold door
  writes it; the TS extension reads it. Round-trip is symmetric (the JSON the one plane writes is
  what the other parses), proven by both unit suites.
- **`pr_id` is a string** (erk's provider-agnostic tripwire): never `int(pr_id)` without an LBYL
  `.isdigit()` guard — relevant when T4/T5 convert it for `gh` issue/PR calls (out of scope here, but
  the type is locked now).

## 6. The session linkage (`active_plan_ref`) + reconciliation

`active_plan_ref` is the §8.3 `perk:workflow-state` field carrying the **current session's** plan
ref. It is *strict* (the verified-linkage tier): durable across process boundaries, so writes are
**read-back-verified** and survive the rebuild on both entry points.

**Reconciliation on `session_start`** (`index.ts`, after the run_id claim block):

```
const cached = readPlanRef(ctx.cwd);                       // PlanRef | null
if (cached !== null) {
  const linked = rebuildWorkflowState(branchEntries()).active_plan_ref ?? null;
  if (!planRefsEqual(linked, cached)) {                    // D4: dedup by (provider, pr_id)
    pi.appendEntry(WORKFLOW_STATE_TYPE, { active_plan_ref: cached });
    if (!planRefsEqual(rebuildWorkflowState(branchEntries()).active_plan_ref ?? null, cached)) {
      reportError(`plan-ref read-back failed`);            // strict tier: loud, non-fatal
    }
  }
}
```

- **Idempotent (D4):** on a `reload()` the branch already carries the entry → `linked == cached` →
  skip. On a planted **fork** the child inherits the entry → skip (it keeps working the same plan).
  A genuinely *new* cache ref (rare: a cold save into an open session's cwd) flips `linked != cached`
  → re-link.
- **Headless-safe:** `reportError` notifies only when `ctx.hasUI`, always logs to stderr, **never
  throws** (mirrors the claim block) — so a read-back failure leaves the session running unlinked,
  loudly, exactly like a failed run-id claim.
- **`session_tree`:** unchanged reconciliation policy — the existing `rebuildWorkflowState` already
  restores `active_plan_ref` via per-field LWW, so branch navigation preserves it with **no** cache
  re-read. (Navigating to a pre-link branch point shows it absent — correct LWW, not a bug.)
- **Sentinel:** extend `.perk-t3.json` (written under `PERK_SELFCHECK`) with `active_plan_ref` so the
  T1 harness can assert linkage on both `session_start` and `session_tree` paths.
- **Ordering:** the plan-ref block runs **after** the run_id claim/fork/keep block so the run is
  settled first; the two append independent fields, merged by the LWW rebuild.

## 7. The cold door write (`perk plan-save`)

A single addition to the T2a command (D2): after `create_plan_issue(…)` succeeds on a **non-dry-run**
save, persist the ref the command already builds —

```
cache.write_plan_ref(repo_root, plan_ref.to_data())
```

- **Dry-run writes nothing** (it shells nothing and creates nothing). The `--json` object gains
  `cached: <bool>` (true on a real save, false on dry-run), alongside the existing `plan_ref` /
  `issue` fields.
- This is the consumer that makes `save.writes: cache.plan-ref` honest, and it makes a cold-saved
  plan **locally discoverable** — the next session's reconciliation (§6) links it, and T4
  `implement` reads it to materialize the worktree.
- No new error surface: `write_plan_ref` is a local file write under `.pi/workflow/` (already
  created by `init`); a filesystem failure surfaces as the normal exception at the command boundary.

## 8. Contract & registry amendments

- **`shared/contracts.md`:**
  - **§8.1** — add `plan-ref.json` to the layout diagram (the `cache.plan-ref` pointer; distinct from
    `plans/`, which caches plan *bodies* = `cache.plan`), and note it is gitignored (local cache;
    GitHub canonical) and `init`-managed.
  - **§8.3** — one line on `active_plan_ref`: *reconciled from `cache.plan-ref` on `session_start`
    (idempotent by `(provider, pr_id)`, strict read-back); restored by the LWW rebuild on
    `session_tree`.*
  - **§8.4** — flip the closing *"T2b materializes it into `cache.plan-ref` and the session linkage"*
    to a shipped **"Status (P1.T2b)"** note describing the file (`.pi/workflow/plan-ref.json`,
    cross-plane) + the reconciliation behavior.
- **`shared/registry.yaml`:** `save.writes: [github.plan, cache.plan-ref]` (`requires`/`reads` stay
  `[]`; `doors`/`run_id` unchanged — T2b adds no door).

## 9. Tests + the verify gate

- **`extension/planRef.test.ts` (new — via the T1 harness, offline):**
  - **link:** `writePlanRef(cwd, ref)` → `loadPerkSession` → `workflowState().active_plan_ref`
    equals `ref`; the sentinel carries it.
  - **no-dup reload:** after the link, `reload()` → the branch still carries exactly one
    `active_plan_ref` entry (assert via `entryIds`/branch scan) and the value is unchanged.
  - **session_tree survives:** `navigateTo(firstEntry)` → `active_plan_ref` still equals `ref`
    (the rebuild restored it; sentinel `source: "tree"` carries it).
  - **fork keeps:** a `plantSession` whose state already carries `active_plan_ref` + a mismatched
    `pi_session_id` (→ fork) → the child's rebuilt state keeps the inherited ref (no duplicate
    append, since `linked == cached`).
- **`extension/cache.test.ts` (extend):** `readPlanRef` missing → `null`; `writePlanRef` →
  `readPlanRef` round-trip in the exact shape `perk/cache.py` writes.
- **`extension/workflowState.test.ts` (extend):** `planRefsEqual` — equal by `(provider, pr_id)`,
  unequal across providers/ids, `null` handling.
- **`tests/test_cache.py` (extend):** `read_plan_ref(write_plan_ref(...))` round-trip; missing →
  `None`.
- **`tests/test_plan_save.py` (extend):** the monkeypatched **success** case asserts
  `.pi/workflow/plan-ref.json` exists with the emitted ref + `--json` `cached: true`; the
  **`--dry-run`** case asserts the file is **absent** + `cached: false`.
- **`tests/test_init_idempotent.py` (extend):** a fresh `init` lists `/.pi/workflow/plan-ref.json` in
  `.gitignore`; re-running `init` reports no changes.
- **`scripts/verify-p1-t2b.sh`** (offline, fresh init'd repo, mirrors the existing verify style):
  (1) the node live suite passes with keys unset (the `planRef.test.ts` linkage cases); (2) the
  registry self-check passes with `save.writes == [github.plan, cache.plan-ref]`; (3) the pytest
  subset (`test_cache.py` / `test_plan_save.py` / `test_init_idempotent.py`) is green; (4) a fresh
  `perk init` gitignores `plan-ref.json`. Appended to `just verify` after `verify-p1-t2a.sh`. **No
  network, no `gh`, no LLM.**

## 10. Explicitly out of scope for T2b (pointers)

- **The warm `/plan-save` tool's direct in-session append + cache write** — **T3**. T2b provides the
  primitives (`writePlanRef` + the `appendEntry` shape) and the boundary reconciliation; T3 wires
  them into the in-session save path.
- **Reading the ref to materialize a worktree** — **T4** `implement` (consumes `cache.plan-ref`).
- **`pr_id` → `int` conversion for `gh`** — the consuming turns (T4/T5); T2b only locks the string
  type + the LBYL tripwire.
- **`created_at`/`synced_at` + plan-ref staleness/sync** — Phase 2.
- **Multi-plan / per-worktree ref indexing** — Phase 2 (MVP is one active ref per checkout).
- **The §8.3 marker-scoped reconstruction subtlety** (re-scan only after the current execution's
  marker) — that governs plan-mode *execution* state, not the durable plan linkage; Phase 2 with the
  gating primitive.
- **GC of `plan-ref.json`** — folds into the §8.1 perk-owned GC (`doctor` check + prune command,
  later).

## 11. Definition of done

The six gate checks in §1 pass via `scripts/verify-p1-t2b.sh` on a fresh init'd repo **offline**;
`cache.plan-ref` is a real cross-plane file primitive (both planes round-trip it); the cold door
persists it on save (and not on dry-run); the extension reconciles it into `active_plan_ref` on
`session_start` (idempotent, strict read-back, headless-safe) and the LWW rebuild preserves it across
`session_tree`; `init` gitignores it idempotently; §8.1/§8.3/§8.4 are amended and `save.writes` is
filled; `just ci` and `just verify` (t1…t7 + p1-t1 + p1-t2a + p1-t2b) are green. T2b lands; **T3 can
now build the warm `/plan-save` twin against a real `cache.plan-ref`, and T4 can read it to
materialize the impl worktree.**

---

## 12. Outcomes (recorded on landing)

**Status: landed, all green.** `just verify` runs **t1…t7 + p1-t1 + p1-t2a + p1-t2b, all PASS**;
`just ci` green — ruff + ruff-format + ty + biome + tsc clean; **112 pytest** (109 prior + 3 new) **+
23 `node:test`** (17 prior + 6 new: 1 cache round-trip, 1 `planRefsEqual`, 4 live linkage). The whole
T2b gate runs **offline** (no `gh`, no LLM, no network).

**Built (matches §4–§7):**
- `extension/cache.ts` — `PlanRef` interface + `planRefPath`/`readPlanRef`/`writePlanRef` over
  `.pi/workflow/plan-ref.json`. `perk/cache.py` — `plan_ref_path`/`write_plan_ref`/`read_plan_ref`
  (dict JSON, like the handoff blob; no `plan.py` import). Symmetric round-trip across the planes.
- `extension/workflowState.ts` — `active_plan_ref` narrowed to `PlanRef | null`; pure
  `planRefsEqual(a, b)` (identity by `provider`+`pr_id`). `extension/index.ts` — the `session_start`
  reconciliation (read `cache.plan-ref` → append `active_plan_ref` iff `!planRefsEqual(linked,
  cached)`, strict read-back, headless-safe via the existing `reportError`); `active_plan_ref` added
  to the `.perk-t3.json` sentinel (both the `session_start` and `session_tree` paths).
- `perk/cli/commands/plan_save_cmd.py` — one call: a successful non-dry-run save writes the
  `cache.plan-ref` pointer; `--json` gains `cached: <bool>`. `perk/init.py` — gitignores
  `/.pi/workflow/plan-ref.json`.
- `shared/contracts.md` §8.1 (the `plan-ref.json` layout line + the cross-plane note),
  §8.3 (the `active_plan_ref` reconciliation paragraph), §8.4 (the **Status (P1.T2b)** note).
  `shared/registry.yaml` — `save.writes: [github.plan, cache.plan-ref]`.
- `scripts/verify-p1-t2b.sh` + `justfile`; tests `extension/planRef.test.ts` (new),
  extended `extension/cache.test.ts` / `extension/workflowState.test.ts` / `tests/test_cache.py` /
  `tests/test_plan_save.py` / `tests/test_init_idempotent.py`.

**Deviations / sharpenings (recorded, not retro-edited):**
- **The `session_tree` linkage test is a two-hop navigation.** The link entry is always the **leaf**
  (appended last in `session_start`), so navigating *to* it is a no-op that never fires the tree
  handler, and the only navigations that fire it land at **pre-link** entries (where
  `active_plan_ref` is correctly absent — the LWW semantics this doc predicted). The test therefore
  hops to a pre-link entry (asserts `source:"tree"` + `active_plan_ref:null`) **then back to the
  leaf** (asserts `source:"tree"` + the ref restored). This proves the invariant more honestly than
  a single nav could — confirmed against the real branch shape via a throwaway probe.
- **The T2a gate's registry check was relaxed from exact-match to membership.** `verify-p1-t2a.sh`
  hardcoded `save.writes == ['github.plan']`; T2b legitimately appended `cache.plan-ref`, so the
  (cumulative) T2a gate now asserts `'github.plan' in save.writes` — T2a's gate cares that T2a filled
  `github.plan`; the full list is T2b's concern. (Forward-convergence over frozen history.)
- **Sentinel observability.** `active_plan_ref` was added to `.perk-t3.json` (under `PERK_SELFCHECK`)
  so the harness can assert linkage on both lifecycle paths — in line with the existing sentinel's
  role (it carries no behavior, only observability).

**Contract/registry:** §8.1/§8.3/§8.4 amended in-turn; `save.writes` filled (`requires`/`reads` stay
`[]`; `doors`/`run_id` unchanged — T2b adds no door).

**Tree at handoff (staged-clean for the user to commit):** new — `extension/planRef.test.ts`,
`scripts/verify-p1-t2b.sh`, `docs/planning/phase-1-turn-2b.md`; modified — `extension/cache.ts`,
`extension/workflowState.ts`, `extension/index.ts`, `extension/testing/harness.ts`,
`extension/cache.test.ts`, `extension/workflowState.test.ts`, `perk/cache.py`,
`perk/cli/commands/plan_save_cmd.py`, `perk/init.py`, `tests/test_cache.py`,
`tests/test_plan_save.py`, `tests/test_init_idempotent.py`, `shared/contracts.md`,
`shared/registry.yaml`, `justfile`, `scripts/verify-p1-t2a.sh`, `docs/index.md`.

**Unblocks T3 + T4:** the warm `/plan-save` tool (T3) can write `cache.plan-ref` + append
`active_plan_ref` against real primitives; `implement` (T4) reads `cache.plan-ref` to materialize the
impl worktree (`pr_id` is a string — LBYL `.isdigit()` before any `int()`).
