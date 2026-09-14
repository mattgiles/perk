---
title: Curation-batch and relocation craft — single-home moves, verbatim-vs-reconcile commits, inbound-reference sweeps
read_when: You are moving, splitting, rehoming or consolidating docs — a docs/learned curation batch, a git-mv relocation sweep, a distillation by delegation, or repointing inbound references.
cluster: knowledge-stewardship
---

# Curation-batch and relocation craft

## docs/learned curation-batch craft

Rules from running verbatim merge/deletion batches over the `docs/learned/` corpus:

- **Verbatim merges faithfully transfer staleness.** Keep merge commits strictly verbatim (the
  diff-auditable content-preservation property is worth it), land accuracy reconciliation of the
  transferred content as its **own separate commit**, and budget an explicit "re-read transferred
  content against current reality" step in the plan — don't rely on review to catch what the
  merge faithfully carried over.
- **Measurement-derived finalized tables invalidate on any late edit.** Generate them
  mechanically (never hand-transcribe), sequence finalization after all content edits, expect one
  re-derivation after review, and stamp the measured HEAD SHA into the artifact so staleness is
  self-describing.
- **Sequential consumers of a frozen snapshot each need their own advancing baseline** — diff
  from the *prior batch's merge commit* (exempting scheduled deletions), not the shared origin
  SHA, or later batches re-report earlier batches' deliberate changes as drift.
- **A deletion/merge batch needs executor-facing per-batch repoint file lists** — including
  backticked path mentions the broken-link scan doesn't detect. Inbound-reference counts are a
  census, not an execution artifact.
- **`docs-check` green ≠ semantically current** — it validates pointer/navigation hygiene, not
  claims; auditing currency means checking claims against live source/config. And **obsolescence
  rationale needs source verification, not config absence** — generic-substrate knowledge isn't
  obsolete just because the current project doesn't exercise it.
- **Distillation headers are derived content and can contradict their own body.** A planning
  outline is only a paraphrase; the current body is authoritative. Verify every summary bullet
  against that body when creating or updating a header. Two of 36 headers were wrong at birth —
  one promoted a retired shape as current and one omitted a CI-enforced exception — while the
  distillation gate remained green because gate #4 checks placement and shape, not header-to-body
  truth. Header freshness is editorial discipline repeated on every doc edit.
- **Mechanical scale increases the need for adversarial review.** A 46-file pass framed as pure
  transcription produced actionable findings from all four review angles: outline drift, a
  newline-semantics seam, and header/body contradictions. Budget multi-angle review for large
  mechanical batches just as deliberately as for design changes.
- **The docs-sync blast-radius table.** A `read_when` edit regenerates one index row only; a
  frontmatter `title`/H1 edit changes NO generated surface; only cluster-membership/slug changes
  move the ambient APPEND_SYSTEM block (#2025, #2007, #2008, #2022).
- **The 12,288-byte distillation threshold** (`DISTILLATION_THRESHOLD_BYTES`,
  `src/perk/learn/docs_sync.py`): estimate a doc's post-edit size and budget the born-bounded
  Distillation opener in the plan when the edit will cross it (#2022).
- **A dream overlap signal can legitimately resolve as cross-link-don't-merge** when the overlap
  is generic/specific layering — one Cross-references row each way characterizing the division
  of labor (#2019). Residual/coverage claims cite the authoritative record without restating
  its detail (#2019).
- **Chronicle → dated-record condensation.** Split a chronicle into a compact dated validation
  record (real merge dates + issue/PR anchors) plus trimmed process craft; the relocation map is
  the load-bearing artifact (promote misfiled mechanics out of "history"); a
  heading-preservation gate plus internal repoints — including stale direction words
  ("below"→"above") — make it safe (#2010).
- **Delegation shape.** One-line pointers naming the counterpart's section anchor, only for
  verified-present content; delegate incident specifics, keep the local discipline; after
  delegating, every citing doc must land at most one hop from the moved content (#2022).
- **Yield calibration (#2156, #2166):** bound an expected byte reduction by summing the
  COMPRESS/DELETE-marked sections' bytes — or publish no percentage (twice-confirmed).
- **Byte count is a poor success proxy** — lead with restaling-surface removal; a "tighten" node
  can legitimately grow the doc (#2164).
- **The restatement-vs-kernel triage** for docs shadowing a normative contract: the delete unit
  is the clause, never the section — a section usually interleaves restatement (delete) with
  kernel (keep) (#2166).
- **Ownership, not repetition, is the deletion criterion** — reciprocal cross-reference rows are
  the ownership registry (#2164).
- **Pointer purity:** a delegation pointer carrying location/state detail restales; one with
  zero detail cannot (#2164).
- **Heading-anchored cross-refs are an inter-layer heading-stability contract** in stacked
  curation trains — a heading rename in one layer breaks a sibling layer's anchors (#2164).
- **Inbound-reference safety** = byte-stable retained headings + a deleted-phrase corpus grep
  (#2166).
- **Re-census a doc's numeric residuals before scoping work off them** — recorded residual
  counts drift (#2175).
- **Git-history dating (`git log -S`) substitutes for absent in-text dates** when the
  archaeology is bounded (#2167).
- **The single-home invariant.** Delete a duplicated section ONLY after grep-proving its only
  inbound citers are rewritten in the SAME plan. Content with NO other corpus home is RELOCATED,
  not deleted — a "pointerize to verified homes" clause does not license deleting it (make a
  home, and surface it as an explicit deviation from a bare prune framing). Bidirectional pointers
  survive as a one-line rule+pointer stub, never a delete.
- **Byte targets are working targets, not gates.** A "prune" node can land near original size
  when inbound-ref-protected sections must be kept; the acceptance is the section-by-section
  disposition table (KEEP/COMPRESS/DELETE/RELOCATE), the preserve list, the N-doc
  inbound-reference sweep, and dated historical-vs-current labels.
- **Pointerize, don't copy, commands.** Three verbatim copies of a raw test command all went
  stale when the justfile glob changed; name the stable entrypoint (`just test-js`) and point to
  the one glob authority.
- **The docs-gate reality.** A `docs/learned/**`-only diff (and `shared/contracts.md`) matches no
  `[[ci.checks]]` glob — the substantive gates are `perk learn docs-sync` + `docs-check` +
  grep-proofs, and every additive bullet edit is re-checked against the Distillation budget.

## Relocation sweeps (git mv reorganizations)

Craft for reorganizations that move docs/records wholesale (`git mv`) and must repoint the
corpus (#2163, #2179):

- **Plan-time link inventories carry per-link *change classes*** derived from the move geometry
  (unchanged / prefix-rewrite / needs-rehoming) — the executor applies classes instead of
  re-deriving each link's fate.
- **Line-break-wrapped path citations are the grep blind spot** — a path split across a wrapped
  line matches no single-line grep; sweep with the path's distinctive tail segment too.
- **Pre-list disambiguation traps for same-named docs** (two `index.md`s, sibling READMEs)
  before the sweep, or hits get repointed to the wrong namesake.
- **Every sweep hit needs an explicit disposition** — repoint / leave-with-reason /
  defer-to-node; leave-verbatim dispositions are as load-bearing as repoints (they record that
  the hit was seen and judged).
- **`:NN` line-suffixes in repointed citations stay verbatim** — the suffix is part of the cited
  evidence, not a live locator.
- **Archive-location-as-status-signal is a pure `git mv`** — no banners; the archive location IS
  the status.
- **Citation-repoint triage inside moved evidence records:** captured output stays byte-verbatim;
  prose/procedure citations repoint.
- **Distinguish asserted-content vs assertion-message vs fixture-data** — asserted content and
  fixture data are untouchable in a sweep; assertion messages (remediation prose) repoint like
  prose.

### Multi-node sweeps — partitioned objectives and concurrent curation

- **Cross-node byte-preservation pins.** When a sibling node distills/deletes content whose sole
  surviving home is a doc this node revises, pin the dependency in both node descriptions and
  declare the passages byte-identical + outside the sweep's blast radius, verified diff-shaped
  (#2013).
- **Rider sections follow the truth a node establishes, not the doc's cluster assignment** — a
  heading rename plus its inbound cross-refs cannot straddle two PRs (#2020).
- **Retain-in-place beats re-homing into a concurrently-planned sibling's file** — disjoint file
  ownership between concurrent curation nodes is worth preserving (#2022).
- **Same-class staleness is absorbed while in the file; a DIFFERENT defect class** (e.g.
  encoding corruption vs fact staleness) **gets a uniform-preserving deferral to its own node**
  (#2025).

The hub-plus-children reference split is settled mechanics: keep a stable hub, assign consecutive
nested sidebar order, and preserve heading slugs when moving text. The pattern has held for
in-session, CLI, and configuration families. Any heading restructure covered by the prose graph
also regenerates `docs/design/prose-prompt-map.md` via `uv run perk-dev prose-map sync`; name that
file in the plan's expected diff rather than discovering the tripwire late.
