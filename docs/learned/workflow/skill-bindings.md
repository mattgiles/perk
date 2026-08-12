---
title: Skill bindings — the two-plane trigger→skill delivery subsystem (+ the layered skills-exposure scoping model)
read_when: You are working on skill bindings (.perk/config.toml [[bindings]]) — delivery doors, worktree mirror — or scoping launch skill discovery (skill_exposure.py, [skills], engagement-gated rollout).
cluster: config-and-convergence
---

# Skill bindings

Skill bindings let a user attach a skill to a trigger (`stage:<id>` or `command:<id>`) in
`.perk/config.toml` (a `[[bindings]]` array-of-tables; contracts §8.9 — `.pi/perk.toml` is
migration-source-only), so that launching that stage/command delivers the skill's `SKILL.md`
content into the session. The subsystem is **two-plane** (Python cold door + TS warm door) over a **shared data
contract** (`shared/bindings.yaml`), built across Objective #63 nodes 1.1–2.2. The cross-cutting
knowledge below is what an agent can't derive from reading any single file.

## The data contract and the resolver (Nodes 1.1, 1.2)

The vocabulary, model, and shipped-default set live in `shared/bindings.yaml` — the **second**
parsed `shared/` contract after `registry.yaml` (see `shared-contracts.md` for the repeatable recipe
for adding such a contract). A trigger is a single `"<kind>:<id>"` string (`kind ∈ {stage, command}`)
stored **literally**, not split into fields, because that's exactly what a user types in
`.perk/config.toml`; readers split on the **first** `:`. Kind-selection rule: bind to `stage:<id>` when a
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

## Single-delivery pins count the whole pointer line, not a token

The no-double-delivery asserts once counted a skill-name substring
(`argv[-1].count("perk-implement") == 1`); when the nudge pointer format grew its read path
(``Follow the `perk-implement` skill (read `.agents/skills/perk-implement/SKILL.md`).``) the name
appeared **twice within one correct pointer**, breaking the pin on correct behavior. The durable
idiom (realized in both suites): a shared pointer-rendering helper — `_pointer(skill)` in
`tests/test_launch.py` and `pointer(skill)` in `extension/substrate/bindingDelivery.test.ts` —
asserted via `count(_pointer(...)) == 1` (plus `count("Follow the") == 1` as the format-agnostic
backstop). The helper also keeps the long literal under lint line-length limits in both suites.
Anyone changing the pointer format again reaches for the helper, not a re-inlined string.

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
stage's bindings.** (The write-capable `perk skills create` / `refine` cold doors are later instances
— they borrow the `save` stage and override `binding_trigger="command:skills-<verb>"`; cross-ref
`write-capable-cold-doors.md`. `perk learn harvest` is another: it borrows the `objective-author`
stage descriptor and overrides `binding_trigger="command:learn-harvest"` — and because the
diverted stage binding can no longer deliver the `perk-objective-author` skill, the harvest seed
hardcodes that skill pointer itself.)

**Forward-declared bindings land ahead of their door.** A `command:<id>` binding + its
`DELIVERABLE_COMMAND_TARGETS` entry can be added **before** the door that fires it exists (the
`command:skills-refine` binding landed in the *create* node, ahead of the refine door). A binding
with no firing call site is **harmless** — it simply never fires until a door wires the matching
`binding_trigger`. The lockstep when growing the default set is unchanged (the checklist below already
documents it).

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

**Remote drives get skills via the real skills-CLI sync, not the mirror.** The remote runner
checkout lacks `.agents/skills/` (gitignored) and the worktree *is* the checkout, so mirroring
from `repo_root/.agents/skills/` would be a self-referential no-op — the runner needs the *sync*,
not the mirror. The `perk-remote-setup` composite installs the `skills` CLI (`go install` from
source — its release binaries are darwin-only), and `run_worker.position_worktree` runs the same
`sync_skills` gesture `perk init` uses against the checkout's committed manifests
(`_deliver_skills`). Posture is **fatal** at both tiers (a failed install fails the job; a failed
sync raises `skills_sync_failed` before the worker spawns) — deliberately diverging from the
loud-but-non-fatal local mirror, because remotely nobody sees a warning (contracts §8.38 named
difference 2). Cross-ref `remote-runner.md`.

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

perk's own `perk-*` skills are **NOT** committed under `.agents/skills/` in the self-repo — the
committed entries there are *borrowed* skills (`dignified-python`, `ruff`, `ty`, `uv`, …). The
`perk-*` skills (23 at this writing — re-derive against the `skills/` directory, don't trust the
count) live at `skills/<name>/SKILL.md` and reach Pi via the `..` package's `skills` CLI sync, not
via `.agents/skills/` symlinks the self-repo materializes. A naive `.agents/skills/<name>/SKILL.md`
presence check therefore emits **one false warning per bound `perk-*` skill** on perk's own
`perk doctor` (8 at the time the trap was hit). The fix:
`is_skill_installed(root, skill, *, self_repo=False)` accepts a `skills/<name>/SKILL.md` fallback
**only** when `self_repo`. Any future code asking "is this perk skill installed?" must thread
`self_repo` or it mis-fires on perk's own tree. (See `init-external-cli.md` for why this fallback is
also the pre-sync safety net.)

Plan-claim caution: a plan must **not** claim an in-branch skill edit "reflects immediately" via
`.agents/skills/` — in the self-repo those entries are symlinks into a **commit-pinned skills-CLI
cache snapshot**, not into `skills/`, so an in-branch edit is not live until re-sync (the stale
mirror + dogfood symlink-swap mechanics are below).

### Two-tier validation split (deliberate, not an oversight)

- **doctor** validates the **full resolved set** (`resolve_bindings(user, defaults=load_bindings()
  .bindings).bindings`) with the **self-repo `skills/` fallback**.
- **Injection** (cold `render_cold_bindings` nudge path + warm `bindingSuffix`) checks only
  **user-originated** bindings and uses `.agents/skills/<name>` **only** (default `self_repo=False`)
  — byte-identical to the delivery read path. Injection only ever references skills the *user*
  installed under `.agents/skills/`; the self-repo fallback is doctor-only. Keep these asymmetric on
  purpose.

### The blind-spot consequence: green doctor, injection ENOENT

The two-tier asymmetry above has a **failure mode**, not just a false-warning fix. In the self-repo,
doctor's skills-delivery check accepts the committed `skills/<name>/SKILL.md` fallback — but warm
injection reads **only** `.agents/skills/<name>/SKILL.md`. So a **stale `.agents/skills/` mirror
passes doctor green and then ENOENTs at injection time** (a dangling worktree symlink whose target
moved/was never synced). Doctor can't see it because it's looking at the *other* tier. The symptom:
a binding that doctor reports healthy still fails to deliver its skill body in a live worktree
session.

Manual repair when you hit it: run `skills update --sync` in the **main checkout** (re-materializes
`.agents/skills/`), then re-point the worktree's `.agents/skills/<name>` symlink (the cold-door
`materialize_skills` mirror does this at launch — a stale one predates the current target). The
structural fix (make doctor's self-repo check see the tier injection actually reads, or converge the
mirror) is tracked on objective #1206 node 4.3 (item 3, status `planning`) — a status pointer, not
fiction to author here.

**Confirmed live, with the durable timing shape.** The worktree mirror freezes at implement-launch
against the main checkout's *then-current* (possibly stale) sync. Main can re-sync minutes later,
but a dogfood session is a **plain `pi` launch — no cold door, so nothing ever re-mirrors**; the
stale window never self-heals. Repair recipe: re-run the skills materialization against the
now-fresh main checkout (`materialize_skills` — idempotent; it repoints stale links but **never
removes orphans**, so retired-skill links must be removed by hand).

**The dogfood variant.** When the worktree branch carries in-branch skill tunings under
`skills/<name>/`, re-point the skills-under-test at the worktree's **own** `skills/<name>` dirs (a
symlink swap) — otherwise the mirror pins main's cache commit and the in-branch tunings are
silently NOT live in the dogfood session, defeating the point of dogfooding from the branch
worktree.

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

The frozenset in `perk/substrate/bindings.py` is the SSOT — each member (e.g.
`command:pr-review`, `command:objective-replan`) is a command with a binding-delivery surface (a
Mechanism-B `bindingSuffix` call site, and for the cold doors a `binding_trigger="command:<id>"`
override). Don't enumerate the members here — the set keeps growing and a hard-coded list goes
stale (the same listing-without-a-count discipline `pi/subagents.md` records for `PERK_AGENTS`).
Any other `command:<id>` binding **can never fire** and doctor reports it as such. Commands that *are*
registry stages bind via `stage:<id>` (the kind-selection rule above). If a future command grows a
delivery surface, this **MANUALLY-curated** frozenset must be extended in lockstep — it is NOT
derived from `bindings.yaml` — following exactly the checklist below.

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
6. **TWO prose count sites** move in the same lockstep:
   `docs/user-docs/how-to/attach-a-skill-to-a-stage.md` and its delivered mirror
   `skills/perk-expert/references/customization-recipes.md` both enumerate the deliverable
   command targets **and spell out their count in words** ("Ten command targets have a delivery
   surface…" today). Both must be bumped in the same turn — they had already drifted once (stuck
   at "eight") before that was caught. Total: the five-site code/test lockstep + 2 prose sites.
7. If configurable: `extension/substrate/config.ts` `PerkConfig` + parser, and `perk/substrate/config.py` `Config` for
   forward parity — flag the Python side as possibly-unused until a cold door exists (don't omit it).
   Concretely, `perk/substrate/config.py`'s `SubagentsTable.pr_reviewer` (`[models.subagents]
   pr-reviewer`) is **parsed-but-unused** on the Python side today; only the TS warm `/pr-review`
   path consumes it.

See `docs/learned/pi/subagents.md` for `/pr-review`'s orchestration (the workflow-level `model`
default this `[models.subagents] pr-reviewer` config feeds).

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

## Shipped-skill repo-specific routing: generic discovery + a repo-side anchor

Shipped `skills/<name>/SKILL.md` must stay **consumer-repo-agnostic** (the constraint is recorded
in `plan-review-flow.md`). When a shipped skill genuinely needs to route to repo-specific
surfaces, the positive mechanism is three-part:

- **The skill carries generic discovery only** — "check `AGENTS.md` conventions and the repo's
  docs index for where design records live" — never repo internals.
- **The repo supplies the anchor.** perk's own `AGENTS.md` "Where decisions are recorded" routing
  bullet is the instance; consumer repos can do the same in *their* `AGENTS.md`.
- **The never-scaffold guard**: if a repo has no canonical decision-record surface, the skill
  instructs *not to invent one* — never bootstrap a foreign doc system into a repo that didn't
  ask for one (the saved plan's Assumptions remain the durable record).

### Adapted-upstream skills can carry dead subsystems

A skill adapted from upstream can ship machinery routing to artifacts the workflow never produces
— the ADR half of `perk-domain-modeling` routed to doc trees no perk repo has, for its whole life,
while its glossary half was real and used. When auditing adapted skills, check whether their
machinery points at artifacts the workflow actually produces. The fix pattern: **keep the
judgment bar, re-target the destination** — the escalation test (hard to reverse / surprising
without context / real trade-off) survived intact; only the *where* changed.

## Description-discovered ≠ stage-bound (the perk-expert pattern, #677)

Not every skill is bound to a trigger. A skill may carry **no `[[bindings]]` row** and be invoked
purely on frontmatter `description` match — `perk-expert` is the first such `perk-*` skill (an
on-demand reference, not a stage orchestrator). Consequence: its **`description` is its primary
documentation** and must enumerate the trigger surface explicitly (every "how does perk … / how do I
configure …" angle), since nothing else routes to it.

### Self-contained references because delivered skills land where `docs/user-docs/` is absent

A delivered skill's reference bodies must be **self-contained** — zero cross-links escaping the skill
dir — because the skill lands in consumer repos where `docs/user-docs/` does not exist. End each with
a `*Canonical source: docs/user-docs/…*` breadcrumb footer.

**Drift is governed by extending the "Update the user docs, don't drift" lockstep, not a generator.**
The config/provider surface now has a **second mirror** in `skills/perk-expert/references/`: a change
to a config key / provider / backend updates BOTH the canonical `docs/user-docs/` reference AND the
matching `perk-expert` reference **in the same turn**. This is a **human-review discipline, not a CI
gate** (a flagged residual). (The `PERK_SKILLS` SSOT cascade for *delivering* a new skill is in
`init-external-cli.md` — cross-ref it, don't duplicate.)

## The layered skills-exposure model (scoping)

**Delivery vs scoping**: bindings put a skill *into* a session; the exposure model decides which
skills a cold launch *discovers* (no overlap — bound skills always win and arrive via the binding
union). perk can scope a cold stage launch's pi skill discovery to the skills relevant to that
stage (`stages:` SKILL.md frontmatter, `[skills]` config, `--no-skills`/`--skill` argv
composition). The canonical spec is `shared/contracts.md` §8.39 — the three-layer resolution, the
bound-skill union, the argv shape, and the fail-open ladder all live there; this section captures
only the cross-cutting reasoning that generalizes beyond the feature. Source pointers:
`src/perk/substrate/skill_exposure.py` (the model),
`perk/run/launch/__init__.py::_skill_exposure_argv` (the argv seam),
`src/perk/substrate/config.py` (the `[skills]` namespace).

### Zero-change rollout via an explicit engagement rule

The scoping flags compose only when the model is provably in use: any `stages:` frontmatter
declaration, or any `[skills]` config content — **including `include_packages` explicitly set to
its default value** (an explicit set counts as engagement even when it changes nothing).
Enumeration always runs (cheap) to detect declarations. Unengaged repos stay byte-identical in
argv **and** stderr — composition warnings are deliberately dropped when unengaged, so
package-tier trouble (a cold `.pi/npm`) can never leak noise into untouched repos. This is a
reusable posture — "engage only on signal, byte-identical otherwise" — for any future scoped
feature (e.g. stage-scoped tools).

### Fail-open granularity: degrade the whole tier, not its members

A listed `npm:` package absent at composition time (argv is built *before* the warm-install
phase) degrades the **whole composition** to unscoped + one warning rather than per-package skips.
Skips would silently drop packages from scoped sessions with no symptom; the honest whole-tier
degrade self-heals on the next launch. Generalizes to any scoped-allowlist feature whose inputs
may be cold at compose time.

### By-name keying dissolved the ownership distinction

The plan-time framing "`[skills.stages]` = an overlay for externally-owned skills" settled as
by-name rows applying to project **and** package skills alike — once rows are keyed by skill
name, restricting them to one ownership class adds nothing. Prefer name-keyed config over
ownership-scoped config unless ownership genuinely changes semantics.

### "Both-plane tests" can honestly resolve to asymmetric coverage

The resolution was a Python resolution/engagement/package matrix plus a single TS
**non-interference pin** (a config carrying `[skills]` content parses and leaves every
`loadPerkConfig` output unchanged), because the TS `parseTomlSubset` drops the namespace
**fail-safe by construction** — pin the fail-safe rather than manufacturing consumption tests on
a plane that deliberately doesn't consume.

## Cross-references

- `shared/bindings.yaml`, `shared/contracts.md` §8.9 — the data contract and trigger vocabulary
  (§8.39 — the skills-exposure spec: three-layer resolution, argv shape, fail-open ladder)
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
- `docs/learned/workflow/cold-door-launch.md` — the worktree `.agents/skills/` mirror (`materialize_skills`);
  also the launch argv seam the exposure scoping flags compose into
