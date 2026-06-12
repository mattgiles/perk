---
title: Borrowed Pi packages — the lockstep-surfaces recipe and the evaluation bar
read_when: You are adding/removing a borrowed Pi package (`BORROWED_PACKAGES`), vetting a borrow candidate (singleton UI slots like setFooter), retiring a borrowed package, allowlisting a borrowed package's tools in read-only mode, or deciding between a provider seam and a plain borrow.
---

# Borrowed Pi packages

perk ships a small set of **borrowed** Pi packages (entries in `BORROWED_PACKAGES` in
`perk/convergence/init.py`, converged into every consumer repo's `.pi/settings.json`). This doc is the recipe
for changing that set without leaving surfaces stale, plus the evaluation bar that decides whether
a capability is a borrow at all.

## The lockstep-surfaces recipe

Adding (or removing) a borrowed package touches a fixed set of surfaces **in one turn**:

1. `BORROWED_PACKAGES` in `perk/convergence/init.py` — a plain unpinned `npm:` string entry **plus one
   rationale line** in the comment block above (every entry has one; keep the pattern).
2. The committed `.pi/settings.json` in this repo — same entry; never let the committed settings lag
   `BORROWED_PACKAGES`.
3. The `borrowed-packages` capability summary in `perk/convergence/capabilities.py` — **this string drifts
   silently**; check it whenever the borrowed set changes.
4. `shared/contracts.md` — the borrowed-set enumeration (settings-wiring section) plus any behavior
   the package alters (e.g. the tool-gating restricted set).
5. Tests — a membership assert in `tests/test_init_idempotent.py`, plus any behavior anchor (e.g.
   `READ_ONLY_TOOLS` membership in `extension/substrate/toolGating.test.ts`).

## Vetting: grep for singleton UI slots (the setFooter clobber)

Pi's footer is a **single last-wins slot**, and extensions receive `session_start` in settings
load order — so a later-loaded borrowed package calling `ctx.ui.setFooter` silently clobbers
perk's footer (no error, no log). This is now a contracts.md rule: borrowed packages must never
call `ctx.ui.setFooter`. Before borrowing, grep the candidate's **installed** source for
`setFooter` and other singleton UI slots — and note gitignored `.pi/npm/` defeats ripgrep
evidence: use `--no-ignore` (or `grep -r`) under `.pi/npm/node_modules/`, or the grep comes back
falsely empty.

## The retirement recipe (thrice-affirmed)

Removing a borrowed package (pi-plan, rpiv-todo, pi-status precedents) touches, in one commit:
remove from `BORROWED_PACKAGES` with an inline rationale comment, edit the committed
`.pi/settings.json`, fix the capability summary string, amend both contracts.md sites
(borrowed-set enumeration + the owning-feature paragraph), and invert the init-idempotency
membership assert. **No `doctor --fix` stale-entry removal** — consumer repos keep the entry as an
unmanaged user extra (precedent thrice-affirmed; a stale-entry doctor check is a plausible future,
deliberately not built).

Fixture subtlety: "borrowed package preserved across provider select/deselect" fixtures must use a
*still-borrowed* package; if a test needs strict "user extra survives" semantics, anchor on
`npm:@me/custom`, not a borrowed entry (init would re-add a borrowed one regardless).

## Foreign tool names are inert when absent

Allowlisting a borrowed package's tool names in `READ_ONLY_TOOLS` needs **no presence detection**:
when the package is absent, `pi.setActiveTools` simply has nothing to enable (the `plan_review`
precedent). Prefer static allowlisting over package-presence gating. The injected read-only notice
interpolates `READ_ONLY_TOOLS`, so it self-updates.

## The read-only bar is repo non-mutation, not zero side effects

Read-only mode's invariant is that the **repo** isn't mutated — not that the tool has zero side
effects. A tool that writes its own cache outside the worktree (e.g. `fetch_content`'s GitHub-clone
path) is morally equivalent to the already-allowlisted `curl`. Use that bar when evaluating future
allowlist candidates.

## Borrow vs. provider-seam criterion

A **provider seam** is for *owned-surface deferral* with a cross-plane contract (see
`workflow/provider-seam.md`). A borrowed capability that defers no perk-owned surface and produces
no cross-plane contract gets a plain `BORROWED_PACKAGES` entry — not a seam.

Evaluation keys that held up for the borrow decision: zero-config (no API key required — the bar
for a *required* borrowed package), headless-safe (`ctx.hasUI` guards verified in the package's
source), actively maintained, license, and the package's pi-version floor vs perk's pin.

## Residuals

- SDK in-process children (`SDK_READ_ONLY_TOOLS` in `extension/worker/readOnlySession.ts`) deliberately
  stay strict — widening them so SDK children can use borrowed tools is an **explicit decision, not
  drift** (spawned pi-subagents children already inherit the tools via `.pi/settings.json`).
- String-entry packages can't filter skills — a bundled skill is accepted wholesale. If one becomes
  noisy, the object-form `package_filter` is the lever.

## Cross-references

- `perk/convergence/init.py` — `BORROWED_PACKAGES`
- `perk/convergence/capabilities.py` — the `borrowed-packages` capability summary
- `docs/learned/workflow/provider-seam.md` — the seam this recipe is *not*; also `package_filter`
- `docs/learned/pi/context-system.md` — the read-only mode whose allowlist this touches
- `docs/learned/pi/tui-surfaces.md` — the perk-owned footer the setFooter rule protects
