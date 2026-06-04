# Phase 2 · Turn 16 — Neutralize pi's stale-lockfile startup warning at perk's launch chokepoint

> The decision-complete plan lives on GitHub plan **#40** (`plan-body` block). This doc records the
> prior-art pass, the turn's decisions, and — written **after** the work lands — the as-built
> **outcomes**. (Planned as "T15" but turn 15 landed first on `main` via #39, so this turn took the
> next free number, **T16**.)

## 1. Objective

Every `perk` command that launches pi (`implement`, `resume`, `objective-plan`, …) prints a yellow
warning on every launch:

```
Warning: (startup session lookup, global settings) ENOTDIR: not a directory, rmdir '~/.pi/agent/settings.json.lock'
```

It is harmless (the launch proceeds) but noisy. Silence it permanently at perk's single launch
chokepoint without patching pi.

## 2. Prior-art pass (pi internals, verified)

- pi locks its global agent-dir settings at startup via `proper-lockfile`:
  `dist/core/settings-manager.js` → `acquireLockSyncWithRetry` → `lockfile.lockSync`.
- `proper-lockfile` holds a lock as a **directory**: `getLockFile` returns `` `${file}.lock` `` and
  `acquireLock` does an atomic `mkdir`; `removeLock` does `rmdir`
  (`node_modules/proper-lockfile/lib/lockfile.js`). A **held** lock is therefore always a directory.
- A stale regular **file** at `settings.json.lock` makes `mkdir` → `EEXIST`; pi judges it stale by
  mtime and `rmdir`s it → **`ENOTDIR`** (path is a file). The error is drained and rendered yellow
  by `reportDiagnostics` (`dist/main.js`).
- `dist/config.js getAgentDir()` resolves `PI_CODING_AGENT_DIR` (env), else `~/.pi/agent`.

## 3. Decisions

- **(1) Fix at the chokepoint.** `launch_stage` in `perk/launch.py`, on the real launch path only
  (after `dry_run` returns), immediately before `os.chdir(wt)` / `os.execvpe(...)`.
- **(2) Safety predicate.** Remove a lock path **iff it is not a directory** (`Path.is_dir()` False).
  A directory = live `proper-lockfile` lock → never touched; a non-directory = stale artifact →
  `unlink(missing_ok=True)`.
- **(3) Which locks.** The two agent-dir locks pi takes: `settings.json.lock` and `auth.json.lock`,
  under pi's global agent dir. Project-scope (`<worktree>/.pi/...`) locks are **out of scope**
  (fresh `.pi/`; observed bug is global) — flagged, not built.
- **(4) Agent-dir resolution mirrors pi:** `PI_CODING_AGENT_DIR` (expanduser) else `~/.pi/agent`.
- **(5) Best-effort/non-fatal.** Wrap in `try/except OSError`; a sweep failure never blocks a launch.
  If a stale lock survives, pi surfaces its own diagnostic — a report-not-swallow boundary.
- **(6) No doctor check** (rejected): `doctor` operates on the repo root and would not prevent the
  next-launch warning on global state.

## 4. Key changes

- `perk/launch.py`: `_PI_AGENT_LOCK_FILES` constant; `_pi_agent_dir()`; `_sweep_stale_pi_agent_locks()`;
  call before `os.chdir` on the real launch path.
- `tests/test_launch.py`: unit tests (file removal, live-dir untouched, absent no-op, OSError
  swallowed, `_pi_agent_dir` env/expanduser/fallback) + an integration test asserting the sweep runs
  before exec.

## 5. Outcomes

As-built matches the plan with no behavioral deviations:

- `perk/launch.py` gained `_PI_AGENT_LOCK_FILES`, `_pi_agent_dir()`, `_sweep_stale_pi_agent_locks()`,
  and the pre-`chdir` sweep call.
- `tests/test_launch.py` gained 7 unit tests + 1 integration test (`test_launch_sweeps_stale_lock_before_exec`);
  full suite green.
- No `shared/contracts.md` change — this is a launch-time best-effort cleanup, not a cross-plane
  behavioral contract.
</content>
</invoke>
