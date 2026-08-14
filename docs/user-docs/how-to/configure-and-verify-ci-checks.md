---
title: "How to configure and verify CI checks"
description: "Author [[ci.checks]] rows, choose how their commands become trusted, and prove their pass, failure, and glob-skip states."
sidebar:
  order: 2105
sidebarGroup: "Core workflow"
---

# How to configure and verify CI checks

Configure `[[ci.checks]]` in `.perk/config.toml`, then exercise every result state so the
in-session gate says exactly what you expect before you rely on it.

## Steps

1. **Declare the checks.** Add one `[[ci.checks]]` row per independently runnable check, with a
   `name`, a `command`, and an optional `glob`:

   ```toml
   [[ci.checks]]
   name = "pass"
   command = "echo ok"

   [[ci.checks]]
   name = "gate"
   command = "test -f green.marker"

   [[ci.checks]]
   name = "code"
   command = "echo should-be-skipped"
   glob = "*.py"
   ```

   The commands run concurrently; the rows' declared order is the report order, not the
   execution order. Keep each row independent. When commands must run in sequence, put that
   sequence inside one `command`, such as `"build && test"`.
2. **Choose the trust posture.** For a repository whose committed checks you trust, add the native
   boolean below to committed `.perk/config.toml`:

   ```toml
   [ci]
   trusted = true
   ```

   A quoted `"true"` grants nothing. Without committed trust, an interactive session can ask for
   confirmation and latch approval for the rest of that session, or you can launch with
   `--allow-project-ci`. A headless session with none of these grants refuses fail-closed.
3. **Prove a pass.** Ask the agent to call `run_ci` with no check argument. Each command that
   exits successfully reports `✓`; in the example, `pass` reports `✓ pass`. Warm `/ci` runs the
   same checks when you want only the one-line overall summary.
4. **Prove a failure is reported, never fixed.** Leave `green.marker` absent for the first run.
   The `gate` row reports `✗ gate` and its captured output (`(no output captured)` when the
   command is silent). Diagnose and fix the cause yourself — perk reports the failure but never
   edits the repository or loops for you.
5. **Prove the glob gate.** With no changed `.py` file relative to the detected trunk, the `code`
   row reports `⊘` and says it is out of scope. Glob gating applies only to a run-all: selecting
   `code` explicitly with `run_ci` or `/ci code` always runs that row. If perk cannot determine
   the changed files because a Git command fails, it fails open and runs the check rather than
   claiming a skip.
6. **Rerun to green.** Apply the fix — for the example, create `green.marker` — then ask the agent
   to call `run_ci` with no check argument again. A green run-all is the definitive gate; any
   glob-skipped checks remain disclosed as intentionally out of scope for the diff.

> **Watch out — local arrays replace committed arrays.** A `[[ci.checks]]` array in
> `.perk/local.toml` replaces the committed array wholesale; it does not merge rows. Review the
> [configuration overlay semantics](../reference/configuration.md#local-overrides--overlay-semantics)
> before using a per-user check set.

## Related

- **Do:** [How to run CI checks in a session](run-ci-in-session.md) — the day-to-day run → report
  → fix → verify loop these rows power.
- **Look up:** [Workflow and CI](../reference/configuration/workflow-and-ci.md#ci) — the exact
  `[ci]` and `[[ci.checks]]` keys, types, and gating rules.
- **Understand:** [Human gates and trust](../explanation/human-gates-and-trust.md) — why perk
  reports results and keeps the fixing judgment with you.
