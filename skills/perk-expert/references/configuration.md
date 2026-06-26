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

## Overlay semantics

1. `.perk/local.toml` overlays `.perk/config.toml` — **local wins.** Tables merge recursively;
   scalar leaves replace.
2. A local `[[bindings]]` array **replaces the committed array wholesale** (arrays are leaves — not
   element-wise merged). Include every binding you want active, not just additions.
3. **Committed-only tables ignore the overlay entirely.** `[issues]` and `[compaction]` are read
   from `.perk/config.toml` **only**; a local value for either is silently ignored (keeps the canonical
   issue store and the converged `.pi/settings.json` deterministic).

## Value-type gotcha

The **TypeScript** config reader consumes **string leaf values only**, so `[trust] ci` and
`[objective] compact_threshold` must be **quoted strings** (`"true"`, `"0.8"`) — an unquoted bool or
number is ignored. By contrast, the `[compaction]` integers are read by the **Python** plane and stay
**native ints** (`reserve_tokens = 16384`).

## Tables

### `[worktree]`

Where `perk worktree create` and the cold-door launchers place worktrees.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `root` | string | `.worktrees` | Relative resolves against repo root; absolute used as-is. |
| `setup` | array of strings | _(none)_ | Shell commands run via `bash -lc`, in order, inside each **freshly created** worktree before `pi` starts. A non-zero exit / timeout / missing `bash` **aborts the launch**. Skipped on resume/reuse, dry-runs, and the remote runner. Overlay-aware (a local `setup` replaces this one wholesale). |

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

### `[[ci]]`

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
[[ci]]
name = "lint"
command = "just lint"
glob = "*.py,*.ts"

[[ci]]
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

```toml
[providers]
plan = "perk-plan"
todo = "perk-checkpoints"
askuser = "perk-ask-user"
footer = "perk-footer"
web = "pi-web-access"
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

### `[subagents]`

Per-agent model overrides for perk's own project agents. **Fixed-key** — no effect on your custom
subagents (they set `model` in frontmatter). An absent key falls back to the agent's frontmatter
default.

| Key | Type | Default |
| --- | --- | --- |
| `pr-reviewer` | string (model id) | _(frontmatter default)_ |
| `review-classifier` | string (model id) | _(frontmatter default)_ |
| `objective-explorer` | string (model id) | _(frontmatter default)_ |
| `conflict-resolver` | string (model id) | _(frontmatter default)_ |

```toml
[subagents]
pr-reviewer = "anthropic/claude-sonnet-4-5"
review-classifier = "anthropic/claude-haiku-4-5"
```

### `[trust]`

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `ci` | string | _(unset)_ | The **quoted string** `"true"` marks the repo's `[[ci]]` checks trusted — they run without a per-session confirm (including headless). Only that exact string grants trust. |

```toml
[trust]
ci = "true"
```

### `[compaction]`

Tunes pi's auto-compaction for `perk <stage>` sessions. **Committed-only** — converged into
`.pi/settings.json`'s `compaction` object by `perk init` / `perk doctor --fix` (re-run to
re-converge). Native ints (not quoted strings).

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `enabled` | bool | _(pi default)_ | Auto-compaction on/off. |
| `reserve_tokens` | int (> 0) | _(pi default)_ | Tokens reserved for the response. |
| `keep_recent_tokens` | int (> 0) | _(pi default)_ | Recent tokens kept verbatim. |

```toml
[compaction]
enabled = true
reserve_tokens = 16384
keep_recent_tokens = 20000
```

### `[objective]`

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `compact_threshold` | string (decimal in `(0,1]`) | _(internal default)_ | Context-usage fraction that triggers compaction while an objective is active. **Quoted decimal string** (`"0.8"`) — the TS reader parses it with `Number.parseFloat`. |

```toml
[objective]
compact_threshold = "0.8"
```

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
