---
title: Reconciling drifted docs against the converged codebase
read_when: You are reconciling a guidelines/design doc against grown reality, citing landed PRs from objective roadmaps, deciding whether to delete never-adopted forward guidance, sweeping prose after a change retires a convention/symbol spelling (grep the retired symbol, not a file list; grep the regex-escaped form too; full CI is the exit gate), qualifying an "X unchanged" plan note under a vocabulary rename, reconciling a validation-record doc (obsolete-mark in place, dated addenda, inlined evidence), or reconciling objective roadmap prose (the hard-count drift-magnet, the prior-node-paragraph gap, the scope-attribution drift, the Anchors-region drift magnet, the landing-narrative PR-number convention, reconciling a node landed with its original planned description).
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

## Validation-record reconciliation (the `remote-runner-e2e-dogfood.md` genre)

A validation-record doc (a dogfood/defect log) has its own reconciliation craft, distinct from
guidelines-doc patterns:

- **Obsolete-mark procedure steps in place** with an *(obsolete since PR #N — skip)* marker;
  **never renumber** — later steps cross-reference the numbers.
- **Fresh verification evidence lands as a dated addendum** with the key excerpts **inlined** —
  GHA logs/artifacts expire (~90 days) and raw logs aren't committed, so a pointer alone rots.
- **Defect-log dispositions are annotated, not rewritten** — add a "verified live <date>" pointer
  to the disposition; the original record stays as written.

## Keep-and-annotate beats delete for never-adopted forward guidance

Guidance describing a pattern that was never built does not get deleted: prepend an explicit
`> **Status: not yet adopted**` note naming the deferral condition ("until a real dashboard",
"if X is ever shared across more transports"). This preserves design intent without authoring
fiction — the same convention as the `> **Status (Node N.N)**` blocks used for sections whose
reality grew past the text.

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
  methods" that a later node made nine (then ten).
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
  issues
- `docs/learned/workflow/shared-contracts.md` — the contract-prose sibling of this maintenance
  discipline
