# Phase 0 · Turn 1 — Monorepo skeleton + the `perk init` spine begins

Detailed execution plan for **T1** of [phase-0-plan.md](./phase-0-plan.md). T1 is the one turn
authored entirely **by hand** (no perk loop, no borrowed plan mode yet); it lands the substrate
that makes T2–T7 possible and *may* unlock the early plan-mode crossover.

> **Scope discipline.** T1 builds the *skeleton*, the *bundling mechanism*, and a *minimal*
> `perk init`. It does **not** build state helpers, `run_id`, the registry contents, subcommand
> generation, worktrees, or `doctor` — those are T2–T6. Resist scope creep; the gate below is the
> whole job.

---

## 1. Objective & the two gates

**Goal.** Stand up the two-artifact monorepo, prove `shared/` bundling, and land a minimal,
idempotent `perk init` that owns the Pi wiring — so *all* Pi-extension wiring is owned by `init`
from the first turn (the init-spine principle).

**Hard gate (must pass to land T1).** On a fresh clone:
1. `uv`/`pip` install → `perk --version` prints the lockstep version.
2. `perk init` writes `.pi/settings.json` (loading perk's own **no-op** extension), creates the
   base `.pi/workflow/` dir, manages `.gitignore`, and writes `AGENTS.md` conventions.
3. Launching `pi` **loads perk's no-op extension** (provably — see §9).
4. **Re-running `perk init` is a no-op** (no diff, no error).
5. A built **wheel** and a built **npm tarball** each contain their own bundled `shared/` copy.

**Crossover goal (may iterate; NOT a blocker).** `perk init` also lists the borrowed default set
in `.pi/settings.json` so that, on next `pi` launch, plan mode + the todo overlay come up. If the
package install/load needs iteration, the hard gate still lands and T2–T7 fall back to hand-
authoring (the dependency spine never assumes the crossover).

---

## 2. Grounding facts (verified against Pi docs)

These are load-bearing and were confirmed in `packages.md` / `extensions.md`, not assumed:

- **Project settings file is `.pi/settings.json`.** `pi install -l <source>` writes there; user
  installs go to `~/.pi/agent/settings.json`. **Pi auto-installs missing packages listed in
  project settings on startup** (packages.md → *Install and Manage*). → *We can wire packages
  declaratively and let `pi` install them; `init` need not shell `pi install` eagerly.*
- **Package sources** in `packages`/`pi install`: `npm:@scope/pkg@ver`, `git:…`, and **local
  paths** (`./rel` or `/abs`). *Local relative paths are resolved against the settings file they
  appear in*, and a directory is loaded "using package rules" (packages.md → *Local Paths*).
- **A package declares resources** via the `pi` key in `package.json`
  (`{ "pi": { "extensions": ["./extension/index.ts"], … } }`), globs + `!exclusions`; or by
  convention dirs (`extensions/`, `skills/`, `prompts/`, `themes/`) if no manifest (packages.md).
- **Peer deps (do NOT bundle):** `@earendil-works/pi-ai`, `@earendil-works/pi-agent-core`,
  `@earendil-works/pi-coding-agent`, `@earendil-works/pi-tui`, `typebox` — list with `"*"`
  (packages.md → *Dependencies*; extensions.md → *Available Imports*).
- **Extensions load via [jiti](https://github.com/unjs/jiti) — TypeScript runs without a build
  step** (extensions.md → *Writing an Extension*). → *No `tsc` is needed to run the extension in
  dev or tests; a "build" is only `npm pack` for publishing.*
- **Project extension auto-discovery** also works from `.pi/extensions/*.ts` or
  `.pi/extensions/*/index.ts`, and `settings.json` accepts an `extensions: [<path>]` array
  (extensions.md → *Extension Locations*).
- **`npmCommand` setting** pins npm to a wrapper (e.g. `["mise","exec","node@20","--","npm"]`) —
  relevant because this toolchain runs node under **mise** (packages.md → *npm*).
- **Distributed installs use `npm install --omit=dev`** → runtime deps go in `dependencies`, not
  `devDependencies` (extensions.md → *Available Imports*).
- **`ctx.hasUI` is `false` in print/JSON mode**, `true` interactive/RPC (extensions.md →
  *ExtensionContext*). This is the basis of the headless-fail-safe convention.

---

## 3. Correction to the T1 "dual-path manifest" deliverable

phase-0-plan.md T1 lists a **"dev-vs-installed resource manifest (agent-stuff §2)"** as the
highest-risk unknown, framed as agent-stuff's *list-every-resource-path-twice* trick. Having
read the mechanics, that framing is **partly mis-targeted** and should be corrected:

- agent-stuff lists paths twice because its **distribution packages re-list resources that live
  in a *separate* bundled package** (`mitsupi`). That is the `dependencies` +
  `bundledDependencies` + `node_modules/<pkg>/…` case in packages.md → *Dependencies*.
- **perk in Phase 0 does not hit that case.** perk's `shared/` is *data* (YAML/JSON the TS and
  Python code read via `fs`/`importlib`), **not** a Pi resource (`extensions/skills/prompts/
  themes`), so it never appears in the `pi` manifest. And the borrowed packages are **independent
  `npm:` entries** in settings, not bundled into perk's package. So there is **no "list twice."**

**The genuine dev-vs-installed work is two narrower things:**

1. **Self-vs-consumer extension wiring** (the real "dual path"). In perk's *own* repo, `init`
   wires perk's extension as a **local-path package** so edits are live and `/reload`-able; in a
   *consumer* repo, `init` wires it as `npm:@perk/pi@<ver>`. Same self-vs-consumer split `doctor`
   already has.
2. **`shared/` resolution that works editable-dev *and* installed, per plane.** Each plane needs
   one helper — "where is my bundled `shared/`?" — that resolves the installed location and falls
   back to the repo sibling in editable/dev. This is the actual fiddly bit (Python editable
   installs + package-data; TS relative path inside the tarball).

I recommend we **update phase-0-plan.md's T1 bullet** to this corrected framing once T1's spike
(§6) confirms it. (Flagging rather than silently editing.)

---

## 4. Target repo layout (end of T1)

Single-root monorepo per `Q12` (both manifests at the root; `shared/` a root subdir):

```
perk/
├── pyproject.toml            # Python "perk" CLI (hatchling); entry point `perk`
├── package.json              # npm pi package "@perk/pi"; pi manifest → extension/index.ts
├── perk/                     # Python package (importable)
│   ├── __init__.py           # __version__
│   ├── __main__.py           # `python -m perk`
│   ├── cli.py                # arg parsing; `perk --version`, `perk init`
│   ├── init.py               # minimal idempotent init (settings.json + dirs + gitignore + AGENTS)
│   └── _resources.py         # shared/ resolver (installed → repo-sibling fallback)
├── extension/                # TS Pi extension
│   ├── index.ts              # no-op: session_start notify + /perk-selfcheck command
│   └── resources.ts          # shared/ resolver (tarball-relative → repo-sibling fallback)
├── shared/                   # cross-plane contracts (DATA, not Pi resources)
│   └── .gitkeep              # contracts authored in T2; placeholder now
├── docs/                     # (existing planning docs)
├── tests/
│   ├── test_init_idempotent.py
│   └── test_resources.py
├── AGENTS.md                 # compressed index + conventions (written/owned by init)
├── .gitignore
└── .pi/
    └── settings.json         # written by `perk init` (committed)
```

Notes:
- **`@perk/pi`** `files: ["extension/", "shared/", "README.md"]` → the tarball preserves the
  `extension/ … ../shared` relative layout, so the extension reads `../shared` identically in dev
  and installed. **No manifest gymnastics.**
- **Python wheel** force-includes `shared/` → `perk/_shared/` (hatchling `force-include`), so it
  ships as package data; `_resources.py` reads `importlib.resources.files("perk")/"_shared"` when
  installed, falling back to the repo `../shared` in editable dev.
- `shared/` is intentionally near-empty in T1 (contracts land T2). T1 only proves it **bundles
  and resolves**.

---

## 5. Proposed concrete choices (confirm before building)

| Choice | Proposal | Why / flag |
|---|---|---|
| npm package name | `@perk/pi` | short, scoped; consumers `pi install -l npm:@perk/pi`. **Confirm.** |
| PyPI dist / CLI name | `perk` | matches the command. **Confirm availability.** |
| Version (lockstep) | `0.0.1` | single source of truth; both manifests read it (see §8). |
| Python build backend | **hatchling** | clean `force-include` for `shared/`; good editable support. |
| Python floor | **3.11+** | `tomllib` (used from T4); set the floor now. |
| Dev extension wiring | local-path **package** entry at repo root (`..` from `.pi/`) | keeps the `pi` manifest + `shared/` shipping shape identical to installed. **Spike-validate** vs the `extensions:[path]` array. |
| Selfcheck mechanism | `/perk-selfcheck` command + `session_start` sentinel under a flag | gives both an interactive and a scriptable load proof (§9). |

---

## 6. Work breakdown (ordered; T1.0 de-risks before real work)

### T1.0 — De-risking spike *(throwaway; do this first)*
Validate the single biggest unknown **before** committing to structure: can a minimal local pi
package be wired via `.pi/settings.json` and provably loaded, alongside an `npm:` borrowed
package, under this mise toolchain?

- Scratch dir: a one-file `index.ts` (`session_start` → `ctx.ui.notify`), a `package.json` with
  the `pi` manifest + peer deps, and a `.pi/settings.json` listing the local path **and** one
  borrowed `npm:` package.
- Launch `pi`; confirm (a) the local extension's notify fires, (b) the borrowed package
  auto-installs and loads, (c) whether `npmCommand` must be set for mise.
- **Record findings** (esp. the exact dev wiring that loads + hot-reloads, and the mise/npm
  story). These decide §5's "Dev extension wiring" row and may amend §3. *Throw the spike away.*

> If the spike shows install/load is harder than expected, **descope the crossover** (borrowed
> packages) to a follow-up and land T1 on the hard gate alone. The plan already permits this.

### T1.a — Monorepo skeleton
`pyproject.toml` (hatchling, entry point `perk = "perk.cli:main"`, `force-include shared→perk/_shared`),
`package.json` (`@perk/pi`, `pi` manifest, peerDeps `"*"`, keywords `pi-package`/`pi-extension`,
`files`), `perk/__init__.py` (`__version__`), `shared/.gitkeep`, `README.md`.
*Accept:* `pip install -e .` → `perk --version` prints; `npm pack --dry-run` lists `extension/` +
`shared/`.

### T1.b — The no-op extension + TS `shared/` resolver
`extension/index.ts`: on `session_start`, `ctx.hasUI && ctx.ui.notify("perk <ver> loaded")`;
register `/perk-selfcheck` (notify version); under a registered `--perk-selfcheck` flag, write a
sentinel (see §9). `extension/resources.ts`: resolve `shared/` (tarball `../shared` →
repo-sibling fallback) and read a probe file. **Establish the headless convention**: guard every
UI call with `ctx.hasUI`.
*Accept:* `pi -e ./extension/index.ts` loads; selfcheck works; resolver finds `shared/`.

### T1.c — `perk` CLI entry + Python `shared/` resolver
`perk/cli.py` (argparse: `--version`, `init`), `perk/_resources.py` (installed
`importlib.resources` → editable repo-sibling fallback).
*Accept:* `perk --version`; `perk` resolves `shared/` in editable install.

### T1.d — Minimal `perk init` (the spine begins)
See §7 for the exact spec. Self-vs-consumer detection; idempotent merge of `.pi/settings.json`;
create `.pi/workflow/`; manage `.gitignore`; write/refresh `AGENTS.md`.
*Accept:* §9 hard-gate checks 2 & 4 (writes correctly; re-run is a no-op).

### T1.e — Bundling/publish proof
Verify both artifacts physically carry `shared/`: `python -m build` → inspect the wheel;
`npm pack` → inspect the tarball.
*Accept:* hard-gate check 5.

### T1.f — Verification script + thin tests
A `scripts/verify-t1.sh` (or a Makefile target) that runs the full hard gate end-to-end on a
fresh checkout, plus `tests/test_init_idempotent.py` (init → re-init = no diff; preserves a
user-added settings key) and `tests/test_resources.py` (resolver finds `shared/`).
*Accept:* the whole hard gate is one command; thin tests pass.

---

## 7. The minimal `perk init` spec

`init` is **declarative and convergent** — it edits files to a desired state and is safe to
re-run. It does **not** eagerly shell `pi install` (Pi auto-installs project packages on launch);
it *wires* settings and lets `pi` install. Steps:

1. **Detect self vs consumer.** Self = the repo is perk itself (e.g. a `[tool.perk] self = true`
   marker or detecting `extension/index.ts` + `pyproject` name `perk`). Consumer = anything else.
2. **Resolve/merge `.pi/settings.json`** (create if absent; parse if present; **preserve unknown
   keys and user entries**). Ensure the `packages` array contains, by identity (dedup):
   - **self:** a local-path entry for perk's own package (repo root, resolved against `.pi/`).
   - **consumer:** `npm:@perk/pi@<version>`.
   - the **borrowed default set** (crossover goal): `npm:@tombell/pi-plan`,
     `npm:@juicesharp/rpiv-todo`, `npm:@tombell/pi-diff`, plus a status bar
     (`npm:@tombell/pi-status`). *(Status-bar choice: confirm in T1.0.)*
   - if mise requires it, set `npmCommand` (decided by the spike).
   Write back with **stable key ordering + formatting** so re-runs diff cleanly.
3. **Create base state dir** `.pi/workflow/` (a `.gitkeep`); full subdir layout grows in T2/T3
   per the init-spine principle.
4. **Manage `.gitignore`** — ensure ignored: `.pi/npm/`, `.pi/git/` (Pi's project install
   caches). Do **not** ignore `.pi/settings.json` (committed). Idempotent block markers
   (`# >>> perk >>>` … `# <<< perk <<<`) so re-runs don't duplicate lines.
5. **Write/refresh `AGENTS.md`** (see §8) — managed region only, preserving any human additions
   outside it.
6. **Human-readable summary** of what changed (or "already converged"). *(No `--json` yet —
   that's T5; T1 keeps a single human surface.)*

**Idempotency mechanics:** every write is a *read → merge-to-desired → write-iff-changed*; a
second run reports "already converged" and touches nothing. This is the invariant the rest of
the init spine will preserve.

**Out of scope for T1's init:** env verification, GitHub checks, capability tracking,
`--upgrade/--force/--no-interactive`, post-init handoff, `--json` — all T5. `perk.toml` scaffold
— T4.

---

## 8. `.pi/settings.json` shapes & version single-source

**Self (perk repo):**
```json
{
  "packages": [
    "..",
    "npm:@tombell/pi-plan",
    "npm:@juicesharp/rpiv-todo",
    "npm:@tombell/pi-diff",
    "npm:@tombell/pi-status"
  ]
}
```
(`".."` = repo root relative to `.pi/`; **spike-validate** this exact form vs an absolute path or
the `extensions:[…]` array.)

**Consumer:**
```json
{
  "packages": [
    "npm:@perk/pi@0.0.1",
    "npm:@tombell/pi-plan",
    "npm:@juicesharp/rpiv-todo",
    "npm:@tombell/pi-diff",
    "npm:@tombell/pi-status"
  ]
}
```

**Lockstep version, one source.** Pick the **Python `perk.__version__`** (or a root `VERSION`
file) as the single source; `package.json` `version` is kept in sync by a tiny check in
`verify-t1.sh` (fail if they differ). Full release tooling is later; T1 only needs the invariant
"they match."

---

## 9. Acceptance gate — concrete, runnable checks

Mapping each hard-gate item to a command (assembled into `scripts/verify-t1.sh`):

1. **CLI installs & versions** — `pip install -e . && perk --version` prints `0.0.1`.
2. **init writes correctly** — in a fresh temp clone: `perk init`; assert `.pi/settings.json`
   contains perk's package entry + the borrowed set; `.pi/workflow/` exists; `.gitignore` has the
   perk block; `AGENTS.md` has the managed region.
3. **Extension provably loads** — the scriptable proof: launch
   `pi -p --perk-selfcheck "noop"` (print mode; `ctx.hasUI === false`); the extension's
   flag-guarded `session_start` writes a sentinel (e.g. `.pi/workflow/.perk-loaded` containing the
   version); the script asserts the sentinel exists and matches. *(Interactive cross-check:
   `/perk-selfcheck` shows the version.)* — **finalize the exact mechanism in T1.0.**
4. **init is idempotent** — run `perk init` twice; assert the second run produces **no file diff**
   and reports "already converged" (also covered by `test_init_idempotent.py`).
5. **Both artifacts bundle `shared/`** — `python -m build` then `unzip -l dist/*.whl | grep
   _shared/`; `npm pack` then `tar tzf perk-pi-*.tgz | grep '^package/shared/'`.

**Crossover smoke (non-gating):** after check 2, launch interactive `pi`; `/plan` enters plan
mode and the todo overlay appears. Record pass/fail; do **not** block T1 on it.

---

## 10. Risks & mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Dev extension-load wiring (`..` local-path vs `extensions:[]`) doesn't load or doesn't `/reload` | **med-high** | **T1.0 spike** resolves the exact form before structure is built |
| `pi install` of borrowed npm packages fails under mise | med | spike checks `npmCommand`; set it in settings if needed; else descope crossover |
| Python editable install can't resolve `force-include`d `shared/` | med | `_resources.py` falls back to repo-sibling; `test_resources.py` covers both modes |
| Repo-root-as-package double-loads (`.pi/extensions/` also present) | low | keep no extension under `.pi/extensions/`; only the package manifest path |
| Scriptable "extension loaded" proof is awkward in print mode | med | sentinel-on-`session_start`-under-flag (§9); finalize in spike; interactive fallback |
| `npm pack` at single-root accidentally includes Python/dev files | low | strict `files` whitelist (`extension/`, `shared/`, `README.md`) |
| Version drift between `pyproject` and `package.json` | low | `verify-t1.sh` asserts equality |

---

## 11. Explicitly out of scope for T1 (pointers)

- State-tiering helpers, `perk:workflow-state`, `run_id`/`PERK_RUN_ID`, `.pi/workflow/` subdir
  layout — **T2 (spec) / T3 (impl)**.
- `registry.yaml` contents, state-key vocabulary, gateway contract — **T2**.
- TOML config loader, registry→subcommand generation, worktrees, process-launch — **T4**.
- init env/GitHub verification, capability tracking, flags, post-init handoff, `--json` — **T5**.
- `perk doctor` — **T6**.
- Internalizing any borrowed package; the gating primitive — **Phase 2**.

## 12. Open questions to settle during T1

1. **Exact dev extension wiring** — output of the T1.0 spike (local-path package vs `extensions:[]`;
   `".."` vs absolute; `/reload` behavior).
2. **Names** — `@perk/pi` and PyPI `perk` availability.
3. **Status-bar package** — `@tombell/pi-status` vs `pi-powerline-footer` (pick one default).
4. **`npmCommand`** — does this toolchain need it pinned in project settings?
5. **Self-detection mechanism** — marker in `pyproject` `[tool.perk]` vs structural detection.
6. **Should phase-0-plan.md's T1 "dual-path manifest" bullet be rewritten** to the §3 correction?
   (My recommendation: yes, after the spike confirms.)

## 13. Definition of done

The five hard-gate checks in §9 pass via `scripts/verify-t1.sh` on a fresh clone; the thin tests
pass; `perk init` is idempotent and owns all Pi wiring; both artifacts physically bundle
`shared/`. The crossover smoke is recorded (pass or deferred). T1 lands; T2 can begin — and, if
the crossover passed, T2 may be authored in borrowed plan mode.

---

## 14. T1 outcomes (recorded after implementation)

**Status: implemented; hard gate ALL PASS (stable ×3); crossover smoke GREEN.**

**Spike (T1.0) findings — all green:**
- `pi -e <ext>` loads an extension; **`session_start` fires in print mode with `hasUI=false`**,
  and an env-gated sentinel write is a reliable scriptable load proof.
- A **local-path package** entry `".."` in `.pi/settings.json` loads perk's own package via its
  `pi` manifest (dev wiring confirmed).
- `shared/` resolves via `../shared` from the extension (TS) and via force-include/sibling
  fallback (Python) — in both editable-dev and built artifacts.
- **Borrowed `npm:` packages auto-install under mise with no `npmCommand`** ("added … in 2s");
  all five borrowed names exist on npm (`@tombell/pi-plan` 0.0.3, `@juicesharp/rpiv-todo` 1.16.1,
  `@tombell/pi-diff` 0.0.3, `@tombell/pi-status` 0.0.5, `pi-powerline-footer` 0.5.6).

**Choices locked (§5):** `@perk/pi` + PyPI `perk`, version `0.0.1`, **hatchling**, Python `>=3.11`,
dev wiring = local-path `".."` package, status bar = `@tombell/pi-status`, self-detection =
`[tool.perk] self = true` in `pyproject.toml`, load proof = `PERK_SELFCHECK` env-gated sentinel.

**§3 correction confirmed.** No agent-stuff-style "list-twice" manifest is needed: `shared/` is
bundled *data* and borrowed packages are independent `npm:` entries. The real dev-vs-installed
work was **self-vs-consumer wiring** + a **per-plane `shared/` resolver**, both implemented.
phase-0-plan.md's T1 "dual-path manifest" bullet has been updated to match.

**Gotchas (for later turns' tooling):**
- macOS has **no `timeout`** — use a background-kill watchdog, and only for `pi` (which can
  hang); `uv build`/`npm pack` self-terminate and must not be watchdog-wrapped.
- `unzip -l … | grep -q` under `set -o pipefail` is **nondeterministic** (grep closes the pipe on
  match → unzip dies with SIGPIPE/141 → pipefail fails the check). Use Python `zipfile`/`tarfile`
  membership for artifact checks instead.
- Pre-existing env quirk: a stray `~/.pi/agent/settings.json.lock` file emits a benign warning on
  every `pi` launch; not ours, not blocking.

**Still open (registry/publish, not gating):** `@perk/pi` and PyPI `perk` name *availability* was
not claimed (nothing published in T1); npm publish + PyPI release tooling is a later concern.

**Verify:** `bash scripts/verify-t1.sh` (5/5 PASS) and `pytest` (4 passed).
