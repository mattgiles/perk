# perk customization recipes

Goal-oriented "change perk's behavior" recipes. All config lives in committed `.perk/config.toml` (or
the gitignored `.perk/local.toml` overlay). After a change that converges packages or affects
resolution, run `perk init` to converge and `perk doctor` to validate.

## Attach a skill to a stage or command (`[[bindings]]`)

Bind an installed skill (under `.agents/skills/<name>/SKILL.md`) so its guidance is delivered into
that session.

1. **Pick a trigger** — one `"<kind>:<id>"` string.
   - `stage:<id>` fires at **both** the cold launcher **and** the warm slash-command. Bindable stage
     ids: `objective-author`, `objective-save`, `objective-plan`, `plan`, `save`, `implement`,
     `submit`, `address`, `land`, `learn`.
   - `command:<id>` binds a command that is **not** a registry stage. Only three command targets have
     a delivery surface: `objective-reconcile`, `learn-docs`, `pr-review`. A `command:<id>` outside
     those three validates but **never fires**. When a command is also a registry stage, bind
     `stage:<id>`.
2. **Choose `nudge` or `transclude`** (`mode`).
   - `nudge` — a short pointer (``Follow the `<skill>` skill.``); relies on the skill being installed
     and Pi-discoverable.
   - `transclude` — inlines the full `SKILL.md` body (heavier, guaranteed present).
3. **Add a row.** A row at a trigger perk does **not** already bind is **appended**:

   ```toml
   [[bindings]]
   trigger = "stage:submit"
   skill = "house-style"
   mode = "nudge"
   ```

4. **Override a default.** A row at a trigger perk **already** binds **replaces** perk's default
   there (e.g. rebind `stage:plan` from the default `perk-plan` nudge to your own skill, or switch a
   default to `transclude`).
5. **Validate** with `perk doctor` — it checks each binding's skill is installed and its trigger
   target exists; problems degrade **loud-but-non-fatal** at delivery.

**Overlay caveat:** a local `[[bindings]]` array **replaces the committed array wholesale** — include
every binding you want active, not just additions.

## Override a subagent model (`[subagents]`)

Fixed-key table — affects only perk's own four agents (`pr-reviewer`, `review-classifier`,
`objective-explorer`, `conflict-resolver`). An absent key uses the agent's frontmatter default.

```toml
[subagents]
pr-reviewer = "anthropic/claude-sonnet-4-5"
review-classifier = "anthropic/claude-haiku-4-5"
```

This has **no effect** on your own custom subagents — they set `model` in frontmatter (see below).

## Configure CI checks (`[[ci]]` + `[trust] ci`)

Declare named check rows; run them with warm `/ci` (or the `run_ci` tool), and they run
automatically at `/ready`.

```toml
[[ci]]
name = "lint"
command = "just lint"
glob = "*.py,*.ts"   # change-scoped: skipped run-all when no matching changed file

[[ci]]
name = "test"
command = "just test"

[trust]
ci = "true"          # quoted string — run checks without a per-session confirm (incl. headless)
```

## Select a provider (`[providers]`)

Point a seam at a supported provider id, then converge + validate.

```toml
[providers]
plan = "plannotator-plan"
footer = "pi-default"
```

Run `perk init` (converges the foreign npm package into `.pi/settings.json`) and `perk doctor`
(reports `plan=… todo=… askuser=… footer=… web=…`). An absent/unknown id falls back to the seam
default (silently / loud-but-non-fatal). See
[providers-and-backends.md](./providers-and-backends.md) for the supported set and postures.

## Switch the issue backend to Linear (`[issues]`)

```toml
[issues]
backend = "linear"
team = "ENG"        # the Linear team KEY, required
```

Set `LINEAR_API_KEY` in the environment (or `[linear] api_key` in the gitignored
`.perk/local.toml`) — **never** committed. Run `perk init` (converges `npm:pi-mono-linear`,
ensures the four `perk:*` labels) and `perk doctor --verify` (the network probes). See the Linear
reference in [providers-and-backends.md](./providers-and-backends.md) (auth header, identifiers,
maturity caveats).

## Target a non-default base branch (`[workflow] base`)

Precedence: **the objective's own base → `[workflow] base` → the GitHub default branch.** Pinned at
save time (a later config change never retargets an already-saved plan/objective).

```toml
[workflow]
base = "develop"   # repo-wide default for standalone plans + objectives that don't override
```

Per-objective: `perk objective create --base develop` (every node plan inherits it), or pass `base`
to the `objective_draft` / `objective_save` tools in a read-only authoring session.

At land, a non-default base makes perk close the plan issue explicitly (GitHub's `Closes #N`
autoclose only fires on the default branch); default-base lands rely on GitHub's autoclose.

## Write a custom subagent (`.pi/agents/<name>.md`)

Distinct from the fixed `[subagents]` model-override table. Author your own agent def anywhere under
`.pi/agents/` **except** the perk-owned `.pi/agents/perk/` subdir (perk rewrites and prunes that
subdir on every `perk init`). The runtime name comes from the **frontmatter** `name` (+ optional
`package` — perk reserves `package: perk`), and `model` is set there (not in `[subagents]`). Invoke it
via pi's native `subagent` tool by its runtime name; `subagent { action: "list" }` enumerates
discovered agents.

```markdown
---
name: my-reviewer
description: One-line summary of what this agent does and when to use it.
model: anthropic/claude-sonnet-4-5
tools: read, grep, find, ls, bash
---

The system prompt body — role, task framing, constraints.
```

---

*Canonical source: the `docs/user-docs/how-to/` customization & provider guides
(`attach-a-skill-to-a-stage`, `write-a-custom-subagent`, `run-ci-in-session`, `select-a-provider`,
`switch-to-linear`, `target-a-non-default-base-branch`).*
