# perk customization recipes

Goal-oriented "change perk's behavior" recipes. All config lives in committed `.perk/config.toml` (or
the gitignored `.perk/local.toml` overlay). After a change that converges packages or affects
resolution, run `perk init` to converge and `perk doctor` to validate.

## Attach a skill to a stage or command (`[[bindings]]`)

Bind an installed skill (under `.agents/skills/<name>/SKILL.md`) so its guidance is delivered into
that session.

1. **Pick a trigger** — one `"<kind>:<id>"` string.
   - `stage:<id>` fires at **both** the cold launcher **and** the warm slash-command. Bindable stage
     ids: `gist-author`, `gist-save`, `objective-author`, `objective-save`, `objective-plan`,
     `plan`, `save`, `implement`, `submit`, `address`, `land`, `learn`. Two registry stages are
     deliberately absent: `stack-review` (every door — cold `perk objective stack review`, warm
     `/stack-review-browser` — overrides the binding trigger to `command:stack-review-browser`, so
     a `stage:stack-review` binding validates but never fires; bind the command trigger instead)
     and `audit` (its only door is the dev-only `perk-dev audit judge`, so no consumer-facing door
     delivers it).
   - `command:<id>` binds a command that is **not** a registry stage. These command targets have
     a delivery surface: `objective-reconcile`, `objective-replan`, `replan`, `learn-docs`,
     `learn-code`, `learn-harvest`, `learn-dream`, `pr-review`, `pr-review-terminal`,
     `pr-review-browser`, `stack-review-browser`, `plan-review-browser`,
     `objective-review-browser`, `skills-create`, `skills-refine`. A `command:<id>` outside that
     set validates but **never fires**. When a command is also a registry stage, bind `stage:<id>`.
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
`draft-reviewer`, `harvest-analyst`, `dream-analyst`,
`dream-reducer`, `scout`, plus the dev-only
`session-auditor` — dormant in consumer repos). An absent key uses
the agent's frontmatter default. The `scout` key is the model the `run_scout_wave` tool spawns in
`/plan`, `/objective-plan` and objective-author sessions — one fresh read-only `perk.scout` lane per
self-contained brief (1–6 per call, one attempt; reports are untrusted DATA to verify).

```toml
[models.subagents]
pr-reviewer = "anthropic/claude-sonnet-4-5:high"   # :thinking suffix sets the thinking level
review-classifier = "anthropic/claude-haiku-4-5"
conflict-resolver = "inherit"                      # inherit the parent session's model
```

This has **no effect** on your own custom subagents — they set `model` in frontmatter (see below).

## Configure CI checks (`[ci]` + `[[ci.checks]]`)

Declare named check rows; run them with warm `/ci` for a one-line overall summary or the `run_ci`
tool for the detailed per-check report — `/ready` does not run them (it marks the draft PR ready
and, for a stacked layer, records the handoff stamp; run the checks first). Checks run
concurrently (the detailed report stays in
declared order), so each row must be independently runnable — put an ordered sequence inside one
`command` (e.g. `"build && test"`).

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
`.perk/local.toml`) — **never** committed. Run `perk init` (converges `npm:pi-mono-linear` and
ensures six `perk:*` labels), then `perk doctor --verify`: the current Linear checks cover auth,
team, all six labels, project-scope access, and workflow-state readiness. See the Linear reference
in [providers-and-backends.md](./providers-and-backends.md) (auth header, identifiers, maturity
caveats).

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

**Managed-filter exception:** Perk owns the `npm:@dietrichgebert/ponytail` entry's
`extensions`/`skills`/`prompts`/`themes` filters as `[]`. That package is an installed internal
review-lane context source, not an ambient Pi resource provider. `perk init` preserves the first
object donor's source pin, metadata, and list position, forces all four filters empty, and removes
same-identity duplicates; cold skill exposure also excludes packages whose `skills` key is exactly
`[]`. Do not use `pi config -l` to enable Ponytail resources: exact-path review-agent binding plus
runtime preflight is the only supported exposure. `perk doctor` reports a missing lazy install as
info and incompatible package/skill identity as warn, with a known-good `4.9.0` remediation.

## Change pi-fff's search mode (`PI_FFF_MODE`)

perk borrows `@ff-labs/pi-fff` (FFF-powered fuzzy file/content search) in every repo, and
**perk-launched** sessions run it in its additive mode via an injected `PI_FFF_MODE=tools-and-ui`
env default: FFF's `fffind`/`ffgrep` (pre-indexed, frecency-ranked) sit beside the untouched
builtin `find`/`grep` — the mode warm/bare `pi` sessions already use. The injection is a
*default*, not a pin — your environment wins at both launch paths (local stage launches and the
remote CI worker), so `export PI_FFF_MODE=override` opts into FFF-as-`find`/`grep`. Caveat (a
0.67.x-only hazard, fixed in pi-subagents 0.68.0): the 0.67.x engine intersected a child agent's
declared tools with the tools the **host** reported as builtin-*sourced*, and override mode
re-registers `grep`/`find` under pi-fff's own name — so every `perk.scout`/`perk.*-reviewer` lane
failed at launch and the other report agents silently lost `grep`/`find`. `perk doctor`'s
`subagent-host-tools` check names that state (an exported `override`, or an `override` mode in
the agent dir's `pi-fff.json`, while the installed pi-subagents is in the affected range
`[0.67.0, 0.68.0)`); on 0.68.0+ it reports `ok` with "counts wrapped core slots as host builtins".
Any other valid pi-fff mode works the same way. To drop
the package's resources entirely in one repo, use the `pi config -l` resource-filter lever (see
[Scope pi resources per-project](#scope-pi-resources-per-project-pi-config--l)).

## Keep pi-subagents out of user-scope settings (`subagent-package-scope`)

perk converges `npm:pi-subagents` into the **project** `.pi/settings.json` on purpose: the engine
is a per-repo borrow perk's `perk.*` agent definitions and wave RPC ride on, so it belongs beside
the other project packages `perk init` manages. A second `npm:pi-subagents` in your **user-scope**
pi settings (`settings.json` in the launch-precedence agent dir — `PI_CODING_AGENT_DIR` →
`[pi] agent_dir` → `~/.pi/agent`; typically the result of a global `pi install npm:pi-subagents`)
is harmless to pi's package loading (it dedupes by identity, project wins) but not to perk's waves.
pi 0.85.1 loads the user-scope extensions *before* project trust resolves and then drops the user
copy from the final set **without invalidating it**; pi-subagents' RPC bridge subscribes on
`pi.events`, so the orphan — which never receives `session_start` — keeps answering perk's wave
RPC with `no_active_session` a few milliseconds before the project instance succeeds.

Symptom **before** this fix: every wave launch (`start_draft_review_wave`, `start_review_wave`,
`run_scout_wave`, …) returned `spawn-failed: no_active_session: No active extension context for
subagent RPC` while the wave actually ran orphaned (`collect_*` answered `no_wave`, the browser's
`perk:wave` marker never cleared). **After:** perk holds the context-less reply until the live
reply arrives, the launch succeeds, and the session shows one `perk: waves — A duplicate
pi-subagents extension is loaded …` warning per extension activation. `perk doctor`'s
`subagent-package-scope` check warns when both scopes list the identity (pinned or object-form
entries included) and names both files.

The fix: remove the user-scope entry — `pi remove npm:pi-subagents` when that file is pi's default
`~/.pi/agent/settings.json` (`pi remove` writes user scope by default), otherwise edit the file —
then **restart** every running pi session in this repo. `/reload` is not enough: it re-runs the
same two-phase load and does not clear the orphan. Leave the project entry alone (`perk init`
keeps it converged). Note the perk repo itself never sees this because `[pi] agent_dir =
".pi/agent"` keeps the user-global settings out of play — a repo-local agent dir is another way
to isolate a consumer repo, at the cost of a separate auth/settings store.

## Cheaper prompt caching for review children (`PI_SUBAGENT_CACHE_RETENTION`)

pi-subagents ≥ 0.68.0 reads `PI_SUBAGENT_CACHE_RETENTION` for the prompt-cache retention its
spawned children request, independent of the parent's `PI_CACHE_RETENTION`. perk's review/scout
children are short-lived fresh-context lanes that never benefit from long cache retention, so when
the parent runs with `PI_CACHE_RETENTION=long`, set `PI_SUBAGENT_CACHE_RETENTION=short` in the
environment (your shell profile, or the same place you export `PI_CACHE_RETENTION`) to stop
paying long-retention cache writes for every lane. Environment-only: perk has no knob for it and
injects no default — an unmeasured cost policy stays the operator's call.

## Write a custom subagent (`.pi/agents/<name>.md`)

Distinct from the fixed `[models.subagents]` model-override table. Author your own agent def anywhere under
`.pi/agents/` (perk manages none of that tree — its own `perk.*` defs ship inside the perk extension
package as pi-subagents package agents). The runtime name comes from the **frontmatter** `name` (+
optional `package`); pi-subagents ranks project defs above package defs, so a project def named
`perk.<name>` (`package: perk` + one of perk's names) silently **shadows** perk's shipped def of that
name — never reuse those names. `model` is set in the frontmatter (not in `[models.subagents]`). Invoke it
via pi's native `subagent` tool by its runtime name — `subagent({agent: "my-reviewer",
task: "…"})` (pi-subagents ≥ 0.49 restored native structured single-child execution — a
direct one-child call runs natively, never converted onto the workflow path);
use `workflowScript` for multi-child orchestration or a custom result projection;
`subagent { action: "list" }` still enumerates discovered agents. pi-subagents' **builtin** agents don't appear: perk converges
the constant `"subagents": {"disableBuiltins": true}` into `.pi/settings.json` in every perk repo (engine-only
borrow — perk ships its own `perk.*` agents as package agents). To re-enable one builtin, add a project-settings
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
`scope-pi-resources-per-project`, `switch-to-linear`, `target-a-non-default-base-branch`,
`delegate-an-investigation-to-perk-scout`).*
