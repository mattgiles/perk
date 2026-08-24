# How to audit recorded sessions

This page is a **how-to guide**. Use it to audit the Pi sessions recorded on your machine for
perk's own repository and triage the resulting leads. For command and vocabulary details, see the
[session audit reference](./session-audit.md).

**Prerequisites:** run from a checkout of the perk repository, with the `perk-dev` workspace
package available. The judgment step also needs model credentials for the repo-local auditor
agent.

## Steps

1. **Census the corpus.**

   ```bash
   perk-dev audit census
   ```

   Read the identity, stage, trigger, and vintage partitions before drawing conclusions from an
   audit. Check each expectation's exercising/applicable counts and the `not exercised` rollup:
   they show what the current machine's history can cover at all. Use
   `--sessions-root <dir>` only when the Pi history is somewhere other than
   `~/.pi/agent/sessions`.

2. **Run the deterministic tier.**

   ```bash
   perk-dev audit run
   ```

   To narrow the report while investigating one entry, repeat its filter as needed:

   ```bash
   perk-dev audit run --expectation bindings.nudge-skill-read
   ```

   Read the per-expectation verdict lines, then inspect every row in the `violations` block. The
   command exits 0 whenever it successfully generates a report, even when it reports violations;
   these are leads for human triage, not CI failures.

3. **Run the judgment wave.**

   ```bash
   perk-dev audit judge
   ```

   `judge` rebuilds one coherent census, full deterministic report, and judgment evidence bundle,
   then launches a seeded read-only session. In that session, let the agent call
   `run_audit_wave` once. It dispatches the packetized evidence to the repo-local auditors and
   writes `verdicts.json`. The session finishes by presenting a copyable fold command.

   Narrow sampling or expectations when calibrating a specific area:

   ```bash
   perk-dev audit judge \
     --expectation plan.grill-before-review \
     --max-sessions 2 \
     --out .perk/workflow/scratch/audit-grill
   ```

   Use `--dry-run` to materialize and inspect the complete bundle without launching the seeded
   session:

   ```bash
   perk-dev audit judge --dry-run
   ```

4. **Fold the judgment verdicts.**

   Run the exact command printed by the seeded session, or provide the bundle directly:

   ```bash
   perk-dev audit fold --bundle .perk/workflow/scratch/audit-evidence
   ```

   Read the `judgment leads` section as leads, not proofs. The `unchecked breakdown` accounts for
   unclear, failed, unboundable, and unsampled evidence instead of treating those cells as passes.

5. **Triage honestly.**

   Open the cited session and entry indices before accepting any violation as real. Distinguish a
   behavioral regression from a false verdict caused by a checker, evidence slicer, fold, or wave
   defect. Treat `unchecked`, `not-exercised`, and `not-applicable` as coverage statements, not
   failures and not successes.

   For a full calibration pass—including the degradation-arm checklist and the
   machinery-fixes-first sequence—follow the procedure in
   [`docs/design/archive/session-audit-dogfood.md`](../design/archive/session-audit-dogfood.md).

---

← Back to the [developer docs router](./index.md).
