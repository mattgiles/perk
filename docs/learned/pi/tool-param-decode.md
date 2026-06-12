---
title: The tool-boundary typed param decode (toolParams.ts) — tri-state seam, strict-fail refusals, ordering proofs
read_when: You are decoding registered-tool params, adding a tool handler, choosing strict vs lenient decode semantics at a boundary, making a required param optional behind a fallback chain, adding a backend-agnostic id param (idParam/idArrayParam), or testing decode-before-side-effect ordering.
---

# Tool-boundary typed param decode

`extension/toolParams.ts` is the typed decode seam at the registered-tool boundary: every tool
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

`extension/toolParams.ts` exports a string-or-number pair for opaque backend-owned ids: strings
pass through, numbers coerce via `String()`, anything else is the strict-fail `null`. This is the
standard shape for id params once ids are backend-owned opaque strings (see
`workflow/issue-backend.md`'s opaque-id relaxation) — don't type new id params as `number`.

## Refusal shapes and the sweep invariant

- The six Result-seam doors refuse mistyped params with a **uniform strict-fail `bad_input`**.
- `run_ci` / `ask_user_question` / `plan_review` refuse in their **native result shapes** (each has
  its own outcome union; a foreign `bad_input` shape would break their consumers).
- The sweep invariant: `params as` survives only in `testing/harness.ts` (deliberate) plus the one
  structural narrowing inside `paramsOf` (the `parseObject` precedent). Anything else is a
  regression.

## Decode-before-side-effect ordering proofs (cheap, deterministic)

Proving "the decode refused *before* the side effect" in harness tests:

- **Cold-door tools:** `fakePerk(..., { argvFile })` + asserting the argv file was never written
  proves no exec happened.
- **`plan_review`:** select plannotator with a short `PERK_PLANNOTATOR_HANDSHAKE_MS`; if the bridge
  had been invoked the outcome would be `unavailable` after the timeout, so a `skipped` /
  `bad_input` outcome proves decode-before-bridge ordering.

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

The test harness's `headfulUIContext` has no `select`/`input` fakes, so a registered-tool-level
UI-interaction test isn't possible offline. The pattern: export the handler's decode as a pure
function (the `decodeAskUserParams` pattern) and compose it with the file's pure core + fake-UI
tests; the handler stays a thin wiring layer. That export is what makes param handling testable at
all (see `pi/extension-api.md`).

## Live-path note

Pi's agent loop schema-validates and converts live tool calls, so the strict-fail arms are
reachable only via **direct `execute` calls**. The behavior change is honest refusals for
programmatic callers, not live-session drift.

## Cross-references

- `extension/toolParams.ts` — the tri-state seam, `paramsOf`
- `extension/toolParams.test.ts` — the decode + ordering-proof pins
- `docs/learned/workflow/cold-door-client.md` — the contrasting advisory decode policy (never reuse
  its helpers here)
- `docs/learned/pi/extension-api.md` — the `headfulUIContext` gap that forces the pure-decode export
- `docs/learned/workflow/issue-backend.md` — the opaque-id relaxation behind `idParam`
- `docs/learned/workflow/plan-save-surfaces.md` — the fallback chain that forced the optionality flip
