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

The conflict resolver instead has an unspecified definition mode and is explicitly launched
foreground by both owned dispatch templates, at the actual trusted target cwd. It inherits
project context and skills, not global context; foreground mode does not load ambient extensions.
Missing directory/profile capabilities stop dispatch, never trigger a mode or extension fallback.

Each code-owned report attempt also captures the parent's current read-only gate after skill
preflight and serializes it in the private `perk.parent-restrictions/1` binding. A failed capture
stops before launch. False is not write authority, and full warm-child enforcement requires the
matching strict consumer/floor repair as well as this producer. This is a spawn-time snapshot,
not continuous revocation, an OS sandbox, or a configuration channel for user/manual agents.
Your direct custom calls above are outside that code-owned snapshot guarantee.

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
