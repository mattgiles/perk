---
title: "How to simplify a baroque draft"
description: "Run a Ponytail-mandated cut pass over the working plan or objective draft with /simplify-plan or /simplify-objective, then let the agent fold the proposal back before you review."
sidebar:
  order: 2138
sidebarGroup: "Core workflow"
---

# How to simplify a baroque draft

`/simplify-plan` and `/simplify-objective` send the working draft to one fresh read-only
`perk.simplifier` lane that cuts it down to its laziest working form under the Ponytail skill's
mandate. The lane's report comes back into your session and the agent rewrites the draft from it.
Running the door is your verdict that the draft is too baroque — the lane does not ask whether to
cut, only what.

**Prerequisite:** a plan-authoring session (`/plan`, `/objective-plan`, or the save stage) with a
working plan draft, or an objective-authoring session (`objective-author` / `objective-save`) with
a working objective draft. The borrowed Ponytail package installs at launch; without it the door
reports `skill-unavailable` and nothing runs.

## Steps

1. **Have the agent write the draft first.** The door cuts the working draft artifact — the one
   `plan_draft` or `objective_draft` wrote — never a pasted draft or the transcript.
2. **Pick an intensity and, optionally, a focus.** Run `/simplify-plan` (or `/simplify-objective`)
   with an optional first word:
   - `lite` — keep the draft's shape; the lane offers lazier alternatives for you to pick.
   - `full` — enforce the ladder (reuse, stdlib, native, already-installed before new); the
     proposal embodies the cuts.
   - `ultra` (the default) — deletion before addition; the proposal embodies the cuts and
     challenges the requirement itself.

   Anything after the intensity is a focus hint, for example
   `/simplify-plan full the config seams`. Without an intensity word the whole text is the focus.
3. **Keep working while it runs.** The door returns at once with `simplifier running…`; the result
   arrives as a message when the lane settles. One run is pending per session — a second
   invocation refuses until the first settles. There is no cancel: a hung lane settles on the
   wave's deadline.
4. **Read the fold-in.** The agent verifies each cut against the checkout, then:
   - at `lite`, lists the offered alternatives and waits for your picks;
   - at `full`/`ultra`, rewrites the draft from the proposal and names anything it restored
     (validation at a trust boundary, data-loss protection, security, accessibility, or your
     explicit requirement).

   Some cuts come back as separate decisions instead: a cut that narrows an objective node's
   deliverables (in an `objective-plan` session), a node merge or removal that would drop an
   adopted-issue or PR link, and any `ultra` challenge to the requirement itself.
5. **Iterate or review.** Nothing is saved and no review opens. Run the door again for another
   pass, or review the rewritten draft (`plan_review`, `/plan-review-browser`,
   `/objective-review-browser`) when you are satisfied.

## Choose the lane model

Set `simplifier = "<provider/id>"` under `[models.subagents]` in `.perk/config.toml`. When the key
is absent, the lane runs on the model in the agent definition's frontmatter. See
[Models and compaction](../reference/configuration/models-and-compaction.md#modelssubagents) for
the table.

## Expected result

One `[SIMPLIFY RESULT — …]` message carrying the lane's report and the fold-in guidance (for an
objective, also the structured fields the rewrite must keep), followed by a smaller working draft
rewritten through `plan_draft` or `objective_draft` — or, at `lite`, a short list of alternatives
awaiting your choice. A failed run instead posts one loud notice and injects nothing; run the door
again.

## Related

- **Look up:** [Review and authoring](../reference/in-session/review-and-authoring.md#draft-simplification)
  — the exact door behavior and refusals.
- **Look up:** [Models and compaction](../reference/configuration/models-and-compaction.md#modelssubagents)
  — the `simplifier` model key.
- **Do:** [How to delegate an investigation to perk.scout](delegate-an-investigation-to-perk-scout.md)
  — the other read-only lane an authoring session can use.
