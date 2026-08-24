---
title: Reconciling drifted docs against the converged codebase
read_when: You are reconciling mirrored/design/validation docs, producing source-verified or dogfood evidence, auditing volatile facts, sequencing /submit work, or reconciling objective prose.
cluster: knowledge-stewardship
---

# Reconciling drifted docs against the converged codebase

A docs-only reconciliation (e.g. bringing `docs/design/first-principles/python-cli-guidelines.md` back in line
with the grouped CLI) has its own craft. These are the durable rules from doing one for real.

## Distillation

- A roadmap node's `pr` field links the PLAN; the merge PR can differ — verify before citing.
- Doc accuracy means grep the named symbols AND execute the doc's runnable examples — "The
  doc-accuracy gate".
- A retired-convention sweep greps the whole corpus, never a named-file census; full CI is the
  exit gate — "A retired-convention sweep needs a symbol grep".
- Plans carry per-fact source ledgers (claim → anchor); audit findings are leads, not proofs;
  every path re-resolves at edit time — "The truth-sweep recipe — per-fact source ledgers".
- Frozen counts/ordinals/censuses/version stamps de-freeze by delegating to a source-owned
  guard, derivation, or event stamp — never a refreshed number — "De-freeze taxonomy".
- The keep-vs-correct unit is the sentence: correct instructive text in place, historicize
  narration, "Resolved:" fixed residuals — "Correction shapes — the instruct-vs-narrate triage".
- For never-adopted forward guidance, keep-and-annotate beats delete — "Keep-and-annotate beats
  delete".
- A keep-history pass can leave the stale-pointer advisory NONZERO; the `broken-doc-ref` weighed
  floor is sized fresh via `perk learn docs-check` — "Deliberate nonzero stale-pointer advisories".
- Sweep-step craft: mirrors, expected no-ops, neighbor staleness — and multi-node sweeps pin
  cross-node byte-preservation + disjoint file ownership — "Sweep-step craft".
- Distillation headers are derived content; the docs-sync blast-radius table and the 12,288-byte
  threshold are budgeting facts — "docs/learned curation-batch craft".
- Mirror drift is omission-shaped; pin a claim ledger before a move; volatile catalogs live in
  source-verified references — "Mirror and fact-drift reconciliation".
- Validation records obsolete-mark in place with dated addenda; the dogfood-record genre is
  settled (pre-committed protocol, per-criterion classification) — "Validation-record
  reconciliation".
- Source verification is a labeled substitute; gates re-derive and bind to one commit; dogfood
  evidence is a pre-submit blocker; disposable remote proofs prove absence afterward —
  "Acceptance evidence craft" / "Disposable-repo proof hygiene".

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
prose surfaces** (`docs/learned/`, `docs/design/first-principles/`, `shared/contracts.md`, user docs)
rather than hand-enumerating the files to update. The `fail()`/`EXIT_FOR_TYPE` consolidation
updated the learned docs it knew about but missed 4 stale references in a third file
(`docs/design/first-principles/python-cli-guidelines.md`) that only multi-angle PR review caught —
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
- **A "no changes to plane X" non-goal covers behavior, not comment truth.** When a plan
  decision widens a cross-plane coordination point (the pinned `perk_version` key literal's
  story broadened from "at claim/mint" to "when run identity is established"), sweep the *other*
  plane's narration in the same PR — comments/docstrings pinning the old, narrower story are
  stale even though the non-goal forbade behavior changes there. A non-goal is not a prose
  freeze.

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

## The truth-sweep recipe — per-fact source ledgers

- **A plan-carried per-fact source ledger makes execution mechanical.** Every corrective claim
  in the plan maps to its file/symbol anchor, re-verified at planning time — the executor
  applies edits instead of re-litigating truth. Confirmed across four consecutive docs-truth
  nodes.
- **Upstream audit findings (learn-dream reports) are leads, not proofs.** Independently
  re-verify every corrective claim against current source before it enters the plan — a sweep
  that transcribes an audit report reintroduces the exact drift class it exists to fix.
- **Even a ledger-backed executor re-resolves every path it touches at edit time.** The
  plan→implement window is enough for drift; the ledger de-risks the plan, it doesn't waive the
  edit-time check.
- **Bounded negative greps are the verification gate for retired spellings.** In a partitioned
  objective the negative grep scopes to the node's owned docs ("no NEW findings"), with
  cross-node hits recorded as a count + attribution rather than fixed out of scope.

## De-freeze taxonomy — counts, ordinals, censuses, version stamps

How to un-freeze prose that carries a number, an enumeration, or a version marker:

- **Delegate a census to a source owner instead of refreshing the number.** A type-checked
  binding or a guard test is a census CI re-derives; prose never is (#2012).
- **Ordinals are counts in disguise.** "To add a third, …" becomes "to add a NEW …" (#2019).
- **Three de-freeze shapes, keyed by what the frozen text was doing:** an *invariant claim* →
  mint (or point at) an enforcement guard plus a derivation instruction; a *routing-aid
  enumeration* → derivation-first, with the snapshot explicitly subordinate to the grep; a
  *historic decision record* → keep verbatim plus ONE live-census-pointer paragraph. A
  reconciliation node may legitimately ship one guard when the "census" is an invariant no test
  owns (#2023).
- **Version markers:** lineage stamps ("source-read at X") are drift magnets — prefer one
  doc-level anchoring convention pinned to a code constant plus a doctor tripwire; version
  numbers survive only as event stamps ("since X, behavior changed") (#2011). A baseline
  re-stamp is an implicit re-assertion of every version-stamped fact — re-verify them all;
  facts not re-verified keep their honest old stamps (#2009).
- **Falsified universally-quantified absolutes** are fixed with a small dimensional matrix or a
  mechanism-scoped claim plus the named standing exception — never a hedge, never a new frozen
  census; advice phrased against a literal count dies with the count (#2012, #2010).

## Mirror and fact-drift reconciliation

Mirror drift usually appears as an omission, not a contradiction. Lockstep edits propagate a
shared sentence, while a newly discovered precision fact lands only on the canonical surface. A
claim-by-claim ledger comparison is the reliable detector. When restructuring mirrored docs, pin
the exact fact ledger in the plan before moving text; it makes the relocation loss-proof and is
the later audit checklist. The perk-expert mirror remains convention-guarded rather than fully
machine-derived, an accepted trade that makes this ledger discipline more important.

How-to pages rot fastest where they enumerate a foreign or volatile catalog. A task guide should
link the stable upstream authority rather than an installed path or copied set. Route catalogs,
defaults, and compatibility postures to reference pages whose facts are regenerated or verified
against source. Ground those claims while planning so implementation-time checks confirm a known
model rather than discover it under deadline. Every backend or config fact correction also greps
`skills/perk-expert/references/` for the matching sentence in the same turn.

A same-turn contract amendment is written from the shipped code, not copied from approved plan
prose. By reconciliation the plan is one revision stale; exact error tables, field names, and
authority ordering can have changed during implementation. The plan-fidelity review angle is the
backstop for that difference. Correcting a contract to match landed behavior is itself an
amendment, not tolerated drift.

Backend-neutral wording requires per-backend reachability evidence. Tolerant reads and strict
decoders can make a degraded state reachable on one backend only. Verify each carrier and qualify
the prose rather than generalizing from one implementation.

The hub-plus-children reference split is settled mechanics: keep a stable hub, assign consecutive
nested sidebar order, and preserve heading slugs when moving text. The pattern has held for
in-session, CLI, and configuration families. Any heading restructure covered by the prose graph
also regenerates `docs/design/prose-prompt-map.md` via `uv run perk-dev prose-map sync`; name that
file in the plan's expected diff rather than discovering the tripwire late.

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
  `docs/design/archive/pr-review-doors-dogfood.md` superseding `docs/design/archive/review-dogfood.md`.
- **The dogfood-record genre is settled across factories** (#2006, #2027): Part A pre-committed
  protocol, blocked-state disposition, probes-vs-attempts budget accounting, per-criterion
  observed-live/offline-pinned/unobserved-not-passed classification, product-artifact-first
  evidence, and era-correcting dated deviations in place of forced captures or defect calls.
  Verdicts classify from artifacts/event projections, never the human's summary label.

### The production side: staging the record (the `review-dogfood.md` genre)

The patterns above reconcile an *existing* validation record; these are the crafts for **producing**
one from a dogfood run:

- **Declare the execution arm; don't claim omitted coverage.** A gate substituting
  deterministic cold saves + headless implement drives for the planned warm authoring/review
  flow proves cold persistence + warm publication, *not* the warm authoring UX — the record
  must state that scope distinction explicitly (instance:
  `docs/design/archive/stacked-publication-dogfood.md`).
- **Staged sacrificial scratch PRs with planted signal are a strong dogfood substrate.** An
  own-authored PR that plants *undisclosed* defects — a workflow-file exfil, a wrong-package defect,
  a body-injection line — gives the run a **measurable scorecard** (did the machinery catch 3/3?),
  and **closing it unmerged** (branch deleted) keeps the whole procedure **repeatable**. A dogfood
  record split into *Part A: the repeatable procedure* + *Part B: the captured evidence + defect
  log* is the shape that survives re-runs. Record instance: `docs/design/archive/review-dogfood.md`.
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
- **Capture-if-fired is a reusable degrade posture.** Never force degrade arms with hooks or
  test-only flags: an arm that fires naturally during the run is recorded with verbatim tool
  results; an arm that never fires is recorded as offline-pinned — **naming the exact pin
  suites** — plus a named residual. Record instance: `docs/design/archive/streaming-doors-dogfood.md`
  (hold-and-accumulate, readiness degrade, and wave incompleteness never fired; the pin suites
  are named per arm).
- **Verify preconditions against the full committed config + effective child metadata — never
  truncated command output.** A truncated grep cut a committed `[models.subagents]` key off a
  config listing, so a wrong "no override" precondition was recorded and later corrected. Two
  sub-rules: (a) read the **whole** config table, then confirm what actually ran from the
  per-child `_meta.json` model field; (b) a plan precondition can be **unsatisfiable against the
  repo's own committed config** — record the deviation honestly; never make an unauthorized
  config flip to satisfy plan text.
- **Cross-verification pointers in a validation record are factual claims.** Existence-check
  every "cross-verifiable against X" (an `ls`/grep) before commit — a nonexistent reference file
  was briefly cited as a cross-verification anchor and caught only a commit later.
- **Independent teardown verification is the authoritative cleanup pass.** Design dogfood
  procedures so teardown re-verifies everything (ls-remote + worktree list + issue-search)
  rather than trusting per-leg cleanup: a session that ended at a browser respond skipped its
  in-session cleanup step, and only the teardown sweep caught the leftover checkout.

### The record-completeness bar

A dogfood record isn't complete until its reproducibility claims are mechanically usable and
acceptance-traceable:

- **Copy-paste-complete commands, one consistent provenance value, decisive source excerpts
  inlined, every unobserved arm pinned at function level with a named residual, and the final
  broad gate explicitly attested** — anything short of that bar forces the next runner to
  re-derive the run instead of replaying it.
- **Audit-grade verdicts must derive from evidence that survives in the committed record**, not
  from richer raw captures later deleted; and make shell-lifetime assumptions actor-specific —
  an EXIT trap can't span separate per-command tool shells, so cleanup guarantees phrased around
  one long-lived shell are fiction for tool-driven runs.
- **Docs-only diffs need semantic claim reconciliation** — a claim-by-claim source matrix plus an
  independent accuracy read — because help/link checks and glob-gated CI can all be green while
  cross-file behavioral claims are wrong.
- **Pinned protocols drift across eras** — restate recipes with explicit era notes (e.g. bare
  `perk plan` now opens idle; "after the seed turn" changed meaning); a report-only record
  tolerates *named* deviations, never silent ones.

## Acceptance evidence craft

### Source verification is a named substitute

Static source tracing may substitute for a live walkthrough only when the evidence maps each
step to its owning code anchor and pinned tests. Label the result exactly as source-verified with
live execution waived by the operator directive; never call it a live-run pass. Quote the
governing directive verbatim and list any claims the static evidence cannot establish as
unverifiable.

For a cold-context evaluation of docs information architecture, copy the built site into a unique
temporary directory outside the repo and record its directory listing as isolation proof. Use a
user-level read-only agent with no project context, run paired navigation tasks in each session,
and after any content fix rebuild the site and start a fresh isolated session. Reusing the warm
review context tests memory, not the docs.

### Gates re-derive and records bind to one commit

A gate verifies state at execution; it does not trust even a same-plan "verified" note. Bind the
evidence record to the implement-worktree SHA that was certified. After that gate, allow only
commits that update evidence records, or re-certify the changed implementation. For a CI leg that
can exist only after submit, use an explicit forward reference rather than inventing a result.

Manual acceptance and dogfood records are submission blockers. A commit message does not satisfy
"recorded on the PR"; put the evidence on the PR at submit time. If an address pass changes the
build under review, rerun the affected leg and record the addressed-build result. Browser dogfood
is executable evidence: drive the real launcher-served application through headless CDP rather
than deferring the check to an unspecified human.

Acceptance choreography spread across sessions degrades silently. If the evidence matters to a
merge decision, encode a machine-checkable condition at the enforcement point. Strong prose in a
prior session is not a gate.

### Disposable-repo proof hygiene

Remote proofs use a unique timestamped repository name and hard-preflight the required `gh`
scopes. Install an unconditional cleanup trap before the first remote mutation. Record secret
*names* only, sanitize evidence identifiers, and finish with post-hoc absence proofs for the
repository, branches, worktrees, and related issues. Cleanup intention is not cleanup evidence.

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

Three structural corollaries:

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
- **A plan step "record X in the PR description" cannot be satisfied in the submitting turn.**
  `/submit` terminates the turn and the PR body is auto-composed, so the content never makes it
  into that body from the same turn — defer it to a post-submit follow-up or route it into a
  committed artifact instead.

## Keep-and-annotate beats delete for never-adopted forward guidance

Guidance describing a pattern that was never built does not get deleted: prepend an explicit
`> **Status: not yet adopted**` note naming the deferral condition ("until a real dashboard",
"if X is ever shared across more transports"). This preserves design intent without authoring
fiction — the same convention as the `> **Status (Node N.N)**` blocks used for sections whose
reality grew past the text.

## Correction shapes — the instruct-vs-narrate triage and its arms

The unit of keep-vs-correct is the **sentence**: instructive sentences (paths, seam maps,
recipes) are corrected in place; history narration keeps its text and gains a dated
`> **Update**` supersession blockquote, a `Historical:` retitle, and past-tensing (#2007,
#2008). The arms and their edge cases:

- **A documented residual whose reality has since been fixed becomes a "Resolved:" note** — the
  third arm beside correct-in-place and keep-and-annotate (#2025).
- **Rationale succession.** Recast a falsified rationale as "the original motivation … / the
  rationale that survives …" (#2017). A correction can stay right for a NEW reason — record the
  history AND the new mechanism, and install one verbatim-consistent corrected reason
  everywhere the falsified phrasing appears (#2011).
- **"Mirrors how X does Y" docstrings** repoint to the one canonical record, never re-inline
  the sibling's current behavior (#2017). **"Nothing calls this yet" claims** are deleted
  outright — a caller inventory re-drifts identically (#2017). Historical narration must not
  contradict current invariants (#2017).
- **Over-generalized rules get a neutral rescope:** narrow the stated domain plus one factual
  contrast sentence — never invent rationale for the excluded case (#2020). **A durable rule
  outlives its expired exhibit:** time-scope the old exhibit, re-verify against a current one,
  restate the rule unchanged; retire claims that silently vanished (#2020).
- **When a mechanic splits into gate + execution,** document the named roles (the *whether* vs
  the *how*) rather than deleting the "single path" claim; enumerating the gate's consumers is
  part of the correction (#2020).
- **Deleting a stale self-contradictory instruction requires a loss-freeness check:** trace each
  durable fact inside the deleted text to a surviving owner first (#2009). When an audit claim
  is DISPROVEN, encode the outcome as an explicit byte-preserve pin so a well-meaning executor
  can't "modernize" correct guidance (#2009).
- **Correcting a falsified safety claim means re-locating where the safety actually lives** —
  the fact-fix may falsify a bundled rationale; sweep both (#2025).
- **Falsified-phrase censuses span src docstrings, test docstrings, and learned-doc headings:**
  grep the phrase repo-wide with per-hit truth checks, never blanket rewrites (#2017).
- **Intra-doc self-contradictions resolve toward code truth** by historicizing at bullet
  granularity; a heading rename is a lockstep set (the H2 + the Distillation quote + an inbound
  cross-ref grep) (#2013). When a documented code anchor becomes a re-export, repoint to the
  owner but keep one clause naming the re-export (#2013). A stale-pointer census classifies
  lookalikes with recorded exclusions (#2013). Heading-stability as an explicit edit-spec
  invariant is cheap and pays off in review (#2009).

## Deliberate nonzero stale-pointer advisories (`perk learn docs-check`)

After a keep-history reconciliation, `perk learn docs-check`'s stale-pointer advisory can
legitimately end **nonzero**. The cheap reduction lever: **drop deleted-module rows from
Cross-references sections** (navigation aids with no learning content) while **keeping deleted
paths inside narrative passages** (deleting those deletes the learning — cross-reference rows are
the cheap place to shed stale pointers; narrative isn't). Record the residual advisory count +
rationale in the PR so the next docs-check runner doesn't re-litigate. Resolved historical
example: for a while the corpus carried **1 deliberate stale pointer** — the retired checkpoints
module (`checkpoints.ts`, under the deleted extension checkpoints dir) cited in
`workflow/provider-seam.md`, whose passages are explicitly marked historical; "fixing" it would
have deleted the learning. A later consolidation pass (PR #1687) reworded the citing passage and
the standing count returned to 0 — the craft stands: paraphrase, don't quote, when naming such an
instance (a verbatim path would add the naming doc to the advisory it documents).

Post-#1973 the `broken-doc-ref` family sits at a **deliberate weighed-advisory floor** (deliberate
example paths, cross-tree shorthands, history citations) — an accepted tail future runs weigh
per-row, not a regression to churn (#2026). The floor's size is a measurement, never a recorded
fact: run `perk learn docs-check` and weigh the current `broken-doc-ref` rows — a count written
here froze once and no substitute number replaces it.

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
- **The `\uXXXX` escape-corruption class.** The docs/skills corpus is clean except
  `learn-evidence-pipeline.md`'s intentional `\ud800` content line (a data-format example a
  sweep must not "fix"); a recurrence guard was deliberately declined; re-derive corruption
  counts at implementation time — node prose counts lie (#2016).
- **Doc→doc repo-relative path pointers are a deterministic-detector blind spot** —
  `git ls-files` per named path is the only net; the reconciliation craft doc itself drifted
  this way (#2019).
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

## Glossary growth must sweep the docs that *enumerate* the glossary

Adding terms to a glossary/vocabulary section leaves stale any prose that presents it as an
exhaustive enumerated list (instance: `CONTEXT.md` § Objective delivery vs
`docs/planning/archive/stacked-prs/objective.md`) — grep for *enumerating* prose, not just citations, in
the same turn.

## Sweep-step craft: mirrors, no-ops, and neighbor staleness

Three sibling lessons about planned prose sweeps:

- **Docs-mirror lockstep binds to where the prose lives, not to file-name symmetry.** A named
  lockstep surface can be prose-free by design (a Key/Type/Default-only table), so the prose
  actually needing the update lives in a differently-named sibling. Planners should verify a
  mirror file's *shape* before naming it in a lockstep step — reviewers read the mismatch as a
  fidelity miss until the shape rationale is stated.
- **A planned sweep step can legitimately no-op — say so instead of manufacturing edits.**
  Phrasing sweep steps as conditional ("update only what became false") keeps a zero-change
  outcome plan-faithful rather than a fidelity gap.
- **Landing a planned section often stales a neighbor's "Status" paragraph — sweep them.** An
  adjacent section's activation/status prose is the likeliest casualty of the section you just
  made true.

And the rename/retirement sweep scope — what a retirement's grep must actually cover:

- **Retiring a model-facing name must grep for it as an *analogy referent*** in sibling flows'
  prose ("like X does"), not just registration/guidance sites; and **verbatim historical evidence
  gets a dated annotation, never a rewrite** — captured transcripts/quotes citing the old name
  stay as written.
- **A symbol extraction's blast radius includes prose in files the plan never listed** — grep old
  `module.helper` names in comments/docstrings and golden/test harnesses, not just call sites.
- **When a PR retires a documented limitation or lands a capability recorded as future work, grep
  `docs/learned/` for it in the same turn** — learned docs are part of the same-turn
  reconciliation surface, exactly like `shared/contracts.md`.
- **Hand-added PR-body content does not survive a later perk publish** (the review-address
  publish regenerates the body from the plan) — until PR-body regions are splice-protected,
  record acceptance after the *final* publish, or re-verify it afterwards.

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
- **Claim sweeps cover `docs/learned/` and `docs/design/first-principles/`** — stale learned docs
  actively fight sanctioned changes; amend them in the same PR (#2028). When behavior grows,
  sweep worked examples, declared-shape docstrings, and tutorials (which must stay runnable
  top-to-bottom), not just normative prose (#2029). Numbered step sequences are themselves
  instructions: scope the whole sequence to one mode with an up-front callout carrying the other
  mode's complete path (#2024).

## "Pure relocation / byte-identical" docstring claims expire on the first deliberate change

When touching a module whose docstring asserts a relocation/byte-stability invariant, scoping
that claim is part of the change ("byte-identical for every pre-existing input; the one
deliberate addition since: …"; instance: `src/perk/objective/render.py`).

## Check the boundary criterion before rewording a principle

When a principle doc's covered surface grows 10x, first test whether its *classification
criterion* still sorts everything correctly. The "narrow `--json` list" principle in
`docs/design/first-principles/cli-vs-pi.md` survived the surface growing from four commands to every cold
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
  enumerate rather than count where possible. Two corollaries: (a) **universally-quantified prose
  claims over a growing key list are drift magnets too** — a JSDoc's "each configured value is
  injected…" silently absorbed a new deliberately-inert `[models.subagents]` key; when a new
  entry breaks the quantifier, qualify the claim in the same change. (b) Plan hard-count sweeps
  as **enumerated anchor lists**, not "fix the docstring" — a stale "three agent defs" count had
  replicated to three anchors (module docstring + two test files), and pre-locating all anchors
  made the sweep trivial. The repair shapes for frozen counts/censuses/version stamps are
  cataloged in "De-freeze taxonomy — counts, ordinals, censuses, version stamps" above.
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

- `docs/design/first-principles/python-cli-guidelines.md`, `docs/design/first-principles/cli-vs-pi.md` — the reconciled docs and
  their status-note conventions
- `docs/learned/workflow/objective-lifecycle.md` — the roadmap whose `pr` field carries plan
  issues, and the remainder-node reconcile playbook for PRs that merged with work incomplete
- `docs/learned/workflow/shared-contracts.md` — the contract-prose sibling of this maintenance
  discipline
