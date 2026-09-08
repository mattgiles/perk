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
`post_pr_review` refuses a clean verdict with `incomplete_coverage`. Complete coverage is
necessary but insufficient for clean: the recorded pass also snapshots a minimum verdict from the
effective post-retry reports (a retry's replacement reports supersede the attempt they replace),
and a clean verdict over any effective actionable assessment — even one with empty findings — or
surviving finding is refused with `review_verdict_conflict` before anything is posted. The recorded
outcome survives that refusal, so the parent may post a reconciled actionable review against it or
post nothing; there is no override, and FYI notes never change the floor. Exact Ponytail package/skill
preflight failure is non-retryable: the child does not spawn or fall back to a same-named skill,
and the attempted `ponytail` lane remains explicitly uncovered with `skill-unavailable` while the
other lanes continue. Package files are expected to stay stable for the short pass; the child
rechecks the exact file/frontmatter as its first action, so post-preflight changes produce no
schema-valid report and remain incomplete rather than counting another source. Actionable findings
may still post with the incomplete-coverage note; without surviving actionable findings, nothing
posts and the parent reports failures in-session.

A schema-valid report is not necessarily a completed assessment. Reviewers return `blocked` when
context is invalid/unavailable or mandatory checks/material evidence cannot be completed. Missing,
null, or blank plan text blocks the required plan-fidelity lane; missing `plan_body` is malformed
for all lanes, while explicit null/blank is valid optional evidence for other angles. Blocked
reports become uncovered `lane-failed` failures before the one bounded retry. Partial concerns in
blocker diagnostics stay in-session and are never posted as findings. Optional supporting-file
read failures do not automatically block a review that has enough evidence to finish. An empty
diff is not itself a block. `blocked` is not a postable verdict.

An optional free-form focus note follows the
command and steers emphasis without removing plan fidelity or changing the 2–4 selected-angle
limit.

Before spawning, the parent resolves the active PR once. Every reviewer lane and retry
reads context only through `perk pr review-context --expected-pr <that-number> --json` — a
pointer envelope whose `body`/`diff`/`plan_body` are `{path, bytes, lines, max_line_bytes}` file
references the child pages with `read`/`grep` (an unreadable referenced file blocks the lane; a
long line, byte-sliced via `sed -n | tail -c +<offset> | head -c`, never does); target drift fails the lane. The resulting outcome is single-use and mutation-bound: starting any new valid pass
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
  `last_pr_review`; it enforces pending, consumed, incomplete-clean, and verdict-conflict
  refusals (in that order, before the cold door runs) plus the stale-target refusal at mutation
  time. A refused post records nothing; the verdict-conflict refusal keeps the recorded outcome
  for a reconciled actionable post.
  After a recorded wave, `last_pr_review.angles` is the authoritative attempted manifest
  (including Ponytail), while `covered_angles` contains only completed schema-valid assessments.
  The PR comes from the cold-door result; callers never supply one. A standalone call before any
  valid wave uses caller-supplied angles for both fields. *Non-terminating.*

### Shared report execution profile

Perk-owned report children select background mode through their definitions; calls omit child
`async` so the native workflow awaits each report. Root scheduling remains async/fresh with the
fixed report-only acceptance contract. Review-head paths are task data, not agent/extension
discovery roots: the native RPC context supplies the trusted calling session cwd, subject to
native worktree defaults for requests that do not opt into caller placement.

After exact-source skill preflight, each attempt captures the current parent read-only gate and
puts a `perk.parent-restrictions/1` boolean packet on every runnable child. Automated `/pr-review`
and `/address` classification opt into the code-owned `caller-read-only` policy: every child
(including Ponytail and review retries) gets `worktree: false` and a true restriction, strengthening
the captured parent value without changing the parent or handoff. Both read the actual caller's
local plan reference; Perk never copies plan authority into an allocated worktree. The classifier
still has no retry and stops on failure. Other report requests retain native placement defaults
and the captured boolean, including false; their schemas are unchanged. There is no new user
configuration key. Retries still sample the parent anew even under the stronger policy. Capture failure returns non-retryable `unavailable` before launch,
retaining any skill-preflight failures; all-skipped attempts do not capture. False grants no
write authority. The implemented runner consumer latches true or invalid packets as an effective
read-only floor before lifecycle work, independent of handoff mode and successful persistence.
Gate exit and branch navigation cannot clear it; the full tool-call allowlist backstop remains
active even when toolset narrowing fails. All ten report identities also suppress agent-scratch
provisioning and direct guidance through the separate advisory startup-prefix reader. Both producer
and consumer must be present with normal background-child Perk loading for this profile. It does
not certify user-shadowed definitions, foreground overrides, or missing consumer installations. Manual subagent calls and uninstrumented foreground
children are outside this channel, which is neither continuous revocation nor an OS sandbox.
Streaming and final-report coverage rules below are unchanged.

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

Each report also requires `blocked: boolean` (never defaulted — a missing or mistyped value is
schema-invalid). `false` is every completed angle, findings or not. `true` means the lane could
not complete its required review — the context fetch failed, a referenced context file was
unreadable, or the hunt stopped early — with empty `findings` and the blocker first in `fyi`. A
blocked lane is **uncovered**, never "no findings": collection reports `complete: false`, lists
the lane in `failures` as `lane-failed` with the `fyi` detail, drops it from `covered`, and the
browser reconcile clears its provisional annotations with the other uncovered sources. There is
no retry (the doors' zero-retry posture stands).

Browser reconciliation withdraws provisional annotations from uncovered lanes before replacing
final findings. Shared anchors get one merged annotation from valid final reports, owned by the
first contributing covered lane; its text retains the other contributors and their severity/
confidence. The highest severity is preserved. Plan views display the owning lane as the author;
PR views display its source badge. A custom lens that overlaps another lane may appear in the
merged text rather than as a separate custom card. Held clears/replacements remain pending, not
finalized; no failed lane's provisional output is treated as an authoritative report.

If the browser becomes ready after annotation work was held—or while a push is still in
flight—the door sends one continuation to finish delivery through the normal annotation tool.
This also works after wave collection, with no further reviewer message or human nudge needed.
The continuation flushes held final replacements/clears; it does not rerun the wave, collect
again, or repeat reconciliation. An empty idle queue causes no extra turn, and a closed or
superseded review does not trigger a delivery continuation.

An early collection retains the pending wave and yields until matching completion. If the
bounded collection grace still expires after matching completion was observed, the flow stops
for owner diagnosis rather than polling or relaunching. Keep the host open for diagnosis.

Engine-failed lanes remain failed, even when a capture file or successful-looking receipt exists.
Only successful, schema-valid reports in the workflow aggregate supply coverage.

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
reviews the current worktree in place against the merge-base of local HEAD and the **PR's current
base branch**, even if the stored plan base or repository default differs. A published stacked
layer is reviewed individually, not as the whole train. Local unpushed or uncommitted changes can
appear: this is not guaranteed byte-identical to the published PR diff.

The selected base is fetched best-effort (15-second timeout); an offline failure may use the cached
ref for that same branch, even if stale. Missing PR-base metadata or an unresolvable base refuses
before hunk launches or guidance is injected—never a fallback to a different branch. A merge-base
failure names the PR and branch and suggests retrying with an explicit PR number/URL. An older CLI
missing the required base field is a `bad_output` version-skew refusal.

Before `/submit`, it becomes a local surface-only review: no reviewers, no GitHub posting, and your
hunk notes return for in-session triage. Only this pre-PR mode uses the pinned plan base (or the
repository default when null); pre-PR stacked-base inference is unchanged. A malformed
`http(s)://` token is a usage error rather than a focus note.

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

Foreign, own-PR, and pre-submit mode selection matches the terminal door. In PR mode the browser
opens the **PR URL**: Plannotator selects the published PR diff, including an individual stacked
layer. Perk sends only `{cwd, prUrl}`, not a local diff type or default branch, and computes no
merge-base. The shared active-PR locator still requires base metadata; missing/malformed evidence
refuses before browser open or guidance. The browser opens in the background, reviewer batches
arrive as badged `perk:<angle>` annotations, and the session remains usable while you review.
Before submit, it is local-only and nothing posts; it uses the pinned plan base or repository
default, with no change to pre-PR stacked-base inference. Malformed URL-shaped targets refuse
rather than becoming focus text. If the local server never becomes ready, the flow degrades loudly
to the in-session table.

You normally post APPROVE or COMMENT, with inline comments, directly from the browser. Perk uses
`submit_pr_review` only for REQUEST CHANGES (unsupported by the UI) or when you explicitly ask it
to post. Own-PR formal verdict limits still apply.

In PR mode, an approval with no decoded annotations completes the review. If it includes a
nonblank note, the session retains that note verbatim as **nonblocking approval guidance**, inside
an explicitly untrusted DATA block. The approval stands; the note is optional advice, not a request
for changes, an edit/posting mandate, or confirmation that a platform review was posted. Missing or
blank notes keep the bare approval message. Closing without submitting takes precedence over any
approval or note; responses with annotations keep their existing triage behavior. Perk still posts
nothing by default.

The door fails fast in a headless session or when the Plannotator extension is absent; select
`[providers] plan = "plannotator-plan"`, run `perk init`, and restart Pi.

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

An approval with no decoded annotations completes the review and may return a nonblank note as
**nonblocking approval guidance**: the exact note is retained inside an explicitly untrusted DATA
block. The note is optional follow-up, not a request for changes or authority to edit or post.
Missing or blank notes keep the bare approval; closing without submitting takes precedence, and
annotation-bearing responses keep their existing triage behavior. Neither approval nor guidance
means a platform review was posted: this browser has no attached PR and posts nothing. You choose
separately whether to post per-PR COMMENT reviews or nothing.

**Posting is perk-side on this door** (the local-diff session has no attached PR, so there is no
browser platform-posting): if you choose to post after triage, perk routes each finding to the PR
that introduced it — body-level by default, inline only where straightforward — dry-run-validates **all** per-PR
batches, then posts one review per member PR bottom→top through `submit_pr_review` (the gate
ladder applies per call). Every real post appends a `{pr, event, at}` row to the `review_posts`
ledger; a mid-sequence failure stops and surfaces posted-vs-pending, and a resume skips confirmed
rows — tool-enforced: a repeat real post to a ledger-confirmed PR refuses with `already_posted`
(`allow_repost: true` is the deliberate override). Cleanup is `perk pr review cleanup --pr <top>`.

The cold twin is [`perk objective stack review`](../cli/objective.md#perk-objective-stack-review-objective)
— it materializes the same checkout and launches a dedicated session whose one
**`open_stack_review`** call (parameterless, single-use) opens the same browser flow.

## Browser draft review

Every draft review — the blocking `plan_review` tool (Plannotator or first-party, for plans,
objectives, gists and refinements) and both browser doors — runs the same four in-memory guards.
Nothing is persisted: there is no review record, no lock, no reconciliation procedure. **A browser
decision does not survive a Pi restart — re-run the door.**

1. **Reviewed bytes.** An approval saves only the bytes the human saw. If the working draft
   changed after the review opened (a `plan_draft` / `objective_draft` / `gist_draft` /
   `objective_refinement_draft` write; for refinements also a re-prepared grounding context), the
   approval saves nothing and the model is told to call `plan_review` on the current draft. A
   denial still returns its feedback, prefixed with a one-line note that the draft moved. The
   compare applies to artifact-sourced reviews (the doors and the Plannotator tool arm); a
   first-party in-TUI review's own edit write-back is the one legitimate draft change during a
   modal review and is saved as reviewed.
2. **Save destination.** At approval the destination must equal what it was when the review
   opened: the main checkout's committed `[issues] backend`/`team`, the git `remote.*.url` /
   `remote.*.gh-resolved` entries (GitHub backend only — Linear never reads remotes), and — for
   plans — the objective node claim. Nothing else participates: landing a PR (which rewrites
   `branch.*` git config), `[workflow] base`, credentials, other Perk TOML edits and comments
   never block an approval. A changed or unverifiable destination saves nothing; the model is
   told which component moved (names, never values) and that a fresh `plan_review` — a fresh
   human approval — is required. Denials never check the destination.
3. **One current review.** Opening a review on ANY surface supersedes the previous one (a
   first-party review supersedes an open browser review and vice versa; `/implement-here`
   retires it). A decision from a superseded review is ignored loudly — one TUI warning, nothing
   saved, nothing injected — even when its bytes are still current: once a newer review exists,
   its approval is the only authority.
4. **Unconfirmed-save latch.** After a save attempt that did not return a typed receipt (a
   failed backend call, a thrown call, an unavailable port), automatic approval-driven saves are
   paused for the rest of the session. The next approval on any surface is refused
   (`save_unconfirmed`) before the backend is touched, naming the earlier failure and the run id.
   **Check the issue backend for an existing plan/objective/gist carrying that run id before
   retrying** — on Linear a partially completed create can leave an issue the retry cannot find
   (GitHub creates are find-then-return on the run id) — then run the manual save command
   (`/plan-save`, `/objective-save`, `/gist-save`, `/objective-refinement-save`): the manual
   command IS the deliberate retry and never consults the latch. A Pi restart clears the latch;
   check the backend before saving again all the same.

Reviewer feedback reaching the model always rides inside `<untrusted_reviewer_feedback>`
delimiters as DATA. A refinement review (an `objective-refine` session) reviews the validated
(draft, grounding-context) pair; there is no refinement browser door or reviewer wave —
`plan_review` uses the plain browser review or the first-party view-only editor.

The Plannotator bridge subscribes to the browser's decision before it emits the review request,
so a decision emitted during the handshake is not lost; there is no status catch-up query. A
browser handshake failure produces one in-session fallback notice; if the browser never becomes
ready, findings degrade loudly to the in-session table and a later browser decision is ignored.

### Manual saves and first-party review

The draft tools, the manual save tools and slash commands (plus the human
`/objective-refinement-save`), `objective_node`, and `/implement-here` consult no review state:
they run their feature operation as before. A manual save reports its outcome into the latch (a
failed manual save pauses automatic saves too) but is never refused by it. If a save succeeds
but later gate, linkage, or notification bookkeeping fails, the stop preserves its known ID/URL;
reconcile the existing object rather than creating it again.

A first-party review opens the current-review slot before the editor (superseding an open browser
review); after the verdict a plain approval runs the latch and destination checks before the save.

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
  for revision. On the Plannotator provider, an eligible call — the Plannotator
  extension actually loaded (the presence probe) plus a validated plan or objective draft
  artifact — first opens an in-TUI launch chooser — browser review **with** the
  reviewer wave or **without** it (Esc chooses without; the review always proceeds). Choosing
  the wave asks for an optional custom review angle, opens the same browser flow as the matching
  door below, and returns wave guidance (`wave_launched`) instead of blocking; the browser
  decision then routes back automatically. Gist review has no wave door and stays plain.
  The plain plan-tool completion saves the reviewed original or verified Direct Edits bytes.
  Manual save source tiers are unchanged.

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

**APPROVE** applies verified Direct Edits to the plan artifact, then auto-saves the reviewed
bytes — behind the four guards above (a moved draft or a changed destination saves nothing and
asks for a fresh `plan_review`; a paused session refuses until `/plan-save`, the deliberate
retry). **DENY** returns the feedback and any Direct Edits for a `plan_draft` revision round,
with the draft-moved note when the draft changed.

The door refuses when Plannotator is missing, the session is headless, the current stage is not a
plan-authoring stage, or the draft is missing or invalid. Create a valid artifact with `plan_draft`
and retry. If the browser cannot become ready, findings degrade loudly to the in-session table.

### `/objective-review-browser`

Review the rendered structured objective draft — prose, explicit `**Delivery:**` line, and roadmap
table — from `objective-author` or `objective-save`. The browser and reviewer wave otherwise behave
like plan review, including the optional custom lane and automatic final core-Ponytail lane.

**APPROVE** normally auto-saves and exits read-only — behind the four guards above — but Direct
Edits never auto-apply to an objective: the browser edited rendered Markdown while save re-reads
structured fields. An approval with Direct Edits therefore saves nothing and becomes a revise
round; fold the diff into `objective_draft`, then re-review. **DENY** returns feedback for an
`objective_draft` revision (with the draft-moved note when the draft changed).

The door refuses when Plannotator is missing, the session is headless, the stage is not objective
authoring, or the structured draft is missing or invalid. It never reviews raw JSON, a pasted
parameter, or transcript text.

## Related

- **Do:** [How to review a foreign PR](../../how-to/review-a-foreign-pr.md) — run the human-triaged
  flow end to end.
- **Look up:** [Model-facing tools](./model-tools.md) — check every tool name and its stage/gate
  restrictions.
- **Look up:** [In-session commands & tools](../in-session.md) — return to the stable surface map.
