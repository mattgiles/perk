---
title: Worktree node_modules resolution trap — stale SDK shadowing
read_when: SDK census or CI red in files you never touched, a worktree resolving the parent's node_modules (setup skipped/failed), a Pi pin bump or host-floor raise, a stale or shared .pi/npm, version facts
cluster: toolchain-gotchas
---

# Worktree `node_modules` resolution

A perk worktree has **two npm worlds** that never overlap. The **root `node_modules`** is perk's
own dev-tool tree — what `tsc` / `node --test` resolve. A linked worktree under `.worktrees/`
resolves **its own** `node_modules` once the marker-gated `[worktree] setup` hook has run (perk's
own `.perk/config.toml` lists `uv sync --all-packages` + `npm ci`;
`src/perk/run/launch/__init__.py::run_pending_setup`, also reached by `perk worktree create`) —
until then those tools walk **up to the parent repo's `node_modules`** (the shared root checkout).
"Until then" is the live state in four cases: a hand-made or detached `git worktree add`; a
worktree whose setup **failed** (the `setup-pending` marker stays and the next launch retries);
anything run in the worktree **before** its first launch (`--dry-run` never runs the hook); and a
consumer repo whose `[worktree].setup` omits `npm ci`. The hook itself:
`workflow/cold-door-launch.md` § "The `[worktree] setup` hook is marker-gated". The **`.pi/npm/`
install root** is Pi's separately staged extension-install world: `materialize_extensions`
(`src/perk/run/launch/materialize.py`) stages the converged repo-root `.pi/npm/` into fresh
worktrees through `fsclone.clone_tree` (see `workflow/cold-door-launch.md` §"Launch banner +
worktree `.pi/npm` pre-staging"; drift/repair mechanics in `workflow/distribution.md` §
"init/doctor/launch own the `@mgiles/perk` npm install"). The resolution trap below is entirely a
**root-world** phenomenon, with two distinct symptoms.

One `.pi/npm`-world rule in passing: an `npm ci --prefix .pi/npm` EUSAGE failure before a live run
is an environment preflight blocker (the gitignored root drifts) — repair with
`npm install --prefix .pi/npm`; detail + posture in `workflow/distribution.md`.

## Distillation

- Two npm worlds: the root `node_modules` (perk's dev tools; a worktree whose setup hook has not
  run — hand-made, failed, or pre-launch — resolves the parent's) and `.pi/npm` (Pi's extension
  installs) — the intro above.
- Red in files you never touched → `git stash` to prove it pre-existing, then compare installed vs
  pinned SDK — "Symptom 1"; a worktree pin bump is inert until `npm install` runs there —
  "Symptom 2"; peer-only `pi-tui`/`typebox` resolutions go stale independently — "Symptom 3".
- Prove provenance before assuming you broke it; exit 143 with no `FAILED` line is a transient
  kill — "Diagnosing pre-existing breakage".
- `.pi/npm` staging is `fsclone.clone_tree` (macOS `clonefile(2)`, else hardlinks + detached
  metadata); `stat -f %l .pi/npm/package.json` > 1 ⇒ the legacy shared layout; a `.pi/npm` package
  can be stale on disk while `npm ls` says it is correct — "The `.pi/npm` world in perk's own
  checkout".
- `git checkout package-lock.json` drops incidental lockfile churn when the manifest did not
  change; a pin bump keeps npm's full output — "Commit hygiene after installing in a worktree".
- A Pi pin bump: `just bump-pi`, keep npm's whole canonical lockfile output and prove it,
  `npm run typecheck` is mandatory, the companions are exact-declared since 1.3.0 — "Pi pin-bump
  mechanics".
- Host floor, adopted Pi pin + install set, dev pins, the pi-subagents pin and the guidance stamp
  are five distinct facts (adopted ≠ certified); tests stay version-honest — "Five version facts,
  kept distinct".
- Smoke the worktree's `.venv/bin/perk` and run `perk init` smokes in a scratch dir — "Stale
  globally-installed `perk`".

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
root checkout, depending on which `node_modules` is resolving), or the bump is inert. The
launch-path hook runs `npm ci` only at materialization, so a bump made *inside* an already-set-up
worktree still needs an explicit `npm install` there.

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
broken at your branch point (a merge race can leave a stale fixture failing tsc on origin/main
HEAD; see `workflow/cold-door-client.md` §"The merge-race fixture sweep" for the incident shape
and the repo-wide fixture-sweep rule). Before assuming you caused it, **prove provenance**:

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

Two sibling one-line rules live here (their corpus home): **test exit 143 (SIGTERM) with no
`FAILED` line is a transient kill — rerun before debugging** (a run-all cancellation fans out as
MIXED wrapper statuses: aligned termination timestamps + truncated tails + no `FAILED`/`✖` lines
across several concurrent checks — `signal 15`/`exit 143` on some, a bare `exit 1` on a
dot-reporter suite — is a runner abort; inspect the scratch `ci-*.md` tails and rerun the gate
before debugging code, #2471); and **whole-tree `typecheck-py`
(ty) is change-unscoped** — a sibling's latent `tests/` ty debt lands red on `main` and blocks an
unrelated PR; prove it pre-existing via the git-stash diagnostic above and clear it separately.

## The `.pi/npm` world in perk's own checkout

Nothing but a Pi launch populates `.pi/npm` here (#2501): `perk doctor --fix` reports
`extension-install: self-repo — local package, no npm install` and `subagent-compat: pi-subagents
not installed — compatibility not evaluated` (its detail: pi lazy-installs the package at launch).
The two populators are Pi's lazy install at an
INTERACTIVE first launch (the Trust step) and `materialize_extensions`' staging (plan-worktree
launches only). A hand-made detached worktree under `.worktrees/` inherits nearest-ancestor trust
(so it never sees the first) and is not a plan launch (so it never sees the second) — stage it
explicitly with `materialize_extensions(<main>, <worktree>)` (`perk/run/launch/materialize.py`).

**How staging isolates (`src/perk/substrate/fsclone.py::clone_tree`).** On macOS a `clonefile(2)`
via ctypes — a whole-hierarchy copy-on-write clone with independent inodes; otherwise
`copytree(copy_function=os.link)` then `detach_shared_files`, which gives every root- and
`node_modules`-level regular file with `st_nlink > 1` its own inode. There is deliberately no
byte-copy tier (CPython's macOS `copy2`/`copyfile` is a byte copy, not a clone). An unpopulated
`dst` is removed first; a partial tree is removed on failure. The structural rule: package
directories are safe to hardlink because package managers replace them wholesale; metadata files
(`package.json`, lockfiles, `node_modules/.package-lock.json`) are rewritten in place and must not
share inodes — the legacy all-hardlink layout shared `package.json` across ~50 trees, so one
install changed every tree.

- **Diagnostic:** `stat -f %l .pi/npm/package.json` > 1 ⇒ legacy shared layout.
- **Every perk launch detaches still-shared metadata** (`pi_exec._detach_extension_install`,
  lazily per worktree); running `pi` directly in a legacy worktree still writes through shared
  inodes.
- A one-time stale-spec warning (`materialize.py::_stale_extension_specs`) fires at stage launch
  only (`perk resume` skips it).
- Merging never touches gitignored `.pi/npm`, so the main checkout and sibling worktrees keep their
  old installs until re-staged, and new worktrees copy whatever main has.
- On the hardlink tier package files stay shared — a tool patching installed files in place leaks
  across trees; the clonefile tier is darwin-only and tested locally only.
- The launch seam itself: `workflow/cold-door-launch.md` § "Launch banner + worktree `.pi/npm`
  pre-staging".

**A `.pi/npm` package can be stale on disk while npm reports it correct.** The census drift guard
in `extension/substrate/nativeSdkBridge.test.ts` saw pi-subagents 0.71.0 (no `typebox/value`)
although `.pi/npm/package.json` wanted `^0.72.1` and both the hidden lockfile and `npm ls` said
0.72.1 — the package folder's own `package.json` / `CHANGELOG.md` were 0.71.0. A plain
`npm install` "added 232 packages" and left the folder untouched; the fix was removing
`.pi/npm/node_modules/<pkg>` and reinstalling. Three consecutive PRs read this as "the census is
stale" — it was not. The rules:

- A census/version failure that disagrees with the lockfile is **install-root staleness**, not code
  drift — check the package's on-disk `package.json`, never `npm ls`.
- The fix is worktree-local and gitignored; the main checkout had the same stale folder.
- Before blaming a branch, reproduce in a detached `origin/main` worktree with `node_modules` and
  `.pi/npm` symlinked in.

## Commit hygiene after installing in a worktree

A worktree that **skipped or failed setup has no `node_modules`** — run the hook's commands
(`npm ci`) before `tsc` / `node --test`, or they resolve `@earendil-works/*` from the parent
checkout's (possibly stale) tree, or not at all (the resolution-walk premise above); the normal
launch path has already done this. The allow-scripts warnings `npm ci` prints are benign.

**Revert only incidental lockfile diffs — never an intentional pin bump.** An incidental diff is a
`package-lock.json` change with NO `package.json` change: the `"peer": true` annotations a worktree
`npm install` adds on transitive deps (e.g. pi-tui, typebox, marked, get-east-asian-width), or the
`pi-ai` bin-path normalization churn below. Run `git checkout package-lock.json` before committing
to keep the PR diff clean. On an intentional pin bump the lockfile diff **is** part of the change:
keep npm's full output and accept it by § "Pi pin-bump mechanics"' validation
(`npm install --package-lock-only` byte-identical, `npm ci`, the `npm ls` gate).

A second churn shape — `pi-ai` bin-path npm-normalization rewrites with no dependency change —
has its rule and detail in `workflow/distribution.md` (§the git→npm install mirror):
`git checkout package-lock.json` before staging when that is the only diff.

## Pi pin-bump mechanics (used at 0.99.2, 1.0.0, 1.1.0, 1.4.0)

`just bump-pi <version>` moves the four `@earendil-works/*` exact dev pins (pi-coding-agent, pi-ai,
pi-tui, pi-agent-core) and runs an `npm ls` gate, the typecheck, `piAiCompatGuard.test.ts` and
`tests/test_packaging.py::test_pi_toolchain_pin_lockstep` (which pins a closed key set). It stops
at its first failing line — after a fixture fix run the remaining gate lines one by one; never
re-run the recipe.

- **Lockfile posture: keep npm's whole canonical output and prove it.** The earlier trim rules
  (hand-preserving a shrinkwrapped tree, reverting incidental re-resolutions) were set aside by
  operator decision at 1.1.0. Acceptance is the validation, not a byte shape:
  `npm install --package-lock-only` leaves the file byte-identical, `npm ci` passes, the `npm ls`
  gate exits 0, and nothing is extraneous.
- **Prune orphans.** Dropping a devDependency leaves extraneous packages — run `npm prune`;
  `npm ls <names>` exits 0 when every problem is `extraneous` (npm 11.16), so the gate misses them.
- **`npm run typecheck` is mandatory** — node:test type-stripping hides SDK type breakage, and
  `as unknown as` fakes never flag interface growth.
- **Grep comments repo-wide** for the old floor literal and old install-shape wording.
- **The pinned package's `schemas/` is a test oracle** — `extension/testing/piConfigSchemas.ts`
  reads them from the root dev install, so the bump's install refreshes it
  (`pi/extension-api.md` § Pi config files and their schemas).
- **The companion graph.** Since Pi 1.3.0 the package declares its companions at exact versions
  (no shrinkwrap since 1.0.1); `PI_COMPANION_PACKAGES` is the presence/version check, and
  `tests/test_pi_host.py` pins exactness and closure against the lockfile. If Pi returns to caret
  ranges those tests fail by name, and a registry `maxSatisfying` preflight plus a closed
  multi-spec install become relevant again (derive the companion set from the target release's
  package manifests, never hardcode).
- **The global single-spec install nests the companions** under the package with only `bin/pi`
  linked — nesting is the healthy layout (the broken-host fixture in `tests/_pi_layout.py` is
  broken by version mismatch or a dangling link, not by nesting).
- **Lockfile-instrument gotchas.** `lockdiff` "ranges unchanged" ≠ revertable; `lockrevert`
  matches dependents by name regardless of nesting.
- **A stale installed SDK fails loudly**: the installed-SDK precondition test in
  `extension/substrate/hostAdmission.test.ts` refuses a below-floor `node_modules` — repair with
  `npm ci`, never weaken the test.
- **The root checkout's `node_modules` can lag the manifest** — never run the suites from it.

Records: `docs/design/archive/pi-1.0.0-dev-pins.md`, `docs/design/archive/pi-1.1.0-dev-pins.md`,
`docs/design/archive/pi-1.4.0-adoption.md`.

## Five version facts, kept distinct

1. **The host floor** — `shared/host-floor.yaml`, read by both planes' admission.
2. **The adopted Pi pin + pinned install set** — `src/perk/substrate/pi_host.py`
   (`PI_ADOPTED_VERSION`, `PI_COMPANION_PACKAGES`, `PI_INSTALL_SPECS`, `PI_INSTALL_COMMAND`); it
   pins the global CLI repair, the consumer remote CLI and the worker SDK.
   `workflow_artifacts.REMOTE_PI_VERSION` is an import-bound alias, never a second literal.
3. **The dev pins** — `package.json` devDependencies; also the self-repo remote worker's SDK via
   `npm ci`.
4. **The pi-subagents supplier pin** — `src/perk/convergence/init/settings.py::SUBAGENTS_PACKAGE`,
   reconciled by `settings-wiring`.
5. **The guidance stamp** — `_SUBAGENTS_GUIDANCE_VERIFIED_VERSION` (`pi/subagents.md` § Sources).

A comment or doc merging any two is drift. The pin-surface table (homes, guards, how each moves)
is owned by `docs/developers/pi-subagents-reverify.md` § The five version facts — the upkeep source
of truth; don't restate it.

- **Adopted vs certified.** A pin moves as *adopted* on characterization + offline evidence;
  *certified* is a later live record; nothing says "certified" before it exists. Pin-leads-stamp
  is legitimate, and the version-honest test shape is
  `tests/test_doctor.py::test_subagent_compat_on_the_pinned_install_follows_the_stamp` (it plants
  the installed version and asserts warn-iff-differs, so no test edit is owed whichever fact
  moves).
- **Sort a floor-raise test list one test at a time** by where the floor comes from: grep
  real-probe and floor-default callers; assert the derived remediation constant in `env.py` rather
  than a literal; keep literals only in the deliberate drift-alarm tests.
- **The committed self-repo managed artifacts have a lockstep test**
  (`tests/test_workflow_artifacts.py::test_committed_self_repo_remote_artifacts_are_the_owners_render`),
  so a forgotten regeneration fails CI — regenerate through the owner, never hand-revert its render.

**Version-honest tests** (dated): an expectation that
holds on both hosts stays unconditional; host-differing expectations were a branched pair until
SDK-boundary admission retired the old arms — do not reintroduce a `hostSdkAtLeast`-style helper.
Assertions on Pi-rendered tool description text are fragile (1.0.0 dropped codemode's inline
"Model API" section). Branch a repo-state precondition on
`satisfies_floor(parse_semver(pin), floor)` (`src/perk/substrate/semver.py`) rather than asserting
`pin != floor`.

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

**Nested vs top-level package instances each carry their own module-global registries** (pi-ai
was nested under `pi-coding-agent` until 1.0.1 and is hoisted top-level since; the principle holds
whenever two copies exist) — see
`docs/learned/pi/headless-session-drive.md` § "Driving the real runtime offline with a faux model
(the e2e worker tier)" (the per-instance pi-ai bullet) for the resolution pattern.

## Cross-references

- `docs/learned/pi/extension-api.md` — the extension API surface a stale SDK fails to provide;
  § "Host admission at the SDK boundary" for the floor the precondition test enforces
- `docs/learned/workflow/init-doctor.md` — the host-floor rows in `perk init` / `perk doctor`
- `docs/learned/toolchain/biome.md` — the other half of the TS CI gate
- `docs/learned/workflow/provider-seam.md` — the `shared/providers.yaml` seam these smokes exercise
- `docs/learned/workflow/cold-door-client.md` — the merge-race fixture sweep after a cross-plane
  shape change
- `docs/learned/workflow/cold-door-launch.md` — the worktree `.pi/npm` pre-staging (the two-world
  home)
- `docs/learned/workflow/mergeability-and-conflict-resolution.md` — the relocated manual
  rebase-recovery recipes (delete/edit + interrupted rebase)
- `docs/learned/workflow/distribution.md` — the `pi-ai` bin-path lockfile churn at the release seam
- `docs/learned/pi/headless-session-drive.md` § "Driving the real runtime offline with a faux model
  (the e2e worker tier)" — the per-instance pi-ai registry resolution
