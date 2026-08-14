---
title: "How to run CI checks in a session"
description: "Run your project's configured CI checks from inside a pi session and read the results — perk reports, never auto-fixes."
sidebar:
  order: 2100
sidebarGroup: "Core workflow"
---

# How to run CI checks in a session

Run your project's configured CI checks from inside a `pi` session and read the results, without
leaving the session. perk **runs and reports** — it executes the checks and surfaces pass/fail plus
failure output; it **never auto-fixes**. You own the fix; perk is the oracle.

**Prerequisite:** one or more `[[ci.checks]]` checks in `.perk/config.toml`. The block is commented out by
default after [`perk init`](../reference/cli.md#perk-init) — you define the named checks your
project runs.

## Steps

1. **Configure the checks.** Add `[[ci.checks]]` rows to `.perk/config.toml` — each row is a `name`, a
   `command`, and an optional `glob`. A check with a `glob` (a comma-separated pattern string,
   e.g. `glob = "*.py"`) is **skipped** when no changed file (vs the repo's trunk) matches it, so a
   docs-only change reports success fast; a row without a `glob` always runs. Checks execute
   **concurrently**, so each row must be independently runnable — when order matters, put the
   sequence inside one row's `command` (e.g. `"build && test"`).
2. **Run all checks.** Ask the agent to call the model-facing `run_ci` tool with no check
   argument when you need the full per-check report. For a quick human-run summary, run warm
   [`/ci`](../reference/in-session/workflow-commands.md#ci): it executes the same check set but surfaces only the
   one-line overall result. While `run_ci` works, its live progress line shows per-check status
   and elapsed time; its final report lists every result in declared order.
3. **Run a subset (optional).** Ask the agent to call `run_ci` with one check name or a
   comma-separated list. The human-run summary twins are `/ci <check-name>` and
   `/ci <name1>,<name2>`.
4. **Read, then fix yourself.** Read the detailed `run_ci` pass/fail report and failure output,
   make the fix in your own turn, then ask the agent to run it again. perk will not edit or loop
   for you — you drive the run → report → fix → verify loop. The detailed green report is
   **scope-aware**: a green **run-all** (no check argument) is reported as the definitive full
   gate — the change is verified, no follow-up re-verification — with glob-skipped checks
   disclosed as intentionally out of scope for the diff; a green **subset** run says so
   ("selected checks passed") and points at the run-all as the full gate.

## The trust gate

Running a project-supplied command is gated: perk will only execute your `[[ci.checks]]` commands
when one of these grants trust — a committed `[ci] trusted = true` in config, the
`--allow-project-ci` flag, an
interactive confirmation, or a per-session approval latch. A headless session with **none** of these
**refuses** to run (fail-closed) rather than executing untrusted commands unattended.

> **Note:** warm `/ready` does **not** run the CI checks — it only marks the draft PR ready for
> review (the deliberate review gate). Run `/ci` first.

## Related

- **Do:** [How to configure and verify CI checks](configure-and-verify-ci-checks.md) — author the
  `[[ci.checks]]` rows and prove each state before trusting the gate.
- **Look up:** [Workflow commands](../reference/in-session/workflow-commands.md) — the exact `/ci`
  and `run_ci` semantics.
- **Look up:** [Configuration files](../reference/configuration.md) — the `[ci]` and
  `[[ci.checks]]` keys and change-scoped gating.
