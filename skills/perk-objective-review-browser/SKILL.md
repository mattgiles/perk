---
name: perk-objective-review-browser
description: Human-in-the-loop review of the rendered working objective draft in the plannotator browser. Use when reviewing an objective draft with /objective-review-browser.
stages: []
disable-model-invocation: true
---

# Reviewing the working objective draft in the plannotator browser (the `/objective-review-browser` door)

`/objective-review-browser` runs a **human-in-the-loop** review of the working objective draft
on plannotator's browser plan-review UI. The reviewed subject is the **rendered** draft — the
prose, the prominent `**Delivery:**` line, and the roadmap table — never the raw JSON artifact.
The door has already done the deterministic substrate before you read this: it verified the
plannotator extension + an interactive UI, gated on an objective-authoring session
(objective-author or objective-save) with a validated working draft, started the browser open
**in the background**, and primed BOTH companion surfaces — the annotation surface for
`push_annotations` (plan mode) and the draft under review for the wave (you never see or relay
the server address, and you never re-send the draft: reviewed bytes == browsed bytes == wave
bytes by construction). Your launch guidance carries the flow — launch the wave, push, reconcile,
end your turn; this skill is the judgment and detail layer behind it.

## Behind the flow (the detail the launch guidance doesn't state)

- **The four lenses.** **grounding** — are the draft's claims about the codebase/world actually
  true? **scope** — right-sized: neither bloated nor missing the ask? **decision-completeness** —
  are the decisions a planner needs actually settled? **risk** — what could go wrong: sequencing,
  dependencies, irreversibility? Pick what fits *this* draft; skip lenses that would produce
  noise. Scope owns goal boundaries plus missing/extraneous deliverables, not standalone
  simplification. The selected 2–3 lanes and optional human custom lane are followed by exactly
  one **required automatic** final `ponytail` lane, outside both menus/caps. It uses the same
  model and report family plus the invocation-private exact-package core `ponytail` skill; never
  select or duplicate it. Ponytail exclusively owns standalone deletion/YAGNI/materially-smaller-
  or-native findings; ordinary lanes mention simplification only when inseparable from their
  assigned harm and never duplicate a standalone Ponytail finding. Failed exact-source preflight
  never dispatches/spawns that child, reports non-retryable `skill-unavailable`, and leaves
  required coverage incomplete without falling back to a same-named skill. The child's
  first-action exact-source recheck makes post-preflight package instability produce no
  schema-valid report; package files are assumed stable for the short pass.
- **Launch truthfulness.** `start_draft_review_wave` returns nested
  `launch: {requested, runnable, preflightFailures}`; only `runnable` lanes were accepted for
  spawning, while collection keeps `requested` as the coverage denominator.
- **The reviewer model.** The configured `[models.subagents] draft-reviewer` model is resolved
  by `start_draft_review_wave` at execute time — the door reads no config and the guidance
  carries no model plumbing.
- **The child report shape (verdict-free).** Each child's completion report is
  `{angle, summary, findings[{phrase, severity, confidence, body}], fyi[]}` (`phrase` is a
  byte-exact span from the rendered draft or `null` for a global finding; an empty `findings`
  is a legitimate, earned outcome). The streamed fenced-JSON batches carry findings in this same
  shape; `null` phrases land in the browser's sidebar.
- **The annotation mechanics are tool-owned.** Behind the launch statement's
  end-to-end/never-compose-HTTP rules, `push_annotations` owns the finding→annotation mapping,
  the dedupe ledger, the hold-and-accumulate retry, and the source-scoped `replace: true`
  reshape (the human's and other lanes' annotations are structurally untouchable).
- **The door observes readiness itself.** There is no handshake poll for you to run: ready → an
  info note; never-ready → a loud error plus a degrade notice injected to you (degraded mode
  below).
- **Reconcile judgment.** Keep the severity/confidence/angle tags. `fyi` notes are in-session
  color, never pushed.

## The approve/deny loop

- **On APPROVE** (the auto-save through the objective approval→save seam the launch statement
  names): the save re-reads the STRUCTURED artifact and the session exits read-only on success.
  The rendered-vs-structured asymmetry is why browser Direct Edits are NEVER auto-applied to an
  objective: the browser edits the rendered markdown, while the save re-reads the structured
  `{prose, roadmap}` artifact — rendered edits cannot be folded back mechanically, so an
  approval whose feedback opens a Direct Edits section saves NOTHING and returns as the revise
  round the launch statement describes (prose hunks → the prose; roadmap-table hunks → the
  matching node fields; then re-review to confirm). The never-rewrite exclusion is a STALE guard
  on the raw artifact bytes: the approval saves only when the live artifact still carries the
  exact bytes captured at open — an `objective_draft` call while the browser review is open
  makes the approval refuse as STALE (nothing saved; the human re-runs the door). You relay the
  save outcome; if the save FAILED the session stays read-only and the human runs
  `/objective-save` (the manual failsafe).
- **On DENY**: the feedback arrives verbatim (any Direct Edits diff included) for the
  `objective_draft` revision round. Deny is model-mediated by design — nothing is saved and
  nothing re-opens automatically; the human re-runs `/objective-review-browser` (or you call
  `plan_review`) for the next round.

## Degraded mode (loud, never lossy)

If the browser never comes up, the door says so plainly and clears both surfaces —
`push_annotations` refuses (`no_surface`) and `start_draft_review_wave` refuses
(`no_draft_context`) from then on. Surface the wave's findings in-session for the human
instead; the human decides the next step via `plan_review` (the in-session review door) or
`/objective-save` (the manual failsafe). A completed review is never lost to a surface failure,
and every degradation is announced, never silent.
