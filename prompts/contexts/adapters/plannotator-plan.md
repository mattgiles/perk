{{ marker }}
A Plannotator browser review surface is configured for plan authoring in this repo. Follow the
plan-authoring contract unchanged, with one difference: plan_review opens the Plannotator
browser UI for the human reviewer, and a DENIED review returns the reviewer's
annotations/feedback to revise against. Approval auto-saves as usual; /plan-save stays the
manual failsafe when the review is skipped or no surface is available.