# Configuration files

This page references perk's repo configuration: the `.perk/config.toml` committed config and the
`.perk/local.toml` per-user overlay. It describes the surface — every table and key — so an
operator can look up any setting. It also carries the canonical [repository layout
contract](#repository-layout--the-dot-directory-contract) — every perk-relevant path with its
owner and lifecycle. It does not teach a task (those belong in
[how-to/](../how-to/index.md)) or argue a design (those belong in
[explanation/](../explanation/index.md)). See the [user-docs router](../index.md) for how this
quadrant fits the whole.

Config tables are not introspectable the way the CLI's `--help` is, so — unlike the
[CLI reference](./cli.md)'s pytest existence guard — these entries are **human-reviewed for
accuracy** against the config readers (`perk/substrate/config.py`, `extension/substrate/config.ts`)
and the `perk init` templates. Accuracy is the governing virtue.

## Orientation

perk reads two files, both under `.perk/`:

- **`.perk/config.toml`** — the committed project config. Edit it freely; it is shared by everyone
  working in the repo. It is also perk's repo **initialization marker**.
- **`.perk/local.toml`** — a per-user overlay. It is gitignored, so it never leaves your
  machine; use it for personal overrides.

[`perk init`](./cli.md#perk-init) scaffolds both with a commented template, and
[`perk doctor`](./cli.md#perk-doctor) validates them. The schema grows as perk does; the tables
below are the live surface.

> **Migrating from `.pi/perk.toml`.** perk's config used to live at `.pi/perk.toml` /
> `.pi/perk.local.toml`. A repo still carrying only the legacy committed file makes `perk init`
> **refuse** (with a `perk doctor --fix` remediation) rather than re-scaffold over it. Run
> [`perk doctor --fix`](./cli.md#perk-doctor): it migrates the config to `.perk/` secret-safely
> (your gitignored `.pi/perk.local.toml` secret moves to `.perk/local.toml` and is never promoted
> into the committed file), then re-run `perk init`.

> **Breaking: config schema v2.** The schema was redesigned top-down (every top-level header
> answers one operator question; structure encodes relationships). There is **no migration
> tooling and no dual-read** — the pre-v2 spellings hard-fail every `perk` command with a
> pointer to the new home (e.g. `legacy table [subagents] — moved to [models.subagents]`).
> Rename map: `[stages.<id>]` → `[models.stages.<id>]` · `[subagents]` → `[models.subagents]` ·
> `[models] model` → `[models] default` · `[[ci]]` → `[[ci.checks]]` · `[trust] ci = "true"` →
> `[ci] trusted = true` · `[objective] compact_threshold = "0.8"` →
> `[compaction] objective_threshold = 0.8`. Types are now honest: `trusted` is a native boolean
> and `objective_threshold` a native float (the quoted-string workaround is dead).

## Repository layout — the dot-directory contract

This is the canonical file-location reference for a perk-wired repo: every perk-relevant path,
who owns it, and how it lives in git. It is the single source of truth for "where does X live?"
questions; the rest of perk's docs link here rather than re-deriving the topology.

**Ownership vs. discovery.** `.perk/` is the authoritative, **perk-owned** dot-directory — perk's
committed source (`config.toml`, repo-authored `skills/`) plus its local cache (`workflow/`,
`local.toml`). `.pi/` and `.agents/` are **discovery** namespaces owned by their host tools — Pi
and the skills CLI, respectively. perk writes a few **generated materializations** into those
namespaces because that is where the host tool looks for them, but `.pi/` is **not** generally
perk-owned: it is Pi's directory with a perk-managed slice.

| Path | Owner | Lifecycle | Versioned |
| --- | --- | --- | --- |
| `.perk/config.toml` | maintainer / perk (the init marker) | committed | yes |
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
machine-local store behind the one-line post-upgrade notice (see
[`perk release-notes`](./cli.md#perk-release-notes)): the max perk version this user has run
interactively. It is self-healing (missing or garbled content is silently re-recorded) and safe
to delete; no doctor check or init convergence touches it.

**Pi-native materializations.** Two committed perk outputs live in Pi's namespace rather than
under `.perk/`, because Pi discovers them there: `.pi/APPEND_SYSTEM.md` (the generated ambient
routing index appended to every session's system prompt) and `.pi/agents/perk/` (perk's owned
slice of Pi's project-agent namespace). They are perk-generated and committed, but they are
framed as materializations into a host tool's directory — not evidence that `.pi/` is perk-owned.

## Local overrides & overlay semantics

How the two files combine:

1. `.perk/local.toml` overlays `.perk/config.toml` — **local wins.** Tables merge recursively;
   scalar leaves replace.
2. A local `[[bindings]]` / `[[ci.checks]]` array **replaces the committed array wholesale**
   (whole-array override, not element-wise merge) — arrays are leaves, so the local array
   substitutes for the committed one entirely.
3. **The overlay rule, once:** keys perk **converges into committed artifacts** ignore
   `.perk/local.toml` — `[models]` `default`/`thinking`, `[compaction]`'s settings keys
   (`enabled`/`reserve_tokens`/`keep_recent_tokens`), and `[issues]` are read from
   `.perk/config.toml` **only**, keeping the canonical issue store and the committed
   `.pi/settings.json` deterministic (a per-user compaction/model override belongs in pi's
   global `~/.pi/agent/settings.json`). Keys **read at runtime** honor the overlay —
   `[models.stages.<id>]`, `[models.subagents]`, `[ci]`, `[compaction] objective_threshold`,
   `[workflow]`, `[worktree]`, `[providers]`, `[skills]`, `[[bindings]]`.

## Tables

### `[worktree]`

Where `perk worktree create` and the cold-door stage launchers place worktrees.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `root` | string | `.worktrees` | A relative path resolves against the repo root; an absolute path is used as-is. |
| `setup` | array of strings | _(none)_ | Shell commands run via `bash -lc`, in order, inside each **freshly created** worktree before `pi` starts (`cwd` = the worktree). A non-zero exit, timeout, or missing `bash` **aborts the launch** (the worktree is left for a fixed re-run). Command output is captured and shown only on failure. Skipped on resume/reuse, dry-runs, and the remote runner. Overlay-aware — a `local.toml` `[worktree] setup` array replaces this one wholesale. |

```toml
[worktree]
root = ".worktrees"
setup = ["uv sync"]
```

See also: [How to run a worktree setup hook](../how-to/run-a-worktree-setup-hook.md).

### `[workflow]`

Project-supplied plan-authoring guidance and the default target branch.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `plan_authoring` | string | _(none)_ | Appended into the plan-authoring context injection inside `plan` sessions. Gotcha: a bare skill name in addendum prose is only model-reachable when that skill is model-invocable; a skill hidden via `disable-model-invocation: true` must be referenced with its read path (`.agents/skills/<name>/SKILL.md`). |
| `base` | string | _(GitHub default branch)_ | The default target branch plans and objectives base off and target. Overrides the repo's GitHub default; an objective's own `--base` wins for its node plans. Pinned at save time — see [Target a non-default base branch](../how-to/target-a-non-default-base-branch.md). |

```toml
[workflow]
plan_authoring = "Prefer the smallest diff that satisfies the acceptance criteria."
base = "develop"
```

### `[ci]`

How work is verified — and whether it's trusted. The `trusted` policy key sits directly above the
`[[ci.checks]]` commands it green-lights.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `trusted` | bool | _(unset ⇒ untrusted)_ | `true` (a **native boolean**) marks the `[[ci.checks]]` below trusted — they run without a per-session confirm (including headless). A quoted `"true"` does **not** grant trust. |

```toml
[ci]
trusted = true
```

#### `[[ci.checks]]`

An array-of-tables: each `[[ci.checks]]` row declares one check. Consumed by the in-session CI
executor (warm `/ci` + the `run_ci` tool); `/ready` does not run them — it only marks the draft
PR ready for review (run `/ci` first). Checks run
**concurrently**; declared order governs the **report** order, not execution order. Each row must
therefore be independently runnable — when sequencing matters, put the ordered steps inside one
row's `command` (e.g. `"build && test"`). `/ci` and the `run_ci` `check` argument accept a single
name or a comma-separated list (e.g. `/ci lint,test`) to re-verify a subset in one call.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `name` | string | _(required)_ | The check name (selected by `/ci <name>`). |
| `command` | string (shell command) | _(required)_ | The command to run. |
| `glob` | string | _(unset)_ | A comma-separated pattern string (e.g. `"*.ts,*.tsx"`). When set, the check is **skipped** on the run-all path if no changed file (vs the repo's trunk) matches; unset ⇒ the check always runs. |

**Change-scoped gating.** A check with a `glob` runs only when at least one changed file (merge-base
vs the detected trunk, plus untracked files) matches one of its patterns — a docs-only change skips
the code checks and reports success fast. A pattern with no `/` matches a file's basename at any
depth (so `*.py` gates any `.py`); `**` crosses directories, `*` matches one path segment. Gating
applies only when running **all** checks: an explicit `/ci <name>` always runs that check, and any
git error **fails open** (all checks run) so uncertainty never produces a false success.

```toml
[[ci.checks]]
name = "lint"
command = "just lint"
glob = "*.py,*.ts"

[[ci.checks]]
name = "test"
command = "just test"
```

See [How to run CI checks in a session](../how-to/run-ci-in-session.md) for the recipe.

### `[providers]`

Per-seam provider selection — provider-id strings pointing into perk's supported provider set.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `plan` | string | `perk-plan` | The plan-authoring provider. |
| `footer` | string | `perk-footer` | The footer provider (selectable: `powerline-footer`, `pi-bar-footer`, `pi-status-footer`, `pi-default`). |
| `web` | string | `pi-web-access` | The web search/fetch provider (selectable: `ollama-web-search`, `juicesharp-web-tools`). |

An absent key falls back to the behavior-preserving default. The retired `review`, `askuser`, and
`todo` keys **hard-fail config load** with removal guidance: the PR-review surface is picked by the
command itself (`/pr-review-terminal` = hunk, `/pr-review-browser` = plannotator), not by config,
the `ask_user_question` questionnaire tool is **built-in** (perk installs
`npm:@juicesharp/rpiv-ask-user-question` for every repo — nothing to select), and the todo
checklist overlay is likewise **built-in** (perk installs `npm:@juicesharp/rpiv-todo` for every
repo); remove `review` / `askuser` / `todo` from `[providers]` if present. This is **config-key
reference depth only**; the supported provider set, postures, and selection mechanics are in the
[providers & issue backends reference](./providers-and-backends.md), and the recipe is
[How to select a provider](../how-to/select-a-provider.md).

```toml
[providers]
plan = "perk-plan"
footer = "perk-footer"
web = "pi-web-access"
```

### `[issues]`

Where canonical plan / learn / objective issues live. **Committed-only** — read from
`.perk/config.toml`, never the overlay (a per-user override would fragment the canonical store).
The read is anchored to the **main checkout's** config even when a command runs inside a linked
worktree, so a worktree's checkout state (a detached HEAD or a commit without `.perk/`) can never
flip the canonical store — an in-worktree `[issues]` edit takes effect when it reaches the main
checkout.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `backend` | string | `github` | `"github"` or `"linear"`. |
| `team` | string | _(none)_ | The Linear team key (e.g. `"ENG"`); required when `backend = "linear"`. |

Selecting `linear` also requires a personal `LINEAR_API_KEY` — set it in the environment **or** in
the gitignored `.perk/local.toml` `[linear] api_key` (see [`[linear]`](#linear) below); never in
this committed file. This is **config-key reference depth only**; the Linear backend reference
(auth, labels, identifiers, maturity) is in the
[providers & issue backends reference](./providers-and-backends.md#issue-backend--linear-reference),
and the recipe is [How to switch the issue backend to Linear](../how-to/switch-to-linear.md).

```toml
[issues]
backend = "linear"
team = "ENG"
```

### `[linear]`

A personal Linear API key, used by **both** perk's Linear issue backend and the in-session
`linear_*` tools. **Gitignored-local-only** — read from `.perk/local.toml`, **never** the
committed `.perk/config.toml` (structurally preventing a committed secret).

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `api_key` | string | _(none)_ | A personal Linear API key (linear.app → Settings → Security & access). |

An exported `LINEAR_API_KEY` environment variable **wins** over this config (the config is a
fallback). When set here, perk seeds the launched `pi` session's environment with the key so the
borrowed in-session `linear_*` tools authenticate too. The key is read from your **main checkout**
at launch — since the file is gitignored it is never copied into a worktree, so this env-seed is
what carries the key into the worktree session and any tools/workers it spawns (they inherit the
seeded environment). perk also reads this key directly from the **main checkout's**
`.perk/local.toml` whenever a command runs inside a linked worktree (`/submit`, `/land`, …) —
so a single entry in the main checkout authenticates every worktree session and cold-door, even
when the launch env-seed did not fire. Malformed local TOML is ignored (fail-soft).

```toml
# .perk/local.toml (gitignored)
[linear]
api_key = "lin_api_…"
```

### `[models]`

Which AI runs where. One namespace: the repo-default `default`/`thinking` keys, the per-stage
`[models.stages.<id>]` sub-tables, and the per-agent `[models.subagents]` table — precedence is
visible as nesting (an explicit flag > a stage override > the default).

The **repo-default model + thinking level** (`default` + `thinking`) is converged by `perk init` /
`perk doctor --fix` into `.pi/settings.json`'s top-level `defaultProvider` / `defaultModel` /
`defaultThinkingLevel` keys, which pi reads natively at session boot. Because it lands in the
committed `settings.json`, it applies to **every** pi session in the repo: perk cold doors, plain
`pi`, and the headless worker (local **and** remote — the worker resolves its model from the
checkout's disk-layered settings, so this is how you configure the worker's model).

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `default` | string (`provider/id`) | _(pi default)_ | Must be an **exact** `provider/id` pair — pi's settings default is an exact provider+id lookup (no fuzzy matching). Split on the **first** `/`, so openrouter ids keep their inner slashes (`openrouter/meta-llama/llama-3-70b` → provider `openrouter`, id `meta-llama/llama-3-70b`). A `:thinking` suffix is accepted (see below). |
| `thinking` | string | _(pi default)_ | One of `off` / `minimal` / `low` / `medium` / `high` / `xhigh`. |

Either key may be set alone. A `:thinking` suffix on `default`
(`default = "anthropic/claude-opus-4-1:high"`) is split at convergence — the last-colon segment
counts as a thinking level **only when** it is one of pi's levels, so ollama-style tags
(`ollama/llama3:70b`) stay part of the model id. An explicit `thinking` key **wins** over a
differing suffix (`perk doctor` warns on the conflict). An **invalid** `thinking` value (or a
`default` without a `/`) is a **hard config error** — a typo never converges into the committed
`settings.json`; `perk doctor`'s `config` check pinpoints the field.

**Committed-only** (`default`/`thinking`) — read from `.perk/config.toml`, never the
`.perk/local.toml` overlay (unlike the overlay-aware `[models.stages.<id>]` /
`[models.subagents]` siblings), so the committed `settings.json` stays a deterministic function
of committed config. Per-user escape hatches: `perk <stage> --model`, a `local.toml`
`[models.stages.<id>]` override, or the in-session model switch. Convergence is
**write-when-present / leave-when-absent** per key: an absent table (or key) leaves any
pre-existing `settings.json` defaults untouched, and **removing** the keys leaves the previously
written settings in place to clean up by hand (perk cannot prove ownership of a bare settings key —
the same residual as `[compaction]`). Note that a committed `[models] default` beats a user's
global `~/.pi/agent/settings.json` default (pi merges project settings over global).

**Precedence** (session model at a cold launch): explicit `perk <stage> --model/--thinking` >
`[models.stages.<id>]` > the `[models] default`-converged settings default > pi's curated
per-provider defaults > first authenticated model. Subagents are separate: `[models.subagents]` >
agent frontmatter `model:` — the settings default never applies to perk's agents (they always
carry a frontmatter model).

```toml
[models]
default = "anthropic/claude-opus-4-1"
thinking = "high"
```

> **Related settings convergence (no config knob):** alongside the `[compaction]`/`[models]`
> convergences, perk also converges the **non-config-driven constant**
> `"subagents": {"disableBuiltins": true}` into the same perk-managed `.pi/settings.json` slice —
> pi-subagents' builtin agents are disabled in every perk repo (perk borrows the delegation engine
> only and ships its own `perk.*` agents). There is no `.perk/config.toml` knob; to re-enable one
> builtin, add a project-settings per-agent
> `"subagents": {"agentOverrides": {"<name>": {"disabled": false}}}` entry — perk owns only the
> `disableBuiltins` key, so sibling keys survive init/doctor. See
> [How to write a custom subagent](../how-to/write-a-custom-subagent.md).
>
> perk also **seeds** `"tuiMode": "fullscreen"` into the same slice — but only when the key is
> absent (seeded once, never overwritten). To opt out, set `"tuiMode": "regular"` in
> `.pi/settings.json`; the value survives init/doctor. Note pi's `/settings` toggle writes the
> **global** settings file, which the committed project key overrides — the durable opt-out is
> the project key itself.

### `[models.stages.<id>]`

Per-stage **model** and **thinking-level** defaults, injected as pi `--model` / `--thinking` flags
when `perk <stage>` cold-launches that stage's pi session. Each stage is its own sub-table
(`[models.stages.implement]`, `[models.stages.plan]`, …).

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `model` | string (model id) | _(pi default)_ | The pi model string (e.g. `anthropic/claude-opus-4-1`). Free-form — perk does not validate it; pi resolves it at session start. A `model:thinking` suffix also works (pi `--model` accepts it). |
| `thinking` | string | _(pi default)_ | One of `off` / `minimal` / `low` / `medium` / `high` / `xhigh`. |

Either key may be set alone. When a stage configures **neither** knob, **nothing is injected** —
pi's own model/thinking resolution is left untouched, falling through to the
[`[models]`](#models)-converged settings default when one is configured (a `[models.stages.<id>]`
entry sits **above** the `[models] default` in the precedence chain). An explicit flag on the
command line wins: `perk implement --model X` overrides a configured `[models.stages.implement]
model` (perk injects the config flag first; pi parses last-wins).

Valid stage ids are the registry stages (`plan`, `implement`, `address`, `learn`,
`objective-author`, `objective-plan`, … — see `perk registry`). This is a **launch-seam** setting:
it takes effect only where a stage cold-launches an interactive pi session. Warm in-session
transitions inherit the launched session's model, and the remote CI runner is unaffected.

The sub-tables are **overlay-aware** — a `.perk/local.toml` `[models.stages.<id>]` leaf-merges
over the committed values (session-transient preference, like `[worktree] root`). `perk doctor`
validates the configured stage ids against the registry and the thinking levels against pi's set
(loud-but-non-fatal — an unknown stage id or invalid thinking level is a `warn`, never a failure).

```toml
[models.stages.implement]
model = "anthropic/claude-opus-4-1"
thinking = "high"

[models.stages.plan]
thinking = "xhigh"
```

### `[models.subagents]`

Per-agent model overrides for each perk-owned project agent.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `pr-reviewer` | string (model id) | _(agent frontmatter default)_ | Model for the PR-reviewer agent. |
| `review-classifier` | string (model id) | _(agent frontmatter default)_ | Model for the review-classifier agent. |
| `objective-explorer` | string (model id) | _(agent frontmatter default)_ | Model for the objective-explorer agent. |
| `conflict-resolver` | string (model id) | _(agent frontmatter default)_ | Model for the conflict-resolver agent (spawned by `/submit` when it detects merge conflicts). |
| `learn-analyst` | string (model id) | _(agent frontmatter default)_ | Model for the learn-analyst agent (used by `/learn` to analyze a landed plan's session evidence). |
| `adversarial-reviewer` | string (model id) | _(agent frontmatter default)_ | Model for the adversarial-reviewer agent (human-in-the-loop PR review; spawned by `/pr-review-terminal` and `/pr-review-browser`). |
| `review-angle-selector` | string (model id) | _(agent frontmatter default)_ | Model for the review-angle-selector agent (a bounded change-profile classifier that selects review coverage angles for the experimental dynamic-review flow). |
| `draft-reviewer` | string (model id) | _(agent frontmatter default)_ | Model for the draft-reviewer agent (streamed draft review; spawned by `/plan-review-browser` and `/objective-review-browser`). |
| `harvest-analyst` | string (model id) | _(agent frontmatter default)_ | Model for the harvest-analyst agent (per-lane `docs/learned` mining for `perk learn harvest`; spawned by the `run_harvest_wave` fan-out). |
| `session-auditor` | string (model id) | _(agent frontmatter default)_ | **Dev-only** — model for the session-auditor agent (perk's own repo's session-audit judgment wave, spawned inside a `perk-dev audit judge` session; the agent def is repo-local, not delivered by `perk init`, so this key is dormant in consumer repos). |

An absent key falls back to the agent's frontmatter default. The table is **fixed-key** — it
configures only perk's own agents (delivered into the perk-managed `.pi/agents/perk/` subdir
by `perk init`, except the dev-only `session-auditor`, whose definition is repo-local to perk's
own repository and never delivered); it has no effect on your own custom subagents, which set
their model in frontmatter.
See [How to write a custom subagent](../how-to/write-a-custom-subagent.md).

A value may carry a **`:thinking` suffix** to set that agent's thinking level
(`pr-reviewer = "anthropic/claude-sonnet-4-5:high"`) — the last-colon segment counts as a
thinking level only when it is one of pi's levels (`off`/`minimal`/`low`/`medium`/`high`/`xhigh`),
so ollama-style tags (`llama3:70b`) stay part of the model id. The special value **`inherit`**
makes the agent inherit the parent session's model. `perk doctor` warns on a suspicious suffix
(an alphabetic last-colon segment that is not a pi thinking level, e.g. a `:hgih` typo — it would
silently become part of the model id).

```toml
[models.subagents]
pr-reviewer = "anthropic/claude-sonnet-4-5:high"
review-classifier = "anthropic/claude-haiku-4-5"
```

### `[compaction]`

How the session manages its context. The `enabled` / `reserve_tokens` / `keep_recent_tokens`
settings keys tune pi's auto-compaction for `perk <stage>` sessions: **committed-only** —
converged into `.pi/settings.json`'s `compaction` object by `perk init` / `perk doctor --fix`;
editing them requires re-running init/doctor to re-converge. The `objective_threshold` sibling is
**runtime-read** (overlay-aware) by the extension instead.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `enabled` | bool | _(pi default)_ | Turns pi's auto-compaction on/off. |
| `reserve_tokens` | int (> 0) | _(pi default)_ | Tokens reserved for the response. |
| `keep_recent_tokens` | int (> 0) | _(pi default)_ | Recent tokens kept verbatim. |
| `objective_threshold` | float in `(0,1]` | `0.8` | The context-usage fraction that triggers compaction **while an objective is active**. A native float (`0.8`, not `"0.8"`); never converged into `settings.json`. |

```toml
[compaction]
enabled = true
reserve_tokens = 16384
keep_recent_tokens = 20000
objective_threshold = 0.8
```

### `[skills]`

Controls the **layered skills-exposure model**: which skills a cold stage launch (`perk plan`,
`perk implement`, …) exposes to the session. For each skill, exposure resolves through three
layers — a `[skills.stages]` config row (by skill name) wins when present; else the skill's
`stages:` SKILL.md frontmatter (`all` or a list of stage ids, e.g. `stages: [plan, implement]`);
else **undeclared → all stages** (existing skills behave like today). An explicit empty list
(`stages: []` or a `= []` row) hides the skill from every stage launch (interactive-only); a
malformed `stages:` value falls back to all stages with a warning. Skills **bound** to the
launch's stage or command via `[[bindings]]` are always exposed, trumping every layer — even a
`= []` row.

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
explicitly set). **Perk's own shipped skills declare `stages:` at source**, so once your
`.agents/skills/` mirror is synced to current perk (`perk init` / `perk doctor --fix`), cold
stage launches are **scoped by default**. A repo whose mirror predates the declarations stays
unscoped (undeclared → all stages, fail-open) until its next re-sync.

> **Migration note — once engaged, global skills stop following you into stage sessions.** A
> scoped launch drops pi's global/user skill dirs (`~/.pi/agent/skills`, `~/.agents/skills`) and
> project `.pi/skills` by default. To keep a personal skill collection in perk sessions — without
> committing anything — whitelist it in your gitignored `.perk/local.toml`:
>
> ```toml
> [skills]
> include_dirs = ["~/.agents/skills"]
> ```

Scoping is composed at the cold launch only — the whole composition is fail-open (any problem,
e.g. a not-yet-installed extension package, degrades that launch back to pi's full skill
discovery with a warning; it never blocks). Bare interactive `pi` sessions and the remote runner
are untouched.

### `[[bindings]]`

An array-of-tables: each row attaches a skill to a stage or command, delivered into that session.

| Key | Type | Notes |
| --- | --- | --- |
| `trigger` | string | `"<kind>:<id>"`; kind is `stage` or `command`. |
| `skill` | string | A skill name installed under `.agents/skills/<name>/SKILL.md`. |
| `mode` | string | `nudge` (a short pointer) or `transclude` (inline the skill body). |

A row at a trigger perk already binds overrides perk's default there; a row at a new trigger is
added. The full mechanics — trigger selection, the nudge/transclude decision, the deliverable-command
caveat — are in
[How to attach your own skill to a stage or command](../how-to/attach-a-skill-to-a-stage.md).

```toml
[[bindings]]
trigger = "stage:implement"
skill = "house-style"
mode = "nudge"
```

### Repo-authored skills (`.perk/skills/`)

A repo can author its **own** skills. Put each under `.perk/skills/<name>/SKILL.md` (a YAML
frontmatter block with `name` matching the directory and a `description`). `perk init` and
`perk doctor --fix` discover them and render a managed skills-CLI manifest fragment at
`.agents/manifest.d/perk-repo-skills.yaml` under a source pointing at **your repo** (its GitHub
origin + default branch). perk **never** edits `.agents/manifest.yaml` — only its own `.d/`
fragment.

The authoring lifecycle is driven by the `perk skills` verbs: **`scaffold NAME`** writes a stub
`SKILL.md` and reconverges the fragment; **`create NAME`** scaffolds and launches a write-capable
authoring session; **`refine NAME`** re-opens an existing skill (skipping sync); **`delete NAME`**
removes it and reconverges. The stub declares `stages: all` with a TODO comment — narrow it
deliberately (a stage-id list, `all`, or `[]` for interactive-only; see
[`[skills]`](#skills) above). See
[How to author a repo-specific skill](../how-to/author-a-repo-skill.md) for the full recipe.

Because the source resolves your skill from your repo's **default branch**, a freshly-added skill
must be **committed and pushed** before the skills CLI can deliver it:

1. Add `.perk/skills/<name>/SKILL.md`.
2. Commit + push it to your default branch.
3. Re-run `perk init` (or `perk doctor --fix`).

`perk init` is forgiving here: a malformed `SKILL.md`, a name/source collision, or an uncommitted
skill is reported as a **non-fatal warning** (init still exits 0 and converges everything else).
[`perk doctor`](./cli.md#perk-doctor) surfaces the same diagnostics as a **`repo-skills`** check
(`fail` on an invalid SKILL.md / no GitHub remote / fragment drift; `warn` on an uncommitted
skill, a skill that leaves `stages:` undeclared — exposed to every stage launch — or a declared
stage id that isn't a registry stage). The only fatal case is the skills CLI failing to resolve
a declared skill at sync time — which the commit-push-resync sequence above fixes.

## A note on value types

Types are **honest** (config schema v2): booleans are native booleans (`trusted = true`), numbers
are native numbers (`objective_threshold = 0.8`, `reserve_tokens = 16384`). The old rule that
TS-read keys had to be quoted strings is dead — a quoted `"true"` no longer grants trust and a
quoted `"0.8"` threshold is ignored.

Python-read keys are **validated at load**: an ill-typed value (e.g. `base = 7` under
`[workflow]`) fails `perk` commands with a field-path error (`workflow.base: Input should be a
valid string`), and [`perk doctor`](./cli.md#perk-doctor) pinpoints the bad field in its `config`
check. (Previously such values were silently ignored.) The `[compaction]` integers must be
**positive** native ints — a quoted numeric string (`"16384"`) is accepted by coercion, but a bare
bool (`reserve_tokens = true`) is rejected. **Legacy spellings hard-fail:** a pre-v2 table
(`[trust]`, `[objective]`, `[subagents]`, `[stages.<id>]`, `[[ci]]`, or a `[models] model` key)
raises a config error naming its new home rather than being silently dropped.

## See also

- [CLI commands](./cli.md) — the `perk …` commands, including `perk init` and `perk doctor`.
- [In-session commands & tools](./in-session.md) — the warm `/…` commands and model-facing tools.
- [How to attach your own skill to a stage or command](../how-to/attach-a-skill-to-a-stage.md) —
  the `[[bindings]]` recipe.
- [How to run CI checks in a session](../how-to/run-ci-in-session.md) — the `[[ci.checks]]` recipe.
- [Providers & issue backends](./providers-and-backends.md) — the supported provider set and the
  Linear backend reference; this page documents their config keys only.
- [How to select a provider](../how-to/select-a-provider.md) /
  [How to switch the issue backend to Linear](../how-to/switch-to-linear.md) — the selection recipes.

---

← Back to the [reference router](index.md).
