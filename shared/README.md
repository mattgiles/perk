# shared — cross-plane contracts

perk's language-neutral contracts, authored once and **bundled into both build
artifacts** (the Python wheel as package data `perk/_shared/`; the npm package under
`shared/`). Each plane reads its *own* bundled copy at runtime — no dependency on
repo layout.

Contents:

- **`registry.yaml`** — a *parsed* contract: the stage registry (descriptor
  shape + stages + graph) and the `state_keys` vocabulary. Read by both
  planes (`src/perk/substrate/registry.py`, `extension/substrate/registry.ts`); validated by
  `perk registry check`.
- **`bindings.yaml`** — the second *parsed* contract: the skill-binding set
  (trigger→skill delivery, with a per-binding `nudge`/`transclude` mode). Read by both
  planes (`src/perk/substrate/bindings.py`, `extension/substrate/bindings.ts`); see `contracts.md` §8.9.
- **`providers.yaml`** — the third *parsed* contract: the provider-selection supported
  set (the catalog of plan/footer/web providers perk can wire, with each entry's `package` /
  `adapter` / `default` / optional `package_filter`). Read by both planes
  (`src/perk/substrate/providers.py`, `extension/substrate/providers.ts`); see `contracts.md` §8.10.
- **`host-floor.yaml`** — the fourth *parsed* contract: the host floor (the minimum supported
  Pi and Node versions, semver `>=`). Read by both planes (`src/perk/substrate/host_floor.py`,
  the authoritative validator; `extension/substrate/hostFloor.ts`, a structural reader); the
  Python launch preflight and `perk init`/`perk doctor` enforce it. See `contracts.md` §8.76.
- **`contracts.md`** — the numbered *prose* contract sections (`§8.1`–`§8.76`,
  non-contiguous: `§8.8` is skipped and `§8.6a` exists), each pinning the exact
  names/paths/shapes both planes implement against. The founding four — the
  `.perk/workflow/` layout, the `PERK_RUN_ID` protocol, the `perk:workflow-state`
  schema, and the GitHub gateway contract — were the original seed, not the current
  inventory.
- **`schemas/`** — committed **golden snapshots** of perk's boundary models (the
  shared-YAML parse contracts — registry, bindings, providers and host floor — the machine
  batch inputs, and the `--json` output envelopes), generated from the Pydantic models in
  `perk/boundary.py` and grouped by role under `contracts/` / `inputs/` / `outputs/`. Their
  function is making
  machine-surface shape changes reviewable in PRs: bundled into both artifacts, read at
  runtime by neither, drift-guarded by `tests/test_contract_schemas.py`. See
  `contracts.md` §8.34.
- **`fixtures/`** — **test-only** cross-plane evidence, read at runtime by neither plane.
  `issues-table.json` pairs `[issues]` TOML spellings (basic, literal, multi-line, dotted-key,
  inline-table, quoted, escaped, absent, non-string) with the TS subset reader's `{backend,
  team}` (`extension/substrate/config.test.ts`), whether that read is provably `tomllib`'s
  (`provable` — the draft-review destination fence trusts the keys only then, else it widens
  to the whole document) and, on divergence, `tomllib`'s own reading
  (`tests/test_issues_config_parity.py` pins "divergent ⇒ unproven"). See `contracts.md` §8.23
  "Draft-review guards".
  `tool-matrix.json` is the **golden stage×tool matrix** derived from the tool catalog
  (`extension/substrate/toolPolicy.ts` `toolMatrix()`): one row per perk/foreign/builtin tool and,
  per registry stage plus `unscoped`, the read-only and read-write eligibility. Generated and
  byte-drift-guarded by `extension/substrate/toolMatrix.test.ts` (`PERK_UPDATE_TOOL_MATRIX=1`
  regenerates); read by both planes' prompt guards (`tests/test_tool_matrix_prompts.py`), the
  docs-site census test and the prose-map governed-tool census. See `contracts.md` §8.40.
  `default-tools-seed.json` pairs project `defaultTools` shapes (absent, modifier list,
  plain-name list, empty, no string entries, each `tool_search` vote form, ill-typed) with what the
  discovery seed converges them to (`tests/test_init_idempotent.py` pins the JSON delta) and, for
  the absent and array cases, lets `extension/substrate/discoveryPilot.test.ts` measure on the real
  host that the seed adds `tool_search` and nothing else to the resolved selection. See `contracts.md` §8.10
  "`defaultTools` discovery convergence".

Resolution goes through the per-plane resolvers (`src/perk/_resources.py`,
`extension/substrate/resources.ts`): installed bundle → editable repo-sibling fallback.
