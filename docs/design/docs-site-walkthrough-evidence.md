# Docs-site executable walkthrough evidence

## Purpose and evidence contract

The executable-content walkthrough matrix in
[`docs-site-blueprint.md` §7](./docs-site-blueprint.md#7-acceptance-matrices) is the contract
for this record. Each live row records its starting state, dated identifiers, expected result,
observed outcome, and cleanup. Secret values never appear: evidence names credential keys and
whether they were present only.

Nodes 3.4 and 3.6 append their assigned walkthrough rows here. Node 5.2 consumes this record
alongside the final cold-context and search gates. A deferred row is deliberately not a pass;
a later consumer can see the exact evidence gap without reconstructing session history.

## Credential and Actions preflight — passed

| Field | Evidence |
|---|---|
| Date | 2026-08-13 |
| Operator | `mattgiles` |
| Mode and starting state | Fresh private repository, seeded `main`, then the current checkout's `perk init` wiring committed and pushed before dispatch |
| Disposable repository | `https://github.com/mattgiles/perk-preflight-2026-08-13` (deleted after the run) |
| Seed and wiring commits | `f712c06` (seed), `3cf8ca6` (`perk init` wiring on remote `main`) |
| Credentials | `PERK_GH_PAT` present; `ANTHROPIC_API_KEY` present; values omitted; `PERK_ENABLED` unset (default-on) |
| Required result | Static workflow check healthy; smoke run completed with conclusion `success`; no durable dispatch record; repository deleted unconditionally |
| Outcome | **Pass** |

Sanitized static-check result:

```text
✓ github (2 checks)
⚠ runner (4 checks)
  • runner-enabled: remote runner enabled (PERK_ENABLED unset → default-on)
  • runner-workflow-permissions: Actions cannot create PRs — advisory; the runner uses a PAT
✓ repository (1 check)
```

The live smoke dispatch produced run id `01KZXWB2H9RKSMMKAPQJ6T2K12` and completed
successfully:

- Actions API URL: `https://api.github.com/repos/mattgiles/perk-preflight-2026-08-13/actions/runs/31716419148`
- Actions run URL: `https://github.com/mattgiles/perk-preflight-2026-08-13/actions/runs/31716419148`
- Conclusion: `success`
- `perk workflow run list`: `No dispatched runs found`

The first deletion attempt proved the documented authorization edge: `gh` required the
`delete_repo` scope. The operator ran `gh auth refresh -h github.com -s delete_repo`, retried
the deletion, and received `Deleted repository mattgiles/perk-preflight-2026-08-13`. A final
`gh repo view` returned `Could not resolve to a Repository`, proving cleanup. Repository
secrets were deleted with the repository.

## Get-started tutorial — deferred by operator override

| Field | Evidence |
|---|---|
| Date | 2026-08-13 |
| Intended mode | Live, external, fresh disposable private GitHub repository; published tutorial steps only |
| Version posture | Tutorial sample pinned to the operator-designated forthcoming `perk 2.4.0`; publication was not awaited |
| Repository / plan / PR / learning identifiers | Not recorded — the walkthrough was not executed |
| Expected-output excerpts | Not recorded |
| Cleanup proof | Not applicable; no walkthrough repository was created |
| Outcome | **Deferred; no live-run pass claimed** |

The operator explicitly waived the release wait and directed implementation to proceed on the
assumption that v2.4.0 will publish soon. This keeps the local-only docs delivery moving but
does not manufacture the §7 evidence. A later gate that requires a live tutorial proof must
run this row against an available release and replace this deferred record with dated
identifiers, observed outputs, learning outcome, and cleanup.

## Objective tutorial — deferred by operator override

| Field | Evidence |
|---|---|
| Date | 2026-08-13 |
| Intended mode | Live, external, fresh disposable private GitHub repository; published tutorial steps only |
| Intended result | Author a two-node incremental objective, plan and land node 1.1, observe auto-done, and capture reconcile output (stale-prose diff or explicit healthy no-op) |
| Objective / plan / PR identifiers | Not recorded — the walkthrough was not executed |
| Before/after objective state and reconcile transcript | Not recorded |
| Expected-output excerpts | Not recorded |
| Cleanup proof | Not applicable; no walkthrough repository was created |
| Outcome | **Deferred; no live-run pass claimed** |

The same operator override applies. No agent-driven or local substitute was used: it would not
satisfy the matrix's published-steps criterion. A later gate that requires the proof must
replace this row with the objective, plan, and PR identifiers; `perk objective show` evidence
from before and after `/land`; the reconcile-turn excerpt plus comment-prose diff or explicit
no-op; expected outputs; and cleanup.

## Defect and rerun log

| ID | Surface | Observation | Resolution | Full rerun required? |
|---|---|---|---|---|
| P1 | Preflight cleanup | Initial repository deletion was refused because the active `gh` token lacked `delete_repo`. | Refreshed the token with the documented scope command, deleted the repository, and proved absence. Both tutorials carry this remediation beside their cleanup command. | No — the smoke result remained valid and unconditional cleanup completed in the same attempt. |
| D1 | Tutorial walkthroughs | No live walkthrough was attempted because the operator waived the release wait. | Recorded as deferred rather than fabricating evidence. | Pending if a later gate requires live proof. |
