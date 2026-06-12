---
name: perk-plan
description: Authoring a perk implementation plan and presenting it for review before the human saves it with the /plan-save command. Use when drafting, revising, or reviewing a plan in a perk repo, before it is saved to GitHub.
---

# Authoring a perk plan

A perk plan is the **canonical, decision-complete record** of a change. You author it (in plan
mode, read-only), then save it **verbatim** to GitHub. The save step is purely mechanical — **all
the judgment lives here**. Write the plan so an executor (a future session, or another engineer)
with **zero prior context** can implement it without guessing.

## Saving: present the complete plan; the human runs `/plan-save`

In interactive plan authoring your deliverable is the **complete plan as your final message** —
you never attempt to save it yourself (`/plan` is a user command you cannot run, and the
`plan_save` tool is hidden while plan mode is on). The flow is:

1. Explore read-only and converge on the plan (`/plan` on).
2. When the plan is decision-complete, write the **complete final plan as your last message** and
   present it to the user for review. The message must be the clean plan and nothing else — no
   preamble, no conversation — because the save scrapes it verbatim.
3. The **human** runs **`/plan-save`** when satisfied: it scrapes your latest message as the plan,
   saves it to GitHub, and on success automatically exits plan mode (the read-only → read-write
   boundary in one gesture).

When the `plannotator-plan` provider is selected, the review step replaces the present-and-wait
flow: keep the working draft current with **`plan_draft`** (the validated draft artifact is what
gets reviewed AND saved) and call the **`plan_review`** tool when the plan is decision-complete —
the Plannotator browser UI opens for the human. On a deny, revise per the returned annotations,
rewrite the draft with `plan_draft`, and call `plan_review` again. On approve, **the plan is
auto-saved** to GitHub and the session leaves read-only — no final-message re-dump, no human
`/plan-save`; relay the save outcome instead. (When that provider is not selected, or `plan_review`
reports it was skipped/unavailable, the default present-plan + human-`/plan-save` flow above
applies — the manual failsafe.)

The `plan_save` **tool** remains the canonical save surface for **orchestrated factory flows**
(objective-plan, learn-docs, replan), where the factory prompt explicitly instructs an autonomous
save — those flows are unchanged. There is no tag or marker convention to use — just author a
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
the implementer gets fine-grained checkpoints. Omit it for prose-only plans — checkpoints stay inert
(no crash, no nagging; the implement status bar instead shows a coarse stage label).

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

- ✅ **Function / class names** — "Update `savePlan()` in `extension/planSave.ts`"
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

## What the tool does (so you don't have to)

`plan_save` derives the title, splits the queryable header from the full body, creates the GitHub
plan issue idempotently, writes the local `cache.plan-ref`, and links this session. It is
deterministic — it **stores what you give it** and computes nothing about the plan's content. Give it
a complete plan; it will not reason on your behalf.
