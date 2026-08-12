# Curation map for `docs/learned/` — per-doc disposition inventory

**Status:** WIP — audit in progress (Objective #1610, Node 2.1).

- **Snapshot commit:** `8b22cd0cf22616d8a19b1332d3a152decb83f308`
- **Audit date:** 2026-08-11
- **Corpus at snapshot:** 62 docs, 1,025,457 bytes (excluding the generated `docs/learned/index.md`)

## 1. Method + definitions

**Snapshot coherence (fail-closed).** Before any measurement: `git status --porcelain --
docs/learned/` was verified **empty** in the implement worktree (a dirty corpus would have
stopped the audit; a mixed revision is never measured) and the snapshot SHA was recorded
(`git rev-parse HEAD`, above). All sizes, metadata, bodies, and signals in this map describe that
one revision (clean worktree ⇒ worktree reads == HEAD bytes). Cleanliness is re-verified before
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
total bytes = Σ all survivors' predicted sizes (unmerged keeps at current bytes).

## 2. Disposition table

Columns: `doc` (category/slug) · `bytes` · `last-modified` (last commit date touching the file) ·
`signals` (`in: N` = inbound references from tracked files, excluding the doc itself and the two
generated navigation artifacts `.pi/APPEND_SYSTEM.md` + `docs/learned/index.md`; plus
stale-pointer / broken-link / dup-cue findings from `perk learn docs-check` — at this snapshot the
only finding is 1 stale pointer, noted inline) · `disposition` (+ target/destination for
merge/fold) · `unit` (execution-unit id; non-keep rows only) · `est. net add` (merge rows only) ·
`cluster` (surviving docs only) · `rationale`.

| doc | bytes | last-mod | signals | disposition | unit | est. net add | cluster | rationale |
|---|---|---|---|---|---|---|---|---|
| `pi/context-injection` | 6541 | 2026-08-09 | in: 7 | TBD | | | | TBD |
| `pi/context-system` | 10505 | 2026-07-10 | in: 5 | TBD | | | | TBD |
| `pi/extension-api` | 21191 | 2026-08-10 | in: 14 | TBD | | | | TBD |
| `pi/extension-seams` | 10828 | 2026-08-09 | in: 5 | TBD | | | | TBD |
| `pi/headless-session-drive` | 17663 | 2026-08-11 | in: 5 | TBD | | | | TBD |
| `pi/structured-output` | 5070 | 2026-07-09 | in: 0 | TBD | | | | TBD |
| `pi/subagents` | 46064 | 2026-08-11 | in: 14 | TBD | | | | TBD |
| `pi/tool-param-decode` | 6528 | 2026-08-09 | in: 5 | TBD | | | | TBD |
| `pi/tui-surfaces` | 14007 | 2026-08-09 | in: 4 | TBD | | | | TBD |
| `toolchain/biome` | 8669 | 2026-07-09 | in: 7 | TBD | | | | TBD |
| `toolchain/node-test-async-determinism` | 1936 | 2026-08-10 | in: 0 | TBD | | | | TBD |
| `toolchain/python-package-splits` | 15034 | 2026-07-09 | in: 3 | TBD | | | | TBD |
| `toolchain/ruff` | 7681 | 2026-08-09 | in: 8 | TBD | | | | TBD |
| `toolchain/test-parallelism` | 4571 | 2026-06-16 | in: 0 | TBD | | | | TBD |
| `toolchain/ts-module-moves` | 4594 | 2026-07-09 | in: 2 | TBD | | | | TBD |
| `toolchain/ty` | 11210 | 2026-08-10 | in: 5 | TBD | | | | TBD |
| `toolchain/uv-workspace-src-layout` | 5794 | 2026-07-09 | in: 2 | TBD | | | | TBD |
| `toolchain/worktree-node-modules` | 6330 | 2026-07-09 | in: 14 | TBD | | | | TBD |
| `workflow/borrowed-packages` | 10173 | 2026-08-09 | in: 3 | TBD | | | | TBD |
| `workflow/broad-catch-narrowing` | 7037 | 2026-08-10 | in: 0 | TBD | | | | TBD |
| `workflow/cli-command-groups` | 32180 | 2026-08-09 | in: 3 | TBD | | | | TBD |
| `workflow/cold-door-client` | 15453 | 2026-07-09 | in: 6 | TBD | | | | TBD |
| `workflow/cold-door-launch` | 22807 | 2026-08-10 | in: 6 | TBD | | | | TBD |
| `workflow/config-tables` | 24895 | 2026-08-10 | in: 5 | TBD | | | | TBD |
| `workflow/distribution` | 22753 | 2026-08-10 | in: 4 | TBD | | | | TBD |
| `workflow/doc-reconciliation` | 22738 | 2026-08-10 | in: 5 | TBD | | | | TBD |
| `workflow/dot-directory-migration` | 11822 | 2026-06-26 | in: 1 | TBD | | | | TBD |
| `workflow/execution-path-parity` | 5529 | 2026-08-10 | in: 2 | TBD | | | | TBD |
| `workflow/extension-clone-lifecycle` | 7478 | 2026-07-09 | in: 5 | TBD | | | | TBD |
| `workflow/github-gateway` | 19775 | 2026-08-11 | in: 4 | TBD | | | | TBD |
| `workflow/human-engagement-reads` | 8652 | 2026-07-09 | in: 4 | TBD | | | | TBD |
| `workflow/in-place-adoption` | 13354 | 2026-07-09 | in: 3 | TBD | | | | TBD |
| `workflow/init-doctor` | 26440 | 2026-08-10 | in: 11 | TBD | | | | TBD |
| `workflow/init-external-cli` | 23789 | 2026-07-10 | in: 5 | TBD | | | | TBD |
| `workflow/issue-backend` | 17071 | 2026-07-09 | in: 6 | TBD | | | | TBD |
| `workflow/learn-evidence-pipeline` | 25668 | 2026-08-10 | in: 3 | TBD | | | | TBD |
| `workflow/learn-harvest` | 3304 | 2026-08-10 | in: 1 | TBD | | | | TBD |
| `workflow/linear-backend` | 63309 | 2026-08-09 | in: 13 | TBD | | | | TBD |
| `workflow/mergeability-and-conflict-resolution` | 10179 | 2026-08-11 | in: 4 | TBD | | | | TBD |
| `workflow/objective-delivery` | 20168 | 2026-08-11 | in: 1 | TBD | | | | TBD |
| `workflow/objective-lifecycle` | 21822 | 2026-08-10 | in: 8 | TBD | | | | TBD |
| `workflow/objective-store` | 26289 | 2026-08-10 | in: 5 | TBD | | | | TBD |
| `workflow/plan-factories` | 8480 | 2026-07-09 | in: 3 | TBD | | | | TBD |
| `workflow/plan-ref-lifecycle` | 13077 | 2026-08-11 | in: 9 | TBD | | | | TBD |
| `workflow/plan-review-flow` | 27157 | 2026-08-10 | in: 5 | TBD | | | | TBD |
| `workflow/plan-save-surfaces` | 14960 | 2026-07-10 | in: 5 | TBD | | | | TBD |
| `workflow/prompt-templates` | 31812 | 2026-08-11 | in: 3 | TBD | | | | TBD |
| `workflow/provider-seam` | 45683 | 2026-08-10 | in: 5; 1 stale-ptr | TBD | | | | TBD |
| `workflow/pydantic-boundary-models` | 37149 | 2026-08-10 | in: 3 | TBD | | | | TBD |
| `workflow/remote-runner` | 20451 | 2026-08-10 | in: 4 | TBD | | | | TBD |
| `workflow/report-waves` | 20416 | 2026-08-11 | in: 3 | TBD | | | | TBD |
| `workflow/seeded-door-pipeline` | 6584 | 2026-08-10 | in: 2 | TBD | | | | TBD |
| `workflow/session-audit-expectations` | 13569 | 2026-08-10 | in: 2 | TBD | | | | TBD |
| `workflow/session-data` | 15225 | 2026-08-10 | in: 5 | TBD | | | | TBD |
| `workflow/shared-contracts` | 13531 | 2026-08-10 | in: 7 | TBD | | | | TBD |
| `workflow/skill-bindings` | 24749 | 2026-08-10 | in: 11 | TBD | | | | TBD |
| `workflow/skills-exposure` | 3510 | 2026-07-10 | in: 1 | TBD | | | | TBD |
| `workflow/source-scan-guards` | 6570 | 2026-08-09 | in: 8 | TBD | | | | TBD |
| `workflow/test-pin-sweeps` | 5336 | 2026-08-10 | in: 1 | TBD | | | | TBD |
| `workflow/warm-door-commands` | 23971 | 2026-08-11 | in: 6 | TBD | | | | TBD |
| `workflow/worktree-lifecycle` | 18656 | 2026-08-10 | in: 6 | TBD | | | | TBD |
| `workflow/write-capable-cold-doors` | 7670 | 2026-07-09 | in: 1 | TBD | | | | TBD |

## 3. Cluster taxonomy

*(TBD — Pass 3.)*

## 4. Execution units + two-batch partition

*(TBD — Pass 3.)*

## 5. Over-threshold read-cost list

*(TBD — Pass 3.)*

## 6. Predictions

*(TBD — Pass 3.)*

## 7. Full-read ledger (appendix)

*(Maintained as the audit proceeds — one line per non-keep doc.)*

## 8. Downstream handoff / reconciliation notes

*(TBD — Pass 3.)*
