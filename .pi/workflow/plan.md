I don't have the `plan_save`/`/plan off` tools exposed in this session, so here is the finalized, decision-complete plan for you to save.

---

# Plan: Neutralize pi's stale-lockfile startup warning at perk's launch chokepoint

## Problem / Status
Every `perk` command that launches pi (`perk implement`, `resume`, `objective-plan`, etc.) prints:

```
Warning: (startup session lookup, global settings) ENOTDIR: not a directory, rmdir '/Users/<user>/.pi/agent/settings.json.lock'
```

This is **harmless** (the launch proceeds) but fires on every launch.

### Root cause (verified)
- pi locks its global settings at startup using `proper-lockfile`:
  - `dist/core/settings-manager.js` → `FileSettingsStorage.acquireLockSyncWithRetry` → `lockfile.lockSync(path, {realpath:false})`.
  - `main.js:423-425`: `getAgentDir()` → `SettingsManager.create(cwd, agentDir)` → at startup `reportDiagnostics(collectSettingsDiagnostics(startupSettingsManager, "startup session lookup"))`.
- `proper-lockfile` acquires a lock by **`mkdir`-ing a directory** named `<file>.lock` (`node_modules/proper-lockfile/lib/lockfile.js`, `acquireLock`: `options.fs.mkdir(lockfilePath, ...)`; `getLockFile` returns `` `${file}.lock` ``). A held lock is therefore **always a directory**.
- When a stale **regular file** sits at `settings.json.lock`: `mkdir` → `EEXIST`; pi judges it stale by mtime; `removeLock` calls `options.fs.rmdir(...)` → **`ENOTDIR`** because the path is a file, not a directory.
- The error is captured via `SettingsManager.recordError` (`settings-manager.js:292-294`), drained by `drainErrors` (line ~376), and rendered yellow by `reportDiagnostics` (`main.js:64-70`).

### Why fix it in perk (not pi)
perk launches pi through a **single chokepoint**: `os.execvpe("pi", argv, env)` at `perk/launch.py:303` inside `launch_stage`. perk cannot patch pi, but it can clean the stale lock immediately before exec. The cleanup is provably safe: a *legitimately held* `proper-lockfile` lock is a **directory**, so removing only **non-directory** lock paths can never clobber a live lock.

## Decisions (all resolved)
1. **Fix location:** `launch_stage` in `perk/launch.py`, on the real launch path only (after `dry_run` has already returned), immediately before `os.chdir(wt)` / `os.execvpe(...)`.
2. **Safety predicate:** remove a lock path **iff it is not a directory** (`Path.is_dir()` is False). A directory = live lock → never touched. A regular file / symlink-to-file / other = stale artifact → removed. `unlink(missing_ok=True)` handles the absent case.
3. **Which locks:** the two agent-dir locks pi takes — `settings.json.lock` and `auth.json.lock` — under pi's **global agent dir**. Project-scope locks (`<worktree>/.pi/settings.json.lock`) are **out of scope**: launched worktrees get a fresh `.pi/` and the observed bug is global; note this deferral explicitly, do not author for it.
4. **Agent-dir resolution (mirror pi exactly):** `config.js getAgentDir()` reads env var `PI_CODING_AGENT_DIR` (= `${APP_NAME.toUpperCase()}_CODING_AGENT_DIR`, `APP_NAME="pi"`), else `homedir()/.pi/agent` (`CONFIG_DIR_NAME=".pi"`). Replicate: `os.environ["PI_CODING_AGENT_DIR"]` (expanduser) else `Path.home()/".pi"/"agent"`.
5. **Failure handling:** best-effort and **non-fatal** — a sweep failure must never block a launch. Wrap in `try/except OSError`. The error boundary is honored by the fact that *if* the stale lock survives, pi prints its own diagnostic (the status-quo warning) — that is the surfaced report. Document this rationale in the docstring so it isn't read as a silent swallow.
6. **No doctor check.** The warning is a launch-time symptom on global state; `doctor` operates on the repo root, so a doctor fix would not prevent the next-launch warning. Keep the fix solely at the launch chokepoint. (Note this as a considered-and-rejected alternative, not a deferral that needs follow-up.)

## Changes

### `perk/launch.py`
- Add module-level constant near the top-of-module helpers:
  ```python
  # pi locks its agent-dir JSON via proper-lockfile, which holds a lock as a *directory*
  # (atomic mkdir). A stale regular *file* at one of these paths makes pi's startup rmdir fail
  # with ENOTDIR and print a "(startup session lookup, global settings)" warning on every launch.
  _PI_AGENT_LOCK_FILES = ("settings.json.lock", "auth.json.lock")
  ```
- Add `_pi_agent_dir() -> Path` mirroring pi's `getAgentDir()`: return `Path(os.environ["PI_CODING_AGENT_DIR"]).expanduser()` if that env var is set and non-empty, else `Path.home() / ".pi" / "agent"`.
- Add `_sweep_stale_pi_agent_locks(agent_dir: Path) -> None`:
  - For each name in `_PI_AGENT_LOCK_FILES`, let `lock = agent_dir / name`.
  - `try: ` if `not lock.is_dir()` then `lock.unlink(missing_ok=True)`; `except OSError: pass`.
  - Docstring states: removes only non-directory lock paths (a directory is a live `proper-lockfile` lock); best-effort/non-fatal because pi will surface its own diagnostic if the stale lock survives.
- In `launch_stage`, on the real launch path (after the `if dry_run:` block returns, alongside the existing `env = {**os.environ, "PERK_RUN_ID": rid}` line, before `os.chdir(wt)`): call `_sweep_stale_pi_agent_locks(_pi_agent_dir())`.

### `tests/test_launch.py`
Add unit tests (pure, `tmp_path`-based; follow the existing `monkeypatch.setattr("perk.launch.os.execvpe", ...)` pattern already used at lines ~153/196/221/327):
1. `_sweep_stale_pi_agent_locks` removes a regular `settings.json.lock` **file** (and `auth.json.lock`).
2. It **leaves a `settings.json.lock` directory untouched** (create the dir; assert it still exists) — the live-lock safety guarantee.
3. No-op when the lock paths are absent (no exception).
4. Swallows `OSError` (e.g. monkeypatch `Path.unlink` to raise `PermissionError`; assert no propagation).
5. `_pi_agent_dir()` honors `PI_CODING_AGENT_DIR` (set via `monkeypatch.setenv`, incl. a `~`-prefixed value → expanduser) and falls back to `~/.pi/agent` when unset.
6. Integration: `launch_stage` calls the sweep before exec — monkeypatch `perk.launch._pi_agent_dir` to a `tmp_path` agent dir seeded with a stale `settings.json.lock` file, monkeypatch `os.execvpe` to a no-op recorder, run a non-dry-run `launch_stage` (reuse the `git_repo` fixture + plan-ref setup from `test_implement_materializes_worktree_and_is_idempotent`), and assert the stale file is gone and exec was reached.

## Per-turn doc (project convention)
Before implementing, create `docs/planning/phase-2-turn-15.md` (next sequential turn after `phase-2-turn-14.md`) capturing: the decision set above + the prior-art pass (pi `proper-lockfile` mechanism). After landing, fill its **outcomes** section with any deviations.

## Codebase evidence
- `perk/launch.py:303` — sole `os.execvpe("pi", ...)` chokepoint (grep confirmed only one occurrence).
- `perk/launch.py:301-303` — `env = {**os.environ, "PERK_RUN_ID": rid}` / `os.chdir(wt)` / `os.execvpe` insertion site.
- `dist/core/settings-manager.js` `acquireLockSyncWithRetry` / `withLock` (lines ~51-104) — pi's lock acquisition.
- `node_modules/proper-lockfile/lib/lockfile.js` `getLockFile` (line 11), `acquireLock` `mkdir` (line ~57), `removeLock` `rmdir` (line ~88) — directory-based locking + the failing `rmdir`.
- `dist/main.js:58-70, 423-425` — `collectSettingsDiagnostics` / `reportDiagnostics` and the `"startup session lookup"` call producing the exact warning string.
- `dist/config.js:369-391` — `ENV_AGENT_DIR = "PI_CODING_AGENT_DIR"`, `getAgentDir()` env-or-`~/.pi/agent` resolution to mirror.
- `tests/test_launch.py` — existing `os.execvpe` monkeypatch + `git_repo` fixture pattern to reuse.
- Observed artifact: `~/.pi/agent/settings.json.lock` is a 0-byte regular file dated Mar 3 (stale).

## Out of scope / deferrals
- Project-scope (`<worktree>/.pi/settings.json.lock`) sweeping — not the observed failure; flag, don't build.
- No `perk doctor` check (rejected: doesn't prevent the next-launch warning; see Decision 6).

---

**Immediate workaround** you can run right now (outside read-only mode): `rm ~/.pi/agent/settings.json.lock` — that silences it until/unless it recurs; the plan above makes the fix permanent and portable.
