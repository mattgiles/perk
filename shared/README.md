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
  set (the catalog of plan/todo/askuser/footer/web providers perk can wire, with each entry's `package` /
  `adapter` / `default` / optional `package_filter`). Read by both planes
  (`src/perk/substrate/providers.py`, `extension/substrate/providers.ts`); see `contracts.md` §8.10.
- **`contracts.md`** — the numbered *prose* contract sections (`§8.1`–`§8.38`,
  non-contiguous: `§8.8` is skipped and `§8.6a` exists), each pinning the exact
  names/paths/shapes both planes implement against. The founding four — the
  `.perk/workflow/` layout, the `PERK_RUN_ID` protocol, the `perk:workflow-state`
  schema, and the GitHub gateway contract — were the original seed, not the current
  inventory.
- **`contracts-history.md`** — the chronological `Status (…)` changelog sibling of the
  prose spec, grouped by `§N.M` anchor (keeps `contracts.md` a compact current-spec
  document).
- **`schemas/`** — committed **golden snapshots** of perk's boundary models (the
  shared-YAML parse contracts, the machine batch inputs, and the `--json` output
  envelopes), generated from the Pydantic models in `perk/boundary.py` and grouped by
  role under `contracts/` / `inputs/` / `outputs/`. Their function is making
  machine-surface shape changes reviewable in PRs: bundled into both artifacts, read at
  runtime by neither, drift-guarded by `tests/test_contract_schemas.py`. See
  `contracts.md` §8.34.

Resolution goes through the per-plane resolvers (`src/perk/_resources.py`,
`extension/substrate/resources.ts`): installed bundle → editable repo-sibling fallback.
