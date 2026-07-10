# Dogfood: the §2.6.3 cache-visibility measurement protocol

Validation record (the `review-dogfood.md` / `remote-runner-e2e-dogfood.md` genre) for the
prompt-cache measurement protocol of `docs/design/pi-adoption-audit.md` §2.6.3, folding in the
§3.10 read-only-child cache-affinity observation. Part A is the repeatable procedure; Part B is
the captured evidence + defect log. The deliverable is the **defect log** — any per-turn
recurring miss traced to an unconditional context strip is *filed* as a GitHub issue, never fixed
here (fixes are follow-up plans traced to the log).

What this protocol measures: with the perk footer's `CH` segment live (the audit §2.6 adoption)
and pi's `showCacheMissNotices` enabled per-user, classify every cache miss across three session
shapes — a plan-mode session, a bindings implement session, and a plain-pi control — as
**(i) transition miss** (aligned with a stage flip / binding delivery / adapter strip turn),
**(ii) idle-gap miss** (the provider's ~5-minute cache TTL expiring between turns), or
**(iii) unexplained**. Acceptance: perk-attributable misses ≈ the predicted transition count
(one per flip) ⇒ documented as expected cost. Any per-turn recurring miss in the perk sessions
but not the control ⇒ a defect issue against the responsible strip (`factories/planMode.ts` /
`factories/objectiveAuthor.ts` / `substrate/bindingDelivery.ts` / the plan/todo adapters — it
would mean a strip mutates the history on every call, violating the conditional-strip pattern).

## Part A — the repeatable procedure

Substrate: the perk repo dogfoods itself — the implement worktree's `.pi/settings.json` packages
load `".."`, so interactive sessions launched from that worktree run this branch's footer code
live (pinned pi ≥ 0.80.4; run `npm ci` in the worktree first —
`docs/learned/toolchain/worktree-node-modules.md`). Each step names its actor: **(human)** for
the interactive sessions, **(session)** for what the implementing session automates (recording,
attribution, filing).

1. **Enable the diagnostic (human).** In any pi session: `/settings` → user scope →
   `showCacheMissNotices: true`. Leave repo settings untouched (perk never converges this key).
2. **Session A — plan-mode toggle (human).** `perk plan <topic>` from the implement worktree;
   ≥6 authoring turns, exit plan mode, 2 more turns. Record per turn: the footer `CH%` /
   `/session` usage numbers + any cache-miss notice verbatim (missed tokens, missed cost,
   idle-gap, model-changed).
3. **Session B — bindings implement (human).** An implement-stage session with ≥1 skill binding,
   ≥8 turns, crossing at least one binding-delivery turn and one stage transition. Same per-turn
   record.
4. **Session C — control (human).** A plain `pi` session (no perk stages) in the same repo, the
   same turn count. Same per-turn record.
5. **§3.10 observation (human + session).** During a session that spawns repeated read-only
   children (e.g. the `perk.objective-explorer` subagent or the `/pr-review` angles), record
   whether child spawns show cache-read affinity (cacheRead > 0 on child usage, where
   observable). The audit flags the SDK-level affinity question as *unverified — observe, don't
   build*: if child usage is not cheaply observable, record the method tried and that finding
   honestly. Observation only, no code change.
6. **Attribute (session).** Classify each recorded notice as transition / idle-gap
   (`idleMs` ≳ the ~5-minute TTL) / unexplained; compare Sessions A/B against C.
7. **Accept or file (session).** Misses ≈ the predicted transition count ⇒ record as expected,
   bounded cost. Any per-turn recurring miss in A/B but not C ⇒ file a GitHub defect issue via
   `gh` against the responsible strip and log it in Part B. Filing, not fixing.

Exit: Part B filled (dated, key excerpts inlined — logs rot; never linked-out), defects filed. A
run that surfaces more than the node can absorb finishes **honestly incomplete**: record what
ran, file the residue as issues, and note the deferral below (the doc-reconciliation
dogfood-gate convention).

## Part B — captured evidence + defect log

*(To be filled during the protocol run in the implement worktree — pre-submit, per the node's
gate sequencing.)*

### Run record

- **Date / worktree / pi version:** *(pending)*
- **Session A (plan-mode toggle):** *(pending)*
- **Session B (bindings implement):** *(pending)*
- **Session C (control):** *(pending)*
- **§3.10 read-only-child affinity observation:** *(pending)*

### Attribution table

| Session | Turn | Notice (verbatim excerpt) | Classification | Notes |
| ------- | ---- | ------------------------- | -------------- | ----- |
| *(pending)* | | | | |

### Defect log

| # | Issue | Responsible strip | Evidence row | Status |
| - | ----- | ----------------- | ------------ | ------ |
| *(pending)* | | | | |
