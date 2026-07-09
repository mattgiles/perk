# perk configuration (`.perk/config.toml`)

perk reads two files under `.perk/`:

- **`.perk/config.toml`** — the committed project config, shared by everyone in the repo. It is
  also perk's repo **initialization marker**.
- **`.perk/local.toml`** — a per-user, **gitignored** overlay for personal overrides.

`perk init` scaffolds both with a commented template; `perk doctor` validates them.

> **Migrating from `.pi/perk.toml`.** perk's config used to live at `.pi/perk.toml` /
> `.pi/perk.local.toml`. A repo carrying only the legacy committed file makes `perk init` **refuse**
> (with a `perk doctor --fix` remediation) rather than re-scaffold over it. `perk doctor --fix`
> migrates the config to `.perk/` secret-safely (the gitignored secret moves to `.perk/local.toml`
> and is never promoted into the committed file); then re-run `perk init`.

> **Breaking: config schema v2.** No migration tooling, no dual-read — pre-v2 spellings hard-fail
> every `perk` command with a pointer to the new home. Rename map: `[stages.<id>]` →
> `[models.stages.<id>]` · `[subagents]` → `[models.subagents]` · `[models] model` →
> `[models] default` · `[[ci]]` → `[[ci.checks]]` · `[trust] ci = "true"` → `[ci] trusted = true` ·
> `[objective] compact_threshold = "0.8"` → `[compaction] objective_threshold = 0.8`.

## Overlay semantics

1. `.perk/local.toml` overlays `.perk/config.toml` — **local wins.** Tables merge recursively;
   scalar leaves replace.
2. A local `[[bindings]]` / `[[ci.checks]]` array **replaces the committed array wholesale**
   (arrays are leaves — not element-wise merged). Include every row you want active, not just
   additions.
3. **The overlay rule, once:** keys perk **converges into committed artifacts** ignore the
   overlay — `[models]` `default`/`thinking`, `[compaction]`'s settings keys, and `[issues]` are
   read from `.perk/config.toml` **only** (keeps the canonical issue store and the converged
   `.pi/settings.json` deterministic). Keys **read at runtime** honor it — `[models.stages.<id>]`,
   `[models.subagents]`, `[ci]`, `[compaction] objective_threshold`, `[workflow]`, `[worktree]`,
   `[providers]`, `[skills]`, `[[bindings]]`.

## Repository layout — the dot-directory contract

**Ownership vs. discovery.** `.perk/` is the authoritative, **perk-owned** dot-directory (committed
source + local cache). `.pi/` and `.agents/` are **discovery** namespaces owned by Pi and the skills
CLI; perk writes a few **generated materializations** into them because that is where the host tool
looks. `.pi/` is **not** generally perk-owned — it is Pi's directory with a perk-managed slice.

| Path | Owner | Lifecycle | Versioned |
| --- | --- | --- | --- |
| `.perk/config.toml` | maintainer / perk (init marker) | committed | yes |
| `.perk/local.toml` | user | gitignored | no |
| `.perk/workflow/` | perk | gitignored (runtime cache) | no |
| `.perk/skills/<name>/SKILL.md` | maintainer / perk | committed | yes |
| `.perk/required-perk-version` | perk-generated (`perk init` / `doctor --fix`) | committed | yes |
| `.perk/managed-state.toml` | perk-generated (`perk init` / `doctor --fix`) | committed | yes |
| `.pi/settings.json` | Pi (perk-managed slice) | committed | yes |
| `.pi/npm/`, `.pi/git/` | Pi | gitignored | no |
| `.pi/agents/perk/*.md` | perk-generated (Pi materialization) | committed | yes |
| `.pi/APPEND_SYSTEM.md` | perk-generated (committed ambient index) | committed | yes |
| `.agents/manifest.yaml` | user / skills CLI | committed | yes |
| `.agents/manifest.d/perk*.yaml` | perk-generated (skills materialization) | committed | yes |
| `.agents/skills/`, `.agents/cache/` | skills CLI (runtime) | gitignored | no |
| `.worktrees/` | perk (worktrees) | gitignored | no |
| `.pi-subagents/` | pi-subagents (borrowed engine, runtime) | gitignored | no |

**One perk-owned path lives *outside* the repo.** `~/.perk/last-seen-version` is the user-level,
machine-local store behind the one-line post-upgrade notice (the `perk release-notes` pointer):
the max perk version this user has run interactively. Self-healing (missing/garbled content is
silently re-recorded) and safe to delete; no doctor check or init convergence touches it.

**Pi-native materializations.** `.pi/APPEND_SYSTEM.md` (generated ambient routing index) and
`.pi/agents/perk/` (perk's slice of Pi's project-agent namespace) are perk-generated and committed,
but they live where Pi discovers them — not evidence that `.pi/` is perk-owned.

## Value types

Types are **honest** (config schema v2): booleans are native booleans (`trusted = true`), numbers
are native numbers (`objective_threshold = 0.8`, `reserve_tokens = 16384`). The old
quoted-string-for-TS-read-keys rule is dead — a quoted `"true"` no longer grants trust and a
quoted `"0.8"` threshold is ignored.

Python-read keys are **validated at load**: an ill-typed value (e.g. `base = 7` under `[workflow]`)
fails `perk` commands with a field-path error (`workflow.base: Input should be a valid string`), and
`perk doctor` pinpoints the bad field in its `config` check. (Previously such values were silently
ignored.) The `[compaction]` integers must be **positive** native ints — a quoted numeric string
(`"16384"`) is accepted by coercion, but a bare bool (`reserve_tokens = true`) is rejected.
**Legacy spellings hard-fail:** a pre-v2 table (`[trust]`, `[objective]`, `[subagents]`,
`[stages.<id>]`, `[[ci]]`, or a `[models] model` key) raises a config error naming its new home
rather than being silently dropped.

## Tables

### `[worktree]`

Where `perk worktree create` and the cold-door launchers place worktrees.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `root` | string | `.worktrees` | Relative resolves against repo root; absolute used as-is. |
| `setup` | array of strings | _(none)_ | Shell commands run via `bash -lc`, in order, inside each **freshly created** worktree before `pi` starts. A non-zero exit / timeout / missing `bash` **aborts the launch**. Command output is captured and shown only on failure. Skipped on resume/reuse, dry-runs, and the remote runner. Overlay-aware (a local `setup` replaces this one wholesale). |

```toml
[worktree]
root = ".worktrees"
setup = ["uv sync"]
```

### `[workflow]`

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `plan_authoring` | string | _(none)_ | Appended into the plan-authoring context injection in `plan` sessions. |
| `base` | string | _(GitHub default branch)_ | Default target branch plans/objectives base off and target. An objective's own `--base` wins. **Pinned at save time.** |

```toml
[workflow]
plan_authoring = "Prefer the smallest diff that satisfies the acceptance criteria."
base = "develop"
```

### `[ci]`

How work is verified — and whether it's trusted (the policy key sits above the checks it
green-lights).

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `trusted` | bool | _(unset ⇒ untrusted)_ | `true` (a **native boolean**) marks the `[[ci.checks]]` below trusted — they run without a per-session confirm (including headless). A quoted `"true"` does **not** grant trust. |

#### `[[ci.checks]]`

Array-of-tables; each row is one check. Consumed by the in-session CI executor (warm `/ci` + the
`run_ci` tool) and run at `/ready`. Declared order preserved.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `name` | string | _(required)_ | Check name (selected by `/ci <name>`). |
| `command` | string | _(required)_ | The shell command to run. |
| `glob` | string | _(unset)_ | Comma-separated patterns (e.g. `"*.ts,*.tsx"`). When set, the check is **skipped** on the run-all path if no changed file (vs trunk) matches; unset ⇒ always runs. |

**Change-scoped gating** applies only when running **all** checks: a `glob` check runs only if a
changed file (merge-base vs trunk, plus untracked) matches. A pattern with no `/` matches a
basename at any depth (`*.py` gates any `.py`); `**` crosses dirs, `*` matches one segment. An
explicit `/ci <name>` always runs; any git error **fails open** (all checks run).

```toml
[ci]
trusted = true

[[ci.checks]]
name = "lint"
command = "just lint"
glob = "*.py,*.ts"

[[ci.checks]]
name = "test"
command = "just test"
```

### `[providers]`

Per-seam provider selection — provider-id strings into perk's supported set. An absent key falls
back to the behavior-preserving default.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `plan` | string | `perk-plan` | Plan-authoring provider. |
| `todo` | string | `perk-checkpoints` | Checkpoint/todo provider. |
| `askuser` | string | `perk-ask-user` | `ask_user_question` tool provider. |
| `footer` | string | `perk-footer` | Footer provider. |
| `web` | string | `pi-web-access` | Web search/fetch provider. |
| `review` | string | `hunk` | Code-review surface the `/review` door drives (selectable: `plannotator-review` — the browser arm; both arms are live). |

```toml
[providers]
plan = "perk-plan"
todo = "perk-checkpoints"
askuser = "perk-ask-user"
footer = "perk-footer"
web = "pi-web-access"
review = "hunk"
```

The supported set, postures, and selection mechanics are in
[providers-and-backends.md](./providers-and-backends.md).

### `[issues]`

Where canonical plan / learn / objective issues live. **Committed-only** (overlay ignored).

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `backend` | string | `github` | `"github"` or `"linear"`. |
| `team` | string | _(none)_ | Linear team **key** (e.g. `"ENG"`); required when `backend = "linear"`. |

Linear also requires a personal `LINEAR_API_KEY` (env var or `[linear] api_key` below) — never in
this committed file.

```toml
[issues]
backend = "linear"
team = "ENG"
```

### `[linear]`

A personal Linear API key for perk's Linear backend **and** the in-session `linear_*` tools.
**Gitignored-local-only** — read from `.perk/local.toml`, never the committed file.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `api_key` | string | _(none)_ | A personal Linear API key. |

An exported `LINEAR_API_KEY` env var **wins** over this (config is the fallback). When set here, perk
seeds the launched session's environment with the key so worktree tools/workers inherit it (the file
is gitignored, never copied into a worktree). perk also reads this key directly from the **main
checkout's** `.perk/local.toml` whenever a command runs inside a linked worktree (`/submit`,
`/land`, …), so a single entry in the main checkout authenticates every worktree session and
cold-door even when the env-seed did not fire. Malformed local TOML is ignored (fail-soft).

```toml
# .perk/local.toml (gitignored)
[linear]
api_key = "lin_api_…"
```

### `[models]`

Which AI runs where — one namespace: the repo-default `default`/`thinking` keys plus the
`[models.stages.<id>]` and `[models.subagents]` sub-tables (precedence is visible as nesting).

The **repo-default model + thinking level** (`default` + `thinking`) is converged by `perk init` /
`perk doctor --fix` into `.pi/settings.json`'s top-level `defaultProvider` / `defaultModel` /
`defaultThinkingLevel` keys, which pi reads natively at session boot. Applies to **every** pi
session in the repo: perk cold doors, plain `pi`, and the headless worker (local **and** remote —
the worker resolves its model from the checkout's disk-layered settings, so this is how you
configure the worker's model).

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `default` | string (`provider/id`) | _(pi default)_ | Must be an **exact** `provider/id` pair (pi's settings default is an exact lookup). Split on the **first** `/`, so openrouter ids keep their inner slashes. A `:thinking` suffix is accepted. |
| `thinking` | string (`off`/`minimal`/`low`/`medium`/`high`/`xhigh`) | _(pi default)_ | |

Either key may be set alone. A `:thinking` suffix on `default`
(`"anthropic/claude-opus-4-1:high"`) is split at convergence — the last-colon segment counts as a
thinking level only when it is one of pi's levels (ollama tags like `llama3:70b` stay part of the
id); an explicit `thinking` key **wins** over a differing suffix (`perk doctor` warns on the
conflict). An invalid `thinking` (or a `default` without a `/`) is a **hard config error** — a typo
never converges into the committed `settings.json`; doctor's `config` check pinpoints the field.

**Committed-only** (a `local.toml` `[models]` `default`/`thinking` is ignored — unlike the
overlay-aware `[models.stages.<id>]` / `[models.subagents]` siblings). Write-when-present /
leave-when-absent per key: absent keys leave pre-existing `settings.json` defaults untouched;
**removing** them leaves the written keys in place to clean up by hand (same residual as
`[compaction]`). A committed `[models] default` beats a user's global `~/.pi/agent/settings.json`
default; per-user escape hatches are `perk <stage> --model`, a `local.toml`
`[models.stages.<id>]` override, or the in-session model switch.

**Precedence** (session model at a cold launch): explicit `perk <stage> --model/--thinking` >
`[models.stages.<id>]` > the `[models] default`-converged settings default > pi's curated
per-provider defaults > first authenticated model. The settings default never applies to perk's
subagents (they always carry a frontmatter model; `[models.subagents]` overrides that).

```toml
[models]
default = "anthropic/claude-opus-4-1"
thinking = "high"
```

> **Related settings convergence (no config knob):** alongside the `[compaction]`/`[models]`
> convergences, perk also converges the **non-config-driven constant**
> `"subagents": {"disableBuiltins": true}` into the same perk-managed `.pi/settings.json` slice —
> pi-subagents' builtin agents are disabled in every perk repo (perk borrows the delegation engine
> only and ships its own `perk.*` agents). No `.perk/config.toml` knob exists; the re-enable is a
> project-settings per-agent `"subagents": {"agentOverrides": {"<name>": {"disabled": false}}}`
> entry — perk owns only the `disableBuiltins` key, so sibling keys survive init/doctor.

### `[models.subagents]`

Per-agent model overrides for perk's own project agents. **Fixed-key** — no effect on your custom
subagents (they set `model` in frontmatter). An absent key falls back to the agent's frontmatter
default.

| Key | Type | Default |
| --- | --- | --- |
| `pr-reviewer` | string (model id) | _(frontmatter default)_ |
| `review-classifier` | string (model id) | _(frontmatter default)_ |
| `objective-explorer` | string (model id) | _(frontmatter default)_ |
| `conflict-resolver` | string (model id) | _(frontmatter default)_ |
| `learn-analyst` | string (model id) | _(frontmatter default)_ |
| `adversarial-reviewer` | string (model id) | _(frontmatter default)_ |

A value may carry a **`:thinking` suffix** setting that agent's thinking level
(`"anthropic/claude-sonnet-4-5:high"`) — the last-colon segment counts only when it is one of
pi's levels, so ollama-style tags (`llama3:70b`) stay part of the model id. The special value
**`inherit`** makes the agent inherit the parent session's model. `perk doctor` warns on a
suspicious suffix (an alphabetic last-colon segment that is not a pi thinking level, e.g. `:hgih`).

```toml
[models.subagents]
pr-reviewer = "anthropic/claude-sonnet-4-5:high"
review-classifier = "anthropic/claude-haiku-4-5"
```

### `[models.stages.<id>]`

Per-stage **model** + **thinking-level** defaults, injected as pi `--model` / `--thinking` flags
when `perk <stage>` cold-launches that stage's pi session. Each stage is its own sub-table.

| Key | Type | Default |
| --- | --- | --- |
| `model` | string (model id, free-form; perk does not validate it; a `model:thinking` suffix also works — pi `--model` accepts it) | _(pi default)_ |
| `thinking` | string (`off`/`minimal`/`low`/`medium`/`high`/`xhigh`) | _(pi default)_ |

Either key may be set alone; when a stage sets **neither**, nothing is injected (pi's own
resolution is left untouched, falling through to the `[models]`-converged settings default when
configured — a `[models.stages.<id>]` entry sits **above** the `[models] default` in the
precedence chain). An explicit `perk <stage> --model X` / `--thinking Y`
wins (the config flag is injected first; pi parses last-wins). Valid stage ids are the registry
stages (`plan`, `implement`, `address`, `learn`, `objective-author`, `objective-plan`, …). It is a
**launch-seam** setting: warm in-session transitions inherit the launched session's model, and the
remote CI runner is unaffected. **Overlay-aware** (a `.perk/local.toml` `[models.stages.<id>]`
leaf-merges). `perk doctor` validates the stage ids + thinking levels (loud-but-non-fatal `warn`).

```toml
[models.stages.implement]
model = "anthropic/claude-opus-4-1"
thinking = "high"

[models.stages.plan]
thinking = "xhigh"
```

### `[compaction]`

How the session manages its context. The `enabled` / `reserve_tokens` / `keep_recent_tokens`
settings keys are **committed-only** — converged into `.pi/settings.json`'s `compaction` object by
`perk init` / `perk doctor --fix` (re-run to re-converge). The `objective_threshold` sibling is
**runtime-read** (overlay-aware) by the extension instead.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `enabled` | bool | _(pi default)_ | Auto-compaction on/off. |
| `reserve_tokens` | int (> 0) | _(pi default)_ | Tokens reserved for the response. |
| `keep_recent_tokens` | int (> 0) | _(pi default)_ | Recent tokens kept verbatim. |
| `objective_threshold` | float in `(0,1]` | `0.8` | Context-usage fraction that triggers compaction **while an objective is active**. A native float (`0.8`, not `"0.8"`); never converged into `settings.json`. |

```toml
[compaction]
enabled = true
reserve_tokens = 16384
keep_recent_tokens = 20000
objective_threshold = 0.8
```

### `[skills]`

The **layered skills-exposure model**: which skills a cold stage launch exposes to the session.
Per skill, exposure resolves through three layers — a `[skills.stages]` config row (by skill
name) wins when present; else the skill's `stages:` SKILL.md frontmatter (`all` or a list of
stage ids, e.g. `stages: [plan, implement]`); else **undeclared → all stages**. An explicit
empty list (`stages: []` or a `= []` row) hides the skill from every stage launch
(interactive-only); a malformed `stages:` value falls back to all stages with a warning. Skills
**bound** to the launch's stage/command via `[[bindings]]` are always exposed — trumping every
layer, even a `= []` row.

| Key | Type | Notes |
| --- | --- | --- |
| `include_dirs` | array of strings | Directories passed wholesale into scoped launches (`~` expands; relative paths resolve against the repo root). Default `[]`. |
| `include_packages` | boolean | Whether npm-package skills (pi-subagents, …) participate in scoped launches. Default: they do. |
| `[skills.stages]` | table | Skill name → `"all"` or a list of stage ids. Overrides the skill's own `stages:` frontmatter (narrowing or re-widening). Ill-typed values fail config load; unknown skill names and stage ids are kept inert. |

```toml
[skills]
include_dirs = []
include_packages = true

[skills.stages]
ast-grep = ["implement", "address"]
dignified-python = "all"
librarian = []
```

The model **engages only when in use**: some skill declares `stages:` frontmatter, or any
`[skills]` content exists (a `stages` row, a non-empty `include_dirs`, or `include_packages`
explicitly set). An untouched repo launches exactly as before. **Once engaged, pi's global/user
skill dirs (`~/.pi/agent/skills`, `~/.agents/skills`) and project `.pi/skills` stop following
into stage sessions** — whitelist a personal collection per-user in the gitignored
`.perk/local.toml`:

```toml
[skills]
include_dirs = ["~/.agents/skills"]
```

Cold stage launches only; fully fail-open (any composition problem degrades that launch back to
pi's full skill discovery with a warning). Bare interactive `pi` sessions and the remote runner
are untouched.

### `[[bindings]]`

Array-of-tables; each row attaches a skill to a stage or command.

| Key | Type | Notes |
| --- | --- | --- |
| `trigger` | string | `"<kind>:<id>"`; kind is `stage` or `command`. |
| `skill` | string | A skill installed under `.agents/skills/<name>/SKILL.md`. |
| `mode` | string | `nudge` (a short pointer) or `transclude` (inline the skill body). |

A row at a trigger perk already binds overrides perk's default there; a row at a new trigger is
added. See the binding recipe in
[customization-recipes.md](./customization-recipes.md).

```toml
[[bindings]]
trigger = "stage:implement"
skill = "house-style"
mode = "nudge"
```

### Repo-authored skills (`.perk/skills/`)

A repo can author its own skills under `.perk/skills/<name>/SKILL.md` (frontmatter `name` matching the
directory + a `description`). `perk init` / `perk doctor --fix` render a managed skills-CLI manifest
fragment `.agents/manifest.d/perk-repo-skills.yaml` under a source pointing at the repo's own GitHub
origin + default branch — `.agents/manifest.yaml` is never touched.

The `perk skills` verbs drive the authoring lifecycle: `scaffold NAME` writes a stub `SKILL.md` and
reconverges the fragment; `create NAME` scaffolds and launches a write-capable authoring session;
`refine NAME` re-opens an existing skill (skipping sync); `delete NAME` removes it and reconverges.

Since the source resolves from the **default branch**, a new skill must be **committed + pushed**,
then `perk init` (or `perk doctor --fix`) re-run, before the skills CLI delivers it. `init` reports
a malformed SKILL.md / name collision / uncommitted skill as a **non-fatal warning** (exit 0);
`perk doctor`'s **`repo-skills`** check is `fail` on invalid SKILL.md / no GitHub remote / fragment
drift and `warn` on an uncommitted skill.

---

*Canonical source: `docs/user-docs/reference/configuration.md`.*
