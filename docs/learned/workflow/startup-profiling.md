---
title: Startup profiling — the PTY launch harness, Pi benchmark facts, the Node module census, and measurement discipline
read_when: You are measuring perk or Pi startup, touching perk-dev profile-startup, the PERK_PROFILE_HANDOFF seam, spawn_pty, the --import module tracer, or comparing against the committed baseline.
cluster: doors-and-launch
---

# Startup profiling

The how-to is `docs/developers/profiling-startup.md`; `shared/contracts.md` §8.72(i) owns the
`PERK_PROFILE_HANDOFF` seam — this doc records the facts and craft behind the instrument
(`perk-dev profile-startup`). Pi facts carry event stamps; measurements are re-measured, never
copied.

## Driving a real `perk`→Pi launch under a pseudo-terminal

`packages/perk-dev/src/perk_dev/profile_startup/pty_session.py`:

- Pi's `resolveAppMode` needs only stdin/stdout TTYs, so stderr can be a plain pipe — `PI_TIMING`'s
  report arrives clean, separated from TUI bytes.
- The child must be a real controlling terminal: `start_new_session` + `TIOCSCTTY` in the pre-exec
  hook, `TIOCSWINSZ` before the spawn.
- Sweep the owned process group even after a natural leader exit (`killpg` after reaping): a
  SIGHUP-ignoring grandchild survives the leader — a falsifiable fixture proves it.
- Only `errno.EIO` on the PTY master is EOF (macOS returns 0 bytes); any other `OSError` is a
  harness defect and re-raises.
- A node:test child-process smoke needs bounded waits and kill-and-await in `finally`.

## Pi benchmark-mode facts (Pi 0.87.0 — event stamp)

- `PI_STARTUP_BENCHMARK=1` runs `interactiveMode.init()`, settles 150 ms, prints timings and exits
  (interactive-only); `PI_TIMING` is compared to the literal `"1"`.
- `resetTimings()` at `main()` entry means Pi's totals EXCLUDE Python + Node boot; the `extensions`
  namespace is reset separately.
- The harness `elapsed_ms` is stamped before `Popen` — describe the remainder as "everything outside
  Pi's own `main` timing", never a measured phase.
- Pi persists no session file for a benchmark session.

## Trust preflight

perk's worktree launches pass `--approve`, which writes NO `trust.json` entry — a subject checkout
must have had `pi` run there once (or `defaultProjectTrust: always`), or the benchmark blocks on the
trust prompt and reads as a timeout. The harness mirrors Pi's `ProjectTrustStore` (nearest-ancestor
boolean wins; a malformed store is refused). A hand-made detached worktree also has an empty
`.pi/npm` — stage it with `materialize_extensions` (`toolchain/worktree-node-modules.md`).

## Env hygiene

Scrub `NODE_OPTIONS`, `PERK_RUN_ID` and the harness's own env from every sample and record what was
removed — inherited Node flags change timings and the module graph without appearing in
provenance. The census arm composes `NODE_OPTIONS` from an empty base.

## The Node module census via `--import` + `node:module.registerHooks`

`module_tracer.mjs`:

- A `resolve` hook sees ESM and CJS alike. Buffer in memory and flush on `exit` (no per-resolve I/O
  under `--cpu-prof`).
- Turn SIGTERM into `process.exit(0)` so a harness-terminated process still runs exit handlers and
  Node writes the `.cpuprofile` — the SIGTERM→SIGKILL grace is the write window.
- Match the main Pi process by `argv[1]` realpath against the `pi` bin realpath: children inherit
  `NODE_OPTIONS` and write their own files.
- What jiti evaluates itself (perk's TS extension) does not appear — document it, not a defect.

Attribution: `by_package` keeps no importer edge, but every raw `census-<pid>.jsonl` resolve record
carries `parent` (the importing module URL) — attribute "who loaded X" from the raw trace rather
than declaring it unknowable. `census.py`'s `SDK_PACKAGE_NAMES` is a reporting filter, not the
bridge's `NATIVE_SDK_CENSUS` authority (`pi/native-sdk-bridge.md`).

## Measurement discipline

- Filesystem cache dominates (36 s cold vs ~4 s warmed; a concurrent test suite inflated a trial
  6×): report medians with ranges, alternate subjects sample-by-sample, keep the warm-up apart,
  compare only same-condition runs.
- `-X importtime` cumulative rows are nested: a thin importer frame outranks its heavy child by
  exactly the wrapper's own children, so a pre-decided lever rule ("pursue iff X is the largest
  `perk.*` subtree") must say whether wrapper frames count as distinct subtrees — write such rules
  over distinct roots, self-time, or a named exclusion (`planning-time-facts-decay.md`).

## `--json` verb craft the harness surfaced

Each generalizes to every `perk`/`perk-dev` `--json` verb:

- Click converts typed options before the callback — declare scalars as strings and parse inside,
  so lexical errors reach the typed `bad_arguments` refusal (`cli-command-groups.md`).
- The `io_error` boundary must cover output *preparation* (`resolve`/`iterdir`/`mkdir` on
  `--output`), tested with a real filesystem.
- Label uniqueness is `casefold`ed when labels become directory names (case-insensitive
  filesystems).
- "Failed arms are recorded, never raised" needs an exception boundary at the spawn, not only
  around the run.
- A machine-contract field name must mean what the how-to says (`output_present` = the artifact
  exists AND is usable).

## The committed baseline

`docs/design/archive/perk-startup-baseline.md` at its stamped commit — re-measure, never copy. A
record embedding the renderer's verbatim `summary.md` couples the record to renderer *wording*, so
re-measure after review settles and commit the record last (`binding-design-records.md`). Guard
ripples such a tool trips: `tests/test_write_guard.py`'s `write_text` allowlist for a new
`src/perk/` writer, and `tests/test_docs_gates.py`'s exact-string pin on the root `package.json`
`lint` script (`source-scan-guards.md`).

## Residual risks (dated, at landing)

- Real-PTY tests run in the fast pytest tier with sub-second timeouts (load-sensitive).
- `perk-dev` imports `PROFILE_HANDOFF_ENV` from `perk.run.pi_exec` — a cross-package coupling the
  guard tests do not see.
- `PERK_PROFILE_HANDOFF` is a maintainer instrument (like `PERK_CLI_VERSION`), documented only in
  the how-to and §8.72.

## Cross-references

- `packages/perk-dev/src/perk_dev/profile_startup/` (`pty_session.py`, `census.py`, `handoff.py`,
  `module_tracer.mjs`), `perk/run/pi_exec.py`
- `docs/developers/profiling-startup.md` — the operator how-to
- `docs/learned/workflow/cli-startup-tiers.md` — the tier structure the harness measures
- `docs/learned/pi/native-sdk-bridge.md` — the second SDK graph the census exposed
- `docs/learned/toolchain/worktree-node-modules.md` — staging `.pi/npm` in a hand-made worktree
