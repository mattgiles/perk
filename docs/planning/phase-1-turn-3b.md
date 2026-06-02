# Phase 1 · Turn 3b — plan-save robustness (a corrective turn)

> A **small corrective turn**, cut mid-Phase-1-gate (T6): the dogfood run saved a *conversational
> message* as the "plan" and a **TOML `# comment` became the plan title**. A *direct* fix that
> **converges forward** on T3 (history not rewritten). Implemented + green before this doc was
> written.

---

## 1. Why (what the dogfood surfaced)

Authoring the prek plan in borrowed plan mode (`@tombell/pi-plan`) then running `/plan-save`
produced PR #2 / issue #1 titled *"Add only if you want format-on-commit too:"* — a TOML comment.
Root cause, traced through the code:

- **`<proposed_plan>` was perk-invented, not native.** `@tombell/pi-plan` is **pure tool-gating**:
  it restricts active tools to `[read, grep, find, ls, bash]`, blocks `edit`/`write`, and injects a
  "propose a plan" prompt. Its plan output is **free-form prose** — no `<proposed_plan>` tag, no
  exit-plan tool, no plan schema. The `<proposed_plan>` regex lived only in T3's `extractPlanMarkdown`
  and **nothing ever produced it**, so it was dead — the command always fell back to "save the whole
  latest assistant message."
- **In plan mode, that message was conversation.** The model (told only "propose a plan") wrote a
  clarifying-questions message with a draft `prek.toml`; the `/plan-save` command scraped it.
- **`derive_title` then grabbed a fenced `#`.** It `strip()`-matched the first `# ` line — which was
  the TOML comment `# Add only if you want format-on-commit too:` *inside a ```toml block*.

The loop still closed end-to-end (issue #1 CLOSED, PR #2 MERGED, `pending-learn` cleared,
`perk resume 1` → "merged and learned — nothing to resume"); these are quality bugs, not blockers.

## 2. Decisions

- **D1 — the `plan_save` tool (explicit `plan` param) is the canonical save.** The borrowed package
  gives perk nothing structured to extract, so the only robust clean-plan source is the model
  **handing the plan to the tool**. Flow: explore in `/plan` → **disable plan mode** → call
  `plan_save`.
- **D2 — perk cannot cleanly *exit* pi-plan, but can *detect* it.** pi-plan owns `enabled` in its
  closure (re-enables on `session_start`, gates via its `tool_call` hook), so perk can't flip it
  without leaving an inconsistent state. But pi-plan persists `plan-mode-state {enabled}` as a
  session entry on every toggle — perk reads the **latest** one (LWW) to know plan mode is on. (A
  soft coupling to a borrowed package's entry type; removed in Phase 2 when perk owns plan mode.)
- **D3 — fail fast, don't paper over.** `savePlan` refuses while plan mode is active rather than
  saving chatter — and the message tells the user to exit `/plan` first (or use the tool once it's
  off). LBYL, headless-safe, soft result (never throws).
- **D4 — drop the `<proposed_plan>` invention.** No tag convention; the command's message-scrape is
  an explicitly-fragile fallback, the tool is the headline (skill + runbook updated).

## 3. What was built

- **`extension/planSave.ts`** — `isPlanModeActive(branch)` (reads the latest `plan-mode-state` entry,
  LWW); a **fail-fast guard** in `savePlan` (refuses with `error_type: "plan_mode_active"` when plan
  mode is on, before any delegation); **removed** the `<proposed_plan>` regex from
  `extractPlanMarkdown` (now: the whole latest assistant message, documented as the fragile fallback).
- **`perk/plan.py`** — `derive_title` now tracks fenced ```` ``` ````/`~~~` blocks and **skips `#`
  inside them**, recognizes a heading only at 0-3 spaces of indent (CommonMark), and prefers the
  first real H1 (safe `fallback` otherwise).
- **`skills/perk-plan/SKILL.md`** — a "Saving: exit plan mode, then call the `plan_save` tool"
  section (the tool-first flow); the command framed as the fragile fallback; no tag convention.
- **`docs/planning/phase-1-turn-6.md`** — Step 1/2 rewritten to the tool-first flow (no
  `<proposed_plan>` instruction).
- **`extension/testing/harness.ts`** — `plantSession(..., { planMode })` seeds a `plan-mode-state`
  entry (and chains `parentId` off the real last entry, fixing a latent id-assumption).

## 4. Tests & gate

- **`extension/planSave.test.ts`** — `isPlanModeActive` pure matrix (LWW, ignores other types); a
  live `/plan-save` **refuses while plan mode is active**; `extractPlanMarkdown` returns the whole
  latest message (the dropped-marker behavior).
- **`tests/test_plan.py`** — `derive_title` ignores a fenced `#` (the exact dogfood shape), prefers a
  real H1 over a fenced `#`, ignores 4-space-indented `#`.
- **`scripts/verify-p1-t3b.sh`** (offline) — the derive_title hardening, the node planSave suite, and
  the absence of any `<proposed_plan>` token in code/skill. Wired into `just verify` after `p1-t3`.

## 5. Contract / registry

No cross-plane contract or registry change — `save`'s state-I/O is unchanged (`writes: [github.plan,
cache.plan-ref, session.workflow-state]`). This is door *robustness* (a precondition + title
hardening), not new state.

## 6. Out of scope (still Phase 2+)

Perk-owned plan mode + the tool-gating primitive (which removes the pi-plan coupling and lets *save*
be the read-only→read-write transition in one gesture); auto-exiting plan mode on save; any
structured plan-capture from the planning surface.

## 7. Outcomes (landed, all green)

- **Green:** ruff + ruff-format + ty + biome + tsc clean; pytest (derive_title hardening) +
  `node --test extension/planSave.test.ts` (10 pass) green; `verify-p1-t3b.sh` ALL PASS.
- **Deviations:** none. The `/plan-save` command remains a (now-guarded) best-effort fallback by
  design — the robust path is the tool; fully clean save is Phase-2 perk-owned plan mode.
- **Recorded as a P1.T6 gate finding** (alongside the `perk implement <plan>` footgun fixed in T4c).
