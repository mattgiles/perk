{{ marker }}
A Plannotator browser review surface is configured for objective authoring in this repo.
Follow the objective-authoring contract unchanged, with one difference: plan_review opens the
Plannotator browser UI showing the RENDERED objective (the prose + a roadmap table — never raw
JSON), and a DENIED review returns the reviewer's annotations/feedback to revise against
(rewrite with objective_draft). Approval auto-saves as usual; /objective-save stays the manual
failsafe when the review is skipped or unavailable.