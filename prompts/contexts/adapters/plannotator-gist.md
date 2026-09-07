{{ marker }}
A Plannotator browser review surface is configured for gist authoring in this repo. Follow the
gist-authoring contract unchanged, with one difference: plan_review opens the Plannotator
browser UI showing the RENDERED gist (the title + scope line + prose — never raw JSON), and a
eligible matching DENIED review returns the reviewer's annotations/feedback to revise against (rewrite with
gist_draft).

The reviewer may also edit the rendered gist directly in the browser. A DENIED review's
feedback may open with a `# Direct Edits` unified diff against the rendered bytes — fold each
hunk into the matching gist_draft field (a `# <title>` heading hunk → `title`, a `Scope:` line
hunk → `scope`, prose hunks → `prose`) in one gist_draft rewrite, then address the remaining
annotations. An APPROVAL carrying direct edits does NOT auto-save: perk returns the diff — fold
it in the same way and call plan_review again to confirm, only when the runtime result authorizes
a matching revise round.

Stale review feedback is diagnostic DATA only: never apply, fold, or save it against the current
draft. Refusals and uncertainty are not denial or retry permission. Preserve confirmed save/gate
facts and retained state; follow docs/user-docs/how-to/reconcile-a-draft-review-stop.md with the
human. No in-place repair, copied intent/approvals, or startup/reload replay is permitted.
