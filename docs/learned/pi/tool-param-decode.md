---
title: The tool-boundary typed param decode (toolParams.ts) — tri-state seam, strict-fail refusals, ordering proofs
read_when: You are decoding registered-tool params, adding a tool handler, choosing strict vs lenient decode semantics at a boundary, or adding a backend-agnostic id param (idParam/idArrayParam).
cluster: pi-extension
---

# Tool-boundary typed param decode

`extension/substrate/toolParams.ts` is the typed decode seam at the registered-tool boundary: every tool
handler narrows its `params` through it instead of `params as {…}` casts. This doc captures the
policy decisions behind the seam and the testing patterns that make decode behavior provable
offline.

## The tri-state seam — and why it can't share the cold-door helpers

The seam is **tri-state**: absent → `undefined`, present-but-mistyped → `null`. Strict-fail
semantics require distinguishing *absent* from *mistyped* — a missing optional param is fine; a
present-but-wrong-typed one is an honest refusal.

**Boundary-specific decode semantics, never shared helpers.** Do NOT reuse `coldDoor.ts`'s
two-state lenient field helpers (absent OR mistyped → `undefined`) at the tool boundary. Those
encode an *advisory-payload* policy (see `workflow/cold-door-client.md`); the tool boundary needs
strict-fail. Resisting the urge to "reuse" kept both policies honest and caused **zero churn** in
the seven door modules importing the cold-door helpers. When two boundaries have different failure
philosophies, separate helper families are the cheap option, not duplication.

## Fallback-chain optionality: flip absent to `undefined`

When a previously-required param grows a **fallback chain** (e.g. `plan_save`'s `plan` once
`resolvePlanSource` landed), the decode must flip the absent case from `""`-coercion to
`undefined`: the empty-string coercion existed so the core's `invalid_input` arm owned the message,
but with a resolver chain the *resolver's* null arm owns "nothing anywhere", and `undefined` is
what lets an absent param fall through to the next source. Present-but-mistyped → `null`
strict-fail is unchanged — **the tri-state survives the optionality flip**.

The one-comparison fold that falls out: `paramsOf(params) === null` (non-object params) and a
mistyped field both fold into a single `=== null` bad_input check, while `undefined` (absent)
proceeds — mistyped-vs-absent for free with one comparison.

## Backend-agnostic id params: `idParam` / `idArrayParam`

`extension/substrate/toolParams.ts` exports a string-or-number pair for opaque backend-owned ids: strings
pass through, numbers coerce via `String()`, anything else is the strict-fail `null`. This is the
standard shape for id params once ids are backend-owned opaque strings (see
`workflow/issue-backend.md`'s opaque-id relaxation) — don't type new id params as `number`.

## Refusal shapes and the sweep invariant

- The Result-seam doors (every perk tool whose outcome is a Result — the count has grown far past
  the original six; don't pin it) refuse mistyped params with a **uniform strict-fail
  `bad_input`**.
- `run_ci` / `plan_review` refuse in their **native result shapes** (each has
  its own outcome union; a foreign `bad_input` shape would break their consumers).
- **The sweep invariant.** A `params as` cast is admissible only as a **structural narrowing
  immediately after an explicit object check**, never as a shape assertion. Three live instances:
  `testing/harness.ts` (deliberate), `paramsOf`'s own narrowing (the `parseObject` precedent), and
  `extension/library/librarian.ts::decodeLibrarianParams` — which narrows to
  `Record<string, unknown>` after its own object check because its decode is a closed-key-set,
  first-violation-wins refusal (unknown keys, control characters, a length cap, per-action field
  rules, values verbatim) that the tri-state helpers don't model. **No guard test enforces the
  sweep** — it is a review convention; a new handler-level `params as {…}` shape assertion is the
  regression.
- **Trim-then-refuse for optional free-text params.** An optional free-text param that survives
  as whitespace rides every composed downstream string as a dangling, contentless suffix. Decode
  should trim, refuse blank (empty *and* whitespace-only), and return the trimmed value —
  matching the command handler's own arg trim. "Present-but-empty ⇒ null" specs let whitespace
  slip through.

## Decode-before-side-effect ordering proofs (cheap, deterministic)

Proving "the decode refused *before* the side effect" in harness tests:

- **Cold-door tools:** `fakePerk(..., { argvFile })` + asserting the argv file was never written
  proves no exec happened. Pins: `extension/pi/v1/plan.test.ts` ("plan_save with a mistyped
  consumed_learn → bad_input, no exec"), `extension/pi/v1/gist.test.ts` ("gist_save with a
  mistyped scope"), `extension/pi/v1/objectiveAuthoring.test.ts` ("objective_save with a mistyped
  roadmap").
- **`plan_review`:** the pin is `extension/pi/v1/planReview.test.ts` ("mistyped plan -> skipped
  with reason bad_input"), and it runs without a plannotator handshake. The short
  `PERK_PLANNOTATOR_HANDSHAKE_MS` technique — select plannotator with a short handshake; an
  invoked bridge would yield `unavailable` after the timeout, so a `skipped` / `bad_input` outcome
  proves decode-before-bridge ordering — is what the neighbouring no-listener / missing-plan pins
  in the same file use, and it is the lever to reach for when a decode refusal must be
  distinguished from an `unavailable` bridge.

Both are deterministic and need no timing slack.

## Layering a boundary over existing guards

- **`failFor`'s third `label` arg** is the lever when a handler-level refusal needs a different
  content prefix than the inner implementation's closure (e.g. `plan_save failed:` vs `plan-save`):
  bind a second closure at the handler, leave the inner one untouched — existing messages stay
  byte-stable.
- **Absent-decodes-to-the-legacy-sentinel** (e.g. an absent prose param decodes to `""`) layers a
  strict boundary over an existing guard *without moving message ownership*: the inner
  `invalid_input` arm keeps owning "nothing to save"; the boundary owns only *mistyped*.
- **Inner runtime guards stay** after adding a boundary decode (e.g. the objective-node /
  reconcile shape checks) — they defend the exported functions' direct callers, not just the tool
  path. Decode-at-boundary and guard-at-implementation are complementary, not redundant.

## UI-interacting tools: exported pure decode + pure core

The harness's `invokeTool(name, params, { ui })` overlays scripted `select`/`input`/`editor`/`confirm`
answers over the recording UI (precedents: `plan_review`'s launch chooser in
`extension/pi/v1/planReview.test.ts`; `run_ci`'s confirm arms in `extension/pi/v1/delivery/ci.test.ts`),
so a registered tool's dialog flow IS testable offline. Only `invokeCommand` (a real `session.prompt`)
has no dialogs. The pattern: export the handler's decode as a pure function (the
`decodePlanSaveParams` precedent in `extension/pi/v1/plan.ts`; the ask-user tool that first carried
the pattern was retired with its provider smoke —
`docs/design/archive/provider-smoke-juicesharp-ask-user.md`) and compose it with the file's pure
core + fake-UI tests; the handler stays a thin wiring layer. That export is the **preferred** shape
for decode/branch coverage — cheap, exhaustive and independent of the dialog script — not a
workaround forced by a harness gap; reserve `opts.ui` overlays for the end-to-end dialog wiring
(see `pi/extension-api.md`).

## Live-path note

Pi's agent loop schema-validates and converts live tool calls, so the strict-fail arms are
reachable only via **direct `execute` calls**. The behavior change is honest refusals for
programmatic callers, not live-session drift.

## Cross-references

- `extension/substrate/toolParams.ts` — the tri-state seam, `paramsOf`
- `extension/substrate/toolParams.test.ts` — the primitive tri-state decoder pins (no door tests)
- `extension/pi/v1/plan.test.ts`, `gist.test.ts`, `objectiveAuthoring.test.ts`,
  `planReview.test.ts` — the decode-before-side-effect ordering-proof pins
- `docs/learned/workflow/cold-door-client.md` — the contrasting advisory decode policy (never reuse
  its helpers here)
- `docs/learned/pi/extension-api.md` — `invokeTool`'s `opts.ui` overlay + the pure-decode recipe
- `docs/learned/workflow/issue-backend.md` — the opaque-id relaxation behind `idParam`
- `docs/learned/workflow/plan-save-surfaces.md` — the fallback chain that forced the optionality flip
