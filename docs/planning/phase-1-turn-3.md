# Phase 1 · Turn 3 — `/plan-save` (the warm terminating door) + the planning skill

Detailed execution plan for **P1.T3** of [phase-1-plan.md](../phase-1-plan.md). T2a built the GitHub
plan write (Python cold door) and T2b made the ref durable + session-linked. T3 adds the **in-session
warm door**: the `plan_save` terminating tool (and a `/plan-save` command twin) that **wraps** T2's
storage from inside a live `pi` session, plus the **planning skill** that encodes plan-authoring
judgment. This is the **read-only → read-write boundary** and the turn that **closes `plan → save`** —
from here, perk can author and save the *rest* of Phase 1 as real perk plans (incremental dogfood).

> **Scope discipline.** T3 is **mostly TS** (the extension warm door) + **one packaged skill** +
> small contract/registry touches. It ships: the `plan_save` **tool** (`terminate: true`,
> `executionMode: "sequential"`, dual-surface return, `promptGuidelines`), a thin **`/plan-save`
> command** twin, one shared **`savePlan()` core** that **delegates the GitHub write to `perk
> plan-save --json`** (D2) and appends `active_plan_ref` for immediate in-session linkage, a
> `PERK_BIN`-resolved binary seam (robustness + test seam), and the **`skills/perk-plan/SKILL.md`**
> planning skill (declared via `package.json` `pi.skills`). It does **not** reimplement the GitHub
> write in TS, touch borrowed plan mode's internals, build a CLI read surface (`plan list/view`),
> add objectives, or transition to implement (that is **T4**'s cold door).

---

## 1. Objective & the gate

**Goal.** Give the agent a native, deterministic, terminating warm door to persist the plan it
authored — wrapping (not re-implementing) T2's storage — so a plan can be saved without leaving the
session, and the live session is immediately linked to the new ref. Encode the *judgment* of good
plan authoring in a skill, keeping the save tool purely mechanical (inference hoisting).

**Hard gate (must pass to land T3).** Via `scripts/verify-p1-t3.sh` on a fresh `perk init`-ed repo,
**fully offline** (no `gh`, no LLM, no network — the GitHub write is faked through `PERK_BIN`):

1. **The warm door drives the real delegation, offline** — a new `extension/planSave.test.ts` runs a
   bound `AgentSession` (the T1 harness) with `PERK_BIN` pointed at a **fake `perk`** that emits a
   canned `plan-save --json`; it proves the `plan_save` tool: writes the plan to a temp file, invokes
   `perk plan-save --plan-file <tmp> --run-id <claimed> --json`, parses the JSON, **appends
   `active_plan_ref`** to the live session (linked + read-back), and returns the **dual-surface**
   result (`content` + `details`) with `terminate: true`.
2. **The command twin works** — `/plan-save` extracts the plan markdown from the latest assistant
   proposal (pure `extractPlanMarkdown` helper, unit-tested), calls the same core, and renders a
   human confirmation; a missing plan fails **loud, non-fatal** with guidance.
3. **Failure is loud, never fatal** — when `PERK_BIN` resolves to nothing (ENOENT) or `perk
   plan-save` exits non-zero / emits unparseable JSON, the tool returns `isError: true` with a clear
   message and appends **no** linkage (headless-safe; never throws).
4. **The planning skill is shipped & declared** — `skills/perk-plan/SKILL.md` exists with a
   non-empty `description`, `package.json` declares `pi.skills: ["./skills"]`, `files` includes
   `skills/`, and the skill body carries erk's hard rule (**line-number references DISALLOWED →
   durable anchors**).
5. **The registry/contracts are filled** — `save.writes` is
   `[github.plan, cache.plan-ref, session.workflow-state]` (warm door appends the linkage), the
   registry self-check passes, and §8.3/§8.4 document the warm door.
6. **The pytest + node suites are green** (the new `planSave.test.ts`, the `extractPlanMarkdown` +
   `savePlan` units, and the unchanged prior suites).

`just verify` runs t1…t7 + p1-t1 + p1-t2a + p1-t2b **+ p1-t3**; `just ci` stays green.

---

## 2. Grounding & doc lineage (what governs T3)

- **The phase plan.** [phase-1-plan.md](../phase-1-plan.md) §P1.T3: the in-session **warm door**
  wrapping T2's storage (the read-only → read-write boundary); **terminating tool** (`terminate:
  true`) so the turn ends on save; cache-mutating tools `executionMode: "sequential"` to avoid
  `.pi/workflow/` races; **dual-surface return** (`content` for the model + `details` structured,
  doubling as forking-safe persisted state); `description`/`promptGuidelines` carry the safety
  contract structurally; the **planning skill** (judgment in the skill, mechanics in the tool; the
  skill's `description` is its only trigger) with erk's **line-numbers-disallowed** rule. *Closes
  `plan → save`; incremental dogfood starts here.*
- **The division of labor.** [cli-vs-pi.md](../cli-vs-pi.md): §2.1 the extension owns in-session
  workflow mutations (plan-save); §3 the planes coordinate through **durable state + process launch +
  the shared registry**, never in-process coupling; **§3.2 `--json` survives for machines that launch
  perk** (the warm tool is such a machine); §4.1 one stage implementation, the other door delegates;
  §4.1 the **plan→implement transition is the cold door's job** (fresh context) — so T3's save door
  does **not** transition to implement.
- **The predecessors.** [phase-1-turn-2a.md](./phase-1-turn-2a.md) (the Python `perk plan-save`
  cold door + its `--json` shape `{success, error_type, message, issue, plan_ref, cached, dry_run}` —
  the contract the warm door consumes) and [phase-1-turn-2b.md](./phase-1-turn-2b.md) (`cache.plan-ref`
  + the `active_plan_ref` reconciliation discipline the warm door reuses for its in-session append).
- **The storage model.** [PRIOR_ART.md](../PRIOR_ART.md) §2 (provider-agnostic ref) and the erk
  planning prior-art: `.prior-art/erk/docs/learned/planning/workflow.md` §"Line Number References Are
  DISALLOWED" (durable anchors: function names, behavioral descriptions, structural locations) and
  `plan-schema.md` / `plan-creation-pathways.md` for plan-body conventions the skill encodes.
- **The state-tier contract.** [contracts.md](../../shared/contracts.md) §8.3 (`active_plan_ref`
  verified-linkage tier — strict, read-back), §8.4 (the GitHub gateway + plan-ref payload the warm
  door persists).
- **The borrowed gate (studied, not coupled).** `@tombell/pi-plan` (installed in Phase 0) gates
  read-only by pinning the active tool set to 5 built-ins with **no injection point** — so a
  model-called `plan_save` tool is unreachable *during* plan mode; the save happens at the boundary
  (plan mode off), when the tool is reachable. The `/plan-save` **command** is the in-plan-mode /
  human trigger. (`@dreki-gg/pi-plan-mode`'s `submit_plan` is the dual-surface tool template;
  `@narumitw/pi-plan-mode` shows the force-include-the-tool pattern — both for the Phase-2 *own plan
  mode* turn, recorded as study-not-depend.)
- **The pi tool/skill API.** `extensions.md` / `skills.md` (installed under
  `@earendil-works/pi-coding-agent/docs`) — `pi.registerTool({ … terminate,
  executionMode, promptGuidelines, promptSnippet, execute })`; `execute` returns `{ content, details,
  isError?, terminate? }`; `pi.exec(cmd, args, {cwd, signal, timeout})` → `{ stdout, stderr, code,
  killed }`; `terminate: true` skips the follow-up LLM call when every result in the batch terminates.
  Skills: packages are discovered via `pi.skills` in `package.json`; only `SKILL.md` `description` is
  always in context, the body loads on demand.
- **Repo conventions in force.** biome + tsc + the T1 harness on the TS side; uv + ruff + ty on the
  Python side (the Python plane is unchanged this turn beyond contract/registry text). `cache.ts`
  stays a pure file primitive; the warm tool bridges via the `--json` contract, not a shared module.

---

## 3. Design decisions (locked — agreed with the user)

- **D1 — Command-first reachability + a parallel terminating tool.** Register **both** surfaces over
  one core: a **command `/plan-save`** (reachable under borrowed plan mode, which hides custom tools)
  and a **tool `plan_save`** (`terminate: true`, `executionMode: "sequential"`, `promptGuidelines`)
  — the canonical surface the phase plan describes, callable once plan mode is off and the forward
  path for Phase-2 owned plan mode. The tool takes the plan as a **parameter** (pure inference
  hoisting: the agent authored it, the tool stores it verbatim); the command **sources** the plan
  from the latest assistant proposal (best-effort, with a loud error when none is found).
- **D2 — The warm door *delegates* the GitHub write; it does not reimplement it.** `savePlan()`
  writes the plan markdown to a temp file and runs `pi.exec(perkBin, ["plan-save", "--plan-file",
  <tmp>, "--run-id", <claimed>, "--json"])`, then parses the **T2a `--json`** result. One GitHub-write
  implementation stays in Python (header/body composition, idempotency, label, error translation —
  already tested exteriorly). This honors "wrapping T2's storage" + "conventions submit/land reuse",
  uses two **sanctioned** coordination channels (process launch + the §3.2 machine-JSON surface), and
  keeps the agent calling a **native** tool (it never constructs the `perk --json` call). The
  pure-TS-`gh` alternative was rejected: it doubles `perk/plan.py` + `perk/github.py` in a second
  language and creates a hard cross-language metadata-block byte-format contract (drift surface).
- **D3 — `PERK_BIN` resolution (robustness + the offline test seam).** Resolve the perk executable as
  `process.env.PERK_BIN ?? "perk"`. In production this lets a launcher pin the exact binary; in tests
  the harness points it at a **fake `perk`** script emitting canned JSON, so the gate exercises the
  *real* delegation path (`pi.exec` actually runs it) fully offline. Per **S2**, `pi.exec` *returns*
  `code !== 0` (it does not throw) on a missing binary or non-zero exit, and `JSON.parse` throws on
  garbage stdout — so the guards are `res.killed || res.code !== 0` + a wrapped parse, surfacing a
  **loud, non-fatal** tool error (`isError: true`, naming the binary + exit code since ENOENT stderr
  is empty), with no linkage appended.
- **D4 — The warm door appends `active_plan_ref` immediately (D-registry consequence).** After a
  successful delegated save, the tool/command parses `plan_ref` from the JSON and
  `pi.appendEntry("perk:workflow-state", { active_plan_ref })` with a **strict read-back** (the §8.3
  verified-linkage tier; reuses T2b's `planRefsEqual` to stay idempotent), so the **live** session is
  linked without waiting for the next `session_start`. The Python subprocess already wrote
  `cache.plan-ref`; on the next reload the reconciliation sees file == linked → idempotent skip. This
  makes the **warm save stage** a direct writer of `session.workflow-state`.
- **D5 — No coupling to borrowed plan mode; no implement transition.** `/plan-save` never touches
  `@tombell/pi-plan`'s internals (we *borrow* it). It saves and **points to the next door** ("saved
  #N → url; transition with `perk implement <plan>` (cold, fresh context) or toggle `/plan` off to
  continue warm"). The plan→implement jump is **T4**'s cold door (must not inherit the planning
  conversation, cli-vs-pi §4.1).
- **D6 — Dual-surface return (dreki's `submit_plan` shape).** The core returns `content` (a short
  model/human confirmation, `Saved plan #N → <url>`) + `details` (structured `{ issue:{number,url},
  plan_ref, cached, existed }`, mirroring `--json`, doubling as branch-safe persisted state) +
  `terminate: true`. The **canonical** linkage stays the appended `active_plan_ref` entry +
  `cache.plan-ref`; `details` is the display/branch surface, not the source of truth.
- **D7 — Planning skill: judgment in the skill, mechanics in the tool.** Ship
  `skills/perk-plan/SKILL.md` (auto-discovered via the package's `pi.skills` — **no `init` change**,
  skills resolve from the installed perk package). Its `description` is the only trigger; the body
  encodes perk plan-authoring conventions and erk's hard rule: 🔴 **line-number references DISALLOWED
  → durable anchors** (function names, behavioral descriptions, structural locations). It composes
  with borrowed plan mode (tombell gates read-only; the skill shapes plan *content*) and describes
  the structure the deterministic tool stores.

---

## 3.5 Spike findings (run during planning — the doc reflects reality)

A throwaway probe extension + bound offline harness session (mirroring T1) verified the load-bearing
mechanics before writing structure:

- **S1 — `pi.exec` works offline in a bound session.** `pi.exec(bin, args, { cwd, signal })` runs a
  real subprocess with **no model turn / no network**; the result is exactly
  `{ stdout, stderr, code, killed }` (confirmed against `ExecResult`). `pi.exec` is on the
  closed-over `pi` (ExtensionAPI), not `ctx`.
- **S2 — Failure modes *return*, they do not throw.** A **missing binary** returns
  `{ code: 1, killed: false, stderr: "" }` (no exception); a **non-zero exit** returns its `code`
  (e.g. 3) with stdout intact. So `savePlan` guards with `res.killed || res.code !== 0` (no spawn
  try/catch), and **`JSON.parse(res.stdout)` is wrapped** (garbage stdout throws there). Because
  ENOENT yields **empty stderr**, the failure message must name the binary + exit code, not echo
  stderr alone.
- **S3 — A tool's `execute` is invocable from the harness.** `session.extensionRunner
  .getAllRegisteredTools()` lists `{ definition, sourceInfo }`; locate by `t.definition.name` and call
  `t.definition.execute(toolCallId, params, signal?, onUpdate?, ctx)`. A **synthesized ctx** with
  `{ cwd, hasUI, ui:{notify}, sessionManager: session.sessionManager, signal: undefined, isIdle }`
  (cast `as unknown as ExtensionContext`) is sufficient — that is what `invokeTool` builds.
- **S4 — `appendEntry` mid-`execute` lands on the branch.** `pi.appendEntry("perk:workflow-state",
  { active_plan_ref })` called inside `execute` is immediately visible in
  `session.sessionManager.getBranch()` (count == 1, correct ref) — so D4's in-session linkage +
  read-back works from the tool.
- **S5 — The return shape + `terminate` + plain-JSON-schema params are accepted.** `execute`
  returning `{ content:[{type:"text",text}], details:{…}, terminate: true }` round-trips intact;
  `executionMode: "sequential"` and a **plain JSON-schema** `parameters` object are accepted (no
  `typebox`/`Type` dependency needed — matches narumitw's style).

## 4. Deliverables

| Path | What |
|---|---|
| `extension/planSave.ts` (new) | The warm door: `savePlan()` core (delegate → parse → append linkage → dual-surface), the `extractPlanMarkdown` pure helper, and `registerPlanSave(pi)` wiring the **tool** + **command**. Node builtins + `pi.exec` only. |
| `extension/index.ts` | Call `registerPlanSave(pi)` from the extension entry (after the lifecycle handlers). |
| `extension/cache.ts` / `extension/workflowState.ts` | Reused as-is (`PlanRef`, `planRefsEqual`, `WORKFLOW_STATE_TYPE`, `rebuildWorkflowState`); no new exports unless a helper proves shared. |
| `skills/perk-plan/SKILL.md` (new) | The planning skill (frontmatter `name`/`description` + body: perk plan conventions + line-numbers-disallowed/durable-anchors). |
| `package.json` | Add `pi.skills: ["./skills"]`; add `skills/` to `files`; keep `!**/*.test.ts`. |
| `shared/registry.yaml` | `save.writes: [github.plan, cache.plan-ref, session.workflow-state]` (warm door appends the linkage). |
| `shared/contracts.md` | §8.3 (warm `/plan-save` appends `active_plan_ref` directly, strict read-back, in addition to the `session_start` reconciliation); §8.4 (the warm door wraps the cold `--json`; the read-only→read-write boundary). |
| `extension/planSave.test.ts` (new) | Harness-driven offline cases (tool delegate+link+terminate; command extract+save; loud failure on missing `perk`/bad JSON/no plan) via the `PERK_BIN` fake. |
| `extension/testing/harness.ts` | Add `invokeTool(name, params)` (locate the registered tool, call `execute` with a stub signal/onUpdate + the command ctx) and a `fakePerk(cwd, json)` helper (write an executable script, return its path for `PERK_BIN`). |
| `scripts/verify-p1-t3.sh` + `justfile` | The offline hard gate; appended to `just verify` after `verify-p1-t2b.sh`. |
| `docs/index.md` | Index entry for this turn (above T2b, reverse-chronological). |

No new runtime dependency. No `gh`/network/LLM anywhere in the turn or its gate.

---

## 5. The save core (`savePlan`) + delegation

`savePlan(pi, ctx, { plan, title? })` is the single implementation both surfaces call:

```
1. plan = plan.trim();  if empty -> loud error ("no plan markdown to save"), return isError.
2. runId = rebuildWorkflowState(getBranch()).run_id ?? "";   // tie idempotency to the claimed run
3. tmp = <mkdtemp>/plan.md; write `plan` (utf8).
4. perkBin = process.env.PERK_BIN ?? "perk";
   res = await pi.exec(perkBin, ["plan-save","--plan-file",tmp,"--run-id",runId,"--json"],
                       { cwd: ctx.cwd, signal });            // the sanctioned process-launch channel
   (finally: rm tmp)
5. if res.killed || res.code !== 0 -> loud error: `perk plan-save failed (exit ${res.code})` +
   stderr tail, or `${perkBin} not found` when stderr is empty (S2: ENOENT returns code 1, empty
   stderr, no throw). return isError, NO linkage. (No spawn try/catch needed — exec returns.)
6. parsed = try JSON.parse(res.stdout) catch -> loud error (unparseable), isError, NO linkage.
   if !parsed.success -> loud error (parsed.message / parsed.error_type), isError, NO linkage.
7. ref = parsed.plan_ref;  // {provider, pr_id, url, labels, objective_id}
   if !planRefsEqual(rebuildWorkflowState(getBranch()).active_plan_ref ?? null, ref):
       pi.appendEntry(WORKFLOW_STATE_TYPE, { active_plan_ref: ref });
       if !planRefsEqual(rebuildWorkflowState(getBranch()).active_plan_ref ?? null, ref):
           reportError("plan-ref read-back failed");        // strict tier: loud, non-fatal
8. return { content:[{type:"text",text:`Saved plan #${ref.pr_id} → ${ref.url}`}],
            details:{ issue: parsed.issue, plan_ref: ref, cached: parsed.cached, existed: parsed.issue.existed ?? null },
            terminate: true };
```

- **`reportError`** mirrors the lifecycle pattern (notify only when `ctx.hasUI`, always log stderr,
  **never throw**) — headless-safe. A delegation failure leaves the session **unlinked but running**.
- **Idempotency:** `--run-id` keys the Python idempotency (re-save returns the existing issue); the
  in-session append is guarded by `planRefsEqual`, so a re-save in the same session is a no-op.
- **No double cache write:** the subprocess writes `cache.plan-ref`; the tool only appends the
  session entry. The next `session_start` reconciliation sees file == linked → skip (T2b §6).

## 6. The two surfaces (one core)

- **Tool `plan_save`** — `pi.registerTool({ name:"plan_save", description, promptSnippet,
  promptGuidelines, executionMode:"sequential", parameters:{ plan: string (required, the full plan
  markdown), title?: string }, execute })`. `execute` calls `savePlan(...)` and returns its
  `{content, details, terminate}`. The `description` + `promptGuidelines` carry the **safety
  contract** structurally (e.g. *"Use plan_save only after the plan is decision-complete and the user
  has agreed; it creates the canonical GitHub plan and ends the turn. Pass the full plan markdown;
  never reference line numbers — use durable anchors."*). `executionMode:"sequential"` avoids
  `.pi/workflow/` races; `terminate:true` (returned by `execute`) ends the turn without an extra LLM
  round-trip.
- **Command `/plan-save [title]`** — `pi.registerCommand("plan-save", { description, handler })`. The
  handler runs `extractPlanMarkdown(ctx.sessionManager.getBranch())` (pure helper — the latest
  assistant text, or its fenced/`<proposed_plan>` block if present), then `savePlan(pi, ctx, {plan,
  title})`, then renders a human confirmation via `ctx.ui.notify` (headful) / stderr. No plan found →
  loud, non-fatal guidance ("no plan to save — propose a plan first, or call the plan_save tool with
  the markdown").
- **`extractPlanMarkdown(entries)`** — pure, unit-testable: walk the branch newest→oldest, return the
  most recent assistant message text (preferring a `<proposed_plan>…</proposed_plan>` or fenced block
  if present, else the whole message), else `null`. Best-effort and deterministic; keeps the agentic
  judgment in the skill, the extraction mechanical.

## 7. The planning skill (`skills/perk-plan/SKILL.md`)

```
---
name: perk-plan
description: Authoring a perk implementation plan to save with plan_save / /plan-save. Use when
  drafting or revising a plan in a perk repo, before saving it to GitHub.
---
```
Body (concise, mined from erk `planning/workflow.md` + `plan-schema.md`):
- **Structure** the plan stores cleanly (title `# `, summary, key changes, test plan, assumptions) —
  the shape the deterministic tool persists verbatim into the GitHub plan body.
- 🔴 **Line-number references are DISALLOWED** (they drift). ✅ **Required:** durable anchors —
  function/class names, behavioral descriptions, structural locations ("the `save` stage descriptor
  in `shared/registry.yaml`").
- **Decision-completeness:** resolve open choices before saving (no "should I proceed?" residue).
- **Inference hoisting:** the skill carries judgment; `plan_save` just stores — never expect the tool
  to reason about the plan.

Discovery: the perk package's `package.json` `pi.skills: ["./skills"]` makes the skill load in any
perk-init'd repo automatically (skills.md: packages discovered via `pi.skills`); only the
`description` sits in context until the agent reads the file. **No `init` change** needed.

## 8. `PERK_BIN` resolution + the harness fake (the offline seam)

- **Production:** `perkBin = process.env.PERK_BIN ?? "perk"`. Perk is present by construction in a
  perk-init'd repo (the CLI scaffolds it; every cold door already shells `pi`); `PERK_BIN` lets a
  launcher pin an exact path (e.g. a venv). ENOENT surfaces as a loud tool error naming the missing
  binary.
- **Tests:** `fakePerk(cwd, jsonObj)` writes an executable shell script (`#!/usr/bin/env bash; cat
  <<'JSON' … JSON`) that ignores its args and prints the canned `plan-save --json` to stdout (exit
  0), plus variants for **non-zero exit** and **garbage stdout**. The harness sets `PERK_BIN` to that
  path, so `pi.exec` runs the fake for real — exercising the actual delegate→parse→append path with
  **no network, no gh, no Python** even invoked. (The Python write itself is already covered by T2a's
  CliRunner suite; T3 must not re-test it.)
- **`invokeTool(name, params)`** (new harness method, verified by **S3**): locate the tool via
  `session.extensionRunner.getAllRegisteredTools().find(t => t.definition.name === name)`, then call
  `t.definition.execute("tc-test", params, undefined, undefined, ctx)` with a **synthesized ctx**
  (`{ cwd, hasUI, ui:{notify→captured}, sessionManager: session.sessionManager, signal: undefined,
  isIdle: ()=>true } as unknown as ExtensionContext`); return `{content, details, isError, terminate}`
  for assertions.

## 9. Contract & registry amendments

- **`shared/registry.yaml`:** `save.writes: [github.plan, cache.plan-ref, session.workflow-state]`
  (the warm door appends `active_plan_ref`). `doors.warm: true` already set; `requires`/`reads` stay
  `[]`; `run_id` unchanged. Update the inline comment to note T3 fills the warm-door behavior.
- **`shared/contracts.md`:**
  - **§8.3** — add: the warm `/plan-save` (T3) appends `active_plan_ref` **directly** in-session
    (strict read-back, idempotent by `(provider, pr_id)`), in addition to the `session_start`
    reconciliation (T2b) — both feed the same LWW field; a warm append makes the next reload's
    reconciliation a no-op.
  - **§8.4** — add a **Status (P1.T3)** note: the warm door **wraps** the cold `perk plan-save
    --json` (process-launch + the §3.2 machine-JSON surface), not a TS reimplementation; it is the
    read-only→read-write boundary; the plan→implement transition is the cold door (T4).

## 10. Tests + the verify gate

- **`extension/planSave.test.ts` (new — via the T1 harness, offline):**
  - **tool delegate + link + terminate:** `PERK_BIN`=fake (success JSON with `plan_ref` #42) →
    `invokeTool("plan_save", { plan })` → result `terminate === true`,
    `details.plan_ref.pr_id === "42"`, `content` mentions `#42`; `workflowState().active_plan_ref`
    equals the ref; the sentinel carries it.
  - **idempotent re-save (same session):** a second `invokeTool` with the same ref appends **no**
    second `active_plan_ref` entry (count == 1, `planRefsEqual` skip).
  - **command extract + save:** plant an assistant message carrying a `<proposed_plan>` block →
    `invokeCommand("plan-save")` → linked + a human notify captured.
  - **loud failure — missing perk:** `PERK_BIN`=/nonexistent → `isError === true`, message names the
    binary, **no** `active_plan_ref` appended, session still alive.
  - **loud failure — bad JSON / non-zero exit:** fake emits garbage / exits 1 → `isError`, no
    linkage.
- **`extension/workflowState.test.ts` or a new unit:** `extractPlanMarkdown` — picks the latest
  assistant text, prefers the fenced/`<proposed_plan>` block, `null` when absent.
- **`scripts/verify-p1-t3.sh`** (offline, fresh init'd repo, mirrors the existing verify style):
  (1) `node --test extension/planSave.test.ts` green with keys unset; (2) the skill exists with a
  non-empty `description` + `package.json` declares `pi.skills` and `files` includes `skills/` + the
  body contains the line-numbers rule; (3) the registry self-check passes with `save.writes ==
  [github.plan, cache.plan-ref, session.workflow-state]`; (4) `extractPlanMarkdown` unit green.
  Appended to `just verify` after `verify-p1-t2b.sh`. **No network, no `gh`, no LLM, no Python write.**
- **Cumulative-gate hygiene:** if any prior gate asserts `save.writes` by exact value, relax/update it
  to the new list (forward-convergence over frozen history — as T2b did for the T2a gate).

## 11. Explicitly out of scope for T3 (pointers)

- **The plan→implement transition** (fresh context, worktree materialization) — **T4** cold door.
- **Owning plan mode** (force-include the tool in the active set; internalize `@tombell/pi-plan`) —
  **Phase 2** (needs the gating primitive); record dreki/narumitw as study-not-depend prior art.
- **CLI read surface** (`perk plan list/view/log`) — later (cli-vs-pi §2.2 read surface).
- **Objectives / `objective_id` population** — Phase 2 (the field stays null).
- **PR-body craft, draft→ready, `address`** — Phase 2 (T5 builds thin submit/land/learn).
- **Re-testing the GitHub write in TS** — never; it lives in Python (T2a CliRunner).

## 12. Definition of done

The six gate checks in §1 pass via `scripts/verify-p1-t3.sh` on a fresh init'd repo **offline**; the
`plan_save` tool + `/plan-save` command share one `savePlan()` core that **delegates** the GitHub
write to `perk plan-save --json` (via `PERK_BIN`), appends `active_plan_ref` (strict read-back,
idempotent, headless-safe), and returns the dual-surface terminating result; failures are loud and
non-fatal; the planning skill is shipped, declared, and carries the line-numbers-disallowed rule;
§8.3/§8.4 are amended and `save.writes` is filled; `just ci` and `just verify` (t1…t7 + p1-t1 +
p1-t2a + p1-t2b + p1-t3) are green. **`plan → save` is closed: perk can now author and save the rest
of Phase 1 as real perk plans (incremental dogfood). T4 builds `/implement` + the cold door that
reads `cache.plan-ref` to materialize the worktree with fresh context.**

---

## 13. Outcomes (recorded on landing)

**Status: landed, all green.** `just verify` runs **t1…t7 + p1-t1 + p1-t2a + p1-t2b + p1-t3, all
PASS**; `just ci` green — ruff + ruff-format + ty + biome + tsc clean; **112 pytest** (unchanged —
T3 is interior-only; one Python test updated for the new `existed` field) **+ 31 `node:test`** (23
prior + 8 new: 6 live warm-door + 2 `extractPlanMarkdown`). The whole T3 gate runs **offline** — the
GitHub write is faked through `PERK_BIN`; no `gh` / LLM / network / Python-write is invoked.

**Built (matches §4–§8):**
- `extension/planSave.ts` (new) — `savePlan()` core (write temp plan → `pi.exec(perkBin, ["plan-save",
  "--plan-file", …, "--run-id", <claimed>, "--json"], {cwd, signal})` → parse → append
  `active_plan_ref` with strict read-back → dual-surface return), the pure `extractPlanMarkdown`
  helper, and `registerPlanSave(pi)` wiring the **`plan_save` tool** (`terminate: true`,
  `executionMode: "sequential"`, `promptGuidelines`, plain JSON-schema params) + the **`/plan-save`
  command** twin.
- `extension/index.ts` — calls `registerPlanSave(pi)`.
- `skills/perk-plan/SKILL.md` (new) + `package.json` (`pi.skills: ["./skills"]`, `files += skills/`).
- `shared/registry.yaml` — `save.writes: [github.plan, cache.plan-ref, session.workflow-state]`.
  `shared/contracts.md` §8.3 (warm direct-linkage paragraph) + §8.4 (**Status (P1.T3)** note).
- `extension/testing/harness.ts` — `invokeTool(name, params)` (synthesized ctx, per S3), `fakePerk()`,
  and a `plantSession(…, {assistantText})` option. `extension/planSave.test.ts` (new, 8 cases).
- `scripts/verify-p1-t3.sh` + `justfile`.

**Deviations / sharpenings (recorded, not retro-edited):**
- **`AgentToolResult` has no `isError` field** (the agent loop derives error only from a *throw*).
  So failures are signaled by **`details.ok = false`** (+ a `details.error`/`error_type`) and
  `reportError` (notify-if-UI + stderr), **never a throw** — which is *more* faithful than throwing
  (it preserves the dual-surface `details` on the failure path too). The §1 "`isError: true`"
  phrasing is realized as this soft-error contract; tests assert `details.ok === false` + `terminate
  !== true`.
- **A small T3 Python touch was needed for `details.existed`.** T2a's `--json` did not carry the
  issue's `existed` flag, so `_result_to_dict` now adds `issue.existed` (additive; the json-shape
  test was updated). This keeps `details.existed` honest (the idempotent-re-save signal) rather than
  always-null.
- **The sentinel is not rewritten by the warm append.** `.perk-t3.json` is a
  `session_start`/`session_tree` observability artifact; the tool's `appendEntry` lands on the branch
  (verified via `workflowState()` rebuild) but does not re-emit the sentinel — so the link test
  asserts the rebuild, not the sentinel (a dropped over-assertion from the first draft).
- **Cumulative-gate hygiene:** the T2b gate hardcoded `save.writes == [github.plan, cache.plan-ref]`;
  T3 appended `session.workflow-state`, so the (cumulative) T2b check was relaxed to **subset**
  membership (`{github.plan, cache.plan-ref} <= writes`) — forward-convergence over frozen history,
  as T2a's gate was relaxed by T2b.
- **`pi.exec` result fields used:** `code`, `killed`, `stdout`, `stderr` (per S1/S2). Failures
  *return* (no spawn try/catch); only `JSON.parse` is wrapped. ENOENT → empty stderr → the message
  names the binary + exit code.

**Not built (correctly deferred):** the plan→implement transition (T4 cold door); owning plan mode /
force-including the tool in the active set (Phase 2); CLI read surface; objectives; re-testing the
GitHub write in TS (it stays in Python).

**Tree at handoff (staged-clean for the user to commit):** new — `extension/planSave.ts`,
`extension/planSave.test.ts`, `skills/perk-plan/SKILL.md`, `scripts/verify-p1-t3.sh`,
`docs/planning/phase-1-turn-3.md`; modified — `extension/index.ts`, `extension/testing/harness.ts`,
`perk/cli/commands/plan_save_cmd.py`, `tests/test_plan_save.py`, `package.json`,
`shared/registry.yaml`, `shared/contracts.md`, `scripts/verify-p1-t2b.sh`, `justfile`,
`docs/index.md`.

**`plan → save` is closed.** perk can now author and save the rest of Phase 1 as real perk plans
(incremental dogfood). **T4** builds `/implement` + the cold door that reads `cache.plan-ref` to
materialize the worktree with fresh context.
</content>
</invoke>
