# pi-subagents RPC migration to 0.74.0

Date: 2026-09-30

## Recommendation

Keep perk's module-rendered wave scripts and migrate the RPC spawn parameter from
`workflowScript` to `script`. Target pi-subagents 0.74.0 explicitly, with updated
compatibility guidance and regression coverage. Handle lifecycle and recovery
improvements as separate work.

This is an integration recommendation, not an implemented or validated migration.

## Failure and upstream contract

pi-subagents 0.74.0 rejects RPC spawn requests containing `workflowScript`:

```text
invalid_params: RPC spawn workflowScript was removed; pass inline script text as script.
```

The new RPC boundary accepts inline JavaScript through `script`, then translates
it into the executor's existing internal `workflowScript` carrier. Perk's generated
`runs.all(...)` orchestration and explicit return projection can therefore remain.

The model-facing tool has a different interface: `workflow: true` executes a fenced
workflow block from an assistant reply, while a workflow string selects a file or
named workflow. RPC has no assistant reply block and rejects `workflow: true`.
Perk's machine-generated waves should use inline `script`.

Sources:

- [0.74.0 RPC implementation](https://github.com/nicobailon/pi-subagents/blob/v0.74.0/src/extension/rpc.ts#L523)
- [0.74.0 changelog](https://github.com/nicobailon/pi-subagents/blob/v0.74.0/CHANGELOG.md#0740---2026-09-30)

The npm registry reported 0.74.0 as latest when this recommendation was prepared.
The tagged source was consulted through the perk library.

## Bounded migration

1. Rename `WaveSpawnParams.workflowScript` to `script` in
   `extension/waves/transport.ts` and update the spawn construction. Internal wave
   spec naming can remain an implementation detail; the external payload must use
   the new contract.
2. Update adapter fixtures and wave assertions to inspect `script`. Add a meaningful
   RPC boundary regression that requires `script` and rejects the presence of
   `workflowScript`, including an undefined legacy property.
3. Preserve the rendered orchestration, fresh context, ephemeral mission policy,
   structured report schemas, engine deadlines, acceptance disable, and intercom
   disable. Re-verify these behaviors against 0.74.0 rather than changing them as
   part of the parameter migration.
4. Update the guidance-verified version in
   `src/perk/convergence/doctor/checks.py`, currently 0.70.1, after verification.
   Update `docs/user-docs/`, the corresponding `skills/perk-expert/references/`
   guidance, and `shared/contracts.md` in the same implementation turn.
5. Update custom-subagent guidance that still teaches the removed model-facing
   `workflowScript` parameter. Explain the distinction between the public tool's
   `workflow` forms and RPC's inline `script`.

Prefer a clear supported baseline over a speculative compatibility shim. Do not
retry a failed spawn with a different parameter dialect: spawning is an operation
with side effects, and generic retry logic can obscure whether work launched.

## Compatibility and package resolution

The RPC protocol remains version 1 despite the breaking spawn parameter change.
Perk's current ping narrowing checks `asyncSpawn`, the presence of `spawn`, and the
advertised completion channel. Those checks do not establish which inline-script
parameter the responder accepts. Upstream 0.74.0 does not advertise an inline-script
dialect capability in ping.

Strengthen compatibility guidance and diagnostics without inventing a capability
that upstream does not provide. A future upstream dialect capability would be a
better basis for negotiation than protocol version alone.

At inspection time, the working `.pi/settings.json` already pinned
`npm:pi-subagents@0.73.1` and had a pre-existing modification. The reported unpinned
0.74.0 installation may come from another settings scope or checkout; establish
the effective package resolution before modifying that file. Preserve the user's
existing changes. Pinning a supported older release is a temporary workaround,
not the recommended integration direction.

## Related integration changes to assess

| Upstream change | Recommendation |
| --- | --- |
| `disabledFeatures` can disable workflow scripts, including RPC launches | Preserve the upstream setting-specific error so the user can identify the configuration that blocks waves. |
| Background children survive runtime replacement, and relaunch can reuse child results | Test reload, cancellation, receipt correlation, and wave freshness expectations before adding automatic recovery. |
| Children inherit the parent's project trust | Verify perk's restriction extension and explicitly selected skills under trusted and untrusted project states. |
| Public lifecycle events and process-terminal proof are available | Consider them separately for progress and confirmation that cancellation has stopped children. |

The lifecycle and process-terminal additions predate 0.74.0 and are relevant to
an audit from perk's older guidance baseline. Their availability does not require
adopting them to fix inline RPC spawning.

## Validation and delivery

Run targeted wave and RPC adapter tests while iterating. Coverage should establish
the actual outbound payload, completion-before-spawn-reply handling, cancellation,
structured aggregation, and preservation of the fixed child policies. Include a
0.74.0 integration check so a permissive fake responder cannot conceal parameter
drift.

Complete the repository's required CI gate before submission. In a perk session,
use one run-all `run_ci` immediately before submitting and treat its green report
as definitive. Dogfood the updated integration with perk driving the next phase.

Deliver the parameter migration, compatibility updates, documentation, and focused
coverage together. Keep automatic relaunch/recovery and richer lifecycle reporting
outside this change unless verification exposes a concrete blocker.
