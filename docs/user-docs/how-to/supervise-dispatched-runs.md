---
title: "How to observe and control dispatched runs"
description: "See what remote runs are in flight and act on them — list, cancel, and retry — from a cold shell."
sidebar:
  order: 2240
sidebarGroup: "Headless & remote"
---

# How to observe and control dispatched runs

Find a remote run, confirm its identity and state, then cancel or retry it safely from any clone.

## Steps

1. **List current and historical runs.** Run
   [`perk workflow run list`](../reference/cli.md#perk-workflow-run-list-alias-ls) (alias `ls`). The
   default view discovers GitHub Actions runs first, so a fresh clone can see runs dispatched by
   another machine. Use `--limit` to bound the newest-first result or `--json` for structured data.
2. **Inspect the run before acting.** Match the stage and plan, then read the dispatch status, live
   run status, conclusion, pull request, and age. Copy the full `RUN_ID`; the control commands take
   the perk run id, not the GitHub numeric run id. In JSON, `source: "discovered"` means the row came
   from Actions, `source: "both"` means a local record enriched it, and `source: "local"` means only
   the local record is available.

   GitHub Actions is the canonical cross-clone existence source. Local dispatch records add plan and
   objective correlation, preserve precise dispatch context, and keep failed or never-triggered
   attempts visible. Use `--no-refresh` only when you deliberately want that local-cache-only view.
3. **Cancel an active run.** For a run that is queued or in progress, run:

   ```bash
   perk workflow run cancel <RUN_ID>
   ```

4. **Retry a terminal run.** For a completed or failed run, rerun the same GitHub Actions run:

   ```bash
   perk workflow run retry <RUN_ID>
   ```

   Add `--failed` to rerun only failed jobs. Retrying does not mint a new perk run id.

## Expected result

The selected Actions run is cancelled or rerun, while its existing perk run id continues to identify
it across clones.

## Related

- **Do:** [Dispatch a stage to CI](./dispatch-a-stage-to-ci.md) — create a run to supervise.
- **Do:** [Advance an objective headlessly](./advance-an-objective-headlessly.md) — let the objective
  supervisor choose one safe next step.
- **Look up:** [`perk workflow run`](../reference/cli.md#perk-workflow-run-list-alias-ls) — list,
  cancel, and retry command family and output.
