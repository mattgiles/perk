---
title: Skill bindings — the two-plane trigger→skill delivery subsystem
read_when: You are working on skill-binding config (.pi/perk.toml [[bindings]]), the cold/warm delivery doors, the resolver, the worktree skill mirror (linked-worktree delivery), or debugging double-delivered / missing binding context.
---

# Skill bindings

Skill bindings let a user attach a skill to a trigger (`stage:<id>` or `command:<id>`) in
`.pi/perk.toml`, so that launching that stage/command delivers the skill's `SKILL.md` content into
the session. The subsystem is **two-plane** (Python cold door + TS warm door) over a **shared data
contract** (`shared/bindings.yaml`), built across Objective #63 nodes 1.1–2.2. The cross-cutting
knowledge below is what an agent can't derive from reading any single file.

## The data contract and the resolver (Nodes 1.1, 1.2)

The vocabulary, model, and shipped-default set live in `shared/bindings.yaml` — the **second**
parsed `shared/` contract after `registry.yaml` (see `shared-contracts.md` for the repeatable recipe
for adding such a contract). A trigger is a single `"<kind>:<id>"` string (`kind ∈ {stage, command}`)
stored **literally**, not split into fields, because that's exactly what a user types in
`.pi/perk.toml`; readers split on the **first** `:`. Kind-selection rule: bind to `stage:<id>` when a
command maps 1:1 to a registry stage of the same name (the canonical trigger fires across BOTH cold
launch and warm slash-command); reserve `command:<id>` for commands with no registry stage. Loaders
stay **registry-free** — target-existence cross-validation is deferred to `doctor`.

Resolution overlays user bindings onto shipped defaults. Two subtle semantics:

- **Whole-array replace, local wins.** A user `[[bindings]]` array replaces the array wholesale
  (mirroring Python `_overlay`'s list-replaces-list), never element-merge. The TS `parseTomlSubset`
  return type had to grow from a flat `StringTable` to `{ tables, arrays }` to carry array-of-tables
  — see `toolchain/biome.md` for the parser-rewrite gotchas.
- **"Earlier-*applied* duplicate", not raw validate-duplicate.** A user binding applies iff
  shape-valid AND its trigger wasn't *already applied*. This differs from naive `validate()` on the
  edge case `[invalid-shape@T, valid@T]`: validate flags the second as a duplicate, but the locked
  decision wants it *applied* (the first was dropped, never applied). Both planes share a per-binding
  issues primitive plus an `applied` set in the resolver — **the resolver does not call validate**.
  Downstream delivery nodes get unique-triggers-by-construction for free.

## "User-originated" is the delivery filter — and the frozen-dataclass test is exact

perk still hardcodes its own "Follow the … skill" nudges (until a later node deletes them), so the
delivery layer must deliver **only** user-originated bindings to avoid double-pointing. The exact
test: a resolved binding **value-equal to a shipped default is dropped**; a *new* trigger or an
*override* of a perk-owned trigger is delivered. Python expresses this as frozen-dataclass set
membership (`Binding` is `@dataclass(frozen=True)` → hashable; `b not in set(defaults)`). The TS twin
has no value identity (plain object), so it serializes a tuple key
(`JSON.stringify([trigger,kind,targetId,skill,mode])`) into a `Set` — the same pattern applies any
time a TS plane mirrors a Python set/`in` over structural objects.

## The two doors and the cold↔warm dedup marker (Nodes 2.1, 2.2)

Cold and warm renderers are **independent code paths** that must not double-deliver when both fire
for one session (a cold launch *and* `before_agent_start`). They dedup through one **byte-identical
header literal**: `BINDING_HEADER` (TS, `extension/substrate/bindingDelivery.ts`) ≡ `_HEADER` (Python,
`perk/substrate/binding_delivery.py`). The warm injector skips when **any entry on `ctx.sessionManager.getBranch()`
already contains the header** — a shape-agnostic scan (`branch.some(e => JSON.stringify(e).includes(HEADER))`)
robust because the header is a distinctive literal. The equality is pinned by a literal test in BOTH
planes; changing the literal in one plane must update the other in the same turn. It is idempotent
across turns/reloads, and re-delivers after compaction drops the original entry (the ongoing value).

The cold/warm injection+strip mechanics (why the strip must be conditional, why it must be narrower
than planMode's) are pi-lifecycle facts captured in `pi/context-injection.md`.

### The `binding_trigger` "borrows-a-stage" hazard

`launch_stage` (`perk/run/launch.py`) is the single cold-launch chokepoint every stage launcher routes
through, so binding delivery wired there covers all launches uniformly. But the trigger defaults to
`f"stage:{stage.id}"`, and **`learn-docs` borrows the `plan` stage descriptor** — keying delivery off
`stage.id` alone would fire `plan`'s bindings for it. The fix is an explicit
`binding_trigger: str | None = None` param; only `learn-docs` overrides it (to `command:learn-docs`).
**Any future "borrows-a-stage" command must set `binding_trigger` or it silently fires the borrowed
stage's bindings.**

Two delivery-surface boundaries that held:

- **Worker commands have no cold-door delivery surface.** `objective-reconcile` rewrites the
  objective body with no `pi` session / initial prompt, so `command:objective-reconcile` can only
  fire at the warm door. Don't wire cold delivery for non-launching workers.
- **Delivery I/O lives apart from the model.** Disk reads (`SKILL.md` transclusion) live in
  `perk/substrate/binding_delivery.py`, keeping `perk/substrate/bindings.py` a pure model/resolver. Resolver `issues` +
  delivery `warnings` are **returned, never raised**, and surfaced loud-but-non-fatal: a missing
  transclude target degrades to the nudge pointer with a warning, never blocking a launch.

## Linked-worktree delivery depends on the cold door mirroring `.agents/skills/`

Both delivery doors read `.agents/skills/<name>/SKILL.md` from the **session cwd** (the worktree),
but a linked worktree's `.agents/skills/` is empty unless the cold door **mirrors it during launch
positioning** — `.agents/skills/` is gitignored (so `git worktree add` never carries it) and pi only
discovers skills up to the worktree's own git root. A dangling-binding warning in a worktree session
is the **symptom** of a missing mirror, not a config error. The mirror mechanism
(`materialize_skills` in `launch_stage`, per-skill single-hop symlinks, loud-but-non-fatal +
idempotent) lives in `workflow/cold-door-launch.md`.

## Skills `references:` frontmatter + subdirectory routing needs no wiring

A skill can route per-variant content via `references:` frontmatter plus a subdirectory (the
dignified-python `versions/` pattern — perk's own instance is `perk-implement`'s
`backends/{github,linear}.md`). This works for perk's skills with **zero init/doctor changes**:
delivery is whole-directory sync, and the launch prompt naming the variant (e.g. the backend in
`implementing perk plan <backend> #<id>`) is the routing signal the model uses to pick
`backends/<backend>.md`. See `linear-backend.md` for the backend-aware prompt side.

**Confirmed again by a bundled upstream skill (#617):** the worktree skill-materialization
(`materialize_skills`) symlinks the **whole skill dir per-skill**, so a skill's `references/` files
(e.g. `ast-grep/references/rule_reference.md`) travel into worktrees **for free** — no manifest or
force-include entry. And **no skill is added to the wheel**: skills ship via the skills CLI, not a
`pyproject` force-include. The `references:` zero-wiring property is not perk-skill-specific.

## doctor validation + the injection-time presence mirror (Node 3.1)

`doctor` validates skill bindings, and a missing/unknown binding target yields a **loud-but-non-fatal
warning** at both doctor-time and injection-time. The traps below are what an agent can't derive from
the mechanics.

### The self-repo skill-layout asymmetry (the biggest trap)

perk's own `perk-*` skills are **NOT** under `.agents/skills/` in the self-repo — that dir holds only
*borrowed* skills (`dignified-python`, `ruff`, `ty`, `uv`). The 9 `perk-*` skills live at
`skills/<name>/SKILL.md` and reach Pi via the `..` package's `skills` CLI sync, not via
`.agents/skills/` symlinks the self-repo materializes. A naive `.agents/skills/<name>/SKILL.md`
presence check therefore emits **8 false warnings** on perk's own `perk doctor`. The fix:
`is_skill_installed(root, skill, *, self_repo=False)` accepts a `skills/<name>/SKILL.md` fallback
**only** when `self_repo`. Any future code asking "is this perk skill installed?" must thread
`self_repo` or it mis-fires on perk's own tree. (See `init-external-cli.md` for why this fallback is
also the pre-sync safety net.)

### Two-tier validation split (deliberate, not an oversight)

- **doctor** validates the **full resolved set** (`resolve_bindings(user, defaults=load_bindings()
  .bindings).bindings`) with the **self-repo `skills/` fallback**.
- **Injection** (cold `render_cold_bindings` nudge path + warm `bindingSuffix`) checks only
  **user-originated** bindings and uses `.agents/skills/<name>` **only** (default `self_repo=False`)
  — byte-identical to the delivery read path. Injection only ever references skills the *user*
  installed under `.agents/skills/`; the self-repo fallback is doctor-only. Keep these asymmetric on
  purpose.

### Severity = `warn`, never `fail` (tied to a real lifecycle fact)

Missing-skill / unknown-target findings are **`warn`** so `perk doctor` stays exit-0 — not cosmetic:
`skills sync` is best-effort/non-fatal and is skipped under `run_init(verify=False)`, so a freshly-
inited test repo (and any consumer who hasn't run `skills sync` yet) legitimately has no
`.agents/skills/perk-*`. A `fail` would break `tests/test_doctor.py::test_healthy_after_init` and
exit-1 a real consumer for a benign state. Only a `BindingsError` on the **bundled** file is `fail`
("Reinstall perk" — impossible in a healthy install; mirrors `_registry_check`).
`RegistryError`/bad-TOML mid-check degrade to a warn *note* (those failures are owned by the
registry/config checks — don't double-fail).

### `DELIVERABLE_COMMAND_TARGETS` is the command-trigger vocabulary

Only `command:objective-reconcile` and `command:learn-docs` have a binding-delivery surface (the two
Mechanism-B `bindingSuffix` call sites + the cold `binding_trigger="command:learn-docs"` override).
Any other `command:<id>` binding **can never fire** and doctor reports it as such. Commands that *are*
registry stages bind via `stage:<id>` (the kind-selection rule above). If a future command grows a
delivery surface, this frozenset must be extended in lockstep.

#### Adding a `command:<id>` binding touches MANY sites (the checklist)

Adding a deliverable command + skill requires **all** of these to change together, or tests/doctor
break (the concrete instance is `/pr-review` → `command:pr-review`):

1. **`shared/bindings.yaml`** — the `{trigger, skill, mode}` row.
2. **`perk/substrate/bindings.py` `DELIVERABLE_COMMAND_TARGETS`** frozenset (+ its comment listing the
   `bindingSuffix` call sites) — else doctor's binding-target check fails.
3. The warm command must call **`bindingSuffix(ctx.cwd, "command:<id>")`** (Mechanism B) — the skill
   pointer is never hardcoded in the guidance body.
4. **`perk/convergence/init.py` `PERK_SKILLS`** tuple, then **regenerate** the committed manifest fragment
   `.agents/manifest.d/perk.yaml` (it's generated via `_desired_skills_manifest(True)`, not
   hand-edited — watch for pre-existing drift).
5. **THREE** binding-count test sites: Python `tests/test_bindings.py` `EXPECTED_DEFAULTS`; TS
   `extension/substrate/bindings.test.ts` `EXPECTED` array **and** the "returns the N shipped default bindings"
   count in the test name.
6. If configurable: `extension/substrate/config.ts` `PerkConfig` + parser, and `perk/substrate/config.py` `Config` for
   forward parity — flag the Python side as possibly-unused until a cold door exists (don't omit it).
   Concretely, `perk/substrate/config.py`'s `pr_review_model` is **parsed-but-unused** today; only the TS warm
   `/pr-review` path consumes it.

See `docs/learned/pi/subagents.md` for `/pr-review`'s orchestration (the per-call inline `model`
override this `[pr-review] model` config feeds).

### The injection mirror: the nudge path now warns too

Previously only the `transclude` path warned on a missing skill; the `nudge` path delivered
silently. Node 3.1 added the `elif not is_skill_installed(...)` branch (both planes) so **every**
delivered binding to a missing skill yields exactly one warning. Also `bindingSuffix` (warm
Mechanism B) now `console.error`s its warnings — it previously "degraded silently". Tests that assert
`warnings == []` must now install the skill they bind (this bit two pre-existing pointer tests in
both planes).

### A report-only check is not a hand-authored managed check

This `bindings` doctor check is **report-only** (no `--fix`): a brand-new `group="bindings"` string
renders fine, and a new report-only check just appends to `doctor._build_checks` and leaves
`_apply_fixes` untouched. This is **not** a contradiction of the "never hand-author a check" rule in
`init-doctor.md` — that rule forbids hand-writing a check for a piece that *has a managed
convergence* (which would duplicate the auto-generated one). A pure validation with no converge/`--fix`
semantics has no convergence to mirror, so it lives in `_build_checks` directly. The coherence guard
checks *capability* coverage, not an enumerated group set, so a free-form group string is fine.

## Cross-references

- `shared/bindings.yaml`, `shared/contracts.md` §8.9 — the data contract and trigger vocabulary
- `perk/substrate/bindings.py` — pure model + resolver; `perk/substrate/binding_delivery.py` — `_HEADER`, cold render
- `extension/substrate/bindingDelivery.ts` — `BINDING_HEADER`, `BINDING_CONTEXT_TYPE`, warm injector + dedup scan
- `perk/run/launch.py` — `launch_stage`, the `binding_trigger` param (the borrows-a-stage seam)
- `docs/learned/workflow/shared-contracts.md` — adding a new parsed `shared/` contract
- `docs/learned/pi/context-injection.md` — the conditional inject-and-strip lifecycle
- `docs/learned/toolchain/biome.md` — the `parseTomlSubset` rewrite gotchas
- `perk/substrate/bindings.py` — `is_skill_installed(root, skill, *, self_repo)`; `perk/convergence/doctor.py` — the
  report-only `bindings` check; `DELIVERABLE_COMMAND_TARGETS`
- `docs/learned/workflow/init-doctor.md` — why a report-only check ≠ a hand-authored managed check
- `docs/learned/workflow/init-external-cli.md` — the `skills` CLI as single delivery path (the
  pre-sync `is_skill_installed` fallback)
- `docs/learned/pi/subagents.md` — `/pr-review` (`command:pr-review`), the concrete `command:<id>` binding instance
- `docs/learned/workflow/cold-door-launch.md` — the worktree `.agents/skills/` mirror (`materialize_skills`)
