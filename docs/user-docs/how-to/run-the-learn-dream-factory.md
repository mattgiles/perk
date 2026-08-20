---
title: "How to run the learn-dream factory"
description: "Audit the whole learned corpus at one stamped commit and curate one bounded curation objective plus the durable dream report."
sidebar:
  order: 2215
sidebarGroup: "Objectives & learnings"
---

# How to run the learn-dream factory

Audit your WHOLE `docs/learned/` corpus at one stamped commit and curate ONE bounded curation
objective plus the durable dream report by running the learn-dream curation factory.

## Steps

1. **Start the factory.** From the shell run
   [`perk learn dream`](../reference/cli/learn-and-gist.md#perk-learn-dream) (cold-only — there
   is no warm `/learn-dream`). Dream is whole-corpus only: there is no `--from`, and the door
   rejects the spelling — a bounded partial mine is
   [`perk learn harvest --from`](../reference/cli/learn-and-gist.md#perk-learn-harvest). The
   door requires a **clean checkout** (untracked files included — a dirty tree refuses
   `dirty_checkout`) so the audit is reproducible from the stamped commit, and it runs the
   fail-closed **origin guard**: one open dream-authored objective per repo — an existing one
   refuses `origin_conflict` (finish or close it first), and a lookup that cannot answer
   refuses rather than proceeding on uncertainty.
2. **It audits at one stamped commit.** The door captures HEAD exactly once as the manifest's
   `commit_sha` snapshot and gathers the tracked corpus into run-scoped lanes. In the launched
   session a two-level wave runs: one read-only analyst per **semantic cluster lane** (at most
   8 docs each, split from the corpus's cluster registry), then three fixed **reducers** that
   read every analyst report and take explicit per-doc stances. The whole wave runs under a
   **revalidation bracket** — after the wave, at draft-write, and at save, perk re-proves the
   checkout still matches the stamped commit; drift makes the outcome stale/incomplete rather
   than silently auditing moved bytes.
3. **Interpret the outcome.** Every doc gets exactly one final **disposition** from the closed
   set `keep` / `revise` / `merge-into` / `retire`. The two destructive dispositions
   (`merge-into`, `retire`) must clear an explicit **evidence bar** of reducer endorsements
   with no challenge; anything short of that is unresolved disagreement, and the session may
   only **downgrade** a proposal (toward `revise`/`keep`/overflow), never resolve it upward.
   Curation work is ranked **truth first, then leverage** (wrong guidance outranks
   consolidation, routing, and read-cost fixes), and the selection is capped at **≤ 12
   distinct roadmap nodes** — everything else stays ranked in the report's durable overflow,
   alongside any **harvest follow-ups** (report-only code-improvement leads, never roadmap
   work). The session ends in one of three honest terminals: an **incomplete audit** (any wave
   failure or drift — reported, never papered over), a **clean audit** (nothing worth
   selecting — no placeholder objective), or a reviewed **curation objective + dream report**.
4. **Review and approve.** On an actionable audit the objective and its dream report ride the
   review loop as ONE approval bundle — approving the objective approves the report with it.
   The approved bundle saves like any other objective, and the report persists durably as
   companion comments on the objective's report carrier (on Linear also linked in the
   Project's **Resources**) with its id recorded in the objective header — see
   [Objectives](../reference/objectives.md#the-metadata-blocks) and
   [the dream-report companion](../reference/providers-and-backends/issue-backends.md#the-dream-report-companion).
5. **Drive the nodes.** Generate per-node plans with
   [`perk objective plan`](../reference/cli/objective.md#perk-objective-plan-number) and take
   each through the ordinary implement → submit → land spine.

> **Dream vs harvest.** A **dream** is the whole-corpus **inward** audit: it reads
> `docs/learned/` to curate the corpus itself (what to keep, revise, merge, retire). A
> [**harvest**](run-the-learn-harvest-factory.md) is the bounded **outward** mine: it reads
> docs as lenses into the code to curate an improvement objective. Neither edits anything in
> its session — both are objective factories.

## Related

- **Do:** [How to run the learn-harvest factory](run-the-learn-harvest-factory.md) — the
  bounded outward mine over the same corpus.
- **Do:** [How to author an objective roadmap](author-a-roadmap.md) — the hand-authored path to
  the same objective shape.
- **Look up:** [Objectives — the roadmap model](../reference/objectives.md) — what the curated
  objective becomes once saved.
