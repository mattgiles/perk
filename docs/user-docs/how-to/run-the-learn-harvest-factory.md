---
title: "How to run the learn-harvest factory"
description: "Mine your accumulated learned docs as lenses into the code and curate one bounded improvement objective."
sidebar:
  order: 2210
sidebarGroup: "Objectives & learnings"
---

# How to run the learn-harvest factory

Mine your accumulated `docs/learned/` knowledge as lenses into the code and curate ONE bounded
improvement objective by running the learn-harvest objective factory.

## Steps

1. **Start the factory.** From the shell run
   [`perk learn harvest`](../reference/cli.md#perk-learn-harvest) (cold-only — there is no warm
   `/learn-harvest`). Bound the run with a repeatable `--from` (a file or directory inside
   `docs/learned/`), e.g. `perk learn harvest --from docs/learned/workflow`; the default is the
   full corpus.
2. **It gathers at one revision.** The door fast-forwards the checkout you run it from when it
   cleanly can (a guarded, best-effort sync — a dirty or diverged tree is warned and skipped, a
   remote-less checkout is left alone; `--no-sync` skips it), gathers the selected `docs/learned`
   docs into a run-scoped manifest, and opens a **read-only objective-authoring session** that
   reads the docs as lenses into the code — following each doc's source pointers and verifying
   its claims on the real checkout.
3. **It curates ONE objective — or honestly stops.** The session grounds every mined opportunity,
   ranks the survivors, and drafts one bounded improvement objective (a single theme, ≤ 8 roadmap
   nodes, everything else recorded in a backlog-with-reasons). When nothing survives grounding it
   reports the evidence and stops — a **zero-opportunity outcome**, never a placeholder objective.
4. **Review and approve.** The objective rides the normal review-first authoring loop; approval
   saves (creates + activates) it like any other objective.
5. **Drive the nodes.** Generate per-node plans with
   [`perk objective plan`](../reference/cli.md#perk-objective-plan-number) and take each through the
   ordinary implement → submit → land spine.

> **It is an objective factory.** Like [`/objective-plan`](../reference/in-session.md#objective-plan)
> is a plan factory, `perk learn harvest` produces an *objective* — it never edits `docs/learned/`
> and never writes code.

**Single lane vs many:** the selection partitions into lanes (one `docs/learned/<category>/`
group, at most 8 docs each). A single-lane selection is analyzed directly by the session; a
multi-lane selection fans one read-only harvest-analyst per lane via the in-session
`run_harvest_wave` wave. Failed lanes are reported honestly with no retry — named in the final
summary (and in a coverage note on the objective when one is authored) — and a failed or
report-less wave is surfaced as an **incomplete harvest** recommending a bounded `--from`
re-run, never a whole-corpus direct read.

## Related

- **Do:** [How to author an objective roadmap](author-a-roadmap.md) — the hand-authored path to the
  same objective shape.
- **Do:** [How to run the learn-docs factory](run-the-learn-docs-factory.md) — grow the
  docs/learned corpus harvest mines.
- **Look up:** [Objectives — the roadmap model](../reference/objectives.md) — what the curated
  objective becomes once saved.
