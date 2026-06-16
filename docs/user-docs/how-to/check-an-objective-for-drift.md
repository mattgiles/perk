# How to check an objective for drift

A Linear-Project objective's roadmap is **observed** state — node-issues, blocking relations, and
phase milestones that anyone with Linear access can edit out from under perk. `perk objective
doctor` compares that live state against the objective's persisted **manifest** (the authoritative
record of what *should* exist) and reports — or, with `--fix`, repairs — the divergence.

> **Linear only.** GitHub objectives store their roadmap atomically with the issue body, so there is
> no divergence to detect — `doctor` always reports a clean objective there.

## Steps

1. **Report the drift.** Run
   [`perk objective doctor N`](../reference/cli.md#perk-objective-doctor-number-alias-doc)
   (alias `perk objective doc`). Each condition is printed with a severity
   (`ERROR`/`WARNING`/`INFO`), a stable code, and a message. Add `--json` for the machine-readable
   report (`{drift: [...], fix: null}`).
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
3. **Preview without writing.** Add `--dry-run` to `--fix` to see the would-apply repair set without
   touching Linear.

> **What perk will *not* auto-fix.** Report-only conditions are surfaced but never changed, because
> repairing them would require perk to *invent* a decision it has no authority to make: duplicate
> node ids, a blocking-relation **cycle**, a relation Linear has that the manifest does not (an
> intentional human edit, or stale?), a **renamed** milestone, an unknown external blocker, or a
> damaged overview marker. Resolve these by hand (or by re-running the relevant `perk objective`
> command), then re-run `doctor` to confirm.

> **The manifest stays current automatically.** Creating an objective, adding a node, editing a
> node's description, and reconciling all keep the manifest in sync — so on a normally-driven
> objective `doctor` reports nothing. Drift appears only when the Linear Project is edited outside
> perk.

---

← Back to the [how-to router](index.md).
