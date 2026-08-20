{{ marker }}
A Plannotator browser review surface is configured for objective authoring in this repo.
Follow the objective-authoring contract unchanged, with one difference: plan_review opens the
Plannotator browser UI showing the RENDERED objective (the prose + a roadmap table — never raw
JSON), and a DENIED review returns the reviewer's annotations/feedback to revise against
(rewrite with objective_draft).

The reviewer may also edit the rendered objective directly in the browser. A DENIED review's
feedback may open with a `# Direct Edits` unified diff against the rendered bytes — fold prose
hunks into the prose and roadmap-table hunks into the matching node updates, all via
objective_draft, then address the remaining annotations. An APPROVAL carrying direct edits does
NOT auto-save: perk returns the diff — fold it into the working draft with objective_draft and
call plan_review again to confirm.

When you call plan_review, perk may first ask the human whether to include a streamed reviewer
wave alongside the browser review. If they choose the wave, the call returns wave guidance
(`status: "wave_launched"`) INSTEAD of a verdict — follow that guidance in the same turn (launch
the wave, relay its findings, end your turn); the human's browser decision routes back
automatically, and you must not call plan_review again while that browser review is open.