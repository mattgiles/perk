---
title: init/doctor division, managed-convergence SSOT, and gitignore untrack pattern
read_when: You are adding a managed piece (so a doctor check), adding a new transient file, fixing a tracked-but-should-be-ignored file, writing a doctor migration, or extending perk init's managed gitignore block.
---

# `init` / `doctor` division

## The split

- **`perk init` converges forward**: desired state, idempotent, never migrations. Maps to
  `perk/init.py` (`GITIGNORE_BODY`, `converge()`).
- **`perk doctor --fix` repairs legacy oddities**: one-off fixes for things `init` can't undo or
  that stem from historical inconsistencies. Maps to `perk/doctor.py` (`_MIGRATIONS`).

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

The selfcheck probes are tolerant by design: an **absent** on-disk ambient index counts as wired (a
fresh consumer repo has none until the first `/learn-docs` lands), so selfcheck never false-fails on
it; only an index that *exists but didn't reach* the prompt is a gap. The "reached" probe is a
trimmed-substring match (robust to join-newline/whitespace differences) and stays sound only while Pi
loads `.pi/APPEND_SYSTEM.md` **verbatim** — see `docs/learned/pi/context-system.md`.

## Doctor migration idempotency rule

`_MIGRATIONS` run **unconditionally on every `--fix`** (not gated on a failing check), so each
migration must be **idempotent** — it must return `[]` once converged. Failing idempotency breaks
the `again.fixed == []` idempotency tests.

## Cross-references

- `perk/init.py` — `GITIGNORE_BODY`, `converge()`, `ManagedConvergence`, `managed_convergences()`,
  `_skill_link_state`, `_sync_skills`
- `perk/doctor.py` — `_MIGRATIONS`, `_managed_checks`, `_MANAGED_GROUP`, `_apply_fixes`
- `perk/capabilities.py` — `Capability`, `applicable()`
- `perk/git.py` — `is_tracked`, `rm_cached`
- `tests/test_doctor.py` — `test_every_required_capability_has_a_doctor_check`
- `tests/test_init_t5.py` — `test_cli_idempotent_second_run`
- `extension/selfcheck.ts` — `MANAGED_AGENTS_MARKER`, `readAmbientIndex`, `buildSelfcheckReport`
- `docs/learned/pi/extension-api.md` — why selfcheck must be a command handler
