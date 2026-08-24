---
title: Plan factory pattern (+ the shared seeded-cold-door pipeline)
read_when: You are building or debugging a perk plan factory (a read-only planning launcher), adding or converting a seeded cold door (seeded_door.py), or extracting/wiring an N-sibling factory family.
cluster: doors-and-launch
---

# Plan factory pattern

## Distillation

- Inbox-over-gh is a DISCIPLINE (deterministic, token-cheap, injection-bounded via untrusted
  markers), no longer structural — never resurrect the "cannot run gh" claim — "Inbox-over-gh:
  a discipline, not a structural constraint".
- A batched/on-demand factory needs no registry stage: borrow the `plan` stage descriptor +
  `prompt_override` — "Non-stage factories borrow the `plan` stage descriptor +
  `prompt_override`".
- Context delivery splits by door: a cold door that knows its subject INJECTS into the seed
  (fail-soft, seed-byte-unchanged when empty); a warm door INSTRUCTS the model to run a read
  worker — "Cold-injects / warm-instructs is a reusable factory pattern".
- N sibling factories share one core — "The parameterized factory-family pattern".
- The seeded cold doors share `seeded_door.py`'s three exports (`run_seeded_door` /
  `SeededLaunch` / `seeded_door_options`) under a byte-pin discipline; the family census is
  derived from `run_seeded_door`'s callers, never a frozen count — "The shared
  seeded-cold-door pipeline".
- A new sibling factory is a multi-surface LOCKSTEP (bindings.yaml, deliverable targets, skill
  set + manifest fragment, …) or delivery silently breaks — "Parallel-factory wiring is a
  multi-surface lockstep".

## Inbox-over-gh: a discipline, not a structural constraint

A seeded read-only plan-mode session historically **could not run `gh`/`perk` in bash** —
`extension/substrate/toolGating.ts` `SAFE_PATTERNS` allowed only
`cat`/`head`/`tail`/`grep`/`find`/`ls`/`git status|log|diff`/`jq`/`curl`.
So every cold-door factory did its GitHub reads up front and materialized the result into a
file the session reads via the `read` tool (e.g. `.perk/workflow/scratch/learn-docs-inbox.md`),
with untrusted fetched bodies wrapped in a marker (`<untrusted_learning>…</untrusted_learning>`).

Since #416 the read-only gate allowlists read-shaped `gh` *query* subcommands, so the constraint
is **no longer structural** — docs that asserted "the gate excludes gh" as the *mechanism* behind
cold-door gathering were reframed keep-and-annotate style. The inbox pattern stays **canonical**
(deterministic, token-cheap, prompt-injection-bounded via the untrusted markers) but is no longer
forced: ad-hoc read-only `gh` queries pass the gate. **Future edits must not resurrect the
"cannot run gh" claim.**

## Mirrored guidance ≠ identical text — the link carrier is plane-specific

When factory guidance exists on both planes (the warm `/objective-plan` guidance and the cold
seed prompt), mirror the *loop* but derive each plane's carrier step from its own mechanics, never
copy text across. The proven instance: the warm factory instructs an **unconditional**
`objective_node` planning mark — a `planning → planning` re-mark is valid/idempotent in the
`src/perk/objective/` package (`update_node` in `graph.py`) and re-records the
`objective_node_claim`, which is what makes
resume-into-an-existing-claim safe — while the cold seed prompt instructs **no** mark, because the
cold door already marked the node pre-launch and the link rides `handoff_extra`.

## Non-stage factories borrow the `plan` stage descriptor + `prompt_override`

A batched/on-demand factory does **not** need a `registry.yaml` stage. Reuse the existing `plan`
stage (`mode: read-only`, `worktree: none`, `cold_remote: false`) and seed via
`launch.launch_stage(stage=plan_stage, prompt_override=seed)`.

- `_initial_prompt` returns `None` for `plan`, so the override is the only seed.
- The `stage: "plan"` handoff makes the session present correctly.
- `plan` does not consume `cache.plan-ref` (no stale-ref leak into the factory session).
- `objective-plan` established this pattern; `learn-docs` reused it without touching
  `DEDICATED_STAGES` (that set only suppresses generic same-named launchers — a factory with no
  dedicated stage needs no entry there).

## Cold-injects / warm-instructs is a reusable factory pattern (#696/#702)

When a factory needs to surface context it already *knows* the subject of, the delivery shape splits
by door:

- **A cold door that already knows its subject** (the node/issue is fixed at launch) reads the
  context and **injects** it into the seed — fail-soft (`try/except → EMPTY`), dry-run-gated, and
  **seed-byte-unchanged on the empty path**.
- **A warm door cannot pre-fetch** (the model selects the subject in-session) → it **instructs the
  model to run a read worker** once it knows the subject.

The concrete instance is the human-engagement read subsystem (see `human-engagement-reads.md`),
which also carries the per-consumer injection-placement rule (inline seed vs scratch-file append
after the consumer's existing untrusted-DATA block).

## The parameterized factory-family pattern (N siblings, one core)

When a factory needs a **sibling** — a second on-demand factory that differs only in *what it
gathers and how it seeds*, not in its gather→render-inbox→launch spine — do **not** duplicate the
cold-door command. Extract a shared core parameterized by a **frozen config dataclass** exposed as
module constants, and reduce each per-command entrypoint to a thin delegator.

The proven instance is the learn factory pair. `src/perk/cli/commands/learn/factory_common.py`
holds the frozen `LearnFactoryKind` dataclass (the per-factory parameter bundle: inbox filename, seed
template, binding trigger, a `select` callable picking this kind's subset out of the
`(doc_destined, code_destined)` partition, an `include_docs_scan` gate, and a cross-hinting
`empty_message`) plus the two module constants `DOCS_FACTORY` / `CODE_FACTORY` and the shared
`run_factory`. `docs_cmd.py` / `code_cmd.py` are then thin Click delegators that pass their kind
constant into `run_factory`. This is the reusable shape for adding a third sibling: add a constant,
not a code path. The TS plane now mirrors the shape for the warm doors:
`extension/doors/learnFactory.ts` holds the `LearnFactoryDoorKind` config interface, the
`DOCS_DOOR` / `CODE_DOOR` constants, and the shared `registerLearnFactoryDoor` (no per-door
delegator files — `extension/index.ts` is the single registration site and passes the kind
constants directly).

## The shared seeded-cold-door pipeline (run_seeded_door / SeededLaunch / seeded_door_options)

A *seeded cold door* is a launcher command with one orchestration shape: **parse → resolve backend
state up front (the read-only session it launches cannot be trusted to) → materialize untrusted
DATA into a scratch/inbox file → `--dry-run`/`--json` supervisor report → `launch_stage` with a
seeded prompt**. The family census is **the set of `run_seeded_door` callers** — derive it fresh
every time: `grep -rn 'run_seeded_door(' src/perk/cli/commands/`, minus the definition in
`seeded_door.py`. No caller roster survives in this doc: a snapshot recorded here froze and
silently omitted the later-added `objective stack review` door — deleted rather than refreshed
(a caller inventory re-drifts identically). The shared seam is
`src/perk/cli/commands/seeded_door.py`.

### Three exports, one contract

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

### Policy stays in the door's `gather` closure

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
seed interpolates only the manifest path, the doc count, and the lane count (all door-derived)
and tells the session the lane ids are in the manifest.

**Gather closures that perform real I/O must convert expected failures to `UserFacingCliError`
themselves.** The seeded-door boundary catches only backend errors and `UserFacingCliError` — an
`OSError` from, say, a manifest write escapes as a traceback. Harvest wraps its manifest write as
`manifest_write_failed` (contracts §8.48); any door whose gather touches the filesystem or network
owns the same conversion.

**Door-emitted copyable callouts must be shell-quoted.** Any "copy-paste this command" seed
callout with an interpolated path goes through `shlex.join` (the audit door's
`perk-dev audit fold --bundle <dir>` callout in `packages/perk-dev/src/perk_dev/cli.py` is the
precedent) — unquoted interpolation breaks on spaces/metacharacters.

### Monkeypatch seams survive by construction

The pipeline calls `launch.launch_stage(...)` through the imported **module object**, so test stubs
patched on the defining module keep intercepting. And always-passing explicit `None` optionals is
indistinguishable from omission because the test stubs read captured kwargs via `.get(...)`.

### The byte-pin discipline scales to a whole-family convergence

When the pipeline was extracted (a 7-command convergence at the time — harvest and dream joined
later), the entire behavior-preservation proof was: **zero edits to existing test files** + pre-change
`--help` captures (to `/tmp`) diffed against post-conversion output. No helper-level duplicate
tests were added — the doors' existing suites already pin the behavior (reaffirms
`cold-door-launch.md`'s byte-exact test-pin discipline).

### Guard-enforced shared primitives

The extraction minted two shared primitives, both enforced by a source-scan guard in
`tests/test_seeded_door.py`:

- **`registry.stage_by_id()`** — the one stage lookup; a miss raises `RegistryError` (not
  `StopIteration`), so defensive registration sites catch it alongside the other structural load
  failures. The guard bans the old `next(s for s in load_registry...)` idiom.
- **The canonical `fail()` in `perk.cli.emit`** — the guard bans non-allowlisted `fail`
  definitions. (See `source-scan-guards.md` for the guard genre.)

## Parallel-factory wiring is a multi-surface lockstep

Adding a sibling factory is **not** a single-file change — a new parallel factory must touch every
surface below **in lockstep**, or delivery silently breaks (the factory exists but its skill/binding
never reaches a session):

- **`shared/bindings.yaml`** — the binding entry mapping the factory's `command:<name>` trigger to
  its skill.
- **`bindings.py`'s deliverable-command-targets** — the set that treats the factory's command as a
  deliverable binding target.
- **`init/skills.py`'s skill set** (+ the matching `.agents/manifest.d/perk.yaml` fragment) — so the
  factory's skill is installed by `perk init`.
- **The `learn` verb group** — register the new command under its noun group.
- **The warm door + `extension/index.ts` registration** — the in-session door and its wiring.
- **`prompts/_fixtures/live.yaml`** — the render fixture the prompt-parity tests read.
- **The default-bindings assertions in BOTH planes** — `tests/test_bindings.py` (Python) **and**
  `extension/substrate/bindings.test.ts` (TS). Both must assert the new default binding, or one
  plane's contract drifts silently.

Missing any one of these leaves the factory half-wired — the command runs but its skill/context is
never delivered.

## Anti-pattern: the scope-expansion requirement-loss trap

When you decompose one requirement into components (one factory → two), verify that **every**
original capability survives *somewhere* — not just the common-case happy path. The concrete miss:
splitting `/learn-docs` into a docs factory + a code factory nearly dropped `/learn-docs`'s
`SHOULD_BE_CODE` **verifier** role, by treating the gather-time `partition_by_destination` split as
the *only* route to code. It is the **default route, not a verdict**: the docs factory still applies
the knowledge-placement hierarchy and emits a `SHOULD_BE_CODE` follow-up step when a doc-stamped
learning actually belongs in code (and the code factory likewise still verifies placement). Both
factories verify placement; the partition just pre-routes the common, pre-classified case. General
rule: a decomposition is only complete when each original capability maps onto a component — audit
for the capability that quietly had no home.

## On-land bookkeeping

When a learn-docs plan lands, consumed `perk:learn` issues are closed and labelled
`perk:consolidated`. This is handled by `_consume_learn_on_land` in the Python plane, which mirrors
the fail-open `_reconcile_objective_on_land` shape — see `docs/learned/workflow/plan-ref-lifecycle.md`
for the canonical fail-open pattern.

## Cross-references

- `src/perk/cli/commands/learn/factory_common.py` — the `LearnFactoryKind` frozen config dataclass, the `DOCS_FACTORY` / `CODE_FACTORY` constants, and the shared `run_factory` core (thin delegators in `docs_cmd.py` / `code_cmd.py`)
- `src/perk/cli/commands/seeded_door.py` — the pipeline (`run_seeded_door`, `SeededLaunch`, `seeded_door_options`)
- `tests/test_seeded_door.py` — the pipeline suite + the source-scan guard
- `docs/learned/workflow/cold-door-launch.md` — the launch seam the pipeline's tail composes
- `docs/learned/workflow/source-scan-guards.md` — the guard pattern enforcing the shared primitives
- `docs/learned/workflow/plan-ref-lifecycle.md` — fail-open on-land bookkeeping pattern
- `docs/learned/pi/context-system.md` — the bash allowlist (incl. the read-only `gh` query subcommands)
- `docs/learned/workflow/human-engagement-reads.md` — the concrete cold-injects/warm-instructs instance
