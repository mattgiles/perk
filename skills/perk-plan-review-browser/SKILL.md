---
name: perk-plan-review-browser
description: Human-in-the-loop review of the working plan draft in the plannotator browser. Use when reviewing a plan draft with /plan-review-browser.
stages: []
disable-model-invocation: true
---

# Reviewing the working plan draft in the plannotator browser (the `/plan-review-browser` door)

`/plan-review-browser` runs a **human-in-the-loop** review of the working plan draft on
plannotator's browser plan-review UI. The door has already done the deterministic substrate
before you read this: it verified the plannotator extension + an interactive UI, gated on a
plan-authoring session with a validated working draft, started the browser open **in the
background**, and primed BOTH companion surfaces — the annotation surface for
`push_annotations` (plan mode) and the draft under review for the wave (you never see or relay
the server address, and you never re-send the draft: reviewed bytes == browsed bytes == wave
bytes by construction). Your launch guidance carries the flow — launch the wave, push, reconcile,
end your turn; this skill is the judgment and detail layer behind it.

## Behind the flow (the detail the launch guidance doesn't state)

- **The four lenses.** **grounding** — are the draft's claims about the codebase/world actually
  true? **scope** — right-sized: neither bloated nor missing the ask? **decision-completeness** —
  are the decisions an implementer needs actually settled? **risk** — what could go wrong:
  migrations, compatibility, irreversibility? Pick what fits *this* draft; skip lenses that
  would produce noise. Scope owns goal boundaries plus missing/extraneous deliverables, not
  standalone simplification. The selected 2–3 lanes and optional human custom lane are followed
  by exactly one **required automatic** final `ponytail` lane, outside both menus/caps. It uses
  the same model and report family plus the invocation-private exact-package core `ponytail`
  skill; never select or duplicate it. Ponytail exclusively owns standalone deletion/YAGNI/
  materially-smaller-or-native findings; ordinary lanes mention simplification only when
  inseparable from their assigned harm and never duplicate a standalone Ponytail finding. Failed
  exact-source preflight never dispatches/spawns that child, reports non-retryable
  `skill-unavailable`, and leaves required coverage incomplete without falling back to a
  same-named skill. The child's first-action exact-source recheck makes post-preflight package
  instability produce no schema-valid report; package files are assumed stable for the short pass.
- **Launch truthfulness.** `start_draft_review_wave` returns nested
  `launch: {requested, runnable, preflightFailures}`; only `runnable` lanes were accepted for
  spawning, while collection keeps `requested` as the coverage denominator.
- **The reviewer model.** The configured `[models.subagents] draft-reviewer` model is resolved
  by `start_draft_review_wave` at execute time — the door reads no config and the guidance
  carries no model plumbing.
- **Native delivery.** Launch once, retain workflow identity, and end the turn with Pi open.
  Relay delivered provisional batches on native supervisor wakes before collecting on matching
  workflow completion (co-delivered notices need no extra turn). Final reports alone authorize
  reconciliation, exactly once. Early collection retains pending; expired grace after observed
  completion requires owner diagnosis, not polling/relaunch. Held annotations retry on native
  batch/readiness/completion wakes; replace each covered lane at reconcile, even if empty.
- **Streaming status.** Required `streamed` means the child submitted at least one nonempty batch
  accepted/queued by the supervisor, not that the human saw it. No findings → false normally;
  unavailable/failed streaming → complete final report plus factual `fyi` (true remains true after
  an earlier successful batch). Disclose every false lane (custom/Ponytail included) in-session
  without changing coverage: neutral “no provisional batches (no findings)” versus warning
  “completion-only findings; no provisional batches”. Never create status annotations; false
  alone does not diagnose a broken bridge.
- **The child report shape (verdict-free).** Each child's completion report is
  `{angle, summary, findings[{phrase, severity, confidence, body}], fyi[], streamed: boolean}` (`phrase` is a
  byte-exact span from the draft or `null` for a global finding; an empty `findings` is a
  legitimate, earned outcome). The streamed fenced-JSON batches carry findings in this same
  shape; `null` phrases land in the browser's sidebar.
- **The annotation mechanics are tool-owned.** Behind the launch statement's
  end-to-end/never-compose-HTTP rules, `push_annotations` owns the finding→annotation mapping,
  the dedupe ledger, the hold-and-accumulate retry, and the source-scoped `replace: true`
  reshape (the human's and other lanes' annotations are structurally untouchable).
- **The door observes readiness itself.** There is no handshake poll for you to run: ready → an
  info note; never-ready → a loud error plus a degrade notice injected to you (degraded mode
  below).
- **Reconcile judgment.** Clear uncovered sources first (`launch.requested` minus
  `collected.covered`), using `push_annotations` with empty findings and `replace: true`.
  Build disjoint final per-angle arrays from valid reports only — never recover failed reports
  from provisional batches or simply re-send every lane's raw array. Merge distinct concerns
  at the same phrase; preserve contributor angle/severity/confidence labels in the merged body
  and the highest severity with its corresponding confidence. The first contributing lane in
  `collected.covered` order owns that anchor; duplicate-only lanes get empty final arrays.
  Replace each covered lane once, including empty arrays. A held clear/replacement is not
  finalization: keep the wake-driven retry/door-owned degrade posture until nothing is held.
  `fyi` notes remain in-session color, never pushed.
- **Visible attribution.** Plan annotations carry both `source` (replacement ownership) and
  `author` (the owning lane label displayed by the plan UI). A valid custom contribution merged
  under another owner remains labelled in the body; it need not have a separate custom card.

## The approve/deny loop

- **On APPROVE** (the auto-save the launch statement names): browser Direct Edits are mechanically
  applied and written back to the draft first, then the save runs exactly as a `plan_review`
  approval would (the session exits read-only on success). The never-rewrite exclusion is a
  STALE guard: the approval saves only when the live draft still matches the reviewed bytes — a
  `plan_draft` call while the browser review is open makes the approval refuse as STALE (nothing
  saved; the human re-runs the door). You relay the save outcome; if the save FAILED the session
  stays read-only and the human runs `/plan-save` (the manual failsafe).
- **On DENY**: the feedback arrives verbatim (any Direct Edits diff included) for the
  `plan_draft` revision round. Deny is model-mediated by design — nothing is saved and nothing
  re-opens automatically; the human re-runs `/plan-review-browser` (or you call `plan_review`)
  for the next round.

## Degraded mode (loud, never lossy)

If the browser never comes up, the door says so plainly and clears both surfaces —
`push_annotations` refuses (`no_surface`) and `start_draft_review_wave` refuses
(`no_draft_context`) from then on. Surface the wave's findings in-session for the human instead;
the human decides the next step via `plan_review` (the in-session review door) or `/plan-save`.
A completed review is never lost to a surface failure, and every degradation is announced,
never silent.
