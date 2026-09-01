# Dogfood record: ts-decomposition Phase 5 gate (code review)

**Status:** validation record (the `*-dogfood.md` archive genre) for the objective's Phase-5
close: *run the repository's current automated review and one human review surface through the
new feature operations; do not proceed on memory-adapter tests alone* — after the Phase-5
feature slices (Node 5.1: the report-wave transport confinement + per-registration pending
state; Node 5.2: the code-review flows into `codeReview/` + `pi/v1/codeReview/`).

**Sequencing + placement note (recorded, not hidden):** this record was owed by node 5.2's
closing sequence and remained an open debt through Phase 6 (node 6.3's Step-0 ordering was
decoupled by operator decision at that node's implementation start). It closes here as node
7.1's HARD submission gate. Operator decision at 7.1 implementation close: the gate RAN from
the `plan-2114` train worktree (the 5.2-migrated review flows are the live extension there;
the legs target its real open PR **#2115**), and the record lands **on node 7.1's layer** —
trading the designed own-layer placement for no published-layer amend, no handoff re-stamp,
and no cascade. The gate's operative requirement (the record exists in 7.1's synchronized
ancestry) is satisfied as written.

Executed **2026-08-31** against the branch under test:

- **Gate worktree (the branch under test):**
  `/Users/mattgiles/dev/github/mattgiles/perk/.worktrees/plan-2114` (branch `plan-2114` — the
  train tip below 7.1, so the live arms exercise exactly the migrated Phase-5 code)
- **Tested commit SHA:** `84906a8c` (`plan-2114` at gate time — the 6.3 handoff-stamped head)
- **Phase-boundary stack check (before the gate):** `perk objective stack status 2083` showed
  the published prefix 11/16 intact (layers 1.1–6.3 all `[published] handoff ready`, base
  `main`, lineage `01M0STVYM6VX2M9C429EHE80M7`, next build-ready 7.1, **no findings**) — no
  base advance to absorb, so the gate ran against the as-is train.

## Arm 1 — the automated review (`/pr-review`) against PR #2115

Fresh session in the gate worktree; the multi-angle reviewer wave through the migrated
`pi/v1/codeReview/automated.ts` + `codeReview/` paths, over the PR's own layer diff
(`gh pr diff 2115`: base `plan-2112` → head `plan-2114`, +3,235/−2,471):

- **Coverage:** complete — plan-fidelity, code-organization, correctness, tests + the
  automatic Ponytail lane (5/5).
- **Verdict:** actionable — an advisory COMMENT review posted to PR #2115 with **4 inline
  comments**: plan-fidelity ×2 (the Step-0 dogfood-evidence prerequisite deferred with the
  archive file absent; the net-negative LOC criterion missed at +220 — both known, recorded
  operator decisions on that node), correctness ×1 (`analyzeDream`'s final digest SET
  conflates the unverified-append arm with rejection), tests ×1 (stale `dream-analyses.json`
  removal only spy-proven). Clean angles: code-organization, Ponytail. No FYI notes.
- The wave was **layer-scoped by construction** (`perk pr review-context --pr` gathers the
  PR's own merge-base diff; the combined train diff exists only on the explicit `--stack`
  arm) — verified in source during the gate.

## Arm 2 — the human review surface (`/pr-review-terminal`) against PR #2115

- **First attempt (the active arm, no argument): aborted — and recorded as a finding.** From
  the stacked layer's own worktree, the active arm resolved the since-base sha from the
  plan-ref's pinned `base`, which is `null` for stacked plans → fallback to `origin/HEAD`
  (`main`) → hunk launched over the **entire train's ~36k-LOC diff** instead of the layer.
  Hunk itself launched correctly (the migrated door mechanics worked); the scope was wrong.
  Not a migration regression (the 5.2 move is behavior-preserving; the fallback predates it)
  — filed as **issue #2117** with the cause, workaround, and fix sketch
  (`browser.ts` shares the same resolution).
- **Completed run (the foreign arm): `/pr-review-terminal 2115`** from a fresh session —
  `perk pr review checkout --pr 2115` produced a detached checkout with
  `base_sha = merge-base(origin/plan-2112, head)`; the hunk diff was **layer-scoped**
  (operator-verified against the ~5.7k-line layer diff). The adversarial wave completed
  clean — **4/4 lanes covered, no degrades**, findings streamed live into hunk throughout.
- **Curated post:** after human triage, one review posted to PR #2115 via
  `submit_pr_review` — event `comment` (own-PR: GitHub refuses formal events, the door's
  expected arm), **1 inline comment kept** (major, claimed-intent: the deferred Phase-6
  dogfood gate / missing evidence file) plus a summary body noting the correctness, tests,
  and Ponytail lanes came back clean.
- **Cleanup:** the detached review worktree (`review-2115`) was removed by the flow.

## Skipped arms

- `/pr-review-browser` (the plannotator human surface) was not exercised — the gate requires
  ONE human review surface; the terminal door is the one exercised here. The browser door
  shares the active-arm base-resolution gap recorded above (issue #2117 names it).

## Cleanup

- The two posted reviews (the Arm-1 advisory review, the Arm-2 curated comment) remain on PR
  #2115 as review artifacts for that layer's normal address flow.
- No worktrees or refs left behind; no branch heads moved (the record lands on node 7.1's
  layer as a docs-only commit — no re-stamp, no cascade).
