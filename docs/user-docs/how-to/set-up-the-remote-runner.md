---
title: "How to set up and verify the remote runner"
description: "Get a repo ready to dispatch perk stages to a remote CI runner, and prove the wiring is live before you depend on it."
sidebar:
  order: 2220
sidebarGroup: "Headless & remote"
---

# How to set up and verify the remote runner

Get a repo ready to dispatch perk stages to a remote CI runner, and prove the wiring is live before
you depend on it. This is the precondition for [dispatching a stage to CI](./dispatch-a-stage-to-ci.md):
do it once per repo (and again whenever the managed runner artifact drifts).

## Steps

1. **Converge the managed runner artifact.** Run
   [`perk init`](../reference/cli.md#perk-init) to install (or re-converge) the managed
   `.github/workflows/perk-run.yml`; run [`perk doctor --fix`](../reference/cli.md#perk-doctor) to
   repair drift if the file was hand-edited or removed.
2. **Run the static prereq check.** Run
   [`perk doctor workflow check`](../reference/cli.md#perk-doctor-workflow-check) to verify GitHub
   readiness, the runner prerequisites, and that the managed workflow is present. Add `--verbose`
   for per-check detail or `--json` for a machine-readable report.
3. **Configure the runner secret and the enable gate.** The runner pushes with a PAT (`PERK_GH_PAT`),
   **not** the default `github.token`, so set that secret in the repo. Remote runs are also gated by
   a repo-level runner-enabled variable: until it is on, `smoke-test` refuses to dispatch. Set both so
   the runner is allowed to start.

   > **Note.** `PERK_GH_PAT` is also the credential the runner uses to clone the repo's declared
   > skill sources when it syncs skills before driving — if a private repo authors its own skills
   > (or declares another private source), the PAT must be able to read those repos. Public
   > sources need nothing extra.
4. **Prove the runner is live.** Run
   [`perk doctor workflow smoke-test`](../reference/cli.md#perk-doctor-workflow-smoke-test) (add
   `--wait` to block on the result). It dispatches a throwaway run that proves dispatchability,
   runner-start, and secret-readability — and it writes nothing durable (no dispatch record, no
   GitHub artifacts), so it never shows up in `perk workflow run list`.

> **Maturity.** The smoke test proves the *wiring* — that a run can be dispatched, the runner starts,
> and its secrets are readable — but **not** the end-to-end worker/model drive that a real stage
> needs. That full chain has live proofs on both the self-repo and a consumer repo (real
> `implement` + `address` runs, end to end). See
> [Headless and remote: how it works, and how proven it is](../explanation/headless-and-remote.md)
> for the full maturity story.

---

← Back to the [how-to router](index.md).
