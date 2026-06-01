---
name: perk-plan
description: Authoring a perk implementation plan before saving it with the plan_save tool or the /plan-save command. Use when drafting, revising, or reviewing a plan in a perk repo, before it is saved to GitHub.
---

# Authoring a perk plan

A perk plan is the **canonical, decision-complete record** of a change. You author it (in plan
mode, read-only), then `plan_save` / `/plan-save` stores it **verbatim** to GitHub. The save tool is
purely mechanical — **all the judgment lives here**. Write the plan so an executor (a future session,
or another engineer) with **zero prior context** can implement it without guessing.

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
