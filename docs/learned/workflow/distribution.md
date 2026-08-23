---
title: How perk ships — version SSOT, the dual-plane release workflow, the install-pin policy, and init/doctor owning the npm install
read_when: You are working on perk's release workflow (`perk-dev release-*`), the version SSOT, PyPI/npm publishing, version parity, the `@mgiles/perk` install path, or the CHANGELOG bullet-token grammar.
cluster: config-and-convergence
---

# Distribution — how perk ships as published packages

perk ships as **two published packages from one repo**: a Python wheel/sdist (`perk` on PyPI, the
CLI + the wheel-bundled `shared/`/`agents/` resources) and an npm tarball (`@mgiles/perk`, the Pi
extension). This doc is the durable arc of *how* perk became publishable — the version SSOT, the
build-backend decision that constrains every future packaging change, the one dual-plane release
workflow, the install-pin policy, and how init/doctor/launch took ownership of the consumer-side npm
install (the mirror of the git-clone lifecycle, and the four places that mirror breaks).

## Distillation

- The version SSOT is `pyproject.toml [project] version`; `perk.__version__` derives via
  `importlib.metadata` (installed → can go stale until `uv sync`); the three-way lockstep test
  guards npm/pyproject/`__version__` — "Version SSOT architecture".
- KEEP hatchling: the wheel force-includes `shared/` → `perk/_shared` and `agents/` →
  `perk/_agents`, which `uv_build` cannot express; uv's release commands are backend-agnostic —
  "Build-backend decision — KEEP hatchling".
- One dual-plane `release.yml` publishes both packages — "The dual-plane `release.yml`
  workflow" (+ the layered local `perk-dev release-*` commands beside it).
- Install pinning is three-way: machine surfaces pin `__version__`, human docs stay unpinned,
  the self-repo is exempt — "The three-way install-pin policy".
- Parity is enforced by the launch env var, the soft drift signal, and the pin-lockstep test —
  "Version-parity enforcement".
- The extension wiring's reconcile discriminator flipped from PROTOCOL (git vs npm) to IDENTITY
  (perk's own package name) when both categories collapsed onto npm — "The git→npm
  extension-wiring flip".
- `.pi/npm` drift breaks `npm ci --prefix .pi/npm`; repair with `npm install --prefix .pi/npm`
  and re-run (environment-class) — "init/doctor/launch own the `@mgiles/perk` npm install".

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

## The never-published `packages/perk-dev` workspace member

perk's uv workspace carries a **dev-only member**, `packages/perk-dev`, that must **never** reach
PyPI. It depends on `perk` via `[tool.uv.sources] perk = { workspace = true }` and reuses perk's
seams — `perk-dev --version` reuses `perk.__version__`, and it calls `src/perk/substrate/git` — so
it is a workspace member, not a standalone package. Its exclusion from perk's published artifacts is
a **belt-and-suspenders** guarantee, three layers deep:

- **Pin `--package perk` at every `uv build` site** so the build only ever produces the `perk`
  distribution, never the member: `.github/workflows/release.yml`, the `justfile` `build` recipe,
  and `docs/release-checklist.md`.
- **`classifiers = ["Private :: Do Not Upload"]`** on the member's `[project]` — the PyPI-honored
  marker that rejects an accidental upload.
- **Standing packaging tests** assert the member is absent from perk's published **wheel and
  sdist**: `tests/test_packaging.py::test_wheel_excludes_perk_dev` and `test_sdist_excludes_perk_dev`
  (the latter also bars any `/packages/` path from the sdist).

The member's `[project] version` is a static `0.0.0` placeholder — intentionally **not** a
tracked/version-bearing surface (no lockstep guard), because `perk-dev --version` reuses
`perk.__version__` rather than carrying its own.

**The prose-enforced reality (tech debt worth documenting):** the `--package perk` build pins and
the `uv sync --all-packages` sync flag are **prose/comment-enforced, not test-enforced**. Reverting
either fails only via a **downstream symptom** — dropping `--all-packages` surfaces as an import
error in `tests/test_perk_dev_cli.py` (the pruned member is gone from the shared venv); dropping a
`--package perk` pin surfaces as a leaked member caught by the exclusion tests — rather than a
dedicated guard that names the reverted line. See `toolchain/uv-workspace-src-layout.md` for the
workspace/`src`-layout mechanics and the `--all-packages` member-pruning trap.

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

## The layered local `perk-dev release-*` commands

The local release preflight is three **layered** commands in `packages/perk-dev/src/perk_dev/cli.py`
(engines in `release.py` / `build.py`), each independently useful:

- **`release-check`** — pure **offline** structural/version/tag validation (changelog structure,
  version lockstep, tag agreement). It deliberately does **NOT** reuse `release.gather()` —
  gather's best-effort origin probe is network; the judging sibling stays offline. `--for-publish`
  adds a clean-tree gate.
- **`release-build`** — the local equivalent of `release.yml`'s build jobs (uv build/twine/wheel
  smoke; npm ci/pack). Artifacts go to a `TemporaryDirectory`, never `dist/` — a validation, not a
  producer. Its `build.verify_tarball_files` expectations are kept honest against **real**
  `npm pack` output by `tests/test_packaging.py`.
- **`release-tag [--push] [--dry-run]`** — creates the annotated `v{version}` tag with the name
  derived from the pyproject SSOT (structurally **no name argument** — you cannot mistype it).
  An existing tag at HEAD is a no-op; an existing tag **elsewhere** is a `tag_conflict` refusal
  (never silently no-op, never move a tag).

`publish-check` composes them (release-check + gh-auth + origin-tag probe + release-build — the
one-command pre-tag preflight); `docs/releasing.md` / `docs/release-checklist.md` already prefer
these commands over hand-run equivalents.

## Release-pipeline validation risks (what only a real release exercises)

Three parts of the release pipeline have never been exercised by PR/main CI — the next releaser
should treat the first real run as part of their validation:

- **The two `release.yml` inline python3 scripts run only on tag pushes.** The changelog-rolled
  gate in `validate-release-versions` and the curated-Release-body slicer in `github-release`
  never run on PR/main CI. They were validated once by a one-off local `/tmp` smoke; any
  regression surfaces only on the next real release tag. The first tag push after they land is
  the real test.
- **The release-header grammar (`^## \[X.Y.Z\] - YYYY-MM-DD`) is deliberately triplicated:**
  perk-dev's `changelog-check` validator plus the two release.yml inline scripts. The workflow
  comments say "promote to a perk-dev verb only if a third consumer appears", but there is **no
  structural sync guard** — if the grammar evolves, all three sites move together by hand.
- **`perk-dev publish-check`'s real composition path has never run end-to-end.** The subprocess
  `gh auth status`, the `git ls-remote` origin probe, and the full `release-build` are verified
  via `--help` + the hermetic seam-recorder suite only. Treat the first real `just publish-check`
  as part of validating it.

## The `[Unreleased]` bullet-token grammar (a hand-authoring trap)

Beside the release-*header* grammar above, `perk-dev release-check` also enforces a per-bullet
grammar on the `[Unreleased]` section: every **top-level** bullet must be a **single physical line
ending with a ` (commithash)` token**. `_TRAILING_HASH_RE` in
`packages/perk-dev/src/perk_dev/changelog.py` checks only the bullet's **first line** —
continuation/table lines beneath a bullet are unchecked — and **released** bullets must NOT carry
a token (`released_has_hash`). A hand-authored multi-line entry fails `unreleased_missing_hash`.

**Reshape recipe for a long entry:** one bullet line ending with the hash token, with any
table/detail as non-bullet lines beneath it (those lines are outside the grammar). This is
verification-time, hand-authoring-facing knowledge the header-grammar note doesn't cover —
`changelog-apply` stamps the token automatically; only hand-authored entries hit it.

**The two-commit ordering:** a hand-authored bullet for the *current* change has a
chicken-and-egg — the bullet requires a real trailing commit-hash token. Commit the
implementation **first**, then add the bullet stamped with that commit's short hash in a
**follow-up commit** (never amend — the hash would self-invalidate). Also keep the canonical
subsection order (`Major Changes, Added, Changed, Deprecated, Removed, Fixed, Security`):
`changelog-check` accepts out-of-order sections but `changelog-apply` inserts in canonical order,
so matching it avoids churn.

**The token goes stale across a rebase:** the `(shorthash)` token is stamped from the
implementation commit, and a conflict-resolving rebase (e.g. the `/submit` mergeability gate)
rewrites that commit — the token then silently points at a commit no longer on the branch; the
changelog check validates shape only, so nothing catches it. Rule: after any rebase that
rewrites the implementation commit, re-stamp the token from the current commit.

## `npm publish --provenance` requires `repository.url` (the HTTP 422 trap)

Provenance fails with **HTTP 422** unless `package.json` carries a `repository.url` that **matches the
OIDC-detected repo** (case-sensitive). Adding `repository` / `homepage` / `bugs` to `package.json`
does **not** change the `npm pack` files surface (verified against the packaging suite), so it is a
safe metadata addition. Two adjacent facts: a scoped name like `@mgiles/perk` needs `--access public` on
first publish, and provenance needs npm ≥ 9.5 — Node 22 ships npm ≥ 10, so the runner is fine.

## The three-way install-pin policy

The durable distribution rule for how consumer-side install commands are pinned:

- **Machine / reproducibility surfaces pin to `__version__`** — the remote-runner consumer install
  (`src/perk/run/workflow_artifacts.py`) pins `perk=={__version__}`, and the npm extension wiring
  (`src/perk/convergence/init/settings.py`, the `_perk_npm_entry` owner) pins `@mgiles/perk@{__version__}`. Both derive
  from the **one** `__version__` SSOT (the `importlib`-derived value).
- **Human-facing docs stay unpinned (always-latest)** — `README` / get-started read a bare
  `uv tool install perk`.
- **The self-repo is exempt** — perk installs itself from `..` / `--from .`, never a version pin.

A practical consequence: pinning a machine surface to `__version__` can require **re-introducing** a
`from perk import __version__` import that an earlier node deliberately dropped — pinning a surface
re-creates the dependency on the SSOT symbol.

## Version-parity enforcement — the launch env var, the soft drift signal, and the pin-lockstep test

The `__version__` SSOT is enforced into the *running session* by three deliberately-chosen mechanisms
(and one deliberately-rejected one). This builds on the install-pin policy above.

- **`PERK_CLI_VERSION` — a second, *informational* launch env var (the precedent).** `launch_stage`
  (`src/perk/run/launch/__init__.py`) injects **two** env vars into the `os.execvpe` env dict: the existing
  run-control `PERK_RUN_ID` **and** the new `PERK_CLI_VERSION = __version__`. The distinction (documented
  in contracts §8.2/§8.6a): `PERK_RUN_ID` is run-control data the extension *acts on*; `PERK_CLI_VERSION`
  is **informational only** — read solely to *compare* versions, never to drive state. This is the
  template for any future "carry a CLI fact into the session for display/comparison" need: add it to the
  single local-launch env dict, document it as non-run-control, and inject **at the local launch seam
  only** — the `--remote`/`--dry-run` paths early-return *before* this seam, so the remote worker (same
  pinned install, headless) is deliberately out of scope with no extra code.

- **Decision: NO third overlapping doctor check (confirmed with maintainer).** Parity is already
  enforced by two *existing* checks against the running CLI's `perk.__version__` SSOT: `settings-wiring`
  (the wired `npm:@mgiles/perk@{__version__}` pin, reconciled forward by `--fix`) and `extension-install`
  (installed-vs-pin, `mismatch`→fail). A redundant `version-parity` check only muddies doctor output.
  **General principle: before adding a doctor check, ask whether an existing check already covers the
  invariant from a different angle.** The later `cli-version` check is **not** that rejected
  duplicate: it compares the *running CLI* against the repo's committed
  `.perk/required-perk-version` requirement (a different axis from the wired/installed npm pins),
  warn-only.

- **The runtime skew the static checks can't see → a soft `session_start` signal.** The one version perk
  cannot statically check is the **live-loaded** extension: pi can lazy-install/load a stale
  `npm:@mgiles/perk`, so the running `@mgiles/perk` may differ from the launching CLI. The extension's
  `session_start` handler (`extension/index.ts`) compares `process.env.PERK_CLI_VERSION` against its own
  `perkVersion()` and, when both are present and differ, emits a **soft non-fatal `warning`** via the
  surfaces seam (`report()`, headless-safe) pointing at `perk doctor --fix`. Deliberately **no
  once-guard** — the simplest code (one plain `if` in the existing handler); re-emitting on reload is
  acceptable for a soft warning. Silent for ad-hoc `pi` (no env) and the self-repo (versions equal).
  Cross-ref `pi/extension-api.md` for the `session_start` handler facts.

- **Reusable test patterns:**
  - **Harness fact:** `sessionLifecycle.test.ts` loads the extension *from source*, so `perkVersion()`
    resolves to the real repo `package.json` version. A fake `PERK_CLI_VERSION: "9.9.9-not-real"`
    deterministically triggers the signal (assert `notifies` matches `/version parity/`); omitting the
    env deterministically suppresses it — no need to read/inject the real version in-test.
  - **Launch-env capture pattern:** to assert what env `launch_stage` passes to exec, monkeypatch
    `perk.run.launch.os.execvpe` with a **recorder** (`lambda _f,_a,env: captured.update(env)`) rather
    than a discarding `_no_exec`, plus the usual `os.chdir`→no-op and `get_plan_body`→None stubs; then
    assert `captured["PERK_CLI_VERSION"] == perk.__version__`.
  - **Pin-lockstep beyond `__version__`** (`tests/test_packaging.py::test_npm_pin_lockstep`): both
    perk-owned `@mgiles/perk` install pins must track the **file** SSOT (`_pyproject_version()`) — the wired
    pin (`settings._perk_npm_entry()`) and the npm-install pin (`extension_install._pinned_spec()`),
    with the install spec's name == `NPM_PACKAGE.removeprefix("npm:")`. Proves both pins track the
    version SSOT, not just each other.

## The git→npm extension-wiring flip — protocol → identity discriminator

When perk's own Pi extension moved from a `git:` package entry to an `npm:` entry (`@mgiles/perk`), the
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

## init/doctor/launch own the `@mgiles/perk` npm install — the git→npm mirror

The npm-install lifecycle **mirrors** the **retired** git-clone lifecycle (its pi `git:`-loading
substrate facts now live in `pi/extension-api.md`): a
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
  init sees `present`; idempotency then becomes "no `@mgiles/perk` line in the second-run changes."

Mechanical reusables that DO transfer from the git lifecycle:

- The lock lives in the install **root** (survives a `node_modules` wipe — same principle as the clone
  lock living in the clone's parent).
- `.pi/npm/` is already **wholesale-gitignored**, so no new gitignore entry is needed.
- The `(file_stem, func_name)` sanctioned-subprocess guard needs the new wrapper's entry.
- **`git checkout package-lock.json` before staging** when the only lockfile diff is `pi-ai` bin-path
  npm-normalization churn from `just ci` / setup (a recurring noise diff — see
  `toolchain/worktree-node-modules.md`).
- **`.pi/npm` is a gitignored, pi-managed lazy-install root that drifts through ordinary pi
  installs**, breaking `npm ci --prefix .pi/npm` — the standard repair is
  `npm install --prefix .pi/npm`, then re-run. Environment-class, never attempt-consuming
  (#2006).

## Cross-references

- `docs/learned/workflow/init-external-cli.md` — the skills-manifest `main` ref that survives
  beside the version-pinned install pins
- `docs/learned/workflow/init-doctor.md` — the fail-level-baseline-shift + `verify=True`
  `report.healthy` census rules a new fail-level check triggers
- `docs/learned/workflow/borrowed-packages.md` — the append-only borrowed npm entries the identity
  discriminator must spare
- `docs/learned/workflow/prompt-templates.md` — the zero-runtime-dep invariant (relevant when a node
  adds a runtime dep)
- `docs/learned/pi/extension-api.md` — the `session_start` handler the version-drift signal rides;
  also the pi `git:`-package loading substrate (the internals the retired git-clone lifecycle sat on)
- `src/perk/run/launch/__init__.py`, `extension/index.ts` — the `PERK_CLI_VERSION` inject + the
  `session_start` drift comparison
- `docs/learned/toolchain/worktree-node-modules.md` — the `package-lock.json` `pi-ai` bin-path churn
- `docs/learned/toolchain/uv-workspace-src-layout.md` — the uv-workspace root-package `src`-layout
  mechanics + the `uv sync --all-packages` member-pruning trap (the `perk-dev` member's home layout)
- `pyproject.toml`, `package.json`, `.github/workflows/release.yml` — the SSOT version + the dual-plane
  workflow
