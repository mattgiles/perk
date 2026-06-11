---
title: Worktree node_modules resolution trap — stale SDK shadowing
read_when: CI surfaces typecheck/test failures in files your diff never touched, a fresh worktree fails `tsc`/`node --test` before `npm ci`, you bump a pinned Pi/SDK version in a worktree and the change seems to do nothing, or a `shared/` source change is not reflected when smoked via the global `perk` binary.
---

# Worktree `node_modules` resolution

A perk worktree under `.worktrees/` has **no `node_modules` of its own**, so `node --test` / `tsc`
resolve `@earendil-works/*` by walking **up to the parent repo's `node_modules`** (the shared root
checkout). This is a real trap with two distinct symptoms.

## Symptom 1: pre-existing failures in files you never touched

On a freshly-landed branch the **root** checkout's installed SDK can lag what HEAD's code expects.
The failure looks like it's your diff but isn't — e.g. `run_ci` reporting `Property 'mode' does not
exist on type 'ExtensionContext'`, `getSystemPromptOptions` errors, and failing `selfcheck (live)` /
`run_mode` tests that have nothing to do with the change.

**Diagnosis practice:** when CI surfaces failures in files you never touched, `git stash` to confirm
they're **pre-existing** (they reproduce without your diff), then compare the **installed vs. pinned**
SDK version (`node_modules/@earendil-works/pi-coding-agent/package.json` vs. the repo's
`package.json`). An `npm install` from the root checkout bumps the installed version and turns CI
green. The install touches only the root checkout's `node_modules` / lockfile — the **worktree's
`git status` stays clean**.

## Symptom 2: a version bump in the worktree does nothing

A devDependency bump in the **worktree's** `package.json` (e.g. 0.78.0 → 0.78.1) **does nothing until
`npm install` runs inside the worktree** — only then does a local (gitignored) `node_modules` get
created that **shadows the parent**. Until then, typecheck/tests silently keep using the parent's old
version.

**Rule:** any plan that bumps a pinned Pi/SDK version must run `npm install` in the worktree (or the
root checkout, depending on which `node_modules` is resolving), or the bump is inert.

## Commit hygiene after installing in a worktree

A **fresh `.worktrees/plan-N` has no `node_modules`** — run `npm ci` (or `npm install`) first, or
`tsc` / `node --test` cannot resolve `@earendil-works/*` (the same resolution-walk premise above).
The allow-scripts warnings `npm ci` prints are benign.

`npm install` in a worktree **dirties `package-lock.json`** with incidental `"peer": true`
annotations on transitive deps (e.g. pi-tui, typebox, marked, get-east-asian-width). Run
`git checkout package-lock.json` before committing to keep the PR diff clean — these annotations are
not part of the change.

## Stale globally-installed `perk` + accidental self-converge

The same staleness trap has a Python-plane analogue. A smoke that exercises a `shared/` source change
can silently run the **globally installed `perk`** (e.g. v0.0.1), which reads the **bundled (old)
`providers.yaml`** rather than the worktree's `shared/` source — so the change appears to do nothing.
To smoke a `shared/` source change you must run the **worktree's `.venv/bin/perk`** (the editable
install resolves `shared/` from the repo sibling), not whatever `perk` is on `PATH`.

Separately, running `perk init` (e.g. `uv run perk init`) **from inside the worktree converges the
worktree repo itself** — it rewrites `.gitignore` ordering, adds manifest skill entries, and similar
incidental dirt that must be `git checkout`-reverted before commit. **Rule:** run `perk init` smokes
in a **scratch dir, never the worktree.**

## The stale-SDK trap generalizes: per-instance module-global registries

The same premise has a sharper variant: **nested vs top-level package instances each carry their
own module-global registries**. `pi-coding-agent` bundles its own nested copy of
`@earendil-works/pi-ai`, so anything registered against the top-level instance is invisible to the
runtime's nested one — see `docs/learned/pi/headless-session-drive.md` for the resolution pattern.

## Cross-references

- `docs/learned/pi/extension-api.md` — the 0.78.x API surface a stale SDK fails to provide
- `docs/learned/toolchain/biome.md` — the other half of the TS CI gate
- `docs/learned/workflow/provider-seam.md` — the `shared/providers.yaml` seam these smokes exercise
