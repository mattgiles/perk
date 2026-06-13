# Configuration files

This page references perk's repo configuration: the `.pi/perk.toml` committed config and the
`.pi/perk.local.toml` per-user overlay. It describes the surface — every table and key — so an
operator can look up any setting. It does not teach a task (those belong in
[how-to/](../how-to/index.md)) or argue a design (those belong in
[explanation/](../explanation/index.md)). See the [user-docs router](../index.md) for how this
quadrant fits the whole.

Config tables are not introspectable the way the CLI's `--help` is, so — unlike the
[CLI reference](./cli.md)'s pytest existence guard — these entries are **human-reviewed for
accuracy** against the config readers (`perk/substrate/config.py`, `extension/substrate/config.ts`)
and the `perk init` templates. Accuracy is the governing virtue.

## Orientation

perk reads two files, both under `.pi/`:

- **`.pi/perk.toml`** — the committed project config. Edit it freely; it is shared by everyone
  working in the repo.
- **`.pi/perk.local.toml`** — a per-user overlay. It is gitignored, so it never leaves your
  machine; use it for personal overrides.

[`perk init`](./cli.md#perk-init) scaffolds both with a commented template, and
[`perk doctor`](./cli.md#perk-doctor) validates them. The schema grows as perk does; the tables
below are the live surface.

## Local overrides & overlay semantics

How the two files combine:

1. `.pi/perk.local.toml` overlays `.pi/perk.toml` — **local wins.** Tables merge recursively;
   scalar leaves replace.
2. A local `[[bindings]]` array **replaces the committed `[[bindings]]` array wholesale**
   (whole-array override, not element-wise merge) — arrays are leaves, so the local array
   substitutes for the committed one entirely.
3. **Committed-only tables ignore the overlay entirely.** `[issues]` and `[compaction]` are read
   from `.pi/perk.toml` **only**; a `.pi/perk.local.toml` value for either is silently ignored —
   this keeps the canonical issue store and the committed `.pi/settings.json` deterministic. A
   per-user compaction override belongs in pi's global `~/.pi/agent/settings.json` instead.

## Tables

### `[worktree]`

Where `perk worktree create` and the cold-door stage launchers place worktrees.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `root` | string | `.worktrees` | A relative path resolves against the repo root; an absolute path is used as-is. |

```toml
[worktree]
root = ".worktrees"
```

### `[workflow]`

Project-supplied plan-authoring guidance.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `plan_authoring` | string | _(none)_ | Appended into the plan-authoring context injection inside `plan` sessions. |

```toml
[workflow]
plan_authoring = "Prefer the smallest diff that satisfies the acceptance criteria."
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

An absent key falls back to the behavior-preserving default. This is **config-key reference depth
only**; the supported provider set, postures, and selection mechanics are in the
[providers & issue backends reference](./providers-and-backends.md), and the recipe is
[How to select a plan or todo provider](../how-to/select-a-provider.md).

```toml
[providers]
plan = "perk-plan"
todo = "perk-checkpoints"
```

### `[issues]`

Where canonical plan / learn / objective issues live. **Committed-only** — read from
`.pi/perk.toml`, never the overlay (a per-user override would fragment the canonical store).

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `backend` | string | `github` | `"github"` or `"linear"`. |
| `team` | string | _(none)_ | The Linear team key (e.g. `"ENG"`); required when `backend = "linear"`. |

Selecting `linear` also requires the `LINEAR_API_KEY` environment variable (a personal API key —
never stored in config). This is **config-key reference depth only**; the Linear backend reference
(auth, labels, identifiers, maturity) is in the
[providers & issue backends reference](./providers-and-backends.md#issue-backend--linear-reference),
and the recipe is [How to switch the issue backend to Linear](../how-to/switch-to-linear.md).

```toml
[issues]
backend = "linear"
team = "ENG"
```

### `[subagents]`

Per-agent model overrides for each perk-owned project agent.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `pr-reviewer` | string (model id) | _(agent frontmatter default)_ | Model for the PR-reviewer agent. |
| `review-classifier` | string (model id) | _(agent frontmatter default)_ | Model for the review-classifier agent. |
| `objective-explorer` | string (model id) | _(agent frontmatter default)_ | Model for the objective-explorer agent. |

An absent key falls back to the agent's frontmatter default.

```toml
[subagents]
pr-reviewer = "anthropic/claude-sonnet-4-5"
review-classifier = "anthropic/claude-haiku-4-5"
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
