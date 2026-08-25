---
title: plan-save surfaces — fidelity gap, handoff_extra carrier, asymmetric write paths
read_when: You are working on plan-save / objective-node linkage, debugging a dropped objective_id / consumed_learn, touching resolvePlanSource's chain, or prepending a copyable command callout to an artifact.
cluster: plan-lifecycle
---

# plan-save surfaces

perk has **two plan-save surfaces with different fidelity**, and the gap between them is the root of
a whole class of silently-dropped-link bugs. Understanding the gap — and the carrier that closes it —
is the durable knowledge.

## Distillation

- Two save surfaces differ in fidelity (the `plan_save` tool carries links; the approval path
  carries no model params) — ASSUME the model picks the lower-fidelity one and make canonical
  linkage flow through the plane that owns the lifecycle — "The fidelity gap".
- A prompt naming a tool the read-only gate hides sends the model off-track every time — sweep
  every consumer surface in lockstep — "The seed/gate contradiction trap".
- The cold door ferries links through the handoff blob: `handoff_extra` is the general carrier
  (explicit flags win; fill both or neither) — "The fix pattern: `handoff_extra` as a general
  cold-door carrier".
- The plan to save resolves artifact → param → transcript → null; the param path's message stays
  byte-identical by design — "The plan-source resolution chain".
- The canonical save is FAIL-LOUD (it's what implement/resume rebuild from); on-land consume and
  reconcile are fail-open — "Fail-loud at the canonical save; fail-open downstream".

## The fidelity gap: assume the model picks the lower-fidelity surface

- The **`plan_save` tool** (TS, warm) passes `objective_id` / `node_id` explicitly.
- The **approval path** (`approvalSave`, and its `/plan-save` manual-failsafe command, which takes
  only an optional title) carries **no model params at all** — no plan, no link.

**The historical incident (pre-carrier behavior):** in a read-only plan-mode session (e.g.
`objective-plan`), the `plan_save` *tool* is gated out by the read-only tool gate (`toolGating.ts`
`READ_ONLY_TOOLS`), and the model fell back to the then-`{plan, title}`-only `/plan-save` command,
which dropped the link. Result: `objective_id: null` in the plan-ref, the node stranded in
`planning`, the downstream `/land` reconcile short-circuiting `no_objective_link`.

**Lesson (durable):** when two surfaces can perform the "same" action, assume the model will pick
the lower-fidelity one. Don't rely on the model passing tool params correctly — make the canonical
linkage flow through a **plane that owns the lifecycle**.

**The current shape:** the `/plan-save` command takes only a title and invokes `approvalSave`
(file-first resolution + warm claim recovery inside `savePlan`), so the "lower-fidelity surface"
today is the approval path itself — and the two recovery carriers below (the cold `handoff_extra`
blob, the warm `objective_node_claim` entry) close it. The dropped-link outcome is a *historical
incident*, not the live failure mode. See contracts §8.23 for the consolidated file-first
contract.

## The seed/gate contradiction trap (a prompt naming a tool the gate hides)

**The gate is structural; prompts are advisory.** A factory prompt that names a tool the
read-only gate hides (e.g. "persist with `plan_save`" in a session where `plan_save` is excluded
from `READ_ONLY_TOOLS`) sends the model off-track every time — the injected read-only context
enumerates the allowlist, so the model sees the contradiction plainly.

Root cause pattern: prompt-vs-reality drift when a flow converts to review-first (or a tool
becomes stage/gate-scoped). Sweep **every** consumer surface in lockstep: the seed template, the
bound SKILL.md, the extension door comments, and the contract note.

**Speak the carrier semantics in the prompt.** The handoff-recovery machinery makes the save
surface-independent, but a prompt that only names the explicit `plan_save` param convinces the
model that is the only path. Correct wording branches on reality: `plan_save` + explicit
`consumed_learn` where the tool is active (warm read-write sessions — load-bearing there, since
the warm gather writes no handoff), else `plan_review` with handoff recovery and `/plan-save` as
the human failsafe.

Resolved: the replan seed (`prompts/stages/replan.md`) now directs the approval-driven
`plan_review` auto-save — an APPROVED review updates plan #N in place (the save is keyed on the
run id; the objective link is preserved) — closing the last known instance of this trap.

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
transition by the `objective_node` tool (`extension/factories/objectivePlan.ts`; the claim decode +
equality helpers live in `extension/substrate/workflowState.ts`, typed over the structural
`BranchSource` slice so the session seam and the save feature import them with no module cycle),
cleared on a non-planning transition for the same node or after a successful node-linked save
matching the FULL claim identity (objective + node) keyed off the cold door's *reported* node. Both planes implement **identical semantics**:
explicit values win outright (even one — never mixed), fill both-or-neither, fail-open (a malformed
carrier never blocks a save).

**When a new factory-threaded save param appears, mirror this pattern on both planes** rather than
inventing a query.

Residual: an abandoned planning claim lingers until a matching transition/save for that node —
bounded (session-tier, and recovery is fill-only when BOTH params are absent), but real.

### Fragile seam: handoff write/read locations must agree

The recovery works **only because the write and read anchor to the same checkout** — the launch
writes the handoff into the resolved session cwd (`_write_session_handoff` →
`write_handoff(resolved.path, …)`), and plan-save reads it from its invocation root
(`read_handoff(repo_root, …)`), which IS that cwd when the save runs inside the session. If a
future consumer read from a different root than the launch wrote to, recovery would silently
miss. **Tie any new `handoff_extra` consumer to the checkout the launch actually wrote.**

> **Update (stacked objective-plan positioning shipped).** The original phrasing here — "works
> only because `objective-plan` is a `worktree: none` stage running at repo root" — is now too
> narrow: a stacked child-layer planning session is positioned in the **predecessor's plan
> worktree** (contracts §8.46), and recovery still works because the handoff was written into
> that same worktree (the invariant is write-root == read-root, not repo-root-ness). The cold
> claim additionally persists `objective_node_claim` from the handoff's `objective_id`/`node_id`
> (contracts §8.3), so cold factory sessions get the implement-here suppression too.

## The plan-source resolution chain

`resolvePlanSource` in `extension/authoring/plan/source.ts` resolves the plan to save as: validated plan-draft
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

## The copyable command callout — server-assigned-id timing dictates the per-backend write strategy

Prepending a visible, copyable Markdown command callout (`perk impl <id>` / `perk objective plan
<id>`) to the human-visible surface of a plan/objective artifact is a write-strategy problem, not a
formatting one. The lesson: **when the id you want to embed is server-assigned, *when* the backend
hands it back dictates the write shape — four distinct shapes:**

- **GitHub standalone plan** — id known only **post-create** → a separate read+PATCH
  (`prepend_plan_callout`) on the fresh-create path (**one extra write**).
- **GitHub / Linear issue-backed objective** — `created.number` / `created.id` known **before** the
  body comment is posted → **fold the callout into the compose step** at compose time (**zero extra
  writes**).
- **Linear project-backed objective** — project UUID known only **after** create → **one post-create
  content update** (mirrors the existing post-create pattern).
- **Linear node↔plan-unified plan** — fold into the description the unified save already writes
  (**zero extra writes**), where an **idempotency guard matters** because that method **re-runs on
  every objective-linked save**.

**"Prepend above all metadata/marker blocks" is durable by construction.** Because every metadata
finder/replacer and every objective splice operates strictly *between* delimiters and preserves the
surrounding text, a callout prepended to the very top survives header rewrites, reconciles, and
table re-renders untouched (verified by a header-survival unit test: prepend → `extract_run_id`
still parses → simulated `update_plan_header` → callout still leads).

**Pure portable Markdown needs no transcoding.** A callout that is bold + fenced code + italic (no
HTML comments / `<details>` / perk sentinels) passes the Linear transcoder **byte-unchanged** and
renders a one-click copy button on both GitHub and Linear — so prepending before-or-after the
transcode is byte-equivalent for sentinel-free content.

**Accepted idempotency-prefix-collision risk.** The idempotency key is a literal `command in body`
substring match, so a shorter id is a substring of a longer one (`perk impl 1` ⊂ `perk impl 10`;
`ENG-1` ⊂ `ENG-10`) — a body already referencing the longer id would skip the shorter id's callout.
Matching the **fenced** form would make it precise; low real risk, deferred.

**Fixture-sweep refinement (the real friction).** Inserting a **new network call into an existing
create/mutation sequence** breaks every scripted-fake test whose response map didn't anticipate it —
**including error-path tests that proceed *past* the insertion point** (e.g. an unknown-dependency
error raised at a *later* relation step still trips the newly-inserted call). Census ALL tests
exercising that path — **happy AND error** — and add the response to each map. (A refinement of the
fixture-sweep rules in `linear-backend.md` / `cold-door-client.md` — cross-ref, don't duplicate.)

Mechanical aside: adding the gateway function's name to `src/perk/github/__init__.py` must place it in
isort-alphabetical position in BOTH the import list and `__all__`, or ruff's `RUF022` fails CI — see
`docs/learned/toolchain/ruff.md`.

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

- `shared/contracts.md` §8.23 — the consolidated file-first plan contract (the three backends)
- `extension/authoring/plan/source.ts` — `resolvePlanSource`; `extension/authoring/plan/save.ts` —
  `savePlan`/`planApprovalSave`; `extension/pi/v1/plan.ts` — the `approvalSave` seam + the save rendering
- `extension/factories/objectivePlan.ts` — the `objective_node_claim` writer + claim helpers
- `docs/learned/workflow/plan-review-flow.md` — the review-side tiering + the approvalSave seam
- `docs/learned/pi/tool-param-decode.md` — the fallback-chain optionality flip
- `src/perk/cli/commands/plan/save_cmd.py` — `_link_from_handoff`, the re-save merge via `update_plan_header`
- `src/perk/run/launch/__init__.py` — `launch_stage` `handoff_extra` param
- `tests/test_plan_save.py` — recover/override/unlinked + the empty-dict skip assertion
- `docs/learned/workflow/plan-ref-lifecycle.md` — the plan-ref/header schema and fail-open on-land shape
- `docs/learned/workflow/objective-lifecycle.md` — node linkage + the objective re-save gap
- `docs/learned/workflow/linear-backend.md` — the Linear transcoder + scripted-GraphQL fixture-sweep rules
- `docs/learned/workflow/issue-backend.md` — the IssueBackend protocol-method ripple (the callout gateway adds one method)
- `docs/learned/toolchain/ruff.md` — the `RUF022` `__all__`-sort gotcha from the same change
