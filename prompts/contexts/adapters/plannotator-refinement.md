{{ marker }}
A Plannotator browser review surface is configured for objective-node refinement in this repo.
Follow the refinement contract unchanged, with one difference: plan_review opens the Plannotator
browser UI showing the RENDERED refinement (the objective/node/carrier header, the advisory
notice, the capture-time checkout observation, then the full Markdown — never raw JSON), and a
DENIED review returns the reviewer's annotations/feedback to revise against (rewrite with
objective_refinement_draft).

The reviewer may also edit the rendered refinement directly in the browser. A DENIED review's
feedback may open with a `# Direct Edits` unified diff against the rendered bytes — fold the
Markdown hunks into one objective_refinement_draft rewrite, then address the remaining
annotations. Hunks against the header lines (objective, node, carrier, pass time, the checkout
observation) are NOT draft edits: those fields are bound by the grounding pass — re-enter
/objective-refine for a new pass rather than fabricating metadata. An APPROVAL carrying direct
edits does NOT save: perk returns the diff — fold it the same way and call plan_review again to
confirm.

A decision for a superseded review, or an APPROVE that arrives after the draft changed or after
the save destination changed (or cannot be read), is refused — nothing is saved; call
plan_review again.
