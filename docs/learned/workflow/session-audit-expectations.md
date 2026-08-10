---
title: The session-audit expectation catalog — curation semantics, census pins, checker constraints
read_when: You are curating perk-dev audit expectations (expectations.yaml), writing a session-audit checker, or citing what the read-only gate / skill delivery actually enforces vs intends.
---

# The session-audit expectation catalog

The perk-dev session-audit expectation catalog lives in
`packages/perk-dev/src/perk_dev/audit/` (`expectations.yaml` + the `load_catalog` loader in
`expectations.py`). Each entry states an expectation about how a perk-driven session should have
behaved, for auditors — human or checker — to grade transcripts against. This doc carries the
curation semantics that entry prose and the schema can't express on their own.

## Expectation prose must mirror the enforcing surface's actual semantics, not its intent

When an entry claims determinism or structural impossibility, verify the claim against the
enforcing code *at the leniency level*, not the headline behavior — the false-violation paths
hide in the documented carve-outs. Two shipped instances, both reworded in review:

- **Prompt-hidden skills have TWO delivery routes.** `disable-model-invocation: true` hides a
  skill from the *model* prompt but preserves human `/skill:<name>` invocation, which injects the
  body without any exact-path read. The `bindings.nudge-skill-read` entry accepts either route as
  uptake evidence; any future deterministic checker keyed to it must implement the dual-route
  semantics or it will report false violations.
- **The read-only gate is an allowlist backstop with accepted, documented leniencies — not a
  mutation classifier.** The gate (`extension/substrate/toolGating.ts`) deliberately permits
  argument-blind `curl`, `agent-browser`
  (whose output flags can write files), and `subagent` with no agent allowlist, so a gate-active
  session *can* mutate the checkout through an accepted leniency with nothing broken. The
  `read-only.no-worktree-mutation` structural canary is scoped to the gate's *direct backstop*
  with the leniencies explicitly carved out of the "should be impossible" claim — otherwise a
  leniency-path mutation would falsely indict the gate, defeating the canary's calibration
  purpose.

## Coverage-shaped self-checks don't pin inventory

Self-checks shaped like "non-empty" or "spans all kinds" still pass if the catalog silently
shrinks. The census test (`test_committed_catalog_census` in
`tests/test_perk_dev_expectations.py`) is an **exact-id-set pin** — set equality plus
`validate()`'s duplicate-id rejection also pins the count — so curating a new expectation is a
deliberate two-file edit (catalog YAML + census). A fresh instance of the exact-set-pin pattern
in `test-pin-sweeps.md`.

## Known open edges for checker work

- `command:<id>` `applies_to` selectors are declared but **not existence-validated**; their
  session-mapping semantics land only with the classifier.
- `vintage_floor` values are round-up estimates; a release-history mapping may lower some — a
  data edit, not a schema event.
- One entry's headless exemption (grill-before-review) lives only in its evidence prose — the
  trigger grammar cannot express interactivity, so judgment auditors must honor it from the text.

## perk-dev subpackage conveniences

- A new `perk_dev/<sub>/` needs **zero toolchain wiring** — the hatchling package glob, the
  ruff/ty scopes, and the root `tests/test_perk_dev_*.py` convention all cover it automatically.
- Dev-only editable packages use plain `Path(__file__).with_name(...)` resource lookup — no
  dual-mode resolution needed when the package is never published.

## Cross-references

- `docs/learned/workflow/test-pin-sweeps.md` — the exact-set-pin pattern the census instantiates
- `docs/learned/workflow/pydantic-boundary-models.md` — the loader/validator house pattern
  (`load_catalog` is the family's canonical fixed shape)
- `docs/learned/workflow/skill-bindings.md` — the skill-delivery routes the nudge entry grades
