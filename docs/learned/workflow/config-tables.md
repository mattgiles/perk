---
title: Adding a `.perk/config.toml` config table — cross-plane parsing, placement, and convergence
read_when: You are adding a [table] or key to .perk/config.toml, deciding where a knob is consumed, anchoring a committed read to the main checkout, a `local.toml` secret fallback, or CI-check gating.
cluster: config-and-convergence
---

# Adding a `.perk/config.toml` config table

perk's `.perk/config.toml` is read by **both planes** — the TypeScript extension (interior) and the
Python CLI (exterior) — through deliberately narrow parsers. Two live tables are the archetypes:
`[ci] trusted`, consumed at runtime by a TS gate, and `[compaction]`, converged by `init` into
`settings.json`. The durable insight is the **contrast** between the two models, not either table
in isolation.

## Distillation

- Placement: settings that govern a thing live WITH the thing (`[ci] trusted` beside its
  `[[ci.checks]]` rows; the `[models]` namespace); never add a non-homogeneous key under a table
  consumed wholesale as a map — "Placement: settings that govern a thing live with the thing".
- Ill-typed values trap differently per plane: TS silently drops unsupported shapes (fail-safe);
  Python raises `ConfigError`. Unknown keys still vanish via `extra="ignore"`, while retired
  spellings trip loudly — "Ill-typed values…", "Schema v2 migration (dated…)".
- Three reader policies: committed-only (config that lands in a committed artifact or selects a
  canonical store), the overlaid `load_config` (session-transient), and the local-only secret
  fallback — "Committed-only read vs the overlaid `load_config`", "The local-only
  secret-fallback reader".
- Config authority, overlay policy, and resolution phase are separate decisions (`[pi] agent_dir`
  reads committed + local overlay FROM THE MAIN CHECKOUT at the consumer); a validated path string
  still has a runtime `expanduser()` boundary; the repo's own committed table is guarded against
  its generated `settings.json` — "Main-checkout anchoring…", "Ill-typed values…", "Convergence
  composition".
- `[[ci.checks]]` rows are an execution contract (declared order, glob change-scoping decides
  what gates a diff) — "The `[[ci.checks]]` execution contract and change-scoped gating".
- Two consumption models decide where a knob lands: runtime interior gate vs init convergence
  into `settings.json` (pi reads settings before extensions load); `[models]` is one validated
  table feeding three paths (init convergence, Python cold launch, TS runtime) — "Two consumption
  models", "The `[models]` namespace — three consumption paths under one table".
- Historical: "Schema v2 migration (dated 2026-07)" holds the retired spellings (`[trust]`,
  `[[ci]]`, `[stages.<id>]`, `[subagents]`, `[objective]`, `[models] model`), their tripwires
  and pins.

## Placement: settings that govern a thing live with the thing

A knob sits in the table of the thing it governs, so the operator finds it beside its subject and
the parser validates related keys together:

- `[ci]` holds `trusted` beside the `[[ci.checks]]` rows it green-lights — both read by the TS
  plane (`loadPerkConfig`); Python only trips on the legacy list shape.
- `[models]` holds `default`/`thinking`/`stages.<id>`/`subagents` and validates as one
  `ModelsTable` (§"The `[models]` namespace").
- `[compaction]` holds the settings-converged keys and the TS-read `objective_threshold`.

**General rule:** never add a non-homogeneous key under a table that is consumed wholesale as a map.
If the table *is* a map, the new knob needs its own section. The array-of-tables rows
(`[[ci.checks]]`, `[[bindings]]`) cannot collide — a stray row field is simply ignored — so today
the rule bites in one place: `[models.stages]` is a stage-id-keyed map (`dict[str, StageTable]`),
so a cross-stage knob cannot be a sibling key there (a scalar fails `StageTable` validation; a
sub-table is kept as a bogus stage id doctor warns about) — the repo-wide default sits one level
up as `[models] default`. It bites again whenever a NEW map-shaped table appears. The `[trust]`
instance that once forced an own-section rule is told in §"Schema v2 migration".

## Ill-typed values — the trap differs per plane

The two planes handle values they can't use differently:

- **TS — unsupported value shapes silently dropped.** `parseTomlSubset`
  (`extension/substrate/config.ts`) reads strings plus **native booleans and numbers**
  (`TomlScalar`); anything else (dates, arrays, inline tables) is silently dropped, and consumers
  guard with `typeof` checks (a string `"true"` does not grant trust).
- **Python — ill-typed values raise.** The pydantic table models in `src/perk/substrate/config.py`
  no longer silently discard: an ill-typed value raises `ConfigError` (field-path message via
  `translate_validation_errors`), surfaced by doctor's `config` check; retired top-level spellings
  trip the schema-v2 tripwire (§"Schema v2 migration") rather than vanishing. The
  `bool`-is-`int`-subclass trap (`isinstance(True, int)` is `True`, so `reserve_tokens = true`
  would otherwise read as `1`) is an explicit `_reject_bool` before-validator on
  `CompactionTable` — it raises, never reads `true` as 1:

  ```toml
  [compaction]
  reserve_tokens = 16000
  ```

**Validated path strings still have a runtime resolution boundary.** `Path.expanduser()` can raise
`RuntimeError` (an unknown `~user`, an unresolvable home) *after* TOML/type validation succeeded.
Translate it into a field-named `ConfigError` at the effective-reader boundary
(`effective_pi_agent_dir` does this for `[pi] agent_dir`) so launch applies its warning/fallback
posture and doctor reports an actionable diagnostic — don't broaden consumers to catch arbitrary
exceptions.

## Committed-only read vs the overlaid `load_config`

Most tables (`[providers]`, `[models.stages.<id>]`, `[models.subagents]`, `[worktree]`,
`[[bindings]]`) read through `load_config`, which overlays the gitignored `.perk/local.toml` for
per-user, session-transient overrides. Config that converges
into a **committed** artifact must not. `[compaction]` lands in `settings.json` (committed), so
`load_committed_compaction` (`src/perk/substrate/config.py`) reads committed `.perk/config.toml` **only**, bypassing the
overlay — otherwise a per-user local override would produce a stray committed git diff. Per-user
overrides for such knobs belong in pi's native global `~/.pi/agent/settings.json` (pi merges it under
project settings).

**Rule of thumb:** the local overlay is safe for session-transient config, unsafe for config that
lands in committed files — the scope of "unsafe" is *committed artifacts*, not every canonical
store (see the authority/overlay/phase distinction under "Main-checkout anchoring" below).

Committed-only knobs have **three precedents** (`[compaction]`, `[issues]`, and
`load_committed_models_table` for `[models] default`/`thinking`); the recipe is fixed: a pure
`parse_*(raw)` parser + a `load_committed_*(repo_root)` that reads `.perk/config.toml` via
`_read_toml` only, lets `TOMLDecodeError` propagate, and stays OUT of the overlaid `Config`
dataclass. Tests must include the **"local overlay is ignored"** case — it's the whole point of
the shape.

### Main-checkout anchoring for committed canonical-store selectors

The `[issues]` backend/team committed-only readers (`_committed_issues` in
`src/perk/substrate/config.py`; `resolveIssueBackendId` in `extension/substrate/config.ts`) resolve
`git.main_worktree_root(repo_root) or repo_root` / `mainCheckoutRoot(cwd)` **before** reading the
committed config.

- This is the **second anchoring precedent, for the inverse reason** of the #730
  `load_local_linear_api_key` one (documented in the local-only-reader section below): the
  gitignored secret is anchored because it *only exists* in the main checkout; the committed
  `[issues]` selection is anchored because it is **repo-durable identity** — a linked worktree
  detached at a commit without `.perk/` (git deletes the file from the checkout) must never
  silently flip a Linear repo to the GitHub default.
- Deliberate semantics: an in-worktree `[issues]` edit takes effect only when it reaches the main
  checkout — the canonical-store selection must not fork mid-plan.
- **Scope guard:** init-convergence reads (`load_committed_compaction`,
  `load_committed_models_table`) stay unanchored — they converge the *current checkout's*
  artifacts, a different lifecycle. Anchor a committed read only when it selects a canonical
  store/identity.
- Diagnosis note: committed reads are plain filesystem reads of the invocation root — not env
  resolution, not `git show HEAD:...` (both were chased as wrong mental models before the root
  cause).
- **The execute-time worktree overlay rule.** A flow tool executing with a linked worktree as cwd
  must decide *per file* whether a config source is committed (worktree-anchored — branch
  semantics: the worktree's checked-out copy is the right read) or local/gitignored
  (main-checkout-anchored — worktrees never materialize it). The realized shape is
  `subagentModel` in `extension/substrate/config.ts`: committed config read from the worktree,
  the local overlay read from the main checkout, a worktree-local overlay still winning when one
  exists — byte-identical behavior in the main checkout — pinned by linked-worktree unit tests.
- **Config authority, overlay policy, and resolution phase are separate decisions.** Main-checkout
  anchoring does not imply committed-only input: repo-wide issue identity uses a committed-only
  reader, while the per-user Pi credential/session store (`[pi] agent_dir`) intentionally reads
  committed config AND its local overlay **from the main checkout** (`effective_pi_agent_dir`) —
  the store must not fork per worktree, but a per-user redirect is exactly what the overlay is
  for. A caller-supplied `Config` may have been loaded from a linked worktree, so it cannot
  establish this authority: use one consumer-side effective reader shared by launch and doctor,
  keep the raw value in `Config`, and resolve at the consumers — never add git/filesystem work to
  `to_domain`. Test conflicting main/worktree files and a main-only local overlay, not just path
  joining.

### Global `subprocess.run` fakes break when a code path grows a git shell

- `tests/test_run_worker.py` monkeypatches the **global** `subprocess.run` (via the shared module
  object) to intercept the worker spawn with a stand-in lacking `stdout`/`stderr`. Adding
  `git.main_worktree_root(...)` inside `_committed_issues` routed a new `git rev-parse` through
  that fake and broke 7 unrelated-looking tests with an `AttributeError` on the stand-in.
- Fix shape: an autouse fixture pinning `git.main_worktree_root` to its real non-repo result
  (`None` → fall back to the given root) keeps those tests hermetic without masking behavior
  (see `stub_main_worktree_root` in `tests/test_run_worker.py`).
- The general rule: if adding a git-shelling call makes a *distant* test suite fail on a fake
  `subprocess.run` return object, look for a test-file-level global subprocess fake — stub the
  new seam at module level (matching its real environment result) rather than widening the fake.

## The local-only secret-fallback reader (`.perk/local.toml`)

A secret may now live in the **gitignored** `.perk/local.toml` (never the committed
`.perk/config.toml`) — a
deliberate, documented relaxation of "Linear key in the environment only." `LINEAR_API_KEY`'s
`[linear] api_key` is read by `config.load_local_linear_api_key(repo_root)`, which reads
`paths.local_config_file` (`.perk/local.toml`) **only** — the **inverse** of the
`load_committed_*` family.

- **It resolves the MAIN checkout first (#730).** The reader reads from
  `git.main_worktree_root(repo_root) or repo_root`, so the gitignored secret is found from inside a
  linked worktree **without a file copy and without relying on the launch env-seed** (the
  `.perk/local.toml` lives only in the main checkout; a worktree has none). The `or repo_root`
  fallback keeps every non-worktree / non-repo caller — including every `tmp_path`-rooted test —
  **byte-identical** (`main_worktree_root` returns `None` outside a repo). See
  `docs/learned/workflow/worktree-lifecycle.md` for the `main_worktree_root` primitive.

- **Critical divergence:** it is **fail-soft on `tomllib.TOMLDecodeError` (returns `None`)**, unlike
  the committed readers which **propagate** it for the config check to map. Rationale: a best-effort
  secret seed must never crash an otherwise-valid command, and a malformed `.perk/local.toml` is
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
raises) — and is **overlay-aware via `load_config`**: a `.perk/local.toml` array **replaces
wholesale**. This contrasts with
`[issues]`/`[compaction]`, which deliberately bypass the overlay (they pick the canonical store).
The decision rule is reaffirmed: **overlay is safe for session-transient config (a per-user
worktree setup), unsafe for config that lands in a committed file or picks a canonical store.** See
`docs/learned/workflow/worktree-lifecycle.md` for the hook's `created`-flag dry-run asymmetry.

## The `[[ci.checks]]` execution contract and change-scoped gating (#490)

Each `[[ci.checks]]` row may carry an optional `glob`; when present, the check is **skipped**
unless a changed file matches it. The cross-cutting facts below are what the `delivery/ci.ts` /
`parseCiChecks` code can't tell you on its own.

### The concurrent execution contract

Checks run **concurrently** — wall time is the max of the rows, not the sum. Declared order
governs **report** order only, so each row must be independently runnable: an ordered sequence
belongs inside one row's `command` (`build && test`), never across rows. The changed-file set is
computed **once**, before any check launches.

**Explicit selection** (`/ci <names>` / `run_ci`'s `check` param) accepts a comma-separated name
list. Selection follows *declared* order (not argument order) and bypasses glob gating entirely —
no git work.

### The selector-widening trap (single-key lookup → delimiter-split list)

When widening a single-key exact-match lookup into a delimiter-split multi-key selector, audit
what the old exact match silently tolerated — or reject those inputs explicitly at the boundary.
Two concrete regressions from widening `only` to a comma list, both fixed and regression-tested
in `extension/delivery/ci.ts`'s `runCiChecks` suite:

- **Delimiter-containing names became unselectable** — the config boundary accepts any nonblank
  name, including one containing `,`; the old selector matched it exactly. Fix pattern: try an
  **exact name match before tokenizing**; only a non-matching string is split.
- **Duplicate names broadened the selection** — a `filter` ran *every* row with a requested name
  (newly concurrent, racing on the same scratch target). Fix pattern: each requested name selects
  the **first declared row** (the pre-concurrency `find` semantics).

`extension/delivery/ci.test.ts` is the reusable example of proof-grade concurrency tests: a
start/end ordering log (all starts before any end) plus a causal deferred-resolution gate — no
timers — and a shared-`AbortSignal` propagation test that settles fail-closed.

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
`src/perk/<module>.py` changed (the repo has no top-level `.py`) — defeating the whole feature. **Lesson:**
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

### The scope-aware CI report contract (run-all vs subset)

The gating above makes a `run_ci` report's meaning **scope-dependent**:

- **A green run-all report is *definitive*** — the change is verified; no follow-up
  re-verification (no re-running checks, subsets, or the underlying commands). Glob-skipped
  checks are intentionally out of scope for the diff.
- **A green subset report is not** — explicitly-selected checks prove only themselves; a subset
  green only points at the run-all gate still to come.
- **Precondition for "definitive"**: the `[[ci.checks]]` rows must mirror the repo's **full**
  verification gate. perk's own gap was `changelog-check` — absent from the rows until plan #1568
  closed it, so a "green run-all" silently under-verified. `setup` is deliberately excluded: it is
  `[worktree] setup`-hook-owned env prep, not verification.
- **The scope of "definitive" today.** perk's rows mirror `just ci` **except** that the JS row runs
  only the fast node:test tier (`just test-js-fast`); the slow manifest
  (`extension/testing/jsTestTiers.ts::SLOW_JS_TEST_FILES`) runs in `just ci` / GitHub CI and ad hoc
  via `just test-js-slow`, and the opt-in prose suites are outside both. So a green run-all
  `run_ci` is definitive for everything the rows cover; a change to a slow-tier file, or to code
  one exercises, needs `just test-js-slow` (or the file itself) run by the implementer.
  `test-py-slow` is host-dependent: its live smokes skip without an admitted PATH `pi`
  (`docs/learned/pi/extension-api.md` § Dogfooding, the floor-lockout bullet).
- **Two cadence registers**, and guidance must name both: *iteration* (narrow targeted checks — a
  single test file, one check name — cheap and frequent) vs *gate* (ONE run-all, immediately
  before submit, terminal). Cadence guidance that says "run `run_ci` often" without naming the
  registers recreates last-mile verification thrash.

### The harness limitation (where to put gating tests)

The registered `run_ci` **tool** path calls `runCiImpl` with prod `piExec` only — there is **no
injectable `exec`**, so a harness test cannot inject a fake git/exec through the tool. End-to-end
gating coverage therefore needs EITHER a **real git repo** (init + a branch + a docs-only commit to
prove a real skip) OR the **fail-open path** (a non-git scaffold cwd → git errors → check still
runs). Deterministic injected-exec gating lives instead at the `runCiChecks` **unit layer**.

### Plumbing boundary: Python never reads `[ci]`

Python never *consumes* `[ci]`: `ConfigFileModel` drops the dict via `extra="ignore"` and only
trips on the legacy list-valued spelling (§"Schema v2 migration"). `[[ci.checks]]` is a
**TS-only** concern — init only scaffolds a commented `[[ci.checks]]` example in
`PERK_TOML_TEMPLATE` (`src/perk/convergence/init/templates.py`). To make the globs gate
per-toolchain, the **justfile split** `lint`/`typecheck`/`test` into per-language recipes
(`-py`/`-js`) with aggregates retained, so a `glob = "*.py"` row can run only the Python toolchain.

## Two consumption models

- **Interior gate (`[ci] trusted`).** Consumed at runtime by `decideCiScope`
  (`extension/delivery/ci.ts`): `trusted` short-circuits to `run` alongside the
  `--allow-project-ci` flag and a per-session UI approval, else confirm-with-UI /
  refuse-headless. `runCiImpl` (`extension/pi/v1/delivery/ci.ts`) feeds it from
  `loadPerkConfig(cwd).ci.trusted`. The session must honor it live.
- **init convergence (`[compaction]`, `[models] default`/`thinking`).** Converged by `init` into
  `settings.json` via `_converge_settings`, which pi reads natively at boot. No extension change
  is even possible here: the interactive pi CLI builds its
  `SettingsManager` *before* extensions load, so the extension can never set
  `reserveTokens`/`keepRecentTokens`.

**The decision:** a knob the *session* must honor at runtime → interior gate; a knob pi consumes from
`settings.json` → init convergence.

## Convergence composition (the settings-targeting path)

Add a settings-targeting converger by composing it *inside* `_converge_settings` (`src/perk/convergence/init/settings.py`):
`_converge_compaction` mutates the shared `settings` dict before the `json.dumps` no-op short-circuit,
so it rides the existing `settings-wiring` `ManagedConvergence` for free — **no new doctor check**.
This mirrors `_converge_provider_packages`. Fold returned change fragments into the init/doctor `parts`
summary. See `init-doctor.md` for the managed-convergence SSOT.

### Non-destructive write-when-present / leave-when-absent

- **Present** ⇒ merge mapped keys over any existing `settings.json` block (perk keys win, hand-added
  keys survive).
- **Absent** ⇒ leave the block untouched (perk can't prove ownership of a bare key, so removal is
  unsafe).

**Residual wrinkle:** deleting `[compaction]` from `.perk/config.toml` leaves a stale `settings.json` block to
clean up by hand.

**The committed-config ↔ generated-artifact self-consistency guard.** For perk's own repo the
"edit the table → re-run init" gotcha is now a CI failure:
`tests/test_config.py::test_repo_committed_settings_carry_converged_compaction` parses the repo's
own table through the production reader (`load_committed_compaction(REPO_ROOT)`) and asserts every
mapped key/value is present in the generated `.pi/settings.json` (verified non-vacuous by mutating
the committed value). The guard is forward-only — the residual wrinkle above (a deleted table
leaving a stale block) is still uncovered — and consumer repos keep the docs-only gotcha.

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

## The cloned-repo tradeoff (`[ci] trusted`)

A repo committing `[ci] trusted = true` auto-runs its own CI and suppresses even the headless
fail-closed refuse. `perk init` therefore scaffolds only a *commented* `[ci]` / `trusted = true`
example in `PERK_TOML_TEMPLATE` so new repos stay safe-by-default. No Python parser reads it — it is
pure-TS / interior-only; the owning statement is the `ci` field doc-comment on `PerkConfig` in
`extension/substrate/config.ts`.

## The `[models]` namespace — three consumption paths under one table

The cross-cutting insight: **one validated table (`ModelsTable`, `src/perk/substrate/config.py`)
feeds three consumption paths, each the right one for its key's lifecycle.**

- **`default`/`thinking` → init convergence.** `_converge_models`
  (`src/perk/convergence/init/settings.py`) writes `defaultProvider`/`defaultModel`/
  `defaultThinkingLevel` write-when-present from the committed-only `load_committed_models_table`.
  Validation is hard — a typo must never converge into the committed `settings.json` — and
  `default` must be `provider/id` (pi's settings default is an exact provider+id lookup).
- **`stages.<id>` → Python cold launch only.** `_stage_model_argv`
  (`src/perk/run/launch/__init__.py`) emits `--model`/`--thinking`, which `_build_argv` splices
  before the user's pi args so an explicit `perk <stage> --model` wins (pi parses last-wins;
  `cold-door-launch.md`'s build-argv-once rule — `--dry-run --json` previews the injected flags).
  Unknown stage ids are KEPT at the parser: doctor's `stage-models` check (`_stage_models_check`
  — offline, `None` when unconfigured, no `--fix` arm, warns on unknown ids and invalid thinking
  levels, reuses the `repository` group) owns registry validation, keeping `config.py`
  registry-free. Inert for `--json` workers (no pi launched); warm in-session transitions inherit
  the launched session's model; the remote runner is unaffected.
- **`subagents` → TS runtime.** `subagentModel` (`extension/substrate/config.ts`) reads the
  per-agent override at execute time under the per-file worktree overlay rule from
  §"Main-checkout anchoring".

Doctor's `models` check (`_models_check`) validates the model strings' thinking suffixes across
all three. The generalizable parser recipe for a keyed sub-table: a pydantic sub-model for types
only (`StageTable` — blank strings normalize to `None` via `StrippedStr`, ill-typed values raise)
mapped by `to_domain()` into a frozen stdlib dataclass (`StageModel`) that the frozen `Config`
holds directly — the `user_bindings` precedent of domain values never re-validated past the
boundary; an all-`None` entry is omitted so an empty sub-table stays inert; overlay-aware for free
via the recursive `_overlay` leaf-merge. Contracts §8.10 documents the convergence and the launch
precedence (flag > `[models.stages.<id>]` > converged default > pi's own default);
`docs/user-docs/` and the `perk-expert` reference mirror it.

## Schema v2 migration (dated 2026-07, #1212) — the retired spellings and their tripwires

The schema was redesigned with **no backwards compatibility**; each retired spelling has one home:

| Retired spelling | Live home |
|---|---|
| `[trust] ci = "true"` | `[ci] trusted = true` (native boolean) |
| `[[ci]]` | `[[ci.checks]]` |
| `[subagents]` / `[stages.<id>]` | `[models.subagents]` / `[models.stages.<id>]` |
| `[objective] compact_threshold = "0.8"` | `[compaction] objective_threshold = 0.8` (a float) |
| `[models] model` | `[models] default` |

- **Python trips loudly.** `ConfigFileModel._reject_legacy_tables` (`mode="before"`, driven by
  `_LEGACY_TABLE_HOMES`; a list-valued `ci` is the legacy `[[ci]]`) and `ModelsTable`'s
  `[models] model` tripwire raise `ConfigError` naming the new home, surfaced by doctor's `config`
  check (`tests/test_doctor.py::test_config_check_fails_on_legacy_spelling_naming_the_new_home`).
- **TS fails safe.** Every retired spelling loads byte-identically to an empty config (the
  retired-spellings cases in `extension/substrate/config.test.ts`, whole-object `deepEqual`; the
  execute-time `subagentModel` reader pinned separately).
- **The dead facts.** The string-values-only TS parser (quoted `ci = "true"` / `"0.8"`
  workarounds; `parseTomlSubset` now reads native booleans/numbers via `TomlScalar`), and the
  own-`[trust]`-section placement rule — forced while `[ci]` was consumed wholesale as a
  named-checks map (a `[ci] trust` key would have parsed as a bogus check), dissolved by the
  map→array migration (#490) and the v2 move of trust beside the checks it governs
  (§"Placement").

## Cross-references

- `extension/substrate/config.ts` — `parseTomlSubset` (the scalar-subset TS parser); `parseCiChecks` (`[[ci.checks]]` → `CiCheck[]`)
- `extension/delivery/ci.ts` — `decideCiScope` (the `[ci] trusted` interior gate); the glob-match/skip plumbing (the `[[ci.checks]]` glob gating)
- `extension/pi/v1/delivery/ci.ts` — `changedFiles` (the changed-set observation the glob gate
  consumes); `runCiImpl` (feeds `[ci] trusted` into `decideCiScope`)
- `src/perk/substrate/config.py` — the pydantic table models (`ConfigFileModel`, `CompactionTable`,
  `WorktreeTable`, …); `load_committed_compaction`, `load_committed_issues_backend` (the
  committed-only reads)
- `src/perk/convergence/init/settings.py` — `_converge_settings` / `_converge_compaction` /
  `_converge_models` composition
- `src/perk/convergence/init/templates.py` — `PERK_TOML_TEMPLATE` (the commented `[ci]` scaffold)
- `src/perk/run/launch/__init__.py` — `_stage_model_argv` / `_build_argv` (the
  `[models.stages.<id>]` launch splice)
- `src/perk/convergence/doctor/checks.py` — `_stage_models_check`, `_models_check`
- `docs/learned/workflow/init-doctor.md` — the managed-convergence SSOT
- `docs/learned/workflow/provider-seam.md` — the mirrored selection shape
- `docs/learned/workflow/linear-backend.md` — the consumer side of the local-only `[linear] api_key` reader
- `docs/learned/workflow/worktree-lifecycle.md` — the `[worktree] setup` hook + the `created`-flag dry-run asymmetry
- `shared/contracts.md` — §8.10 — the `[compaction]` + `[models]` settings convergence and the
  model precedence
