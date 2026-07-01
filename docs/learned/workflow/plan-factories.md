---
title: Plan factory pattern
read_when: You are building or debugging a perk plan factory (learn-docs, objective-plan, or any new on-demand factory that launches a read-only planning session), extracting an N-sibling factory family from one factory (a shared core parameterized by a frozen config dataclass + thin delegators), wiring a new parallel-factory sibling across its multi-surface lockstep, or decomposing one requirement into components without dropping an original capability (the scope-expansion requirement-loss trap).
---

# Plan factory pattern

## Inbox-over-gh: a discipline, not a structural constraint

A seeded read-only plan-mode session historically **could not run `gh`/`perk` in bash** —
`extension/substrate/toolGating.ts` `SAFE_PATTERNS` allowed only
`cat`/`head`/`tail`/`grep`/`find`/`ls`/`git status|log|diff`/`jq`/`curl`.
So every cold-door factory did its GitHub reads up front and materialized the result into a
file the session reads via the `read` tool (e.g. `.pi/workflow/scratch/learn-docs-inbox.md`),
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
`objective_node` planning mark — a `planning → planning` re-mark is valid/idempotent in
`perk/objective.py` and re-records the `objective_node_claim`, which is what makes
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

The proven instance is the learn factory pair. `perk/cli/commands/learn/factory_common.py` holds
the frozen `LearnFactoryKind` dataclass (the per-factory parameter bundle: inbox filename, seed
template, binding trigger, a `select` callable picking this kind's subset out of the
`(doc_destined, code_destined)` partition, an `include_docs_scan` gate, and a cross-hinting
`empty_message`) plus the two module constants `DOCS_FACTORY` / `CODE_FACTORY` and the shared
`run_factory`. `docs_cmd.py` / `code_cmd.py` are then thin Click delegators that pass their kind
constant into `run_factory`. This is the reusable shape for adding a third sibling: add a constant,
not a code path.

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

- `perk/cli/commands/learn/factory_common.py` — the `LearnFactoryKind` frozen config dataclass, the `DOCS_FACTORY` / `CODE_FACTORY` constants, and the shared `run_factory` core (thin delegators in `docs_cmd.py` / `code_cmd.py`)
- `docs/learned/workflow/plan-ref-lifecycle.md` — fail-open on-land bookkeeping pattern
- `docs/learned/pi/context-system.md` — the bash allowlist (incl. the read-only `gh` query subcommands)
- `docs/learned/workflow/human-engagement-reads.md` — the concrete cold-injects/warm-instructs instance
