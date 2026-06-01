# Phase 1 · Turn 4 — `perk implement` (the cold door) + session-lifecycle gates

> Detailed, implementation-level plan for **P1.T4**. Grounded in
> [phase-1-plan.md](../phase-1-plan.md) (the T4 section), [cli-vs-pi.md](../cli-vs-pi.md)
> (§2.3 hand-off, §4.1 door legality, §4.4 stage table, §4.5 local/remote), the Phase-0 launch
> spine (`perk/launch.py`, `perk/cli/stages.py`, `perk/git.py`), the T2/T3 plan-ref tiers
> (`perk/cache.py`, `extension/cache.ts`, the `session_start` reconciliation in
> `extension/index.ts`), [pi-best-practices.md](../pi-best-practices.md) §7 (lifecycle gates),
> and the pi extension API (`session_before_switch`/`session_before_fork` →
> `{ cancel?: boolean }`).
>
> **Scope discipline.** T4 closes `save → implement`. It is **two independent halves** landed as a
> seam:
> - **T4a (Python/exterior — the cold door):** teach the registry-generated launcher to **resolve
>   and materialize a worktree from the active plan-ref**, idempotently, then `exec pi` with **fresh
>   context**. This is the first stage that creates a branch and the first transition that can *lose
>   work*; the launcher stays a **launcher that delegates** (cli-vs-pi §2.3), never a
>   reimplementation.
> - **T4b (TS/interior — the gates):** one reusable **dirty-repo lifecycle gate**
>   (`session_before_switch`/`session_before_fork` → `{ cancel: true }`) scoped to active perk
>   workflows, fail-safe-headless; plus a **guard-only `/implement`** command that *enforces*
>   the stage's `warm: false` legality structurally.
>
> It does **not**: resolve an arbitrary plan `#N` from GitHub (that is **T5c `perk resume`**), add a
> `[PLAN]` positional, build the in-process `ctx.newSession` warm fresh-context (Phase 2), ship a
> "proceed-anyway" confirm dialog or `git-checkpoint` stash (Phase 2), or run `perk implement` from
> *inside* a worktree (assume repo-root invocation; flagged limitation).

---

## 1. Objective & the gate

**Close `save → implement`.** After a plan is saved (T3), a single cold command materializes the
work environment and drops the engineer (or a fresh agent) into an implementation session with
**clean context** — *not* the planning conversation. The interior gains the safety primitive that
makes stage transitions non-destructive.

Two verify gates run **fully offline** (no `pi` model turn, no network):

**`scripts/verify-p1-t4a.sh` (cold door):**
1. `perk implement --dry-run` after a saved plan **derives the worktree name `plan-<pr_id>`** from
   the active `cache.plan-ref` (no `--worktree` needed) and prints the launch plan.
2. With **no** `cache.plan-ref`, `perk implement` exits non-zero with a loud "no saved plan — run
   `/plan-save` first" message (stable `error_type`).
3. A **real-git integration test** (temp repo): `perk implement` (non-dry-run, `exec` stubbed)
   creates the `plan-<pr_id>` worktree+branch and **materializes the plan-ref + handoff into it**;
   re-running **reuses** the worktree (idempotent resume) instead of erroring.
4. `implement` registry I/O is filled (`requires`/`reads`/`writes`) and the registry self-check holds.

**`scripts/verify-p1-t4b.sh` (gates):**
5. The lifecycle-gate live suite passes offline: dirty repo + active workflow → `before_fork`/
   `before_switch` **cancel**; clean → allow; **no active workflow → allow** (perk doesn't interfere);
   headless + dirty → cancel.
6. The guard-only `/implement` refuses outside an impl worktree (points to `perk implement`) and
   acknowledges inside one.

`just verify` runs t1…t7 + p1-t1 + p1-t2a + p1-t2b + p1-t3 + **p1-t4a + p1-t4b**; `just ci` stays
green.

---

## 2. Grounding & doc lineage (what governs T4)

- **[cli-vs-pi.md](../cli-vs-pi.md) §4.1 (door legality):** "the warm door is not always safe …
  `implement` should not inherit the planning conversation, so the stage should be **cold-only**."
  The registry records this (`implement.doors.warm: false`). §2.3: the CLI **positions + launches +
  hands off, then done.** §4.4: cold `perk implement` does *prepare + launch*; warm `/implement`
  *assumes the worktree is already current*. §4.5: the cold door is parameterized by target —
  `--remote` stays blocked (Phase 3).
- **[phase-1-plan.md](../phase-1-plan.md) T4:** primary transition is the **CLI cold door**;
  **lifecycle gates** are "one primitive, reused across all stages," ported from erk's
  dirty-repo/commit-before-leaving checks, **fail-safe (block) when headless**. The in-process
  `ctx.newSession` warm fresh-context is **Phase 2**.
- **[pi-best-practices.md](../pi-best-practices.md) §7:** `dirty-repo-guard.ts` — block
  switching/forking with uncommitted changes via `pi.exec("git", ["status","--porcelain"])`; **block
  by default headless**.
- **Plan-ref contract (contracts §8.4):** the plan-ref is provider-agnostic
  (`{provider, pr_id, url, labels, objective_id}`) and carries **no branch** — the plan-header's
  `branch` field is `null` until **submit**. So the implement worktree/branch name must be
  **derived deterministically** from the plan-ref.
- **PRIOR_ART §2 (no issue-numbers-as-linkage):** the *linkage* is the plan-ref, not a branch name.
  Using `pr_id` for the *local worktree dir / branch* is fine (ephemeral scaffolding, re-derivable),
  not a linkage mechanism.

---

## 3. Design decisions (locked — agreed with the user)

- **D1 — Worktree/branch name is derived: `plan-<pr_id>`.** Deterministic, re-derivable, idempotent.
  `pr_id` stays a **string**; a `.isdigit()` LBYL check guards any future `int()` (none needed in T4
  — the name is a string; the name is sanitized so `42 → plan-42`, `PROJ-123 → plan-PROJ-123`).
- **D2 — Resolve the *active* `cache.plan-ref`; no `[PLAN]` arg in T4.** `perk implement` (no
  positional) reads `cache.plan-ref` from the repo root = "implement the plan I just saved."
  Arbitrary plan `#N` resolution (a GitHub read) is **T5c `perk resume`**. No plan-ref ⇒ loud error.
- **D3 — Make the *generic* launcher plan-ref-aware (no bespoke command).** For `worktree:
  create`/`reuse` stages, when `--worktree` is omitted, derive the name from the active plan-ref and
  **materialize the plan-ref into the worktree**. `--worktree` stays an explicit override. This is
  registry-driven and **directly sets up T5** (submit/land/learn are `reuse` → same resolution).
- **D4 — `create` is idempotent (resume-safe).** If `plan-<pr_id>` already exists → **reuse +
  relaunch** (implement-as-resume); else create. (Replaces today's "error if exists.")
- **D5 — Cross-worktree state materialization is the crux.** A new `git worktree` shares `.git` and
  checks out the committed `.pi/settings.json` (so the extension loads), but its `.pi/workflow/` is
  fresh. The cold door writes **handoff + plan-ref into the worktree** so `session_start` (cwd =
  worktree) reconciles `active_plan_ref` and claims the run.
- **D6 — Gate scope: only when a perk workflow is active.** The dirty-repo gate engages **only when
  the session has an `active_plan_ref`** (rebuilt from the branch); otherwise it allows (perk never
  interferes with non-perk forks/switches — "authority follows the actor"). Within a workflow:
  **dirty ⇒ `{cancel:true}` + loud notify** (both modes — no proceed-anyway dialog in Phase 1);
  clean ⇒ allow. Fail-safe-headless is automatic (we never allow dirty).
- **D7 — Warm `/implement` is a guard-only command that *enforces* `warm: false`.** Registry stays
  `warm: false`. A small hand-wired `/implement`: if already in an impl worktree (read-write +
  plan-ref linked) → acknowledge "continue"; otherwise → refuse + point to `perk implement`. It is
  **not** a registry-generated warm door; it exists to make the cold-only contract structural
  (perk's "enforce, don't suggest" thesis), not system-prompt hope.
- **D8 — Registry `implement` I/O (as-built):** `requires: [cache.plan-ref]`, `reads:
  [cache.plan-ref]`, `writes: [session.workflow-state]` (the worktree session links the ref).
  `doors` unchanged. (`github.plan` is read by the **agent**, not the handler — kept out of the
  handler I/O.)
- **D9 — `--remote` stays blocked** (Phase 3) — the existing `launch_stage` guard already raises;
  T4 keeps it.

---

## 3.5 Spike findings (run during planning — the doc reflects reality)

Throwaway spike **S-B** (deleted after) drove a real bound offline session and confirmed the gate
mechanics end-to-end:

- **S-B1** — A gate registered with `pi.on("session_before_fork", …)` / `pi.on("session_before_switch",
  …)` is fired by `session.extensionRunner.emit({ type: "session_before_fork", entryId, position })`
  / `emit({ type: "session_before_switch", reason })`, which **returns** the handler's
  `SessionBeforeForkResult | undefined` (`{ cancel?: boolean }`). This is the offline test trigger.
- **S-B2** — The handler closes over `pi` (the `ExtensionAPI`) and calls
  `pi.exec("git", ["status","--porcelain"], { cwd: ctx.cwd })`; it resolves the **session cwd** and
  returns the real `ExecResult`. Dirty → non-empty `stdout` → `{ cancel: true }`; clean → empty →
  `undefined` (allow).
- **S-B3** — `{ cancel: true }` round-trips through `emit`; an allowed transition returns
  `undefined`. The handler signature is `(event, ctx) => Promise<Result | void>` — returning
  `undefined` (not `{cancel:false}`) is the idiomatic "allow."
- **Harness needs (folded into §8):** a `gitInit(cwd, { dirty })` helper (real `git init` + seed
  commit + optional uncommitted file) and an `emitLifecycle(event)` accessor over
  `session.extensionRunner.emit`.

---

## 4. Deliverables

### T4a — the cold door (Python)
- **`perk/launch.py`** — plan-ref-aware `resolve_worktree` (derive `plan-<pr_id>` when `--worktree`
  omitted for create/reuse stages; idempotent reuse on `create`) + plan-ref/handoff materialization
  into the worktree in `launch_stage`; a `resolve_plan_worktree_name(plan_ref)` pure helper.
- **`perk/cli/stages.py`** — unchanged signature if the generic command already forwards
  `--worktree=None`; confirm the dry-run JSON now includes the derived worktree + plan_ref.
- **`shared/registry.yaml`** — fill `implement` `requires`/`reads`/`writes` (D8).
- **`shared/contracts.md`** — §8.4 status note (T4 cold door materializes the worktree from the
  plan-ref).
- **`tests/test_launch.py`** — extend: plan-ref name derivation, no-plan-ref error, idempotent
  reuse, dry-run JSON shape; **a real-git integration test** for materialization.
- **`scripts/verify-p1-t4a.sh`** + `justfile`.

### T4b — the lifecycle gates (TS)
- **`extension/lifecycleGates.ts`** (NEW) — `registerLifecycleGates(pi)`: the dirty-repo gate on
  `session_before_switch`/`session_before_fork`, scoped to active workflows (D6); a pure
  `gateDecision(...)` helper for unit-testing the dirty/active/headless matrix without a subprocess;
  the guard-only `/implement` command (D7).
- **`extension/index.ts`** — call `registerLifecycleGates(pi)`.
- **`extension/testing/harness.ts`** — `gitInit(cwd, { dirty })` + `emitLifecycle(event)` (§8).
- **`extension/lifecycleGates.test.ts`** (NEW) — live gate matrix + `/implement` guard + pure-helper
  units.
- **`shared/contracts.md`** — a short lifecycle-gate paragraph (interior gate mechanics).
- **`scripts/verify-p1-t4b.sh`** + `justfile`.
- **`docs/index.md`** — index entry.

---

## 5. The cold door — a plan-ref-aware launcher

The launcher stays generic and registry-driven. The change is localized to worktree resolution +
state materialization; `exec pi` and the dry-run path are unchanged in spirit.

```python
# perk/launch.py  (pseudocode — durable anchors, not line numbers)

def resolve_plan_worktree_name(plan_ref: dict) -> str:
    """Deterministic, re-derivable worktree/branch name for a plan (D1)."""
    pr_id = str(plan_ref["pr_id"])
    Ensure.invariant("/" not in pr_id and pr_id not in ("", ".", ".."),
                     f"plan-ref pr_id unusable as a worktree name: {pr_id!r}")
    return f"plan-{pr_id}"

def resolve_worktree(*, repo_root, config, stage, worktree, materialize) -> ResolvedWorktree:
    if stage.worktree == "none":
        return ResolvedWorktree(path=repo_root, plan_ref=None)

    plan_ref = None
    name = worktree
    if name is None:                                   # D3: derive from the active plan-ref
        plan_ref = cache.read_plan_ref(repo_root)
        Ensure.not_none(plan_ref,
            "no saved plan — run /plan-save first (or pass --worktree NAME).")  # D2
        name = resolve_plan_worktree_name(plan_ref)
    Ensure.invariant("/" not in name and name not in ("", ".", ".."), "invalid worktree name")

    path = config.worktree_root / name
    if stage.worktree == "create":
        if path.exists():                              # D4: idempotent reuse (resume)
            ... # treat as reuse; do NOT error
        elif materialize:
            git.worktree_add(repo_root, path, branch=name, create_branch=True)
    else:  # reuse
        Ensure.path_exists(path, f"Worktree not found: {path}\nRun 'perk implement' first.")
    return ResolvedWorktree(path=path, plan_ref=plan_ref)

def launch_stage(...):
    # ... --remote guard (D9), cold_local door assertion (unchanged) ...
    resolved = resolve_worktree(..., materialize=not dry_run)
    wt = resolved.path
    rid = run_id.mint()
    if dry_run:
        ... # JSON now includes "worktree": str(wt) and (if any) "plan_ref": resolved.plan_ref
        return
    cache.ensure_layout(wt)
    cache.write_handoff(wt, rid, {"stage": stage.id, "mode": stage.mode})  # D5
    if resolved.plan_ref is not None:                                       # D5
        cache.write_plan_ref(wt, resolved.plan_ref)
    os.chdir(wt); os.execvpe("pi", ["pi", *pi_args], {**os.environ, "PERK_RUN_ID": rid})
```

Notes:
- The active plan-ref is read from **`repo_root`** (where the planning session saved it; `plan`/`save`
  are `worktree: none`). Running `perk implement` from inside a worktree is a flagged limitation.
- Materializing the plan-ref into the worktree is what lets the extension's `session_start`
  reconciliation (already built, T2b) link `active_plan_ref` from the worktree cwd — **no extension
  change is needed** for linkage.
- `ResolvedWorktree` is a tiny frozen dataclass (path + optional plan_ref) so `launch_stage` knows
  whether to materialize; avoids re-reading the plan-ref.

---

## 6. The lifecycle gates (TS interior)

```ts
// extension/lifecycleGates.ts (pseudocode)

export interface GateInputs { active: boolean; dirty: boolean; }
/** Pure policy (D6): cancel only inside an active perk workflow with a dirty tree. */
export function gateDecision(i: GateInputs): { cancel: boolean } {
  return { cancel: i.active && i.dirty };
}

export function registerLifecycleGates(pi: ExtensionAPI): void {
  const guard = async (ctx): Promise<{ cancel: true } | undefined> => {
    const active = rebuildWorkflowState(branch(ctx)).active_plan_ref != null;   // D6 scope
    if (!active) return undefined;                                              // don't interfere
    const res = await pi.exec("git", ["status", "--porcelain"], { cwd: ctx.cwd });
    const dirty = res.code === 0 && res.stdout.trim().length > 0;
    if (!gateDecision({ active, dirty }).cancel) return undefined;
    const msg = "perk: uncommitted changes — commit or stash before switching/forking this stage.";
    if (ctx.hasUI) ctx.ui.notify(msg, "warning"); else console.error(msg);     // fail-safe-headless
    return { cancel: true };
  };
  pi.on("session_before_fork", async (_e, ctx) => guard(ctx));
  pi.on("session_before_switch", async (_e, ctx) => guard(ctx));

  registerImplementGuard(pi);   // §7
}
```

- `branch(ctx)` = `ctx.sessionManager.getBranch() as unknown as BranchEntry[]` (the established
  pattern).
- If `git status` itself fails (`res.code !== 0`, e.g. not a repo), we **allow** (the gate is a
  hygiene guard, not a repo validator) — flagged behavior, matches "block only on a real dirty tree."

---

## 7. The guard-only warm `/implement` (D7)

```ts
function registerImplementGuard(pi: ExtensionAPI): void {
  pi.registerCommand("implement", {
    description: "Implement requires fresh context — use the cold door `perk implement`.",
    handler: async (_args, ctx) => {
      const st = rebuildWorkflowState(ctx.sessionManager.getBranch() as unknown as BranchEntry[]);
      const inImpl = st.mode === "read-write" && st.active_plan_ref != null;
      const msg = inImpl
        ? "perk: already implementing — continue in this session."
        : "perk: /implement is cold-only — run `perk implement` from a shell for fresh context.";
      if (ctx.hasUI) ctx.ui.notify(msg, inImpl ? "info" : "warning"); else console.error(msg);
    },
  });
}
```

The command never performs the plan→implement transition; it makes `implement.doors.warm: false`
*enforced at the surface* rather than merely absent. (`mode === "read-write"` alone is not enough —
`save` is also read-write; the `active_plan_ref != null` + being in a worktree is the impl signal.
For T4 we approximate "impl context" as read-write + a linked plan-ref; sharpened if it proves
loose.)

---

## 8. Harness additions (the offline test seam)

Per spike S-B, add to `extension/testing/harness.ts`:

- **`gitInit(cwd, { dirty }: { dirty: boolean }): void`** — `git init -q` + `user.email`/`user.name`
  config + a seed file + `add -A` + `commit -qm seed`; when `dirty`, write an uncommitted file. (Uses
  `node:child_process` `execFileSync`, test-only.)
- **`emitLifecycle(event)`** on `PerkSession` — thin wrapper over
  `session.extensionRunner.emit(event)` returning the result; typed for the `session_before_*` union.
- `scaffoldRepo` gains an optional `{ git?: { dirty: boolean } }` to `gitInit` the scaffold (or call
  `gitInit` separately after scaffolding — chosen at implementation for the cleanest call site).

These are dev-only (the `testing/` dir is excluded from the published tarball).

---

## 9. Contract & registry amendments

- **`shared/registry.yaml`** — `implement`: `requires: [cache.plan-ref]`, `reads: [cache.plan-ref]`,
  `writes: [session.workflow-state]` (D8). `doors` unchanged.
- **`shared/contracts.md` §8.4** — add a **Status (P1.T4)** note: the cold door derives
  `plan-<pr_id>`, creates the worktree+branch idempotently, and **materializes handoff + plan-ref
  into the worktree** so `session_start` links `active_plan_ref` there; the branch name is recorded
  into the plan-header at **submit** (T5).
- **`shared/contracts.md` (new short paragraph, near §8.3)** — **Session-lifecycle gates (T4):** the
  interior guards `session_before_switch`/`session_before_fork` with a dirty-repo check (`git status
  --porcelain` via `pi.exec`), **scoped to active workflows** (`active_plan_ref != null`), returning
  `{ cancel: true }` on a dirty tree (loud, fail-safe-headless). The proceed-anyway dialog +
  `git-checkpoint` stash are Phase 2.
- **Cumulative-gate hygiene:** if a prior gate hardcodes a value T4 changes, relax it to membership
  (the T2b/T3 precedent). None expected for T4 (implement I/O was empty), but check on the green
  sweep.

---

## 10. Tests + the verify gates

**T4a (`tests/test_launch.py`, CliRunner + a real temp git repo):**
- `resolve_plan_worktree_name` derives `plan-<pr_id>` for numeric + non-numeric ids; rejects unusable
  ids.
- `perk implement --dry-run` with an active plan-ref → JSON carries the derived `worktree` +
  `plan_ref`; no `--worktree` required.
- No `cache.plan-ref` → exit non-zero, "no saved plan" message (stable `error_type`).
- **Integration (real git):** scaffold a repo with a committed `.pi/settings.json` + an active
  plan-ref; stub `os.execvpe` (capture argv/env, don't exec); assert the `plan-<pr_id>` worktree +
  branch exist and the worktree's `.pi/workflow/` has the **handoff + plan-ref**; re-run → **reuse**
  (no error, no second branch).
- `--worktree NAME` override still works (back-compat for the existing launch tests).

**T4b (`extension/lifecycleGates.test.ts`, T1 harness, offline):**
- Pure `gateDecision` matrix (active×dirty).
- Live: dirty + active workflow (planted `active_plan_ref`) → `emitLifecycle(before_fork)` and
  `(before_switch)` both `{cancel:true}`; clean + active → allow; **dirty + no active workflow →
  allow** (scope); headless (`headful:false`) + dirty + active → cancel (fail-safe) with a stderr
  message (no notify).
- `/implement` guard: outside impl → warns "cold-only"; inside impl (planted read-write +
  plan-ref) → infos "continue."

Both `scripts/verify-p1-t4a.sh` / `verify-p1-t4b.sh` run the above offline and assert the registry
I/O; wired into `just verify` and `just ci`.

---

## 11. Explicitly out of scope for T4 (pointers)
- **Arbitrary plan `#N` resolution + the `[PLAN]` positional** → **T5c `perk resume`** (needs a
  GitHub read).
- **In-process `ctx.newSession` warm fresh-context** (the warm twin of the cold door) → Phase 2.
- **Proceed-anyway confirm dialog + `git-checkpoint.ts` stash-on-turn** → Phase 2.
- **`reconcile`/`sync`/conflict-fix git-state maintenance** → Phase 2.
- **Running `perk implement` from inside a worktree** → flagged limitation; assume repo-root
  invocation.
- **Submit recording the branch into the plan-header** → **T5a**.

---

## 12. Definition of done
- `perk implement` (no args) after a saved plan creates/reuses `plan-<pr_id>` and launches a fresh
  `pi` positioned in the worktree, which **links `active_plan_ref`** on `session_start`.
- The dirty-repo gate cancels switch/fork inside an active workflow with uncommitted changes (loud,
  fail-safe-headless) and never interferes outside a workflow.
- `/implement` enforces cold-only at the surface.
- Registry `implement` I/O filled; contracts §8.4 + the lifecycle paragraph amended.
- `just verify` (incl. p1-t4a + p1-t4b) + `just ci` green; the seam (T4a then T4b) each land green.

---

## 13. Outcomes (recorded on landing)

**Status: both seams landed, all green.** `just verify` runs t1…t7 + p1-t1 + p1-t2a + p1-t2b +
p1-t3 + **p1-t4a + p1-t4b**, all PASS; `just ci` green (ruff + ruff-format + ty + biome + tsc clean).
**121 pytest** (+13 in `tests/test_launch.py`) **+ 38 `node:test`** (+7 in `lifecycleGates.test.ts`).
The whole T4 gate runs **offline** (real git, no LLM/network/gh; `os.execvpe` stubbed in the
integration test).

**Built (matches §4–§9):**
- **T4a** — `perk/launch.py`: `ResolvedWorktree` dataclass + `resolve_plan_worktree_name()` (D1) +
  plan-ref-aware `resolve_worktree` (derive `plan-<pr_id>` when `--worktree` omitted; **idempotent
  reuse** on `create`; `GitError → UserFacingCliError` at the boundary) + `launch_stage`
  materializing **handoff + plan-ref into the worktree** and adding `plan_ref` to the dry-run JSON.
  `shared/registry.yaml` `implement` I/O (D8). `shared/contracts.md` §8.4 **Status (P1.T4a)**.
  `tests/test_launch.py` (+ a real-git integration test). `scripts/verify-p1-t4a.sh`.
- **T4b** — `extension/lifecycleGates.ts` (`gateDecision` pure helper + the `guardTransition`
  dirty-repo gate on both `session_before_*` hooks, scoped to active workflows + fail-safe-headless
  + the guard-only `/implement`); `extension/index.ts` wiring; `extension/testing/harness.ts`
  (`gitInit` + `emitLifecycle`); `extension/lifecycleGates.test.ts` (7 cases);
  `shared/contracts.md` lifecycle-gate paragraph; `scripts/verify-p1-t4b.sh`.

**Deviations / sharpenings (recorded, not retro-edited):**
- **A frozen Phase-0 test changed behavior, not just a gate value.** `test_cli_stages.py` asserted
  the old `implement` message "needs a worktree"; T4a intentionally changed it to "needs a saved
  plan" (no `--worktree` now derives from the plan-ref). Updated the test + renamed it
  `test_implement_requires_plan_ref` — forward-convergence over frozen history (the T2b/T3
  precedent), here applied to a *test* whose asserted behavior the turn legitimately superseded.
- **The harness `gitInit` had to gitignore more than `.pi/workflow/`.** Two test artifacts dirtied
  the tree and were not real edits: (1) `PERK_SELFCHECK` sentinel writes under `.pi/workflow/`
  (gitignored, as a real perk repo does), and (2) the planted session `.jsonl` — which
  `SessionManager.open` **rewrites on load** (`M planted-parent.jsonl`). Real pi session files live
  in the agent dir, not the repo tree, so `gitInit` ignores `*.jsonl` (+ `fake-perk.sh`). Net:
  only a genuine source edit dirties the tree. (Found via a throwaway in-tree probe — the failing
  "clean+active" case printed ` M planted-parent.jsonl`.)
- **`emit` fields used (per S-B):** `extensionRunner.emit({type:"session_before_fork", entryId,
  position})` / `({type:"session_before_switch", reason})` return `{cancel?:boolean} | undefined`;
  the gate reads `ExecResult.code` + `.stdout` and returns `{cancel:true}` or `undefined` (idiomatic
  allow). No deviations from the spike.
- **`--worktree` override skips plan-ref materialization** (it is the escape hatch / test seam);
  derived runs (the dogfood path) always materialize. Acceptable + flagged.

**Not built (correctly deferred):** arbitrary plan `#N` + the `[PLAN]` positional (T5c `perk
resume`); in-process `ctx.newSession` warm fresh-context (Phase 2); the proceed-anyway dialog +
`git-checkpoint` stash (Phase 2); running `perk implement` from inside a worktree (repo-root
invocation assumed); submit recording the branch into the plan-header (T5a).

**`save → implement` is closed.** `perk implement` materializes a fresh-context worktree from the
active plan-ref; the interior now refuses to orphan work at a stage transition. **T5** (PR
lifecycle + `perk resume`) is next — submit/land/learn are all `reuse` stages that reuse T4a's
plan-ref-aware launcher, and `perk resume` generalizes T4a's idempotent-reuse into arbitrary-plan
resolution.

**Tree at handoff (staged-clean for the user to commit):** new — `extension/lifecycleGates.ts`,
`extension/lifecycleGates.test.ts`, `scripts/verify-p1-t4a.sh`, `scripts/verify-p1-t4b.sh`,
`docs/planning/phase-1-turn-4.md`; modified — `perk/launch.py`, `tests/test_launch.py`,
`tests/test_cli_stages.py`, `extension/index.ts`, `extension/testing/harness.ts`,
`shared/registry.yaml`, `shared/contracts.md`, `justfile`, `docs/index.md`.
