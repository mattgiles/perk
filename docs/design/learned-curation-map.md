# Curation map for `docs/learned/` — per-doc disposition inventory

**Status:** decided — map complete (Objective #1610, Node 2.1). Executed by nodes 2.2/2.3;
consumed by 2.4 (clusters) and 4.1 (over-threshold list, finalized by 2.3).

- **Snapshot commit:** `8b22cd0cf22616d8a19b1332d3a152decb83f308`
- **Audit date:** 2026-08-11/12 (Pass 0 measured 2026-08-11; dispositions finalized 2026-08-12)
- **Corpus at snapshot:** 62 docs, 1,025,457 bytes (excluding the generated `docs/learned/index.md`);
  35 docs exceed the 12,288 B read-cost threshold

## 1. Method + definitions

**Snapshot coherence (fail-closed).** Before any measurement: `git status --porcelain --
docs/learned/` was verified **empty** in the implement worktree (a dirty corpus would have
stopped the audit; a mixed revision is never measured) and the snapshot SHA was recorded
(`git rev-parse HEAD`, above). All sizes, metadata, bodies, and signals in this map describe that
one revision (clean worktree ⇒ worktree reads == HEAD bytes). Cleanliness was re-verified before
finalizing the map. The doc count and totals above come from this Pass-0 measurement.

**Byte measure.** Committed-file bytes (`wc -c` on the clean snapshot worktree), matching the
objective's gate posture ("committed-artifact bytes").

**Read-cost threshold.** 12 KB = **12,288 bytes**.

**Dispositions** (closed vocabulary — exactly one per doc):

- **keep** — the doc survives as-is (later distillation per 4.1 notwithstanding). Gets a cluster.
- **merge-into `<target>`** — the doc's durable content is folded into the named *surviving*
  `docs/learned/` doc and the source file is deleted. The target must itself be disposed **keep**
  (no merging into a retiring/merging doc; no chains). The row names the content to preserve.
- **retire** — the doc is deleted because its content is obsolete (describes retired machinery or
  superseded behavior). The row either enumerates each still-durable nugget with its fold
  destination, or states "fully obsolete" with the rationale. This is the only disposition that
  may drop content, and only content shown to be obsolete.
- **fold `<destination>`** — the doc's durable content belongs in a better **non-learned** carrier
  (`shared/contracts.md` §, a `docs/design/*.md` note, `docs/user-docs/`, a skill reference) and
  moves there; the learned doc is deleted. The row names the destination. (Fold relocates
  *outside* `docs/learned/`; merge-into stays within it.)

A doc that "should be split" has no disposition for it — the vocabulary is closed; such a doc is
recorded as **keep** with a note (splitting is out of this objective's curation scope; 4.1's
distillation header bounds its read cost instead).

**Content preservation invariant** (objective boundary): merge/fold never drop durable learnings;
only **retire** may drop content, and only with the per-row obsolescence rationale.

**Merge-size estimate (`est. net add`).** Every merge row records **estimated net added bytes** —
the bytes the merge is expected to add to the target *after* dedup against the target's existing
content. When uncertain, the conservative upper bound applies: the full source-file byte count.
Predicted target size = current target bytes + Σ its sources' `est. net add`. Predicted corpus
total bytes = Σ all survivors' predicted sizes (unmerged keeps at current bytes). (This map also
counts the two U1 retire-nugget folds as adds to their destination docs — stricter than the
formula requires, for honest totals.)

**Audit method.** Pass 0 measured mechanics only (bytes, last-modified, `perk learn docs-check`
signals, inbound references via `git grep -l -F '<category>/<slug>.md'` over tracked files,
excluding the doc itself and the two generated navigation artifacts `.pi/APPEND_SYSTEM.md` +
`docs/learned/index.md`). Pass 1 ran a read-only subagent summarizer wave (a temporary
project-scoped agent def, deleted after the wave; 8 alphabetical lanes) producing per-doc
summaries treated as untrusted DATA. Pass 2 applied the disposition rubric in the parent session
— **every non-keep doc was full-read before its call** (§8 ledger), as was every doc whose
summary left the call uncertain (`execution-path-parity`, `human-engagement-reads`,
`write-capable-cold-doors`, plus the merge targets `plan-factories`, `skill-bindings` skimmed for
dedup estimation). Pass 3 synthesized clusters, units, batches, and predictions.

**Disposition rubric applied** (from the plan): retire signals = self-described retired machinery,
concentrated stale pointers, content fully superseded elsewhere; merge signals = same seam or
module family, overlapping `read_when` cues, docs routing together for one task, small satellites
orbiting a bigger doc's topic; fold signals = content that is really a contract statement, design
decision record, or operator documentation; **keep is the default** for load-bearing, current,
distinct docs.

## 2. Disposition table

Columns: `doc` (category/slug) · `bytes` · `last-mod` (last commit date touching the file) ·
`signals` (`in: N` = inbound references from tracked files, exclusions as above; plus
stale-pointer / broken-link / dup-cue findings from `perk learn docs-check` — at this snapshot
the only finding corpus-wide is **1 stale pointer**, noted inline on its row) · `disposition`
(+ target for merge) · `unit` (execution-unit id; non-keep rows only) · `est. net add` (merge
rows only) · `cluster` (surviving docs only) · `rationale`.

| doc | bytes | last-mod | signals | disposition | unit | est. net add | cluster | rationale |
|---|---|---|---|---|---|---|---|---|
| `pi/context-injection` | 6,541 | 2026-08-09 | in: 7 | keep |  |  | pi-extension | Live inject-and-conditionally-strip + `branchCarries` dedup patterns; distinct from context-system's file/allowlist facts. |
| `pi/context-system` | 10,505 | 2026-07-10 | in: 5 | keep |  |  | pi-extension | Context-file loading facts + the read-only bash-allowlist five-surface lockstep; load-bearing, current. |
| `pi/extension-api` | 21,191 | 2026-08-10 | in: 14 | keep |  |  | pi-extension | The SDK facts catalog; most-referenced pi doc. Over threshold → 4.1 distills. |
| `pi/extension-seams` | 10,828 | 2026-08-09 | in: 5 | keep |  |  | pi-extension | Seam-extraction recipe (`report()`/`branchOf`/strict-append); current, distinct. |
| `pi/headless-session-drive` | 17,663 | 2026-08-11 | in: 5 | keep |  |  | pi-extension | Headless construction/driving recipe (worker pattern, faux-model determinism). Over threshold → 4.1. |
| `pi/structured-output` | 5,070 | 2026-07-09 | in: 0 | keep |  |  | pi-extension | Distinct task cue (typed model output, `PERK_NO_LLM` gate, faux-provider routing); zero inbound refs is fine — routing is ambient-index-driven. |
| `pi/subagents` | 46,064 | 2026-08-11 | in: 14 | keep |  |  | subagent-orchestration | The central orchestration doc; 3rd-largest, carries contract restatement + historical corrections → prime 4.1 distillation target. |
| `pi/tool-param-decode` | 6,528 | 2026-08-09 | in: 5 | keep |  |  | pi-extension | Tri-state strict decode at the tool boundary; deliberately distinct from cold-door-client's advisory decode policy. |
| `pi/tui-surfaces` | 14,007 | 2026-08-09 | in: 4 | keep |  |  | pi-extension | Surfaces-module governance + harness recipes. Over threshold → 4.1. |
| `toolchain/biome` | 8,669 | 2026-07-09 | in: 7 | keep |  |  | toolchain-gotchas | Biome/tsc gotcha catalog; current, distinct. |
| `toolchain/node-test-async-determinism` | 1,936 | 2026-08-10 | in: 0 | keep |  |  | toolchain-gotchas | Smallest doc but a distinct, current test-craft cue (mock.timers determinism); no candidate target shares its task. |
| `toolchain/python-package-splits` | 15,034 | 2026-07-09 | in: 3 | keep |  |  | code-migration | Module→package split recipe + fold/relocation craft. Over threshold → 4.1. |
| `toolchain/ruff` | 7,681 | 2026-08-09 | in: 8 | keep |  |  | toolchain-gotchas | check-vs-format split + RUF-family catalog; current. |
| `toolchain/test-parallelism` | 4,571 | 2026-06-16 | in: 0 | keep |  |  | toolchain-gotchas | xdist + node file-split recipes; distinct performance-craft cue. |
| `toolchain/ts-module-moves` | 4,594 | 2026-07-09 | in: 2 | keep |  |  | code-migration | Two-commit mv+sweep recipe with the pre-move-resolve rule; distinct. |
| `toolchain/ty` | 11,210 | 2026-08-10 | in: 5 | keep |  |  | toolchain-gotchas | ty narrowing catalog for untyped/JSON values; current. |
| `toolchain/uv-workspace-src-layout` | 5,794 | 2026-07-09 | in: 2 | keep |  |  | code-migration | Repo-level src-layout conversion; distinct grain from python-package-splits' module-level recipe. |
| `toolchain/worktree-node-modules` | 6,330 | 2026-07-09 | in: 14 | keep |  |  | toolchain-gotchas | The stale-SDK/worktree resolution trap; most-referenced toolchain doc. |
| `workflow/borrowed-packages` | 10,173 | 2026-08-09 | in: 3 | keep |  |  | config-and-convergence | Borrowed-package lifecycle lockstep + vetting; current. |
| `workflow/broad-catch-narrowing` | 7,037 | 2026-08-10 | in: 0 | keep |  |  | quality-and-guards | Exception-posture sweep craft; recurring task class, ambient routing covers the zero inbound refs. |
| `workflow/cli-command-groups` | 32,180 | 2026-08-09 | in: 3 | keep |  |  | doors-and-launch | Group-dir template + CLI testing patterns are live; the enacted-taxonomy chronicle is historical ballast → 4.1 distills (4th-largest). |
| `workflow/cold-door-client` | 15,453 | 2026-07-09 | in: 6 | keep |  |  | doors-and-launch | Envelope-aware decode-policy tiers for warm→cold delegation. Over threshold → 4.1. |
| `workflow/cold-door-launch` | 22,807 | 2026-08-10 | in: 6 | keep |  |  | doors-and-launch | The launch seam (argv/env/worktree positioning/io_step). Over threshold → 4.1. |
| `workflow/config-tables` | 24,895 | 2026-08-10 | in: 5 | keep |  |  | config-and-convergence | Config-table placement/read-tier craft; the schema-v2 blockquote marks older spellings historical → 4.1 distills. |
| `workflow/distribution` | 22,753 | 2026-08-10 | in: 4 | keep |  |  | config-and-convergence | Release/publish learnings + the live npm extension-delivery lifecycle (supersedes extension-clone-lifecycle). Over threshold → 4.1. |
| `workflow/doc-reconciliation` | 22,738 | 2026-08-10 | in: 5 | keep |  |  | knowledge-stewardship | Doc-truth reconciliation craft; feeds this objective's own execution. Over threshold → 4.1. |
| `workflow/dot-directory-migration` | 11,822 | 2026-06-26 | in: 1 | keep |  |  | code-migration | Durable path-migration craft (path seam, sweep forms, `_MIGRATIONS`). Note: the arc-status section is stale — the 2.1 config move has since landed (`.perk/config.toml` exists; `.pi/perk.toml` gone); prose refresh is ordinary doc-reconciliation, not curation. |
| `workflow/execution-path-parity` | 5,529 | 2026-08-10 | in: 2 | keep |  |  | cross-plane-contracts | Full-read (fold candidate considered): genuinely parity-testing craft anchored on §8.38, not a contract restatement — keep. |
| `workflow/extension-clone-lifecycle` | 7,478 | 2026-07-09 | in: 5 | retire | U1 |  | — | Self-described RETIRED (git-clone delivery superseded by npm; live story in distribution.md). Nuggets: (1) the retire-an-orphaned-lifecycle recipe (≈2.3 KB) → fold into workflow/init-doctor.md; (2) the F821 test-insertion split-assert gotcha (≈0.5 KB) → fold into workflow/test-pin-sweeps.md. Remainder obsolete: the pi `git:`-loading gap analysis has no live perk consumer (BORROWED_PACKAGES + LINEAR_PACKAGE are all `npm:`), and “where the live story went” is pointer prose. |
| `workflow/github-gateway` | 19,775 | 2026-08-11 | in: 4 | keep |  |  | backends-and-integrations | The gh gateway consolidation + mutation-posting policies. Over threshold → 4.1. |
| `workflow/human-engagement-reads` | 8,652 | 2026-07-09 | in: 4 | keep |  |  | backends-and-integrations | Full-read (fold candidate considered): §8.25 itself lives in contracts.md; this doc holds the durable reasoning (leaf-vocabulary rule, keying decision rule, conformance-ripple craft) — keep. |
| `workflow/in-place-adoption` | 13,354 | 2026-07-09 | in: 3 | keep |  |  | backends-and-integrations | Adoption-writer family + per-tier preservation rules. Over threshold → 4.1. |
| `workflow/init-doctor` | 26,440 | 2026-08-10 | in: 11 | keep |  |  | config-and-convergence | The convergence/repair SSOT doc; U1's recipe-nugget destination (predicted 28,765 B). Over threshold → 4.1. |
| `workflow/init-external-cli` | 23,789 | 2026-07-10 | in: 5 | keep |  |  | config-and-convergence | External-CLI failure postures + skills-delivery SSOT cascade. Over threshold → 4.1. |
| `workflow/issue-backend` | 17,071 | 2026-07-09 | in: 6 | keep |  |  | backends-and-integrations | The issue-tier protocol extraction + conformance craft. Over threshold → 4.1. |
| `workflow/learn-evidence-pipeline` | 25,668 | 2026-08-10 | in: 3 | keep |  |  | knowledge-stewardship | The /learn evidence pipeline; merge TARGET (U3, predicted 28,668 B). Over threshold → 4.1. |
| `workflow/learn-harvest` | 3,304 | 2026-08-10 | in: 1 | merge-into `workflow/learn-evidence-pipeline` | U3 | 3,000 | — | Same module family (`src/perk/learn/`); a small satellite of the learn subsystem. Preserve all four sections (pipeline-fed ordering trap, containment pattern + root-validation, lane-cap watch item, orthogonal error vocabularies) as a harvest-core section. |
| `workflow/linear-backend` | 63,309 | 2026-08-09 | in: 13 | keep |  |  | backends-and-integrations | The largest doc; live backend with heavy landed-arc chronicling → prime 4.1 distillation target. |
| `workflow/mergeability-and-conflict-resolution` | 10,179 | 2026-08-11 | in: 4 | keep |  |  | plan-lifecycle | Conflict probe + resolver-drive mechanics; current. |
| `workflow/objective-delivery` | 20,168 | 2026-08-11 | in: 1 | keep |  |  | objective-system | Stacked-delivery journal/train mechanics. Over threshold → 4.1. |
| `workflow/objective-lifecycle` | 21,822 | 2026-08-10 | in: 8 | keep |  |  | objective-system | Node state machine + authoring loop + supervisor. Over threshold → 4.1. |
| `workflow/objective-store` | 26,289 | 2026-08-10 | in: 5 | keep |  |  | objective-system | Objective-storage Protocol extraction + growth craft. Over threshold → 4.1. |
| `workflow/plan-factories` | 8,480 | 2026-07-09 | in: 3 | keep |  |  | doors-and-launch | Merge TARGET (U4): absorbs seeded-door-pipeline → one read-only-launcher family doc (predicted 14,380 B — crosses the threshold and joins the §6 list). |
| `workflow/plan-ref-lifecycle` | 13,077 | 2026-08-11 | in: 9 | keep |  |  | plan-lifecycle | plan-ref duality + clobber hazard + additive-field recipe. Over threshold → 4.1. |
| `workflow/plan-review-flow` | 27,157 | 2026-08-10 | in: 5 | keep |  |  | plan-lifecycle | Review→approval→save pipeline + race classes. Over threshold → 4.1. |
| `workflow/plan-save-surfaces` | 14,960 | 2026-07-10 | in: 5 | keep |  |  | plan-lifecycle | Two-surface fidelity gap + recovery carriers. Over threshold → 4.1. |
| `workflow/prompt-templates` | 31,812 | 2026-08-11 | in: 3 | keep |  |  | cross-plane-contracts | Cross-plane render-parity architecture (5th-largest). Over threshold → 4.1. |
| `workflow/provider-seam` | 45,683 | 2026-08-10 | in: 5; 1 stale-ptr | keep |  |  | config-and-convergence | 2nd-largest; live seams (plan/footer/web) + retired-seam chronicles; carries the corpus's one stale pointer (`extension/checkpoints/checkpoints.ts`) → prime 4.1 target (the pointer fix rides the distillation edit). |
| `workflow/pydantic-boundary-models` | 37,149 | 2026-08-10 | in: 3 | keep |  |  | quality-and-guards | Boundary↔domain conversion pattern + supersession records → 4.1 distills. |
| `workflow/remote-runner` | 20,451 | 2026-08-10 | in: 4 | keep |  |  | doors-and-launch | Remote dispatch + CI execution seam. Over threshold → 4.1. |
| `workflow/report-waves` | 20,416 | 2026-08-11 | in: 3 | keep |  |  | subagent-orchestration | The wave-module mechanics + flow-migration checklist. Over threshold → 4.1. |
| `workflow/seeded-door-pipeline` | 6,584 | 2026-08-10 | in: 2 | merge-into `workflow/plan-factories` | U4 | 5,900 | — | Same launcher family: the pipeline IS the factory spine generalized (8 doors share it); the two docs route together for “add/convert a seeded read-only door”. All six sections transfer (three exports, gather-closure policy, seed-interpolation rule, monkeypatch seams, byte-pin discipline, guard-enforced primitives); cross-ref block dedups. |
| `workflow/session-audit-expectations` | 13,569 | 2026-08-10 | in: 2 | keep |  |  | knowledge-stewardship | perk-dev audit-catalog curation semantics. Over threshold → 4.1. |
| `workflow/session-data` | 15,225 | 2026-08-10 | in: 5 | keep |  |  | plan-lifecycle | run-id/provenance/GC lifecycle. Over threshold → 4.1. |
| `workflow/shared-contracts` | 13,531 | 2026-08-10 | in: 7 | keep |  |  | cross-plane-contracts | shared/ subsystem craft (six-seam recipe, contracts dieting). Over threshold → 4.1. |
| `workflow/skill-bindings` | 24,749 | 2026-08-10 | in: 11 | keep |  |  | config-and-convergence | Merge TARGET (U2, predicted 27,649 B): becomes the one skills-into-sessions doc (delivery + scoping). Over threshold → 4.1. |
| `workflow/skills-exposure` | 3,510 | 2026-07-10 | in: 1 | merge-into `workflow/skill-bindings` | U2 | 2,900 | — | Self-described complement of skill-bindings (“delivery vs scoping”; sole inbound ref is skill-bindings itself); routes together for skills-into-sessions work. Preserve all four reasoning sections (engagement-gated zero-change rollout, whole-tier degrade, by-name keying, asymmetric both-plane coverage) as a scoping section. |
| `workflow/source-scan-guards` | 6,570 | 2026-08-09 | in: 8 | keep |  |  | quality-and-guards | The grep-guard test genre; heavily referenced. |
| `workflow/test-pin-sweeps` | 5,336 | 2026-08-10 | in: 1 | keep |  |  | quality-and-guards | Pinned-prose sweep craft; U1's F821-gotcha destination (predicted 5,866 B). |
| `workflow/warm-door-commands` | 23,971 | 2026-08-11 | in: 6 | keep |  |  | doors-and-launch | Warm-command gating/driving disciplines. Over threshold → 4.1. |
| `workflow/worktree-lifecycle` | 18,656 | 2026-08-10 | in: 6 | keep |  |  | plan-lifecycle | Worktree batch-op posture (uncertainty→skip, self-heal). Over threshold → 4.1. |
| `workflow/write-capable-cold-doors` | 7,670 | 2026-07-09 | in: 1 | keep |  |  | doors-and-launch | Full-read (merge candidate considered): the save-stage borrow is the write-capable *sibling* of plan-factories' read-only borrow with its own consumers (repo-skills lifecycle verbs) — distinct cue, kept. |

**Non-keep set (4 docs):** `workflow/extension-clone-lifecycle` (retire),
`workflow/skills-exposure`, `workflow/learn-harvest`, `workflow/seeded-door-pipeline` (merges).
No **fold** disposition was warranted: the two full-read fold candidates
(`execution-path-parity`, `human-engagement-reads`) hold genuine cross-cutting reasoning, not
contract restatement — the restated contracts already live in `shared/contracts.md` and the docs
carry the *why* behind them. No "should-be-split" notes were needed.

## 3. Cluster taxonomy

12 clusters (guardrail: 6–12; every surviving doc in exactly one; orthogonal to the
`pi/`/`toolchain/`/`workflow/` directories — no files move; `cluster:` becomes frontmatter in
2.4). Theme lines are **non-binding drafts** of 2.4's ≤160-char rollup cues.

### pi-extension (8)

*Theme draft:* Pi SDK/extension substrate craft — API facts, context injection/loading, seams,
TUI surfaces, tool-param decode, structured output, headless session driving.

Members: `pi/context-injection`, `pi/context-system`, `pi/extension-api`, `pi/extension-seams`,
`pi/headless-session-drive`, `pi/structured-output`, `pi/tool-param-decode`, `pi/tui-surfaces`.

### subagent-orchestration (2)

*Theme draft:* Spawning and orchestrating subagents — pi-subagents mechanics, agent defs, report
waves, lane semantics, streaming. (Two members, not a singleton: the pair is the whole
orchestration domain — pi-subagents substrate + perk's wave module — and neither belongs with
the pi-extension substrate facts.)

Members: `pi/subagents`, `workflow/report-waves`.

### toolchain-gotchas (6)

*Theme draft:* Lint/typecheck/test toolchain gotchas — Biome/tsc, ruff, ty, node:test
determinism, test parallelism, worktree node_modules resolution.

Members: `toolchain/biome`, `toolchain/node-test-async-determinism`, `toolchain/ruff`,
`toolchain/test-parallelism`, `toolchain/ty`, `toolchain/worktree-node-modules`.

### code-migration (4)

*Theme draft:* Moving code shapes safely — Python module→package splits, TS module moves,
src-layout conversion, dot-directory path-root migrations.

Members: `toolchain/python-package-splits`, `toolchain/ts-module-moves`,
`toolchain/uv-workspace-src-layout`, `workflow/dot-directory-migration`.

### doors-and-launch (7)

*Theme draft:* CLI↔session plumbing — cold-door launch/client, warm-door commands, CLI command
groups, read-only factory/seeded doors, write-capable doors, the remote runner.

Members: `workflow/cli-command-groups`, `workflow/cold-door-client`,
`workflow/cold-door-launch`, `workflow/plan-factories` (post-U4: + seeded pipeline),
`workflow/remote-runner`, `workflow/warm-door-commands`, `workflow/write-capable-cold-doors`.

### plan-lifecycle (6)

*Theme draft:* The plan artifact's life — plan-ref linkage, review→approval→save, save surfaces,
worktree filesystem lifecycle, session data/run identity, mergeability + conflict resolution.

Members: `workflow/mergeability-and-conflict-resolution`, `workflow/plan-ref-lifecycle`,
`workflow/plan-review-flow`, `workflow/plan-save-surfaces`, `workflow/session-data`,
`workflow/worktree-lifecycle`.

### objective-system (3)

*Theme draft:* Objectives — node state machine and authoring loop, objective storage Protocol,
stacked delivery trains.

Members: `workflow/objective-delivery`, `workflow/objective-lifecycle`,
`workflow/objective-store`.

### backends-and-integrations (5)

*Theme draft:* Issue backends and external integrations — the issue-tier Protocol, GitHub
gateway, Linear backend, human-engagement reads, in-place adoption.

Members: `workflow/github-gateway`, `workflow/human-engagement-reads`,
`workflow/in-place-adoption`, `workflow/issue-backend`, `workflow/linear-backend`.

### config-and-convergence (7)

*Theme draft:* Repo wiring and convergence — config tables, init/doctor, external CLIs, borrowed
packages, provider seams, skill bindings/exposure, distribution.

Members: `workflow/borrowed-packages`, `workflow/config-tables`, `workflow/distribution`,
`workflow/init-doctor`, `workflow/init-external-cli`, `workflow/provider-seam`,
`workflow/skill-bindings` (post-U2: + skills exposure).

### cross-plane-contracts (3)

*Theme draft:* Cross-plane/cross-path agreement — shared/ parsed contracts, prompt-template
render parity, execution-path parity testing.

Members: `workflow/execution-path-parity`, `workflow/prompt-templates`,
`workflow/shared-contracts`.

### knowledge-stewardship (3)

*Theme draft:* Keeping the record true — /learn evidence pipeline (+ harvest core post-U3), doc
reconciliation craft, session-audit expectation curation.

Members: `workflow/doc-reconciliation`, `workflow/learn-evidence-pipeline`,
`workflow/session-audit-expectations`.

### quality-and-guards (4)

*Theme draft:* Code-quality disciplines — source-scan guard tests, test-pin sweeps, broad-catch
narrowing, Pydantic boundary models.

Members: `workflow/broad-catch-narrowing`, `workflow/pydantic-boundary-models`,
`workflow/source-scan-guards`, `workflow/test-pin-sweeps`.

### Predicted ambient-tier size (informational, not a gate)

One ambient line per cluster (title + ≤160-char rollup cue + member slugs), estimated per
cluster: pi-extension ≈ 420 B · subagent-orchestration ≈ 240 B · toolchain-gotchas ≈ 350 B ·
code-migration ≈ 310 B · doors-and-launch ≈ 400 B · plan-lifecycle ≈ 390 B · objective-system ≈
270 B · backends-and-integrations ≈ 330 B · config-and-convergence ≈ 400 B ·
cross-plane-contracts ≈ 290 B · knowledge-stewardship ≈ 300 B · quality-and-guards ≈ 310 B.
Sum ≈ 4.0 KB + block preamble/markers ≈ 0.7 KB → **≈ 4.7 KB**, comfortably under the objective's
~8 KB soft target (vs. today's ~13 KB 62-line routing block).

## 4. Execution units + two-batch partition

**Batch rule (settled):** cohesion first — each execution unit (a target/destination with ALL its
sources, or a standalone retire) lands whole in one batch. **Burden** per unit = Σ source bytes ×
kind weight: retire (fully obsolete) ×1.0; retire (with nugget extraction) ×1.5; fold ×1.5; merge
×2.0. **Balanced** = the heavier batch's total burden ≤ 1.5× the lighter. Each batch must be
independently coherent, landable, and leave `perk learn docs-check` green after its own
`perk learn docs-sync` regeneration.

| unit | kind | target or destination | sources | burden | batch |
|---|---|---|---|---|---|
| U1 | retire (nugget extraction) | — (nuggets → `workflow/init-doctor`, `workflow/test-pin-sweeps`) | `workflow/extension-clone-lifecycle` | 7,478 × 1.5 = 11,217 | A |
| U2 | merge | `workflow/skill-bindings` | `workflow/skills-exposure` | 3,510 × 2.0 = 7,020 | A |
| U3 | merge | `workflow/learn-evidence-pipeline` | `workflow/learn-harvest` | 3,304 × 2.0 = 6,608 | B |
| U4 | merge | `workflow/plan-factories` | `workflow/seeded-door-pipeline` | 6,584 × 2.0 = 13,168 | B |

No unit shares a target or destination with another; every non-keep row belongs to exactly one
unit; merge targets stay keep rows above (their edit happens inside their unit's batch).

**Batch A** (node 2.2): U1 + U2 — burden **18,237**; 2 units, 2 source docs deleted; edits
`workflow/init-doctor.md`, `workflow/test-pin-sweeps.md`, `workflow/skill-bindings.md`.

**Batch B** (node 2.3): U3 + U4 — burden **19,776**; 2 units, 2 source docs deleted; edits
`workflow/learn-evidence-pipeline.md`, `workflow/plan-factories.md`.

Balance: 19,776 / 18,237 = **1.08** ≤ 1.5 ✓ (no forcing unit).

## 5. Over-threshold read-cost list (predictive — 2.3 finalizes)

**Correction rule (settled, stated here for the executors):** this list is *predictive*. At 2.3
close, the executor re-measures every survivor (`wc -c` at 2.3's HEAD) and **replaces this list
with the actual-bytes membership** (survivors > 12,288 B) — the finalized list is what 4.1
consumes. Prediction errors are corrected mechanically at 2.3, never re-litigated at 4.1
planning.

Predicted membership — **36 docs** (35 current over-threshold keeps, all surviving, plus
`workflow/plan-factories`, which the U4 merge pushes over; merge/fold targets shown at predicted
size, all others at current bytes):

| doc | predicted bytes |
|---|---|
| `workflow/linear-backend` | 63,309 |
| `workflow/provider-seam` | 45,683 |
| `pi/subagents` | 46,064 |
| `workflow/pydantic-boundary-models` | 37,149 |
| `workflow/cli-command-groups` | 32,180 |
| `workflow/prompt-templates` | 31,812 |
| `workflow/init-doctor` | 28,765 (26,440 + 2,325 U1 nugget) |
| `workflow/learn-evidence-pipeline` | 28,668 (25,668 + 3,000 U3) |
| `workflow/skill-bindings` | 27,649 (24,749 + 2,900 U2) |
| `workflow/plan-review-flow` | 27,157 |
| `workflow/objective-store` | 26,289 |
| `workflow/warm-door-commands` | 23,971 |
| `workflow/init-external-cli` | 23,789 |
| `workflow/cold-door-launch` | 22,807 |
| `workflow/distribution` | 22,753 |
| `workflow/doc-reconciliation` | 22,738 |
| `workflow/objective-lifecycle` | 21,822 |
| `pi/extension-api` | 21,191 |
| `workflow/remote-runner` | 20,451 |
| `workflow/report-waves` | 20,416 |
| `workflow/objective-delivery` | 20,168 |
| `workflow/github-gateway` | 19,775 |
| `workflow/worktree-lifecycle` | 18,656 |
| `pi/headless-session-drive` | 17,663 |
| `workflow/issue-backend` | 17,071 |
| `workflow/cold-door-client` | 15,453 |
| `workflow/session-data` | 15,225 |
| `toolchain/python-package-splits` | 15,034 |
| `workflow/plan-save-surfaces` | 14,960 |
| `workflow/plan-factories` | 14,380 (8,480 + 5,900 U4) |
| `pi/tui-surfaces` | 14,007 |
| `workflow/session-audit-expectations` | 13,569 |
| `workflow/shared-contracts` | 13,531 |
| `workflow/in-place-adoption` | 13,354 |
| `workflow/plan-ref-lifecycle` | 13,077 |
| `pi/context-system` | 10,505 — **NOT on the list** (shown as the nearest miss for calibration; membership starts strictly above 12,288 B) |

(The table's final row is calibration context, not a member; the predicted membership is the 35
rows above it plus `workflow/plan-factories` = 36.)

Near-threshold watch (for 2.3's re-measure): `workflow/plan-ref-lifecycle` (13,077),
`workflow/in-place-adoption` (13,354), `workflow/shared-contracts` (13,531) sit within ~1.1 KB of
the line; `workflow/test-pin-sweeps` (predicted 5,866) and `workflow/dot-directory-migration`
(11,822) stay under.

## 6. Predictions

- **Post-curation doc count: 58** (62 − 1 retire − 3 merges; exact, from the dispositions).
- **Post-curation corpus total: ≈ 1,019,236 bytes**, derived per the §1 formula:
  1,025,457 − 20,876 (removed sources: 7,478 + 3,510 + 3,304 + 6,584)
  + 11,800 (merge `est. net add`: 2,900 + 3,000 + 5,900)
  + 2,855 (U1 nugget folds: 2,325 + 530) = **1,019,236**.
- Reading of the numbers (for 2.3's reconciliation): Phase 2's byte win is deliberately modest
  (~6 KB net) — its real yields are the doc count (−4), the removal of obsolete content, and
  routing consolidation; the corpus's byte problem is concentrated in the 36 over-threshold docs
  and is 4.1's job (distillation), not curation's.
- 2.3 reconciles actual doc count and bytes against this section and names drift (per the §9
  protocol) as a variance source where applicable. `est. net add` values are judgment estimates
  (derivations in §4's unit rows: source bytes minus frontmatter/title minus duplicated
  cross-ref lines); the conservative upper bound (full source bytes) would predict
  1,025,457 − 20,876 + 13,398 + 2,855 = 1,020,834 — the ~1.6 KB spread between the two is noise
  at corpus scale.

## 7. Downstream handoff / reconciliation notes

- **Node 2.2 (Batch A)** executes U1 + U2 from §4: delete `workflow/extension-clone-lifecycle.md`
  after folding its two nuggets (§2 row) into `workflow/init-doctor.md` +
  `workflow/test-pin-sweeps.md`; merge `workflow/skills-exposure.md` into
  `workflow/skill-bindings.md` (merged doc's `read_when` must cover both cues). Then
  `perk learn docs-sync` + green `perk learn docs-check`; record before/after doc counts and
  bytes against §6.
- **Node 2.3 (Batch B)** executes U3 + U4: merge `workflow/learn-harvest.md` into
  `workflow/learn-evidence-pipeline.md`; merge `workflow/seeded-door-pipeline.md` into
  `workflow/plan-factories.md`. Then docs-sync/check as above; reconcile actuals vs §6; and
  **finalize §5** (re-measure every survivor at 2.3's HEAD; replace the predictive list with
  actual-bytes membership — that finalized list is 4.1's input).
- **Node 2.4** takes §3's cluster assignments as the two-tier taxonomy input (`cluster:`
  frontmatter, one ambient line per cluster); the theme lines are drafts for its ≤160-char rollup
  cues; 2.4 assigns clusters for any addendum survivors (drift protocol below).
- **Node 4.1** takes the **2.3-finalized** §5 list as the distillation pass's membership. The §2
  rationale column flags the docs where distillation has the most historical ballast to shed
  (`linear-backend`, `provider-seam` — which also carries the corpus's one stale pointer —
  `pi/subagents`, `cli-command-groups`, `config-tables`, `pydantic-boundary-models`).
- **Merge execution notes:** in every merge, the source's `read_when` cue content folds into the
  target's cue (the merged doc must still route for the source's tasks); source cross-reference
  blocks dedup against the target's; inbound references to the deleted files (see §2 `in:`
  counts; enumerable via the same `git grep -l -F` form) must be repointed in the executing
  batch so `docs-check`'s broken-link hygiene stays clean.

**Drift protocol (the map is frozen at its snapshot).** At the start of nodes 2.2 and 2.3, the
executor runs `git diff --name-status <map-snapshot-SHA>..HEAD -- docs/learned/`
(snapshot SHA in the header). **Trigger:** any changed blob or new/deleted file (mechanical — no
"substantiality" judgment). **Ownership:** the executing node (2.2 first; anything visible only
later, 2.3) reconciles ALL drift it sees; 2.4 assigns clusters for addendum survivors.
**Action:** a new doc gets a full addendum row (this map's rubric applied) and, if non-keep,
joins a unit in the owning node's batch; a changed doc gets an addendum row marked
`supersedes <doc>` re-affirming or revising its disposition — the addendum row is authoritative
over the original. **Predictions are not recomputed** — 2.3's actuals-vs-predictions
reconciliation names drift explicitly; the over-threshold list needs no drift handling (2.3
finalizes it from actuals regardless).

## 8. Full-read ledger (appendix)

One line per non-keep doc — the merge/retire call was made only after the full read:

- [x] `workflow/extension-clone-lifecycle` — full-read 2026-08-12
- [x] `workflow/skills-exposure` — full-read 2026-08-12
- [x] `workflow/learn-harvest` — full-read 2026-08-12
- [x] `workflow/seeded-door-pipeline` — full-read 2026-08-12

(Additionally full-read because summaries left the call uncertain, all resolved **keep**:
`workflow/execution-path-parity`, `workflow/human-engagement-reads`,
`workflow/write-capable-cold-doors`, `workflow/plan-factories` — listed for completeness; the
ledger proper covers exactly the non-keep set.)
