# How to observe and control dispatched runs

See what remote runs are in flight and act on them — list, cancel, and retry — from a cold shell.

This works from **any machine** — a second clone, a teammate's checkout, a fresh CI shell. The
existence record for a remote run is the GitHub Actions run itself (its run-name embeds the stage,
plan id, and perk `run_id`), so listing, cancelling, and retrying do **not** require the local
dispatch record written by the machine that dispatched the run; the local record is an
accelerator/enricher, not the existence source.

## Steps

1. **List the runs.** Run
   [`perk workflow run list`](../reference/cli.md#perk-workflow-run-list-alias-ls) (alias `ls`) and
   read the `RUN_ID / STAGE / DISPATCH / RUN / CONCLUSION / PLAN / PR / AGE` columns. This command is
   **read-only** — it mutates nothing — and every GitHub read is best-effort and fail-soft. Runs
   this clone never dispatched appear too (in `--json`, `source: "discovered"` rows). Use
   `--no-refresh` for the zero-network local-cache-only view, `--limit` to bound the rows, or
   `--json` for machine-readable output.
2. **Copy the full `RUN_ID`.** The control commands take the perk `run_id` exactly as listed — copy it
   whole, never truncated.
3. **Cancel an in-flight run.** Run
   [`perk workflow run cancel <RUN_ID>`](../reference/cli.md#perk-workflow-run-cancel-run_id) to stop
   a run that is still going — including one this machine never dispatched.
4. **Retry a finished run.** Run
   [`perk workflow run retry <RUN_ID>`](../reference/cli.md#perk-workflow-run-retry-run_id) (add
   `--failed` to re-run only the failed jobs). Retry **re-runs the same GHA run** — it does not mint a
   new run id.

> **Maturity.** These observe/control surfaces have deterministic, tested logic, but they act on the
> remote runner whose live end-to-end execution is not yet proven. See
> [Headless and remote: how it works, and how proven it is](../explanation/headless-and-remote.md)
> for the full maturity story.

---

← Back to the [how-to router](index.md).
