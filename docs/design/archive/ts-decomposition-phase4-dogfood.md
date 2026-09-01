# Dogfood record: ts-decomposition Phase 4 gate (plan + objective flows)

**Status:** validation record (the `*-dogfood.md` archive genre) for the objective's Phase-4
close: *perk uses the migrated plan flow to drive the next slice, completes one objective
authoring path interactively (deny→revise AND approve→verified save), then reloads and forks the
resulting session without losing verified state* — after the Phase-4 feature slices (Node 4.1:
the plan flow into `authoring/plan/` + `pi/v1/`; Node 4.2: the three objective flows into
`authoring/objective/` + `pi/v1/`, the session identity lifecycle into `session/lifecycle.ts`,
`extension/factories/` deleted whole).

**Sequencing note (recorded, not hidden):** this gate ran AFTER node 5.1's layer was accepted —
the gate's first arm IS node 5.1's planning session (it cannot precede 4.2's review by the
plan's own sequencing), and the operator explicitly waived the Phase-5 start gate for node 5.1
when the missing record was surfaced at that node's implementation start. This record closes the
gate before the train lands.

Executed **2026-08-26** against the branch under test:

- **Gate worktree (the branch under test):**
  `/Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2103` (branch `plan-2103` — node
  4.2's own layer head, so the interactive arms test exactly the Phase-4 code)
- **Tested commit SHA:** `c0d84dbf` (`plan-2103` at gate time — the 4.2 handoff-stamped head)
- **Phase-boundary stack check (before the gate):** `perk objective stack status` showed the
  published prefix 7/16 intact (layers 1.1/1.2/2.1/3.1/4.1/4.2/5.1 all `[published] handoff
  ready`, base `main`), and `origin/main` (`40a30df8`) is an ancestor of the train tip
  (`f988b700`) — **no base advance to absorb**, so no `stack sync --base` was needed and the
  gate ran against the as-is train.

## Arm 1 — the migrated plan flow drives the next slice (node 5.1's planning session)

The factory loop (draft → review → approval save → node link) through the migrated `pi/v1` +
`authoring/` + `session/` paths, observed on the real next slice:

- **Saved plan:** issue **#2105** ("Confine report-wave transport and add per-registration
  pending state"), created `2026-08-25T23:27:30Z`, planning-session run id
  `01M0X0G6YDW9V6QCDWFED17QM2`, header `objective_id: '2083'` / `objective_node_id: '5.1'` /
  `delivery_lineage: 01M0STVYM6VX2M9C429EHE80M7` / `predecessor_plan_id: '2103'` — the stacked
  lineage threaded by the migrated planning carrier.
- **Node link:** roadmap node 5.1 carries `pr: '#2105'` and moved `pending → planning →
  in_progress` through the migrated `objective_node` path (the claim carrier).
- **Downstream proof the artifact is real:** plan #2105 was implemented and published as PR
  #2106 (layer 7/7 of the train, handoff-stamped) — the plan the migrated flow produced drove a
  full implement → review → address → ready pass.
- **Session observations (human):** the planning session ran from a train worktree and the
  factory loop (draft → review → approval save → node link) behaved normally — no anomalies
  observed (operator-confirmed at gate time).

## Arm 2 — one objective path completes interactively (sacrificial objective)

The human's interactive run, from the gate worktree (`perk objective author`):

- **Authoring session run id:** `01M0Z88NBSG2VHC956HKFD951M` (threaded into the saved
  objective's header by the migrated save path — the identity observation rides the artifact).
- **Draft:** a deliberately sacrificial objective ("Phase-4 gate fixture" — one phase, trivial
  nodes) drafted through `objective_draft`.
- **Deny→revise round:** one DENY with feedback through `plan_review`'s objective arm; the
  draft visibly revised (operator-confirmed at gate time).
- **Approve→verified save:** the revised draft APPROVED; the flow flipped read-write and the
  verified save minted issue **#2107** ("Phase-4 gate fixture",
  <https://github.com/mattgiles/perk/issues/2107>, `perk:objective` label, created
  `2026-08-26T14:47:50Z`, header `status: active`) — the gate's exit observation. Session
  output: `objective APPROVED by reviewer.` / `Saved objective #2107 → …/issues/2107`.
- **Anomalies:** none — the draft → review → save flow behaved normally (operator-confirmed).

## Arm 3 — reload + fork without losing verified state

`/reload` on the arm-2 session, then a fork — both observed by asking each session's agent to
report its scratch-banner run id and its draft/objective state:

- **Reload:** identity kept — the same run id `01M0Z88NBSG2VHC956HKFD951M` (no re-mint); the
  draft artifact still resolves
  (`.perk/workflow/scratch/runs/01M0Z88NBSG2VHC956HKFD951M/data/objective-draft.json`, 1641
  bytes, the approved 3-node version, sha `6a36e17b…`); `active_objective` reconstructed —
  #2107 live in the workflow (`perk objective show 2107`: 3 pending nodes, `next: 1.1`).
- **Fork:** child run id `01M0Z88NBSG2VHC956HKFD951M.3` — the `<parent>.<n>` derivation
  (`deriveForkRunId` returns max sibling suffix + 1; `.1`/`.2` already existed in the session's
  history, so `.3` is the correct next free suffix). `active_objective` inherited — the child
  reported #2107 (and correctly distinguished it from #2083, the decomposition objective the
  worktree's layer context points at). No stage impersonation observed — the child behaved as
  an ordinary authoring-session fork.
- **Artifact isolation (probe-covered, recorded honestly):** the child's draft probe read the
  parent's scratch file straight off disk (trivially present — shared cwd), so it did NOT
  exercise the session-level isolation semantics; that sub-check rides the harness suite per
  the gate's "headless-probe-able arms may run as harness-shaped probes":
  `extension/session/workflowSession.test.ts` pins "a pointer keyed to a foreign run reads
  absent (fork isolation)" over BOTH backings. The disk probe did confirm the fork left the
  parent's artifact intact.

## Skipped arms

None skipped. One sub-check ran as a harness probe instead of an interactive observation (the
fork artifact-isolation read — see Arm 3), per the gate's explicit "headless-probe-able arms
may run as harness-shaped probes" allowance.

## Cleanup

The sacrificial objective **#2107 closed as cleanup** (the plan's default disposition;
operator-confirmed), with a closing comment pointing at this record. The gate sessions were
disposable authoring sessions in the gate worktree — no repo state to clean; no sacrificial
branches or PRs were created.

## Phase-boundary stack sync (after the gate)

Re-checked after the gate: `origin/main` (`40a30df8`) is still an ancestor of the train tip —
**no base advance to absorb**, so no `stack sync --base` cascade was needed and no ready stamps
were staled by sync. This record commits on the train tip (layer 5.1, `plan-2105` / PR #2106 —
the operator's recorded call: one commit, only the tip's stamp to re-run, node 4.2's stamped
layer untouched), so it exists on the train before any landing.
