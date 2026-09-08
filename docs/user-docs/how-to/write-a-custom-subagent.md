---
title: "How to write a custom subagent"
description: "Author your own agent definition and delegate work to a purpose-built subagent with its own model, tools, and prompt."
sidebar:
  order: 2280
sidebarGroup: "Customization"
---

# How to write a custom subagent

Add one project agent and run it directly through the `subagent` tool.

## Steps

1. **Choose a user-owned path.** Project agents are discovered recursively under `.pi/agents/`, so
   create `.pi/agents/<my-specialist>.md` or place the file in your own nested directory. Do not use
   `.pi/agents/perk/`: perk owns only that subtree, converges its managed `perk.*` definitions there, and
   prunes foreign files from it.
2. **Write a minimal agent definition.** The frontmatter `name` is its runtime name; the body is its
   system prompt.

   ```markdown
   ---
   name: my-specialist
   description: Reviews one module for concrete correctness risks.
   tools: read, grep, find
   ---

   Inspect only the module named in the task. Return concise findings with file and line
   references. Do not edit files.
   ```

3. **List before executing.** Ask the management surface what is currently executable and confirm
   that `my-specialist` appears:

   ```js
   subagent({ action: "list" })
   ```

4. **Run one child directly.** Pass the agent's runtime name and the task:

   ```js
   subagent({ agent: "my-specialist", task: "Review src/payments.ts" })
   ```

   pi-subagents runs a direct one-child call natively (structured single-child execution); use
   `workflowScript` when you need multi-child orchestration or a custom result projection.

## Perk-owned profiles

Perk's code-owned report waves use background children selected by `async: true` in their
managed definitions (and in the repo-local session auditor). Child calls deliberately omit
`async` so native workflow awaiting still collects their reports. Reports replace the base
prompt, inherit neither global/project context nor discovered skills, and omit extension lists
so runner ambient discovery remains available. Explicit source-bound Ponytail assignment skills
are separate from discovered-skill inheritance. Models and ordered fallbacks are unchanged.

Report profiles also declare `completionGuard: false`. This is **report-only completion**, and it
is separate from acceptance: the wave already disables pi-subagents' acceptance contract, while
this field disables the engine's completion *mutation* guard — the check that fails a child for
finishing "without making edits" when its task text reads like an implementation request. A
reviewer's task quotes the reviewed document verbatim, so a draft saying "… must change …" used
to fail every lane after it had submitted its findings. With the field set, a report lane
completes on its validated `structured_output` report and its findings are retained. Three things
do not change: the report contract (a lane that never calls `structured_output`, or calls it with
a schema-invalid report, still fails), the read-only enforcement (inspection `bash` remains
available; not editing is Perk's restrictions and the rubric's job, never the guard's), and
coverage (a failed lane is uncovered — `collect_*` reports it as incomplete, its provisional
annotations are cleared rather than finalized, and a failed lane is never a clean review). Your
own custom agents keep the engine default; an agent override that re-enables the guard on a Perk
report profile reintroduces the failure and is a documented compatibility limit.

The conflict resolver keeps an unspecified definition mode and inherits project context and
skills, not global context; foreground mode does not load ambient extensions. Submit/address
uses `resolve_submit_conflicts`: a single-use authorized, code-owned native foreground delegation
at the trusted worktree cwd, with a strict structured terminal record and a persistent worktree-wide
execution lock. The bridge disables acceptance; receipts do not invent artifact paths or expose
child output. Native `worktree: true` allocation defaults are incompatible: inspect
`extensions/subagent/config.json` under Pi's agent directory, correct the setting and reload.
Reload does not clear a retained lock; use [human-only recovery](recover-a-dirty-worktree.md#recover-a-retained-submit-conflict-lock).
Retained continuation uses the same code-owned foreground adapter, directly awaited inside
`objective_stack_sync`, with a distinct retained schema and activation-local authorization. Its
sentinel is code-built child task data, not parent-authored launch guidance. The lock is acquired
at the retained worktree; the independent manifest-side session claim persists across outcomes.
Missing target directory/profile capabilities stop dispatch without repairing wiring, copying a
handoff, or changing mode/extensions. Retained `continuation-ready` permits only a post-result
offer and new human approval before canonical continuation, never push/abort authority. A
follow-up delivery-unconfirmed diagnostic preserves the result and means stop for human direction.

Each code-owned report attempt also captures the parent's current read-only gate after skill
preflight and serializes it in the private `perk.parent-restrictions/1` binding. A failed capture
stops before launch. The matching runner consumer is implemented: true or invalid packets impose
an in-memory read-only floor before lifecycle work, even if mode persistence fails. False is not
write authority; existing read-only mode still applies. Both halves are required. This is a
spawn-time snapshot, not continuous revocation, an OS sandbox, or a configuration channel for
user/manual agents. Your direct custom calls above are outside that code-owned snapshot guarantee.

## Scratch guidance and custom-agent limits

When Perk is active and the effective gate is off, a valid custom/unknown native startup-prefix
name remains scratch-eligible. An unavailable prefix (absent, malformed, unreadable or stale) in
a runner-hosted child suppresses scratch with a bounded warning; without the runner bit it retains
the parent/unidentified-foreground fallback. Append-mode custom prompts without a first-line
marker can take the unavailable runner row. Legacy environment names or binding-only name claims
cannot supply identity. Do not use a forged report/writer prefix as a permission mechanism: the
claim affects only scratch guidance/provisioning, never tools, workflow mode, stage or handoff.

Foreground mode does not discover ambient Perk extensions. The unavailable non-runner fallback
is a negative boundary, not proof of foreground enforcement or guaranteed scratch provisioning.
Do not add an explicit Perk extension list or switch execution modes merely to make a failing
profile pass. See [Agent scratch](../reference/configuration/repository-layout.md#agent-scratch)
for the exact report set and directory lifecycle.

## Builtins in a perk repo

pi-subagents currently ships `delegate`, `oracle`, `researcher`, `reviewer`, `scout`, and `worker`.
perk converges `subagents.disableBuiltins: true`, so those builtins are disabled by default in a
perk-managed project. To re-enable one, add a project-level
`subagents.agentOverrides.<name>.disabled = false` override in `.pi/settings.json`. A user-global
override cannot defeat the project's bulk disable; project settings have the required precedence.
perk preserves sibling user-owned `subagents` settings when it reconverges its one managed key.

## Expected result

`subagent({ action: "list" })` reports the project agent as executable, and the run returns that
agent's focused review output.

## Related

- **Look up:** [pi-subagents authoring and workflow guidance](https://github.com/nicobailon/pi-subagents/blob/main/skills/pi-subagents/SKILL.md)
  — current agent and workflow guidance.
- **Look up:** [`[models.subagents]`](../reference/configuration/models-and-compaction.md#modelssubagents) — perk-owned
  agent model configuration and builtin override rules.
