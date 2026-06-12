---
title: init/doctor division, managed-convergence SSOT, and gitignore untrack pattern
read_when: You are adding a managed piece (so a doctor check), adding a new transient file, fixing a tracked-but-should-be-ignored file, writing a doctor migration, extending perk init's managed gitignore block, adding a doctor check group / fail-level check / report field, adding a network-touching repair (the verify-gated gesture), or changing a monkeypatched seam's signature.
---

# `init` / `doctor` division

## The split

- **`perk init` converges forward**: desired state, idempotent, never migrations. Maps to
  `perk/init.py` (`GITIGNORE_BODY`, `converge()`).
- **`perk doctor --fix` repairs legacy oddities**: one-off fixes for things `init` can't undo or
  that stem from historical inconsistencies. Maps to `perk/doctor.py` (`_MIGRATIONS`).
- **`doctor` is the diagnostic pre-flight layer**: It utilizes report-only free functions
  (non-converging) inside `verify:` blocks. While `init` actively manages forward on-disk files,
  `doctor` provides diagnostic gating without mutating state (unless `--fix` is explicitly run).

Keep `init` a clean forward path — never a pile of version branches. New desired state goes into
`init`'s `converge()`; one-off/legacy repairs go into `doctor`'s `_MIGRATIONS`.

## Managed convergence is the SSOT for doctor checks — never hand-author a check

A **managed convergence** (`init.ManagedConvergence`, listed by `init.managed_convergences()`) is
one structural piece expressed as a single dry-run/apply function: `init` calls it with
`apply=True` to converge; `doctor` calls it with `apply=False` to detect drift and `apply=True`
to `--fix`. `doctor._managed_checks` **auto-generates exactly one `Check` per convergence** (the
convergence `name` becomes the check name). Verification *and* `--fix` come for free —
`doctor._apply_fixes` iterates the same convergences.

So to add any new managed piece (the recipe is **three edits**, never a bespoke check):

1. Add a `ManagedConvergence` in `init.managed_convergences()` — its `name` becomes the doctor
   check name; `covers` lists the capability names it verifies.
2. Add the matching `Capability` in `perk/capabilities.py` (referenced by the convergence's
   `covers`).
3. Optionally add a `name → render-group` entry in `doctor._MANAGED_GROUP` (purely cosmetic
   grouping; absent ⇒ falls back to `"repository"`).

**Do NOT hand-write a check in some `_build_checks`-style function** — that produces a *duplicate*
check for the same piece. The skills-manifest work (#56) was originally planned with a bespoke
`_skills_manifest_check`; that was wrong against this architecture and was dropped for the
three-edit recipe.

The coherence guard `test_every_required_capability_has_a_doctor_check`
(`tests/test_doctor.py`) enforces convergence↔capability parity: every dry-run convergence has a
check, and no applicable capability is left uncovered.

**The exception — a report-only check is not a hand-authored managed check.** This rule forbids
hand-writing a check for a piece that *has a managed convergence* (that would duplicate the
auto-generated one). A **pure validation with no converge/`--fix` semantics** has no convergence to
mirror, so it legitimately appends to `doctor._build_checks` directly and leaves `_apply_fixes`
untouched (e.g. the skill-bindings `bindings` check — see `skill-bindings.md`). Doctor group strings
are free-form (`_MANAGED_GROUP` only governs managed-convergence render grouping), and the coherence
guard checks *capability* coverage, not an enumerated group set, so a brand-new report-only group
renders fine. The test to apply: **does this piece have a `--fix`/converge side?** Yes → three-edit
managed convergence; no → a report-only `_build_checks` entry.

## Gitignore untrack pattern

A gitignore rule is **inert for already-tracked files** — `git check-ignore` even reports a tracked
path as "not ignored" (confusing). Adding the rule to `.gitignore` without untracking the file
leaves it churning on every change.

The proper two-plane fix:

1. **`init`** — add the entry to `GITIGNORE_BODY` so it lives *inside* the managed block (init owns
   all managed gitignore entries; never hand-add outside the `# BEGIN/END perk managed` block).
2. **`doctor --fix`** — run `git rm --cached <file>` (kept on disk) and strip any stray ungrouped
   line. `is_tracked` / `rm_cached` helpers live in `perk/git.py`.

**Generalizable rule:** any file materialized into `.pi/workflow/` is transient and must be added
to the managed gitignore block in `init.py` (alongside `plan-ref.json`, `handoff/`, `scratch/`,
`markers/`).

## `report.changes` must reflect real filesystem deltas (idempotency)

Anything appended to `InitReport.changes` must be a **genuine delta**, never "an action was
attempted". The load-bearing invariant `test_cli_idempotent_second_run`
(`tests/test_init_t5.py`) asserts a second `perk init` on a converged repo reports
`changes == []`. A convergence that always appends a change on success breaks it.

The pattern for any side-effecting step (e.g. shelling out to an external CLI): **snapshot before
and after, append only on difference.** `_sync_skills` snapshots the `.agents/skills/` symlink set
(`_skill_link_state`: name → target) before and after running `skills sync`, and appends a change
only when the set actually changed.

## "doctor checks disk; selfcheck checks the prompt"

perk converges context **onto disk** (`perk init` writes the `<!-- BEGIN perk managed -->` AGENTS
block; `/learn-docs` maintains `.pi/APPEND_SYSTEM.md`) and trusts Pi to splice it into the model
prompt. `perk doctor` verifies only the **disk** side. The `/perk-selfcheck` command verifies the
**prompt** side via the live `getSystemPromptOptions()` (see `docs/learned/pi/extension-api.md` for
why that must be a *command* handler). The division:

| Surface | Verifies | Mechanism |
|---|---|---|
| `perk doctor` | the on-disk convergence | managed-convergence dry-run |
| `/perk-selfcheck` | the spliced system prompt | live `getSystemPromptOptions()` |

This made `<!-- BEGIN perk managed -->` a **cross-plane string contract**: `perk/init.py`
(`AGENTS_BEGIN`) writes it, `extension/selfcheck.ts` (`MANAGED_AGENTS_MARKER`) reads it. Changing the
literal in one plane must update the other in the same turn (recorded in `shared/contracts.md` §8.7).

**Byte-match proof for the managed AGENTS block:** after editing the convergence source
(`_agents_inner()`) and the committed `AGENTS.md` in parallel, prove they're in sync with a small
`uv run python` snippet that splits the file on the `AGENTS_BEGIN`/`AGENTS_END` markers and
compares the inner text to the function output — cheaper and exact, versus re-running `perk init`
and eyeballing. (The scratch-dir `perk init` smoke still validates end-to-end convergence.)

The selfcheck probes are tolerant by design: an **absent** on-disk ambient index counts as wired (a
fresh consumer repo has none until the first `/learn-docs` lands), so selfcheck never false-fails on
it; only an index that *exists but didn't reach* the prompt is a gap. The "reached" probe is a
trimmed-substring match (robust to join-newline/whitespace differences) and stays sound only while Pi
loads `.pi/APPEND_SYSTEM.md` **verbatim** — see `docs/learned/pi/context-system.md`.

## `doctor`'s human output renders only the `GROUP_ORDER` groups

`perk doctor`'s **condensed human output** renders only the groups in the literal group-order
tuple in the doctor command module. Its render loop iterates that tuple, so any check whose group
is **not** listed is **invisible in the human text** and surfaces only in `--json` and the exit
code.

**The trap struck again** (the skills-delivery check): the new `skills` group wasn't in the render
order — and neither were the pre-existing `bindings` and `providers` groups, meaning those checks
had been silently invisible in human output the whole time. Durable rule: **any new `Check.group`
value MUST be added to the render group order in the same change**, and a render-visibility test
is cheap insurance.

This is distinct from `perk/doctor.py`'s `_MANAGED_GROUP` (which only *assigns* a managed
convergence's group name, falling back to `"repository"`); assigning a group there does **not**
make it render unless that group is also in the render module's `GROUP_ORDER`
(`perk/cli/commands/doctor/render.py`). Any new doctor groups will remain completely invisible in
the condensed human text unless explicitly added there.

## Fail-level checks, fix_errors, and the machine-surface co-owners

Lessons from making skills delivery a fail-level concern (see also `init-external-cli.md`):

- **A new fail-level verify-gated check shifts the baseline of every `verify=True` test repo** —
  freshly-converged test repos now fail the new check unless the healthy end-state exists. Budget
  for a conftest fixture that plants that end-state (e.g. the converged skills workspace) rather
  than patching individual tests.
- **Failed repairs are first-class report data**: `DoctorReport.fix_errors` is rendered in human
  output and present in `--json`, never folded into `fixed`. The `--fix` re-verify must trigger on
  fixes *or* fix-errors — otherwise a failing sync with zero successful fixes reports stale
  pre-fix checks.
- **The machine-surface contract sections are always co-owners**: when adding error types or
  report fields, the exit-code taxonomy (`shared/contracts.md` §8.5) and the `--json` shape
  (§8.6) need same-turn amendment — plan them in, not just the feature's own section.
- **Seam-signature ripple**: before changing a patched seam's signature, grep tests for the seam
  name — the skills-sync seam had 8 stub sites whose monkeypatch lambdas all needed widening.

## Network repairs live in the verify-gated repair gesture, never a `ManagedConvergence`

Managed convergences run **unconditionally in offline unit tests**, so anything that does network
I/O (the Linear label ensure, skills sync) must instead follow the `sync_skills` pattern: a
`fix AND verify`-gated call in `run_doctor` appending to `fixed`/`fix_errors`, idempotent via
lookup-first. Corollary: `_apply_fixes`' check-keyed loop only acts on `fail` checks — warn-level
findings are repairable *only* through the gesture path.

Related readiness shape (full detail in `linear-backend.md`): **one report-shaped probe, two
consumers** — a never-raising `check_readiness` with an `ensure_labels` flag splitting doctor's
lookup-only path from init/`--fix`'s converge path. Probe results carry only what was
*discovered*; an input value a render needs goes on the wrapping report, not the probe result. And
a verify-gated group that can't run must say *why it stopped* (a single warn check), never
silently pass.

## Managed template reconvergence

When you edit managed full-file templates in the codebase (for example, `PERK_RUN_WORKFLOW` in
`perk/workflow_artifacts.py`), you must immediately trigger self-repo copy reconvergence (such as
updating `.github/workflows/perk-run.yml` in perk's own repo) in the same turn. Run
`perk doctor --fix` or `perk init` to apply the updated template to the self-repo, and commit the
converged changes together with the template edits.

## Click bottom-of-file imports

To avoid circular imports when registering Click command subgroups, place the subgroup registration
imports at the bottom of the parent group file, strictly *after* the parent group object (`cli` or
`perk_group`) has been fully defined. This ensures the parent group is available in the module
namespace when child commands attempt to import and register themselves onto it.

**Scope this idiom to genuinely registration-induced cycles.** When the cycle is *helper-induced*
(a subgroup importing the parent's helpers), dissolve it instead by extracting the shared helpers
into a sibling leaf module (the `doctor/render.py` pattern) so both `__init__.py`s import
top-of-file normally — see `docs/learned/workflow/cli-command-groups.md`.

### `register_with_aliases` single-command constraint

The `register_with_aliases` helper in `perk/cli/alias.py` is strictly designed for single-command
registration. Attempting to pass extra positionals (e.g., trying to register multiple commands in a
single call) will fail loudly at import time.

The latent trap: "mirror an existing group" instructions inherit that group's own render status —
the `bindings` and `providers` groups were unrendered for a long time before the skills-delivery
fix added them. Extending `GROUP_ORDER` changes long-standing behavior for previously-invisible
groups, so treat it as a deliberate cross-cutting change, not a drive-by. **Verify render
visibility empirically with `perk doctor`, not just `--json`.**

## Doctor migration idempotency rule

`_MIGRATIONS` run **unconditionally on every `--fix`** (not gated on a failing check), so each
migration must be **idempotent** — it must return `[]` once converged. Failing idempotency breaks
the `again.fixed == []` idempotency tests.

## Cross-references

- `perk/init.py` — `GITIGNORE_BODY`, `converge()`, `ManagedConvergence`, `managed_convergences()`,
  `_skill_link_state`, `_sync_skills`
- `perk/doctor.py` — `_MIGRATIONS`, `_managed_checks`, `_MANAGED_GROUP`, `_apply_fixes`
- `perk/cli/commands/doctor/render.py` — `GROUP_ORDER` (the human-render group allow-list)
- `perk/capabilities.py` — `Capability`, `applicable()`
- `perk/git.py` — `is_tracked`, `rm_cached`
- `tests/test_doctor.py` — `test_every_required_capability_has_a_doctor_check`
- `tests/test_init_t5.py` — `test_cli_idempotent_second_run`
- `extension/selfcheck.ts` — `MANAGED_AGENTS_MARKER`, `readAmbientIndex`, `buildSelfcheckReport`
- `docs/learned/pi/extension-api.md` — why selfcheck must be a command handler
- `docs/learned/workflow/linear-backend.md` — the full Linear readiness probe shape
