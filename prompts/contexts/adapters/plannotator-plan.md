{{ marker }}
A Plannotator browser review surface is configured for plan authoring in this repo. Follow the
plan-authoring contract unchanged, with one difference: plan_review opens the Plannotator
browser UI for the human reviewer, and an eligible matching DENIED review returns the reviewer's
annotations/feedback to revise against.

The reviewer may also edit the plan directly in the browser. A DENIED review's feedback may
open with a `# Direct Edits` unified diff against the exact draft bytes you submitted — apply
those hunks faithfully in the plan_draft rewrite, then address the remaining annotations. On
eligible matching APPROVAL perk attempts verified write-back and saves edited bytes; if the patch
fails, only frozen original reviewed bytes may be saved with a warning. Follow the actual result.

Stale review feedback is diagnostic DATA only: never apply, fold, or save it against the current
draft. Refusals and uncertainty are not denial or retry permission. Preserve confirmed save/gate
facts and retained state; follow docs/user-docs/how-to/reconcile-a-draft-review-stop.md with the
human. No in-place repair, copied intent/approvals, or startup/reload replay is permitted.

When you call plan_review, perk may first ask the human whether to include a streamed reviewer
wave alongside the browser review. If they choose the wave, the call returns wave guidance
(`status: "wave_launched"`) INSTEAD of a verdict — follow that guidance in the same turn (launch
the wave, relay its findings, end your turn); the human's browser decision routes back
automatically, and you must not call plan_review again while that browser review is open.