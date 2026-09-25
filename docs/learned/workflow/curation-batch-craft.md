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

## Distillation

- Delete a duplicated section only after its citers are rewritten; ownership, not repetition, is
  the criterion; a byte-forced deletion names each row's surviving anchor — "The single-home
  invariant and the deletion criterion".
- Keep move commits verbatim and reconcile facts separately; prove a relocation with the
  three-check gate — "Verbatim moves stay separate from fact reconciliation".
- Repoint every citer, grepping topic words as well as paths — "Inbound-reference sweeps".
- Hub-plus-children splits keep heading slugs — "Rehoming moves preserve anchors".
- Chronicles become a dated record + trimmed craft; byte targets are working targets —
  "Distillation and chronicle condensation".
- A single-doc byte-ceiling diet carries its replacement text verbatim in the plan, measured with
  `wc -c` and backed by a ranked drop-list — "Diet craft — verbatim-in-plan replacements under a
  byte ceiling".
- Partitioned nodes pin cross-node dependencies and treat Assumptions handoffs as conditional
  leads — "Concurrent curation — partitioned objectives".
- A docs-only diff glob-skips every CI check; the docs gates are the proof — "The docs-only gate".

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
- **A byte-forced deletion ledger names each row's surviving anchor (#2523).** When a byte
  criterion forces deleting "no other `docs/learned/` home" content, the ledger names each row's
  surviving anchor (a source docstring, intent comment or test name — most already live where the
  comment-hygiene rule prefers invariants) or marks it un-homed; verify anchors at edit time.
  Un-homed generic heuristics re-enter via a source comment at the enforcing guard, not a learned
  doc.

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
- **The three-check verbatim-relocation gate (#2520).** An anchor-locating script (headings +
  bold lead-ins, never line numbers) extracts the named extents from `git show HEAD:<spine>`; then
  (a) their in-order concatenation diffs empty against the new file's body after the H1, (b)
  `git diff --numstat` on the spine reports 0 added lines, and (c) every moved extent's first line
  greps zero in the stripped spine. Shared frontmatter lines are declared outside the checks.
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
- **An inbound "X lives in `Y.md`" gloss is a semantic anchor `docs-check` cannot see** (#2518,
  #2514, #2517) — the scanner checks target-file existence only, strips fragments and skips
  slashless tokens. When a diet DELETES or pointerizes a section, grep citers for the *topic words*
  ("engine", "contract", "detail lives in"), not just the path, and repoint each hit in the same PR
  (a one-line repoint in a `keep` doc is not a re-home) or assign an owner; a path-only cite
  restales by *meaning*. A pre-plan one-liner "N citers, M §-anchored, K path-only" decides heading
  freedom; inbound censuses need `rg --hidden` to see `.pi/APPEND_SYSTEM.md`; a loose-but-true
  citation beats a cross-node dependency (retain a one-bullet generalized rule in place).

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
  substitutes for absent in-text dates when the archaeology is bounded (#2167) — across the
  src-layout conversion it needs the pre-migration pathspec (`perk/cli/…`, not `src/perk/cli/…`),
  no pathspec, or `--follow` (#2517; `toolchain/uv-workspace-src-layout.md`).

## Diet craft — verbatim-in-plan replacements under a byte ceiling

Full replacement text authored verbatim in the plan is the right shape for a single-doc,
single-owner, hard-byte-target `revise` diet (four byte-identical landings in one diet objective;
#2511, #2517, #2518, #2523, #2520, #2508); the per-section disposition table is for
multi-doc/relocation batches. Supports:

- **Measure, never eyeball.** Measure the fenced block from the plan-draft artifact (`awk` between
  the fences + `wc -c`), and measure the FINAL literal — a stated figure taken on an earlier
  iteration misled; a read-only session measuring pasted text undercounts the file form by the
  trailing newline. Count a Distillation literal with `wc -l`. `awk '{print length}'` counts bytes
  in a byte-oriented locale — right for `wc -c` gates, wrong for the ~100-column wrap check.
- **Pre-declare a tightening order / ranked drop-list** (cross-references → dated residuals →
  migration gotchas → intro wording; never a rule or pointer) so an over-budget copy has a
  deterministic remedy — wording-tightening saturates after two passes; only clause deletion moves
  bytes.
- **Budget a structural pass.** A faithful first render of "retained content" lands ~1.6× the
  target (cross-reference glosses → three-word labels, parentheticals, multibyte glyphs at 3 B
  each); soft section budgets sum to ≤ ~85 % of the ceiling (91 % landed at 99.98 %).
- **Headroom per fact.** A truth-revise over N changed facts needs ~+100–150 B headroom per fact or
  no ceiling (#2509); a ≤ 50 B margin is fragile against any additive fact fix.
- **Frontmatter-unchanged is a legitimate diet outcome** (`docs-sync` no-op). Verify
  `## Distillation` bullets with `perk learn docs-check` (the source-owned shape check), not a hand
  grep of wrapped headings.
- **The byte ceiling certifies the LANDING, not the steady state** — `pi/subagents.md` crossed its
  ceiling within two engine bumps; a rules-first doc states its no-history convention in its
  intro.

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
- **A cross-node handoff recorded in `## Assumptions` is a lead with a decay clock (#2518)** —
  write it as a CONDITIONAL ("if the § objective doctor section survives 3.3's diet, repoint …"),
  pin the tree it was read at, and re-verify at HEAD after the sibling lands before minting a node
  (a phantom node was born from a lead true only against the sibling's parent commit).

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
