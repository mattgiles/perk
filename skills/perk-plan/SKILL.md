---
name: perk-plan
description: Authoring a perk implementation plan — draft with plan_draft, request a human review with plan_review (approval auto-saves), with present + /plan-save as the manual failsafe. Use when drafting, revising, or reviewing a plan in a perk repo, before it is saved to GitHub.
stages: [plan]
disable-model-invocation: true
---

# Authoring a perk plan

A perk plan is the **canonical, decision-complete record** of a change. You author it (in plan
mode, read-only), then save it **verbatim** to GitHub. The save step is purely mechanical — **all
the judgment lives here**. Write the plan so an executor (a future session, or another engineer)
with **zero prior context** can implement it without guessing.

## Saving: draft → review → approval auto-saves

In interactive plan authoring the default flow is **review-first** (`/plan` is a user command you
cannot run, and the `plan_save` tool is hidden while plan mode is on):

1. Explore read-only and converge on the plan (`/plan` on).
2. Keep the working draft current with **`plan_draft`** — the validated draft artifact is what
   gets reviewed AND saved.
3. Before requesting review, follow the `perk-grill` skill (read
   `.agents/skills/perk-grill/SKILL.md`) — stress-test the plan with the user until no decision
   residue remains.
4. When the plan is decision-complete, call the **`plan_review`** tool — the human reviews the
   plan in the configured review surface (perk's in-TUI editor review by default; the human may
   edit the plan there, and those edits are written back to the draft before the verdict).
5. On a **deny**, revise per the returned feedback, rewrite the draft with `plan_draft`, and call
   `plan_review` again. On an **approve**, the plan is **auto-saved** to GitHub and the session
   leaves read-only — no final-message re-dump, no telling the user to run `/plan-save`; relay
   the save outcome instead.

When the `plannotator-plan` provider is selected, the same `plan_review` call opens the
Plannotator browser UI instead of the in-TUI editor review — the flow is otherwise identical.
The reviewer may edit the plan directly in that browser: on a deny the feedback may open with a
`# Direct Edits` unified diff to apply faithfully in the `plan_draft` rewrite; on an approve
perk auto-applies those edits to the draft and saves them (no action needed).

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

### Optional: a `## Steps` list for checkpoints

If the work decomposes into discrete, ordered steps, add a `## Steps` section with a **numbered
list** (`1.`, `2.`, …). When present, perk seeds **checkpoints** from it during implementation and
tracks progress as the implement session emits `[WIP:n]` (started step n) and `[DONE:n]` (completed
step n) markers:

    ## Steps
    1. First step description
    2. Second step description
    3. ...

Genuinely multi-step work **should** include a `## Steps` list — you (the planner) control whether
the implementer gets fine-grained checkpoints. Prose plans (no `## Steps`) now get a **best-effort
generated checklist** at implement time (perk asks the session model for one and seeds checkpoints
from it; when generation is unavailable, checkpoints stay inert and the implement status bar shows
a coarse stage label). An authored `## Steps` list remains **preferred**: it is deterministic,
reviewable, and its numbering is visible in the plan issue.

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

**Consult prior learnings (optional).** Before drafting, skim the ambient `docs/learned/` routing
index and `read` any doc whose `read_when` cue matches your change — it may surface prior art or a
gotcha worth knowing. There is often nothing relevant; this is a check, not a requirement, and a
plan need not be grounded in learned docs.

**Consult the language house-style skill (code plans).** When the plan is code-heavy in one
language, read the repo's house-style skill(s) for that language (check your available skills)
before drafting — reviewers hold plans to those standards, and a denial-and-redraft costs far more
than the read.

## What the tool does (so you don't have to)

`plan_save` derives the title, splits the queryable header from the full body, creates the GitHub
plan issue idempotently, writes the local `cache.plan-ref`, and links this session. It is
deterministic — it **stores what you give it** and computes nothing about the plan's content. Give it
a complete plan; it will not reason on your behalf.
