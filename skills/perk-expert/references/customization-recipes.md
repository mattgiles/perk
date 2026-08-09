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
   - `command:<id>` binds a command that is **not** a registry stage. Nine command targets have a
     delivery surface: `objective-reconcile`, `objective-replan`, `learn-docs`, `learn-code`,
     `pr-review`, `pr-review-terminal`, `pr-review-browser`, `skills-create`,
     `skills-refine`. A `command:<id>` outside those nine validates but **never fires**. When a
     command is also a registry stage, bind `stage:<id>`.
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

Fixed-key table — affects only perk's own agents (`pr-reviewer`, `review-classifier`,
`objective-explorer`, `conflict-resolver`, `learn-analyst`, `adversarial-reviewer`,
`review-angle-selector`, `draft-reviewer`). An absent key uses
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
(reports `plan=… footer=… web=…`). An absent/unknown id falls back to the seam
default (silently / loud-but-non-fatal). The `ask_user_question` questionnaire tool and the todo
checklist overlay are **built-in** (no seam — perk installs
`npm:@juicesharp/rpiv-ask-user-question` and `npm:@juicesharp/rpiv-todo` for every repo). See
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

## Scope pi resources per-project (`pi config -l`)

pi's per-project resource overrides trim a package's extensions/skills/prompts/themes in one repo:
`pi config -l` rewrites a `.pi/settings.json` `packages` entry to **object form**
(`{ "source": "<spec>", "extensions"/"skills"/"prompts"/"themes": [...] }`) or adds `-`/`!`
disable patterns to the top-level override arrays. This is the sanctioned way to disable a
*borrowed*/*provider* package resource per-repo, and it **survives `perk init`**: perk recognizes
package identity in every entry form (no duplicate string append), never writes the top-level
override arrays, and — if perk's own entry was rewritten to object form — keeps its version pin
fresh by reconciling only the entry's `source`, preserving your filter keys byte-for-byte (perk
never *creates* an object-form entry for its own package). **Don't filter perk's own extension
off** (`"extensions": []` on the `@mgiles/perk` entry) — that breaks every interactive stage
session (no stage tools, footer, or gates). `perk doctor`'s report-only `resource-overrides`
check (group `package`) **warns** — never fails, no `--fix` arm — when an override reaches perk's
own resources (an object-form perk entry, or a disable pattern mentioning `@mgiles/perk` / a perk
skill name; a substring heuristic). To undo, re-enable via `pi config -l` or restore the plain
string entry.

## Change pi-fff's search mode (`PI_FFF_MODE`)

perk borrows `@ff-labs/pi-fff` (FFF-powered fuzzy file/content search) in every repo, and
**perk-launched** sessions run it in override mode via an injected `PI_FFF_MODE=override` env
default: the builtin `find`/`grep` become FFF-backed (pre-indexed, frecency-ranked). The
injection is a *default*, not a pin — your environment wins at both launch paths (local stage
launches and the remote CI worker), so `export PI_FFF_MODE=tools-and-ui` restores pi-fff's
additive default (separate `fffind`/`ffgrep` tools beside the untouched builtins; the mode
warm/bare `pi` sessions already use). Any valid pi-fff mode works the same way. To drop the
package's resources entirely in one repo, use the `pi config -l` resource-filter lever (see
[Scope pi resources per-project](#scope-pi-resources-per-project-pi-config--l)).

## Write a custom subagent (`.pi/agents/<name>.md`)

Distinct from the fixed `[models.subagents]` model-override table. Author your own agent def anywhere under
`.pi/agents/` **except** the perk-owned `.pi/agents/perk/` subdir (perk rewrites and prunes that
subdir on every `perk init`). The runtime name comes from the **frontmatter** `name` (+ optional
`package` — perk reserves `package: perk`), and `model` is set there (not in `[models.subagents]`). Invoke it
via pi's native `subagent` tool in `workflowScript` mode by its runtime name — direct
`{agent, task}` execution was removed, so a run is an explicit-return one-child workflowScript
(`return runs.run("main", {agent: "my-reviewer", task: "…"})`); `subagent { action: "list" }`
still enumerates discovered agents. pi-subagents' **builtin** agents don't appear: perk converges
the constant `"subagents": {"disableBuiltins": true}` into `.pi/settings.json` in every perk repo (engine-only
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

## Prefer pi's regular TUI mode (`tuiMode`)

perk seeds `"tuiMode": "fullscreen"` into `.pi/settings.json` — but only when the key is absent
(seeded once, never overwritten). To prefer pi's regular mode, set `"tuiMode": "regular"` in
`.pi/settings.json`; the value survives init/doctor. pi's `/settings` toggle writes the
**global** settings file, which the committed project key overrides — the durable opt-out is the
project key itself.

```json
{ "tuiMode": "regular" }
```

## Read the footer's cache-hit rate; diagnose misses (`showCacheMissNotices`)

The perk footer's `CH<pct>%` segment is the prompt-cache-hit rate of the latest turn (restoring
pi's default-footer display; absent until the session shows cache activity). For per-miss detail,
enable pi's `showCacheMissNotices` setting **per-user** via `/settings` (user scope) — an operator
diagnostic perk deliberately **never converges** into managed repo settings (no init/doctor arm).
Reading the notices: transition misses (stage flips, skill-binding deliveries) are expected and
bounded; idle-gap misses (the provider's ~5-minute cache TTL expiring between turns) are not
perk's doing.

---

*Canonical source: the `docs/user-docs/how-to/` customization & provider guides
(`attach-a-skill-to-a-stage`, `write-a-custom-subagent`, `run-ci-in-session`, `select-a-provider`,
`scope-pi-resources-per-project`, `switch-to-linear`, `target-a-non-default-base-branch`).*
