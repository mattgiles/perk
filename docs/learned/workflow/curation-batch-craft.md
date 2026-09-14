---
title: Curation-batch and relocation craft — single-home moves, verbatim-vs-reconcile commits, inbound-reference sweeps
read_when: You are moving, splitting, rehoming or consolidating docs — a docs/learned curation batch, a git-mv relocation sweep, a distillation by delegation, or repointing inbound references.
cluster: knowledge-stewardship
---

# Curation-batch and relocation craft

Rules for moving, splitting, rehoming, consolidating and distilling `docs/learned/` docs. The
truth-sweep craft is `docs/learned/workflow/doc-reconciliation.md`; the generated routing tier,
`docs/learned/workflow/learn-docs-scan.md`; record production,
`docs/learned/workflow/binding-design-records.md`.

## The single-home invariant and the deletion criterion

- **Single home.** Delete a duplicated section ONLY after grep-proving its citers are rewritten
  in the SAME plan; content with no other home is RELOCATED, never deleted (a "pointerize to
  verified homes" clause does not license deleting it); a bidirectional pointer pair survives as
  a one-line rule+pointer stub.
- **Ownership, not repetition, is the deletion criterion** — reciprocal Cross-references rows
  are the ownership registry (#2164).
- **The restatement-vs-kernel triage** for docs shadowing a normative contract: the delete unit
  is the clause, never the section (#2166).
- **Delegation shape**: one-line pointers to the counterpart's section anchor, only for
  verified-present content; delegate incident specifics, keep the local discipline; every citer
  lands at most one hop from the moved content (#2022). **Pointer purity**: a pointer carrying
  location/state detail restales; one with zero detail cannot (#2164).
- **Pointerize, don't copy, commands** — verbatim copies of a test command all stale together
  when the justfile glob changes; name the stable entrypoint (`just test-js`).
- **A dream overlap signal can resolve as cross-link-don't-merge** for generic/specific
  layering — one Cross-references row each way; cite the authoritative record, don't restate it
  (#2019).

## Verbatim moves stay separate from fact reconciliation

- **Verbatim merges faithfully transfer staleness.** Keep the move commit strictly verbatim
  (diff-auditable preservation), reconcile the moved content's accuracy in its own commit, and
  budget an explicit re-read of it against current reality.
- **Measurement-derived finalized tables invalidate on any late edit** — generate mechanically,
  finalize after all edits, expect one re-derivation after review, stamp the measured HEAD SHA.
- **Sequential consumers of a frozen snapshot each need their own advancing baseline** — diff
  from the prior batch's merge commit, not the shared origin SHA.
- **Mechanical scale increases the need for adversarial review** — a corpus-wide "pure
  transcription" pass drew actionable findings from every review angle.
- **`docs-check` green ≠ semantically current** — it validates pointer hygiene, not claims;
  obsolescence rationale needs source verification, not config absence.
- **Distillation headers are derived content and can contradict their own body** — verify every
  summary bullet against the body on every edit; the initial header pass shipped two header/body
  contradictions while the distillation gate (placement and shape, not truth) stayed green.
- **Crossing `DISTILLATION_THRESHOLD_BYTES`** (`perk/learn/docs_sync.py`) means authoring the
  born-bounded Distillation opener in the same edit (#2022). Which generated surfaces an edit
  moves: `docs/learned/workflow/learn-docs-scan.md` § "How docs-sync and docs-check derive the
  routing tier".

## Inbound-reference sweeps

- **A deletion/merge batch needs executor-facing per-batch repoint file lists** — including the
  name-mentions and un-backticked paths the scanner does not check (coverage:
  `docs/learned/workflow/doc-reconciliation.md` § "The doc-accuracy gate"); inbound counts are a
  census, not an execution artifact.
- **Inbound-reference safety** = byte-stable retained headings + a deleted-phrase corpus grep
  (#2166); **heading-anchored cross-refs are an inter-layer stability contract** in stacked
  curation trains (#2164).
- **`git mv` relocation sweeps** (#2163, #2179): per-link *change classes* in the plan's link
  inventory (unchanged / prefix-rewrite / needs-rehoming); line-wrapped citations match no
  single-line grep — sweep by the distinctive tail segment; pre-list same-named-doc traps (two
  `index.md`s); every hit gets an explicit disposition, leave-verbatim included; `:NN`
  line-suffixes stay verbatim (cited evidence, not a locator); archive-location-as-status is a
  pure `git mv`, no banners; captured output stays byte-verbatim while prose citations repoint;
  asserted content and fixture data are untouchable, assertion messages repoint like prose.

## Rehoming moves preserve anchors

The hub-plus-children reference split is settled mechanics: a stable hub, consecutive nested
sidebar order, heading slugs preserved when text moves. A heading restructure covered by the
prose graph also regenerates `docs/design/prose-prompt-map.md` via `uv run perk-dev prose-map sync`
— name that file in the plan's expected diff rather than discovering the tripwire late.

## Distillation and chronicle condensation

- **Chronicle → dated record + trimmed craft** (#2010): the relocation map is the load-bearing
  artifact (promote misfiled mechanics out of "history"); a heading-preservation gate plus
  internal repoints (stale direction words included) make it safe.
- **Yield calibration**: bound an expected reduction by summing the COMPRESS/DELETE-marked
  sections' bytes, or publish no percentage (#2156, #2166). **Byte count is a poor success
  proxy** — lead with restaling-surface removal; a "tighten" node may grow a doc (#2164).
- **Byte targets are working targets, not gates** — the acceptance is the per-section
  disposition table, the preserve list, the N-doc inbound sweep, and dated
  historical-vs-current labels.
- **Re-census numeric residuals before scoping work off them** (#2175); **`git log -S` dating**
  substitutes for absent in-text dates when the archaeology is bounded (#2167).

## Concurrent curation — partitioned objectives

- **Cross-node byte-preservation pins**: when a sibling node deletes content whose sole surviving
  home is a doc this node revises, pin the dependency in both node descriptions and declare the
  passages byte-identical (#2013).
- **Rider sections follow the truth a node establishes**, not the doc's cluster — a heading
  rename plus its inbound cross-refs cannot straddle two PRs (#2020).
- **Retain-in-place beats re-homing into a concurrently-planned sibling's file** — disjoint file
  ownership is worth preserving (#2022).
- **A DIFFERENT defect class** (encoding corruption vs fact staleness) gets a uniform-preserving
  deferral to its own node; same-class staleness is absorbed in the file (#2025).

## The docs-only gate

A `docs/learned/**`-only diff (and `shared/contracts.md`) matches no `[[ci.checks]]` glob, so a
run-all `run_ci` glob-skips every check for it. The gates are `perk learn docs-sync` +
`docs-check` + grep-proofs + the live-corpus pytest `tests/test_learned_docs_cues.py`, which runs
only when selected explicitly (`run_ci` with the check name `test-py-fast`, or `just test-py-fast`).
Every additive edit re-checks the Distillation budget.

## Cross-references

- `docs/learned/workflow/doc-reconciliation.md` — the truth-sweep core
- `docs/learned/workflow/learn-docs-scan.md` § "How docs-sync and docs-check derive the routing
  tier"
- `docs/learned/workflow/binding-design-records.md` — the measurement-rule consumer
- `docs/learned/workflow/test-pin-sweeps.md`
- `docs/design/archive/learned-curation-map.md` — the source curation record
- `skills/perk-learn-docs/SKILL.md` — the frontmatter + opener contract
