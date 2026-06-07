# shared — cross-plane contracts

perk's language-neutral contracts, authored once and **bundled into both build
artifacts** (the Python wheel as package data `perk/_shared/`; the npm package under
`shared/`). Each plane reads its *own* bundled copy at runtime — no dependency on
repo layout (`Q12`).

Contents (authored in **T2**):

- **`registry.yaml`** — a *parsed* contract: the stage registry (descriptor
  shape + the six MVP stages + graph) and the `state_keys` vocabulary. Read by both
  planes (`perk/registry.py`, `extension/registry.ts`); validated by
  `perk registry check`.
- **`bindings.yaml`** — the second *parsed* contract: the skill-binding set
  (trigger→skill delivery, with a per-binding `nudge`/`transclude` mode). Read by both
  planes (`perk/bindings.py`, `extension/bindings.ts`); see `contracts.md` §8.9.
- **`providers.yaml`** — the third *parsed* contract: the provider-selection supported
  set (the catalog of plan/todo providers perk can wire, with each entry's `package` /
  `adapter` / `default` / optional `package_filter`). Read by both planes
  (`perk/providers.py`, `extension/providers.ts`); see `contracts.md` §8.10.
- **`contracts.md`** — the four *prose* specs implemented once per plane: the
  `.pi/workflow/` layout, the `PERK_RUN_ID` protocol, the `perk:workflow-state`
  schema, and the GitHub gateway contract.

Resolution is proven by T1's per-plane resolvers (`perk/_resources.py`,
`extension/resources.ts`): installed bundle → editable repo-sibling fallback.
