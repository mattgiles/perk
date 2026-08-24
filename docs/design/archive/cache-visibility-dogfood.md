# Dogfood: the §2.6.3 cache-visibility measurement protocol

Validation record (the `review-dogfood.md` / `remote-runner-e2e-dogfood.md` genre) for the
prompt-cache measurement protocol of `docs/design/archive/pi-adoption-audit.md` §2.6.3, folding in the
§3.10 read-only-child cache-affinity observation. Part A is the repeatable procedure; Part B is
the captured evidence + defect log. The deliverable is the **defect log** — any per-turn
recurring miss traced to an unconditional context strip is *filed* as a GitHub issue, never fixed
here (fixes are follow-up plans traced to the log).

What this protocol measures: classify every cache miss across three session shapes — a
plan-mode session, a bindings implement session, and a plain-pi control — as
**(i) transition miss** (aligned with a stage flip / binding delivery / adapter strip turn),
**(ii) idle-gap miss** (the provider's ~5-minute cache TTL expiring between turns), or
**(iii) unexplained**. Acceptance: perk-attributable misses ≈ the predicted transition count
(one per flip) ⇒ documented as expected cost. Any per-turn recurring miss in the perk sessions
but not the control ⇒ a defect issue against the responsible strip (`factories/planMode.ts` /
`factories/objectiveAuthor.ts` / `substrate/bindingDelivery.ts` / the plan/todo adapters — it
would mean a strip mutates the history on every call, violating the conditional-strip pattern).

**Instrument (primary): session-JSONL usage inspection.** Session files live under
`~/.pi/agent/sessions/--<encoded-cwd>--/<id>.jsonl` and survive worktree deletion
(`docs/learned/workflow/learn-evidence-pipeline.md`). Each assistant `message` entry carries
`message.usage.{input,cacheRead,cacheWrite}` — the exact inputs of the footer `CH` formula
(`extension/surfaces/surfaces.ts` `latestCacheHitRate`). A **full miss** = `cacheRead: 0` with a
large `cacheWrite` on any assistant message after the first. The footer `CH` segment and pi's
`showCacheMissNotices` are corroborating color only — notices are TUI-only, never persisted (the
#1325 method note, promoted here to protocol).

## Part A — the repeatable procedure

Substrate: the perk repo dogfoods itself — with the adopted footer/notices code **on main**
(PR #1326 merged 2026-07-10, `a9407f7`), the main checkout's `.pi/settings.json` packages load
`".."`, so any session launched from the main checkout runs the adopted extension live, and so
does any fresh implement worktree stacked on main: the `[worktree] setup` hook runs `npm ci`,
keeping the worktree's extension live automatically (the
`docs/learned/toolchain/worktree-node-modules.md` gotcha, now automated). Pinned pi ≥ 0.80.4.
Each step names its actor: **(human)** for the interactive sessions, **(session)** for what the
implementing session automates (recording, attribution, filing).

1. **Enable the diagnostic (human — optional color).** In any pi session: `/settings` → user
   scope → `showCacheMissNotices: true`. Corroborating color only (notices are TUI-only, never
   persisted); the JSONL inspection above is the instrument. Leave repo settings untouched (perk
   never converges this key).
2. **Session A — plan-mode toggle (human).** `perk plan <topic>` from a worktree or checkout
   running the code under measurement; ≥6 authoring turns, exit plan mode, 2 more turns. Record
   per assistant message (from the session JSONL): `input` / `cacheRead` / `cacheWrite`; the
   footer `CH%` and any cache-miss notices (missed tokens, missed cost, idle-gap, model-changed)
   as color.
3. **Session B — bindings implement (session, self-measured).** The measuring plan's own
   implement session: launched post-land from the main checkout via `perk implement <N>` into a
   fresh worktree stacked on main (the setup hook keeps its extension live), with ≥1 skill
   binding (`stage:implement`) delivered cold in the seed prompt; ≥8 assistant turns. Cold-launch
   mechanics (verified in `extension/substrate/bindingDelivery.ts`): a cold stage session carries
   `BINDING_HEADER` in the turn-1 seed — there is **no mid-session binding-delivery turn to
   cross** — and the binding-context *strip* (a warm-injected custom removed at stage exit) is
   architecture-identical to the planMode strip Session A validated live (conditional, fires
   exactly once at the flip). Late in the session (after ≥8 assistant messages, before filling
   Part B), the session locates its own JSONL and measures the window up to that point; the
   `/submit` stage transition necessarily falls **outside** the measured window — record that
   boundary honestly. Predicted in-window perk-attributable mutation count: **zero**.
4. **Session C — control (human).** A fresh plain `pi` session (no perk stages) launched from
   the main checkout, roughly matching Session B's measured turn count (~8–10 turns). The
   implement session then inspects its JSONL — the newest file in the main checkout's
   cwd-encoded sessions dir, confirmed by timestamp with the operator.
5. **§3.10 observation (session).** Self-contained repeated-spawn observation: spawn the same
   read-only agent 2–3 times back-to-back via the `subagent` tool (small bounded exploration
   tasks) and record `cacheRead` on each child's **first** assistant message. Two inspection
   surfaces: the pi-subagents per-child artifacts
   (`.pi-subagents/artifacts/<runId>_<agent>_<i>_transcript.jsonl` + `_meta.json` — children
   are subprocess `pi` spawns, and artifacts land even when the child session is not
   persisted) and child session files where persisted. If no usage-bearing
   surface resolves, record the method tried and that finding honestly (the audit's *observe,
   don't build* sanction). Structural finding to carry into Part B: the SDK-level in-process
   child (`extension/worker/readOnlySession.ts`) uses `SessionManager.inMemory` (never persists
   JSONL) and has no live production call site — the SDK-level affinity question is structurally
   unobservable live today.
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

**Close: honestly incomplete (operator-called, 2026-07-10).** Step 1 + Session A executed and
passed (the one observed miss is the predicted plan-mode-exit transition miss; no defects);
Sessions B/C and the dedicated §3.10 observation deferred to
[#1325](https://github.com/mattgiles/perk/issues/1325) on the Part A precondition gap recorded
at step 3. Method note: `showCacheMissNotices` notices are TUI-only (not persisted to session
JSONL) and were not captured verbatim; the classification below derives from the session JSONL's
per-assistant-message usage — the ground truth the notices summarize. #1325 proposes making the
JSONL inspection the primary instrument on the re-run.

**Close: complete (2026-07-10 re-run — the #1325 rework).** Part A reworked post-land (PR #1326
merged the same day, dissolving the step-3 precondition gap); Sessions B and C executed and
measured via the promoted session-JSONL instrument; the dedicated §3.10 repeated-spawn
observation executed against the pi-subagents artifacts. In-window perk-attributable misses:
**zero** (= the predicted count; the one in-window miss is an idle-gap miss during the
operator's absence). No defects filed;
[#1325](https://github.com/mattgiles/perk/issues/1325) closes with this run's PR. Full record
in the re-run sections below.

### Run record

- **Date / worktree / pi version:** 2026-07-10; `.worktrees/plan-1319` (packages load `".."` =
  this branch's extension); pi 0.80.5.
- **Session A (plan-mode toggle): executed — passed.** A `perk plan` session launched from the
  implement worktree (session `019f4c61-5399…`, 14:14–14:19 UTC, 19 assistant messages:
  authoring turns, plan save + plan-mode exit, then 2 post-exit turns). The operator observed
  the `CH` segment rendering live throughout ("worked great"). Full per-message usage below;
  the one full miss (a#17) is the first assistant turn after the recorded
  `perk:workflow-state {"mode": "read-write"}` custom entry at 14:18:39 (the plan-mode exit).
  37s after the prior turn ⇒ not idle-gap; rebuilt prefix (57,071 written) *smaller* than the
  pre-exit cached prefix (59,681) ⇒ consistent with the plan-mode injection being stripped
  once at the flip; cache resumes on the very next turn. Observed misses (1) = predicted
  transition count (1 flip) ⇒ the expected, bounded cost. No per-turn recurring miss.
- **Session B (bindings implement): not executed** — the step-3 precondition gap; deferred to
  #1325. *(Executed by the re-run below.)*
- **Session C (control): not executed** — deferred with B (#1325). *(Executed by the re-run
  below.)*
- **§3.10 read-only-child affinity observation: dedicated leg not executed** (deferred to
  #1325). Adjacent observation, honestly bounded: two separately-spawned objective plan-factory
  sessions in the main checkout (14:21:56 / 14:22:29 UTC the same day) show `cacheRead > 0` on
  their **first** assistant message (6,664 and 18,354 tokens read at spawn) — spawn-time
  cross-session provider-cache prefix affinity, observed via session-JSONL usage inspection
  (cheaply observable there). These are separate pi processes, not in-process read-only
  children, so the audit's SDK-level child-affinity question stays *unverified* — observation
  only, no code change. *(Dedicated leg executed by the re-run below.)*

### Session A — per-assistant-message usage (session JSONL, inlined — logs rot)

`CH` = the footer segment's value after that message (`cacheRead / (input + cacheRead +
cacheWrite)`).

| a# | time (UTC) | input | cacheRead | cacheWrite | CH |
| -- | ---------- | ----- | --------- | ---------- | -- |
| 1 | 14:14:49 | 2 | 0 | 23505 | CH0.0% |
| 2 | 14:15:06 | 2 | 23505 | 3594 | CH86.7% |
| 3 | 14:15:18 | 2 | 27099 | 6517 | CH80.6% |
| 4 | 14:15:32 | 2 | 33616 | 2606 | CH92.8% |
| 5 | 14:15:46 | 2 | 36222 | 2591 | CH93.3% |
| 6 | 14:15:57 | 2 | 38813 | 638 | CH98.4% |
| 7 | 14:16:19 | 2 | 39451 | 496 | CH98.8% |
| 8 | 14:16:52 | 2 | 39947 | 1274 | CH96.9% |
| 9 | 14:17:10 | 2 | 41221 | 4317 | CH90.5% |
| 10 | 14:17:32 | 2 | 45538 | 4337 | CH91.3% |
| 11 | 14:17:39 | 2 | 49875 | 1871 | CH96.4% |
| 12 | 14:17:57 | 2 | 51746 | 331 | CH99.4% |
| 13 | 14:18:05 | 2 | 52077 | 1252 | CH97.6% |
| 14 | 14:18:18 | 2 | 53329 | 3023 | CH94.6% |
| 15 | 14:18:28 | 2 | 56352 | 3325 | CH94.4% |
| 16 | 14:18:34 | 2 | 59677 | 4 | CH100.0% |
| 17 | 14:19:11 | 2 | 0 | 57071 | CH0.0% |
| 18 | 14:19:20 | 2 | 57071 | 3104 | CH94.8% |
| 19 | 14:19:34 | 2 | 60175 | 791 | CH98.7% |

Key timeline excerpt around the flip (session JSONL):

```
14:18:34  assistant  cR=59677 cW=4      (a#16 — pre-exit, CH100.0%)
14:18:39  custom     perk:workflow-state {"mode": "read-write"}   ← the plan-mode exit
14:18:45  user       "continue"
14:19:11  assistant  cR=0     cW=57071  (a#17 — THE transition miss, full rebuild)
14:19:20  assistant  cR=57071 cW=3104   (a#18 — cache resumed)
```

### Attribution table

| Session | Turn | Evidence (usage-derived; notices not persisted) | Classification | Notes |
| ------- | ---- | ----------------------------------------------- | -------------- | ----- |
| A | a#1 | `cR=0 cW=23505` at session start | — (cold start) | Not a miss — first fill; footer correctly shows `CH0.0%`. |
| A | a#17 | `cR=0 cW=57071`, 37s after a#16, first turn after the `mode: read-write` flip | **(i) transition miss** | The predicted one-per-flip plan-mode-exit strip; conditional (fires once — a#18 resumes at `cR=57071`). |
| A | a#2–a#16, a#18–a#19 | `cacheRead` ≥ prior prefix every turn | — (hits) | No idle-gap misses (session span < TTL); no unexplained misses. |

A/B-vs-C comparison: not available this run (B/C deferred — #1325); filled by the re-run
below.

### Defect log

| # | Issue | Responsible strip | Evidence row | Status |
| - | ----- | ----------------- | ------------ | ------ |
| — | *(none filed)* | — | — | No per-turn recurring miss observed; the single miss matches the predicted transition cost, so the conditional-strip pattern held. |

Residue (not defects): the Part A step-3 precondition gap + the deferred B/C/§3.10 legs — filed
as [#1325](https://github.com/mattgiles/perk/issues/1325) and executed by the re-run below
(#1325 closes with its PR).

### Run record — 2026-07-10 re-run (Sessions B/C + §3.10, the #1325 rework)

- **Date / substrate / pi version:** 2026-07-10, 16:06–16:34 UTC; Session B in
  `.worktrees/plan-1339` — a fresh worktree stacked on main at `8ad1b66` (main carries the
  merged #1326 `a9407f7`; the `[worktree] setup` hook's `npm ci` keeps its packages-`".."`
  extension live); Session C in the main checkout; pi 0.80.6.
- **Session B (bindings implement, self-measured): executed — passed.** This node's own
  implement session (session `019f4cc7-bdcd…`, cold-launched 16:06:39 UTC via
  `perk implement 1339`): the `stage:implement` binding block and the juicesharp todo-adapter
  note ride the turn-1 seed prefix — no mid-session delivery turn exists, as Part A step 3
  predicts — and perk's session-start customs (run-id claim, `active_plan_ref`, plannotator
  idle) are context-invisible. Measured window: a#1 (16:06:47) → a#23 (16:34:13), closed at
  the measurement turn; the Part B fill, the closing commits, and the `/submit` stage
  transition fall **outside** the window (recorded here, unmeasured). 23 assistant messages:
  one cold fill (a#1), one idle-gap miss (a#21 — a 21.2-minute gap ≫ the ~5-min TTL while the
  operator was away running Session C; partial rebuild, cache resumed a#22), and **zero
  perk-attributable misses** — matching the predicted in-window mutation count of zero. The
  §3.10 spawns ran in-window (between a#10 and a#11) with no cache disturbance (a#11 resumes
  at `cR=57489` ≥ the prior prefix).
- **Session C (control): executed — passed.** An operator-driven plain `pi` session in the
  main checkout (session `019f4cdc-2eab…`, 16:28:46–16:33 UTC, 11 assistant messages, no perk
  stages; the only perk entries are the context-invisible session-start customs). One cold
  fill (a#1); zero misses after — every turn's `cacheRead` ≥ the prior prefix, including
  across a 2.3-minute gap (< TTL, cache held).
- **§3.10 read-only-child affinity observation: executed.** Three back-to-back spawns of the
  same read-only agent (`perk.objective-explorer`; `subagent` chain `95ab12eb`;
  `anthropic/claude-haiku-4-5`; 16:09:52–16:10:29 UTC; small bounded exploration tasks). The
  inspection surface that resolved: the pi-subagents per-child artifacts
  (`.pi-subagents/artifacts/95ab12eb_perk.objective-explorer_<i>_transcript.jsonl` +
  `_meta.json`) — child session files were **not** persisted (conditional persistence: no
  `sessionFile`/`sessionDir`/`share` configured, so the subprocess children ran without
  session files). Result: child 0's first assistant message is a cold fill (`cR=0 cW=10747`);
  children 1 and 2 both read the 9,848-token shared agent prefix at spawn (`cR=9848` on their
  **first** assistant message) — **spawn-time cross-process provider-cache prefix affinity
  confirmed** for subprocess children. The SDK-level arm: structurally unobservable live
  today — `extension/worker/readOnlySession.ts` builds its child on `SessionManager.inMemory`
  (never persists JSONL) and has zero live production call sites (`doors/ciExecutor.ts`
  deliberately does not call `runReadOnlyChild`); method + finding recorded, no code change
  (the audit's *observe, don't build* sanction).

### Session B — per-assistant-message usage (session JSONL, inlined — logs rot)

Measured window a#1–a#23; `input` = 2 on every row (omitted). `CH` as defined for Session A.

| a# | time (UTC) | cacheRead | cacheWrite | CH |
| -- | ---------- | --------- | ---------- | -- |
| 1 | 16:06:47 | 0 | 34459 | CH0.0% |
| 2 | 16:07:06 | 34459 | 5730 | CH85.7% |
| 3 | 16:07:12 | 40189 | 1483 | CH96.4% |
| 4 | 16:07:18 | 41672 | 4525 | CH90.2% |
| 5 | 16:07:30 | 46197 | 414 | CH99.1% |
| 6 | 16:08:40 | 46611 | 1219 | CH97.4% |
| 7 | 16:08:45 | 47830 | 6680 | CH87.7% |
| 8 | 16:08:57 | 54510 | 319 | CH99.4% |
| 9 | 16:09:10 | 54829 | 1889 | CH96.7% |
| 10 | 16:09:34 | 56718 | 771 | CH98.7% |
| 11 | 16:10:35 | 57489 | 1735 | CH97.1% |
| 12 | 16:10:42 | 59224 | 173 | CH99.7% |
| 13 | 16:10:54 | 59397 | 798 | CH98.7% |
| 14 | 16:11:04 | 60195 | 487 | CH99.2% |
| 15 | 16:11:12 | 60682 | 1410 | CH97.7% |
| 16 | 16:11:31 | 62092 | 1168 | CH98.2% |
| 17 | 16:11:40 | 63260 | 1216 | CH98.1% |
| 18 | 16:11:54 | 64476 | 446 | CH99.3% |
| 19 | 16:12:05 | 64922 | 995 | CH98.5% |
| 20 | 16:12:19 | 65917 | 451 | CH99.3% |
| 21 | 16:33:40 | 17566 | 49144 | CH26.3% |
| 22 | 16:33:52 | 66710 | 663 | CH99.0% |
| 23 | 16:34:13 | 67373 | 1400 | CH98.0% |

Key timeline excerpts (Session B JSONL). The cold-launch turn-1 prefix — everything perk
delivers arrives **before** a#1, so there is nothing to strip mid-window:

```
16:06:39  custom          perk:workflow-state (run-id claim)      ┐ session-start customs
16:06:39  custom          perk:workflow-state (active_plan_ref)   │ (context-invisible)
16:06:39  custom          plannotator {"phase":"idle"}            ┘
16:06:39  user            seed prompt — carries the BINDING_HEADER binding block (cold delivery)
16:06:39  custom_message  perk:todo-adapter-juicesharp            ← turn-1 prefix, no delivery turn
16:06:47  assistant       cR=0 cW=34459   (a#1 — cold start, CH0.0%)
```

The one in-window miss — the idle gap:

```
16:12:19  assistant  cR=65917 cW=451     (a#20 — last pre-gap turn, CH99.3%)
          — 21.2-minute idle gap: operator away running Session C —
16:33:32  user       "Done. Began at 1228pm local time. …"
16:33:40  assistant  cR=17566 cW=49144   (a#21 — THE idle-gap miss; partial rebuild, CH26.3%)
16:33:52  assistant  cR=66710 cW=663     (a#22 — cache resumed)
```

(Honest note: a#21's `cacheRead=17566 > 0` — the provider retained part of the prefix past the
nominal TTL; a partial rather than full rebuild. Recorded as observed; the mechanism is
provider-side.)

### Session C — per-assistant-message usage (session JSONL, inlined — logs rot)

`input` = 2 on every row (omitted).

| a# | time (UTC) | cacheRead | cacheWrite | CH |
| -- | ---------- | --------- | ---------- | -- |
| 1 | 16:29:22 | 0 | 35875 | CH0.0% |
| 2 | 16:29:34 | 35875 | 1916 | CH94.9% |
| 3 | 16:29:53 | 37791 | 655 | CH98.3% |
| 4 | 16:29:59 | 38446 | 217 | CH99.4% |
| 5 | 16:30:04 | 38663 | 195 | CH99.5% |
| 6 | 16:30:15 | 38858 | 95 | CH99.8% |
| 7 | 16:30:21 | 38953 | 1182 | CH97.1% |
| 8 | 16:30:27 | 40135 | 600 | CH98.5% |
| 9 | 16:30:38 | 40735 | 648 | CH98.4% |
| 10 | 16:32:54 | 41383 | 586 | CH98.6% |
| 11 | 16:33:07 | 41969 | 939 | CH97.8% |

### §3.10 — per-child first-assistant-message usage (pi-subagents artifacts, inlined)

| child | spawn a#1 (UTC) | input | cacheRead | cacheWrite |
| ----- | --------------- | ----- | --------- | ---------- |
| 0 | 16:09:52 | 10 | 0 | 10747 |
| 1 | 16:10:11 | 10 | **9848** | 1321 |
| 2 | 16:10:22 | 10 | **9848** | 1068 |

### Attribution table — re-run

| Session | Turn | Evidence (usage-derived; notices not persisted) | Classification | Notes |
| ------- | ---- | ----------------------------------------------- | -------------- | ----- |
| B | a#1 | `cR=0 cW=34459` at session start | — (cold start) | Not a miss — first fill; the binding block + adapter note are inside this prefix. |
| B | a#21 | `cR=17566 cW=49144`, first turn after a 21.2-min idle gap | **(ii) idle-gap miss** | Gap ≫ the ~5-min TTL (operator away running Session C); no custom/strip entry anywhere in the gap; partial prefix retained; a#22 resumes at `cR=66710`. |
| B | a#2–a#20, a#22–a#23 | `cacheRead` ≥ prior prefix every turn | — (hits) | Zero transition misses: no mid-window stage flip, binding delivery, or adapter strip exists to cross (cold-launch mechanics). |
| C | a#1 | `cR=0 cW=35875` at session start | — (cold start) | Control cold fill. |
| C | a#2–a#11 | `cacheRead` ≥ prior prefix every turn | — (hits) | Includes a 2.3-min gap (< TTL) that held. |

A/B-vs-C comparison (the line the first run left "not available"): per-turn recurring misses in
the perk shapes = **zero**, same as the control. B's only non-cold miss is idle-gap-classified
(caused by the operator leaving to run C, not by any strip); A's only miss was the predicted
one-per-flip plan-mode-exit transition miss. Perk-attributable misses across all three shapes =
1 (A's flip) = the predicted transition count ⇒ the conditional-strip pattern held everywhere
it was exercised.

### Defect log — re-run

| # | Issue | Responsible strip | Evidence row | Status |
| - | ----- | ----------------- | ------------ | ------ |
| — | *(none filed)* | — | — | Zero perk-attributable misses in B and C; no per-turn recurring miss anywhere; nothing to file. |

Residue: none — the legs deferred by the first run (B, C, the dedicated §3.10 observation) all
executed; #1325 closes with this run's PR.
