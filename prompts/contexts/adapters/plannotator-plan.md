{{ marker }}
A Plannotator browser review surface is configured for plan authoring in this repo. Follow the
plan-authoring contract unchanged, with one difference: plan_review opens the Plannotator
browser UI for the human reviewer, and a DENIED review returns the reviewer's
annotations/feedback to revise against.

The reviewer may also edit the plan directly in the browser. A DENIED review's feedback may
open with a `# Direct Edits` unified diff against the exact draft bytes you submitted — apply
those hunks faithfully in the plan_draft rewrite, then address the remaining annotations. On
APPROVAL perk auto-applies such edits to the draft and saves them (no action needed).

When you call plan_review, perk may first ask the human whether to include a streamed reviewer
wave alongside the browser review. If they choose the wave, the call returns wave guidance
(`status: "wave_launched"`) INSTEAD of a verdict — follow that guidance in the same turn (launch
the wave, relay its findings, end your turn); the human's browser decision routes back
automatically, and you must not call plan_review again while that browser review is open.