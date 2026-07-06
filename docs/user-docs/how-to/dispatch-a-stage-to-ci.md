# How to dispatch a stage to a remote runner

Hand an unattended stage off to a CI runner instead of running it locally, with `--remote`. This is
the canonical home for the `--remote` cold door.

## Steps

1. **Confirm the runner is set up.** The repo must have a converged runner and a passing smoke test —
   see [How to set up and verify the remote runner](./set-up-the-remote-runner.md).
2. **Dispatch a stage.** Add `--remote` to a cold stage launch —
   [`perk implement … --remote`](../reference/cli.md#perk-implement-plan-alias-impl) — or to a resume —
   [`perk plan resume 42 --remote`](../reference/cli.md#perk-plan-resume-plan). perk records the
   run-to-plan linkage in durable state and triggers the runner instead of opening a local session.
   A fresh plan needs no pre-existing `plan-<N>` branch — the runner creates it from the plan's
   base when it doesn't exist yet.
3. **Know what is remotely runnable.** Only the unattended stages — `implement` and `address` — have
   a remote door. The interactive and deterministic stages (planning above all) stay local.
4. **Observe the dispatched run.** Coordination happens through GitHub, not a watched terminal — see
   [How to observe and control dispatched runs](./supervise-dispatched-runs.md).

> **Maturity.** Both the dispatch wiring **and** the live end-to-end chain (dispatch → checkout →
> setup → drive → submit/resolve → reporting) are proven live on both the self-repo and a consumer
> repo with real `implement` and `address` runs; `perk doctor workflow smoke-test` still verifies
> dispatch and secrets only. See
> [Headless and remote: how it works, and how proven it is](../explanation/headless-and-remote.md)
> for the full maturity story.

---

← Back to the [how-to router](index.md).
