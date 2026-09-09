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

The conflict resolver (git-tracked `.pi/agents/perk/conflict-resolver.md`, perk-reconverged) keeps
writer tools and project/skill inheritance. `/submit`/`/address` dispatch it via
`resolve_submit_conflicts`: one code-owned foreground delegation at the worktree cwd, a strict
structured record, one per-worktree execution lock and **no restriction packet** (no read-only
floor). No `subagent` tool → `unavailable`, no lock; an agent-dir `extensions/subagent/config.json`
`worktree` default (read once at activation) other than absent/`false` refuses, naming file,
observation and fix (`false`/delete the key, quit and resume); perk never edits it. Retained
continuation is offer-only; delivery-unconfirmed means stop for human direction. Reload never clears
a retained lock ([recovery](recover-a-dirty-worktree.md#recover-a-retained-submit-conflict-lock)).

Every code-owned report child receives the constant `perk.parent-restrictions/1 = {readOnly: true}`
binding and `worktree: false`. A pi-subagents runner child carrying the packet has an in-memory
read-only floor for its whole activation, even if mode persistence fails; a malformed or
unsupported-version packet fails closed. Your direct custom calls above are outside that channel.

## Scratch guidance and custom-agent limits

A runner child (`PI_SUBAGENT_CHILD=1`) never receives Perk's scratch guidance or provisioning, and
there is no name-based eligibility. Foreground mode does not discover ambient Perk extensions; see
[Agent scratch](../reference/configuration/repository-layout.md#agent-scratch) for the lifecycle.

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
