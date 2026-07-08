# JSON Schema snapshots

This page describes the **JSON Schema snapshots** perk commits for its cross-plane machine
surfaces. It describes the surface; it does not teach a task (those belong in
[how-to/](../how-to/index.md)) or argue a design (those belong in
[explanation/](../explanation/index.md)). See the [user-docs router](../index.md) for how this
quadrant fits the whole.

perk's machine-facing surfaces are Pydantic **boundary models** (`perk/boundary.py`). Their
`model_json_schema()` is committed as **golden snapshots** under `shared/schemas/`. Their function
is making machine-surface shape changes **reviewable in PRs**: a change to any boundary model
shows up as a schema diff guarded by the drift test, so a shape change is always deliberate. The
snapshots are not a runtime resource — neither plane reads them at runtime (TypeScript reads the
YAML contracts directly; Python validates via the live models) — and they carry no
consumer-publication promise.

## Layout

The snapshots are grouped by role under `shared/schemas/`:

- `contracts/` — the shared-YAML parse contracts.
- `inputs/` — the machine batch inputs.
- `outputs/` — the `--json` output envelopes.

Files are `<name>.schema.json`.

## What each snapshot describes

### `contracts/` — shared-YAML parse contracts

The three parsed cross-plane contracts (validation mode — the shape perk **accepts**):

| Schema | Model | Describes |
| --- | --- | --- |
| `registry.schema.json` | `RegistryFile` | the stage registry (`shared/registry.yaml`) |
| `bindings.schema.json` | `BindingsFile` | the skill-binding set (`shared/bindings.yaml`) |
| `providers.schema.json` | `ProvidersFile` | the provider-selection catalog (`shared/providers.yaml`) |

### `inputs/` — machine batch inputs

The strict machine-authored CLI inputs (validation mode):

| Schema | Model | Describes |
| --- | --- | --- |
| `review-post-batch.schema.json` | `ReviewBatchInput` | the `pr review-post` batch |
| `review-submit-batch.schema.json` | `ReviewSubmitBatchInput` | the `pr review-submit` batch |
| `resolve-threads-batch.schema.json` | `ResolveThreadsBatch` | the resolve-threads batch |
| `handoff-arg.schema.json` | `HandoffArgInput` | the `--handoff` payload object |
| `structured-roadmap-node.schema.json` | `StructuredRoadmapNode` | one objective-roadmap node |

### `outputs/` — `--json` output envelopes

The thirteen `--json` envelopes (serialization mode — the shape consumers **receive**): `plan-save`,
`pr-submit`, `pr-ready`, `pr-land`, `pr-feedback`, `pr-review-context`, `pr-review-checkout`,
`pr-review-cleanup`, `pr-review-submit`, `learn-capture`, `learn-skip`, `init-report`,
`doctor-report` (`.schema.json` each). Nested per-field sub-models ride along in `$defs`.

## Where they ship

The snapshots are bundled into both build artifacts — `perk/_shared/schemas/` in the Python wheel,
`shared/schemas/` in the npm package — read at runtime by neither.

## Generation, mode, and drift

The snapshots are generated from the live boundary models via `model_json_schema()`. The **mode is
per category**: parse/input contracts use **validation mode** (what perk accepts); output envelopes
use **serialization mode** (what `--json` consumers receive).

The committed files are regenerated only via:

```
PERK_UPDATE_SCHEMAS=1 uv run pytest tests/test_contract_schemas.py
```

`tests/test_contract_schemas.py` fails CI on any un-regenerated drift — per-model drift assertions,
a no-orphans/no-gaps coverage test, and a per-category mode-correctness check — so a schema change
is always reviewed intentionally.

## Non-goals

- `ConfigFileModel` (`.perk/config.toml`, TOML — not a shared YAML contract) is not snapshotted.
- The stored-block serializers `PlanHeaderOut` / `PlanRefOut` get no standalone snapshots;
  `PlanRefOut` appears transitively in `plan-save.schema.json`'s `$defs`.
