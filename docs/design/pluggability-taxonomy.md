# Design: pluggability taxonomy — what makes a good provider seam

**Status:** design doc (Objective #115, Node 1.1)
**Motivation:** Objective #115 wants perk's workflow elements to become **pluggable providers** —
swappable implementations behind a stable seam, so a foreign package (or an alternate perk
implementation) can stand in for perk's own. But "make everything pluggable" is a trap: most of
perk's surfaces are *not* good seams, and forcing a provider boundary through them would either
fracture a coherent responsibility or expose internals that other subsystems quietly depend on.
This doc establishes **first-principles criteria** for what makes a workflow element a good plugin
seam, **inventories** perk's surfaces against them, and **scope-fences Objective #115** to the two
seams that actually pass — **plan** and **todo** — handing the contract and adapter design forward
to Nodes 1.2 and 1.3.

This is a **prose design doc only**: it ships no code, no schema, and no `shared/providers.yaml`
(that shape is Node 1.3). It locks the *verdicts*, not the downstream machinery.

## Criteria

A workflow element is a good **plugin seam** *iff it satisfies all four* of the following. The
criteria are ordered from "is this even one thing" outward to "can it actually be swapped without
collateral damage."

- **C1 · Owns a coherent surface.** The element has **one nameable responsibility / UX it fully
  owns end-to-end** — not a slice of behavior smeared across several handlers, and not a
  cross-cutting substrate every stage touches. If you cannot say "this *is* the X" in a phrase,
  there is no surface to put a seam around.

- **C2 · Stable internal contract it produces or consumes.** The element exposes a perk-**internal**
  artifact boundary — a durable state key or a session-entry vocabulary — that *is* the seam. The
  contract is stable **independent of whatever implementation sits behind it**: downstream code
  binds to the artifact, not to how the artifact got produced. Without such a boundary there is
  nothing for a provider to conform to.

- **C3 · Behavior-preserving default exists.** perk's own implementation can remain the default with
  **zero behavior change**, and swapping in a foreign provider is strictly **opt-in**. If perk's
  implementation *is* the differentiating behavior — such that any substitute changes what perk
  fundamentally does — then the element is core, not a seam.

- **C4 · Low cross-coupling.** The element is swappable **without forcing changes in unrelated
  subsystems**. Downstream consumers depend only on C2's contract, **never on the element's
  internals**. If other surfaces reach *into* this one to do their job, every swap ripples.

**Disqualifier corollary.** An element that other surfaces consume by reaching into its internals
(**fails C4**), or that has no behavior-preserving foreign default because it *is* a perk
differentiator (**fails C3**), is a poor seam **regardless of how coherent its surface is** (however
strong its C1). A clean, nameable responsibility is necessary but not sufficient — the seam has to
survive substitution without leaking and without changing what perk is.

## Inventory

Each of perk's workflow surfaces, scored against C1–C4 with a verdict. Evidence anchors (file +
symbol, contract §-refs) follow the table.

| Surface | C1 | C2 | C3 | C4 | Verdict |
|---|---|---|---|---|---|
| **plan** | ✅ authoring surface | ✅ `cache.plan-ref` (§8.4) | ✅ perk planMode/planSave | ✅ consumers read only the ref | **Candidate (primary)** |
| **todo** | ✅ implement-progress overlay | ✅ `perk:checkpoint` + `## Steps`/`[DONE:n]` vocab | ✅ perk checkpoints | ✅ dedicated entry, inert-by-default | **Candidate (primary)** |
| CI executor | ✅ Run→Report oracle | ⚠️ `CiReport` internal, loop-bound | ✅ exists | ❌ tightly bound to parent loop + handoff | **Not** — already config-pluggable via `[ci]`; no foreign-provider value |
| address loop | ✅ classify-then-act | ❌ GitHub-API-shaped, not an internal artifact | ❌ no behavior-preserving foreign default | ❌ "act" = irreducible parent judgment | **Not** |
| objectives | ✅ goal-as-plan-factory | ⚠️ GitHub-issue + DependencyGraph | ❌ it *is* perk's differentiator | ❌ threads through plan-ref + reconcile | **Not** (core, not seam) |
| learn | ✅ capture→consolidate | ⚠️ `perk:learn` + `docs/learned` | ⚠️ no foreign analogue | ⚠️ pipeline still maturing | **Not (yet)** |
| bindings | ⚠️ it's a delivery substrate | ✅ `shared/bindings.yaml` | ✅ exists | ❌ cross-cuts every stage | **Not** (a config substrate, not a provider seam) |

**plan — Candidate (primary).** plan owns one coherent surface: the read-only authoring UX
(`extension/planMode.ts` `registerPlanMode` — `/plan`, `Ctrl+Alt+P`, `--plan`, the
`perk:plan-context` injection over the tool gate) and the save path (`extension/planSave.ts` — the
`plan_save` tool + `/plan-save` command, `isPlanModeActive`), gated by `extension/toolGating.ts`
(`registerToolGating`, the `enter`/`exit` read-only authority). Its **stable internal contract is
the provider-agnostic `cache.plan-ref`** (contracts §8.4; the ROADMAP non-goal commits that "the
provider-agnostic plan ref is the sole source of truth from day one"). Downstream worktree stages
read only that ref, never plan-mode internals (C4). perk's own planMode/planSave is the
behavior-preserving default (C3). **All four pass.**

**todo — Candidate (primary).** todo owns the implement-progress overlay
(`extension/checkpoints.ts` `registerCheckpoints`): the dedicated `perk:checkpoint` session entry,
seeded from the plan body's `## Steps` list and advanced by the `[WIP:n]`/`[DONE:n]` marker
vocabulary, inert-by-default on prose plans (contracts §8.3, "Checkpoints"). The seam is the
`perk:checkpoint` entry plus the `## Steps` / `[DONE:n]` vocabulary (C2) — a dedicated, isolated
entry that nothing else reaches into (C4). perk's checkpoints are the behavior-preserving default
(C3). **All four pass.**

**CI executor — Not.** It owns a coherent surface (the Run→Report stateless oracle —
`extension/ciExecutor.ts` `registerCiExecutor`, the `run_ci` tool + `/ci` command +
`--allow-project-ci`) and a behavior-preserving default exists (C1, C3 pass). But it is **already
config-pluggable** via the `[ci]` named-checks map in `.pi/perk.toml` — projects already swap *what
runs* without a provider boundary — and its `CiReport` is an internal, loop-bound shape rather than a
stable swap contract (C2 weak). Decisively, it is **tightly bound to the parent's
Run→Report→Fix→Verify loop and the T4 handoff contract** (C4 fails): a foreign "CI provider" would
have to re-implement that coupling for no added value. **Not a seam worth building.**

**address loop — Not.** Classify-then-act is a coherent surface (`extension/address.ts`
`registerAddress`, the `resolve_review_threads` tool + `/address`), and classification already rides
the borrowed `pi-subagents` engine running the perk-owned `perk.review-classifier` agent. But the
contract is **GitHub-API-shaped, not a perk-internal artifact** (C2 fails), there is **no
behavior-preserving foreign default** for it (C3 fails), and the "act" half is **irreducible parent
judgment** — the three never-delegate boundaries — which cannot be handed to a provider (C4 fails).
**Not a seam.**

**objectives — Not (core, not seam).** A coherent surface (the goal-as-plan-factory:
`extension/objective.ts`, `objectivePlan.ts`, `objectiveAuthor.ts`, `objectiveSave.ts` over the
deterministic `perk/objective.py` `DependencyGraph`), but it is **deeply coupled** to GitHub-issue
storage, dependency-graph selection, plan-ref `objective_id` threading, and reconciliation typing
(C4 fails). Above all it **is perk's differentiator** — the ROADMAP names "perk's GitHub-canonical
workflow + objectives model" as the reason perk exists (open decision #1) — so there is no
behavior-preserving substitute (C3 fails). Making it pluggable would mean making perk's identity
pluggable. **Core, not a seam.**

**learn — Not (yet).** A coherent capture→consolidate surface (`extension/learn.ts`
`registerLearn`, a thin marker clear; `extension/learnDocs.ts` `registerLearnDocs`, the `/learn-docs`
consolidation plan factory) with a real contract (`perk:learn` issues + `docs/learned/`). But the
**pipeline is still maturing** — its session-introspection consumer is unbuilt
(`docs/design/session-introspection.md`) — there is **no foreign analogue** to validate a provider
against, and the contract/coupling are not yet settled (C2/C3/C4 all marginal). Premature to seam.
**Not yet.**

**bindings — Not (a config substrate, not a provider seam).** bindings
(`extension/bindings.ts` + `extension/bindingDelivery.ts` `registerBindingDelivery`, reading
`shared/bindings.yaml` for trigger→skill `nudge`/`transclude` delivery) has a clean contract
(`shared/bindings.yaml`, C2) and a default (C3). But it is itself a **configuration / delivery
substrate that users already extend** — not a swappable implementation behind a surface — and it
**cross-cuts every stage** rather than owning one (C1 weak, C4 fails). You extend bindings by editing
config, which is the point; there is no provider to swap. **A config substrate, not a provider
seam.**

## Scope fence for Objective #115

**Objective #115 is scoped to exactly two seams: `plan` and `todo`.** They are the only surfaces that
**pass all four criteria** *and* have a **vetted foreign-package analogue already proven by perk's
own borrow-then-retire history**:

- **plan** ↔ `@tombell/pi-plan` — the read-only plan-mode borrow (`/plan`, `Ctrl+Alt+P`, `--plan`),
  carried in Phase 0 and retired once perk owned plan mode (the ROADMAP keeps it as a
  keep-wrap-vs-own decision).
- **todo** ↔ `@juicesharp/rpiv-todo` — the checklist overlay surviving `/reload` and compaction,
  retired **P2.T12** in favor of the perk-owned `perk:checkpoint` seam.

Those two foreign packages are real surfaces perk has already swapped against — the **empirical
reason** plan and todo are the validatable seams: the provider machinery built for #115 can be
exercised against an actual foreign implementation (Nodes 2.3 / 3.2), not a hypothetical one.

The **other five surfaces are explicitly out of scope**, each with its disqualifying criterion:

- **CI executor** — already config-pluggable via `[ci]`; tightly bound to the parent loop (C4). No
  foreign-provider value.
- **address loop** — GitHub-API-shaped contract (C2), no behavior-preserving default (C3), "act" is
  irreducible parent judgment (C4).
- **objectives** — it *is* perk's differentiator (C3); deeply coupled through plan-ref + reconcile
  (C4). Core, not seam.
- **learn** — pipeline still maturing; no foreign analogue to validate against (C2/C3/C4 marginal).
  Not yet.
- **bindings** — a configuration/delivery substrate that cross-cuts every stage (C1/C4), not a
  swappable provider.

**Hand-off forward.** This node locks *which* surfaces are seams; it does **not** author the seam
design. Two downstream nodes pick that up:

- **Node 1.2 — the abstract provider contract** for the plan and todo seams: the operations and
  artifact boundary a provider must conform to (built on `cache.plan-ref` for plan and the
  `perk:checkpoint` + `## Steps`/`[DONE:n]` vocabulary for todo).
- **Node 1.3 — adapter architecture + selection substrate**: how a chosen provider is wired in,
  including the `shared/providers.yaml` shape (deliberately *not* defined here).

Per "don't author fiction for unbuilt components," this doc stops at the verdict and the forward
pointer — Nodes 1.2 and 1.3 own their own content.

## References

- **Contracts:** `shared/contracts.md` §8.1 (`.pi/workflow/` layout, the `cache.*` state-key
  vocabulary), §8.3 (the plan-ref selector/binding duality, Checkpoints), §8.4 (the provider-agnostic
  plan-ref payload).
- **ROADMAP:** `docs/ROADMAP.md` — the "Default packages: bootstrap set vs permanent set" section
  (`@tombell/pi-plan` keep-wrap-vs-own; `@juicesharp/rpiv-todo` retired P2.T12 → perk checkpoints;
  `pi-subagents` borrow, open decision #6) and open decision #1 (perk's GitHub-canonical workflow +
  objectives model as the differentiator).
- **Inventoried surfaces:** `extension/planMode.ts`, `extension/planSave.ts`, `extension/toolGating.ts`
  (plan); `extension/checkpoints.ts` (todo); `extension/ciExecutor.ts` (CI executor);
  `extension/address.ts` (address loop); `extension/objective.ts`, `extension/objectivePlan.ts`,
  `extension/objectiveAuthor.ts`, `extension/objectiveSave.ts`, `perk/objective.py` (objectives —
  `DependencyGraph`); `extension/learn.ts`, `extension/learnDocs.ts` (learn);
  `extension/bindings.ts`, `extension/bindingDelivery.ts`, `shared/bindings.yaml` (bindings).
- **Foreign-package analogues / borrow-then-retire history:** `@tombell/pi-plan` (plan-mode borrow,
  retired in Phase 2) and `@juicesharp/rpiv-todo` (todo borrow, retired P2.T12) — the proven foreign
  surfaces Nodes 2.3 / 3.2 re-enable as adapted providers.
- **Format precedent:** `docs/design/session-introspection.md` (the `# Design:` / `**Status:**` /
  `**Motivation:**` / `## References` design-doc shape this doc mirrors; like it, intentionally not
  listed in `docs/index.md`).
