---
name: perk-learn-dream
description: Auditing the whole learned corpus and curating ONE bounded curation objective + dream report — the perk learn dream factory. Use when running perk learn dream in a perk repo.
stages: []
disable-model-invocation: true
---

# Dreaming over `docs/learned/` (the `perk learn dream` factory)

`perk learn dream` is perk's **whole-corpus curation factory**: it audits every learned doc at one
stamped commit and curates ONE bounded curation objective plus the durable dream report. The flow —
read the manifest, the one `run_dream_wave` call, the uniform incomplete rule, the clean-audit
stop, the review-first authoring loop — is stated in your launch seed; this skill carries the
judgment detail: the closed dispositions, the destructive evidence bar, the ranking, the selection
shape, and the `dream_report` fields. It is a **factory, not a writer**: the corpus is never
edited and no code is changed. Judgment, user interaction, and durable writes stay with **you**
(the parent) — never delegate them.

## The closed dispositions

Every doc gets exactly ONE final disposition from this closed set — no fifth action, no free-form
cleanup:

| disposition | meaning | required result |
|---|---|---|
| `keep` | the doc is true, well-placed, and worth its read cost | no change; `merge_target` null |
| `revise` | the doc earns its place but carries stale/incorrect/bloated content | a bounded rewrite of that doc (named in a unit when selected) |
| `merge-into` | the doc's durable content belongs inside a surviving doc | `merge_target` names the surviving corpus doc; the source is folded in and removed |
| `retire` | the doc's value is gone (superseded, obsolete, wrong) | the doc is removed; anything durable was proven absent or already housed elsewhere |

## The destructive evidence bar + the disagreement rule

`merge-into` and `retire` are **destructive** and eligible only when the reducer stances clear the
bar: an explicit `endorse` from BOTH the `consolidation-preservation` AND the `currency-accuracy`
reducers, and NO `challenge` from ANY reducer (`knowledge-architecture` included). **Silence
counts as non-endorsement** — a missing gate-angle stance blocks eligibility. Anything else is
unresolved disagreement, and you may only **downgrade** — to `revise`, to `keep`, or into overflow
— never resolve upward (`keep → revise` is an escalation and refuses); record the per-row
`fallback_reason` whenever your final disposition differs from the analyst proposal. The bar is
necessary, not sufficient: an eligible destructive proposal may still be downgraded on your
judgment.

## Ranking (truth first, then leverage)

Rank curation work in this fixed priority order:

1. **Incorrect / stale / misleading guidance** — a wrong doc actively damages future sessions.
2. **High-leverage consolidation** that preserves durable content (merges with a clear survivor).
3. **Routing / clustering / boundary improvements** (docs in the wrong cluster, split/join moves).
4. **Read-cost / distillation improvements** (verbosity, copied source, overlong cues).

## Selection

Select **coherent, plan-sized curation units**: a merge source + its surviving target + the
reference repoints it forces are ONE unit, never split; several small same-shaped fixes may bundle
into one unit, and several units may map onto one roadmap node (many-to-one). The cap is **≤ 12
distinct roadmap nodes** across the selected units; everything else stays **ranked in the report's
overflow** — nothing mined is dropped silently. There is no shrink quota: predictions are not
quotas, and a mostly-`keep` audit is a valid outcome.

## Harvest follow-ups

Code-improvement leads the analysts surfaced ride the report's `harvest_followups` — bounded,
**report-only** (no issue is minted), each citing a *surviving* destination (a final-`keep`/
`revise` doc or a cluster named by one). They are never curation-roadmap work and never
learn-code issues; a follow-up pointing at a merged-away or retired doc must be repointed at the
survivor.

## The `dream_report` param fields

The param carries **your decisions only** — the tool injects the trusted context (snapshot
identity, wave coverage, analyst evidence, reducer stances), and validation re-proves coverage,
path-set equality, merge-target survival/acyclicity, and the evidence bar in code:

- `rows` — one per corpus doc: `path`, `disposition`, `merge_target` (non-null iff `merge-into`),
  `rationale`, `fallback_reason` (non-null iff your final differs from the analyst proposal);
- `uncertainties` — your open questions (analyst/reducer uncertainties are injected);
- `selected_units` — ranked units `{title, docs, rationale, roadmap_node}` (the node mapping may
  be many-to-one; ≤ 12 distinct nodes);
- `overflow_units` — the ranked remainder `{title, docs, rationale}` (no node);
- `harvest_followups` — `{title, pointer, evidence, destination}` per the section above;
- `predicted_effects` — `docs_after`/`bytes_after` (+ optional `note`); type sanity only.

## Boundaries

- **No corpus edits, no code work.** Every disposition lands as objective roadmap work executed
  later — this session changes nothing.
- **No partial dreams.** There is no `--from`; a bounded partial mine is `perk learn harvest`.
- **One open dream objective per repo** — the door's origin guard refuses a second while one is
  open; finish or close it first.
- Objective prose/roadmap craft is the `perk-objective-author` skill (read
  `.agents/skills/perk-objective-author/SKILL.md` — it is prompt-hidden).
