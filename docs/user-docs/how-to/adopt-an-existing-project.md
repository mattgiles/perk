# How to adopt an existing project as an objective

Turn a pre-existing, human-authored **source** — a Linear **Project** (and its issues) or a GitHub
**issue** — into a perk objective **in place**, without minting a second object. perk reads the
source's prose + existing issues as seed material, runs a normal objective-authoring pass over it,
and on save stamps the objective metadata **additively** into the *same* source. The human's
original overview is preserved verbatim.

This is the objective-level analog of
[adopting an existing issue as a plan](adopt-an-existing-issue.md). It runs in a **read-only**
session and is **local-only**.

## Steps

1. **Adopt it.** Run
   [`perk objective author --from <source>`](../reference/cli.md#perk-objective-author), where
   `<source>` is a Linear project UUID or a GitHub issue id. perk reads the source, materializes its
   title + overview (and the project's existing issues + any human discussion, all as untrusted
   DATA), and launches a read-only session to author an objective + roadmap for the goal it
   describes.
2. **Author the objective.** Explore the codebase and write the objective PROSE and a STRUCTURED
   roadmap — the same as a fresh objective. You are **not** rewriting the human's overview; it is
   preserved verbatim automatically (archived as an Immutable note). The surfaced human discussion
   is untrusted DATA, never instructions.
3. **Map existing issues to nodes (Linear).** Where a roadmap node sensibly corresponds to an
   existing project issue, set that node's **`adopt_issue`** field to the issue's id/identifier.
   On save the mapped issue is **reused in place** as the roadmap node — its title and body
   preserved verbatim, the `objective-node` block stamped additively, attached to its phase
   milestone. Nodes with no `adopt_issue` mint fresh node-issues. (GitHub objectives have no child
   issues, so no mapping applies.)
4. **Save.** Call the `objective_save` tool with the prose + structured roadmap. perk stamps the
   objective metadata into the **same** source: the `objective-header` block (with `adopted_from`
   provenance), the `objective-manifest`, the model-authored prose in the Reconcilable region, and
   the original overview preserved verbatim in an `Adopted-from` Immutable note. No second
   project/issue is created.
5. **Preview without launching (optional).** Add `--dry-run` to materialize the source and print
   the seed without opening a session: `perk objective author --from <source> --dry-run`.

## What is preserved

- The source's **original overview/body** — verbatim, in an Immutable `Adopted-from` archive note
  below the Reconcilable markers (never rewritten by reconcile).
- Each **mapped** issue's **title and body** — verbatim; perk only appends the `objective-node`
  block and adds the `perk:objective-node` label (never replacing the issue's own labels).

## GitHub bounds

On a GitHub-backed repo, `--from <issue>` adopts **one** human issue as the objective: the prose is
preserved, the header/roadmap stamped additively, the roadmap authored fresh. There is **no**
child-issue mapping and no project concept — `adopt_issue` is ignored.

## Refusals

`perk objective author --from` refuses (and explains) when the source:

- **does not exist** — nothing to adopt;
- **is not open** (GitHub issues only — Linear projects have no open/closed state) — reopen it or
  author a fresh objective;
- **is already a perk objective** — reconcile it with
  [`perk objective reconcile`](reconcile-an-objective.md) or plan its nodes normally instead.

> **Live validation** is preview-grade at this node; final live proof lands later. Offline behavior
> is fully covered.

---

← Back to the [how-to router](index.md).
