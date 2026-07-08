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
   - `command:<id>` binds a command that is **not** a registry stage. Eight command targets have a
     delivery surface: `objective-reconcile`, `objective-replan`, `learn-docs`, `learn-code`,
     `pr-review`, `review`, `skills-create`, `skills-refine`. A `command:<id>` outside those eight
     validates but **never fires**. When a command is also a registry stage, bind `stage:<id>`.
2. **Choose `nudge` or `transclude`** (`mode`).
   - `nudge` — a short pointer (``Follow the `<skill>` skill (read
     `.agents/skills/<skill>/SKILL.md`).``). The pointer carries the skill's read path, so it works
     even for a skill hidden from the ambient system prompt via `disable-model-invocation: true`
     frontmatter (the recipe perk's own workflow `perk-*` skills use — hidden ambiently, delivered
     per-door; the file stays on disk and `/skill:<name>` keeps working).
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

## Set a repo default model (`[models]`)

One key instead of N `[models.stages.<id>]` entries — converged into the committed
`.pi/settings.json` (`defaultProvider`/`defaultModel`/`defaultThinkingLevel`), which pi reads
natively: perk cold doors, plain `pi`, and the headless worker (local + remote) all pick it up.
Re-run `perk init` (or `perk doctor --fix`) after editing to re-converge.

```toml
[models]
default = "anthropic/claude-opus-4-1"   # exact provider/id; "provider/id:high" also works
thinking = "high"                     # explicit key wins over a :thinking suffix
```

Per-door overrides win: `[models.stages.<id>]`, then an explicit `perk <stage> --model X` on
top. Committed-only (a `local.toml` `[models]` `default`/`thinking` is ignored); it never applies
to perk's subagents (frontmatter/`[models.subagents]` own those).

## Override a subagent model (`[models.subagents]`)

Fixed-key table — affects only perk's own six agents (`pr-reviewer`, `review-classifier`,
`objective-explorer`, `conflict-resolver`, `learn-analyst`, `guest-reviewer`). An absent key uses
the agent's frontmatter default.

```toml
[models.subagents]
pr-reviewer = "anthropic/claude-sonnet-4-5:high"   # :thinking suffix sets the thinking level
review-classifier = "anthropic/claude-haiku-4-5"
conflict-resolver = "inherit"                      # inherit the parent session's model
```

This has **no effect** on your own custom subagents — they set `model` in frontmatter (see below).

## Configure CI checks (`[ci]` + `[[ci.checks]]`)

Declare named check rows; run them with warm `/ci` (or the `run_ci` tool), and they run
automatically at `/ready`.

```toml
[ci]
trusted = true       # native boolean — run checks without a per-session confirm (incl. headless)

[[ci.checks]]
name = "lint"
command = "just lint"
glob = "*.py,*.ts"   # change-scoped: skipped run-all when no matching changed file

[[ci.checks]]
name = "test"
command = "just test"
```

## Select a provider (`[providers]`)

Point a seam at a supported provider id, then converge + validate.

```toml
[providers]
plan = "plannotator-plan"
footer = "pi-default"
```

Run `perk init` (converges the foreign npm package into `.pi/settings.json`) and `perk doctor`
(reports `plan=… todo=… askuser=… footer=… web=… review=…`). An absent/unknown id falls back to the seam
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

Distinct from the fixed `[models.subagents]` model-override table. Author your own agent def anywhere under
`.pi/agents/` **except** the perk-owned `.pi/agents/perk/` subdir (perk rewrites and prunes that
subdir on every `perk init`). The runtime name comes from the **frontmatter** `name` (+ optional
`package` — perk reserves `package: perk`), and `model` is set there (not in `[models.subagents]`). Invoke it
via pi's native `subagent` tool by its runtime name; `subagent { action: "list" }` enumerates
discovered agents. pi-subagents' **builtin** agents don't appear: perk converges the constant
`"subagents": {"disableBuiltins": true}` into `.pi/settings.json` in every perk repo (engine-only
borrow — perk ships its own `perk.*` agents). To re-enable one builtin, add a project-settings
per-agent `"subagents": {"agentOverrides": {"<name>": {"disabled": false}}}` entry; it survives
init/doctor (perk owns only the `disableBuiltins` key). A user-global re-enable does not work.

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
