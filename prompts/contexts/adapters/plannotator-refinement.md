{{ marker }}
A Plannotator browser review surface is configured for objective-node refinement in this repo.
Follow the refinement contract unchanged, with one difference: plan_review opens the Plannotator
browser UI showing the RENDERED refinement (the objective/node/carrier header, the advisory
notice, the capture-time checkout observation, then the full Markdown — never raw JSON), and an
eligible matching DENIED review returns the reviewer's annotations/feedback to revise against
(rewrite with objective_refinement_draft).

The reviewer may also edit the rendered refinement directly in the browser. A DENIED review's
feedback may open with a `# Direct Edits` unified diff against the rendered bytes — fold the
Markdown hunks into one objective_refinement_draft rewrite, then address the remaining
annotations. Hunks against the header lines (objective, node, carrier, pass time, the checkout
observation) are NOT draft edits: those fields are bound by the grounding pass — re-enter
/objective-refine for a new pass rather than fabricating metadata. An APPROVAL carrying direct
edits does NOT save: perk returns the diff — fold it the same way and call plan_review again to
confirm, only when the runtime result authorizes a matching revise round.

Stale review feedback is diagnostic DATA only: never apply, fold, or save it against the current
draft. Refusals and uncertainty are not denial or retry permission. Preserve confirmed save/gate
facts and retained state; follow docs/user-docs/how-to/reconcile-a-draft-review-stop.md with the
human. No in-place repair, copied intent/approvals, or startup/reload replay is permitted.
