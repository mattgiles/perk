---
title: "JSON Schema snapshots"
description: "The JSON Schema snapshots perk commits for its cross-plane machine surfaces, and what keeps them from drifting."
sidebar:
  order: 3060
---

# JSON Schema snapshots

perk commits JSON Schema snapshots for its Pydantic boundary models so a machine-surface change is
visible and reviewable in the same pull request as its code. The live registry contains **26**
snapshots: 3 shared contracts, 5 machine inputs, and 18 output envelopes.

The snapshots are golden artifacts under `shared/schemas/`. They are not runtime resources and do
not promise a separately versioned public API: Python validates with the live models, while the two
planes read their live shared contracts directly.

## Layout

Snapshots are grouped by role:

- `contracts/` — shared-YAML parse contracts;
- `inputs/` — machine-authored batch and structured inputs;
- `outputs/` — JSON output envelopes.

Every file uses the `<name>.schema.json` suffix. The filename column below is relative to its
category directory.

## What each snapshot describes

### `contracts/` — shared-YAML parse contracts

<!-- perk:reference-facts:schemas-contracts:start -->
| Schema filename | Model class | Mode | Purpose |
| --- | --- | --- | --- |
| `registry.schema.json` | `RegistryFile` | `validation` | Accepted shape of the stage registry in `shared/registry.yaml`. |
| `bindings.schema.json` | `BindingsFile` | `validation` | Accepted shape of the skill-binding set in `shared/bindings.yaml`. |
| `providers.schema.json` | `ProvidersFile` | `validation` | Accepted shape of the provider catalog in `shared/providers.yaml`. |
<!-- perk:reference-facts:schemas-contracts:end -->

### `inputs/` — machine inputs

<!-- perk:reference-facts:schemas-inputs:start -->
| Schema filename | Model class | Mode | Purpose |
| --- | --- | --- | --- |
| `review-post-batch.schema.json` | `ReviewBatchInput` | `validation` | Batch accepted by the advisory PR review-post surface. |
| `review-submit-batch.schema.json` | `ReviewSubmitBatchInput` | `validation` | Atomic foreign-PR review submission batch. |
| `resolve-threads-batch.schema.json` | `ResolveThreadsBatch` | `validation` | Review-thread reply and resolution batch. |
| `handoff-arg.schema.json` | `HandoffArgInput` | `validation` | Structured run handoff accepted by stage launchers. |
| `structured-roadmap-node.schema.json` | `StructuredRoadmapNode` | `validation` | One strict objective-roadmap authoring node. |
<!-- perk:reference-facts:schemas-inputs:end -->

### `outputs/` — JSON envelopes

<!-- perk:reference-facts:schemas-outputs:start -->
| Schema filename | Model class | Mode | Purpose |
| --- | --- | --- | --- |
| `plan-save.schema.json` | `PlanSaveOut` | `serialization` | Saved plan reference, issue, and linkage result. |
| `pr-submit.schema.json` | `PrSubmitOut` | `serialization` | Pull-request publication result. |
| `pr-ready.schema.json` | `PrReadyOut` | `serialization` | Draft-to-ready transition result. |
| `pr-land.schema.json` | `PrLandOut` | `serialization` | Pull-request landing and plan-finalization result. |
| `pr-feedback.schema.json` | `PrFeedbackOut` | `serialization` | Classified PR feedback and thread inventory. |
| `pr-review-context.schema.json` | `PrReviewContextOut` | `serialization` | Read-only PR review context. |
| `pr-review-checkout.schema.json` | `PrReviewCheckoutOut` | `serialization` | Isolated PR review checkout result. |
| `pr-review-cleanup.schema.json` | `PrReviewCleanupOut` | `serialization` | Review checkout cleanup result. |
| `pr-review-submit.schema.json` | `PrReviewSubmitOut` | `serialization` | Atomic posted-review result. |
| `learn-capture.schema.json` | `LearnCaptureOut` | `serialization` | Captured learning issue and pending-learn transition. |
| `learn-skip.schema.json` | `LearnSkipOut` | `serialization` | Explicit learn-skip and pending-learn transition. |
| `init-report.schema.json` | `InitReportOut` | `serialization` | Repository convergence and readiness report. |
| `doctor-report.schema.json` | `DoctorReportOut` | `serialization` | Repository diagnosis and repair report. |
| `objective-stack-status.schema.json` | `ObjectiveStackStatusOut` | `serialization` | Stacked delivery-train status and unresolved operations. |
| `objective-stack-sync.schema.json` | `ObjectiveStackSyncOut` | `serialization` | Stack sync preview, cascade, or continuation result. |
| `objective-stack-recover.schema.json` | `ObjectiveStackRecoverOut` | `serialization` | Interrupted-operation classification and recovery result. |
| `objective-stack-land.schema.json` | `ObjectiveStackLandOut` | `serialization` | Atomic train readiness or landing result. |
| `objective-doctor.schema.json` | `ObjectiveDoctorOut` | `serialization` | Objective manifest, cancellation, and train diagnosis. |
<!-- perk:reference-facts:schemas-outputs:end -->

The `validation` mode records what a parser accepts. The `serialization` mode records what a JSON
producer emits. Nested field models appear under each snapshot's `$defs` rather than as additional
registry entries.

## Where they ship

The same snapshots are bundled into both distribution artifacts:

- `perk/_shared/schemas/` in the Python wheel;
- `shared/schemas/` in the npm package.

Neither artifact reads the snapshots at runtime. Packaging them keeps the reviewed contract record
available alongside each distributed plane.

## Generation, mode, and drift

The registry in `tests/_schemas.py` is the single source of truth for snapshot path, model class,
and mode. Regenerate committed files only with:

```sh
PERK_UPDATE_SCHEMAS=1 uv run pytest tests/test_contract_schemas.py
```

`tests/test_contract_schemas.py` compares every file with a fresh `model_json_schema()` render,
rejects orphan or missing snapshots, and checks category mode. The user-docs reference-facts guard
also derives this inventory from the registry, so a new schema cannot leave these tables silently
stale.

## Non-goals

- `ConfigFileModel` describes TOML configuration rather than a shared YAML contract and is not
  snapshotted.
- Stored-block serializers such as `PlanHeaderOut` and `PlanRefOut` have no standalone snapshots;
  `PlanRefOut` appears transitively in `plan-save.schema.json`.
- The snapshots do not replace runtime validation or establish an independent compatibility
  lifecycle.

## Related

- **Look up:** [CLI commands](./cli.md).
- **Look up:** [Model-facing tools](./in-session/model-tools.md).
- **Understand:** [How perk thinks](../explanation/how-perk-thinks.md).
