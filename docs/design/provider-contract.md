# Design: the provider contract — the abstract seam for the plan + todo providers

**Status:** design doc (Objective #115, Node 1.2)
**Motivation:** Node 1.1 (`docs/design/pluggability-taxonomy.md`, PR #117) established the
four-criteria test for a good plugin seam (C1 coherent surface, C2 stable internal contract, C3
behavior-preserving default, C4 low cross-coupling) and scope-fenced Objective #115 to exactly two
surfaces that pass all four — **plan** and **todo**. It deliberately stopped at the *verdict* and
handed forward: "Node 1.2 — the abstract provider contract for the plan and todo seams: the
operations and artifact boundary a provider must conform to." This doc is that hand-off. It defines,
**first-principles**, the abstract seam any pluggable provider must satisfy — the surface it owns
plus the perk-internal contracts it produces and consumes — and then characterizes the **plan** and
**todo** seams concretely against that abstract shape, naming perk's own
`planMode`/`planSave`/`toolGating` and `checkpoints` as the **reference providers**.

Like its sibling, this is a **prose design doc only**: it ships no code, no schema, and no
`shared/providers.yaml` — that shape, the adapter-shim architecture, and config-driven selection are
**Node 1.3**. This doc locks the *contract shape* (the dimensions a provider declaration must fill
and the conformance point for each seam), not the downstream machinery. Per the repo's "don't author
fiction for unbuilt components" rule, it stops at the abstract contract + the two reference
characterizations and points forward to 1.3. No source files, registry, contracts, or config change
in this node — the contract it describes is realized in Phases 2–3 (Nodes 2.1/2.2/3.1), and its spec
lands in `shared/contracts.md` only when those handlers exist.

## The central thesis: a provider *is* its artifact contract, never its surface

The construction rule for every seam below — the C2/C4 finding from Node 1.1 restated:

> **A provider is defined by the perk-internal *artifact contract* it produces/consumes, never by
> its surface.** Downstream perk binds only to the artifact (C4 isolation); the provider's authoring
> UX is free to differ wildly across implementations. The seam *is* the artifact boundary plus the
> perk lifecycle hooks where perk hands control to the provider.

A conforming provider may present *any* authoring surface — perk's structured plan mode, a foreign
package's free-form prose editor, a wholly different checklist overlay — so long as its output lands
at the exact perk-internal artifact boundary downstream consumers read. The surface is the variable;
the artifact is the invariant.

## The seven dimensions every provider declaration fills

A provider seam is a declaration filling a fixed set of **dimensions**:

1. **Seam identity** — which seam (`plan` | `todo`) and the provider id. (The registry/id *shape* is
   Node 1.3's `shared/providers.yaml`; 1.2 names the dimension, not the file.)
   > **Reconciling note (shipped contract):** the `id == cache.plan-ref.provider` equivalence this
   > doc aspires to never shipped — in the shipped contract `cache.plan-ref.provider` is the **issue
   > backend** (the stamped `backend_id`, e.g. `"github"`), not the seam id. See
   > `shared/contracts.md` §8.10.
2. **Owned surface** — the user/session-facing surface the provider fully owns end-to-end (commands,
   shortcuts, flags, tools, status/widget UI, marker vocabularies). This is the dimension **free to
   vary** across providers; a foreign package's surface need not resemble perk's.
3. **Produced contract** — the perk-internal durable/transient artifact the provider must emit.
   **This is the conformance point**: whatever its surface, a conforming provider must land its
   output at this exact artifact boundary.
4. **Consumed contract** — the perk-internal artifacts the provider may read as input (and the gates
   that decide *whether* it is active).
5. **Lifecycle binding** — the perk extension hooks the provider plugs into (`session_start`,
   `session_tree`, `turn_end`, `before_agent_start`, `context`, `tool_call`) and the **shared perk
   primitives it composes but does not own** (notably the read-only tool-gate).
6. **Behavior-preserving default** — the perk-owned reference implementation that must remain the
   no-config default with **zero behavior change** (Node 1.1's C3); selecting a foreign provider is
   strictly opt-in.
7. **Isolation guarantee** — the explicit promise that downstream consumers bind only to dimension 3
   (the produced contract) and never reach into the provider's internals (C4); a swap ripples
   nowhere else.

### Generalization 1 — the produced contract spans two artifact tiers

The two seams force a generalization that 1.3's adapter architecture must accommodate: the *produced
contract* (dimension 3) can be **either**

- a **durable, cross-plane artifact** — a `cache.*` file plus a reconciled session field, written by
  one plane and read by both (the **plan** seam: `cache.plan-ref` + `active_plan_ref`); **or**
- a **transient, single-plane session-entry vocabulary** — a `perk:*` custom entry that rebuilds with
  the live branch and never touches the shared cross-plane record (the **todo** seam:
  `perk:checkpoint`).

The abstract contract accommodates both tiers. A provider's artifact may live in either, and Node
1.3's adapter shim must not assume a single storage shape.

### Generalization 2 — provider-owned surface vs. shared perk primitive

Load-bearing for 1.3's adapter shim: not everything a provider touches is *owned* by that provider.
The read-only **tool-gate** (`extension/toolGating.ts` `registerToolGating`) is a **shared perk
substrate** — also consumed by the read-only CI executor (P2.T5) — that the plan provider *composes*
via `enter`/`exit`, **not** a thing the plan provider *owns*. When a foreign plan provider is adapted
(Node 2.3), the perk-owned shim bridges the foreign authoring surface to perk's gate + `plan_save` +
`cache.plan-ref`; **the gate stays perk's.** 1.3/2.x must not mistake the gate for swappable.

## Characterizing the plan seam against the contract

| Dimension | plan seam anchor |
|---|---|
| **1 · Seam identity** | seam `plan`; reference provider is perk's own plan mode (the concrete id string is Node 1.3's registry concern, left unnamed here). |
| **2 · Owned surface** | the read-only authoring UX — `extension/planMode.ts` `registerPlanMode` (the `/plan` command, the `Ctrl+Alt+P` shortcut, the `--plan` flag), the `perk:plan-context` injection (`PLAN_CONTEXT_TYPE`, `PLAN_AUTHORING_CONTEXT`, `planContextContent`, `display: false`, the gather-then-plan contract); and the **save surface** — `extension/planSave.ts` `registerPlanSave` (the `plan_save` tool + the `/plan-save` command, plus `extractPlanMarkdown` as the command's fragile prose fallback). |
| **3 · Produced contract** | the **provider-agnostic `cache.plan-ref`** — see below; the conformance point. |
| **4 · Consumed contract** | the read-only tool-gate primitive (composed, not owned) — see below. |
| **5 · Lifecycle binding** | `before_agent_start`, `context`, `session_start` — see below. |
| **6 · Behavior-preserving default** | perk-owned `planMode` + `planSave` over `toolGating`; the no-config default. |
| **7 · Isolation guarantee** | downstream stages read only `cache.plan-ref` / `active_plan_ref`. |

**Produced contract — the conformance point.** The **provider-agnostic `cache.plan-ref`** (`PlanRef`
in `extension/cache.ts`; the Python twin `perk.plan.PlanRef`; `shared/contracts.md` §8.4). Written
via `savePlan` → `pi.exec("perk", ["plan-save", "--json", …])` — the canonical Python cold door; the
warm door **delegates**, never reimplements the GitHub write — persisted as
`.pi/workflow/plan-ref.json` (`planRefPath`/`writePlanRef`) and reconciled into the `active_plan_ref`
last-write-wins session field (`shared/contracts.md` §8.3). The payload shape (§8.4, canonical
`perk.plan.PlanRef`):

```
PlanRef {
  provider:       string          # the seam-identity provider id
  pr_id:          string          # a STRING — allows non-numeric ids (e.g. Jira PROJ-123)
  url:            string
  labels:         string[]
  objective_id:   string | null   # the linked objective node, when planning under an objective
  consumed_learn: int[]           # the perk:learn issues a docs plan consumes (closed on land)
}
```

The ROADMAP non-goal makes this the conformance point: *"the provider-agnostic plan ref is the sole
source of truth from day one"* (`docs/ROADMAP.md`, non-goals — no state encoded in branch names).
**The decision-complete plan → `plan_save` → `cache.plan-ref` path is the single thing any plan
provider must conform to**, whatever its authoring surface: perk emits structured plan markdown; the
retired `@tombell/pi-plan` borrow emitted free-form prose — both must terminate at `plan_save`.

**Consumed contract.** The read-only tool-gate primitive (`extension/toolGating.ts`
`registerToolGating`: the `ToolGating` API `enter`/`exit`/`isActive`/`syncFromState`, the
`READ_ONLY_TOOLS` allowlist, the `tool_call` destructive/safe backstop, the `perk:mode-context`
injection). `isPlanModeActive` reads the gate's own `mode === "read-only"` field. The gate is the
**shared substrate** (Generalization 2) — composed, not owned.

**Lifecycle binding.** `before_agent_start` (inject `perk:plan-context`), `context` (strip the
`[PLAN AUTHORING]` marker when the gate is off), `session_start` (`--plan` flag entry + gate sync).
Plus the **stage-field coupling break**: plan mode **defers** when
`rebuildWorkflowState(branch).stage === OBJECTIVE_AUTHOR_STAGE` (`extension/objectiveAuthor.ts`), so
an objective-author session — also read-only — gets its own authoring context instead of the plan
one. Wired in `extension/index.ts` in the order `registerToolGating` → `registerPlanMode` →
`registerPlanSave`, with the single gate instance shared across all three.

**Behavior-preserving default.** perk-owned `planMode` + `planSave` over `toolGating` is the
reference provider and the no-config default. The `@tombell/pi-plan` borrow was retired once perk
owned plan mode (P2.T2a) and is the **Node 2.3 foreign-adapter validation target**.

**Isolation guarantee.** Downstream worktree stages read **only** `cache.plan-ref` /
`active_plan_ref`, and only when the launched stage's registry `requires`/`reads` lists
`cache.plan-ref` (§8.3's stage-gated reconciliation — root `worktree: none` stages never inherit a
stale ref); nothing reads plan-mode internals.

## Characterizing the todo seam against the contract

| Dimension | todo seam anchor |
|---|---|
| **1 · Seam identity** | seam `todo`; reference provider is perk's own checkpoints. |
| **2 · Owned surface** | the implement-progress overlay — see below. |
| **3 · Produced contract** | the dedicated `perk:checkpoint` session entry (transient tier) — see below. |
| **4 · Consumed contract** | `cache.plan` (the materialized plan body) + `active_plan_ref` as the active-workflow gate. |
| **5 · Lifecycle binding** | `session_start`, `session_tree`, `turn_end` — see below. |
| **6 · Behavior-preserving default** | perk-owned `checkpoints`; opt-in + inert-by-default. |
| **7 · Isolation guarantee** | a dedicated, isolated session entry nothing else reaches into. |

**Owned surface.** The implement-progress overlay: `extension/checkpoints.ts` `registerCheckpoints`
(the `/checkpoints` command, the `ctx.ui.setStatus`/`setWidget` status + widget — `📋 done/total ·
▶n`, the `☑`/`▶`/`☐` glyphs — all `ctx.hasUI`-guarded), and the **`[WIP:n]` / `[DONE:n]` marker
vocabulary** the implement session emits (taught via the launch prompt + the `perk-implement` skill).

**Produced contract.** The dedicated **`perk:checkpoint` session entry** (`CHECKPOINT_TYPE`): the
ordered `CheckpointStep[]`-with-completion state, advanced by `[DONE:n]` and rebuilt with the
**scan-after-marker** discipline (`rebuildCheckpoint`, `markCompletedSteps`, `computeCurrent`,
`latestWipStep`). This is a **transient, TS-only session entry** (the second artifact tier of
Generalization 1) — kept **off** the shared `perk:workflow-state` record because progress is
high-churn (`shared/contracts.md` §8.3, "Checkpoints").

**Consumed contract.** `cache.plan` (the materialized plan body at `.pi/workflow/plan.md`,
`readPlanBody`/`planBodyPath`; **written by the Python cold door** `perk implement` →
`launch._materialize_plan_body`, read by TS), whose `## Steps` numbered list is parsed by
`extractSteps`; and `active_plan_ref` as the **active-workflow gate** (seed only when
`active_plan_ref != null`).

**Lifecycle binding.** `session_start` (**seed once** from `## Steps` when active + inert, then
rebuild), `session_tree` (rebuild), `turn_end` (advance on `[DONE:n]`, recompute `current` from
`[WIP:n]`). All hooks are best-effort + logged-not-thrown.

**Behavior-preserving default.** perk-owned `checkpoints` is the reference provider and the no-config
default. It is **opt-in + inert-by-default**: a prose plan with no `## Steps` yields no entry and no
crash (a coarse `📋 <stage>` status fallback, P2.T15). The retired `@juicesharp/rpiv-todo` borrow
(removed P2.T12) is the **Node 3.2 foreign-adapter validation target**.

**Isolation guarantee.** A dedicated, isolated session entry nothing else reaches into; the seam is
the `perk:checkpoint` entry plus the `## Steps` / `[DONE:n]`/`[WIP:n]` vocabulary.

## The two seams side by side

The contrast makes the two divergences the abstract contract spans legible at a glance — the
**artifact tier** and the **shared-primitive composition**:

| Dimension | **plan** (reference: `planMode`/`planSave`) | **todo** (reference: `checkpoints`) |
|---|---|---|
| **1 · Seam identity** | seam `plan` | seam `todo` |
| **2 · Owned surface** | `/plan` + `Ctrl+Alt+P` + `--plan`, `plan_save` tool/command, `perk:plan-context` | `/checkpoints`, status/widget overlay, `[WIP:n]`/`[DONE:n]` vocabulary |
| **3 · Produced contract** | **durable cross-plane** `cache.plan-ref` (file + `active_plan_ref` field) | **transient TS-only** `perk:checkpoint` session entry |
| **4 · Consumed contract** | the read-only tool-gate (shared substrate) | `cache.plan` `## Steps` + `active_plan_ref` gate |
| **5 · Lifecycle binding** | `before_agent_start` / `context` / `session_start`; **composes the tool-gate** | `session_start` / `session_tree` / `turn_end`; **composes no shared primitive** |
| **6 · Behavior-preserving default** | perk `planMode`+`planSave`; default; `@tombell/pi-plan` is the 2.3 target | perk `checkpoints`; default + inert-by-default; `@juicesharp/rpiv-todo` is the 3.2 target |
| **7 · Isolation guarantee** | stages read only `cache.plan-ref`/`active_plan_ref` (stage-gated) | a dedicated entry nothing else reads |

The two divergences: **artifact tier** (plan = durable cross-plane `cache.plan-ref`; todo =
transient TS-only `perk:checkpoint` entry — dimension 3) and **shared-primitive composition** (plan
composes the tool-gate; todo composes none — dimension 5).

## Forward hand-off (what 1.2 does NOT decide)

Per the repo's anti-fiction rule, the following belong to **Node 1.3** and are out of scope here:

- the `shared/providers.yaml` registry shape (provider id, seam, package spec, adapter module,
  default flag) and its parser in both planes;
- the perk-owned **adapter-shim** architecture (how a foreign package's surface is bridged to the
  produced/consumed contracts) and Pi package filtering to enable/disable extensions;
- config-driven selection (`[providers]` in `.pi/perk.toml`) and how `perk init` reads it and wires
  the chosen package(s) into `.pi/settings.json`.

1.2 locks the **contract shape and the two conformance points**; 1.3 locks how a provider is
*selected and wired*; Phases 2–3 implement the refactor + the first foreign adapters.

## References

- **Sibling design doc:** `docs/design/pluggability-taxonomy.md` (Node 1.1 — the four criteria
  C1–C4, the plan/todo verdicts, the forward pointer this doc answers).
- **Contracts:** `shared/contracts.md` §8.1 (`.pi/workflow/` layout; the `cache.*` vocabulary; the
  `cache.plan-ref` selector/binding duality), §8.3 (`perk:workflow-state` schema, the
  `active_plan_ref` stage-gated reconciliation, the Checkpoints subsection, tool-gating P2.T1,
  perk-owned plan mode P2.T2a), §8.4 (the provider-agnostic `cache.plan-ref` payload + the cold-door
  delegation pattern).
- **ROADMAP:** `docs/ROADMAP.md` — the non-goal "the provider-agnostic plan ref is the sole source of
  truth from day one"; open decision #1 (perk's GitHub-canonical workflow + objectives model as the
  differentiator) and the `@tombell/pi-plan` / `@juicesharp/rpiv-todo` borrow-then-retire history.
- **Plan seam:** `extension/planMode.ts` (`registerPlanMode`, `PLAN_CONTEXT_TYPE`,
  `PLAN_AUTHORING_CONTEXT`, `planContextContent`), `extension/planSave.ts` (`registerPlanSave`,
  `savePlan`, `isPlanModeActive`, `extractPlanMarkdown`, `PlanSaveDetails`), `extension/toolGating.ts`
  (`registerToolGating`, `ToolGating`, `READ_ONLY_TOOLS`, `isReadOnlyBashCommand`), `extension/cache.ts`
  (`PlanRef`, `planRefPath`/`readPlanRef`/`writePlanRef`), `perk/plan.py` (`PlanRef` — the canonical
  twin), `extension/objectiveAuthor.ts` (`OBJECTIVE_AUTHOR_STAGE`, the coupling break),
  `extension/index.ts` (the registration order, gate shared).
- **Todo seam:** `extension/checkpoints.ts` (`registerCheckpoints`, `CHECKPOINT_TYPE`,
  `CheckpointStep`/`CheckpointState`, `extractSteps`, `rebuildCheckpoint`, `markCompletedSteps`,
  `extractDoneSteps`/`extractWipSteps`/`latestWipStep`/`computeCurrent`, `isInert`), `extension/cache.ts`
  (`readPlanBody`/`planBodyPath`, `readHandoff`), the Python materializer `perk implement` →
  `launch._materialize_plan_body`.
- **Format precedent:** `docs/design/session-introspection.md` (the `# Design:` design-doc shape;
  like it, intentionally not listed in `docs/index.md`).
