# How to write a custom subagent

Author your own agent definition so you can delegate work to a purpose-built subagent — invoked via
pi's native `subagent` tool, with its own model, tools, and system prompt.

**Background:** pi-subagents discovers **project agents** by walking your repo's `.pi/agents/`
directory **recursively**. perk delivers its own six agents (`pr-reviewer`, `review-classifier`,
`objective-explorer`, `conflict-resolver`, `learn-analyst`, `guest-reviewer`) into the perk-managed
**`.pi/agents/perk/`** subdir. perk owns that subdir
exclusively — `perk init` rewrites it byte-for-byte and **prunes any file you add there**, so never
edit or place files under `.pi/agents/perk/`. Your custom agents live **anywhere else** under
`.pi/agents/` (top-level or any non-`perk/` subdir).

perk also **disables pi-subagents' builtin agents** (context-builder, delegate, oracle, planner,
researcher, reviewer, scout, worker) in every perk repo, via the managed
`"subagents": {"disableBuiltins": true}` key in `.pi/settings.json` — perk borrows pi-subagents as
the delegation engine only and ships its own agents, so the builtins would just be noise in agent
discovery. To re-enable one builtin, add a **project-settings** per-agent override to
`.pi/settings.json`:

```json
"subagents": {
  "disableBuiltins": true,
  "agentOverrides": { "oracle": { "disabled": false } }
}
```

The override survives `perk init` / `perk doctor --fix` (perk owns only the `disableBuiltins` key —
sibling keys are preserved). A **user-global** (`~/.pi/agent/settings.json`) re-enable does *not*
work: pi-subagents checks the project bulk-disable before user-scope overrides.

## Steps

1. **Create the agent file** at `.pi/agents/<name>.md` (or under any subdir other than `perk/`,
   e.g. `.pi/agents/mine/<name>.md`). The runtime name comes from the **frontmatter**, not the path.

2. **Write the frontmatter.** The common fields:

   ```markdown
   ---
   name: my-reviewer
   description: One-line summary of what this agent does and when to use it.
   model: anthropic/claude-sonnet-4-5
   fallbackModels:
     - anthropic/claude-haiku-4-5
   tools: read, grep, find, ls, bash
   systemPromptMode: replace
   inheritProjectContext: true
   inheritSkills: false
   ---

   The system prompt body goes here — the role, the task framing, and any
   constraints the agent must follow.
   ```

   - `name` (+ optional `package`) sets the runtime name (`<package>.<name>`, or just `<name>` with
     no package). Omit `package` for your own agents — perk reserves `package: perk`.
   - `model` is the **only** place to set your agent's model. perk's `[models.subagents]` config table is
     fixed-key (it configures only perk's own six agents) and has no effect on your agents.
   - `tools` is a comma-separated allowlist; `systemPromptMode`, `inheritProjectContext`, and
     `inheritSkills` control prompt composition.

3. **Invoke it** via pi's native `subagent` tool — by the runtime name from your frontmatter (e.g.
   `my-reviewer`). The tool's `task` parameter carries the work.

4. **Verify discovery (optional).** `subagent` with `{ action: "list" }` enumerates the executable
   project agents pi found, including your new one alongside the `perk.*` agents. pi-subagents'
   builtins don't appear (perk disables them — see Background); the `/agents` TUI manager still
   lists them as *disabled*, and a per-agent `agentOverrides` re-enable brings one back.

## See also

- [Configuration reference — `[models.subagents]`](../reference/configuration.md#modelssubagents) — the fixed-key
  model-override table for perk's own six agents.
- The [`pi-subagents` skill](../../../.pi/npm/node_modules/pi-subagents/skills/pi-subagents/SKILL.md)
  — delegation patterns for the `subagent` tool.

---

← Back to the [how-to router](index.md).
