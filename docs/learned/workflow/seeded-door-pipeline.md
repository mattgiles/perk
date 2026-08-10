---
title: The shared seeded-cold-door pipeline (run_seeded_door / SeededLaunch / seeded_door_options)
read_when: You are adding or converting a seeded cold door (a launcher that materializes untrusted data into scratch and execs pi with a seeded prompt), or touching `perk/cli/commands/seeded_door.py`.
---

# The shared seeded-cold-door pipeline

A *seeded cold door* is a launcher command with one orchestration shape: **parse → resolve backend
state up front (the read-only session it launches cannot be trusted to) → materialize untrusted
DATA into a scratch/inbox file → `--dry-run`/`--json` supervisor report → `launch_stage` with a
seeded prompt**. Eight doors share it: `plan from`/`replan`, `objective plan`/`replan`/
`author --from`, the two learn factories (`learn docs`/`code`), and `perk learn harvest`. The
shared seam is `src/perk/cli/commands/seeded_door.py`; the doors delegate from
`plan/from_cmd.py`, `plan/replan_cmd.py`, `objective/author_cmd.py`, `objective/plan_cmd.py`,
`objective/replan_cmd.py`, `learn/factory_common.py`, and `learn/harvest_cmd.py`.

## Three exports, one contract

- **`run_seeded_door()`** — the spine: the exception boundary (backend errors → `github_error`,
  `UserFacingCliError` → its `error_type`, both through the canonical `fail()`), then the dry-run
  report, then `launch_stage` with the seeded prompt.
- **`SeededLaunch`** — a frozen dataclass, the contract between a door's policy and the shared
  tail: the seed, the launch note, the dry-run label/fields/payload, `dry_run_shows_seed`
  (`objective plan` and the learn factories' `--gather` suppress the seed section), and the
  handoff extras (`handoff_extra`, `binding_trigger`, `run_id_override`).
- **`seeded_door_options()`** — a *parameterized* decorator factory for the shared trailing option
  block (`--worktree/--dry-run/--remote/--json/--no-sync` + the `pi_args` argument): three
  help phrases vary across the family, plus an optional `no_sync_help` override. It applies the
  decorators in **reversed** list order so Click's `__click_params__` reversal renders `--help`
  byte-identically to hand-stacked decorators.

**`seeded_door_options` is parameterizable per-door, not forkable.** When `perk learn harvest`
needed `--no-sync` to describe its *own* pre-gather boundary (harvest syncs the invocation
checkout before gathering, inside its closure — not the generic pre-launch sync), the shared
decorator gained the `no_sync_help` override rather than being forked, with the help text
test-pinned (`tests/test_learn_harvest_cmd.py`). The same door's sync-ordering contract pins
three seams in order — `sync → head → gather` — because a `commit_sha` captured pre-sync would
name the wrong revision.

## Policy stays in the door's `gather` closure

The pipeline owns only the shared shape. Everything per-command lives in the door's `gather`
closure: `require_github` placement, id parsing, `launch.resolve_target` ordering, backend/store
resolution, banner gating (e.g. learn's `not gather_only`), the `io_step` narration blocks,
validation raises, fail-soft engagement reads, scratch writes, seed rendering, and each door's
`--json` payload keys/order (`SeededLaunch.dry_run_payload` is the FULL payload — the door owns its
keys and their order). **Resisting the urge to normalize per-door payload differences is what made
byte-preservation possible.**

**The seed-interpolation rule.** Door-derived values (run-scoped paths, counts) may interpolate
into the seed prompt; **repository-derived strings must ride the materialized artifact** (the
manifest), where the session reads them as DATA. Interpolating a repo-derived name — e.g. a lane
id built from a directory name — into instruction text is a prompt-injection surface. The harvest
seed interpolates only the manifest path and the doc count and tells the session the lane id "is
in the manifest".

**Gather closures that perform real I/O must convert expected failures to `UserFacingCliError`
themselves.** The seeded-door boundary catches only backend errors and `UserFacingCliError` — an
`OSError` from, say, a manifest write escapes as a traceback. Harvest wraps its manifest write as
`manifest_write_failed` (contracts §8.48); any door whose gather touches the filesystem or network
owns the same conversion.

**Door-emitted copyable callouts must be shell-quoted.** Any "copy-paste this command" seed
callout with an interpolated path goes through `shlex.join` (the audit door's
`perk-dev audit fold --bundle <dir>` callout in `packages/perk-dev/src/perk_dev/cli.py` is the
precedent) — unquoted interpolation breaks on spaces/metacharacters.

## Monkeypatch seams survive by construction

The pipeline calls `launch.launch_stage(...)` through the imported **module object**, so test stubs
patched on the defining module keep intercepting. And always-passing explicit `None` optionals is
indistinguishable from omission because the test stubs read captured kwargs via `.get(...)`.

## The byte-pin discipline scales to a whole-family convergence

When the pipeline was extracted (a 7-command convergence at the time — harvest joined later), the
entire behavior-preservation proof was: **zero edits to existing test files** + pre-change
`--help` captures (to `/tmp`) diffed against post-conversion output. No helper-level duplicate
tests were added — the doors' existing suites already pin the behavior (reaffirms
`cold-door-launch.md`'s byte-exact test-pin discipline).

## Guard-enforced shared primitives

The extraction minted two shared primitives, both enforced by a source-scan guard in
`tests/test_seeded_door.py`:

- **`registry.stage_by_id()`** — the one stage lookup; a miss raises `RegistryError` (not
  `StopIteration`), so defensive registration sites catch it alongside the other structural load
  failures. The guard bans the old `next(s for s in load_registry...)` idiom.
- **The canonical `fail()` in `perk.cli.emit`** — the guard bans non-allowlisted `fail`
  definitions. (See `source-scan-guards.md` for the guard genre.)

## Cross-references

- `perk/cli/commands/seeded_door.py` — the pipeline (`run_seeded_door`, `SeededLaunch`, `seeded_door_options`)
- `tests/test_seeded_door.py` — the pipeline suite + the source-scan guard
- `docs/learned/workflow/plan-factories.md` — the N-sibling factory family this generalizes beyond
- `docs/learned/workflow/cold-door-launch.md` — the launch seam the pipeline's tail composes
- `docs/learned/workflow/source-scan-guards.md` — the guard pattern enforcing the shared primitives
