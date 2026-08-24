# Dreaming: systematic curation of the learned corpus

## Executive summary

perk has a complete write-time learning lane but no first-class offline curation lane.

- `/learn` extracts durable candidates from completed sessions.
- `perk learn docs` consolidates doc-destined learn issues into `docs/learned/`.
- `perk learn docs-sync` and `docs-check` maintain the corpus's routing and structural hygiene.
- `perk learn harvest` uses learned docs as lenses into code and authors an improvement objective.

What is missing is the maintenance step between accumulation and use: periodically reading the
learned corpus as a whole, checking it against current repository truth, identifying stale or
redundant knowledge, and producing a reviewed program of pruning and consolidation. Today that
work is performed ad hoc and only after the corpus has become visibly burdensome.

`perk learn dream` will make that step explicit. It will launch a read-only objective-authoring
session, analyze the complete learned corpus through two code-owned Pi subagent waves, and produce
one bounded curation objective plus an immutable companion report. It will never edit the corpus
directly. Humans review the objective and report together before either becomes active, and the
normal objective-plan/implement lifecycle performs the actual changes later.

Dreaming is deliberately review-before-deploy. It is an objective factory over perk's persistent
memory layer, not a scheduler, autonomous writer, replacement memory store, or variant of harvest.

## Problem statement

### perk learns additively

The existing learn lane is good at deciding what to remember while a session is still fresh. That
is necessarily a write-time judgment made under context pressure: the agent sees one session, one
plan, and the nearby corpus cues. It cannot yet know which facts will remain useful, which will be
superseded, or which independently captured lessons will later collapse into the same durable
idea.

`perk learn docs` improves the write path by consolidating an inbox of learn issues before adding
to `docs/learned/`. It still works from new inputs toward the existing corpus. It is not a periodic
whole-corpus audit, and it does not revisit every existing document once the new inbox is empty.

The result is healthy accumulation followed by irregular cleanup. Repeated implementation arcs
add chronology, once-distinct topics converge, canonical code and contracts move, routing cues
broaden, and large documents retain more historical explanation than future agents need. None of
those changes necessarily violates a structural check.

### Structural health is not semantic health

The corpus snapshot at commit `5b6942b64dc9d72a2abdc75b7642128d2d1637eb` on 2026-08-18 makes
the distinction visible:

- 63 authored learned docs, excluding the generated index;
- 1,160,620 bytes of authored learned material;
- 37 docs above the 12,288-byte distillation threshold;
- a fully green `perk learn docs-check` result;
- a fresh generated index, no stale source pointers, broken links, cue collisions, invalid
  clusters, or distillation violations;
- an ambient routing block of 3,858 bytes against the 5,120-byte gate.

The latest manual curation record reduced an earlier snapshot from 62 to 58 docs and from
1,025,457 to 1,022,177 bytes. Six days later the corpus had grown by five docs and 138,443 bytes,
roughly 13.5%. The point is not that growth is inherently bad. The point is that a green corpus
can still grow materially faster than humans revisit its semantic shape.

`docs-check` should remain a deterministic structural checker. Trying to make it decide whether a
paragraph is still useful, whether two explanations should merge, or whether a historical lesson
has become canonical source truth would turn a reliable gate into a probabilistic policy engine.
That judgment belongs in a reviewed agent workflow.

### Ad hoc curation does not scale

The prior `docs/design/archive/learned-curation-map.md` exercise established a sound manual method:

- freeze a coherent snapshot;
- inventory every doc;
- use closed dispositions rather than vague cleanup suggestions;
- preserve every unique durable insight before deleting anything;
- verify currency against real code and contracts;
- group edits into coherent, independently landable batches;
- repoint inbound references;
- re-run `docs-sync` and `docs-check` after each batch;
- reconcile drift between the audit snapshot and execution.

It also demonstrated why this cannot remain a single-agent reading exercise. The current corpus is
over a megabyte, individual semantic clusters already reach roughly 195 KB, and the parent must
still compare conclusions across clusters. A whole-corpus prompt would spend the main context on
raw reading and leave too little room for synthesis, objective authoring, and review.

## Motivation and design lessons

The motivating pattern is offline curation: leave the original observations untouched, examine
the persistent memory layer with the benefit of later repository truth, then publish a proposed
reorganization through a human-reviewed path. The important distinction is temporal:

- write-time learning asks, "What from this session appears durable?"
- dream-time curation asks, "What in the accumulated memory remains true, unique, well routed,
  and worth its reading cost now?"

Several existing perk designs already supply the right architectural ingredients.

### `perk learn harvest` is the launch precedent, not the semantic implementation

Harvest is already a cold-only objective factory over `docs/learned/`. It gathers a revision-bound
manifest, borrows the read-only `objective-author` stage, binds specialized guidance, delegates
large analysis through the extension's report-wave machinery, and leaves the first durable write
to approved objective save.

Dream should follow that exterior/interior shape instead of introducing a registry stage or a
parallel objective lifecycle. It must not reuse harvest's semantic schema or blur the two jobs:

| Lane | Input | Output | Explicit boundary |
|------|-------|--------|-------------------|
| `learn docs` | Open `perk:learn` issues | A plan to add or update learned docs | New-learning consolidation, not whole-corpus maintenance |
| `learn dream` | The complete learned corpus | A reviewed corpus-curation objective and dream report | Memory-layer maintenance, not code implementation |
| `learn harvest` | Selected learned docs as code lenses | A bounded code-improvement objective | Code opportunity mining, not docs cleanup |

Dream may discover code opportunities while verifying learned claims. It records those as bounded
harvest follow-ups, citing the surviving doc or semantic cluster through which harvest should
revisit them. It does not add code work to the curation roadmap and does not mint learn-code issues.

### Report waves are the scale mechanism

perk already owns a deep report-wave module over the Pi subagent RPC seam. It provides fresh
contexts, parallel lanes, structured output, stable lane identity, strict completeness, timeouts,
durable aggregates, and explicit failure reports. Dream should use that implementation directly.
The parent model must not author workflow scripts, manually spawn a fleet, invent retries, or
reconstruct coverage from prose.

The learned corpus has a ready semantic partition: `docs/learned/clusters.yaml`. The current 12
clusters contain between two and eight docs each. Cluster lanes make related material visible to
one analyst without forcing the parent to load the corpus. A second reducer wave is then necessary
because duplication, stale assumptions, and routing problems can cross cluster boundaries.

### Objective authoring is the control plane

The desired outcome is not a direct rewrite. It is a decision-complete objective whose roadmap can
be planned, reviewed, and implemented through perk's ordinary lifecycle. Borrowing
`objective-author` gives dreaming:

- read-only repository access during analysis;
- structured objective drafting;
- the existing human review loop;
- backend-neutral objective creation;
- roadmap execution through normal objective planning;
- no bespoke save or project-management workflow.

The one necessary lifecycle addition is a first-class companion record. A compact full-corpus
audit is valuable and reviewable but too detailed to make the objective prose pleasant to use. It
must remain durably attached to the objective rather than disappear in run scratch.

## Domain language

The implementation and documentation should use the following terms consistently.

**Learned corpus**
: The authored durable-memory documents under `docs/learned/`, excluding generated navigation
  such as `index.md`.

**Dream**
: A manual, offline, review-first audit of the complete learned corpus that proposes a bounded
  curation objective. A dream does not edit the corpus.

**Dream report**
: The immutable companion record for one successful dream: snapshot identity, complete coverage,
  one disposition per doc, evidence for non-keep decisions, selected curation units, overflow,
  uncertainties, and harvest follow-ups.

**Disposition**
: One of the closed corpus judgments `keep`, `revise`, `merge-into`, or `retire` assigned to every
  authored learned doc in the snapshot.

**Curation unit**
: A coherent, plan-sized group of mutually dependent corpus changes. A merge source, its surviving
  target, and all required reference repoints are one unit; they cannot be split across roadmap
  nodes.

**Curation objective**
: The bounded objective produced from the highest-priority accepted curation units in a dream
  report.

**Harvest follow-up**
: A bounded surviving-doc or cluster scope that deserves a later `perk learn harvest` run. It is
  not code work inside the curation objective.

These definitions should eventually be mirrored in `CONTEXT.md`, including the distinction
between dream and harvest.

## Goals

`perk learn dream` should:

1. Audit the complete committed learned corpus against current committed repository truth.
2. Scale beyond a single model context through code-owned, parallel Pi subagent waves.
3. Produce one explicit disposition for every authored learned doc.
4. Detect stale claims, redundant documents, consolidation opportunities, routing weaknesses,
   historical ballast, and excessively expensive reads.
5. Preserve unique durable knowledge before any merge or retirement is proposed.
6. Reconcile cluster-local analysis into cross-corpus decisions.
7. Author a bounded, decision-complete objective of coherent curation batches.
8. Persist a full, immutable dream report next to the objective.
9. Keep all durable writes behind one human approval.
10. Report incomplete and no-action outcomes honestly without manufacturing an objective.
11. Route code opportunities toward later harvest runs without combining docs and code work.
12. Work for any initialized perk repository, on both supported objective backends.

## Non-goals

The first version will not:

- schedule dreams or trigger them automatically;
- add a warm `/learn-dream` door;
- read session transcripts, audit telemetry, or invented usefulness metrics;
- claim outcome-based memory optimization when perk has no durable per-doc usefulness signal;
- accept `--from` or otherwise perform partial-corpus dreams;
- edit `docs/learned/` during the authoring session;
- implement code opportunities discovered during verification;
- create `SHOULD_BE_CODE` issues;
- add a vector store or a second persistent memory system;
- use dynamic analyst/reducer role selection;
- allow free-form dispositions;
- support folding content into arbitrary canonical docs as a fifth disposition;
- optimize toward a mandatory byte, document-count, or per-file-size reduction;
- automatically author a chain of follow-on curation objectives;
- silently continue after incomplete subagent coverage;
- mutate or summarize away the original corpus before reviewed plans land.

## Product behavior

### Command surface

The public door is:

```text
perk learn dream [--worktree <name>] [--dry-run] [--remote ...] [--json] [--no-sync] [pi-args...]
```

It uses the shared seeded-door option family for consistency, but the borrowed
`objective-author` stage remains local-only. There is no `--from` flag. The command always means a
complete corpus audit.

The implementation should be a thin cold door modeled on `perk learn harvest`:

- gather deterministic inputs in Python;
- write only run-scoped scratch before launch;
- borrow `objective-author` rather than create a registry stage;
- supply a dream-specific seed and binding trigger;
- let the extension own in-session analysis and review;
- leave backend mutation to approved objective save.

### Snapshot and preconditions

A dream report makes a stronger promise than harvest's current best-effort revision context. It is
an immutable audit of one reproducible repository state. Therefore a real run must:

1. resolve the local launch target;
2. perform the standard pre-gather fast-forward unless `--no-sync` is set;
3. require a resolvable `HEAD`;
4. require a clean checkout after that sync, including no visible untracked files;
5. enumerate a non-empty learned corpus;
6. verify that no open objective already has `origin: learn-dream`;
7. capture the commit SHA exactly once;
8. gather the manifest and launch without another sync.

The clean-tree refusal is intentional. Analysts will inspect both learned docs and repository
sources; stamping a commit while reading uncommitted content would make the report irreproducible.

`--dry-run` remains offline and side-effect-free outside run scratch. It validates local
preconditions, renders the manifest summary and seed, and reports that the remote active-dream
guard was not evaluated. A real launch resolves the configured objective backend and fails closed
if the active-dream query fails.

### One active dream objective

Running another full audit while an earlier curation objective remains open creates duplicate or
contradictory work. V1 therefore enforces one open dream-origin objective per repository.

- Objectives authored by this factory carry `origin: learn-dream` in objective metadata.
- The objective-store interface gains an authoritative open-objective lookup by origin.
- Both GitHub and Linear adapters implement the lookup against durable backend state.
- A matching open objective refuses the command before manifest creation and links the existing
  objective.
- Closed or completed dream objectives do not block a later run.
- Backend lookup failure refuses a real run rather than weakening the guard.

The origin marker must be written as part of initial objective creation so an interrupted companion
save cannot make the objective invisible to the overlap guard.

### Outcomes

A run ends in exactly one of three honest outcomes.

**Incomplete analysis**
: Any missing, failed, timed-out, or malformed lane in either wave produces a coverage report and
  stops before `objective_draft`. Successful partial reports may be surfaced diagnostically but
  never become a partial whole-corpus objective. There is no parent fallback that reads the corpus
  directly and no hidden retry.

**Complete, no selected action**
: The parent reports the clean audit and stops before `objective_draft`. No empty objective, report
  gist, or maintenance placeholder is created. The scratch reports remain disposable.

**Complete, actionable analysis**
: The parent drafts one curation objective and one dream report, reviews them together, and saves
  them through the atomic approval flow described below.

## Architectural strategy

```text
perk learn dream
  -> clean committed snapshot + run-bound manifest
  -> run_dream_wave()                         [one code-owned tool call]
       -> cluster analyst report wave         [parallel fresh contexts]
       -> compact run-scratch report bundle
       -> three-angle reducer report wave     [parallel fresh contexts]
  -> parent reconciliation
  -> structured objective draft + structured dream report
  -> one human review
  -> objective + immutable companion record
  -> normal objective planning and implementation
```

This keeps two deep interfaces:

- the parent knows only how to call one run-bound analysis tool and interpret its typed result;
- objective callers know only that a reviewed objective may carry a typed companion record, while
  backend-specific comment/sentinel storage stays behind the objective-store seam.

### Exterior: gather once in Python

The exterior owns facts that must be established before the model session starts:

- checkout and clean-snapshot validation;
- active-dream lookup;
- learned-doc enumeration;
- cluster registry validation;
- deterministic lane partitioning;
- corpus counts and byte measurements;
- `docs-check`/rich-scan findings;
- commit capture;
- run ID minting;
- manifest writing;
- binding and launch.

The manifest is versioned JSON in run-owned scratch. Its minimum content is:

- schema version;
- commit SHA;
- total authored-doc count and bytes;
- structural and advisory corpus findings;
- cluster-registry mode;
- ordered lane definitions;
- for every doc: repo-relative path, title, routing cue, declared cluster, and raw byte size.

All doc paths must be lexically and physically contained under the resolved `docs/learned/` root.
The manifest and every document are untrusted data, never model instructions.

### Lane partitioning

When `docs/learned/clusters.yaml` exists and is valid, its semantic clusters are the partitioning
source of truth. Each cluster's docs are ordered by path and split deterministically into chunks of
at most eight. Stable lane IDs combine the cluster ID with a one-based chunk number.

When the registry is truly absent, legacy repos remain supported through the existing harvest-like
fallback: group by the top-level category under `docs/learned/`, sort by path, and chunk at eight.

A present-but-invalid registry does not silently fall back. Unknown or missing doc assignments,
an invalid registry shape, or an unreadable registry refuse the run with the same broad posture as
`docs-sync`. Other `docs-check` findings are analysis inputs rather than launch blockers; dreaming
exists partly to propose their repair.

### Interior: one run-bound tool

The extension exposes one `run_dream_wave` tool in the borrowed read-only objective-author
session. It accepts no path, lane, role, or retry parameters. The tool derives the exact manifest
from claimed run state and refuses outside a dream launch.

That small interface hides:

- strict manifest decoding;
- lexical and resolved path containment checks;
- lane construction;
- the two report-wave calls;
- fixed agent identities and report schemas;
- configured subagent-model resolution;
- timeout and cancellation handling;
- intermediate report-bundle writing;
- strict coverage accounting;
- reducer task composition;
- typed normalization of the final aggregate.

The tool writes only fixed-name artifacts beneath the current run's scratch/session-data roots, so
it remains safe in the read-only gate. It uses the standard report-wave RPC and memory-test
adapters; it does not introduce another subagent runtime.

### First wave: semantic-cluster analysis

The first report wave launches one fresh-context dream analyst per manifest lane. All lanes run in
parallel through the standard Pi subagent workflow.

Each analyst must:

1. read the manifest first and select only its byte-exact assigned lane;
2. fully read every assigned document;
3. identify the durable claims, routing purpose, and unique knowledge in each doc;
4. follow real source/contract/doc pointers needed to test currency;
5. distinguish stable guidance from historical narrative and superseded implementation detail;
6. propose exactly one disposition per assigned doc;
7. name merge targets and preservation requirements where applicable;
8. flag suspected cross-cluster overlap without reading arbitrary corpus shards;
9. record bounded harvest follow-ups for code opportunities;
10. return only the engine-validated structured report.

The report carries, at minimum:

- lane and doc identity;
- proposed disposition;
- merge target when applicable;
- concise rationale;
- durable content that must survive;
- repository evidence checked;
- confidence;
- cross-cluster overlap signals;
- harvest follow-ups;
- uncertainties.

The first wave uses strict completeness. One failed lane makes the analysis incomplete even when
all other reports are useful.

### Second wave: cross-corpus reduction

The tool writes the compact analyst reports into one run-bound data bundle, then launches three
fresh-context reducers in parallel. Every reducer sees the complete compact report set, not the raw
corpus.

The fixed reducer angles are:

1. **Consolidation and preservation** — reconcile merge/retire proposals, detect cross-cluster
   redundancy, ensure unique durable content has a surviving home, and reject merge cycles or
   retiring targets.
2. **Currency and accuracy** — challenge claims against current repository truth, distinguish
   obsolete knowledge from still-valid rationale, and prioritize misleading guidance.
3. **Knowledge architecture and routing** — evaluate document boundaries, clusters, cues,
   distillation/read cost, and the quality of proposed harvest follow-ups.

Reducers may selectively re-read cited raw docs or sources only to resolve a conflict or verify a
high-impact non-keep proposal. They must not rescan broad corpus slices; doing so would defeat the
context partition.

The reducer wave is also strict. All three fixed angles are required. Dynamic role selection,
partial reducer acceptance, and reducer-authored sub-waves are out of scope.

### Parent reconciliation

Reducer reports are untrusted data and may disagree. The parent owns final judgment, user
interaction, objective composition, and durable writes.

The parent reconciles the three reports into a closed structured dream-report draft. It must prove:

- the final path set equals the manifest's authored-doc set exactly;
- every doc has exactly one valid disposition;
- every merge target exists and survives;
- merge relationships are acyclic;
- every merge/retire decision satisfies the destructive evidence bar;
- every accepted curation unit is either selected for the roadmap or retained in overflow;
- selected units map onto at most 12 coherent roadmap nodes;
- harvest follow-ups cite surviving destinations;
- incomplete coverage is never described as complete.

Unresolved disagreement falls back non-destructively: `keep`, `revise`, or overflow with the
uncertainty recorded. The parent never forces a merge or retirement merely to complete the table.

## Curation policy

### Closed dispositions

| Disposition | Meaning | Required result |
|-------------|---------|-----------------|
| `keep` | The doc is true, distinct, appropriately routed, and worth its current reading cost | No corpus change; record a concise reason |
| `revise` | The doc remains the right durable home but needs accuracy, focus, routing, boundary, or distillation improvement | Preserve its identity while naming the required revision |
| `merge-into` | Another learned doc is the better durable home for all unique content | Name the surviving target, transferred knowledge, cue/cluster reconciliation, and inbound-reference repoints |
| `retire` | The doc contains no unique durable knowledge after current-source verification, or its durable content already exists in a surviving authoritative home | Prove obsolescence/redundancy and name any reference repoints |

There is no generic "cleanup" disposition and no free-form fifth action. A doc that might deserve
work but cannot yet meet a specific action's evidence bar remains keep/revise or enters overflow.

### Destructive evidence bar

`merge-into` and `retire` require all of the following:

1. a full read of the source doc;
2. verification against current repository sources or canonical docs;
3. explicit enumeration of unique durable content;
4. an explicit surviving home for that content, or proof that none exists;
5. known inbound-reference handling;
6. high confidence after both reducer waves;
7. no unresolved analyst/reducer disagreement.

Reducer consensus alone is insufficient. Human review remains necessary but does not replace the
evidence contract.

### Selection and roadmap cap

A complete report may accept more work than one objective should carry. Accepted curation units
are ranked in this order:

1. incorrect, stale, or actively misleading guidance;
2. high-leverage consolidation that preserves durable content while removing duplicated reading;
3. routing, clustering, and document-boundary improvements;
4. read-cost and distillation improvements;
5. evidence confidence as the stable tie-breaker within a priority tier.

The objective includes at most 12 roadmap nodes. The cap applies to coherent curation batches, not
individual files. A node must remain plan-sized and independently landable; unrelated work is not
packed together merely to fit the cap.

Every accepted but unselected unit remains ranked in the immutable report. A later whole-corpus
dream reassesses it against fresh repository truth. Dreaming does not automatically author a
second objective from overflow.

### No shrink quota

Dreaming optimizes truth, uniqueness, routing quality, and reading cost. It reports document and
byte predictions and later actuals, but it never deletes or compresses knowledge to satisfy a
numerical target. A correct no-shrink objective is better than a destructive target-driven one.

### Harvest routing

When verification exposes a credible code opportunity, the report records:

- the surviving learned doc or cluster that provides the lens;
- the observed code area or pointer;
- why a later harvest is warranted;
- enough scope for a bounded `perk learn harvest --from ...` invocation after curation.

These entries stay outside the curation roadmap. If their source doc will merge or retire, the
follow-up points at the surviving destination rather than a path scheduled for deletion.

## Dream report and objective lifecycle

### Report contents

The dream report is a compact but complete human-readable rendering of the structured final
analysis. It includes:

1. run ID, schema version, commit SHA, date, corpus counts, bytes, registry mode, and structural
   findings;
2. exact first-wave lane and second-wave reducer coverage;
3. one row per authored learned doc with path, cluster, disposition, target, confidence, and
   concise rationale;
4. expanded evidence and preservation notes for every non-keep disposition;
5. unresolved uncertainties and non-destructive fallbacks;
6. ranked selected curation units and their roadmap-node mapping;
7. ranked accepted overflow;
8. bounded harvest follow-ups;
9. predicted document/byte effects without turning them into quotas.

Raw child transcripts and redundant first-wave prose do not belong in the durable report. The
typed intermediate bundle remains run scratch; the report preserves the decisions and evidence a
reviewer or future planner needs.

### First-class companion record

The structured objective draft gains an optional typed companion-record field. Dreaming supplies
one record with a fixed kind such as `learn-dream-report`, a title, its structured source payload,
and immutable semantics. A deterministic renderer owns the Markdown representation; the model
does not invent storage markers or carrier paths.

The review surface renders the objective and companion report together. One approval covers both.
Denial returns to the normal revise/draft/review loop, and every redraft supplies the full objective
and full report.

On approval:

1. create or idempotently recover the objective by run ID, with `origin: learn-dream` in its
   initial metadata;
2. resolve the objective's backend-neutral carrier;
3. create the marker-keyed immutable report record on that carrier;
4. record a retrievable companion reference on the objective and expose it to humans;
5. activate/link the objective in session state only after all preceding steps succeed;
6. terminate through the ordinary objective-save success path.

GitHub stores the companion as a marked comment on the objective issue. Linear stores it as a
marked comment on the project's metadata-sentinel issue. Those are adapter details behind the
objective-store interface.

The save is convergent rather than transactionally magical. If the objective is created and the
report write fails, the remote objective remains origin-marked but the session does not activate
it or report success. Retrying the same save finds the objective by run ID, upserts the absent
record, records its reference, and then activates. Repeating identical content is idempotent;
attempting to replace an existing immutable report with different bytes fails loudly. The system
does not delete the objective as rollback.

### Objective prose and roadmap

The objective prose stays readable. It summarizes:

- why this curation cycle matters;
- the snapshot and overall findings;
- the principles governing preservation and execution;
- selected curation themes;
- boundaries and non-goals;
- a visible reference to the complete dream report.

It does not duplicate the full per-doc table.

The roadmap begins with executable curation batches, not another whole-corpus audit. Dreaming has
already performed the design pass. Each node identifies its complete curation unit, affected
survivors/sources, required reference repoints, expected navigation regeneration, and explicit
dependencies.

### Execution drift

The dream report is an immutable snapshot, not a living progress document. Plans written from its
roadmap must compare their touched corpus paths with the report's commit:

- overlapping changes are re-read and reconciled in that node's plan;
- a changed merge source or target may alter or invalidate the unit;
- a no-longer-safe destructive action is revised or skipped rather than forced;
- unrelated new docs or changes outside the unit wait for the next dream;
- the companion report is never rewritten to pretend it described the later state.

Each landed curation batch must preserve the ordinary corpus invariants:

- unique durable content survives;
- merge sources and targets land atomically;
- inbound Markdown and literal path references are repointed;
- titles, `read_when`, clusters, and distillation headers remain coherent;
- generated navigation is refreshed with `perk learn docs-sync`;
- `perk learn docs-check` is green;
- before/after document and byte measurements are recorded without quota interpretation.

## Required interfaces and contracts

The feature should add the minimum interfaces needed to keep complex behavior behind existing
seams.

### CLI/exterior

- A `dream` verb in the `perk learn` command group.
- A pure learned-corpus resolver and deterministic cluster/category partitioner.
- A versioned dream-manifest model and run-scratch writer.
- A dream-specific seeded prompt and `command:learn-dream` binding.
- Real-launch clean-snapshot and active-origin preconditions.

### Extension/interior

- One globally registered, read-only-safe, run-bound `run_dream_wave` tool.
- A dream wave module over the existing report-wave interface.
- Fixed dream-analyst and dream-reducer agent definitions with closed structured-output schemas.
- A fixed intermediate report-bundle artifact under run scratch.
- Dream-specific guidance that calls the wave once, reconciles, drafts, and uses the ordinary
  review-first objective loop.

### Objective lifecycle

- Optional objective `origin` metadata, including the `learn-dream` value.
- Backend-neutral lookup of an open objective by origin.
- One optional immutable companion record in the structured objective draft/review/save path.
- Backend-neutral create/read/reference behavior for the companion at the objective carrier.
- Save ordering that withholds session activation until objective and companion converge.

### Shared contract

Because Python gathers the manifest, TypeScript consumes it, and objective persistence spans both
planes and both backends, the implementation must amend `shared/contracts.md` in the same change.
The contract should pin behavior and ownership, not incidental function names:

- snapshot and manifest semantics;
- partition and fallback rules;
- strict two-wave coverage;
- fixed reducer roles;
- report/disposition vocabulary;
- no-objective outcomes;
- objective origin and active-run guard;
- companion review/save/immutability behavior;
- activation and retry ordering.

## Failure and trust posture

| Condition | Required behavior |
|-----------|-------------------|
| No resolvable HEAD | Refuse before gathering |
| Dirty checkout | Refuse and explain the immutable-snapshot requirement |
| No authored learned docs | Report `no_learned_docs`; launch nothing |
| Registry absent | Use deterministic category fallback |
| Registry present but invalid/incomplete | Refuse; never silently fall back |
| Learned path escapes through traversal or symlink | Refuse before any analyst spawn |
| Open `learn-dream` objective exists | Refuse and point to it |
| Active-origin backend lookup fails | Fail closed on real launch |
| Manifest missing, mismatched, or malformed | Wave tool refuses before spawn |
| First-wave lane fails or is missing | Mark incomplete; no reducer/objective |
| Reducer lane fails or is missing | Mark incomplete; no objective |
| Reports disagree on destructive action | Non-destructive fallback or overflow |
| No selected action after complete analysis | Report and stop without objective |
| Objective review denied | Revise both objective and report, then review again |
| Objective created but report save fails | Do not activate; retry converges by run ID |
| Existing immutable report differs | Refuse overwrite loudly |

Every manifest value, doc body, source body, analyst report, reducer report, and companion payload
crossing a process/model boundary is untrusted data. Task prompts must say so explicitly. The
implementation validates closed shapes, whitelists fields when normalizing, derives paths from
run state, and never treats report content as instructions.

## Implementation shape

The eventual implementation should proceed in five coherent slices.

### 1. Exterior and manifest

- Add the command, clean-snapshot and active-origin preflight, full-corpus resolver, semantic
  partition, legacy fallback, manifest render/write, dry-run envelope, seed, and binding launch.
- Reuse the seeded-door pipeline and learned-doc enumerator.
- Do not create a registry stage or duplicate launch plumbing.

### 2. Two-level dream wave

- Add the typed manifest decoder, containment checks, analyst/reducer report schemas, fixed lanes,
  intermediate bundle, strict completeness, and single run-bound tool.
- Build entirely on the standard report-wave module and adapters.
- Keep wave mechanics in code and judgment rubrics in agent/skill prose.

### 3. Structured report and curation policy

- Add the final report schema and deterministic Markdown renderer.
- Validate complete path coverage, disposition relationships, destructive evidence, 12-node cap,
  selected/overflow partition, and surviving harvest targets.
- Extend objective drafting/review so the report is reviewed beside the objective without
  bloating objective prose.

### 4. Origin and companion persistence

- Add objective origin metadata and authoritative open-origin lookup to both objective adapters.
- Add immutable companion persistence through the existing carrier seam.
- Make save/retry ordering convergent and withhold activation until the report is durable.
- Preserve existing objective behavior byte-for-byte when origin/companion are absent.

### 5. Documentation, contracts, and dogfood

- Amend the shared contract in the same implementation change.
- Update CLI reference and add a concise how-to for running and interpreting a dream.
- Update the relevant perk-expert backend reference because objective backend behavior grows.
- Add the new domain terms to `CONTEXT.md`.
- Dogfood `perk learn dream` on perk's own clean corpus and use it to author the next real curation
  objective and companion report.

## Verification plan

### Python/exterior coverage

- command registration, help, aliases, standard seeded-door options, and local-only posture;
- clean checkout, dirty checkout, missing HEAD, and empty corpus;
- real active-origin refusal, closed-origin allowance, backend failure, and offline dry run;
- valid cluster partitioning, stable order, >8-doc chunking, root/category fallback, absent
  registry, and invalid/incomplete registry refusal;
- lexical and resolved containment, including escaping symlinks;
- deterministic manifest bytes, commit capture, findings, counts, and run-scoped path;
- launch borrows `objective-author`, uses `command:learn-dream`, and never creates a registry stage.

### TypeScript/interior coverage

- strict manifest decode and bound-path refusal;
- no-argument tool registration and read-only gating;
- exact analyst lanes and tasks from a manifest;
- analyst and reducer JSON schemas;
- first-wave parallel call followed by reducer-wave parallel call;
- strict failure for missing, malformed, timed-out, or failed lanes at either level;
- no reducer launch after incomplete first-wave coverage;
- selective-evidence reducer instructions and untrusted-data posture;
- fixed-name scratch bundle and normalized final result;
- configured analyst/reducer model resolution;
- report-wave production adapter and in-memory test adapter behavior.

### Curation/report coverage

- one and only one disposition per manifest doc;
- exact path-set equality and duplicate rejection;
- merge-target existence, survival, and cycle rejection;
- destructive-evidence enforcement;
- unresolved disagreement's non-destructive fallback;
- truth-then-leverage ranking;
- at most 12 selected roadmap nodes;
- accepted overflow retention;
- surviving-destination harvest follow-ups;
- no shrink quota encoded as validation;
- deterministic report rendering;
- complete/no-action path stopping before draft.

### Objective lifecycle coverage

- optional origin and companion are absence-compatible with every existing objective path;
- review renders objective and report as one approval bundle;
- GitHub objective-issue companion creation/read/reference;
- Linear metadata-sentinel companion creation/read/reference;
- objective-origin lookup on both adapters;
- objective-created/report-failed leaves the session inactive;
- retry finds the objective and converges the missing report;
- identical report retry is idempotent;
- different report bytes refuse immutable overwrite;
- active-origin guard sees an interrupted save;
- approval terminates only after objective, reference, and activation all succeed.

### Repository gates

- prompt fixture/parity and prompt-budget tests;
- skill/binding/packaging inventory tests in both planes;
- CLI taxonomy and command parity tests;
- surface/tool-gating guards;
- shared-contract assertions;
- user-doc build/link checks;
- targeted Python and Node tests while iterating;
- one definitive `run_ci` immediately before submission;
- the real dogfood run as the final product acceptance gate.

## Acceptance criteria

The feature is complete when all of the following are true:

1. A clean initialized repo with learned docs can run `perk learn dream` and enter a tailored
   read-only objective-authoring session.
2. The command audits the full corpus at one stamped commit and refuses dirty or overlapping runs.
3. Raw corpus reading is distributed across parallel semantic lanes with at most eight docs each.
4. Three parallel reducers compare the complete compact analysis across clusters.
5. Any incomplete lane at either level prevents objective authoring.
6. A complete run yields exactly one disposition for every authored learned doc.
7. Merge and retire proposals satisfy the conservative preservation/evidence contract.
8. The selected curation roadmap contains no more than 12 coherent plan-sized nodes.
9. Accepted overflow and code-oriented harvest follow-ups remain durable in the report.
10. Objective and report are reviewed together and activation occurs only after both persist.
11. GitHub and Linear expose equivalent origin-guard and companion-record behavior.
12. A complete no-action audit creates no placeholder objective.
13. Existing objective, learn-docs, and harvest behavior remains unchanged when dream fields are
    absent.
14. User docs, shared contracts, domain vocabulary, and tests describe the same behavior.
15. perk successfully uses the shipped command to author its next real learned-corpus curation
    objective.

## Settled decisions

The following choices are closed for v1:

- corpus health is the core job; code opportunities route to harvest follow-ups;
- repository truth, not transcripts or usage telemetry, is the evidence source;
- every run covers the whole corpus;
- analysis uses the standard Pi report-wave implementation;
- semantic clusters are the primary lanes, with an eight-doc cap;
- legacy repos fall back to category lanes only when no registry exists;
- one code-owned tool runs both wave levels;
- the second level has three fixed reducer angles;
- both wave levels require complete coverage;
- reducers may selectively verify evidence but may not broadly rescan;
- dispositions are keep, revise, merge-into, and retire;
- unresolved disagreements fall back non-destructively;
- destructive changes require full reads, source verification, preservation proof, and high
  confidence;
- objective and report receive one atomic human review;
- the report is a separate immutable companion record, not duplicated objective prose;
- companion persistence uses the objective's existing backend-neutral carrier;
- a failed report save prevents activation and is recovered by idempotent retry;
- actionable work is ranked by truth first, then leverage;
- the roadmap has a hard cap of 12 plan-sized curation nodes;
- overflow remains in the report for a later fresh dream;
- there is no mandatory shrink target;
- execution reconciles only overlapping snapshot drift;
- the feature is available to any perk repo;
- v1 exposes only the manual cold command;
- a clean checkout is required;
- a clean no-op is reported only in-session;
- one open dream-origin objective blocks another run;
- no new registry stage, scheduler, warm door, memory database, or autonomous writer is added.
