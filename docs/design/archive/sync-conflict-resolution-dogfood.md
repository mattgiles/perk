# Dogfood: the warm sync-conflict drive (Objective #2071, Node 3.1)

**Status: PASSED 2026-08-23** (run journal-stamped 2026-08-24T03:50–03:51Z). This
validation record (the settled dogfood-record genre —
`docs/learned/workflow/doc-reconciliation.md` § "Validation-record reconciliation": Part A the
pre-committed repeatable protocol, Part B the dated captured evidence + defect log) proves the
**automated conflict-resolution loop** landed by objective #2071 nodes 1.1/2.1/2.2 (merge
commits `ba6da6c5` #2073, `2a79595f` #2075, `9c7ef426` #2077) **live on the real backlog**:
objective #2040's stalled base cascade, recovered end-to-end through the warm
retained-continuation drive. Happy path only — every failure arm stays offline-pinned in the
hermetic suites (§ Offline-pinned arms), referenced and never exercised live. **Overall
verdict: PASS — all five criteria (C1–C5) observed live on the first attempt; the defect log
is empty** (five named non-defect observations; the layer-4 semantic contradiction is recorded
in the pre-committed content note, routed to the train's own workflow).

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
files (`docs/design/archive/sync-conflict-resolution-dogfood.md`, `docs/index.md`, `CHANGELOG.md`) —
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

> **Execution COMPLETE (2026-08-23 local; journal timestamps 2026-08-24Z).** Step 0 and the
> durable captures ran from the executor's shell; the human drove every gesture (approval,
> consent) in the interactive repo-root session, pasting the transcript excerpts inlined
> below. Scratch captures lived in `/tmp/sync-dogfood-2040-2026-08-23/` (disposable); every
> decisive excerpt is inlined here.

### Provenance rows

| Fact | Observed |
|---|---|
| Driving checkout | `~/dev/github/mattgiles/perk` (repo root, main checkout), `git rev-parse HEAD` → `9c7ef426d60f74d81d36adb4b6b874030b967774` (includes #2077), `git status --short` empty |
| Extension freshness | `npm ci` run 2026-08-23 immediately before the driving session (allow-scripts advisory only) |
| Resolver model | committed `[models.subagents] conflict-resolver = "openai/gpt-5.6-luna"`; confirmed from the child run's `_meta.json`: `model: openai/gpt-5.6-luna` |
| Driver split | held — the human ran the gestures; the executor captured the durable halves and authored this record from them |

### Step 0 — preconditions (captured 2026-08-23, executor shell, worktree at `9c7ef426`)

- **Train health** (`perk objective stack status 2040 --json`): `unresolved_operation: null`,
  `continuation: null`, 10/10 layers `published`/`synced`/`exact` with `writer: active`
  (claimed), orphaned residue none; exactly ONE information row — `base_advanced`
  (`0c724e43…` → `9c7ef426…`, remediation `perk objective stack sync 2040 --base`). No
  dirty-worktree cleanup was needed.
- **Conflict-reality precheck** (cold `perk objective stack sync 2040 --base --dry-run
  --json`, exit 1) — the premise held, verbatim:

  ```json
  {"success": false, "error_type": "rebase_conflict", "message": "the candidate rebase for
  layer 4 ('plan-2054' onto a0c043b944caa0e884d69bc4786ce4d999d08cfe) hit a conflict — this
  was a dry-run preview, so nothing was retained; a real sync would retain the conflicted
  worktree here under a continuation manifest"}
  ```

  The `for layer 4 ` freshness token present; `sync-continuations/` still empty afterwards
  (nothing retained); **no warm-route hint on the dry-run arm** — correct by design (the
  hint rides only resolution-real refusals), the by-omission half of the node-2.2 capture.
- **Pre-run remote heads** captured (all 10 train branches at their published heads — the
  same SHAs the status read reports); this closes the zero-publication chain end to end
  (§ S4).

### S1 — the warm cascade

Executed 2026-08-23 (operator, interactive `pi` at the repo root). `/objective-sync 2040`;
the human asked for the base advance verbatim: "advance the stack onto current main —
cascade with the base advance". The door previewed per its own guidance —
`objective_stack_status`, then `objective_stack_sync { dry_run: true, base: true }` — and
the preview refused typed `rebase_conflict` at layer 4 ("…this was a dry-run preview, so
nothing was retained…"), which the session presented honestly with the expected real-run
consequences before asking for approval. The human approved: "yes — run the real mutating
sync with the base advance" → the mutating `objective_stack_sync { objective: 2040,
base: true }` call (the approved call IS the consent). *Benign note:* preview rebase
candidates mint fresh commit SHAs per run (the cold precheck's `onto a0c043b9…`, the warm
preview's `onto ba0778b3…`, the real run's `onto 500b5b0a…` — same content, fresh
committer stamps).

### S2 — the conflict stop

The mutating call refused typed `rebase_conflict` (operator capture, verbatim — the tool
result in the driving session):

> the candidate rebase **for layer 4** ('plan-2054' onto
> 500b5b0ab214bd8ea3794e7289f34ad81be52e98) hit a conflict — the conflicted worktree is
> retained at `/Users/mattgiles/dev/github/mattgiles/perk/.worktrees/sync-01M0RW2HS3VSWG1T8GN2R2JVYH`
> under the continuation manifest
> `/Users/mattgiles/dev/github/mattgiles/perk/.perk/workflow/sync-continuations/01M0QDMWFE5E5P918WFFYZE9FR.json`;
> no remote ref and no journal record was created. Resolve the conflict in the retained
> worktree (`git rebase --continue`) and run `perk objective stack sync --continue`, or
> discard it with `perk objective stack sync --abort`. **Automated resolution is available
> from a read-write perk session: run `/objective-sync 2040` — on your approval it
> dispatches the conflict resolver into the retained worktree and hands publication back to
> you.**

The §8.49 `for layer 4 ` freshness token AND the appended node-2.2 warm-route hint, both on
the resolution-real arm exactly as pinned. **The continuation manifest** (bytes captured
pre-continue): `operation_id: 01M0RW2HS3VSWG1T8GN2R2JVYH`, `objective_id: '2040'`, the
lineage, `run_id: 01M0Q8AEJGDZC89F6Q651AN2T5` (the driving session), `include_base: true`,
`captured_base_head: 9c7ef426…` (= main at approval), `conflict_node_id: 4`, created
`2026-08-24T03:12:32Z`; layers 1–3 carry their rebased `candidate_sha`s
(`587b3e01…`/`c7bffb00…`/`500b5b0a…`), layer 4 `candidate_sha: null` with
`new_parent_edge: 500b5b0a…`, layers 5–10 `new_parent_edge: null` (unreached). **Remote-heads
snapshot A**: all 10 train branches at their original published heads — byte-identical to the
pre-run Step-0 heads. *(Operator-timing note: A was captured after the resolver child had
already finished — still pre-continue; the chain pre-run == A == B keeps the
zero-publication closure exact.)*

### S3 — the drive fires

- **The auto-dispatch** (operator capture — the injected message, arriving immediately after
  the refusal with no human gesture in between): "perk /objective-sync — objective #2040's
  stack cascade stopped on a rebase conflict in layer 4 (branch plan-2054, PR #2055); the
  conflicted worktree was retained. **This is attempt 1 of 2.**" — the rendered
  `conflict-resolution-continuation.md` carrying: the ONE-`subagent`-call workflowScript
  recipe (`async: false`, `context: "fresh"`, `model: "openai/gpt-5.6-luna"` — the
  configured `[models.subagents]` value, named as such), the task text opening with the
  concrete `cd /Users/…/.worktrees/sync-01M0RW2HS3VSWG1T8GN2R2JVYH` command, the column-zero
  `RETAINED-CONTINUATION SENTINEL: resume the in-progress rebase in …` line, the layer
  identity (node 4, branch plan-2054, PR #2055), and the completed-only outcome gate with
  the never-unprompted `continue` consent rule. The rendered "attempt 1 of 2" IS the
  persisted verified increment (the dispatch injects only after the counter write reads
  back).
- **The child run**: one `subagent` workflowScript dispatch, foreground, 1 lane
  (`perk.conflict-resolver [fresh] (gpt-5.6-luna)`), 42 tool uses, 3m35s. **The report opens
  with the terminal outcome class** — verbatim head of the child's output artifact:

  ```text
  completed

  Mode: retained-continuation
  Resolved files: `docs/learned/workflow/dot-directory-migration.md`
  Resolve→add→continue rounds: 1
  ```

  …followed by the resolution summary ("kept the canonical deletion of `perk_dir`/`perkDir`
  while applying the incoming triad-scope and workflow-cache exception edits"), "Rebase
  completed at `e5b805d3`; the worktree is clean with no rebase in progress. **No push was
  performed**; the human resumes with `sync --continue`.", and the verification table
  (10 learned-doc cue tests passed; `perk learn docs-check` passed with stale pointers 0;
  conflict-marker scan + `git diff-tree --check` clean; the mergeability doc at 12,262 bytes
  under the 12,288 limit; no staged/uncommitted files).
- **Retained-mode facts, independently verified read-only in the worktree** (executor,
  pre-continue): rebase COMPLETE (no `rebase-merge` dir), clean tree, HEAD =
  `e5b805d3850d0418dcee09cdb2e0a3bf8c0e47bc` sitting atop `500b5b0a…` (the layer-3
  candidate = layer 4's manifest `new_parent_edge` exactly); the worktree was never aborted
  (it survived intact until S5's continue consumed it). No fresh rebase: the child resumed
  the in-progress one (1 resolve→add→continue round on the single conflicted file).
- **Late supervisor progress echoes** arrived after the child had completed; the driving
  session correctly held (presented the completed outcome, did NOT call `continue` on its
  own) — the consent rule observed under a mild race (a non-defect observation below).

### S4 — zero-publication check

Snapshot B (pre-continue, executor shell): **byte-identical to snapshot A** (`diff` empty
over all `refs/heads/plan-*`), and both equal the pre-run Step-0 heads — across the entire
stop + resolve window, no remote ref moved.

### S5 — the human continue

Explicit consent in-session ("yes — resume the cascade: continue") → `objective_stack_sync
{ objective: 2040, continue: true }` → completed: "The cascade resumed and completed —
operation 01M0RW2HS3VSWG1T8GN2R2JVYH is done", all 10 layers republished (the session's
before→after table matches the journal's observed set below), "The continuation worktree
and manifest were consumed by the completed operation." No new conflict on continue — the
S2–S5 loop ran once (1 dispatch of the cap's 2).

### S6 — clean at the new anchor

- **Snapshot C** (post-continue): vs B, **exactly 10 refs changed — the train branches
  only**, one atomic multi-ref change to `587b3e01…` (plan-2041), `c7bffb00…` (plan-2045),
  `500b5b0a…` (plan-2050), `e5b805d3…` (plan-2054, the conflict-resolved head), `9dc76039…`
  (plan-2056), `be66f0c6…` (plan-2058), `d6ca9ad5…` (plan-2062), `3b40582a…` (plan-2064),
  `637f0ba3…` (plan-2067), `c39d1af8…` (plan-2069). Layers 1–3 landed at the manifest's
  candidate SHAs exactly.
- **The journal SYNC record** (issue #2040, the durable authority): operation
  `01M0RW2HS3VSWG1T8GN2R2JVYH`, `prepared` `2026-08-24T03:50:57Z` (before: base `main` @
  `9c7ef426…`; the 10 branches + 10 PRs at their original heads) → `completed`
  `2026-08-24T03:51:28Z` (observed: the 10 branches AND the 10 PR heads at the new SHAs
  above) — one operation, concluded; `run_id` = the driving session's.
- **Terminal train read** (`perk objective stack status 2040 --json`): `unresolved_operation:
  null`, `continuation: null`, **information rows EMPTY** (`base_advanced` GONE — main never
  moved mid-run, so the benign-deviation arm stayed unfired), `observed_base_head_sha:
  9c7ef426…` = layer 1's new `parent_checkpoint_sha` = the manifest's `captured_base_head`
  exactly (the base anchor IS the main head captured at approval); all 10 layers
  `published`/`synced`/`ready`/`exact` at the new checkpoints; orphaned residue none.
- **Local residue**: the retained worktree gone, the manifest consumed, no
  `refs/perk/sync/*` temp refs remain — the one leftover is the designed
  `…json.resolver-lock` claim dir (below).

### Content note — the layer-4 semantic resolution (observed, not gated)

- **The textual conflict was ONE file, not the predicted two.**
  `docs/learned/workflow/dot-directory-migration.md` conflicted; the resolver judged the
  semantic contradiction **correctly**: it kept the new base's truth (main's `c247a931`
  paragraph — `perk_dir`/`perkDir` deleted as dead code) over the layer's stale rewrite of
  the same paragraph ("still returning `.pi` … currently caller-less"), while preserving
  the layer's three non-conflicting hunks (distillation header, `_MIGRATIONS` triad scope,
  workflow-cache exception) — verified by diffing the resolved commit against its parent.
- **`docs/learned/workflow/mergeability-and-conflict-resolution.md` auto-merged** — git
  never stopped on it (main's sentence extends the paragraph's last line; the layer's
  paragraph inserts after it), so the resolver was never asked to judge it. The rebased
  layer-4 content therefore now carries the semantic contradiction verbatim: main's "The
  rule is now plumbed into the dispatch itself…" immediately followed by the layer's
  "*Unmet as of 2026-08 (dream audit):* the shipped resolver task text does not implement
  this rule…" — a claim this very run's S3 capture disproves live (the injected dispatch
  DID open with the concrete `cd` command). **Disposition:** a content observation per
  § Gate criteria stay mechanical — not a resolver defect (no conflict was presented to it)
  and not a gate criterion; the stale claim is the layer's own authored content, made false
  by the base advance, and its fix is an ordinary layer-4 amend owned by the #2040 train's
  own curation workflow (this record's PR does not touch the train's files).

### Defect log

**No defects.** Five named **non-defect observations**:

1. **One conflicted file, not two (S2/S3):** the predicted profile said two; the
   mergeability doc auto-merged (adjacent, non-overlapping textual edits). A
   profile-prediction deviation, not a criterion — and the auto-merge is what routed the
   semantic contradiction into the content note above.
2. **Preview candidates mint fresh SHAs per run (Step 0/S1):** the cold precheck, the warm
   preview, and the real run each reported a different `onto <sha>` for the same layer-3
   candidate content — rebase re-commits with fresh committer stamps; benign.
3. **The consumed operation leaves the resolver-lock dir**
   (`01M0QDMWFE5E5P918WFFYZE9FR.json.resolver-lock` beside the deleted manifest): designed —
   the claim is deliberately never released on dispatch and self-heals via the
   reclaimability predicate (operation consumed ⇒ reclaimable;
   `extension/substrate/resolverLease.ts` header). The status door's residue sweep reports
   none — correctly, this is not orphaned residue.
4. **Late snapshot-A capture (S2):** operator timing — A was taken post-resolve rather than
   at the stop; closure restored exactly by pre-run == A == B (and the refusal itself
   attests "no remote ref … was created" at the stop).
5. **Late supervisor progress echoes (S3):** two child progress notifications rendered
   after the workflow call had already returned; the driving session correctly treated them
   as stale echoes and held for consent — the completed-only gate was never at risk.

### Verdicts

Derived from the artifacts and event projections above — never from the human's summary
label.

| Criterion | Verdict | Surviving evidence |
|---|---|---|
| **C1** — the warm arm fired | **PASS (observed-live)** | the injected dispatch arrived unprompted on the human-approved mutating cascade's corroborated `rebase_conflict` stop (S2 refusal → S3 injection, no human gesture between); the rendered "attempt 1 of 2" is the persisted verified increment |
| **C2** — retained-mode resolution to `completed` | **PASS (observed-live)** | the child report opens `completed` / `Mode: retained-continuation` / 1 resolve→add→continue round; verification table passed; the worktree independently verified rebase-complete, clean, HEAD `e5b805d3` — never aborted, no fresh rebase |
| **C3** — zero resolver-driven publication | **PASS (observed-live)** | pre-run == snapshot A == snapshot B (byte-identical); the report records "No push was performed"; the ONLY remote mutation is S5's single atomic 10-ref push, journal-recorded as operation `01M0RW2HS3VSWG1T8GN2R2JVYH` |
| **C4** — the explicit human continue | **PASS (observed-live)** | consent gesture in-session, then `continue: true`; the session withheld continuation until asked (including across the late-echo race) |
| **C5** — clean at the new anchor | **PASS (observed-live)** | terminal status: no continuation, no unresolved operations, no information rows, all 10 layers at the new checkpoints, base anchor = the approval-captured main head `9c7ef426…` |

**Overall: PASS** — all five criteria observed live on the first attempt; no criterion
classified offline-pinned or unobserved-not-passed; the offline-pinned failure arms stand
referenced in Part A, none fired.
