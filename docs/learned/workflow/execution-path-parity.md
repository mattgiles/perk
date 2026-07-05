---
title: Execution-path parity testing — one implementation per stage across warm / cold-local / remote
read_when: You are adding or auditing a warm/cold-local/remote surface, enforcing "one implementation per stage", writing a cross-plane or cross-path parity test, or deciding whether a path difference should be converged or named.
---

# Execution-path parity testing

perk's stages run on three execution paths — warm (in-session tools/doors), cold-local (the `perk`
CLI launching a session), and remote (the headless worker) — and the product claim is **one
implementation per stage**, not three lookalikes. This doc captures the discipline for keeping that
claim true: where the ground truth lives, the reusable test shapes that enforce it, and the decision
rule for differences.

## Ground truth = the §8.38 matrix

`shared/contracts.md` §8.38 ("Per-stage path parity") is the canonical matrix: six surfaces × the
**shared implementation** × the **enforcing tests** × the **named intentional differences**. Start
any parity effort by reading that table — do not re-derive the surface list from the code.

## Audit-first, not from-scratch

Most parity cells were already enforced by earlier work (the shared-implementation convergence
happened as each surface landed). The dedicated parity effort was an **audit plus targeted gaps**:
four gap tests and a naming pass — not a from-scratch parity suite. When asked to "verify parity",
first map existing tests onto the matrix; only then write tests for the genuinely-unenforced cells.

## The test-shape catalog

Each shape below is a reusable pattern, with its landed exemplar:

- **Stage-selection equality across two `--dry-run --json` surfaces.** Run both entry points
  (`plan resume` vs the `objective run` supervisor) in dry-run and assert they select the same
  next stage, not just the same verdict — `tests/test_next_action_parity.py`.
- **Save→reconstruct round trip with a dataclass field-census tripwire.** Round-trip the artifact
  through the writer and the reconstructor, and separately pin `dataclasses.fields(PlanRef)` set
  equality — so growing the type forces extending **both** the writer and the reconstructor —
  `tests/test_plan_ref_parity.py`.
- **Positioning artifact byte parity.** Prepare two roots, run `launch_stage` positioning on one
  and `position_worktree` on the other, then compare the resulting `.perk/workflow/` bytes with
  `run_id` excepted —
  `tests/test_run_worker.py::test_positioning_parity_local_launch_vs_remote_worker`.
- **Cross-plane render byte parity via a one-shot node script driven from pytest.** pytest renders
  through the Python engine, shells a small TS entry (`extension/testing/renderBindingsLive.ts`)
  for the extension's render, and byte-compares — `tests/test_binding_render_parity.py`, following
  the `tests/test_prompt_parity.py` precedent.
- **Lockstep literals.** Where both planes must agree on a frozen shape (`RunOutcome`), pin the
  literal byte-identically in both suites with reciprocal comments pointing at each other —
  `tests/test_run_report.py` ↔ `extension/worker/worker.test.ts` (see
  `docs/learned/workflow/shared-contracts.md` for the general lockstep-literal pattern).

## Name differences instead of forcing identity

Where a path *intentionally* differs — learn is resume-only; binding delivery mechanism differs
while content does not; `address --preview` is local-only; the conflict-resolver drive needs a
session; terminal classification is worker-only; run reporting is remote-only — the §8.38 matrix
and the user docs **name** the difference rather than implying identity. The decision rule:
**converge trivial formatting; name structural divergence.** A difference that survives is a
documented product fact, not an accidental drift.

## Byte-parity tests surface platform drift (the CRLF pointer)

A byte-parity test between planes turns platform newline divergence into real, visible drift —
Python and Node read files with different newline handling, and a cross-plane byte comparison
caught a latent CRLF frontmatter bug. See "The CRLF byte-parity hazard" in
`docs/learned/workflow/prompt-templates.md` for the read-boundary normalization rule.

## Cross-references

- `shared/contracts.md` §8.38 — the canonical parity matrix
- `docs/learned/workflow/prompt-templates.md` — the CRLF byte-parity hazard
- `docs/learned/workflow/shared-contracts.md` — lockstep literals + cross-plane contract ripple
- `docs/learned/workflow/remote-runner.md` — the remote path this parity discipline covers
