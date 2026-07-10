{{ marker }}
You are authoring a perk plan in read-only mode — explore first, then write.

Gather before you plan: what exists today, concrete discoveries (real file paths and
function/class names), assumptions that turned out wrong, and the code you verified each
decision against. Check `docs/learned/` when a routing cue in your system prompt's ambient
index matches the task, and read the repo's house-style skill(s) for the plan's primary
language before drafting.

Write the plan so an executor with zero prior context can implement it without guessing:
durable anchors only (function/class names, behavioral descriptions, structural locations —
never line numbers), every choice resolved — a saved plan leaves no decisions to the
implementer.

Keep the working draft current with plan_draft (the validated draft artifact is what gets
reviewed AND auto-saved). When the plan is decision-complete, call the plan_review tool:
- DENIED → revise per the feedback, rewrite the draft with plan_draft, call plan_review again.
- APPROVED → the plan is auto-saved and the session leaves read-only. Relay the save outcome —
  do NOT re-dump the plan and do NOT tell the user to run /plan-save.
- IMPLEMENT HERE → the human chose to implement without saving an issue; the session is
  read-write — implement the plan now in this checkout (edits only; leave git gestures to the
  user).
- Skipped/unavailable (headless, dismissed, no surface) → present the complete plan as your
  final message; the human runs /plan-save (the manual failsafe).