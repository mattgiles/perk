---
title: Adding a perk.toml config table — cross-plane parsing, placement, and convergence
read_when: You are adding a new [table] to .pi/perk.toml (or a key under one), deciding where a knob is consumed, or hitting a config value that silently vanishes.
---

# Adding a `perk.toml` config table

perk's `.pi/perk.toml` is read by **both planes** — the TypeScript extension (interior) and the
Python CLI (exterior) — through deliberately narrow parsers. Two recent additions (`[trust]`,
consumed at runtime by a TS gate; `[compaction]`, converged by `init` into `settings.json`) expose a
small set of cross-cutting decisions worth preserving. The durable insight is the **contrast** between
the two models, not either table in isolation.

## Placement: own `[section]` vs a sub-key

A sibling key under an existing table is silently mis-parsed when that table is consumed *wholesale*.
`loadPerkConfig` consumes the entire `[ci]` table as the named-checks map, so a `[ci] trust = …`
sub-key would have been swallowed as a (bogus) named check. Trust therefore had to be its own
`[trust]` section:

```toml
[trust]
ci = "true"
```

**General rule:** never add a non-homogeneous key under a table that is consumed wholesale as a map.
If the table *is* a map, the new knob needs its own section.

## Parsers drop ill-typed values — the trap differs per plane

Each plane's parser silently discards values it can't use, but the failure mode is different:

- **TS — string values only.** `parseTomlSubset` (`extension/config.ts`) keeps only string values, so
  a boolean `trust = true` is **silently dropped**. The value must be the quoted string
  `ci = "true"` (the same reason `objectiveCompactThreshold` is `"0.8"`), and the gate guards with
  `.trim().toLowerCase() === "true"`.
- **Python — `bool`-is-`int`-subclass.** `isinstance(True, int)` is `True`, so a positive-int
  validator must add `and not isinstance(value, bool)` or `reserve_tokens = true` parses as `1`:

  ```toml
  [compaction]
  reserve_tokens = 16000
  ```

## Committed-only read vs the overlaid `load_config`

Most tables (`[providers]`, `[subagents]`, `[[bindings]]`) read through `load_config`, which overlays
`perk.local.toml` for per-user, session-transient overrides. Config that converges into a
**committed** artifact must not. `[compaction]` lands in `settings.json` (committed), so
`load_committed_compaction` (`perk/config.py`) reads committed `.pi/perk.toml` **only**, bypassing the
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

## Two consumption models

- **Interior gate (`[trust]`).** Consumed at runtime by a TS gate — `decideCiScope` in
  `extension/ciExecutor.ts`. The session must honor it live.
- **init convergence (`[compaction]`).** Converged by `init` into `settings.json`, which pi reads
  natively at boot. No extension change is even possible here: the interactive pi CLI builds its
  `SettingsManager` *before* extensions load, so the extension can never set
  `reserveTokens`/`keepRecentTokens`.

**The decision:** a knob the *session* must honor at runtime → interior gate; a knob pi consumes from
`settings.json` → init convergence.

## Convergence composition (the settings-targeting path)

Add a settings-targeting converger by composing it *inside* `_converge_settings` (`perk/init.py`):
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

### snake_case → camelCase mapping in the pure parser

The TOML→settings key mapping lives in the pure parser (`parse_compaction_table`): `enabled`→`enabled`,
`reserve_tokens`→`reserveTokens`, `keep_recent_tokens`→`keepRecentTokens`. LBYL silent-omit
(ill-typed/absent keys dropped; pi fills its own defaults).

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

## Cross-references

- `extension/config.ts` — `parseTomlSubset` (string-values-only TS parser)
- `extension/ciExecutor.ts` — `decideCiScope` (the `[trust]` interior gate)
- `perk/config.py` — `parse_compaction_table`, `load_committed_compaction`,
  `load_committed_issues_backend` (the committed-only reads)
- `perk/init.py` — `_converge_settings` / `_converge_compaction` composition
- `docs/learned/workflow/init-doctor.md` — the managed-convergence SSOT
- `docs/learned/workflow/provider-seam.md` — the mirrored selection shape
- `shared/contracts.md` — the `[trust]` + `[compaction]` cross-plane prose
