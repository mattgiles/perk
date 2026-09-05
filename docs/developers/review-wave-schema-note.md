# Review-wave completion reports

The human-review wave modules define their report contracts in
`extension/waves/adversarialReviewWave.ts` and `extension/waves/draftReviewWave.ts`.

Both `ADVERSARIAL_REVIEW_REPORT_SCHEMA` and `DRAFT_REVIEW_REPORT_SCHEMA` require a top-level
`verdict` string, restricted to `clean` or `actionable`. A report omitting `verdict` is rejected
by the engine's schema validator and cannot count toward covered review lanes.

The final report contains the complete findings for its assigned angle. Provisional findings
may be sent to the parent before completion; the parent reconciles from the final report.
