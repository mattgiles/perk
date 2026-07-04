# How to advance an objective with the run supervisor

Push an objective's backlog forward one safe step at a time, without sitting in an interactive
session, using the deterministic `perk objective run` supervisor.

## Steps

1. **Run one safe step.** Run
   [`perk objective run <NUMBER>`](../reference/cli.md#perk-objective-run-number-alias-r) (alias `r`).
   It reports the cumulative budget, then takes **one** autonomously-safe action and stops — it does no
   agentic reasoning of its own.
2. **Read the outcome.** The supervisor prints one action verb telling you what it did and what comes
   next:

   | Outcome | What it means as a next step |
   | --- | --- |
   | `dispatched` | The next ready `implement`/`address` step was sent to the remote runner — observe it with `perk workflow run list`. |
   | `awaiting_run` | A dispatched run is still in flight — wait, or re-run with `--wait`. |
   | `plan_required` | The next node needs a plan — author one before the supervisor can advance. |
   | `ready_for_review` | An implementation is done and needs a PR marked ready — your `/ready`. |
   | `awaiting_review` | A PR is open and waiting on human review. |
   | `merged_pending_reconcile` | A PR merged; the supervisor will observe the merge→done reconcile. When the plan's learn pass is still pending, the report names it (`next_action: learn`) with the local remediation — run `perk plan resume <plan-id>`. |
   | `blocked` | The backlog cannot advance — a dependency or blocker needs you. |
   | `pr_closed` | A PR was closed without merging — decide how to proceed. |
   | `completed` | The objective's roadmap is fully done. |

3. **Wait on an in-flight run.** Add `--wait` to poll a dispatched run to completion, then re-evaluate
   the backlog once. The in-flight check reads GitHub's own run enumeration, so it works from a
   **fresh clone** — the supervisor never double-dispatches just because this machine has no local
   dispatch records. (The cumulative budget, by contrast, sums local run outcomes — a fresh clone
   undercounts it.)
4. **Preview offline.** Add `--dry-run` to resolve the next decision without dispatching, minting, or
   writing anything.
5. **Note it never lands.** The supervisor only advances autonomously-safe steps — marking a PR ready
   and merging stays the human `/land`; it merely observes the merge→done reconcile. For the full
   plan→learn spine, see [How to drive a change through the full spine](./drive-the-full-spine.md).

> **Maturity.** The supervisor's own scheduling logic is deterministic and tested, and it dispatches
> into a remote runner whose live end-to-end chain is proven on perk's own repo (consumer repos
> have not yet exercised it). See
> [Headless and remote: how it works, and how proven it is](../explanation/headless-and-remote.md)
> for the full maturity story.

---

← Back to the [how-to router](index.md).
