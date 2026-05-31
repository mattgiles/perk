# shared — cross-plane contracts

perk's language-neutral contracts, authored once and **bundled into both build
artifacts** (the Python wheel as package data `perk/_shared/`; the npm package under
`shared/`). Each plane reads its *own* bundled copy at runtime — no dependency on
repo layout (`Q12`).

The contracts themselves are authored in **T2**: the stage registry
(`registry.yaml`), the state-key vocabulary, the `.pi/workflow/` layout spec, the
`PERK_RUN_ID` protocol, the `perk:workflow-state` schema, and the GitHub gateway
contract. T1 only proves this directory **bundles and resolves** from both planes
(`perk/_resources.py`, `extension/resources.ts`).
