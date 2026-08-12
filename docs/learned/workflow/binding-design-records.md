---
title: Binding design records & disposable-scaffold spikes
read_when: You are authoring a binding design record, spike, or blueprint — disposable-scaffold evidence, teardown proofs, cross-section arithmetic, re-measure at commit, reconciliation rules.
cluster: knowledge-stewardship
---

# Binding design records & disposable-scaffold spikes

A *binding* design record (a blueprint or spike whose decisions later work must honor) has its own
authoring craft, distilled from the docs-site records
(`docs/design/docs-site-blueprint.md`, `docs/design/docs-site-visual-blueprint.md`,
`docs/design/docs-site-bridge-spike.md`) and the curation map
(`docs/design/learned-curation-map.md`). Only the cross-cutting record-authoring patterns live
here — the docs-site–specific discoveries stay bound in those committed records; reuse rather
than re-derive.

## The proven record shape (three confirmations)

Settle the criteria in the plan → verify them in a **disposable untracked scaffold** → commit
**text-only** evidence (verbatim command output, contrast tables, annotated ASCII wireframes) →
close with a teardown `git status --porcelain` proof → bind the decisions with a **named-consumer
list and an explicit reconciliation rule** (who must obey the record, and what event forces a
re-verify). A record built this way is reusable evidence, not an opinion — later work reuses it
instead of re-running the spike.

## Disposable spike teardown is two-part

gitignore covers *generated state* but not scaffold source, untracked fixtures, or temp edits to
tracked files — so teardown = remove the scaffold + restore the tracked edits + remove the
fixtures, and only then commit the porcelain proof. Pre-script the teardown in the plan; an
improvised teardown is what leaves the dangling checkout.

## Pin outcome criteria, not third-party config fragments

An exact prescribed config drifts with upstream deprecations (the remark-plugins key
auto-coercion case was the shipped instance). Encode version selection as a **resolution rule**
("latest patch at spike time"), not a hard pin, and record the *resolved* pair as the binding
selection — the rule survives upstream churn; the frozen fragment doesn't.

## Cross-section reconciliation arithmetic is where verification effort belongs

In a decisions-pinned spec, the actionable review findings were **consistency failures between
the doc's own sections** — not wrong individual decisions. When a doc claims total-coverage rules,
carry the arithmetic **in-doc** so drift self-detects; and a catch-all rule must own its pinned
exceptions as a first-class case, not rely on cross-section memory.

## Readiness tables for opt-out gates record effective state, not provisioning status

A default-on knob phrased as a prerequisite becomes a false requirement — the table must say what
is *effectively* on/off for this record's scope, not whether someone provisioned it.

## Point-in-time records re-measure at commit

Never transcribe planning-time numbers into the committed record — re-measure at commit time, and
verify the counting selectors themselves (the `git ls-files '<glob>'` root-file drop trap: a glob
that misses root-level files undercounts silently).

## Verification tooling disposed with a scaffold must be rebuilt from prose later

Preserve verbatim outputs + the methodology in the record, because the checks themselves are torn
down with the scaffold. Once the target becomes committed code, prefer making the checks
repo-owned and re-runnable (deferred here until `docs/site/` exists — flagged, not fiction).

## Cross-references

- `docs/learned/workflow/doc-reconciliation.md` — the curation-batch measurement rules
  (SHA-stamped, mechanically-derived tables) and the record-completeness bar
- `docs/design/docs-site-blueprint.md`, `docs/design/docs-site-visual-blueprint.md`,
  `docs/design/docs-site-bridge-spike.md` — the binding records this craft was distilled from
