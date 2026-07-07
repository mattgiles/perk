---
title: The cold-door pi-launch seam and composing --json surfaces
read_when: You are touching launch_stage's argv construction, injecting child env vars at the launch seam (the merge-order setdefault layering, incl. the Linear-key env-seed before chdir), running a repo-configured `[worktree] setup` hook before exec (`run_worktree_setup`, the single canonical path; remote `position_worktree` skips it), pi project-trust on ephemeral worktrees, mirroring `.agents/skills/` into a worktree at launch positioning, wrapping a last-wins CLI, composing/testing a Python surface that nests a command emitting machine_output, asserting CliRunner stdout/stderr byte-identity on Click ≥8.2, applying the leveled progress-log discipline (`io_step` + `log_done`/`log_warn`, all stderr — narrate-where-the-I/O-happens, never-dangle made structural by `io_step`, the guarded TTY in-place rewrite + its append fallbacks, post-check a conditionally-narrated step), or refactoring launch/run modules behind byte-exact test pins.
---

# The cold-door pi-launch seam

A perk *local* stage launch ends by `execvpe`-ing into `pi`: the perk CLI process **becomes** pi. This
seam (`perk/run/launch/`) carries a handful of non-obvious mechanics about argv construction, pi's
project-trust prompt on throwaway worktrees, and what happens when a `--json` surface composes a
launcher that emits its own JSON.

## Build `argv` once, branch only on execute-vs-preview

`launch_stage` builds the full `argv` vector **once, before** the `dry_run` branch, so the dry-run JSON
preview and the real `os.execvpe` stay in lockstep — the `--approve` injection shows up faithfully in
`--dry-run --json`. **Generalize:** build the launch vector once and branch only on
execute-vs-preview, never construct two divergent vectors.

## pi project-trust vs perk's ephemeral worktrees

pi prompts for project trust on a cwd that has trust inputs (`.pi/`, `AGENTS.md`/`CLAUDE.md`,
`.agents/skills` in the cwd or an ancestor) and no saved decision; trust is keyed per canonical cwd and
persisted in `~/.pi/agent/trust.json`. perk `chdir`s into a brand-new `plan-<id>` checkout for every
worktree stage, so pi re-prompted on **every** `implement`/`submit`/`address`/`land`/`learn` launch.

**Fix:** prepend `--approve` for worktree stages —
`trust_args = ["--approve"] if stage.worktree != "none" else []`.

### `--approve` works in *interactive* mode, not just `-p`/`--mode json`

The pi docs describe `--approve` only in non-interactive contexts, which is misleading. Verified
against the pi `dist/`: when the project-trust override is set, the resolve-prompt short-circuits and
trust resolves true regardless of app mode. **Anti-pattern flag:** when pi's docs and its `dist/`
source disagree, trust the dist source.

### `--approve` is run-scoped, not persisted

`--approve` does **not** write `~/.pi/agent/trust.json` — it is run-scoped, which is exactly right for
throwaway `plan-<id>` worktrees (no trust residue accumulates). Don't reach for a persistent trust
write for ephemeral paths.

## Last-wins arg injection

pi parses args last-wins, so perk injects its default **before** `*pi_args`; a user-passed
`--no-approve`/`-na` then naturally wins with zero extra perk code. **General CLI-wrapping pattern:**
when wrapping a last-wins CLI, inject your default *before* pass-through args to leave the user an
override.

## Env setdefault via merge order (the launch-seam env layering)

The cheapest override-respecting env injection at the launch seam is **merge order**:
`{**injected_defaults, **os.environ, **perk_stamps}` yields three clean precedence tiers (injected
defaults < operator env < perk-owned stamps) with **no conditional logic**. The precedent is
`_NPM_QUIET_ENV` in `launch_stage` (npm loglevel=error, fund/audit off). Slot new launch-seam env
vars into this layering rather than writing `env.setdefault()` loops.

- **Test hygiene:** pytest inherits the operator's real environment, so a test asserting an
  *injected default* must `monkeypatch.delenv` first — otherwise a developer's exported value
  causes a phantom failure. Pair it with a `setenv` override test proving the operator wins.
  `tests/test_launch.py`'s exec-capture fixture family has an env-capturing member
  (`_launch_and_capture_env`) — reuse it for any child-env claim.
- **The two spawn sites diverge on purpose:** `run_worker.spawn` (remote/CI) deliberately does
  NOT get the quiet vars — CI logs keep full npm output.
- **Fail-soft:** the quieting is advisory; if pi ever sanitizes the child env before spawning npm,
  the noise returns silently (no breakage, no detection).
- **#654 — Linear key seed.** `launch_stage` seeds `env["LINEAR_API_KEY"]` from
  `load_local_linear_api_key(repo_root)` (the **main checkout**), **only when env doesn't already
  provide it**, just before `os.execvpe` — built **before `os.chdir(worktree)`** so worktree
  consumers inherit it. This is the bridge that carries a gitignored `perk.local.toml` secret into a
  linked worktree session (see `docs/learned/workflow/linear-backend.md` for the consumer side).

## Running a repo-configured setup hook before exec (#652)

`run_worktree_setup` runs the `[worktree] setup` commands via `bash -lc` inside a **freshly
created** worktree before `exec pi`, **aborting the launch on any failure**. It is the **single
canonical setup-execution path** with two consumers (cold-door `launch_stage` + manual
`perk worktree create`'s `_create_impl`), mirroring `materialize_plan_body`/`materialize_skills`.

- **Scope boundary:** the remote runner's `position_worktree` deliberately does **not** run the hook
  (CI env setup belongs to the GHA composite action) — a recorded non-goal. This is
  Python-plane-only (the TS extension never creates worktrees).
- See `docs/learned/workflow/worktree-lifecycle.md` for the `created`-flag dry-run asymmetry that
  gates the dry-run preview of this hook.

## `stage.worktree != "none"` is the canonical worktree-stage predicate

It already gates `_materialize_plan_body` — reuse it rather than enumerating stage ids. `worktree:
none` stages (objective-author/save/plan, plan, save) run in `repo_root`; create/reuse stages run in a
fresh `plan-<id>` worktree.

## Worktree positioning must mirror `.agents/skills/` (#467)

A session launched in a **linked worktree** (`stage.worktree` create/reuse —
implement/submit/address/land/learn) sees **zero skills** unless the cold door mirrors them at
positioning time. Two compounding root causes:

1. `.agents/skills/` is **gitignored** (the `skills managed runtime artifacts` block), so
   `git worktree add` — which checks out only *tracked* files — never carries it. A fresh worktree's
   `.agents/` has only the tracked `manifest.yaml`/`manifest.d/`.
2. pi discovers `.agents/skills/` in cwd + ancestors **only up to the git repo root** (pi
   `docs/skills.md`), and a linked worktree **is its own git root** — so pi never ascends to the
   main repo's skills. The dangling skill-binding warnings (`bindingDelivery.ts` pointer fallback)
   are a *symptom* of this, not a separate bug.

**The fix shape:** `materialize_skills(repo_root, worktree)` in `perk/run/launch/materialize.py` mirrors
`materialize_plan_body`, wired into `launch_stage`'s `if stage.worktree != "none":` block **right
after `materialize_plan_body`** (after the `dry_run` early return, before `os.chdir`/`os.execvpe`).
It creates **per-skill symlinks** — one per entry of `repo_root/.agents/skills/*` — each pointing at
`entry.resolve()` (single-hop straight to the real cache dir, avoiding a symlink-to-symlink chain).
This delivers ALL skills (perk's own + borrowed).

**Rejected alternatives (settled with the user):**

- **A single top-level `skills/` dir symlink** — avoided so there's zero risk of pi declining to
  follow a symlinked discovery *root*; per-skill links keep each target a real directory.
- **`skills update --sync` in the worktree** — re-clones sources into the worktree's own
  `.agents/cache`; needs network, heavy.
- **`perk init` per launch** — heavy: GitHub checks, config convergence, network re-clone.

**Posture:** loud-but-non-fatal + idempotent (D4 resume). A missing/empty `repo_root/.agents/skills/`
(perk init never ran) warns via `user_output` and continues — the launch is **never** blocked
(doctor's fail-level `skills-delivery` check stays the hard gate for the main repo). Idempotency:
an already-correct symlink is left untouched, a **stale** symlink is repointed, and a **real
(non-symlink) entry already present is never clobbered** (skip on `link.exists()` after the
`is_symlink()` branch).

**Scope boundary — local cold-launch only.** `run_worker.position_worktree` (remote CI) positions
into `repo_root` itself (worktree == repo_root), so mirroring would be a self-referential no-op —
the CI setup action owns skills delivery there. **No TS change:** `bindingDelivery.ts` already reads
`.agents/skills` from `ctx.cwd` (the worktree) and resolves automatically once mirrored. (No
`.claude/skills` mirror — pi reads `.agents/skills`.) See `workflow/skill-bindings.md` for the
delivery side and `pi/extension-api.md` for the git-root skill-discovery boundary.

## The headless worker is NOT subject to this seam

`perk run-worker` spawns `node` against the worker entry and builds its session without pi-CLI arg
parsing or CLI trust resolution — so this is purely **local cold-door launch** mechanics. No
`shared/contracts.md` change accompanies the trust injection.

## A local stage launch never returns

It ends in `os.execvpe("pi", …)` — the CLI *becomes* pi, and nothing after that runs. A supervisor
**cannot** compose a *local* launch (it would never come back); landing therefore stays the
human/interactive path (see `objective-lifecycle.md`).

## Launch banner + worktree `.pi/npm` pre-staging (the exec-wall, applied two ways)

**The exec-wall reaffirmed.** `launch_stage` ends in `os.execvpe` — perk *becomes* pi, so all
intervention is **pre-exec**. pi's startup npm noise (`added N packages`) is pi's own output **after**
exec and cannot be filtered; the only lever is to make pi have nothing to install.

**Banner first.** `print_launch_banner(repo_root)` is **idempotent** — it latches a module-level
guard (`_LAUNCH_BANNER_EMITTED`) on first emit and no-ops on every later call, so the banner never
doubles. `launch_stage` emits it immediately after the cold-local invariant and **before**
`resolve_worktree` (before the git-worktree-add), gated `if not dry_run` — the sole emitter for
every non-narrating launch command. But several cold-door commands narrate load-bearing pre-launch
I/O *before* they call `launch_stage` (its result builds the seed, so it cannot move after the
launch). The narrating cold doors: the backend lookups/gathers of `plan resume`, `plan replan`,
`objective plan`, `objective replan`, `implement <plan>` (the PLAN-id branch), `plan from` (the
adoption arm; file mode is trivial local I/O and stays silent), and `objective author --from` (the
source arm; file mode silent); `skills create` narrates its pre-launch scaffold (a tracked-file
write + an offline-failable manifest reconverge); and the two learn factories (`perk learn docs` /
`perk learn code`, through the shared `run_factory`) narrate a `perk:learn` listing + (docs only) a
docs scan. All of them emit the banner **themselves**, right before their gather/lookup narration,
through one shared seam — `print_launch_banner_gated(repo_root, *, dry_run, remote)` — so the gate
(`not dry_run and remote is None`) lives in exactly one place instead of duplicated across the call
sites; `launch_stage`'s own call is then the no-op fallback. The learn factories add one further
gate: the banner is emitted only when `not gather_only`, because `--gather` is a warm sub-call
(feeds JSON to a warm door) that must stay banner-free — the gather narration itself is stderr-only
so it never corrupts the `--gather` stdout payload. The guard is reset by an autouse
`conftest.py` fixture so the process-global flag never leaks across tests. Both counts (skills =
dir count in `.agents/skills/`; extensions = package count in `.pi/settings.json`) are knowable up
front from `repo_root`, so the first render is accurate. The `remote is None` test (not
`resolve_target` ordering) is the exact "this is a local launch" gate — `--remote` absent → `None`
(local), `--remote`/`--remote=x` → `""`/`"x"` (both remote, no banner).

**Pre-stage `.pi/npm`.** `materialize_extensions` clone-copies the converged repo-root `.pi/npm/` into
the worktree so pi's `needsInstall` short-circuits (silent + faster). Copy (not symlink) preserves
per-worktree isolation. The two npm worlds never overlap: repo-root `node_modules` = perk's own dev
deps; `.pi/npm/` = pi's extension install root only.

**Reorder gotcha (safe-move discipline).** `ensure_extension_install_present` moved to **before** the
worktree block — safe because it is idempotent and depends on neither `env` nor `chdir`, but the
load-bearing *reason* it had to move: the repo-root install must be fully warmed before
`materialize_extensions` clones it.

**The partial-tree cache hazard (general lesson).** The clone uses a hardlink ladder (`copytree` with
`os.link`, falling back to a deep copy; `shutil.Error` subclasses `OSError`). A **presence-only**
idempotency resume guard combined with a writer that leaves a partial tree on a mid-copy failure would
**permanently cache corruption** (a half-copied package can satisfy a presence check yet fail to
load). Fix: `rmtree(dst, ignore_errors=True)` in the failure branch so a failed stage degrades to a
fresh in-session install. **General rule: a presence-only resume guard requires its writer to clean up
partial state on failure, or it caches corruption.**

**Posture + test gotchas.** Loud-but-non-fatal + idempotent (mirrors `materialize_skills`); TTY-gated
styling (dim only when stderr is a TTY and not `NO_COLOR`, since `user_output` writes to stderr) keeps
`--json`/piped/CI output escape-code-free. The end-to-end ordering test is **non-deterministic unless
`ensure_extension_install_present` is monkeypatched to a no-op** (unstubbed it can genuinely
network-install into repo-root `.pi/npm`, flipping the "not staged" warning path the assertion depends
on). The banner was pinned byte-for-byte against the approved wordmark via a `/tmp` capture before
committing (box-drawing glyphs are easy to transcribe wrong).

## Refactoring launch/run behind byte-exact pins

The node-4.3 dignified sweep of `perk/run/launch.py` / the run worker established three constraints:

- **`perk/state/cache.py` is a deliberate import-leaf** (it imports only `perk.substrate.output`), and
  `github.py` *lazily* imports `cache` for cycle avoidance — so any helper that calls *into*
  `github` cannot live in `cache.py` without creating a real import cycle. When a backlog says
  "move helper X to a shared home", check the candidate home's import posture first:
  **promote-in-place in the consumer-owning module** is the correct move when the shared home is
  a leaf. This is why the public plan-body materializer lives in the `perk/run/launch/` package, with the run worker
  as the documented second consumer, rather than relocated.
- **Frozen-dataclass state transitions**: keep the initial construction, then use
  `dataclasses.replace` for every subsequent status evolution — unchanged fields carry by
  construction and the persisted dicts stay byte-identical.
- **When refactoring behind exact-string test pins, the pins themselves are sufficient proof of
  behavior preservation** — zero test edits is the success signal; don't add helper-level tests.

## Composing a launcher that emits `machine_output` inside a `--json` surface

A composed cold-door launcher (e.g. the remote dispatch path `_drive_remote_target`) writes its own
dispatch JSON to stdout via `machine_output` and returns. A surface that wants a *single* unified
`--json` payload must wrap the call in `contextlib.redirect_stdout(io.StringIO())` and parse the needed
fields (e.g. `run_id`) out of the captured text — otherwise it emits **two** JSON objects and corrupts
the stream. (`user_output`→stderr is unaffected and can flow through.) **General trap:** any Python
surface nesting a command that calls `machine_output` must isolate that inner stdout.

## Leveled progress-log discipline

The cold-door launch path narrates its perceptible waits through the glyph-only leveled-log
vocabulary in `perk/substrate/output.py`, **all routed through `user_output` → stderr**
(python-cli-guidelines.md §7.5) so they never touch the stdout `--json` payload. Steps go through
**`io_step(attempt)`** — the context-manager seam yielding a handle whose `.done(msg)` /
`.warn(msg)` resolves the step; `log_done`/`log_warn` stay the raw surface for step-less
confirmations, and `log_step` is guard-confined to `output.py` (a source-scan guard in
`tests/test_output.py` fails the suite on any other call site). The rules:

- **Narrate the wait wherever the I/O happens — never gate narration on a flag the narrated I/O
  ignores.** The reasoning trap is conflating "keep stdout pristine" with "gate on `dry_run`" —
  the two are **independent** because the log is stderr-only. A backend lookup that *also* runs on
  the dry-run path (dry-run resolves its `--json` via the same read) must narrate
  **unconditionally**; the stderr line leaves the stdout `--json` payload byte-unchanged regardless,
  so the `dry_run` gate was never needed for byte-invariance. Gate a step only on whether the
  I/O actually happens, not on the output mode.

- **Every narrated step resolves — structurally.** `io_step` auto-resolves with `done(attempt)` on
  a clean exit, so an unresolved-branch bug (the PR #1070 class) is unrepresentable; an exception
  escaping the block deliberately leaves the dangling `›` as the pinpointing signal (the `fail`
  boundary's error text below IS the resolution). A second resolution call appends defensively
  (never raises).

- **The guarded TTY rewrite is best-effort cosmetics.** On an interactive stderr (`NO_COLOR`
  unset, step line narrower than the terminal) resolution rewrites the `›` line in place
  (cursor-up + erase-line); ANY interleaved `user_output`/`machine_output` bumps a shared revision
  counter and forces plain append, so the rewrite can never erase a foreign line (the
  `$ {command}` echoes in `run_worktree_setup` disable it on purpose — the subprocess streams
  live). CliRunner/CI/piped stderr is never a TTY → tests and CI logs keep the deterministic
  ANSI-free two-line shape. Tests exercising rewrite mode fake a TTY by patching `isatty` on
  **`type(sys.stderr)`** (the capsys CaptureIO *class*) — capsys swaps in a fresh instance between
  fixture setup and the test body, so an instance patch silently vanishes.

- **Post-check disambiguation for a conditionally-narrated step.** When a step is narrated behind an
  unlocked pre-check and the best-effort function returns `None` — an **ambiguous** outcome (a
  concurrent process won the cross-process lock → the op effectively succeeded, OR the op genuinely
  failed) — **re-check the observable state after the call** to decide between a done line and a warn
  line, rather than assuming `None` means failure.

Cross-link: adding new stderr progress lines re-triggers the combined-stream gotcha in
**"Testing `--json` surfaces"** below — parse `result.stdout` for the JSON payload and
`result.stderr` for the progress lines; comparing `result.output` (the combined stream) fails
spuriously once a step line lands ahead of the payload.

## Testing `--json` surfaces (Click 8.4.1 gotcha)

`CliRunner(mix_stderr=False)` raises `TypeError` on Click 8.4.1 (the kwarg was dropped), and
`result.output` still **mixes** stderr + stdout. So when a command writes human lines to stderr
*before* its `--json` payload, `json.loads(result.output)` fails. Parse the **last non-empty line** of
`result.output`. (Sibling tests that `json.loads(result.output)` directly get away with it only because
those commands emit nothing to stderr ahead of the JSON.)

Refinement (Click ≥8.2): `Result.output` is an independent **combined** stdout+stderr stream, but
`result.stdout` and `result.stderr` are still available separately. For "fail-soft never changes
the `--json` payload" byte-identity asserts, compare `result.stdout` against the baseline's and
assert the loud-but-non-fatal note via `result.stderr` — comparing `.output` fails spuriously
because the stderr note lands in the combined stream.

## Cross-references

- `perk/run/launch/` — `launch_stage` argv construction + `--approve` trust injection
- `docs/learned/workflow/seeded-door-pipeline.md` — the shared seeded-door pipeline whose tail composes `launch_stage`
- `perk/cli/commands/objective/run_cmd.py` — the supervisor that composes the remote dispatch launcher
- `docs/learned/workflow/objective-lifecycle.md` — the supervisor design that composes these mechanics
- `docs/learned/workflow/remote-runner.md` — the remote dispatch path that emits the nested `machine_output`
- `docs/learned/workflow/skill-bindings.md` — the skill-delivery subsystem the worktree mirror feeds
- `docs/learned/workflow/worktree-lifecycle.md` — the `[worktree] setup` hook + `created`-flag dry-run asymmetry
- `docs/learned/workflow/linear-backend.md` — the consumer side of the Linear-key env-seed
- `docs/learned/pi/extension-api.md` — pi's git-root skill-discovery boundary
