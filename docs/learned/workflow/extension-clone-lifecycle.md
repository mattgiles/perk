---
title: The pi `git:`-package loading substrate (historical) + the retire-an-orphaned-lifecycle recipe
read_when: You need pi's `git:`-package loading internals (how a `git:` extension is cloned/installed/loaded), OR you are retiring an orphaned substrate lifecycle (relocate-the-survivor + facade scrub + three-site doctor-check removal + the `_MIGRATIONS` filesystem-rmtree forward-migration seam). NOTE the git-clone extension lifecycle this doc once owned is RETIRED — perk now ships as `npm:@perk/pi`; the live extension-delivery story is in `distribution.md`.
---

# The pi `git:`-package loading substrate (historical) + the retire-recipe

> **Retired.** perk's own Pi extension moved from a `git:` package to **`npm:@perk/pi`**. The entire
> git-clone extension lifecycle module (`perk/convergence/init/extension_clone.py`) and its
> `extension-clone` doctor check were **removed**. The **live** extension-delivery lifecycle (the npm
> install, owned by init/doctor/launch) now lives in **`distribution.md`**. This doc is retained for
> two durable things: the **pi-`git:`-loading substrate** (still accurate for understanding *any*
> `git:` package) and the **retire-an-orphaned-lifecycle recipe** the removal produced.

## How pi loads a `git:`-package extension (the root-cause substrate)

perk *formerly* shipped as a Pi `git:` package; pi materialized it as a git **clone** on the
consumer's disk and loaded the TS extension from it. This substrate is still exactly how pi loads
**any** `git:` package, so it is kept here.

pi loads a `git:`-package extension from a clone at `.pi/git/<host>/<path>/` via jiti, resolving the
extension's imports through a **fixed host-alias set**
(`@earendil-works/pi-coding-agent`/`-ai`/`-tui`, `@mariozechner/*`, `typebox`/`@sinclair/typebox`)
**plus** native `node_modules` walking. The relevant internals live in
`@earendil-works/pi-coding-agent/dist/core/package-manager.js`, where three distinct gaps could leave
a consumer loading *no* tools or *months-old* code:

- **(a) No self-heal install.** `installGit`/`ensureGitRef` run `npm install --omit=dev` **only**
  on a fresh clone OR when `localHead != targetHead`. A clone already present at the pinned ref
  returns early and never installs (`pi update` shares that early return). So a clone can carry no /
  partial `node_modules` and pi cannot self-heal → `Cannot find module 'yaml'` at load.
- **(b) Unlocked lazy clone race.** `resolvePackageSources` clones a missing `git:` package lazily
  and **UNLOCKED**. Two near-simultaneous launches against an absent clone race: the second sees the
  first's half-created dir, takes the `else` (collect) branch over an incomplete checkout, and the
  extension **silently fails to load** — none of its tools appear, it is absent from
  `[Extensions]`, and a throwing extension lands only in pi's `errors[]`.
- **(c) Frozen present clone.** A **present project-scoped** clone is left **frozen** — pi's branch
  for it only calls `collectPackageResources` with no `git fetch`/`reset`, so a months-old clone
  keeps loading months-old code (wrong import paths; a since-retired import → a hard load failure)
  while a static `doctor` reports green.

These gaps are why perk, while it shipped as a `git:` package, had to own its clone's deps,
freshness, and materialization itself. That ownership is **gone** with the npm move; only the
substrate above survives.

## Where the live story went (and the dep-elimination)

The four-PR arc that made perk the owner of its own clone (deps / freshness / materialization),
the `extension_clone_status` ownership recipe (init-converges / doctor-repairs / launch-warms), and
the clone-specific gotchas it produced are **retired** — superseded by the npm-install lifecycle in
**`distribution.md`** (which also records the four *mirror-breaks* where "just copy the git
lifecycle" would be wrong). The one still-general piece of the deps story — **dropping an npm parser
by vendoring a bounded reader** (`extension/substrate/miniYaml.ts`, scoped to perk's own files, so an
unsupported edit throws loudly) — lives in `shared-contracts.md` and `prompt-templates.md`.

## The retire-an-orphaned-lifecycle recipe (the durable removal value)

When a substrate lifecycle module is superseded and you remove it, this is the reusable recipe:

- **Relocate the one surviving primitive to its dependency's home — don't keep the dead module alive
  for it.** `consumer_git_clone_root` moved **verbatim** into `settings.py` **beside its sole
  dependency `GIT_PACKAGE`**, re-exported through the `init/__init__.py` facade so the
  `init.consumer_git_clone_root` attribute path keeps resolving for every consumer unchanged. The
  facade is a real surface to scrub: drop the dead module's whole import block + its `__all__` entries,
  re-add the relocated survivor to the settings import — **RUF022 isort-alphabetical in BOTH the import
  list and `__all__`** — delete the orchestrator helper + its call site, and **fix the package
  docstring** (it enumerated the now-gone submodule + a now-gone monkeypatch target).
- **Removing a doctor check is a three-site edit:** the `_xxx_check` def in `checks.py`; the import +
  `__all__` entry + `checks.append(...)` registration in `doctor/__init__.py` (reword the grouping
  comment that paired it with a sibling); and the `elif check.name == "..."` fix branch in `fixes.py`.
  Keep the sibling check (`extension-install`) intact.
- **Dead substrate primitives go last, after proving sole-consumption.** `git.clone` / `reset_hard` /
  `head_sha` / `ls_remote_sha` were verified (repo-wide grep) consumed **only** by the deleted module →
  removed with their tests. **Shared** primitives (`git.fetch`, used by `worktree.py`) and shared
  fixtures **stay** — prove sole-consumption before deleting.
- **The `_MIGRATIONS` forward-migration seam (a filesystem `rmtree`).** `doctor --fix` migrates a former
  consumer forward via `_remove_orphaned_git_clone(root)` appended to the `_MIGRATIONS` tuple
  (`perk/convergence/doctor/fixes.py`): forward-only, **idempotent** (a genuine `([], [])` no-op once
  the clone is absent), returns `(changes, errors)` so a failed `shutil.rmtree` lands on
  `report.fix_errors` **loudly** (`OSError` → append to errors). Filesystem-only on a gitignored path
  (no network); `_MIGRATIONS` runs **unconditionally** after the fix loop, so a
  `run_doctor(fix=True, verify=False)` test exercises it without seeding a failing check.

## A still-general gotcha (kept)

- **Test-insertion split-assert (F821 trap).** Inserting a new test function *between* two existing
  tests with an `edit` `oldText` that stops at the prior test's first visible terminator (e.g. a
  closing `]`) can orphan a trailing line that belonged to that test (a stranded
  `assert report_to_dict(report)[...]` → `F821 Undefined name report`). When inserting between
  functions, anchor on the prior test's **complete** boundary (its last statement), not the first
  plausible-looking end.

## Cross-references

- `docs/learned/workflow/distribution.md` — the **npm-install** extension-delivery lifecycle that
  superseded the git-clone lifecycle (and the four mirror-breaks)
- `perk/convergence/init/settings.py` — `consumer_git_clone_root` (the relocated survivor) + `GIT_PACKAGE`
- `perk/convergence/doctor/fixes.py` — `_remove_orphaned_git_clone` + the `_MIGRATIONS` tuple
- `@earendil-works/pi-coding-agent/dist/core/package-manager.js` — the pi `git:`-loading internals
- `docs/learned/workflow/init-doctor.md` — managed-convergence + verify-gated reconcile SSOT
- `docs/learned/workflow/shared-contracts.md` — the vendored `miniYaml` reader (the dropped npm parser)
