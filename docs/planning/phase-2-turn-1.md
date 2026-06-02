# Phase 2 · Turn 1 — Tool-gating primitive (the keystone)

> Implementation-level plan for **P2.T1**. Grounded in pi's authoritative read-only recipe
> (`examples/extensions/plan-mode/{index,utils}.ts` — the `setActiveTools` allowlist, the
> `tool_call` bash sub-allowlist, the `before_agent_start` context injection + the `context`
> strip-when-off filter, and the `session_start` restore), `examples/extensions/preset.ts`
> (the **snapshot-then-restore** discipline on the first off→on transition), and the perk
> interior already shipped in Phase 1 (`extension/index.ts` `session_start`/`session_tree`
> rebuilds, `extension/workflowState.ts` per-field LWW + the live `mode` field, the
> `extension/testing/harness.ts` bound-session harness).

---

## 1. Objective & scope

Build the **generic, reusable read-only-mode primitive** that T2 (perk-owned plan mode) and
T5 (read-only CI executor) will both consume — **structural enforcement, not prompting**. The
gate attaches to the existing `perk:workflow-state.mode` field (`read-only` / `read-write`);
there is **no new registry stage**.

**Substrate only.** This turn does **not**: take over `/plan` ownership (T2), build the CI
executor (T5), add a registry stage, or retire the borrowed `pi-plan` extension. It ships the
enforcement mechanism + the `enter`/`exit` API surface T2/T5 will call, and wires the
allowlist-restore into the existing lifecycle handlers.

## 2. Prior-art pass (what exists, what we copy)

- **`plan-mode/index.ts`** — the canonical shape: an in-memory `planModeEnabled` flag drives a
  `tool_call` bash sub-allowlist; `setActiveTools(PLAN_MODE_TOOLS)` on enable; a
  `before_agent_start` hidden `[PLAN MODE ACTIVE]` context; a `context` filter that strips that
  marker when **not** enabled; restore on `session_start`. We mirror all five pieces.
- **`plan-mode/utils.ts`** — `isSafeCommand()` = `!DESTRUCTIVE && SAFE` over two regex tables.
  We **copy** these tables into `toolGating.ts` (perk-owned, renamed `isReadOnlyBashCommand`) so
  T2's eventual retirement of the borrowed `pi-plan` extension leaves **no dangling import**.
- **`preset.ts`** — snapshots `pi.getActiveTools()` **once**, on the transition from no-preset,
  and restores it on clear. We adopt the same **snapshot-then-restore** order: snapshot only on
  the off→on transition, restore on on→off.
- **perk Phase 1** — `index.ts` already rebuilds `perk:workflow-state` on **both**
  `session_start` and `session_tree` (per-field LWW via `rebuildWorkflowState`). The `mode` field
  is the source of truth; we hang the allowlist sync off those two existing rebuild points.

## 3. Design

`extension/toolGating.ts` composes three pieces, with pure policy kept separable for offline
unit tests:

1. **`setActiveTools` allowlist** — `READ_ONLY_TOOLS = ["read", "grep", "find", "ls", "bash"]`,
   with **snapshot-then-restore**: snapshot `pi.getActiveTools()` only on off→on; on on→off,
   restore the snapshot (falling back to the full `pi.getAllTools()` set if none — never a
   hardcoded list, so perk's custom tools survive).
2. **`tool_call` bash sub-allowlist** — when active, `{ block: true, reason }` on a
   non-allowlisted `bash` command (pure `isReadOnlyBashCommand`), and **defensively** on `edit` /
   `write` (the allowlist already removes them from the model's tool set, but the `tool_call`
   guard is the structural backstop).
3. **Persist/restore + context hygiene** — the live `mode` field is the source of truth;
   `syncFromState(mode)` reapplies the allowlist on `session_start` **and** `session_tree`; a
   `before_agent_start` hook injects a hidden `[READ-ONLY MODE]` mode-context when active; a
   `context` filter **strips** that marker when off so it never pollutes the window.

### `enter` / `exit` — the T2/T5 surface (signature locked, call sites deferred)

```ts
registerToolGating(pi: ExtensionAPI): ToolGating
interface ToolGating {
  syncFromState(mode: string | undefined): void; // reapply allowlist from a rebuilt mode
  enter(ctx?: ExtensionContext): void;            // append mode=read-only + go active (T2/T5)
  exit(ctx?: ExtensionContext): void;             // append mode=read-write + go inactive (T2/T5)
  isActive(): boolean;                            // test/introspection
}
```

`enter`/`exit` append the `mode` field to `perk:workflow-state` (best-effort transient per §8.3 —
no strict read-back) and flip the in-memory gate + allowlist. They take an optional `ctx` to lock
a forward-compatible signature; T2/T5 own the call sites.

### Fail-closed (headless safety)

The in-memory `active` flag (like plan-mode's `planModeEnabled`) drives `tool_call`. Two rules:

- **Sync never flips the gate open on error.** `index.ts` wraps the state rebuild; if the rebuild
  throws, it does **not** call `syncFromState`, so the gate is left as-is (never opened by a
  failed sync).
- **`tool_call` blocks on any internal error.** The handler is wrapped so an unexpected throw
  returns `{ block: true }` — pi already treats `tool_call` errors as fail-safe-block; we make it
  explicit.

### Why this is safe to wire now

`perk/launch.py` writes the handoff `mode` = the registry stage's `mode`. Only `plan` is
`read-only`; the read-write stages (`implement`/`submit`/`land`/`learn`) are unaffected. Layering
perk-owned enforcement onto the still-borrowed `pi-plan` plan session is **additive** (both are
read-only) and breaks nothing. T2 later internalizes plan mode and removes the `pi-plan` coupling.

## 4. Files

- **`extension/toolGating.ts`** *(new)* — `READ_ONLY_TOOLS`, pure `isReadOnlyBashCommand`,
  `registerToolGating(pi)` returning the `ToolGating` controller.
- **`extension/toolGating.test.ts`** *(new)* — pure `isReadOnlyBashCommand` matrix + the live
  read-only round-trip via the harness.
- **`extension/testing/harness.ts`** — add `emitToolCall(toolName, input)` (via
  `session.extensionRunner.emitToolCall(...)`, returns `{ block?, reason? }`).
- **`extension/index.ts`** — `const gating = registerToolGating(pi)`; call
  `gating.syncFromState(...)` inside the existing `session_start` (after state resolution) and
  `session_tree` handlers, each guarded fail-closed.
- **`shared/contracts.md`** — amend §8.3: the `mode` field now **structurally gates tools**.
- **`scripts/verify-p2-t1.sh`** *(new)* + **`justfile`** — appended to the cumulative `verify`.

## 5. Verify gate (`verify-p2-t1.sh`, fully offline)

1. `toolGating.test.ts` green offline — pure policy matrix + the live round-trip:
   **allowlist on → blocked write → blocked unsafe bash → safe bash allowed → mode off →
   write allowed**.
2. Gating is wired into `index.ts` (`registerToolGating`) and synced on **both** `session_start`
   and `session_tree`.
3. `just verify` (t1…t7 + p1-* + **p2-t1**) and `just ci` stay green.

## 6. Decisions settled

- **Perk-owned allowlist (copied), not a `pi-plan` import.** The destructive/safe regex tables
  are copied into `toolGating.ts` so plan-mode's eventual retirement in T2 leaves no dangling
  dependency.
- **`bash` stays in the allowlist** (with the sub-allowlist), following plan-mode — read-only
  shell (cat/grep/git status/…) is needed during exploration; the sub-allowlist is the guard.
- **`enter`/`exit` signature locked** as `(ctx?: ExtensionContext) => void`; T2/T5 own the call
  sites. `mode` writes are best-effort transient (no strict read-back), per §8.3.

## 7. Outcomes

Built as planned. Notes / refinements:

- **`registerToolGating(pi)` returns a `ToolGating` controller** (`syncFromState`, `enter`,
  `exit`, `isActive`) — `index.ts` captures it and calls `gating.syncFromState(...)` inside the
  existing `session_start` (after `resolved` is computed) and `session_tree` handlers, each wrapped
  in a `try/catch` that logs and leaves the gate as-is (fail-closed).
- **`tool_call` blocks `edit`/`write` outright and bash via `isReadOnlyBashCommand`**, with a
  `catch` that returns `{ block: true }` on any internal error. The `before_agent_start` injection
  uses `customType: "perk:mode-context"` + the `[READ-ONLY MODE]` marker; the `context` handler
  strips both when the gate is off.
- **Harness:** added `emitToolCall(toolName, input)` via `session.extensionRunner.emitToolCall`
  (the generic `emit` excludes `ToolCallEvent`). The live round-trip plants
  `[{mode:"read-only"}, {mode:"read-write"}]` and navigates across the boundary; note the branch
  also carries session-setup `model_change`/`thinking_level_change` entries after the two planted
  ones, so the test reads the first two `entryIds()` rather than asserting a branch length.
- **Pre-existing gate repair (corrective):** the earlier "Fix docs" commit moved
  `docs/phase-1-plan.md` → `docs/planning/phase-1-plan.md` but left `scripts/verify-t7.sh` Check 4
  pointing at the old path, so `just verify` was already red on the base. Repaired the stale path
  in `verify-t7.sh` in this turn to keep the cumulative gate green.
- **Deferred (unchanged):** `/plan` ownership and `pi-plan` retirement (T2), the read-only CI
  executor (T5), any new registry stage. The `enter`/`exit` signature is locked; call sites are
  T2/T5's.
