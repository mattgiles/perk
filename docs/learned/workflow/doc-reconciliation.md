---
title: Reconciling drifted docs against the converged codebase
read_when: You are reconciling a guidelines/design/validation doc against reality, sweeping prose after a symbol retires, staging a dogfood record, sequencing work around /submit, or objective roadmap prose.
---

# Reconciling drifted docs against the converged codebase

A docs-only reconciliation (e.g. bringing `docs/planning/python-cli-guidelines.md` back in line
with the grouped CLI) has its own craft. These are the durable rules from doing one for real.

## Roadmap `pr` field ≠ merge PR — verify before citing

Objective roadmap nodes' `pr` field holds the **plan issue** number, not the merge PR. Before a
doc cites "landed via PR #N", resolve the real merge PR from the node-description prose and
confirm each with `gh pr view <n> --json state,mergedAt`. The trap is real: it bit 2 of 4 cited
sweeps in the first reconciliation that checked.

## The doc-accuracy gate: grep symbols AND execute the doc's examples

- **The cheap mechanical pass**: grep every referenced symbol/path against the tree, and render
  live `--help` for every cited CLI surface. Catches stale names.
- **The decisive pass**: *execute the doc's code examples for real* — a throwaway runner script
  (e.g. a `CliRunner` snippet) before committing is what proves an example isn't fiction. For
  guidelines docs, runnable examples are test cases, not prose.

## A retired-convention sweep needs a symbol grep, not a named-file census

When a change retires a convention/symbol spelling, grep the retired symbol/phrase across **ALL
prose surfaces** (`docs/learned/`, `docs/guiding-principles/`, `shared/contracts.md`, user docs)
rather than hand-enumerating the files to update. The `fail()`/`EXIT_FOR_TYPE` consolidation
updated the learned docs it knew about but missed 4 stale references in a third file
(`docs/guiding-principles/python-cli-guidelines.md`) that only multi-angle PR review caught —
cross-linked docs mirror each other's conventions, so a named-file census undercounts by
construction.

Two nuances from the `[subagents]` → `[models.subagents]` sweep:

- **Grep the regex-escaped form too, and end with full CI.** A literal-string sweep missed a test
  pin written as the escaped regex `\[subagents\]` (`extension/factories/objectivePlan.test.ts`) —
  which also survived the plain-grep verification and surfaced only in full `just ci`. **A sweep's
  exit gate is the full CI run, not a spot grep.** (The same sweep's plan-file enumeration also
  missed two SKILL.md files that the repo-wide grep caught — reinforcing the rule above.)
- **"X unchanged" plan notes don't survive a vocabulary change inside X.** A plan that renames
  vocabulary must read any "leave X unchanged" instruction as "unchanged *except* occurrences of
  the renamed vocabulary" — the `renderCiProse` runtime message in `extension/` literally named the
  retired `[[ci]]` spelling, and the plan's own retired-spelling grep gate required changing it
  despite the plan's "prose rendering unchanged" note. Planners should qualify such notes
  explicitly.

And two **vocabulary-layer blind spots a correctly-scoped symbol gate structurally misses** (both
from seam-retirement sweeps):

- **Natural-language enumerations of the retired SET.** A symbol gate scoped to retired
  identifiers cannot catch prose that lists the set in words — a "plan/todo/askuser/footer/web"
  provider catalog line (`shared/README.md`) sailed through the gate and every CI check.
  Mitigate by grepping the *adjacent* member names (e.g. `plan/todo` or `footer/web`, which have
  no legitimate-survivor problem), or run one supplemental bare-word grep and hand-triage the
  hits.
- **Concept-level vocabulary/glossary/index blocks.** Retirement sweeps anchored on identifiers
  miss postures/concepts that don't contain them — a skill's posture index still advertising a
  retired posture; a data file's vocabulary block still defining a retired bridge term. When
  retiring a seam/posture, additionally sweep glossary/vocabulary/index blocks for the retired
  *concepts*, not just the symbols the plan lists.

One inversion of the sweep: **an exact-survivor-set grep gate constrains NEW prose, not just
old.** When acceptance is "the retired-symbol hit list matches the survivor table exactly", any
new annotation quoting a retired literal breaks the set — **paraphrase retired grammar in new
annotations** (worked example: describing the retired checkpoints marker protocol without the
literal `[WIP:n]`/`[DONE:n]` tokens); retired literals may only appear in files already
classified as survivors. "Mirror sibling wording" plan instructions must yield to the gate.

## A comment repoint from a deleted file is a fresh factual claim

When a plan says "repoint comment X (referencing the deleted file) to analogous site Y", verify
the claimed referent **exists as described** before committing the claim — never treat the
repoint as a mechanical substitution. A repoint to "file X's coverage of helper Y" failed because
X never names Y (it exercises the helper end-to-end without naming it); the fix describes the
actual coverage shape.

## Validation-record reconciliation (the `remote-runner-e2e-dogfood.md` genre)

A validation-record doc (a dogfood/defect log) has its own reconciliation craft, distinct from
guidelines-doc patterns:

- **Obsolete-mark procedure steps in place** with an *(obsolete since PR #N — skip)* marker;
  **never renumber** — later steps cross-reference the numbers.
- **Fresh verification evidence lands as a dated addendum** with the key excerpts **inlined** —
  GHA logs/artifacts expire (~90 days) and raw logs aren't committed, so a pointer alone rots.
- **Defect-log dispositions are annotated, not rewritten** — add a "verified live <date>" pointer
  to the disposition; the original record stays as written.
- **The early-merge internal-inconsistency failure mode.** An early merge can land a record whose
  header attests one phase while a section still carries now-false forward-looking prose ("Not
  yet executed — runs after the first `/submit`"). Reconcile passes should diff the merged PR's
  scope against the record's *sections*, not just its header. And an early land on a
  partially-executed record should be preceded by a residuals-naming + teardown commit — the
  post-merge reconcile is one merge too late when the dangling state is dangerous by design.
- **Supersession: never extend a retired flow's record.** When a validated flow is
  retired/replaced, author a NEW record for the new flow and prepend a dated keep-and-annotate
  supersession note to the old record's Status line — cross-annotated both ways; the new record's
  header states prior vs current coverage and re-examines standing residuals. Worked example:
  `docs/design/pr-review-doors-dogfood.md` superseding `docs/design/review-dogfood.md`.

### The production side: staging the record (the `review-dogfood.md` genre)

The patterns above reconcile an *existing* validation record; these are the crafts for **producing**
one from a dogfood run:

- **Staged sacrificial scratch PRs with planted signal are a strong dogfood substrate.** An
  own-authored PR that plants *undisclosed* defects — a workflow-file exfil, a wrong-package defect,
  a body-injection line — gives the run a **measurable scorecard** (did the machinery catch 3/3?),
  and **closing it unmerged** (branch deleted) keeps the whole procedure **repeatable**. A dogfood
  record split into *Part A: the repeatable procedure* + *Part B: the captured evidence + defect
  log* is the shape that survives re-runs. Record instance: `docs/design/review-dogfood.md`.
- **A dogfood gate's tuning scope *emerges* — plan the loop, not the fixes.** You cannot enumerate
  the fixes up front; the plan can only promise "tune from what the runs surface." The real
  deliverable is the **defect log**, with each fix evidence-traced back to a logged row. Don't author
  speculative fix lists into the plan — they're fiction until a run produces the row.
- **A dogfood node can legitimately finish *incomplete* when the operator calls it.** When a run
  surfaces more than its node can absorb (the `/review` dogfood: machinery held 3/3, human
  experience failed R1–R7), **defer honestly to a scoped follow-up node** rather than grinding the
  node to "complete." An honest incomplete finish + a named follow-up (objective #1206 node 4.3) is
  the correct close, not a failure of the node.
- **Validate each protocol leg's session-shape precondition against the gate's own context.** A
  leg that needs the adopted code in a different stage than the gate context can produce (e.g. an
  implement-stage session running the branch-under-test's extension while the implement worktree
  is occupied) belongs post-land, or needs a sacrificial second plan stacked on the branch.
  Enumerate each leg's required session shape at planning time.
- **The evidence-gap honesty pattern.** Live-leg evidence the human forgot to capture is surfaced
  to the operator with the structural evidence in hand and recorded as a dated
  "operator-accepted, non-residual" inline note — a category distinct from named residuals
  (deliberate skips).

## Sequencing work around `/submit` — post-submit operator work lands incomplete

A plan whose deliverables depend on operator action *after* the first `/submit` (live dogfood
legs, evidence capture, record fills) cannot complete inside one implementation-session turn:
`/submit` ends the turn, and nothing stops the draft PR merging before the follow-up turns run.
This recurred **four consecutive times** in one dogfood arc — awareness in plan prose,
"mandatory"/"ALWAYS" labels included, does not enforce itself. Mitigations, in preference order:

1. **Front-load** every land-worthy artifact before the first `/submit`. The
   arm-independent-first-commit split is the proven shape — it makes an early merge harmless.
2. Scope the plan to pre-submit work only and give the live/operator leg its **own roadmap node**
   from the start.
3. Accept the reconcile loop as the *planned* outcome, not a failure (see
   `workflow/objective-lifecycle.md` for the remainder-node mechanic).

Two structural corollaries:

- **Sequence "ALWAYS" steps first, not last.** When a plan carries a mandatory
  cleanup/attestation step (teardown of sacrificial state) plus intervening operator-optional
  work, run the mandatory step FIRST — the enabling check is that it is independent of the
  optional legs. Cleanup-last failed twice before teardown-first made a dangle structurally
  impossible.
- **State "what merges when" — exit gates are checked at the merge gate, not the submit gate.** A
  dogfood node straddles its own PR: the implementation session delivers only the scaffold; live
  legs are follow-up turns, and a self-review leg *requires* the PR to exist. Either the PR stays
  draft until the record is filled and teardown attested, or the live-execution half is
  explicitly its own node. Multi-leg interactive plans should name split-eligibility — which legs
  may land without which.

## Keep-and-annotate beats delete for never-adopted forward guidance

Guidance describing a pattern that was never built does not get deleted: prepend an explicit
`> **Status: not yet adopted**` note naming the deferral condition ("until a real dashboard",
"if X is ever shared across more transports"). This preserves design intent without authoring
fiction — the same convention as the `> **Status (Node N.N)**` blocks used for sections whose
reality grew past the text.

## Deliberate nonzero stale-pointer advisories (`perk learn docs-check`)

After a keep-history reconciliation, `perk learn docs-check`'s stale-pointer advisory can
legitimately end **nonzero**. The cheap reduction lever: **drop deleted-module rows from
Cross-references sections** (navigation aids with no learning content) while **keeping deleted
paths inside narrative passages** (deleting those deletes the learning — cross-reference rows are
the cheap place to shed stale pointers; narrative isn't). Record the residual advisory count +
rationale in the PR so the next docs-check runner doesn't re-litigate. Standing instance: **1
deliberate stale pointer** — the retired checkpoints module (`checkpoints.ts`, under the deleted
extension checkpoints dir) cited in `workflow/provider-seam.md`, whose passages are explicitly
marked historical; fixing it would delete the learning. (Naming that instance here *paraphrases*
the full path — quoting it verbatim would add this doc to the advisory it documents.)

## Glossary growth must sweep the docs that *enumerate* the glossary

Adding terms to a glossary/vocabulary section leaves stale any prose that presents it as an
exhaustive enumerated list (instance: `CONTEXT.md` § Objective delivery vs
`docs/planning/stacked-prs/objective.md`) — grep for *enumerating* prose, not just citations, in
the same turn.

## "Pure relocation / byte-identical" docstring claims expire on the first deliberate change

When touching a module whose docstring asserts a relocation/byte-stability invariant, scoping
that claim is part of the change ("byte-identical for every pre-existing input; the one
deliberate addition since: …"; instance: `src/perk/objective/render.py`).

## Check the boundary criterion before rewording a principle

When a principle doc's covered surface grows 10x, first test whether its *classification
criterion* still sorts everything correctly. The "narrow `--json` list" principle in
`docs/planning/cli-vs-pi.md` survived the surface growing from four commands to every cold
worker/door plus a second machine consumer — because both consumers are still *machines that
launch perk*. When the criterion still classifies correctly, an additive status note suffices;
don't touch the principle itself.

## Objective-roadmap reconciliation craft

Three patterns from reconciling Objective #548's prose against its landed nodes:

- **Hard counts in prose are drift magnets.** A literal count ("the protocol grew to **N** methods",
  "**N** phases") goes stale the moment the thing it counts grows. **Re-derive every count each
  reconcile** rather than trusting the prior prose — Objective #548's prose carried a stale "eight
  methods" that a later node made nine (then ten). And **even a planning-time-verified count is
  stale-by-default at implementation time** — the plan→implement window is enough for drift (a
  contracts.md section range pinned at plan time was off by one section by implementation). Plans
  should ship the **derivation command** (e.g. a `rg`-pipe re-derive), not only the derived value;
  enumerate rather than count where possible.
- **Check the *prior* node's landed-narrative paragraph, not only the current one.** When a per-node
  "Node X landed (PR #…)" narrative convention exists, a prior reconcile that updated only a node
  *description* (not the prose narrative) leaves a silent gap — #548's narrative had **skipped Node
  4.2 entirely**. Verify the previous node's paragraph is present too; narrative gaps accumulate
  across turns.
- **Scope-attribution drift.** When a node's residual is much narrower than its original framing
  because *earlier* nodes absorbed the work (Node 4.1's clauses 1–4 actually landed at Node 3.4, PR
  #593), `/objective-reconcile` is the place to fix it: rewrite the node `description` (the Mechanical
  table re-renders from it) **AND** extend the per-node landed-narrative — both tied to the concrete
  PR diff scope (here: the diff touched only the prompt helpers, never the store-routing), not the
  original framing.
- **The landing-log recipe (the safe single-entry append).** The Reconcilable prose is a per-node
  **landing log**: reconciling a just-landed node = **add one "Node X.Y landed (PR #n)" entry after
  the prior one** and let it resolve earlier entries' forward-references *collectively* — do **not**
  rewrite older entries (keep-and-annotate, don't rewrite history). Because the reconcile call
  **overwrites the whole region**, the safe mechanical recipe is: extract the exact current region
  between the bare reconcilable markers, insert one entry programmatically, **`difflib` to prove
  only-additions** (1 line added / 0 removed), then pass the full region as `prose`. Node
  scope/naming drift still goes through the **node-description path** (re-renders the mechanical table
  while preserving status/pr) — not the prose region.
- **The "Anchors (verified)" region is a drift magnet (#687).** When a node delivers the very thing
  an anchor said *didn't* exist (Node 1.2 landed the human-engagement read the Anchors region said
  "doesn't exist"), that anchor is **guaranteed-stale** — check the Anchors region **every reconcile**,
  keep-and-annotate with italic landed-notes, don't delete.
- **Landing-narrative PR-number convention (#696/#702/#705).** In objectives whose body is
  header+roadmap only (**no Reconcilable prose region** — the GitHub-objective shape), the durable
  `LANDED (PR #n)` narrative lives in the **node description** (via `objective_node` description), and
  it cites the **plan-issue number** for sibling consistency while the roadmap `pr` field *also* holds
  the plan issue — both legitimately differ from the actual merge PR (reinforces the `pr`-field-≠-merge-PR
  rule).
- **Reconcile a node landed with its ORIGINAL planned description (#711).** A node auto-marked `done`
  may carry **no** landing narrative (unlike siblings) — reconcile must append the `LANDED (PR #n)`
  narrative AND rewrite the phase-progress "X remains" sentence (the phase-complete claim is a drift
  magnet — re-check the prior node's narrative + the phase-complete claim **every pass**).

## Cross-references

- `docs/planning/python-cli-guidelines.md`, `docs/planning/cli-vs-pi.md` — the reconciled docs and
  their status-note conventions
- `docs/learned/workflow/objective-lifecycle.md` — the roadmap whose `pr` field carries plan
  issues, and the remainder-node reconcile playbook for PRs that merged with work incomplete
- `docs/learned/workflow/shared-contracts.md` — the contract-prose sibling of this maintenance
  discipline
