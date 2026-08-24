# Dogfood: the warm sync-conflict drive (Objective #2071, Node 3.1)

**Status: IN PROGRESS (scaffold committed 2026-08-23; Part B not yet executed).** This
validation record (the settled dogfood-record genre —
`docs/learned/workflow/doc-reconciliation.md` § "Validation-record reconciliation": Part A the
pre-committed repeatable protocol, Part B the dated captured evidence + defect log) proves the
**automated conflict-resolution loop** landed by objective #2071 nodes 1.1/2.1/2.2 (merge
commits `ba6da6c5` #2073, `2a79595f` #2075, `9c7ef426` #2077) **live on the real backlog**:
objective #2040's stalled base cascade, recovered end-to-end through the warm
retained-continuation drive. Happy path only — every failure arm stays offline-pinned in the
hermetic suites (§ Offline-pinned arms), referenced and never exercised live. The overall
verdict is written at evidence-fill time from the § Verdict criteria — never before.

**What this record proves** (the three landed pieces, driven as one loop):

- **the mode-aware resolver agent** (`agents/conflict-resolver.md`, node 1.1): fail-closed
  retained-continuation mode selected by the column-zero `RETAINED-CONTINUATION SENTINEL:`
  line; no fresh rebase; resolve → `git add` → `GIT_EDITOR=true git rebase --continue` to
  completion; verify; NEVER push; the report opens with the terminal outcome class;
- **the `/objective-sync` retained-continuation drive** (node 2.1, contracts §8.51): a
  mutating sync/continue refusing `rebase_conflict` corroborates the stop (the §8.49
  `for layer <node_id> ` freshness token), takes the resolver lease, persists the verified
  attempt increment (cap `CONFLICT_RESOLUTION_ATTEMPT_CAP = 2`, contracts §8.3), and injects
  the rendered dispatch (`prompts/stages/conflict-resolution-continuation.md`) — publication
  stays a human gesture (`continue: true` on explicit consent only);
- **the cold warm-route hint** (node 2.2): the cold CLI's resolution-real `rebase_conflict`
  refusal appends the copyable `/objective-sync <id>` sentence
  (`src/perk/delivery/sync.py::_warm_route_hint`).

**The substrate is real backlog** (the stacked-dogfood pattern): the train under recovery is
objective #2040 ("Learned-corpus curation — 2026-08 dream audit"), a 10-layer stacked docs
train genuinely stalled behind a main advance whose commits rewrote regions a layer edits — no
conflict is manufactured; the recovery is wanted for its own sake. This record's PR owns three
files (`docs/design/sync-conflict-resolution-dogfood.md`, `docs/index.md`, `CHANGELOG.md`) —
disjoint from the train's `docs/learned/**` by construction.

## Part A — the repeatable protocol

### Scope claim

Proves the warm retained-continuation drive **live, happy path only**: one human-approved
mutating base cascade → a corroborated `rebase_conflict` stop → the auto-dispatch → a
`completed` resolver outcome → zero resolver-driven publication → the explicit human
`continue` → a clean train at the new anchor. Everything else — every refusal, degrade, and
contention arm — is offline-pinned (below), referenced and deliberately not exercised on the
real backlog.

### Offline-pinned arms (referenced, never exercised live)

| Arm | Pinned by |
|---|---|
| Report-only corroboration failures (`corroborateSyncConflict`'s fail-closed matrix: no continuation, stale/foreign manifest, freshness-token mismatch, malformed status) | `extension/doors/objectiveStackDrive.test.ts` (the §8.51 corroboration matrix) |
| The shared attempt cap (`CONFLICT_RESOLUTION_ATTEMPT_CAP = 2`; the LOUD attempt-N-of-N report; the manual-remedy refusal past the cap) | `extension/doors/objectiveStackDrive.test.ts` + `extension/doors/submit.test.ts` (the shared-counter arms) |
| Resolver lease contention (busy holders, dead-pid reclaim, corrupt-lease judgment, raced-in fresh claims) | `extension/substrate/resolverLease.test.ts` (the claim-policy matrix — the ONLY home of these rules) |
| Continuation-manifest write failure (conflict retained NOTHING; residue cleaned; typed refusal) | `tests/test_delivery_sync.py` (the manifest-write-failure conflict arm) |
| The `rebase_conflict` refusal shape + the §8.49 `for layer <node_id> ` freshness token (dry-run retains nothing; real conflicts retain worktree + manifest) | `tests/test_delivery_sync.py` (the conflict-arm / freshness-token pins) |
| Non-`completed` resolver outcomes withhold continuation; the dispatch/decision seams of the drive | `extension/doors/objectiveStack.test.ts` + `extension/doors/objectiveStackDrive.test.ts` (the drive decision/delivery specs) |

### Provenance

- **The driving session** is an interactive `pi` session at the **repo root (main checkout)**
  of `mattgiles/perk` — NOT this plan's worktree — at a recorded `git rev-parse HEAD` that
  includes `9c7ef426` (#2077). `npm ci` freshness is noted (in-session doors run the
  checkout's extension source).
- **The resolver model** is recorded from the committed `[models.subagents]`
  `conflict-resolver` key (`openai/gpt-5.6-luna` at scaffold time; re-read at run time) and
  confirmed from what actually ran.
- **The driver split:** the human runs the gestures (approval, consent, captures); the
  implement-session executor authors this record from the captured artifacts. Captures land
  in an untracked scratch dir (e.g. `/tmp/sync-dogfood-2040-<date>/`); this record inlines
  the key excerpts (pointers rot); the scratch dir is disposable afterwards.

### The target train and its stall (implement-time verified 2026-08-23)

All facts below re-verified on 2026-08-23 from the worktree at `9c7ef426` (durable-authority
reads: `perk objective stack status 2040 --json` + git object inspection):

- **The train.** Objective #2040, `delivery_lineage 01M0QDMWFE5E5P918WFFYZE9FR`, 10 layers,
  branches `plan-2041 … plan-2069`, PRs #2042→#2070 (all OPEN, non-draft, bottom base
  `main`), editing only `docs/learned/**`. All 10 layers `published`/`synced`/`exact`, writer
  `active` (claimed) on every layer, `handoff ready` ×10, `landed_prefix_len: 0`, no
  blockers, no unresolved operation, no continuation, no orphaned residue.
- **The stall.** The train is anchored at pre-advance main `0c724e43…` while main sits at
  `9c7ef426…` — the status read carries exactly one information row, `base_advanced`, naming
  the cascade remediation (`perk objective stack sync 2040 --base`).
- **The conflict profile.** Two main-side commits touch train-edited `docs/learned` files:
  - `c247a931` (#2052) rewrote the exact regions **layer 4** (node 4, plan #2054, branch
    `plan-2054`, PR #2055) edits, in TWO files sharing base blobs with the layer's diff:
    - `docs/learned/workflow/mergeability-and-conflict-resolution.md` — main appended "The
      rule is now plumbed into the dispatch itself…" onto the exact paragraph-end line
      layer 4 anchors its own appended "*Unmet as of 2026-08 (dream audit)…*" paragraph on
      (both diffs from base blob `31078917`);
    - `docs/learned/workflow/dot-directory-migration.md` — both sides rewrite the same
      `perk_dir` seam paragraph (both diffs from base blob `1a926077`, hunks `@@ -46,11` on
      each side).
  - `3f7f84c9` (#2061) edited `docs/learned/workflow/shared-contracts.md` around line 145 —
    disjoint from layer 3's (plan #2050, PR #2051) hunks at lines ~14/39/250 — likely clean.
  - Expected profile: **one stop, at layer 4** (the refusal carries the `for layer 4 `
    freshness token), two conflicted files. The shared cap (2) accommodates one unforeseen
    extra stop before hand-resolution takes over.
- **No pending continuation.** `.perk/workflow/sync-continuations/` at the repo root is
  empty; when retained, the manifest path is
  `.perk/workflow/sync-continuations/01M0QDMWFE5E5P918WFFYZE9FR.json`.
- **The semantic wrinkle.** Layer 4's "*Unmet as of 2026-08*" claim is FALSE at the new base:
  main's `c247a931` (#2052) plus node 1.1's `ba6da6c5` (#2073) landed exactly the plumbing
  the paragraph declares unmet — the textual conflict is also a semantic contradiction the
  resolver must judge. § Gate criteria stay mechanical governs how that judgment is scored.

### Step 0 — preconditions (each a captured row)

- **Train health:** `perk objective stack status 2040 --json` → no unresolved operations, no
  pending continuation (`continuation: null`), all 10 layers claimed; any
  `dirty_worktree`-risk local claimed worktree is cleaned first (the sync path refuses on
  dirty claimed writers).
- **Conflict-reality precheck:** cold `perk objective stack sync 2040 --base --dry-run` must
  refuse typed `rebase_conflict` — the dry-run arm retains NOTHING (no manifest, no
  worktree; the message says so). A clean dry-run voids the node's premise → the
  premise-void contingency. The refusal message here is also the node-2.2 capture surface:
  a **dry-run** refusal is resolution-unreal, so the warm-route hint must NOT ride it — the
  hint is asserted on the real S2 stop instead.

### Live-run steps (gesture + capture at each boundary)

- **S1 — the warm cascade.** In the repo-root `pi` session: `/objective-sync 2040`; the human
  asks for the base advance; the door previews (`objective_stack_status`, then
  `objective_stack_sync { dry_run: true, base: true }`); on the presented preview the human
  approves → the mutating `objective_stack_sync { objective: 2040, base: true }` call (the
  approved call IS the consent — the human's mutating gesture is the drive's approval).
- **S2 — the conflict stop.** Capture verbatim: the `rebase_conflict` refusal (must carry the
  `for layer <node_id> ` freshness token AND the appended warm-route hint sentence), the
  continuation manifest bytes
  (`.perk/workflow/sync-continuations/01M0QDMWFE5E5P918WFFYZE9FR.json`), and remote-heads
  snapshot A: `git ls-remote origin 'refs/heads/plan-*'`.
- **S3 — the drive fires.** Capture: the auto-dispatch (the injected message rendering
  `conflict-resolution-continuation.md` — attempt N of 2, the task text opening with the
  concrete `cd <retained worktree>` command, the column-zero
  `RETAINED-CONTINUATION SENTINEL:` line, and the layer identity — node/branch/PR), the ONE
  `subagent` workflowScript dispatch (async: false, fresh context, the configured model),
  and the resolver child's report — it must OPEN with the terminal outcome class, and ONLY
  `completed` (rebase finished AND verification passed) may be offered for continue consent.
- **S4 — zero-publication check.** Remote-heads snapshot B (pre-continue) — must equal A.
- **S5 — the human continue.** Explicit consent in-session → `objective_stack_sync
  { objective: 2040, continue: true }`. A NEW conflict on continue loops S2–S5 (bounded by
  the shared cap: max 2 dispatches before a clean completion resets the counter).
- **S6 — clean at the new anchor.** Capture: remote-heads snapshot C (exactly one atomic
  multi-ref change vs B), the journal SYNC record on issue #2040 (the applied push,
  concluded), and `perk objective stack status 2040 --json` → no pending continuation, no
  unresolved operations, claimed prefix = all 10 layers at their new checkpoints, base
  anchor = the main head captured at approval (`base_advanced` absent unless main moved
  mid-run — a recorded benign deviation, not a defect).

### Evidence sources (pinned per fact)

- **Journal comments on issue #2040** — the durable authority for the SYNC operation record
  (prepared → completed, the before/after ref table).
- **`perk objective stack status 2040 --json`** outputs at each boundary (Step 0, S6).
- **The `git ls-remote origin 'refs/heads/plan-*'` snapshots** A/B/C (the zero-publication
  and atomicity facts).
- **The continuation manifest bytes** (S2) and the retained-worktree facts.
- **Inlined session-transcript excerpts** for the dispatch, the resolver report, and the
  consent gestures (warm-session facts are operator captures paired with their durable
  machine halves).

### Verdict criteria (per-criterion classification; PASS = all five observed-live)

| Criterion | Pass condition |
|---|---|
| **C1** — the warm arm fired | the auto-dispatch occurred on the human-approved mutating cascade's corroborated `rebase_conflict` stop (dispatch observed; the `conflict_resolution_attempts` counter incremented) |
| **C2** — retained-mode resolution to `completed` | the resolver resolved in retained-continuation mode (no fresh rebase; `git add` → `GIT_EDITOR=true git rebase --continue` to completion; verification passed; the retained worktree never aborted) |
| **C3** — zero resolver-driven publication | snapshot A == snapshot B; the resolver report records no push; the ONLY remote mutation is S5's single atomic leased multi-ref push, journal-recorded |
| **C4** — the explicit human continue | consent then `continue: true` — publication stayed a human gesture |
| **C5** — clean at the new anchor | the S6 captures: `stack status` clean, all 10 layers at new checkpoints on the new base anchor |

Each criterion classifies **observed-live / offline-pinned / unobserved-not-passed** from
artifacts and event projections — never from the human's summary label.

### Gate criteria stay mechanical

HOW the resolver resolves the layer-4 semantic contradiction (the false "Unmet as of
2026-08" claim vs main's landed plumbing) is OBSERVED and recorded as a content note in
Part B — it is not a gate criterion. Wrong resolved content is a defect-log **content
observation** routed to an ordinary layer-4 amend + suffix cascade afterwards — never a live
re-run of this gate, and never a C1–C5 failure by itself.

### Contingencies (each a pre-committed disposition, not an improvisation)

- **Premise void** (the Step-0 dry-run finds no conflict): still run the wanted cascade (it
  is the real recovery); the gate cannot pass — record the outcome, report to the human,
  route the node to replan. Never manufacture a conflict on the real backlog.
- **The drive does not fire** on a corroborated retained conflict stop: a node-2.1 defect —
  log it, the gate FAILS honestly; unblock the real train by the manual remedy (hand
  `git rebase --continue` in the retained worktree, then `continue: true`); any perk fix is
  NEW work on a separate PR, never this node's.
- **Resolver outcome ≠ `completed`:** continuation is withheld per contract; investigate;
  hand-finishing the rebase to unblock the train is allowed; C2 classifies honestly.
- **A third conflict stop** hits the attempt cap (a LOUD report is the contract, not a
  defect): hand-resolve the remainder; C1/C2 classify on the drive-resolved stops; the cap
  event is recorded.
- **A perk code defect requiring a fix:** the fix lands on its own PR; restart boundary —
  re-pin provenance and re-run from Step 0.
- **`remote_drift` at post-approval re-observation** (mid-run main advance): rerun sync; a
  benign-deviation row, not a defect.

### Sequencing (what merges when)

1. **Scaffold commit (this record's implement session, pre-run):** Part A complete + the
   Part B shells with explicit filled-at-evidence-time markers + the `docs/index.md` row.
2. **The live run:** the human drives S0–S6 at the repo root per Part A; the executor waits,
   then collects the scratch-dir artifacts and transcript excerpts.
3. **Evidence-fill:** Part B (dated evidence, the C1–C5 verdict matrix, the defect log —
   possibly empty, plus named non-defect observations), the ONE `[Unreleased]` CHANGELOG
   entry written to match the actual verdict (never pre-claimed), the trued-up index row +
   this record's Status header.
4. **Evidence is a pre-submit blocker:** the PR is never submitted with forward-looking
   prose (the early-merge internal-inconsistency rule) — unlike the stacked-* records, no
   draft-PR window exists; the record is complete before the PR opens.
5. ONE run-all `run_ci` (docs-only: the code-suffix globs skip; `changelog-check` runs),
   then submit.

### Out of scope

No failure-arm live exercises (they stay hermetic, § Offline-pinned arms). No changes to
sync/resolver code, prompts, contracts, or user docs — this node validates landed behavior
and changes none. No headless resolution; no automated publication of any kind. No landing
of the #2040 train and no review of its content — its own workflow owns those. Running the
live cascade before this PR merges is safe: this PR's files are disjoint from the train's,
and later main advances merely re-raise the `base_advanced` notice (a notice, never a
blocker).

## Part B — the captured evidence

> **Not yet executed — filled at evidence time.** Every section below is a shell until the
> live run completes; the Status header stays IN PROGRESS until then.

### Provenance rows

*Filled at evidence time:* main-checkout SHA at the run, `npm ci` freshness, the resolver
model that actually ran.

### Step 0 — preconditions

*Filled at evidence time:* the train-health status read; the conflict-reality dry-run
refusal.

### S1 — the warm cascade

*Filled at evidence time:* the preview, the approval, the mutating call.

### S2 — the conflict stop

*Filled at evidence time:* the verbatim refusal (freshness token + warm-route hint), the
manifest bytes, snapshot A.

### S3 — the drive fires

*Filled at evidence time:* the injected dispatch, the child dispatch call, the resolver
report (terminal outcome class first).

### S4 — zero-publication check

*Filled at evidence time:* snapshot B vs A.

### S5 — the human continue

*Filled at evidence time:* the consent gesture, the `continue: true` call and its result.

### S6 — clean at the new anchor

*Filled at evidence time:* snapshot C, the journal SYNC record, the terminal status read.

### Content note — the layer-4 semantic resolution

*Filled at evidence time:* how the resolver judged the "Unmet as of 2026-08" contradiction
(observed, per § Gate criteria stay mechanical).

### Defect log

*Filled at evidence time* (possibly empty, plus named non-defect observations).

### Verdicts

*Filled at evidence time:* the C1–C5 matrix, classified from artifacts/event projections.
