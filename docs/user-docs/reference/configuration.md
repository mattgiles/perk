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
2. A local `[[bindings]]` array **replaces the committed `[[bindings]]` array wholesale**
   (whole-array override, not element-wise merge) — arrays are leaves, so the local array
   substitutes for the committed one entirely.
3. **Committed-only tables ignore the overlay entirely.** `[issues]` and `[compaction]` are read
   from `.perk/config.toml` **only**; a `.perk/local.toml` value for either is silently ignored —
   this keeps the canonical issue store and the committed `.pi/settings.json` deterministic. A
   per-user compaction override belongs in pi's global `~/.pi/agent/settings.json` instead.

## Tables

### `[worktree]`

Where `perk worktree create` and the cold-door stage launchers place worktrees.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `root` | string | `.worktrees` | A relative path resolves against the repo root; an absolute path is used as-is. |
| `setup` | array of strings | _(none)_ | Shell commands run via `bash -lc`, in order, inside each **freshly created** worktree before `pi` starts (`cwd` = the worktree). A non-zero exit, timeout, or missing `bash` **aborts the launch** (the worktree is left for a fixed re-run). Skipped on resume/reuse, dry-runs, and the remote runner. Overlay-aware — a `local.toml` `[worktree] setup` array replaces this one wholesale. |

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
| `plan_authoring` | string | _(none)_ | Appended into the plan-authoring context injection inside `plan` sessions. |
| `base` | string | _(GitHub default branch)_ | The default target branch plans and objectives base off and target. Overrides the repo's GitHub default; an objective's own `--base` wins for its node plans. Pinned at save time — see [Target a non-default base branch](../how-to/target-a-non-default-base-branch.md). |

```toml
[workflow]
plan_authoring = "Prefer the smallest diff that satisfies the acceptance criteria."
base = "develop"
```

### `[[ci]]`

An array-of-tables: each `[[ci]]` row declares one check. Consumed by the in-session CI executor
(warm `/ci` + the `run_ci` tool) and run automatically at `/ready`. Declared order is preserved.

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
[[ci]]
name = "lint"
command = "just lint"
glob = "*.py,*.ts"

[[ci]]
name = "test"
command = "just test"
```

See [How to run CI checks in a session](../how-to/run-ci-in-session.md) for the recipe.

### `[providers]`

Per-seam provider selection — provider-id strings pointing into perk's supported provider set.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `plan` | string | `perk-plan` | The plan-authoring provider. |
| `todo` | string | `perk-checkpoints` | The checkpoint/todo provider. |
| `askuser` | string | `perk-ask-user` | The `ask_user_question` tool provider (selectable: `juicesharp-ask-user`). |
| `footer` | string | `perk-footer` | The footer provider (selectable: `powerline-footer`, `pi-bar-footer`, `pi-status-footer`, `pi-default`). |
| `web` | string | `pi-web-access` | The web search/fetch provider (selectable: `ollama-web-search`, `juicesharp-web-tools`). |

An absent key falls back to the behavior-preserving default. This is **config-key reference depth
only**; the supported provider set, postures, and selection mechanics are in the
[providers & issue backends reference](./providers-and-backends.md), and the recipe is
[How to select a plan or todo provider](../how-to/select-a-provider.md).

```toml
[providers]
plan = "perk-plan"
todo = "perk-checkpoints"
askuser = "perk-ask-user"
footer = "perk-footer"
web = "pi-web-access"
```

### `[issues]`

Where canonical plan / learn / objective issues live. **Committed-only** — read from
`.perk/config.toml`, never the overlay (a per-user override would fragment the canonical store).

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

### `[subagents]`

Per-agent model overrides for each perk-owned project agent.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `pr-reviewer` | string (model id) | _(agent frontmatter default)_ | Model for the PR-reviewer agent. |
| `review-classifier` | string (model id) | _(agent frontmatter default)_ | Model for the review-classifier agent. |
| `objective-explorer` | string (model id) | _(agent frontmatter default)_ | Model for the objective-explorer agent. |
| `conflict-resolver` | string (model id) | _(agent frontmatter default)_ | Model for the conflict-resolver agent (spawned by `/submit` when it detects merge conflicts). |
| `learn-analyst` | string (model id) | _(agent frontmatter default)_ | Model for the learn-analyst agent (used by `/learn` to analyze a landed plan's session evidence). |

An absent key falls back to the agent's frontmatter default. The table is **fixed-key** — it
configures only perk's own agents (delivered into the perk-managed `.pi/agents/perk/` subdir
by `perk init`); it has no effect on your own custom subagents, which set their model in frontmatter.
See [How to write a custom subagent](../how-to/write-a-custom-subagent.md).

```toml
[subagents]
pr-reviewer = "anthropic/claude-sonnet-4-5"
review-classifier = "anthropic/claude-haiku-4-5"
```

### `[stages.<id>]`

Per-stage **model** and **thinking-level** defaults, injected as pi `--model` / `--thinking` flags
when `perk <stage>` cold-launches that stage's pi session. Each stage is its own sub-table
(`[stages.implement]`, `[stages.plan]`, …).

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `model` | string (model id) | _(pi default)_ | The pi model string (e.g. `anthropic/claude-opus-4-1`). Free-form — perk does not validate it; pi resolves it at session start. |
| `thinking` | string | _(pi default)_ | One of `off` / `minimal` / `low` / `medium` / `high` / `xhigh`. |

Either key may be set alone. When a stage configures **neither** knob, **nothing is injected** —
pi's own model/thinking resolution is left completely untouched (there is no silently-enforced perk
default). An explicit flag on the command line wins: `perk implement --model X` overrides a
configured `[stages.implement] model` (perk injects the config flag first; pi parses last-wins).

Valid stage ids are the registry stages (`plan`, `implement`, `address`, `learn`,
`objective-author`, `objective-plan`, … — see `perk registry`). This is a **launch-seam** setting:
it takes effect only where a stage cold-launches an interactive pi session. Warm in-session
transitions inherit the launched session's model, and the remote CI runner is unaffected.

The table is **overlay-aware** — a `.perk/local.toml` `[stages.<id>]` leaf-merges over the
committed values (session-transient preference, like `[worktree] root`). `perk doctor` validates
the configured stage ids against the registry and the thinking levels against pi's set
(loud-but-non-fatal — an unknown stage id or invalid thinking level is a `warn`, never a failure).

```toml
[stages.implement]
model = "anthropic/claude-opus-4-1"
thinking = "high"

[stages.plan]
thinking = "xhigh"
```

### `[trust]`

Per-repo trust declarations.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `ci` | string | _(unset)_ | The string `"true"` marks the repo's `[[ci]]` checks trusted — they run without a per-session confirm (including headless). |

The value is a **quoted string** (`ci = "true"`); only that exact string grants trust.

```toml
[trust]
ci = "true"
```

### `[compaction]`

Tunes pi's auto-compaction for `perk <stage>` sessions. **Committed-only** — converged into
`.pi/settings.json`'s `compaction` object by `perk init` / `perk doctor --fix`; editing it requires
re-running init/doctor to re-converge.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `enabled` | bool | _(pi default)_ | Turns pi's auto-compaction on/off. |
| `reserve_tokens` | int (> 0) | _(pi default)_ | Tokens reserved for the response. |
| `keep_recent_tokens` | int (> 0) | _(pi default)_ | Recent tokens kept verbatim. |

These are native ints read by the Python plane (not quoted strings).

```toml
[compaction]
enabled = true
reserve_tokens = 16384
keep_recent_tokens = 20000
```

### `[objective]`

Tuning for objective-active sessions.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `compact_threshold` | string (decimal in `(0,1]`) | _(internal default)_ | The context-usage fraction that triggers compaction while an objective is active. |

The value is a **quoted decimal string** (e.g. `"0.8"`) — the TS reader consumes string leaf
values only and parses it with `Number.parseFloat`.

```toml
[objective]
compact_threshold = "0.8"
```

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
removes it and reconverges. See [How to author a repo-specific skill](../how-to/author-a-repo-skill.md)
for the full recipe.

Because the source resolves your skill from your repo's **default branch**, a freshly-added skill
must be **committed and pushed** before the skills CLI can deliver it:

1. Add `.perk/skills/<name>/SKILL.md`.
2. Commit + push it to your default branch.
3. Re-run `perk init` (or `perk doctor --fix`).

`perk init` is forgiving here: a malformed `SKILL.md`, a name/source collision, or an uncommitted
skill is reported as a **non-fatal warning** (init still exits 0 and converges everything else).
[`perk doctor`](./cli.md#perk-doctor) surfaces the same diagnostics as a **`repo-skills`** check
(`fail` on an invalid SKILL.md / no GitHub remote / fragment drift; `warn` on an uncommitted
skill). The only fatal case is the skills CLI failing to resolve a declared skill at sync time —
which the commit-push-resync sequence above fixes.

## A note on value types

The TypeScript config reader consumes **string leaf values only**, so `[trust] ci` and
`[objective] compact_threshold` must be written as **quoted strings** (`"true"`, `"0.8"`) — an
unquoted bool or number is ignored. By contrast, the `[compaction]` integers are read by the Python
plane and stay **native ints** (`reserve_tokens = 16384`).

## See also

- [CLI commands](./cli.md) — the `perk …` commands, including `perk init` and `perk doctor`.
- [In-session commands & tools](./in-session.md) — the warm `/…` commands and model-facing tools.
- [How to attach your own skill to a stage or command](../how-to/attach-a-skill-to-a-stage.md) —
  the `[[bindings]]` recipe.
- [How to run CI checks in a session](../how-to/run-ci-in-session.md) — the `[[ci]]` recipe.
- [Providers & issue backends](./providers-and-backends.md) — the supported provider set and the
  Linear backend reference; this page documents their config keys only.
- [How to select a plan or todo provider](../how-to/select-a-provider.md) /
  [How to switch the issue backend to Linear](../how-to/switch-to-linear.md) — the selection recipes.

---

← Back to the [reference router](index.md).
