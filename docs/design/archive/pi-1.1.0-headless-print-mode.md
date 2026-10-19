# Record: headless print mode on Pi 1.1.0 + pi-subagents 0.76.1 — the #2660 reproduction and the post-terminal attribution

**Status:** IN PROGRESS — this commit freezes the classification and disposition tables before
the first live row runs. Every reading, class and verdict below the tables is filled in by later
commits on this branch.

## The fixed classification tables

These tables were committed to this record before the first live row ran. They are copied from
the plan (§2 and §3) without change. Later commits add readings; they never edit these tables.

### Exit class (evaluated in this order; the FIRST matching class is the row's class)

| Order | Class | Test |
| --- | --- | --- |
| 1 | `NOT STAGED` | the intended trigger did not fire: `missingbase` without the `Worktree admission failed` text; `badmodel` without `Unknown subagent model`; a runner started (`status.json` with `pid`) for a `missingbase`/`badmodel` row; `restricted` lane not `ok: true` or no runner; or the spawn reply `success: false` for a reason other than the trigger — re-run per the launch budget, never scored |
| 2 | `TRIGGER-ABSENT` | the trigger text is present AND the row has no wake evidence (none of the three wake signals below) |
| 3 | `LOOPS` | a `watchdog:` line is present (GRACE or CAP), whatever the exit code |
| 4 | `EXITS-NONZERO` | no `watchdog:` line, `exit≠0` |
| 5 | `EXITS` | no `watchdog:` line, `exit=0` |

**Wake evidence** for a row = any of: a `subagent-notify` / `subagent-incremental-child-notify`
custom entry in the shutdown census or the session file; a `message_start` for the user text
`Subagent updates above.`; or an `agent_start` lifecycle line.

### Arm class (R1 = perk, R2 = no-perk; each arm = its scored replicates)

`NOT STAGED` replicates never count. Precedence:

- (a) any `LOOPS` → arm `LOOPS` (annotated `INTERMITTENT` if another scored replicate is not
  `LOOPS`);
- (b) else every scored replicate `TRIGGER-ABSENT` → arm `TRIGGER-ABSENT`;
- (c) else any `EXITS`/`EXITS-NONZERO` → arm `EXITS` (annotated `TRIGGER-INTERMITTENT` when a
  replicate was `TRIGGER-ABSENT`; a non-zero code quoted);
- (d) fewer than two scored replicates after the budget → arm `UNSTAGED`.

Two replicates per arm. A third replicate runs only when the first two differ in class (budget
permitting).

### Post-terminal observables (P rows), per observable

| Class | Rule |
| --- | --- |
| `HOST` | present in the no-perk arm (whatever the perk arm shows) |
| `PERK-ADDITIVE` | present with perk, absent without |
| `ABSENT` | absent in both arms |

### P-row validity (checked in this order)

A failing row is re-run once per the launch budget; still failing → `INVALID`, its readings
recorded.

| Check | Rule |
| --- | --- |
| V1 staged | `restricted` lane `ok: true`, a runner started and `status.json` `complete` (else `NOT STAGED`) |
| V2 wake observed | `wakeSeenAt` set AND an `agent_start` lifecycle line (else `NO-WAKE`) |
| V3 (settle rows) settled | `wake-wait` has `timedOut: false` and `agentSettled.length ≥ 1` (else `WAKE-UNSETTLED`) |
| V4 (settle rows) SETTLED-OK | the shutdown census shows exactly one assistant entry after the wake user entry with `stopReason ∉ {error, aborted}`, provider-reported `usage.input + usage.output > 0`, and the last `agent_settled` has `aborted: false` (else `WAKE-FAILED` — provider request NOT ESTABLISHED on that row) |

### H predictions (P1/P3 = `return`, P2/P4 = `settle`)

- **Core.** C1: P1 and P3 each show `<boundary>` ≥ 1 and no non-aborted assistant entry in the
  census/file. C2: P2 and P4 each show `<boundary>` = 0 and stale-ctx = 0.
- **Secondary.** S1: P1 stale-ctx ≥ 1 and the probe's `context` and/or `agent_settled` lifecycle
  lines show `afterShutdown: true, ctxStale: true`. S2: P3 stale-ctx = 0. S3: P2 and P4 are
  SETTLED-OK with exactly one assistant entry. S4: P2 shows `loadout presentation failed` = 0 and
  no lifecycle line with `ctxStale: true`.

### H verdict (closed vocabulary; evaluated in this order)

1. `INCONCLUSIVE` — any P row `INVALID` or NOT RUN (the valid rows' readings are still recorded
   and classified `HOST`/`PERK-ADDITIVE`/`ABSENT` where both arms exist).
2. `FALSIFIED` — all rows valid and any core prediction fails.
3. `PARTIAL` — all rows valid, every core prediction holds, at least one secondary prediction
   fails (each failing cell named).
4. `CONFIRMED` — all rows valid, every prediction holds.

### The rows

| Row | Arm | Lane | Probe mode | Replicates | Required |
| --- | --- | --- | --- | --- | --- |
| R1 | perk loaded | `missingbase` (refused at worktree admission) | `return` | 2 (R1, R1-r2) | yes |
| R2 | no-perk (X3) | `missingbase` | `return` | 2 (R2, R2-r2) | yes |
| R3 | perk loaded | `badmodel` (the other pre-spawn failure) | `return` | 1 | no |
| R4 = P1 | perk loaded | `restricted` (`worktree: false` + packet) | `return` | 1 | yes |
| P2 | perk loaded | `restricted` | `settle` | 1 | yes |
| P3 | no-perk (X3) | `restricted` | `return` | 1 | yes |
| P4 | no-perk (X3) | `restricted` | `settle` | 1 | yes |
| R1t / R2t (conditional) | as R1 / R2 | `missingbase` | `settle` | 1 each, ONLY if the matching arm is `LOOPS`; never scored for the disposition | no |

**H predictions per P row (pre-registered):**

| Row | Prediction under H |
| --- | --- |
| P1 (= R4) | C1 + S1: stale-ctx ≥ 1, `<boundary>` = 1, assistant `message_start` = 0, census has the wake user entry and NO non-aborted assistant entry; lifecycle `context`/`agent_settled` lines after `session_shutdown` read `ctxStale: true`; `EXITS` |
| P2 | C2 + S3 + S4: `wake-wait` `timedOut: false`; stale-ctx = 0, `<boundary>` = 0, `loadout presentation failed` = 0, no `ctxStale: true` line; exactly one SETTLED-OK assistant entry after the wake user entry; `EXITS` |
| P3 | C1 + S2: stale-ctx = 0, `<boundary>` = 1, no non-aborted assistant entry; `EXITS` |
| P4 | C2 + S3: stale-ctx = 0, `<boundary>` = 0, one SETTLED-OK assistant entry; `EXITS` |

### Launch budget, retry priority and endpoint

9 mandatory launches (R1, R1-r2, R2, R2-r2, R3, R4/P1, P2, P3, P4), ≤ 2 conditional (R1t, R2t),
≤ 5 re-runs/third replicates — ≤ 16 parent launches and ≤ 60 min live wall in total. Re-runs are
allocated in this priority: the R1/R2 arms (staging, then a third replicate on disagreement) >
P2/P4 > P1/P3 > R3 > R1t/R2t. A row gets at most ONE re-run.

**Endpoint.** When the budget or wall is exhausted, unrun rows are `NOT RUN`. If a required row is
`NOT RUN`, an R arm is `UNSTAGED`, or a P row is `INVALID`, the record still lands with every
reading as measured. The #2660 disposition is then **`UNRESOLVED`** (no comment, no close, no
follow-up — the operator decides), and H is `INCONCLUSIVE`. The PR body names the unresolved items.
A missing R3, R1t or R2t never affects the disposition.

### Disposition rule (the two arm classes decide, nothing else)

| R1 (perk) | R2 (no-perk) | Disposition text (the record + the #2660 comment) | GitHub action |
| --- | --- | --- | --- |
| `LOOPS` | `LOOPS` | Persists on Pi 1.1.0 + pi-subagents 0.76.1 and reproduces without perk: an upstream limitation of the print-mode parent after a refused lane's wake; outside perk's report path (`worktree: false` on every lane); no perk regression, no repair | comment + close |
| `LOOPS` | `EXITS` | Perk-attributable on the exact pair (the no-perk control exits); NOT repaired here; follow-up issue filed | file the follow-up, then comment + close #2660 pointing at it |
| `LOOPS` | `TRIGGER-ABSENT` | A loop observed only with perk loaded; without perk the refused lane never woke the parent, so upstream-only cannot be shown — treated as perk-attributable; NOT repaired here; follow-up filed with the asymmetry quoted | file the follow-up, then comment + close #2660 pointing at it |
| `EXITS` | `LOOPS` | Reproduces only without perk: upstream limitation; perk's extension is not the cause and masks nothing perk-supported | comment + close |
| `EXITS` | `EXITS` | No longer reproduces on the exact pair (measured on every scored replicate; no release-note inference) | comment + close |
| `EXITS` | `TRIGGER-ABSENT` | No loop observed on the pair: with perk the refused lane wakes the parent, which exits; without perk it never woke the parent (quoted) | comment + close |
| `TRIGGER-ABSENT` | `LOOPS` | Reproduces only without perk (with perk the refused lane never woke the parent): upstream limitation | comment + close |
| `TRIGGER-ABSENT` | `EXITS` | No loop observed on the pair (asymmetric trigger presence quoted) | comment + close |
| `TRIGGER-ABSENT` | `TRIGGER-ABSENT` | The refused lane no longer wakes the print-mode parent on this pair in either arm (the measured refusal path quoted); #2660's shape is unreachable | comment + close |
| `UNSTAGED` in either arm | — | `UNRESOLVED` | none |
