{{ marker }}
A Plannotator browser review surface is configured for plan authoring in this repo. Author the plan
read-only exactly as the plan-authoring contract describes; then add one review step:

- Keep the working draft current with plan_draft — the validated plan-draft artifact is what gets
  reviewed AND auto-saved; the plan param is only a fallback for sessions that never wrote a draft.
- When the plan is decision-complete, call the plan_review tool. The Plannotator browser UI opens
  for the human reviewer.
- If the review is DENIED: revise per the returned annotations/feedback, rewrite the working draft
  with plan_draft, then call plan_review again.
- If the review is APPROVED: the plan is auto-saved to GitHub and the session leaves read-only.
  Do NOT re-dump the plan as a final message and do NOT tell the user to run /plan-save — relay
  the save outcome (and any reviewer feedback) instead.
- If plan_review reports it was skipped or no review surface is available: fall back to presenting
  the complete plan to the user; the human runs /plan-save (the manual failsafe).