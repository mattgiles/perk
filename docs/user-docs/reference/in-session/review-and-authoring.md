---
title: "Review and authoring"
description: "Exact behavior for automated PR review, terminal and browser human triage, and browser draft-review doors."
sidebar:
  order: 3023
---

# Review and authoring

Six warm commands cover three distinct jobs: automated review that posts one reconciled result,
human-triaged PR review in a terminal or browser (single PRs and whole stacks), and browser review
of plan/objective drafts before they are saved. Their companion tools are listed with each flow; the complete availability census
lives in [Model-facing tools](./model-tools.md).

## Automated PR review

### `/pr-review`

Run one automated wave with 2–4 selected fresh-context reviewer lanes. **Plan fidelity &
completeness** is mandatory; the parent chooses 1–3 additional angles from correctness, tests,
quality, API design, code organization, and idiomatic language use. Perk then appends exactly one
required automatic final `ponytail` lane outside that selection cap. It uses the same reviewer
model, directive, and report schema family; it is not selectable and must not be duplicated.
Ponytail exclusively owns standalone YAGNI, deletion, dependency/configuration removal, and
materially-smaller/native-replacement findings. Ordinary lanes mention simplification only when
inseparable from their assigned harm and never duplicate the standalone finding. Every lane
returns an engine-validated report and never posts.

The parent unions and deduplicates findings, derives one verdict, then posts once. Actionable work
becomes an advisory COMMENT review; a clean result becomes a 👍 reaction. Coverage is strict: the
wave applies one bounded retry, reports any remaining failure as incomplete, and
`post_pr_review` refuses a clean verdict with `incomplete_coverage`. Exact Ponytail package/skill
preflight failure is non-retryable: the child does not spawn or fall back to a same-named skill,
and the attempted `ponytail` lane remains explicitly uncovered with `skill-unavailable` while the
other lanes continue. Package files are expected to stay stable for the short pass; the child
rechecks the exact file/frontmatter as its first action, so post-preflight changes produce no
schema-valid report and remain incomplete rather than counting another source. Actionable findings
may still post with the incomplete-coverage note. An optional free-form focus note follows the
command and steers emphasis without removing plan fidelity or changing the 2–4 selected-angle
limit.

Before spawning, the parent resolves the active PR once. Every reviewer lane and retry
reads context only through `perk pr review-context --expected-pr <that-number> --json`; target drift
fails the lane. The resulting outcome is single-use and mutation-bound: starting any new valid pass
invalidates older evidence immediately, target-resolution failure leaves posting unavailable, and
one successful post consumes the record. Duplicate posts fail `review_wave_consumed`; pending
passes fail `review_wave_unavailable`. At mutation time `perk pr review-post` re-resolves the PR and
compares its private `expected_pr`; drift becomes `stale_review_wave`, invalidates the reports, and
requires a fresh review. Other posting failures leave the same outcome retryable.

Companion tools:

- **`run_pr_review_wave`** — run 2–4 unique selected angles including `plan-fidelity`, append the
  automatic final Ponytail lane, thread the optional directive to every lane as data, apply one
  bounded retry to retryable failures, and return `{ complete, covered, retried, reports,
  failures }`. *Non-terminating.*
- **`post_pr_review`** — post the reconciled result through `perk pr review-post` and record
  `last_pr_review`; it enforces incomplete-clean, pending, consumed, and stale-target refusals.
  After a recorded wave, `last_pr_review.angles` is the authoritative attempted manifest
  (including Ponytail), while `covered_angles` contains only successful schema-valid coverage.
  The PR comes from the cold-door result; callers never supply one. A standalone call before any
  valid wave uses caller-supplied angles for both fields. *Non-terminating.*

## Human-triaged PR review

### Native delivery and streaming status

For terminal/browser PR reviews (including stacks) and both browser draft-review doors, the
agent launches once, then ends its turn **without closing Pi**. An idle prompt does not mean
its wave was lost: native supervisor messages wake the parent to relay provisional findings,
and the matching workflow-completion notice triggers collection. Messages arriving during an
active turn queue normally; co-delivered batches are relayed before collection, without an
extra turn boundary. Only final typed reports authorize reconciliation, exactly once.

Each covered report requires `streamed: boolean`: true means the child successfully submitted
at least one nonempty finding batch, not proof of human-visible annotation delivery. False with
no findings is neutral **“no provisional batches (no findings)”**. False with findings produces
an in-session **“completion-only findings; no provisional batches”** warning naming those lanes.
`fyi` explains unavailable or partial streaming. Neither false case changes coverage or implies
by itself that the supervisor bridge is broken; these notices never become posted comments.

Browser reconciliation withdraws provisional annotations from uncovered lanes before replacing
final findings. Shared anchors get one merged annotation from valid final reports, owned by the
first contributing covered lane; its text retains the other contributors and their severity/
confidence. The highest severity is preserved. Plan views display the owning lane as the author;
PR views display its source badge. A custom lens that overlaps another lane may appear in the
merged text rather than as a separate custom card. Held clears/replacements remain pending, not
finalized; no failed lane's provisional output is treated as an authoritative report.

An early collection retains the pending wave and yields until matching completion. If the
bounded collection grace still expires after matching completion was observed, the flow stops
for owner diagnosis rather than polling or relaunching. Keep the host open for diagnosis.

### Temporary compatibility recovery

The two human-review wave families have a narrowly source-fenced workaround for pi-subagents
0.65.1's stale `Request timed out.` error after a successful native retry. Perk accepts a final
capture only when correlated artifacts prove successful retry, capture execution and settlement,
and the report passes the original requested schema. Collection then displays **“Compatibility
recovery (pi-subagents 0.65.1)”**, names the lane, and retains the original failure in attempt
receipt details. This is not a new wave attempt and does not recover provisional findings.

Missing reports, genuine failures, incomplete evidence, and changed or unsupported engine sources
remain failures. Other wave families, including `/pr-review`, are unchanged. The workaround does
not pin or modify pi-subagents and does not change the human posting/save gates.

### `/pr-review-terminal`

Open a human-in-the-loop adversarial review in the
[hunk](https://github.com/modem-dev/hunk) TUI:

```text
/pr-review-terminal [pr number|url] [focus note]
```

With a PR target, perk creates a detached read-only checkout for a foreign PR, never executes its
code, and streams batches from 2–3 selected adversarial reviewers plus one automatic final
source-bound Ponytail reviewer into hunk while they run. `claimed-intent` is mandatory; Ponytail is
outside the 2–3 input cap, uses the same model/directive/report family, and is never selected or
duplicated. A failed exact-source preflight leaves Ponytail explicitly uncovered with
`skill-unavailable` while other lanes continue. With no target and an active PR, the same flow
reviews the current worktree's
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

- **`start_review_wave`** / **`collect_review_wave`** — request 2–3 selected lanes plus required
  automatic final Ponytail non-blocking and collect `{ complete, covered, reports, failures }`.
  Start details return `launch: {requested, runnable, preflightFailures}`: only `runnable` lanes
  were accepted for spawning, while collection retains `requested` as the denominator. Incomplete
  coverage is reported, never hidden. *Non-terminating.*
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

### `/stack-review-browser`

Review an **entire PR stack** in one browser session over the combined diff (stack base → top
head):

```text
/stack-review-browser [objective id|issue URL|pr:<n>|PR URL] [focus note]
```

A bare number, `#n`, or issue URL targets a perk **objective's delivery train**; `pr:<n>` or a
PR URL walks the **base-ref chain** from any member PR (non-perk stacks included); with no
target, the session's active objective, then the worktree plan-ref's linked objective, are
tried in order. Single-PR targets refuse with a pointer at `/pr-review-browser`; forks, ambiguous
chains, and stacks deeper than 20 members refuse typed. perk fetches every member head in one
round trip, validates the commit topology fail-closed (a broken stack refuses before any
checkout), checks out the **top** head detached at `review-<top>`, and opens plannotator on the
combined diff. One adversarial wave reviews the combined diff (`stack: true` — reviewer children
fetch per-member context with `perk pr review-context --pr <top> --stack`).

**Posting is perk-side on this door** (the local-diff session has no attached PR, so there is no
browser platform-posting): after triage, perk routes each finding to the PR that introduced it
— body-level by default, inline only where straightforward — dry-run-validates **all** per-PR
batches, then posts one review per member PR bottom→top through `submit_pr_review` (the gate
ladder applies per call). Every real post appends a `{pr, event, at}` row to the `review_posts`
ledger; a mid-sequence failure stops and surfaces posted-vs-pending, and a resume skips confirmed
rows — tool-enforced: a repeat real post to a ledger-confirmed PR refuses with `already_posted`
(`allow_repost: true` is the deliberate override). Cleanup is `perk pr review cleanup --pr <top>`.

The cold twin is [`perk objective stack review`](../cli/objective.md#perk-objective-stack-review-objective)
— it materializes the same checkout and launches a dedicated session whose one
**`open_stack_review`** call (parameterless, single-use) opens the same browser flow.

## Browser draft review

Both draft doors review the exact validated artifact primed by the command. They never accept
pasted draft text from the model. The shared companion tools are:

- **`start_draft_review_wave`** / **`collect_draft_review_wave`** — request 2–3 selected
  non-blocking `perk.draft-reviewer` lanes over the primed bytes, followed by an optional supplied
  custom lane and exactly one required automatic final source-bound Ponytail lane, and return
  `{ complete, covered, reports, failures }`. Start details use the same nested
  `launch: {requested, runnable, preflightFailures}` truthfulness contract. Ponytail is outside the
  selected/custom menus and uses the same model/report family. An exact-source failure is
  `skill-unavailable`, uncovered, and never falls back. Coverage failures are reported with no
  retry. *Non-terminating.*
- **`push_annotations`** — deliver phrase-anchored findings to the same primed browser surface.
  *Non-terminating.*
- **`plan_review`** — process the human decision through the normal approval/denial/save seams.
  It terminates on a successful approval-driven save and otherwise leaves the session available
  for revision or recovery. On the Plannotator provider, an eligible call — the Plannotator
  extension actually loaded (the presence probe) plus a validated plan or objective draft
  artifact — first opens an in-TUI launch chooser — browser review **with** the
  reviewer wave or **without** it (Esc chooses without; the review always proceeds). Choosing
  the wave asks for an optional custom review angle, opens the same browser flow as the matching
  door below, and returns wave guidance (`wave_launched`) instead of blocking; the browser
  decision then routes back automatically. Gist review has no wave door and stays plain.

### `/plan-review-browser`

Review the working plan draft from plan mode, an objective-node planning session, or a save-stage
session. The browser opens on the exact draft bytes; 2–3 selected
grounding/scope/decision-completeness/risk lanes stream phrase annotations. Any argument text adds
one custom review lane, and exactly one automatic final core-Ponytail lane follows outside both
menus/caps.

The same flow is reachable from inside `plan_review`: on the Plannotator provider the tool's
launch chooser offers "Browser review + reviewer wave" every eligible round, with an optional
custom-angle input on the wave choice. `/plan-review-browser <angle text>` remains the manual
door for plans and `/objective-review-browser <angle text>` for objectives — the
subject-appropriate doors (the plan door refuses objective stages).

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
like plan review, including the optional custom lane and automatic final core-Ponytail lane.

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
