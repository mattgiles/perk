---
title: The layered skills-exposure model — engagement-gated scoping of cold-launch skill discovery
read_when: You are touching the layered skills-exposure model (skill_exposure.py, stages frontmatter, [skills] config), scoping launch skill discovery, or designing an engagement-gated zero-change rollout.
---

# The layered skills-exposure model

perk can scope a cold stage launch's pi skill discovery to the skills relevant to that stage
(`stages:` SKILL.md frontmatter, `[skills]` config, `--no-skills`/`--skill` argv composition).
The canonical spec is `shared/contracts.md` §8.39 — the three-layer resolution, the bound-skill
union, the argv shape, and the fail-open ladder all live there; this doc captures only the
cross-cutting reasoning that generalizes beyond the feature. Source pointers:
`src/perk/substrate/skill_exposure.py` (the model), `perk/run/launch/__init__.py::_skill_exposure_argv`
(the argv seam), `src/perk/substrate/config.py` (the `[skills]` namespace).

## Zero-change rollout via an explicit engagement rule

The scoping flags compose only when the model is provably in use: any `stages:` frontmatter
declaration, or any `[skills]` config content — **including `include_packages` explicitly set to
its default value** (an explicit set counts as engagement even when it changes nothing).
Enumeration always runs (cheap) to detect declarations. Unengaged repos stay byte-identical in
argv **and** stderr — composition warnings are deliberately dropped when unengaged, so
package-tier trouble (a cold `.pi/npm`) can never leak noise into untouched repos. This is a
reusable posture — "engage only on signal, byte-identical otherwise" — for any future scoped
feature (e.g. stage-scoped tools).

## Fail-open granularity: degrade the whole tier, not its members

A listed `npm:` package absent at composition time (argv is built *before* the warm-install
phase) degrades the **whole composition** to unscoped + one warning rather than per-package skips.
Skips would silently drop packages from scoped sessions with no symptom; the honest whole-tier
degrade self-heals on the next launch. Generalizes to any scoped-allowlist feature whose inputs
may be cold at compose time.

## By-name keying dissolved the ownership distinction

The plan-time framing "`[skills.stages]` = an overlay for externally-owned skills" settled as
by-name rows applying to project **and** package skills alike — once rows are keyed by skill
name, restricting them to one ownership class adds nothing. Prefer name-keyed config over
ownership-scoped config unless ownership genuinely changes semantics.

## "Both-plane tests" can honestly resolve to asymmetric coverage

The resolution was a Python resolution/engagement/package matrix plus a single TS
**non-interference pin** (a config carrying `[skills]` content parses and leaves every
`loadPerkConfig` output unchanged), because the TS `parseTomlSubset` drops the namespace
**fail-safe by construction** — pin the fail-safe rather than manufacturing consumption tests on
a plane that deliberately doesn't consume.

## Cross-references

- `shared/contracts.md` §8.39 — the canonical spec (three-layer resolution, argv shape, fail-open ladder)
- `docs/learned/workflow/skill-bindings.md` — **delivery**, the complement of this doc's **scoping**:
  bound skills always win and arrive via the binding union; bindings put a skill *into* a session
- `docs/learned/workflow/cold-door-launch.md` — the launch argv seam this composes into
