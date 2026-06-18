---
title: The consumer extension-clone lifecycle — how pi loads perk, and perk's ownership of clone deps/freshness/materialization
read_when: A consumer repo loads none of perk's tools or the extension fails at launch (Cannot find module / months-old code), you are touching extension-clone materialization (the launch warm-clone, init/doctor freshness reconcile), the vendored miniYaml reader, or you need pi's git:-package loading internals.
---

# The consumer extension-clone lifecycle

perk ships to consumer repos as a Pi `git:`-package **extension**. pi materializes that package as a
git **clone** on the consumer's disk and loads the TS extension from it. Three distinct gaps in how
pi manages that clone could leave a consumer loading *no* perk tools — or *months-old* perk code —
while `perk doctor` reported green. This doc captures the root-cause substrate, the four-PR arc that
made perk the **owner** of its own clone's deps/freshness/materialization, and the durable gotchas
that generalize.

## How pi loads the perk extension (the root-cause substrate)

pi loads a `git:`-package extension from a clone at `.pi/git/<host>/<path>/` via jiti, resolving the
extension's imports through a **fixed host-alias set**
(`@earendil-works/pi-coding-agent`/`-ai`/`-tui`, `@mariozechner/*`, `typebox`/`@sinclair/typebox`)
**plus** native `node_modules` walking. The relevant internals live in
`@earendil-works/pi-coding-agent/dist/core/package-manager.js`, where three distinct gaps forced
perk to work around pi:

- **(a) No self-heal install.** `installGit`/`ensureGitRef` run `npm install --omit=dev` **only**
  on a fresh clone OR when `localHead != targetHead`. A clone already present at the pinned ref
  returns early and never installs (`pi update` shares that early return). So a clone can carry no /
  partial `node_modules` and pi cannot self-heal → `Cannot find module 'yaml'` at load.
- **(b) Unlocked lazy clone race.** `resolvePackageSources` clones a missing `git:` package lazily
  and **UNLOCKED**. Two near-simultaneous launches against an absent clone race: the second sees the
  first's half-created dir, takes the `else` (collect) branch over an incomplete checkout, and the
  extension **silently fails to load** — none of perk's tools appear, perk is absent from
  `[Extensions]`, and a throwing extension lands only in pi's `errors[]`.
- **(c) Frozen present clone.** A **present project-scoped** clone is left **frozen** — pi's branch
  for it only calls `collectPackageResources` with no `git fetch`/`reset`, so a months-old clone
  keeps loading months-old code (wrong import paths; a since-retired import → a hard load failure)
  while `perk doctor` reported green.

## Three concerns the clone bundles — keep them separate

Dependency **installation**, commit **freshness**, and materialization **presence** are distinct
concerns. A correct "nothing to install" fix can silently hide an uncovered "nothing keeps it
current" — exactly the #639→#642 gap. **When retiring a check, separate the concerns it bundled**
before deciding the surface is covered.

## The narrative arc (four PRs)

Read as one story — each PR reframed the problem the prior one left open:

- **#637 (band-aid): ref-aware package convergence.** `_merge_static_packages` was append-only and
  ref-blind (dedup by git identity, which strips `@ref`); it now reconciles perk's **own** `git:`
  ref forward, rewriting a stale string-form `@v0.0.1` → `@main` **in place** (list position
  preserved) and collapsing duplicate perk entries to one canonical entry. This rides the existing
  `settings-wiring` ManagedConvergence (ref drift = a `settings-wiring` FAIL that `--fix` repairs)
  — **no new doctor wiring for the ref**. Plus a `dependencies`-only `extension-deps` doctor check
  (peers are pi-bundled → checking them would false-positive). **Why a band-aid:** init never
  installs and `doctor --fix` is a separate step — it never touched the `init → use` crash path.
- **#639 (the real deps fix): eliminate the lone non-host import.** The only non-host runtime import
  was `yaml`; it was replaced by a **bounded** vendored YAML-subset reader
  (`extension/substrate/miniYaml.ts`). Once the extension imports only host-aliased packages + Node
  builtins, pi's install behavior is irrelevant in **every** case (fresh/stale/partial/offline).
  The now-dead `extension-deps` check was retired; root `package.json` ends with **zero runtime
  `dependencies`**.
- **#642 (freshness): perk owns clone commit-freshness.** Detection is a network op
  (`git ls-remote refs/heads/main` vs the clone `HEAD`) → **verify-gated in BOTH planes** (the
  doctor check + the init reconcile run only under `if verify:`; a regression guard asserts the
  check's absence without verify). **Three-tier degrade, never a silent pass:** `stale → fail`
  (+remediation `perk doctor --fix`), `unverifiable → warn` (carries the offline reason),
  `fresh → ok`, `absent → info`, `self → info`. Repair = blow-away-and-reclone (filesystem-only /
  no perk-side network, relying on pi's verified-absent → `git clone` path next launch).
- **#655 (materialization + race fix): perk owns clone materialization.** New
  `git.clone()`/`git.reset_hard()` primitives; `launch_stage` **warms the clone before
  `os.execvpe`** under an `fcntl.flock` lock — serializing perk's own launches and removing the
  missing-clone window (gap (b)). The blow-away reclone was **retired** in favor of an in-place
  freshen.

## The ownership pattern (reusable recipe)

init-converges-forward / doctor-reports-and-repairs / launch-warms. A single
`extension_clone_status(root, *, self_repo) -> (status, detail)` SSOT (in `init.py`, with a
`Literal` `ExtensionCloneStatus`) feeds **both** the doctor check and the init reconcile, so the
classification lives in one place. `consumer_git_clone_root(repo_root)` is the SSOT clone-path
helper, derived from the **ref-less** `GIT_PACKAGE` constant — **never hardcode `.pi/git/...`
segments**, and never desync the run-worker entry resolver from the doctor check. The comparison ref
is always `@main` (perk pins its own package at `@main`; a hand-pinned other ref is out of scope —
init rewrites it to `@main`).

Note the enabling asymmetry: `perk doctor`/`perk init` are **Python** CLIs that **never load the TS
extension**. That is exactly what makes Python-plane ownership of a TS-extension-loading concern
viable — they run fine against a clone too stale to even load, and repair it for the *next* launch.

## Gotchas that generalize

- **Idempotency forces a `str | None` reconcile signature.** A verify-gated init reconcile that
  "always appends a status line" breaks `test_cli_idempotent_second_run` (a converged re-run must
  yield `changes == []`). No-ops (`self`/`fresh`/offline `unverifiable`) must return `None` (stay
  silent); only real changes (absent→cloned, stale→freshened) or a swallowed-`GitError` message
  return a `str`; both call sites guard `if message is not None`. **Check the `changes == []`
  idempotency tests before making an init/doctor reconcile always-append.**
- **Warming-on-absent network-couples the whole test surface.** A reconcile that starts doing
  network work on a previously-inert status (`absent`) silently turns every `verify=True` /
  `launch_stage` test into a real `git clone github.com/mattgiles/perk`. **Census ALL such tests
  and stub the network primitive in the shared `stub_env` fixture** — and make the clone stub
  `mkdir(parents=True, exist_ok=True)` so a *second* verified init sees the clone present →
  `extension_clone_status` returns `unverifiable` (non-git dir → no network) → no-op → idempotent.
  `tests/test_launch.py` needs an **autouse** no-op stub of `ensure_extension_clone_present`.
- **The lock lives in the clone's PARENT, gitignored.** `.pi/git/.perk-extension-clone.lock` (not
  inside the clone dir) so a clone-dir removal never drops the lock; `.pi/git/` is already
  gitignored. A double-checked `is_dir()` under the lock gives exactly-once cloning (race test: two
  threads + `threading.Barrier` + a slow clone stub asserting `call_count == 1`). `fcntl` is
  POSIX-only → guarded import with a no-op `@contextlib.contextmanager` lock fallback.
- **The `extension-deps` retirement ripple.** Removing the dead doctor check required dropping the
  now-unused `import subprocess` from `doctor.py`, removing its `_SANCTIONED_SUBPROCESS_WRAPPERS`
  entry, and fixing **stale doc-comments** in `init.py`/`run_worker.py`. The ref-reconcile test was
  **interleaved** between the extension-deps tests (two surgical edits around it, not one block
  delete).
- **The sanctioned-subprocess-wrapper guard fires on every new `subprocess.run` site.**
  `tests/test_tooling.py::test_subprocess_run_only_in_sanctioned_wrappers_with_check_and_timeout`
  AST-scans `perk/**/*.py` and fails CI on any direct `subprocess.run` outside the
  `(module_stem, func_name)` set or missing explicit `check=`/`timeout=`. The npm-install repair and
  each new clone primitive tripped it (see `docs/learned/toolchain/ruff.md` / dignified-python §1.9).
- **ty gotchas in the infra.** `fcntl = None` after `import fcntl` trips `invalid-assignment` → use
  `from types import ModuleType` + `fcntl: ModuleType | None` + `import fcntl as _fcntl;
  fcntl = _fcntl`, placed **below all imports** (mid-imports triggers `E402`). A direct module-attr
  assignment (`git_mod.clone = stub`) trips ty's implicit-function-shadowing → use
  `monkeypatch.setattr(init_mod.git, "clone", stub)` (string-keyed, ty-invisible, thread-safe). An
  event-recorder list holding tuples must be typed `list[object]` (ty checks `tests/` too).

## The vendored-parser pattern (when to drop an npm parser)

When a shared SSOT file (`shared/*.yaml`) is parsed on both planes, you can drop the TS npm parser
by vendoring a **bounded** reader scoped to perk's **own** files — NOT a general parser. **Census
the actual feature surface first** (block maps/seqs incl. `- id: x` map-as-seq-item, flow
`{}`/`[]`, the scalar types perk's files use, comment handling); everything outside that surface
**throws loudly** so a future unsupported edit fails CI rather than silently mis-parsing. Fidelity
is pinned by a `node:test` deep-equal vs the reference lib (which survives **dev-only**, powering
exactly that test). Self-containment is verified by grepping non-test `extension/**/*.ts` for bare
imports outside the alias set (`.test.ts` is excluded from the published tarball, so a dev-only
`import … from "yaml"` in a test is fine).

**Residual:** the reader is pinned only against the current files; a future `shared/*.yaml` edit
using an unsupported construct fails CI (intended) — the author must extend the **reader**, not just
the YAML. The user opted OUT of an import-allowlist guard test, so nothing structurally prevents
re-introducing a bare npm import except review + the indirect fidelity test.

## Cross-references

- `perk/convergence/init.py` — `extension_clone_status`, `materialize_extension_clone`,
  `ensure_extension_clone_present`, `consumer_git_clone_root`, `_merge_static_packages`
- `perk/substrate/git.py` — `clone`, `reset_hard`, `head_sha`, `ls_remote_sha`
- `perk/run/launch.py` — the launch warm-clone
- `extension/substrate/miniYaml.ts` — the vendored bounded YAML reader
- `@earendil-works/pi-coding-agent/dist/core/package-manager.js` — the root-cause pi internals
- `docs/learned/workflow/init-doctor.md` — managed-convergence + verify-gated reconcile SSOT
- `docs/learned/workflow/cold-door-launch.md` — the launch seam + the `materialize_skills` sibling mirror
- `docs/learned/workflow/shared-contracts.md` — the TS reader, now `miniYaml`
