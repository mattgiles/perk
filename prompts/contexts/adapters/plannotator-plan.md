{{ marker }}
A Plannotator browser review surface is configured for plan authoring in this repo. Follow the
plan-authoring contract unchanged, with one difference: plan_review opens the Plannotator
browser UI for the human reviewer, and a DENIED review returns the reviewer's
annotations/feedback to revise against.

The reviewer may also edit the plan directly in the browser. A DENIED review's feedback may
open with a `# Direct Edits` unified diff against the exact draft bytes you submitted — apply
those hunks faithfully in the plan_draft rewrite, then address the remaining annotations. On
APPROVAL perk auto-applies such edits to the draft and saves them (no action needed).