---
title: plan-save surfaces — fidelity gap, handoff_extra carrier, asymmetric write paths
read_when: You are working on plan-save / objective-node linkage, debugging a dropped objective_id / consumed_learn, adding context that must survive a model's choice of save surface, touching resolvePlanSource's artifact→param→transcript chain, or extending the warm objective_node_claim recovery carrier.
---

# plan-save surfaces

perk has **two plan-save surfaces with different fidelity**, and the gap between them is the root of
a whole class of silently-dropped-link bugs. Understanding the gap — and the carrier that closes it —
is the durable knowledge.

## The fidelity gap: assume the model picks the lower-fidelity surface

- The **`plan_save` tool** (TS, warm) passes `objective_id` / `node_id` explicitly.
- The **`/plan-save` command** (TS) forwards only `{plan, title}` to `perk plan-save` — it **cannot
  carry the link**.

In a read-only plan-mode session (e.g. `objective-plan`), the `plan_save` *tool* is gated out by the
read-only tool gate (`toolGating.ts` `READ_ONLY_TOOLS`), so the model falls back to the *command*,
which drops the link. Result: `objective_id: null` in the plan-ref, the node stranded in `planning`,
the downstream `/land` reconcile short-circuiting `no_objective_link`.

**Lesson:** when two surfaces can perform the "same" action, assume the model will pick the
lower-fidelity one. Don't rely on the model passing tool params correctly — make the canonical
linkage flow through a **plane that owns the lifecycle**.

## The fix pattern: `handoff_extra` as a general cold-door carrier

The cold door (which *does* own the lifecycle) ferries the link through the handoff blob:

- `launch.launch_stage` gained `handoff_extra: dict[str, object] | None`, merged into the handoff
  (`{"stage", "mode", **handoff_extra}`).
- `objective-plan` stashes `{objective_id, node_id}` (the node it just marked `planning`).
- `perk plan-save` recovers them via `_link_from_handoff(...)` when **neither** flag was passed
  (explicit flags always win; it fills **both or neither**, never silently mixing a half-specified
  link with the handoff; it catches `(OSError, ValueError)` so a malformed handoff never blocks a
  save — best-effort, fail-open).

The TS `Handoff` interface already has `[key: string]: unknown`, so **arbitrary keys ride along with
zero TS change** — a reusable seam for any CLI→session context that must survive a model's surface
choice.

### The two-plane recovery-carrier pattern is now complete

The handoff carrier covers **cold** sessions; warm sessions got the matching half: the
`objective_node_claim` carrier in `perk:workflow-state`, written on a successful `planning`
transition by the `objective_node` tool (`extension/objectivePlan.ts` — the claim helpers live
there, typed over the structural `BranchSource` slice so `planSave.ts` imports them with no module
cycle), cleared on a non-planning transition for the same node or after a successful node-linked
save keyed off the cold door's *reported* node. Both planes implement **identical semantics**:
explicit values win outright (even one — never mixed), fill both-or-neither, fail-open (a malformed
carrier never blocks a save).

**When a new factory-threaded save param appears, mirror this pattern on both planes** rather than
inventing a query.

Residual: an abandoned planning claim lingers until a matching transition/save for that node —
bounded (session-tier, and recovery is fill-only when BOTH params are absent), but real.

### Fragile seam: handoff write/read locations must agree

The recovery works **only because `objective-plan` is a `worktree: none` stage** — its session runs
at repo root, so the handoff write (`write_handoff(repo_root, …)`) and the plan-save read
(`read_handoff(repo_root, …)`) agree on location. If a future stage that ferries link context ran in
a worktree, the locations would diverge and recovery would silently miss. **Tie any new
`handoff_extra` consumer to the stage's `worktree` mode.**

## The plan-source resolution chain

`resolvePlanSource` in `extension/planSave.ts` resolves the plan to save as: validated plan-draft
artifact → `plan` param → transcript scrape → null. The artifact tier needs `run_id`; the param
tier doesn't. Success messages annotate **only the NEW sources** (` · plan source: plan-draft
artifact`/`transcript`) — the param path stays byte-identical by design, so existing tests and
downstream regexes don't churn; machine consumers read `details.plan_source` instead of parsing the
suffix. **Gotcha for surface work:** the param-path source suffix is *intentionally absent* — a
test expecting `plan source: param` in the message is wrong by design (assert
`details.plan_source === "param"` instead).

Review surfaces use a deliberately shorter chain (artifact → param ONLY, never the transcript) —
see `plan-review-flow.md` for the asymmetric-tiering law.

### Surfacing an ignored input beats both silence and hard-fail

When the artifact and a differing `plan` param conflict, the artifact wins but the save message
visibly flags the ignored differing param — never silent (model confusion would be invisible),
never fatal (the validated artifact is by construction the better bytes). The mismatch compares
`.trim()`-ed bytes so trailing-whitespace deltas don't false-positive.

### The stale-draft hazard (known, open)

If the model revises the plan in its final message **without re-calling `plan_draft`**, the older
artifact beats the fresher transcript; `/plan-save` has no param to compare against, so it saves
the stale draft with no mismatch flag. Keep-the-draft-current (the `plan_draft` guideline) is the
mitigation.

### Optional-param fallback decode flip

Making `plan` optional required flipping the absent case from `""`-coercion to `undefined` so an
absent param falls through to the next source — the resolver's null arm now owns "nothing
anywhere". Present-but-mistyped → `null` strict-fail is unchanged. See `pi/tool-param-decode.md`
for the general fallback-chain optionality pattern.

## Asymmetric write paths — the re-save bug class

`perk plan-save` composes the full `plan-header` block on **every** save, but only the **fresh-create**
path actually wrote it (via `create_plan_issue(body=…)`). The idempotent **re-save** path PATCHed
*only* the `plan-body` comment + the issue title — never the issue body / `plan-header`. So any
re-save (e.g. an initial link-less save, then a revised save that adds the link) silently kept the
*first-create* header; the composed body was discarded.

**General watch:** whenever one code path composes a full payload but a sibling "update" path
persists only a subset, suspect a silent drop. The fix reuses the existing `update_plan_header` merge
gateway **additively** — build a dict of only the *provided* fields, merge
(`{**header, **fields}` → replace block → PATCH), skip the write entirely when the dict is empty (no
needless PATCH on a plain revise). Additive matters: omitting a field leaves the existing value
intact, so it never clobbers a previously-linked objective/learn set nor resets the
submit-populated `branch`/`pr`/`lifecycle_stage`.

## Fail-loud at the canonical save; fail-open downstream

The canonical-save write is **fail-loud** (raises `GitHubError` → exit `github_error`) — it is the
single source `perk implement <N>` / `resume` rebuild from, so a silent drop there is precisely the
bug. Contrast the on-land consume / objective-reconcile, which are **fail-open** (the merge already
succeeded). Why the canonical header matters: a multi-hop field like `consumed_learn` travels
plan-save header → `reconstruct_plan_ref` (which reads the **GitHub header**, not the local cache) →
worktree plan-ref → on-land consume. **A multi-hop field is only as good as its canonical
persistence point — verify the read source, not just that *some* write happened.** Because the
on-land step is fail-open and only prints on success, a stale header broke the whole chain silently.

> **Re-save asymmetry note (objectives):** `objective_save` is NOT yet a symmetric upsert —
> `create_objective_issue` is idempotent on `run_id` but on a hit **returns the existing issue
> without updating it**, so re-running `objective_save` after editing prose/roadmap won't push the
> edits. A genuine gap if in-session objective re-editing becomes a need. See
> `objective-lifecycle.md`.

## Cross-references

- `extension/planSave.ts` — `resolvePlanSource`, `savePlan`, the `approvalSave` seam
- `extension/objectivePlan.ts` — the `objective_node_claim` writer + claim helpers
- `docs/learned/workflow/plan-review-flow.md` — the review-side tiering + the approvalSave seam
- `docs/learned/pi/tool-param-decode.md` — the fallback-chain optionality flip
- `perk/cli/commands/plan_save_cmd.py` — `_link_from_handoff`, the re-save merge via `update_plan_header`
- `perk/launch.py` — `launch_stage` `handoff_extra` param
- `tests/test_plan_save.py` — recover/override/unlinked + the empty-dict skip assertion
- `docs/learned/workflow/plan-ref-lifecycle.md` — the plan-ref/header schema and fail-open on-land shape
- `docs/learned/workflow/objective-lifecycle.md` — node linkage + the objective re-save gap
