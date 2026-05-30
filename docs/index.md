# perk docs — research & planning index

**perk** is a Pi-native rebuild of the [erk](https://github.com/dagster-io/erk)
plan-oriented engineering workflow — a Python CLI (the session *exterior*) plus a TypeScript
Pi extension (the session *interior*), sequenced so that **perk bootstraps itself**. The
project is in the **planning stage**; the documents below are the research and the plan, not
shipped behavior.

Read order for someone new: **ROADMAP** (the plan) → **foundation-open-questions** (the
locked decisions and their rationale) → the research inputs and pattern studies as needed.

## The plan (living documents)

| Doc | What it is |
|---|---|
| [ROADMAP.md](./ROADMAP.md) | **Start here.** The phased build plan: core thesis, context strategy, implementation-craft constraints, the seven **locked foundational decisions**, Phases 0–3 with **dogfood gates**, default-package strategy, non-goals, open decisions. |
| [foundation-open-questions.md](./foundation-open-questions.md) | The thirteen questions (Q1–Q13) that had to be settled before Phase 0, each with options, rationale, and the **recorded resolution**. This is the *why* behind the ROADMAP's "Foundational decisions (locked)" section — read it when you need the reasoning behind a decision. |
| [phase-0-plan.md](./phase-0-plan.md) | Phase 0 decomposed into seven landable turns (T1–T7), each with deliverables, an acceptance gate, and dependencies. The execution plan for the first phase. |
| [phase-0-turn-1.md](./phase-0-turn-1.md) | Detailed, implementation-level plan for **T1** (monorepo skeleton + the minimal `perk init`): grounded Pi packaging facts, target repo layout, a de-risking spike, the `init` spec, and runnable acceptance checks. |

## Research inputs (grounding; mostly stable)

| Doc | What it is |
|---|---|
| [RESEARCH.md](./RESEARCH.md) | The seed document: original problem analysis and the Pi-native architecture rationale the roadmap is built on. |
| [PRIOR_ART.md](./PRIOR_ART.md) | erk distilled into findings for perk (12 sections: state tiers, plan storage, objectives, PR operations, CI/review, context injection, hooks, capability model, etc.). |
| [erk-subagent-usage.md](./erk-subagent-usage.md) | How erk used subagents, and the governing principle perk adopts: a subagent is a **context-and-capability device, not a parallelism trick** (11 sections — route-don't-relay, double-delivery, the three never-delegate boundaries, model tiering). |

## Pattern studies (how to build it in Pi)

| Doc | What it is |
|---|---|
| [pi--best-practices.md](./pi--best-practices.md) | The **authoritative** patterns, from Pi's own `examples/` and the SDK (plan-mode recipe, presets, subagent spawn, handoff, goal/loop/review controllers, `createAgentSession`/`SessionManager`). The templates perk follows. |
| [agent-stuff-best-practices.md](./agent-stuff-best-practices.md) | Corroborating real-world patterns from `mitsuhiko/agent-stuff` (packaging idiom, structural command safety, `go-to-bed.ts`/`uv.ts`, `goal.ts` budget + completion-audit). Independent confirmation of the same bets. |

## Architecture / design principle

| Doc | What it is |
|---|---|
| [cli-vs-pi.md](./cli-vs-pi.md) | The CLI/extension separation: **boundary = the session; authority follows the actor.** The CLI owns the exterior, the extension owns the interior; they coordinate only through durable state, process launch, and a shared static schema. Defines **stage parity** (warm/cold-local/cold-remote doors from one stage registry). |

## Explainers (interactive HTML)

> **Status: not currently on disk — to regenerate.** Both were authored earlier this session
> / a prior session but are absent now and were never committed. Regenerate on request.

| Doc | What it is |
|---|---|
| `erk-explained.html` | A self-contained, interactive first-principles explainer of erk (layered diagrams, lifecycle stepper, glossary, theme toggle). |
| `perk-explained.html` | The companion explainer for perk, built around a **"follows erk ↔ departs from erk"** motif — what the Pi-native rebuild keeps and what it changes given control of Pi's execution context. |

## How the documents relate

- **ROADMAP § Foundational decisions (locked)** ⟷ **foundation-open-questions Q1–Q13** —
  the ROADMAP carries the summary; the open-questions doc carries the full options/rationale
  and any qualifications. Keep them in sync (the Q5 stage-set decision, for example,
  reshaped the ROADMAP's Phase-1 spine to `plan → save → implement → submit → land → learn`).
- **cli-vs-pi.md** feeds the ROADMAP's stage-registry decision (#3) and the CLI/extension
  split throughout.
- **PRIOR_ART / RESEARCH** are the source findings; **pi-- / agent-stuff best-practices** are
  the build templates; the ROADMAP cites all four at the point each pattern is used.

## External references (not in this repo)

- erk source — `~/dev/github/dagster-io/erk` (workflow being ported).
- erk learned-docs mirror — `.prior-art/erk/docs/learned/` (the prior-art corpus).
- Pi docs — `~/dev/docs/pi/` and the npm install under `@earendil-works/pi-coding-agent/docs`.
- Pi examples — `~/dev/github/earendil-works/pi/packages/coding-agent/examples/` (authoritative pattern source).
- `mitsuhiko/agent-stuff` — `~/dev/github/mitsuhiko/agent-stuff/` (corroborating patterns).
- `pi-subagents` — `~/dev/github/nicobailon/pi-subagents` (the delegation engine perk borrows in Phase 2).
