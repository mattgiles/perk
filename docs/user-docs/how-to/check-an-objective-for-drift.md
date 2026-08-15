---
title: "How to check an objective for drift"
description: "Compare an objective's live roadmap state against its persisted manifest and report — or repair — the divergence."
sidebar:
  order: 2180
sidebarGroup: "Objectives & learnings"
---

# How to check an objective for drift

A Linear-Project objective's roadmap is **observed** state — node-issues, blocking relations, and
phase milestones that anyone with Linear access can edit out from under perk. `perk objective
doctor` compares that live state against the objective's persisted **manifest** (the authoritative
record of what *should* exist) and reports — or, with `--fix`, repairs — the divergence. The same
run also diagnoses the objective's **delivery train** (stacked objectives, every backend): the
exact `stack status` findings, each annotated with a severity, whether doctor can repair it, and
the remediation when it cannot.

> **The manifest part is Linear only.** GitHub objectives store their roadmap atomically with the
> issue body, so there is no manifest divergence to detect — but the **train** diagnosis runs on
> every backend (a GitHub stacked objective with a broken train reports its train findings).

## Steps

1. **Report the drift.** Run
   [`perk objective doctor N`](../reference/cli/objective.md#perk-objective-doctor-number-alias-doc)
   (alias `perk objective doc`). Each condition is printed with a severity
   (`ERROR`/`WARNING`/`INFO`), a stable code, and a message. Add `--json` for the machine-readable
   report (`drift`/`fix` for the manifest part, `train`/`train_fix` for the delivery train).
2. **Apply the safe repairs.** Run `perk objective doctor N --fix`. perk converges only the
   **safe, unambiguous** cases:
   - a **missing manifest** is backfilled from the current node-issues;
   - a **missing node-issue** is recreated from its manifest entry (under its phase milestone, with
     its blocking relations);
   - a **deleted phase milestone** is recreated and its node-issues reattached;
   - a **missing blocking relation** (an edge the manifest declares but Linear lost) is re-added.

   Repairs apply in a deterministic order and **stop at the first failed write** (fail-loud) — the
   report shows what was `applied`, what `failed`, and what `remaining` drift is still present.
   Re-running is safe (idempotent).
3. **Read the train section.** On a stacked objective the report's second part lists the
   delivery-train findings with their remediations. One special case is a **native cancellation**:
   a roadmap node a human canceled directly in Linear projects as skipped — but only when perk can
   positively **prove** it is unpublished future work: a clean, coherent plan backlink is
   acceptable (and so is abandoned-only publication history — recovery writes it only after an
   all-before proof), but any identity conflict, checkpoint or PR claim, completed or unresolved
   publication, remote branch, or branch-owned PR in any state is not. A proven one shows as a repairable
   `canceled_unpublished_projected` warning; anything unprovable stays a visible `canceled` layer
   with blockers naming the exact conflicting evidence — fail-closed, projection-only (nothing is
   persisted by the read).
4. **Apply the train repair.** `--fix` also persists each **safely projected** cancellation into
   the node attachment (pending/planning/… → skipped) — with a fresh proof immediately before
   each conditional write, a post-write verification, and a compensating rollback + loud abort if
   the world moved (e.g. the node was re-opened in Linear mid-repair). A raced candidate is
   skipped, never forced.
5. **Preview without writing.** Add `--dry-run` to `--fix` to see both would-apply repair sets
   without touching Linear.

## The both-headers corruption signature

Every doctor run also checks the objective's **issue-tier carrier** — on GitHub the objective
issue itself, on a Linear-Project objective the metadata **sentinel** issue — for the
**kind-corruption signature**: a carrier bearing BOTH `objective-header` and `plan-header`
metadata. That state means one header was stamped onto the wrong kind of carrier (historically:
a plan door run with an objective's id, or a wrong-kind adoption — both directions are now
refused at entry and at the writers, so a detected signature is pre-existing damage).

- **Direction-neutral.** The signature cannot prove which header is the stray one from the
  carrier alone. Inspect provenance — the issue's edit history and each header's `run_id` — to
  identify the stray side.
- **Report-only, explicitly no auto-repair.** `--fix` never touches it (there is no repair code
  path): removing a header is a destructive judgment call perk has no authority to make. Remove
  the stray header by hand — or, when the objective side is the live one, retire the carrier by
  superseding it (`perk objective replan N`); the supersession redirects doctor away from the
  retired carrier, so it stops alarming.
- **A clean report.** A detected finding rides the `corruption` field (and a `Corruption:`
  section in the human report, printed only when detected) but keeps exit `0`.

> **What perk will *not* auto-fix.** Report-only conditions are surfaced but never changed, because
> repairing them would require perk to *invent* a decision it has no authority to make: duplicate
> node ids, a blocking-relation **cycle**, a relation Linear has that the manifest does not (an
> intentional human edit, or stale?), a **renamed** milestone, an unknown external blocker, or a
> damaged overview marker — and on the train side, plan identity, checkpoints, journal history,
> branches, PRs, and native stack membership (each finding names its explicit remediation:
> conclude the operation via `stack recover`/`/submit`, repair GitHub then rerun status, or
> restore the edited authority and only then consider a replan). Resolve these by hand (or by
> re-running the relevant `perk objective` command), then re-run `doctor` to confirm.

> **The manifest stays current automatically.** Creating an objective, adding a node, editing a
> node's description, and reconciling all keep the manifest in sync — so on a normally-driven
> objective `doctor` reports nothing. Drift appears only when the Linear Project is edited outside
> perk.

## Related

- **Do:** [How to recover a stacked delivery train](recover-a-stacked-train.md) — conclude the train
  operations doctor reports but cannot repair.
- **Do:** [How to diagnose a perk repo](diagnose-a-perk-repo.md) — the repository-health sibling of
  this objective-scoped doctor.
- **Look up:** [Objective commands](../reference/cli/objective.md) — exact `perk objective doctor` syntax and flags.
