---
title: Python CLI command groups — the §8.1 group-dir template, hybrid stage/group coexistence, sectioned help
read_when: You are adding or folding a `perk` CLI command group, a shell-emitting verb (copyable hints, emitted scripts), the sectioned root `--help` taxonomy, a pass-through noun-group, or a CLI refactor.
cluster: doors-and-launch
---

# CLI command groups

The `perk` CLI is group directories under `perk/cli/commands/` behind a sectioned root help.
`docs/design/first-principles/python-cli-guidelines.md` owns the *what* (§8.1 the layout tree,
§11 the decided taxonomy); this doc is the structural *how-to*: four playbooks plus migration
gotchas. Rosters are derived from source, never listed here: groups = the `__init__.py`-bearing
dirs under `commands/`; root taxonomy = `COMMAND_GROUPS` / `STAGE_LAUNCHERS` / `SETUP_HEALTH`
(`perk/cli/alias.py`); dedicated stages = `DEDICATED_STAGES` (`perk/cli/stages.py`).

## Distillation

- Group-dir template: `__init__.py` (docstring + group + bottom registrations), standalone
  `{verb}_{noun}` verb files, cross-verb helpers in `{group}/shared.py`, the envelope helpers
  once in `perk/cli/emit.py`; every new root command touches the same lockstep surfaces —
  "Playbook 1 — the group-dir template".
- A stage name colliding with a group name is the hybrid default-dispatch recipe; a launcher
  with a deterministic worker is a `MergedCommand` (`--json` routes to the worker, argv
  preserved, option schemas never unioned) — "Playbook 2 — hybrid default-dispatch groups and
  `MergedCommand`".
- Root help is a fixed taxonomy (`SectionedGroup`); CLI-structure tests are structural and
  registry-keyed, never raw help text; `CliRunner` has stdin and stream pitfalls — "Playbook 3 —
  sectioned help and structural tests".
- Emitted shell source is a program: quote, guard, confine, and source it in a real shell in
  the test; exec verbs build one argv for preview and exec — "Playbook 4 — shell-emitting and
  exec verbs".
- Boundary: `perk skills` registration facts live here; its write-capable doors' behaviour is
  `write-capable-cold-doors.md`'s.

## Playbook 1 — the group-dir template

- `commands/{group}/__init__.py` carries the design docstring, the group object (`AliasGroup`,
  or `SectionedAliasGroup` when launchers and workers share a group), top-of-file verb imports,
  and one registration per verb at the bottom — `register_with_aliases(group, verb)` (plain
  `add_command` when the verb declares no alias; `mark_kind(cmd, "launcher" | "worker")` wraps
  each verb of a sectioned group). Nested groups nest dirs (`workflow/run/`).
- Verb files are standalone `@click.command("name")` defs named `{verb}_{noun}` (never
  `@group.command`) with a one-line docstring naming the command. Verb-local helpers move with
  the verb and keep their `_` prefix; cross-verb helpers go in `{group}/shared.py` and drop it
  (intra-package API, e.g. `parse_objective_id`).
- The result envelope lives ONCE in `perk/cli/emit.py` (`fail` / `emit` / `EXIT_FOR_TYPE`), a
  neutral `cli/`-level leaf every group and `perk_dev` import, so no group needs another group's
  `shared.py` for it. A cross-group `shared.py` import is an exception to justify, not a
  pattern — census it with a grep for `from perk.cli.commands.<other>.shared import`.
- Supervisor-surface contract for every verb: `--json` payload → stdout, human text → stderr,
  exits `0` ok · `1` invalid/op-failure · `2` `not_a_repo` (`EXIT_FOR_TYPE`). Detect/repair
  workers split exits on report-vs-abort: a *completed* detection is a clean `0` even when it
  reports ERROR-severity findings; an aborted repair is `1`
  (`perk/cli/commands/objective/doctor_cmd.py`'s docstring is the shape).
- Helper-induced import cycles dissolve into a sibling leaf module
  (`perk/cli/commands/doctor/render.py`) so both `__init__.py`s import top-of-file;
  bottom-of-file imports are only for registration-induced cycles (`init-doctor.md` § "Click
  bottom-of-file imports").
- Folds keep JSON shapes, `error_type`s and exit codes byte-identical: `fail(..., extra=)`
  merges `extra` AFTER the base keys (dry-run-capable verbs pass `extra={"dry_run": False}` on
  every failure path). Before consolidating N near-identical private helpers, re-grep all N
  bodies — plans have mis-stated "the only divergence" before.

### Every new root command touches the same lockstep surfaces

Registration in `perk/cli/cli.py` (or the group's `__init__.py`); a root section (a group →
`COMMAND_GROUPS`; an unlisted root command falls into `Other` automatically); the structural
fingerprint `EXPECTED_SURFACE` in `tests/test_cli_parity_smoke.py` (sorted — a verb row goes in
TRUE alphabetical order whatever a plan says); the help-slice assertion in
`tests/test_cli_help_sections.py`; and the user-docs reference family:
`tests/test_user_docs_cli_reference.py` guards documented ↔ exists both ways over the
`docs/user-docs/reference/cli.md` hub (+ its marked command map) and the `cli/*.md` children —
assign the command to exactly one `FAMILY_MAP` page, document it there, add a hub-map row
(existence and placement are pinned; wording is not). A flat informational command
(`release-notes`) is one `commands/{name}_cmd.py` + `cli.add_command` — no alias, group or
registry stage — riding the same surfaces.

### The pass-through noun-group (`perk skills`)

- Pass-through-first: every verb forwards to the substrate binary EXCEPT the ones upstream
  lacks; derive that set from the group's `__init__.py` docstring, never from here. The
  forwarding runner inherits stdio (no capture) and propagates the upstream exit code verbatim;
  a reimplemented verb whose rollback needs stderr captures instead (`run_captured`). The perk
  manifest fragment's `sources` keys are the "is this perk-managed" check.
- N symmetric rollback arms = test ALL N (structural-coverage reviewers count arms) — `remove`'s
  `skills sync` restores the original manifest bytes on each of its failure arms.
- A new `subprocess.run` site fails
  `tests/test_tooling.py::test_subprocess_run_only_in_sanctioned_wrappers_with_check_and_timeout`
  until it joins `_SANCTIONED_SUBPROCESS_WRAPPERS` (keyed `(file_stem, func_name)`) with explicit
  `check=` / `timeout=`.
- The envelope is shared, not mirrored: aligning the group's private failure helper onto
  `emit.py` moved `not_a_repo` from exit 1 to the CLI-wide 2 — expect such deltas when
  consolidating.
- Boundary: `create` / `refine` (the write-capable doors), `scaffold` / `delete`, main-checkout
  resolution and the dogfood-gate test belong to `write-capable-cold-doors.md`.

## Playbook 2 — hybrid default-dispatch groups and `MergedCommand`

A stage launcher and a command group wanting the same name (`perk learn`, `perk plan`) coexist
through a default-dispatch group. Derive the current roster from the `resolve_command`
overrides under `perk/cli/commands/` (`LearnGroup` is the template; a shared base class is a
deliberate deferral):

- Group `context_settings={"ignore_unknown_options": True}` so launcher options survive
  group-level parsing and reach `resolve_command` intact.
- `parse_args`: empty args → substitute the hidden launcher name (guard `ctx.resilient_parsing`
  for completion, and only when the launcher registered) — bare `perk learn` launches.
- `resolve_command`: a registered verb (or `--help` / `-h`) defers to `super()`; anything else
  routes to the launcher with ALL args preserved — Click's default strips `args[0]`; don't.
- A leading `--help` is an eager option consumed by the group's own parse, so group help renders
  before `resolve_command` runs; the override lists it beside the verbs only as a guard.
- The hidden launcher is `make_stage_launcher(stage)` (`perk/cli/stages.py`) added with
  `hidden = True`, and the stage joins `DEDICATED_STAGES` so `register_stage_commands` skips it.
  Edge: pi-args whose first token is a verb name route to the verb.

**`MergedCommand`** (`perk/cli/stages.py`, built by `make_merged_command(stage, worker)`) fronts
two intact halves — `make_stage_launcher(stage)` and an existing worker `Command` — dispatching
on the literal `--json` token anywhere in argv and handing the FULL argv to the chosen half;
neither half's options are unioned. Its own help fires only when `--help` / `-h` is present AND
`--json` absent (`--json --help` renders the worker's help). Accepted edge: `--json` cannot pass
through to pi via the merged command — use the explicit launcher. Prove the factory by one
unregistered construction over a real stage + worker, then the registered routing end-to-end
(launcher default vs `--json` → worker; `tests/test_cli_stages.py`).

- **Retiring a generated flat launcher takes two edits:** the stage id into `DEDICATED_STAGES`
  (stops generation) AND out of the curated `STAGE_LAUNCHERS` (`perk/cli/alias.py`; the drift
  guard's "no stale entries" arm). A flat alias keeps the row rendering, so step 2 is honesty.
- **Build defensively at import time:** wrap the registry read in `try/except (RegistryError,
  FileNotFoundError, KeyError)`; the fallback keeps the group's `--help` and the warm
  `perk <group> <verb> --json` doors working and loses only the bare-launch half (`pr` registers
  the bare workers; `plan` / `learn` skip the launcher).
- **L vs L+W vs W is a registry fact, not an author-time annotation.** A command has a launcher
  half only if its id is a `shared/registry.yaml` stage — verify there, never in an objective's
  target tree. Launcher-only (`pr address`): a dedicated command with the launcher option set
  (`PlanLauncherCommand`, `perk/cli/launcher_grammar.py`, for a positional PLAN;
  `seeded_door_options` for seeded doors — `plan-factories.md`). Worker-only: `pr ready` —
  `ready` is not a stage, so never mint one; the flat `perk ready` is a distinct continuation
  wrapper (contracts.md §8.66) that borrows `objective-save` to launch.
- **Pure relocation ≠ merge.** A fold with no worker to merge (`objective`) is `git mv` +
  `cls=SectionedAliasGroup` + `mark_kind` wraps + dropped flat registrations — no
  `MergedCommand`, no flat alias; bare `perk objective` stays group help. Don't reach for the
  factory by reflex.
- **Per-object marker state, never module globals:** aliases (`ALIAS_ATTR`) and kinds
  (`KIND_ATTR`) ride the command object; flat-alias bookkeeping (`FLAT_ALIAS_ATTR`,
  `register_flat_alias`) rides the root group. `SectionedGroup.format_commands` routes flat
  aliases into the launcher bucket BEFORE consulting `STAGE_LAUNCHERS`, so swapping a generated
  launcher for a merged/flat one leaves the rendered rows unchanged.
- The registry `command:` field is informational (`_check_shapes` requires non-empty; launchers
  key off `stage.id`) — keep it current, but nothing dispatches on it.
- **The ROOT-level bare launch is not the hybrid.** Bare `perk` is `invoke_without_command=True` +
  a `ctx.invoked_subcommand is None` callback arm (`perk/cli/cli.py`): Click 8.4.1 sets
  `no_args_is_help = not invoke_without_command`; `--help`/`--version` stay eager; an unknown token
  still fails in `resolve_command`; a lone `perk --` is the bare invocation. Reserve the
  `parse_args`/`resolve_command` hybrid for a noun that is both a group and a canonical stage. The
  root form adds no command, so a zero diff on `EXPECTED_SURFACE`, help and user docs IS the proof;
  deferred one-unit registration lives in `cli-startup-tiers.md`.

### The warm plane is decoupled from cold spellings

Slash commands, `command:<id>` triggers, deliverable targets and inbox paths survive a cold
rename; only `pi.exec` / `runColdDoor` argv arrays in the extension change, and the warm↔cold
contract is `<group> <verb> --json` (which `MergedCommand` satisfies). Before implementing an
"update the warm argv" clause, verify it is stale — it is often a no-op. When a leading argv
token does change, grep ALL `extension/**/*.test.ts` for the literal token (the approval→save
path in `extension/pi/v1/planReview.test.ts` pinned it, not only the save suite) and prefer
`argv.slice(0, 2)` deepEqual pins over a bare `argv[0]`.

## Playbook 3 — sectioned help and structural tests

- `SectionedGroup(AliasGroup)` (`perk/cli/alias.py`) is root-only (Stage Launchers / Command
  Groups / Setup & Health / Other / Hidden); `SectionedAliasGroup(AliasGroup)` sections a
  subgroup into Launchers / Workers / Commands via `mark_kind` (unmarked verbs fall into
  Commands, so an unmarked group renders like a bare `AliasGroup`). They are SIBLINGS off
  `AliasGroup`, not parent/child — `test_root_and_subgroups_use_alias_group` asserts subgroups
  are `AliasGroup` but not `SectionedGroup`, and stays green for a sectioned subgroup.
- `Hidden` renders only when `PERK_SHOW_HIDDEN` is truthy (`not in (None, "", "0")`); empty
  sections are omitted.
- Only commands built by `make_stage_launcher` carry the generated "Opens a primed pi session…"
  long-help paragraph; dedicated launchers add it by hand. The section header, not the factory,
  disambiguates launchers from same-named workers.
- Click's two-paragraph help is a free short/long split: `summary\n\nlong sentence` enriches
  `--help` while listing rows keep the first paragraph (`get_short_help_str`). Lock it by
  asserting the listing row lacks the sentence and the command's `--help` contains it.
- **Structural fingerprint, never raw help text.** `EXPECTED_SURFACE` is a literal dict (verb
  sets + sorted alias tuples + each root command's bucket) — terminal-width-stable, and the diff
  IS the review surface. It also proves dormancy: a capability-before-enactment change ships
  mechanism + tests with the fingerprint unchanged.
- **Drift guard** (`test_section_lists_drift_guard`): curated lists resolve to live commands,
  are pairwise disjoint, and union with `Other` to the visible set.
- **Help-slice tests match the rendered row** (`"objective (obj)"`), never a bare substring —
  `objective-*` names false-positive it.
- **Registry-keyed census** for data-derived help
  (`test_remote_help_census_states_cold_remote_scope`): derive the expected set from
  `load_registry()` and assert BOTH arms; enumerate every surface the generic help reaches,
  hidden ones included (`<group> launch --help`); a statically worded help that names a
  data-derived set gets its own registry pin. **Click wraps option help** — normalize with
  `" ".join(result.output.split())` before substring assertions.
- **`CliRunner` keeps three streams** (Click ≥ 8.2): `result.stdout`, `result.stderr`, and
  `result.output` (both, interleaved). Assert the stream the contract names — a `result.output`
  hit proves nothing about which stream carried the text.
- **`CliRunner` replaces `sys.stdin`** with a non-tty stream for the call, so an `isatty()` fork
  cannot be tested by patching `sys.stdin.isatty`; swap the command module's `sys` for
  `SimpleNamespace(stdin=SimpleNamespace(isatty=lambda: …))` (`tests/test_skills_cmd.py`).
- **`launch_exec_recorder` defeats `CliRunner.isolated_filesystem()`** — the fixture
  (`tests/conftest.py`) stubs the process-global `os.chdir`, so the isolated cwd is never entered;
  omit the recorder for isolated-filesystem cases or establish the isolated cwd before installing
  the stub.
- **Merged-command worker tests invoke the worker object directly** with an explicit
  `obj=PerkContext(...)` (the root callback's lazy default doesn't run) — through `cli` the
  worker is reachable only under `--json`.
- **Behavior-parity smoke** for structural refactors: dump `--help` for the root and every
  (sub)group in worktree and main, then diff — identical help ⇒ identical surface. Drive tests
  through the `cli` object unless unit-testing a helper; test files keep flat names across
  folds — only invocations and monkeypatch import paths change (grep the BARE module name when
  renaming).

## Playbook 4 — shell-emitting and exec verbs

Emitted shell source is a PROGRAM, not display text (`perk worktree checkout --script`,
`perk/cli/commands/worktree/checkout_cmd.py`):

- Quote every user-controlled argument in copyable hints (`shlex.quote`) so `#7` is not a
  comment and spaced names survive as one token.
- Guard state-changing commands — `cd … || return 1` — so a vanished target cannot echo success
  and return 0 from a sourced script; a resolution failure emits a valid `return 1` stub because
  `source <(cmd)` cannot see `cmd`'s exit code.
- Confine name-based resolution before emitting navigation (no separators, no `.` / `..`; a bare
  `Path` join adopts absolute inputs wholesale) and resolve directories only (`is_dir()`).
- Test by sourcing in a real shell (`bash -c "source … && …"`,
  `tests/test_worktree_checkout.py`): PWD changes through an apostrophe path, both failure modes
  return non-zero and break `&&`. Substring assertions on script text prove none of this.

**The external-TUI exec verb** (kind X in `python-cli-guidelines.md` §11.6; `perk plan watch`,
`perk/cli/commands/plan/watch_cmd.py`) execs a foreign TUI, not pi: `ignore_unknown_options` +
variadic `UNPROCESSED` args with a decided grammar (perk owns the flags before the first bare
`--`, Click consumes it, a second `--` reaches the child); ONE argv construction shared by
`--dry-run` and exec, printed via `shlex.join`; `chdir` + `exec` with the child's exit status
inherited, a failed `chdir` / `exec` being an ordinary `OSError` arm. Its tests use seam fakes
that record the RESOLVED repo argument plus an ops-order log (macOS `/tmp` symlinks skew raw
comparisons) and apply `monkeypatch.chdir(tmp)` BEFORE stubbing `os.chdir` (LIFO teardown).

**Typed Click options break the `--json` refusal contract.** Click converts typed options BEFORE
the callback, so `type=int`/`type=float` produce Click's exit-2 usage error, violating "every
refusal is typed under `--json`" — declare scalars as strings and parse inside the command
(`startup-profiling.md` § "`--json` verb craft the harness surfaced").

Selector parsing gates digit conversion on `value.isascii() and value.isdigit()`
(`perk/cli/plan_selection.py::_is_ascii_digits`) — neither `str.isdigit` nor `int()` alone is
that predicate. Vocabularies whose values reach unquoted argv or injected guidance require an
alphanumeric first character — owner: `mergeability-and-conflict-resolution.md` § "Warm-route
hints on cold refusals".

## Mechanical-migration gotchas

- `git mv` first, edit second — rename detection and blame survive a group-dir migration.
- Bash `case` patterns with spaces must be quoted (`"pr submit")`); `fakePerkRouter`
  (`extension/testing/harness.ts`) takes two-token route keys, so a regroup only updates route
  keys in tests.
- Parallel CLI nodes conflict on a predictable set — `DEDICATED_STAGES` and `perk/cli/cli.py`'s
  registration block; resolve as a UNION of both sides, re-verify the merged `EXPECTED_SURFACE`
  by eye, run the CI gate. Rebase blockers: `package-lock.json` churn
  (`toolchain/worktree-node-modules.md`), the pre-commit format hook on the first commit
  (`toolchain/ruff.md`).
- **Reusing a retired/folded root name with a different meaning trips the "old spellings are gone"
  pins** (`tests/test_cli_stages.py`) — rewrite the pin to assert the new command is not an alias
  of the old one: its help exits 0, mentions the new behaviour, and lacks the retired stage's help
  marker (the flat `resume` session picker vs the retired stage-resume verb).

## Residuals (dated)

- History: the taxonomy folds landed 2026-06 (`python-cli-guidelines.md` §11.5 / §11.7 record
  the removal list and corrections); the prose-pinned user-docs guard deleted then was
  re-created 2026-08-15 as the structural family guard in Playbook 1.
- Cosmetic: `perk learn docs`' dry-run label still prints the pre-fold `learn-docs` spelling
  (`perk/cli/commands/learn/factory_common.py`).

## Cross-references

- `docs/design/first-principles/python-cli-guidelines.md` — §8.1 layout tree, §11 taxonomy SSOT
- `docs/learned/workflow/write-capable-cold-doors.md` — the `perk skills` doors' behaviour
