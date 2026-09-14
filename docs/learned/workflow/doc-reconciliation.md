---
title: Reconciling drifted docs against the converged codebase
read_when: You are reconciling drifted mirrored/design/validation docs against the codebase, auditing volatile facts (counts, version stamps, retired symbols), or sequencing post-/submit evidence.
cluster: knowledge-stewardship
---

# Reconciling drifted docs against the converged codebase

A docs-only reconciliation brings drifted prose — mirrors, design principles, validation records,
objective narratives — back to what the code does. This doc is the truth-sweep craft: find the
falsified claim, pick its correction shape, keep the fix from re-drifting. Moving, splitting or
rehoming docs — including the batch measurement rule (finalized tables are generated mechanically
after all edits and stamped with the measured HEAD SHA) — is
`docs/learned/workflow/curation-batch-craft.md`'s; producing a validation or dogfood record is
`docs/learned/workflow/binding-design-records.md`'s.

## Distillation

- Grep every named symbol (in sentences you WRITE too) and execute the examples; repointing
  never re-verifies a paragraph — "The doc-accuracy gate".
- Sweep retired conventions by whole-corpus grep, escaped form included; full CI is the exit
  gate — "A retired-convention sweep needs a symbol grep".
- Per-fact source ledgers; audit findings are leads; gates verify at execution — "The
  truth-sweep recipe".
- Frozen counts/censuses/version stamps delegate to a source-owned guard, derivation or event
  stamp, never a refreshed number — "De-freeze taxonomy".
- Mirror drift is an omission: pin the fact ledger first; truthfulness beats scope — "Mirror and
  fact-drift reconciliation".
- The keep-vs-correct unit is the sentence: instruct → correct, narrate → dated annotation —
  "Correction shapes".
- Keep-and-annotate serves a live audience; a changelog's archive is git history —
  "Keep-and-annotate beats delete".
- Stale-pointer advisories may end deliberately nonzero: pin the scanner's token shapes,
  rephrase-first — "Deliberate nonzero stale-pointer advisories".
- Sweep steps may no-op; neighbor Status prose stales — "Sweep-step craft".
- Post-submit choreography fails on every observed instance: front-load; artifact-anchored
  forward references only; evidence on a pre-`/submit` carrier — "Validation-record
  reconciliation".
- Ship the derivation command; re-check the prior node's narrative; append one landing-log entry
  — "Objective-roadmap reconciliation craft".

Dated instances live inline as `(#NNNN)` issue anchors.

## The doc-accuracy gate: grep symbols AND execute the doc's examples

- **The cheap mechanical pass**: grep every referenced symbol/path against the tree; render live
  `--help` for every cited CLI surface.
- **The decisive pass**: *execute the doc's code examples for real* (a throwaway `CliRunner`
  snippet) before committing — runnable examples are test cases, not prose.
- **Apply the grep to the sentences you *write***, not only those you correct — new prose mints
  new pointers. A record's "cross-verifiable against X" pointer is a factual claim:
  existence-check it before commit.
- **Repointing a citation is not re-verifying its paragraph** — read the claim and fix falsified
  prose in the same touch, or the fresh pointer lends a false sentence authority.
- **Docs-only diffs need claim-by-claim semantic reconciliation** (a source matrix plus an
  independent accuracy read): link checks and glob-gated CI stay green over wrong cross-file
  behavioral claims.
- **What the scanner checks, as of the backtick-token widening**
  (`perk/learn/docs_scan.py::_broken_doc_paths`): Markdown/MDX links resolve against the doc's
  parent dir only; full-span backtick `.md`/`.mdx` tokens containing a `/` resolve against repo
  root, doc parent and scan root (`_doc_reference_resolves`). Every other form — un-backticked,
  slashless, line-wrapped, inside a longer backtick span — is verified by `rg` or `git ls-files`
  per named path (this doc once drifted there, #2019).

## A retired-convention sweep needs a symbol grep, not a named-file census

Grep a retired symbol/phrase across ALL prose surfaces (`docs/learned/`,
`docs/design/first-principles/`, `shared/contracts.md`, user docs) instead of hand-enumerating
files: cross-linked docs mirror each other's conventions, so a named-file census undercounts by
construction (the `fail()`/`EXIT_FOR_TYPE` consolidation missed a third file's references).

- **Grep the regex-escaped form too, and end with full CI** — a literal sweep missed an escaped
  test pin (`\[subagents\]` in `extension/pi/v1/objectivePlanning.test.ts`) only full CI caught.
- **"X unchanged" plan notes yield to vocabulary changes inside X** (the `renderCiProse` runtime
  message named the retired `[[ci]]` spelling despite such a note); a **"no changes to plane X"
  non-goal** covers behavior, not comment truth — sweep that plane's narration in the same PR.
- **Natural-language enumerations of the retired SET** slip a symbol gate (a
  "plan/todo/askuser/footer/web" catalog line in `shared/README.md`): grep *adjacent* member
  names, or one bare-word grep hand-triaged. **Concept-level glossary/index blocks** slip it too
  — sweep for the retired *concepts*.
- **Glossary growth must sweep the docs that *enumerate* the glossary** — an "exhaustive list"
  presentation stales on every added term (`CONTEXT.md` § Objective delivery).
- **An exact-survivor-set gate constrains NEW prose too**: paraphrase retired grammar in new
  annotations; "mirror sibling wording" instructions yield to the gate.
- **The `\uXXXX` escape-corruption class.** The corpus is clean except
  `learn-evidence-pipeline.md`'s intentional `\ud800` content line (a data-format example a sweep
  must not "fix"); re-derive corruption counts at implementation time — plan counts lie (#2016).

## The truth-sweep recipe — per-fact source ledgers

- **A plan-carried per-fact source ledger makes execution mechanical** — every corrective claim
  maps to a file/symbol anchor re-verified at planning time.
- **Audit findings (learn-dream reports) are leads, not proofs** — transcribing one reintroduces
  the drift class it exists to fix; re-verify against current source first.
- **The executor re-resolves every path at edit time, and a gate verifies state at execution** —
  neither trusts a same-plan "verified" note; the plan→implement window is enough for drift.
- **Bounded negative greps gate retired spellings**: scoped to the node's owned docs in a
  partitioned objective, cross-node hits recorded as count + attribution.
- **Pin procedures + classifications, not numbers**: on a moved base re-derive every measured
  fact; discovered-stale claims get explicit census-correction rows, never silent fixes.
- **A docs layer documenting a gap with a queued code fix races that fix** — sequence the fix
  first, cite the tracker, or re-verify at cascade/land time.
- **Path-anchor inventories are a floor** — the executable repo-wide grep, not the plan's list, is
  the acceptance.

## De-freeze taxonomy — counts, ordinals, censuses, version stamps

- **Delegate a census to a source owner instead of refreshing the number** — a type-checked
  binding or guard test is a census CI re-derives; prose never is (#2012). **Ordinals are counts
  in disguise**: "to add a third" → "to add a NEW" (#2019).
- **Shapes keyed by what the frozen text was doing** (#2023, #2162): *invariant claim* → an
  enforcement guard (a reconciliation node may mint one) plus a derivation instruction;
  *routing-aid enumeration / roster* → derivation-first, snapshot subordinate to the grep;
  *historic decision record* → verbatim plus ONE live-census-pointer paragraph; bare *number* →
  a live-measurement instruction plus an anti-refreeze sentence; *list pinned by a source-owned
  test* → state the subordination. Add "as of <event>" where history matters; expect the freeze
  to recur one layer up in the replacement sentence.
- **Version markers**: lineage stamps are drift magnets — prefer one doc-level `## Sources`
  convention pinned to a code constant plus a doctor tripwire (`docs/learned/pi/subagents.md`);
  version numbers survive only as event stamps (#2011). A baseline re-stamp re-asserts every
  stamped fact — re-verify all, or keep the honest old stamp (#2009).
- **Falsified universally-quantified absolutes** get a small dimensional matrix or a
  mechanism-scoped claim plus the named exception — never a hedge or a new frozen census; advice
  phrased against a literal count dies with the count (#2012, #2010).
- **Census method (#2165)**: call-site counts ≠ runtime registration counts; anchor on
  interfaces/methods and re-derive at execution (summary-plus-anchor is the freeze-resistant
  shape); premise confirmations record near-misses, not just pass/fail.

## Mirror and fact-drift reconciliation

Mirror drift is usually an omission, not a contradiction — lockstep edits propagate a shared
sentence while a new precision fact lands only on the canonical surface. A claim-by-claim ledger
comparison detects it; pin the exact fact ledger in the plan before restructuring mirrored text
(the perk-expert mirror is convention-guarded, not machine-derived).

How-to pages rot fastest where they enumerate a foreign or volatile catalog: link the stable
upstream authority and route volatile catalogs to reference pages verified against source. Every
backend or config fact correction greps `skills/perk-expert/references/` in the same turn. A
same-turn contract amendment is written from the shipped code, not from plan prose (one revision
stale by then). Backend-neutral wording needs per-backend reachability evidence — a degraded
state can be reachable on one backend only.

Mirror truthfulness beats a plan's scope exclusion: fix the falsified mirror sentence minimally
and record the deviation (#2030); a re-verify pass likewise prunes prose the new facts falsify
outside the enumerated items (a stale "Perk-owned profiles" user-doc section).

## Correction shapes — the instruct-vs-narrate triage and its arms

The unit of keep-vs-correct is the **sentence**: instructive sentences are corrected in place;
narration keeps its text and gains a dated `> **Update**` blockquote, a `Historical:` retitle, or
past-tensing (#2007, #2008). The arms:

- **A fixed residual becomes a "Resolved:" note** — the third arm (#2025).
- **Rationale succession**: "the original motivation … / the rationale that survives …"; a
  correction right for a NEW reason records history AND mechanism, one consistent reason at
  every carrier (#2017, #2011).
- **"Mirrors how X does Y" docstrings** repoint to the one canonical record; **"nothing calls
  this yet"** is deleted outright (caller inventories re-drift); narration never contradicts
  current invariants (#2017).
- **A comment repoint from a deleted file is a fresh factual claim** — verify the referent exists
  *as described*, never substitute mechanically.
- **Neutral rescope**: narrow the domain plus one factual contrast sentence, no invented
  rationale; **a durable rule outlives its exhibit** — time-scope the old one, re-verify against a
  current one, restate the rule (#2020).
- **Qualify, don't prune, overbroad "absolute law" prose**: replace a blanket "never"/"exactly
  two" with the N-way boundary the code enforces and **name the exception** — a consumer that
  cannot import a centralized seam gets an allowlist entry plus a parity test, never a silent
  duplicate.
- **Delete, don't reword, unverifiable non-load-bearing cautions** — they re-enter only via
  `/learn`.
- **A mechanic split into gate + execution** documents the named roles (*whether* vs *how*) and
  enumerates the gate's consumers (#2020).
- **Deleting a self-contradictory instruction needs a loss-freeness check** — trace each durable
  fact to a surviving owner; a DISPROVEN audit claim becomes an explicit byte-preserve pin
  (#2009).
- **A falsified safety claim relocates where the safety lives** — sweep the bundled rationale too
  (#2025). **Falsified-phrase censuses** span src docstrings, test docstrings and learned-doc
  headings — per-hit truth checks, never blanket rewrites (#2017).
- **Intra-doc contradictions resolve toward code truth** at bullet granularity; a heading rename
  is a lockstep set (H2 + Distillation quote + inbound cross-ref grep); an anchor that became a
  re-export repoints to the owner but keeps one clause naming the re-export (#2013).
- **"Pure relocation / byte-identical" docstring claims expire on the first deliberate change** —
  scoping the claim is part of that change (instance: `perk/objective/render.py`).
- **Verify-or-delete for mechanism-bound conclusions** (#2157): a dead mechanism's claim goes; a
  surviving conclusion keeps a contrast clause; *drifted* vs *wrong when made* drives historicize
  vs correct; a partial re-verify never bumps a whole-doc version stamp.
- **Check the boundary criterion before rewording a principle** whose surface grew tenfold — if
  the criterion still classifies everything (`docs/design/first-principles/cli-vs-pi.md`'s
  "narrow `--json` list"), an additive status note suffices.
- **Dry-run the plan's straggler greps against its own quoted target shapes** (#2157).

## Keep-and-annotate beats delete for never-adopted forward guidance

Never-built guidance is not deleted: prepend `> **Status: not yet adopted**` naming the deferral
condition — design intent preserved without authoring fiction. The boundary (#2160):
keep-and-annotate serves a **live reading audience**; a mechanical verbatim changelog has git
history as its archive tier, so retiring it outright is correct.

## Deliberate nonzero stale-pointer advisories (`perk learn docs-check`)

After a keep-history reconciliation the stale-pointer advisory can legitimately end **nonzero**.
Drop deleted-module rows from Cross-references (navigation aids, no learning) but keep deleted
paths inside narrative — deleting those deletes the learning. Record the residual count +
rationale in the commit message. The floor is a measurement, never a recorded number: run
`perk learn docs-check` and weigh the `broken-doc-ref` rows per row (an accepted tail of example
paths, shorthands and history citations, #2026) — a count written here froze once. The resolved
instance: a deliberate pointer to the retired checkpoints module lived in
`workflow/provider-seam.md`'s historical passages until PR #1687 reworded it; paraphrase, don't
quote, such an instance, or the naming doc joins the advisory.

Scanner-aware citation craft (#2158, #2157, #2167):

- **Pin the scanner's token shapes at planning time**: `perk/learn/docs_scan.py::_DOC_TOKEN_RE`
  (a backtick doc token is checked only when it contains a `/`) and its source-pointer sibling,
  which resolves only under `_SOURCE_ROOTS` (a `src/`-prefixed pointer is invisible to it).
- **Three replacement forms keyed to why the pointer died**: renamed/moved → the live path;
  deleted mechanism → a dated-history rewrite naming the deleting event, written locally at each
  hit; hypothetical example → the angle-bracket placeholder (`<name>`), which the charset exempts.
- **Two intentional-dead-path shapes survive**: the placeholder, and the self-annotating accepted
  residual. Rephrase-first — never accept a new residual when a rewording avoids the row.
- **Census expectations state their scope predicate** (trees, token shapes) and
  checkout-dependence — prove per-row provenance when a row exists only in some checkouts.

## Sweep-step craft: mirrors, no-ops, and neighbor staleness

- **Lockstep binds to where the prose lives, not file-name symmetry** — a named mirror surface
  can be prose-free by design; verify its *shape* before naming it.
- **A planned sweep step can legitimately no-op — say so** ("update only what became false")
  instead of manufacturing edits.
- **Landing a section stales a neighbor's "Status" paragraph** — sweep it.
- **Retiring a model-facing name greps for it as an *analogy referent*** ("like X does"), not
  just registration sites; **verbatim historical evidence gets a dated annotation, never a
  rewrite**.
- **A symbol extraction's blast radius includes unlisted prose** — comments, docstrings,
  golden/test harnesses naming the old `module.helper`.
- **A retired limitation or landed future-work capability greps `docs/learned/` the same turn**,
  exactly as `shared/contracts.md` is swept.
- **Scope-narrow an overstated evidence shorthand across ALL its carriers** — the learned doc,
  test docstrings, the contracts row, any clause inheriting that row's proof.
- **Claim sweeps cover `docs/learned/` and `docs/design/first-principles/`** (#2028), plus worked
  examples, declared-shape docstrings and tutorials (runnable top-to-bottom) when behavior grows
  (#2029); a numbered step sequence is scoped to one mode with an up-front callout carrying the
  other mode's complete path (#2024).

## Validation-record reconciliation — sequencing, forward references, evidence classification

**Reconciling an existing record:** obsolete-mark steps in place (*obsolete since PR #N — skip*),
never renumber; fresh evidence is a dated addendum with excerpts inlined (CI logs expire);
dispositions are annotated, never rewritten; an early merge can leave a header attesting one
phase over a section's stale forward-looking prose — diff the merged scope against the record's
*sections*, and precede an early land with a residuals-naming + teardown commit; supersession is
a NEW record plus a dated cross-annotated Status note on the old (`pr-review-doors-dogfood.md`
over `review-dogfood.md` in `docs/design/archive/`).

**Sequencing around `/submit`** — post-submit operator choreography has failed on every observed
instance, "ALWAYS" labels included; prose awareness does not enforce itself:

- Prefer, in order: **front-load** every land-worthy artifact (an arm-independent first commit
  makes an early merge harmless); give the live leg its **own roadmap node**; or plan the
  reconcile loop (`docs/learned/workflow/objective-lifecycle.md` § "The remainder-node
  reconcile playbook").
- Sequence "ALWAYS" steps (teardown, attestation) FIRST; state **what merges when** — exit gates
  are checked at the merge gate, not the submit gate — and name split-eligibility.
- **The PR body is unreachable from the submitting turn** and regenerated on every republish:
  `/submit` terminates the turn, `_compose_pr_body` (`perk/cli/commands/pr/submit_cmd.py`) is a
  fixed composition, and a todo-tracked post-submit `gh pr edit` once lost to the merge.
  Recorded evidence lands on a carrier written *before* `/submit` — the implementation commit
  message, a plan-issue comment, or a tracked artifact the plan names — never the PR body, where
  hand-added content does not survive a republish.

**Forward references and stacked trains:** author only **artifact-anchored** forward references
(an issue, a successor plan — self-resolving), never **commit-anchored** ones (a promised
same-branch commit strands once the branch merges or the layer is ready-stamped: permanently
UNOBSERVED — NOT PASSED) (#2187); a stacked train has no post-submit slot — evidence is complete
at ready time or lives outside the branch; records owed by a stamped layer land on the next
*unpublished* layer with a placement note (#2186); a file-existence gate whose first arm IS the
next node's planning session is self-blocking — recorded operator waiver, later layer (#2175);
bind arms to node/layer identity, never a PR number; a precondition destroyed by the event it
follows needs enforcement before it (#2182); gates needing post-review live arms close as a
successor node (#2188).

**Evidence classification and record hygiene:**

- Part A repeatable protocol / Part B dated evidence + defect log; a sacrificial planted-signal
  PR is a measurable scorecard, closed unmerged so the procedure stays repeatable.
- Per criterion: observed-live / offline-pinned (naming the pin suites) / unobserved — NOT
  PASSED; source-verified-with-live-waived is labelled exactly so, execution arm's scope declared.
- Capture-if-fired, never forced: a naturally-firing degrade arm is recorded verbatim; one that
  never fires is offline-pinned plus a named residual.
- The evidence-gap honesty note: forgotten live evidence is recorded as a dated,
  operator-accepted, **non-residual** note — distinct from named residuals.
- An honest *incomplete* finish defers to a scoped follow-up node; plan the loop, not the fixes —
  the defect log is the deliverable.
- Enumerate per-leg session shapes at planning time; headless SDK probes cover automatable
  observables, interactive launches the `hasUI`-gated ones (#2168); a warm session cannot reload
  its own bindings — live proof is a fresh headless session (#2184).
- The truncated-config trap: verify against the whole committed table and the per-child
  `_meta.json`, never truncated output; an unsatisfiable precondition is a recorded deviation,
  never an unauthorized config flip.
- Copy-paste-complete commands, one provenance value, decisive excerpts inlined, era notes for
  drifted recipes, actor-specific shell lifetimes (no EXIT trap spans per-command tool shells).
- An acceptance line names a *surface* — run exactly that one (#2181); byte-exact literals are
  compared, never transcribed (#2118); outputs may be keepable artifacts (#2169); measurements
  bind to the last commit touching the measured tree plus a standing command (#2193).
- Remote proofs: a unique timestamped repo name, preflighted `gh` scopes, a cleanup trap before
  the first mutation, secret *names* only, post-hoc absence proofs.

Pure pointers: cold-context docs evaluation → `docs/design/docs-site-blueprint.md` § "Cold-context
usability"; browser legs → `docs/learned/toolchain/jsdom-react-component-harness.md` § "Raw-CDP
fallback for browser dogfood"; record *production* (shape, teardown, measured-vs-source-derived,
FAIL verdicts, waivers, offline-proven closure) → `docs/learned/workflow/binding-design-records.md`.

## Objective-roadmap reconciliation craft

- **Hard counts are drift magnets** — even a planning-time-verified one is stale-by-default at
  implementation. Ship the **derivation command**, enumerate anchors rather than count, and
  qualify universally-quantified claims over a growing list when a new entry breaks the
  quantifier. Repair shapes: "De-freeze taxonomy".
- **Re-check the *prior* node's landed narrative and the phase-complete sentence every pass** —
  a reconcile that updated only a node *description* once skipped a narrative entirely.
- **Scope-attribution drift**: when earlier nodes absorbed a node's work, rewrite its
  `description` (the Mechanical table re-renders) AND extend the narrative, both tied to the PR
  diff scope.
- **The landing-log single-entry append**: add one "Node X.Y landed (PR #n)" entry after the
  prior one, never rewriting older ones; the reconcile call overwrites the region, so extract it,
  insert programmatically, `difflib`-prove only-additions, pass the full region.
- **The "Anchors (verified)" region is a drift magnet (#687)** — a node that delivers what an
  anchor said didn't exist stales it; check every reconcile, keep-and-annotate, don't delete.
- **The roadmap `pr` field ≠ the merge PR.** It holds the **plan issue**, as does the
  `LANDED (PR #n)` narrative in header+roadmap-only objectives (#696/#702/#705). Resolve the real
  merge PR with `gh pr view <n> --json state,mergedAt` before citing "landed via PR #N". A node
  auto-marked `done` may carry no narrative — append it (#711).

## Cross-references

- `docs/learned/workflow/curation-batch-craft.md` — moving/splitting/rehoming docs (this doc's
  own split followed them)
- `docs/learned/workflow/binding-design-records.md` — validation/dogfood record production
- `docs/learned/workflow/learn-docs-scan.md` — scanner token shapes + routing-tier derivation
- `docs/learned/workflow/objective-lifecycle.md` — the roadmap `pr` field + remainder-node playbook
- `docs/learned/workflow/shared-contracts.md` — the contract-prose sibling
- `docs/learned/workflow/test-pin-sweeps.md` — pin sweeps
- `docs/learned/toolchain/jsdom-react-component-harness.md` — browser evidence legs
- `docs/design/first-principles/python-cli-guidelines.md`, `docs/design/first-principles/cli-vs-pi.md`
  — the reconciled docs and their status-note conventions
