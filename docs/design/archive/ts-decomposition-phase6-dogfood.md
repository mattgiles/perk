# Dogfood record: ts-decomposition Phase 6 gate (learning)

**Status:** validation record (the `*-dogfood.md` archive genre) for the objective's Phase-6
close: *run the current learning capture and one downstream learning workflow through the
migrated paths, producing and validating real artifacts* — after the Phase-6 feature slices
(Node 6.1: learn capture + routing into `learning/` + `pi/v1/learning/`; Node 6.2: the
session-audit judgment op; Node 6.3: harvest + dream). All three arms (A/B/C from node 6.3's
closing-sequence definition) ran live — no waivers, none skipped.

**Sequencing + placement note (recorded, not hidden):** this record was owed by node 6.3's
closing sequence ("rides this node post-review from the train worktree") and closes here as
node 7.1's HARD submission gate, after 6.3's review + handoff stamp. Operator decision at 7.1
implementation close: the gate RAN from the `plan-2114` train worktree (the migrated learning
flows are the live extension there), and the record lands **on node 7.1's layer** — trading
the designed own-layer placement for no published-layer amend, no handoff re-stamp, and no
cascade. The gate's operative requirement (the record exists in 7.1's synchronized ancestry)
is satisfied as written.

Executed **2026-08-31** against the branch under test:

- **Gate worktree (the branch under test):**
  `/Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2114` (branch `plan-2114` — the
  train tip below 7.1, so the live arms exercise exactly the migrated Phase-6 code)
- **Tested commit SHA:** `84906a8c` (`plan-2114` at gate time — the 6.3 handoff-stamped head;
  unchanged across all three arms — Arm C's manifest pins `commit_sha: 84906a8c52d1…` and its
  resulting objective's title carries "audit at 84906a8")
- **Phase-boundary stack check (before the arms):** `perk objective stack status 2083` showed
  the published prefix 11/16 intact (layers 1.1–6.3 all `[published] handoff ready`, base
  `main`, next build-ready 7.1, **no findings**) — no base advance to absorb; the Phase-5 gate
  (its own record) ran immediately before against the same head.

## Arm A — learning capture (`/learn`, live wave)

Substrate (identity-safe, explicit): the worktree's plan-ref was snapshotted, temporarily
rebound to **plan #2098** ("Worker gate fixture: create the Phase-3 gate fixture file" — the
most recent landed plan with session pointers, `impl_run_ids:
01M0VBSTCMMAXP5KSG8EC3G6DK` + `01M0VC49PXRVHYHE1X11F72W1N`), and restored after the arm
(restore verified: the plan-ref reads `pr_id: 2114` again).

- Fresh session in the gate worktree; a real warm `/learn` through the migrated
  `pi/v1/learning/learn.ts` + `learning/` paths: evidence bundle gathered from #2098's
  recorded sessions (run `01M1C66GNTQX4PS4EJH0WNX6Z0`; the learn evidence artifact
  `learn-1788189663203.md` persisted in its run scratch), live analyst wave, reconcile.
- **Outcome: captured** — `perk:learn` issue **#2118** ("Learnings: Worker gate fixture:
  create the Phase-3 gate fixture file"), left open for normal docs-routing.

## Arm B — harvest (live, multi-lane)

- `perk learn harvest` from the gate worktree (run `01M1C6JPVNQS9TDK0GG2QK0SS1`): the
  run-scoped `harvest-manifest.json` planned **10 lanes**, and the live wave launched all of
  them (10/10 lane-child run directories) — the migrated installer, registration payload,
  `analyzeHarvest` feature op, and the live engine contract exercised end to end.
- **Outcome:** the curation objective **#2119** ("Harden the perk session substrate: stage
  scoping, skill delivery, config parsing, and context re-injection") was created from the
  harvested analyses, then **closed as sacrificial cleanup BEFORE Arm C** (the
  `origin_conflict` avoidance rule).

## Arm C — dream (live, `--no-sync`, full two-level analysis)

- `perk learn dream --no-sync` from the gate worktree (run `01M1C7Y97ECX9491HV87S0BVVE`;
  `--no-sync` per the one-revision discipline — the tested SHA never moved): the run-scoped
  `dream-manifest.json` bound **14 analyst lanes** over **66 docs** at
  `commit_sha 84906a8c52d1…`; the analyst wave and the reducer wave both completed (15
  lane-child run directories: the analyst lanes + the reducer tier).
- **Artifacts validated:** the finalized bundle `dream-analyses.json` (195,938 bytes;
  schema v1, doc_count 66, 14 lanes, 3 reducer angles, total_bytes 1,320,301) **decodes
  through the strict `decodeFinalizedDreamBundle`** (verified from the 7.1 worktree's
  migrated `learning/dreamReducer.ts` in a subprocess import). Recovery ran through the
  §8.63 dream-report gate into a real objective draft + save
  (`dream-report-transfer.json` + `objective.md` persisted in the run scratch); the gate
  validates the `dream_bundle_digest` marker against the finalized bytes, so the accepted
  recovery is the marker-integrity evidence.
- **Outcome:** objective **#2120** ("Learned-corpus dream curation — audit at 84906a8")
  saved for real, then **closed as sacrificial cleanup** (the 4.2 precedent).

## Skipped arms

None — all three arms ran live to completion; no degrades, refusals, or waivers were
observed or recorded.

## Cleanup

- The sacrificial curation objectives #2119 (harvest) and #2120 (dream) are closed;
  `perk:learn` #2118 stays open as a real capture for normal routing.
- The plan-ref rebind was restored; no worktrees or refs left behind; no branch heads moved
  (this record lands on node 7.1's layer as a docs-only commit — no re-stamp, no cascade).
