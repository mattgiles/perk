# ts-decomposition Phase-7 dogfood + objective #2083 closing record

**Status:** validation record (Objective #2130, Node 1.1; authored 2026-09-02). This record
closes **three gates at once**:

1. the **Phase-7 dogfood gate** (defined at Node 7.5 of
   `docs/planning/ts-decomposition/migration-and-verification.md`);
2. the **#2083 objective closing gate** (also defined at Node 7.5 — the same ordered
   protocol);
3. the folded **Node 7.3 and Node 7.4 live-proof closeouts** (each node's own pending
   protocol).

**Why this record supersedes the original protocols' arms:** all three protocols bound
their arms to the pre-land #2083 train — arm E synced *2083's* stack, arm C readied *7.5's
own plan*, and the 7.3/7.4 closeouts ran `perk ready` / the stack dry-runs from *the train
worktree* against the open train. The train landed (16 stacked layers squash-merged as
`40a30df8..a5dc757e` on `main`) and objective #2083 closed **before any arm ran**, so the
arms are unexecutable as written. Closure is therefore recorded here honestly: the landing
evidence PLUS fresh live legs of the **same migrated delivery bindings**, re-bound to
objective #2130 node 1.1 (this record's own plan, #2131) and to #2130's own delivery
train. No result below is invented; every leg is classified **observed-live** or
**forward-referenced**, and nothing is claimed "passed" without an artifact.

**Leg → original-arm mapping** (the Node 7.5 protocol's arms; the 7.3/7.4 folds noted):

| Fresh leg (this record) | Original arm | Folds |
| --- | --- | --- |
| Landing evidence (no session) | — (the precondition all arms assumed) | — |
| Leg D — `/commit-and-compact` drives this record's own first commit | Arm D | — |
| Leg A — run-all `run_ci` before each `/submit`; definitive at the final published head | Arm A | — |
| Leg B — `/submit` publishes node 1.1's plan | Arm B | — |
| Leg E — `/objective-stack 2130` + `objective_stack_sync` (dry-run, then `base: true`) + `objective_stack_recover`/`objective_stack_land` dry-runs on #2130's train | Arm E | Node 7.4 closeout |
| Leg C — the warm `/ready` on node 1.1's plan (post-review, human-run) | Arm C | Node 7.3 closeout |

## Part A — the protocol (pre-committed)

In execution order. Each leg names its session-shape precondition. The migrated bindings
under test all landed on the #2083 train and are live in any session launched from this
worktree (branch `plan-2131`, branched from `main` @ `53fe2d7d`).

1. **Landing evidence** *(no session needed)*: objective #2083 is CLOSED
   (`gh issue view 2083`); `git log --oneline 40a30df8..a5dc757e` lists exactly the 16
   squash-merge commits, each subject carrying its merge PR number (`#2090` … `#2129`) —
   the local-range derivation; no per-plan remote lookups.
2. **Leg D — `/commit-and-compact`** *(this implementation session, with the drafted
   node-1.1 docs as the real dirty tree)*: the migrated
   `pi/v1/delivery/commitCompact.ts` binding drives the commit — the driven commit IS this
   record's own first commit; the observed report/continuation render is appended in
   commit 2.
3. **Leg A — run-all `run_ci`** *(the implementing session; the migrated
   `pi/v1/delivery/ci.ts` binding)*: one run-all green immediately before EVERY `/submit`
   publication — the repo discipline. The **definitive instance is the run at the final
   published head** (after commit 3, the last content change). The commit-2-head run's
   green result is recorded observed-live in commit 3's addendum; the final-head run
   cannot be recorded in-file without moving the head, so **this protocol statement IS its
   recording** (the 7.3-note precedent), and its green report in the implementation
   session is definitive per the repo discipline.
4. **Leg B — `/submit`** *(the implementing session's terminating gesture; the migrated
   `pi/v1/delivery/submit.ts` binding)*: publishes this node's plan as a draft PR; the PR
   number is recorded in commit 3's addendum.
5. **Leg E — the stack family** *(a fresh post-submit session in this plan's worktree —
   at layer 1 the plan worktree IS the train's bottom layer, so this is "the train
   worktree"; folds the Node 7.4 closeout)*: `/objective-stack 2130`, then
   `objective_stack_sync {objective: "2130", dry_run: true}`, then
   `objective_stack_sync {objective: "2130", base: true}` (the real base-absorbing sync —
   a no-op outcome is still a live exercise and is recorded as observed), then
   `objective_stack_recover {dry_run: true}`, then `objective_stack_land {dry_run: true}`
   — all through the migrated `pi/v1/delivery/stackStatus.ts` / `stackSync.ts` /
   `stackRecover.ts` / `stackLand.ts` bindings. Session id + observed renders recorded in
   commit 3 (the LAST content change on the branch).
6. **Leg C — the warm ready** *(a fresh session in this plan's worktree, post-review,
   run by the human; folds the Node 7.3 closeout)*: an explicit **forward reference** —
   after review, the human runs the warm `/ready` (the in-session command/tool of
   `pi/v1/delivery/ready.ts::installReadyBindings`); the migrated binding performs the
   SHA-bound stamp through its cold worker (`perk pr ready`) and drives the
   `shared/contracts.md` §8.66 ready-time reconcile continuation in-session. The durable
   evidence is the **`perk:stack-ready-stamp` journal comment on objective #2130's issue**
   (the §8.43 append-only stamp naming plan + SHA — written by
   `src/perk/delivery/journal.py` via `src/perk/delivery/publish.py`), NOT the PR; this
   record names that comment location as the verification pointer. No post-ready commit;
   the record does not chase re-stamps.

**Surface correction carried from the 7.3 fold** (recorded here and in the 7.3 update
note): the migrated ready binding's live exercise is the **warm in-session `/ready`**; the
cold `perk ready` CLI is the Python continuation wrapper
(`src/perk/cli/commands/pr/ready_cmd.py` — worker mechanics plus the launch of the
ready-time reconcile session, whose in-session drive, `driveReadyContinuation`, is adapter
code).

**What merges when:** Part B is complete except legs A-final and C before this node's PR
is reviewed; leg C is definitionally post-review and stays a forward reference; commit 3
is the last content change on the branch.

## Part B — evidence

### Landing evidence — observed-live (2026-09-02, no session)

`gh issue view 2083` → state **CLOSED** (title: "TypeScript decomposition: typed features
and Pi application adapters").

`git log --oneline 40a30df8..a5dc757e` → exactly 16 commits:

```text
a5dc757e Migrate /commit-and-compact to typed delivery op; close Phase 7 gate (#2129)
353fb53a Migrate delivery train-operation family and per-plan land into delivery/ (#2127)
6c6e61ad Migrate ready/handoff transitions to typed delivery operations (#2125)
5c96d10e Migrate address/submit doors into typed delivery ops under pi/v1 (#2123)
f34ac388 Migrate stack-status read and CI execution to delivery/ feature home (#2121)
f8b54e94 Migrate harvest and dream workflows into learning/ as typed feature ops (#2115)
3c696ef1 Migrate audit workflow into learning/ as typed op with Pi adapter (#2113)
f22f8a46 Migrate learn capture and learn-docs/code routing into learning/ feature home (#2111)
52d67504 Move code review behind typed operations and retire /pr-review-dynamic (#2109)
10abe49c Confine report-wave transport and add per-registration pending state (#2106)
aa160242 Extract objective authoring, review, and planning into typed feature ops (#2104)
fd861091 Migrate plan authoring, save, and review flows to typed feature ops (#2102)
38b61ecc Confine stage execution behind worker seam with private SDK adapter (#2100)
2b6da55c Migrate gist slice to typed authoring/session modules with v1 installer (#2095)
9562092a Break config↔bindings import cycle and add import-direction guards (#2092)
3f43ae85 Refresh the ts-decomposition baseline at 95ff7cc7 + freeze the binding inventory (#2090)
```

### Leg D — `/commit-and-compact` — pending its execution (this record's first commit)

The protocol places leg D at this record's own first commit: this file (plus the D1–D4
amendments) is the real dirty tree the migrated binding commits. The observed
report/continuation render is appended here in commit 2.

**Commit-2 addendum — observed-live (2026-09-02, the node-1.1 implementation session,
run `01M1HFJKZDBBGJNKE1XK085BQE`):** the operator ran `/commit-and-compact` with the
five drafted deliverables as the real dirty tree. Observed sequence, in order:

1. The migrated binding injected the commit-drive instructions into the session —
   "Commit the work completed so far — perk will compact this session once your commit
   is in." with the three-step drive (review the working tree; stage exactly the changes
   that belong — no blanket `git add -A`; commit with a descriptive message, do NOT
   push) and the nothing-to-commit escape hatch ("perk will then skip compaction").
2. The driven commit — this record's own first commit — landed as `f0b5633e`
   ("Reconcile ts-decomposition contract, pin storage-freedom policy + #2130 baseline,
   author Phase-7 closing record"): 5 files changed, 620 insertions(+), 8 deletions(-),
   exactly the five deliverables staged by path; not pushed.
3. Compaction ran automatically once the run settled, and the continuation resumed the
   session against plan #2131 with the driven commit presented as evidence: "Compaction
   completed successfully. Resume work on the active plan #2131 …" followed by the
   untrusted `<commit-evidence>` block listing `f0b5633e` as ahead of the
   invocation-time HEAD, plus the reorient-from-repository-evidence instructions.

Leg D is **closed observed-live**: the migrated `/commit-and-compact` binding drove a
real commit→compact→resume cycle on this record's own first commit.

### Leg A — run-all `run_ci` — protocol-recorded + one observed-live instance

- Commit-2-head run: recorded in commit 3's addendum.
- Final-head run (the definitive instance): protocol-recorded — Part A step 3's statement
  is the recording (the 7.3-note precedent); its green report in the implementation
  session is definitive per the repo discipline.

*(Commit-3 addendum lands here.)*

*(Node 5.1 reconciliation, 2026-09-04: commit 3 never landed — this run is unrecorded; see
the addendum at the end of this record.)*

### Leg B — `/submit` — forward-referenced until commit 3

*(Commit-3 addendum lands here: the PR number.)*

*(Node 5.1 reconciliation, 2026-09-04: commit 3 never landed — leg B is resolved-completed
from durable artifacts; see the addendum at the end of this record.)*

### Leg E — the stack family — forward-referenced until commit 3

*(Commit-3 addendum lands here: session id + the five observed renders.)*

*(Node 5.1 reconciliation, 2026-09-04: commit 3 never landed — leg E is UNOBSERVED — NOT
PASSED; see the addendum at the end of this record.)*

### Leg C — the warm `/ready` — forward-referenced (definitionally post-review)

Verification pointer: the `perk:stack-ready-stamp` journal comment on objective #2130's
issue (github #2130), naming this plan (#2131) and the exact verified published head SHA.
This record is complete without a post-ready commit.

### Cleanup / residue

No sacrificial state is created by this protocol: every leg is either a read
(status/dry-run observations, CI), an ordinary publication gesture the node needs anyway
(commit, submit, ready), or the one real base sync on #2130's own train (its intended
operation). Nothing to tear down.

## Reconciliation addendum (Objective #2130, Node 5.1, 2026-09-04)

This record's promised **commit 3 never landed**: `plan-2131`'s branch carries exactly two
commits — `f0b5633e` + `5de49442` (verified 2026-09-04 against PR #2132's commit list) — and
the `(Commit-3 addendum lands here.)` placeholders above were still unfilled when node 5.1
reconciled this record. This is the **post-submit evidence sequencing failure mode**: legs
whose recording depended on a future commit were stranded when that commit never came. Node
5.1's own closing protocol (`docs/design/archive/ts-seam-deepening-closeout.md` §3) is
designed against exactly this — no leg's completion may depend on a future commit; every
forward reference must be self-describing. Per-leg disposition, each claim re-verified from
durable artifacts at edit time (never renumbering or rewriting the record above):

- **Leg B (`/submit`): resolved-completed.** PR #2132 exists; plan #2131's `plan-header`
  carries `published_head_sha: 5de4944285464142acd7b33a8bd913f493214f91`; and the §8.43
  ready stamp for plan 2131 on issue #2130 names the same SHA
  (`perk:stack-ready-stamp:2130:2131:1.1:5de49442…`). The migrated submit binding
  observably published this record's plan.
- **Leg C (the warm `/ready`): resolved-completed.** The `perk:stack-ready-stamp` journal
  comment for objective 2130 / plan 2131 / node 1.1 @ `5de49442…` exists on issue #2130 —
  the record's own named verification pointer, now confirmed.
- **Leg A, the commit-2-head run: missing/unrecorded.** The promised observed-live
  recording was the commit-3 addendum that never landed, and no durable artifact proves
  that specific run. Classified honestly as **unrecorded**. The DIFFERENT final-head
  instance stays protocol-recorded per this record's own Part A step 3 — the two are not
  conflated. The repo-discipline consolation (a green run-all precedes every submit) is
  context, not evidence.
- **Leg E (the stack family; the folded Node 7.4 closeout): unexecuted-as-specified /
  missing.** Issue #2130's journal carries 13 `perk:stack-operation-event` records, every
  one `operation_kind: publish` — zero `sync`/`recover`/`land` events exist (re-verified
  2026-09-04; the journal also carries 7 `perk:stack-ready-stamp` comments, one per accepted
  layer through plan 2147) — and no session evidence of the prescribed
  `/objective-stack` + dry-run sequence was ever recorded. The leg (and the Node 7.4
  closeout it folded) is classified **UNOBSERVED — NOT PASSED**, a named residual of this
  record. Node 5.1 does NOT re-run it (out of scope); #2130's own land-time operations will
  exercise the sync/recover/land bindings as future events, which is not evidence for this
  protocol.
