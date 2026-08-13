---
title: Worktree node_modules resolution trap — stale SDK shadowing
read_when: CI surfaces failures in files your diff never touched, a fresh worktree fails `tsc`/`node --test` before `npm ci`, a pinned Pi/SDK bump seems inert, or you hit lockfile churn / an already-red main.
cluster: toolchain-gotchas
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

## Symptom 3: wildcard-peer resolutions go stale independently of the direct pins

Bumping the `pi-coding-agent`/`pi-ai` devDependencies does **NOT** move the top-level
`@earendil-works/pi-tui`/`typebox` resolutions — those are peer-only, and npm leaves an already
installed satisfying version in place (they stayed at 0.78.0/1.1.39 across two prior SDK bumps).
Direct imports of those packages then silently typecheck against ancient types. Fix shape: add
**explicit devDependency pins matching pi's bundled versions**, `npm ci` *before* editing the
manifest (so the install starts from lockfile truth), then `npm install` in the worktree, then
verify the top-level resolutions with `npm ls`.

## Diagnosing pre-existing breakage (prove provenance FIRST)

A stale SDK is only one cause of "red in files I never touched" — main itself can be genuinely
broken at your branch point (e.g. the #386/#387 merge race left a stale `issue: { number }`
fixture failing tsc on origin/main HEAD; both #391 and #392 found genuine red-on-main this way).
Before assuming you caused it, **prove provenance**:

```
git stash && npx tsc --noEmit -p . && git stash pop
```

(or run the suite on the clean branch point). If the failure reproduces without your diff, it's
pre-existing — fix-the-fixture in-scope when it's a one-line contract-shape correction, and never
misattribute it to your change.

**A green rebase doesn't freeze the target:** main can advance *again* mid-flight — a CI failure
naming files/tests absent from your branch means *re-check `git log origin/main`*, not your diff
(the same "red in files I never touched" family, with a moving branch point instead of a stale
SDK).

### The delete/edit rebase-conflict recipe

When main edits lines your branch *moved* to a new file, the rebase surfaces a delete/edit
conflict. Resolution: **keep the deletion, then verify the moved copy already carries main's fix**
(grep the new file for the fixed shape). When a payload shape changes, grep ALL test fixtures
repo-wide, not just the owning module's suite (see `workflow/cold-door-client.md`'s merge-race
fixture sweep).

### Interrupted-rebase recovery

When a rebase is interrupted mid-pick (e.g. a killed process leaves `.git/rebase-merge` behind),
**never start another rebase**. Read `git status` first — it shows the done list and the staged
pick's content — then `git commit -C <pick-sha>` the staged step and `git rebase --continue`.

## Commit hygiene after installing in a worktree

A **fresh `.worktrees/plan-N` has no `node_modules`** — run `npm ci` (or `npm install`) first, or
`tsc` / `node --test` cannot resolve `@earendil-works/*` (the same resolution-walk premise above).
The allow-scripts warnings `npm ci` prints are benign.

`npm install` in a worktree **dirties `package-lock.json`** with incidental `"peer": true`
annotations on transitive deps (e.g. pi-tui, typebox, marked, get-east-asian-width). Run
`git checkout package-lock.json` before committing to keep the PR diff clean — these annotations are
not part of the change.

A **second lockfile-churn shape**: npm invocations during CI/verification can rewrite
`package-lock.json` with **no dependency change at all** — e.g. a `bin` path normalization
(`./dist/cli.js` → `dist/cli.js`) produced by a different npm version. On a dirty-tree submit
refusal, inspect the lockfile diff for this shape and `git checkout -- package-lock.json` rather
than investigating a phantom dependency change or committing tooling noise.

## The gitignored `.pi/npm` install root drifts independently of the tracked lockfile

The Pi-owned `.pi/npm` install root is gitignored, so it drifts independently of the tracked root
lockfile — an `npm ci --prefix .pi/npm` EUSAGE failure before a live run is an **environment
preflight blocker, not a product defect**: heal with `npm install --prefix .pi/npm`, restart the
declared preflight without consuming attempt budget, and never commit the ignored install state.

## False failure: a `run_ci` test exit of -1/143 is a kill, not a failure

A `run_ci` test run reporting exit code **-1/143 with no `FAILED` line** was SIGTERMed mid-run,
not failed — a clean rerun passes unchanged. Check for an actual `FAILED` assertion line before
debugging; rerun first.

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
- `docs/learned/workflow/cold-door-client.md` — the merge-race fixture sweep after a cross-plane
  shape change
