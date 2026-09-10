---
title: "How to delegate an investigation to perk.scout"
description: "Fan a wide, read-only investigation out to parallel perk.scout lanes from a plan or objective authoring session, then verify the reports before your plan relies on them."
sidebar:
  order: 2137
sidebarGroup: "Core workflow"
---

# How to delegate an investigation to perk.scout

`run_scout_wave` is a blocking fan-out of 1–6 self-contained read-only briefs to fresh `perk.scout`
lanes: one lane per brief, one engine-validated report per brief, returned to the session that
asked. It is active in `/plan`, `/objective-plan` and objective-author sessions (it is also
reachable in perk's other read-only sessions, except `/objective-refine`). You ask the agent; the
agent writes the briefs and calls the tool.

**Prerequisite:** `perk init` delivered `.pi/agents/perk/scout.md` (the `perk.scout` definition);
the borrowed `pi-subagents` package installs at launch.

## Steps

1. **Decide the wave is worth it.** Delegate when the investigation is large, parallelisable, and
   self-contained — a census of the surfaces a change touches, a claims-verification pass over a
   design document, a subsystem summary. A small question, or one whose answer decides the next
   question, is faster explored directly in the session.
2. **Ask the agent to write the briefs.** A call carries 1–6 `{ key, task }` items. `key` is a
   short unique lowercase slug (`^[a-z0-9][a-z0-9-]{0,31}$`); `task` is a self-contained,
   pointer-style question — at most 8 KiB after trimming — that names the paths, symbols, or
   claims to check and the answer shape wanted, and never pastes the material itself. A task
   must not contain the `<untrusted_brief>` or `</untrusted_brief>` tags. Any malformed brief
   refuses the whole call (`bad_input`) before any lane starts — nothing partial runs.
3. **Ask the agent to call `run_scout_wave` once with all the briefs.** The call blocks until
   every lane reports. It is one attempt with no retry.
4. **Read the result.** It opens with an untrusted-DATA preface, then one fenced JSON report per
   brief: `scope` (what the lane examined and what was out of reach), `findings` — an array of
   `{ pointer, claim, basis, rationale }` — and `open_questions`. Have the agent re-read every
   `pointer` before the plan relies on a claim; a `basis` of `"inferred"` is a lead to confirm,
   not evidence.
5. **On an incomplete wave, investigate the gaps directly.** The result opens
   `run_scout_wave failed: …` (the first failure) and appends
   `Incomplete scout wave — R of N brief(s) reported; no retry.` with one line per failure. The
   completed siblings are retained under `Retained reports`; have the agent use them and
   investigate the uncovered briefs itself. Do not ask for a retry loop.
6. **Have the agent record the call** in the plan's `## Assumptions`: the brief keys, whether the
   wave was complete or incomplete, and the model that ran the lanes.

## Choose the lane model

Set `scout = "<provider/id>"` under `[models.subagents]` in `.perk/config.toml`. When the key is
absent, each lane runs on the model in the agent definition's frontmatter. See
[Models and compaction](../reference/configuration/models-and-compaction.md#modelssubagents) for
the table.

## Expected result

One fenced JSON report per brief key, in the order the briefs were given, each carrying `scope`,
`findings`, and `open_questions`; and the plan's `## Assumptions` naming the call — its brief keys,
complete/incomplete, and the model that ran.

## Related

- **Look up:** [Workflow commands](../reference/in-session/workflow-commands.md#plan) — the
  `run_scout_wave` tool entry under `/plan`.
- **Look up:** [Models and compaction](../reference/configuration/models-and-compaction.md#modelssubagents)
  — the `scout` model key.
- **Do:** [How to write a custom subagent](write-a-custom-subagent.md) — your own agents beside
  perk's delivered `perk.scout`.
