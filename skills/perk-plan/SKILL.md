---
name: perk-plan
description: Authoring a perk implementation plan before saving it with the plan_save tool or the /plan-save command. Use when drafting, revising, or reviewing a plan in a perk repo, before it is saved to GitHub.
---

# Authoring a perk plan

A perk plan is the **canonical, decision-complete record** of a change. You author it (in plan
mode, read-only), then save it **verbatim** to GitHub. The save step is purely mechanical — **all
the judgment lives here**. Write the plan so an executor (a future session, or another engineer)
with **zero prior context** can implement it without guessing.

## Saving: exit plan mode, then call the `plan_save` tool

The **robust** save path is the `plan_save` **tool** — you pass the finalized plan markdown in its
`plan` parameter, so the exact plan is stored (no guessing what "the plan" was). Because plan mode
hides custom tools, the flow is:

1. Explore read-only and converge on the plan (`/plan` on).
2. **Disable plan mode** (`/plan` off) so the `plan_save` tool becomes available.
3. Call **`plan_save`** with the complete plan markdown (and an optional `title`).

The `/plan-save` **command** is a fallback that scrapes your most recent message as the plan; it is
fragile (it can't tell a clean plan from conversation). It *can* run while plan mode is active, and
on a successful save it **automatically exits plan mode** (the read-only → read-write boundary in
one gesture). Prefer the tool. There is no tag or marker convention to use — just author a clean plan
and hand it to the tool.

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
tracks progress as your responses emit `[DONE:n]` markers:

    ## Steps
    1. First step description
    2. Second step description
    3. ...

Omit it for prose-only plans — checkpoints simply stay inert (no crash, no nagging).

Keep it concise and human- *and* agent-digestible. Resolve every open choice **before** saving — a
saved plan must leave **no decisions to the implementer** (no "should I…?" residue).

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
