---
title: "Review and authoring"
description: "Exact behavior for automated PR review, terminal and browser human triage, and browser draft-review doors."
sidebar:
  order: 3023
---

# Review and authoring

Six warm commands cover three distinct jobs: automated review that posts one reconciled result,
human-triaged PR review in a terminal or browser, and browser review of plan/objective drafts before
they are saved. Their companion tools are listed with each flow; the complete availability census
lives in [Model-facing tools](./model-tools.md).

## Automated PR review

### `/pr-review`

Run one automated wave with 2–4 fresh-context reviewer lanes. **Plan fidelity & completeness** is
mandatory; the parent chooses 1–3 additional angles from correctness, tests, quality, API design,
code organization, and idiomatic language use. Every lane returns an engine-validated report and
never posts.

The parent unions and deduplicates findings, derives one verdict, then posts once. Actionable work
becomes an advisory COMMENT review; a clean result becomes a 👍 reaction. Coverage is strict: the
wave applies one bounded retry, reports any remaining failure as incomplete, and
`post_pr_review` refuses a clean verdict with `incomplete_coverage`. Actionable findings may still
post with the incomplete-coverage note. An optional free-form focus note follows the command and
steers emphasis without removing plan fidelity or changing the 2–4 lane limit.

Companion tools:

- **`run_pr_review_wave`** — run 2–4 unique angles including `plan-fidelity`, thread the optional
  directive to every lane as data, apply one bounded retry, and return
  `{ complete, covered, retried, reports, failures }`. *Non-terminating.*
- **`post_pr_review`** — post the reconciled result through `perk pr review-post` and record
  `last_pr_review`; it enforces the incomplete-clean refusal. *Non-terminating.*

### `/pr-review-dynamic`

**Experimental.** This sibling delegates additional-angle selection to a fresh
`perk.review-angle-selector` lane that runs concurrently with mandatory plan fidelity. Module code
normalizes the selector output: fixed angles come only from
`correctness|tests|quality|api-design|code-organization|idioms`, unknown and duplicate entries are
dropped, forced angles run first, and at most three additional lanes survive. A failed,
low-confidence, or empty valid selection falls back to correctness plus tests.

The selector may propose one change-specific custom angle. Module code accepts only a non-reserved
3–32 character kebab-case slug and a whitespace-collapsed scope of at most 300 characters, and only
when it fits under the lane cap. Fixed-angle reviewers never see selector output; the custom lane
sees only its validated scope. Reconciliation and the incomplete-clean guard are the same as
`/pr-review`.

A free-form note rides `directive`; when it explicitly names fixed angles, the parent passes them
as `force_angles` instead. Companion tool:

- **`run_pr_review_dynamic_wave`** — run the selector-driven workflow with optional `directive`
  and 1–3 optional forced fixed angles, apply one bounded retry, and return
  `{ complete, covered, retried, reports, failures, selection }`. Selection metadata is in-session
  data and is never posted. *Non-terminating.*

The shared `post_pr_review` tool posts the reconciled result.

## Human-triaged PR review

### `/pr-review-terminal`

Open a human-in-the-loop adversarial review in the
[hunk](https://github.com/modem-dev/hunk) TUI:

```text
/pr-review-terminal [pr number|url] [focus note]
```

With a PR target, perk creates a detached read-only checkout for a foreign PR, never executes its
code, and streams batches from 2–3 adversarial reviewers into hunk while they run. `claimed-intent`
is mandatory. With no target and an active PR, the same flow reviews the current worktree's
since-base diff in place. Before `/submit`, it becomes a local surface-only review: no reviewers,
no GitHub posting, and your hunk notes return for in-session triage. A malformed `http(s)://` token
is a usage error rather than a focus note.

The door launches hunk through your interactive login shell when possible, prints
`cd <worktree> && hunk diff <base_sha> --agent-notes`, and copies it when clipboard support is
available. `PERK_TERMINAL_LAUNCH` and `PERK_CLIPBOARD_CMD` use unset for platform defaults, empty to
disable, or a custom command. If hunk does not connect, perk asks whether to keep waiting or
continue without it; there is no timer-based silent downgrade. Continuing without hunk displays an
in-session findings table.

You keep, drop, or reword each candidate, include your own hunk notes, and choose the event last.
Nothing posts before that triage. The door refuses headless sessions and a missing hunk CLI with an
install hint. Foreign review always cleans up its checkout.

Companion tools:

- **`start_review_wave`** / **`collect_review_wave`** — launch the 2–3 lane wave non-blocking and
  collect `{ complete, covered, reports, failures }`. Incomplete coverage is reported, never
  hidden. *Non-terminating.*
- **`submit_pr_review`** — validate with `dry_run: true`, then submit comments, body, and event as
  one atomic review through `perk pr review-submit`, recording `last_review`. It rejects formal
  approve/request-changes events on your own PR (`own_pr`), because GitHub rejects them, and
  refuses formal events headlessly because they require a blocking confirmation. `comment` posts
  only after conversational approval. This is the terminal door's sole posting path.
  *Non-terminating.*

### `/pr-review-browser`

Open the same human-in-the-loop review in Plannotator's browser code-review UI:

```text
/pr-review-browser [pr number|url] [focus note]
```

Foreign, own-PR, and pre-submit modes match the terminal door. The browser opens in the background,
reviewer batches arrive as badged `perk:<angle>` annotations, and the session remains usable while
you review. Before submit, it is local-only and nothing posts. Malformed URL-shaped targets refuse
rather than becoming focus text. If the local server never becomes ready, the flow degrades loudly
to the in-session table.

You normally post APPROVE or COMMENT, with inline comments, directly from the browser. Perk uses
`submit_pr_review` only for REQUEST CHANGES (unsupported by the UI) or when you explicitly ask it
to post. Own-PR formal verdict limits still apply. The door fails fast in a headless session or
when the Plannotator extension is absent; select `[providers] plan = "plannotator-plan"`, run
`perk init`, and restart Pi.

It shares `start_review_wave`, `collect_review_wave`, and `submit_pr_review` with the terminal door,
and adds:

- **`push_annotations`** — push each angle's batch to the door-primed surface with tool-owned
  mapping, global dedupe, hold-and-retry, and source-scoped replacement. It refuses with
  `no_surface` outside a browser door opened by perk. *Non-terminating.*

## Browser draft review

Both draft doors review the exact validated artifact primed by the command. They never accept
pasted draft text from the model. The shared companion tools are:

- **`start_draft_review_wave`** / **`collect_draft_review_wave`** — run 2–3 non-blocking
  `perk.draft-reviewer` lanes over the primed bytes and return
  `{ complete, covered, reports, failures }`. A supplied custom angle rides automatically.
  Coverage failures are reported with no retry. *Non-terminating.*
- **`push_annotations`** — deliver phrase-anchored findings to the same primed browser surface.
  *Non-terminating.*
- **`plan_review`** — process the human decision through the normal approval/denial/save seams.
  It terminates on a successful approval-driven save and otherwise leaves the session available
  for revision or recovery.

### `/plan-review-browser`

Review the working plan draft from plan mode, an objective-node planning session, or a save-stage
session. The browser opens on the exact draft bytes; 2–3 grounding/scope/decision-completeness/risk
lanes stream phrase annotations. Any argument text adds one custom review lane.

**APPROVE** applies Direct Edits to the plan artifact, then auto-saves. If the artifact changed
while the browser was open, approval refuses as stale and saves nothing; re-run the door. A failed
save is loud, keeps the session read-only, and falls back to `/plan-save`. **DENY** returns feedback
and any Direct Edits for a `plan_draft` revision round.

The door refuses when Plannotator is missing, the session is headless, the current stage is not a
plan-authoring stage, or the draft is missing or invalid. Create a valid artifact with `plan_draft`
and retry. If the browser cannot become ready, findings degrade loudly to the in-session table.

### `/objective-review-browser`

Review the rendered structured objective draft — prose, explicit `**Delivery:**` line, and roadmap
table — from `objective-author` or `objective-save`. The browser and reviewer wave otherwise behave
like plan review, including the optional custom lane.

**APPROVE** normally auto-saves and exits read-only, but Direct Edits never auto-apply to an
objective: the browser edited rendered Markdown while save re-reads structured fields. An approval
with Direct Edits therefore saves nothing and becomes a revise round; fold the diff into
`objective_draft`, then re-review. A stale artifact also saves nothing. Failed save falls back to
`/objective-save`. **DENY** returns feedback for an `objective_draft` revision.

The door refuses when Plannotator is missing, the session is headless, the stage is not objective
authoring, or the structured draft is missing or invalid. It never reviews raw JSON, a pasted
parameter, or transcript text.

## Related

- **Do:** [How to review a foreign PR](../../how-to/review-a-foreign-pr.md) — run the human-triaged
  flow end to end.
- **Look up:** [Model-facing tools](./model-tools.md) — check every tool name and its stage/gate
  restrictions.
- **Look up:** [In-session commands & tools](../in-session.md) — return to the stable surface map.
