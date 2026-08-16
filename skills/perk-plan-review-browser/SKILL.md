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
  would produce noise. The selected 2–3 lanes and optional human custom lane are followed by
  exactly one automatic final `ponytail` lane, outside both menus/caps. It uses the same model and
  report family plus the invocation-private exact-package core `ponytail` skill; never select or
  duplicate it. Failed exact-source preflight omits only that child, reports non-retryable
  `skill-unavailable`, leaves it uncovered, and never falls back to a same-named skill.
- **The reviewer model.** The configured `[models.subagents] draft-reviewer` model is resolved
  by `start_draft_review_wave` at execute time — the door reads no config and the guidance
  carries no model plumbing.
- **The child report shape (verdict-free).** Each child's completion report is
  `{angle, summary, findings[{phrase, severity, confidence, body}], fyi[]}` (`phrase` is a
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
- **Reconcile judgment.** Keep the severity/confidence/angle tags. `fyi` notes are in-session
  color, never pushed.

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
