---
title: Adding a perk.toml config table — cross-plane parsing, placement, and convergence
read_when: You are adding a [table] or key to .perk/config.toml, deciding where a knob is consumed, adding a `local.toml` secret fallback, chasing a silently-vanishing config value, or `[[ci.checks]]` CI gating.
---

# Adding a `perk.toml` config table

perk's `.perk/config.toml` is read by **both planes** — the TypeScript extension (interior) and the
Python CLI (exterior) — through deliberately narrow parsers. Two additions (repo trust,
consumed at runtime by a TS gate; `[compaction]`, converged by `init` into `settings.json`) expose a
small set of cross-cutting decisions worth preserving. The durable insight is the **contrast** between
the two models, not either table in isolation.

> **Update (config schema v2, 2026-07, #1212).** The schema was redesigned with **no backwards
> compatibility**: `[trust] ci = "true"` → `[ci] trusted = true` (native boolean), `[[ci]]` →
> `[[ci.checks]]`, `[subagents]` → `[models.subagents]`, `[stages.<id>]` → `[models.stages.<id>]`,
> `[objective] compact_threshold = "0.8"` → `[compaction] objective_threshold = 0.8` (native
> float), `[models] model` → `[models] default`. Three consequences for this doc:
>
> - **The string-values-only TS parser fact is dead.** `parseTomlSubset` now reads native
>   booleans and numeric literals (`TomlScalar`); the quoted-string workaround is retired.
> - **The silently-vanishes trap now has a tripwire for retired spellings.** A `mode="before"`
>   validator on `ConfigFileModel` (and `ModelsTable`) raises `ConfigError` for each legacy
>   top-level table / the `[models] model` key, naming the new home — loud-over-silent. New
>   unknown keys still vanish via `extra="ignore"`, so the trap below remains real for typos.
> - Sections below that name old spellings (`[trust]`, `[[ci]]`, `[stages.<id>]`, `[subagents]`)
>   are **historical**: the placement/consumption reasoning stands; map spellings through the
>   rename table above. Trust now lives *with* the thing it governs (`[ci] trusted` above the
>   `[[ci.checks]]` rows it green-lights) — the "own section" placement rule below was superseded
>   by "settings that govern a thing live with the thing" once the map→array migration removed
>   the wholesale-map collision.
> - **Residual / validation risk: the TS-side fail-safe paths have thin regression coverage.**
>   The design is "Python trips loudly, TS fails safe" — but only the `[ci] trusted` native-bool
>   path has an explicit negative test (quoted `"true"` ⇒ untrusted). Nothing pins that a legacy
>   `[[ci]]` array yields empty `checks`, or that a legacy `[subagents]` table yields no model
>   overrides, under the new reader; and no test asserts that `perk doctor` on a legacy-config
>   repo surfaces the tripwire *actionably* (the config check fails with the field-path message,
>   but the legacy-spelling case specifically is unpinned). Cheap tests to add if the fail-safe
>   claim ever matters in anger.

## Placement: own `[section]` vs a sub-key

A sibling key under an existing table is silently mis-parsed when that table is consumed *wholesale*.
`loadPerkConfig` consumed the entire `[ci]` table as the named-checks map, so a `[ci] trust = …`
sub-key would have been swallowed as a (bogus) named check. Trust therefore had to be its own
`[trust]` section:

> **Update (#490):** `[ci]` migrated from a `name = "command"` **map** to a `[[ci]]`
> **array-of-tables** (each row `name`/`command`/optional `glob`), parsed by `parseCiChecks` into
> `CiCheck[]`. The wholesale-map collision footgun above **no longer applies** under
> array-of-tables (a `trust` key would just be an ignored row field) — but the placement decision
> (trust as its own `[trust]` section) stands and is now also the cleaner shape.

```toml
[trust]
ci = "true"
```

**General rule:** never add a non-homogeneous key under a table that is consumed wholesale as a map.
If the table *is* a map, the new knob needs its own section.

## Ill-typed values — the trap differs per plane

The two planes handle values they can't use differently:

- **TS — unsupported value shapes silently dropped.** *(Historical: pre-v2 the parser kept only
  string values, forcing quoted `ci = "true"` / `"0.8"` workarounds.)* `parseTomlSubset`
  (`extension/substrate/config.ts`) now reads strings plus **native booleans and numbers**
  (`TomlScalar`); anything else (dates, arrays, inline tables) is still silently dropped, and
  consumers guard with `typeof` checks (a string `"true"` no longer grants trust).
- **Python — ill-typed values raise.** The pydantic table models in `perk/substrate/config.py`
  no longer silently discard: an ill-typed value raises `ConfigError` (field-path message via
  `translate_validation_errors`), surfaced by doctor's `config` check. The `bool`-is-`int`-subclass
  trap (`isinstance(True, int)` is `True`, so `reserve_tokens = true` would otherwise read as `1`)
  is now an explicit `_reject_bool` before-validator on `CompactionTable` — it raises, never reads
  `true` as 1:

  ```toml
  [compaction]
  reserve_tokens = 16000
  ```

## Committed-only read vs the overlaid `load_config`

Most tables (`[providers]`, `[subagents]`, `[[bindings]]`) read through `load_config`, which overlays
`perk.local.toml` for per-user, session-transient overrides. Config that converges into a
**committed** artifact must not. `[compaction]` lands in `settings.json` (committed), so
`load_committed_compaction` (`perk/substrate/config.py`) reads committed `.pi/perk.toml` **only**, bypassing the
overlay — otherwise a per-user local override would produce a stray committed git diff. Per-user
overrides for such knobs belong in pi's native global `~/.pi/agent/settings.json` (pi merges it under
project settings).

**Rule of thumb:** the local overlay is safe for session-transient config, unsafe for config that
lands in committed files.

Committed-only knobs now have **three precedents** (`[compaction]`, `[issues]`, the
settings-convergence reads); the recipe is fixed: a pure `parse_*(raw)` parser + a
`load_committed_*(repo_root)` that reads `.pi/perk.toml` via `_read_toml` only, lets
`TOMLDecodeError` propagate, and stays OUT of the overlaid `Config` dataclass. Tests must include
the **"local overlay is ignored"** case — it's the whole point of the shape.

## The local-only secret-fallback reader (`perk.local.toml`)

A secret may now live in the **gitignored** `perk.local.toml` (never the committed `perk.toml`) — a
deliberate, documented relaxation of "Linear key in the environment only." `LINEAR_API_KEY`'s
`[linear] api_key` is read by `config.load_local_linear_api_key(repo_root)`, which reads
`.pi/perk.local.toml` **only** — the **inverse** of the `load_committed_*` family.

- **It resolves the MAIN checkout first (#730).** The reader reads from
  `git.main_worktree_root(repo_root) or repo_root`, so the gitignored secret is found from inside a
  linked worktree **without a file copy and without relying on the launch env-seed** (the
  `perk.local.toml` lives only in the main checkout; a worktree has none). The `or repo_root`
  fallback keeps every non-worktree / non-repo caller — including every `tmp_path`-rooted test —
  **byte-identical** (`main_worktree_root` returns `None` outside a repo). See
  `docs/learned/workflow/worktree-lifecycle.md` for the `main_worktree_root` primitive.

- **Critical divergence:** it is **fail-soft on `tomllib.TOMLDecodeError` (returns `None`)**, unlike
  the committed readers which **propagate** it for the config check to map. Rationale: a best-effort
  secret seed must never crash an otherwise-valid command, and a malformed `perk.local.toml` is
  surfaced nowhere else today.
- The key is **deliberately NOT added to the merged `Config` dataclass** (that would make it
  readable from the **committed** file and widen the surface) — a standalone reader, mirroring
  `load_committed_issues_team`. **Env still wins; config is a fallback.**
- This is a **third reader shape** alongside the committed-only and overlaid readers:
  *committed-only* (canonical-store knobs), *overlaid* (`load_config`, session-transient), and now
  *local-only* (best-effort secret fallback, fail-soft on malformed).

See `docs/learned/workflow/linear-backend.md` for the consumer side (the env-first /
config-fallback `client_from_env` seam + the worktree env bridge).

## The `[worktree] setup` overlay-aware config key (#652)

`[worktree] setup` (an array of shell command strings) parses through the `WorktreeTable` model —
an after-mode validator on `setup` strips each entry and drops blanks (a non-string element
raises) — and is **overlay-aware via `load_config`**: a `perk.local.toml` array **replaces
wholesale**. This contrasts with
`[issues]`/`[compaction]`, which deliberately bypass the overlay (they pick the canonical store).
The decision rule is reaffirmed: **overlay is safe for session-transient config (a per-user
worktree setup), unsafe for config that lands in a committed file or picks a canonical store.** See
`docs/learned/workflow/worktree-lifecycle.md` for the hook's `created`-flag dry-run asymmetry.

## Change-scoped CI gating: the `[[ci]]` glob convention (#490)

Each `[[ci]]` row may carry an optional `glob`; when present, the check is **skipped** unless a
changed file matches it. The cross-cutting facts below are what the `ciExecutor.ts` /
`parseCiChecks` code can't tell you on its own.

### The basename glob convention (a reconciled rule)

The glob→regex translation distinguishes `**` (→ `.*`, crosses `/`) from `*` (→ `[^/]*`, stays
within a path segment), but the **anchoring** is the subtle part. The rule perk actually ships is
the **gitignore/fnmatch convention**:

- A **slash-free** pattern matches the path's **basename at any depth** — `glob = "*.py"` matches
  `a/b/c.py`, not just a top-level `c.py`.
- A pattern **containing `/`** matches the **full repo-relative path**.

This was a reconciliation, not the plan's literal mechanism. The plan specified `*` → `[^/]*` over a
**top-level-anchored** full path (`^…$`) *and* specified perk's own config as `glob = "*.py"` with a
test expecting `*.py` to match `a/b/c.py`. Those contradict: `^[^/]*\.py$` does **not** match
`a/b/c.py`, so a top-level-anchored `*.py` would silently false-skip Python checks whenever
`src/perk/foo.py` changed (the repo has no top-level `.py`) — defeating the whole feature. **Lesson:**
when a plan's stated mechanism contradicts its own examples/config, the examples + the feature's
purpose win — implement what makes the feature correct and reconcile via a well-known convention,
not the literal-but-broken rule.

### The skip-result shape

A skipped check does **not** execute its command: its `CiCheckResult` is `{skipped:true,
passed:true, exitCode:0, shown:"", …}`. Two non-obvious points:

- **Skips never fail** — an all-skip run is `passed:true`.
- `renderCiProse` needs the glob for its `⊘ name (skipped — no changed files match <glob>)` line, so
  the skipped result carries an **extra optional `glob?` field purely for the prose**. Don't smuggle
  the glob through `shown` (which must stay `""`).

### Run-all-only gating discipline (never skip on uncertainty)

The gating only applies to a *run-all* invocation, and the git work is computed defensively:

- Compute `changedFiles` **once**, and **only** when some selected row is actually globbed (no git
  work otherwise).
- An explicit `only` check **always runs** — no glob gate, no git work.
- `changed === null` (any git error → fail-open) **runs everything** — never skip on uncertainty,
  never a false success. `changedFiles` is merge-base vs detected trunk ∪ untracked, and trunk
  detection probes both `main`/`master`, so default-branch-name uncertainty is harmless.

### The harness limitation (where to put gating tests)

The registered `run_ci` **tool** path calls `runCiImpl` with prod `piExec` only — there is **no
injectable `exec`**, so a harness test cannot inject a fake git/exec through the tool. End-to-end
gating coverage therefore needs EITHER a **real git repo** (init + a branch + a docs-only commit to
prove a real skip) OR the **fail-open path** (a non-git scaffold cwd → git errors → check still
runs). Deterministic injected-exec gating lives instead at the `runCiChecks` **unit layer**.

### Plumbing boundary: Python never reads `[ci]`

`[[ci]]` is a **TS-only** concern — no Python plumbing reads it (init only scaffolds a commented
`[[ci]]` example in `PERK_TOML_TEMPLATE`). To make the globs gate per-toolchain, the **justfile
split** `lint`/`typecheck`/`test` into per-language recipes (`-py`/`-js`) with aggregates retained,
so a `glob = "*.py"` row can run only the Python toolchain.

## Two consumption models

- **Interior gate (`[trust]`).** Consumed at runtime by a TS gate — `decideCiScope` in
  `extension/doors/ciExecutor.ts`. The session must honor it live.
- **init convergence (`[compaction]`).** Converged by `init` into `settings.json`, which pi reads
  natively at boot. No extension change is even possible here: the interactive pi CLI builds its
  `SettingsManager` *before* extensions load, so the extension can never set
  `reserveTokens`/`keepRecentTokens`.

**The decision:** a knob the *session* must honor at runtime → interior gate; a knob pi consumes from
`settings.json` → init convergence.

## Convergence composition (the settings-targeting path)

Add a settings-targeting converger by composing it *inside* `_converge_settings` (`perk/convergence/init.py`):
`_converge_compaction` mutates the shared `settings` dict before the `json.dumps` no-op short-circuit,
so it rides the existing `settings-wiring` `ManagedConvergence` for free — **no new doctor check**.
This mirrors `_converge_provider_packages`. Fold returned change fragments into the init/doctor `parts`
summary. See `init-doctor.md` for the managed-convergence SSOT.

### Non-destructive write-when-present / leave-when-absent

- **Present** ⇒ merge mapped keys over any existing `settings.json` block (perk keys win, hand-added
  keys survive).
- **Absent** ⇒ leave the block untouched (perk can't prove ownership of a bare key, so removal is
  unsafe).

**Residual wrinkle:** deleting `[compaction]` from `perk.toml` leaves a stale `settings.json` block to
clean up by hand.

### snake_case → camelCase mapping in the table model

The TOML→settings key mapping lives in `CompactionTable.to_settings()`, behind
`load_committed_compaction`: `enabled`→`enabled`, `reserve_tokens`→`reserveTokens`,
`keep_recent_tokens`→`keepRecentTokens`. Absent keys are omitted (pi fills its own defaults);
ill-typed keys raise `ConfigError`.

## Mirror the existing selection shape

Both changes followed the `parseProvidersSelection` / `_parse_providers_selection` shape — an
always-present object with absent/ill-typed keys omitted — and reused its test matrix (absent → `{}`,
parses, false/blank → absent, local-overlay-wins). When a gate's pure signature grows a field (e.g.
`decideCiScope` gaining `trusted`), it's a small cross-file contract: update **all** call sites + the
test matrix in lockstep.

## The cloned-repo tradeoff (`[trust]`)

A repo committing `[trust] ci` auto-runs its own CI and suppresses even the headless fail-closed refuse
(documented in `shared/contracts.md`). `perk init` therefore scaffolds only a *commented* `[trust]`
example so new repos stay safe-by-default. No Python parser mirrors `[trust]` — it is pure-TS /
interior-only.

## Single-plane (Python-only) launch-seam config feature (`[stages.<id>]`)

The cross-cutting insight: **a config knob that only shapes the local cold-launch `pi` argv needs no
cross-plane work.** `[stages.<id>]` lets a repo pass per-stage `pi` args (e.g. a per-stage `--model`)
at the cold launch. The end-to-end recipe is single-plane (Python only):

- **Parser** (`config.py`): a frozen stdlib `@dataclass` held **by identity** in both `ConfigFileModel`
  (pydantic) and the frozen `Config` — the exact `user_bindings` precedent
  (`revalidate_instances="never"` preserves instances; `to_domain()` does explicit attribute copy).
  LBYL silent-omit (non-dict table → `{}`; blank/ill-typed sub-keys dropped; an empty sub-table stays
  inert). **Unknown stage ids are KEPT at the parser** — registry validation is the doctor check's
  job, which keeps `config.py` free of a registry import.
- **Injection** (`launch_stage`): splice the per-stage model args into the **single** argv vector,
  mirroring the existing `--approve` trust-arg precedent. Two free wins from building argv **once
  before** the `dry_run` branch: `--dry-run --json` previews the injected flags, and
  inject-before-pass-through gives user-`--model`-wins for free (see `cold-door-launch.md`'s
  build-argv-once rule). The remote path early-returns before this block, so `--remote` carries no
  per-stage args (a documented non-goal).
- **Doctor check**: returns **`None` to contribute nothing when unconfigured** (keeps a clean repo's
  `perk doctor` quiet), wired with a walrus conditional-append and **NOT** gated behind `if verify:`
  (offline: reads config + the bundled registry). Malformed-TOML → `warn` deferring to the config
  check; a registry error skips the stage-id check (the registry check owns that finding — don't
  double-fail). Reuses an existing check group → no `GROUP_ORDER` change. No `--fix` arm (user-owned
  config).

Specifics worth keeping: the TS plane needs **no change** (`parseTomlSubset` keys `[stages.*]` as an
unread section); overlay-aware for free (the recursive `_overlay` leaf-merges nested `[stages.<id>]`
tables); `contracts.md` is deliberately **not** amended (it documents only cross-plane config — a
Python-launch-only knob is out of scope) while `docs/user-docs/` + the `perk-expert` reference mirror
**are** updated.

Residual scope: `[stages.<id>]` applies only where a stage cold-launches an interactive pi session;
deterministic `--json` workers launch no pi (inert there); warm in-session transitions inherit the
launched session's model; the remote runner is unaffected.

## Cross-references

- `extension/substrate/config.ts` — `parseTomlSubset` (the scalar-subset TS parser); `parseCiChecks` (`[[ci.checks]]` → `CiCheck[]`)
- `extension/doors/ciExecutor.ts` — `decideCiScope` (the `[ci] trusted` interior gate); `changedFiles`/`matchesGlob`/skip plumbing (the `[[ci.checks]]` glob gating)
- `perk/substrate/config.py` — the pydantic table models (`ConfigFileModel`, `CompactionTable`,
  `WorktreeTable`, …); `load_committed_compaction`, `load_committed_issues_backend` (the
  committed-only reads)
- `perk/convergence/init.py` — `_converge_settings` / `_converge_compaction` composition
- `docs/learned/workflow/init-doctor.md` — the managed-convergence SSOT
- `docs/learned/workflow/provider-seam.md` — the mirrored selection shape
- `docs/learned/workflow/linear-backend.md` — the consumer side of the local-only `[linear] api_key` reader
- `docs/learned/workflow/worktree-lifecycle.md` — the `[worktree] setup` hook + the `created`-flag dry-run asymmetry
- `shared/contracts.md` — the `[trust]` + `[compaction]` cross-plane prose
