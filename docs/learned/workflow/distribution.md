---
title: How perk ships — version SSOT, the dual-plane release workflow, the install-pin policy, and init/doctor owning the npm install
read_when: You are working on perk's release workflow, the version SSOT, PyPI/npm publishing (OIDC trusted publishing, `npm publish --provenance`), the consumer install-pin policy, the git→npm extension-wiring flip, or init/doctor/launch owning the `@perk/pi` npm install.
---

# Distribution — how perk ships as published packages

perk ships as **two published packages from one repo**: a Python wheel/sdist (`perk` on PyPI, the
CLI + the wheel-bundled `shared/`/`agents/` resources) and an npm tarball (`@perk/pi`, the Pi
extension). This doc is the durable arc of *how* perk became publishable — the version SSOT, the
build-backend decision that constrains every future packaging change, the one dual-plane release
workflow, the install-pin policy, and how init/doctor/launch took ownership of the consumer-side npm
install (the mirror of the git-clone lifecycle, and the four places that mirror breaks).

## Version SSOT architecture

The single source of truth is the static `[project] version` in `pyproject.toml`, bumped with
`uv version` (which edits that field). The old `[tool.hatch.version]` dynamic-version model and the
hand-maintained literal `__version__` are both **gone**. `perk.__version__` is now **derived** at
import time via `importlib.metadata.version("perk")`, with a `pyproject.toml`-via-`tomllib` fallback
for an **uninstalled** source tree.

The load-bearing caveat: the `importlib.metadata` value reflects what is **installed**, so it can go
stale between a `uv version` bump and the next `uv sync` — `uv sync` (and CI's `uv sync`) re-install
the editable package and refresh it. The lockstep guard is `test_version_lockstep`, now **three-way**:
`package.json` == `pyproject.toml [project] version` == `perk.__version__` must all agree. A two-plane
bump (Python + npm) is deliberately **two commands**; the lockstep test is what prevents drift.

## Build-backend decision — KEEP hatchling, do NOT switch to `uv_build`

This is the constraint that governs every future packaging node, so it is recorded as a decision, not
just a fact: perk's wheel **force-includes** two top-level dirs into the package — `shared/` →
`perk/_shared` and `agents/` → `perk/_agents` — via hatchling's force-include, guarded by the
packaging suite (`tests/test_packaging.py`). `uv_build` cannot express this: it has **no wheel
force-include**, and its `tool.uv.build-backend.data` keys are **fixed sysconfig slots** that cannot
nest a payload at `site-packages/perk/_shared`. So hatchling stays.

Critically, the uv *release ergonomics* need nothing from `uv_build`: `uv build` / `uv publish` /
`uv version` are all **backend-agnostic** and work fine over a hatchling backend. Reach for uv's
release commands without touching the build backend.

## The dual-plane `release.yml` workflow

One tag-triggered workflow now serves PRs / main / tags / `workflow_dispatch` via **widened triggers
plus per-job gating**. The durable discipline this surfaced:

- **When you widen a tag-only workflow's triggers, audit EVERY existing job for tag-assumptions and
  gate them too.** The pre-existing `validate-release-versions` job read a `v`-prefixed ref and would
  break on a non-tag event — it had to gain the same `if: startsWith(github.ref, 'refs/tags/')` guard.
  Widening triggers is never "just add triggers"; it is "re-audit every job's ref assumptions."

- **The PyPI half is build-once / download-to-publish.** `build-pypi` runs always-on and uploads a
  deliberately-named artifact (`pypi-dist`); the publish jobs **download** that artifact and never
  rebuild. Publishing uses **OIDC trusted publishing** — no tokens, a per-job `id-token: write`, and
  GitHub **Environments with required reviewers** as the human gate. The trusted-publisher config is
  registered **out-of-band** on PyPI, so it is a **runbook obligation**, not something the workflow
  can self-configure.

- **The npm half is an intentional asymmetry.** `npm publish --provenance` **re-packs from source at
  publish time** and generates the Sigstore attestation **then** — so there is **no** build→publish
  artifact handoff on the npm side. `build-npm` is therefore an independent **always-on rehearsal**,
  not a producer feeding a publish job. Do not try to "fix" this into a symmetric build→download shape;
  the asymmetry is inherent to how npm provenance works.

- **Capstone:** a separate **tag-gated** `github-release` job `needs:` **both** publish jobs, so a
  single tag publishes both planes before the GitHub Release is cut.

## `npm publish --provenance` requires `repository.url` (the HTTP 422 trap)

Provenance fails with **HTTP 422** unless `package.json` carries a `repository.url` that **matches the
OIDC-detected repo** (case-sensitive). Adding `repository` / `homepage` / `bugs` to `package.json`
does **not** change the `npm pack` files surface (verified against the packaging suite), so it is a
safe metadata addition. Two adjacent facts: a scoped name like `@perk/pi` needs `--access public` on
first publish, and provenance needs npm ≥ 9.5 — Node 22 ships npm ≥ 10, so the runner is fine.

## The three-way install-pin policy

The durable distribution rule for how consumer-side install commands are pinned:

- **Machine / reproducibility surfaces pin to `__version__`** — the remote-runner consumer install
  (`perk/run/workflow_artifacts.py`) pins `perk=={__version__}`, and the npm extension wiring
  (`perk/substrate/settings.py` / the convergence layer) pins `@perk/pi@{__version__}`. Both derive
  from the **one** `__version__` SSOT (the `importlib`-derived value).
- **Human-facing docs stay unpinned (always-latest)** — `README` / get-started read a bare
  `uv tool install perk`.
- **The self-repo is exempt** — perk installs itself from `..` / `--from .`, never a version pin.

A practical consequence: pinning a machine surface to `__version__` can require **re-introducing** a
`from perk import __version__` import that an earlier node deliberately dropped — pinning a surface
re-creates the dependency on the SSOT symbol.

## The git→npm extension-wiring flip — protocol → identity discriminator

When perk's own Pi extension moved from a `git:` package entry to an `npm:` entry (`@perk/pi`), the
reconcile-forward logic in `_merge_static_packages` had to change its discriminator:

- **The discriminator shifted from PROTOCOL to IDENTITY.** The old git-vs-npm split keyed on the entry
  *protocol*. Once perk's own package is itself an `npm:` entry, a protocol-based split would wrongly
  reconcile **borrowed** npm packages (which must stay append-only). So the discriminator moved **down
  a level** — to an identity comparison against perk's own package **name**; every other npm entry is
  untouched. **Generalizable: when two formerly-distinct categories collapse into one protocol, the
  category discriminator must move down to identity-within-protocol.**

- **The in-body migration flipped DIRECTION.** It now strips the **legacy `git:` perk entry** by
  ref-agnostic identity, so an old-wired repo converges forward to the npm entry. `GIT_PACKAGE` is
  **retained**, but its role changed: from *desired-source* to *migration strip-identity*.

- **The transient-orphan cross-node convention.** The flip leaves the orphaned git-clone lifecycle
  (status/lock/materialize/freshness) running with an explicit **"retired in a later node"
  forward-pointer** comment, rather than retiring it inline or silently leaving stale text. Deliberate
  staged-deprecation hygiene: name the orphan and point forward.

## init/doctor/launch own the `@perk/pi` npm install — the git→npm mirror

The npm-install lifecycle **mirrors** the git-clone lifecycle (see `extension-clone-lifecycle.md`): a
gateway over the CLI, a status/lock/materialize/launch-warm path, and a verify-gated doctor check. But
four **mirror-breaks** are the durable take-aways — the places where "just copy the git lifecycle"
would be wrong:

- **The "trusted tool" assumption does NOT transfer.** The git gateway does not catch
  `FileNotFoundError` / `OSError`, because git is an **env-verified required tool**. **npm is not
  env-verified**, so the npm gateway's run-wrapper **must wrap `OSError`** into its domain error — else
  a host without npm raises a raw traceback past best-effort callers. **Rule: a gateway over a
  non-env-verified CLI must wrap `OSError` into its domain error; do not inherit the required-tool
  leniency.**

- **A best-effort `json.loads(...)[key]` reader must catch `TypeError`, not just `KeyError`.** A
  valid-but-non-dict `package.json` (`[]` / `null` / a scalar) parses fine, but subscripting it raises
  `TypeError` — a *different* failure mode from a missing key. A best-effort reader that only guards
  `KeyError` lets the `TypeError` escape.

- **A new fail-level check whose default state is `fail` on a fresh repo ripples into existing doctor
  tests.** This check maps `absent` / `mismatch` → **fail + `--fix`** (its charter is *install
  ownership*, and `--fix` only acts on `fail`), so a fresh `verify=True` run is now **unhealthy**.
  **Rule: census ALL `verify=True` `report.healthy` assertions when adding such a check** — `--fix`
  paths self-heal (the fix arm installs + re-verifies), plain-verify paths don't, so the baseline
  shifts. (See `init-doctor.md` for the fail-level-baseline-shift + verify=True census rules.)

- **The conftest install stub must land a HEALTHY terminal state (`present`), not `unverifiable`.**
  Forced by `absent → fail`: the fake must write `package.json` with the right version so a *second*
  init sees `present`; idempotency then becomes "no `@perk/pi` line in the second-run changes."

Mechanical reusables that DO transfer from the git lifecycle:

- The lock lives in the install **root** (survives a `node_modules` wipe — same principle as the clone
  lock living in the clone's parent).
- `.pi/npm/` is already **wholesale-gitignored**, so no new gitignore entry is needed.
- The `(file_stem, func_name)` sanctioned-subprocess guard needs the new wrapper's entry.
- **`git checkout package-lock.json` before staging** when the only lockfile diff is `pi-ai` bin-path
  npm-normalization churn from `just ci` / setup (a recurring noise diff — see
  `toolchain/worktree-node-modules.md`).

## Cross-references

- `docs/learned/workflow/extension-clone-lifecycle.md` — the git-clone lifecycle the npm-install
  lifecycle mirrors (and the four mirror-breaks above)
- `docs/learned/workflow/init-external-cli.md` — `__version__`'s post-collapse role (version-string +
  AGENTS-stamp only, never a ref pin)
- `docs/learned/workflow/init-doctor.md` — the fail-level-baseline-shift + `verify=True`
  `report.healthy` census rules a new fail-level check triggers
- `docs/learned/workflow/borrowed-packages.md` — the append-only borrowed npm entries the identity
  discriminator must spare
- `docs/learned/workflow/prompt-templates.md` — the zero-runtime-dep invariant (relevant when a node
  adds a runtime dep)
- `docs/learned/toolchain/worktree-node-modules.md` — the `package-lock.json` `pi-ai` bin-path churn
- `pyproject.toml`, `package.json`, `.github/workflows/release.yml` — the SSOT version + the dual-plane
  workflow
