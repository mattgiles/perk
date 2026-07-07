{{ marker }}
A Plannotator browser review surface is configured for objective authoring in this repo. Author
the objective read-only exactly as the objective-authoring contract describes; then add one
review step:

- Keep the working objective current with objective_draft — pass the FULL prose and the FULL
  structured roadmap each call (it rewrites the whole draft); never hand-write roadmap YAML.
- When the objective + roadmap are decision-complete, call the plan_review tool. The Plannotator
  browser UI shows the RENDERED objective (the prose + a roadmap table) derived from the draft
  artifact — never raw JSON.
- If the review is DENIED: revise per the returned annotations/feedback, rewrite the working
  draft with objective_draft, then call plan_review again.
- If the review is APPROVED: the objective is auto-saved to GitHub and the session leaves
  read-only — do NOT re-dump the objective as a final message and do NOT tell the user to run
  /objective-save; relay the save outcome (and any reviewer feedback) instead.
- If plan_review reports it was skipped or no review surface is available: present the complete
  objective + structured roadmap to the user; the human runs /objective-save (the manual
  failsafe).