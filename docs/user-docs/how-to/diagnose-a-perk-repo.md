---
title: "How to diagnose a perk repo"
description: "Read a failing perk doctor report, find the group that owns the problem, and apply the bounded repair."
sidebar:
  order: 2115
sidebarGroup: "Core workflow"
---

# How to diagnose a perk repo

Use `perk doctor` to find which part of a perk-managed repository is unhealthy, apply only the
repair that check calls for, and prove the repository is healthy again.

## Steps

1. **Run `perk doctor`.** Read the grouped report. A clean group collapses to one `✓` line; a
   failing group expands its `✗` checks; a warning-only group expands its warnings beneath an
   `⚠` heading. Add `--verbose` to show every check in every group.
2. **Identify the owning group and check.** The groups cover environment and tooling
   (`environment`), backend and runner readiness (`github`, `linear`, `runner`), package and
   extension install (`package`), repository-managed artifacts (`repository`, `registry`,
   `skills`, `bindings`), config integrations (`providers`, `issues`), and local workflow state
   (`state`). Use the [`perk doctor` reference](../reference/cli.md#perk-doctor) for the
   check-by-check detail.
3. **Read the `Remediation` section.** Each failing or warning check with a repair contributes its
   remediation line here, so you can act without guessing from the summary alone.
4. **Apply the bounded repair.** For managed-artifact drift, run `perk doctor --fix`; it
   re-converges managed pieces, seeds missing config, and reports a `Fixed` list, but never mutates
   GitHub or overwrites your config edits. For a missing tool, install what the environment check
   names. For invalid config, edit `.perk/config.toml` as the check directs.
5. **Recheck.** Run `perk doctor` again and resolve every remaining `✗` until the report ends in
   `✓ healthy`. Exit code `0` means healthy, `1` means at least one check failed, and `2` means the
   command was run outside a Git repository. GitHub checks deliberately warn rather than fail, so
   an unavailable GitHub probe does not make the local repository unhealthy.

Use [`perk doctor workflow`](set-up-the-remote-runner.md) for the remote-runner subsystem. Use
[`perk objective doctor`](check-an-objective-for-drift.md) for objective-store and delivery-train
drift; neither belongs to this repository-health procedure.

## Related

- **Do:** [How to recover a dirty worktree](recover-a-dirty-worktree.md) — the recovery move when
  the blocker is uncommitted changes, not repo health.
- **Do:** [How to set up and verify the remote runner](set-up-the-remote-runner.md) — the dedicated
  doctor workflow checks for the remote subsystem.
- **Look up:** [CLI commands](../reference/cli.md) — the complete check-by-check `perk doctor`
  reference.
