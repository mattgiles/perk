---
title: The cold-door pi-launch seam and composing --json surfaces
read_when: You are touching launch_stage's argv or prompt assembly (prompt_suffix), launch-seam env injection, the `[worktree] setup` hook, worktree positioning, or the `io_step` progress-log discipline.
cluster: doors-and-launch
---

# The cold-door pi-launch seam

A perk *local* stage launch ends in `os.execvpe(<absolute pi path>, …)`: the perk CLI process
**becomes** pi. The seam is the `perk/run/launch/` package (`launch_stage` + its phase functions
in `perk/run/launch/__init__.py`; `materialize.py`, `prompts.py`, `worktree.py`, `remote.py`).
This doc owns the launch phase — execution + positioning; what a door *gathers* before calling
`launch_stage` is `plan-factories.md`'s (§ "Policy stays in the door's `gather` closure").

## Distillation

- Build the launch `argv` ONCE, before the `dry_run` branch; inject perk defaults BEFORE
  pass-through args (pi parses last-wins) — "Build `argv` once, inject before pass-through".
- A local launch never returns; `--remote` returns through `_drive_remote_target` before any
  positioning or prompt assembly — "Local execs, remote returns".
- Env layering is merge order (injected defaults < operator env < perk stamps); a blank
  `PI_CODING_AGENT_DIR` is scrubbed from the child env, never forwarded; ONE agent-dir resolver,
  `launch_pi_agent_dir` — "Env setdefault via merge order", "The launch-precedence agent dir".
- A `worktree: none` stage runs in the MAIN checkout even from a linked worktree; positioning
  gates key off the *launched stage instance* — "`worktree: none` resolves to the main checkout".
- The `[worktree] setup` marker clears only after the hook succeeds — "The `[worktree] setup`
  hook is marker-gated".
- Skills are mirrored and `.pi/npm` pre-staged into the worktree before exec — nothing is
  filterable after the exec-wall — "Worktree positioning must mirror `.agents/skills/`", "Launch
  banner + worktree `.pi/npm` pre-staging".
- Resolve the absolute executable path BEFORE `os.chdir` (`which_absolute`): closes worktree
  binary substitution, NOT the shebang-interpreter `PATH` walk — "Exec-launcher safety".

## Local execs, remote returns

`launch_stage` resolves the target first (`resolve_target`). A remote target hands off to
`_drive_remote_target` (`remote.py`) and **returns** before positioning, prompt assembly or the
banner — `prompt_suffix`, `preview`, `[models.stages]` flags and the skills mirror are inert on
`--remote` (`remote-runner.md`). The local path is a fixed pipeline: banner → guarded main
fast-forward (`_sync_main_checkout`, read-only `worktree: none` stages) → `resolve_worktree` →
agent-dir resolution → the frozen `_LaunchContext` (argv included) → `--dry-run` preview
**returns here** → handoff → repo-root extension warm-up → worktree materialization → Linear
run-started emit → setup hook → `_exec_pi`. Nothing after the exec runs: a supervisor **cannot**
compose a local launch, so landing stays the interactive path (`objective-lifecycle.md`). The
headless worker (`perk run-worker`) bypasses this seam — no pi-CLI arg parsing, no trust
resolution; only the env parity below reaches it.

## Build `argv` once, inject before pass-through

`_build_argv` assembles the one vector shared verbatim by the dry-run JSON and `os.execvpe`, so
`--dry-run --json` previews exactly what would exec. Order: `pi`, `--approve` (worktree stages),
`[models.stages.<id>]` `--model`/`--thinking`, the skill-exposure flags (contracts §8.39,
fail-open to full discovery), `*pi_args`, the prompt. pi parses **last-wins**, so a user's
`--no-approve`/`--model` wins with zero perk code.

**Project trust on ephemeral worktrees.** pi prompts for trust on a cwd carrying trust-requiring
project resources (entries under `.pi/`, or `.agents/skills` in cwd/ancestors) with no decision
saved in the agent dir's `trust.json`. Every worktree stage `chdir`s into a fresh `plan-<id>`
checkout, so perk prepends `--approve` for `stage.worktree != "none"`. Verified in pi's `dist/`
(trust the dist when its docs disagree): the override short-circuits before any UI check, so it
works in **interactive** mode too, and writes no `trust.json` entry (run-scoped; no residue).

## Prompt assembly: the augment-only `prompt_suffix` seam

`_resolve_prompt` (`prompts.py`) assembles stage primer (or `prompt_override`) → `prompt_suffix`
→ skill-binding suffix. Both suffixes are **augment-only**: they never synthesize a prompt, so an
idle launch stays idle and the suffix is dropped. Use the seam for caller-supplied, *path-scoped*
additions — the `plan resume` reuse advisory (contracts §8.38) is the motivating caller — rather
than editing a parity-locked `prompts/stages/*.md` primer, which broadens behavior across all
three render sites.

## Env setdefault via merge order

`_build_exec_env` is `{**_NPM_QUIET_ENV, **FFF_MODE_ENV, **environ, PERK_RUN_ID, PERK_CLI_VERSION}`:
injected defaults < operator env < perk-owned stamps, **no conditionals**. Slot new launch-seam
vars into this layering, never `env.setdefault()` loops.

- **Cosmetic defaults are local-only; correctness defaults ride both spawn sites.** The advisory
  npm quiet vars stay off `perk/run/run_worker.py::_spawn_worker` (CI keeps full npm output);
  `FFF_MODE_ENV` (`PI_FFF_MODE=tools-and-ui`) is merged at BOTH sites — reviewer lanes need host
  `grep`/`find` on every path (`pi/subagents.md` § "The ≥ 0.67.0 host-builtin intersection").
- **The inherited-env trap.** A session launched by a *pre-flip* launcher carries the old
  injected value in its operator tier: judge a changed default from a relaunch or under `env -u
  PI_FFF_MODE`, and when a lane fails closed on "host lacks `[grep, find]`" read the launch
  seam's merge **first** — it was perk's injected tier, not the shell profile.
- **The Linear key seed.** `_exec_pi` fills `LINEAR_API_KEY` from `load_local_linear_api_key`
  (the gitignored `.perk/local.toml`, read from the **main checkout before `os.chdir`**) only
  when the environment lacks a non-blank value (`linear-backend.md`).
- **Test hygiene.** Env builders take `environ` explicitly — test them with a dict; a seam
  reading `os.environ` at call time needs an autouse `monkeypatch.delenv` (`tests/conftest.py`),
  or a developer's exported value causes phantom failures.

**Precedence normalization must reach the child environment.** Merge order suffices only when
key *presence* is the override rule. `launch_pi_agent_dir` treats a whitespace-only
`PI_CODING_AGENT_DIR` as unset, so `_build_exec_env` **scrubs** a blank inherited value from the
copied child env (never mutating the parent) instead of forwarding it — forwarding made pi read
an empty dir. Decide the configured redirect once, before the preview branch, and carry it
through preview and exec: the exec step cannot safely recompute precedence after `chdir`.

## The launch-precedence agent dir

`perk/substrate/config.py::launch_pi_agent_dir` is the ONE precedence implementation: non-blank
`PI_CODING_AGENT_DIR` → the main checkout's `[pi] agent_dir` (`effective_pi_agent_dir`, committed
config + local overlay — `config-tables.md`) → `~/.pi/agent`; `None` when nothing resolves. The
result carries its `source`: env injection only for `config` (the env arm already carries the
value; `default` is pi's own); the stale-lock sweep (non-directory lock paths only) targets the
resolution and skips on `None`; a broken main-checkout config warns and falls back to the
`default` arm. Every consumer acting on files *inside* the agent dir resolves through this
function — grep for `launch_pi_agent_dir(` to derive them (`init-doctor.md`).

## `worktree: none` resolves to the main checkout

`stage.worktree != "none"` is the canonical worktree-stage predicate — never enumerate stage
ids. The resolver ignores `--worktree` on a `worktree: none` stage, and invoking a two-roots
plan-selecting door **from** a linked worktree does not position there:
`perk/cli/plan_selection.py::main_repo_root` anchors the session at the main checkout.
`launch_stage` takes both roots — `repo_root` (positioning anchor) and `invocation_root` (only
the no-argument cache fallback: *which* plan) — and never derives one from the other
(`git-substrate.md`). So a planning session launched from a plan worktree runs in `main`, as do
its scout lanes — briefs name a target worktree by **absolute path** (`pi/subagents.md` § "Lane
evidence pitfalls").

**Positioning gates key off the launched stage instance**, not the registry row: `perk objective
plan`'s stacked child-layer arm positions a registry-`worktree: none` stage by passing a
transient `worktree: "reuse"` stage through `SeededLaunch.stage_override` (contracts §8.46), and
`_sync_main_checkout`, gated on the *effective* `worktree == "none"`, skips there.

## The `[worktree] setup` hook is marker-gated

`run_worktree_setup` (`materialize.py`) is the **single canonical setup-execution path** — the
*how*: each command runs via `bash -lc` in the worktree with captured stdio, swallowed on success
(the `$ {command}` echoes narrate) and replayed to stderr before the abort; non-zero exit,
timeout or missing `bash` raise `worktree_setup_failed`. *Whether* it runs is
`run_pending_setup` (`__init__.py`), keyed on `cache.SETUP_PENDING`: **set** by the positioner at
materialization (`create-fresh`/`restore-remote`,
`perk/run/launch/worktree.py::_materialize_binding`) and by `perk worktree create`; **cleared
only on success** — a failed setup leaves the marker, aborts before `exec pi`, and the next run
retries (a `reuse-local` checkout still carrying the marker is setup-eligible). Grep for
`run_pending_setup(` to derive the gate's consumers — never a roster. The remote
`position_worktree` deliberately skips the hook (CI setup is the composite action's).
**Ownership:** this section owns the marker lifecycle + execution prose; `worktree-lifecycle.md`
§ "The `[worktree] setup` hook and the dry-run preview asymmetry" owns only the preview
asymmetry and defers here.

## Worktree positioning must mirror `.agents/skills/`

A **linked-worktree** session sees **zero skills** unless the cold door mirrors them at
positioning time — two compounding causes: `.agents/skills/` is gitignored (the `skills managed
runtime artifacts` block), so `git worktree add` never carries it; and pi discovers
`.agents/skills/` only **up to the git repo root** (`@earendil-works/pi-coding-agent/docs/skills.md`
§ Locations), and a linked worktree is its own root. `materialize_skills(repo_root, worktree)`
(`materialize.py`) runs in `_materialize_into_worktree` after `materialize_plan_body`, before
`chdir`/exec: **per-skill symlinks** to `entry.resolve()` (single hop), delivering ALL skills —
not one `skills/` dir link (never a symlinked discovery *root*), not a per-launch skills sync
(network, heavy). Loud-but-non-fatal + idempotent: a missing/empty source warns and continues
(doctor's `skills-delivery` is the hard gate); a correct link is left, a stale one repointed, a
real entry never clobbered. Local-only: the remote `position_worktree` runs in `repo_root` and
syncs skills via the skills CLI (`skill-bindings.md`).

## Launch banner + worktree `.pi/npm` pre-staging

**The exec-wall.** pi's startup npm noise is pi's output *after* exec and cannot be filtered; the
only lever is pre-exec — make pi have nothing to install.

**Banner.** `print_launch_banner(repo_root)` latches a module-level guard on first emit and
no-ops after; `launch_stage` calls it before any worktree work, gated `not dry_run`. A door that
narrates load-bearing pre-launch I/O emits it *itself* through
`print_launch_banner_gated(repo_root, dry_run=, remote=)` — the one home of the `not dry_run
and remote is None` gate; `launch_stage`'s call is then the no-op fallback. Grep for
`print_launch_banner_gated(` to derive the narrating doors.

**Pre-stage `.pi/npm`.** `materialize_extensions` clone-copies the converged repo-root `.pi/npm/`
into the worktree so pi's `needsInstall` short-circuits. Copy, not symlink — per-worktree
isolation. The two npm worlds never overlap: repo-root `node_modules` = perk's dev deps;
`.pi/npm/` = pi's extension-install root (`toolchain/worktree-node-modules.md`). The repo-root
install is warmed **before** the clone — `_warm_extension_install`
(`ensure_extension_install_present`; idempotent, needs neither `env` nor `chdir`) precedes the
worktree block.

**The partial-tree cache hazard.** `_clone_npm_tree` is two-tier and `OSError`-only (hardlink
`copytree(copy_function=os.link)`, on `OSError` rmtree + deep copy); `materialize_extensions`
wraps it in `except OSError` and rmtrees the partial tree (`shutil.Error` subclasses `OSError`).
**General rule: a presence-only resume guard requires its writer to clean up partial state on
failure, or it caches corruption** (a half-copied package satisfies a presence check yet fails
to load).

## Exec-launcher safety: resolve the absolute executable path BEFORE the chdir

A launcher that **probes** for its executable and bare-name-execs *after* `os.chdir(worktree)`
lets a relative `PATH` entry (`.`) select a binary from the very tree it inspects. Safe shape:
resolve pre-chdir, exec the **absolute path** (argv[0] stays the bare name), typed refusal on a
miss, the chdir/exec race an ordinary `OSError` arm. Both probing seams — the pi launch and
`hunk_cli_path` — share ONE probe, `perk/substrate/proc.py::which_absolute`: `shutil.which`
pre-chdir, absolutized via `Path.absolute()` because `which` returns a **relative** candidate
when the matching `PATH` entry is relative; `None` on a miss. `_exec_pi` resolves `pi` FIRST
(`_resolve_pi_executable`; a miss is a typed `pi_cli_missing` refusal, **no bare-name
fallback**), then `os.execvpe(pi_path, …)` inside the `launch_failed` `OSError` arm. The miss
aborts the **exec phase only** — earlier phases may have run; a re-run reuses the materialized
worktree but **mints a fresh `run_id` + handoff** (handoffs are per-run artifacts, never
resumed).

**Bounded protection (recorded residual).** This closes *name substitution* from the worktree.
It does NOT close the shebang-interpreter lookup: pi's bin is a `#!/usr/bin/env node` script and
post-chdir `env` walks the unchanged `PATH`, so a relative entry could still select a
worktree-local `node`. Nor does it repair an untrusted *invocation* environment: launching from
**inside** the inspected tree with a relative `PATH` entry still resolves within it. The
residuals live in `which_absolute`'s docstring AND here — a claim of closing them must revisit
both.

## Composing a launcher that emits `machine_output` inside a `--json` surface

A composed launcher — the remote dispatch path `_drive_remote_target` — writes its own JSON to
stdout via `machine_output` and returns. A surface wanting ONE unified `--json` payload
(`perk/cli/commands/objective/run_cmd.py`) wraps the call in
`contextlib.redirect_stdout(io.StringIO())` and parses the needed fields (`run_id`) out of the
capture; otherwise it emits **two** JSON objects. **General trap:** any Python surface nesting a
`machine_output` caller must isolate that inner stdout.

## Leveled progress-log discipline (`io_step`)

The launch path narrates perceptible waits through `perk/substrate/output.py`'s glyph-only
vocabulary, **all via `user_output` → stderr**, so they never touch the stdout `--json` payload.
Steps use **`io_step(attempt)`** — a context manager yielding a handle whose `.done(msg)` /
`.warn(msg)` resolves the step; `log_step` is guard-confined to `output.py`
(`tests/test_output.py`).

- **Narrate where the I/O happens; never gate narration on a flag the I/O ignores.** "Keep
  stdout pristine" and "gate on `dry_run`" are independent because the log is stderr-only — a
  backend read that also runs on the dry-run path narrates unconditionally.
- **Every step resolves — structurally.** `io_step` auto-resolves `done(attempt)` on a clean
  exit; an escaping exception deliberately leaves the dangling `›` as the pinpointing signal. A
  second resolution appends, never raises. ANY interleaved `user_output`/`machine_output`
  forces the resolution to append rather than rewrite the `›` line, so a foreign line is never
  erased.

## Testing `--json` surfaces (Click ≥ 8.2 stream split)

Parse the payload from **`result.stdout`**. Since Click 8.2 `result.output` is the **combined**
stdout+stderr stream (`CliRunner(mix_stderr=False)` raises `TypeError` — the kwarg is gone), so
`json.loads(result.output)` breaks the moment a command narrates to stderr before its payload.
Byte-identity asserts split the same way: compare `result.stdout` against the baseline and
assert the loud-but-non-fatal note via `result.stderr`. When refactoring launch/run behind such
pins, **byte-exact test pins are sufficient proof of behavior preservation** — zero test edits
is the success signal; don't add helper-level tests (`plan-factories.md` reaffirms this).

## Cross-references

- `perk/run/launch/__init__.py` (`launch_stage`, `_build_argv`, `_build_exec_env`, `_exec_pi`,
  `run_pending_setup`), `perk/substrate/config.py` (`launch_pi_agent_dir`),
  `perk/substrate/proc.py` (`which_absolute`)
- `docs/learned/workflow/plan-factories.md` — the seeded-cold-door pipeline whose tail composes
  `launch_stage` (gather policy lives there); `docs/learned/workflow/worktree-lifecycle.md` —
  the setup hook's dry-run preview asymmetry
- `docs/learned/workflow/remote-runner.md`, `docs/learned/workflow/objective-lifecycle.md`,
  `docs/learned/workflow/skill-bindings.md`, `docs/learned/workflow/linear-backend.md`
