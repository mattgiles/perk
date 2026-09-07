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
   `[providers]`, `[skills]`, `[pi]`, `[[bindings]]`. `[pi] agent_dir` reads **both files from
   the main checkout**, even from a linked worktree; worktree-local edits are not consulted.
4. `[linear] api_key` is **local-only**: perk reads it only from `.perk/local.toml`, and an
   exported `LINEAR_API_KEY` takes precedence.

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
| `setup` | array of strings | _(none)_ | Shell commands run via `bash -lc`, in order, inside each **newly materialized** worktree (freshly created *or* restored from the remote plan branch) before `pi` starts. A non-zero exit / timeout / missing `bash` **aborts the launch**; the pending-setup marker makes the next run retry the hook (a failed setup is never silently skipped). Command output is captured and shown only on failure. Skipped on valid local resume/reuse, dry-runs, and the remote runner. Overlay-aware (a local `setup` replaces this one wholesale). |

```toml
[worktree]
root = ".worktrees"
setup = ["uv sync"]
```

### `[workflow]`

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `plan_authoring` | string | _(none)_ | Appended into the plan-authoring context injection in `plan` sessions. Gotcha: a bare skill name in addendum prose is only model-reachable when that skill is model-invocable; a skill hidden via `disable-model-invocation: true` must be referenced with its read path (`.agents/skills/<name>/SKILL.md`). |
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

Array-of-tables; each row is one check. Consumed by the in-session CI executor (warm `/ci` gives
the one-line overall summary; the `run_ci` tool returns the detailed per-check report); `/ready`
does not run them — it marks the draft PR ready (and, for a stacked layer, records the handoff
stamp); run the checks first. Checks run
**concurrently**; declared order governs the detailed **report** order, not execution order — each
row must be independently runnable (sequence inside one `command`, e.g. `"build && test"`). `/ci`
/ the `run_ci` `check` argument accept a single name or a comma-separated list.

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
back to the behavior-preserving default. The retired `review`, `askuser`, and `todo` keys **hard-fail
config load** with removal guidance — the PR-review surface is picked by the command itself
(`/pr-review-terminal` = hunk, `/pr-review-browser` = plannotator), the `ask_user_question`
questionnaire tool is **built-in** (perk installs `npm:@juicesharp/rpiv-ask-user-question` for
every repo), and the todo checklist overlay is **built-in** (perk installs
`npm:@juicesharp/rpiv-todo` for every repo); remove `review` / `askuser` / `todo` from
`[providers]` if present.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `plan` | string | `perk-plan` | Plan-authoring provider. |
| `footer` | string | `perk-footer` | Footer provider. |
| `web` | string | `pi-web-access` | Web search/fetch provider. |

```toml
[providers]
plan = "perk-plan"
footer = "perk-footer"
web = "pi-web-access"
```

The supported set, postures, and selection mechanics are in
[providers-and-backends.md](./providers-and-backends.md).

### `[issues]`

Where canonical plan / learn / objective issues live. **Committed-only** (overlay ignored), read
from the **main checkout's** config even inside a linked worktree — a worktree's checkout state
can never flip the canonical store.

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

The key rarely needs writing by hand: when the committed `[issues] backend` is `"linear"` (with
a `team`) and no key resolves, **interactive `perk init`** prompts for it (hidden input),
validates it against Linear, and persists it here atomically — tightening the file to mode
`0600` and refusing unless the file is provably untracked and gitignored. The prompt never runs
under `--no-interactive`, a non-TTY stdin, or `--json`.

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
>
> perk also **seeds** `"tuiMode": "fullscreen"` into the same slice — but only when the key is
> absent (seeded once, never overwritten). To opt out, set `"tuiMode": "regular"` in
> `.pi/settings.json`; the value survives init/doctor. Note pi's `/settings` toggle writes the
> **global** settings file, which the committed project key overrides — the durable opt-out is
> the project key itself.

### `[models.subagents]`

Per-agent model overrides for perk's own project agents. **Fixed-key** — no effect on your custom
subagents (they set `model` in frontmatter). An absent key falls back to the agent's frontmatter
default.

| Key | Type | Default |
| --- | --- | --- |
| `pr-reviewer` | string (model id) | _(frontmatter default)_ |
| `review-classifier` | string (model id) | _(frontmatter default)_ — consumed by the `classify_review_feedback` tool at execute time |
| `objective-explorer` | string (model id) | _(frontmatter default)_ — consumed by the `explore_objective_node` tool at execute time |
| `conflict-resolver` | string (model id) | _(frontmatter default)_ — read at `resolve_submit_conflicts` execution for submit/address; retained continuation still uses its script |
| `learn-analyst` | string (model id) | _(frontmatter default)_ |
| `adversarial-reviewer` | string (model id) | _(frontmatter default)_ |
| `draft-reviewer` | string (model id) | _(frontmatter default)_ |
| `harvest-analyst` | string (model id) | _(frontmatter default)_ |
| `dream-analyst` | string (model id) | _(frontmatter default)_ — consumed by the `run_dream_wave` tool at execute time |
| `dream-reducer` | string (model id) | _(frontmatter default)_ — consumed by the `run_dream_wave` tool at execute time |
| `session-auditor` | string (model id) | _(frontmatter default)_ — **dev-only** (perk's own repo's session-audit judgment wave; dormant in consumer repos) |

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

Submit/address conflict resolution consumes this existing override through native foreground
structured delegation (including `inherit` and native ordered fallbacks), not model-authored
launch text. No new config key is added. The native engine setting `worktree` in
`join(getAgentDir(), "extensions/subagent/config.json")` must be absent/false (or the file missing).
True, nonboolean, malformed/unreadable or activation-changed settings refuse; inspect/correct and
reload rather than allocating a second worktree or switching mode. Reload does not clear retained
`perk-submit-conflict.lock` files in the canonical per-worktree Git directory. Recovery is human-
only after all sessions/writers/subprocesses are quiescent; PID death alone is insufficient.

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

### `[pi]`

Pi-process launch knobs. `agent_dir` loads a project `models.json` for custom providers or
per-model overrides by injecting **`PI_CODING_AGENT_DIR`** into every **cold-local Pi launch**.
Off by default; no auth seeding or session-dir pinning.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `agent_dir` | string (path) | _(unset — Pi's normal directory)_ | Relative → **main checkout root**; absolute as-is; `~` expands. Blank → disabled. |

```toml
[pi]
agent_dir = ".pi/agent"
```

**Effective read:** BOTH `.perk/config.toml` and `.perk/local.toml` come from the **main
checkout**, not the invocation checkout or a caller's preloaded config. This is uniform across
all cold-local doors, including seeded/skills/objective doors invoked from linked worktrees;
worktree-local config edits are not consulted. Local wins: put per-machine absolute paths in the
main checkout's `local.toml`, or use `agent_dir = ""` there to disable a committed value. No init
rerun is needed for a runtime config edit.

**Operator env wins:** a non-blank `PI_CODING_AGENT_DIR` skips the config read and is never
clobbered. Escape hatch: `PI_CODING_AGENT_DIR=~/.pi/agent perk plan`. A nested cold launch inherits
the parent session's injected value like an operator-set env var, so it wins over later edits too.
Empty/whitespace-only env values count as unset and are removed from the child environment when
no configured path replaces them, allowing Pi's normal directory fallback.

**Pure whole-directory redirect**, not a models-only overlay: `auth.json`, `trust.json`,
`sessions/`, `models-store.json`, global-tier `settings.json`, and other agent resources move
alongside `models.json`.

- OAuth credentials do not follow automatically: copy/symlink `auth.json` from `~/.pi/agent`
  if needed, or use env API keys. Protect it from git before copying.
- New `trust.json` starts empty: worktree stages already use `--approve`; main-checkout stages
  prompt for trust once.
- Logs go under `<agent-dir>/sessions/`. `/learn` still works (absolute `session_file` pointers).
  `perk-dev` session tools retain `~/.pi/agent/sessions`; use their `--session-root` override.
- Global settings move; the repo's `.pi/settings.json` remains the overriding project tier.

**Diagnostics:** a missing dir warns and launches (Pi creates an empty dir on demand, without
`auth.json`/`models.json`); an existing non-directory raises **`pi_agent_dir_invalid`**, because Pi
cannot create its sessions tree there. A malformed/ill-typed main config read or unresolvable
configured `~` home warns and launches without the redirect. Doctor's offline **`pi-agent-dir`**
check is quiet when unconfigured, ok when its probes pass, and warns for missing/non-directory/
hazardous paths. It includes path-resolution errors in check detail and defers parse/type errors
to the config check. No `--fix` arm; it diagnoses the configured directory regardless of operator env.

**Git safety:** init's managed block ignores `/.pi/agent/*` then opts in
`!/.pi/agent/models.json`. The contents-glob (not a directory exclusion) permits later user `!`
rules after the block for intentionally committed `settings.json` or `prompts/`. A non-conventional
in-repo path needs its own matching ignore rules **before copying credentials or launching**.
Doctor probes `auth.json`, `trust.json`, `settings.json`, `models-store.json`, auth/settings lock
files, and a nested `sessions/` log path, including nonexistent files; auth-only ignore coverage
is insufficient. Representative probes are not exhaustive proof: prefer a contents rule plus
narrow exceptions. It also warns on every tracked entry besides top-level `models.json`;
intentionally versioned settings still warn for operator assessment. Gitignore never untracks:
`git rm --cached <path>` keeps the file on disk while removing it from the index (`-r` for
directories). Never commit auth/trust/session data.

**Dry-run scope:** only generic stage launchers reaching the launch seam (plan/implement/submit/
address/land/…) preview the `PI_CODING_AGENT_DIR=<path>` line, `pi_agent_dir` JSON field, and
missing-dir warning. Seeded-door previews, skills create/refine, and `plan resume` return earlier
and omit these; their real launches still apply the same checks and injection.

**Non-goals:** `--remote`, the headless worker (throwaway agentDir), and a hand-run `pi` are
unaffected. Use direnv or your shell for a hand-run Pi redirect.

### `[compaction]`

How the session manages its context. The `enabled` / `reserve_tokens` / `keep_recent_tokens`
settings keys are **committed-only** — converged into `.pi/settings.json`'s `compaction` object by
`perk init` / `perk doctor --fix` (re-run to re-converge). Convergence is write-when-present and
leave-when-absent per key: absent keys leave existing settings untouched, while removing them
leaves previously written values in place to clean up by hand. The `objective_threshold` sibling
is **runtime-read** (overlay-aware) by the extension instead.

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

### Required skill installation

`dignified-python` remains required in every perk project. It is vendored from Dagster with its
upstream Apache 2.0 license and a documented local correction to the Python 3.13 annotation
guidance. The skills CLI delivers it from perk's managed source
(`https://github.com/mattgiles/perk`, ref `main`). Dagster is no longer a required source; the
remaining required external sources are Astral and Matt Pocock.

After upgrading perk, run `perk init` or `perk doctor --fix` to regenerate the managed declaration
and synchronize delivery. User-owned declarations and existing caches are not cleaned up.

Required installation does **not** force invocation or add a binding. The vendored skill's
frontmatter has no `stages:` declaration, so it remains exposed to all stages unless a
`[skills.stages]` override scopes it. Installation, exposure, and binding delivery remain separate.

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
explicitly set). **Perk-authored shipped skills declare `stages:` at source**; vendored skills
such as `ast-grep` and `dignified-python` preserve upstream frontmatter without that field.
The authored declarations make cold stage launches scoped **by default** once the repo's
`.agents/skills/` mirror is synced to current perk (`perk init` / `perk doctor --fix`); a mirror
predating the declarations stays unscoped (undeclared → all stages, fail-open) until its next
re-sync. **Once engaged, pi's global/user
skill dirs (`~/.pi/agent/skills`, `~/.agents/skills`) and project `.pi/skills` stop following
into stage sessions** — whitelist a personal collection per-user in the gitignored
`.perk/local.toml` (the standard migration move):

```toml
[skills]
include_dirs = ["~/.agents/skills"]
```

Cold stage launches only; fully fail-open (any composition problem degrades that launch back to
pi's full skill discovery with a warning). Bare interactive `pi` sessions and the remote runner
are untouched.

### `[[bindings]]`

Array-of-tables; each row attaches a skill to a stage or command. Every field is required, and
rows have no defaults.

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
The stub declares `stages: all` with a narrowing TODO — pick a stage-id list, `all`, or `[]`
(interactive-only) deliberately (see `[skills]` above).

Since the source resolves from the **default branch**, a new skill must be **committed + pushed**,
then `perk init` (or `perk doctor --fix`) re-run, before the skills CLI delivers it. `init` reports
a malformed SKILL.md / name collision / uncommitted skill as a **non-fatal warning** (exit 0);
`perk doctor`'s **`repo-skills`** check is `fail` on invalid SKILL.md / no GitHub remote / fragment
drift and `warn` on an uncommitted skill, an undeclared `stages:` (exposed to every stage launch),
or a declared stage id that isn't a registry stage.

---

*Canonical sources: `docs/user-docs/reference/configuration.md` for orientation, precedence,
the table map, and value types; family detail in
`docs/user-docs/reference/configuration/repository-layout.md`,
`docs/user-docs/reference/configuration/workflow-and-ci.md`,
`docs/user-docs/reference/configuration/backends.md`,
`docs/user-docs/reference/configuration/models-and-compaction.md`, and
`docs/user-docs/reference/configuration/skills-and-bindings.md`.*
