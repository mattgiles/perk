# How to run CI checks in a session

Run your project's configured CI checks from inside a `pi` session and read the results, without
leaving the session. perk **runs and reports** — it executes the checks and surfaces pass/fail plus
failure output; it **never auto-fixes**. You own the fix; perk is the oracle.

**Prerequisite:** a populated `[ci]` table in `.pi/perk.toml`. The table is commented out by default
after [`perk init`](../reference/cli.md#perk-init) — you define the named checks your project runs.

## Steps

1. **Configure the checks.** Add named checks to the `[ci]` table in `.pi/perk.toml` (each entry is
   a check name mapped to its command).
2. **Run all checks.** Run warm `/ci`. perk runs every configured check in declared order and reports
   each one's result. (In-session command; its reference is coming with Objective
   [#453](https://github.com/mattgiles/perk/issues/453) Node 2.2.)
3. **Run one check (optional).** Run `/ci <check-name>` to run a single configured check instead of
   all of them.
4. **Read, then fix yourself.** Read the reported pass/fail and failure output, make the fix in your
   own turn, then run `/ci` again to re-verify. perk will not edit or loop for you — you drive the
   run → report → fix → verify loop. (The model-facing `run_ci` tool follows the same run-and-report
   contract.)

## The trust gate

Running a project-supplied command is gated: perk will only execute your `[ci]` commands when one of
these grants trust — a committed `[trust] ci = "true"` in config, the `--allow-project-ci` flag, an
interactive confirmation, or a per-session approval latch. A headless session with **none** of these
**refuses** to run (fail-closed) rather than executing untrusted commands unattended.

> **Note:** warm `/ready` also runs the configured CI checks — it is the draft → ready gate, so a
> plan's checks run automatically when you mark its PR ready.

---

← Back to the [how-to router](index.md).
