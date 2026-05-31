# Phase 0 · Turn 4 — CLI exterior core (config, worktrees, launch, registry→subcommands)

Detailed execution plan for **T4** of [phase-0-plan.md](./phase-0-plan.md). T4 builds the
session **exterior** ([cli-vs-pi.md](../cli-vs-pi.md) §2.2): the TOML config loader, the
registry-generated `perk <stage>` subcommands, the worktree lifecycle, and the **process-launch
primitive** that closes the loop T3 opened — the shell mints a `run_id`, launches `pi`, and the
T3 extension claims it. It also extends `perk init` to scaffold config + converge `.gitignore`.

> **The key reframe — T4 is (almost) pure-Python exterior, reusing T3's interior.** The launch
> primitive just *feeds* the T3 claim: mint a `run_id`, write the handoff, set `PERK_RUN_ID`,
> `exec pi`. The T3 extension already claims it (no TS change). T4 = the CLI launcher that closes
> the loop T3 built. Two small `contracts.md` touches (the handoff `stage` field; the now-built
> cold-mint launch path) are the only contract changes.

> **Scope discipline.** T4 builds the **launch *mechanism* and the CLI plumbing**. It does **not**
> resolve plan-refs / GitHub (Phase 1 — so stage positioning is by an explicit `--worktree NAME`,
> not by a plan), run in-session stage *handlers* (Phase 1), enforce read-only mode gating
> (Phase 2 mode primitive), or dispatch to a **remote** runner (Phase 3 — `--remote` errors,
> since every MVP stage is `cold_remote: false`). It introduces `require_github` *no earlier* —
> the GitHub gateway lands in **T5**.

---

## 1. Objective & the gate

**Goal.** Stand up the CLI exterior: `tomllib` config, the six registry-generated `perk <stage>`
launchers, `perk worktree create/list/remove`, and the `os.execvp` launch primitive — and extend
`perk init` to scaffold `perk.toml`/`perk.local.toml` and converge the `.gitignore` managed block.

**Hard gate (must pass to land T4).** Via `scripts/verify-t4.sh` on a fresh clone:
1. **Subcommands are registry-generated.** `perk --help` lists all six stages (`plan save
   implement submit land learn`); `perk implement --help` works; `perk plan --remote` errors with
   a clear "remote target is Phase 3" message (the `cold_remote: false` constraint, surfaced).
2. **Worktree lifecycle** against a real temp git repo: `perk worktree create wt1` creates a git
   worktree under `.worktrees/` and reports its path; `perk worktree list` shows it; `perk
   worktree remove wt1` removes it.
3. **The launch primitive closes the T3 loop.** `perk implement --worktree wt1 --dry-run` prints a
   sane plan (worktree path + `pi` argv + `PERK_RUN_ID`); **and** a real
   `perk plan -- -e $EXT --session-dir T --session-id S -p --no-tools "reply ok"` execs `pi`, the
   T3 extension **claims the run_id** (handoff consumed; the session's `perk:workflow-state` carries
   the CLI-minted id; `source=env`) — the same checks as T3, but the id is now minted+launched by
   `perk <stage>`.
4. **`perk init` scaffolds config + converges `.gitignore`.** It writes `.pi/perk.toml`
   (committed) and `.pi/perk.local.toml` (gitignored), and moves the T3 transient `.pi/workflow/`
   ignores into the **managed** block (+ `perk.local.toml`); re-running is a **no-op**; the T1/T2/T3
   gates still pass.
5. **Unit tests** (`pytest`): config overlay (local wins), git worktree ops, launch argv
   construction + `--dry-run`, and registry→subcommand generation.

`just verify` runs t1 + t2 + t3 + **t4**.

---

## 2. Grounding & doc lineage (what governs T4)

- **The CLI↔Pi boundary (cli-vs-pi §2–§4).** T4 is the **exterior** (§2.2): setup/config,
  worktree lifecycle, process launching. **The CLI may *initiate* a stage but never *steers* a
  live turn** (§2.3) — the launcher positions + execs `pi`, then hands off. The **stage is the
  unit of parity** (§4.1): one extension implementation (interior), up to three cold/warm doors,
  **generated from the one registry** (§4.2) so parity can't drift. The cold door is
  **parameterized by target** (§4.5) — local (`exec pi`) now, remote (Phase 3) later.
- **The CLI house style is `python-cli-guidelines.md`** — and T4 is where the **deferred DI lands**
  (the guideline's own scope note: "the DI context lands with the first command that takes a
  git/GitHub dependency"). Worktrees + launch + config are exactly that. The three-layer structure
  (§1), `require_*()` (§2), option rules (§3), `Ensure.*`/`UserFacingCliError` (§4–5), and the
  human/machine stream split (§7) all apply.
- **Config = TOML, repo+local split (Q13).** `.pi/perk.toml` (committed) overlaid by
  `.pi/perk.local.toml` (gitignored), via stdlib **`tomllib`** (read-only; `init` *writes* the
  files). The global `~/.pi` layer (PRIOR_ART §9) is deferred.
- **Reuses the T3 substrate verbatim:** `run_id.mint`, `cache.write_handoff`/`ensure_layout`, and
  the T3 extension's `claimRunId` (no TS change). The registry (T2) is the source of truth for the
  generated subcommands and each stage's `worktree`/`mode`/`doors`.
- **Repo convention in force:** no `from __future__ import annotations` (3.13); dignified-python
  throughout (LBYL, `encoding="utf-8"`, `click.echo` via `output.py`, `UserFacingCliError` at the
  boundary).

---

## 3. Prior-art pass — sharpenings folded in

1. **Three-layer command structure is mandatory** (guidelines §1): every command is `@click`
   callback → `require_*()` → a Click-free `_impl(*, keyword-only)`. Applies to all four worktree/
   stage commands; it's what makes them testable via `PerkContext.for_test`.
2. **`--remote` uses the documented optional-value-flag shape** (§3.4):
   `type=str, default=None, is_flag=False, flag_value=""` (`--remote` → default runner; `--remote
   ci-large` → named). In T4 it **errors** (remote-blocked), but the shape is the locked one.
3. **Domain validation via `Ensure.*`** (§4 Tier 2): worktree name non-empty / no path
   separators, repo-required, door-legal — `Ensure.invariant`/`not_empty`/`not_none`, not ad-hoc
   `if`s. `perk/cli/ensure.py` already ships `Ensure` (T1).
4. **Stage launchers are supervisor-facing, not agent affordances** (§8.2 / cli-vs-pi §3.2): the
   machine surface is **`--dry-run --json`** (`{success, …}`) for a supervisor/CI; the agent never
   shells `perk <stage>`. Keep it narrow; **no `schema`/MCP**.
5. **Local exec borrows `prompt_executor.os.execvp`** — erk's `launch_cmd.py` is the **remote**
   GitHub-Actions dispatch (= perk's Phase-3 `--remote` target), *not* the local launcher. T4's
   local launch is `os.execvp`; `--remote` is the future analog.
6. **Defer Rich** (a flagged §7.3 deviation): `worktree list` is 2–3 columns — use simple aligned
   `user_output`, not the `rich` dep, until a real dashboard lands. Recorded, not silent.
7. **No branch-name-encoded metadata** (PRIOR_ART §11): worktrees are named **explicitly**
   (`--worktree NAME`); the plan→branch mapping is `cache.plan-ref` (Phase 1). T4 does not derive
   names from plans.
8. **Config is the repo+local split now** (PRIOR_ART §9); erk's idiom
   `tomllib.loads(path.read_text(encoding="utf-8"))` → a **frozen dataclass**. Global layer
   deferred.
9. **Registry→subcommand generation is defensive** (cli-vs-pi §4.2): if the registry fails to
   load, the stage commands are simply absent and the core commands (`--version`, `init`, `doctor`,
   `registry`, `state`) still work — so `perk registry check` can diagnose the break.

---

## 4. Repo additions (end of T4)

```
perk/
├── perk/
│   ├── config.py            # NEW — tomllib loader (perk.toml + perk.local.toml overlay) -> Config
│   ├── git.py               # NEW — thin git gateway (repo_root, worktree add/list/remove, branch)
│   ├── launch.py            # NEW — the launch primitive (mint + handoff + position + execvp)
│   ├── init.py              # (modified — scaffold perk.toml/perk.local.toml; managed .gitignore)
│   └── cli/
│       ├── cli.py           # (modified — build PerkContext on the root group; register stages)
│       ├── context.py       # NEW — PerkContext + require_repo/require_config/require_git (+ for_test)
│       ├── stages.py        # NEW — registry -> one launcher command per stage (the generator)
│       └── commands/
│           └── worktree_cmd.py   # NEW — `perk worktree create/list/remove`
├── shared/
│   └── contracts.md         # (modified — handoff carries `stage`; the cold-mint launch path, §8.1/§8.2)
├── tests/
│   ├── test_config.py       # NEW — overlay/defaults
│   ├── test_git.py          # NEW — worktree ops against a temp repo
│   ├── test_launch.py       # NEW — argv construction + dry-run (no exec)
│   └── test_cli_stages.py   # NEW — CliRunner: generation, --remote error, worktree cmds (for_test)
├── scripts/verify-t4.sh     # NEW — the T4 hard gate (checks 1–5)
├── pyproject.toml           # (UNCHANGED — tomllib is stdlib; NO new dep)
└── justfile                 # (modified — `verify` adds t4)
```

**No new dependency** — `tomllib` is stdlib (3.11+); Rich is deferred (#6). No TS change (the T3
extension does the claiming).

---

## 5. Locked choices (the six decisions + the sharpenings)

| Choice | Locked value | Why / easy-to-forget detail |
|---|---|---|
| Launch mechanism | **`os.execvp`** (replace the process) | The CLI *becomes* `pi` — hand-off is literal (erk's `prompt_executor`). **`chdir` to the worktree first**, then `execvpe` with a copied env + `PERK_RUN_ID` set. Local-interactive by default. |
| Test/headless seams | `--dry-run` (print argv, no exec) + trailing `-- <pi args>` passthrough | `--dry-run` is the **supervisor machine surface** (`--json`). The `--` passthrough lets the gate inject `-e … --session-dir … -p …`; real interactive use passes nothing and `pi` auto-loads the extension via `.pi/settings.json`. |
| T4 = Python-only | reuses the T3 extension claim | The handoff gains a forward-looking **`stage`** field (Phase 1 auto-runs that stage's command; T4's extension ignores it). Handoff = `{run_id, stage, mode, consumed}`. |
| DI lands now | `PerkContext` + `require_repo`/`require_config`/`require_git` | Built **lazily** — the root group sets `ctx.obj = PerkContext(cwd=Path.cwd())` (cheap, no I/O), so `--version`/`init`/`registry`/`state` work **outside a repo**; `require_*` does discovery and raises `UserFacingCliError` if not a repo. **No `require_github` yet** (T5). |
| Generation | defensive, registry-driven | Load the registry at CLI construction inside `try/except`; on failure, stage commands are absent and core commands still work. One launcher per stage, named `stage.id`. |
| Worktree root | **`<repo>/.worktrees/<name>`** (self-contained), configurable | `[worktree] root` in `perk.toml` overrides; relative roots resolve against the repo root. `init` gitignores `.worktrees/`. `perk worktree create` **only creates + reports the path** — no shell-`cd` (shell-activation is Phase 1, phase-0-plan deferral). |
| Config | minimal — `[worktree] root` only | `tomllib` (stdlib, **read-only**); `init` *writes* the templated TOML. `Config` is a frozen dataclass; the template ships commented future sections (no fiction). |
| `worktree list` output | simple aligned `user_output` (defer Rich) | §7.3 mandates Rich for tables; deferred until a real dashboard — flagged, not silent. |
| Verify wiring | add `scripts/verify-t4.sh`; `just verify` runs t1+t2+t3+t4 | Gates are cumulative. |

---

## 6. Work breakdown (ordered)

### T4.spike — the execvp/watchdog launch mechanics (throwaway)
Before building, confirm headlessly: (a) when `perk` (run via `uv run`) **`os.execvp`s into `pi`**,
the gate's background-kill **watchdog still terminates the resulting `pi`** (the exec replaces the
process image in place, so the PID the watchdog holds *is* `pi`); (b) `pi -p` **self-exits** so the
watchdog is only a safety net; (c) the exact `pi` argv shape for the passthrough (so `perk plan --
-e … -p …` lands a clean invocation). *Accept:* the kill works (or pin the wrapping that makes it
work) and a real `perk <stage> -- … -p …` round-trips the claim. Carry the working invocation into
`verify-t4.sh`.

### T4.a — `perk/config.py`
`Config` (frozen dataclass: `worktree_root: Path`); `load_config(repo_root) -> Config` reads
`.pi/perk.toml` then overlays `.pi/perk.local.toml` via `tomllib.loads(path.read_text("utf-8"))`,
missing files → defaults; a relative `[worktree] root` resolves against `repo_root` (default
`repo_root/".worktrees"`). LBYL (`is_file()` before read).
*Accept:* `test_config.py` — defaults when absent; local overrides shared; relative root resolves.

### T4.b — `perk/git.py`
A thin `git`-shelling gateway: `repo_root(cwd) -> Path | None` (`rev-parse --show-toplevel`);
`Worktree` dataclass (path, branch, head); `worktree_add/list/remove`, `current_branch`. Parse
`git worktree list --porcelain`. `subprocess.run([... ], check, capture, text)`; translate failures
to `UserFacingCliError` at the command boundary, not deep in the gateway.
*Accept:* `test_git.py` — against a `git init`'d temp repo: add → list shows it → remove.

### T4.c — `perk/cli/context.py` (the DI)
`PerkContext` (holds `cwd`; lazily resolves+caches `repo_root`, `config`, `git`); `require_repo`/
`require_config`/`require_git(ctx) ` (narrow + clear errors per guidelines §2); `PerkContext.for_test(
*, repo_root=…, config=…, git=…)`.
*Accept:* `require_repo` raises a clean `UserFacingCliError` outside a repo; `for_test` injects fakes.

### T4.d — `perk/launch.py` (the primitive)
`launch_stage(*, ctx, stage, worktree, dry_run, remote, pi_args)`:
1. `remote is not None` → `UserFacingCliError` ("remote target is Phase 3; `<stage>` is
   cold_remote-blocked").
2. `Ensure` the `cold_local` door is open (defensive; all MVP stages true).
3. resolve the worktree path by the stage's `worktree`: `none` → repo root; `create` → create under
   `config.worktree_root/NAME` (require `--worktree`); `reuse` → resolve existing (require
   `--worktree`).
4. `rid = run_id.mint()`; `cache.ensure_layout(wt)`; `cache.write_handoff(wt, rid, {"stage":
   stage.id, "mode": stage.mode})`.
5. build argv `["pi", *pi_args]`; env `{**os.environ, "PERK_RUN_ID": rid}`.
6. `dry_run` → print `{worktree, run_id, argv}` (human to stderr; `--json` to stdout) and return.
7. else → `os.chdir(wt)`; `os.execvpe("pi", argv, env)`.
*Accept:* `test_launch.py` — argv + handoff written under the worktree; `--dry-run` returns without
exec; `--remote` raises.

### T4.e — `perk/cli/stages.py` + register in `cli.py`
`make_stage_command(stage) -> click.Command` (a launcher: `--worktree`, `--dry-run`, the §3.4
`--remote`, and `-- <pi args>`; thin callback → `require_*` → `launch_stage(...)`).
`register_stage_commands(cli)` loads the registry defensively and adds one per stage. `cli.py`'s
root group sets `ctx.obj = PerkContext(cwd=Path.cwd())`.
*Accept:* gate check 1.

### T4.f — `perk/cli/commands/worktree_cmd.py`
`perk worktree` group: `create NAME [--branch B]`, `list`, `remove NAME [--force]` — thin callbacks
→ `require_git`/`require_config` → `_impl`. `create` prints the path (no shell-`cd`).
*Accept:* gate check 2.

### T4.g — extend `perk/init.py`
Scaffold `.pi/perk.toml` (committed; templated default with a `[worktree]` section + commented
future sections) and `.pi/perk.local.toml` (gitignored; minimal). **Converge `.gitignore`**: move
the T3-added transient `.pi/workflow/` ignores into the **managed** block and add
`.pi/perk.local.toml` + `.worktrees/`. Idempotent.
*Accept:* gate check 4 (+ T1/T2/T3 gates still pass).

### T4.h — `contracts.md`, tests, verify, just
Amend `contracts.md` §8.1/§8.2 (handoff `{run_id, stage, mode, consumed}`; the CLI cold-mint launch
path now built). Write the tests, `scripts/verify-t4.sh` (checks 1–5), wire `just verify`. Keep
`ruff`/`ty`/`biome`/`tsc` green.
*Accept:* the whole T4 gate is one command; `just ci` stays green.

---

## 7. The launch primitive (the locked design)

The cold door (cli-vs-pi §4.1): **position the environment, then `exec pi` primed for the stage.**
T4 builds the mechanism; plan-ref positioning is Phase 1.

```
launch_stage(ctx, stage, worktree, dry_run, remote, pi_args):
  if remote is not None: raise UserFacingCliError("remote target is Phase 3 …")   # cold_remote:false
  Ensure.invariant(stage.doors["cold_local"], f"{stage.id} has no cold-local door")
  wt = resolve_worktree(ctx, stage, worktree)        # none->repo_root ; create/reuse->.worktrees/NAME
  rid = run_id.mint()                                # the CLI is the only minter (T3)
  cache.ensure_layout(wt)
  cache.write_handoff(wt, rid, {"stage": stage.id, "mode": stage.mode})
  argv = ["pi", *pi_args]; env = {**os.environ, "PERK_RUN_ID": rid}
  if dry_run: emit({worktree: wt, run_id: rid, argv}); return
  os.chdir(wt); os.execvpe("pi", argv, env)          # CLI becomes pi; hand-off is literal
```

**Easy-to-forget mechanics:**
- **The handoff is written under the *worktree*** (`wt/.pi/workflow/handoff/<rid>.json`), because
  `pi` runs with `cwd = wt` and the extension claims from `ctx.cwd`. `chdir(wt)` before `execvpe`.
- **`execvpe` replaces the process** — nothing after it runs; the env carries `PERK_RUN_ID`. This is
  the literal §2.3 hand-off (the CLI's authority ends at launch).
- **Extension loading:** real interactive use passes no `pi_args`; `pi` auto-discovers
  `.pi/settings.json` (which `init` wired) and loads the perk extension. The **gate** passes
  `-- -e $EXT …` so it doesn't depend on settings.json in a throwaway repo.
- **The launched session claims the run_id via the T3 extension** — `PERK_RUN_ID` is set, the
  handoff exists, `claimRunId` records it in `perk:workflow-state` and marks the handoff consumed.
  T4 adds **no** interior logic; the in-session *stage handler* (acting on `handoff.stage`) is
  Phase 1.
- **`--remote` is the §3.4 optional-value flag** and errors now; it is the seam for the Phase-3
  remote target (erk's `launch`/`dispatch`).

---

## 8. Registry → subcommands + the stage-command shape

cli-vs-pi §4.2: the Python CLI **generates** its subcommands from the registry, so the two entry
planes can't drift.

- At CLI construction, `register_stage_commands(cli)` calls `load_registry()` (defensive
  `try/except`) and, per stage, `cli.add_command(make_stage_command(stage))`.
- Each generated command is named `stage.id` and is a **launcher** over the stage descriptor
  (its `worktree`, `mode`, `doors`). The stage's `summary` becomes the help text.
- **Door legality from the registry:** `--remote` is rejected because `doors.cold_remote == false`;
  a (hypothetical) `cold_local: false` stage would refuse a cold launch with a clear message. All
  six MVP stages have a cold-local door, so all six get a launcher.

**Stage command shape (locked):**
```
perk <stage> [--worktree NAME] [--dry-run] [--remote [NAME]] [-- <pi args>]
```
- `--worktree NAME` positions a `create`/`reuse` stage (required for those; ignored for `none`).
  *Plan-ref resolution that would derive this name is Phase 1* (PRIOR_ART §11 — no branch-name
  metadata).
- `--dry-run` prints the plan (`--json` for the supervisor); `--remote` errors; `-- <pi args>`
  passes through to `pi`.

---

## 9. Config + DI (the exterior plumbing)

**Config (Q13).** `tomllib` (stdlib, read-only) loads `.pi/perk.toml` then overlays
`.pi/perk.local.toml`; **`init` writes** them (templated strings — `tomllib` can't write). `Config`
is a **frozen dataclass**; T4 needs only `worktree_root` (default `repo_root/".worktrees"`,
overridable via `[worktree] root`). The template carries commented future sections — no fiction.

**DI (guidelines §1–§2, landing now).** Three layers per command: thin `@click` callback →
`require_*(ctx)` → `_impl(*, …)`. `PerkContext` holds `cwd` and lazily resolves+caches `repo_root`
(via `git.repo_root`), `config` (via `load_config`), and a `git` gateway. `require_repo`/
`require_config`/`require_git` narrow + raise clean `UserFacingCliError`s; `for_test` injects fakes.
Built **lazily** (root group sets `ctx.obj = PerkContext(cwd=Path.cwd())`) so non-repo commands
(`--version`, `init`, `registry`, `state`) keep working outside a git repo.

**`init` convergence (forward).** `init` now also: writes `perk.toml`/`perk.local.toml` if missing;
**moves** the T3 transient `.pi/workflow/` ignores from the dev-artifacts section into the **managed**
block and adds `.pi/perk.local.toml` + `.worktrees/`. Re-running stays a no-op (idempotent). This is
the "init converges forward / doctor repairs oddities" rule — the T3 hand-edit is now init-owned.

---

## 10. Acceptance gate — concrete, runnable checks (`scripts/verify-t4.sh`)

Reuses the harness conventions: only `pi` is watchdog-wrapped; `uv run --project` for Python;
artifact/state membership via Python, never `grep` under `pipefail`.

1. **Generation.** `perk --help` lists the six stages; `perk implement --help` works; `perk plan
   --remote` exits non-zero with "remote target is Phase 3".
2. **Worktrees.** In a temp `git init` repo: `perk worktree create wt1` → `.worktrees/wt1` exists +
   path printed; `perk worktree list` shows `wt1`; `perk worktree remove wt1` → gone.
3. **Launch loop.** `perk implement --worktree wt1 --dry-run` prints a worktree path + a `pi` argv +
   the minted `PERK_RUN_ID` (asserted via `--json`); **then** the real loop in a temp repo:
   `perk plan -- -e $EXT --session-dir $T/sessions --session-id s4 -p --no-tools "reply ok"` →
   handoff `consumed: true`, the session JSONL has a `perk:workflow-state` entry whose `run_id` is
   the CLI-minted id, and the T3 sentinel reports `source=env`.
4. **`init` convergence.** `perk init` writes `perk.toml` (committed) + `perk.local.toml`
   (gitignored), the managed `.gitignore` block contains the `.pi/workflow/` transients +
   `perk.local.toml` + `.worktrees/`; a second `perk init` changes nothing; `git check-ignore`
   confirms `perk.local.toml` is ignored.
5. **Unit tests.** `pytest tests/test_config.py tests/test_git.py tests/test_launch.py
   tests/test_cli_stages.py` pass.

`just verify` runs t1 + t2 + t3 + t4; `just ci` stays green.

---

## 11. Risks & mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| `uv run perk` → `execvp pi` breaks the gate's kill-watchdog (PID indirection) | med | **spike it** (T4.spike); `execvp` replaces the image in-place so the watchdog's PID *is* `pi`; `-p` self-exits anyway |
| `pi` in the launched worktree can't find the perk extension (settings.json relative paths in a worktree) | med | the gate passes `-e $EXT` explicitly; real consumers commit `.pi/settings.json`; doctor (T6) verifies wiring |
| Registry fails to load → whole CLI bricks | low | generation is **defensive** (try/except); core commands survive; `registry check` diagnoses |
| Worktree-inside-repo (`.worktrees/`) confuses git status / recursion | low-med | `init` gitignores `.worktrees/`; `worktree list` uses `--porcelain`; cleanup via `worktree remove` |
| `--dry-run` machine output drifts from the real exec argv | low | both paths build argv from one `_build_argv`; `test_launch.py` asserts they match |
| DI over-built for one turn | low | scope to `require_repo`/`require_config`/`require_git`; no `require_github` (T5); lazy build keeps non-repo commands working |

---

## 12. Explicitly out of scope for T4 (pointers)

- **Plan-ref / GitHub resolution** (derive worktree/branch from a plan; materialize plan state) —
  **Phase 1**. T4 positions by explicit `--worktree NAME`.
- **In-session stage *handlers*** (what `/implement` etc. *do*) — **Phase 1** (the launched `pi`
  claims and sits).
- **Read-only mode *enforcement*** (plan-mode gating) — **Phase 2** (T4 records `mode` in the
  handoff; the extension stores it; no gating yet).
- **Remote target** (`--remote` actually dispatching a runner) — **Phase 3** (erk's
  `launch`/`dispatch`); T4's flag errors.
- **Cold-mint-with-predecessor across a real *resume*** — **Phase 1** (needs plan-ref resolution to
  find the prior run); T4 mints fresh ids.
- **GitHub gateway / `require_github`** — **T5**. **`perk doctor`** (verifies config + worktrees +
  wiring) — **T6**. **Capability tracking** (required-vs-optional) — **T5**.
- **Shell-activation movement** (`source <(perk … --script)` to `cd` the parent shell) — **Phase 1**
  (phase-0-plan deferral); `worktree create` only reports the path.
- **Rich tables** — deferred until a real dashboard (§7.3).

## 13. Open questions to settle during T4 (lean answers)

1. **`perk worktree create` default branch** — new branch off HEAD vs detached. *(Lean: create a
   branch named after the worktree off the current HEAD; `--branch` overrides.)*
2. **`--dry-run` JSON shape** — `{success, worktree, run_id, argv}`. *(Lean: yes, that shape — it's
   the supervisor surface for the Phase-3 dispatch path.)*
3. **`perk.toml` template breadth** — only `[worktree]` vs commented `[launch]`/`[github]` stubs.
   *(Lean: `[worktree]` live + a short commented header pointing at the docs; no fiction.)*
4. **Does the root group's lazy `PerkContext` interfere with `CliRunner` tests** that pass
   `obj=PerkContext.for_test(...)`? *(Lean: no — `ctx.obj` set via `invoke(obj=…)` is respected;
   the group callback only builds one when `obj is None`.)*

## 14. Definition of done

The five hard-gate checks in §10 pass via `scripts/verify-t4.sh` on a fresh clone; the six stage
launchers are **registry-generated**; `perk worktree …` creates/lists/removes; the launch primitive
**closes the T3 loop** (a `perk <stage>`-minted `run_id` appears in the launched session's
`perk:workflow-state`); `perk init` scaffolds the config files and converges `.gitignore`, and
re-running stays a no-op; `tomllib` config overlays correctly; `just ci` and `just verify`
(t1+t2+t3+t4) are green. T4 lands; **T5 can finish `init` (env/GitHub verification, capability
tracking, handoff) on top of this config + DI, and Phase 1 can hang real plan-ref positioning and
in-session handlers off these launchers.**

---

## 15. T4 outcomes (recorded after implementation)

**Status: implemented; T4 hard gate ALL PASS; T1–T3 gates still PASS; `just ci` green.**

**Built (as planned):** `perk/config.py` (tomllib overlay -> `Config`), `perk/git.py` (worktree
gateway + `repo_root`/`current_branch`), `perk/cli/context.py` (`PerkContext` +
`require_repo`/`require_config` + `for_test`), `perk/launch.py` (`launch_stage` +
`resolve_worktree`), `perk/cli/stages.py` (registry -> six launchers), `perk/cli/commands/worktree_cmd.py`
(`create`/`list`/`remove`), the `cli.py` root-context wiring, and the `init.py` extension
(scaffold `perk.toml`/`perk.local.toml` + managed-block `.gitignore` convergence). Tests:
`test_config`, `test_git`, `test_launch`, `test_cli_stages` (+ a `git_repo` conftest fixture).
`scripts/verify-t4.sh`; `just verify` runs t1–t4. **Python-only — no TS change** (the T3 extension
does the claiming).

**Gate results:** all five checks PASS — (1) `perk --help` lists the six registry-generated stages,
`perk plan --remote` blocks with "Phase 3"; (2) `perk worktree create/list/remove` against a real
repo; (3) `perk implement --dry-run` emits a launch plan, **and a real `perk plan -- -e … -p …`
launches `pi` whose extension claims the CLI-minted run_id** (handoff consumed + persisted to the
session, `source=env`); (4) `perk init` scaffolds config + converges `.gitignore`, re-run is a
no-op, `perk.local.toml` is git-ignored; (5) unit tests (14). Full suite: **43 pytest + 11
node:test**.

**Decisions confirmed by building:**
- **`os.execvpe` + watchdog works through `uv run`** (T4.spike): the exec'd `pi` claims the run_id
  and is killable; `pi -p` self-exits. The verified invocation is in `verify-t4.sh` check 3.
- **`--dry-run` was made side-effect-free** (refined from the plan): `resolve_worktree` takes a
  `materialize` flag, so a dry run neither creates the worktree nor writes a handoff — it only
  mints an in-memory run_id and prints the argv. This is the right supervisor surface.
- **`require_git` folded into `require_repo`** (deviation from the doc's naming): git ops are
  stateless module functions over the repo root, so `require_repo` *is* the git binding — a
  separate `require_git` would be ceremony. `require_repo`/`require_config` are the two accessors.
- **Lazy `PerkContext` doesn't fight `CliRunner`** (open question #4 confirmed): the root group
  only builds a context when `ctx.obj is None`, so `invoke(obj=PerkContext.for_test(…))` is honored.
- **Defensive generation holds:** a registry load failure leaves the core commands working.

**Deps:** **none added** — `tomllib` is stdlib; Rich deferred (`worktree list` uses plain aligned
output, a flagged §7.3 deviation). No TS runtime/dev dep.

**Implementation notes (easy-to-forget, for later turns):**
- The handoff is written under the **worktree** (`os.chdir(wt)` before `execvpe`), because `pi`'s
  `ctx.cwd` is the worktree and the extension claims from there. For a `worktree: none` stage the
  worktree *is* the repo root.
- **Stage passthrough:** the launchers use `context_settings={"ignore_unknown_options": True}` +
  `nargs=-1, type=click.UNPROCESSED`, so `perk <stage> -- <pi args>` forwards cleanly.
- `uv run --project $ROOT perk` runs in the **caller's cwd** (not `$ROOT`), which is why
  `require_repo` discovers the right repo and the handoff lands in the right place.
- The door/remote checks currently run **after** `require_repo`/`require_config` (the three-layer
  pattern resolves deps first), so `perk plan --remote` must be run inside a repo to see the
  "Phase 3" message rather than "Not a git repository".

**Contract reconciliation (`shared/contracts.md`, per §2).** §8.1 now documents the **handoff blob**
`{ run_id, stage, mode, consumed }` (+ `pi_session_id` once claimed) — the `stage` field the launch
adds for Phase 1's in-session handler. The `.gitignore` was converged forward: the T3 hand-edited
transient ignores moved from the dev-artifacts section into `init`'s **managed block** (+
`perk.local.toml` + `.worktrees/`).

**Still deferred (unchanged):** plan-ref / GitHub resolution + in-session handlers (Phase 1);
read-only mode *enforcement* (Phase 2); the remote target (Phase 3); `require_github` + the gateway
+ capability tracking (T5); `perk doctor` (T6); shell-activation movement (Phase 1); Rich tables.

**Verify:** `bash scripts/verify-t4.sh` (5/5 PASS), `just verify` (t1–t4 ALL PASS), `just ci` green
(ruff + biome + ty + tsc + 43 pytest + 11 node:test).
