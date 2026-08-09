---
name: perk-domain-modeling
description: Build and sharpen a project's domain model — pin down domain terminology or a ubiquitous language (CONTEXT.md glossary), and route crystallized design decisions to the repo's durable records. Use when the user wants to pin terminology, record a design decision durably, or when another skill needs to maintain the domain model.
stages: [plan, objective-plan, objective-author, implement, address]
---

# Domain Modeling

Actively build and sharpen the project's domain model as you design. This is the *active* discipline — challenging terms, inventing edge-case scenarios, and writing the glossary and decisions down the moment they crystallise. (Merely *reading* `CONTEXT.md` for vocabulary is not this skill — that's a one-line habit any skill can do. This skill is for when you're changing the model, not just consuming it.)

## The glossary file

The glossary lives in a single `CONTEXT.md` at the repo root, in the format given in [CONTEXT-FORMAT.md](./CONTEXT-FORMAT.md). Create it lazily — when the first term is resolved. If a `CONTEXT-MAP.md` exists at the root, the repo has multiple contexts; follow it to the per-context `CONTEXT.md` (CONTEXT-FORMAT.md documents the map format).

## Where decisions are recorded

1. **Every resolved decision lands in the plan/objective draft.** In a perk repo the plan is the canonical decision-time record — its `## Assumptions` section exists exactly for "decisions taken and constraints relied on"; objectives carry theirs in the prose.
2. **A rare decision deserves a durable doc beyond the plan.** Escalate only when the three-part test holds (see "Escalate decisions sparingly" below). For those, find the repo's **canonical decision-record surface** — check `AGENTS.md` conventions and the repo's docs index for where design records / contract docs live — and amend *that*: directly in a write-capable session, or as an explicit plan step in a read-only one.
3. **No canonical surface? Don't invent one.** The saved plan's Assumptions remain the durable record — never scaffold a decision-doc system (`docs/adr/` or otherwise) into a repo that didn't ask for one.
4. **Post-landing distillation is not this skill's job.** Durable cross-cutting learnings from landed work reach `docs/learned/` through the `/learn` pipeline — never author those ad hoc.

## Read-only sessions

In perk's read-only doors (plan and objective authoring), file writes are blocked — do **not**
attempt to create or edit `CONTEXT.md` or other decision records there. Instead, record the
outcomes **in the plan/objective draft**: (a) an explicit "update `CONTEXT.md`" step carrying the
resolved term, and (b) for an escalated decision, an explicit "amend `<the canonical doc>`" step
carrying the resolved content — so the implement session lands them. Everything else in this
skill — challenging terms, sharpening language, stress-testing scenarios — applies unchanged.

## During the session

### Challenge against the glossary

When the user uses a term that conflicts with the existing language in `CONTEXT.md`, call it out immediately. "Your glossary defines 'cancellation' as X, but you seem to mean Y — which is it?"

### Sharpen fuzzy language

When the user uses vague or overloaded terms, propose a precise canonical term. "You're saying 'account' — do you mean the Customer or the User? Those are different things."

### Discuss concrete scenarios

When domain relationships are being discussed, stress-test them with specific scenarios. Invent scenarios that probe edge cases and force the user to be precise about the boundaries between concepts.

### Cross-reference with code

When the user states how something works, check whether the code agrees. If you find a contradiction, surface it: "Your code cancels entire Orders, but you just said partial cancellation is possible — which is right?"

### Update CONTEXT.md inline

When a term is resolved, update `CONTEXT.md` right there. Don't batch these up — capture them as they happen. Use the format in [CONTEXT-FORMAT.md](./CONTEXT-FORMAT.md).

`CONTEXT.md` should be totally devoid of implementation details. Do not treat `CONTEXT.md` as a spec, a scratch pad, or a repository for implementation decisions. It is a glossary and nothing else.

### Escalate decisions sparingly

Only route a decision beyond the plan when all three are true:

1. **Hard to reverse** — the cost of changing your mind later is meaningful
2. **Surprising without context** — a future reader will wonder "why did they do it this way?"
3. **The result of a real trade-off** — there were genuine alternatives and you picked one for specific reasons

If all three hold, route it to the repo's canonical decision-record surface per *Where decisions
are recorded*. If any of the three is missing, skip the escalation — the plan's Assumptions
section already carries the decision.
