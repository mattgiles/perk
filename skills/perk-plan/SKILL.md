---
name: perk-plan
description: Authoring a perk implementation plan in a perk plan session. Use when drafting, revising, or reviewing a perk plan before it is saved.
stages: [plan]
disable-model-invocation: true
---

# Authoring a perk plan

A perk plan is the **canonical, decision-complete record** of a change. You author it (in plan
mode, read-only), then save it **verbatim** to GitHub. The save step is purely mechanical — **all
the judgment lives here**. Write the plan so an executor (a future session, or another engineer)
with **zero prior context** can implement it without guessing.

## Saving: draft → review → approval auto-saves

The flow itself — keep the draft current with `plan_draft`, call `plan_review` when
decision-complete, a DENY returns feedback for a revise-and-re-review round, an APPROVE
auto-saves — is stated by your session's plan-authoring context; this section carries the detail
behind it.

- The posture is **review-first**: the `plan_save` tool is hidden while the read-only gate is on
  (and `/plan` is a user command you cannot run).
- Before requesting review, follow the `perk-grill` skill (read
  `.agents/skills/perk-grill/SKILL.md`) — stress-test the plan with the user until no decision
  residue remains.
- In the first-party in-TUI editor review the human may edit the plan directly; those edits are
  written back to the draft before the verdict.

When the `plannotator-plan` provider is selected, the same `plan_review` call opens the
Plannotator browser instead of the in-TUI editor — the injected `[PLAN ADAPTER: PLANNOTATOR]`
context carries that surface's delta (annotations on deny, `# Direct Edits` handling).

### The implement-here exit (no issue saved)

For simple changes the human may choose **implement here** instead of saving: the in-TUI review
offers a 4th verdict (“Implement here — no issue saved”), and the **`/implement-here`** command is
the manual gesture for the same exit (the only surface when the Plannotator review is selected —
its browser review returns only approve/deny). Either way the read-only gate comes off **without**
creating an issue, and you implement the reviewed plan directly in the current session/checkout —
**edits only**: do not commit, branch, or push unless asked; git gestures stay with the human.
perk's lifecycle doors (`/submit`, `/land`, `/learn`) do not apply (there is no plan issue or
plan-ref), and the draft artifact stays intact so `/plan-save` can still create the canonical
issue later. This exit is human-only — never choose it yourself — and it is unavailable in
objective-node planning sessions (a node-linked plan must always be saved).

If `plan_review` reports it was **skipped or unavailable** (headless session, the human dismissed
the review, no surface), fall back to the manual flow: write the **complete final plan as your
last message** — the clean plan and nothing else, no preamble — and the **human** runs
**`/plan-save`** when satisfied (it prefers the validated draft artifact, falling back to scraping
your latest message; on success it exits plan mode — the read-only → read-write boundary in one
gesture).

Orchestrated factory flows (objective-plan, the learn factories, replan, plan-from) are
review-first too — their gated read-only sessions hide the `plan_save` tool, and the
approval-driven save recovers each factory's link params (the node link, `consumed_learn`,
`adopt_from`) from the run's carriers. The `plan_save` tool remains the canonical programmatic
surface where it is active (read-write sessions — e.g. the warm learn doors, which pass
`consumed_learn` explicitly). There is no tag or marker convention to use — just author a
clean plan.

## Structure

Write Markdown with these sections (the first `# ` heading becomes the issue title):

```markdown
# <concise imperative title>

## Summary
What changes and why — one short paragraph.

## Key changes
The concrete edits, each anchored durably (see below). Group by file or component.

## Test plan
How the change is verified (commands, new/updated tests, the acceptance gate).

## Assumptions
Decisions taken and constraints relied on — so the executor inherits the reasoning, not just the steps.
```

### Optional: a `## Steps` list — the implementer's checklist seed

If the work decomposes into discrete, ordered steps, add a `## Steps` section with a **numbered
list** (`1.`, `2.`, …). The list seeds the implementer's live todo checklist: the implement
session creates one checklist item per step, in order, then owns the checklist dynamically as the
work unfolds:

    ## Steps
    1. First step description
    2. Second step description
    3. ...

Genuinely multi-step work **should** include a `## Steps` list — you (the planner) control the
initial shape of the implementer's checklist. For a prose plan (no `## Steps`), the implementer
derives a short checklist from the plan body itself. An authored `## Steps` list remains
**preferred**: it is deterministic, reviewable, and its numbering is visible in the plan issue.

Keep it concise and human- *and* agent-digestible. Resolve every open choice **before** saving — a
saved plan must leave **no decisions to the implementer** (no "should I…?" residue).

### No time or effort estimates

A perk plan describes **what changes and why**, never **how long it takes**. Do not include time
estimates, effort sizing, story points, velocity, or any other quantification of duration in a plan —
not in the title, the steps, or the prose. They add no implementation signal, drift the moment
anything shifts, and a saved plan is a canonical GitHub artifact where such guesses read as
commitments. Describe scope through the concrete edits themselves; let the work define its own size.

## 🔴 Line-number references are DISALLOWED

Line numbers drift as code changes and cause implementation failures. **Never** reference a line
number in a plan step. Use **durable anchors** instead:

- ✅ **Function / class names** — "Update `savePlan()` in `extension/factories/planSave.ts`"
- ✅ **Behavioral descriptions** — "Add a read-back check before appending the linkage"
- ✅ **Structural locations** — "In the `save` stage descriptor in `shared/registry.yaml`, add …"
- ✅ **File + context** — "In the `session_start` handler in `extension/index.ts`, after the run_id claim"
- 🔴 **Disallowed** — "edit `extension/index.ts:142`"

(Historical line numbers are fine *only* in a "Context / research" note documenting what you found,
never in an actionable step.)

## Ground the plan in evidence

Plan mode is read-only on purpose: **explore first, then write**. Anchor every change in something
you verified — an actual function name, a real file path, an observed behavior — not a guess. If a
high-impact ambiguity remains, ask before saving rather than encoding a guess.

**Consult prior learnings (first stop).** Your session context makes the `docs/learned/` walk
the first gathering step — skim the ambient cluster lines, open `docs/learned/index.md` (the
full per-doc cues), read the docs whose cues touch the change, and stop at diminishing returns.
Misses are common and fine: a plan need not cite or be grounded in learned docs — the attempt is
what matters, not the yield.

**Consult the language house-style skill (code plans).** When the plan is code-heavy in one
language, read the repo's house-style skill(s) for that language (check your available skills)
before drafting — reviewers hold plans to those standards, and a denial-and-redraft costs far more
than the read.

## What the tool does (so you don't have to)

`plan_save` derives the title, splits the queryable header from the full body, creates the GitHub
plan issue idempotently, writes the local `cache.plan-ref`, and links this session. It is
deterministic — it **stores what you give it** and computes nothing about the plan's content. Give it
a complete plan; it will not reason on your behalf.
